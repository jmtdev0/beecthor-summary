#!/usr/bin/env python3
"""Import historical Polymarket collector JSONL snapshots into PostgreSQL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from polymarket_assistant.market_price_collector import (
    DEFAULT_OUTPUT_PATH,
    count_postgres_snapshots,
    insert_postgres_rows,
    marketdata_dsn,
)


def iter_jsonl(path: Path) -> tuple[int, int, list[dict[str, Any]]]:
    total_lines = 0
    bad_lines = 0
    rows: list[dict[str, Any]] = []
    with path.open('r', encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            total_lines += 1
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            if not isinstance(payload, dict):
                bad_lines += 1
                continue
            rows.append(payload)
    return total_lines, bad_lines, rows


def chunked(rows: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [rows[index : index + size] for index in range(0, len(rows), size)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Migrate market snapshot JSONL into PostgreSQL.')
    parser.add_argument('--input', type=Path, default=DEFAULT_OUTPUT_PATH, help='Source JSONL path.')
    parser.add_argument('--dsn', default='', help='PostgreSQL DSN. Defaults to POLYMARKET_MARKETDATA_DSN.')
    parser.add_argument('--batch-size', type=int, default=1000, help='Rows per INSERT batch.')
    parser.add_argument('--limit', type=int, default=0, help='Import at most N valid rows, for smoke tests.')
    parser.add_argument('--dry-run', action='store_true', help='Parse and summarize without inserting.')
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.input.exists():
        raise SystemExit(f'Input JSONL not found: {args.input}')

    total_lines, bad_lines, rows = iter_jsonl(args.input)
    if args.limit > 0:
        rows = rows[: args.limit]

    if args.dry_run:
        print(
            json.dumps(
                {
                    'input': str(args.input),
                    'total_lines': total_lines,
                    'valid_rows': len(rows),
                    'bad_lines': bad_lines,
                    'limited': args.limit > 0,
                    'sample': rows[:2],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    dsn = marketdata_dsn(args.dsn)
    before_count = count_postgres_snapshots(dsn)
    inserted = 0
    for batch in chunked(rows, args.batch_size):
        inserted += insert_postgres_rows(batch, dsn)
    after_count = count_postgres_snapshots(dsn)

    print(
        json.dumps(
            {
                'input': str(args.input),
                'total_lines': total_lines,
                'valid_rows_seen': len(rows),
                'bad_lines': bad_lines,
                'inserted': inserted,
                'db_count_before': before_count,
                'db_count_after': after_count,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
