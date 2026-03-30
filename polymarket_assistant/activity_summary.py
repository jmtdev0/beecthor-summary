#!/usr/bin/env python3
"""
Polymarket activity summary helper.

Fetches public account activity, open positions, and closed positions from the
Polymarket Data API, then prints a compact chronological summary.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import requests

DATA_API_HOST = 'https://data-api.polymarket.com'


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Summarize Polymarket account activity.')
    parser.add_argument('--user', required=True, help='Wallet address to inspect.')
    parser.add_argument('--limit', type=int, default=25, help='Max activity items to fetch.')
    parser.add_argument(
        '--json',
        action='store_true',
        help='Print raw fetched payloads as JSON instead of a formatted summary.',
    )
    return parser.parse_args()


def get_json(path: str, **params: Any) -> Any:
    response = requests.get(f'{DATA_API_HOST}{path}', params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_ts(value: Any) -> datetime | None:
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    value = str(value)
    try:
        if value.endswith('Z'):
            return datetime.fromisoformat(value.replace('Z', '+00:00'))
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fmt_ts(value: str) -> str:
    dt = parse_ts(value)
    if not dt:
        return value or '?'
    return dt.astimezone(UTC).strftime('%Y-%m-%d %H:%M UTC')


def summarize_activity_entry(entry: dict[str, Any]) -> str:
    kind = entry.get('type') or entry.get('activityType') or 'UNKNOWN'
    slug = entry.get('slug') or entry.get('marketSlug') or entry.get('eventSlug') or '?'
    outcome = entry.get('outcome') or '?'
    side = entry.get('side') or '?'
    size = to_float(entry.get('size'))
    price = to_float(entry.get('price'))
    usdc = to_float(entry.get('usdcSize') or entry.get('usdcAmount'))
    timestamp = entry.get('timestamp') or entry.get('createdAt') or ''
    details = [
        fmt_ts(timestamp),
        kind,
        side,
        outcome,
        f'size={size:.4f}' if size else None,
        f'price={price:.4f}' if price else None,
        f'usdc={usdc:.4f}' if usdc else None,
        slug,
    ]
    return ' | '.join(part for part in details if part)


def main() -> None:
    args = parse_args()

    activity = get_json('/activity', user=args.user, limit=args.limit, offset=0)
    positions = get_json('/positions', user=args.user, sizeThreshold=0.01, limit=100, offset=0)
    closed_positions = get_json('/closed-positions', user=args.user, limit=100, offset=0)

    if args.json:
        print(json.dumps({
            'activity': activity,
            'positions': positions,
            'closed_positions': closed_positions,
        }, indent=2, ensure_ascii=False))
        return

    print(f'User: {args.user}')
    print(f'Activity items fetched: {len(activity)}')
    print(f'Open positions: {len(positions)}')
    print(f'Closed positions: {len(closed_positions)}')

    if activity:
        counts = Counter(
            entry.get('type') or entry.get('activityType') or 'UNKNOWN'
            for entry in activity
            if isinstance(entry, dict)
        )
        print('Activity types:', ', '.join(f'{k}={v}' for k, v in counts.most_common()))
        print('')
        print('Recent activity:')
        for entry in activity:
            if isinstance(entry, dict):
                print(f'- {summarize_activity_entry(entry)}')

    if positions:
        print('')
        print('Open positions:')
        for pos in positions:
            slug = pos.get('slug') or '?'
            outcome = pos.get('outcome') or '?'
            size = to_float(pos.get('size'))
            cur_price = to_float(pos.get('curPrice'))
            pnl = to_float(pos.get('cashPnl'))
            print(
                f'- {slug} | {outcome} | size={size:.4f} | '
                f'cur_price={cur_price:.4f} | cash_pnl={pnl:.4f}'
            )

    if closed_positions:
        total_realized = sum(to_float(pos.get('realizedPnl')) for pos in closed_positions if isinstance(pos, dict))
        print('')
        print(f'Closed positions realized PnL: {total_realized:.4f}')
        print('Most recent closed positions:')
        closed_sorted = sorted(
            (pos for pos in closed_positions if isinstance(pos, dict)),
            key=lambda item: parse_ts(item.get('endDate') or item.get('timestamp') or '') or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[:10]
        for pos in closed_sorted:
            slug = pos.get('slug') or '?'
            outcome = pos.get('outcome') or '?'
            realized = to_float(pos.get('realizedPnl'))
            avg_price = to_float(pos.get('avgPrice'))
            print(f'- {slug} | {outcome} | avg={avg_price:.4f} | realized_pnl={realized:.4f}')


if __name__ == '__main__':
    main()
