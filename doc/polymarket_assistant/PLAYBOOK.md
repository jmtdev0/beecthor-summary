# BTC Polymarket Playbook

## Core principles

1. Beecthor provides the thesis, but Binance provides execution reality.
2. A Beecthor video from today or yesterday (D-1) is considered current — betting is allowed. A video from two or more days ago (D-2+) is stale — only open a position if the thesis is exceptionally clear and Binance confirms the direction; otherwise skip.
3. The latest transcript is mandatory context.
4. Recent transcripts and recent entries in `analyses_log.json` must be reviewed before any bet.
5. Prefer conservative BTC price-hit markets first; use floor markets only when the thesis is specifically about support holding.

## Cycle steps (in order)

Each automated cycle must follow these steps strictly in order:

1. **Discarded-slot check** — No automated stop-loss. If a daily or weekly position falls to `<= 20%` probability on Polymarket, it may remain open but be treated as **discarded for slot availability**. Discarded means the position no longer blocks a fresher entry of the same type; it does **not** mean force-sell it.
2. **Take-profit check** — Review all open positions. Consider exiting any position where the market probability has reached `90-95%`. If resolution is near-certain (very obvious the market will resolve in our favor), the position may be held to let it resolve naturally.
3. **Reconciliation gate** — Before opening any new position, confirm that `account_state.json` and `trade_log.json` tell a coherent story about open positions and recently closed trades. If reconciliation is broken, the only valid action for new entries is `NO_ACTION` until the state is repaired.
4. **Analyze context** — Fetch the current BTC price from Binance. Review the latest Beecthor transcripts and recent summaries from `analyses_log.json`. Determine the current directional thesis.
5. **Scout opportunities** — For each slot (daily / weekly / floor), check whether it is occupied by an **active** position. Discarded daily / weekly positions do not block the slot. If the slot is free, scan active BTC markets of that type on Polymarket. Look for markets that are:
   - In line with Beecthor's current directional thesis.
   - In line with the current BTC price trend (momentum confirmation).
   - Both directions (REACH and DIP) must be evaluated before deciding. Do not default to one direction by habit — if Beecthor's thesis supports a bullish move, a REACH market may be the right bet even if recent cycles have been DIP.
   - Preferably between `45%` and `84%` probability on Polymarket (hard cap at `< 85%`).
   - For weekly markets: prioritize entering early in the period with the most obvious strike.
  - For floor markets: only bet `Yes`, and only when Beecthor identifies a strong support zone that Binance still respects.
6. **Place bet (if valid)** — If a viable market is found, open a position following the entry rules below. Only one new position per cycle.

## Market scope

Three allowed market types, each tracked separately:

| Slot | Type | Example URL pattern |
|------|------|---------------------|
| 1 daily | `what-price-will-bitcoin-hit-on-{month}-{day}` | daily expiry |
| 1 weekly | `what-price-will-bitcoin-hit-{month}-{day1}-{day2}` | weekly expiry |
| 1 floor | `bitcoin-above-{X}k-on-{month}-{day}` | same-day support-hold |

- Daily markets are for same-day timing expressions.
- The goal for weekly markets is to **enter early** and pick the **most obvious strike** given Beecthor's current directional thesis. The longer the time horizon, the more margin for the thesis to play out.
- Floor markets are secondary to price-hit markets and are only valid when the thesis is about defending support rather than tagging a fresh target.
- Not allowed:
  - non-BTC markets
  - vague narrative markets
  - bets that require ignoring current price structure
  - monthly or long-term markets (e.g. `what-price-will-bitcoin-hit-in-{month}-{year}`, `before-{year}`)

## Entry rules

- Start from the latest Beecthor transcript.
- Check whether the same directional idea appears in recent transcripts and recent summaries.
- Compare the thesis with the current BTC price and recent BTC structure on Binance.
- Choose the vehicle first:
  - use a **daily** only when direction and timing both look aligned for the current UTC session
  - use a **weekly** when direction is clear but same-day timing is less precise
  - use a **floor** only when the thesis is about holding support, not reaching a new strike
- When the directional bias is valid, treat the nearest reasonable strike as the first candidate, not as a veto on all other strikes.
- If BTC looks bullish, first evaluate the closest upside target above price before considering farther upside targets.
- If BTC looks bearish, first evaluate the closest downside target below price before considering farther downside targets.
- It is acceptable to skip the nearest strike when it is already effectively resolved, already `>= 85%`, or offers clearly worse risk/reward than the next clean expression.
- Do not chase the next weekly strike just because the previous target already hit. If the setup requires one more extension after a strong move has already happened, demand clear Binance continuation evidence and a modest remaining distance.
- Reject daily setups that need a fresh second leg after much of the move has already happened, or that are more likely to resolve one day late than before the current expiry.
- A daily or weekly position with current Polymarket probability `<= 20%` may be treated as **discarded for slot purposes**:
  - it remains open
  - it does not trigger an automatic sell
  - it does not occupy the active slot of its type
  - it does not justify reopening the exact same market/outcome just to average down
  - any replacement trade of the same type must be materially cleaner than the discarded one
- **Polymarket probabilities are guidelines, not hard rules.** They move in real time with the BTC spot price — a market at 70% today may drop to 40% tomorrow simply because price moved away from the strike, with no change in the underlying thesis. Polymarket probabilities carry noise and should never be trusted more than Beecthor's directional analysis. When the two conflict, favor Beecthor's thesis.
- As a general guide, prefer markets with a Polymarket probability between `45%` and `84%` when the direction is aligned with Beecthor's thesis. If the probability is within this range and the thesis is aligned, there should be a strong reason to skip — do not invent vague excuses to avoid the trade.
- Proximity of the current BTC price to the strike is NOT a valid rejection reason on its own. The market price already reflects that proximity. If the thesis is aligned, that is sufficient.
- Be cautious below `45%` (limited market consensus). Apply this as a soft filter, not an absolute cutoff — a slightly out-of-range market with a very clear thesis is still worth considering.
- **Hard rule: never open a position with probability `>= 85%`.** Risk/reward is too poor at that level — potential gain is minimal while downside remains real. No exceptions.
- Prefer higher-probability conservative setups when they still align with the thesis and stay below the 85% cap.
- Maximum simultaneous exposure: **3 active open positions total**. Daily / weekly positions marked as discarded for slot purposes do not count toward the active-position cap.
- Position cap by type:
  - **1 active daily** position maximum
  - **1 active weekly** position maximum
  - **1 floor** position maximum
- Monthly or longer-dated positions are not allowed, so they do not count toward the cap.
- Base stake per entry: `15%` of currently available cash.
- **Early-stage cap:** while the total portfolio value (cash + open exposure) is below `$15`, the maximum stake per entry is `$1` regardless of the 15% rule.

## Exit rules

- Stop loss:
  - disabled — no automated stop-loss exits
  - if a daily or weekly position drops to `<= 20%`, it may be treated as discarded for slot availability, but it still remains open until take-profit or natural resolution
- Take profit:
  - consider exit once market probability reaches `90%`
  - default full take profit range: `90-95%`
  - exception: if resolution is near-certain (market is about to close and the outcome is obvious), the position may be held to resolve naturally at 100%

## Execution freshness

- A pending entry order older than `120` minutes is stale and must be skipped instead of executed blindly.
- A pending BUY order is invalid if the live market price has repriced above its stored `max_entry_probability`.
- Repricing is allowed only while it stays inside the originally accepted entry ceiling.

## Reconciliation rules

- Reconciliation is a **hard gate** for new entries. If any tracked open position disappeared without a matching closure record, or if a live position is missing from `account_state.json`, the next valid opening action is `NO_ACTION` until the mismatch is fixed.
- After each sync, every position that disappeared from `open_positions` must have a matching closure record in `trade_log.json`.
- Expired losers must be logged explicitly. Do not leave them implied by the next account snapshot.
- Before opening a new position, confirm that `account_state.json` and the latest `trade_log.json` tell a coherent story about cash, open exposure, and recently closed trades.

## Daily cadence

- Review window 1:
  - around `08:00`
- Review window 2:
  - after the new Beecthor video is available
- Automated cycles run every `2 hours` on the server

## Required log fields

Every decision must record:
- date
- review window
- latest video id
- transcript file used
- thesis summary
- market type
- Binance BTC price at decision time
- market title
- position side
- Polymarket probability at entry
- stake
- status
- close timestamp if closed
- exit reason if closed
- realized PnL if closed

`No bet` days must also be logged.
