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

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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
LAST_VIDEO_FILE = REPO_ROOT / "last_video_id.txt"
LOG_FILE = REPO_ROOT / "analyses_log.json"
TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

MAX_TRANSCRIPT_CHARS = 80_000  # ~80K chars stays safely within the 128K-token context

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
# Copilot CLI summary generation
# ---------------------------------------------------------------------------

MAX_COPILOT_TRANSCRIPT_CHARS = 6_000


def generate_summary_via_copilot(
    transcript: str,
    robot_score: float,
    robot_comment: str,
) -> tuple[str, str, str]:
    """Call Copilot CLI to generate the Beecthor summary fields.

    Returns (macro_summary, resumen, full_analysis) — all in Spanish.
    Raises RuntimeError if Copilot auth is missing or output cannot be parsed.
    """
    excerpt = transcript[:MAX_COPILOT_TRANSCRIPT_CHARS]
    if len(transcript) > MAX_COPILOT_TRANSCRIPT_CHARS:
        excerpt += "\n[transcript truncated]"

    prompt = (
        "You are a financial analyst assistant specialized in Bitcoin technical analysis.\n"
        "Analyze the following transcript from a Spanish Bitcoin trading video by Beecthor "
        f"(robot score: {robot_score:.1f}/10 — {robot_comment}).\n\n"
        "Return ONLY a valid JSON object with exactly these three fields (all content in Spanish):\n"
        '  "macro_summary": 1-2 sentences on the macro BTC outlook (direction, key levels, bias)\n'
        '  "resumen": 3-5 bullet lines covering macro view, Elliott count/structure, key levels, '
        "liquidations, and the operational conclusion. Each bullet starts with •\n"
        '  "full_analysis": a detailed paragraph covering all technical aspects: Elliott wave count, '
        "Fibonacci levels, liquidations, Value Area/POC, EMAs, AVWAP, supports/resistances, "
        "and the operational conclusion\n\n"
        "Return ONLY valid JSON. No markdown fences, no explanation outside the JSON.\n\n"
        f"TRANSCRIPT:\n{excerpt}"
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

    macro_summary = data.get("macro_summary", "")
    resumen = data.get("resumen", "")
    full_analysis = data.get("full_analysis", "")
    if not macro_summary or not resumen or not full_analysis:
        raise RuntimeError(f"Copilot JSON missing required fields: {list(data.keys())}")

    return macro_summary, resumen, full_analysis


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------


def _fmt_btc(usd: float, eur: float) -> str:
    """Format a BTC price pair with European thousands separator (e.g. 70.492$)."""
    return f"<b>{usd:,.0f}$</b> / <b>{eur:,.0f}€</b>".replace(",", ".")


def _fmt_sol(usd: float, eur: float) -> str:
    """Format a SOL price pair with two decimal places."""
    return f"<b>{usd:.2f}$</b> / <b>{eur:.2f}€</b>"


def build_message(
    video_id: str,
    prices_now: dict,
    prices_yesterday: dict | None,
    robot_score: float,
    robot_comment: str,
    resumen: str,
    macro_summary: str,
    full_analysis: str,
) -> str:
    """Assemble the full HTML Telegram message."""
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    lines = [f'🎯 <b>Beecthor — Último vídeo</b> (<a href="{video_url}">ver</a>)', ""]

    if prices_yesterday:
        btc_pct = (
            (prices_now["btc_usd"] - prices_yesterday["btc_usd"])
            / prices_yesterday["btc_usd"]
            * 100
        )
        lines.append(
            f"📈 BTC ayer: {_fmt_btc(prices_yesterday['btc_usd'], prices_yesterday['btc_eur'])}"
        )
        lines.append(
            f"📈 BTC ahora: {_fmt_btc(prices_now['btc_usd'], prices_now['btc_eur'])}"
            f"  (<b>{btc_pct:+.2f}%</b>)"
        )
        lines.append("")

        if prices_yesterday.get("sol_usd") and prices_now.get("sol_usd"):
            sol_pct = (
                (prices_now["sol_usd"] - prices_yesterday["sol_usd"])
                / prices_yesterday["sol_usd"]
                * 100
            )
            lines.append(
                f"📈 SOL ayer: {_fmt_sol(prices_yesterday['sol_usd'], prices_yesterday['sol_eur'])}"
            )
            lines.append(
                f"📈 SOL ahora: {_fmt_sol(prices_now['sol_usd'], prices_now['sol_eur'])}"
                f"  (<b>{sol_pct:+.2f}%</b>)"
            )
            lines.append("")
    else:
        # First run — no previous log entry to compare against
        lines.append(f"💰 BTC ahora: {_fmt_btc(prices_now['btc_usd'], prices_now['btc_eur'])}")
        if prices_now.get("sol_usd"):
            lines.append(f"💰 SOL ahora: {_fmt_sol(prices_now['sol_usd'], prices_now['sol_eur'])}")
        lines.append("")

    if macro_summary:
        lines.append("🧭 <b>Visión macro</b>")
        lines.append(macro_summary)
        lines.append("")

    lines.append(f"🤖 <b>Índice robot: {robot_score:.1f} / 10</b>")
    lines.append(f"<i>{robot_comment}</i>")
    lines.append("")
    lines.append("📌 <b>Resumen</b>")
    lines.append(resumen)
    lines.append("")
    lines.append("🔍 <b>Análisis completo</b> <i>(toca para ver)</i>")
    lines.append(f"<tg-spoiler>{full_analysis}</tg-spoiler>")

    return "\n".join(lines)


def collect_video_context(video_id: str, save_to_disk: bool = True) -> dict:
    """Collect transcript, prices, and local robot score for agent-authored summaries."""
    print("Fetching transcript...")
    transcript = get_transcript(video_id)

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


def send_telegram_message(message: str) -> None:
    """Send an HTML-formatted message to the configured Telegram group."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
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
        str(REPO_ROOT / "CHANGELOG.md"),
    ]
    for f in TRANSCRIPTS_DIR.glob(f"{video_id}_*.txt"):
        files_to_add.append(str(f))

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


def run_auto(video_id: str) -> None:
    """Fully automated flow: collect context, generate summary via Copilot CLI, send and commit."""
    context = collect_video_context(video_id, save_to_disk=True)

    print("Generating summary via Copilot CLI...")
    macro_summary, resumen, full_analysis = generate_summary_via_copilot(
        context["transcript"],
        context["robot_score"],
        context["robot_comment"],
    )
    print("Summary generated.")

    message = build_message(
        video_id=context["video_id"],
        prices_now=context["prices_now"],
        prices_yesterday=context["prices_yesterday"],
        robot_score=context["robot_score"],
        robot_comment=context["robot_comment"],
        resumen=resumen,
        macro_summary=macro_summary,
        full_analysis=full_analysis,
    )

    print("Sending message to Telegram...")
    send_telegram_message(message)

    save_last_processed_id(video_id)
    append_log_entry(video_id, context["prices_now"], context["robot_score"], message)
    git_commit_and_push(video_id)
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
            "Fully automated mode: generate summary via Copilot CLI, send to Telegram, "
            "and commit without manual intervention."
        ),
    )
    args = parser.parse_args()

    print("=== Beecthor Bitcoin Summary ===")

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
        run_auto(latest_id)
    else:
        run_daily(latest_id, send_telegram=True)


if __name__ == "__main__":
    main()
