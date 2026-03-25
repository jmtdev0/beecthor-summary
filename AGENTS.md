# AGENTS.md

## Purpose

This repository automates a daily Beecthor workflow:
- detect the latest YouTube video
- obtain a transcript through the fallback chain
- generate a Spanish Telegram summary plus a spoiler analysis
- store the transcript and log entry
- optionally send the message to Telegram

## Working Rules

1. Use the local virtual environment explicitly:
   `e:\Software\Coding\beecthor-summary\.venv\Scripts\python.exe`
2. Keep all code, comments, and identifiers in English.
3. Keep Telegram output in Spanish and HTML format.
4. Do not break the current daily workflow unless the user asks for a behavior change.
5. Preserve existing logs, transcripts, and bet tracking files.

## Daily Workflow Expectations

When the user asks for a new daily run:
- detect whether a new video exists before doing any write action
- generate the summary and Telegram message in chat from the collected transcript; do not delegate the summary to Groq or any other external LLM
- if the user asks to preview the message first, generate the message and show it in chat before sending it to Telegram
- only send to Telegram after user confirmation when a preview was requested
- after a successful approved run, update `last_video_id.txt`, `analyses_log.json`, `transcripts/`, and `CHANGELOG.md`

## Transcript And Analysis Notes

- Preferred transcript path is the built-in fallback chain already implemented in `scripts/summarize_beecthor.py`.
- Tier 2 (`yt-dlp` VTT) is usually the reliable path.
- Without Groq, there is no audio transcription fallback; if Tiers 1-3 fail, the agent must report that the transcript could not be obtained automatically.
- The Telegram message should keep prices, a visible short-term summary, a visible macro view, and the robot score above the `<tg-spoiler>` block.
- The spoiler block should summarize the usual Beecthor sections adaptively: context for newcomers, macro count, current 4h count, liquidations, Fibonacci, Value Area/POC, EMAs, AVWAP, and operational conclusion when they are clearly present.
- The robot score and justification should be computed locally from the transcript, and the actual summary text should be written by the agent in chat.

## Repo-Specific Context

- `bets_real.md` tracks real positions.
- `bets_simulation.md` tracks simulated positions.
- `analyses_log.json` is the source of yesterday-versus-today price comparisons.
- `CHANGELOG.md` should record only notable progress, grouped by date.

## Editing Guidance

- Prefer minimal, focused changes.
- Keep prompts specific to Beecthor's structure: macro, current count, liquidations, Fibonacci, Value Area/POC, EMAs, AVWAP, key levels, and strategy.
- If the user wants a Telegram template change, update the prompt first and keep `build_message()` as simple as possible.