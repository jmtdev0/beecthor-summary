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
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

from log_client import refresh_log_client_config, send_server_log
from polymarket_order_v2 import (
    CLOB_ORDER_VERSION,
    ORDER_PATH,
    build_order_dict_v2,
    get_clob_version,
    is_order_version_mismatch_response,
)

ENV_FILE = Path.home() / '.polymarket.env'
EXECUTED_ORDERS_FILE = Path.home() / '.polymarket_executed_order_ids'
CLOB_HOST = 'https://clob.polymarket.com'
DATA_API_HOST = 'https://data-api.polymarket.com'
RECENT_ACTIVITY_LIMIT = 20
RECENT_TRADE_WINDOW_SECONDS = 6 * 60 * 60
BUY_FOK_REPRICE_OFFSETS = (0.0, 0.01, 0.02, 0.03, 0.05)
MAX_OPEN_POSITION_BUY_PRICE = 0.90
MAX_PENDING_ORDER_AGE_MINUTES = 120
PENDING_ORDERS_API_URL = (
    'https://api.github.com/repos/jmtdev0/beecthor-summary/contents'
    '/polymarket_assistant/pending_orders.json'
)
TRADE_LOG_API_URL = (
    'https://api.github.com/repos/jmtdev0/beecthor-summary/contents'
    '/polymarket_assistant/trade_log.json'
)

load_dotenv(ENV_FILE)
NEG_RISK_CACHE: dict[str, bool] = {}

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
POLY_API_SECRET = os.environ.get('POLY_API_SECRET', '')
POLY_API_PASSPHRASE = os.environ.get('POLY_API_PASSPHRASE', '')
POLY_FUNDER = os.environ.get('POLY_FUNDER', '')
POLY_SIGNER_ADDRESS = os.environ.get('POLY_SIGNER_ADDRESS', '')
POLY_PRIVATE_KEY = os.environ.get('POLY_PRIVATE_KEY', '')

GH_TOKEN = os.environ.get('GH_TOKEN', '')

def refresh_runtime_config() -> None:
    global TELEGRAM_BOT_TOKEN
    global TELEGRAM_CHAT_ID
    global POLY_API_KEY
    global POLY_API_SECRET
    global POLY_API_PASSPHRASE
    global GH_TOKEN
    global POLY_FUNDER
    global POLY_SIGNER_ADDRESS
    global POLY_PRIVATE_KEY

    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
    POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
    GH_TOKEN = os.environ.get('GH_TOKEN', '')
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


def parse_order_timestamp(order_id: str) -> datetime | None:
    if not order_id:
        return None
    try:
        return datetime.fromisoformat(order_id.replace('Z', '+00:00')).astimezone(UTC)
    except ValueError:
        return None


class MarketResolvedException(Exception):
    """Raised when the order book returns 404 because the market already resolved."""


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


def clamp_price(value: float) -> float:
    return min(0.999, max(0.001, round(value, 3)))


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


def as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def append_trade_opened_to_log(entry: dict) -> None:
    if not GH_TOKEN:
        print('[executor] GH_TOKEN not set - skipping trade_log update')
        return

    headers = {
        'Authorization': f'token {GH_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    resp = requests.get(TRADE_LOG_API_URL, headers=headers, timeout=20)
    if not resp.ok:
        print(f'[executor] Failed to fetch trade_log.json: {resp.status_code}')
        return

    data = resp.json()
    sha = data['sha']
    log = json.loads(base64.b64decode(data['content']).decode('utf-8'))
    market_slug = str(entry.get('market_slug') or '')
    position_side = str(entry.get('position_side') or '')
    for existing in log:
        if existing.get('type') != 'trade_opened':
            continue
        existing_side = str(existing.get('position_side') or existing.get('outcome') or '')
        if existing.get('market_slug') == market_slug and existing_side == position_side:
            print(f'[executor] trade_opened already present for {market_slug}:{position_side}')
            return

    log.append(entry)
    new_content = base64.b64encode(
        json.dumps(log, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    put_resp = requests.put(
        TRADE_LOG_API_URL,
        headers=headers,
        json={
            'message': f'chore: auto trade_opened {market_slug}',
            'content': new_content,
            'sha': sha,
            'committer': {
                'name': 'beecthor-summarizer[bot]',
                'email': 'beecthor-summarizer[bot]@users.noreply.github.com',
            },
        },
        timeout=30,
    )
    if put_resp.ok:
        print(f'[executor] trade_opened appended to trade_log.json for {market_slug}:{position_side}')
    else:
        print(f'[executor] Failed to update trade_log.json: {put_resp.status_code} {put_resp.text[:200]}')


def update_pending_order_status(order_id: str, status: str, detail: str, payload: dict | None = None) -> None:
    if not GH_TOKEN or not order_id:
        return

    headers = {
        'Authorization': f'token {GH_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    resp = requests.get(PENDING_ORDERS_API_URL, headers=headers, timeout=20)
    if not resp.ok:
        print(f'[executor] Failed to fetch pending_orders.json for receipt: {resp.status_code}')
        return

    data = resp.json()
    sha = data['sha']
    queue = json.loads(base64.b64decode(data['content']).decode('utf-8'))
    changed = False
    now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    for item in queue:
        if item.get('order_id') != order_id:
            continue
        item['status'] = status
        item['execution_status_detail'] = detail[:500]
        item['execution_updated_at'] = now
        if payload:
            item['execution_payload'] = payload
        changed = True
        break
    if not changed:
        return

    new_content = base64.b64encode(
        json.dumps(queue, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    put_resp = requests.put(
        PENDING_ORDERS_API_URL,
        headers=headers,
        json={
            'message': f'chore: mark pending order {status} {order_id}',
            'content': new_content,
            'sha': sha,
            'committer': {
                'name': 'beecthor-summarizer[bot]',
                'email': 'beecthor-summarizer[bot]@users.noreply.github.com',
            },
        },
        timeout=30,
    )
    if put_resp.ok:
        print(f'[executor] pending order receipt updated: {order_id} -> {status}')
    else:
        print(f'[executor] Failed to update pending order receipt: {put_resp.status_code} {put_resp.text[:200]}')


def build_trade_opened_entry(
    pending: dict,
    live_position: dict | None,
    recent_trade: dict | None,
    *,
    source: str,
    notes: str,
) -> dict | None:
    market_slug = str(pending.get('market_slug') or pending.get('market') or (live_position or {}).get('slug') or '')
    position_side = str(pending.get('outcome') or (live_position or {}).get('outcome') or (recent_trade or {}).get('outcome') or '')
    if not market_slug or not position_side:
        return None

    order_ts = parse_order_timestamp(str(pending.get('order_id') or ''))
    trade_ts = recent_trade.get('timestamp') if recent_trade else None
    entry_dt = order_ts or datetime.now(UTC)
    try:
        if trade_ts is not None:
            entry_dt = datetime.fromtimestamp(int(trade_ts), UTC)
    except (TypeError, ValueError, OSError):
        pass

    avg_price = as_float((live_position or {}).get('avgPrice'))
    if avg_price <= 0.0:
        avg_price = as_float((recent_trade or {}).get('price'))

    shares = as_float((live_position or {}).get('size'))
    if shares <= 0.0:
        shares = as_float((recent_trade or {}).get('size'))
    if shares <= 0.0 and avg_price > 0.0:
        shares = round(as_float(pending.get('stake_usd')) / avg_price, 4)

    entry_cost = as_float((live_position or {}).get('initialValue'))
    if entry_cost <= 0.0 and shares > 0.0 and avg_price > 0.0:
        entry_cost = round(shares * avg_price, 4)
    if entry_cost <= 0.0:
        entry_cost = as_float(pending.get('stake_usd'))

    to_win = shares if shares > 0.0 else 0.0
    max_profit = to_win - entry_cost if to_win > 0.0 and entry_cost > 0.0 else 0.0

    entry = {
        'timestamp': entry_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'type': 'trade_opened',
        'review_window': 'phone_executor',
        'event_slug': (live_position or {}).get('eventSlug', ''),
        'market_slug': market_slug,
        'market_title': str(pending.get('market') or (live_position or {}).get('title') or market_slug),
        'position_side': position_side,
        'token_id': str(pending.get('token_id') or (live_position or {}).get('asset') or (recent_trade or {}).get('asset') or ''),
        'entry_probability': round(avg_price, 6) if avg_price > 0.0 else None,
        'entry_cost_usd': round(entry_cost, 4) if entry_cost > 0.0 else None,
        'shares': round(shares, 4) if shares > 0.0 else None,
        'to_win_usd': round(to_win, 4) if to_win > 0.0 else None,
        'max_profit_usd': round(max_profit, 4) if max_profit > 0.0 else None,
        'market_type': pending.get('market_type'),
        'slot_name': pending.get('slot_name'),
        'beecthor_aligned': pending.get('beecthor_aligned'),
        'momentum_confirmed': pending.get('momentum_confirmed'),
        'expiry_validity': pending.get('expiry_validity'),
        'status': 'open',
        'source': source,
        'notes': notes,
    }
    return {key: value for key, value in entry.items() if value not in (None, '')}


def reconcile_trade_opened(
    pending: dict,
    *,
    source: str,
    notes: str,
    live_position: dict | None = None,
    recent_trade: dict | None = None,
) -> dict | None:
    live_position = live_position or resolve_live_position(pending)
    recent_trade = recent_trade or find_recent_matching_trade(pending)
    entry = build_trade_opened_entry(
        pending,
        live_position,
        recent_trade,
        source=source,
        notes=notes,
    )
    if entry:
        append_trade_opened_to_log(entry)
    return entry


def format_money(value: object) -> str:
    amount = as_float(value)
    if amount <= 0.0:
        return 'n/d'
    return f'${amount:.2f}'


def format_shares(value: object) -> str:
    shares = as_float(value)
    if shares <= 0.0:
        return 'n/d'
    return f'{shares:.4f}'.rstrip('0').rstrip('.')


def build_buy_success_message(
    *,
    order_type: str,
    outcome: str,
    market: str,
    amount: float,
    execution_price: float,
    trade_entry: dict | None,
) -> str:
    trade_entry = trade_entry or {}
    shares = as_float(trade_entry.get('shares'))
    if shares <= 0.0 and execution_price > 0.0:
        shares = round_down(amount / execution_price, 4)

    entry_cost = as_float(trade_entry.get('entry_cost_usd'))
    if entry_cost <= 0.0:
        entry_cost = round_down(amount, 2)

    avg_price = as_float(trade_entry.get('entry_probability'))
    if avg_price <= 0.0 and shares > 0.0:
        avg_price = entry_cost / shares

    to_win = as_float(trade_entry.get('to_win_usd'))
    if to_win <= 0.0:
        to_win = shares

    max_profit = as_float(trade_entry.get('max_profit_usd'))
    if max_profit <= 0.0 and to_win > 0.0 and entry_cost > 0.0:
        max_profit = to_win - entry_cost

    lines = [
        '✅ Orden ejecutada desde el móvil:',
        f'{order_type} {outcome}',
        market,
        f'Coste: {format_money(entry_cost)}',
        f'Shares: {format_shares(shares)}',
        f'TO WIN: {format_money(to_win)}',
    ]
    if avg_price > 0.0:
        lines.append(f'Precio medio: {avg_price:.0%}')
    if max_profit > 0.0:
        lines.append(f'Beneficio máximo: +{format_money(max_profit)}')
    return '\n'.join(lines)


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
        'deferExec': False,
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


def is_fill_or_kill_rejection(resp: requests.Response) -> bool:
    return resp.status_code == 400 and 'fully filled or killed' in resp.text.lower()


def build_price_candidates(base_price: float, side: str, order_type: str) -> list[float]:
    if side != 'BUY' or order_type != 'OPEN_POSITION':
        return [clamp_price(base_price)]

    candidates: list[float] = []
    for offset in BUY_FOK_REPRICE_OFFSETS:
        raw_price = base_price + offset
        if raw_price > MAX_OPEN_POSITION_BUY_PRICE:
            continue
        price = clamp_price(raw_price)
        if price not in candidates:
            candidates.append(price)
    return candidates


def post_order_with_version_retry(
    token_id: str,
    side: str,
    amount: float,
    price: float,
    *,
    order_type: str = 'FOK',
) -> tuple[requests.Response, dict]:
    order_dict = build_order_dict_v2(
        token_id,
        side,
        amount,
        price,
        funder=POLY_FUNDER,
        signer_address=POLY_SIGNER_ADDRESS,
        private_key=POLY_PRIVATE_KEY,
    )
    resp = post_order(order_dict, order_type=order_type)
    if not is_order_version_mismatch_response(resp):
        return resp, order_dict

    clob_version = get_clob_version()
    print(f'[executor] CLOB reported order_version_mismatch; live version={clob_version}. Retrying once with fresh V2 signature.')
    if clob_version != CLOB_ORDER_VERSION:
        return resp, order_dict

    retry_order = build_order_dict_v2(
        token_id,
        side,
        amount,
        price,
        funder=POLY_FUNDER,
        signer_address=POLY_SIGNER_ADDRESS,
        private_key=POLY_PRIVATE_KEY,
    )
    retry_resp = post_order(retry_order, order_type=order_type)
    return retry_resp, retry_order


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

    order_ts = parse_order_timestamp(order_id)
    if order_ts and datetime.now(UTC) - order_ts > timedelta(minutes=MAX_PENDING_ORDER_AGE_MINUTES):
        age_minutes = round((datetime.now(UTC) - order_ts).total_seconds() / 60)
        print(f'[executor] Skipping stale order older than {MAX_PENDING_ORDER_AGE_MINUTES} minutes ({age_minutes}m).')
        send_server_log(
            'phone.executor',
            'order_skipped',
            'Pending order skipped because it is stale',
            payload={
                'order_id': order_id,
                'market_slug': pending.get('market_slug'),
                'reason': 'stale_order',
                'age_minutes': age_minutes,
            },
        )

        update_pending_order_status(order_id, 'stale', 'Pending order skipped because it is stale', {'age_minutes': age_minutes})
        save_executed_order_id(order_id)
        if not dry_run:
            send_telegram(
                f'\u26a0\ufe0f Orden descartada por antigua:\n'
                f'{market}\n'
                f'{outcome}\n'
                f'Edad: {age_minutes} min. Mejor esperar una nueva validación del siguiente ciclo.'
            )

        return True

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
            reconcile_trade_opened(
                pending,
                source='phone_executor_reconciled',
                notes='Backfilled from recent account activity after the executor detected the BUY was already executed.',
                recent_trade=recent_trade,
            )
            update_pending_order_status(order_id, 'skipped_already_done', 'Recent matching BUY found in account activity')
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
            reconcile_trade_opened(
                pending,
                source='phone_executor_reconciled',
                notes='Backfilled from a live position after the executor detected the BUY was already open.',
                live_position=live_position,
            )
            update_pending_order_status(order_id, 'skipped_already_done', 'Matching live position already open')
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
            base_price = get_market_price(token_id, side, amount)
            if side == 'BUY' and order_type == 'OPEN_POSITION' and base_price > MAX_OPEN_POSITION_BUY_PRICE:
                detail = (
                    'Live OPEN_POSITION price is above the phone execution cap '
                    f'({base_price:.1%} > {MAX_OPEN_POSITION_BUY_PRICE:.0%})'
                )
                print(f'[executor] Skipping high-probability order: {detail}')
                send_server_log(
                    'phone.executor',
                    'order_skipped',
                    'Pending OPEN_POSITION skipped because live probability is too high',
                    payload={
                        'order_id': order_id,
                        'market_slug': pending.get('market_slug'),
                        'reason': 'live_probability_too_high',
                        'live_probability': round(base_price, 4),
                        'max_allowed_probability': MAX_OPEN_POSITION_BUY_PRICE,
                    },
                )
                update_pending_order_status(
                    order_id,
                    'skipped_probability_too_high',
                    detail,
                    {
                        'market_slug': pending.get('market_slug'),
                        'live_probability': round(base_price, 4),
                        'max_allowed_probability': MAX_OPEN_POSITION_BUY_PRICE,
                    },
                )
                save_executed_order_id(order_id)
                if not dry_run:
                    send_telegram(
                        '\u26a0\ufe0f OPEN_POSITION descartada por precio demasiado alto:\n'
                        f'{market}\n'
                        f'{outcome}\n'
                        f'Precio vivo: {base_price:.0%}\n'
                        f'Límite del móvil: {MAX_OPEN_POSITION_BUY_PRICE:.0%}\n'
                        'Riesgo/recompensa demasiado pobre para abrir ahora.'
                    )
                return True
            price_candidates = build_price_candidates(base_price, side, order_type)
            print(f'[executor] Market price: {base_price} | candidates={price_candidates}')
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
            update_pending_order_status(order_id, 'stale', 'Market already resolved before execution', {'token_id': token_id})
            save_executed_order_id(order_id)
            return True
        except Exception as exc:
            last_error = str(exc)
            print(f'[executor] Failed to build order: {exc}')
            if attempt < max_attempts:
                print(f'[executor] Retrying in {retry_delay}s...')
                time.sleep(retry_delay)
            continue

        for candidate_index, price in enumerate(price_candidates, 1):
            body = {
                'order': build_order_dict_v2(
                    token_id,
                    side,
                    amount,
                    price,
                    funder=POLY_FUNDER,
                    signer_address=POLY_SIGNER_ADDRESS,
                    private_key=POLY_PRIVATE_KEY,
                ),
                'owner': POLY_API_KEY,
                'orderType': 'FOK',
                'deferExec': False,
                'postOnly': False,
            }

            if dry_run:
                print('[executor] DRY RUN payload:')
                print(json.dumps(body, indent=2))
                send_server_log(
                    'phone.executor',
                    'order_dry_run',
                    'Built order payload successfully',
                    payload={
                        'order_id': order_id,
                        'market_slug': pending.get('market_slug'),
                        'price': price,
                        'price_candidates': price_candidates,
                    },
                )
                return True

            resp, _order_dict = post_order_with_version_retry(
                token_id,
                side,
                amount,
                price,
                order_type='FOK',
            )
            if resp.ok:
                print(f'[executor] SUCCESS: {resp.text}')
                send_server_log(
                    'phone.executor',
                    'order_executed',
                    'Order executed successfully on phone',
                    payload={
                        'order_id': order_id,
                        'market_slug': pending.get('market_slug'),
                        'price': price,
                        'response': resp.text[:500],
                    },
                )
                update_pending_order_status(
                    order_id,
                    'executed',
                    'Order executed successfully on phone',
                    {'market_slug': pending.get('market_slug'), 'price': price, 'response': resp.text[:500]},
                )
                save_executed_order_id(order_id)
                trade_entry = None
                if side == 'BUY':
                    trade_entry = reconcile_trade_opened(
                        pending,
                        source='phone_executor',
                        notes='Recorded after a successful phone-side BUY execution.',
                    )
                if side == 'BUY':
                    send_telegram(
                        build_buy_success_message(
                            order_type=order_type,
                            outcome=outcome,
                            market=market,
                            amount=amount,
                            execution_price=price,
                            trade_entry=trade_entry,
                        )
                    )
                else:
                    send_telegram(f'\u2705 Order executed from phone:\n{order_type} {outcome}\n{market} size={amount}')
                return True

            last_error = f'{resp.status_code}: {resp.text}'
            print(f'[executor] Attempt {attempt} candidate {candidate_index}/{len(price_candidates)} FAILED {last_error}')
            if is_fill_or_kill_rejection(resp) and candidate_index < len(price_candidates):
                send_server_log(
                    'phone.executor',
                    'order_repriced',
                    'FOK order failed to fully fill; retrying with a more aggressive price',
                    payload={
                        'order_id': order_id,
                        'market_slug': pending.get('market_slug'),
                        'attempt': attempt,
                        'failed_price': price,
                        'next_price': price_candidates[candidate_index],
                    },
                )
                continue
            break

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
    update_pending_order_status(order_id, 'failed', 'Order failed after retries', {'error': last_error})
    return False


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file, override=True)
    refresh_runtime_config()

    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[executor] {ts} dry_run={args.dry_run}')
    send_server_log('phone.executor', 'run_started', 'Executor run started', payload={'timestamp': ts, 'dry_run': args.dry_run})
    clob_version = get_clob_version()
    if clob_version != CLOB_ORDER_VERSION:
        send_server_log(
            'phone.executor',
            'clob_version_warning',
            f'Unexpected CLOB version {clob_version}',
            level='warning',
            payload={'expected_version': CLOB_ORDER_VERSION, 'actual_version': clob_version},
        )

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
