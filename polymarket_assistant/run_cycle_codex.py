#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import run_cycle as base


def normalize_decision(decision: dict[str, Any]) -> dict[str, Any]:
    return base.normalize_decision(decision)


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith('```'):
        stripped = re.sub(r'^```(?:json)?', '', stripped).strip()
        stripped = re.sub(r'```$', '', stripped).strip()
    return normalize_decision(json.loads(stripped))


def run_copilot(prompt: str, model: str) -> dict[str, Any]:
    env = os.environ.copy()
    has_token = env.get('COPILOT_GITHUB_TOKEN') or env.get('GH_TOKEN') or env.get('GITHUB_TOKEN')
    has_gh_auth = subprocess.run(['gh', 'auth', 'status'], capture_output=True, env=env).returncode == 0
    if not has_token and not has_gh_auth:
        raise RuntimeError('No Copilot authentication found. Set COPILOT_GITHUB_TOKEN or run gh auth login')
    cmd = [
        'copilot',
        '--continue',
        '-p',
        prompt,
        '--model',
        model,
        '--effort=high',
        '-s',
        '--no-ask-user',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=240, check=True)
    return extract_json(result.stdout)


def load_decision_from_file(path: Path) -> dict[str, Any]:
    return normalize_decision(json.loads(path.read_text(encoding='utf-8')))


def is_automatic_fallback_decision(decision: dict[str, Any]) -> bool:
    if decision.get('action') != 'NO_ACTION':
        return False
    summary = (decision.get('summary') or '').strip()
    rationale = (decision.get('rationale') or '').strip()
    return (
        summary.startswith('Automatic Codex cycle fallback:')
        or rationale.startswith('Codex auto-cycle fallback:')
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='Run one unattended Polymarket operator cycle via Codex JSON decisions')
    parser.add_argument('--model', default='gpt-5.4')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--decision-file', help='Use a local JSON file instead of calling copilot')
    parser.add_argument(
        '--force-bet', nargs=4, metavar=('EVENT_DATE', 'STRIKE', 'OUTCOME', 'STAKE'),
        help='Bypass GPT and place a direct bet. Example: --force-bet march-27 69000 No 1.0',
    )
    args = parser.parse_args()

    subprocess.run(
        ['git', '-C', str(base.REPO_ROOT), 'pull', '--ff-only', 'origin', 'main'],
        capture_output=True, timeout=30,
    )

    config = base.load_env()
    required = [
        'POLY_PRIVATE_KEY',
        'POLY_FUNDER',
        'POLY_SIGNATURE_TYPE',
    ]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise SystemExit(f'Missing required Polymarket configuration: {", ".join(missing)}')

    if args.force_bet:
        event_date, strike_str, outcome, stake_str = args.force_bet
        base.force_bet(config, event_date, int(strike_str), outcome, float(stake_str))
        return

    context = base.build_context_snapshot(config)
    base.notify_claimable_positions(context['polymarket']['positions'], config)
    prompt = base.render_prompt(context)

    if args.decision_file:
        decision = load_decision_from_file(Path(args.decision_file))
    else:
        decision = run_copilot(prompt, args.model)
    decision = normalize_decision(decision)

    ok, message = base.validate_decision(decision, context)
    execution: dict[str, Any] = {'performed': False, 'details': None}
    positions_before = len(context['polymarket']['positions'])
    client = base.build_private_client(config)

    if ok and not args.dry_run and decision.get('action') != 'NO_ACTION':
        if decision['action'] == 'OPEN_POSITION':
            telegram_token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
            telegram_chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
            execution['details'] = []
            for open_target in base.iter_requested_open_targets(decision):
                order = base.prepare_open_order_via_phone(
                    open_target,
                    context['polymarket']['active_btc_markets'],
                    telegram_token,
                    telegram_chat_id,
                    context['binance']['spot_price'],
                )
                execution['details'].append(order)
            execution['performed'] = bool(execution['details'])
        elif decision['action'] in {'CLOSE_POSITION', 'REDUCE_POSITION'}:
            telegram_token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
            telegram_chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
            execution['details'] = []
            for management_target in base.iter_requested_management_targets(decision):
                order = base.prepare_position_management_via_phone(
                    decision['action'],
                    management_target,
                    context['polymarket']['positions'],
                    telegram_token,
                    telegram_chat_id,
                    context['binance']['spot_price'],
                )
                execution['details'].append(order)
            execution['performed'] = bool(execution['details'])
    elif not ok:
        execution['details'] = {'rejected': message}

    refreshed_positions = base.fetch_positions(config)
    refreshed_balance = base.fetch_balance_allowance(client, config)
    balance_usdc = base.safe_float(refreshed_balance.get('balance')) / 1_000_000
    account_state = base.sync_account_state(context['account_state'], balance_usdc, refreshed_positions)
    base.save_json(base.ACCOUNT_STATE_PATH, account_state)

    log_entry = {
        'timestamp': base.now_utc(),
        'type': 'cycle_run',
        'run_id': decision.get('run_id', ''),
        'dry_run': args.dry_run,
        'decision': decision,
        'validation': {'ok': ok, 'message': message},
        'execution': execution,
        'binance_spot_price': context['binance']['spot_price'],
        'positions_before': positions_before,
        'positions_after': len(refreshed_positions),
    }
    base.append_trade_log(log_entry)

    run_summary = {
        'timestamp': log_entry['timestamp'],
        'run_id': decision.get('run_id', ''),
        'dry_run': args.dry_run,
        'decision': decision,
        'validation': {'ok': ok, 'message': message},
        'execution': execution,
        'binance_spot_price': context['binance']['spot_price'],
        'positions_before': positions_before,
        'positions_after': len(refreshed_positions),
    }
    base.save_json(base.LAST_RUN_SUMMARY_PATH, run_summary)
    base.write_summary_markdown(run_summary)

    token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
    if token and chat_id and not args.dry_run and not is_automatic_fallback_decision(decision):
        action = decision.get('action', 'UNKNOWN')
        summary_text = decision.get('summary', '')
        btc = context['binance']['spot_price']
        action_emoji = {
            'NO_ACTION': '\U0001f7e1',
            'OPEN_POSITION': '\U0001f7e2',
            'CLOSE_POSITION': '\U0001f534',
            'REDUCE_POSITION': '\U0001f7e0',
        }.get(action, '\u2139\ufe0f')
        msg = f'{action_emoji} {action}\nBTC ${btc:,.0f}\n\n{summary_text}'
        try:
            base.requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': msg},
                timeout=15,
            )
        except Exception as exc:
            print(f'[telegram] Failed to send cycle summary: {exc}')
    elif is_automatic_fallback_decision(decision):
        print('[telegram] Skipping Telegram summary for automatic Codex fallback NO_ACTION.')

    print(json.dumps(run_summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(exc.stdout)
        print(exc.stderr, file=sys.stderr)
        raise
