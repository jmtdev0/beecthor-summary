# JUGADA

## Purpose

This file is a lightweight trading diary for the Polymarket assistant.
It focuses on:

- what position was opened
- why it was opened
- what actually happened
- whether the read was correct
- what we should learn from it

The goal is not to duplicate `trade_log.json`, but to keep a human-readable retrospective of the most important plays.

## Current focus

### 2026-04-16 — Weekly BTC $78k reach (Apr 13-19)

- Market: `will-bitcoin-reach-78k-april-13-19`
- Side: `Yes`
- Entry thesis:
  - The latest Beecthor view turned short-term bullish again.
  - Expected path: correction first, then continuation higher toward `78k-79k`.
  - Macro view still bearish later, but one more upside leg first.
- Entry details:
  - Intended at `2026-04-16 17:29 UTC`
  - Executed from phone at `2026-04-16 17:33 UTC`
  - Average price: `0.16`
  - Size: `5.872`
  - Cost: `$1.00`
- Current status:
  - Still open
  - Latest observed share price: `0.203`
  - Unrealized cash PnL: `+$0.2524`
- Retrospective:
  - The directional read is still alive.
  - BTC has already traded materially higher after entry.
  - The market has not repriced aggressively yet, so the thesis remains open but not validated.
- What to learn:
  - The weekly entry was a good way to express Beecthor's "one more push higher" thesis without forcing exact daily timing.
  - When Beecthor is structurally right but timing is fuzzy, weeklys fit better than dailies.

### 2026-04-16 — Daily BTC $76k reach (Apr 16)

- Market: `will-bitcoin-reach-76k-on-april-16`
- Side: `Yes`
- Entry thesis:
  - Same short-term bullish thesis as the weekly.
  - BTC had reclaimed the `75k` area and was pressing the session high.
  - The nearest daily upside strike still available was `76k`.
- Entry details:
  - Intended at `2026-04-16 20:00 UTC`
  - Enqueued at `2026-04-16 20:02 UTC`
  - Executed from phone at `2026-04-16 20:11 UTC`
  - Average price: `0.55`
  - Size: `1.7592`
  - Cost: `$1.00`
- Outcome:
  - Failed on the market's own expiry day
  - Current share price: `0.0`
  - Current cash PnL: `-$0.9676`
  - The move to `76k` happened later, but too late for this market
- Retrospective:
  - The direction was not crazy.
  - The timing was wrong.
  - This is a clean example of being "right, but too late" for a daily market.
- What to learn:
  - Dailies punish late entries much more than weeklys.
  - If the thesis is "higher soon" but not "higher before today's close", the daily may be the wrong vehicle even when the direction is correct.
  - We should be stricter with late-session daily entries, especially when less than a few hours remain to expiry.

## Recent resolved reference plays

### 2026-04-14 — Daily BTC $74k dip

- Market: `will-bitcoin-dip-to-74k-on-april-14`
- Side: `Yes`
- Result: win
- Exit: take profit by monitor
- Realized PnL: `+$1.2194`
- Lesson:
  - Conservative, nearby strikes work well when Beecthor's short-term direction and Binance momentum line up.

### 2026-04-15 — Daily BTC $73k dip

- Market: `will-bitcoin-dip-to-73k-on-april-15`
- Side: `Yes`
- Result: loss
- Realized PnL: `-$1.0000`
- Lesson:
  - Beecthor's bigger bearish thesis was not enough on its own.
  - The short-term path still allowed one more upside leg first, and the daily market was too tight for that uncertainty.

## Working lessons

1. Weekly markets are better when the thesis is directionally clear but timing is loose.
2. Daily markets are better only when Beecthor and Binance both support not just direction, but also near-term timing.
3. "Nearest strike first" is good, but it does not solve timing risk by itself.
4. A move happening one day late is still a losing daily trade.
5. If a setup feels structurally right but temporally fragile, prefer `NO_ACTION` or a weekly over a late daily.
