#!/usr/bin/env python3
"""
Beecthor Summarizer - Phone Script

Fetches the latest Beecthor YouTube video, downloads its transcript,
generates a structured summary using Copilot CLI, and appends it to
analyses_log.json in the repo.

Run manually after a new video is published, or add to crontab.

Dependencies: requests, python-dotenv, youtube-transcript-api
"""

import json
import os
import re
import shutil
import subprocess
import sys
import argparse
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from log_client import refresh_log_client_config, send_server_log

ENV_FILE = Path.home() / '.polymarket.env'
LAST_PROCESSED_FILE = Path.home() / '.beecthor_last_processed_video_id'

BEECTHOR_CHANNEL_ID = 'UCO5MrB8OoQ_nRzeB_ehPbFw'  # youtube.com/@Beecthor
BINANCE_TICKER_URL = 'https://api.binance.com/api/v3/ticker/price'
COPILOT_MODEL = 'gpt-5.4'
NUM_EXAMPLES = 2  # entries from analyses_log used as format examples
TELEGRAM_MAX_MESSAGE_CHARS = 4000
TRANSCRIPT_RETRY_ATTEMPTS = 2
TRANSCRIPT_RETRY_DELAY_SECONDS = 5 * 60

load_dotenv(ENV_FILE)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
GH_TOKEN = os.environ.get('GH_TOKEN', '')
refresh_log_client_config()


def detect_repo_dir() -> Path:
    repo_from_script = Path(__file__).resolve().parent.parent
    if (repo_from_script / 'analyses_log.json').exists():
        return repo_from_script
    return Path.home() / 'beecthor-summary'


REPO_DIR = detect_repo_dir()
ANALYSES_LOG = REPO_DIR / 'analyses_log.json'
TRANSCRIPTS_DIR = REPO_DIR / 'transcripts'
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))


def now_utc() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


class TranscriptRetryableError(RuntimeError):
    """Raised when the latest video exists but subtitles/transcript are not ready yet."""


def shorten_error(value: Exception | str, limit: int = 300) -> str:
    text = str(value).replace('\n', ' ').strip()
    return text[:limit]


def is_retryable_transcript_error(exc: Exception) -> bool:
    if isinstance(exc, TranscriptRetryableError):
        return True
    text = shorten_error(exc).lower()
    markers = (
        'produced no vtt file',
        'could not retrieve a transcript',
        'no transcripts were found',
        'subtitles are unavailable',
        'subtitles are disabled',
        'failed to extract any player response',
    )
    return any(marker in text for marker in markers)


def split_telegram_message(text: str, max_chars: int = TELEGRAM_MAX_MESSAGE_CHARS) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    spoiler_match = re.search(r'<tg-spoiler>([\s\S]*)</tg-spoiler>', text)
    if not spoiler_match:
        return split_plain_html_text(text, max_chars)

    spoiler_start = spoiler_match.start()
    spoiler_end = spoiler_match.end()
    spoiler_text = spoiler_match.group(1)
    before_spoiler = text[:spoiler_start].rstrip()
    after_spoiler = text[spoiler_end:].strip()

    parts: list[str] = []
    if before_spoiler:
        parts.extend(split_plain_html_text(before_spoiler, max_chars))

    spoiler_chunks = split_plain_html_text(spoiler_text, max_chars - len('<tg-spoiler></tg-spoiler>'))
    for chunk in spoiler_chunks:
        parts.append(f'<tg-spoiler>{chunk}</tg-spoiler>')

    if after_spoiler:
        parts.extend(split_plain_html_text(after_spoiler, max_chars))

    return [part for part in parts if part.strip()]


def split_plain_html_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    paragraphs = text.split('\n\n')
    parts: list[str] = []
    current = ''

    for paragraph in paragraphs:
        candidate = f'{current}\n\n{paragraph}'.strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            parts.append(current)
            current = ''
        if len(paragraph) <= max_chars:
            current = paragraph
            continue
        parts.extend(split_long_line(paragraph, max_chars))

    if current:
        parts.append(current)

    return parts


def split_long_line(text: str, max_chars: int) -> list[str]:
    parts: list[str] = []
    remaining = text.strip()
    while len(remaining) > max_chars:
        split_at = remaining.rfind('\n', 0, max_chars)
        if split_at == -1:
            split_at = remaining.rfind(' ', 0, max_chars)
        if split_at == -1:
            split_at = max_chars
        parts.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


DASHBOARD_BASE_URL = 'https://6p6s8bcz-5050.uks1.devtunnels.ms/videos'
TELEGRAM_TRUNCATE_AT = 3900


def truncate_for_telegram(text: str, video_id: str = '') -> str:
    """If text exceeds TELEGRAM_TRUNCATE_AT, cut at the last paragraph boundary
    and append a link to the full summary on the dashboard."""
    if len(text) <= TELEGRAM_TRUNCATE_AT:
        return text
    link = f'{DASHBOARD_BASE_URL}/{video_id}' if video_id else DASHBOARD_BASE_URL
    suffix = f'\n\n… <a href="{link}">ver resumen completo →</a>'
    budget = TELEGRAM_TRUNCATE_AT - len(suffix)
    cut = text.rfind('\n\n', 0, budget)
    if cut == -1:
        cut = text.rfind('\n', 0, budget)
    if cut == -1:
        cut = budget
    truncated = text[:cut].rstrip()
    # Close any unclosed <tg-spoiler> tag to avoid Telegram HTML parse errors
    if truncated.count('<tg-spoiler>') > truncated.count('</tg-spoiler>'):
        truncated += '</tg-spoiler>'
    return truncated + suffix


def send_telegram_message(text: str, video_id: str = '') -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print('[summarizer] Telegram not configured. Skipping notification.')
        return

    text = truncate_for_telegram(text, video_id=video_id)
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False,
    }
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get('ok'):
        raise RuntimeError(f'Telegram API rejected message: {data}')
    print(f'[summarizer] Telegram message sent ({len(text)} chars).')


# ---------------------------------------------------------------------------
# YouTube helpers
# ---------------------------------------------------------------------------

def get_latest_video_id(channel_id: str) -> str:
    rss_url = f'https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}'
    resp = requests.get(rss_url, timeout=20)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    ns = {
        'atom': 'http://www.w3.org/2005/Atom',
        'yt': 'http://www.youtube.com/xml/schemas/2015',
    }
    entry = root.find('atom:entry', ns)
    if entry is None:
        raise RuntimeError('No entries found in channel RSS feed')
    return entry.find('yt:videoId', ns).text


def get_transcript(video_id: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=['es', 'es-ES', 'es-419', 'en'])
        return ' '.join(
            (s.text if hasattr(s, 'text') else s['text']) for s in fetched
        )
    except Exception as api_exc:
        try:
            return get_transcript_via_ytdlp(video_id)
        except TranscriptRetryableError as fallback_exc:
            raise TranscriptRetryableError(
                'Transcript not ready yet. '
                f'youtube-transcript-api: {shorten_error(api_exc)} | '
                f'yt-dlp: {shorten_error(fallback_exc)}'
            ) from fallback_exc


def parse_vtt(vtt_text: str) -> str:
    lines = []
    seen: set[str] = set()
    for line in vtt_text.splitlines():
        line = line.strip()
        if not line or line.startswith('WEBVTT') or '-->' in line or line.isdigit():
            continue
        line = re.sub(r'<[^>]+>', '', line).strip()
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    return ' '.join(lines)


def get_transcript_via_ytdlp(video_id: str) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                'yt-dlp',
                '--write-auto-subs',
                '--sub-lang', 'es',
                '--skip-download',
                '--js-runtimes', 'node',
                '--output', os.path.join(tmpdir, '%(id)s'),
                f'https://www.youtube.com/watch?v={video_id}',
            ],
            capture_output=True,
            text=True,
        )
        vtt_files = list(Path(tmpdir).glob('*.vtt'))
        if not vtt_files:
            raise TranscriptRetryableError(f'yt-dlp produced no VTT file. stderr: {result.stderr[:300]}')
        transcript = parse_vtt(vtt_files[0].read_text(encoding='utf-8'))
        if not transcript.strip():
            raise TranscriptRetryableError('yt-dlp produced an empty VTT transcript.')
        return transcript


def save_transcript(video_id: str, transcript: str) -> Path:
    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    date_str = datetime.now(UTC).strftime('%Y-%m-%d')
    path = TRANSCRIPTS_DIR / f'{video_id}_{date_str}.txt'
    path.write_text(transcript, encoding='utf-8')
    return path


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def get_prices() -> dict:
    def binance_price(symbol: str) -> float:
        return float(requests.get(BINANCE_TICKER_URL, params={'symbol': symbol}, timeout=10).json()['price'])

    btc_usd = binance_price('BTCUSDT')
    eur_usdt = binance_price('EURUSDT')  # 1 EUR in USDT
    sol_usd = binance_price('SOLUSDT')

    return {
        'btc_usd': round(btc_usd),
        'btc_eur': round(btc_usd / eur_usdt),
        'sol_usd': round(sol_usd, 2),
        'sol_eur': round(sol_usd / eur_usdt, 2),
    }


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def build_prompt(
    transcript: str,
    examples: list,
    prices: dict,
    prev_prices: dict,
    video_id: str,
) -> str:
    def pct_str(now, prev) -> str:
        if not prev:
            return ''
        change = (now - prev) / prev * 100
        sign = '+' if change >= 0 else ''
        return f'  (<b>{sign}{change:.2f}%</b>)'

    video_url = f'https://www.youtube.com/watch?v={video_id}'

    btc_pct = pct_str(prices['btc_usd'], prev_prices.get('btc_usd'))
    sol_pct = pct_str(prices['sol_usd'], prev_prices.get('sol_usd'))

    examples_json = json.dumps(examples, ensure_ascii=False, indent=2)

    return f"""You are a Spanish-speaking crypto analyst assistant. Your task is to summarize a YouTube video from "Beecthor", a Spanish Bitcoin analyst who uses Elliott Wave theory and Fibonacci levels.

Generate a JSON object following EXACTLY the format of the examples below. Pay close attention to:
- The HTML structure of the "message" field (Telegram HTML — use <b>, <i>, <a>, <tg-spoiler>)
- The 🤖 robot_score (float 0-10): how robotic/technical vs human the video felt
- The witty one-liner under the robot score (ironic, concise, in Spanish)
- The 🧭 Visión macro section: MAXIMUM 2 lines. Just the medium/long-term directional bias, nothing more. No wave counts, no Fibonacci levels, no targets — only the big-picture direction.
- The 📌 Resumen section: 2-3 direct lines with the key SHORT-TERM trade idea and the most important price levels.
- The full detailed analysis inside <tg-spoiler>
- PRICE LEVELS ARE CRITICAL: include every specific price level Beecthor mentions in <b> tags — resistance zones, support zones, VWAP/BWAP anchors, Fibonacci targets, liquidation clusters, wave invalidation points. Traders rely on these numbers. Do not omit any.
- Writing style: concise, uses <b> for key price levels and concepts, in Spanish
- The final "message" must fit in a single Telegram message and must not exceed 4096 total characters
- If you need to shorten something, shorten the macro narrative in <tg-spoiler> first — never drop price levels
- Do not produce multiple parts, continuations, or references to a second message

EXAMPLES (last {len(examples)} entries — learn the format from these):
{examples_json}

---

NEW VIDEO — generate the entry for this video.

The following values are already computed — embed them exactly in the message header:
- video_url: {video_url}
- BTC yesterday: {prev_prices.get('btc_usd', 'N/A')}$ / {prev_prices.get('btc_eur', 'N/A')}€
- BTC now: {prices['btc_usd']}$ / {prices['btc_eur']}€{btc_pct}
- SOL yesterday: {prev_prices.get('sol_usd', 'N/A')}$ / {prev_prices.get('sol_eur', 'N/A')}€
- SOL now: {prices['sol_usd']}$ / {prices['sol_eur']}€{sol_pct}

TRANSCRIPT:
{transcript[:14000]}

Return ONLY a valid JSON object with exactly two fields:
- "robot_score": float
- "message": string (full Telegram HTML message)

Do not include timestamp, video_id, video_url, btc_usd, etc. — the script adds those.
Do not wrap the JSON in markdown code blocks.
"""


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------

def run_copilot(prompt: str) -> dict:
    env = {**os.environ, 'LANG': 'en_US.UTF-8', 'PYTHONIOENCODING': 'utf-8'}
    copilot_bin = shutil.which('copilot') or shutil.which('copilot.cmd')
    if not copilot_bin:
        raise RuntimeError('copilot CLI not found in PATH')
    result = subprocess.run(
        [copilot_bin, '-p', prompt, '--model', COPILOT_MODEL, '-s', '--allow-all', '--no-ask-user'],
        capture_output=True, text=True, timeout=300, env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f'Copilot exited {result.returncode}: {result.stderr[:500]}')
    raw = result.stdout.strip()
    if raw.startswith('```'):
        raw = re.sub(r'^```(?:json)?', '', raw).strip()
        raw = re.sub(r'```$', '', raw).strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def git_env() -> dict:
    """Return env dict with GH_TOKEN injected for git credential helper."""
    env = {**os.environ}
    if GH_TOKEN:
        # Write credentials file and set helper — works regardless of global gitconfig
        cred_file = Path.home() / '.git-credentials'
        cred_line = f'https://x-access-token:{GH_TOKEN}@github.com\n'
        existing = cred_file.read_text() if cred_file.exists() else ''
        if 'github.com' not in existing:
            with open(cred_file, 'a') as f:
                f.write(cred_line)
        # Force credential.helper=store via env — overrides any broken global config
        env['GIT_CONFIG_COUNT'] = '1'
        env['GIT_CONFIG_KEY_0'] = 'credential.helper'
        env['GIT_CONFIG_VALUE_0'] = 'store'
    return env


def git_commit_and_push(video_id: str, transcript: str) -> None:
    if not GH_TOKEN:
        raise RuntimeError('GH_TOKEN not set — cannot push to GitHub')

    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    date_str = datetime.now(UTC).strftime('%Y-%m-%d')
    transcript_path = TRANSCRIPTS_DIR / f'{video_id}_{date_str}.txt'
    transcript_path.write_text(transcript, encoding='utf-8')

    env = git_env()
    subprocess.run(
        ['git', '-C', str(REPO_DIR), 'add', str(ANALYSES_LOG), str(transcript_path)],
        check=True, env=env,
    )
    subprocess.run(
        ['git', '-C', str(REPO_DIR), '-c', 'user.name=beecthor-summarizer[bot]',
         '-c', 'user.email=beecthor-summarizer[bot]@users.noreply.github.com',
         'commit', '-m', f'feat: Beecthor summary {video_id} ({date_str})'],
        check=True, capture_output=True, env=env,
    )
    subprocess.run(
        ['git', '-C', str(REPO_DIR), 'push', 'origin', 'main'],
        check=True, capture_output=True, env=env,
    )


def load_last_processed_id() -> str:
    try:
        return LAST_PROCESSED_FILE.read_text().strip()
    except Exception:
        return ''


def save_last_processed_id(video_id: str) -> None:
    LAST_PROCESSED_FILE.write_text(video_id)


def load_log() -> list:
    return json.loads(ANALYSES_LOG.read_text(encoding='utf-8')) if ANALYSES_LOG.exists() else []


def git_pull_rebase_if_configured() -> None:
    env = git_env()
    if not (REPO_DIR / '.git').exists():
        return
    try:
        subprocess.run(
            ['git', '-C', str(REPO_DIR), 'pull', '--rebase', 'origin', 'main'],
            check=True,
            capture_output=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        print(f'[summarizer] git pull skipped: {exc}')


def build_summary_entry(video_id: str) -> tuple[dict, str]:
    print('[summarizer] Downloading transcript...')
    transcript = get_transcript(video_id)
    print(f'[summarizer] Transcript length: {len(transcript)} chars')

    print('[summarizer] Fetching current prices...')
    prices = get_prices()
    print(f'[summarizer] BTC ${prices["btc_usd"]} / €{prices["btc_eur"]} | SOL ${prices["sol_usd"]}')

    log = load_log()
    examples = log[-NUM_EXAMPLES:] if len(log) >= NUM_EXAMPLES else log
    prev = log[-1] if log else {}
    prev_prices = {k: prev.get(k) for k in ('btc_usd', 'btc_eur', 'sol_usd', 'sol_eur')}

    print(f'[summarizer] Calling Copilot ({COPILOT_MODEL})...')
    prompt = build_prompt(transcript, examples, prices, prev_prices, video_id)
    result = run_copilot(prompt)
    print('[summarizer] Copilot done.')

    entry = {
        'timestamp': now_utc(),
        'type': 'latest_video_summary',
        'video_id': video_id,
        'video_url': f'https://www.youtube.com/watch?v={video_id}',
        'btc_usd': prices['btc_usd'],
        'btc_eur': prices['btc_eur'],
        'sol_usd': prices['sol_usd'],
        'sol_eur': prices['sol_eur'],
        'robot_score': result.get('robot_score', 0.0),
        'message': result['message'],
    }
    return entry, transcript


def build_summary_entry_with_retry(video_id: str) -> tuple[dict, str, int]:
    last_exc: Exception | None = None

    for attempt in range(1, TRANSCRIPT_RETRY_ATTEMPTS + 1):
        try:
            entry, transcript = build_summary_entry(video_id)
            return entry, transcript, attempt
        except Exception as exc:
            last_exc = exc
            if attempt >= TRANSCRIPT_RETRY_ATTEMPTS or not is_retryable_transcript_error(exc):
                raise

            wait_minutes = TRANSCRIPT_RETRY_DELAY_SECONDS // 60
            print(
                '[summarizer] Transcript not ready yet. '
                f'Waiting {wait_minutes} minutes before retry {attempt + 1}/{TRANSCRIPT_RETRY_ATTEMPTS}...'
            )
            send_server_log(
                'phone.summarizer',
                'retry_scheduled',
                'Transcript not ready yet; summarizer retry scheduled',
                level='warning',
                payload={
                    'video_id': video_id,
                    'attempt': attempt,
                    'retry_attempt': attempt + 1,
                    'retry_in_seconds': TRANSCRIPT_RETRY_DELAY_SECONDS,
                    'reason': shorten_error(exc),
                },
            )
            time.sleep(TRANSCRIPT_RETRY_DELAY_SECONDS)

    if last_exc:
        raise last_exc
    raise RuntimeError('Unexpected summarizer retry flow without a result')


def write_entry(entry: dict, transcript: str, send_telegram: bool, update_last_processed: bool) -> None:
    git_pull_rebase_if_configured()
    log = load_log()
    if any(existing.get('video_id') == entry['video_id'] for existing in log):
        print(f"[summarizer] Entry for {entry['video_id']} already exists. Skipping write.")
        return

    if send_telegram:
        print('[summarizer] Sending message to Telegram...')
        send_telegram_message(entry['message'], video_id=entry.get('video_id', ''))

    log.append(entry)
    ANALYSES_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')
    save_transcript(entry['video_id'], transcript)
    print('[summarizer] Entry appended to analyses_log.json')

    if update_last_processed:
        save_last_processed_id(entry['video_id'])


def backfill_video(video_id: str) -> None:
    print(f'[summarizer] Backfill mode for {video_id}')
    entry, transcript = build_summary_entry(video_id)
    write_entry(entry, transcript, send_telegram=False, update_last_processed=False)
    print('[summarizer] Backfill done.')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description='Beecthor phone summarizer')
    parser.add_argument('--video-id', help='Specific YouTube video ID to process')
    parser.add_argument('--backfill', action='store_true', help='Store summary in repo without Telegram send or last_video update')
    args = parser.parse_args()

    print(f'[summarizer] {now_utc()}')
    send_server_log('phone.summarizer', 'run_started', 'Summarizer run started', payload={'backfill': args.backfill, 'video_id': args.video_id or ''})

    if args.video_id:
        video_id = args.video_id.strip()
        print(f'[summarizer] Using explicit video ID: {video_id}')
    else:
        print('[summarizer] Fetching latest Beecthor video ID...')
        video_id = get_latest_video_id(BEECTHOR_CHANNEL_ID)
    print(f'[summarizer] Latest video: {video_id}')

    if not args.backfill and video_id == load_last_processed_id():
        print(f'[summarizer] Already processed {video_id}. Nothing to do.')
        send_server_log('phone.summarizer', 'run_skipped', 'Latest video already processed', payload={'video_id': video_id})
        return

    if args.backfill:
        backfill_video(video_id)
        send_server_log('phone.summarizer', 'backfill_completed', 'Backfill stored without Telegram send', payload={'video_id': video_id})
        return

    entry, transcript, attempts = build_summary_entry_with_retry(video_id)
    write_entry(entry, transcript, send_telegram=True, update_last_processed=True)
    if attempts > 1:
        send_server_log(
            'phone.summarizer',
            'retry_succeeded',
            'Transcript retry succeeded; daily summary stored and sent to Telegram',
            payload={'video_id': video_id, 'robot_score': entry['robot_score'], 'attempts': attempts},
        )
    else:
        send_server_log('phone.summarizer', 'summary_stored', 'Daily summary stored and sent to Telegram', payload={'video_id': video_id, 'robot_score': entry['robot_score'], 'attempts': attempts})

    print('[summarizer] Committing and pushing...')
    git_commit_and_push(video_id, transcript)
    print('[summarizer] Done.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        try:
            send_telegram_message(f'❌ Beecthor summarizer failed:\n{exc}')
        except Exception:
            pass
        send_server_log('phone.summarizer', 'run_failed', f'Unhandled exception: {exc}', level='error')
        sys.exit(1)
