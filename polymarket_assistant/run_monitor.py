#!/usr/bin/env python3
"""
Polymarket Position Monitor

Runs every minute while the server systemd timer is active.
No GPT/Copilot — hard-coded thresholds only:
  - Take-profit: phone executable SELL price for the full position >= 0.75

On trigger: stores an advisory sell signal, then attempts to launch the phone
monitor executor immediately through the reverse SSH tunnel. The server never
passes order instructions such as token id, side, or amount; the phone refreshes
positions and the live order book, then creates the SELL order only if the
threshold is still viable at execution time. This keeps detection on the server
while preserving residential-IP execution on the phone.

The timer is intentionally on-demand: server cycles enable it after queueing a
phone OPEN_POSITION order, and this monitor disables it again once no live
position remains.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from polymarket_assistant.run_cycle import (
    ASSISTANT_DIR,
    PENDING_ORDERS_PATH,
    fetch_positions,
    load_env,
    load_json,
    now_utc,
    safe_float,
    save_json,
)

MONITOR_ACTION_PATH = ASSISTANT_DIR / 'last_monitor_action.json'
MONITOR_DISPATCH_STATE_PATH = ASSISTANT_DIR / 'monitor_dispatch_state.json'
MONITOR_HISTORY_PATH = ASSISTANT_DIR / 'monitor_history.json'
MONITOR_TIMER_NAME = os.environ.get('POLYMARKET_MONITOR_TIMER_NAME', 'polymarket-monitor.timer')
CLOB_HOST = 'https://clob.polymarket.com'

TAKE_PROFIT_THRESHOLD = 0.75
ENABLE_EXCEPTIONAL_STOP_LOSS = False
EXCEPTIONAL_STOP_LOSS_THRESHOLD = 0.15
MAX_TAKE_PROFIT_ACTIONS_PER_RUN = 2
MAX_MONITOR_HISTORY_ENTRIES = 24
PENDING_OPEN_ORDER_GRACE_SECONDS = 20 * 60
SUCCESS_DISPATCH_COOLDOWN_SECONDS = 15 * 60
FAILED_DISPATCH_RETRY_SECONDS = 2 * 60

PHONE_SSH = [
    'ssh',
    '-p',
    '2222',
    '-o',
    'BatchMode=yes',
    '-o',
    'StrictHostKeyChecking=no',
    '-o',
    'ConnectTimeout=15',
    'u0_a647@localhost',
]
PHONE_MONITOR_CMD = (
    "bash -lc 'cd ~/beecthor-summary && "
    "git pull --ff-only >/dev/null 2>&1 || true; "
    "nohup python3 phone/polymarket_monitor_executor.py "
    ">> ~/polymarket_monitor_executor.log 2>&1 </dev/null &'"
)


def send_telegram(token: str, chat_id: str, text: str) -> None:
    if not token or not chat_id:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text},
            timeout=15,
        )
    except Exception as exc:
        print(f'[monitor] Telegram error: {exc}')


def load_dispatch_state() -> dict[str, dict[str, Any]]:
    state = load_json(MONITOR_DISPATCH_STATE_PATH, {})
    return state if isinstance(state, dict) else {}


def monitor_action_key(action: dict[str, object]) -> str:
    return f'{action.get("market_slug", "")}::{action.get("outcome", "")}::{action.get("action", "")}'


def should_dispatch(action: dict[str, object], dispatch_state: dict[str, dict[str, Any]]) -> tuple[bool, str]:
    state = dispatch_state.get(monitor_action_key(action), {})
    last_attempt = int(safe_float(state.get('last_attempt_ts'), 0))
    if not last_attempt:
        return True, 'fresh_trigger'

    elapsed = max(0, int(time.time()) - last_attempt)
    last_status = str(state.get('last_status') or 'unknown')
    retry_after = SUCCESS_DISPATCH_COOLDOWN_SECONDS if last_status == 'success' else FAILED_DISPATCH_RETRY_SECONDS
    if elapsed < retry_after:
        return False, f'cooldown_active:{retry_after - elapsed}s'
    return True, 'cooldown_elapsed'


def update_dispatch_state(
    actions: list[dict[str, object]],
    dispatch_state: dict[str, dict[str, Any]],
    *,
    status: str,
    detail: str,
) -> None:
    now_ts = int(time.time())
    for action in actions:
        dispatch_state[monitor_action_key(action)] = {
            'last_attempt_ts': now_ts,
            'last_status': status,
            'detail': detail[:500],
            'updated_at': now_utc(),
            'prob': safe_float(action.get('prob')),
        }
    save_json(MONITOR_DISPATCH_STATE_PATH, dispatch_state)


def fetch_sell_book(token_id: str) -> tuple[list[tuple[float, float]], dict[str, object]]:
    details: dict[str, object] = {
        'token_id': token_id,
        'book_best_bid': None,
        'top_bid_size': None,
        'bid_depth_top5': 0.0,
        'collector_error': '',
    }
    if not token_id:
        details['collector_error'] = 'missing_token_id'
        return [], details

    try:
        resp = requests.get(f'{CLOB_HOST}/book', params={'token_id': token_id}, timeout=15)
        if resp.status_code == 404:
            details['collector_error'] = 'order_book_not_found'
            return [], details
        resp.raise_for_status()
        book = resp.json()
    except Exception as exc:
        details['collector_error'] = str(exc)[:240]
        return [], details

    bids: list[tuple[float, float]] = []
    for level in book.get('bids', []):
        price = safe_float(level.get('price'), -1)
        size = safe_float(level.get('size'), 0)
        if price >= 0 and size > 0:
            bids.append((price, size))
    bids.sort(key=lambda item: item[0], reverse=True)

    if bids:
        details['book_best_bid'] = bids[0][0]
        details['top_bid_size'] = bids[0][1]
        details['bid_depth_top5'] = round(sum(size for _, size in bids[:5]), 6)
    return bids, details


def executable_sell_price_from_bids(bids: list[tuple[float, float]], amount: float) -> float | None:
    if amount <= 0:
        return None
    filled = 0.0
    for price, size in bids:
        filled += size
        if filled >= amount:
            return price
    return None


def trigger_phone_monitor_executor() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            PHONE_SSH + [PHONE_MONITOR_CMD],
            capture_output=True,
            text=True,
            timeout=25,
        )
    except subprocess.TimeoutExpired:
        return False, 'phone_trigger_timeout'
    except Exception as exc:
        return False, f'phone_trigger_exception: {exc}'

    stdout = (result.stdout or '').strip()
    stderr = (result.stderr or '').strip()
    if result.returncode != 0:
        detail = stderr or stdout or f'ssh exit {result.returncode}'
        return False, detail
    return True, stdout or 'phone_monitor_executor_started'


def summarize_open_position(position: dict[str, Any]) -> dict[str, object]:
    current_price = safe_float(position.get('cur_price'))
    size = safe_float(position.get('size'))
    current_value = safe_float(position.get('current_value'))
    if current_value <= 0.0:
        current_value = current_price * size
    return {
        'market_slug': position.get('market_slug', ''),
        'market_title': position.get('market_title') or position.get('market_slug', ''),
        'outcome': position.get('outcome', ''),
        'prob': current_price,
        'shares': size,
        'value_usd': round(current_value, 6),
        'pnl_usd': round(safe_float(position.get('cash_pnl')), 6),
    }


def append_monitor_history(entry: dict[str, object]) -> None:
    history = load_json(MONITOR_HISTORY_PATH, [])
    if not isinstance(history, list):
        history = []
    history.append(entry)
    save_json(MONITOR_HISTORY_PATH, history[-MAX_MONITOR_HISTORY_ENTRIES:])


def parse_utc_timestamp(value: object) -> float:
    if not value:
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def order_timestamp(order: dict[str, Any]) -> float:
    for key in ('created_at', 'timestamp', 'order_id'):
        parsed = parse_utc_timestamp(order.get(key))
        if parsed:
            return parsed
    return 0.0


def has_recent_pending_open_order() -> tuple[bool, dict[str, object]]:
    queue = load_json(PENDING_ORDERS_PATH, [])
    if not isinstance(queue, list):
        return False, {'pending_open_order_count': 0}

    now_ts = datetime.now(timezone.utc).timestamp()
    pending_open_orders: list[dict[str, Any]] = []
    for order in queue:
        if not isinstance(order, dict):
            continue
        if order.get('type') != 'OPEN_POSITION':
            continue
        if order.get('status') != 'pending_phone_execution':
            continue
        pending_open_orders.append(order)

    recent_orders = []
    for order in pending_open_orders:
        created_ts = order_timestamp(order)
        age_seconds = max(0, int(now_ts - created_ts)) if created_ts else None
        if age_seconds is None or age_seconds <= PENDING_OPEN_ORDER_GRACE_SECONDS:
            recent_orders.append(
                {
                    'order_id': order.get('order_id', ''),
                    'market_slug': order.get('market_slug', ''),
                    'age_seconds': age_seconds,
                }
            )

    return bool(recent_orders), {
        'pending_open_order_count': len(pending_open_orders),
        'recent_pending_open_order_count': len(recent_orders),
        'recent_pending_open_orders': recent_orders[:3],
        'grace_seconds': PENDING_OPEN_ORDER_GRACE_SECONDS,
    }


def systemd_available() -> bool:
    if os.environ.get('POLYMARKET_MONITOR_SELF_MANAGE', '1') == '0':
        return False
    return os.name == 'posix' and Path('/run/systemd/system').exists()


def deactivate_monitor_timer(reason: str) -> dict[str, object]:
    if not systemd_available():
        print(f'[monitor] Timer self-management skipped: {reason}')
        return {'attempted': False, 'reason': reason}

    result = subprocess.run(
        ['systemctl', 'disable', '--now', MONITOR_TIMER_NAME],
        capture_output=True,
        text=True,
        timeout=20,
    )
    detail = (result.stderr or result.stdout or '').strip()
    if result.returncode == 0:
        print(f'[monitor] Disabled {MONITOR_TIMER_NAME}: {reason}')
        return {'attempted': True, 'success': True, 'timer': MONITOR_TIMER_NAME, 'reason': reason}

    print(f'[monitor] WARN: failed to disable {MONITOR_TIMER_NAME}: {detail}')
    return {
        'attempted': True,
        'success': False,
        'timer': MONITOR_TIMER_NAME,
        'reason': reason,
        'detail': detail[:500],
    }


def main() -> None:
    print(f'[monitor] Starting at {now_utc()}')

    config = load_env()
    required = ['POLY_FUNDER']
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise SystemExit(f'Missing required config: {missing}')

    telegram_token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
    telegram_chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
    dispatch_state = load_dispatch_state()

    positions = fetch_positions(config)
    open_positions_snapshot = [summarize_open_position(position) for position in positions]
    history_entry: dict[str, object] = {
        'timestamp': now_utc(),
        'status': 'started',
        'open_position_count': len(open_positions_snapshot),
        'open_positions': open_positions_snapshot,
        'action_count': 0,
        'eligible_action_count': 0,
        'skipped_actions': [],
        'actions': [],
    }
    if not positions:
        print('[monitor] No open positions.')
        has_recent_pending, pending_detail = has_recent_pending_open_order()
        history_entry['pending_open_order_guard'] = pending_detail
        if has_recent_pending:
            history_entry['status'] = 'no_open_positions_pending_open_order'
            print('[monitor] Recent pending OPEN_POSITION order found; keeping timer active.')
        else:
            history_entry['status'] = 'no_open_positions'
            history_entry['timer_action'] = deactivate_monitor_timer('no_open_positions')
        save_json(MONITOR_ACTION_PATH, history_entry)
        append_monitor_history(history_entry)
        return

    monitor_actions: list[dict[str, object]] = []
    skipped_actions: list[dict[str, object]] = []
    candidates: list[tuple[int, float, dict[str, Any], str, float, dict[str, object]]] = []
    for pos in positions:
        prob = safe_float(pos.get('cur_price'))
        size = safe_float(pos.get('size'))
        token_id = str(pos.get('asset', ''))
        bids, book_details = fetch_sell_book(token_id)
        full_sell_price = executable_sell_price_from_bids(bids, size)
        book_details.update(
            {
                'full_executable_sell_price': full_sell_price,
            }
        )

        if full_sell_price is not None and full_sell_price >= TAKE_PROFIT_THRESHOLD:
            candidates.append((0, full_sell_price, pos, 'TAKE_PROFIT', 1.0, book_details))
        else:
            visible_trigger = prob >= TAKE_PROFIT_THRESHOLD
            if visible_trigger:
                skipped_actions.append(
                    {
                        'market_slug': str(pos.get('market_slug', '')),
                        'outcome': str(pos.get('outcome', '')),
                        'reason': 'book_executable_price_below_exit_threshold',
                        'visible_probability': round(prob, 6),
                        **book_details,
                    }
                )

        if (
            ENABLE_EXCEPTIONAL_STOP_LOSS
            and 0 < prob <= EXCEPTIONAL_STOP_LOSS_THRESHOLD
            and safe_float(pos.get('current_value')) >= 0.05
        ):
            candidates.append((2, prob, pos, 'EXCEPTIONAL_STOP_LOSS', 1.0, book_details))
    candidates.sort(key=lambda item: (item[0], -item[1]))

    for _, executable_sell_price, pos, action, fraction, book_details in candidates[:MAX_TAKE_PROFIT_ACTIONS_PER_RUN]:
        prob = safe_float(pos.get('cur_price'))
        market_slug = pos['market_slug']
        outcome = pos['outcome']
        title = pos.get('market_title', market_slug)
        threshold = TAKE_PROFIT_THRESHOLD

        print(
            f'[monitor] {action}: {market_slug} | {outcome} @ {prob:.1%} | '
            f'book_sell={executable_sell_price:.1%} | sell_fraction={fraction:.0%}'
        )
        monitor_actions.append(
            {
                'timestamp': now_utc(),
                'action': action,
                'status': 'phone_evaluation_requested',
                'market_slug': market_slug,
                'market_title': title,
                'outcome': outcome,
                'prob': prob,
                'sell_fraction': fraction,
                'minimum_book_sell_price': threshold,
                'book_sell_price': executable_sell_price,
                'book_best_bid': book_details.get('book_best_bid'),
                'top_bid_size': book_details.get('top_bid_size'),
                'bid_depth_top5': book_details.get('bid_depth_top5'),
            }
        )

    if not monitor_actions:
        print('[monitor] No exit trigger in live positions.')
        history_entry['status'] = 'no_trigger'
        history_entry['skipped_actions'] = skipped_actions
        save_json(MONITOR_ACTION_PATH, history_entry)
        append_monitor_history(history_entry)
        return

    eligible_actions: list[dict[str, object]] = []
    for action in monitor_actions:
        should_run, reason = should_dispatch(action, dispatch_state)
        if should_run:
            eligible_actions.append(action)
        else:
            skipped_actions.append(
                {
                    'market_slug': str(action['market_slug']),
                    'outcome': str(action['outcome']),
                    'reason': reason,
                }
            )

    payload: dict[str, object] = {
        'timestamp': now_utc(),
        'status': 'trigger_detected',
        'open_position_count': len(open_positions_snapshot),
        'open_positions': open_positions_snapshot,
        'action_count': len(monitor_actions),
        'actions': monitor_actions,
        'eligible_action_count': len(eligible_actions),
        'skipped_actions': skipped_actions,
    }
    payload.update(monitor_actions[0])
    save_json(MONITOR_ACTION_PATH, payload)

    if not eligible_actions:
        print('[monitor] Trigger present, but all actions are in cooldown.')
        payload['status'] = 'cooldown'
        save_json(MONITOR_ACTION_PATH, payload)
        append_monitor_history(payload)
        return

    dispatch_ok, dispatch_detail = trigger_phone_monitor_executor()
    update_dispatch_state(
        eligible_actions,
        dispatch_state,
        status='success' if dispatch_ok else 'failed',
        detail=dispatch_detail,
    )

    summary_slug = str(eligible_actions[0]['market_slug'])
    if len(eligible_actions) > 1:
        summary_slug = f'{summary_slug} +{len(eligible_actions) - 1}'

    if dispatch_ok:
        payload['status'] = 'phone_triggered'
        payload['dispatch_detail'] = dispatch_detail
        print(f'[monitor] Phone executor triggered: {summary_slug} ({dispatch_detail})')
        first_action = eligible_actions[0]
        book_sell_price = safe_float(first_action.get('book_sell_price'))
        price_line = f'\nbook_sell={book_sell_price:.0%}' if book_sell_price else ''
        sell_fraction = safe_float(first_action.get('sell_fraction'), 1.0)
        phone_instruction = (
            f'Phone asked to re-check live book and sell {sell_fraction:.0%} only if still viable.'
        )
        send_telegram(
            telegram_token,
            telegram_chat_id,
            f'\U0001f514 MONITOR EXIT\n{summary_slug}{price_line}\n{phone_instruction}',
        )
    else:
        payload['status'] = 'trigger_failed'
        payload['dispatch_detail'] = dispatch_detail
        print(f'[monitor] WARN: phone trigger failed for {summary_slug}: {dispatch_detail}')
        send_telegram(
            telegram_token,
            telegram_chat_id,
            f'\u26a0\ufe0f MONITOR EXIT trigger failed\n{summary_slug}\n{dispatch_detail}',
        )

    save_json(MONITOR_ACTION_PATH, payload)
    append_monitor_history(payload)
    print(f'[monitor] Done at {now_utc()}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[monitor] Exception: {exc}', file=sys.stderr)
        sys.exit(1)
