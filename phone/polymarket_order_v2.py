#!/usr/bin/env python3
"""
Shared Polymarket CLOB V2 order helpers for phone-side execution.
"""

from __future__ import annotations

import random
import time
from typing import Any

import requests
from eth_keys import keys as eth_keys
from eth_utils import keccak

CLOB_HOST = 'https://clob.polymarket.com'
ORDER_PATH = '/order'
VERSION_PATH = '/version'
ORDER_VERSION_MISMATCH = 'order_version_mismatch'

CLOB_ORDER_VERSION = 2
EXCHANGE_ADDRESS_V2 = '0xE111180000d2663C0091e4f400237545B87B996B'
CHAIN_ID = 137
SIGNATURE_TYPE = 1  # POLY_PROXY
ZERO_BYTES32_HEX = '0x' + ('00' * 32)
DOMAIN_TYPEHASH = keccak(
    text='EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)'
)
ORDER_TYPEHASH = keccak(
    text=(
        'Order(uint256 salt,address maker,address signer,uint256 tokenId,uint256 makerAmount,'
        'uint256 takerAmount,uint8 side,uint8 signatureType,uint256 timestamp,bytes32 metadata,bytes32 builder)'
    )
)
DOMAIN_NAME_HASH = keccak(text='Polymarket CTF Exchange')
DOMAIN_VERSION_HASH = keccak(text=str(CLOB_ORDER_VERSION))


def round_down(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    return int(value * factor) / factor


def to_usdc(value: float) -> int:
    return int(round(value * 1_000_000))


def get_clob_version(timeout: int = 10) -> int:
    try:
        resp = requests.get(f'{CLOB_HOST}{VERSION_PATH}', timeout=timeout)
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            return int(payload.get('version', CLOB_ORDER_VERSION))
    except Exception:
        pass
    return CLOB_ORDER_VERSION


def is_order_version_mismatch_response(resp: requests.Response) -> bool:
    try:
        payload = resp.json()
    except Exception:
        return ORDER_VERSION_MISMATCH in resp.text
    error = payload.get('error') if isinstance(payload, dict) else None
    if isinstance(error, str):
        return ORDER_VERSION_MISMATCH in error
    return ORDER_VERSION_MISMATCH in resp.text


def encode_uint256(value: int) -> bytes:
    return int(value).to_bytes(32, byteorder='big')


def encode_address(value: str) -> bytes:
    return bytes.fromhex(value.lower().replace('0x', '')).rjust(32, b'\x00')


def encode_bytes32_hex(value: str) -> bytes:
    raw = bytes.fromhex(value.replace('0x', ''))
    if len(raw) != 32:
        raise ValueError('bytes32 value must be exactly 32 bytes')
    return raw


def build_domain_separator() -> bytes:
    return keccak(
        DOMAIN_TYPEHASH
        + DOMAIN_NAME_HASH
        + DOMAIN_VERSION_HASH
        + encode_uint256(CHAIN_ID)
        + encode_address(EXCHANGE_ADDRESS_V2)
    )


def build_order_digest(order: dict[str, Any]) -> bytes:
    side_int = 0 if order['side'] == 'BUY' else 1
    struct_hash = keccak(
        ORDER_TYPEHASH
        + encode_uint256(order['salt'])
        + encode_address(order['maker'])
        + encode_address(order['signer'])
        + encode_uint256(order['tokenId'])
        + encode_uint256(order['makerAmount'])
        + encode_uint256(order['takerAmount'])
        + encode_uint256(side_int)
        + encode_uint256(order['signatureType'])
        + encode_uint256(order['timestamp'])
        + encode_bytes32_hex(order['metadata'])
        + encode_bytes32_hex(order['builder'])
    )
    return keccak(b'\x19\x01' + build_domain_separator() + struct_hash)


def sign_order_v2(order: dict[str, Any], private_key: str) -> str:
    digest = build_order_digest(order)
    pk = eth_keys.PrivateKey(bytes.fromhex(private_key.lstrip('0x')))
    sig = pk.sign_msg_hash(digest)
    sig_bytes = bytearray(sig.to_bytes())
    sig_bytes[64] += 27
    return '0x' + bytes(sig_bytes).hex()


def build_order_dict_v2(
    token_id: str,
    side: str,
    amount: float,
    price: float,
    *,
    funder: str,
    signer_address: str,
    private_key: str,
) -> dict[str, Any]:
    salt = random.randint(1, 2**32)
    timestamp_ms = time.time_ns() // 1_000_000

    if side == 'BUY':
        maker_amount = to_usdc(round_down(amount, 2))
        taker_amount = to_usdc(round_down(amount / price, 4))
    else:
        maker_tokens = round_down(amount, 2)
        maker_amount = to_usdc(maker_tokens)
        taker_amount = to_usdc(round_down(maker_tokens * price, 4))

    order = {
        'salt': salt,
        'maker': funder,
        'signer': signer_address,
        'tokenId': str(token_id),
        'makerAmount': str(maker_amount),
        'takerAmount': str(taker_amount),
        'side': side,
        'expiration': '0',
        'signatureType': SIGNATURE_TYPE,
        'timestamp': str(timestamp_ms),
        'metadata': ZERO_BYTES32_HEX,
        'builder': ZERO_BYTES32_HEX,
    }
    order['signature'] = sign_order_v2(order, private_key)
    return order
