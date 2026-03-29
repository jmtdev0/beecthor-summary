#!/usr/bin/env python3
"""
Polymarket Phone Executor

Runs 5 minutes after each server cycle (cron: 01:05, 07:35, 13:35, 20:05 UTC).
Reads the pending signed order from last_run_summary.json in the GitHub repo
and executes it via the Polymarket CLOB API using the phone's residential IP.

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
LAST_EXECUTED_FILE = Path.home() / '.polymarket_last_executed_ts'
CLOB_HOST = 'https://clob.polymarket.com'
ORDER_PATH = '/order'
# Use GitHub Contents API to bypass CDN caching on raw.githubusercontent.com
SUMMARY_API_URL = (
    'https://api.github.com/repos/jmtdev0/beecthor-summary/contents'
    '/polymarket_assistant/last_run_summary.json'
)

load_dotenv(ENV_FILE)

TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
POLY_API_SECRET = os.environ.get('POLY_API_SECRET', '')
POLY_API_PASSPHRASE = os.environ.get('POLY_API_PASSPHRASE', '')
POLY_FUNDER = os.environ.get('POLY_FUNDER', '')
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
    print(f'[executor] {ts}')

    missing = [v for v in ('POLY_API_KEY', 'POLY_API_SECRET', 'POLY_API_PASSPHRASE', 'POLY_FUNDER', 'POLY_SIGNER_ADDRESS')
               if not os.environ.get(v)]
    if missing:
        print(f'[executor] Missing env vars: {missing}. Check {ENV_FILE}')
        sys.exit(1)

    # Fetch latest run summary via GitHub Contents API (bypasses CDN cache)
    resp = requests.get(SUMMARY_API_URL, timeout=15, headers={'Cache-Control': 'no-cache'})
    resp.raise_for_status()
    summary = json.loads(base64.b64decode(resp.json()['content']))

    execution = summary.get('execution', {})
    details = execution.get('details') or {}

    if details.get('status') != 'pending_phone_execution':
        print(f'[executor] No pending order. Last action: {summary.get("decision", {}).get("action")}')
        return

    order_payload = details.get('order_payload')
    if not order_payload:
        print('[executor] pending_phone_execution but no order_payload found.')
        return

    order_ts = summary.get('timestamp', '')
    if order_ts == get_last_executed_ts():
        print(f'[executor] Order at {order_ts} already executed. Nothing to do.')
        return

    # Fields differ between OPEN (market/stake_usd) and CLOSE/REDUCE (market_slug/amount/type)
    order_type = details.get('type', 'OPEN_POSITION')
    market = details.get('market') or details.get('market_slug', '')
    outcome = details.get('outcome', '')
    stake = details.get('stake_usd') or details.get('amount', '')
    print(f'[executor] Pending order: {order_type} {outcome} on "{market}" size={stake}')
    print(f'[executor] Order timestamp: {order_ts}')

    # Reconstruct the full POST body (add 'owner' from local .env)
    partial = json.loads(order_payload)
    body = {
        'order': partial['order'],
        'owner': POLY_API_KEY,
        'orderType': partial.get('orderType', 'FOK'),
        'postOnly': False,
    }
    body_str = json.dumps(body, separators=(',', ':'), ensure_ascii=False)

    headers = build_l2_headers('POST', ORDER_PATH, body_str)

    print('[executor] Posting order to Polymarket CLOB...')
    resp = requests.post(
        f'{CLOB_HOST}{ORDER_PATH}',
        headers=headers,
        data=body_str.encode('utf-8'),
        timeout=30,
    )

    if resp.ok:
        print(f'[executor] SUCCESS: {resp.text}')
        save_last_executed_ts(order_ts)
        send_telegram(f'\u2705 Order executed from phone:\n{order_type} {outcome}\n{market} size={stake}')
    else:
        print(f'[executor] FAILED {resp.status_code}: {resp.text}')
        send_telegram(f'\u274c Order failed from phone:\n{resp.status_code} {resp.text}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'[executor] Exception: {exc}')
        send_telegram(f'\u274c Exception in phone executor: {exc}')
