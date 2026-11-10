#!/usr/bin/env python3
"""
Beecthor Bitcoin Summary Bot

Daily routine:
  1. Detect the latest video on Beecthor's YouTube channel
  2. Skip if it matches the last processed ID in last_video_id.txt
    3. Download the Spanish transcript via the non-Groq fallback chain
  4. Save the parsed transcript to transcripts/<video_id>_<YYYY-MM-DD>.txt
  5. Fetch live BTC and SOL prices (USD + EUR) from CoinGecko
    6. Compute a local robot score from the transcript
    7. Hand the transcript context to the agent so the daily summary is written in chat
    8. Build/send/log only after the agent has produced the final message

Transcript fallback chain:
  Tier 1 — youtube-transcript-api       (fast; often fails on very recent videos)
  Tier 2 — yt-dlp .es.vtt download      (reliable; works consistently in practice)
    Tier 3 — Invidious captions API       (proxy fallback; usually inaccessible locally)

Environment variables (loaded from .env automatically):
  TELEGRAM_BOT_TOKEN   — Telegram bot token from @BotFather
  TELEGRAM_CHAT_ID     — Target chat/group ID (negative number for supergroups)
"""

import copy
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
import requests
from youtube_transcript_api import YouTubeTranscriptApi

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHANNEL_URL = "https://www.youtube.com/@Beecthor"
REPO_ROOT = Path(__file__).parent.parent
load_dotenv(REPO_ROOT / "polymarket_assistant" / ".env", override=False)
LAST_VIDEO_FILE = REPO_ROOT / "last_video_id.txt"
LOG_FILE = REPO_ROOT / "analyses_log.json"
TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"
PERPS_THESES_DIR = REPO_ROOT / "data" / "perps_theses"
LATEST_PERPS_THESIS_FILE = PERPS_THESES_DIR / "latest.json"

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_TRANSCRIPT_CHARS = 80_000  # ~80K chars stays safely within the 128K-token context
MAX_PERPS_THESIS_VALID_HOURS = 48
MAX_LLM_TRANSCRIPT_CHARS = 14_000
BEECTHOR_SUMMARY_LLM_PROVIDER = os.environ.get("BEECTHOR_SUMMARY_LLM_PROVIDER", "codex").strip().lower()
DEFAULT_BEECTHOR_CODEX_MODEL = "gpt-6-luna"
BEECTHOR_CODEX_MODEL = os.environ.get("BEECTHOR_CODEX_MODEL", "").strip() or DEFAULT_BEECTHOR_CODEX_MODEL
BEECTHOR_PERPS_SYMBOL = os.environ.get("BEECTHOR_PERPS_SYMBOL", "BTCUSDC").strip().upper() or "BTCUSDC"
TELEGRAM_MAX_MESSAGE_CHARS = 3900

COINGECKO_PRICE_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin,solana&vs_currencies=usd,eur"
)

# ---------------------------------------------------------------------------
# YouTube / video ID helpers
# ---------------------------------------------------------------------------


def get_latest_video_id() -> str:
    """Return the video ID of the most recent upload on Beecthor's channel."""
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--playlist-end", "1",
            "--print", "%(id)s",
            "--js-runtimes", "node",
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
#  Tier 1   — youtube-transcript-api    : fast, no download; works when captions exist
#  Tier 2   — yt-dlp VTT subtitles      : downloads .es.vtt directly from YouTube
#  Tier 3   — Invidious captions API    : proxy-based; bypasses YouTube bot-detection
#
#  GitHub Actions IPs are blocked by YouTube for direct content access, so Tier 3
#  routes through Invidious (open-source YouTube frontend) as a proxy.
# ---------------------------------------------------------------------------

# Multiple Invidious public instances for redundancy
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.fdn.fr",
    "https://yt.cdaut.de",
    "https://invidious.nerdvpn.de",
    "https://invidious.privacyredirect.com",
]

def get_transcript(video_id: str) -> str:
    """Try the non-Groq tiers in order; return the first successful transcript."""

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

    # --- Tier 2: yt-dlp VTT subtitles ---
    try:
        text = _get_captions_via_ytdlp(video_id)
        print(f"[Tier 2] yt-dlp VTT OK ({len(text)} chars).")
        return text
    except Exception as e:
        print(f"[Tier 2] Failed: {e}")

    # --- Tier 3: Invidious captions API ---
    try:
        text = _get_captions_via_invidious(video_id)
        print(f"[Tier 3] Invidious captions OK ({len(text)} chars).")
        return text
    except Exception as e:
        print(f"[Tier 3] Failed: {e}")

    raise RuntimeError(
        "No transcript source succeeded without Groq. Tier 1, Tier 2, and Tier 3 all failed."
    )


def _parse_vtt(vtt_text: str) -> str:
    """Strip VTT markup/timestamps and return deduplicated plain text."""
    lines = []
    seen: set[str] = set()
    for line in vtt_text.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line or line.isdigit():
            continue
        # Remove inline timestamp/formatting tags like <00:00:01.234><c>
        line = re.sub(r"<[^>]+>", "", line).strip()
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    return " ".join(lines)


def _get_captions_via_ytdlp(video_id: str) -> str:
    """Download auto-generated .es.vtt subtitle file via yt-dlp and return plain text."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                "yt-dlp",
                "--write-auto-subs",
                "--sub-lang", "es",
                "--skip-download",
                "--js-runtimes", "node",
                "--output", os.path.join(tmpdir, "%(id)s"),
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True,
            text=True,
        )
        vtt_files = list(Path(tmpdir).glob("*.vtt"))
        if not vtt_files:
            raise RuntimeError(
                f"yt-dlp produced no VTT file. stderr: {result.stderr[:300]}"
            )
        return _parse_vtt(vtt_files[0].read_text(encoding="utf-8"))


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


def save_transcript(video_id: str, text: str) -> None:
    """Save the parsed transcript to transcripts/<video_id>_<YYYY-MM-DD>.txt."""
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = TRANSCRIPTS_DIR / f"{video_id}_{date_str}.txt"
    path.write_text(text, encoding="utf-8")
    print(f"Transcript saved: {path.name} ({len(text)} chars).")


# ---------------------------------------------------------------------------
# Price helpers  (CoinGecko)
# ---------------------------------------------------------------------------


def get_live_prices() -> dict:
    """Fetch live BTC and SOL prices (USD + EUR) from CoinGecko."""
    resp = requests.get(COINGECKO_PRICE_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return {
        "btc_usd": data["bitcoin"]["usd"],
        "btc_eur": data["bitcoin"]["eur"],
        "sol_usd": data["solana"]["usd"],
        "sol_eur": data["solana"]["eur"],
    }


def get_yesterday_prices() -> dict | None:
    """Return {btc_usd, btc_eur, sol_usd, sol_eur} from the last log entry, or None."""
    if not LOG_FILE.exists():
        return None
    entries = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    if not entries:
        return None
    last = entries[-1]
    if "btc_usd" not in last:
        return None
    return {
        "btc_usd": last["btc_usd"],
        "btc_eur": last["btc_eur"],
        "sol_usd": last.get("sol_usd"),
        "sol_eur": last.get("sol_eur"),
    }


def generate_robot_score(transcript: str) -> tuple[float, str]:
    """Return a deterministic local robot score and a short justification."""
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        transcript = transcript[:MAX_TRANSCRIPT_CHARS]

    text = transcript.lower()
    technical_patterns = [
        r"\bonda(?:s)?\b",
        r"\belliott\b",
        r"\bfibo(?:nacci)?\b",
        r"golden pocket",
        r"\bconteo\b",
        r"\bdiagonal\b",
        r"\bimpulso\b",
        r"\bretroceso\b",
        r"\bliquidaciones\b",
        r"value area",
        r"point of control|punto de control|\bpoc\b",
        r"\bema(?:s)?\b",
        r"\bvwap\b|avwap",
        r"\bsoporte(?:s)?\b",
        r"\bresistencia(?:s)?\b",
        r"\binvalida(?:ción|cion|do)?\b",
        r"\bratio(?:s)?\b",
        r"\babc\b",
    ]
    human_markers = [
        (r"machacar ese like|dar la campanita|suscrib", "Dijo lo de machacar ese like y enseguida volvió al desfile de ondas."),
        (r"bloofin|bluffin|promoci", "Metió la promo de Bloofin y luego regresó a Elliott como si nada."),
        (r"discord|telegram", "Hizo la parada reglamentaria en Discord o Telegram antes de seguir con el mapa mental."),
        (r"muchas gracias|sois los mejores|un saludo", "Se permitió el momento humano de agradecer a la parroquia antes de volver al conteo."),
        (r"no me esperaba|me he levantado|esta mañana|me encontr", "Dejó caer una observación personal y por eso hoy el robot afloja un poco."),
    ]

    technical_hits = sum(len(re.findall(pattern, text)) for pattern in technical_patterns)
    distinct_technical = sum(bool(re.search(pattern, text)) for pattern in technical_patterns)
    human_hits = sum(len(re.findall(pattern, text)) for pattern, _ in human_markers)

    score = 6.6
    score += min(2.6, technical_hits * 0.05)
    score += min(1.0, distinct_technical * 0.09)
    score -= min(1.8, human_hits * 0.18)
    score = max(0.0, min(10.0, round(score, 1)))

    for pattern, comment in human_markers:
        if re.search(pattern, text):
            return score, comment

    if technical_hits >= 30:
        return score, "Hoy casi no salió del circuito de Elliott, Fibonacci y liquidaciones en todo el vídeo."

    return score, "Tuvo algo de respiración humana, pero el guion técnico siguió mandando casi todo el rato."


# ---------------------------------------------------------------------------
# Perps thesis helpers
# ---------------------------------------------------------------------------

SUPPORTED_PERPS_SETUPS = {
    "wait",
    "short_resistance",
    "short_rejection",
    "short_resistance_bearish_regime",
    "long_support",
    "sweep_reclaim_long",
    "long_support_sweep_reclaim",
}
LONG_PERPS_SETUPS = {"long_support", "sweep_reclaim_long", "long_support_sweep_reclaim"}
SHORT_PERPS_SETUPS = {"short_resistance", "short_rejection", "short_resistance_bearish_regime"}
WAIT_PERPS_SETUPS = {"wait", "no_trade", "none", ""}
SUPPORTED_MACRO_BIASES = {"bearish", "bullish", "neutral", "mixed", "unknown"}


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _clamp_confidence(value: object) -> float:
    confidence = _float_or_none(value)
    if confidence is None:
        return 0.0
    return max(0.0, min(1.0, confidence))


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _normalize_zone(raw_zone: object, direction: str) -> dict | None:
    if not isinstance(raw_zone, dict):
        return None

    low = _float_or_none(raw_zone.get("low"))
    high = _float_or_none(raw_zone.get("high"))
    stop_loss = _float_or_none(raw_zone.get("stop_loss"))
    if low is None or high is None or stop_loss is None or low >= high:
        return None

    raw_targets = raw_zone.get("targets", [])
    targets = []
    if isinstance(raw_targets, list):
        targets = [target for target in (_float_or_none(item) for item in raw_targets) if target is not None]

    if direction == "long":
        targets = [target for target in targets if target > high]
        if stop_loss >= low or not targets:
            return None
        targets = sorted(targets)
    else:
        targets = [target for target in targets if target < low]
        if stop_loss <= high or not targets:
            return None
        targets = sorted(targets, reverse=True)

    return {
        "low": low,
        "high": high,
        "stop_loss": stop_loss,
        "targets": targets,
        "label": str(raw_zone.get("label", "")).strip(),
    }


def _wait_perps_thesis(video_id: str, reason: str, generated_at: datetime | None = None) -> dict:
    now = generated_at or datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "source": "beecthor-summary",
        "symbol": BEECTHOR_PERPS_SYMBOL,
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        "generated_at": _utc_iso(now),
        "created_at": _utc_iso(now),
        "valid_until": _utc_iso(now + timedelta(hours=MAX_PERPS_THESIS_VALID_HOURS)),
        "macro_bias": "unknown",
        "preferred_setup": "wait",
        "confidence": 0.0,
        "long_zones": [],
        "short_zones": [],
        "invalidation_levels": [],
        "no_trade_conditions": [reason],
        "notes": reason,
    }


def normalize_perps_thesis(payload: object, video_id: str) -> dict:
    """Return a safe, schema-versioned perps thesis for downstream automation."""
    if not isinstance(payload, dict):
        return _wait_perps_thesis(video_id, "LLM did not return a perps_thesis object.")

    now = datetime.now(timezone.utc)
    generated_at = _parse_utc_datetime(payload.get("generated_at")) or now
    max_valid_until = generated_at + timedelta(hours=MAX_PERPS_THESIS_VALID_HOURS)
    valid_until = _parse_utc_datetime(payload.get("valid_until")) or max_valid_until
    if valid_until > max_valid_until:
        valid_until = max_valid_until

    preferred_setup = str(payload.get("preferred_setup", "wait")).strip().lower()
    if preferred_setup in WAIT_PERPS_SETUPS:
        preferred_setup = "wait"

    macro_bias = str(payload.get("macro_bias", "unknown")).strip().lower()
    if macro_bias not in SUPPORTED_MACRO_BIASES:
        macro_bias = "unknown"

    long_zones = [
        zone
        for zone in (_normalize_zone(raw_zone, "long") for raw_zone in payload.get("long_zones", []) or [])
        if zone is not None
    ]
    short_zones = [
        zone
        for zone in (_normalize_zone(raw_zone, "short") for raw_zone in payload.get("short_zones", []) or [])
        if zone is not None
    ]

    confidence = _clamp_confidence(payload.get("confidence", 0.0))
    notes = str(payload.get("notes", "")).strip()
    no_trade_conditions = _text_list(payload.get("no_trade_conditions"))
    invalidation_levels = payload.get("invalidation_levels", [])
    if not isinstance(invalidation_levels, list):
        invalidation_levels = []

    safe_video_id = str(payload.get("video_id") or video_id).strip()
    if safe_video_id != video_id:
        safe_video_id = video_id

    if preferred_setup not in SUPPORTED_PERPS_SETUPS:
        return _wait_perps_thesis(
            video_id,
            f"Unsupported perps setup from LLM: {preferred_setup or '(empty)'}",
            generated_at,
        )
    if preferred_setup in LONG_PERPS_SETUPS and not long_zones:
        return _wait_perps_thesis(video_id, "Long setup returned without any valid long zone.", generated_at)
    if preferred_setup in SHORT_PERPS_SETUPS and not short_zones:
        return _wait_perps_thesis(video_id, "Short setup returned without any valid short zone.", generated_at)
    if preferred_setup == "wait":
        long_zones = []
        short_zones = []
        if not no_trade_conditions:
            no_trade_conditions = ["The transcript did not produce a clear automated setup."]

    return {
        "schema_version": 1,
        "source": "beecthor-summary",
        "symbol": BEECTHOR_PERPS_SYMBOL,
        "video_id": safe_video_id,
        "video_url": f"https://www.youtube.com/watch?v={safe_video_id}" if safe_video_id else "",
        "generated_at": _utc_iso(generated_at),
        "created_at": _utc_iso(generated_at),
        "valid_until": _utc_iso(valid_until),
        "macro_bias": macro_bias,
        "preferred_setup": preferred_setup,
        "confidence": confidence,
        "long_zones": long_zones,
        "short_zones": short_zones,
        "invalidation_levels": invalidation_levels,
        "no_trade_conditions": no_trade_conditions,
        "notes": notes,
    }


def save_perps_thesis(video_id: str, thesis: dict) -> Path:
    """Persist the operable perps thesis as both historical and latest JSON."""
    normalized = normalize_perps_thesis(copy.deepcopy(thesis), video_id)
    PERPS_THESES_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    history_path = PERPS_THESES_DIR / f"{date_str}_{video_id}.json"
    serialized = json.dumps(normalized, ensure_ascii=False, indent=2)
    history_path.write_text(serialized + "\n", encoding="utf-8")
    LATEST_PERPS_THESIS_FILE.write_text(serialized + "\n", encoding="utf-8")
    print(f"Perps thesis saved: {history_path}")
    print(f"Latest perps thesis updated: {LATEST_PERPS_THESIS_FILE}")
    return history_path


# ---------------------------------------------------------------------------
# LLM summary generation
# ---------------------------------------------------------------------------

PERPS_ZONE_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["low", "high", "stop_loss", "targets", "label"],
    "properties": {
        "low": {"type": "number"},
        "high": {"type": "number"},
        "stop_loss": {"type": "number"},
        "targets": {"type": "array", "items": {"type": "number"}},
        "label": {"type": "string"},
    },
}


PERPS_THESIS_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "symbol",
        "video_id",
        "generated_at",
        "valid_until",
        "macro_bias",
        "preferred_setup",
        "confidence",
        "long_zones",
        "short_zones",
        "invalidation_levels",
        "no_trade_conditions",
        "notes",
    ],
    "properties": {
        "schema_version": {"type": "integer"},
        "symbol": {"type": "string", "enum": [BEECTHOR_PERPS_SYMBOL]},
        "video_id": {"type": "string"},
        "generated_at": {"type": "string"},
        "valid_until": {"type": "string"},
        "macro_bias": {"type": "string"},
        "preferred_setup": {"type": "string"},
        "confidence": {"type": "number"},
        "long_zones": {"type": "array", "items": PERPS_ZONE_OUTPUT_SCHEMA},
        "short_zones": {"type": "array", "items": PERPS_ZONE_OUTPUT_SCHEMA},
        "invalidation_levels": {"type": "array", "items": {"type": "number"}},
        "no_trade_conditions": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
}


SHORT_SUMMARY_FIELDS = ("expected_move", "if_lower", "if_higher", "his_plan", "long_term")

SUMMARY_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [*SHORT_SUMMARY_FIELDS, "perps_thesis"],
    "properties": {
        **{field: {"type": "string"} for field in SHORT_SUMMARY_FIELDS},
        "perps_thesis": PERPS_THESIS_OUTPUT_SCHEMA,
    },
}


SHORT_SUMMARY_GUIDE = (
    "The Telegram message is read by people who do NOT know technical analysis. "
    "Write in plain, everyday Spanish, as if explaining it to a friend. "
    "Strictly forbidden jargon in these five fields: ondas, Elliott, conteos, A-B-C, impulsos, "
    "Fibonacci, retrocesos (0,382, 0,5...), Golden Pocket, Value Area, POC, EMAs, AVWAP, order blocks, "
    "liquidaciones, gap del CME. Translate any of them into what it means for the price "
    "(e.g. 'una zona donde suele rebotar').\n"
    "Use at most three price levels across the whole summary: one for the expected move, "
    "one for the downside case and one for the upside case. Write prices like 70.000 $ or "
    "70.000–71.000 $. Never invent levels that are not in the transcript.\n"
    "Each field is ONE short sentence (max ~25 words), no bullets, no HTML tags:\n"
    '  "expected_move": where Beecthor expects BTC to go next in the short term (hours to a few days), '
    "and what he expects after that. Example: 'que el precio siga bajando un poco más, hasta "
    "70.000–71.000 $, y que desde ahí rebote.'\n"
    '  "if_lower": what happens if the price falls further than expected: the next zone where he sees '
    "a bounce. Example: 'la siguiente zona donde ve rebote está en 66.700–67.600 $.'\n"
    '  "if_higher": what would change his mind upwards. Example: \'solo daría la bajada por terminada si '
    "BTC recupera los 81.000 $.'\n"
    '  "his_plan": what he would do himself, in plain words. Beecthor separates two activities and the '
    "reader must never confuse them: (1) TRADING (perps): opening or holding longs/shorts; (2) CYCLE "
    "ACCUMULATION (spot): his long-term 'compras de ciclo'. Never write a bare 'comprar' or 'vender': say "
    "'abrir largos/cortos' or 'mantener el corto' for trading, and 'compras de ciclo' or 'acumular en "
    "spot' for accumulation. If the video mentions both, include both in the same sentence. If he already "
    "has an open trade, mention it. Example: 'para trading, no abrir largos todavía; esperar a que toque "
    "70.000 $ y se dé la vuelta. Mientras tanto sigue con sus compras de ciclo en spot.' If the video "
    "gives no clear trading path, say plainly that he sees no clear trade and prefers to wait.\n"
    '  "long_term": the big-picture direction in one sentence, no levels. Example: \'sigue siendo alcista. '
    "Ve esta caída como una corrección normal dentro de una subida mayor.'\n"
    "Start each field in lowercase unless it begins with a proper noun or BTC, because the message "
    "puts a bold label before it (e.g. 'Qué espera: ...'). Never repeat the label words at the start of the field (write 'la siguiente zona...', not 'si cae más, la siguiente zona...'; write 'sigue viendo más subida', not 'a largo plazo sigue...'). If the transcript does not cover a field, "
    "say so briefly in plain words instead of guessing."
)


def build_current_market_context(prices_now: dict | None) -> str:
    if not prices_now:
        return "Current BTC market context is unavailable."
    btc_usd = prices_now.get("btc_usd")
    btc_eur = prices_now.get("btc_eur")
    if btc_usd is None:
        return "Current BTC market context is unavailable."
    context = f"Current BTC reference: BTC is approximately {btc_usd}$"
    if btc_eur is not None:
        context += f" / {btc_eur}€"
    return (
        context
        + ". Use it only to phrase the summary relative to the current price; direction and levels "
        "must come from Beecthor's transcript. BTCUSDC can be treated as the same USD reference."
    )


def build_llm_summary_prompt(
    transcript: str,
    video_id: str,
    prices_now: dict | None = None,
    max_transcript_chars: int = MAX_LLM_TRANSCRIPT_CHARS,
) -> str:
    excerpt = transcript[:max_transcript_chars]
    if len(transcript) > max_transcript_chars:
        excerpt += "\n[transcript truncated]"

    return (
        "You are a financial analyst assistant specialized in Bitcoin technical analysis.\n"
        "Analyze the following transcript from a Spanish Bitcoin trading video by Beecthor and "
        "explain his short-term price expectation in very simple terms.\n\n"
        f"{build_current_market_context(prices_now)}\n\n"
        "Return ONLY a valid JSON object with exactly these six fields: "
        f"{', '.join(SHORT_SUMMARY_FIELDS)}, perps_thesis.\n\n"
        f"{SHORT_SUMMARY_GUIDE}\n\n"
        f'  "perps_thesis": an object for a deterministic {BEECTHOR_PERPS_SYMBOL} perpetual futures bot. '
        "This object is NOT shown to readers, so technical precision is welcome here. "
        "Use English enum values and numeric prices only. If the transcript is ambiguous, "
        'set preferred_setup to "wait" and leave long_zones and short_zones empty. '
        "Supported preferred_setup values are: wait, short_resistance_bearish_regime, "
        "short_resistance, short_rejection, long_support_sweep_reclaim, long_support, "
        "sweep_reclaim_long. The perps_thesis object must contain exactly these fields: "
        "schema_version, symbol, video_id, generated_at, valid_until, macro_bias, "
        "preferred_setup, confidence, long_zones, short_zones, invalidation_levels, "
        "no_trade_conditions, notes. Each zone must contain low, high, stop_loss, targets, label. "
        "Long targets must be above the zone and long stop_loss below the zone. "
        "Short targets must be below the zone and short stop_loss above the zone. "
        "Never invent precise levels not supported by the transcript; prefer wait when unsure. "
        f'Use video_id "{video_id}" and symbol "{BEECTHOR_PERPS_SYMBOL}". valid_until must be no more than '
        f"{MAX_PERPS_THESIS_VALID_HOURS} hours after generated_at. "
        "The five summary fields must be consistent with perps_thesis: if preferred_setup is "
        '"wait", his_plan must not suggest opening a trade.\n\n'
        "The five summary fields must be in Spanish. perps_thesis enum/string fields must be in English.\n"
        "Return ONLY valid JSON. No markdown fences, no explanation outside the JSON.\n\n"
        f"TRANSCRIPT:\n{excerpt}"
    )


def parse_llm_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(raw):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(raw[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise RuntimeError(f"LLM output did not contain valid JSON:\n{raw[:500]}")


def _clean_summary_sentence(value: object) -> str:
    """Strip HTML tags, bullets and stray whitespace from a one-sentence summary field."""
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    text = re.sub(r"^\s*[•\-*]\s*", "", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_summary_payload(data: dict, video_id: str) -> tuple[dict[str, str], dict]:
    """Return (short_summary, perps_thesis) from the LLM JSON payload."""
    perps_thesis = normalize_perps_thesis(data.get("perps_thesis"), video_id)
    short_summary = {field: _clean_summary_sentence(data.get(field)) for field in SHORT_SUMMARY_FIELDS}
    missing = [field for field, value in short_summary.items() if not value]
    if missing:
        raise RuntimeError(f"LLM JSON missing required summary fields: {missing}")
    return short_summary, perps_thesis


def generate_summary_via_codex(
    transcript: str,
    video_id: str,
    prices_now: dict | None = None,
) -> tuple[dict[str, str], dict]:
    """Call Codex CLI non-interactively; returns (short_summary, perps_thesis)."""
    codex_bin = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_bin:
        raise RuntimeError("Codex CLI not found in PATH")

    prompt = build_llm_summary_prompt(transcript, video_id, prices_now)
    env = os.environ.copy()
    env.setdefault("LANG", "en_US.UTF-8")
    env.setdefault("PYTHONIOENCODING", "utf-8")

    last_message_raw = ""
    with tempfile.TemporaryDirectory() as tmpdir:
        schema_path = Path(tmpdir) / "summary_schema.json"
        last_message_path = Path(tmpdir) / "last_message.json"
        schema_path.write_text(json.dumps(SUMMARY_OUTPUT_SCHEMA), encoding="utf-8")
        cmd = [
            codex_bin,
            "exec",
            "--sandbox",
            "read-only",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(last_message_path),
        ]
        if BEECTHOR_CODEX_MODEL:
            cmd.extend(["--model", BEECTHOR_CODEX_MODEL])
        cmd.append("-")
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
            env=env,
            timeout=600,
            check=False,
        )
        if last_message_path.exists():
            last_message_raw = last_message_path.read_text(encoding="utf-8").strip()

    if result.returncode != 0:
        raise RuntimeError(
            f"Codex exited {result.returncode}: stdout={result.stdout[:4000]} stderr={result.stderr[:4000]}"
        )
    return normalize_summary_payload(parse_llm_json(last_message_raw or result.stdout), video_id)


MAX_COPILOT_TRANSCRIPT_CHARS = 6_000


def generate_summary_via_copilot(
    transcript: str,
    video_id: str,
    prices_now: dict | None = None,
) -> tuple[dict[str, str], dict]:
    """Call Copilot CLI to generate the short Beecthor summary.

    Returns (short_summary, perps_thesis).
    Raises RuntimeError if Copilot auth is missing or output cannot be parsed.
    """
    prompt = build_llm_summary_prompt(
        transcript, video_id, prices_now, max_transcript_chars=MAX_COPILOT_TRANSCRIPT_CHARS
    )

    env = os.environ.copy()
    has_token = env.get("COPILOT_GITHUB_TOKEN") or env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
    has_gh_auth = (
        subprocess.run(["gh", "auth", "status"], capture_output=True, env=env).returncode == 0
    )
    if not has_token and not has_gh_auth:
        raise RuntimeError(
            "No Copilot authentication found. Set COPILOT_GITHUB_TOKEN or run gh auth login"
        )

    result = subprocess.run(
        ["copilot", "-p", prompt, "-s", "--no-ask-user"],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=True,
    )

    raw = result.stdout.strip()
    # Strip markdown fences if present
    raw = re.sub(r"^```(?:json)?", "", raw).strip()
    raw = re.sub(r"```$", "", raw).strip()
    # Find first JSON object in the output
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        raise RuntimeError(f"Copilot output did not contain valid JSON:\n{raw[:500]}")
    data = json.loads(match.group())

    return normalize_summary_payload(data, video_id)


def generate_summary_via_llm(
    transcript: str,
    video_id: str,
    prices_now: dict | None = None,
) -> tuple[dict[str, str], dict]:
    if BEECTHOR_SUMMARY_LLM_PROVIDER == "copilot":
        return generate_summary_via_copilot(transcript, video_id, prices_now)
    if BEECTHOR_SUMMARY_LLM_PROVIDER == "codex":
        return generate_summary_via_codex(transcript, video_id, prices_now)
    raise RuntimeError(
        "Unsupported BEECTHOR_SUMMARY_LLM_PROVIDER: "
        f"{BEECTHOR_SUMMARY_LLM_PROVIDER!r}. Use 'codex' or 'copilot'."
    )


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------


ALLOWED_TELEGRAM_TAG_RE = re.compile(r"</?(?:b|i|u|s|code|pre)>", flags=re.IGNORECASE)


def sanitize_telegram_html_fragment(text: object) -> str:
    """Escape dynamic LLM text while preserving the small HTML subset we allow."""
    value = str(text or "")
    placeholders: dict[str, str] = {}

    def hold_allowed_tag(match: re.Match[str]) -> str:
        placeholder = f"__TG_HTML_TAG_{len(placeholders)}__"
        placeholders[placeholder] = match.group(0)
        return placeholder

    protected = ALLOWED_TELEGRAM_TAG_RE.sub(hold_allowed_tag, value)
    escaped = html.escape(protected, quote=False)
    for placeholder, tag in placeholders.items():
        escaped = escaped.replace(placeholder, tag)
    return escaped


def _fmt_price(value: float) -> str:
    """Format a BTC price with European thousands separator (e.g. 73.200)."""
    return f"{value:,.0f}".replace(",", ".")


SHORT_SUMMARY_LINES = (
    ("expected_move", "👉", "Qué espera"),
    ("if_lower", "🛑", "Si cae más"),
    ("if_higher", "✅", "Si sube"),
    ("his_plan", "💡", "Qué haría él"),
    ("long_term", "🧭", "A largo plazo"),
)


def build_message(
    video_id: str,
    prices_now: dict,
    prices_yesterday: dict | None,
    short_summary: dict[str, str],
) -> str:
    """Assemble the short, jargon-free HTML Telegram message."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    lines = [f'🎯 <b>Beecthor — vídeo de hoy</b> (<a href="{video_url}">ver</a>)']

    price_line = f"BTC ahora: <b>{_fmt_price(prices_now['btc_usd'])} $</b>"
    if prices_yesterday and prices_yesterday.get("btc_usd"):
        btc_pct = (prices_now["btc_usd"] - prices_yesterday["btc_usd"]) / prices_yesterday["btc_usd"] * 100
        price_line += f" ({btc_pct:+.1f} % desde ayer)".replace(".", ",")
    lines.extend([price_line, ""])

    for field, emoji, label in SHORT_SUMMARY_LINES:
        text = sanitize_telegram_html_fragment(short_summary.get(field, ""))
        if text:
            lines.extend([f"{emoji} <b>{label}:</b> {text}", ""])

    return "\n".join(lines).rstrip()


def collect_video_context(
    video_id: str,
    save_to_disk: bool = True,
    transcript: str | None = None,
) -> dict:
    """Collect transcript, prices, and local robot score for agent-authored summaries."""
    if transcript is None:
        print("Fetching transcript...")
        transcript = get_transcript(video_id)
    else:
        print(f"Using provided transcript ({len(transcript)} chars).")

    if save_to_disk:
        print("Saving transcript...")
        save_transcript(video_id, transcript)

    print("Fetching live prices from CoinGecko...")
    prices_now = get_live_prices()
    prices_yesterday = get_yesterday_prices()
    print(
        f"BTC: ${prices_now['btc_usd']:,.0f} / €{prices_now['btc_eur']:,.0f}"
        f" | SOL: ${prices_now['sol_usd']:.2f}"
    )

    print("Generating robot score locally...")
    robot_score, robot_comment = generate_robot_score(transcript)
    print(f"Robot score: {robot_score:.1f}/10")

    return {
        "video_id": video_id,
        "transcript": transcript,
        "prices_now": prices_now,
        "prices_yesterday": prices_yesterday,
        "robot_score": robot_score,
        "robot_comment": robot_comment,
    }


def finalize_daily_message(
    video_id: str,
    prices: dict,
    robot_score: float,
    message: str,
    update_last_processed: bool = True,
) -> None:
    """Persist a manually authored message after it has been reviewed and optionally sent."""
    if update_last_processed:
        save_last_processed_id(video_id)
        print(f"Saved last_video_id: {video_id}")

    append_log_entry(video_id, prices, robot_score, message)

    print("Committing to git...")
    git_commit_and_push(video_id)

    print("Done.")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def compact_telegram_message(message: str, max_chars: int = TELEGRAM_MAX_MESSAGE_CHARS) -> str:
    """Keep Telegram delivery under its practical HTML limit without losing the saved full log."""
    if len(message) <= max_chars:
        return message

    marker = "\n🔍 <b>Análisis completo</b>"
    fallback_analysis = (
        "\n\n🔍 <b>Análisis completo</b>\n"
        "<tg-spoiler>Resumen completo disponible en la aplicación Flask.</tg-spoiler>"
    )
    if marker in message:
        head = message.split(marker, 1)[0].rstrip()
        compact = f"{head}{fallback_analysis}"
        if len(compact) <= max_chars:
            return compact

    suffix = "\n\n<i>Mensaje recortado por límite de Telegram; resumen completo en la aplicación Flask.</i>"
    budget = max_chars - len(suffix)
    cut = message[: max(0, budget)].rstrip()
    paragraph_cut = cut.rfind("\n\n")
    if paragraph_cut > 0:
        cut = cut[:paragraph_cut].rstrip()
    return f"{cut}{suffix}"


def telegram_plain_text_fallback(message: str, max_chars: int = TELEGRAM_MAX_MESSAGE_CHARS) -> str:
    """Plain text fallback for rare Telegram HTML parser failures."""
    plain = re.sub(r"</?tg-spoiler>", "", message)
    plain = re.sub(r"<a\s+href=\"[^\"]+\">([^<]+)</a>", r"\1", plain, flags=re.IGNORECASE)
    plain = re.sub(r"</?(?:b|i|u|s|code|pre)>", "", plain, flags=re.IGNORECASE)
    plain = html.unescape(plain)
    if len(plain) <= max_chars:
        return plain
    suffix = "\n\n[Mensaje recortado por límite de Telegram; resumen completo en la aplicación Flask.]"
    return plain[: max(0, max_chars - len(suffix))].rstrip() + suffix


def raise_telegram_error(response: requests.Response) -> None:
    """Raise a sanitized Telegram error without leaking the bot token in the URL."""
    try:
        details = response.json()
    except ValueError:
        details = response.text
    details_text = str(details).replace(TELEGRAM_BOT_TOKEN, "[redacted]")[:500]
    raise RuntimeError(f"Telegram sendMessage failed with HTTP {response.status_code}: {details_text}")


def send_telegram_message(message: str) -> None:
    """Send an HTML-formatted message to the configured Telegram group."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    safe_message = compact_telegram_message(message)
    if safe_message != message:
        print(
            "Telegram message compacted "
            f"from {len(message)} to {len(safe_message)} chars before sending."
        )
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": safe_message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    response = requests.post(url, json=payload, timeout=30)
    if response.ok:
        print("Message sent to Telegram successfully.")
        return

    print(f"Telegram HTML send failed with HTTP {response.status_code}; trying plain text fallback.")
    fallback_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": telegram_plain_text_fallback(safe_message),
        "disable_web_page_preview": False,
    }
    fallback_response = requests.post(url, json=fallback_payload, timeout=30)
    if not fallback_response.ok:
        raise_telegram_error(fallback_response)
    print("Message sent to Telegram successfully.")


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------


def append_log_entry(
    video_id: str,
    prices: dict,
    robot_score: float,
    message: str,
) -> None:
    """Append a new summary entry to analyses_log.json."""
    if LOG_FILE.exists():
        entries = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    else:
        entries = []
    if any(existing.get("video_id") == video_id for existing in entries if isinstance(existing, dict)):
        print(f"Log entry for {video_id} already exists. Skipping append.")
        return

    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "type": "latest_video_summary",
        "video_id": video_id,
        "video_url": f"https://www.youtube.com/watch?v={video_id}",
        "btc_usd": prices["btc_usd"],
        "btc_eur": prices["btc_eur"],
        "sol_usd": prices["sol_usd"],
        "sol_eur": prices["sol_eur"],
        "robot_score": robot_score,
        "message": message,
    }
    entries.append(entry)
    LOG_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Log entry appended (entry #{len(entries)}).")


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


def git_commit_and_push(video_id: str) -> None:
    """Stage relevant files and commit + push to main."""
    files_to_add = [
        str(LAST_VIDEO_FILE),
        str(LOG_FILE),
        str(REPO_ROOT / "doc" / "CHANGELOG.md"),
    ]
    for f in TRANSCRIPTS_DIR.glob(f"{video_id}_*.txt"):
        files_to_add.append(str(f))
    for f in PERPS_THESES_DIR.glob(f"*_{video_id}.json"):
        files_to_add.append(str(f))
    if LATEST_PERPS_THESIS_FILE.exists():
        files_to_add.append(str(LATEST_PERPS_THESIS_FILE))

    try:
        subprocess.run(["git", "add"] + files_to_add, cwd=REPO_ROOT, check=True)
        subprocess.run(
            [
                "git", "commit", "-m",
                f"daily: {video_id} ({datetime.now().strftime('%Y-%m-%d')})",
            ],
            cwd=REPO_ROOT,
            check=True,
        )
        subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
        print("Git commit and push successful.")
    except subprocess.CalledProcessError as e:
        print(f"Git operation failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_daily(video_id: str, send_telegram: bool = True) -> None:
    """
    Collect transcript and market context for a given video ID.
    The final summary/message must be authored by the agent in chat.
    """
    context = collect_video_context(video_id, save_to_disk=True)

    if send_telegram:
        print(
            "Automatic send is disabled: write the summary/message in chat first, "
            "then call send_telegram_message() and finalize_daily_message() after approval."
        )
    else:
        print("Data collection complete. Manual summary still required.")

    print(
        f"Context ready for {context['video_id']} with transcript length "
        f"{len(context['transcript'])} chars."
    )


def log_entry_exists(video_id: str) -> bool:
    if not LOG_FILE.exists():
        return False
    try:
        entries = json.loads(LOG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return any(entry.get("video_id") == video_id for entry in entries if isinstance(entry, dict))


def infer_video_id_from_transcript_path(path: Path) -> str:
    stem = path.stem
    match = re.match(r"(?P<video_id>[A-Za-z0-9_-]+)_\d{4}-\d{2}-\d{2}$", stem)
    return match.group("video_id") if match else stem


def run_auto(
    video_id: str,
    transcript_path: Path | None = None,
    *,
    send_telegram: bool = True,
    update_last_processed: bool = True,
    commit_and_push: bool = True,
) -> None:
    """Fully automated flow: collect context, generate summary via configured LLM, send and commit."""
    if log_entry_exists(video_id):
        print(f"Entry for {video_id} already exists in analyses_log.json. Nothing to do.")
        return

    provided_transcript = None
    save_to_disk = True
    if transcript_path is not None:
        provided_transcript = transcript_path.read_text(encoding="utf-8")
        save_to_disk = False

    context = collect_video_context(video_id, save_to_disk=save_to_disk, transcript=provided_transcript)

    print(f"Generating summary via {BEECTHOR_SUMMARY_LLM_PROVIDER}...")
    short_summary, perps_thesis = generate_summary_via_llm(
        context["transcript"],
        context["video_id"],
        context["prices_now"],
    )
    print("Summary generated.")

    message = build_message(
        video_id=context["video_id"],
        prices_now=context["prices_now"],
        prices_yesterday=context["prices_yesterday"],
        short_summary=short_summary,
    )

    if send_telegram:
        print("Sending message to Telegram...")
        send_telegram_message(message)
    else:
        print("Telegram send skipped by request.")

    if update_last_processed:
        save_last_processed_id(video_id)
    else:
        print("last_video_id.txt update skipped by request.")
    append_log_entry(video_id, context["prices_now"], context["robot_score"], message)
    save_perps_thesis(video_id, perps_thesis)
    if commit_and_push:
        git_commit_and_push(video_id)
    else:
        print("Git commit/push skipped by request.")
    print("Done.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Beecthor Bitcoin Summary Bot")
    parser.add_argument(
        "--backfill",
        metavar="VIDEO_ID",
        help=(
            "Collect transcript and prices for a past video without attempting "
            "automatic Telegram delivery."
        ),
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "Fully automated mode: generate summary via the configured LLM, send to Telegram, "
            "and commit without manual intervention."
        ),
    )
    parser.add_argument(
        "--from-transcript",
        type=Path,
        help="Use an already saved transcript file instead of downloading from YouTube.",
    )
    parser.add_argument(
        "--video-id",
        help="Specific video ID to process with --auto, or to use with --from-transcript.",
    )
    parser.add_argument(
        "--no-telegram",
        action="store_true",
        help="With --auto, generate and store the summary without sending it to Telegram.",
    )
    parser.add_argument(
        "--no-update-last",
        action="store_true",
        help="With --auto, do not update last_video_id.txt.",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="With --auto, do not create or push a git commit.",
    )
    args = parser.parse_args()

    print("=== Beecthor Bitcoin Summary ===")

    if args.from_transcript:
        transcript_path = args.from_transcript
        if not transcript_path.exists():
            raise FileNotFoundError(f"Transcript file not found: {transcript_path}")
        video_id = args.video_id or infer_video_id_from_transcript_path(transcript_path)
        print(f"Transcript mode: {transcript_path} -> {video_id}")
        run_auto(
            video_id,
            transcript_path=transcript_path,
            send_telegram=not args.no_telegram,
            update_last_processed=not args.no_update_last,
            commit_and_push=not args.no_git,
        )
        return

    if args.video_id and args.auto:
        print(f"Auto mode for explicit video ID: {args.video_id}")
        run_auto(
            args.video_id,
            send_telegram=not args.no_telegram,
            update_last_processed=not args.no_update_last,
            commit_and_push=not args.no_git,
        )
        return

    if args.backfill:
        print(f"Backfill mode: {args.backfill}")
        run_daily(args.backfill, send_telegram=False)
        return

    print("Fetching latest video ID from channel...")
    latest_id = get_latest_video_id()
    print(f"Latest video: https://www.youtube.com/watch?v={latest_id}")

    last_id = get_last_processed_id()
    print(f"Last processed: {last_id or '(none)'}")

    if latest_id == last_id:
        print("No new video found. Nothing to do.")
        sys.exit(0)

    print(f"New video detected: {latest_id}")
    if args.auto:
        run_auto(
            latest_id,
            send_telegram=not args.no_telegram,
            update_last_processed=not args.no_update_last,
            commit_and_push=not args.no_git,
        )
    else:
        run_daily(latest_id, send_telegram=True)


if __name__ == "__main__":
    main()
