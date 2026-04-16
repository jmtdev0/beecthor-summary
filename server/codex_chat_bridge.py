#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

HistoryLoader = Callable[[], list[dict[str, Any]]]
HistorySaver = Callable[[list[dict[str, Any]]], None]
EventLogger = Callable[[str, str, str, str, dict[str, Any] | None], Any]

BRIDGE_DIR = Path(os.environ.get('CODEX_CHAT_BRIDGE_DIR', '/var/lib/codex-chat-bridge'))
BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
VSCODE_CHAT_SEND_SCRIPT = Path(os.environ.get('CODEX_CHAT_SEND_SCRIPT', '/root/scripts/vscode_chat_send.sh'))
BRIDGE_REPLY_WRITER = Path(os.environ.get('CODEX_BRIDGE_REPLY_WRITER', '/root/scripts/codex_bridge_write_reply.sh'))
BRIDGE_TIMEOUT_SECONDS = int(os.environ.get('CODEX_CHAT_BRIDGE_TIMEOUT_SECONDS', '150'))
BRIDGE_STALE_SECONDS = int(os.environ.get('CODEX_CHAT_BRIDGE_STALE_SECONDS', '1800'))
BRIDGE_POLL_INTERVAL_MS = int(os.environ.get('CODEX_CHAT_BRIDGE_POLL_INTERVAL_MS', '1500'))
BRIDGE_SEND_TIMEOUT_SECONDS = int(os.environ.get('CODEX_CHAT_BRIDGE_SEND_TIMEOUT_SECONDS', '90'))


def utc_now() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def history_timestamp() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def request_paths(request_id: str) -> dict[str, Path]:
    return {
        'prompt': BRIDGE_DIR / f'prompt_{request_id}.txt',
        'reply': BRIDGE_DIR / f'reply_{request_id}.md',
        'meta': BRIDGE_DIR / f'request_{request_id}.json',
    }


def load_request_meta(request_id: str) -> dict[str, Any] | None:
    meta_path = request_paths(request_id)['meta']
    if not meta_path.exists():
        return None
    return load_json(meta_path, None)


def save_request_meta(meta: dict[str, Any]) -> None:
    meta['updated_at'] = utc_now()
    save_json(request_paths(meta['request_id'])['meta'], meta)


def iter_request_meta() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(BRIDGE_DIR.glob('request_*.json')):
        payload = load_json(path, None)
        if isinstance(payload, dict):
            items.append(payload)
    items.sort(key=lambda item: item.get('created_at', ''), reverse=True)
    return items


def parse_iso_utc(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=UTC)
    except Exception:
        return None


def age_seconds(timestamp: str) -> int:
    dt = parse_iso_utc(timestamp)
    if not dt:
        return BRIDGE_STALE_SECONDS + 1
    return int((datetime.now(UTC) - dt).total_seconds())


def active_request_meta() -> dict[str, Any] | None:
    for meta in iter_request_meta():
        if meta.get('status') == 'pending' and age_seconds(meta.get('created_at', '')) <= BRIDGE_TIMEOUT_SECONDS:
            return meta
    return None


def build_bridge_prompt(message: str, request_id: str, reply_file: Path) -> str:
    return f"""[webchat request_id={request_id} reply_file={reply_file}]

This message comes from /private/chat and should be treated as part of the same ongoing conversation with Javier.
Reply normally in this VS Code conversation, and also write the same final user-facing answer as plain UTF-8 text to reply_file.
If useful, you can write it with this helper:
{BRIDGE_REPLY_WRITER} {reply_file} <<'EOF'
<your final answer here>
EOF

{message}
"""


def history_has_response(history: list[dict[str, Any]], request_id: str) -> bool:
    return any(item.get('bridge_request_id') == request_id and item.get('role') != 'user' for item in history)


def append_response_to_history(
    request_id: str,
    text: str,
    timestamp: str,
    history_loader: HistoryLoader,
    history_saver: HistorySaver,
) -> None:
    history = history_loader()
    if history_has_response(history, request_id):
        return
    history.append({
        'role': 'codex',
        'text': text,
        'timestamp': timestamp,
        'bridge_request_id': request_id,
    })
    history_saver(history)


def finalize_request(
    meta: dict[str, Any],
    *,
    status: str,
    response_text: str,
    timestamp: str,
    history_loader: HistoryLoader,
    history_saver: HistorySaver,
    logger: EventLogger | None = None,
    event_type: str = 'bridge_completed',
    level: str = 'info',
    message: str = 'Bridge request completed',
) -> dict[str, Any]:
    append_response_to_history(meta['request_id'], response_text, timestamp, history_loader, history_saver)
    meta['status'] = status
    meta['response_timestamp'] = timestamp
    meta['response_text'] = response_text
    meta['history_saved'] = True
    save_request_meta(meta)
    if logger:
        logger('app.chat', event_type, level, message, {'request_id': meta['request_id'], 'status': status})
    return meta


def reconcile_bridge_requests(
    history_loader: HistoryLoader,
    history_saver: HistorySaver,
    logger: EventLogger | None = None,
) -> None:
    for meta in iter_request_meta():
        if meta.get('status') in {'completed', 'failed', 'timeout'} and meta.get('history_saved'):
            continue
        reply_path = Path(meta.get('reply_file') or request_paths(meta['request_id'])['reply'])
        if reply_path.exists():
            text = reply_path.read_text(encoding='utf-8').strip()
            if text:
                finalize_request(
                    meta,
                    status='completed',
                    response_text=text,
                    timestamp=history_timestamp(),
                    history_loader=history_loader,
                    history_saver=history_saver,
                    logger=logger,
                    event_type='bridge_completed',
                    level='info',
                    message='Bridge response captured from Codex session',
                )
                continue
        if meta.get('status') == 'pending' and age_seconds(meta.get('created_at', '')) > BRIDGE_TIMEOUT_SECONDS:
            finalize_request(
                meta,
                status='timeout',
                response_text='(timeout — Codex bridge did not produce a reply file in time)',
                timestamp=history_timestamp(),
                history_loader=history_loader,
                history_saver=history_saver,
                logger=logger,
                event_type='bridge_timeout',
                level='warning',
                message='Bridge request timed out',
            )


def prune_stale_bridge_files() -> None:
    for meta in iter_request_meta():
        if age_seconds(meta.get('created_at', '')) <= BRIDGE_STALE_SECONDS:
            continue
        paths = request_paths(meta['request_id'])
        for path in paths.values():
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass


def start_bridge_request(
    message: str,
    *,
    history_loader: HistoryLoader,
    history_saver: HistorySaver,
    logger: EventLogger | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    reconcile_bridge_requests(history_loader, history_saver, logger)
    prune_stale_bridge_files()
    active = active_request_meta()
    if active:
        return None, 'Codex bridge busy — wait for the current reply to finish.'

    request_id = f'bridge-{datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")}-{uuid4().hex[:8]}'
    paths = request_paths(request_id)
    prompt = build_bridge_prompt(message, request_id, paths['reply'])
    paths['prompt'].write_text(prompt, encoding='utf-8')

    timestamp = history_timestamp()
    history = history_loader()
    history.append({
        'role': 'user',
        'text': message,
        'timestamp': timestamp,
        'bridge_request_id': request_id,
    })
    history_saver(history)

    meta = {
        'request_id': request_id,
        'status': 'pending',
        'created_at': utc_now(),
        'updated_at': utc_now(),
        'user_message': message,
        'user_timestamp': timestamp,
        'prompt_file': str(paths['prompt']),
        'reply_file': str(paths['reply']),
        'history_saved': False,
    }
    save_request_meta(meta)

    try:
        result = subprocess.run(
            [str(VSCODE_CHAT_SEND_SCRIPT), '--file', str(paths['prompt'])],
            capture_output=True,
            text=True,
            timeout=BRIDGE_SEND_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        meta = finalize_request(
            meta,
            status='failed',
            response_text='(error — bridge sender script not found)',
            timestamp=history_timestamp(),
            history_loader=history_loader,
            history_saver=history_saver,
            logger=logger,
            event_type='bridge_send_failed',
            level='error',
            message='Bridge sender script not found',
        )
        return meta, None
    except subprocess.TimeoutExpired:
        meta = finalize_request(
            meta,
            status='failed',
            response_text='(error — timed out while sending the message to the VS Code Codex session)',
            timestamp=history_timestamp(),
            history_loader=history_loader,
            history_saver=history_saver,
            logger=logger,
            event_type='bridge_send_timeout',
            level='error',
            message='Bridge sender script timed out',
        )
        return meta, None

    if result.returncode != 0:
        error_text = result.stderr.strip() or result.stdout.strip() or '(unknown bridge sender error)'
        meta = finalize_request(
            meta,
            status='failed',
            response_text=f'(error — could not deliver the message to the VS Code Codex session: {error_text})',
            timestamp=history_timestamp(),
            history_loader=history_loader,
            history_saver=history_saver,
            logger=logger,
            event_type='bridge_send_failed',
            level='error',
            message='Bridge sender returned a non-zero exit code',
        )
        return meta, None

    if logger:
        logger('app.chat', 'bridge_sent', 'info', 'Bridge message sent to VS Code Codex session', {'request_id': request_id})
    return meta, None


def bridge_request_status(
    request_id: str,
    *,
    history_loader: HistoryLoader,
    history_saver: HistorySaver,
    logger: EventLogger | None = None,
) -> tuple[dict[str, Any], int]:
    reconcile_bridge_requests(history_loader, history_saver, logger)
    meta = load_request_meta(request_id)
    if not meta:
        return {'error': 'Bridge request not found'}, 404

    status = meta.get('status')
    if status == 'pending':
        return {'status': 'pending', 'poll_after_ms': BRIDGE_POLL_INTERVAL_MS}, 200
    if status == 'completed':
        return {
            'status': 'completed',
            'response': meta.get('response_text', ''),
            'timestamp': meta.get('response_timestamp', history_timestamp()),
        }, 200
    return {
        'status': status or 'failed',
        'response': meta.get('response_text', '(bridge request failed)'),
        'timestamp': meta.get('response_timestamp', history_timestamp()),
    }, 200
