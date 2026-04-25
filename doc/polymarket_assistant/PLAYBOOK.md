# BTC Polymarket Playbook

## Core principles

1. Beecthor provides the thesis, but Binance provides execution reality.
2. A Beecthor video from today or yesterday (D-1) is considered current — betting is allowed. A video from two or more days ago (D-2+) is stale — only open a position if the thesis is exceptionally clear and Binance confirms the direction; otherwise skip.
3. The latest transcript is mandatory context.
4. Recent transcripts and recent entries in `analyses_log.json` must be reviewed before any bet.
5. Prefer conservative BTC price-hit markets first. Floor markets are out of scope and must not be used.

## Cycle steps (in order)

Each automated cycle must follow these steps strictly in order:

1. **Discarded-slot check** — No automated stop-loss. If a daily or weekly position falls to `<= 20%` probability on Polymarket, it may remain open but be treated as **discarded for slot availability**. Discarded means the position no longer blocks a fresher entry of the same type; it does **not** mean force-sell it.
2. **Take-profit check** — Review all open positions. Consider exiting any position where the market probability has reached `90-95%`. If two positions independently meet the take-profit criteria in the same review, exiting both in the same pass is allowed. If resolution is near-certain (very obvious the market will resolve in our favor), the position may be held to let it resolve naturally.
3. **Partial take-profit check** — If a position reaches `80-85%` probability and expiry is not imminent, consider reducing `40-60%` to lock in profit while leaving upside for full resolution.
4. **Exceptional invalidation check** — Normal stop-loss remains disabled, but a full exit is allowed when probability is `<= 15-20%`, the thesis no longer supports the trade, Binance confirms opposite structure, and executable liquidity is acceptable.
5. **Reconciliation gate** — Before opening any new position, confirm that `account_state.json` and `trade_log.json` tell a coherent story about open positions and recently closed trades. If reconciliation is broken, the only valid action for new entries is `NO_ACTION` until the state is repaired.
6. **Account-equity gate** — Before opening any new position, review cash, live open value, discarded-position loss, and net equity versus starting bankroll. If the account is carrying too much hidden pain, reduce risk or return `NO_ACTION`.
7. **Analyze context** — Fetch the current BTC price from Binance. Review the latest Beecthor transcripts and recent summaries from `analyses_log.json`. Determine the current directional thesis, but also whether Binance has actually confirmed that thesis.
8. **Scout opportunities** — Default to the two primary slots first: `daily thesis` and `weekly thesis`. Only if Binance is showing a very clear continuation that does not fit the main Beecthor thesis should the system consider the secondary slots (`daily momentum` and `weekly momentum`). For each slot (`daily thesis / daily momentum / weekly thesis / weekly momentum`), check whether it is occupied by an **active** position. Discarded daily / weekly positions do not block the slot. If the slot is free, scan active BTC price-hit markets of that type on Polymarket. Look for markets that are:
   - In line with Beecthor's current directional thesis.
   - In line with the current BTC price trend (momentum confirmation).
   - Both directions (REACH and DIP) must be evaluated before deciding. Do not default to one direction by habit — if Beecthor's thesis supports a bullish move, a REACH market may be the right bet even if recent cycles have been DIP.
   - Preferably between `45%` and `84%` probability on Polymarket (hard cap at `< 85%`).
   - For weekly markets: prioritize entering early in the period with the most obvious strike.
   - For the **daily momentum** slot: it may go against the main Beecthor thesis, but only when Binance shows a very clear intraday continuation that is cleaner than forcing the thesis-aligned daily.
9. **Place bet (if valid)** — If viable markets are found, open positions following the entry rules below. A cycle may open up to **two** new positions when they are independently justified and respect slot and cash limits. Most cycles should still open `0` or `1` positions.

## Market scope

Four allowed BTC price-hit slots, tracked separately:

| Slot | Type | Example URL pattern |
|------|------|---------------------|
| 1 daily thesis | `what-price-will-bitcoin-hit-on-{month}-{day}` | daily expiry |
| 1 daily momentum | `what-price-will-bitcoin-hit-on-{month}-{day}` | daily expiry |
| 1 weekly thesis | `what-price-will-bitcoin-hit-{month}-{day1}-{day2}` | weekly expiry |
| 1 weekly momentum | `what-price-will-bitcoin-hit-{month}-{day1}-{day2}` | weekly expiry |

- Daily markets are for same-day timing expressions.
- The **daily thesis** slot is the default same-day expression of Beecthor's current directional view.
- The **daily momentum** slot exists to exploit a very clear intraday continuation even when it runs against the original thesis. This is not revenge trading and must not be used to average down a failed idea.
- The **weekly thesis** slot is the default structural expression of Beecthor's main directional view. The goal is to **enter early** and pick the **most obvious strike** given the current thesis.
- The **weekly momentum** slot exists only for cases where price action is showing a very clear weekly continuation that does not fit the main Beecthor thesis cleanly enough to ignore.
- The default portfolio intention is therefore **1 daily thesis + 1 weekly thesis**. The two momentum slots are secondary and should stay empty unless the market is showing a very clear non-thesis trend worth exploiting.
- The two weekly slots are not meant for random extra exposure. They exist so the system can hold up to **two frontier weekly expressions** around the current price structure when closest-strike-first logic still shows edge.
- In practice, the weekly momentum slot should only be used for the next clean weekly strike once the weekly thesis slot is already occupied or discarded. Do not skip nearer weekly strikes just to force a farther story.
- Not allowed:
  - non-BTC markets
  - vague narrative markets
  - bets that require ignoring current price structure
  - floor markets (`bitcoin-above-{X}k-on-{month}-{day}`)
  - monthly or long-term markets (e.g. `what-price-will-bitcoin-hit-in-{month}-{year}`, `before-{year}`)

## Entry rules

- Start from the latest Beecthor transcript.
- Check whether the same directional idea appears in recent transcripts and recent summaries.
- Compare the thesis with the current BTC price and recent BTC structure on Binance.
- Choose the vehicle first:
  - use a **daily thesis** slot when direction and timing both look aligned for the current UTC session
  - use the **daily momentum** slot only when Binance shows a clear same-day continuation that is cleaner than forcing the thesis-aligned daily
  - use the **weekly thesis** slot when direction is clear but same-day timing is less precise
  - use the **weekly momentum** slot only when Binance shows a clear higher-timeframe continuation that is cleaner than forcing the thesis-aligned weekly
- When the directional bias is valid, treat the nearest reasonable strike as the first candidate, not as a veto on all other strikes.
- Separate **level validity** from **expiry validity**. A Beecthor level can be valid eventually but still be a bad Polymarket trade if the selected market expires too soon.
- Every new position must answer both questions: "is this level meaningful?" and "is this likely enough before this expiry?"
- If BTC looks bullish, first evaluate the closest upside target above price before considering farther upside targets.
- If BTC looks bearish, first evaluate the closest downside target below price before considering farther downside targets.
- For the **daily momentum** slot, closest-strike-first still applies. If momentum clearly points up, prefer `75k reach` before `76k reach`; if momentum clearly points down, prefer the nearest downside strike first.
- For the **weekly momentum** slot, closest-strike-first also applies. It should mirror frontier price action, not become a license to jump straight to a far weekly narrative.
- It is acceptable to skip the nearest strike when it is already effectively resolved, already `>= 85%`, or offers clearly worse risk/reward than the next clean expression.
- Do not chase the next weekly strike just because the previous target already hit. If the setup requires one more extension after a strong move has already happened, demand clear Binance continuation evidence and a modest remaining distance.
- Reject daily setups that need a fresh second leg after much of the move has already happened, or that are more likely to resolve one day late than before the current expiry.
- With less than `4h` left in a daily market, only open a new daily position when the strike is close, the probability is strong but below the hard cap, and Binance momentum points directly at that strike.
- After a large intraday move, do not chase the next strike unless the market consolidates/retests or Binance shows fresh continuation. Avoid paying for "one more push" after most of the move is already spent.
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
- As a portfolio construction rule, try to fill only the thesis-aligned daily and weekly slots whenever possible. Secondary momentum slots should only be filled when price action is clearly trending in a way that the main Beecthor thesis is not capturing well enough.
- Beecthor-bias correction: if recent Beecthor summaries remain bearish while BTC is flat or net higher over the same period, bearish `DIP` entries require explicit Binance rejection evidence (lower high, failed reclaim, support loss, downside expansion, or clear bearish repricing). Without that evidence, evaluate the nearest `REACH` momentum setup before forcing another bearish entry.
- Weekly entries require stricter evidence than daily entries. Prefer opening them in the first half of the weekly period, avoid weak probabilities below `25%` unless evidence is exceptional, and do not open a weekly trade just because a slot is free.
- If discarded-position unrealized losses exceed `15-20%` of current bankroll, do not add new exposure in the same broad direction unless confirmation is exceptional.
- Maximum simultaneous exposure: **4 active open positions total**. Daily / weekly positions marked as discarded for slot purposes do not count toward the active-position cap.
- Maximum new openings per cycle: **2**.
- Maximum managed positions per cycle: **2**.
- Position cap by type:
  - **2 active daily** positions maximum
  - **2 active weekly** positions maximum
- Monthly, longer-dated, and floor positions are not allowed, so they do not count toward the cap.
- Base stake per entry: `15%` of currently available cash.
- **Early-stage cap:** while the total portfolio value (cash + open exposure) is below `$15`, the maximum stake per entry is `$1` regardless of the 15% rule.

## Exit rules

- Stop loss:
  - disabled — no automated stop-loss exits
  - if a daily or weekly position drops to `<= 20%`, it may be treated as discarded for slot availability, but it still remains open until take-profit or natural resolution
  - exception: a thesis-invalidated exit is allowed only when probability is `<= 15-20%`, the original thesis is no longer valid, Binance confirms the opposite direction, and liquidity is acceptable
- Take profit:
  - consider partial exit once market probability reaches `80-85%`
  - consider exit once market probability reaches `90%`
  - default full take profit range: `90-95%`
  - if two positions independently hit the take-profit zone in the same review, exiting both is valid
  - exception: if resolution is near-certain (market is about to close and the outcome is obvious), the position may be held to resolve naturally at 100%

## Execution freshness

- A pending entry order older than `120` minutes is stale and must be skipped instead of executed blindly.

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
