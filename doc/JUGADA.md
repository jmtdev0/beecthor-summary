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

### 2026-04-17 — Weekly BTC $80k reach (Apr 13-19)

- Market: `will-bitcoin-reach-80k-april-13-19`
- Side: `Yes`
- Entry thesis:
  - After the `78k` target had been achieved, the cleanest remaining bullish expression of Beecthor's thesis was the weekly `80k` reach market.
  - The trade relied on time still being available in the weekly window, not on an immediate breakout in the next hour.
- Entry details:
  - Intended at `2026-04-17 18:01 UTC`
  - Executed from phone at `2026-04-17 22:11 UTC`
  - Execution needed repricing because the first `FOK` attempt could not be fully filled.
  - Final fill price: `0.148`
  - Shares: `15.7002`
  - Entry cost: `$2.1666`
- Current status:
  - Still open
  - Last synced at `2026-04-19 08:01 UTC`
  - Latest observed share price: `0.01`
  - Current value: `$0.1570`
  - Unrealized cash PnL: `-$2.0096`
- Retrospective:
  - This is the clearest recent example of a thesis that looked reasonable when opened and then failed badly afterwards.
  - The trade was not "wrong because weeklys are bad"; it was wrong because the final push simply did not extend far enough.
- What to learn:
  - A weekly gives timing room, but it does not remove directional risk.
  - When a target requires one more extension after a strong move has already happened, we should demand extra caution before chasing the next weekly strike.
  - The execution bug around rigid `FOK` orders is solved, but that only helps execution quality, not trade quality.

## Recent plays

### 2026-04-16 — Weekly BTC $78k reach (Apr 13-19)

- Market: `will-bitcoin-reach-78k-april-13-19`
- Side: `Yes`
- Entry thesis:
  - Beecthor turned short-term bullish again after the correction.
  - Expected path: one more upside leg toward `78k-79k`.
- Entry details:
  - Intended at `2026-04-16 17:29 UTC`
  - Executed from phone at `2026-04-16 17:32 UTC`
  - Average price: `0.16`
  - Shares: `5.872`
  - Entry cost: `$0.9395`
- Outcome:
  - Closed by monitor at `2026-04-17 15:05 UTC`
  - Exit reason: `take_profit`
  - Exit price: `0.999`
  - Realized PnL: `+$4.9266` (`+524.39%`)
- Retrospective:
  - This was an excellent expression of the thesis.
  - The weekly captured the directional move without forcing exact same-day timing.
- What to learn:
  - When Beecthor is structurally right but timing is slightly loose, a weekly often fits much better than a daily.

### 2026-04-17 — Daily BTC $78k reach (Apr 17)

- Market: `will-bitcoin-reach-78k-on-april-17`
- Side: `Yes`
- Entry thesis:
  - The short-term bullish thesis was still active and the daily `78k` strike was the cleanest same-day expression left.
- Entry details:
  - First decision at `2026-04-17 13:19 UTC` was wrongly rejected by the hard `nearest-strike-first` validator.
  - Re-enqueued manually at `2026-04-17 13:28 UTC`
  - Executed from phone at `2026-04-17 13:29 UTC`
  - Average price: `0.3999`
  - Shares: `2.392`
  - Entry cost: `$0.9566`
- Outcome:
  - Closed by monitor at `2026-04-17 17:05 UTC`
  - Exit reason: `take_profit`
  - Exit price: `0.999`
  - Realized PnL: `+$1.4330` (`+149.8%`)
- Retrospective:
  - The read was good.
  - The original rejection was a system bug, not a trade-quality problem.
- What to learn:
  - "Nearest strike first" should stay a preference, not a veto.
  - If the thesis is strong and the market is still reasonably priced, the system must not block a valid daily purely because another strike exists.

### 2026-04-18 — Daily BTC $76k dip (Apr 18)

- Market: `will-bitcoin-dip-to-76k-on-april-18`
- Side: `Yes`
- Entry thesis:
  - After the `78k-79k` sweep, Beecthor's short-term read shifted toward exhaustion and downside continuation.
  - The `76k` dip was the cleanest daily bearish expression available.
- Entry details:
  - Intended at `2026-04-18 08:41 UTC`
  - Executed from phone at `2026-04-18 08:44 UTC`
  - Average price: `0.4899`
  - Shares: `1.9658`
  - Entry cost: `$0.9630`
- Outcome:
  - Closed by monitor at `2026-04-18 11:05 UTC`
  - Exit reason: `take_profit`
  - Exit price: `0.9000`
  - Realized PnL: `+$0.8062` (`+83.72%`)
- Retrospective:
  - The short-term bearish read was correct and timely.
  - This is a good example of a daily working exactly as intended.
- What to learn:
  - Dailies are strong when Beecthor and price action align on both direction and near-term timing.
  - Nearby conservative strikes remain the cleanest daily implementation.

### 2026-04-18 — Daily BTC $75k dip (Apr 18)

- Market: `will-bitcoin-dip-to-75k-on-april-18`
- Side: `Yes`
- Entry thesis:
  - BTC had already moved below `76k`, so the next clean daily bearish expression was the `75k` dip market.
  - There were still about `10` hours left in the daily window at decision time.
- Entry details:
  - Intended at `2026-04-18 14:01 UTC`
  - Executed from phone at `2026-04-18 14:05 UTC`
  - Fill price: `0.131`
  - Shares: `7.633586`
  - Entry cost: about `$1.00`
- Outcome:
  - No formal `trade_closed` entry was written to `trade_log.json`
  - By the `2026-04-19 08:01 UTC` account sync, the position was no longer open
  - Binance `5m` data for `2026-04-18 UTC` shows a session low of `75,445.16`, so the `75k` strike was not hit in that UTC session
- Retrospective:
  - The bearish direction was broadly fine, but the strike was too ambitious for the remaining move.
  - This looks like a near miss rather than a bad read of the broader path.
- What to learn:
  - Once price has already done a meaningful part of the move, the next strike can become deceptively attractive but still be too far for a daily.
  - We still have a tracking gap here: expiry/resolution outcomes should be logged as cleanly as monitor-driven take profits.

### 2026-04-16 — Daily BTC $76k reach (Apr 16)

- Market: `will-bitcoin-reach-76k-on-april-16`
- Side: `Yes`
- Entry thesis:
  - Same short-term bullish thesis as the weekly `78k` reach.
  - BTC had reclaimed the `75k` area and was pressing the session high.
- Entry details:
  - Intended at `2026-04-16 20:00 UTC`
  - Enqueued at `2026-04-16 20:02 UTC`
  - Executed from phone at `2026-04-16 20:11 UTC`
  - Average price: about `0.55`
  - Cost: about `$1.00`
- Outcome:
  - The move to `76k` happened later, but too late for this market
  - Effective result: loss
- Retrospective:
  - The direction was not absurd.
  - The timing was wrong, and dailies punish that brutally.
- What to learn:
  - If the thesis is "higher soon" but not clearly "higher before today's close", a daily can still be the wrong vehicle.

## Recent no-trade lessons

### 2026-04-19 — Why we did not keep forcing the `75k dip`

- By `06:00 UTC`, the fresh April 19 dailies were not yet clean enough to justify a new bearish entry.
- By `08:00 UTC`, the `75k dip` market was already effectively priced as done, so there was no edge left.
- Lesson:
  - Missing the entry is frustrating, but buying a nearly resolved market is worse.
  - If a daily bearish play is the right one, it often has to be anticipated before the market reprices it to certainty.

## Working lessons

1. Weeklys are best when the thesis is directionally clear but the exact timing is loose.
2. Dailies are best only when Beecthor and price action align on both direction and timing.
3. "Nearest strike first" is a useful bias, not a hard law.
4. A move happening one day late is still a losing daily trade.
5. A daily can also fail by being one strike too ambitious even when the broader move is correct.
6. Tracking needs to log expiry/resolution outcomes as clearly as take-profit exits, otherwise post-mortems get blurry.
