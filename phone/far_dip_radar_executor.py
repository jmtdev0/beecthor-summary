#!/usr/bin/env python3
"""
Mechanical phone-side executor for the far_dip_radar strategy.

It runs without an LLM: during the 06:00-08:00 UTC window it looks for the
objective daily dip-NO candidate defined by the strategy rules and executes at
most one BUY per UTC window.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

import log_client
from polymarket_executor import (
    ENV_FILE,
    MarketResolvedException,
    execute_order,
    fetch_live_positions,
    fetch_recent_activity,
    find_recent_matching_trade,
    get_market_price,
    refresh_runtime_config,
    resolve_live_position,
)

SOURCE = 'phone.far_dip_radar'
STRATEGY = 'far_dip_radar'
GAMMA_HOST = 'https://gamma-api.polymarket.com'
BINANCE_TICKER_URL = 'https://api.binance.com/api/v3/ticker/price'
STATE_FILE = Path.home() / '.far_dip_radar_window_state.json'
WINDOW_START_HOUR = 6
WINDOW_END_HOUR = 8
MIN_DISTANCE_USD = 1500.0
MIN_NO_PROBABILITY = 0.25
MAX_NO_PROBABILITY = 0.714
STAKE_USD = 1.0
MONTH_SLUGS = [
    'january',
    'february',
    'march',
    'april',
    'may',
    'june',
    'july',
    'august',
    'september',
    'october',
    'november',
    'december',
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Phone-side far_dip_radar executor.')
    parser.add_argument('--dry-run', action='store_true', help='Evaluate and build the order without posting it.')
    parser.add_argument('--ignore-window', action='store_true', help='Run even outside the 06:00-08:00 UTC window.')
    parser.add_argument('--ignore-strategy', action='store_true', help='Run even if the server strategy switch is not far_dip_radar.')
    parser.add_argument('--env-file', default=str(ENV_FILE), help='Path to the phone .env file.')
    return parser.parse_args()


def log_event(event_type: str, message: str, *, level: str = 'info', payload: dict[str, Any] | None = None) -> None:
    print(f'[{SOURCE}] {event_type}: {message}')
    log_client.send_server_log(SOURCE, event_type, message, level=level, payload=payload or {})


def safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def decode_json_list(value: object) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def current_window(now: datetime) -> tuple[bool, str]:
    start = now.replace(hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
    end = now.replace(hour=WINDOW_END_HOUR, minute=0, second=0, microsecond=0)
    window_id = f'{now:%Y-%m-%d}T{WINDOW_START_HOUR:02d}-{WINDOW_END_HOUR:02d}Z'
    return start <= now < end, window_id


def load_state() -> dict[str, Any]:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')


def window_already_executed(window_id: str) -> dict[str, Any] | None:
    windows = load_state().get('executed_windows') or {}
    item = windows.get(window_id)
    return item if isinstance(item, dict) else None


def mark_window_executed(window_id: str, order: dict[str, Any], evidence: dict[str, Any]) -> None:
    state = load_state()
    windows = state.setdefault('executed_windows', {})
    windows[window_id] = {
        'executed_at': datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'order_id': order.get('order_id'),
        'market_slug': order.get('market_slug'),
        'outcome': order.get('outcome'),
        'stake_usd': order.get('stake_usd'),
        'evidence': evidence,
    }

    # Keep the local file tiny; this is a dedup aid, not an audit log.
    if len(windows) > 30:
        for key in sorted(windows)[:-30]:
            windows.pop(key, None)
    save_state(state)


def strategy_state_url() -> str:
    explicit = os.environ.get('SERVER_STRATEGY_API_URL', '').strip()
    if explicit:
        return explicit
    log_url = log_client.LOG_API_URL
    if log_url.endswith('/api/mobile-log'):
        return f'{log_url[:-len("/api/mobile-log")]}/api/mobile/strategy-state'
    return ''


def strategy_is_active() -> bool:
    url = strategy_state_url()
    secret = os.environ.get('SERVER_STRATEGY_API_SECRET', '').strip() or log_client.LOG_API_SECRET
    if not url or not secret:
        log_event(
            'strategy_check_skipped',
            'Cannot verify active strategy because the server strategy endpoint is not configured',
            level='warning',
            payload={'url_configured': bool(url), 'secret_configured': bool(secret)},
        )
        return os.environ.get('FAR_DIP_RADAR_ASSUME_ACTIVE_IF_STATE_UNAVAILABLE') == '1'

    try:
        response = requests.get(url, headers={'X-Log-Secret': secret}, timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        log_event(
            'strategy_check_failed',
            'Cannot verify active strategy from server',
            level='warning',
            payload={'error': str(exc), 'url': url},
        )
        return os.environ.get('FAR_DIP_RADAR_ASSUME_ACTIVE_IF_STATE_UNAVAILABLE') == '1'

    active = str(payload.get('active_strategy') or '').strip()
    if active != STRATEGY:
        log_event(
            'run_skipped',
            f'Active strategy is {active or "unknown"}, not {STRATEGY}',
            payload={'active_strategy': active},
        )
        return False
    return True


def event_slug_for_day(now: datetime) -> str:
    month = MONTH_SLUGS[now.month - 1]
    return f'what-price-will-bitcoin-hit-on-{month}-{now.day}'


def day_slug_fragment(now: datetime) -> str:
    month = MONTH_SLUGS[now.month - 1]
    return f'on-{month}-{now.day}'


def fetch_spot_price() -> float:
    response = requests.get(BINANCE_TICKER_URL, params={'symbol': 'BTCUSDT'}, timeout=20)
    response.raise_for_status()
    return safe_float(response.json().get('price'))


def parse_market(record: dict[str, Any], fallback_event_slug: str) -> dict[str, Any] | None:
    question = str(record.get('question') or '')
    title = question.lower()
    if 'bitcoin' not in title or 'dip to $' not in title:
        return None

    match = re.search(r'\$([0-9,]+)', question)
    if not match:
        return None
    strike = int(match.group(1).replace(',', ''))

    outcomes = decode_json_list(record.get('outcomes'))
    outcome_prices = [safe_float(item) for item in decode_json_list(record.get('outcomePrices'))]
    token_ids = [str(item) for item in decode_json_list(record.get('clobTokenIds'))]
    outcome_map: dict[str, dict[str, Any]] = {}
    for idx, outcome in enumerate(outcomes):
        outcome_name = str(outcome)
        outcome_map[outcome_name] = {
            'probability': outcome_prices[idx] if idx < len(outcome_prices) else None,
            'token_id': token_ids[idx] if idx < len(token_ids) else None,
        }

    return {
        'event_slug': record.get('eventSlug') or fallback_event_slug,
        'market_slug': record.get('slug') or '',
        'question': question,
        'strike': strike,
        'active': bool(record.get('active')),
        'closed': bool(record.get('closed')),
        'accepting_orders': bool(record.get('acceptingOrders')),
        'outcomes': outcome_map,
    }


def fetch_daily_dip_markets(now: datetime) -> list[dict[str, Any]]:
    event_slug = event_slug_for_day(now)
    response = requests.get(f'{GAMMA_HOST}/events/slug/{event_slug}', timeout=30)
    if response.status_code == 404:
        log_event('run_skipped', 'Daily BTC event is not available on Gamma', payload={'event_slug': event_slug})
        return []
    response.raise_for_status()
    event = response.json()

    markets: list[dict[str, Any]] = []
    for item in event.get('markets', []):
        parsed = parse_market(item, event_slug)
        if not parsed:
            continue
        if parsed['closed'] or not parsed['accepting_orders']:
            continue
        markets.append(parsed)
    return markets


def outcome_probability(market: dict[str, Any], outcome: str) -> float:
    return safe_float((market.get('outcomes') or {}).get(outcome, {}).get('probability'))


def outcome_token_id(market: dict[str, Any], outcome: str) -> str:
    return str((market.get('outcomes') or {}).get(outcome, {}).get('token_id') or '')


def build_candidates(markets: list[dict[str, Any]], spot_price: float) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for market in markets:
        strike = safe_float(market.get('strike'))
        if strike <= 0.0 or spot_price <= 0.0:
            continue
        distance = round(spot_price - strike, 2)
        if distance < MIN_DISTANCE_USD:
            continue

        no_probability = outcome_probability(market, 'No')
        if not (MIN_NO_PROBABILITY <= no_probability <= MAX_NO_PROBABILITY):
            continue

        token_id = outcome_token_id(market, 'No')
        if not token_id:
            continue

        candidate_id = f'{STRATEGY}:{market["market_slug"]}:No'
        candidates.append({
            'candidate_id': candidate_id,
            'event_slug': market.get('event_slug', ''),
            'market_slug': market.get('market_slug', ''),
            'question': market.get('question', ''),
            'outcome': 'No',
            'token_id': token_id,
            'strike': strike,
            'spot_price': spot_price,
            'distance_above_strike_usd': distance,
            'no_probability': round(no_probability, 4),
        })
    candidates.sort(key=lambda item: (item['no_probability'], -item['distance_above_strike_usd']))
    return candidates


def first_live_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for candidate in candidates:
        try:
            live_price = get_market_price(candidate['token_id'], 'BUY', STAKE_USD)
        except MarketResolvedException as exc:
            log_event(
                'candidate_skipped',
                'Candidate skipped because the order book is already resolved',
                payload={'market_slug': candidate['market_slug'], 'error': str(exc)},
            )
            continue
        except Exception as exc:
            log_event(
                'candidate_skipped',
                'Candidate skipped because live book price could not be fetched',
                level='warning',
                payload={'market_slug': candidate['market_slug'], 'error': str(exc)},
            )
            continue

        candidate = dict(candidate)
        candidate['live_no_price'] = round(live_price, 4)
        if MIN_NO_PROBABILITY <= live_price <= MAX_NO_PROBABILITY:
            return candidate

        log_event(
            'candidate_skipped',
            'Candidate no longer satisfies live NO price bounds',
            payload={
                'market_slug': candidate['market_slug'],
                'gamma_no_probability': candidate['no_probability'],
                'live_no_price': round(live_price, 4),
                'min_no_probability': MIN_NO_PROBABILITY,
                'max_no_probability': MAX_NO_PROBABILITY,
            },
        )
    return None


def build_order(candidate: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        'order_id': now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
        'type': 'OPEN_POSITION',
        'side': 'BUY',
        'market': candidate['question'],
        'market_slug': candidate['market_slug'],
        'event_slug': candidate['event_slug'],
        'outcome': 'No',
        'token_id': candidate['token_id'],
        'amount': STAKE_USD,
        'stake_usd': STAKE_USD,
        'market_type': 'daily',
        'position_kind': 'price_hit',
        'slot_name': STRATEGY,
        'strategy': STRATEGY,
        'strategy_candidate_id': candidate['candidate_id'],
        'strategy_reason': 'far_dip_radar objective candidate selected by phone 5-minute radar',
        'beecthor_aligned': False,
        'momentum_confirmed': True,
        'expiry_validity': 'acceptable',
        'max_entry_probability': MAX_NO_PROBABILITY,
        'status': 'phone_direct_execution',
        'created_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'metadata': {
            'spot_price': candidate['spot_price'],
            'strike': candidate['strike'],
            'distance_above_strike_usd': candidate['distance_above_strike_usd'],
            'gamma_no_probability': candidate['no_probability'],
            'live_no_price': candidate.get('live_no_price'),
        },
    }


def recent_window_trade(now: datetime) -> dict[str, Any] | None:
    start = now.replace(hour=WINDOW_START_HOUR, minute=0, second=0, microsecond=0)
    end = now.replace(hour=WINDOW_END_HOUR, minute=0, second=0, microsecond=0)
    fragment = day_slug_fragment(now)

    try:
        activity = fetch_recent_activity(limit=50)
    except Exception as exc:
        log_event('activity_check_failed', 'Could not inspect recent activity', level='warning', payload={'error': str(exc)})
        return None

    for item in activity:
        if item.get('type') != 'TRADE' or item.get('side') != 'BUY' or item.get('outcome') != 'No':
            continue
        slug = str(item.get('slug') or '')
        if fragment not in slug or 'dip-to' not in slug:
            continue
        try:
            ts = datetime.fromtimestamp(int(item.get('timestamp')), UTC)
        except (TypeError, ValueError, OSError):
            continue
        if start <= ts < end:
            return item
    return None


def live_far_dip_position(now: datetime) -> dict[str, Any] | None:
    fragment = day_slug_fragment(now)
    try:
        positions = fetch_live_positions()
    except Exception as exc:
        log_event('position_check_failed', 'Could not inspect live positions', level='warning', payload={'error': str(exc)})
        return None

    for item in positions:
        slug = str(item.get('slug') or '')
        if fragment in slug and 'dip-to' in slug and item.get('outcome') == 'No':
            return item
    return None


def validate_environment() -> bool:
    required = [
        'POLY_API_KEY',
        'POLY_API_SECRET',
        'POLY_API_PASSPHRASE',
        'POLY_FUNDER',
        'POLY_SIGNER_ADDRESS',
        'POLY_PRIVATE_KEY',
    ]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        log_event('run_failed', 'Missing required Polymarket environment variables', level='error', payload={'missing': missing})
        return False
    return True


def main() -> int:
    args = parse_args()
    load_dotenv(args.env_file, override=True)
    refresh_runtime_config()
    log_client.refresh_log_client_config()

    now = datetime.now(UTC)
    in_window, window_id = current_window(now)
    log_event(
        'run_started',
        'far_dip_radar mechanical sweep started',
        payload={'utc_now': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'window_id': window_id, 'dry_run': args.dry_run},
    )

    if not args.ignore_window and not in_window:
        log_event('run_skipped', 'Current UTC time is outside the 06:00-08:00 far_dip_radar window', payload={'window_id': window_id})
        return 0

    existing_window = window_already_executed(window_id)
    if existing_window:
        log_event('run_skipped', 'This far_dip_radar window already has an executed order', payload={'window_id': window_id, 'state': existing_window})
        return 0

    if not args.ignore_strategy and not strategy_is_active():
        return 0

    if not validate_environment():
        return 1

    recent_trade = recent_window_trade(now)
    if recent_trade:
        log_event('run_skipped', 'A matching daily dip-NO BUY already happened in this UTC window', payload={'window_id': window_id, 'trade': recent_trade})
        return 0

    existing_position = live_far_dip_position(now)
    if existing_position:
        log_event('run_skipped', 'A matching daily dip-NO live position already exists today', payload={'window_id': window_id, 'position': existing_position})
        return 0

    try:
        spot_price = fetch_spot_price()
        markets = fetch_daily_dip_markets(now)
    except Exception as exc:
        log_event('run_failed', 'Failed to fetch market inputs', level='error', payload={'error': str(exc)})
        return 1

    candidates = build_candidates(markets, spot_price)
    if not candidates:
        log_event(
            'no_candidate',
            'No far_dip_radar candidate satisfies the Gamma rules',
            payload={
                'spot_price': spot_price,
                'markets_checked': len(markets),
                'min_distance_usd': MIN_DISTANCE_USD,
                'min_no_probability': MIN_NO_PROBABILITY,
                'max_no_probability': MAX_NO_PROBABILITY,
            },
        )
        return 0

    candidate = first_live_candidate(candidates)
    if not candidate:
        log_event('no_candidate', 'No far_dip_radar candidate satisfies the live order-book rules', payload={'candidate_count': len(candidates)})
        return 0

    order = build_order(candidate)
    log_event(
        'candidate_selected',
        'Selected far_dip_radar candidate for direct phone execution',
        payload={'window_id': window_id, 'order': order},
    )

    if args.dry_run:
        execute_order(order, dry_run=True)
        log_event('dry_run_completed', 'Dry run built a valid far_dip_radar order without executing it', payload={'window_id': window_id, 'order': order})
        return 0

    executed = execute_order(order, dry_run=False)
    if not executed:
        log_event('order_failed', 'Direct far_dip_radar order failed', level='error', payload={'window_id': window_id, 'order': order})
        return 1

    evidence: dict[str, Any] = {}
    matching_trade = find_recent_matching_trade(order)
    if matching_trade:
        evidence['recent_trade'] = matching_trade
    matching_position = resolve_live_position(order)
    if matching_position:
        evidence['live_position'] = matching_position

    if evidence:
        mark_window_executed(window_id, order, evidence)
        log_event('order_recorded', 'far_dip_radar window marked as executed', payload={'window_id': window_id, 'order': order, 'evidence': evidence})
    else:
        log_event(
            'order_unconfirmed',
            'Executor returned success but no recent trade/live position evidence was found yet; next sweep may reconcile it',
            level='warning',
            payload={'window_id': window_id, 'order': order},
        )

    return 0


if __name__ == '__main__':
    sys.exit(main())
