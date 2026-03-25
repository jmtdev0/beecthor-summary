#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests
from dotenv import dotenv_values
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import MarketOrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137
GAMMA_HOST = 'https://gamma-api.polymarket.com'
ENV_PATH = Path(__file__).resolve().parent / '.env'


def load_env() -> dict[str, str]:
    data = {
        key: value
        for key, value in dotenv_values(ENV_PATH).items()
        if value is not None and str(value).strip()
    }
    return {key: str(value).strip() for key, value in data.items()}


def build_client(config: dict[str, str]) -> ClobClient:
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


def fetch_event(event_slug: str) -> dict:
    response = requests.get(f'{GAMMA_HOST}/events/slug/{event_slug}', timeout=20)
    response.raise_for_status()
    return response.json()


def find_market(event: dict, threshold: int) -> dict:
    target = f'${threshold:,.0f}'
    for market in event.get('markets', []):
        if target in market.get('question', ''):
            return market
    raise SystemExit(f'No market found for threshold {target}')


def extract_token_id(market: dict, outcome: str) -> str:
    outcomes = json.loads(market['outcomes'])
    token_ids = json.loads(market['clobTokenIds'])
    mapping = dict(zip(outcomes, token_ids, strict=True))
    if outcome not in mapping:
        raise SystemExit(f'Outcome {outcome} not found. Available: {outcomes}')
    return mapping[outcome]


def main() -> None:
    parser = argparse.ArgumentParser(description='Prepare or execute a Polymarket price-hit order')
    parser.add_argument('--event-slug', required=True)
    parser.add_argument('--threshold', type=int, required=True)
    parser.add_argument('--outcome', choices=['Yes', 'No'], default='No')
    parser.add_argument('--amount', type=float, required=True, help='Collateral amount in USDC')
    parser.add_argument('--execute', action='store_true', help='Actually post the order')
    args = parser.parse_args()

    config = load_env()
    client = build_client(config)
    event = fetch_event(args.event_slug)
    market = find_market(event, args.threshold)
    token_id = extract_token_id(market, args.outcome)
    order_book = client.get_order_book(token_id)

    order_args = MarketOrderArgs(
        token_id=token_id,
        amount=args.amount,
        side=BUY,
        order_type=OrderType.FOK,
    )
    signed_order = client.create_market_order(order_args)
    inner_order = getattr(signed_order, 'order', None)

    print('=== Order Preview ===')
    print(f"Event: {event['title']}")
    print(f"Market: {market['question']}")
    print(f"Outcome: {args.outcome}")
    print(f"Token ID: {token_id}")
    print(f"Amount: ${args.amount:.2f}")
    print(f"Best bid: {market.get('bestBid')} | Best ask: {market.get('bestAsk')} | Last trade: {market.get('lastTradePrice')}")
    print(f"Order book bids: {len(getattr(order_book, 'bids', []))} | asks: {len(getattr(order_book, 'asks', []))}")
    print(f"Signed order price: {getattr(inner_order, 'price', 'n/a')}")
    print(f"Signed order maker amount: {getattr(inner_order, 'makerAmount', 'n/a')}")
    print(f"Signed order taker amount: {getattr(inner_order, 'takerAmount', 'n/a')}")

    if not args.execute:
        print('Preview only. Re-run with --execute to post the order.')
        return

    response = client.post_order(signed_order, OrderType.FOK)
    print('=== Order Response ===')
    print(response)


if __name__ == '__main__':
    main()
