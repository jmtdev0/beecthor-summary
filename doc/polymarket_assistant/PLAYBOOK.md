# BTC Polymarket Playbook

## Core principles

1. Beecthor provides the primary thesis, but Binance provides execution reality.
2. A Beecthor video from today or yesterday (D-1) is considered current — betting is allowed. A video from two or more days ago (D-2+) is stale — only open a position if the thesis is exceptionally clear and Binance confirms the direction; otherwise skip.
3. The latest transcript is mandatory context.
4. Recent transcripts and recent entries in `analyses_log.json` must be reviewed before any bet.
5. Prefer conservative BTC price-hit markets first. Floor markets are out of scope and must not be used.
6. **No-trade is the default in lateral BTC regimes.** If BTC is chopping inside a tight range, the system should protect capital, manage existing positions, and wait for a confirmed break/rejection instead of forcing fresh expiry-based bets.
7. The LLM may trade against Beecthor only when the last ~48h of BTC price action clearly shows that Beecthor's thesis is wrong or badly timed. This must be explicit in the decision rationale.
8. The `08:00 UTC` cycle is the primary strategic window for daily entries: it is late enough for the Polymarket daily board, which usually starts forming around `04:00 UTC`, to show early direction, but early enough to leave ample time for a daily `REACH/DIP` target to resolve.

## Cycle steps (in order)

Each automated cycle must follow these steps strictly in order:

1. **Discarded-slot check** — No automated stop-loss. If a daily or legacy weekly position falls to `<= 20%` probability on Polymarket, it may remain open but be treated as **discarded for slot availability**. Discarded means the position no longer blocks fresher allowed daily exposure; it does **not** mean force-sell it.
2. **Take-profit check** — Review all open positions. Consider exiting any position where the market probability has reached `90-95%`. If two positions independently meet the take-profit criteria in the same review, exiting both in the same pass is allowed. If resolution is near-certain (very obvious the market will resolve in our favor), the position may be held to let it resolve naturally.
3. **Partial take-profit check** — If a position reaches `80-85%` probability and expiry is not imminent, automatically reduce `40-60%` to lock in profit while leaving upside for full resolution.
4. **Exceptional invalidation check** — Disabled. No stop-loss sale may be executed by the server, the phone, or the LLM. Positions with very low probability can be treated as discarded for slot availability, but they must not be force-sold.
5. **Reconciliation gate** — Before opening any new position, confirm that `account_state.json` and `trade_log.json` tell a coherent story about open positions and recently closed trades. If reconciliation is broken, the only valid action for new entries is `NO_ACTION` until the state is repaired.
6. **Account-equity gate** — Before opening any new position, review cash, live open value, discarded-position loss, and net equity versus starting bankroll. If the account is carrying too much hidden pain, reduce risk or return `NO_ACTION`.
7. **Analyze context** — Fetch the current BTC price from Binance. Review the latest Beecthor transcripts and recent summaries from `analyses_log.json`. Determine the current directional thesis, but also whether Binance has actually confirmed that thesis.
8. **Range / no-trade gate** — Before scouting new entries, decide whether BTC is in a lateral regime. If the last `24-72h` show compression, repeated failed extensions, and no clean break of the local range, the default decision for new entries is `NO_ACTION`. Existing positions may still be monitored, reduced, closed, or allowed to resolve.
9. **Scout opportunities** — Daily markets are the only allowed new-entry vehicle. Weekly `REACH/DIP` openings are disabled after historical review showed poor risk-adjusted performance. Default to the `daily thesis` slot first; use `daily momentum` only when Binance is showing a very clear same-day continuation that does not fit the main Beecthor thesis. For each daily slot (`daily thesis / daily momentum`), check whether it is occupied by an **active** daily position. Discarded daily positions do not block the slot. If the slot is free, scan active BTC daily price-hit markets on Polymarket. Look for markets that are:
   - In line with Beecthor's current directional thesis.
   - In line with the current BTC price trend (momentum confirmation).
   - Both directions (REACH and DIP) must be evaluated before deciding. Do not default to one direction by habit — if Beecthor's thesis supports a bullish move, a REACH market may be the right bet even if recent cycles have been DIP.
   - Preferably between `45%` and `90%` probability on Polymarket (hard cap at `> 90%`).
   - For the **daily momentum** slot: it may go against the main Beecthor thesis, but only when Binance shows a very clear intraday continuation that is cleaner than forcing the thesis-aligned daily.
10. **Place bet (if valid)** — If a viable daily market is found, open at most **one** new daily position following the entry rules below. Most cycles should still open `0` positions.

## Market scope

Two allowed BTC price-hit slots, tracked separately:

| Slot | Type | Example URL pattern |
|------|------|---------------------|
| 1 daily thesis | `what-price-will-bitcoin-hit-on-{month}-{day}` | daily expiry |
| 1 daily momentum | `what-price-will-bitcoin-hit-on-{month}-{day}` | daily expiry |

- Daily markets are for same-day timing expressions.
- The **daily thesis** slot is the default same-day expression of Beecthor's current directional view.
- The **daily momentum** slot exists to exploit a very clear intraday continuation even when it runs against the original thesis. This is not revenge trading and must not be used to average down a failed idea.
- Weekly `REACH/DIP` markets are **disabled for new openings**. Existing weekly positions may still be monitored, partially reduced, closed for take-profit, or allowed to resolve naturally, but they do not create permission to open another weekly.
- The default portfolio intention is therefore **daily thesis first**, with **daily momentum** only as a secondary slot when same-day price action is unusually clear.
- Not allowed:
  - non-BTC markets
  - vague narrative markets
  - bets that require ignoring current price structure
  - floor markets (`bitcoin-above-{X}k-on-{month}-{day}`)
  - weekly, monthly, or long-term openings (e.g. `what-price-will-bitcoin-hit-{month}-{day1}-{day2}`, `what-price-will-bitcoin-hit-in-{month}-{year}`, `before-{year}`)

## Entry rules

- Start from the latest Beecthor transcript.
- Check whether the same directional idea appears in recent transcripts and recent summaries.
- Compare the thesis with the current BTC price and recent BTC structure on Binance.
- Choose the vehicle first:
  - use a **daily thesis** slot when direction and timing both look aligned for the current UTC session
  - use the **daily momentum** slot only when Binance shows a clear same-day continuation that is cleaner than forcing the thesis-aligned daily
  - do **not** use weekly markets for new openings, even when direction is clear but same-day timing is less precise
- When the directional bias is valid, treat the nearest reasonable strike as the first candidate, not as a veto on all other strikes.
- Separate **level validity** from **expiry validity**. A Beecthor level can be valid eventually but still be a bad Polymarket trade if the selected market expires too soon.
- Every new position must answer both questions: "is this level meaningful?" and "is this likely enough before this expiry?"
- If BTC looks bullish, first evaluate the closest upside target above price before considering farther upside targets.
- If BTC looks bearish, first evaluate the closest downside target below price before considering farther downside targets.
- For the **daily momentum** slot, closest-strike-first still applies. If momentum clearly points up, prefer `75k reach` before `76k reach`; if momentum clearly points down, prefer the nearest downside strike first.
- It is acceptable to skip the nearest strike when it is already effectively resolved, already `> 90%`, or offers clearly worse risk/reward than the next clean expression.
- Do not chase the next strike just because the previous target already hit. If the setup requires one more extension after a strong move has already happened, demand clear Binance continuation evidence and a modest remaining distance.
- Reject daily setups that need a fresh second leg after much of the move has already happened, or that are more likely to resolve one day late than before the current expiry.
- **08:00 UTC strategic window:** when the current cycle is around `08:00 UTC`, give a modest confidence bonus to a daily setup that already passes all hard gates and has coherent Beecthor/Binance alignment. Do not demand late-session-level confirmation in this window: the point is to capture the first clean daily expression while there is still enough time for the market to reach the target.
- The `08:00 UTC` confidence bonus must never override hard protections: reconciliation gate, post-win daily cooldown, lateral/range lock, stale thesis rules, weekly ban, `> 90%` entry cap, cash/slot limits, or weak expiry validity.
- With less than `4h` left in a daily market, only open a new daily position when the strike is close, the probability is strong but below the hard cap, and Binance momentum points directly at that strike.
- **Post-win daily cooldown:** if a BTC daily `REACH` or `DIP` position has already resolved in our favor or been exited via take-profit during the current UTC day, do not open any additional BTC daily position until the next UTC day. This rule is about having already captured the daily prediction, not about the absolute size of the UTC-day BTC move.
- After a large intraday move, do not chase the next strike unless the market consolidates/retests or Binance shows fresh continuation in the opposite or reset structure. Avoid paying for "one more push" after most of the move is already spent.
- **Lateral regime / range lock:** when BTC has spent the last `24-72h` moving mostly sideways inside a narrow local range, do not open fresh daily positions from the middle of that range. Price-hit markets punish correct-but-early direction calls when expiry is tight.
- In a lateral regime, opening a `DIP` requires a clean breakdown: loss of the local range low, failed reclaim, downside expansion, or clear bearish repricing on Polymarket.
- In a lateral regime, opening a `REACH` requires a clean breakout: reclaim/break of the local range high, acceptance above it, upside expansion, or clear bullish repricing on Polymarket.
- If BTC is still inside the range and neither side has confirmed, return `NO_ACTION` even if Beecthor's level map remains useful. Use Beecthor's map to define the battlefield, not to force a timed bet.
- A daily or legacy weekly position with current Polymarket probability `<= 20%` may be treated as **discarded for slot purposes**:
  - it remains open
  - it does not trigger an automatic sell
  - it does not occupy the active slot of its type
  - it does not justify reopening the exact same market/outcome just to average down
  - any replacement trade of the same type must be materially cleaner than the discarded one
- **Polymarket probabilities are guidelines, except for the hard `> 90%` entry cap.** They move in real time with the BTC spot price — a market at 70% today may drop to 40% tomorrow simply because price moved away from the strike, with no change in the underlying thesis. Polymarket probabilities carry noise and should not override Beecthor's directional analysis unless the last ~48h of BTC price action clearly contradicts Beecthor.
- As a general guide, prefer markets with a Polymarket probability between `45%` and `90%` when the direction is aligned with Beecthor's thesis. If the probability is within this range and the thesis is aligned, there should be a strong reason to skip — do not invent vague excuses to avoid the trade.
- Proximity of the current BTC price to the strike is NOT a valid rejection reason on its own. The market price already reflects that proximity. If the thesis is aligned, that is sufficient.
- Be cautious below `45%` (limited market consensus). Apply this as a soft filter, not an absolute cutoff — a slightly out-of-range market with a very clear thesis is still worth considering.
- **Hard rule: never open a position with probability `> 90%`.** Risk/reward is too poor above that level — potential gain is minimal while downside remains real. No exceptions.
- Prefer higher-probability conservative setups when they still align with the thesis and stay at or below the 90% cap.
- As a portfolio construction rule, try to fill only the thesis-aligned daily slot whenever possible. The secondary daily momentum slot should only be filled when price action is clearly trending in a way that the main Beecthor thesis is not capturing well enough.
- Beecthor-bias correction: if recent Beecthor summaries remain bearish while BTC is flat or net higher over the same period, bearish `DIP` entries require explicit Binance rejection evidence (lower high, failed reclaim, support loss, downside expansion, or clear bearish repricing). Without that evidence, evaluate the nearest `REACH` momentum setup before forcing another bearish entry.
- Weekly entries are disabled. Do not open new weekly `REACH/DIP` positions under any evidence threshold.
- If discarded-position unrealized losses exceed `15-20%` of current bankroll, do not add new exposure in the same broad direction unless confirmation is exceptional.
- Maximum simultaneous exposure: **3 active open positions total** while any legacy weekly remains open; this preserves room for up to **2 active daily** positions plus a legacy weekly. Daily / legacy weekly positions marked as discarded for slot purposes do not count toward the active-position cap.
- Maximum new openings per cycle: **1**, and it must be a daily position.
- Maximum managed positions per cycle: **2**.
- Position cap by type:
  - **2 active daily** positions maximum
  - **0 new weekly** positions
- Weekly, monthly, longer-dated, and floor openings are not allowed.
- Base stake per entry: `15%` of currently available cash.
- **Early-stage cap:** while the total portfolio value (cash + open exposure) is below `$15`, the maximum stake per entry is `$1` regardless of the 15% rule.

## Exit rules

- Stop loss:
  - disabled — no stop-loss exits
  - if a daily or legacy weekly position drops to `<= 20%`, it may be treated as discarded for slot availability, but it still remains open until take-profit or natural resolution
  - no exceptional stop-loss exits are allowed; do not sell losing positions solely because they reached `<= 15-20%` or because the thesis looks invalidated
- Take profit:
  - automatically partial-exit `40-60%` once market probability reaches `80-85%` and expiry is not imminent
  - consider exit once market probability reaches `90%`
  - default full take profit range: `90-95%`
  - if two positions independently hit the take-profit zone in the same review, exiting both is valid
  - exception: if resolution is near-certain (market is about to close and the outcome is obvious), the position may be held to resolve naturally at 100%

## Execution freshness

- A pending entry order older than `120` minutes is stale and must be skipped instead of executed blindly.
- Phone execution live-price guard: even if the server approved an entry earlier, the phone must skip any `OPEN_POSITION` buy whose live Polymarket probability is now `> 90%`. This matches the server-side hard cap and protects against fast repricing between decision and execution.

## Post-win daily cooldown

- Strict daily rule: if any BTC daily `REACH` or `DIP` position resolves in our favor or is exited via take-profit on a given UTC day, do not open any new BTC daily `REACH` or `DIP` position until the next UTC day. The system may open the first daily position of the day even after a large BTC move, but once that first daily prediction has paid, the daily board is done for the day.
- The server must compute this from Polymarket account activity before calling the LLM and expose the result in the run context. If the activity check is unavailable, new daily openings are invalid until the check works again.
- Rationale: once the daily move has already paid, additional same-day daily entries are usually late-chase trades with worse risk/reward. Historical account activity shows that continuing to open daily positions after the first fulfilled position has reduced performance.
- Weekly openings are always forbidden for new entries, independently of the daily cooldown state. Legacy weekly positions may still be managed by the exit rules.

## Reconciliation rules

- Reconciliation is a **hard gate** for new entries. If any tracked open position disappeared without a matching closure record, or if a live position is missing from `account_state.json`, the next valid opening action is `NO_ACTION` until the mismatch is fixed.
- After each sync, every position that disappeared from `open_positions` must have a matching closure record in `trade_log.json`.
- Expired losers must be logged explicitly. Do not leave them implied by the next account snapshot.
- Before opening a new position, confirm that `account_state.json` and the latest `trade_log.json` tell a coherent story about cash, open exposure, and recently closed trades.

## Daily cadence

- Review window 1:
  - around `08:00 UTC` — primary strategic daily-entry window
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
