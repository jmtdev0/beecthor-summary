#!/usr/bin/env python3
"""
Tiny HTTP log client for the private dashboard API.

The phone scripts can POST small structured events to the server so the
dashboard can show what happened without scraping stdout files.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ENV_FILE = Path.home() / '.polymarket.env'
load_dotenv(ENV_FILE)

LOG_API_URL = os.environ.get('SERVER_LOG_API_URL', '').strip()
LOG_API_SECRET = os.environ.get('SERVER_LOG_API_SECRET', '').strip()


def refresh_log_client_config() -> None:
    global LOG_API_URL
    global LOG_API_SECRET

    LOG_API_URL = os.environ.get('SERVER_LOG_API_URL', '').strip()
    LOG_API_SECRET = os.environ.get('SERVER_LOG_API_SECRET', '').strip()


def send_server_log(
    source: str,
    event_type: str,
    message: str,
    *,
    level: str = 'info',
    payload: dict[str, Any] | None = None,
) -> bool:
    if not LOG_API_URL or not LOG_API_SECRET:
        return False

    body = {
        'timestamp': datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'source': source,
        'event_type': event_type,
        'level': level,
        'message': message,
        'payload': payload or {},
        'secret': LOG_API_SECRET,
    }

    try:
        response = requests.post(LOG_API_URL, json=body, timeout=10)
        response.raise_for_status()
        return bool(response.json().get('ok'))
    except Exception:
        return False
