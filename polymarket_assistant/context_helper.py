#!/usr/bin/env python3
"""
Quick context helper for manual Polymarket decisions.

This script does not place trades. It only reads local Beecthor context and,
optionally, fetches BTC spot data from Binance for decision support.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests


REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"
ANALYSES_LOG = REPO_ROOT / "analyses_log.json"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"
BINANCE_KLINES_URL = (
    "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit={limit}"
)


@dataclass
class TranscriptSnapshot:
    path: Path
    video_id: str
    date: str
    size: int
    preview: str


def load_recent_transcripts(limit: int) -> list[TranscriptSnapshot]:
    snapshots: list[TranscriptSnapshot] = []
    files = sorted(
        TRANSCRIPTS_DIR.glob("*.txt"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )[:limit]
    for path in files:
        text = path.read_text(encoding="utf-8").strip()
        preview = " ".join(text.split())[:500]
        try:
            video_id, date_part = path.stem.split("_", 1)
        except ValueError:
            video_id, date_part = path.stem, "unknown"
        snapshots.append(
            TranscriptSnapshot(
                path=path,
                video_id=video_id,
                date=date_part,
                size=len(text),
                preview=preview,
            )
        )
    return snapshots


def load_recent_summaries(limit: int) -> list[dict[str, Any]]:
    entries = json.loads(ANALYSES_LOG.read_text(encoding="utf-8"))
    return entries[-limit:]


def fetch_binance_context(hours: int) -> dict[str, Any]:
    ticker_response = requests.get(BINANCE_TICKER_URL, timeout=15)
    ticker_response.raise_for_status()
    ticker_price = float(ticker_response.json()["price"])

    klines_response = requests.get(BINANCE_KLINES_URL.format(limit=hours), timeout=15)
    klines_response.raise_for_status()
    klines = klines_response.json()
    prices = [float(item[4]) for item in klines]

    return {
        "symbol": "BTCUSDT",
        "spot_price": ticker_price,
        "hours": hours,
        "close_min": min(prices) if prices else None,
        "close_max": max(prices) if prices else None,
        "close_last": prices[-1] if prices else None,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def print_report(transcript_limit: int, summary_limit: int, hours: int) -> None:
    print("=== Polymarket Manual Context ===")
    print(f"Generated at: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print()

    print(f"Recent transcripts: {transcript_limit}")
    for snapshot in load_recent_transcripts(transcript_limit):
        print(
            f"- {snapshot.date} | {snapshot.video_id} | {snapshot.path.name} | "
            f"{snapshot.size} chars"
        )
        print(f"  Preview: {snapshot.preview}")
    print()

    print(f"Recent summary entries: {summary_limit}")
    for entry in load_recent_summaries(summary_limit):
        message_preview = " ".join(entry.get("message", "").split())[:280]
        print(
            f"- {entry.get('timestamp')} | {entry.get('video_id')} | "
            f"BTC ${entry.get('btc_usd')}"
        )
        print(f"  Preview: {message_preview}")
    print()

    print("Binance BTC context")
    try:
        binance_context = fetch_binance_context(hours)
    except requests.RequestException as exc:
        print(f"- Binance fetch failed: {exc}")
        return

    print(
        f"- Spot: ${binance_context['spot_price']:,.2f} | "
        f"{hours}h range closes: ${binance_context['close_min']:,.2f} -> "
        f"${binance_context['close_max']:,.2f}"
    )
    print(f"- Fetched at: {binance_context['fetched_at']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Manual Polymarket context helper")
    parser.add_argument(
        "--transcripts",
        type=int,
        default=3,
        help="Number of recent transcripts to include",
    )
    parser.add_argument(
        "--summaries",
        type=int,
        default=3,
        help="Number of recent summary entries to include",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Number of Binance 1h candles to inspect",
    )
    args = parser.parse_args()
    print_report(
        transcript_limit=args.transcripts,
        summary_limit=args.summaries,
        hours=args.hours,
    )


if __name__ == "__main__":
    main()
