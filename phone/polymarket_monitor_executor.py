#!/usr/bin/env python3
"""
Autonomous Polymarket phone monitor for exits.

Runs on the phone every odd UTC hour + 5 minutes, reads live open positions
directly from the Polymarket Data API, applies hard-coded stop-loss / take-
profit thresholds, validates against recent account activity, and if needed
builds and signs a SELL order locally before posting it to the CLOB.

No server-side action file or LLM is required for exits.
"""

from __future__ import annotations

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
from typing import Any

import requests
from dotenv import load_dotenv
from eth_keys import keys as eth_keys
from eth_utils import keccak
from poly_eip712_structs import Address, EIP712Struct, Uint, make_domain

ENV_FILE = Path.home() / '.polymarket.env'
CLOB_HOST = 'https://clob.polymarket.com'
ORDER_PATH = '/order'
DATA_API_HOST = 'https://data-api.polymarket.com'
RECENT_ACTIVITY_LIMIT = 30
RECENT_TRADE_WINDOW_SECONDS = 6 * 60 * 60
STOP_LOSS_THRESHOLD = 0.20
TAKE_PROFIT_THRESHOLD = 0.88

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
    parser = argparse.ArgumentParser(description='Autonomous phone monitor for Polymarket exits.')
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Select a target and print the SELL payload without posting it.',
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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sign_order(order: Order) -> str:
    struct_hash = keccak(order.signable_bytes(domain=DOMAIN))
    pk = eth_keys.PrivateKey(bytes.fromhex(POLY_PRIVATE_KEY.lstrip('0x')))
    sig = pk.sign_msg_hash(struct_hash)
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


def build_order_dict(token_id: str, side: str, amount: float, price: float) -> dict[str, Any]:
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


def build_l2_headers(method: str, path: str, body_str: str) -> dict[str, str]:
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


def fetch_live_positions() -> list[dict[str, Any]]:
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


def fetch_recent_activity(limit: int = RECENT_ACTIVITY_LIMIT) -> list[dict[str, Any]]:
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


def find_recent_matching_sell(position: dict[str, Any]) -> dict[str, Any] | None:
    now_ts = int(time.time())
    market_slug = position.get('slug', '')
    outcome = position.get('outcome', '')
    token_id = str(position.get('asset', ''))

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


def classify_action(position: dict[str, Any]) -> str | None:
    prob = safe_float(position.get('curPrice'))
    if prob <= STOP_LOSS_THRESHOLD:
        return 'STOP_LOSS'
    if prob >= TAKE_PROFIT_THRESHOLD:
        return 'TAKE_PROFIT'
    return None


def position_priority_key(position: dict[str, Any]) -> tuple[int, float]:
    action = classify_action(position)
    prob = safe_float(position.get('curPrice'))
    if action == 'STOP_LOSS':
        return (0, prob)
    return (1, -prob)


def choose_target_position(positions: list[dict[str, Any]]) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    candidates: list[tuple[str, dict[str, Any]]] = []
    for pos in positions:
        action = classify_action(pos)
        if action:
            candidates.append((action, pos))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: position_priority_key(item[1]))
    return candidates[0]


def post_order(order_dict: dict[str, Any]) -> requests.Response:
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

    missing = [
        v
        for v in (
            'POLY_API_KEY',
            'POLY_API_SECRET',
            'POLY_API_PASSPHRASE',
            'POLY_FUNDER',
            'POLY_SIGNER_ADDRESS',
            'POLY_PRIVATE_KEY',
        )
        if not os.environ.get(v)
    ]
    if missing:
        print(f'[monitor-executor] Missing env vars: {missing}. Check {ENV_FILE}')
        sys.exit(1)

    positions = fetch_live_positions()
    if not positions:
        print('[monitor-executor] No open positions.')
        return

    action, target = choose_target_position(positions)
    if not target:
        print('[monitor-executor] No stop-loss or take-profit trigger in live positions.')
        return

    market_slug = target.get('slug', '')
    title = target.get('title', market_slug)
    outcome = target.get('outcome', '')
    prob = safe_float(target.get('curPrice'))
    amount = safe_float(target.get('size'))
    token_id = str(target.get('asset', ''))
    print(f'[monitor-executor] Trigger: {action} SELL {outcome} on "{market_slug}" amount={amount} prob={prob:.1%}')

    recent_sell = find_recent_matching_sell(target)
    if recent_sell:
        print(
            '[monitor-executor] Recent matching SELL found in activity; '
            'marking monitor action as already handled.'
        )
        maybe_send_telegram(
            f'\u26a0\ufe0f {action} ya parece ejecutado:\n'
            f'{market_slug}\n'
            f'{outcome} @ {prob:.0%}\n'
            'He visto una venta reciente en la actividad de la cuenta. '
            'Probablemente te adelantaste, impaciente.'
        )
        return

    max_attempts = 5
    retry_delay = 20
    resp = None

    for attempt in range(1, max_attempts + 1):
        print(f'[monitor-executor] Attempt {attempt}/{max_attempts} — querying order book...')
        try:
            price = get_market_price(token_id, 'SELL', amount)
            print(f'[monitor-executor] Market price: {price}')
            order_dict = build_order_dict(token_id, 'SELL', amount, price)
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
            maybe_send_telegram(
                f'\u2705 {action} executed from phone:\n'
                f'{title}\n'
                f'{outcome} @ {prob:.0%}\n'
                f'sold {amount:.4f}'
            )
            return

        print(f'[monitor-executor] Attempt {attempt} FAILED {resp.status_code}: {resp.text}')
        if attempt < max_attempts:
            print(f'[monitor-executor] Retrying in {retry_delay}s...')
            time.sleep(retry_delay)

    if resp is not None:
        maybe_send_telegram(
            f'\u274c Monitor order failed after {max_attempts} attempts ({action}):\n'
            f'{title}\n{resp.status_code} {resp.text}'
        )


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[monitor-executor] Exception: {exc}')
        send_telegram(f'\u274c Exception in monitor executor: {exc}')
