#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from dotenv import dotenv_values
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams, MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

REPO_ROOT = Path(__file__).resolve().parent.parent
ASSISTANT_DIR = REPO_ROOT / 'polymarket_assistant'
DOCS_DIR = REPO_ROOT / 'doc'
ASSISTANT_DOCS_DIR = DOCS_DIR / 'polymarket_assistant'
TRANSCRIPTS_DIR = REPO_ROOT / 'transcripts'
ANALYSES_LOG_PATH = REPO_ROOT / 'analyses_log.json'
PLAYBOOK_PATH = ASSISTANT_DOCS_DIR / 'PLAYBOOK.md'
PROMPT_TEMPLATE_PATH = ASSISTANT_DOCS_DIR / 'copilot_prompt.md'
ACCOUNT_STATE_PATH = ASSISTANT_DIR / 'account_state.json'
TRADE_LOG_PATH = ASSISTANT_DIR / 'trade_log.json'
LAST_RUN_SUMMARY_PATH = ASSISTANT_DIR / 'last_run_summary.json'
WORKFLOW_SUMMARY_PATH = ASSISTANT_DOCS_DIR / 'last_run_summary.md'
NOTIFIED_CLAIMS_PATH = ASSISTANT_DIR / 'notified_claims.json'
PENDING_ORDERS_PATH = ASSISTANT_DIR / 'pending_orders.json'
HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137
GAMMA_HOST = 'https://gamma-api.polymarket.com'
DATA_API_HOST = 'https://data-api.polymarket.com'
BINANCE_TICKER_URL = 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT'
BINANCE_STATS_URL = 'https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT'
BINANCE_FUNDING_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT'
BINANCE_LS_RATIO_URL = 'https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=5m&limit=1'
BINANCE_OI_URL = 'https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT'
BINANCE_OI_HIST_URL = 'https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=5'
FEAR_GREED_URL = 'https://api.alternative.me/fng/?limit=1'
MAX_TRANSCRIPTS = 3
MAX_SUMMARIES = 4
MAX_MARKETS = 24


def load_env() -> dict[str, str]:
    env_path = ASSISTANT_DIR / '.env'
    file_values: dict[str, str] = {}
    if env_path.exists():
        file_values = {
            key: str(value).strip()
            for key, value in dotenv_values(env_path).items()
            if value is not None and str(value).strip()
        }
    merged = dict(file_values)
    for key, value in os.environ.items():
        if key.startswith('POLY_') or key == 'COPILOT_GITHUB_TOKEN':
            merged[key] = value.strip()
    return merged


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def now_utc() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def build_private_client(config: dict[str, str]) -> ClobClient:
    client = ClobClient(
        HOST,
        key=config['POLY_PRIVATE_KEY'],
        chain_id=CHAIN_ID,
        signature_type=int(config.get('POLY_SIGNATURE_TYPE', '1')),
        funder=config.get('POLY_FUNDER') or None,
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)
    return client


def read_recent_transcripts(limit: int = MAX_TRANSCRIPTS, chars_per_file: int = 3500) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    files = sorted(TRANSCRIPTS_DIR.glob('*.txt'), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    for path in files:
        text = path.read_text(encoding='utf-8').strip()
        try:
            video_id, date_part = path.stem.split('_', 1)
        except ValueError:
            video_id, date_part = path.stem, 'unknown'
        results.append({
            'file': f'transcripts/{path.name}',
            'video_id': video_id,
            'date': date_part,
            'chars': len(text),
            'excerpt': ' '.join(text.split())[:chars_per_file],
        })
    return results


def read_recent_summaries(limit: int = MAX_SUMMARIES, chars_per_message: int = 1200) -> list[dict[str, Any]]:
    entries = load_json(ANALYSES_LOG_PATH, [])[-limit:]
    results: list[dict[str, Any]] = []
    for entry in entries:
        results.append({
            'timestamp': entry.get('timestamp'),
            'video_id': entry.get('video_id'),
            'btc_usd': entry.get('btc_usd'),
            'robot_score': entry.get('robot_score'),
            'message_excerpt': ' '.join(str(entry.get('message', '')).split())[:chars_per_message],
        })
    return results


def fetch_btc_funding_rate() -> dict[str, Any] | None:
    """Fetch the current BTC perpetual funding rate from Binance futures.

    Returns a dict with the raw rate, annualised rate, and a human-readable
    sentiment label, or None if the request fails.
    """
    try:
        resp = requests.get(BINANCE_FUNDING_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        rate = safe_float(data.get('lastFundingRate'))
        rate_pct = round(rate * 100, 4)
        annualised_pct = round(rate * 3 * 365 * 100, 2)  # 3 payments/day * 365 days
        if rate > 0.0005:
            sentiment = 'bullish (longs paying shorts)'
        elif rate < -0.0005:
            sentiment = 'bearish (shorts paying longs)'
        else:
            sentiment = 'neutral'
        return {
            'funding_rate': rate_pct,
            'annualised_pct': annualised_pct,
            'sentiment': sentiment,
        }
    except Exception:
        return None


def fetch_fear_greed() -> dict[str, Any] | None:
    """Fetch the current Fear & Greed index from alternative.me."""
    try:
        resp = requests.get(FEAR_GREED_URL, timeout=10)
        resp.raise_for_status()
        entry = resp.json()['data'][0]
        value = int(entry['value'])
        label = entry['value_classification']
        return {'value': value, 'label': label}
    except Exception:
        return None


def fetch_long_short_ratio() -> dict[str, Any] | None:
    """Fetch the global BTC long/short account ratio from Binance futures."""
    try:
        resp = requests.get(BINANCE_LS_RATIO_URL, timeout=10)
        resp.raise_for_status()
        data = resp.json()[0]
        ratio = safe_float(data.get('longShortRatio'))
        long_pct = round(safe_float(data.get('longAccount')) * 100, 1)
        short_pct = round(safe_float(data.get('shortAccount')) * 100, 1)
        if ratio > 1.1:
            bias = 'longs dominant'
        elif ratio < 0.9:
            bias = 'shorts dominant'
        else:
            bias = 'balanced'
        return {'ratio': round(ratio, 3), 'long_pct': long_pct, 'short_pct': short_pct, 'bias': bias}
    except Exception:
        return None


def fetch_open_interest() -> dict[str, Any] | None:
    """Fetch current OI and 4h trend from Binance futures."""
    try:
        oi_resp = requests.get(BINANCE_OI_URL, timeout=10)
        oi_resp.raise_for_status()
        current_oi = safe_float(oi_resp.json().get('openInterest'))

        hist_resp = requests.get(BINANCE_OI_HIST_URL, timeout=10)
        hist_resp.raise_for_status()
        hist = hist_resp.json()
        if len(hist) >= 2:
            oldest_oi = safe_float(hist[0].get('sumOpenInterest'))
            change_pct = round((current_oi - oldest_oi) / oldest_oi * 100, 2) if oldest_oi else 0.0
            if change_pct > 1:
                trend = 'expanding (new money entering)'
            elif change_pct < -1:
                trend = 'contracting (positions closing)'
            else:
                trend = 'flat'
        else:
            change_pct = 0.0
            trend = 'unknown'

        return {
            'current_btc': round(current_oi, 0),
            'change_4h_pct': change_pct,
            'trend': trend,
        }
    except Exception:
        return None


def build_market_time_context() -> dict[str, Any]:
    """Return time-awareness context for daily and weekly Polymarket markets."""
    now = datetime.now(UTC)
    # Daily markets reset at UTC midnight
    hours_until_daily_close = round((23 - now.hour) + (60 - now.minute) / 60, 1)
    # Weekly markets (Mon–Sun) close at end of Sunday UTC
    days_until_weekly_close = 6 - now.weekday()  # weekday(): Mon=0, Sun=6
    if days_until_weekly_close < 0:
        days_until_weekly_close = 0
    hours_until_weekly_close = round(days_until_weekly_close * 24 + hours_until_daily_close, 1)
    return {
        'utc_now': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'utc_hour': now.hour,
        'hours_until_daily_market_close': hours_until_daily_close,
        'hours_until_weekly_market_close': hours_until_weekly_close,
        'note': (
            'Daily markets resolve at UTC midnight. '
            'A position entered with <4h remaining has very limited time to resolve.'
        ),
    }


def fetch_binance_snapshot() -> dict[str, Any]:
    ticker = requests.get(BINANCE_TICKER_URL, timeout=20)
    ticker.raise_for_status()
    stats = requests.get(BINANCE_STATS_URL, timeout=20)
    stats.raise_for_status()
    ticker_json = ticker.json()
    stats_json = stats.json()
    spot = safe_float(ticker_json.get('price'))
    high = safe_float(stats_json.get('highPrice'))
    low = safe_float(stats_json.get('lowPrice'))
    change_pct = safe_float(stats_json.get('priceChangePercent'))
    # Intraday move context: how much of the daily range has already been used
    daily_range = high - low
    pct_from_high = round((high - spot) / high * 100, 2) if high else 0.0
    pct_from_low = round((spot - low) / low * 100, 2) if low else 0.0
    snapshot = {
        'symbol': ticker_json.get('symbol'),
        'spot_price': spot,
        'price_change_percent_24h': change_pct,
        'high_24h': high,
        'low_24h': low,
        'volume_24h': safe_float(stats_json.get('volume')),
        'daily_range_usd': round(daily_range, 0),
        'pct_below_24h_high': pct_from_high,
        'pct_above_24h_low': pct_from_low,
    }
    for fetcher, key in [
        (fetch_btc_funding_rate, 'funding_rate'),
        (fetch_long_short_ratio, 'long_short_ratio'),
        (fetch_open_interest, 'open_interest'),
    ]:
        result = fetcher()
        if result:
            snapshot[key] = result
    return snapshot


def infer_btc_market_type(question: str, event_slug: str = '', fallback_event_slug: str = '') -> str:
    slug = (event_slug or fallback_event_slug or '').lower()
    if '-on-' in slug:
        return 'daily'
    if slug:
        return 'weekly'

    lowered_question = question.lower()
    if re.search(r'\bon [a-z]+ \d{1,2}\b', lowered_question):
        return 'daily'
    if re.search(r'\b[a-z]+ \d{1,2}-\d{1,2}\b', lowered_question):
        return 'weekly'
    return 'weekly'


def parse_market(record: dict[str, Any], fallback_event_slug: str = '') -> dict[str, Any] | None:
    question = str(record.get('question', ''))
    title = question.lower()
    if 'bitcoin' not in title:
        return None
    family = None
    if 'reach $' in title:
        family = 'reach'
    elif 'dip to $' in title:
        family = 'dip'
    else:
        return None
    match = re.search(r'\$([0-9,]+)', question)
    if not match:
        return None
    strike = int(match.group(1).replace(',', ''))
    outcomes = []
    outcome_prices = []
    token_ids = []
    try:
        outcomes = json.loads(record.get('outcomes', '[]'))
        outcome_prices = [safe_float(x) for x in json.loads(record.get('outcomePrices', '[]'))]
        token_ids = json.loads(record.get('clobTokenIds', '[]'))
    except json.JSONDecodeError:
        return None
    outcome_map = {}
    for idx, outcome in enumerate(outcomes):
        outcome_map[outcome] = {
            'probability': outcome_prices[idx] if idx < len(outcome_prices) else None,
            'token_id': token_ids[idx] if idx < len(token_ids) else None,
        }
    event_slug = record.get('eventSlug', '') or fallback_event_slug
    market_type = infer_btc_market_type(question, event_slug=event_slug, fallback_event_slug=fallback_event_slug)
    return {
        'event_id': record.get('eventId'),
        'event_slug': event_slug,
        'market_slug': record.get('slug'),
        'question': question,
        'family': family,
        'market_type': market_type,
        'strike': strike,
        'best_bid': safe_float(record.get('bestBid')),
        'best_ask': safe_float(record.get('bestAsk')),
        'last_trade_price': safe_float(record.get('lastTradePrice')),
        'active': bool(record.get('active')),
        'closed': bool(record.get('closed')),
        'accepting_orders': bool(record.get('acceptingOrders')),
        'end_date': record.get('endDate'),
        'outcomes': outcome_map,
    }


def parse_floor_market(record: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a 'Bitcoin above $X on date' binary market record from the GAMMA API."""
    question = str(record.get('question', ''))
    title = question.lower()
    if 'bitcoin' not in title or 'above' not in title:
        return None
    match = re.search(r'\$([0-9,]+)', question)
    if not match:
        return None
    floor_level = int(match.group(1).replace(',', ''))
    outcomes = []
    outcome_prices = []
    token_ids = []
    try:
        outcomes = json.loads(record.get('outcomes', '[]'))
        outcome_prices = [safe_float(x) for x in json.loads(record.get('outcomePrices', '[]'))]
        token_ids = json.loads(record.get('clobTokenIds', '[]'))
    except json.JSONDecodeError:
        return None
    outcome_map = {}
    for idx, outcome in enumerate(outcomes):
        outcome_map[outcome] = {
            'probability': outcome_prices[idx] if idx < len(outcome_prices) else None,
            'token_id': token_ids[idx] if idx < len(token_ids) else None,
        }
    event_slug = record.get('eventSlug', '')
    return {
        'event_slug': event_slug,
        'market_slug': record.get('slug'),
        'question': question,
        'family': 'floor',
        'market_type': 'floor',
        'floor_level': floor_level,
        'best_bid': safe_float(record.get('bestBid')),
        'best_ask': safe_float(record.get('bestAsk')),
        'last_trade_price': safe_float(record.get('lastTradePrice')),
        'active': bool(record.get('active')),
        'closed': bool(record.get('closed')),
        'accepting_orders': bool(record.get('acceptingOrders')),
        'end_date': record.get('endDate'),
        'outcomes': outcome_map,
    }


def _fetch_daily_event_slugs(days_ahead: int = 2) -> list[str]:
    # Start from yesterday in UTC: Polymarket daily events close at 11:59 PM ET (~05:00 UTC
    # the following day), so the previous UTC day's markets may still be open and accepting
    # orders in the early hours of the next UTC day.
    slugs: list[str] = []
    now = datetime.now(UTC)
    for delta in range(-1, days_ahead):
        d = now + timedelta(days=delta)
        month = d.strftime('%B').lower()
        day = d.day
        slugs.append(f'what-price-will-bitcoin-hit-on-{month}-{day}')
    return slugs


def _fetch_weekly_event_slugs() -> list[str]:
    # Query Gamma API for active weekly BTC price-hit events.
    # Weekly slug pattern: what-price-will-bitcoin-hit-{month}-{d1}-{d2}
    # Excluded: daily ("-on-"), monthly ("-in-"), long-term ("before-")
    seen: set[str] = set()
    slugs: list[str] = []
    try:
        response = requests.get(
            f'{GAMMA_HOST}/events',
            params={'tag_slug': 'weekly', 'active': 'true', 'closed': 'false', 'limit': 100},
            timeout=30,
        )
        response.raise_for_status()
        events = response.json()
        for event in events:
            slug = event.get('slug', '')
            if not slug.startswith('what-price-will-bitcoin-hit'):
                continue
            if any(x in slug for x in ('-on-', '-in-', 'before-')):
                continue
            if slug not in seen:
                seen.add(slug)
                slugs.append(slug)
    except requests.RequestException:
        pass
    return slugs


def _fetch_floor_event_slugs(days_ahead: int = 2) -> list[str]:
    # Slug pattern: bitcoin-above-on-{month}-{day}
    slugs: list[str] = []
    now = datetime.now(UTC)
    for delta in range(-1, days_ahead):
        d = now + timedelta(days=delta)
        month = d.strftime('%B').lower()
        day = d.day
        slugs.append(f'bitcoin-above-on-{month}-{day}')
    return slugs


def fetch_active_floor_markets() -> list[dict[str, Any]]:
    """Return 'Bitcoin above $X' binary markets in the contested probability range (0.45–0.82)."""
    markets: list[dict[str, Any]] = []
    for event_slug in _fetch_floor_event_slugs():
        try:
            response = requests.get(
                f'{GAMMA_HOST}/events/slug/{event_slug}',
                timeout=30,
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            event = response.json()
            for item in event.get('markets', []):
                parsed = parse_floor_market(item)
                if not parsed or not parsed['accepting_orders'] or parsed['closed']:
                    continue
                yes_prob = (parsed['outcomes'].get('Yes') or {}).get('probability', 0.0)
                if 0.45 <= yes_prob <= 0.82:
                    markets.append(parsed)
        except requests.RequestException:
            continue
    markets.sort(key=lambda m: (m['end_date'] or '', m['floor_level']))
    return markets


def fetch_active_btc_markets(limit: int = MAX_MARKETS) -> list[dict[str, Any]]:
    all_markets: list[dict[str, Any]] = []
    event_slugs = _fetch_daily_event_slugs() + _fetch_weekly_event_slugs()
    for event_slug in event_slugs:
        try:
            response = requests.get(
                f'{GAMMA_HOST}/events/slug/{event_slug}',
                timeout=30,
            )
            if response.status_code == 404:
                continue
            response.raise_for_status()
            event = response.json()
            for item in event.get('markets', []):
                parsed = parse_market(item, fallback_event_slug=event_slug)
                if parsed and parsed['accepting_orders'] and not parsed['closed']:
                    all_markets.append(parsed)
        except requests.RequestException:
            continue
    all_markets.sort(key=lambda item: (item['end_date'] or '', item['family'], item['strike']))
    return all_markets[:limit]


def fetch_positions(config: dict[str, str]) -> list[dict[str, Any]]:
    user = config.get('POLY_FUNDER') or config.get('POLY_SIGNER_ADDRESS')
    if not user:
        return []
    response = requests.get(
        f'{DATA_API_HOST}/positions',
        params={'user': user, 'sizeThreshold': 0.01, 'limit': 100, 'offset': 0},
        timeout=30,
    )
    response.raise_for_status()
    positions = response.json()
    now_utc = datetime.now(UTC)
    normalized = []
    for item in positions:
        size = safe_float(item.get('size'))
        if size <= 0:
            continue
        if item.get('redeemable'):
            continue  # market resolved — position is redeemable, exclude from active
        end_date_str = item.get('endDate')
        if end_date_str:
            try:
                end_dt = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=UTC)  # treat bare date as UTC midnight
                if end_dt < now_utc:
                    continue  # market already expired — exclude from active positions
            except Exception:
                pass
        normalized.append({
            'market_slug': item.get('slug'),
            'market_title': item.get('title'),
            'event_slug': item.get('eventSlug'),
            'outcome': item.get('outcome'),
            'asset': item.get('asset'),
            'size': size,
            'avg_price': safe_float(item.get('avgPrice')),
            'initial_value': safe_float(item.get('initialValue')),
            'current_value': safe_float(item.get('currentValue')),
            'cash_pnl': safe_float(item.get('cashPnl')),
            'percent_pnl': safe_float(item.get('percentPnl')),
            'cur_price': safe_float(item.get('curPrice')),
            'end_date': end_date_str,
        })
    return normalized


def fetch_balance_allowance(client: ClobClient, config: dict[str, str]) -> dict[str, Any]:
    return client.get_balance_allowance(
        BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=int(config.get('POLY_SIGNATURE_TYPE', '1')),
        )
    )


def compute_performance_snapshot(trade_log: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compute a calibration summary from closed trades for GPT context.

    Returns None when fewer than 3 closed trades exist (not statistically useful).
    """
    closed = [e for e in trade_log if e.get('type') == 'trade_closed']
    if len(closed) < 3:
        return None

    wins = [t for t in closed if safe_float(t.get('pnl_usd')) > 0]
    losses = [t for t in closed if safe_float(t.get('pnl_usd')) <= 0]
    win_rate = round(len(wins) / len(closed) * 100, 1)

    avg_gain = round(sum(safe_float(t.get('pnl_pct')) for t in wins) / len(wins), 1) if wins else 0.0
    avg_loss = round(sum(safe_float(t.get('pnl_pct')) for t in losses) / len(losses), 1) if losses else 0.0

    # Win rate by entry probability band
    bands: dict[str, list[bool]] = {'20-40%': [], '40-60%': [], '60-80%': [], '>80%': []}
    for t in closed:
        prob = safe_float(t.get('avg_entry_price'))
        result = safe_float(t.get('pnl_usd')) > 0
        if prob < 0.40:
            bands['20-40%'].append(result)
        elif prob < 0.60:
            bands['40-60%'].append(result)
        elif prob < 0.80:
            bands['60-80%'].append(result)
        else:
            bands['>80%'].append(result)

    band_stats = {}
    for label, results in bands.items():
        if results:
            band_stats[label] = f"{round(sum(results) / len(results) * 100)}% win ({len(results)} trades)"

    # Recent streak (last 5 closed trades)
    streak = ''.join('W' if safe_float(t.get('pnl_usd')) > 0 else 'L' for t in closed[-5:])

    return {
        'total_closed_trades': len(closed),
        'win_rate_pct': win_rate,
        'avg_gain_on_wins_pct': avg_gain,
        'avg_loss_on_losses_pct': avg_loss,
        'by_entry_probability_band': band_stats,
        'recent_streak_last5': streak,
    }


def build_context_snapshot(config: dict[str, str]) -> dict[str, Any]:
    client = build_private_client(config)
    account_state = load_json(ACCOUNT_STATE_PATH, {})
    trade_log = load_json(TRADE_LOG_PATH, [])
    positions = fetch_positions(config)  # already filtered by endDate
    balance = fetch_balance_allowance(client, config)
    orders = client.get_orders()
    perf = compute_performance_snapshot(trade_log)
    reconciliation = build_reconciliation_status(account_state, positions, trade_log)

    # Reconcile account_state.open_positions against live positions before
    # passing to GPT. Any position whose market has expired (excluded from
    # fetch_positions by endDate) is removed here so GPT always sees an
    # accurate slot count, even if the previous sync wrote a stale entry.
    live_slugs = {p['market_slug'] for p in positions}
    account_state = dict(account_state)
    account_state['open_positions'] = [
        p for p in account_state.get('open_positions', [])
        if p.get('market_slug') in live_slugs
    ]

    return {
        'playbook': PLAYBOOK_PATH.read_text(encoding='utf-8'),
        'recent_transcripts': read_recent_transcripts(),
        'recent_summaries': read_recent_summaries(),
        'account_state': account_state,
        'recent_trade_log': trade_log[-8:],
        'performance_snapshot': perf,
        'reconciliation': reconciliation,
        'market_time_context': build_market_time_context(),
        'binance': fetch_binance_snapshot(),
        'polymarket': {
            'cash_balance_usdc': safe_float(balance.get('balance')) / 1_000_000,
            'allowances': balance.get('allowances', {}),
            'open_orders': orders,
            'positions': positions,
            'discarded_probability_threshold': discarded_probability_threshold(account_state),
            'active_price_hit_positions': [
                p for p in positions
                if infer_position_market_type(p) in {'daily', 'weekly'} and not is_slot_discarded(p, account_state)
            ],
            'discarded_price_hit_positions': [
                p for p in positions
                if infer_position_market_type(p) in {'daily', 'weekly'} and is_slot_discarded(p, account_state)
            ],
            'active_btc_markets': fetch_active_btc_markets(),
            'active_floor_markets': fetch_active_floor_markets(),
            'open_floor_positions': [p for p in positions if infer_position_market_type(p) == 'floor'],
        },
    }


def render_prompt(context: dict[str, Any]) -> str:
    template = PROMPT_TEMPLATE_PATH.read_text(encoding='utf-8').strip()
    compact_context = json.dumps(context, ensure_ascii=False, indent=2)
    return f'{template}\n\n{compact_context}\n'


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith('```'):
        stripped = re.sub(r'^```(?:json)?', '', stripped).strip()
        stripped = re.sub(r'```$', '', stripped).strip()
    return json.loads(stripped)


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
    return json.loads(path.read_text(encoding='utf-8'))


def find_market_by_slug(markets: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    for market in markets:
        if market['market_slug'] == slug:
            return market
    return None


def infer_position_market_type(position: dict[str, Any]) -> str:
    """Infer market_type from position slugs (positions don't carry this field natively)."""
    market_slug = position.get('market_slug') or ''
    event_slug = position.get('event_slug') or ''
    market_title = position.get('market_title') or ''
    if market_slug.startswith('bitcoin-above') or event_slug.startswith('bitcoin-above'):
        return 'floor'
    return infer_btc_market_type(market_title, event_slug=event_slug)


def nearest_strike_ok(market: dict[str, Any], markets: list[dict[str, Any]], spot_price: float) -> bool:
    # Nearest-strike-first applies only within the same market_type (daily vs weekly).
    family = market['family']
    mtype = market.get('market_type', 'daily')
    peers = [m for m in markets if m['family'] == family and m.get('market_type') == mtype]
    if family == 'reach':
        candidates = sorted([m['strike'] for m in peers if m['strike'] > spot_price])
        return not candidates or market['strike'] == candidates[0]
    candidates = sorted([m['strike'] for m in peers if m['strike'] < spot_price], reverse=True)
    return not candidates or market['strike'] == candidates[0]


def outcome_probability(market: dict[str, Any], outcome: str) -> float:
    return safe_float(market.get('outcomes', {}).get(outcome, {}).get('probability'))


def discarded_probability_threshold(account_state: dict[str, Any]) -> float:
    return safe_float(account_state.get('discarded_probability_threshold', 0.20))


def position_probability(position: dict[str, Any]) -> float | None:
    raw = position.get('cur_price')
    if raw is None:
        raw = position.get('current_price')
    if raw is None:
        return None
    return safe_float(raw)


def is_slot_discarded(position: dict[str, Any], account_state: dict[str, Any]) -> bool:
    """Daily/weekly positions at or below the threshold stay open but stop blocking the slot."""
    if infer_position_market_type(position) not in {'daily', 'weekly'}:
        return False
    prob = position_probability(position)
    if prob is None:
        return False
    return prob <= discarded_probability_threshold(account_state)


def build_reconciliation_status(
    account_state: dict[str, Any],
    live_positions: list[dict[str, Any]],
    trade_log: list[dict[str, Any]],
) -> dict[str, Any]:
    tracked_positions = account_state.get('open_positions', [])

    def key(position: dict[str, Any]) -> tuple[str, str]:
        outcome = position.get('position_side') or position.get('outcome') or ''
        return (position.get('market_slug') or '', outcome)

    tracked_keys = {key(pos) for pos in tracked_positions if key(pos)[0]}
    live_keys = {key(pos) for pos in live_positions if key(pos)[0]}
    closed_keys = {
        (entry.get('market_slug') or '', entry.get('outcome') or '')
        for entry in trade_log
        if entry.get('type') == 'trade_closed'
    }

    issues: list[str] = []

    for position_key in sorted(tracked_keys - live_keys):
        if position_key not in closed_keys:
            issues.append(f'missing closure record for {position_key[0]}:{position_key[1]}')

    for position_key in sorted(live_keys - tracked_keys):
        issues.append(f'live position missing from account_state for {position_key[0]}:{position_key[1]}')

    expected_open_exposure = round(sum(safe_float(pos.get('current_value')) for pos in live_positions), 8)
    recorded_open_exposure = round(safe_float(account_state.get('open_exposure')), 8)
    if abs(expected_open_exposure - recorded_open_exposure) > 0.05:
        issues.append(
            'open_exposure mismatch between account_state and live positions '
            f'({recorded_open_exposure} vs {expected_open_exposure})'
        )

    return {
        'ok': not issues,
        'issues': issues,
    }


def validate_decision(decision: dict[str, Any], context: dict[str, Any]) -> tuple[bool, str]:
    action = decision.get('action')
    allowed_actions = {'NO_ACTION', 'OPEN_POSITION', 'CLOSE_POSITION', 'REDUCE_POSITION'}
    if action not in allowed_actions:
        return False, f'Invalid action: {action}'

    polymarket = context['polymarket']
    account_state = context['account_state']
    markets = polymarket['active_btc_markets']
    positions = polymarket['positions']
    spot_price = context['binance']['spot_price']

    if action == 'OPEN_POSITION':
        reconciliation = context.get('reconciliation') or {}
        if not reconciliation.get('ok', True):
            issues = '; '.join(reconciliation.get('issues', [])[:2])
            return False, f'Reconciliation required before opening new position: {issues}'

        new_position = decision.get('new_position') or {}
        floor_position = decision.get('new_floor_position') or {}
        cash_available = polymarket['cash_balance_usdc']
        portfolio_value = cash_available + safe_float(account_state.get('open_exposure'))
        early_stage_cap = safe_float(account_state.get('early_stage_max_stake', 1.0))
        early_stage_threshold = safe_float(account_state.get('early_stage_threshold', 15.0))
        base_stake_pct = safe_float(account_state.get('base_stake_pct', 0.15))
        max_open = int(account_state.get('max_open_positions', 3))
        price_hit_opening = bool(new_position.get('should_open'))
        floor_opening = bool(floor_position.get('should_open'))
        active_positions = [pos for pos in positions if not is_slot_discarded(pos, account_state)]

        # Total active positions after this cycle must not exceed max_open_positions.
        # Discarded daily/weekly positions stay open, but no longer block a fresh slot.
        pending_opens = (1 if price_hit_opening else 0) + (1 if floor_opening else 0)
        if len(active_positions) + pending_opens > max_open:
            return False, f'Opening {pending_opens} active position(s) would exceed max_open_positions ({max_open})'

        if price_hit_opening:
            market = find_market_by_slug(markets, new_position.get('market_slug', ''))
            if not market:
                return False, 'Selected market slug not found among active BTC markets'
            outcome = new_position.get('outcome')
            if outcome not in market['outcomes']:
                return False, 'Selected outcome not valid for chosen market'
            max_entry_probability = safe_float(new_position.get('max_entry_probability'))
            live_probability = outcome_probability(market, outcome)
            if max_entry_probability <= 0 or max_entry_probability > 1:
                return False, 'Price-hit max_entry_probability must be between 0 and 1'
            if max_entry_probability < live_probability:
                return False, 'Price-hit max_entry_probability is below the current live market probability'
            stake_usd = safe_float(new_position.get('stake_usd'))
            if stake_usd <= 0 or stake_usd > cash_available:
                return False, 'Price-hit stake is invalid or exceeds available cash'
            if portfolio_value < early_stage_threshold and stake_usd > early_stage_cap:
                return False, f'Early-stage cap: max stake ${early_stage_cap} while portfolio < ${early_stage_threshold}'
            if portfolio_value >= early_stage_threshold:
                max_stake = round(cash_available * base_stake_pct, 2)
                if stake_usd > max_stake:
                    return False, f'Price-hit stake ${stake_usd} exceeds {base_stake_pct:.0%} of cash (max ${max_stake})'
            # Per-type slot: max 1 active daily, max 1 active weekly.
            # Discarded positions at <= discarded_probability_threshold no longer block the slot.
            mtype = market.get('market_type', 'daily')
            type_open = sum(
                1 for p in positions
                if infer_position_market_type(p) == mtype and not is_slot_discarded(p, account_state)
            )
            if type_open >= 1:
                return False, f'{mtype.capitalize()} price-hit active slot already occupied'
            duplicate = any(
                pos['market_slug'] == market['market_slug'] and pos['outcome'] == outcome
                for pos in positions
            )
            if duplicate:
                return False, 'Duplicate price-hit position already open'
            # Nearest-strike-first is a preference from the playbook, not a hard
            # validation veto. The model should usually choose the closest
            # reasonable strike, but a farther strike can still be valid when
            # the nearer one is too aggressively priced or otherwise not the
            # cleanest expression of the thesis.

        if floor_opening:
            floor_markets = polymarket.get('active_floor_markets', [])
            floor_market = find_market_by_slug(floor_markets, floor_position.get('market_slug', ''))
            if not floor_market:
                return False, 'Floor market slug not found among active floor markets'
            if floor_position.get('outcome', 'Yes') != 'Yes':
                return False, 'Floor positions must always bet Yes'
            floor_max_entry_probability = safe_float(floor_position.get('max_entry_probability'))
            floor_live_probability = outcome_probability(floor_market, 'Yes')
            if floor_max_entry_probability <= 0 or floor_max_entry_probability > 1:
                return False, 'Floor max_entry_probability must be between 0 and 1'
            if floor_max_entry_probability < floor_live_probability:
                return False, 'Floor max_entry_probability is below the current live market probability'
            floor_stake = safe_float(floor_position.get('stake_usd'))
            if floor_stake <= 0 or floor_stake > cash_available:
                return False, 'Floor stake is invalid or exceeds available cash'
            if portfolio_value < early_stage_threshold and floor_stake > early_stage_cap:
                return False, f'Early-stage cap applies to floor stake too'
            if portfolio_value >= early_stage_threshold:
                max_stake = round(cash_available * base_stake_pct, 2)
                if floor_stake > max_stake:
                    return False, f'Floor stake ${floor_stake} exceeds {base_stake_pct:.0%} of cash (max ${max_stake})'
            # Max 1 floor position open at a time
            floor_open_count = len(polymarket.get('open_floor_positions', []))
            max_floor = int(account_state.get('max_floor_positions', 1))
            if floor_open_count >= max_floor:
                return False, f'Floor position slot already occupied ({floor_open_count}/{max_floor})'
            duplicate_floor = any(pos['market_slug'] == floor_market['market_slug'] for pos in positions)
            if duplicate_floor:
                return False, 'Duplicate floor position already open'

    elif action in {'CLOSE_POSITION', 'REDUCE_POSITION'}:
        management = decision.get('position_management') or {}
        target_slug = management.get('target_market_slug', '')
        target_outcome = management.get('target_outcome', '')
        match = next((pos for pos in positions if pos['market_slug'] == target_slug and pos['outcome'] == target_outcome), None)
        if not match:
            return False, 'Requested managed position is not currently open'
    return True, 'ok'


def token_id_for_outcome(market: dict[str, Any], outcome: str) -> str:
    token_id = market['outcomes'][outcome]['token_id']
    if not token_id:
        raise RuntimeError(f'Missing token id for {market["market_slug"]} / {outcome}')
    return token_id


def prepare_and_send_order_via_phone(
    decision: dict[str, Any],
    markets: list[dict[str, Any]],
    telegram_token: str,
    telegram_chat_id: str,
    btc_price: float,
) -> dict[str, Any]:
    """Write order params to last_run_summary.json for the phone to sign and execute.

    The phone queries the live order book, builds the EIP-712 order, signs it with
    the private key, and POSTs to clob.polymarket.com using its residential IP.
    This avoids the datacenter IP geoblock and ensures the price is fresh at execution time.
    """
    new_pos = decision['new_position']
    market = find_market_by_slug(markets, new_pos['market_slug'])
    if not market:
        raise RuntimeError(f'Market not found: {new_pos["market_slug"]}')
    token_id = token_id_for_outcome(market, new_pos['outcome'])

    message = (
        f'\U0001f514 OPEN \u2192 {new_pos["outcome"]}\n'
        f'{market["question"]}\n'
        f'Stake: ${new_pos["stake_usd"]} | BTC ${btc_price:,.0f}'
    )
    requests.post(
        f'https://api.telegram.org/bot{telegram_token}/sendMessage',
        json={'chat_id': telegram_chat_id, 'text': message},
        timeout=30,
    )
    order = {
        'order_id': now_utc(),
        'status': 'pending_phone_execution',
        'type': 'OPEN_POSITION',
        'token_id': token_id,
        'side': 'BUY',
        'stake_usd': new_pos['stake_usd'],
        'max_entry_probability': safe_float(new_pos.get('max_entry_probability', 0.0)),
        'market': market['question'],
        'market_slug': new_pos['market_slug'],
        'outcome': new_pos['outcome'],
    }
    enqueue_pending_order(order)
    print(f'[execution] Order enqueued in pending_orders.json for phone execution.')
    return order


def force_bet(config: dict[str, Any], event_date: str, strike: int, outcome: str, stake: float) -> None:
    """Place a direct bet bypassing GPT. Used for testing execution and manual overrides."""
    from datetime import datetime as _dt
    _d = _dt.strptime(event_date, '%Y-%m-%d')
    event_slug = f'what-price-will-bitcoin-hit-on-{_d.strftime("%B").lower()}-{_d.day}'
    print(f'[force-bet] Fetching event: {event_slug}')
    response = requests.get(f'{GAMMA_HOST}/events/slug/{event_slug}', timeout=30)
    response.raise_for_status()
    event = response.json()

    market = None
    for raw in event.get('markets', []):
        parsed = parse_market(raw)
        if parsed and parsed['strike'] == strike and parsed['accepting_orders'] and not parsed['closed']:
            market = parsed
            break

    if not market:
        raise SystemExit(f'No open market found for strike ${strike:,} in {event_slug}')
    # Normalize outcome to match the market's casing (e.g. "NO" → "No", "YES" → "Yes")
    outcome_map = {k.upper(): k for k in market['outcomes']}
    outcome = outcome_map.get(outcome.upper(), outcome)
    if outcome not in market['outcomes']:
        raise SystemExit(f'Outcome "{outcome}" not found. Available: {list(market["outcomes"].keys())}')

    prob = safe_float(market['outcomes'][outcome].get('probability'))
    print(f'[force-bet] Market  : {market["question"]}')
    print(f'[force-bet] Outcome : {outcome}  probability={prob:.1%}')
    print(f'[force-bet] Stake   : ${stake}')

    decision = {
        'action': 'OPEN_POSITION',
        'confidence': 1.0,
        'summary': f'Force bet: {outcome} on {market["question"]} stake=${stake}',
        'rationale': '--force-bet manual override, no GPT analysis',
        'position_management': {
            'should_manage_existing': False,
            'target_market_slug': '',
            'target_outcome': '',
            'reason': 'none',
            'reduce_fraction': 0.5,
        },
        'new_position': {
            'should_open': True,
            'event_slug': event_slug,
            'market_slug': market['market_slug'],
            'outcome': outcome,
            'direction': 'bearish' if outcome == 'No' else 'bullish',
            'strike': strike,
            'stake_usd': stake,
            'max_entry_probability': 1.0,
        },
    }

    telegram_token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
    telegram_chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
    if not telegram_token or not telegram_chat_id:
        raise SystemExit('TELEGRAM_BOT_TOKEN and TELEGRAM_PERSONAL_CHAT_ID must be set for phone execution')

    print('[force-bet] Preparing order params for phone execution...')
    execution_details = prepare_and_send_order_via_phone(
        decision, [market], telegram_token, telegram_chat_id, btc_price=0,
    )
    print(f'[force-bet] {execution_details}')
    print('[force-bet] Run the phone executor now: python ~/polymarket_executor.py')

    run_summary = {
        'timestamp': now_utc(),
        'dry_run': False,
        'decision': decision,
        'validation': {'ok': True, 'message': 'force-bet bypass'},
        'execution': {'performed': True, 'details': execution_details},
        'binance_spot_price': None,
        'positions_before': 0,
        'positions_after': 0,
    }
    append_trade_log({'timestamp': now_utc(), 'type': 'force_bet', **run_summary})
    save_json(LAST_RUN_SUMMARY_PATH, run_summary)
    write_summary_markdown(run_summary)
    print(json.dumps(run_summary, ensure_ascii=False, indent=2))


def execute_open_position(client: ClobClient, decision: dict[str, Any], markets: list[dict[str, Any]]) -> dict[str, Any]:
    new_position = decision['new_position']
    market = find_market_by_slug(markets, new_position['market_slug'])
    token_id = token_id_for_outcome(market, new_position['outcome'])
    order = client.create_market_order(
        MarketOrderArgs(
            token_id=token_id,
            amount=safe_float(new_position['stake_usd']),
            side=BUY,
            order_type=OrderType.FOK,
        )
    )
    response = client.post_order(order, OrderType.FOK)
    return {
        'type': 'OPEN_POSITION',
        'market_slug': market['market_slug'],
        'outcome': new_position['outcome'],
        'stake_usd': safe_float(new_position['stake_usd']),
        'response': response,
    }


def prepare_close_or_reduce_via_phone(
    decision: dict[str, Any],
    positions: list[dict[str, Any]],
    telegram_token: str,
    telegram_chat_id: str,
    btc_price: float,
) -> dict[str, Any]:
    """Write SELL order params for the phone to sign and execute.

    The phone queries the live order book, builds the EIP-712 SELL order, signs it
    with the private key, and POSTs to clob.polymarket.com using its residential IP.
    No signing happens on the server — price is fresh at execution time.
    """
    management = decision['position_management']
    target = next(
        pos for pos in positions
        if pos['market_slug'] == management['target_market_slug'] and pos['outcome'] == management['target_outcome']
    )
    fraction = 1.0 if decision['action'] == 'CLOSE_POSITION' else min(max(safe_float(management.get('reduce_fraction', 0.5)), 0.05), 0.95)
    amount = target['size'] * fraction

    action_label = 'CLOSE' if decision['action'] == 'CLOSE_POSITION' else f'REDUCE {fraction:.0%}'
    message = (
        f'\U0001f514 {action_label} \u2192 {target["outcome"]}\n'
        f'{target["market_slug"]}\n'
        f'Size: {amount:.4f} | BTC ${btc_price:,.0f}'
    )
    requests.post(
        f'https://api.telegram.org/bot{telegram_token}/sendMessage',
        json={'chat_id': telegram_chat_id, 'text': message},
        timeout=30,
    )
    order = {
        'order_id': now_utc(),
        'status': 'pending_phone_execution',
        'type': decision['action'],
        'token_id': target['asset'],
        'side': 'SELL',
        'amount': amount,
        'market_slug': target['market_slug'],
        'outcome': target['outcome'],
        'fraction': fraction,
    }
    enqueue_pending_order(order)
    print(f'[execution] SELL order enqueued in pending_orders.json for phone execution.')
    return order


def sync_account_state(existing: dict[str, Any], balance_usdc: float, positions: list[dict[str, Any]]) -> dict[str, Any]:
    state = dict(existing)
    discard_threshold = discarded_probability_threshold(state)
    state['cash_available'] = balance_usdc
    state['open_exposure'] = round(sum(pos['current_value'] for pos in positions), 8)
    state['open_positions'] = [
        {
            'event_slug': pos['event_slug'],
            'market_slug': pos['market_slug'],
            'market_title': pos['market_title'],
            'position_side': pos['outcome'],
            'token_id': pos['asset'],
            'shares': pos['size'],
            'avg_price': pos['avg_price'],
            'entry_cost_usd': pos['initial_value'],
            'current_price': pos['cur_price'],
            'current_value_usd': pos['current_value'],
            'cash_pnl_usd': pos['cash_pnl'],
            'status': 'open',
            'slot_status': (
                'discarded_for_slot'
                if infer_position_market_type(pos) in {'daily', 'weekly'} and safe_float(pos.get('cur_price')) <= discard_threshold
                else 'active'
            ),
        }
        for pos in positions
    ]
    state['last_synced_at'] = now_utc()
    return state


def notify_claimable_positions(positions: list[dict[str, Any]], config: dict[str, str]) -> None:
    """Send a Telegram notification for any won positions that haven't been notified yet."""
    token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
    if not token or not chat_id:
        return

    already_notified: list[str] = load_json(NOTIFIED_CLAIMS_PATH, [])
    new_notified = list(already_notified)

    for pos in positions:
        if safe_float(pos.get('cur_price')) < 0.99:
            continue
        key = f"{pos.get('market_slug')}:{pos.get('outcome')}"
        if key in already_notified:
            continue
        pnl = safe_float(pos.get('cash_pnl'))
        msg = (
            f'\U0001f3c6 CLAIM AVAILABLE\n'
            f'{pos.get("market_title", pos.get("market_slug"))}\n'
            f'Outcome: {pos.get("outcome")} \u2192 WON\n'
            f'PnL: +${pnl:.4f}\n'
            f'Go to Polymarket to redeem.'
        )
        try:
            requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': msg},
                timeout=15,
            )
            new_notified.append(key)
            print(f'[claim] Notified: {key}')
        except Exception as exc:
            print(f'[claim] Telegram error: {exc}')

    if new_notified != already_notified:
        save_json(NOTIFIED_CLAIMS_PATH, new_notified)


def append_trade_log(entry: dict[str, Any]) -> None:
    log = load_json(TRADE_LOG_PATH, [])
    log.append(entry)
    save_json(TRADE_LOG_PATH, log)


def enqueue_pending_order(order: dict[str, Any]) -> None:
    """Append an order to pending_orders.json. Prunes entries older than 12 hours."""
    queue: list[dict[str, Any]] = load_json(PENDING_ORDERS_PATH, [])
    cutoff = (datetime.now(UTC) - timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%SZ')
    queue = [o for o in queue if o.get('order_id', '') >= cutoff]
    queue.append(order)
    save_json(PENDING_ORDERS_PATH, queue)


def write_summary_markdown(summary: dict[str, Any]) -> None:
    lines = [
        '# Polymarket Operator Run',
        '',
        f"- Timestamp: {summary['timestamp']}",
        f"- Dry run: {summary['dry_run']}",
        f"- BTC price: {summary['binance_spot_price']}",
        f"- Decision action: {summary['decision'].get('action')}",
        f"- Decision summary: {summary['decision'].get('summary')}",
        f"- Validation: {summary['validation']['ok']} ({summary['validation']['message']})",
        f"- Open positions before: {summary['positions_before']}",
        f"- Open positions after: {summary['positions_after']}",
        '',
        '## Execution',
        '',
        '```json',
        json.dumps(summary['execution'], ensure_ascii=False, indent=2),
        '```',
    ]
    WORKFLOW_SUMMARY_PATH.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Run one unattended Polymarket operator cycle')
    parser.add_argument('--model', default='gpt-5.4')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--decision-file', help='Use a local JSON file instead of calling copilot')
    parser.add_argument(
        '--force-bet', nargs=4, metavar=('EVENT_DATE', 'STRIKE', 'OUTCOME', 'STAKE'),
        help='Bypass GPT and place a direct bet. Example: --force-bet march-27 69000 No 1.0',
    )
    args = parser.parse_args()

    subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'pull', '--ff-only', 'origin', 'main'],
        capture_output=True, timeout=30,
    )

    config = load_env()
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
        force_bet(config, event_date, int(strike_str), outcome, float(stake_str))
        return

    context = build_context_snapshot(config)
    notify_claimable_positions(context['polymarket']['positions'], config)
    prompt = render_prompt(context)

    if args.decision_file:
        decision = load_decision_from_file(Path(args.decision_file))
    else:
        decision = run_copilot(prompt, args.model)

    ok, message = validate_decision(decision, context)
    execution: dict[str, Any] = {'performed': False, 'details': None}
    positions_before = len(context['polymarket']['positions'])
    client = build_private_client(config)

    if ok and not args.dry_run and decision.get('action') != 'NO_ACTION':
        if decision['action'] == 'OPEN_POSITION':
            telegram_token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
            telegram_chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
            execution['details'] = []
            # Price-hit position (reach/dip markets)
            if (decision.get('new_position') or {}).get('should_open'):
                order = prepare_and_send_order_via_phone(
                    decision, context['polymarket']['active_btc_markets'],
                    telegram_token, telegram_chat_id, context['binance']['spot_price'],
                )
                execution['details'].append(order)
            # Floor position (bitcoin-above-X markets)
            if (decision.get('new_floor_position') or {}).get('should_open'):
                floor_order = prepare_and_send_order_via_phone(
                    {'new_position': decision['new_floor_position']},
                    context['polymarket']['active_floor_markets'],
                    telegram_token, telegram_chat_id, context['binance']['spot_price'],
                )
                execution['details'].append(floor_order)
            execution['performed'] = bool(execution['details'])
        elif decision['action'] in {'CLOSE_POSITION', 'REDUCE_POSITION'}:
            telegram_token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
            telegram_chat_id = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
            execution['details'] = prepare_close_or_reduce_via_phone(
                decision, context['polymarket']['positions'],
                telegram_token, telegram_chat_id, context['binance']['spot_price'],
            )
            execution['performed'] = True
    elif not ok:
        execution['details'] = {'rejected': message}

    refreshed_positions = fetch_positions(config)
    refreshed_balance = fetch_balance_allowance(client, config)
    balance_usdc = safe_float(refreshed_balance.get('balance')) / 1_000_000
    account_state = sync_account_state(context['account_state'], balance_usdc, refreshed_positions)
    save_json(ACCOUNT_STATE_PATH, account_state)

    log_entry = {
        'timestamp': now_utc(),
        'type': 'cycle_run',
        'dry_run': args.dry_run,
        'decision': decision,
        'validation': {'ok': ok, 'message': message},
        'execution': execution,
        'binance_spot_price': context['binance']['spot_price'],
        'positions_before': positions_before,
        'positions_after': len(refreshed_positions),
    }
    append_trade_log(log_entry)

    run_summary = {
        'timestamp': log_entry['timestamp'],
        'dry_run': args.dry_run,
        'decision': decision,
        'validation': {'ok': ok, 'message': message},
        'execution': execution,
        'binance_spot_price': context['binance']['spot_price'],
        'positions_before': positions_before,
        'positions_after': len(refreshed_positions),
    }
    save_json(LAST_RUN_SUMMARY_PATH, run_summary)
    write_summary_markdown(run_summary)

    # Send cycle summary to personal Telegram chat
    _token = config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN', '')
    _chat = config.get('TELEGRAM_PERSONAL_CHAT_ID') or os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
    if _token and _chat and not args.dry_run:
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
            requests.post(
                f'https://api.telegram.org/bot{_token}/sendMessage',
                json={'chat_id': _chat, 'text': msg},
                timeout=15,
            )
        except Exception as exc:
            print(f'[telegram] Failed to send cycle summary: {exc}')

    print(json.dumps(run_summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(exc.stdout)
        print(exc.stderr, file=sys.stderr)
        raise
