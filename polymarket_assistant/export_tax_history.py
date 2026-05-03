#!/usr/bin/env python3
"""Export Polymarket account activity for tax review.

The script uses the public Polymarket Data API with the proxy wallet address
from polymarket_assistant/.env. It does not use trading API credentials.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


DATA_API_HOST = 'https://data-api.polymarket.com'
POLYGONSCAN_TX_URL = 'https://polygonscan.com/tx/'
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / 'polymarket_assistant' / '.env'
EXPORT_ROOT = REPO_ROOT / 'polymarket_assistant' / 'tax_exports'


def load_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def utc_from_timestamp(value: Any) -> str:
    try:
        return datetime.fromtimestamp(int(value), UTC).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError, OSError):
        return ''


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def fetch_paginated(endpoint: str, user: str, *, limit: int, max_offset: int = 10000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset <= max_offset:
        response = requests.get(
            f'{DATA_API_HOST}/{endpoint}',
            params={'user': user, 'limit': limit, 'offset': offset},
            timeout=30,
        )
        response.raise_for_status()
        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return rows


def filter_by_year(rows: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    start = int(datetime(year, 1, 1, tzinfo=UTC).timestamp())
    end = int(datetime(year + 1, 1, 1, tzinfo=UTC).timestamp())
    filtered = []
    for row in rows:
        try:
            ts = int(row.get('timestamp'))
        except (TypeError, ValueError):
            continue
        if start <= ts < end:
            filtered.append(row)
    return filtered


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def normalize_activity(row: dict[str, Any]) -> dict[str, Any]:
    tx_hash = row.get('transactionHash') or ''
    return {
        'timestamp_utc': utc_from_timestamp(row.get('timestamp')),
        'timestamp_unix': row.get('timestamp', ''),
        'type': row.get('type', ''),
        'side': row.get('side', ''),
        'market_title': row.get('title', ''),
        'market_slug': row.get('slug', ''),
        'event_slug': row.get('eventSlug', ''),
        'outcome': row.get('outcome', ''),
        'asset': row.get('asset', ''),
        'condition_id': row.get('conditionId', ''),
        'size_shares': row.get('size', ''),
        'price_usdc': row.get('price', ''),
        'cash_amount_usdc': row.get('usdcSize', ''),
        'transaction_hash': tx_hash,
        'polygonscan_url': f'{POLYGONSCAN_TX_URL}{tx_hash}' if tx_hash else '',
    }


def normalize_closed_position(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'timestamp_utc': utc_from_timestamp(row.get('timestamp')),
        'timestamp_unix': row.get('timestamp', ''),
        'market_title': row.get('title', ''),
        'market_slug': row.get('slug', ''),
        'event_slug': row.get('eventSlug', ''),
        'outcome': row.get('outcome', ''),
        'asset': row.get('asset', ''),
        'condition_id': row.get('conditionId', ''),
        'avg_price_usdc': row.get('avgPrice', ''),
        'total_bought_usdc': row.get('totalBought', ''),
        'realized_pnl_usdc': row.get('realizedPnl', ''),
        'current_price_usdc': row.get('curPrice', ''),
        'end_date': row.get('endDate', ''),
    }


def normalize_open_position(row: dict[str, Any]) -> dict[str, Any]:
    return {
        'market_title': row.get('title', ''),
        'market_slug': row.get('slug', ''),
        'event_slug': row.get('eventSlug', ''),
        'outcome': row.get('outcome', ''),
        'asset': row.get('asset', ''),
        'condition_id': row.get('conditionId', ''),
        'size_shares': row.get('size', ''),
        'avg_price_usdc': row.get('avgPrice', ''),
        'initial_value_usdc': row.get('initialValue', ''),
        'current_value_usdc': row.get('currentValue', ''),
        'cash_pnl_usdc': row.get('cashPnl', ''),
        'realized_pnl_usdc': row.get('realizedPnl', ''),
        'current_price_usdc': row.get('curPrice', ''),
        'redeemable': row.get('redeemable', ''),
        'mergeable': row.get('mergeable', ''),
        'end_date': row.get('endDate', ''),
    }


def summarize(activity_rows: list[dict[str, Any]], closed_rows: list[dict[str, Any]], open_rows: list[dict[str, Any]]) -> dict[str, Any]:
    activity_by_type = Counter(row.get('type', '') for row in activity_rows)
    trades = [row for row in activity_rows if row.get('type') == 'TRADE']
    buy_cash = sum(safe_float(row.get('cash_amount_usdc')) for row in trades if row.get('side') == 'BUY')
    sell_cash = sum(safe_float(row.get('cash_amount_usdc')) for row in trades if row.get('side') == 'SELL')
    realized_pnl = sum(safe_float(row.get('realized_pnl_usdc')) for row in closed_rows)
    open_value = sum(safe_float(row.get('current_value_usdc')) for row in open_rows)
    open_cash_pnl = sum(safe_float(row.get('cash_pnl_usdc')) for row in open_rows)
    return {
        'generated_at_utc': datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'activity_count': len(activity_rows),
        'activity_by_type': dict(sorted(activity_by_type.items())),
        'trade_count': len(trades),
        'buy_cash_usdc': round(buy_cash, 6),
        'sell_cash_usdc': round(sell_cash, 6),
        'closed_position_count': len(closed_rows),
        'closed_positions_realized_pnl_usdc': round(realized_pnl, 6),
        'open_position_count': len(open_rows),
        'open_positions_current_value_usdc': round(open_value, 6),
        'open_positions_unrealized_pnl_usdc': round(open_cash_pnl, 6),
    }


def main() -> None:
    env = load_env_values(ENV_PATH)
    user = env.get('POLY_FUNDER') or env.get('POLY_SIGNER_ADDRESS')
    if not user:
        raise SystemExit('POLY_FUNDER/POLY_SIGNER_ADDRESS not found in polymarket_assistant/.env')

    year = datetime.now(UTC).year
    output_dir = EXPORT_ROOT / str(year)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_activity = filter_by_year(fetch_paginated('activity', user, limit=500), year)
    raw_closed = filter_by_year(fetch_paginated('closed-positions', user, limit=50), year)
    open_positions_response = requests.get(
        f'{DATA_API_HOST}/positions',
        params={'user': user, 'sizeThreshold': 0.01, 'limit': 500, 'offset': 0},
        timeout=30,
    )
    open_positions_response.raise_for_status()
    raw_open = open_positions_response.json()
    if not isinstance(raw_open, list):
        raw_open = []

    activity = [normalize_activity(row) for row in raw_activity]
    closed_positions = [normalize_closed_position(row) for row in raw_closed]
    open_positions = [normalize_open_position(row) for row in raw_open]
    summary = summarize(activity, closed_positions, open_positions)
    summary['tax_year'] = year
    summary['public_wallet_tail'] = user[-8:]

    write_json(output_dir / 'activity_raw.json', raw_activity)
    write_json(output_dir / 'closed_positions_raw.json', raw_closed)
    write_json(output_dir / 'open_positions_snapshot_raw.json', raw_open)
    write_json(output_dir / 'summary.json', summary)

    write_csv(
        output_dir / 'activity.csv',
        activity,
        [
            'timestamp_utc',
            'timestamp_unix',
            'type',
            'side',
            'market_title',
            'market_slug',
            'event_slug',
            'outcome',
            'asset',
            'condition_id',
            'size_shares',
            'price_usdc',
            'cash_amount_usdc',
            'transaction_hash',
            'polygonscan_url',
        ],
    )
    write_csv(
        output_dir / 'closed_positions.csv',
        closed_positions,
        [
            'timestamp_utc',
            'timestamp_unix',
            'market_title',
            'market_slug',
            'event_slug',
            'outcome',
            'asset',
            'condition_id',
            'avg_price_usdc',
            'total_bought_usdc',
            'realized_pnl_usdc',
            'current_price_usdc',
            'end_date',
        ],
    )
    write_csv(
        output_dir / 'open_positions_snapshot.csv',
        open_positions,
        [
            'market_title',
            'market_slug',
            'event_slug',
            'outcome',
            'asset',
            'condition_id',
            'size_shares',
            'avg_price_usdc',
            'initial_value_usdc',
            'current_value_usdc',
            'cash_pnl_usdc',
            'realized_pnl_usdc',
            'current_price_usdc',
            'redeemable',
            'mergeable',
            'end_date',
        ],
    )
    write_csv(output_dir / 'summary.csv', [summary], list(summary.keys()))

    print(json.dumps({'output_dir': str(output_dir), **summary}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
