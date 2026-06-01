#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

HistoryLoader = Callable[[], list[dict[str, Any]]]
HistorySaver = Callable[[list[dict[str, Any]]], None]
EventLogger = Callable[[str, str, str, str, dict[str, Any] | None], Any]

BRIDGE_DIR = Path(os.environ.get('CODEX_CLI_BRIDGE_DIR') or os.environ.get('CODEX_CHAT_BRIDGE_DIR', '/var/lib/codex-cli-bridge'))
BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
SESSION_STATE_PATH = Path(os.environ.get('CODEX_CLI_BRIDGE_SESSION_STATE') or (BRIDGE_DIR / 'session.json'))
CODEX_CLI = os.environ.get('CODEX_CLI', '/usr/bin/codex')
CODEX_WORKDIR = Path(os.environ.get('CODEX_CLI_BRIDGE_WORKDIR', '/root'))
CODEX_MODEL = os.environ.get('CODEX_CLI_BRIDGE_MODEL', 'gpt-5.5')
CODEX_REASONING_EFFORT = os.environ.get('CODEX_CLI_BRIDGE_REASONING_EFFORT', 'xhigh')
BRIDGE_TIMEOUT_SECONDS = int(os.environ.get('CODEX_CHAT_BRIDGE_TIMEOUT_SECONDS', '600'))
BRIDGE_STALE_SECONDS = int(os.environ.get('CODEX_CHAT_BRIDGE_STALE_SECONDS', '1800'))
BRIDGE_POLL_INTERVAL_MS = int(os.environ.get('CODEX_CHAT_BRIDGE_POLL_INTERVAL_MS', '1500'))

_WORKER_LOCK = threading.Lock()


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
        'log': BRIDGE_DIR / f'codex_{request_id}.log',
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


def load_session_state() -> dict[str, Any]:
    state = load_json(SESSION_STATE_PATH, {})
    return state if isinstance(state, dict) else {}


def save_session_state(state: dict[str, Any]) -> None:
    state['updated_at'] = utc_now()
    save_json(SESSION_STATE_PATH, state)


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


def build_bridge_prompt(message: str, request_id: str, source_label: str = '/private/chat') -> str:
    return f"""[codex-cli-bridge request_id={request_id} source={source_label}]

This prompt comes from Javier through {source_label}. Treat it as part of the same long-running server-side Codex conversation.

Operational context:
- You are running on Javier's VPS through Codex CLI.
- Your working root is /root, so you can inspect beecthor-summary, beecthor-perps, and other cloned repositories.
- When a request targets a repository, read its AGENTS.md or doc/AGENTS.md before changing behavior.
- You may use the full power of Codex CLI for Javier's requests. Be careful with destructive operations and explain important results clearly.
- Reply in the user's language unless the user asks otherwise.

User message:
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
            text = reply_path.read_text(encoding='utf-8', errors='replace').strip()
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
                    message='Bridge response captured from Codex CLI',
                )
                continue
        if meta.get('status') == 'pending' and age_seconds(meta.get('created_at', '')) > BRIDGE_TIMEOUT_SECONDS:
            finalize_request(
                meta,
                status='timeout',
                response_text='(timeout - Codex CLI did not produce a reply in time)',
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


def parse_session_id(output: str) -> str:
    match = re.search(r'session id:\s*([0-9a-fA-F-]{16,})', output or '')
    return match.group(1) if match else ''


def completed_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
    def as_text(value: str | bytes | None) -> str:
        if value is None:
            return ''
        if isinstance(value, bytes):
            return value.decode('utf-8', errors='replace')
        return value

    return (as_text(stdout) + '\n' + as_text(stderr)).strip()


def codex_command(session_id: str, reply_file: Path) -> list[str]:
    common = [
        '--dangerously-bypass-approvals-and-sandbox',
        '--skip-git-repo-check',
        '--model',
        CODEX_MODEL,
        '-c',
        f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
        '--output-last-message',
        str(reply_file),
    ]
    if session_id:
        return [CODEX_CLI, 'exec', 'resume', *common, session_id, '-']
    return [CODEX_CLI, 'exec', *common, '-C', str(CODEX_WORKDIR), '-']


def run_codex_worker(
    request_id: str,
    *,
    history_loader: HistoryLoader,
    history_saver: HistorySaver,
    logger: EventLogger | None = None,
) -> None:
    with _WORKER_LOCK:
        meta = load_request_meta(request_id)
        if not meta or meta.get('status') != 'pending':
            return
        paths = request_paths(request_id)
        session_state = load_session_state()
        session_id = str(session_state.get('session_id') or '')
        cmd = codex_command(session_id, paths['reply'])
        meta['codex_command_mode'] = 'resume' if session_id else 'new'
        meta['codex_session_id'] = session_id
        save_request_meta(meta)
        if logger:
            logger(
                'app.chat',
                'bridge_cli_started',
                'info',
                'Codex CLI bridge request started',
                {'request_id': request_id, 'mode': meta['codex_command_mode'], 'workdir': str(CODEX_WORKDIR), 'model': CODEX_MODEL},
            )
        try:
            prompt_text = paths['prompt'].read_text(encoding='utf-8')
            result = subprocess.run(
                cmd,
                input=prompt_text,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=BRIDGE_TIMEOUT_SECONDS,
                cwd=str(CODEX_WORKDIR),
                env={**os.environ, 'HOME': os.environ.get('HOME', str(Path.home())), 'LANG': os.environ.get('LANG', 'en_US.UTF-8'), 'PYTHONIOENCODING': 'utf-8'},
                check=False,
            )
        except FileNotFoundError:
            finalize_request(
                meta,
                status='failed',
                response_text='(error - Codex CLI was not found on the server)',
                timestamp=history_timestamp(),
                history_loader=history_loader,
                history_saver=history_saver,
                logger=logger,
                event_type='bridge_cli_missing',
                level='error',
                message='Codex CLI bridge executable not found',
            )
            return
        except subprocess.TimeoutExpired as exc:
            paths['log'].write_text(completed_output(exc.stdout, exc.stderr), encoding='utf-8')
            finalize_request(
                meta,
                status='timeout',
                response_text='(timeout - Codex CLI did not finish in time)',
                timestamp=history_timestamp(),
                history_loader=history_loader,
                history_saver=history_saver,
                logger=logger,
                event_type='bridge_cli_timeout',
                level='warning',
                message='Codex CLI bridge request timed out',
            )
            return

        combined_output = completed_output(result.stdout, result.stderr)
        paths['log'].write_text(combined_output + ('\n' if combined_output else ''), encoding='utf-8')
        new_session_id = parse_session_id(combined_output)
        if new_session_id:
            session_state.update({
                'session_id': new_session_id,
                'created_at': session_state.get('created_at') or utc_now(),
                'last_request_id': request_id,
                'workdir': str(CODEX_WORKDIR),
                'model': CODEX_MODEL,
                'reasoning_effort': CODEX_REASONING_EFFORT,
            })
            save_session_state(session_state)
            meta['codex_session_id'] = new_session_id

        if result.returncode != 0:
            error_text = combined_output[-2000:] or f'Codex CLI exited with {result.returncode}'
            finalize_request(
                meta,
                status='failed',
                response_text=f'(error - Codex CLI failed: {error_text})',
                timestamp=history_timestamp(),
                history_loader=history_loader,
                history_saver=history_saver,
                logger=logger,
                event_type='bridge_cli_failed',
                level='error',
                message='Codex CLI bridge returned a non-zero exit code',
            )
            return

        response_text = ''
        if paths['reply'].exists():
            response_text = paths['reply'].read_text(encoding='utf-8', errors='replace').strip()
        if not response_text:
            response_text = combined_output.strip()
        if not response_text:
            response_text = '(sin respuesta)'
        finalize_request(
            meta,
            status='completed',
            response_text=response_text,
            timestamp=history_timestamp(),
            history_loader=history_loader,
            history_saver=history_saver,
            logger=logger,
            event_type='bridge_cli_completed',
            level='info',
            message='Codex CLI bridge request completed',
        )


def start_bridge_request(
    message: str,
    *,
    history_loader: HistoryLoader,
    history_saver: HistorySaver,
    logger: EventLogger | None = None,
    source_label: str = '/private/chat',
) -> tuple[dict[str, Any] | None, str | None]:
    reconcile_bridge_requests(history_loader, history_saver, logger)
    prune_stale_bridge_files()
    active = active_request_meta()
    if active:
        return None, 'Codex bridge busy - wait for the current reply to finish.'

    request_id = f'bridge-{datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")}-{uuid4().hex[:8]}'
    paths = request_paths(request_id)
    prompt = build_bridge_prompt(message, request_id, source_label=source_label)
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
        'log_file': str(paths['log']),
        'source_label': source_label,
        'history_saved': False,
        'bridge_backend': 'codex_cli',
    }
    save_request_meta(meta)

    thread = threading.Thread(
        target=run_codex_worker,
        kwargs={'request_id': request_id, 'history_loader': history_loader, 'history_saver': history_saver, 'logger': logger},
        name=f'codex-cli-bridge-{request_id}',
        daemon=True,
    )
    thread.start()
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
