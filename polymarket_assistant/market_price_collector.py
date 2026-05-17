#!/usr/bin/env python3
"""Collect live Polymarket BTC market price snapshots."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = REPO_ROOT / 'server_runtime_logs' / 'polymarket_market_snapshots.jsonl'
DEFAULT_ENV_PATH = REPO_ROOT / '.env'

GAMMA_HOST = 'https://gamma-api.polymarket.com'
CLOB_HOST = 'https://clob.polymarket.com'
BINANCE_TICKER_URL = 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT'

REQUEST_TIMEOUT_SECONDS = 20
BOOK_BATCH_SIZE = 100

SNAPSHOT_COLUMNS = [
    'captured_at_utc',
    'btc_spot',
    'event_slug',
    'event_title',
    'event_id',
    'market_id',
    'market_slug',
    'question',
    'market_family',
    'market_type',
    'strike',
    'range_low',
    'range_high',
    'window_start_utc',
    'outcome',
    'token_id',
    'active',
    'closed',
    'accepting_orders',
    'end_date',
    'gamma_probability',
    'gamma_best_bid',
    'gamma_best_ask',
    'gamma_last_trade_price',
    'liquidity',
    'volume',
    'collector_error',
    'book_best_bid',
    'book_best_ask',
    'book_mid',
    'book_spread',
    'book_last_trade_price',
    'top_bid_size',
    'top_ask_size',
    'bid_depth_top5',
    'ask_depth_top5',
    'min_order_size',
    'tick_size',
    'book_hash',
]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS market_price_snapshots (
    id BIGSERIAL PRIMARY KEY,
    captured_at_utc TIMESTAMPTZ NOT NULL,
    btc_spot DOUBLE PRECISION,
    event_slug TEXT NOT NULL,
    event_title TEXT,
    event_id TEXT,
    market_id TEXT,
    market_slug TEXT NOT NULL,
    question TEXT,
    market_family TEXT,
    market_type TEXT,
    strike DOUBLE PRECISION,
    range_low DOUBLE PRECISION,
    range_high DOUBLE PRECISION,
    window_start_utc TIMESTAMPTZ,
    outcome TEXT NOT NULL,
    token_id TEXT NOT NULL,
    active BOOLEAN,
    closed BOOLEAN,
    accepting_orders BOOLEAN,
    end_date TIMESTAMPTZ,
    gamma_probability DOUBLE PRECISION,
    gamma_best_bid DOUBLE PRECISION,
    gamma_best_ask DOUBLE PRECISION,
    gamma_last_trade_price DOUBLE PRECISION,
    liquidity DOUBLE PRECISION,
    volume DOUBLE PRECISION,
    collector_error TEXT,
    book_best_bid DOUBLE PRECISION,
    book_best_ask DOUBLE PRECISION,
    book_mid DOUBLE PRECISION,
    book_spread DOUBLE PRECISION,
    book_last_trade_price DOUBLE PRECISION,
    top_bid_size DOUBLE PRECISION,
    top_ask_size DOUBLE PRECISION,
    bid_depth_top5 DOUBLE PRECISION,
    ask_depth_top5 DOUBLE PRECISION,
    min_order_size DOUBLE PRECISION,
    tick_size DOUBLE PRECISION,
    book_hash TEXT,
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (captured_at_utc, token_id, market_slug, outcome)
);

CREATE INDEX IF NOT EXISTS idx_market_price_snapshots_captured_at
    ON market_price_snapshots (captured_at_utc);
CREATE INDEX IF NOT EXISTS idx_market_price_snapshots_market_slug
    ON market_price_snapshots (market_slug);
CREATE INDEX IF NOT EXISTS idx_market_price_snapshots_token_id
    ON market_price_snapshots (token_id);
CREATE INDEX IF NOT EXISTS idx_market_price_snapshots_market_type
    ON market_price_snapshots (market_type);
CREATE INDEX IF NOT EXISTS idx_market_price_snapshots_market_family
    ON market_price_snapshots (market_family);
CREATE INDEX IF NOT EXISTS idx_market_price_snapshots_market_outcome_time
    ON market_price_snapshots (market_slug, outcome, captured_at_utc);
"""

INSERT_SQL = f"""
INSERT INTO market_price_snapshots ({', '.join(SNAPSHOT_COLUMNS)})
VALUES ({', '.join(['%s'] * len(SNAPSHOT_COLUMNS))})
ON CONFLICT (captured_at_utc, token_id, market_slug, outcome) DO NOTHING
"""


@dataclass(frozen=True)
class OutcomeToken:
    event_slug: str
    event_title: str
    event_id: str
    market_id: str
    market_slug: str
    question: str
    market_family: str
    market_type: str
    strike: float | None
    range_low: float | None
    range_high: float | None
    window_start_utc: str
    outcome: str
    token_id: str
    gamma_probability: float | None
    gamma_best_bid: float | None
    gamma_best_ask: float | None
    gamma_last_trade_price: float | None
    active: bool
    closed: bool
    accepting_orders: bool
    end_date: str
    liquidity: float | None
    volume: float | None


def now_utc() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_env_file(path: Path = DEFAULT_ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def marketdata_dsn(explicit_dsn: str = '') -> str:
    load_env_file()
    dsn = explicit_dsn or os.environ.get('POLYMARKET_MARKETDATA_DSN', '')
    if not dsn:
        raise SystemExit('POLYMARKET_MARKETDATA_DSN must be set for PostgreSQL storage')
    return dsn


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = f'{text[:-1]}+00:00'
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def safe_float(value: Any) -> float | None:
    if value in (None, ''):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def money_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r'\$([0-9,]+(?:\.\d+)?)', text):
        values.append(float(match.group(1).replace(',', '')))
    return values


def infer_market_shape(question: str, event_slug: str) -> tuple[str, str, float | None, float | None, float | None]:
    title = question.lower()
    values = money_values(question)
    first_value = values[0] if values else None

    if event_slug.startswith('btc-updown-4h-') or 'up or down' in title:
        return 'up_down', 'up_down_4h', None, None, None
    if 'reach $' in title:
        return 'reach', 'daily_price_hit', first_value, None, None
    if 'dip to $' in title:
        return 'dip', 'daily_price_hit', first_value, None, None
    if 'above $' in title and 'price of bitcoin' in title:
        return 'above', 'above_below', first_value, first_value, None
    if 'less than $' in title:
        return 'range', 'price_range', None, None, first_value
    if 'between $' in title and len(values) >= 2:
        return 'range', 'price_range', None, values[0], values[1]
    if any(phrase in title for phrase in ('greater than $', 'more than $')) and first_value is not None:
        return 'range', 'price_range', None, first_value, None
    return 'other_btc', 'other_btc', first_value, None, None


def window_start_from_slug(event_slug: str) -> str:
    match = re.fullmatch(r'btc-updown-4h-(\d+)', event_slug)
    if not match:
        return ''
    ts = int(match.group(1))
    return datetime.fromtimestamp(ts, UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def daily_event_slugs(days_back: int = 1, days_ahead: int = 2) -> list[str]:
    slugs: list[str] = []
    current = datetime.now(UTC)
    for delta in range(-days_back, days_ahead + 1):
        day = current + timedelta(days=delta)
        month = day.strftime('%B').lower()
        slugs.extend(
            [
                f'what-price-will-bitcoin-hit-on-{month}-{day.day}',
                f'bitcoin-above-on-{month}-{day.day}',
                f'bitcoin-price-on-{month}-{day.day}',
            ]
        )
    return slugs


def up_down_4h_event_slugs(windows_back: int = 1, windows_ahead: int = 2) -> list[str]:
    now_ts = int(datetime.now(UTC).timestamp())
    current_window = (now_ts // (4 * 60 * 60)) * (4 * 60 * 60)
    return [
        f'btc-updown-4h-{current_window + offset * 4 * 60 * 60}'
        for offset in range(-windows_back, windows_ahead + 1)
    ]


def candidate_event_slugs() -> list[str]:
    seen: set[str] = set()
    slugs: list[str] = []
    for slug in daily_event_slugs() + up_down_4h_event_slugs():
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def fetch_event(session: requests.Session, slug: str) -> dict[str, Any] | None:
    response = session.get(f'{GAMMA_HOST}/events/slug/{slug}', timeout=REQUEST_TIMEOUT_SECONDS)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    event = response.json()
    return event if isinstance(event, dict) else None


def parse_event_markets(event: dict[str, Any]) -> list[OutcomeToken]:
    event_slug = str(event.get('slug') or '')
    event_title = str(event.get('title') or '')
    event_id = str(event.get('id') or '')
    parsed: list[OutcomeToken] = []

    for market in event.get('markets') or []:
        if not isinstance(market, dict):
            continue
        question = str(market.get('question') or event_title or '')
        if 'bitcoin' not in question.lower() and not event_slug.startswith('btc-updown-4h-'):
            continue

        outcomes = [str(item) for item in parse_json_list(market.get('outcomes'))]
        token_ids = [str(item) for item in parse_json_list(market.get('clobTokenIds'))]
        probabilities = [safe_float(item) for item in parse_json_list(market.get('outcomePrices'))]
        if not outcomes or not token_ids:
            continue

        market_family, market_type, strike, range_low, range_high = infer_market_shape(question, event_slug)
        if market_type == 'other_btc':
            continue

        active = bool(market.get('active'))
        closed = bool(market.get('closed'))
        accepting_orders = bool(market.get('acceptingOrders'))
        if closed or not active or not accepting_orders:
            continue

        for index, outcome in enumerate(outcomes):
            if index >= len(token_ids) or not token_ids[index]:
                continue
            parsed.append(
                OutcomeToken(
                    event_slug=event_slug,
                    event_title=event_title,
                    event_id=event_id,
                    market_id=str(market.get('id') or ''),
                    market_slug=str(market.get('slug') or ''),
                    question=question,
                    market_family=market_family,
                    market_type=market_type,
                    strike=strike,
                    range_low=range_low,
                    range_high=range_high,
                    window_start_utc=window_start_from_slug(event_slug),
                    outcome=outcome,
                    token_id=token_ids[index],
                    gamma_probability=probabilities[index] if index < len(probabilities) else None,
                    gamma_best_bid=safe_float(market.get('bestBid')),
                    gamma_best_ask=safe_float(market.get('bestAsk')),
                    gamma_last_trade_price=safe_float(market.get('lastTradePrice')),
                    active=active,
                    closed=closed,
                    accepting_orders=accepting_orders,
                    end_date=str(market.get('endDate') or ''),
                    liquidity=safe_float(market.get('liquidity')),
                    volume=safe_float(market.get('volume')),
                )
            )
    return parsed


def fetch_btc_spot(session: requests.Session) -> float | None:
    response = session.get(BINANCE_TICKER_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    response.raise_for_status()
    return safe_float(response.json().get('price'))


def chunked(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def fetch_books_batch(session: requests.Session, token_ids: list[str]) -> dict[str, dict[str, Any]]:
    books: dict[str, dict[str, Any]] = {}
    for chunk in chunked(token_ids, BOOK_BATCH_SIZE):
        payload = [{'token_id': token_id} for token_id in chunk]
        response = session.post(f'{CLOB_HOST}/books', json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list):
            raise ValueError('Unexpected /books response payload')
        for book in data:
            if not isinstance(book, dict):
                continue
            asset_id = str(book.get('asset_id') or '')
            if asset_id:
                books[asset_id] = book
    return books


def fetch_book_single(session: requests.Session, token_id: str) -> tuple[dict[str, Any] | None, str]:
    try:
        response = session.get(f'{CLOB_HOST}/book', params={'token_id': token_id}, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None, ''
    except Exception as exc:
        return None, str(exc)[:500]


def fetch_books(session: requests.Session, token_ids: list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    try:
        books = fetch_books_batch(session, token_ids)
        missing = [token_id for token_id in token_ids if token_id not in books]
        errors: dict[str, str] = {}
    except Exception as exc:
        books = {}
        missing = token_ids
        errors = {token_id: f'batch_books_failed: {exc}'[:500] for token_id in token_ids}

    for token_id in missing:
        book, error = fetch_book_single(session, token_id)
        if book:
            books[token_id] = book
            errors.pop(token_id, None)
        elif error:
            errors[token_id] = error
    return books, errors


def parse_book_levels(levels: Any, *, reverse: bool) -> list[dict[str, float]]:
    parsed: list[dict[str, float]] = []
    if not isinstance(levels, list):
        return parsed
    for level in levels:
        if not isinstance(level, dict):
            continue
        price = safe_float(level.get('price'))
        size = safe_float(level.get('size'))
        if price is None or size is None:
            continue
        parsed.append({'price': price, 'size': size})
    parsed.sort(key=lambda item: item['price'], reverse=reverse)
    return parsed


def summarize_book(book: dict[str, Any] | None) -> dict[str, Any]:
    if not book:
        return {
            'book_best_bid': None,
            'book_best_ask': None,
            'book_mid': None,
            'book_spread': None,
            'book_last_trade_price': None,
            'top_bid_size': None,
            'top_ask_size': None,
            'bid_depth_top5': None,
            'ask_depth_top5': None,
            'min_order_size': None,
            'tick_size': None,
            'book_hash': '',
        }

    bids = parse_book_levels(book.get('bids'), reverse=True)
    asks = parse_book_levels(book.get('asks'), reverse=False)
    top_bid = bids[0] if bids else None
    top_ask = asks[0] if asks else None
    best_bid = top_bid['price'] if top_bid else None
    best_ask = top_ask['price'] if top_ask else None
    spread = round(best_ask - best_bid, 6) if best_bid is not None and best_ask is not None else None
    mid = round((best_bid + best_ask) / 2, 6) if best_bid is not None and best_ask is not None else None

    return {
        'book_best_bid': best_bid,
        'book_best_ask': best_ask,
        'book_mid': mid,
        'book_spread': spread,
        'book_last_trade_price': safe_float(book.get('last_trade_price')),
        'top_bid_size': top_bid['size'] if top_bid else None,
        'top_ask_size': top_ask['size'] if top_ask else None,
        'bid_depth_top5': round(sum(level['size'] for level in bids[:5]), 6) if bids else None,
        'ask_depth_top5': round(sum(level['size'] for level in asks[:5]), 6) if asks else None,
        'min_order_size': safe_float(book.get('min_order_size')),
        'tick_size': safe_float(book.get('tick_size')),
        'book_hash': str(book.get('hash') or ''),
    }


def snapshot_row(
    token: OutcomeToken,
    *,
    captured_at_utc: str,
    btc_spot: float | None,
    book: dict[str, Any] | None,
    collector_error: str,
) -> dict[str, Any]:
    row = {
        'captured_at_utc': captured_at_utc,
        'btc_spot': btc_spot,
        'event_slug': token.event_slug,
        'event_title': token.event_title,
        'event_id': token.event_id,
        'market_id': token.market_id,
        'market_slug': token.market_slug,
        'question': token.question,
        'market_family': token.market_family,
        'market_type': token.market_type,
        'strike': token.strike,
        'range_low': token.range_low,
        'range_high': token.range_high,
        'window_start_utc': token.window_start_utc,
        'outcome': token.outcome,
        'token_id': token.token_id,
        'active': token.active,
        'closed': token.closed,
        'accepting_orders': token.accepting_orders,
        'end_date': token.end_date,
        'gamma_probability': token.gamma_probability,
        'gamma_best_bid': token.gamma_best_bid,
        'gamma_best_ask': token.gamma_best_ask,
        'gamma_last_trade_price': token.gamma_last_trade_price,
        'liquidity': token.liquidity,
        'volume': token.volume,
        'collector_error': collector_error,
    }
    row.update(summarize_book(book))
    return row


def discover_outcome_tokens(session: requests.Session, max_markets: int | None) -> list[OutcomeToken]:
    tokens: list[OutcomeToken] = []
    seen_markets: set[str] = set()
    gamma_failures = 0
    found_events = 0

    for slug in candidate_event_slugs():
        try:
            event = fetch_event(session, slug)
        except requests.RequestException as exc:
            gamma_failures += 1
            print(f'[collector] WARN: Gamma fetch failed for {slug}: {exc}', file=sys.stderr)
            continue
        if not event:
            continue

        found_events += 1
        for token in parse_event_markets(event):
            if token.market_slug not in seen_markets:
                if max_markets is not None and len(seen_markets) >= max_markets:
                    continue
                seen_markets.add(token.market_slug)
            if token.market_slug in seen_markets:
                tokens.append(token)

    if found_events == 0 and gamma_failures:
        raise RuntimeError('Gamma discovery failed for all candidate events')
    return tokens


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8', newline='\n') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')


def row_to_db_values(row: dict[str, Any]) -> tuple[Any, ...]:
    normalized = dict(row)
    normalized['captured_at_utc'] = parse_timestamp(row.get('captured_at_utc'))
    normalized['window_start_utc'] = parse_timestamp(row.get('window_start_utc'))
    normalized['end_date'] = parse_timestamp(row.get('end_date'))
    if normalized['captured_at_utc'] is None:
        raise ValueError('captured_at_utc is required')
    return tuple(normalized.get(column) for column in SNAPSHOT_COLUMNS)


def create_postgres_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def insert_postgres_rows(rows: list[dict[str, Any]], dsn: str, *, create_schema: bool = True) -> int:
    if not rows:
        return 0
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit('psycopg is required for PostgreSQL storage. Install requirements.txt first.') from exc

    values = [row_to_db_values(row) for row in rows]
    with psycopg.connect(dsn) as conn:
        if create_schema:
            create_postgres_schema(conn)
        with conn.cursor() as cur:
            cur.executemany(INSERT_SQL, values)
            inserted = cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0
        conn.commit()
        return inserted


def count_postgres_snapshots(dsn: str) -> int:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit('psycopg is required for PostgreSQL storage. Install requirements.txt first.') from exc
    with psycopg.connect(dsn) as conn:
        create_postgres_schema(conn)
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM market_price_snapshots')
            return int(cur.fetchone()[0])


def collect(args: argparse.Namespace) -> list[dict[str, Any]]:
    session = requests.Session()
    captured_at = now_utc()
    btc_spot = fetch_btc_spot(session)
    tokens = discover_outcome_tokens(session, args.max_markets)
    token_ids = sorted({token.token_id for token in tokens})
    books, book_errors = fetch_books(session, token_ids)

    rows = [
        snapshot_row(
            token,
            captured_at_utc=captured_at,
            btc_spot=btc_spot,
            book=books.get(token.token_id),
            collector_error=book_errors.get(token.token_id, ''),
        )
        for token in tokens
    ]
    rows.sort(key=lambda row: (row['event_slug'], row['market_slug'], row['outcome']))
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Collect live Polymarket BTC market snapshots.')
    parser.add_argument('--dry-run', action='store_true', help='Fetch and print a summary without writing JSONL.')
    parser.add_argument(
        '--storage',
        choices=('postgres', 'jsonl'),
        default='postgres',
        help='Storage backend. Systemd uses postgres; jsonl is kept for manual debugging.',
    )
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT_PATH, help='JSONL output path.')
    parser.add_argument('--dsn', default='', help='PostgreSQL DSN. Defaults to POLYMARKET_MARKETDATA_DSN.')
    parser.add_argument('--max-markets', type=int, default=None, help='Limit market count for tests.')
    return parser


def main() -> None:
    args = build_parser().parse_args()
    rows = collect(args)
    market_count = len({row['market_slug'] for row in rows})
    error_count = sum(1 for row in rows if row.get('collector_error'))

    if args.dry_run:
        print(
            json.dumps(
                {
                    'dry_run': True,
                    'rows': len(rows),
                    'markets': market_count,
                    'errors': error_count,
                    'sample': rows[:3],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.storage == 'jsonl':
        write_jsonl(args.output, rows)
        print(f'[collector] wrote rows={len(rows)} markets={market_count} errors={error_count} output={args.output}')
        return

    inserted = insert_postgres_rows(rows, marketdata_dsn(args.dsn))
    print(
        f'[collector] inserted rows={inserted}/{len(rows)} '
        f'markets={market_count} errors={error_count} storage=postgres'
    )


if __name__ == '__main__':
    main()
