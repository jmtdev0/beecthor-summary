# Beecthor Bitcoin Summary Bot

A daily manual routine that fetches the latest video from [Beecthor](https://www.youtube.com/@Beecthor)'s YouTube channel, parses the Spanish transcript, and delivers a structured Bitcoin analysis summary to a private Telegram group — including live BTC and SOL prices and a light-hearted "robot score" for Beecthor himself.

## How it works

```
Daily session (manual)
  ├─ yt-dlp              → fetches latest video ID and downloads .es.vtt captions
  ├─ Python parser       → strips VTT markup, deduplicates lines → plain transcript
  ├─ Transcript saved    → transcripts/<video_id>_<date>.txt
  ├─ CoinGecko API       → live BTC + SOL prices (USD & EUR); yesterday's from log
  ├─ Manual analysis     → structured summary authored from the transcript
  ├─ Telegram Bot API    → sends HTML message with spoiler block to the group
  ├─ analyses_log.json   → appends entry (prices, video, message)
  └─ git commit + push   → commits transcript + log + changelog to main
```

## Telegram message format

Each daily message includes:

- **Link** to the video
- **BTC prices**: yesterday → today with % change
- **SOL prices**: yesterday → today with % change
- **🤖 Robot score**: 0–10 rating (with one decimal) of how robotic vs. human Beecthor sounded that day — purely for fun. A score close to 10 means pure Elliott Wave tech-speak; closer to 0 means he wandered off-script and said something human.
- **📌 Resumen**: 2–3 sentence plain-language verdict (does BTC go to new ATH or visit cycle lows first?)
- **🔍 Análisis completo**: full structured analysis hidden behind a Telegram spoiler tap

## Features

- **No video download** — only the auto-generated `.es.vtt` subtitle file is fetched
- **Spoiler block** — the detailed analysis is hidden until the reader taps, keeping the message clean
- **Price comparison** — yesterday's prices are pulled from the last entry in `analyses_log.json`; SOL historical price from CoinGecko on the very first entry
- **Transcript archive** — every parsed transcript is saved to `transcripts/` for future reference
- **Daily git commit** — `analyses_log.json`, the new transcript, and `CHANGELOG.md` are committed and pushed to `main` after each session

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

```
GROQ_API_KEY=your_groq_key
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id   # negative number for supergroups
```

The Telegram bot must be **admin** in the target supergroup to send messages.

### 3. Configure git

Ensure `git push` works without prompts (use a credential manager or SSH key).

## Dependencies

| Package | Purpose |
|---|---|
| `yt-dlp` | Fetch latest video ID and download `.es.vtt` captions |
| `requests` | Telegram Bot API calls (in original script) |

## Notes

- The original `summarize_beecthor.py` GitHub Actions script is kept in the repo but is not used in the current daily manual flow.
- `youtube-transcript-api` and Groq API calls were attempted in early sessions but abandoned due to rate limits and transcript availability issues.
- Telegram `parse_mode: HTML` is used (not Markdown) to support `<tg-spoiler>` tags.
- The `|` character breaks Telegram MarkdownV2 — use `/` as a separator if needed.
