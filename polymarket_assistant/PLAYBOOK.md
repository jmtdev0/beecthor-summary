# BTC Polymarket Playbook

## Core principles

1. Beecthor provides the thesis, but Binance provides execution reality.
2. No new Beecthor video means no bet.
3. The latest transcript is mandatory context.
4. Recent transcripts and recent entries in `analyses_log.json` must be reviewed before any bet.
5. Prefer conservative BTC `What price will Bitcoin hit...` markets.

## Cycle steps (in order)

Each automated cycle must follow these steps strictly in order:

1. **Stop-loss check** — Review all open positions. Exit any position where the market probability has dropped to `20%` or below.
2. **Take-profit check** — Review all open positions. Consider exiting any position where the market probability has reached `90-95%`. If resolution is near-certain (very obvious the market will resolve in our favor), the position may be held to let it resolve naturally.
3. **Analyze context** — Fetch the current BTC price from Binance. Review the latest Beecthor transcripts and recent summaries from `analyses_log.json`. Determine the current directional thesis.
4. **Scout opportunities** — If fewer than `2` positions are open, scan active BTC price-hit markets on Polymarket. Look for markets that are:
   - In line with Beecthor's current directional thesis.
   - In line with the current BTC price trend (momentum confirmation).
   - Preferably already above `50%` probability on Polymarket.
5. **Place bet (if valid)** — If a viable market is found, open a position following the entry rules below. Only one new position per cycle.

## Market scope

- Allowed:
  - BTC daily price-hit markets
  - BTC weekly price-hit markets only when the recent thesis is unusually clear
- Not allowed:
  - non-BTC markets
  - vague narrative markets
  - bets that require ignoring current price structure

## Entry rules

- Start from the latest Beecthor transcript.
- Check whether the same directional idea appears in recent transcripts and recent summaries.
- Compare the thesis with the current BTC price and recent BTC structure on Binance.
- When the directional bias is valid, prefer the nearest reasonable strike first.
- If BTC looks bullish, first evaluate the closest upside target above price before considering farther upside targets.
- If BTC looks bearish, first evaluate the closest downside target below price before considering farther downside targets.
- Do not skip to the more ambitious target just because Beecthor believes price can extend there. Go step by step: first the nearest strike, then the next one if the first is going well.
- Only move to the next farther strike if the nearest strike is already too discounted or offers poor value.
- Reject the trade if the move is already too close to the target or obviously too discounted.
- Reject the trade if Polymarket probability is below `50%`.
- Prefer higher-probability conservative setups when they still align with the thesis.
- Maximum simultaneous exposure: `2` open positions.
- Base stake per entry: `33%` of currently available cash.
- **Early-stage cap:** while the total portfolio value (cash + open exposure) is below `$15`, the maximum stake per entry is `$1` regardless of the 33% rule.

## Exit rules

- Stop loss:
  - exit if market probability drops to `20%` or below
- Take profit:
  - consider exit once market probability reaches `90%`
  - default full take profit range: `90-95%`
  - exception: if resolution is near-certain (market is about to close and the outcome is obvious), the position may be held to resolve naturally at 100%

## Daily cadence

- Review window 1:
  - around `08:00`
- Review window 2:
  - after the new Beecthor video is available
- Automated cycles run every `4 hours` on the server

## Required log fields

Every decision must record:
- date
- review window
- latest video id
- transcript file used
- thesis summary
- Binance BTC price at decision time
- market title
- position side
- Polymarket probability at entry
- stake
- status
- exit reason if closed
- realized PnL if closed

`No bet` days must also be logged.
