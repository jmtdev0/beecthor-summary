# Beecthor Bitcoin Summary Bot

A daily workflow that fetches the latest video from [Beecthor](https://www.youtube.com/@Beecthor)'s YouTube channel, collects transcript and market context, and leaves the final summary/message to be written by the agent in chat — including live BTC and SOL prices, a visible macro view, and a locally computed "robot score" for Beecthor himself.

Run it when a new video is out. The script handles transcript collection, prices, local robot score, logging helpers, and git support; the summary itself is written manually by the agent from the transcript.

## How it works

```
python scripts/summarize_beecthor.py
  ├─ yt-dlp              → fetches latest video ID; skips if already processed
  ├─ 3-tier chain        → downloads .es.vtt subtitle → plain transcript
  │    Tier 1: youtube-transcript-api
  │    Tier 2: yt-dlp .es.vtt  ← works reliably in practice
  │    Tier 3: Invidious captions API
  ├─ Transcript saved    → transcripts/<video_id>_<YYYY-MM-DD>.txt
  ├─ CoinGecko API       → live BTC + SOL prices (USD & EUR)
  ├─ analyses_log.json   → yesterday's prices read from last entry
  ├─ Local transcript heuristics → robot score 0-10 + one-liner comment
  ├─ Agent in chat       → writes resumen + macro line + adaptive HTML spoiler
  ├─ Telegram Bot API    → optional send after review
  ├─ analyses_log.json   → append entry after final message is approved
  └─ git commit + push   → commits transcript + log + changelog to main
```

## Telegram message format

Messages use `parse_mode: HTML` (required for `<tg-spoiler>` and `<a href>` tags).

```
🎯 Beecthor — Último vídeo (ver)

📈 BTC ayer: 70.965$ / 61.324€
📈 BTC ahora: 83.210$ / 71.450€  (+17.26%)

📈 SOL ayer: 86.82$ / 74.90€
📈 SOL ahora: 120.00$ / 103.20€  (+38.21%)

🧭 Visión macro
<ATH directly or visit lower cycle levels first, with levels>

🤖 Índice robot: 8.2 / 10
<one-liner comment in Spanish, dry and slightly sarcastic>

📌 Resumen
<2-3 sentence verdict: what Beecthor expects, key level to watch>

🔍 Análisis completo (toca para ver)
<tg-spoiler>
  🌍 Contexto para nuevos …
  📉 Conteo macro …
  📊 Conteo actual (4h) …
  💧 Liquidaciones …
  📐 Fibonacci …
  📦 Value Area / POC …
  📈 EMAs …
  🧷 AVWAP anclado …
  🎯 Conclusión operativa …
</tg-spoiler>
```

**Price formatting**: BTC uses the European thousands separator (e.g. `70.492$`); SOL uses 2 decimal places. The `📈` emoji is always shown regardless of direction; the % sign carries `+` or `−`.

**Robot score**: 0–10 (one decimal). 10 = pure Elliott Wave tech-speak with zero human moments; 0 = went completely off-script. It is computed locally from transcript heuristics.

## Features

- **4-tier transcript fallback** — yt-dlp `.es.vtt` (Tier 2) works reliably in practice; Invidious tiers are rarely needed locally
- **No full video download** — only the subtitle file is fetched (fast, lightweight)
- **Local robot score** — computed from transcript heuristics so it stays deterministic and cheap
- **Agent-authored summary** — the final visible summary, macro line, and spoiler are written in chat from the collected transcript
- **Spoiler block** — the full analysis is hidden behind a Telegram tap, keeping the message scannable while mirroring Beecthor's usual section order
- **Price comparison** — live prices from CoinGecko; yesterday's prices from the last `analyses_log.json` entry
- **Transcript archive** — every parsed transcript saved to `transcripts/<video_id>_<date>.txt`
- **Log archive** — every sent message with metadata appended to `analyses_log.json`
- **Automatic git commit** — `last_video_id.txt`, `analyses_log.json`, the transcript, and `CHANGELOG.md` committed and pushed to `main` after each run

## Project structure

```
.github/
  workflows/
    beecthor-summary.yml          # Original GitHub Actions workflow (kept for reference)
scripts/
  summarize_beecthor.py           # Original main script (kept for reference)
transcripts/
  <video_id>_<date>.txt           # Parsed transcript archive (one file per day)
analyses_log.json                 # All sent summaries with prices and metadata
CHANGELOG.md                      # Notable changes grouped by date
requirements.txt                  # Python dependencies
last_video_id.txt                 # Last processed video ID
```

## Setup

### 1. Clone this repository

```bash
git clone https://github.com/jmtdev0/beecthor-summary.git
cd beecthor-summary
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Create a `.env` file

Copy `.env.example` to `.env` and fill in your real values:

```bash
copy .env.example .env
```

```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id   # negative number for supergroups
```

The Telegram bot must be **admin** in the target supergroup to send messages.

The script loads `.env` automatically via `python-dotenv` — no need to set variables manually in the shell.

### 3. Configure git

Ensure `git push` works without prompts (use a credential manager or SSH key).

### 4. Run the script

```bash
python scripts/summarize_beecthor.py
```

The script will:
1. Detect the latest video on Beecthor's channel via yt-dlp
2. Skip if its ID matches `last_video_id.txt` (no duplicate messages)
3. Download the `.es.vtt` subtitle file (3-tier fallback; Tier 2 works in practice)
4. Save the parsed transcript to `transcripts/<video_id>_<YYYY-MM-DD>.txt`
5. Fetch live BTC + SOL prices (USD + EUR) from CoinGecko
6. Read yesterday's prices from the last `analyses_log.json` entry
7. Compute `generate_robot_score()` locally from the transcript → score 0–10 + one-liner comment
8. Hand the transcript to the agent so the summary and spoiler are written in chat
9. After approval, send the HTML message to Telegram and persist it
10. Update `last_video_id.txt` and append to `analyses_log.json`
11. `git add` + `git commit` + `git push` to main

#### Backfill mode

If a video was already sent to Telegram with the old script (missing prices, log entry, or transcript), use `--backfill` to recover without sending a duplicate:

```bash
python scripts/summarize_beecthor.py --backfill <VIDEO_ID>
```

This collects transcript and prices for a past video without sending anything to Telegram and without updating `last_video_id.txt`. The summary still has to be written manually in chat before any message is sent or logged.

#### Message format consistency

The `build_message()` function produces the canonical HTML format. When reviewing or debugging a message, compare it against the previous entry in `analyses_log.json` — the `"message"` field contains the exact text sent to Telegram.

If you need to resend a stored message (e.g. it was accidentally deleted from Telegram), read the entry from `analyses_log.json` and POST it to the Telegram Bot API with `parse_mode: HTML`. The content is ready to send as-is.



## Dependencies

| Package | Purpose |
|---|---|
| `yt-dlp` | Fetch latest video ID and download `.es.vtt` captions (Tier 2) |
| `requests` | CoinGecko price API and Telegram Bot API |
| `python-dotenv` | Auto-loads `.env` into environment variables at startup |
| `youtube-transcript-api` | Transcript Tier 1 fallback (often fails on recent videos) |

## Notes

- Telegram `parse_mode: HTML` is required (not Markdown) — needed for `<tg-spoiler>` and `<a href>` tags.
- BTC prices use a period as the thousands separator (European convention: `70.492$`). This is handled by `.replace(",", ".")` on Python's `:,.0f` format output.
- `youtube-transcript-api` (Tier 1) and Invidious (Tier 3) are preserved as fallbacks but rarely succeed in the local environment. Tier 2 (yt-dlp VTT) is the reliable path.
- Without Groq, there is no audio transcription fallback. If the video has no usable subtitles yet, the daily run has to wait or be handled manually.
- The `analyses_log.json` drives the "yesterday's prices" comparison. If the last entry lacks `sol_usd`/`sol_eur` (older entries), the SOL comparison block is skipped.
- The git commit step is non-fatal: if `git push` fails the script still exits successfully after logging and saving.
- The `.github/workflows/beecthor-summary.yml` file is kept for reference only — GitHub Actions IPs are blocked by YouTube for direct content access.
