#!/usr/bin/env python3
"""
Polymarket Position Monitor

Runs every minute on the server via systemd timer.
No GPT/Copilot — hard-coded thresholds only:
  - Take-profit: cur_price >= 0.90

On trigger: stores a local snapshot of the candidate actions, then attempts to
launch the phone monitor executor immediately through the reverse SSH tunnel.
This keeps detection on the server while preserving residential-IP execution on
the phone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

import requests

from polymarket_assistant.run_cycle import (
    ASSISTANT_DIR,
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

PARTIAL_TAKE_PROFIT_THRESHOLD = 0.80
TAKE_PROFIT_THRESHOLD = 0.90
EXCEPTIONAL_STOP_LOSS_THRESHOLD = 0.15
MAX_TAKE_PROFIT_ACTIONS_PER_RUN = 2
MAX_MONITOR_HISTORY_ENTRIES = 24
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
    if action.get('action') == 'PARTIAL_TAKE_PROFIT' and last_status == 'success':
        return False, 'partial_take_profit_already_dispatched'
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
        history_entry['status'] = 'no_open_positions'
        save_json(MONITOR_ACTION_PATH, history_entry)
        append_monitor_history(history_entry)
        return

    monitor_actions: list[dict[str, object]] = []
    candidates: list[tuple[int, dict[str, Any], str, float]] = []
    for pos in positions:
        prob = safe_float(pos.get('cur_price'))
        if prob >= TAKE_PROFIT_THRESHOLD:
            candidates.append((0, pos, 'TAKE_PROFIT', 1.0))
        elif prob >= PARTIAL_TAKE_PROFIT_THRESHOLD:
            candidates.append((1, pos, 'PARTIAL_TAKE_PROFIT', 0.5))
        elif 0 < prob <= EXCEPTIONAL_STOP_LOSS_THRESHOLD and safe_float(pos.get('current_value')) >= 0.05:
            candidates.append((2, pos, 'EXCEPTIONAL_STOP_LOSS', 1.0))
    candidates.sort(key=lambda item: (item[0], -safe_float(item[1].get('cur_price'))))

    for _, pos, action, fraction in candidates[:MAX_TAKE_PROFIT_ACTIONS_PER_RUN]:
        prob = safe_float(pos.get('cur_price'))
        market_slug = pos['market_slug']
        outcome = pos['outcome']
        size = safe_float(pos['size'])
        amount = size * fraction
        title = pos.get('market_title', market_slug)

        print(f'[monitor] {action}: {market_slug} | {outcome} @ {prob:.1%} | amount={amount:.4f}')
        monitor_actions.append(
            {
                'timestamp': now_utc(),
                'action': action,
                'status': 'pending_phone_execution',
                'market_slug': market_slug,
                'market_title': title,
                'outcome': outcome,
                'prob': prob,
                'token_id': pos['asset'],
                'side': 'SELL',
                'amount': amount,
                'fraction': fraction,
            }
        )

    if not monitor_actions:
        print('[monitor] No exit trigger in live positions.')
        history_entry['status'] = 'no_trigger'
        save_json(MONITOR_ACTION_PATH, history_entry)
        append_monitor_history(history_entry)
        return

    eligible_actions: list[dict[str, object]] = []
    skipped_actions: list[dict[str, str]] = []
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
        send_telegram(
            telegram_token,
            telegram_chat_id,
            f'\U0001f514 MONITOR EXIT\n{summary_slug}\nPhone executor triggered via tunnel.',
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
