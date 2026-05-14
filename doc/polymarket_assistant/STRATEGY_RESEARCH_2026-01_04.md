# BTC Polymarket strategy research, 2026-01 to 2026-04

Research date: 2026-05-12

This document summarizes an exploratory backtest over Binance `BTCUSDT` 1m candles for January, February, March, and April 2026. It intentionally starts from market mechanics rather than the existing Beecthor or `far_dip_radar` strategies.

## Data used

- Binance spot monthly 1m klines:
  - `BTCUSDT-1m-2026-01.csv`
  - `BTCUSDT-1m-2026-02.csv`
  - `BTCUSDT-1m-2026-03.csv`
  - `BTCUSDT-1m-2026-04.csv`
- The first UTC hours of 2026-05-01 were fetched from Binance API to complete the 2026-04-30 ET market day.
- Market rules are documented in `doc/polymarket_assistant/MARKET_RULES.md`.
- Historical Polymarket CLOB prices were checked for daily hit-price markets from 2026-03-05 to 2026-04-30, where Gamma/CLOB data exists.

## Important limitations

- Binance candles determine exact outcomes for Binance-sourced markets, but they do not always determine entry price.
- Many very high win-rate patterns are probably priced close to certainty by Polymarket and may not be buyable with a 30-40% win payoff.
- For the CLOB-priced daily hit-price check, only entries with historical side price between `0.25` and `0.714` were counted. A price of `0.714` means a winning trade returns roughly `+40%` on the amount spent.
- January and February candles are useful for BTC behavior, but the current daily hit-price market family was not available through the same Gamma slug pattern for those months.
- Short-window `4h`, `15m`, and `5m` up/down markets use Chainlink, so Binance-only tests are not official for those markets.

## Executive conclusion

The strongest candidates are not the original Beecthor-style directional calls. The best candidates found are:

1. **Far No Range Guard**: buy `No` on very far daily `dip` or `reach` hit-price barriers early in the ET day, especially when the strike is at least `$4,000` away and the historical `No` price is still `<= 0.714`.
2. **Late Hour Momentum Follow**: for hourly up/down, follow the current 1h candle direction after minute `45` when it is already `$50-$150` away from the hourly open.
3. **Daily Up/Down Noon Follow**: for daily up/down, follow the direction 1-2h before noon ET if spot is already at least `$250-$500` away from the prior noon close.
4. **Noon Range Hold**: for price range markets, 1h before noon ET, bet the current `$2,000` bracket only when spot is not too close to either bracket edge.
5. **Close Target Yes Continuation**: buy `Yes` on nearby daily `reach/dip` targets `$500-$1,000` away later in the day, but only when the market price remains below `0.714`.

The strongest warning is equally clear: **mechanical fade / mean-reversion performed badly**. If BTC is already moving decisively in a short time window, fading that move was consistently poor in this sample.

## 1. Far No Range Guard

Market family: daily hit price `reach/dip`

Rule:

- Buy `No` on a daily hit-price market.
- Use Binance 1m path-dependent rules:
  - `reach`: `Yes` resolves if any later 1m `High >= strike`.
  - `dip`: `Yes` resolves if any later 1m `Low <= strike`.
- Prefer early ET-day entries.
- Prefer strikes at least `$4,000` away from current BTC spot.
- Only consider entries where historical `No` price was `0.25-0.714`.

Actual Polymarket CLOB-priced sample, March-April:

| Pattern | Trades | Wins | Losses | Win rate | Avg price | ROI per $1 trade |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `DIP_NO`, t+1h after ET open, distance `4000+` | 30 | 30 | 0 | 100.0% | 0.514 | +94.9% |
| `REACH_NO`, t+1h after ET open, distance `4000+` | 18 | 18 | 0 | 100.0% | 0.511 | +96.0% |
| `DIP_NO`, t+1h, distance `3000-4000` | 11 | 10 | 1 | 90.9% | 0.512 | +78.7% |
| `DIP_NO`, t+1h, distance `2500-3000` | 9 | 8 | 1 | 88.9% | 0.534 | +68.2% |
| `DIP_NO`, t+1h, distance `1500-2000` | 24 | 18 | 6 | 75.0% | 0.526 | +48.4% |

Interpretation:

- This is the clearest Polymarket-specific edge found so far.
- The surprising part is that some very far `No` barriers still had historical prices around `0.50-0.60`.
- The risk is crash/spike correlation: several far `No` positions can all lose together in an exceptional trend day.
- If implemented, this should start with one small position per cycle, not a basket of all available far `No` markets.

## 2. Late Hour Momentum Follow

Market family: hourly up/down

Rule:

- Observe a Binance 1h candle after it has already developed.
- If price is above the hourly open by a threshold, follow `Up`.
- If price is below the hourly open by a threshold, follow `Down`.
- Best-performing observation point: minute `45` of the hour.

Binance-only outcome scan, January-April:

| Pattern | Samples | Wins | Losses | Win rate |
| --- | ---: | ---: | ---: | ---: |
| `Down`, minute 45, move `>= $100` below open | 962 | 910 | 52 | 94.6% |
| `Up`, minute 45, move `>= $50` above open | 1167 | 1071 | 96 | 91.8% |
| `Down`, minute 45, move `>= $50` below open | 1186 | 1085 | 101 | 91.5% |
| `Up`, minute 45, move `>= $100` above open | 931 | 874 | 57 | 93.9% |
| `Down`, minute 45, move `>= $150` below open | 729 | 702 | 27 | 96.3% |

Interpretation:

- This is the most frequent and statistically stable pattern in pure Binance data.
- It probably has the least reasoning burden: a script can evaluate it mechanically.
- The unresolved question is price: at minute 45, Polymarket may already price the winning side too high for a `30-40%` payoff.
- It deserves a separate CLOB-price backtest before any implementation.

## 3. Daily Up/Down Noon Follow

Market family: daily up/down

Rule:

- Compare current BTC price with the previous `12:00 PM ET` close.
- If current price is already meaningfully above/below that prior close before current noon ET, follow the direction.
- Avoid fading the move.

Binance-only outcome scan, January-April:

| Pattern | Samples | Wins | Losses | Win rate |
| --- | ---: | ---: | ---: | ---: |
| `Down`, 1h before noon, lead `>= $250` | 60 | 59 | 1 | 98.3% |
| `Down`, 2h before noon, lead `>= $250` | 60 | 58 | 2 | 96.7% |
| `Up`, 1h before noon, lead `>= $250` | 48 | 46 | 2 | 95.8% |
| `Down`, 4h before noon, lead `>= $250` | 56 | 53 | 3 | 94.6% |
| `Down`, 4h before noon, lead `>= $500` | 40 | 39 | 1 | 97.5% |

Interpretation:

- Strong behaviorally, but probably less profitable if the market already prices it efficiently.
- Useful as a dashboard signal even if not immediately traded.
- It can also serve as a veto: do not take a conflicting Beecthor or hit-price trade if daily up/down momentum is already clear.

## 4. Noon Range Hold

Market family: daily price range

Rule:

- 1h before the `12:00 PM ET` resolution candle, identify the current `$2,000` price bracket.
- Bet the current bracket only if spot is not too close to the bracket boundary.

Binance-only outcome scan, January-April:

| Pattern | Samples | Wins | Losses | Win rate |
| --- | ---: | ---: | ---: | ---: |
| Current bracket, 1h before noon, edge buffer `>= $500` | 65 | 60 | 5 | 92.3% |
| Current bracket, 1h before noon, edge buffer `>= $250` | 94 | 80 | 14 | 85.1% |
| Current bracket, 1h before noon, no edge filter | 120 | 97 | 23 | 80.8% |

Interpretation:

- This is cleaner than hit-price markets because it is close-dependent, not wick-dependent.
- It may be a strong candidate for a small mechanical strategy if CLOB prices are not too expensive.
- Avoid entries near a bracket edge.

## 5. Close Target Yes Continuation

Market family: daily hit price `reach/dip`

Rule:

- Buy `Yes` on a nearby daily hit-price target.
- Target distance: roughly `$500-$1,000`.
- Prefer when historical price is `0.25-0.714`, leaving room for at least `+40%` on wins.

Actual Polymarket CLOB-priced sample, March-April:

| Pattern | Trades | Wins | Losses | Win rate | Avg price | ROI per $1 trade |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `REACH_YES`, t+6h, distance `500-1000` | 17 | 14 | 3 | 82.4% | 0.558 | +58.6% |
| `REACH_YES`, t+8h, distance `500-1000` | 16 | 12 | 4 | 75.0% | 0.539 | +47.4% |
| `REACH_YES`, t+10h, distance `500-1000` | 10 | 8 | 2 | 80.0% | 0.510 | +45.2% |
| `DIP_YES`, t+8h, distance `500-1000` | 19 | 14 | 5 | 73.7% | 0.519 | +36.1% |
| `DIP_YES`, t+12h, distance `500-1000` | 17 | 10 | 7 | 58.8% | 0.445 | +47.2% |

Interpretation:

- More volatile than Far No Range Guard.
- Better as an opportunistic continuation strategy than as a default daily system.
- Needs volatility and trend filters.

## Patterns to avoid

### Mechanical fading

- Hourly fade was consistently bad.
- Daily up/down fade was also bad.
- Example: daily fade against a clear move often had win rates around `17-27%`.

Conclusion: do not build a mean-reversion strategy just because BTC has already moved. The January-April sample says momentum continuation was much stronger than automatic fade.

### Blindly buying every cheap side

The actual CLOB-priced daily hit-price universe from March-April, filtered only by side price `0.25-0.714`, was slightly negative overall:

| Scope | Trades | Wins | Losses | Win rate | Avg price | ROI |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All daily hit-price sides with price `0.25-0.714` | 2339 | 1119 | 1220 | 47.8% | 0.482 | -2.5% |

Conclusion: the edge is in pattern selection, not in "cheap" markets by themselves.

## Proposed next research steps

1. Run a CLOB-price backtest for hourly up/down and daily up/down. The Binance outcome edge is strong, but entry price decides whether it is tradable.
2. Turn Far No Range Guard into a paper strategy with strict rules:
   - one position per cycle,
   - distance `>= $4,000`,
   - price `0.25-0.714`,
   - early ET day only,
   - skip high realized volatility days,
   - skip if Polymarket liquidity/spread is poor.
3. Research a paired range strategy: buy one far `NO reach` and one far `NO dip` only if combined risk/reward is favorable.
4. Add a dashboard page for research signals:
   - current ET-day open,
   - distance to far `reach/dip` barriers,
   - hourly candle progress,
   - daily up/down noon lead,
   - current price range bracket and edge buffer.

## Current practical ranking

1. **Far No Range Guard** — best actual CLOB-backed candidate.
2. **Late Hour Momentum Follow** — best behavioral candidate, pending price validation.
3. **Daily Up/Down Noon Follow** — clean directional signal, pending price validation.
4. **Noon Range Hold** — promising close-based candidate, pending price validation.
5. **Close Target Yes Continuation** — profitable in selected cases, but more discretionary and fragile.

## 2026-05-12 CLOB-backed recheck from 2026-03-08 onward

After identifying that `4h` up/down markets appear in Gamma from 2026-03-08 onward, the candidate families were rechecked using both:

- Binance 1m candles for the market outcome where Binance is the source.
- Polymarket CLOB `/prices-history` around the intended entry timestamp.

The entry filter was intentionally strict: only trades with historical side price between `0.25` and `0.714` were counted. This keeps the analysis focused on entries that could plausibly pay at least about `+40%` when correct.

### CLOB-backed summary

| Candidate | Entries | Wins | Losses | Win rate | Avg entry price | PnL if staking `$1` each | ROI per entry |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Far No Range Guard | 73 | 73 | 0 | 100.0% | 0.536 | +64.22 | +88.0% |
| Close Target Yes Continuation | 171 | 105 | 66 | 61.4% | 0.496 | +42.67 | +25.0% |
| Daily Up/Down Noon Follow | 3 | 3 | 0 | 100.0% | 0.688 | +1.36 | +45.3% |
| 4h Momentum Follow | 15 | 10 | 5 | 66.7% | 0.662 | -0.05 | -0.3% |

Notes:

- **Far No Range Guard remains the standout.** It survived the stricter date window and real Polymarket price check.
- **Close Target Yes Continuation remains positive but is less robust.** It needs tighter filtering before being automated.
- **Daily Up/Down Noon Follow has too few valid CLOB-priced entries** in this window to trust yet.
- **4h Momentum Follow does not currently justify implementation.** The outcome check here uses Binance as a proxy, while the actual 4h rules use Chainlink, and even with that favorable simplification the result is roughly flat.
- `Noon Range Hold` and `Above Ladder Guard` did not produce eligible entries under the specific tested filters and CLOB price band. They remain research candidates, but not deployment candidates.

### Updated practical ranking after the CLOB-backed recheck

1. **Far No Range Guard** — still the only strong deployment candidate.
2. **Close Target Yes Continuation** — profitable, but needs additional filters.
3. **Daily Up/Down Noon Follow** — promising signal, insufficient priced sample.
4. **Noon Range Hold / Above Ladder** — unresolved; no eligible priced sample under current filters.
5. **4h Momentum Follow** — deprioritize for now.
