#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137
ENV_PATH = Path(r'e:\Software\Coding\beecthor-summary\polymarket_assistant\.env')

config = {k: str(v).strip() for k, v in dotenv_values(ENV_PATH).items() if v is not None and str(v).strip()}
client = ClobClient(
    HOST,
    key=config['POLY_PRIVATE_KEY'],
    chain_id=CHAIN_ID,
    signature_type=int(config.get('POLY_SIGNATURE_TYPE', '2')),
    funder=config.get('POLY_FUNDER') or None,
)
creds = client.create_or_derive_api_creds()
client.set_api_creds(creds)

summary = {
    'signature_type': config.get('POLY_SIGNATURE_TYPE', '2'),
    'signer': config.get('POLY_SIGNER_ADDRESS', ''),
    'funder': config.get('POLY_FUNDER', ''),
}

try:
    balance = client.get_balance_allowance(
        BalanceAllowanceParams(
            asset_type=AssetType.COLLATERAL,
            signature_type=int(config.get('POLY_SIGNATURE_TYPE', '2')),
        )
    )
    summary['balance_check'] = 'ok'
    summary['balance_available'] = balance.get('balance') if isinstance(balance, dict) else 'n/a'
except Exception as exc:
    summary['balance_check'] = f'failed: {type(exc).__name__}: {exc}'

try:
    orders = client.get_orders()
    summary['orders_check'] = 'ok'
    if isinstance(orders, dict):
        data = orders.get('data')
        summary['orders_count'] = len(data) if isinstance(data, list) else 0
    elif isinstance(orders, list):
        summary['orders_count'] = len(orders)
    else:
        summary['orders_count'] = -1
except Exception as exc:
    summary['orders_check'] = f'failed: {type(exc).__name__}: {exc}'

print('Polymarket private smoke test complete.')
for key, value in summary.items():
    print(f'{key}: {value}')
