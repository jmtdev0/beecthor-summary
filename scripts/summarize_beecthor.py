#!/usr/bin/env python3
"""
Beecthor Bitcoin Summary Bot

Checks for new videos on Beecthor's YouTube channel, extracts the transcript,
summarizes it with Groq (Llama 3.3 70B), and sends the result to Telegram.
Persists the last processed video ID in last_video_id.txt to avoid duplicates.
"""

import glob as glob_module
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from groq import Groq
from youtube_transcript_api import YouTubeTranscriptApi

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHANNEL_URL = "https://www.youtube.com/@Beecthor"
LAST_VIDEO_FILE = Path(__file__).parent.parent / "last_video_id.txt"

GROQ_API_KEY = os.environ["GROQ_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

GROQ_MODEL = "llama-3.3-70b-versatile"
# Keep transcript within model context limits (~100K tokens ≈ 400K chars; we use 80K to be safe)
MAX_TRANSCRIPT_CHARS = 80_000

SUMMARY_SYSTEM_PROMPT = """\
Eres un asistente especializado en análisis técnico de Bitcoin. \
Recibirás la transcripción de un vídeo de Beecthor, un analista técnico español de Bitcoin.

Extrae y resume de forma clara y estructurada los siguientes puntos:

1. 📊 *Situación actual* — precio aproximado y contexto del mercado en el momento del vídeo
2. 🚀 *Escenario alcista* — condiciones necesarias, niveles clave y objetivos de precio
3. 🔻 *Escenario bajista* — condiciones que lo activarían, niveles clave y soportes a vigilar
4. 💡 *Conclusión de Beecthor* — qué espera que ocurra y qué recomienda tener en cuenta

Normas de formato:
- Máximo 280 palabras en total
- Usa negritas (*texto*) y emojis para facilitar la lectura en Telegram
- Escribe en español
- No incluyas frases introductorias como "En este vídeo..." — ve directo al grano
"""


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------


def get_latest_video_id() -> str:
    """Return the video ID of the most recent upload on Beecthor's channel."""
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--playlist-end", "1",
            "--print", "%(id)s",
            CHANNEL_URL,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    video_id = result.stdout.strip()
    if not video_id:
        raise RuntimeError("yt-dlp returned an empty video ID. Check the channel URL.")
    return video_id


def get_last_processed_id() -> str:
    """Read the last processed video ID from disk. Returns empty string if not set."""
    if LAST_VIDEO_FILE.exists():
        return LAST_VIDEO_FILE.read_text(encoding="utf-8").strip()
    return ""


def save_last_processed_id(video_id: str) -> None:
    """Persist the latest processed video ID to disk."""
    LAST_VIDEO_FILE.write_text(video_id, encoding="utf-8")


# ---------------------------------------------------------------------------
# Transcript helpers
# ---------------------------------------------------------------------------


def get_transcript(video_id: str) -> str:
    """
    Attempt to fetch the transcript via youtube-transcript-api.
    Falls back to yt-dlp auto-generated subtitles if that fails.
    """
    try:
        entries = YouTubeTranscriptApi.get_transcript(
            video_id, languages=["es", "es-ES", "es-419"]
        )
        transcript = " ".join(entry["text"] for entry in entries)
        print(f"Transcript fetched via youtube-transcript-api ({len(transcript)} chars).")
        return transcript
    except Exception as primary_error:
        print(f"youtube-transcript-api failed: {primary_error}. Trying yt-dlp fallback...")
        return _get_transcript_via_ytdlp(video_id)


def _get_transcript_via_ytdlp(video_id: str) -> str:
    """Fallback: download auto-generated VTT subtitles and extract plain text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(
            [
                "yt-dlp",
                "--write-auto-sub",
                "--sub-lang", "es",
                "--sub-format", "vtt",
                "--skip-download",
                "--output", f"{tmpdir}/sub",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            check=True,
        )
        sub_files = glob_module.glob(f"{tmpdir}/*.vtt")
        if not sub_files:
            raise RuntimeError(
                f"No Spanish subtitles found for video {video_id}. "
                "The video may not have subtitles yet."
            )
        with open(sub_files[0], encoding="utf-8") as f:
            lines = f.readlines()

        # Strip VTT metadata, timestamps, and blank lines
        text_lines = [
            line.strip()
            for line in lines
            if line.strip()
            and not line.startswith("WEBVTT")
            and "-->" not in line
            and not line.strip().isdigit()
        ]
        transcript = " ".join(text_lines)
        print(f"Transcript fetched via yt-dlp fallback ({len(transcript)} chars).")
        return transcript


# ---------------------------------------------------------------------------
# LLM summarization
# ---------------------------------------------------------------------------


def summarize_with_groq(transcript: str, video_id: str) -> str:
    """Send the transcript to Groq and return the structured summary."""
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        print(
            f"Transcript truncated from {len(transcript)} to {MAX_TRANSCRIPT_CHARS} chars."
        )
        transcript = transcript[:MAX_TRANSCRIPT_CHARS] + "\n... [transcripción truncada]"

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    client = Groq(api_key=GROQ_API_KEY)

    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Vídeo analizado: {video_url}\n\n"
                    f"Transcripción:\n{transcript}"
                ),
            },
        ],
        temperature=0.3,
        max_tokens=1024,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def send_telegram_message(summary: str, video_id: str) -> None:
    """Send the formatted summary to the configured Telegram group."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    message = (
        f"🎯 *Resumen Beecthor* — [ver vídeo]({video_url})\n\n"
        f"{summary}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    print("Message sent to Telegram successfully.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    print("=== Beecthor Bitcoin Summary ===")

    print("Fetching latest video ID from channel...")
    latest_id = get_latest_video_id()
    print(f"Latest video: https://www.youtube.com/watch?v={latest_id}")

    last_id = get_last_processed_id()
    print(f"Last processed: {last_id or '(none)'}")

    if latest_id == last_id:
        print("No new video found. Nothing to do.")
        sys.exit(0)

    print(f"New video detected: {latest_id}")

    print("Fetching transcript...")
    transcript = get_transcript(latest_id)

    print("Generating summary with Groq...")
    summary = summarize_with_groq(transcript, latest_id)
    print("Summary generated successfully.")

    print("Sending summary to Telegram...")
    send_telegram_message(summary, latest_id)

    save_last_processed_id(latest_id)
    print(f"Saved new last_video_id: {latest_id}")
    print("Done.")


if __name__ == "__main__":
    main()
