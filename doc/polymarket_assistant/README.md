# Polymarket Assistant

Manual support resources for a separate Polymarket account driven by Beecthor's daily BTC thesis.

This folder is intentionally isolated from the Telegram summary workflow. Nothing here sends messages, updates the daily transcript pipeline, or executes trades automatically.

## Purpose

Use this folder when you want to discuss a new BTC bet in chat.

The assistant should:
- read the latest Beecthor transcript from `../transcripts/`
- review recent summaries from `../analyses_log.json`
- check recent and current BTC price from Binance
- compare Beecthor's thesis with the current market position
- suggest `bet` or `no bet`
- record the final decision in the dedicated tracking files

## Files

- `doc/polymarket_assistant/PLAYBOOK.md` — operating rules and hard constraints
- `account_state.json` — bankroll, cash, open positions, realized PnL
- `trade_log.json` — daily decisions, entries, exits, and no-bet days
- `context_helper.py` — optional helper script for quick context snapshots
- `activity_summary.py` — public Polymarket activity/positions summary for any wallet

## Suggested manual workflow

1. Ask for the bet in chat.
2. Review the latest transcript and recent summaries.
3. Check BTC on Binance.
4. Decide whether the edge is real or already priced in.
5. If a trade is taken, update `trade_log.json` and `account_state.json`.
6. If no trade is taken, still log the decision.

## Notes

- Markets are limited to BTC `What price will Bitcoin hit...` style markets.
- Daily markets have priority over weekly markets.
- No trade is allowed without a new Beecthor video on that day.
- Binance is the price source of truth for entry timing.
