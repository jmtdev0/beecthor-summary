# BTC Polymarket Playbook

## Core principles

1. Beecthor provides the thesis, but Binance provides execution reality.
2. A Beecthor video from today or yesterday (D-1) is considered current — betting is allowed. A video from two or more days ago (D-2+) is stale — only open a position if the thesis is exceptionally clear and Binance confirms the direction; otherwise skip.
3. The latest transcript is mandatory context.
4. Recent transcripts and recent entries i `analyses_log.json`n must be reviewed before any bet.
5. Prefer conservative BTC `What price will Bitcoin hit...` markets.

## Cycle steps (in order)

Each automated cycle must follow these steps strictly in order:

1. **Stop-loss check** — Skipped. No automated stop-loss while portfolio is in early stage (below $15). Positions are held until take-profit or natural resolution.
2. **Take-profit check** — Review all open positions. Consider exiting any position where the market probability has reached `90-95%`. If resolution is near-certain (very obvious the market will resolve in our favor), the position may be held to let it resolve naturally.
3. **Analyze context** — Fetch the current BTC price from Binance. Review the latest Beecthor transcripts and recent summaries from `analyses_log.json`. Determine the current directional thesis.
4. **Scout opportunities** — For each market type (daily / weekly / monthly), check if the slot is already filled. If not, scan active BTC price-hit markets of that type on Polymarket. Look for markets that are:
   - In line with Beecthor's current directional thesis.
   - In line with the current BTC price trend (momentum confirmation).
   - Preferably between `45%` and `84%` probability on Polymarket (hard cap at `< 85%`).
   - For weekly and monthly markets: prioritize entering early in the period with the most obvious strike.
5. **Place bet (if valid)** — If a viable market is found, open a position following the entry rules below. Only one new position per cycle.

## Market scope

Two allowed market types, each tracked separately:

| Slot | Type | Example URL pattern |
|------|------|---------------------|
| 1 daily | `what-price-will-bitcoin-hit-on-{month}-{day}` | daily expiry |
| 2 weekly | `what-price-will-bitcoin-hit-{month}-{day1}-{day2}` | weekly expiry |

- The goal for weekly markets is to **enter early** and pick the **most obvious strike** given Beecthor's current directional thesis. The longer the time horizon, the more margin for the thesis to play out.
- Not allowed:
  - non-BTC markets
  - vague narrative markets
  - bets that require ignoring current price structure
  - monthly or long-term markets (e.g. `what-price-will-bitcoin-hit-in-{month}-{year}`, `before-{year}`)

## Entry rules

- Start from the latest Beecthor transcript.
- Check whether the same directional idea appears in recent transcripts and recent summaries.
- Compare the thesis with the current BTC price and recent BTC structure on Binance.
- When the directional bias is valid, prefer the nearest reasonable strike first.
- If BTC looks bullish, first evaluate the closest upside target above price before considering farther upside targets.
- If BTC looks bearish, first evaluate the closest downside target below price before considering farther downside targets.
- Do not skip to the more ambitious target just because Beecthor believes price can extend there. Go step by step: first the nearest strike, then the next one if the first is going well.
- Only move to the next farther strike if the nearest strike is already too discounted or offers poor value.
- **Polymarket probabilities are guidelines, not hard rules.** They move in real time with the BTC spot price — a market at 70% today may drop to 40% tomorrow simply because price moved away from the strike, with no change in the underlying thesis. Polymarket probabilities carry noise and should never be trusted more than Beecthor's directional analysis. When the two conflict, favor Beecthor's thesis.
- As a general guide, prefer markets with a Polymarket probability between `45%` and `84%` when the direction is aligned with Beecthor's thesis. If the probability is within this range and the thesis is aligned, there should be a strong reason to skip — do not invent vague excuses to avoid the trade.
- Proximity of the current BTC price to the strike is NOT a valid rejection reason on its own. The market price already reflects that proximity. If the thesis is aligned, that is sufficient.
- Be cautious below `45%` (limited market consensus). Apply this as a soft filter, not an absolute cutoff — a slightly out-of-range market with a very clear thesis is still worth considering.
- **Hard rule: never open a position with probability `>= 85%`.** Risk/reward is too poor at that level — potential gain is minimal while downside remains real. No exceptions.
- Prefer higher-probability conservative setups when they still align with the thesis and stay below the 85% cap.
- Maximum simultaneous exposure: **3 open positions total**.
- Position cap by type:
  - **1 daily** position maximum
  - **2 weekly** positions maximum
- Monthly or longer-dated positions are not allowed, so they do not count toward the cap.
- Base stake per entry: `15%` of currently available cash.
- **Early-stage cap:** while the total portfolio value (cash + open exposure) is below `$15`, the maximum stake per entry is `$1` regardless of the 15% rule.

## Exit rules

- Stop loss:
  - disabled in early stage (portfolio below `$15`) — let positions run to resolution or take-profit
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
