#!/usr/bin/env python3
"""
Polymarket Monitor Phone Executor

Runs 5 minutes after each monitor check (cron: every odd UTC hour + 5min).
Reads the pending signed SELL order from last_monitor_action.json in the GitHub
repo and executes it via the Polymarket CLOB API using the phone's residential IP.

This script is the phone-side counterpart of polymarket_assistant/run_monitor.py.
It handles stop-loss and take-profit exits signed by the server.

Dependencies: requests, python-dotenv (no compilation required)
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_FILE = Path.home() / '.polymarket.env'
LAST_EXECUTED_FILE = Path.home() / '.polymarket_last_monitor_ts'
CLOB_HOST = 'https://clob.polymarket.com'
ORDER_PATH = '/order'
# Use GitHub Contents API to bypass CDN caching on raw.githubusercontent.com
MONITOR_API_URL = (
    'https://api.github.com/repos/jmtdev0/beecthor-summary/contents'
    '/polymarket_assistant/last_monitor_action.json'
)

load_dotenv(ENV_FILE)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
POLY_API_SECRET = os.environ.get('POLY_API_SECRET', '')
POLY_API_PASSPHRASE = os.environ.get('POLY_API_PASSPHRASE', '')
POLY_SIGNER_ADDRESS = os.environ.get('POLY_SIGNER_ADDRESS', '')


def build_l2_headers(method: str, path: str, body_str: str) -> dict:
    """Compute Polymarket L2 HMAC authentication headers using Python stdlib only."""
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


def main() -> None:
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    print(f'[monitor-executor] {ts}')

    missing = [v for v in ('POLY_API_KEY', 'POLY_API_SECRET', 'POLY_API_PASSPHRASE', 'POLY_SIGNER_ADDRESS')
               if not os.environ.get(v)]
    if missing:
        print(f'[monitor-executor] Missing env vars: {missing}. Check {ENV_FILE}')
        sys.exit(1)

    # Fetch latest monitor action via GitHub Contents API (bypasses CDN cache)
    resp = requests.get(MONITOR_API_URL, timeout=15, headers={'Cache-Control': 'no-cache'})
    if resp.status_code == 404:
        print('[monitor-executor] last_monitor_action.json not found — no monitor action yet.')
        return
    resp.raise_for_status()
    action_data = json.loads(base64.b64decode(resp.json()['content']))

    if action_data.get('status') != 'pending_phone_execution':
        print(f'[monitor-executor] No pending order. Status: {action_data.get("status")}')
        return

    order_payload = action_data.get('order_payload')
    if not order_payload:
        print('[monitor-executor] pending_phone_execution but no order_payload found.')
        return

    order_ts = action_data.get('timestamp', '')
    if order_ts == get_last_executed_ts():
        print(f'[monitor-executor] Order at {order_ts} already executed. Nothing to do.')
        return

    action = action_data.get('action', '')
    market_slug = action_data.get('market_slug', '')
    outcome = action_data.get('outcome', '')
    amount = action_data.get('amount', '')
    prob = action_data.get('prob', 0)
    print(f'[monitor-executor] Pending: {action} {outcome} on "{market_slug}" amount={amount} prob={prob:.1%}')
    print(f'[monitor-executor] Order timestamp: {order_ts}')

    # Reconstruct the full POST body (add 'owner' from local .env)
    partial = json.loads(order_payload)
    body = {
        'order': partial['order'],
        'owner': POLY_API_KEY,
        'orderType': partial.get('orderType', 'FOK'),
        'postOnly': False,
    }
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)

    max_attempts = 5
    retry_delay = 20  # seconds between attempts

    for attempt in range(1, max_attempts + 1):
        # Rebuild headers each attempt (timestamp in HMAC must be fresh)
        headers = build_l2_headers('POST', ORDER_PATH, body_str)
        print(f'[monitor-executor] Posting SELL order to Polymarket CLOB (attempt {attempt}/{max_attempts})...')
        resp = requests.post(
            f'{CLOB_HOST}{ORDER_PATH}',
            headers=headers,
            data=body_str.encode('utf-8'),
            timeout=30,
        )

        if resp.ok:
            print(f'[monitor-executor] SUCCESS: {resp.text}')
            save_last_executed_ts(order_ts)
            send_telegram(
                f'\u2705 {action} executed from phone:\n'
                f'{outcome} @ {prob:.0%}\n'
                f'{market_slug} sold {amount}'
            )
            return

        print(f'[monitor-executor] Attempt {attempt} FAILED {resp.status_code}: {resp.text}')
        if attempt < max_attempts:
            print(f'[monitor-executor] Retrying in {retry_delay}s...')
            time.sleep(retry_delay)

    send_telegram(f'\u274c Monitor order failed after {max_attempts} attempts ({action}):\n{resp.status_code} {resp.text}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[monitor-executor] Exception: {exc}')
        send_telegram(f'\u274c Exception in monitor executor: {exc}')
