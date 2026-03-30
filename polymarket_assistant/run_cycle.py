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
TRANSCRIPTS_DIR = REPO_ROOT / 'transcripts'
ANALYSES_LOG_PATH = REPO_ROOT / 'analyses_log.json'
PLAYBOOK_PATH = ASSISTANT_DIR / 'PLAYBOOK.md'
PROMPT_TEMPLATE_PATH = ASSISTANT_DIR / 'copilot_prompt.md'
ACCOUNT_STATE_PATH = ASSISTANT_DIR / 'account_state.json'
TRADE_LOG_PATH = ASSISTANT_DIR / 'trade_log.json'
LAST_RUN_SUMMARY_PATH = ASSISTANT_DIR / 'last_run_summary.json'
WORKFLOW_SUMMARY_PATH = ASSISTANT_DIR / 'last_run_summary.md'
NOTIFIED_CLAIMS_PATH = ASSISTANT_DIR / 'notified_claims.json'
PENDING_ORDERS_PATH = ASSISTANT_DIR / 'pending_orders.json'
HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137
GAMMA_HOST = 'https://gamma-api.polymarket.com'
DATA_API_HOST = 'https://data-api.polymarket.com'
BINANCE_TICKER_URL = 'https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT'
BINANCE_STATS_URL = 'https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT'
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


def fetch_binance_snapshot() -> dict[str, Any]:
    ticker = requests.get(BINANCE_TICKER_URL, timeout=20)
    ticker.raise_for_status()
    stats = requests.get(BINANCE_STATS_URL, timeout=20)
    stats.raise_for_status()
    ticker_json = ticker.json()
    stats_json = stats.json()
    return {
        'symbol': ticker_json.get('symbol'),
        'spot_price': safe_float(ticker_json.get('price')),
        'price_change_percent_24h': safe_float(stats_json.get('priceChangePercent')),
        'high_24h': safe_float(stats_json.get('highPrice')),
        'low_24h': safe_float(stats_json.get('lowPrice')),
        'volume_24h': safe_float(stats_json.get('volume')),
    }


def parse_market(record: dict[str, Any]) -> dict[str, Any] | None:
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
    event_slug = record.get('eventSlug', '')
    if '-on-' in event_slug:
        market_type = 'daily'
    else:
        market_type = 'weekly'
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
                parsed = parse_market(item)
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
    normalized = []
    for item in positions:
        size = safe_float(item.get('size'))
        if size <= 0:
            continue
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
            'end_date': item.get('endDate'),
        })
    return normalized


def fetch_balance_allowance(client: ClobClient, config: dict[str, str]) -> dict[str, Any]:
    return client.get_balance_allowance(
        BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=int(config.get('POLY_SIGNATURE_TYPE', '1')),
        )
    )


def build_context_snapshot(config: dict[str, str]) -> dict[str, Any]:
    client = build_private_client(config)
    account_state = load_json(ACCOUNT_STATE_PATH, {})
    trade_log = load_json(TRADE_LOG_PATH, [])
    positions = fetch_positions(config)
    balance = fetch_balance_allowance(client, config)
    orders = client.get_orders()
    return {
        'playbook': PLAYBOOK_PATH.read_text(encoding='utf-8'),
        'recent_transcripts': read_recent_transcripts(),
        'recent_summaries': read_recent_summaries(),
        'account_state': account_state,
        'recent_trade_log': trade_log[-8:],
        'binance': fetch_binance_snapshot(),
        'polymarket': {
            'cash_balance_usdc': safe_float(balance.get('balance')) / 1_000_000,
            'allowances': balance.get('allowances', {}),
            'open_orders': orders,
            'positions': positions,
            'active_btc_markets': fetch_active_btc_markets(),
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
        new_position = decision.get('new_position') or {}
        market = find_market_by_slug(markets, new_position.get('market_slug', ''))
        if not market:
            return False, 'Selected market slug not found among active BTC markets'
        outcome = new_position.get('outcome')
        if outcome not in market['outcomes']:
            return False, 'Selected outcome not valid for chosen market'
        probability = outcome_probability(market, outcome)
        if probability < safe_float(account_state.get('min_entry_probability', 0.3)):
            return False, f'Outcome probability {probability:.4f} below configured minimum'
        stake_usd = safe_float(new_position.get('stake_usd'))
        cash_available = polymarket['cash_balance_usdc']
        if stake_usd <= 0 or stake_usd > cash_available:
            return False, 'Stake is invalid or exceeds available cash'
        portfolio_value = cash_available + safe_float(account_state.get('open_exposure'))
        early_stage_cap = safe_float(account_state.get('early_stage_max_stake', 1.0))
        early_stage_threshold = safe_float(account_state.get('early_stage_threshold', 15.0))
        if portfolio_value < early_stage_threshold and stake_usd > early_stage_cap:
            return False, f'Early-stage cap: max stake ${early_stage_cap} while portfolio < ${early_stage_threshold}'
        if len(positions) >= int(account_state.get('max_open_positions', 2)):
            return False, 'Maximum number of open positions reached'
        duplicate = any(
            pos['market_slug'] == market['market_slug'] and pos['outcome'] == outcome
            for pos in positions
        )
        if duplicate:
            return False, 'Duplicate position already open'
        if not nearest_strike_ok(market, markets, spot_price):
            return False, 'Nearest-strike-first rule rejected the proposed market'
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
            execution['details'] = prepare_and_send_order_via_phone(
                decision, context['polymarket']['active_btc_markets'],
                telegram_token, telegram_chat_id, context['binance']['spot_price'],
            )
            execution['performed'] = True
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
