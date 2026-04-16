#!/usr/bin/env python3
"""
Polymarket Phone Executor

Reads all pending orders from pending_orders.json in the GitHub repo, executes
each one sequentially (sign EIP-712, POST to CLOB), and tracks executed order IDs
locally to avoid duplicates.

Dependencies: requests, python-dotenv, eth-keys, poly-eip712-structs (no Rust)
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import random
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from eth_keys import keys as eth_keys
from poly_eip712_structs import Address, EIP712Struct, Uint, make_domain
from eth_utils import keccak

from log_client import refresh_log_client_config, send_server_log

ENV_FILE = Path.home() / '.polymarket.env'
EXECUTED_ORDERS_FILE = Path.home() / '.polymarket_executed_order_ids'
CLOB_HOST = 'https://clob.polymarket.com'
ORDER_PATH = '/order'
DATA_API_HOST = 'https://data-api.polymarket.com'
RECENT_ACTIVITY_LIMIT = 20
RECENT_TRADE_WINDOW_SECONDS = 6 * 60 * 60
PENDING_ORDERS_API_URL = (
    'https://api.github.com/repos/jmtdev0/beecthor-summary/contents'
    '/polymarket_assistant/pending_orders.json'
)

# Polymarket CTF Exchange on Polygon
EXCHANGE_ADDRESS = '0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E'
CHAIN_ID = 137
FEE_RATE_BPS = 1000
SIGNATURE_TYPE = 1  # POLY_PROXY

load_dotenv(ENV_FILE)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
POLY_API_SECRET = os.environ.get('POLY_API_SECRET', '')
POLY_API_PASSPHRASE = os.environ.get('POLY_API_PASSPHRASE', '')
POLY_FUNDER = os.environ.get('POLY_FUNDER', '')
POLY_SIGNER_ADDRESS = os.environ.get('POLY_SIGNER_ADDRESS', '')
POLY_PRIVATE_KEY = os.environ.get('POLY_PRIVATE_KEY', '')


def refresh_runtime_config() -> None:
    global TELEGRAM_BOT_TOKEN
    global TELEGRAM_CHAT_ID
    global POLY_API_KEY
    global POLY_API_SECRET
    global POLY_API_PASSPHRASE
    global POLY_FUNDER
    global POLY_SIGNER_ADDRESS
    global POLY_PRIVATE_KEY

    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
    POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
    POLY_API_SECRET = os.environ.get('POLY_API_SECRET', '')
    POLY_API_PASSPHRASE = os.environ.get('POLY_API_PASSPHRASE', '')
    POLY_FUNDER = os.environ.get('POLY_FUNDER', '')
    POLY_SIGNER_ADDRESS = os.environ.get('POLY_SIGNER_ADDRESS', '')
    POLY_PRIVATE_KEY = os.environ.get('POLY_PRIVATE_KEY', '')
    refresh_log_client_config()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Phone executor for Polymarket orders.')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Build and print the live order payloads without posting them.',
    )
    parser.add_argument(
        '--env-file',
        default=str(ENV_FILE),
        help='Path to the .env file to load before executing.',
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# EIP-712 order struct (mirrors py_order_utils Order)
# ---------------------------------------------------------------------------

class Order(EIP712Struct):
    salt = Uint(256)
    maker = Address()
    signer = Address()
    taker = Address()
    tokenId = Uint(256)
    makerAmount = Uint(256)
    takerAmount = Uint(256)
    expiration = Uint(256)
    nonce = Uint(256)
    feeRateBps = Uint(256)
    side = Uint(8)
    signatureType = Uint(8)


DOMAIN = make_domain(
    name='Polymarket CTF Exchange',
    version='1',
    chainId=str(CHAIN_ID),
    verifyingContract=EXCHANGE_ADDRESS,
)


class MarketResolvedException(Exception):
    """Raised when the order book returns 404 because the market already resolved."""


def sign_order(order: Order) -> str:
    """Sign EIP-712 order struct with the private key."""
    struct_hash = keccak(order.signable_bytes(domain=DOMAIN))
    pk = eth_keys.PrivateKey(bytes.fromhex(POLY_PRIVATE_KEY.lstrip('0x')))
    sig = pk.sign_msg_hash(struct_hash)
    # eth_keys produces v ∈ {0, 1}; Ethereum expects v ∈ {27, 28}
    sig_bytes = bytearray(sig.to_bytes())
    sig_bytes[64] += 27
    return '0x' + bytes(sig_bytes).hex()


def get_market_price(token_id: str, side: str, amount: float) -> float:
    """Query the live order book and compute the market price for the given amount."""
    resp = requests.get(
        f'{CLOB_HOST}/book',
        params={'token_id': token_id},
        timeout=15,
    )
    if resp.status_code == 404:
        raise MarketResolvedException(
            f'Order book not found (404) — market likely resolved; token_id={token_id}'
        )
    resp.raise_for_status()
    book = resp.json()

    if side == 'BUY':
        levels = book.get('asks', [])
        levels = sorted(levels, key=lambda x: float(x['price']))
    else:
        levels = book.get('bids', [])
        levels = sorted(levels, key=lambda x: float(x['price']), reverse=True)

    total = 0.0
    for level in levels:
        price = float(level['price'])
        size = float(level['size'])
        if side == 'BUY':
            total += size * price
        else:
            total += size
        if total >= amount:
            return price

    if levels:
        return float(levels[-1]['price'])
    raise RuntimeError('Empty order book')


def round_down(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(value * factor) / factor


def to_usdc(value: float) -> int:
    """Convert float USDC to 6-decimal integer (Polymarket uses 1e6)."""
    return int(round(value * 1_000_000))


def build_order_dict(token_id: str, side: str, amount: float, price: float) -> dict:
    """Build and sign an EIP-712 order, return the dict ready for the CLOB API."""
    salt = random.randint(1, 2**32)
    side_int = 0 if side == 'BUY' else 1

    if side == 'BUY':
        maker_amount = to_usdc(round_down(amount, 2))
        taker_amount = to_usdc(round_down(amount / price, 4))
    else:
        maker_amount = to_usdc(round_down(amount, 2))
        taker_amount = to_usdc(round_down(amount * price, 4))

    order = Order(
        salt=salt,
        maker=POLY_FUNDER,
        signer=POLY_SIGNER_ADDRESS,
        taker='0x0000000000000000000000000000000000000000',
        tokenId=int(token_id),
        makerAmount=maker_amount,
        takerAmount=taker_amount,
        expiration=0,
        nonce=0,
        feeRateBps=FEE_RATE_BPS,
        side=side_int,
        signatureType=SIGNATURE_TYPE,
    )
    signature = sign_order(order)

    return {
        'salt': salt,
        'maker': POLY_FUNDER,
        'signer': POLY_SIGNER_ADDRESS,
        'taker': '0x0000000000000000000000000000000000000000',
        'tokenId': str(token_id),
        'makerAmount': str(maker_amount),
        'takerAmount': str(taker_amount),
        'expiration': '0',
        'nonce': '0',
        'feeRateBps': str(FEE_RATE_BPS),
        'side': side,
        'signatureType': SIGNATURE_TYPE,
        'signature': signature,
    }


def build_l2_headers(method: str, path: str, body_str: str) -> dict:
    timestamp = str(int(time.time()))
    message = timestamp + method + path + body_str
    sig = base64.urlsafe_b64encode(
        hmac.new(
            base64.urlsafe_b64decode(POLY_API_SECRET),
            message.encode('utf-8'),
            hashlib.sha256,
        ).digest()
    ).decode('utf-8')
    return {
        'POLY_ADDRESS': POLY_SIGNER_ADDRESS,
        'POLY_SIGNATURE': sig,
        'POLY_TIMESTAMP': timestamp,
        'POLY_API_KEY': POLY_API_KEY,
        'POLY_PASSPHRASE': POLY_API_PASSPHRASE,
        'Content-Type': 'application/json',
    }


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': text},
            timeout=15,
        )
    except Exception:
        pass


def fetch_live_positions() -> list[dict]:
    user = POLY_FUNDER or POLY_SIGNER_ADDRESS
    if not user:
        return []
    resp = requests.get(
        f'{DATA_API_HOST}/positions',
        params={'user': user, 'sizeThreshold': 0.01, 'limit': 100, 'offset': 0},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_recent_activity(limit: int = RECENT_ACTIVITY_LIMIT) -> list[dict]:
    user = POLY_FUNDER or POLY_SIGNER_ADDRESS
    if not user:
        return []
    resp = requests.get(
        f'{DATA_API_HOST}/activity',
        params={'user': user, 'limit': limit, 'offset': 0},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def find_recent_matching_trade(pending: dict) -> dict | None:
    side = pending.get('side', '')
    market_slug = pending.get('market') or pending.get('market_slug', '')
    outcome = pending.get('outcome', '')
    token_id = str(pending.get('token_id', ''))
    now_ts = int(time.time())

    for item in fetch_recent_activity():
        if item.get('type') != 'TRADE':
            continue
        if item.get('side') != side:
            continue
        if item.get('slug') != market_slug:
            continue
        if item.get('outcome') != outcome:
            continue
        item_token = str(item.get('asset', ''))
        if token_id and item_token and item_token != token_id:
            continue
        item_ts = item.get('timestamp')
        try:
            item_ts = int(item_ts)
        except (TypeError, ValueError):
            continue
        if now_ts - item_ts <= RECENT_TRADE_WINDOW_SECONDS:
            return item
    return None


def resolve_live_position(pending: dict) -> dict | None:
    market_slug = pending.get('market') or pending.get('market_slug', '')
    outcome = pending.get('outcome', '')
    token_id = str(pending.get('token_id', ''))

    positions = fetch_live_positions()
    exact = [
        pos for pos in positions
        if pos.get('slug') == market_slug and pos.get('outcome') == outcome
    ]
    if exact:
        exact.sort(key=lambda pos: float(pos.get('size') or 0), reverse=True)
        return exact[0]

    hinted = [
        pos for pos in positions
        if str(pos.get('asset', '')) == token_id
    ]
    if hinted:
        hinted.sort(key=lambda pos: float(pos.get('size') or 0), reverse=True)
        return hinted[0]

    return None


def load_executed_order_ids() -> set:
    try:
        return set(EXECUTED_ORDERS_FILE.read_text().splitlines())
    except Exception:
        return set()


def save_executed_order_id(order_id: str) -> None:
    ids = load_executed_order_ids()
    ids.add(order_id)
    EXECUTED_ORDERS_FILE.write_text('\n'.join(sorted(ids)))


def post_order(order_dict: dict, order_type: str = 'FOK') -> requests.Response:
    body = {
        'order': order_dict,
        'owner': POLY_API_KEY,
        'orderType': order_type,
        'postOnly': False,
    }
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)
    headers = build_l2_headers('POST', ORDER_PATH, body_str)
    return requests.post(
        f'{CLOB_HOST}{ORDER_PATH}',
        headers=headers,
        data=body_str.encode('utf-8'),
        timeout=30,
    )


def execute_order(pending: dict, dry_run: bool = False) -> bool:
    """Execute a single pending order. Returns True on success."""
    order_id = pending.get('order_id', '')
    token_id = pending.get('token_id', '')
    side = pending.get('side', '')
    order_type = pending.get('type', 'OPEN_POSITION')
    market = pending.get('market') or pending.get('market_slug', '')
    outcome = pending.get('outcome', '')
    amount = float(pending.get('stake_usd') or pending.get('amount', 0))

    print(f'[executor] Order: {order_type} {side} {outcome} on "{market}" amount={amount}')
    send_server_log(
        'phone.executor',
        'order_received',
        f'{order_type} {side} {outcome} on {market}',
        payload={
            'order_id': order_id,
            'market': market,
            'market_slug': pending.get('market_slug'),
            'outcome': outcome,
            'amount': amount,
            'dry_run': dry_run,
        },
    )

    if side == 'BUY':
        recent_trade = find_recent_matching_trade(pending)
        if recent_trade:
            print('[executor] Recent matching BUY found in activity; marking order as already handled.')
            send_server_log(
                'phone.executor',
                'order_skipped',
                'Recent matching BUY found in activity; treating order as already executed',
                payload={'order_id': order_id, 'market_slug': pending.get('market_slug'), 'reason': 'recent_activity'},
            )
            save_executed_order_id(order_id)
            if not dry_run:
                send_telegram(
                    f'\u26a0\ufe0f OPEN_POSITION ya parece ejecutada:\n'
                    f'{market}\n'
                    f'{outcome}\n'
                    'He visto una compra reciente en la actividad de la cuenta. '
                    'Probablemente te adelantaste, impaciente.'
                )
            return True

        live_position = resolve_live_position(pending)
        if live_position:
            print('[executor] Matching live position already open; marking order as already handled.')
            send_server_log(
                'phone.executor',
                'order_skipped',
                'Matching live position already open; treating order as already executed',
                payload={'order_id': order_id, 'market_slug': pending.get('market_slug'), 'reason': 'live_position'},
            )
            save_executed_order_id(order_id)
            if not dry_run:
                send_telegram(
                    f'\u26a0\ufe0f OPEN_POSITION ya no aplica:\n'
                    f'{market}\n'
                    f'{outcome}\n'
                    'La posición ya aparece abierta en Polymarket. '
                    'Probablemente entraste tú antes, impaciente.'
                )
            return True

    max_attempts = 5
    retry_delay = 20
    resp = None
    last_error = ''

    for attempt in range(1, max_attempts + 1):
        print(f'[executor] Attempt {attempt}/{max_attempts} — querying order book...')
        try:
            price = get_market_price(token_id, side, amount)
            print(f'[executor] Market price: {price}')
            order_dict = build_order_dict(token_id, side, amount, price)
        except MarketResolvedException as exc:
            print(f'[executor] Skipping stale order because market is already resolved: {exc}')
            send_server_log(
                'phone.executor',
                'order_skipped',
                'Pending order skipped because market already resolved',
                payload={
                    'order_id': order_id,
                    'market_slug': pending.get('market_slug'),
                    'reason': 'market_resolved',
                    'token_id': token_id,
                },
            )
            save_executed_order_id(order_id)
            return True
        except Exception as exc:
            last_error = str(exc)
            print(f'[executor] Failed to build order: {exc}')
            if attempt < max_attempts:
                print(f'[executor] Retrying in {retry_delay}s...')
                time.sleep(retry_delay)
            continue

        body = {
            'order': order_dict,
            'owner': POLY_API_KEY,
            'orderType': 'FOK',
            'postOnly': False,
        }
        if dry_run:
            print('[executor] DRY RUN payload:')
            print(json.dumps(body, indent=2))
            send_server_log(
                'phone.executor',
                'order_dry_run',
                'Built order payload successfully',
                payload={'order_id': order_id, 'market_slug': pending.get('market_slug'), 'price': price},
            )
            return True

        resp = post_order(order_dict)
        if resp.ok:
            print(f'[executor] SUCCESS: {resp.text}')
            send_server_log(
                'phone.executor',
                'order_executed',
                'Order executed successfully on phone',
                payload={'order_id': order_id, 'market_slug': pending.get('market_slug'), 'response': resp.text[:500]},
            )
            save_executed_order_id(order_id)
            send_telegram(f'\u2705 Order executed from phone:\n{order_type} {outcome}\n{market} size={amount}')
            return True

        last_error = f'{resp.status_code}: {resp.text}'
        print(f'[executor] Attempt {attempt} FAILED {last_error}')
        if attempt < max_attempts:
            print(f'[executor] Retrying in {retry_delay}s...')
            time.sleep(retry_delay)

    send_telegram(f'\u274c Order failed after {max_attempts} attempts:\n{market} {outcome}\n{last_error}')
    send_server_log(
        'phone.executor',
        'order_failed',
        'Order failed after retries',
        level='error',
        payload={'order_id': order_id, 'market_slug': pending.get('market_slug'), 'error': last_error},
    )
    return False


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file, override=True)
    refresh_runtime_config()

    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[executor] {ts} dry_run={args.dry_run}')
    send_server_log('phone.executor', 'run_started', 'Executor run started', payload={'timestamp': ts, 'dry_run': args.dry_run})

    missing = [v for v in ('POLY_API_KEY', 'POLY_API_SECRET', 'POLY_API_PASSPHRASE',
                           'POLY_FUNDER', 'POLY_SIGNER_ADDRESS', 'POLY_PRIVATE_KEY')
               if not os.environ.get(v)]
    if missing:
        print(f'[executor] Missing env vars: {missing}. Check {ENV_FILE}')
        send_server_log('phone.executor', 'run_failed', 'Missing required environment variables', level='error', payload={'missing': missing})
        sys.exit(1)

    resp = requests.get(PENDING_ORDERS_API_URL, timeout=15, headers={'Cache-Control': 'no-cache'})
    if resp.status_code == 404:
        print('[executor] pending_orders.json not found in repo. Nothing to do.')
        send_server_log('phone.executor', 'run_skipped', 'pending_orders.json not found in repo')
        return
    resp.raise_for_status()
    queue = json.loads(base64.b64decode(resp.json()['content']))

    if not queue:
        print('[executor] No pending orders in queue.')
        send_server_log('phone.executor', 'run_skipped', 'No pending orders in queue')
        return

    executed_ids = load_executed_order_ids()
    pending = [o for o in queue if o.get('status') == 'pending_phone_execution' and o.get('order_id') not in executed_ids]

    if not pending:
        print(f'[executor] {len(queue)} order(s) in queue, all already executed.')
        send_server_log('phone.executor', 'run_skipped', 'All queued orders were already executed', payload={'queue_size': len(queue)})
        return

    print(f'[executor] {len(pending)} pending order(s) to execute.')
    send_server_log('phone.executor', 'run_active', 'Pending orders ready for execution', payload={'pending_count': len(pending), 'queue_size': len(queue)})
    for i, order in enumerate(pending, 1):
        print(f'[executor] --- Order {i}/{len(pending)} (id={order.get("order_id")}) ---')
        execute_order(order, dry_run=args.dry_run)
        if i < len(pending):
            time.sleep(3)  # small pause between orders


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[executor] Exception: {exc}')
        send_telegram(f'\u274c Exception in phone executor: {exc}')
        send_server_log('phone.executor', 'run_failed', f'Unhandled exception: {exc}', level='error')
