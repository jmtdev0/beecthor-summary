#!/usr/bin/env python3
"""
Beecthor Bitcoin Summary Bot

Checks for new videos on Beecthor's YouTube channel, extracts the transcript
(3-tier fallback: youtube-transcript-api → Invidious captions → Invidious audio + Groq Whisper),
summarizes it with Groq (Llama 3.3 70B), and sends the result to Telegram.
Persists the last processed video ID in last_video_id.txt to avoid duplicates.
"""

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
# Transcript helpers  (3-tier fallback)
# ---------------------------------------------------------------------------
#
#  Tier 1 — youtube-transcript-api    : fast, no download; works when captions exist
#  Tier 2 — Invidious captions API    : proxy-based; bypasses YouTube bot-detection
#  Tier 3 — Invidious audio + Whisper : downloads audio via proxy, transcribes free
#
#  GitHub Actions IPs are blocked by YouTube for direct content access, so Tiers 2
#  and 3 route through Invidious (open-source YouTube frontend) as a proxy.
# ---------------------------------------------------------------------------

# Multiple Invidious public instances for redundancy
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.fdn.fr",
    "https://yt.cdaut.de",
    "https://invidious.nerdvpn.de",
    "https://invidious.privacyredirect.com",
]

# Groq Whisper hard limit is 25 MB; stay safely below it
MAX_AUDIO_BYTES = 24 * 1024 * 1024  # 24 MB


def get_transcript(video_id: str) -> str:
    """Try all three tiers in order; return the first successful transcript."""

    # --- Tier 1: youtube-transcript-api ---
    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        try:
            transcript_obj = transcript_list.find_transcript(["es", "es-ES", "es-419"])
        except Exception:
            # Accept any auto-generated transcript, Spanish first then English
            transcript_obj = transcript_list.find_generated_transcript(
                ["es", "es-ES", "es-419", "en"]
            )
        text = " ".join(entry["text"] for entry in transcript_obj.fetch())
        print(f"[Tier 1] youtube-transcript-api OK ({len(text)} chars).")
        return text
    except Exception as e:
        print(f"[Tier 1] Failed: {e}")

    # --- Tier 2: Invidious captions API ---
    try:
        text = _get_captions_via_invidious(video_id)
        print(f"[Tier 2] Invidious captions OK ({len(text)} chars).")
        return text
    except Exception as e:
        print(f"[Tier 2] Failed: {e}")

    # --- Tier 3: Invidious audio download + Groq Whisper ---
    print("[Tier 3] Downloading audio via Invidious for Whisper transcription...")
    text = _transcribe_audio_via_invidious(video_id)
    print(f"[Tier 3] Groq Whisper OK ({len(text)} chars).")
    return text


def _get_captions_via_invidious(video_id: str) -> str:
    """
    Fetch available caption tracks from Invidious and return plain text.
    Tries each public instance until one succeeds.
    """
    last_err: Exception = RuntimeError("No Invidious instances configured.")

    for instance in INVIDIOUS_INSTANCES:
        try:
            # 1. List available caption tracks for this video
            r = requests.get(
                f"{instance}/api/v1/captions/{video_id}",
                timeout=15,
            )
            r.raise_for_status()
            tracks = r.json().get("captions", [])
            if not tracks:
                raise ValueError("No caption tracks found.")

            # 2. Prefer Spanish; fall back to English; otherwise take the first one
            def lang_priority(track: dict) -> int:
                code = track.get("languageCode", "")
                if code.startswith("es"):
                    return 0
                if code.startswith("en"):
                    return 1
                return 2

            track = sorted(tracks, key=lang_priority)[0]
            # Invidious returns a relative URL like /api/v1/captions/VIDEO_ID?label=...
            caption_url = track.get("url", "")
            if caption_url.startswith("/"):
                caption_url = f"{instance}{caption_url}"

            # 3. Download the VTT content
            vtt_resp = requests.get(caption_url, timeout=30)
            vtt_resp.raise_for_status()
            vtt_text = vtt_resp.text

            # 4. Strip VTT metadata, timestamps, and cue numbers → plain text
            lines = [
                line.strip()
                for line in vtt_text.splitlines()
                if line.strip()
                and not line.startswith("WEBVTT")
                and "-->" not in line
                and not line.strip().isdigit()
            ]
            return " ".join(lines)

        except Exception as e:
            print(f"  [{instance}] {e}")
            last_err = e
            continue

    raise RuntimeError(f"All Invidious instances failed for captions. Last: {last_err}")


def _transcribe_audio_via_invidious(video_id: str) -> str:
    """
    Download audio through an Invidious proxy (avoids YouTube bot-detection),
    then transcribe with Groq Whisper (free, same API key).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = _download_audio_via_invidious(video_id, tmpdir)

        client = Groq(api_key=GROQ_API_KEY)
        ext = os.path.splitext(audio_path)[1].lstrip(".")  # "webm" or "mp4"
        mime = f"audio/{ext}"

        with open(audio_path, "rb") as f:
            transcription = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), f, mime),
                model="whisper-large-v3",
                language="es",
                response_format="text",
            )
        return transcription


def _download_audio_via_invidious(video_id: str, tmpdir: str) -> str:
    """
    Fetch audio stream metadata from Invidious, then stream-download the audio.
    Returns the local path of the downloaded file.
    """
    last_err: Exception = RuntimeError("No Invidious instances configured.")

    for instance in INVIDIOUS_INSTANCES:
        try:
            # 1. Get video metadata (adaptive formats list)
            r = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()

            # 2. Pick the lowest-bitrate audio-only format (sufficient for speech)
            audio_fmts = [
                f for f in data.get("adaptiveFormats", [])
                if f.get("type", "").startswith("audio/")
            ]
            if not audio_fmts:
                raise ValueError("No audio formats in Invidious response.")

            fmt = min(audio_fmts, key=lambda f: f.get("bitrate", float("inf")))
            itag = fmt["itag"]
            ext = "webm" if "webm" in fmt.get("type", "") else "mp4"

            # 3. Stream-download via Invidious proxy (local=true routes through the instance)
            audio_url = (
                f"{instance}/latest_version"
                f"?id={video_id}&itag={itag}&local=true"
            )
            audio_path = os.path.join(tmpdir, f"audio.{ext}")
            total = 0

            with requests.get(audio_url, stream=True, timeout=180) as dl:
                dl.raise_for_status()
                with open(audio_path, "wb") as out:
                    for chunk in dl.iter_content(chunk_size=65_536):
                        total += len(chunk)
                        if total > MAX_AUDIO_BYTES:
                            raise RuntimeError(
                                f"Audio exceeds {MAX_AUDIO_BYTES // 1_048_576} MB limit."
                            )
                        out.write(chunk)

            print(
                f"  [{instance}] Audio downloaded: {total / 1_048_576:.1f} MB"
            )
            return audio_path

        except Exception as e:
            print(f"  [{instance}] {e}")
            last_err = e
            continue

    raise RuntimeError(f"All Invidious instances failed for audio. Last: {last_err}")


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
