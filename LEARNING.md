# LEARNING.md

## Polymarket automation retrospective

**Date:** 2026-04-25  
**Scope:** Beecthor thesis, BTC trend, `trade_log.json`, `account_state.json`, and `doc/polymarket_assistant/PLAYBOOK.md`.  
**Purpose:** identify practical improvements that can increase expected profit and reduce avoidable losses.

This is not financial advice. It is an operational learning document for the current BTC Polymarket automation.

---

## 1. Current diagnosis

The system is not broken. It is in a learning phase where the infrastructure is already doing useful work, but the strategy still has two clear tensions:

1. **Beecthor is structurally bearish most of the time.**
2. **BTC has recently been more resilient than that bearish framing expected.**

That does not make Beecthor useless. His value is strongest as a **level map**: resistances, invalidation zones, liquidation clusters, possible reaction points, and likely paths. His weakest current contribution is directional certainty when the market keeps grinding upward despite bearish structure.

Our best lesson so far:

> We should use Beecthor to define the battlefield, but not let his permanent bearish bias choose the side automatically.

The current automation already understands this in principle: the playbook says Binance provides execution reality and both `REACH` and `DIP` must be evaluated. The next improvement is making that rule more enforceable and measurable.

---

## 2. BTC trend context

Recent Binance BTCUSDT 1h data sampled on 2026-04-25 around 09:00 UTC:

| Window | Start | End | Change | High | Low |
|---|---:|---:|---:|---:|---:|
| 24h | 77,752 | 77,761 | +0.01% | 78,479 | 77,264 |
| 48h | 77,404 | 77,761 | +0.46% | 78,663 | 76,960 |
| 72h | 78,157 | 77,761 | -0.51% | 79,473 | 76,960 |
| 96h | 76,746 | 77,761 | +1.32% | 79,473 | 74,822 |

Interpretation:

- BTC had a strong push into the 78k-79.5k area, then moved into a choppy consolidation.
- The last 72h are not a clean bearish breakdown. They are a failed/paused upside extension inside a higher range.
- Beecthor's 78k-82k resistance map has been useful.
- His repeated expectation of a deeper move toward 72k-70k has not yet materialized in the latest sequence.
- The market currently looks more like **range compression near resistance** than an already confirmed bearish continuation.

Implication for the bot:

> When BTC is holding a higher range after a rally, bearish `DIP` trades need stronger confirmation than "Beecthor still thinks the macro is bearish."

---

## 3. Beecthor thesis assessment

Recent summaries show a stable Beecthor pattern:

- Macro view remains bearish.
- Rebounds are treated as corrective.
- The 78k-82k area is repeatedly framed as a short/resistance zone.
- Downside magnets are repeatedly named: 76.4k, 75.15k, 74.8k, 73k, 72k, 70k.
- Invalidation remains far above current price, usually around 86k.

What has been good:

- His resistance zones have been relevant.
- His levels have helped identify Polymarket strikes that actually matter.
- His "sell strength" framing can work well for daily `DIP` markets when the market has already shown weakness.
- His liquidation/level map is useful for selecting the nearest meaningful strike.

What has been weak:

- He has stayed bearish through a period where BTC moved from the low/mid 70k area into the high 70k area.
- The system can become too willing to open bearish daily/weekly `DIP` positions just because the thesis is still bearish.
- If Beecthor says "possible final push higher before downside", the system sometimes treats the downside as actionable too early.
- His bias is often right about **where a reversal might matter**, but early about **when the reversal has actually started**.

Recommended interpretation:

> Treat Beecthor's thesis as conditional: "if price rejects this zone, then bearish continuation is likely." Do not convert it into a bearish bet until Binance confirms rejection or Polymarket offers unusually good risk/reward.

---

## 4. Trade log summary

`trade_log.json` currently contains:

| Metric | Value |
|---|---:|
| Total entries | 193 |
| Cycle runs | 173 |
| Live cycles | 166 |
| Dry-run cycles | 7 |
| Closed trades logged | 10 |
| Open-position decisions | 38 |
| Executed cycle actions | 33 |
| Validation rejections | 8 |

Closed trade performance from logged `trade_closed` entries:

| Metric | Value |
|---|---:|
| Closed wins | 9 |
| Closed losses | 1 |
| Closed win rate | 90% |
| Sum of logged closed PnL | +9.4991 |
| Average win | +1.2962 |
| Average loss | -2.1666 |
| Take-profit exits | 8 |
| Take-profit PnL | +11.3245 |
| Expired losses | 1 |
| Expired-loss PnL | -2.1666 |

By direction:

| Direction | Trades | Wins | Losses | PnL |
|---|---:|---:|---:|---:|
| DIP | 5 | 5 | 0 | +4.2335 |
| REACH | 5 | 4 | 1 | +5.2656 |

By market duration:

| Type | Trades | Wins | Losses | PnL |
|---|---:|---:|---:|---:|
| Daily | 8 | 8 | 0 | +6.7391 |
| Weekly | 2 | 1 | 1 | +2.7600 |

Important caveat:

The raw closed-trade PnL is not the same thing as true account performance. `account_state.json` currently shows:

| Field | Value |
|---|---:|
| Starting bankroll | 7.842164 |
| Cash available | 8.291378 |
| Open exposure | 1.0102 |
| Tracked portfolio value | 9.3016 |
| Net vs starting bankroll | +1.4594 |
| `realized_pnl` field | +0.3412 |

There are also three open positions:

| Market | Status | Entry | Current value | PnL |
|---|---|---:|---:|---:|
| weekly 72k DIP | discarded_for_slot | 0.9625 | 0.0250 | -0.9375 |
| weekly 80k REACH | discarded_for_slot | 0.9690 | 0.2125 | -0.7565 |
| daily 77k DIP | active | 0.9719 | 0.7727 | -0.1992 |

Takeaway:

> The closed-trade win rate looks excellent, but the account-level truth is less clean because open discarded positions can hide losses until resolution. We should optimize for account equity, not just closed wins.

---

## 5. What is working

### Take-profit automation is the strongest module

The best realized PnL comes from take-profit exits. Eight logged take-profit exits produced +11.3245 before considering other losses. This suggests the monitor is doing exactly what a human would often fail to do: take the money when Polymarket reprices the outcome strongly in our favor.

Improvement direction:

- Keep the take-profit monitor.
- Consider adding earlier partial exits.
- Keep using Polymarket probability as the exit trigger, because that is the tradable venue.

### Validation is protecting the system

The validator rejected bad proposals:

- nearest-strike-first failures
- probability below minimum
- max open position cap

This is a real strength. The LLM can produce a plausible narrative, but the validator stops it from turning every plausible story into a trade.

Improvement direction:

- Add more validation around trend conflict and late-session entries.
- Keep hard gates for reconciliation and stale pending orders.

### Small stake sizing has preserved learning capital

The `$1` early-stage cap is doing its job. The strategy has been able to learn through real execution without letting any single mistake dominate the account.

Improvement direction:

- Do not scale stake yet.
- Require a cleaner account-level performance snapshot before increasing size.

### Daily markets have been better than weekly markets

Logged daily positions are 8/8 closed wins. Weekly trades include the biggest expired loss. This does not mean weekly markets are bad, but it does mean weekly exposure needs a stricter rule set.

Improvement direction:

- Keep daily as the primary experimentation surface.
- Make weekly entries more selective.
- Avoid weekly trades after much of the move has already happened.

---

## 6. What is not working well enough

### Beecthor bias is still overweighted

The playbook says Binance provides execution reality, but recent decisions still show repeated bearish framing even when BTC was holding a higher range.

Problem:

- Beecthor says "bearish macro".
- BTC holds above prior support and keeps testing resistance.
- The system opens or prefers `DIP` too early.

Better rule:

> If Beecthor is bearish but BTC is making higher lows or holding above the last video price, require explicit rejection evidence before opening a bearish daily thesis trade.

### Discarded positions can become hidden losses

The discarded-slot mechanism is useful because it prevents dead positions from blocking new ideas. But it also creates a psychological/accounting problem: the position remains open and can quietly become a near-total loss.

Problem:

- Slot is freed.
- The loss is not realized.
- The bot may keep trading while account equity is worse than the closed-trade stats imply.

Better rule:

> Discarded positions should still count toward a separate "pain budget" and be included prominently in every decision context.

### Weekly trades carry too much dead-position risk

Weekly markets can produce large wins, but if the thesis is early or wrong, they can sit as low-probability leftovers for days.

Problem:

- Weekly 72k DIP and 80k REACH are both currently discarded.
- They no longer block slots, but they still represent capital tied to losing outcomes.

Better rule:

> Weekly trades should require stronger evidence than daily trades, not weaker evidence. They should be entered early in the weekly period and only when the strike is the obvious frontier.

### The system can confuse "level likely eventually" with "market likely before expiry"

This is the core Polymarket problem. Beecthor may be right that BTC eventually revisits 72k or 70k, but a daily or weekly market only pays if it happens before expiry.

Better rule:

> Every decision must explicitly answer: "Is the timing good enough for this expiry, or is this just a correct level on the wrong clock?"

### Accounting is not yet clean enough for confident scaling

There is a mismatch between:

- logged closed PnL
- `account_state.realized_pnl`
- open exposure
- user-level sense that the account is roughly flat

This is normal for an evolving bot, but it matters before scaling.

Better rule:

> Do not increase stake size until account equity, realized PnL, open exposure, redeemed/resolved markets, and pending orders reconcile cleanly from one source of truth.

### Pending order state can become stale

`pending_orders.json` currently still contains an order for the daily 77k DIP even though `account_state.json` already sees the position. The phone may dedupe locally, but the repo queue should not remain ambiguous.

Better rule:

> Phone execution must write back an execution receipt or send a server callback that lets the server mark the queue item as executed.

---

## 7. Recommended playbook improvements

### 1. Add a Beecthor bias correction rule

Suggested rule:

> If Beecthor has kept the same bearish thesis for at least three recent videos while BTC is net higher over the same period, the system must downgrade bearish thesis confidence by one level unless Binance shows a fresh rejection, lower high, failed reclaim, or strong downside momentum.

Operational version:

- Compare latest video BTC price vs current BTC.
- Compare 24h/48h/72h trend.
- If BTC is above the latest video price and the last 48h trend is positive or flat, bearish `DIP` entries require rejection evidence.
- If BTC is below the latest video price and breaking lower, bearish `DIP` entries can proceed normally.

### 2. Separate "level validity" from "expiry validity"

Add this mandatory decision field mentally or in prompt:

```text
level_validity: is the strike a meaningful Beecthor/Binance level?
expiry_validity: is it likely to be hit before this market expires?
```

Trade only when both are true.

This would reduce trades where the thesis is directionally reasonable but too slow for the Polymarket contract.

### 3. Strengthen daily momentum permission

Current rule allows daily momentum when Binance shows very clear continuation. Make it more concrete:

Allow counter-thesis daily momentum only when at least two are true:

- BTC is above the latest Beecthor video price.
- BTC is holding the upper half of its 24h range.
- BTC has made a higher high or higher low in the last 12h.
- Polymarket probability is in the 45-75% range, not already expensive.
- The nearest reach/dip strike is within realistic intraday range.

This protects us from Beecthor's directional lag without turning the bot into pure chase mode.

### 4. Add partial take-profit

Current rule:

- consider exit at 90-95%

Suggested refinement:

- At 80-85%: optionally sell 50% if the position is already up strongly and expiry is not near.
- At 90-95%: sell the rest by default.
- Near-certain expiry can still be held, but only if time to resolution is short and liquidity is poor.

Reason:

Some of the diary notes show the pain of being very close to a target and giving back edge. A partial take-profit rule would convert "almost right" into realized account growth more often.

### 5. Add a discarded-position pain budget

Suggested rule:

> If total unrealized loss from discarded positions exceeds 15-20% of current bankroll, do not open new positions in the same broad direction until the next cycle shows fresh confirmation.

This keeps discarded positions from becoming invisible leverage.

### 6. Make weekly entries stricter

Suggested weekly rules:

- Prefer weekly entries in the first half of the weekly period.
- Do not open a weekly trade if the thesis depends on a move that already failed as a daily thesis.
- Do not open a weekly momentum slot unless the weekly thesis slot is active or discarded and the next strike is still close enough to the frontier.
- Avoid weekly probabilities below 25% unless there is exceptional evidence.

### 7. Add late-session daily restrictions

Suggested rule:

> With less than 4h left in the daily market, open a new daily position only if the strike is close, the probability is already in a strong but not expensive band, and Binance momentum points directly at that strike.

This avoids paying for a correct idea that needs one more leg after the clock has nearly run out.

### 8. Add stronger queue reconciliation

Suggested operational rule:

- Every pending order should end in one of:
  - `executed`
  - `skipped_already_done`
  - `stale`
  - `failed`
- The phone should notify the server/dashboard, and the server should clean or archive the queue.

The dashboard already has mobile log ingestion, so this is now feasible.

### 9. Add a real performance snapshot

The system should compute after every cycle:

- starting bankroll
- cash
- live open value
- redeemable/won value
- unresolved loser value
- realized PnL
- unrealized PnL
- net account equity
- win rate by slot
- PnL by slot
- PnL by Beecthor-aligned vs momentum

This would prevent the bot from feeling profitable because closed trades look good while dead positions hide in open exposure.

---

## 8. Recommended prompt improvements

Add these questions to the decision prompt before the final JSON:

```text
Before choosing action, answer internally:
1. Is Beecthor giving a confirmed direction, or mostly a level map?
2. Has BTC confirmed Beecthor's direction since the latest video?
3. What is the strongest opposite-direction trade, and why is it rejected or accepted?
4. Is this trade likely to resolve before expiry, not merely eventually?
5. Are discarded positions hiding current account pain in this same direction?
6. Would this trade still be attractive if Beecthor's macro bias were ignored?
```

Expected effect:

- Less automatic bearishness.
- Better use of momentum slots.
- Fewer trades based on "eventually correct" levels.
- More honest handling of open losses.

---

## 9. Current strategic stance

Given the last 72h:

- BTC is not strongly trending up anymore.
- BTC is also not breaking down decisively.
- Beecthor's resistance zone around 78k-82k remains relevant.
- His deeper downside map remains possible, but not confirmed.
- Current open daily 77k DIP is understandable, but it should not justify stacking more bearish exposure unless price actually rejects and moves lower.

Best current behavior:

1. Let the current daily 77k DIP resolve or hit take-profit.
2. Do not add a second bearish daily unless BTC breaks lower with confirmation.
3. Avoid new weekly bearish exposure while two discarded weekly positions already exist.
4. If BTC reclaims strength toward 79k-80k, evaluate nearest `REACH` as a possible momentum setup instead of forcing another `DIP`.
5. Keep stake at `$1` until accounting is cleaner.

## 10. Highest-leverage improvements

These are the clearest improvements if the goal is specifically to increase expected profit and reduce drawdowns. They are ordered by expected impact, not by implementation difficulty.

### 1. Add partial take-profit before the full take-profit zone

**Why it matters:** our best-performing component is the take-profit monitor. The system makes money when it converts a correct move into realized cash. The diary already shows the pain point: being very close to target, being "right enough", and still risking a full give-back.

Recommended rule:

- At `80-85%` Polymarket probability: sell `40-60%` if the position is up strongly and expiry is not imminent.
- At `90-95%`: sell the rest by default.
- If the market is within minutes of obvious resolution and liquidity is bad, holding to resolution remains allowed.

Expected benefit:

- More realized wins.
- Lower variance.
- Less dependence on perfect resolution.

Implementation target:

- `polymarket_assistant/run_monitor.py`
- `phone/polymarket_monitor_executor.py`
- dashboard log labels for `PARTIAL_TAKE_PROFIT` and `FULL_TAKE_PROFIT`

### 2. Add an account-equity gate, not just a trade-count/win-rate view

**Why it matters:** closed trades look excellent, but discarded open positions can hide losses. We need to optimize for account equity, not only "closed winners".

Recommended rule:

- Every cycle computes `net_liquidation_value = cash + live open value + redeemable value`.
- New trades are throttled if:
  - equity is below starting bankroll,
  - unrealized discarded losses exceed a threshold,
  - or the last N trades produced negative equity delta despite positive closed win rate.

Expected benefit:

- Prevents "winning trades, losing account" behavior.
- Stops the bot from adding risk while old losses are still bleeding.

Implementation target:

- `polymarket_assistant/run_cycle.py`
- dashboard `build_polymarket_snapshot()`
- optional new `performance_snapshot.json`

### 3. Introduce a discarded-position pain budget

**Why it matters:** the discarded-slot rule is useful, but it currently frees slot capacity while capital remains impaired. That can lead to layered exposure in the same broad wrong thesis.

Recommended rule:

- Track total unrealized loss from `discarded_for_slot` positions.
- If discarded unrealized loss is more than `15-20%` of current bankroll, block new trades in the same broad direction.
- If two discarded positions exist at once, weekly trades require exceptional confirmation.

Expected benefit:

- Fewer repeated bets in a thesis that is currently failing.
- Better protection against death-by-many-small-$1 positions.

Implementation target:

- Playbook
- prompt context
- `validate_decision()`

### 4. Make weekly entries much stricter

**Why it matters:** daily trades have been cleaner in the logged history; weekly trades can become dead capital for days. The largest logged loss came from an expired weekly `REACH`.

Recommended rule:

- Weekly trades are allowed mostly in the first half of the weekly period.
- Weekly probability below `25%` should be avoided unless there is exceptional evidence.
- Do not open a weekly trade if the same directional thesis has just failed as a daily.
- Do not open a second weekly just because a slot is free.

Expected benefit:

- Less capital tied in low-probability leftovers.
- Fewer slow losses from stale narratives.

Implementation target:

- Playbook
- GPT prompt
- validation around `market_type == weekly`

### 5. Add Beecthor-bias correction

**Why it matters:** Beecthor's level map is useful, but his macro bias is often bearish. BTC recently spent days holding higher than that bias implied. The system should not automatically translate "Beecthor bearish" into `DIP`.

Recommended rule:

- If Beecthor has been bearish for 3+ recent summaries while BTC is net higher or flat over the same period, bearish entries require explicit Binance rejection evidence.
- Evidence can include lower high, failed reclaim, loss of support, strong downside candle, or Polymarket repricing in the bearish direction.
- If no rejection evidence exists, evaluate `REACH` momentum before opening `DIP`.

Expected benefit:

- Fewer early bearish entries.
- Better use of the daily momentum slot.
- More alignment with actual price behavior.

Implementation target:

- Playbook
- prompt
- optional trend classifier in `build_context_snapshot()`

### 6. Add expiry-validity as a hard decision concept

**Why it matters:** Beecthor may identify a level that is likely eventually, but Polymarket pays only if the strike is hit before expiry. This is probably one of the biggest hidden sources of bad trades.

Recommended rule:

- A trade needs both `level_validity` and `expiry_validity`.
- If the thesis is "it may hit tomorrow or next week", do not use a same-day market.
- With less than `4h` left in a daily market, require direct momentum toward the strike.

Expected benefit:

- Fewer "right level, wrong clock" losses.
- Cleaner separation between daily and weekly setups.

Implementation target:

- Prompt
- playbook
- validation for late-session daily entries

### 7. Add phone-to-server execution receipts

**Why it matters:** the server can enqueue, the phone can execute, and the dashboard can show logs, but the queue can still remain ambiguous. This is operational risk, not strategy risk.

Recommended rule:

- Every pending order must end as `executed`, `skipped_already_done`, `stale`, or `failed`.
- The phone sends a callback to the server after each outcome.
- The server cleans or archives `pending_orders.json`.

Expected benefit:

- Less manual reconciliation.
- Fewer ghost orders.
- More trust in the dashboard.

Implementation target:

- `phone/polymarket_executor.py`
- `server/copilot_chat.py` mobile-log endpoint or a dedicated order-receipt endpoint
- `pending_orders.json` lifecycle

### 8. Add a real stop-loss policy for exceptional cases

**Why it matters:** no automated stop-loss has protected us from panic exits, but "never sell losers" can leave too much dead capital. We do not need a normal tight stop-loss, but we do need an emergency invalidation exit.

Recommended rule:

- Keep normal stop-loss disabled.
- Add `thesis_invalidated_exit` only when all are true:
  - position probability is below `15-20%`,
  - Beecthor thesis no longer supports it,
  - Binance confirms opposite structure,
  - and there is enough liquidity to exit without absurd slippage.

Expected benefit:

- Avoids holding hopeless positions only because the playbook has no sell-loser path.
- Still avoids emotional stop-loss churn.

Implementation target:

- Playbook
- monitor logic
- GPT decision schema already supports `CLOSE_POSITION` with `thesis_invalidated`

### 9. Add "do nothing after big move" cooling rules

**Why it matters:** several decisions happen after BTC has already used much of the move. Chasing a second leg creates bad timing risk.

Recommended rule:

- If BTC has already moved more than a configurable intraday threshold toward the strike, require either consolidation/retest or skip.
- If a daily strike requires one more extension after a large move, prefer `NO_ACTION` unless Polymarket still prices it attractively and Binance momentum is strong.

Expected benefit:

- Less late chasing.
- Fewer entries where the market needed "just one more push" before expiry.

Implementation target:

- Playbook
- `build_price_structure_context()`
- validation warning or hard gate

### 10. Improve post-trade learning by slot

**Why it matters:** we need to know whether profit comes from thesis daily, momentum daily, weekly thesis, or weekly momentum. Right now the history is useful, but not enough to tune slot-level behavior confidently.

Recommended rule:

- Every opened trade stores:
  - `slot_name`
  - `beecthor_aligned: true/false`
  - `momentum_confirmed: true/false`
  - `expiry_hours_at_entry`
  - `entry_probability_band`
- Performance snapshot groups PnL by those fields.

Expected benefit:

- We learn which parts of the strategy deserve more capital.
- We stop arguing from anecdotes.

Implementation target:

- `run_cycle.py`
- `trade_log.json` schema
- dashboard private metrics

### Priority order

| Priority | Improvement | Main benefit |
|---:|---|---|
| 1 | Partial take-profit | More realized gains, lower variance |
| 2 | Account-equity gate | Prevents hidden-loss overtrading |
| 3 | Discarded-position pain budget | Stops repeated wrong-thesis exposure |
| 4 | Stricter weekly entries | Reduces slow dead-capital losses |
| 5 | Beecthor-bias correction | Reduces automatic bearish overfitting |
| 6 | Expiry-validity gate | Avoids right-level/wrong-clock trades |
| 7 | Execution receipts | Reduces operational ambiguity |
| 8 | Exceptional stop-loss | Releases hopeless positions selectively |
| 9 | Post-big-move cooling | Reduces chasing |
| 10 | Slot-level performance learning | Enables better future tuning |

---

## 11. Concrete next actions

Highest-impact changes:

1. **Update the playbook with Beecthor bias correction.**
2. **Add expiry-validity language to the playbook and prompt.**
3. **Add partial take-profit rules.**
4. **Add discarded-position pain budget.**
5. **Make weekly entries stricter.**
6. **Implement queue status callbacks from the phone to the server.**
7. **Build an account-equity performance snapshot independent of closed-trade win rate.**

Suggested order:

1. Playbook/prompt changes first.
2. Then accounting snapshot.
3. Then phone/server queue cleanup.
4. Then partial take-profit implementation.

This keeps strategy and observability aligned before we add more moving parts.

---

## 12. One-line lesson

The system's biggest edge is not predicting BTC perfectly; it is combining Beecthor's level map, Binance's current reality, Polymarket probabilities, and disciplined automated exits. The next leap is reducing thesis bias and making account equity, not narrative correctness, the scoreboard.
