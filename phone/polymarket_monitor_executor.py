#!/usr/bin/env python3
"""
Polymarket Monitor Phone Executor

Runs 5 minutes after each monitor check (cron: every odd UTC hour + 5min).
Reads order params from last_monitor_action.json in the GitHub repo, queries
the live order book, builds and signs the EIP-712 SELL order with the private
key, and POSTs to the Polymarket CLOB API using the phone's residential IP.

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

ENV_FILE = Path.home() / '.polymarket.env'
LAST_EXECUTED_FILE = Path.home() / '.polymarket_last_monitor_ts'
CLOB_HOST = 'https://clob.polymarket.com'
ORDER_PATH = '/order'
DATA_API_HOST = 'https://data-api.polymarket.com'
RECENT_ACTIVITY_LIMIT = 20
RECENT_TRADE_WINDOW_SECONDS = 6 * 60 * 60
MONITOR_API_URL = (
    'https://api.github.com/repos/jmtdev0/beecthor-summary/contents'
    '/polymarket_assistant/last_monitor_action.json'
)

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Phone monitor executor for Polymarket exits.')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Build and print the live SELL payload without posting it.',
    )
    parser.add_argument(
        '--env-file',
        default=str(ENV_FILE),
        help='Path to the .env file to load before executing.',
    )
    return parser.parse_args()


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


def sign_order(order: Order) -> str:
    struct_hash = keccak(order.signable_bytes(domain=DOMAIN))
    pk = eth_keys.PrivateKey(bytes.fromhex(POLY_PRIVATE_KEY.lstrip('0x')))
    sig = pk.sign_msg_hash(struct_hash)
    # eth_keys produces v ∈ {0, 1}; Ethereum expects v ∈ {27, 28}
    sig_bytes = bytearray(sig.to_bytes())
    sig_bytes[64] += 27
    return '0x' + bytes(sig_bytes).hex()


def get_market_price(token_id: str, side: str, amount: float) -> float:
    resp = requests.get(
        f'{CLOB_HOST}/book',
        params={'token_id': token_id},
        timeout=15,
    )
    resp.raise_for_status()
    book = resp.json()

    if side == 'BUY':
        levels = sorted(book.get('asks', []), key=lambda x: float(x['price']))
    else:
        levels = sorted(book.get('bids', []), key=lambda x: float(x['price']), reverse=True)

    total = 0.0
    for level in levels:
        price = float(level['price'])
        size = float(level['size'])
        total += size if side == 'SELL' else size * price
        if total >= amount:
            return price

    if levels:
        return float(levels[-1]['price'])
    raise RuntimeError('Empty order book')


def round_down(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(value * factor) / factor


def to_usdc(value: float) -> int:
    return int(round(value * 1_000_000))


def build_order_dict(token_id: str, side: str, amount: float, price: float) -> dict:
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

    # Types must match SignedOrder.dict() from py_order_utils exactly:
    # salt → int, tokenId/amounts/expiration/nonce/feeRateBps → str, signatureType → int
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


def find_recent_matching_sell(action_data: dict) -> dict | None:
    now_ts = int(time.time())
    market_slug = action_data.get('market_slug', '')
    outcome = action_data.get('outcome', '')
    token_id = str(action_data.get('token_id', ''))

    for item in fetch_recent_activity():
        if item.get('type') != 'TRADE':
            continue
        if item.get('side') != 'SELL':
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


def resolve_live_target(action_data: dict) -> dict | None:
    market_slug = action_data.get('market_slug', '')
    outcome = action_data.get('outcome', '')
    token_id = action_data.get('token_id', '')

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
        if str(pos.get('asset', '')) == str(token_id)
    ]
    if hinted:
        hinted.sort(key=lambda pos: float(pos.get('size') or 0), reverse=True)
        return hinted[0]

    return None


def get_last_executed_ts() -> str:
    try:
        return LAST_EXECUTED_FILE.read_text().strip()
    except Exception:
        return ''


def save_last_executed_ts(ts: str) -> None:
    LAST_EXECUTED_FILE.write_text(ts)


def post_order(order_dict: dict) -> requests.Response:
    body = {
        'order': order_dict,
        'owner': POLY_API_KEY,
        'orderType': 'FOK',
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


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file, override=True)
    refresh_runtime_config()

    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[monitor-executor] {ts} dry_run={args.dry_run}')

    def maybe_send_telegram(text: str) -> None:
        if not args.dry_run:
            send_telegram(text)

    missing = [v for v in ('POLY_API_KEY', 'POLY_API_SECRET', 'POLY_API_PASSPHRASE',
                           'POLY_FUNDER', 'POLY_SIGNER_ADDRESS', 'POLY_PRIVATE_KEY')
               if not os.environ.get(v)]
    if missing:
        print(f'[monitor-executor] Missing env vars: {missing}. Check {ENV_FILE}')
        sys.exit(1)

    resp = requests.get(MONITOR_API_URL, timeout=15, headers={'Cache-Control': 'no-cache'})
    if resp.status_code == 404:
        print('[monitor-executor] last_monitor_action.json not found — no monitor action yet.')
        return
    resp.raise_for_status()
    action_data = json.loads(base64.b64decode(resp.json()['content']))

    if action_data.get('status') != 'pending_phone_execution':
        print(f'[monitor-executor] No pending order. Status: {action_data.get("status")}')
        return

    order_ts = action_data.get('timestamp', '')
    if order_ts == get_last_executed_ts():
        print(f'[monitor-executor] Order at {order_ts} already executed. Nothing to do.')
        return

    action = action_data.get('action', '')
    market_slug = action_data.get('market_slug', '')
    outcome = action_data.get('outcome', '')
    side = action_data.get('side', 'SELL')
    prob = action_data.get('prob', 0)
    amount = float(action_data.get('amount', 0))
    token_id = action_data.get('token_id', '')
    print(f'[monitor-executor] Pending: {action} {side} {outcome} on "{market_slug}" amount={amount} prob={prob:.1%}')
    print(f'[monitor-executor] Order timestamp: {order_ts}')

    recent_sell = find_recent_matching_sell(action_data)
    if recent_sell:
        print(
            '[monitor-executor] Recent matching SELL found in activity; '
            'marking monitor action as already handled.'
        )
        save_last_executed_ts(order_ts)
        message = (
            f'\u26a0\ufe0f {action} ya parece ejecutado:\n'
            f'{market_slug}\n'
            f'{outcome} @ {prob:.0%}\n'
            'He visto una venta reciente en la actividad de la cuenta. '
            'Probablemente te adelantaste, impaciente.'
        )
        maybe_send_telegram(message)
        return

    live_target = resolve_live_target(action_data)
    if not live_target:
        print('[monitor-executor] No matching live position found. Marking action as stale.')
        save_last_executed_ts(order_ts)
        if action == 'TAKE_PROFIT':
            message = (
                f'\u26a0\ufe0f TAKE_PROFIT ya no aplica:\n'
                f'{market_slug}\n'
                f'{outcome} @ {prob:.0%}\n'
                'La posición ya no aparece abierta en Polymarket. '
                'Probablemente la cerraste tú antes, impaciente.'
            )
        else:
            message = (
                f'\u26a0\ufe0f Monitor action skipped as stale:\n'
                f'{market_slug}\n'
                f'{outcome} @ {prob:.0%}\n'
                'No live matching position found on Polymarket.'
            )
        maybe_send_telegram(
            message
        )
        return

    live_token_id = str(live_target.get('asset', ''))
    live_amount = float(live_target.get('size') or 0)
    live_outcome = live_target.get('outcome', outcome)
    if live_outcome != outcome or live_token_id != str(token_id) or abs(live_amount - amount) > 0.0001:
        print(
            '[monitor-executor] Live position differs from queued action; '
            f'using live values outcome={live_outcome} token={live_token_id} size={live_amount:.6f}'
        )
        outcome = live_outcome
        token_id = live_token_id
        amount = live_amount

    if not token_id or amount <= 0:
        print('[monitor-executor] Invalid live token/amount after reconciliation.')
        return

    max_attempts = 5
    retry_delay = 20
    resp = None

    for attempt in range(1, max_attempts + 1):
        print(f'[monitor-executor] Attempt {attempt}/{max_attempts} — querying order book...')
        try:
            price = get_market_price(token_id, side, amount)
            print(f'[monitor-executor] Market price: {price}')
            order_dict = build_order_dict(token_id, side, amount, price)
        except Exception as exc:
            print(f'[monitor-executor] Failed to build order: {exc}')
            if attempt < max_attempts:
                print(f'[monitor-executor] Retrying in {retry_delay}s...')
                time.sleep(retry_delay)
            continue

        body = {
            'order': order_dict,
            'owner': POLY_API_KEY,
            'orderType': 'FOK',
            'postOnly': False,
        }
        if args.dry_run:
            print('[monitor-executor] DRY RUN payload:')
            print(json.dumps(body, indent=2))
            return

        resp = post_order(order_dict)
        if resp.ok:
            print(f'[monitor-executor] SUCCESS: {resp.text}')
            save_last_executed_ts(order_ts)
            maybe_send_telegram(
                f'\u2705 {action} executed from phone:\n'
                f'{outcome} @ {prob:.0%}\n'
                f'{market_slug} sold {amount}'
            )
            return

        print(f'[monitor-executor] Attempt {attempt} FAILED {resp.status_code}: {resp.text}')
        if attempt < max_attempts:
            print(f'[monitor-executor] Retrying in {retry_delay}s...')
            time.sleep(retry_delay)

    if resp is not None:
        maybe_send_telegram(f'\u274c Monitor order failed after {max_attempts} attempts ({action}):\n{resp.status_code} {resp.text}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[monitor-executor] Exception: {exc}')
        send_telegram(f'\u274c Exception in monitor executor: {exc}')
