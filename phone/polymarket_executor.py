#!/usr/bin/env python3
"""
Polymarket Phone Executor

Runs 5 minutes after each server cycle (cron: 01:05, 07:35, 13:35, 20:05 UTC).
Reads order params from last_run_summary.json in the GitHub repo, queries the
live order book, builds and signs the EIP-712 order with the private key, and
POSTs to the Polymarket CLOB API using the phone's residential IP.

Dependencies: requests, python-dotenv, eth-keys, poly-eip712-structs (no Rust)
"""

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
LAST_EXECUTED_FILE = Path.home() / '.polymarket_last_executed_ts'
CLOB_HOST = 'https://clob.polymarket.com'
ORDER_PATH = '/order'
SUMMARY_API_URL = (
    'https://api.github.com/repos/jmtdev0/beecthor-summary/contents'
    '/polymarket_assistant/last_run_summary.json'
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
    resp.raise_for_status()
    book = resp.json()

    if side == 'BUY':
        levels = book.get('asks', [])
        # asks are sorted ascending — walk from cheapest
        levels = sorted(levels, key=lambda x: float(x['price']))
    else:
        levels = book.get('bids', [])
        # bids are sorted descending — walk from highest
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

    # If not fully fillable, return best available price (FOK will fail if insufficient)
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
        # makerAmount = USDC spent, takerAmount = shares received
        maker_amount = to_usdc(round_down(amount, 2))
        taker_amount = to_usdc(round_down(amount / price, 4))
    else:
        # makerAmount = shares sold, takerAmount = USDC received
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
        'salt': str(salt),
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


def get_last_executed_ts() -> str:
    try:
        return LAST_EXECUTED_FILE.read_text().strip()
    except Exception:
        return ''


def save_last_executed_ts(ts: str) -> None:
    LAST_EXECUTED_FILE.write_text(ts)


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


def main() -> None:
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[executor] {ts}')

    missing = [v for v in ('POLY_API_KEY', 'POLY_API_SECRET', 'POLY_API_PASSPHRASE',
                           'POLY_FUNDER', 'POLY_SIGNER_ADDRESS', 'POLY_PRIVATE_KEY')
               if not os.environ.get(v)]
    if missing:
        print(f'[executor] Missing env vars: {missing}. Check {ENV_FILE}')
        sys.exit(1)

    resp = requests.get(SUMMARY_API_URL, timeout=15, headers={'Cache-Control': 'no-cache'})
    resp.raise_for_status()
    summary = json.loads(base64.b64decode(resp.json()['content']))

    execution = summary.get('execution', {})
    details = execution.get('details') or {}

    if details.get('status') != 'pending_phone_execution':
        print(f'[executor] No pending order. Last action: {summary.get("decision", {}).get("action")}')
        return

    token_id = details.get('token_id', '')
    side = details.get('side', '')
    if not token_id or not side:
        print('[executor] Missing token_id or side in order params.')
        return

    order_ts = summary.get('timestamp', '')
    if order_ts == get_last_executed_ts():
        print(f'[executor] Order at {order_ts} already executed. Nothing to do.')
        return

    order_type = details.get('type', 'OPEN_POSITION')
    market = details.get('market') or details.get('market_slug', '')
    outcome = details.get('outcome', '')
    amount = float(details.get('stake_usd') or details.get('amount', 0))
    print(f'[executor] Pending: {order_type} {side} {outcome} on "{market}" amount={amount}')
    print(f'[executor] Order timestamp: {order_ts}')

    max_attempts = 5
    retry_delay = 20

    for attempt in range(1, max_attempts + 1):
        print(f'[executor] Attempt {attempt}/{max_attempts} — querying order book...')
        try:
            price = get_market_price(token_id, side, amount)
            print(f'[executor] Market price: {price}')
            order_dict = build_order_dict(token_id, side, amount, price)
        except Exception as exc:
            print(f'[executor] Failed to build order: {exc}')
            if attempt < max_attempts:
                print(f'[executor] Retrying in {retry_delay}s...')
                time.sleep(retry_delay)
            continue

        resp = post_order(order_dict)
        if resp.ok:
            print(f'[executor] SUCCESS: {resp.text}')
            save_last_executed_ts(order_ts)
            send_telegram(f'\u2705 Order executed from phone:\n{order_type} {outcome}\n{market} size={amount}')
            return

        print(f'[executor] Attempt {attempt} FAILED {resp.status_code}: {resp.text}')
        if attempt < max_attempts:
            print(f'[executor] Retrying in {retry_delay}s...')
            time.sleep(retry_delay)

    send_telegram(f'\u274c Order failed after {max_attempts} attempts:\n{resp.status_code} {resp.text}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[executor] Exception: {exc}')
        send_telegram(f'\u274c Exception in phone executor: {exc}')
