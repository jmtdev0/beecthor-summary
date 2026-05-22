#!/usr/bin/env python3
"""
Autonomous Polymarket phone monitor for exits.

Runs on the phone every odd UTC hour + 5 minutes, reads live open positions
directly from the Polymarket Data API, applies a hard-coded take-profit
threshold, and if needed builds and signs a SELL order locally before posting
it to the CLOB.

No server-side action file or LLM is required for exits. The phone always
refreshes the live order book before selling. Positions bought at or below 75%
can be fully sold at 75% or better; positions bought above 75% are left to run
until the executable sell price reaches 100%.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
CLOB_HOST = 'https://clob.polymarket.com'
DATA_API_HOST = 'https://data-api.polymarket.com'
TAKE_PROFIT_THRESHOLD = 0.75
HIGH_ENTRY_TAKE_PROFIT_THRESHOLD = 1.0
ENABLE_EXCEPTIONAL_STOP_LOSS = False
EXCEPTIONAL_STOP_LOSS_THRESHOLD = 0.15
# Do not execute an exit below the configured threshold, even if the server saw
# a qualifying quote a few seconds earlier. The live executable book price is
# the final source of truth for the order.
MAX_TAKE_PROFIT_ACTIONS_PER_RUN = 2
MONITOR_EXECUTED_ACTIONS_FILE = Path.home() / '.polymarket_monitor_executed_action_keys'

load_dotenv(ENV_FILE)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
POLY_API_SECRET = os.environ.get('POLY_API_SECRET', '')
POLY_API_PASSPHRASE = os.environ.get('POLY_API_PASSPHRASE', '')
POLY_FUNDER = os.environ.get('POLY_FUNDER', '')
POLY_SIGNER_ADDRESS = os.environ.get('POLY_SIGNER_ADDRESS', '')
POLY_PRIVATE_KEY = os.environ.get('POLY_PRIVATE_KEY', '')
GH_TOKEN = os.environ.get('GH_TOKEN', '')

TRADE_LOG_API_URL = 'https://api.github.com/repos/jmtdev0/beecthor-summary/contents/polymarket_assistant/trade_log.json'
NEG_RISK_CACHE: dict[str, bool] = {}


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
    global GH_TOKEN
    GH_TOKEN = os.environ.get('GH_TOKEN', '')
    refresh_log_client_config()


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class MarketResolvedException(Exception):
    """Raised when the order book returns 404 because the market has already resolved."""


def parse_end_date(value: Any) -> float:
    if not value:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.fromisoformat(f'{text}T23:59:59+00:00')
        except ValueError:
            return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def is_live_exit_position(position: dict[str, Any]) -> bool:
    if position.get('redeemable') is True:
        return False
    if safe_float(position.get('size')) <= 0:
        return False
    current_value = safe_float(position.get('currentValue'))
    cur_price = safe_float(position.get('curPrice'))
    if current_value <= 0 and cur_price <= 0:
        return False
    end_ts = parse_end_date(position.get('endDate'))
    if end_ts and end_ts < time.time():
        return False
    return True


def get_market_price(token_id: str, side: str, amount: float) -> float:
    resp = requests.get(
        f'{CLOB_HOST}/book',
        params={'token_id': token_id},
        timeout=15,
    )
    if resp.status_code == 404:
        raise MarketResolvedException(f'Order book not found (404) — market likely resolved; token_id={token_id}')
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


def monitor_action_key(action: str, position: dict[str, Any]) -> str:
    return f'{action}:{position.get("slug", "")}:{position.get("outcome", "")}:{position.get("asset", "")}'


def load_monitor_action_keys() -> set[str]:
    try:
        return set(MONITOR_EXECUTED_ACTIONS_FILE.read_text().splitlines())
    except Exception:
        return set()


def save_monitor_action_key(key: str) -> None:
    keys = load_monitor_action_keys()
    keys.add(key)
    MONITOR_EXECUTED_ACTIONS_FILE.write_text('\n'.join(sorted(keys)))


def take_profit_sell_threshold(position: dict[str, Any]) -> float:
    avg_price = safe_float(position.get('avgPrice'))
    if avg_price > TAKE_PROFIT_THRESHOLD:
        return HIGH_ENTRY_TAKE_PROFIT_THRESHOLD
    return TAKE_PROFIT_THRESHOLD


def classify_action(
    position: dict[str, Any],
) -> tuple[str, float] | tuple[None, None]:
    prob = safe_float(position.get('curPrice'))
    size = safe_float(position.get('size'))
    token_id = str(position.get('asset', ''))

    full_sell_price = None
    if token_id and size > 0:
        try:
            full_sell_price = get_market_price(token_id, 'SELL', size)
        except MarketResolvedException as exc:
            print(f'[monitor-executor] Skipping resolved/untradeable position while classifying: {exc}')
            return None, None
        except Exception as exc:
            print(f'[monitor-executor] Could not classify by executable book price: {exc}')

    min_full_sell_price = take_profit_sell_threshold(position)
    if full_sell_price is not None and full_sell_price >= min_full_sell_price:
        position['_selected_book_sell_price'] = full_sell_price
        return 'TAKE_PROFIT', 1.0
    if (
        ENABLE_EXCEPTIONAL_STOP_LOSS
        and 0 < prob <= EXCEPTIONAL_STOP_LOSS_THRESHOLD
        and safe_float(position.get('currentValue')) >= 0.05
    ):
        return 'EXCEPTIONAL_STOP_LOSS', 1.0
    return None, None


def position_priority_key(action: str, position: dict[str, Any]) -> tuple[int, float]:
    sell_price = safe_float(position.get('_selected_book_sell_price'), safe_float(position.get('curPrice')))
    priority = {
        'TAKE_PROFIT': 0,
        'EXCEPTIONAL_STOP_LOSS': 1,
    }.get(action, 9)
    return (priority, -sell_price)


def choose_target_positions(
    positions: list[dict[str, Any]],
    limit: int = MAX_TAKE_PROFIT_ACTIONS_PER_RUN,
) -> list[tuple[str, float, dict[str, Any]]]:
    candidates: list[tuple[str, float, dict[str, Any]]] = []
    executed_keys = load_monitor_action_keys()
    for pos in positions:
        if not is_live_exit_position(pos):
            continue
        action, fraction = classify_action(pos)
        if action:
            key = monitor_action_key(action, pos)
            if key in executed_keys:
                continue
            candidates.append((action, fraction, pos))
    candidates.sort(key=lambda item: position_priority_key(item[0], item[2]))
    return candidates[:max(0, limit)]


def choose_target_position(positions: list[dict[str, Any]]) -> tuple[str, float, dict[str, Any]] | tuple[None, None, None]:
    targets = choose_target_positions(positions, limit=1)
    if not targets:
        return None, None, None
    return targets[0]


def post_order(order_dict: dict[str, Any]) -> requests.Response:
    body = {
        'order': order_dict,
        'owner': POLY_API_KEY,
        'orderType': 'FOK',
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


def append_trade_closed_to_log(entry: dict[str, Any]) -> None:
    """Append a monitor trade entry to trade_log.json via GitHub Contents API."""
    if not GH_TOKEN:
        print('[monitor-executor] GH_TOKEN not set — skipping trade_log update')
        return
    headers = {
        'Authorization': f'token {GH_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
    }
    resp = requests.get(TRADE_LOG_API_URL, headers=headers, timeout=20)
    if not resp.ok:
        print(f'[monitor-executor] Failed to fetch trade_log.json: {resp.status_code}')
        return
    data = resp.json()
    sha = data['sha']
    log = json.loads(base64.b64decode(data['content']).decode('utf-8'))
    log.append(entry)
    new_content = base64.b64encode(
        json.dumps(log, ensure_ascii=False, indent=2).encode('utf-8')
    ).decode('utf-8')
    put_resp = requests.put(
        TRADE_LOG_API_URL,
        headers=headers,
        json={
            'message': f'chore: auto {entry.get("type", "trade_exit")} {entry.get("market_slug", "")} ({entry.get("close_reason", "")})',
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
        print('[monitor-executor] monitor trade entry appended to trade_log.json on GitHub')
    else:
        print(f'[monitor-executor] Failed to update trade_log.json: {put_resp.status_code} {put_resp.text[:200]}')


def minimum_executable_price(action: str, position: dict[str, Any]) -> float:
    if action == 'TAKE_PROFIT':
        return take_profit_sell_threshold(position)
    return 0.001


def post_sell_order_with_version_retry(token_id: str, amount: float, price: float) -> requests.Response:
    order_dict = build_order_dict_v2(
        token_id,
        'SELL',
        amount,
        price,
        funder=POLY_FUNDER,
        signer_address=POLY_SIGNER_ADDRESS,
        private_key=POLY_PRIVATE_KEY,
    )
    resp = post_order(order_dict)
    if not is_order_version_mismatch_response(resp):
        return resp

    clob_version = get_clob_version()
    print(f'[monitor-executor] CLOB reported order_version_mismatch; live version={clob_version}. Retrying once with fresh V2 signature.')
    if clob_version != CLOB_ORDER_VERSION:
        return resp

    retry_order = build_order_dict_v2(
        token_id,
        'SELL',
        amount,
        price,
        funder=POLY_FUNDER,
        signer_address=POLY_SIGNER_ADDRESS,
        private_key=POLY_PRIVATE_KEY,
    )
    return post_order(retry_order)


def execute_target_position(action: str, fraction: float, target: dict[str, Any], dry_run: bool = False) -> bool:
    market_slug = target.get('slug', '')
    title = target.get('title', market_slug)
    outcome = target.get('outcome', '')
    prob = safe_float(target.get('curPrice'))
    size = safe_float(target.get('size'))
    amount = size * fraction
    token_id = str(target.get('asset', ''))
    action_key = monitor_action_key(action, target)

    def maybe_send_telegram(text: str) -> None:
        if not dry_run:
            send_telegram(text)

    selected_book_sell_price = safe_float(target.get('_selected_book_sell_price'))
    book_note = f' selected_book_sell={selected_book_sell_price:.1%}' if selected_book_sell_price else ''
    print(f'[monitor-executor] Trigger: {action} SELL {outcome} on "{market_slug}" amount={amount} prob={prob:.1%}{book_note}')
    send_server_log(
        'phone.monitor',
        'trigger_detected',
        f'{action} selected for {market_slug}',
        payload={
            'market_slug': market_slug,
            'title': title,
            'outcome': outcome,
            'probability': prob,
            'selected_book_sell_price': selected_book_sell_price,
            'amount': amount,
            'fraction': fraction,
        },
    )

    try:
        print('[monitor-executor] Querying order book...')
        price = get_market_price(token_id, 'SELL', amount)
        print(f'[monitor-executor] Market price: {price}')
        minimum_price = minimum_executable_price(action, target)
        if price < minimum_price:
            detail = (
                f'Live executable SELL price {price:.4f} is below the minimum '
                f'exit threshold {minimum_price:.4f}'
            )
            print(f'[monitor-executor] Skipping SELL: {detail}')
            send_server_log(
                'phone.monitor',
                'trigger_skipped',
                detail,
                payload={
                    'market_slug': market_slug,
                    'action': action,
                    'live_probability': prob,
                    'book_sell_price': price,
                    'minimum_exit_price': minimum_price,
                },
            )
            maybe_send_telegram(
                f'\u2139\ufe0f {action} skipped from phone:\n'
                f'{title}\n'
                f'{outcome} @ {prob:.0%}\n'
                f'El libro solo permit\u00eda vender a {price:.0%}. '
                f'No vendo por debajo de {minimum_price:.0%}.'
            )
            return False
    except MarketResolvedException as exc:
        print(f'[monitor-executor] Market already resolved: {exc}')
        send_server_log(
            'phone.monitor',
            'market_resolved',
            'Order book unavailable — market has resolved; Polymarket will auto-redeem',
            payload={'market_slug': market_slug, 'action': action, 'token_id': token_id},
        )
        maybe_send_telegram(
            f'\u2139\ufe0f {action} — market already resolved:\n'
            f'{title}\n'
            f'{outcome} @ {prob:.0%}\n'
            'El mercado ya est\u00e1 resuelto. Polymarket har\u00e1 el reembolso autom\u00e1ticamente.'
        )
        return True
    except Exception as exc:
        print(f'[monitor-executor] Failed to build order: {exc}')
        send_server_log('phone.monitor', 'order_failed', f'Failed to build order: {exc}', level='error', payload={'market_slug': market_slug, 'action': action})
        maybe_send_telegram(f'\u274c Monitor order build failed ({action}):\n{title}\n{exc}')
        return False

    body = {
        'order': build_order_dict_v2(
            token_id,
            'SELL',
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
        print('[monitor-executor] DRY RUN payload:')
        print(json.dumps(body, indent=2))
        send_server_log('phone.monitor', 'order_dry_run', 'Built SELL payload successfully', payload={'market_slug': market_slug, 'action': action, 'price': price})
        return True

    resp = post_sell_order_with_version_retry(token_id, amount, price)
    if resp.ok:
        print(f'[monitor-executor] SUCCESS: {resp.text}')
        send_server_log(
            'phone.monitor',
            'order_executed',
            f'{action} executed successfully',
            payload={
                'market_slug': market_slug,
                'title': title,
                'outcome': outcome,
                'action': action,
                'price': price,
                'amount': amount,
                'fraction': fraction,
                'live_probability': prob,
                'response': resp.text[:500],
            },
        )
        save_monitor_action_key(action_key)
        maybe_send_telegram(
            f'\u2705 {action} executed from phone:\n'
            f'{title}\n'
            f'{outcome} @ {prob:.0%}\n'
            f'sold {amount:.4f}'
        )
        avg_entry = safe_float(target.get('avgPrice', 0))
        entry_cost = round(amount * avg_entry, 4) if avg_entry else None
        exit_proceeds = round(amount * price, 4)
        pnl_usd = round(exit_proceeds - entry_cost, 4) if entry_cost is not None else None
        pnl_pct = round((exit_proceeds / entry_cost - 1) * 100, 2) if entry_cost else None
        append_trade_closed_to_log({
            'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'type': 'trade_closed',
            'market_slug': market_slug,
            'market_title': title,
            'outcome': outcome,
            'side': 'SELL',
            'close_reason': action.lower(),
            'shares': round(amount, 4),
            'fraction': round(fraction, 4),
            'avg_entry_price': avg_entry,
            'exit_price': round(price, 4),
            'entry_cost_usd': entry_cost,
            'exit_proceeds_usd': exit_proceeds,
            'pnl_usd': pnl_usd,
            'pnl_pct': pnl_pct,
            'source': 'monitor_executor',
        })
        return True

    print(f'[monitor-executor] FAILED {resp.status_code}: {resp.text}')
    send_server_log('phone.monitor', 'order_failed', f'{action} failed', level='error', payload={'market_slug': market_slug, 'action': action, 'status_code': resp.status_code, 'error': resp.text[:500]})
    maybe_send_telegram(f'\u274c Monitor order failed ({action}):\n{title}\n{resp.status_code} {resp.text}')
    return False


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file, override=True)
    refresh_runtime_config()

    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[monitor-executor] {ts} dry_run={args.dry_run}')
    send_server_log('phone.monitor', 'run_started', 'Monitor run started', payload={'timestamp': ts, 'dry_run': args.dry_run})
    clob_version = get_clob_version()
    if clob_version != CLOB_ORDER_VERSION:
        send_server_log(
            'phone.monitor',
            'clob_version_warning',
            f'Unexpected CLOB version {clob_version}',
            level='warning',
            payload={'expected_version': CLOB_ORDER_VERSION, 'actual_version': clob_version},
        )

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
        send_server_log('phone.monitor', 'run_failed', 'Missing required environment variables', level='error', payload={'missing': missing})
        sys.exit(1)

    positions = fetch_live_positions()
    if not positions:
        print('[monitor-executor] No open positions.')
        send_server_log('phone.monitor', 'run_skipped', 'No open positions')
        return

    targets = choose_target_positions(positions)
    if not targets:
        print('[monitor-executor] No exit trigger in live positions.')
        send_server_log('phone.monitor', 'run_skipped', 'No exit trigger in live positions', payload={'open_positions': len(positions)})
        return

    send_server_log(
        'phone.monitor',
        'run_active',
        'Exit targets selected for execution',
        payload={'open_positions': len(positions), 'selected_targets': len(targets)},
    )

    for index, (action, fraction, target) in enumerate(targets, 1):
        print(f'[monitor-executor] --- Target {index}/{len(targets)} ---')
        execute_target_position(action, fraction, target, dry_run=args.dry_run)
        if index < len(targets):
            time.sleep(3)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[monitor-executor] Exception: {exc}')
        send_telegram(f'\u274c Exception in monitor executor: {exc}')
        send_server_log('phone.monitor', 'run_failed', f'Unhandled exception: {exc}', level='error')
