#!/usr/bin/env python3
"""
Polymarket Position Monitor

Runs every 2 hours (odd UTC hours) via systemd timer.
No GPT/Copilot — hard-coded thresholds only:
  - Stop-loss:  cur_price <= 0.20
  - Take-profit: cur_price >= 0.88

On trigger: updates conditional token allowance on-chain (no geoblock),
signs a SELL order, writes last_monitor_action.json, commits to GitHub,
and sends a Telegram notification. The phone executor picks it up 5 min later.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import requests
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import SELL

# Reuse utilities from run_cycle in the same package
from polymarket_assistant.run_cycle import (
    ASSISTANT_DIR,
    REPO_ROOT,
    build_private_client,
    fetch_positions,
    load_env,
    now_utc,
    safe_float,
    save_json,
)

MONITOR_ACTION_PATH = ASSISTANT_DIR / 'last_monitor_action.json'

STOP_LOSS_THRESHOLD = 0.20
TAKE_PROFIT_THRESHOLD = 0.88


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


def git_commit_and_push(action: str, market_slug: str) -> None:
    files = [str(MONITOR_ACTION_PATH)]
    subprocess.run(['git', '-C', str(REPO_ROOT), 'add'] + files, capture_output=True)
    if subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'diff', '--staged', '--quiet'],
        capture_output=True,
    ).returncode == 0:
        return
    subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'config', 'user.name', 'polymarket-operator[bot]'],
        capture_output=True,
    )
    subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'config', 'user.email', 'polymarket-operator[bot]@users.noreply.github.com'],
        capture_output=True,
    )
    subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'commit', '-m', f'monitor: {action} ({market_slug})'],
        capture_output=True,
    )
    result = subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'push', 'origin', 'main'],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f'[monitor] WARN: git push failed: {result.stderr.decode()}')
    else:
        print(f'[monitor] Committed and pushed: {action} ({market_slug})')


def main() -> None:
    print(f'[monitor] Starting at {now_utc()}')

    config = load_env()
    required = ['POLY_PRIVATE_KEY', 'POLY_FUNDER', 'POLY_SIGNATURE_TYPE']
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise SystemExit(f'Missing required config: {missing}')

    client = build_private_client(config)
    telegram_token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
    telegram_chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')

    positions = fetch_positions(config)
    if not positions:
        print('[monitor] No open positions.')
        return

    for pos in positions:
        prob = safe_float(pos.get('cur_price'))
        if prob <= STOP_LOSS_THRESHOLD:
            action = 'STOP_LOSS'
        elif prob >= TAKE_PROFIT_THRESHOLD:
            action = 'TAKE_PROFIT'
        else:
            continue

        market_slug = pos['market_slug']
        outcome = pos['outcome']
        size = safe_float(pos['size'])
        title = pos.get('market_title', market_slug)

        print(f'[monitor] {action}: {market_slug} | {outcome} @ {prob:.1%} | size={size:.4f}')

        # Update conditional allowance on-chain (Polygon tx, no geoblock)
        try:
            client.update_balance_allowance(BalanceAllowanceParams(
                asset_type=AssetType.CONDITIONAL,
                token_id=pos['asset'],
                signature_type=int(client.signer._signature_type),
            ))
            print(f'[monitor] Conditional allowance updated for {pos["asset"][:16]}...')
        except Exception as exc:
            print(f'[monitor] WARN: allowance update failed: {exc}')

        # Sign SELL order
        signed_order = client.create_market_order(MarketOrderArgs(
            token_id=pos['asset'],
            amount=size,
            side=SELL,
            order_type=OrderType.FOK,
        ))
        try:
            order_dict = signed_order.model_dump()
        except AttributeError:
            order_dict = signed_order.dict()

        order_payload = json.dumps({'order': order_dict, 'orderType': 'FOK'}, ensure_ascii=False)

        monitor_action = {
            'timestamp': now_utc(),
            'action': action,
            'status': 'pending_phone_execution',
            'market_slug': market_slug,
            'market_title': title,
            'outcome': outcome,
            'prob': prob,
            'amount': size,
            'order_payload': order_payload,
        }
        save_json(MONITOR_ACTION_PATH, monitor_action)

        send_telegram(
            telegram_token,
            telegram_chat_id,
            f'\U0001f514 MONITOR {action}\n{title}\n{outcome} @ {prob:.0%} | size={size:.4f}',
        )

        git_commit_and_push(action, market_slug)

        # One action per run to avoid race conditions
        break

    print(f'[monitor] Done at {now_utc()}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[monitor] Exception: {exc}', file=sys.stderr)
        sys.exit(1)
