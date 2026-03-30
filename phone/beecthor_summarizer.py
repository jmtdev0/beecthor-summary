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
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV_FILE = Path.home() / '.polymarket.env'
REPO_DIR = Path.home() / 'beecthor-summary'
ANALYSES_LOG = REPO_DIR / 'analyses_log.json'
TRANSCRIPTS_DIR = REPO_DIR / 'transcripts'
LAST_PROCESSED_FILE = Path.home() / '.beecthor_last_processed_video_id'

BEECTHOR_CHANNEL_ID = 'UCO5MrB8OoQ_nRzeB_ehPbFw'  # youtube.com/@Beecthor
BINANCE_TICKER_URL = 'https://api.binance.com/api/v3/ticker/price'
COPILOT_MODEL = 'gpt-5.4'
NUM_EXAMPLES = 2  # entries from analyses_log used as format examples

load_dotenv(ENV_FILE)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_PERSONAL_CHAT_ID', '')
GH_TOKEN = os.environ.get('GH_TOKEN', '')


def now_utc() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'HTML'},
            timeout=15,
        )
    except Exception:
        pass


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
    api = YouTubeTranscriptApi()
    # Try Spanish first (Beecthor's native language), fall back to any available
    try:
        fetched = api.fetch(video_id, languages=['es', 'es-ES'])
    except Exception:
        fetched = api.fetch(video_id)
    return ' '.join(s.text for s in fetched)


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
- The 🧭 Visión macro section summarizing the medium/long-term bias
- The 📌 Resumen section: 2-3 direct lines with the key trade idea
- The full detailed analysis inside <tg-spoiler>
- Writing style: concise, uses <b> for key price levels and concepts, in Spanish

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
    result = subprocess.run(
        ['copilot', '-p', prompt, '--model', COPILOT_MODEL, '-s', '--allow-all', '--no-ask-user'],
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

def ensure_git_credentials() -> None:
    if not GH_TOKEN:
        raise RuntimeError('GH_TOKEN not set — cannot push to GitHub')
    cred_file = Path.home() / '.git-credentials'
    cred_line = f'https://x-access-token:{GH_TOKEN}@github.com\n'
    existing = cred_file.read_text() if cred_file.exists() else ''
    if 'github.com' not in existing:
        with open(cred_file, 'a') as f:
            f.write(cred_line)
    subprocess.run(
        ['git', 'config', '--global', 'credential.helper', 'store'],
        check=True, capture_output=True,
    )


def git_commit_and_push(video_id: str, transcript: str) -> None:
    ensure_git_credentials()

    TRANSCRIPTS_DIR.mkdir(exist_ok=True)
    date_str = datetime.now(UTC).strftime('%Y-%m-%d')
    transcript_path = TRANSCRIPTS_DIR / f'{video_id}_{date_str}.txt'
    transcript_path.write_text(transcript, encoding='utf-8')

    subprocess.run(
        ['git', '-C', str(REPO_DIR), 'pull', '--rebase', 'origin', 'main'],
        check=True, capture_output=True,
    )
    subprocess.run(
        ['git', '-C', str(REPO_DIR), 'add', str(ANALYSES_LOG), str(transcript_path)],
        check=True,
    )
    subprocess.run(
        ['git', '-C', str(REPO_DIR), '-c', 'user.name=beecthor-summarizer[bot]',
         '-c', 'user.email=beecthor-summarizer[bot]@users.noreply.github.com',
         'commit', '-m', f'feat: Beecthor summary {video_id} ({date_str})'],
        check=True, capture_output=True,
    )
    subprocess.run(
        ['git', '-C', str(REPO_DIR), 'push', 'origin', 'main'],
        check=True, capture_output=True,
    )


def load_last_processed_id() -> str:
    try:
        return LAST_PROCESSED_FILE.read_text().strip()
    except Exception:
        return ''


def save_last_processed_id(video_id: str) -> None:
    LAST_PROCESSED_FILE.write_text(video_id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f'[summarizer] {now_utc()}')

    print('[summarizer] Fetching latest Beecthor video ID...')
    video_id = get_latest_video_id(BEECTHOR_CHANNEL_ID)
    print(f'[summarizer] Latest video: {video_id}')

    if video_id == load_last_processed_id():
        print(f'[summarizer] Already processed {video_id}. Nothing to do.')
        return

    print('[summarizer] Downloading transcript...')
    transcript = get_transcript(video_id)
    print(f'[summarizer] Transcript length: {len(transcript)} chars')

    print('[summarizer] Fetching current prices...')
    prices = get_prices()
    print(f'[summarizer] BTC ${prices["btc_usd"]} / €{prices["btc_eur"]} | SOL ${prices["sol_usd"]}')

    log = json.loads(ANALYSES_LOG.read_text(encoding='utf-8')) if ANALYSES_LOG.exists() else []
    examples = log[-NUM_EXAMPLES:] if len(log) >= NUM_EXAMPLES else log
    prev = log[-1] if log else {}
    prev_prices = {k: prev.get(k) for k in ('btc_usd', 'btc_eur', 'sol_usd', 'sol_eur')}

    print(f'[summarizer] Calling Copilot ({COPILOT_MODEL})...')
    prompt = build_prompt(transcript, examples, prices, prev_prices, video_id)
    result = run_copilot(prompt)

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

    log.append(entry)
    ANALYSES_LOG.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding='utf-8')
    print('[summarizer] Entry appended to analyses_log.json')

    print('[summarizer] Committing and pushing...')
    git_commit_and_push(video_id, transcript)
    save_last_processed_id(video_id)
    print('[summarizer] Done.')

    send_telegram(entry['message'])
    print('[summarizer] Telegram notification sent.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        send_telegram(f'❌ Beecthor summarizer failed:\n{exc}')
        sys.exit(1)
