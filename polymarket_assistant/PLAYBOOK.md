# BTC Polymarket Playbook

## Core principles

1. Beecthor provides the thesis, but Binance provides execution reality.
2. No new Beecthor video means no bet.
3. The latest transcript is mandatory context.
4. Recent transcripts and recent entries in `analyses_log.json` must be reviewed before any bet.
5. Prefer conservative BTC `What price will Bitcoin hit...` markets.

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
- Do not skip to the more ambitious target just because Beecthor believes price can extend there.
- Only move to the next farther strike if the nearest strike is already too discounted or offers poor value.
- Reject the trade if the move is already too close to the target or obviously too discounted.
- Reject the trade if Polymarket probability is below `30%`, unless this playbook is revised later.
- Prefer higher-probability conservative setups when they still align with the thesis.
- Maximum simultaneous exposure: `2` open positions.
- Base stake per entry: `33%` of currently available cash.

## Exit rules

- Stop loss:
  - exit if market probability drops below `20%`
- Take profit:
  - consider exit once market probability reaches `90%`
  - default full take profit range: `90-95%`

## Daily cadence

- Review window 1:
  - around `08:00`
- Review window 2:
  - after the new Beecthor video is available

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
