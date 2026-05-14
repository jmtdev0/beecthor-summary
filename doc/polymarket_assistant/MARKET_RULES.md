# Polymarket BTC market rules

This file records the resolution mechanics for BTC Polymarket market families that may be useful for strategy research. Rules were checked against live Polymarket pages on 2026-05-12.

Operational note: do not treat this file as a substitute for the current market page. Before enabling a new strategy against a market family, re-read the specific market's `Rules` block and confirm the source, candle interval, time window, and boundary behavior.

## Shared cautions

- Polymarket pages can reuse similar titles with different resolution sources. Do not infer a market's source from the UI category alone.
- For Binance-based markets, the relevant pair is usually `BTC/USDT` on Binance, not another exchange, pair, or spot index.
- For Chainlink-based short-window markets, Binance candles are not the source of truth.
- Time labels on Polymarket BTC pages are usually expressed in `ET`. Convert explicitly when backtesting or scheduling from UTC.
- Historical backtests must use the exact candle field in the rules: `High`, `Low`, `Open`, or `Close`.

## Market families

| Family | Example URL | Source | Resolution field | Window | Boundary behavior | Current interest |
| --- | --- | --- | --- | --- | --- | --- |
| Daily hit price: `reach` | `https://polymarket.com/event/what-price-will-bitcoin-hit-on-may-12` | Binance `BTC/USDT` | 1m candle `High` | Date in title, `12:00 AM ET` to `11:59 PM ET` | `Yes` if `High >= strike`; otherwise `No` | High |
| Daily hit price: `dip` | `https://polymarket.com/event/what-price-will-bitcoin-hit-on-may-12` | Binance `BTC/USDT` | 1m candle `Low` | Date in title, `12:00 AM ET` to `11:59 PM ET` | `Yes` if `Low <= strike`; otherwise `No` | High |
| Weekly hit price: `reach` | `https://polymarket.com/event/what-price-will-bitcoin-hit-may-11-17` | Binance `BTC/USDT` | 1m candle `High` | Date range in title, first date `12:00 AM ET` to last date `11:59 PM ET` | `Yes` if `High >= strike`; otherwise `No` | Low, currently disabled for new entries |
| Weekly hit price: `dip` | `https://polymarket.com/event/what-price-will-bitcoin-hit-may-11-17` | Binance `BTC/USDT` | 1m candle `Low` | Date range in title, first date `12:00 AM ET` to last date `11:59 PM ET` | `Yes` if `Low <= strike`; otherwise `No` | Low, currently disabled for new entries |
| Monthly hit price: `reach` | `https://polymarket.com/event/what-price-will-bitcoin-hit-in-may-2026` | Binance `BTC/USDT` | 1m candle `High` | Month in title, first day `12:00 AM ET` to last day `11:59 PM ET` | `Yes` if `High >= strike`; otherwise `No` | Research only |
| Monthly hit price: `dip` | `https://polymarket.com/event/what-price-will-bitcoin-hit-in-may-2026` | Binance `BTC/USDT` | 1m candle `Low` | Month in title, first day `12:00 AM ET` to last day `11:59 PM ET` | `Yes` if `Low <= strike`; otherwise `No` | Research only |
| Daily `above` ladder | `https://polymarket.com/event/bitcoin-above-on-may-13` | Binance `BTC/USDT` | 1m candle `Close` | The `12:00 PM ET` candle on the date in title | `Yes` if close is higher than strike; otherwise `No` | Medium |
| Intraday `above` ladder | `https://polymarket.com/event/bitcoin-above-on-may-12-2026-2pm-et` | Binance `BTC/USDT` | 1h candle `Close` | The 1h candle that ends at the time/date in title | `Yes` if close is higher than strike; otherwise `No` | Research only |
| Daily price range | `https://polymarket.com/event/bitcoin-price-on-may-13` | Binance `BTC/USDT` | 1m candle `Close` | The `12:00 PM ET` candle on the date in title | Resolves to the matching bracket; if exactly on a boundary, resolves to the higher bracket | Medium |
| Daily up/down | `https://polymarket.com/event/bitcoin-up-or-down-on-may-13-2026` | Binance `BTC/USDT` | 1m candle `Close` | Compare prior date `12:00 PM ET` close vs current date `12:00 PM ET` close | `Up` if current close is higher; `Down` if lower; exact equality resolves `50-50` | Medium |
| Hourly up/down | `https://polymarket.com/event/bitcoin-up-or-down-may-12-2026-1pm-et` | Binance `BTC/USDT` | 1h candle `Open` and `Close` | 1h candle beginning at the time/date in title | `Up` if `Close >= Open`; otherwise `Down` | Medium research |
| 4h up/down | `https://polymarket.com/event/btc-updown-4h-1778601600` | Chainlink `BTC/USD` data stream | Start and end stream price | Time range in title | `Up` if end price is `>=` beginning price; otherwise `Down` | Research only |
| 15m up/down | `https://polymarket.com/event/btc-updown-15m-1778607000` | Chainlink `BTC/USD` data stream | Start and end stream price | Time range in title | `Up` if end price is `>=` beginning price; otherwise `Down` | Research only |
| 5m up/down | `https://polymarket.com/event/btc-updown-5m-1778607300` | Chainlink `BTC/USD` data stream | Start and end stream price | Time range in title | `Up` if end price is `>=` beginning price; otherwise `Down` | Research only |

## Strategy implications

### Hit price markets

- These are path-dependent, not close-dependent.
- For `reach`, a single 1m `High` touching the strike is enough.
- For `dip`, a single 1m `Low` touching the strike is enough.
- Backtests must scan every 1m candle in the ET window, not just daily open/close.
- `NO` positions in far-away `dip` or `reach` markets are short volatility/path risk: the trade can lose even if the final close is far from the strike.

### Above and price range markets

- These are point-in-time close markets.
- They can be backtested from a single Binance candle, usually the `12:00 PM ET` 1m close for daily markets.
- They are less exposed to intraday wicks than hit-price markets.
- Boundary behavior matters: range markets assign exact bracket boundaries to the higher bracket.

### Up/down markets

- Daily and hourly Binance variants are candle-comparison markets.
- Short-window 4h/15m/5m variants seen on 2026-05-12 use Chainlink, not Binance.
- Because Chainlink can differ slightly from Binance, Binance-only backtests are not valid for Chainlink up/down markets unless Chainlink history is also collected.

## Source pages checked

- `https://polymarket.com/event/what-price-will-bitcoin-hit-on-may-12`
- `https://polymarket.com/event/what-price-will-bitcoin-hit-may-11-17`
- `https://polymarket.com/event/what-price-will-bitcoin-hit-in-may-2026`
- `https://polymarket.com/event/bitcoin-above-on-may-13`
- `https://polymarket.com/event/bitcoin-above-on-may-12-2026-2pm-et`
- `https://polymarket.com/event/bitcoin-price-on-may-13`
- `https://polymarket.com/event/bitcoin-up-or-down-on-may-13-2026`
- `https://polymarket.com/event/bitcoin-up-or-down-may-12-2026-1pm-et`
- `https://polymarket.com/event/btc-updown-4h-1778601600`
- `https://polymarket.com/event/btc-updown-15m-1778607000`
- `https://polymarket.com/event/btc-updown-5m-1778607300`
