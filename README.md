# Beecthor Bitcoin Summary Bot

A GitHub Actions workflow that automatically detects new videos from [Beecthor](https://www.youtube.com/@Beecthor)'s YouTube channel, extracts the transcript, summarizes the Bitcoin analysis using an LLM, and delivers the summary to a Telegram group.

## How it works

```
GitHub Actions (daily cron at 21:00 Madrid time)
  └─ summarize_beecthor.py
       ├─ yt-dlp          → fetches the latest video ID from the channel
       ├─ Compares with last_video_id.txt
       ├─ If new video found:
       │    ├─ youtube-transcript-api → extracts Spanish transcript
       │    ├─ Groq API (Llama 3.3 70B) → generates structured summary
       │    └─ Telegram Bot API → sends summary to the group
       └─ Commits updated last_video_id.txt to prevent duplicate messages
```

## Features

- **No video download** — only the transcript is fetched, keeping execution fast and lightweight
- **Deduplication** — `last_video_id.txt` is committed back to the repo after each run so the same video is never processed twice
- **Fallback transcription** — if `youtube-transcript-api` fails, `yt-dlp` auto-subtitles are used as a backup
- **Manual trigger** — the workflow can be run on demand from the GitHub Actions tab (`workflow_dispatch`)

## Project structure

```
.github/
  workflows/
    beecthor-summary.yml    # Workflow definition (cron + manual trigger)
scripts/
  summarize_beecthor.py     # Main logic: transcript → summary → Telegram
requirements.txt            # Python dependencies
last_video_id.txt           # Tracks the last processed video (auto-updated by CI)
```

## Setup

### 1. Fork / clone this repository

Push it to your own GitHub account.

### 2. Create a Telegram Bot

1. Open Telegram and start a chat with `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** you receive
4. Add the bot to your group
5. Retrieve the **group chat ID** by sending any message to the group and opening:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   The `chat.id` value (a negative number like `-100123456789`) is your chat ID.

### 3. Create a Groq API key

1. Sign up at [console.groq.com](https://console.groq.com)
2. Navigate to **API Keys** and generate a new key

### 4. Add GitHub Secrets

Go to your repo → **Settings → Secrets and variables → Actions → New repository secret** and add:

| Secret name | Value |
|---|---|
| `GROQ_API_KEY` | Your Groq API key |
| `TELEGRAM_BOT_TOKEN` | The token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your group's chat ID (negative number) |

### 5. Run it

The workflow runs automatically every day at **21:00 Madrid time (winter) / 22:00 (summer)**.

To test it manually: **Actions tab → Beecthor Bitcoin Summary → Run workflow**.

## Dependencies

| Package | Purpose |
|---|---|
| `yt-dlp` | Fetch latest video ID; fallback subtitle download |
| `youtube-transcript-api` | Primary transcript extraction (no video download) |
| `groq` | Groq Python SDK for LLM summarization |
| `requests` | Telegram Bot API calls |

## Notes

- GitHub Actions cron does not support timezone-aware scheduling natively. `0 20 * * *` (UTC) maps to 21:00 CET (winter) and 22:00 CEST (summer).
- The Groq free tier is sufficient for this use case (one request per day, transcript ≤ 80K characters).
- If Beecthor's video has no Spanish subtitles available yet, the workflow will exit with an error and retry the following day.
