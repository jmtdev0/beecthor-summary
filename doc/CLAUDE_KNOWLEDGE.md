# Claude Knowledge Base — Beecthor Summary / Polymarket Operator

Last updated: 2026-04-16

This file documents everything Claude currently knows about this project. It is intended as a persistent context reference for future conversations.

---

## Project Overview

An autonomous BTC trading bot that:
1. Fetches and summarizes Beecthor's daily YouTube analysis videos.
2. Uses GPT (GitHub Copilot CLI) to make Polymarket trading decisions based on Beecthor's thesis.
3. Executes orders on Polymarket via a phone (Termux/Android) using a residential IP.
4. Monitors open positions and triggers take-profit automatically.

**GitHub repo**: `jmtdev0/beecthor-summary` (private)

---

## Infrastructure

### Hetzner VPS
- **IP**: redacted (see private notes)
- **OS**: Ubuntu + XFCE4 + xrdp
- **Python venv**: `/root/beecthor-summary/.venv`
- **Project root**: `/root/beecthor-summary`
- **Dashboard**: Flask app at port 5050 (`server/copilot_chat.py`), always running
- **RDP**: connect via mstsc with user `root` (credentials in private notes)
- **xrdp gotcha**: if black screen on login, check for orphaned `xfce4-session` holding `org.xfce.SessionManager` on dbus. Fix: `pkill -TERM xfce4-session` then kill remaining XFCE procs.

### Phone (Termux/Android)
- Runs order executors as cron jobs
- Connected to server via autossh reverse tunnel: phone → server:2222 → phone SSH port 8022
- Key env file: `~/.polymarket.env`
- Cron jobs: `polymarket_executor.py` and `beecthor_summarizer.py`

### GitHub as communication bus
- Server commits `pending_orders.json` → phone reads via GitHub Contents API and executes
- Server commits `last_run_summary.json`, `account_state.json`, `trade_log.json`

---

## Blockchain / Wallet

- **Network**: Polygon (chain_id=137)
- **POLY_FUNDER**: redacted (see `.env`)
  - This is a **smart contract proxy wallet** (EIP-1167 minimal proxy, 45 bytes)
  - Implementation at a custom Polymarket contract (unverified ABI)
  - Holds the ERC-1155 conditional tokens (positions)
  - Does NOT hold POL (gas) — sending POL here fails because the contract has no `receive()`
- **POLY_SIGNER_ADDRESS**: redacted (see `.env`)
  - This is an EOA controlled by `POLY_PRIVATE_KEY`
  - Has ~1 POL for gas (sent 2026-04-16)
  - Signs CLOB orders (EIP-712) on behalf of the funder
- **USDC (collateral)**: `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (USDC.e on Polygon)
- **CTF Exchange**: `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`
- **ConditionalTokens**: `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045`

### Redemption status (as of 2026-04-16)
On-chain redemption requires calling `redeemPositions` from the funder proxy. The proxy ABI is custom/unverified — we cannot call through it from the signer. This is a known limitation. LOST positions are filtered out of the active position list automatically (see `fetch_positions` fix below). WON positions are sold via the CLOB before resolution by the monitor.

---

## Key Files

### Decision & Cycle
| File | Purpose |
|------|---------|
| `polymarket_assistant/run_cycle.py` | Main base cycle: builds context, calls GPT, validates, executes |
| `polymarket_assistant/run_cycle_codex.py` | Codex-specific variant: accepts normalized JSON decisions with `run_id` |
| `polymarket_assistant/run_monitor.py` | Runs every 2h (odd UTC hours), checks take-profit, writes SELL orders |
| `doc/polymarket_assistant/PLAYBOOK.md` | Binding trading rules for GPT |
| `doc/polymarket_assistant/copilot_prompt.md` | GPT prompt template + JSON schema |

### State & Logs
| File | Purpose |
|------|---------|
| `polymarket_assistant/account_state.json` | Cash, open positions, config params |
| `polymarket_assistant/trade_log.json` | Full history of every cycle + trade |
| `polymarket_assistant/pending_orders.json` | Queue of orders awaiting phone execution |
| `polymarket_assistant/last_run_summary.json` | Output of the last cycle (JSON) |
| `doc/polymarket_assistant/last_run_summary.md` | Output of the last cycle (Markdown) |
| `analyses_log.json` | Beecthor video summaries history |
| `transcripts/` | Raw video transcripts (one file per video) |

### Phone
| File | Purpose |
|------|---------|
| `phone/polymarket_executor.py` | Reads `pending_orders.json`, signs & submits BUY/SELL to CLOB |
| `phone/polymarket_monitor_executor.py` | Reads `last_monitor_action.json`, executes monitor-triggered SELL |
| `phone/beecthor_summarizer.py` | Fetches latest Beecthor video, summarizes via Copilot CLI, commits |

### Server
| File | Purpose |
|------|---------|
| `server/copilot_chat.py` | Flask dashboard: Polymarket zone, Beecthor gallery, logs, APIs |
| `/root/scripts/vscode_chat_send.sh` | xdotool helper to type into VS Code chat |
| `/root/scripts/codex_heartbeat.sh` | Proof-of-concept: sends time-write prompt to Codex (cron removed) |

---

## Systemd Timers (on VPS)

| Timer | Schedule | What it runs |
|-------|----------|-------------|
| `polymarket-operator.timer` | even UTC hours every 2h | `/root/run_polymarket_cycle.sh` -> `run_cycle_codex.py --decision-file` |
| `polymarket-monitor.timer` | odd UTC hours | `run_monitor.py` (take-profit / stop-loss check, no GPT) |

---

## Trading Architecture

### Position slots
| Slot | Market type | Max open |
|------|-------------|----------|
| daily | `will-bitcoin-reach/dip-to-Xk-on-{date}` | 1 |
| weekly | `will-bitcoin-reach/dip-to-Xk-{date-range}` | 1 |
| floor | `bitcoin-above-Xk-on-{date}` | 1 |
| **total** | all | **3** |

### Entry rules (summary)
- Base stake: 15% of available cash
- Early-stage cap: max $1 per trade while portfolio < $15
- Probability range: 45–84% (hard cap at 85%)
- Nearest-strike-first rule enforced per type (daily/weekly independent)
- Both REACH and DIP directions must be evaluated before deciding

### Exit rules
- Take-profit: ≥90–95% probability (monitor auto-triggers SELL)
- Stop-loss: disabled in early stage
- No stop-loss at monitor level, only take-profit

### Cycle flow
```
run_cycle.py
  1. git pull
  2. load config from polymarket_assistant/.env
  3. build_context_snapshot()
       - fetch BTC price, funding rate, L/S ratio from Binance
       - fetch_positions() → active open positions (filtered)
       - fetch_active_btc_markets() → daily + weekly markets from GAMMA API
       - fetch_active_floor_markets() → "bitcoin-above-X" markets from GAMMA API
       - load account_state.json, trade_log.json, transcripts, analyses_log.json
  4. render_prompt() → doc/polymarket_assistant/copilot_prompt.md + full context JSON
  5. run_copilot() → GPT returns JSON decision
     (or --decision-file to skip this step)
  6. validate_decision() → enforces all playbook rules
  7. if OPEN_POSITION:
       prepare_and_send_order_via_phone() → writes to pending_orders.json + Telegram
  8. if new_floor_position:
       prepare_and_send_order_via_phone() → same flow
  9. sync_account_state() → refresh cash + positions from API
  10. append_trade_log() → writes cycle entry to trade_log.json
  11. save last_run_summary.json + .md
  12. git commit + push
  13. send Telegram notification
```

### Phone executor flow
```
polymarket_executor.py (Termux cron)
  1. fetch pending_orders.json from GitHub Contents API
  2. for each order where status == 'pending_phone_execution':
       - check order_id not in ~/.polymarket_executed_order_ids (24h dedup)
       - check no existing live position for same market+outcome (anti-duplicate)
       - sign EIP-712 order with POLY_PRIVATE_KEY (local signing, no server)
       - POST to https://clob.polymarket.com/order
       - on success: save order_id to dedup file
       - 5 retries with 20s delay
```

---

## GPT Decision Schema

```json
{
  "action": "NO_ACTION | OPEN_POSITION | CLOSE_POSITION | REDUCE_POSITION",
  "confidence": 0.0,
  "summary": "",
  "rationale": "",
  "position_management": {
    "should_manage_existing": false,
    "target_market_slug": "",
    "target_outcome": "",
    "reason": "take_profit | thesis_invalidated | rebalance | none",
    "reduce_fraction": 0.5
  },
  "new_position": {
    "should_open": false,
    "event_slug": "",
    "market_slug": "",
    "outcome": "",
    "direction": "bullish | bearish | neutral",
    "strike": 0,
    "stake_usd": 0,
    "max_entry_probability": 0.0
  },
  "new_floor_position": {
    "should_open": false,
    "event_slug": "",
    "market_slug": "",
    "outcome": "Yes",
    "floor_level": 0,
    "stake_usd": 0,
    "max_entry_probability": 0.0
  }
}
```

---

## Polymarket APIs Used

| API | Base URL | Usage |
|-----|----------|-------|
| CLOB | `https://clob.polymarket.com` | order submission, positions, balance |
| GAMMA | `https://gamma-api.polymarket.com` | market discovery, event slugs |
| DATA | `https://data-api.polymarket.com` | positions with `redeemable` field, richer metadata |
| Binance | `https://api.binance.com` | BTC spot price, funding rate, L/S ratio, OI |

### GAMMA slug patterns
- Daily price-hit events: `what-price-will-bitcoin-hit-on-{month}-{day}`
- Weekly price-hit events: `what-price-will-bitcoin-hit-{month}-{day1}-{day2}`
- Floor events: `bitcoin-above-on-{month}-{day}` (markets inside: `bitcoin-above-{X}k-on-{date}`)

---

## Key Bugs Fixed

### fetch_positions — resolved position ghost (2026-04-16)
**Bug**: When `endDate` is a bare date string (e.g. `"2026-04-16"`) with no time component, `datetime.fromisoformat()` returns a naive datetime. Comparing it with `datetime.now(UTC)` (aware) raises `TypeError`, caught silently, and the expired position leaks through to GPT.

**Fix**: Two-layer filter in `fetch_positions()`:
1. If `item.get('redeemable')` is true → skip immediately (market resolved)
2. After parsing `end_dt`, if `end_dt.tzinfo is None` → `end_dt = end_dt.replace(tzinfo=UTC)`

### execution.details — list vs dict (2026-04-14)
After adding multi-position support, `execution['details']` changed from a single dict to a list. Two locations in `server/copilot_chat.py` were calling `.get()` directly on it, causing `AttributeError`. Fixed in `build_polymarket_snapshot()` and `build_cycle_trace_entries()`.

### xrdp black screen (2026-04-14)
Orphaned `xfce4-session` (PID 22258, running since 2026-03-26) held `org.xfce.SessionManager` on the systemd user dbus. Every new xrdp connection tried to start a second XFCE session which exited in 0 seconds. Fixed by killing all orphaned XFCE processes and removing `/tmp/.X10-lock`.

---

## Account State (as of 2026-04-16)

```json
{
  "starting_bankroll": 7.842164,
  "cash_available": ~10.02,
  "realized_pnl": 0.34,
  "open_positions": [],
  "max_open_positions": 3,
  "max_floor_positions": 1,
  "base_stake_pct": 0.15,
  "early_stage_max_stake": 1.0,
  "early_stage_threshold": 15.0,
  "take_profit_probability_min": 0.9,
  "take_profit_probability_max": 0.95,
  "discarded_probability_threshold": 0.2
}
```

---

## Trade History (notable)

| Date | Market | Side | Result | PnL |
|------|--------|------|--------|-----|
| ~2026-04-10 | will-bitcoin-reach-73k-on-april-10 | YES | Win (TP) | +$x |
| ~2026-04-13 | will-bitcoin-dip-to-74k-on-april-13 | YES | Win (TP) | +$1.22 |
| 2026-04-15 | will-bitcoin-dip-to-73k-on-april-15 | YES | LOST | -$0.97 |

---

## VS Code / Codex Automation

- VS Code runs on display `:10` on the VPS (xrdp session)
- `xdotool` is installed and can interact with VS Code even with mstsc disconnected
- `/root/scripts/vscode_chat_send.sh` types a message into the active VS Code chat input
- **Codex heartbeat experiment**: cron every 4h asked Codex to append current time to `/root/codex_heartbeat.txt`. Ran successfully for 1.5 days. Cron removed after validation (2026-04-16).
- **Codex as decision engine**: `/root/run_polymarket_cycle.sh` builds context, sends the trigger to Codex via xdotool, waits for a decision JSON, then runs `run_cycle_codex.py --decision-file`.

---

## Pending / Known Limitations

- **On-chain redemption**: not implemented. Funder proxy ABI is custom/unverified. LOST positions are filtered from GPT context. WON positions are sold via CLOB before resolution.
- **Codex as decision engine**: planned but not implemented. Would replace Copilot CLI call with VS Code chat roundtrip.
- **Performance snapshot**: activates at ≥3 `trade_closed` entries in trade_log. Currently at 2.
- **Beecthor DIP bias**: GPT tends to bet DIP because Beecthor is structurally bearish. PLAYBOOK updated to explicitly require evaluating both directions.
