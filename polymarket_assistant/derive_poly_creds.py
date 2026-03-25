#!/usr/bin/env python3
"""
Derive or validate Polymarket L2 API credentials from a local .env file.

This script never prints the private key. It only reports whether credentials
were derived successfully and can optionally persist missing values back into
the local polymarket_assistant/.env file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from dotenv import dotenv_values

try:
    from py_clob_client.client import ClobClient
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit(
        "Missing dependency: py_clob_client. Install it with "
        "`pip install py-clob-client` in the project venv."
    ) from exc


HOST = "https://clob.polymarket.com"
CHAIN_ID = 137
ENV_PATH = Path(__file__).resolve().parent / ".env"


def load_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        raise SystemExit(f"Missing env file: {ENV_PATH}")
    data = {
        key: value
        for key, value in dotenv_values(ENV_PATH).items()
        if value is not None and str(value).strip()
    }
    return {key: str(value).strip() for key, value in data.items()}


def mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def build_client(config: dict[str, str]) -> ClobClient:
    private_key = config.get("POLY_PRIVATE_KEY")
    if not private_key:
        raise SystemExit("POLY_PRIVATE_KEY is required in polymarket_assistant/.env")

    signature_type = int(config.get("POLY_SIGNATURE_TYPE", "2"))
    funder = config.get("POLY_FUNDER")
    if signature_type != 0 and not funder:
        raise SystemExit(
            "POLY_FUNDER is required when POLY_SIGNATURE_TYPE is not 0."
        )

    return ClobClient(
        HOST,
        key=private_key,
        chain_id=CHAIN_ID,
        signature_type=signature_type,
        funder=funder,
    )


def update_env_file(updates: dict[str, str]) -> None:
    original = ENV_PATH.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    rewritten: list[str] = []

    for line in original:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            rewritten.append(line)
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            rewritten.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            rewritten.append(line)

    for key, value in updates.items():
        if key not in seen:
            rewritten.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(rewritten) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Derive or validate Polymarket L2 API credentials"
    )
    parser.add_argument(
        "--write-missing",
        action="store_true",
        help="Persist derived POLY_API_KEY/POLY_API_SECRET/POLY_API_PASSPHRASE into polymarket_assistant/.env if they are missing.",
    )
    args = parser.parse_args()

    config = load_env()
    client = build_client(config)

    existing_creds = {
        "api_key": config.get("POLY_API_KEY"),
        "api_secret": config.get("POLY_API_SECRET"),
        "api_passphrase": config.get("POLY_API_PASSPHRASE"),
    }

    derived = client.create_or_derive_api_creds()

    print("Polymarket L2 credential derivation succeeded.")
    print(f"API key: {mask(derived.api_key)}")
    print(f"Secret: {mask(derived.api_secret)}")
    print(f"Passphrase: {mask(derived.api_passphrase)}")

    updates: dict[str, str] = {}
    if not existing_creds["api_key"]:
        updates["POLY_API_KEY"] = derived.api_key
    if not existing_creds["api_secret"]:
        updates["POLY_API_SECRET"] = derived.api_secret
    if not existing_creds["api_passphrase"]:
        updates["POLY_API_PASSPHRASE"] = derived.api_passphrase

    if args.write_missing and updates:
        update_env_file(updates)
        print(f"Wrote {len(updates)} missing value(s) into {ENV_PATH.name}.")
    elif args.write_missing:
        print("No missing L2 values to write.")
    else:
        print("Run with --write-missing to persist any missing values into the env file.")


if __name__ == "__main__":
    main()
