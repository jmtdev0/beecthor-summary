#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from run_cycle import build_context_snapshot, load_env, now_utc


def main() -> None:
    parser = argparse.ArgumentParser(description='Export a fresh Polymarket cycle context snapshot')
    parser.add_argument('--run-id', required=True, help='Unique run identifier for the automated cycle')
    parser.add_argument('--output', required=True, help='Path to the JSON snapshot file to write')
    args = parser.parse_args()

    config = load_env()
    context = build_context_snapshot(config)
    payload = {
        'run_id': args.run_id,
        'generated_at': now_utc(),
        'context': context,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
