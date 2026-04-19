#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

_CET = ZoneInfo('Europe/Madrid')
from functools import wraps
from pathlib import Path
from typing import Any

import requests
from codex_chat_bridge import (
    bridge_request_status as get_bridge_request_status,
    reconcile_bridge_requests,
    start_bridge_request,
)
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, redirect, render_template_string, request, session, url_for

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds, AssetType, BalanceAllowanceParams
except ImportError:  # pragma: no cover - optional at runtime
    ClobClient = None
    ApiCreds = None
    AssetType = None
    BalanceAllowanceParams = None

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / 'polymarket_assistant' / '.env'
HISTORY_FILE = Path(__file__).resolve().parent / 'copilot_chat_history.json'
ANALYSES_LOG_PATH = REPO_ROOT / 'analyses_log.json'
ACCOUNT_STATE_PATH = REPO_ROOT / 'polymarket_assistant' / 'account_state.json'
TRADE_LOG_PATH = REPO_ROOT / 'polymarket_assistant' / 'trade_log.json'
PENDING_ORDERS_PATH = REPO_ROOT / 'polymarket_assistant' / 'pending_orders.json'

load_dotenv(ENV_FILE)

CHAT_PASSWORD = os.environ.get('COPILOT_CHAT_PASSWORD', '')
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change-me-in-env')
MOBILE_LOG_API_SECRET = os.environ.get('MOBILE_LOG_API_SECRET', '')
POLY_FUNDER = os.environ.get('POLY_FUNDER', '')
POLY_SIGNER_ADDRESS = os.environ.get('POLY_SIGNER_ADDRESS', '')
POLY_PRIVATE_KEY = os.environ.get('POLY_PRIVATE_KEY', '')
POLY_API_KEY = os.environ.get('POLY_API_KEY', '')
POLY_API_SECRET = os.environ.get('POLY_API_SECRET', '')
POLY_API_PASSPHRASE = os.environ.get('POLY_API_PASSPHRASE', '')
POLY_SIGNATURE_TYPE = int(os.environ.get('POLY_SIGNATURE_TYPE', '1'))
DATA_API_HOST = 'https://data-api.polymarket.com'
CLOB_HOST = 'https://clob.polymarket.com'
CHAIN_ID = 137
LOG_DIR = Path(os.environ.get('DASHBOARD_LOG_DIR') or (REPO_ROOT / 'server_runtime_logs'))
LOG_DIR.mkdir(parents=True, exist_ok=True)
TRACE_LANE_LIMIT = 5
PRIVATE_CHAT_VSCODE_DISPLAY = os.environ.get('PRIVATE_CHAT_VSCODE_DISPLAY', ':10')
PRIVATE_CHAT_VSCODE_XAUTHORITY = os.environ.get(
    'PRIVATE_CHAT_VSCODE_XAUTHORITY',
    str(Path.home() / '.Xauthority'),
)
PRIVATE_CHAT_VSCODE_CAPTURE_BIN = os.environ.get('PRIVATE_CHAT_VSCODE_CAPTURE_BIN', 'import')
PRIVATE_CHAT_VSCODE_CAPTURE_TIMEOUT_SECONDS = float(
    os.environ.get('PRIVATE_CHAT_VSCODE_CAPTURE_TIMEOUT_SECONDS', '8')
)

app = Flask(__name__)
app.secret_key = SECRET_KEY

STYLE = """
<style>
:root{
  --bg:#0f0f0f;
  --surface:#181818;
  --surface-soft:#212121;
  --surface-strong:#111827;
  --border:#2d2d2d;
  --muted:#aaaaaa;
  --text:#f1f5f9;
  --blue:#3ea6ff;
  --green:#22c55e;
  --red:#ef4444;
  --amber:#f59e0b;
  --shadow:0 14px 40px rgba(0,0,0,.28);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
html{-webkit-text-size-adjust:100%}
body{
  font-family:Roboto,"Segoe UI",Arial,sans-serif;
  background:
    radial-gradient(circle at top left, rgba(62,166,255,.09), transparent 28%),
    radial-gradient(circle at top right, rgba(34,197,94,.06), transparent 24%),
    linear-gradient(180deg,#0b0b0c 0%, #111315 100%);
  color:var(--text);
}
a{color:inherit;text-decoration:none}
img{display:block;max-width:100%}
.shell{max-width:1380px;margin:0 auto;padding:0 24px 40px}
.public-shell{max-width:1520px}
.top{
  display:flex;justify-content:space-between;gap:20px;align-items:flex-end;
  padding:26px 0 18px;border-bottom:1px solid rgba(255,255,255,.08);margin-bottom:24px
}
.brand-title{font-size:2.2rem;line-height:1;font-weight:800;letter-spacing:-.04em;margin:0}
.section-subtitle,.muted{color:var(--muted)}
.muted a{color:var(--muted)}
.nav{display:flex;gap:18px;flex-wrap:wrap;align-items:center}
.nav-group{display:flex;gap:18px;flex-wrap:wrap;align-items:center;justify-content:flex-end}
.nav a{color:#d7dee7;font-weight:500}
.nav a:hover{color:#fff}
.video-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(295px,1fr));gap:26px 18px}
.video-card{display:block}
.video-link{display:block}
.thumb-wrap{
  position:relative;overflow:hidden;border-radius:18px;background:#000;
  box-shadow:0 0 0 1px rgba(255,255,255,.08);
  aspect-ratio:16/9;transform:translateY(0);transition:transform .18s ease, box-shadow .18s ease
}
.thumb-wrap img{width:100%;height:100%;object-fit:cover;transition:transform .35s ease}
.video-card:hover .thumb-wrap{transform:translateY(-4px);box-shadow:0 18px 42px rgba(0,0,0,.42),0 0 0 1px rgba(255,255,255,.14)}
.video-card:hover .thumb-wrap img{transform:scale(1.05)}
.video-meta{display:grid;grid-template-columns:1fr;gap:8px;padding-top:12px}
.video-title{
  font-size:1.16rem;line-height:1.35;font-weight:700;color:#f8fafc;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden
}
.video-date{font-size:.95rem;color:#9ca3af}
.detail-layout{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(320px,.85fr);gap:28px;align-items:start}
.detail-media,.detail-panel,.surface-card,.metric-card,.stream-card,.chat-card{
  background:linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.02));
  border:1px solid rgba(255,255,255,.08);
  border-radius:22px;
  box-shadow:var(--shadow);
}
.detail-media{overflow:hidden}
.detail-media img{width:100%;aspect-ratio:16/9;object-fit:cover}
.detail-panel{padding:26px}
.detail-title{font-size:2.15rem;line-height:1.05;font-weight:800;letter-spacing:-.04em;margin:0 0 10px}
.detail-actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px}
.detail-summary-card{margin-top:22px;padding:22px 24px}
.detail-summary-label{font-size:.82rem;letter-spacing:.06em;text-transform:uppercase;color:#8fb9ff;font-weight:800;margin-bottom:10px}
.detail-summary-text{font-size:1.08rem;line-height:1.72;color:#eef4ff}
.detail-section-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:18px}
.detail-section-card{
  padding:20px 22px;
  background:linear-gradient(180deg, rgba(255,255,255,.04), rgba(255,255,255,.02));
  border:1px solid rgba(255,255,255,.08);
  border-radius:22px;
  box-shadow:var(--shadow);
}
.detail-section-head{display:flex;align-items:center;gap:10px;margin-bottom:12px}
.detail-section-icon{font-size:1.15rem;line-height:1}
.detail-section-title{font-size:1.15rem;font-weight:800;line-height:1.2}
.detail-section-body{font-size:1rem;line-height:1.72;color:#dce6f5}
.detail-section-body b{color:#fff}
.detail-section-body a{color:var(--blue)}
.detail-fallback{margin-top:18px;padding:22px 24px}
.detail-fallback .summary-body{padding:0}
.button-link,button{
  background:#1f6feb;color:#fff;border:none;border-radius:999px;padding:11px 16px;cursor:pointer;
  font-weight:700
}
.button-link.secondary{background:#22272d;color:#f3f4f6}
.summary-body{padding:26px 28px;font-size:1rem;line-height:1.68}
.summary-body b{color:#fff}
.summary-body a{color:var(--blue)}
.summary-body tg-spoiler,.summary-body .spoiler-fallback{
  display:block;margin-top:20px;padding:18px 20px;border-radius:16px;background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);color:#d6dfeb
}
.private-shell{max-width:1460px}
.private-header{display:flex;justify-content:space-between;gap:20px;align-items:center;padding:28px 0 22px}
.private-title{font-size:2.65rem;line-height:.95;font-weight:800;letter-spacing:-.05em;margin:0}
.private-strip{display:grid;grid-template-columns:1.15fr .95fr;gap:18px;margin-bottom:18px}
.metric-panel,.pnl-panel{
  background:linear-gradient(180deg,#111827 0%, #0f172a 100%);
  border:1px solid rgba(255,255,255,.06);
  border-radius:26px;padding:24px 26px;box-shadow:var(--shadow)
}
.metric-label{color:#b8c2d1;font-size:1.02rem}
.metric-value{font-size:3rem;line-height:1;font-weight:800;margin:8px 0}
.metric-foot{color:#9fb0c7}
.private-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-bottom:18px}
.metric-card{padding:22px}
.metric-card .big{font-size:2.25rem;line-height:1;font-weight:800;margin:8px 0 10px}
.good{color:var(--green)} .bad{color:var(--red)} .warn{color:var(--amber)}
.panel-grid{display:grid;grid-template-columns:1.2fr .8fr;gap:18px;margin-bottom:18px}
.stream-card,.surface-card,.chat-card{padding:22px}
.section-title{font-size:1.15rem;font-weight:800;margin:0 0 16px}
.position-list,.pipeline-list{display:flex;flex-direction:column;gap:12px}
.position-item,.pipeline-item{
  background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:18px;padding:16px
}
.trace-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-top:18px}
.trace-lane{
  background:linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.02));
  border:1px solid rgba(255,255,255,.08);
  border-radius:22px;
  padding:18px;
  min-height:320px;
}
.trace-lane-head{padding-bottom:14px;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:14px}
.trace-lane-title{font-size:1.04rem;font-weight:800;margin:0 0 4px}
.trace-lane-subtitle{font-size:.92rem;color:#93a0b4}
.trace-stack{display:flex;flex-direction:column;gap:12px}
.trace-entry{
  background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.06);
  border-radius:18px;
  padding:14px 14px 13px;
}
.trace-entry.info{border-color:rgba(62,166,255,.16)}
.trace-entry.warning{border-color:rgba(245,158,11,.2)}
.trace-entry.error{border-color:rgba(239,68,68,.24)}
.trace-time{font-size:.82rem;color:#8ea0ba;margin-bottom:6px}
.trace-eyebrow{font-size:.78rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:#7fb2ff;margin-bottom:6px}
.trace-entry.warning .trace-eyebrow{color:#f7bf57}
.trace-entry.error .trace-eyebrow{color:#ff8f8f}
.trace-title{font-size:.95rem;line-height:1.45;font-weight:600;color:#eef4ff}
.trace-meta{font-size:.84rem;line-height:1.45;color:#97a7bd;margin-top:8px}
.position-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
.position-market{font-weight:700;line-height:1.35}
.position-sub,.position-kv,.log-filter-note{color:#98a7bb}
.position-kv{margin-top:8px;font-size:.95rem}
.table{width:100%;border-collapse:collapse}
.table th,.table td{padding:12px 14px;border-bottom:1px solid rgba(255,255,255,.07);text-align:left;vertical-align:top}
.table th{font-size:.8rem;letter-spacing:.04em;text-transform:uppercase;color:#95a3b8}
.table-wrap{overflow:auto;border:1px solid rgba(255,255,255,.07);border-radius:18px}
.raw{background:#0a1018;border:1px solid rgba(255,255,255,.07);border-radius:18px;padding:16px;white-space:pre-wrap;max-height:360px;overflow:auto}
.log-controls{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
.log-controls input,.log-controls select,.chat-card textarea,input,select,textarea{
  background:#0d131d;color:#e7edf6;border:1px solid rgba(255,255,255,.09);border-radius:14px;padding:11px 13px
}
.log-controls input,.log-controls select{min-width:0}
.chat{display:flex;flex-direction:column;gap:12px;max-height:60dvh;overflow:auto}
.bubble{padding:14px 16px;border-radius:18px;white-space:pre-wrap}
.user{background:#0b57d0}
.bot{background:#111827;border:1px solid rgba(255,255,255,.08)}
.status-line{color:#9fb0c7;margin-top:10px}
.inline-controls{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.display-preview-shell{
    border:1px solid rgba(255,255,255,.07);
    border-radius:18px;
    overflow:hidden;
    background:#05070b;
}
.display-preview-image{
    width:100%;
    display:block;
    aspect-ratio:16/9;
    object-fit:contain;
    background:#05070b;
}
.position-open-item{
    font-size:.78rem;
    padding:12px;
    background:#1e1e1e;
    border:1px solid rgba(255,255,255,.05);
    border-radius:14px;
    display:flex;
    flex-direction:column;
    gap:10px;
}
.position-open-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
.position-open-info{min-width:0;display:flex;flex-direction:column;gap:6px;flex:1 1 auto}
.position-open-title{
    color:#ccc;
    overflow:hidden;
    display:-webkit-box;
    -webkit-line-clamp:2;
    -webkit-box-orient:vertical;
    line-height:1.35;
}
.position-open-meta{display:flex;flex-wrap:wrap;gap:6px 10px;color:#888}
.position-open-shares{color:#666}
.position-open-action{display:flex;justify-content:flex-end;flex-shrink:0}
.sell-trigger{
    width:auto;
    background:#2a3340;
    color:#fff;
    border:none;
    border-radius:999px;
    padding:7px 12px;
    cursor:pointer;
    font-weight:700;
    font-size:.72rem;
    white-space:nowrap;
}
.sell-modal-backdrop{
    position:fixed;
    inset:0;
    display:none;
    align-items:center;
    justify-content:center;
    padding:24px;
    background:rgba(4,6,9,.78);
    backdrop-filter:blur(10px);
    z-index:1000;
}
.sell-modal-backdrop.is-open{display:flex}
.sell-modal{
    width:min(520px, 100%);
    background:linear-gradient(180deg,#111827 0%, #0f172a 100%);
    border:1px solid rgba(255,255,255,.08);
    border-radius:24px;
    padding:24px;
    box-shadow:var(--shadow);
}
.sell-modal-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:14px}
.sell-modal-kicker{font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;color:#8fb9ff;font-weight:800;margin-bottom:8px}
.sell-modal-title{font-size:1.25rem;line-height:1.1;font-weight:800;margin:0}
.sell-modal-close{
    width:auto;
    background:transparent;
    color:#d7dee7;
    border:1px solid rgba(255,255,255,.14);
    padding:8px 12px;
}
.sell-modal-body{color:#dce6f5;font-size:.95rem;line-height:1.6}
.sell-modal-position{font-weight:700;color:#fff}
.sell-modal-stats{margin-top:8px;color:#9fb0c7}
.sell-option-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:18px}
.sell-option-form{margin:0}
.sell-option-button{
    width:100%;
    background:#2a3340;
    color:#fff;
    border:none;
    border-radius:16px;
    padding:14px 12px;
    font-weight:800;
    font-size:.9rem;
}
.sell-option-button.full{background:#8b1e2d}
.sell-modal-note{margin-top:14px;font-size:.84rem;color:#93a0b4}
@media (max-width: 1180px){
  .private-strip,.panel-grid,.detail-layout,.detail-section-grid{grid-template-columns:1fr}
}
@media (max-width: 960px){
  .private-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .trace-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width: 680px){
  .shell{padding:0 16px 28px}
  .top,.private-header{flex-direction:column;align-items:flex-start}
  .nav,.nav-group{width:100%;justify-content:flex-start;gap:12px}
  .nav a{padding:4px 0}
  .brand-title,.private-title{font-size:1.9rem}
  .video-grid{grid-template-columns:1fr}
  .private-grid{grid-template-columns:1fr}
  .trace-grid{grid-template-columns:1fr}
  .metric-value{font-size:2.35rem}
  .detail-title{font-size:1.7rem}
  .detail-panel,.detail-summary-card,.detail-section-card,.stream-card,.surface-card,.chat-card,.metric-card,.metric-panel,.pnl-panel,.trace-lane{padding:18px}
  .detail-actions{flex-direction:column;align-items:stretch}
  .button-link,button{width:100%;text-align:center}
  .table th,.table td{padding:10px 10px;font-size:.92rem}
  .summary-body{padding:18px 0 0}
  .raw{font-size:.9rem}
  .log-controls{flex-direction:column}
    .position-open-head{flex-direction:column}
    .position-open-action{width:100%}
    .sell-trigger{width:100%}
    .sell-option-grid{grid-template-columns:1fr}
    .sell-modal{padding:20px}
    .sell-modal-close{width:auto}
}
</style>
"""

def page_start(title: str) -> str:
    safe_title = (title or 'Beecthor').replace('{', '&#123;').replace('}', '&#125;')
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{safe_title}</title>{STYLE}</head><body>"
    )


PAGE_END = "</body></html>"

LOGIN_HTML = page_start('Login | Beecthor') + """
<div class="shell"><div class="card" style="max-width:360px;margin:10vh auto 0">
<h1>Zona privada</h1><p class="muted">Polymarket, logs y chat</p>
{% if error %}<p class="bad">{{ error }}</p>{% endif %}
<form method="POST"><input type="password" name="password" placeholder="Password" style="width:100%;margin:12px 0"><button style="width:100%">Entrar</button></form>
</div></div>""" + PAGE_END


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def save_history(history: list[dict[str, Any]]) -> None:
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def load_history() -> list[dict[str, Any]]:
    return load_json(HISTORY_FILE, [])


def visible_chat_history() -> list[dict[str, Any]]:
    history = load_history()
    bridge_items = [item for item in history if item.get('bridge_request_id')]
    return bridge_items if bridge_items else []


def utc_now() -> str:
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ''):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def require_private(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('login'))
        return view(*args, **kwargs)
    return wrapped


def log_file_for_source(source: str) -> Path:
    if source.startswith('phone.'):
        return LOG_DIR / 'mobile.jsonl'
    if source.startswith('api.'):
        return LOG_DIR / 'api.jsonl'
    return LOG_DIR / 'app.jsonl'


def append_jsonl_event(source: str, event_type: str, level: str, message: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    event = {'timestamp': utc_now(), 'source': source, 'event_type': event_type, 'level': level, 'message': message, 'payload': payload or {}}
    with log_file_for_source(source).open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')
    return event


def enqueue_pending_order(order: dict[str, Any]) -> None:
    queue: list[dict[str, Any]] = load_json(PENDING_ORDERS_PATH, [])
    cutoff = (datetime.now(UTC) - timedelta(hours=12)).strftime('%Y-%m-%dT%H:%M:%SZ')
    queue = [item for item in queue if item.get('order_id', '') >= cutoff]
    queue.append(order)
    save_json(PENDING_ORDERS_PATH, queue)


def active_manual_sell_order(market_slug: str, outcome: str) -> dict[str, Any] | None:
    pending_orders = load_json(PENDING_ORDERS_PATH, [])
    for order in pending_orders:
        if order.get('status') != 'pending_phone_execution':
            continue
        if order.get('side') != 'SELL':
            continue
        if order.get('market_slug') == market_slug and order.get('outcome') == outcome:
            return order
    return None


def build_manual_sell_feedback(status: str, market_slug: str, outcome: str, fraction: float = 1.0) -> dict[str, str] | None:
    if not status:
        return None
    label = f'{outcome} · {market_slug}' if market_slug else outcome
    percent_label = f'{round(fraction * 100):.0f}%'
    palette = {
        'queued': {
            'text': f'✓ SELL manual {percent_label} encolado para {label}. El executor del móvil se ha lanzado en background.',
            'bg': 'rgba(34,197,94,.12)',
            'border': 'rgba(34,197,94,.25)',
            'color': '#4ade80',
        },
        'duplicate': {
            'text': f'⚠ Ya había una orden SELL pendiente para {label}. No se ha duplicado.',
            'bg': 'rgba(245,158,11,.12)',
            'border': 'rgba(245,158,11,.24)',
            'color': '#fbbf24',
        },
        'missing': {
            'text': f'⚠ La posición {label} ya no aparece como abierta. Refresca el panel.',
            'bg': 'rgba(245,158,11,.12)',
            'border': 'rgba(245,158,11,.24)',
            'color': '#fbbf24',
        },
        'error': {
            'text': f'✗ No se pudo preparar la orden SELL para {label}. Revisa los logs.',
            'bg': 'rgba(239,68,68,.12)',
            'border': 'rgba(239,68,68,.24)',
            'color': '#f87171',
        },
        'invalid': {
            'text': f'⚠ Fracción SELL no válida para {label}. Usa 25%, 50%, 75% o 100%.',
            'bg': 'rgba(245,158,11,.12)',
            'border': 'rgba(245,158,11,.24)',
            'color': '#fbbf24',
        },
    }
    return palette.get(status)


def capture_private_chat_display() -> tuple[bytes | None, str | None]:
    env = os.environ.copy()
    env['DISPLAY'] = PRIVATE_CHAT_VSCODE_DISPLAY
    if PRIVATE_CHAT_VSCODE_XAUTHORITY:
        env['XAUTHORITY'] = PRIVATE_CHAT_VSCODE_XAUTHORITY

    try:
        result = subprocess.run(
            [PRIVATE_CHAT_VSCODE_CAPTURE_BIN, '-window', 'root', 'png:-'],
            capture_output=True,
            timeout=PRIVATE_CHAT_VSCODE_CAPTURE_TIMEOUT_SECONDS,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return None, 'Display capture tool not installed on the server'
    except subprocess.TimeoutExpired:
        return None, 'Display capture timed out'

    if result.returncode != 0:
        stderr = (result.stderr or b'').decode('utf-8', errors='replace').strip()
        return None, stderr or 'Display capture failed'
    if not result.stdout:
        return None, 'Display capture returned no image data'
    return result.stdout, None


def read_jsonl_logs(limit: int = 200, *, source: str = '', level: str = '', event_type: str = '') -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in sorted(LOG_DIR.glob('*.jsonl')):
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except Exception:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if source and item.get('source') != source:
                continue
            if level and item.get('level') != level:
                continue
            if event_type and item.get('event_type') != event_type:
                continue
            item['payload_preview'] = json.dumps(item.get('payload', {}), ensure_ascii=False)[:160]
            items.append(item)
    items.sort(key=lambda item: item.get('timestamp', ''), reverse=True)
    return items[:limit]


def humanize_event_type(value: str) -> str:
    return value.replace('_', ' ').strip().title()


def compact_payload(payload: dict[str, Any], keys: list[str]) -> str:
    parts = []
    for key in keys:
        value = payload.get(key)
        if value in (None, ''):
            continue
        parts.append(f'{key}: {value}')
    return ' · '.join(parts)


def build_mobile_trace_entries(source: str, limit: int, payload_keys: list[str] | None = None, allowed_events: set[str] | None = None) -> list[dict[str, str]]:
    payload_keys = payload_keys or []
    events = read_jsonl_logs(limit=limit * 4, source=source)
    items: list[dict[str, str]] = []
    for event in events:
        if allowed_events and event.get('event_type') not in allowed_events:
            continue
        payload = event.get('payload') or {}
        meta = compact_payload(payload, payload_keys)
        items.append({
            'timestamp': fmt_cet(event.get('timestamp', '')),
            'eyebrow': humanize_event_type(event.get('event_type', 'event')),
            'title': event.get('message', ''),
            'meta': meta,
            'tone': event.get('level', 'info'),
        })
        if len(items) >= limit:
            break
    return items


def classify_cycle_outcome(action: str, validation: dict[str, Any], execution: dict[str, Any]) -> tuple[str, str]:
    validation_ok = bool(validation.get('ok'))
    performed = bool(execution.get('performed'))
    if performed:
        return 'enqueued', 'warning' if action in {'OPEN_POSITION', 'REDUCE_POSITION', 'CLOSE_POSITION'} else 'info'
    if not validation_ok:
        return 'rejected', 'error'
    if action == 'NO_ACTION':
        return 'no action', 'info'
    return 'not executed', 'warning'


def extract_cycle_json(text: str) -> dict[str, Any] | None:
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def build_cycle_trace_entries(limit: int = 10) -> list[dict[str, str]]:
    cycle_dir = Path('/var/log/polymarket-operator')
    if not cycle_dir.exists():
        return []
    items: list[dict[str, str]] = []
    for path in sorted(cycle_dir.glob('cycle-*.log'), reverse=True)[:limit]:
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            continue
        payload = extract_cycle_json(text)
        if payload:
            decision = payload.get('decision') or {}
            validation = payload.get('validation') or {}
            execution = payload.get('execution') or {}
            raw_details = execution.get('details') or {}
            # details may be a list (multi-order) or a single dict
            if isinstance(raw_details, list):
                details = raw_details[0] if raw_details else {}
            else:
                details = raw_details
            action = decision.get('action', 'UNKNOWN')
            summary = decision.get('summary') or details.get('market') or 'Cycle completed'
            outcome_label, tone = classify_cycle_outcome(action, validation, execution)
            meta_parts = [
                f"BTC: {payload.get('binance_spot_price')}",
                f"before: {payload.get('positions_before')}",
                f"after: {payload.get('positions_after')}",
            ]
            if validation.get('message'):
                meta_parts.append(f"validation: {validation.get('message')}")
            if details.get('rejected'):
                meta_parts.append(f"rejected: {details.get('rejected')}")
            slugs = [d.get('market_slug') for d in (raw_details if isinstance(raw_details, list) else [details]) if d.get('market_slug')]
            if slugs:
                meta_parts.append(f"market: {', '.join(slugs)}")
            items.append({
                'timestamp': fmt_cet(payload.get('timestamp', path.stem.replace('cycle-', '').replace('-', ':', 2))),
                'eyebrow': f'{action} · {outcome_label.upper()}',
                'title': summary,
                'meta': ' · '.join(part for part in meta_parts if part and not part.endswith('None')),
                'tone': tone,
            })
        else:
            tail = ' '.join(text.splitlines()[-4:])[:220]
            items.append({
                'timestamp': path.stem.replace('cycle-', ''),
                'eyebrow': 'Cycle file',
                'title': tail or path.name,
                'meta': path.name,
                'tone': 'info',
            })
    return items[:limit]


def build_private_trace_lanes() -> list[dict[str, Any]]:
    return [
        {
            'title': 'Beecthor summaries',
            'subtitle': 'Móvil · generación del resumen',
            'entries': build_mobile_trace_entries(
                'phone.summarizer',
                limit=TRACE_LANE_LIMIT,
                payload_keys=['video_id', 'robot_score'],
            ),
            'triggers': [{'process': 'summarizer', 'label': '▶ Run Summaries', 'primary': True}],
        },
        {
            'title': 'Server cycles',
            'subtitle': 'Servidor · decisión de ciclo',
            'entries': build_cycle_trace_entries(limit=TRACE_LANE_LIMIT),
            'triggers': [{'process': 'cycle', 'label': '▶ Run Cycle', 'primary': True}],
        },
        {
            'title': 'Open operations',
            'subtitle': 'Móvil · aperturas',
            'entries': build_mobile_trace_entries(
                'phone.executor',
                limit=TRACE_LANE_LIMIT,
                payload_keys=['order_id', 'market_slug', 'outcome', 'status'],
                allowed_events={'run_started', 'run_skipped', 'order_received', 'order_executed', 'order_skipped', 'order_failed', 'run_active'},
            ),
            'triggers': [{'process': 'executor', 'label': '▶ Run Executor', 'primary': True}],
        },
        {
            'title': 'TP / SL',
            'subtitle': 'Móvil · take-profit y stop-loss',
            'triggers': [
                {'process': 'monitor', 'label': '⚡ Monitor', 'primary': False},
                {'process': 'monitor_executor', 'label': '▶ Executor', 'primary': True},
            ],
            'entries': build_mobile_trace_entries(
                'phone.monitor',
                limit=TRACE_LANE_LIMIT,
                payload_keys=['market_slug', 'outcome', 'reason', 'status'],
                allowed_events={'trigger_detected', 'trigger_skipped', 'order_executed', 'order_failed', 'run_skipped'},
            ),
        },
    ]


def fmt_cet(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(_CET)
        return dt.strftime('%Y-%m-%dT%H:%M')
    except Exception:
        return timestamp


def timestamp_to_local(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(_CET)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return timestamp


def extract_message_section(message: str, start_label: str, end_label: str | None = None) -> str:
    start = message.find(start_label)
    if start == -1:
        return ''
    start += len(start_label)
    end = message.find(end_label, start) if end_label else -1
    if end == -1:
        end = len(message)
    return message[start:end].strip()


def strip_html_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text or '').strip()


def derive_public_title(entry: dict[str, Any]) -> str:
    title = strip_html_tags(entry.get('title', ''))
    if title:
        return title
    summary = strip_html_tags(extract_message_section(entry.get('message', ''), '📌 <b>Resumen</b>', '🔍 <b>Análisis completo</b>'))
    if summary:
        summary = re.sub(r'\s+', ' ', summary)
        return summary[:92].rstrip(' ,.;:') + ('…' if len(summary) > 92 else '')
    return f"Beecthor vídeo {entry.get('video_id', '').strip() or 'sin título'}"


def youtube_watch_url(video_id: str) -> str:
    return f'https://www.youtube.com/watch?v={video_id}'


def youtube_thumb_url(video_id: str) -> str:
    return f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'


def normalize_html_text_block(text: str) -> str:
    normalized = (text or '').strip()
    normalized = normalized.replace('\r\n', '\n').replace('\r', '\n')
    normalized = re.sub(r'\n{3,}', '\n\n', normalized)
    return normalized.replace('\n', '<br>')


def extract_spoiler_inner_html(message: str) -> str:
    match = re.search(r'<tg-spoiler>(.*?)</tg-spoiler>', message or '', flags=re.S)
    if match:
        return match.group(1).strip()
    analysis = extract_message_section(message or '', '🔍 <b>Análisis completo</b>', None)
    analysis = re.sub(r'^\s*<i>.*?</i>\s*', '', analysis, flags=re.S)
    return analysis.strip()


def parse_analysis_sections(message: str) -> list[dict[str, str]]:
    spoiler_html = extract_spoiler_inner_html(message)
    if not spoiler_html:
        return []
    chunks = [chunk.strip() for chunk in re.split(r'\n\s*\n', spoiler_html) if chunk.strip()]
    sections: list[dict[str, str]] = []
    pattern = re.compile(
        r'^\s*(?:(?P<icon>[^\w<\s][^<\n]{0,3})\s+)?<b>(?P<title>[^<]+)</b>\s*(?P<body>.*)$',
        flags=re.S,
    )
    for chunk in chunks:
        match = pattern.match(chunk)
        if not match:
            continue
        body = normalize_html_text_block(match.group('body'))
        if not strip_html_tags(body):
            continue
        sections.append(
            {
                'icon': (match.group('icon') or '•').strip(),
                'title': match.group('title').strip(),
                'body_html': body,
            }
        )
    return sections


def load_summary_entries() -> list[dict[str, Any]]:
    entries = load_json(ANALYSES_LOG_PATH, [])
    items = []
    for entry in reversed(entries):
        message = entry.get('message', '')
        video_id = entry.get('video_id', '')
        items.append({
            **entry,
            'timestamp_local': timestamp_to_local(entry.get('timestamp', '')),
            'summary_html': extract_message_section(message, '📌 <b>Resumen</b>', '🔍 <b>Análisis completo</b>') or '<span class="muted">Sin resumen visible</span>',
            'message_html': message,
            'public_title': derive_public_title(entry),
            'youtube_url': youtube_watch_url(video_id),
            'thumbnail_url': youtube_thumb_url(video_id),
        })
    return items


def find_summary(video_id: str) -> dict[str, Any] | None:
    for item in load_summary_entries():
        if item.get('video_id') == video_id:
            return item
    return None


def classify_market_bucket(text: str) -> str:
    normalized = (text or '').lower()
    month = r'(january|february|march|april|may|june|july|august|september|october|november|december)'
    # Weekly: slug contains two date references separated by a range (e.g. march-30-april-5 or april-6-12)
    if re.search(rf'{month}-\d{{1,2}}-{month}-\d{{1,2}}', normalized):
        return 'weekly'
    if re.search(rf'{month}\s+\d{{1,2}}\s*-\s*{month}\s+\d{{1,2}}', normalized):
        return 'weekly'
    if re.search(rf'{month}-\d{{1,2}}-\d{{1,2}}', normalized):
        return 'weekly'
    # Daily: slug contains "on-month-day" or "on april 9" or ends with month-day
    if re.search(rf'on-{month}-\d{{1,2}}', normalized):
        return 'daily'
    if re.search(rf'on {month} \d{{1,2}}', normalized):
        return 'daily'
    if re.search(rf'-on-\d{{1,2}}$', normalized):
        return 'daily'
    return 'unknown'


def fetch_live_positions() -> list[dict[str, Any]]:
    user = POLY_FUNDER or POLY_SIGNER_ADDRESS
    if not user:
        return []
    try:
        response = requests.get(f'{DATA_API_HOST}/positions', params={'user': user, 'sizeThreshold': 0.01, 'limit': 100}, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


# Positions permanently excluded from the dashboard (test trades, non-BTC narrative bets, etc.)
IGNORED_POSITION_SLUGS: set[str] = {
    'will-december-be-the-best-month-for-bitcoin-in-2026',
}


def fetch_closed_positions_live() -> list[dict[str, Any]]:
    user = POLY_FUNDER or POLY_SIGNER_ADDRESS
    if not user:
        return []
    try:
        response = requests.get(f'{DATA_API_HOST}/closed-positions', params={'user': user, 'limit': 200, 'offset': 0}, timeout=20)
        response.raise_for_status()
        return [p for p in response.json() if p.get('slug') not in IGNORED_POSITION_SLUGS]
    except Exception:
        return []


def fetch_live_position_value() -> float | None:
    user = POLY_FUNDER or POLY_SIGNER_ADDRESS
    if not user:
        return None
    try:
        response = requests.get(f'{DATA_API_HOST}/value', params={'user': user}, timeout=20)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list) and payload:
            return safe_float(payload[0].get('value'))
    except Exception:
        return None
    return None


def fetch_live_cash_balance() -> float | None:
    if not all([ClobClient, ApiCreds, AssetType, BalanceAllowanceParams]):
        return None
    if not all([POLY_PRIVATE_KEY, POLY_FUNDER, POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE]):
        return None
    try:
        client = ClobClient(
            CLOB_HOST,
            key=POLY_PRIVATE_KEY,
            chain_id=CHAIN_ID,
            signature_type=POLY_SIGNATURE_TYPE,
            funder=POLY_FUNDER,
        )
        client.set_api_creds(
            ApiCreds(
                api_key=POLY_API_KEY,
                api_secret=POLY_API_SECRET,
                api_passphrase=POLY_API_PASSPHRASE,
            )
        )
        payload = client.get_balance_allowance(
            BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=POLY_SIGNATURE_TYPE,
            )
        )
        return safe_float(payload.get('balance')) / 1_000_000
    except Exception:
        return None


def normalize_live_position(position: dict[str, Any]) -> dict[str, Any]:
    market_slug = position.get('slug', '')
    event_slug = position.get('eventSlug', '')
    return {
        'event_slug': event_slug,
        'market_slug': market_slug,
        'market_title': position.get('title') or market_slug,
        'position_side': position.get('outcome', ''),
        'token_id': position.get('asset', ''),
        'shares': round(safe_float(position.get('size')), 4),
        'avg_price': round(safe_float(position.get('avgPrice')), 4),
        'entry_cost_usd': round(safe_float(position.get('initialValue')), 6),
        'current_price': round(safe_float(position.get('curPrice')), 4),
        'current_value_usd': round(safe_float(position.get('currentValue')), 6),
        'cash_pnl_usd': round(safe_float(position.get('cashPnl')), 6),
        'category': classify_market_bucket(event_slug or market_slug or position.get('title') or ''),
        'status': 'open',
    }


def build_polymarket_snapshot() -> dict[str, Any]:
    account_state = load_json(ACCOUNT_STATE_PATH, {})
    trade_log = load_json(TRADE_LOG_PATH, [])
    pending_orders = load_json(PENDING_ORDERS_PATH, [])
    live_positions_raw = fetch_live_positions()
    open_positions = [normalize_live_position(item) for item in live_positions_raw]
    closed_positions = fetch_closed_positions_live()
    live_cash_balance = fetch_live_cash_balance()
    live_position_value = fetch_live_position_value()
    fallback_cash = safe_float(account_state.get('cash_available'))
    fallback_position_value = sum(safe_float(p.get('current_value_usd')) for p in account_state.get('open_positions', []))
    cash_balance = live_cash_balance if live_cash_balance is not None else fallback_cash
    position_value = live_position_value if live_position_value is not None else fallback_position_value
    portfolio_value = round(cash_balance + position_value, 6)
    unrealized_pnl = round(sum(safe_float(p.get('cash_pnl_usd')) for p in open_positions), 6)
    starting_bankroll = safe_float(account_state.get('starting_bankroll'))
    total_pnl = round(portfolio_value - starting_bankroll, 6) if starting_bankroll else round(sum(safe_float(item.get('realizedPnl')) for item in closed_positions), 6) + unrealized_pnl
    realized_pnl = round(total_pnl - unrealized_pnl, 6)
    wins = sum(1 for item in closed_positions if float(item.get('realizedPnl', 0.0)) > 0)
    losses = sum(1 for item in closed_positions if float(item.get('realizedPnl', 0.0)) < 0)
    total_closed = len(closed_positions)
    total_operations = total_closed + len(open_positions)
    win_rate = round((wins / total_closed) * 100, 1) if total_closed else 0.0
    daily_count = 0
    weekly_count = 0
    for item in [*open_positions, *closed_positions]:
        bucket = classify_market_bucket(item.get('event_slug') or item.get('market_slug') or item.get('title') or '')
        if bucket == 'daily':
            daily_count += 1
        elif bucket == 'weekly':
            weekly_count += 1
    metrics = [
        {'label': 'Portfolio', 'value': f'{portfolio_value:.2f}$', 'caption': 'live cash + live positions when available', 'css_class': ''},
        {'label': 'Cash', 'value': f"{cash_balance:.2f}$", 'caption': 'available to trade' if live_cash_balance is not None else 'fallback from local state', 'css_class': ''},
        {'label': 'PnL realizado', 'value': f'{realized_pnl:.2f}$', 'caption': 'portfolio - bankroll - unrealized', 'css_class': 'good' if realized_pnl >= 0 else 'bad'},
        {'label': 'PnL no realizado', 'value': f'{unrealized_pnl:.2f}$', 'caption': 'posiciones abiertas', 'css_class': 'good' if unrealized_pnl >= 0 else 'bad'},
        {'label': 'Operaciones', 'value': str(total_operations), 'caption': f'{total_closed} cerradas · {len(open_positions)} abiertas', 'css_class': '', 'open_positions': [
            {
                'title': p.get('market_title', p.get('market_slug', '')),
                'market_slug': p.get('market_slug', ''),
                'outcome': p.get('position_side', ''),
                'prob': f"{safe_float(p.get('current_price')) * 100:.0f}¢",
                'pnl': safe_float(p.get('cash_pnl_usd')),
                'shares': safe_float(p.get('shares')),
                'can_sell': safe_float(p.get('shares')) > 0 and bool(p.get('token_id')),
            }
            for p in open_positions
        ]},
        {'label': 'Aciertos / fallos', 'value': f'{wins} / {losses}', 'caption': 'closed positions', 'css_class': ''},
        {'label': 'Win rate', 'value': f'{win_rate:.1f}%', 'caption': 'closed positions', 'css_class': 'good' if win_rate >= 50 else 'bad'},
        {'label': 'Daily / Weekly', 'value': f'{daily_count} / {weekly_count}', 'caption': 'classified positions', 'css_class': ''},
    ]
    positions = open_positions
    recent_operations = []
    for entry in reversed(trade_log):
        execution = entry.get('execution') or {}
        raw_details = execution.get('details') or {}
        # details may be a list (multi-order) or a single dict
        details_list = raw_details if isinstance(raw_details, list) else ([raw_details] if raw_details else [])
        if entry.get('type') == 'trade_opened':
            market_slug = entry.get('market_slug', '')
            recent_operations.append({'timestamp': entry.get('timestamp', ''), 'type': 'trade_opened', 'market_slug': market_slug, 'category': classify_market_bucket(entry.get('event_slug') or market_slug), 'status': entry.get('status', '')})
        elif details_list:
            for details in details_list:
                market_slug = details.get('market_slug', '')
                recent_operations.append({'timestamp': entry.get('timestamp', ''), 'type': details.get('type', entry.get('type', 'cycle_run')), 'market_slug': market_slug, 'category': classify_market_bucket(market_slug), 'status': details.get('status', 'performed' if execution.get('performed') else 'skipped')})
    return {'metrics': metrics, 'positions': positions, 'recent_operations': recent_operations[:12], 'pipeline': {'pending_count': len(pending_orders), 'pending_orders': pending_orders[:12]}}


def load_recent_operator_tail() -> str:
    monitor_log = Path('/var/log/polymarket-operator/monitor.log')
    if not monitor_log.exists():
        return 'Operator monitor log not found.'
    try:
        return '\n'.join(monitor_log.read_text(encoding='utf-8', errors='replace').splitlines()[-80:])
    except Exception as exc:
        return f'Could not read operator log: {exc}'


def load_latest_cycle_tail() -> str:
    cycle_dir = Path('/var/log/polymarket-operator')
    if not cycle_dir.exists():
        return 'Cycle log directory not found.'
    cycle_files = sorted(cycle_dir.glob('cycle-*.log'))
    if not cycle_files:
        return 'No cycle logs found.'
    latest = cycle_files[-1]
    try:
        return latest.name + '\n\n' + '\n'.join(latest.read_text(encoding='utf-8', errors='replace').splitlines()[-80:])
    except Exception as exc:
        return f'Could not read latest cycle log: {exc}'


def run_copilot(message: str) -> str:
    try:
        result = subprocess.run(['copilot', '-p', message, '--continue', '-s', '--allow-all'], capture_output=True, text=True, encoding='utf-8', timeout=120, cwd=str(REPO_ROOT), env={**os.environ, 'HOME': '/root', 'LANG': 'en_US.UTF-8', 'PYTHONIOENCODING': 'utf-8'})
        output = result.stdout.strip() or result.stderr.strip() or f'(no output, exit code {result.returncode})'
        append_jsonl_event('app.chat', 'copilot_response', 'info', 'Copilot chat message processed', {'exit_code': result.returncode})
        return output
    except subprocess.TimeoutExpired:
        append_jsonl_event('app.chat', 'copilot_timeout', 'warning', 'Copilot took more than 120 seconds')
        return '(timeout — Copilot took more than 120 seconds)'
    except FileNotFoundError:
        append_jsonl_event('app.chat', 'copilot_missing', 'error', 'copilot CLI not found in PATH')
        return '(copilot CLI not found in PATH)'
    except Exception as exc:
        append_jsonl_event('app.chat', 'copilot_error', 'error', f'Copilot execution failed: {exc}')
        return f'(error: {exc})'


@app.route('/')
def public_index():
    items = load_summary_entries()
    html = page_start('Resúmenes | Beecthor') + """
    <div class="shell public-shell">
      <div class="top">
        <div>
          <h1 class="brand-title">Beecthor</h1>
          <div class="section-subtitle">Biblioteca pública de resúmenes, organizada como una videoteca del canal.</div>
        </div>
        <div class="nav"></div>
      </div>
      <div class="video-grid">
        {% for item in items %}
        <article class="video-card">
          <a class="video-link" href="{{ url_for('public_video_detail', video_id=item.video_id) }}">
            <div class="thumb-wrap">
              <img src="{{ item.thumbnail_url }}" alt="{{ item.public_title }}">
            </div>
            <div class="video-meta">
              <div class="video-title">{{ item.public_title }}</div>
              <div class="video-date">{{ item.timestamp_local }}</div>
            </div>
          </a>
        </article>
        {% endfor %}
      </div>
    </div>""" + PAGE_END
    return render_template_string(html, items=items)


@app.route('/videos/<video_id>')
def public_video_detail(video_id: str):
    item = find_summary(video_id)
    if not item:
        return ('Not found', 404)
    summary_html = extract_message_section(item.get('message_html', ''), '📌 <b>Resumen</b>', '🔍 <b>Análisis completo</b>') or '<span class="muted">Sin resumen visible.</span>'
    analysis_sections = parse_analysis_sections(item.get('message_html', ''))
    fallback_analysis_html = ''
    if not analysis_sections:
        spoiler_html = extract_spoiler_inner_html(item.get('message_html', ''))
        if spoiler_html:
            fallback_analysis_html = normalize_html_text_block(spoiler_html)
    html = page_start(f"{item.get('public_title', 'Resumen')} | Beecthor") + """
    <div class="shell public-shell">
      <div class="top">
        <div>
          <h1 class="brand-title">Beecthor</h1>
          <div class="section-subtitle">Resumen detallado del vídeo seleccionado.</div>
        </div>
        <div class="nav"><a href="/">Vídeos</a></div>
      </div>
      <div class="detail-layout">
        <section class="detail-media">
          <img src="{{ item.thumbnail_url }}" alt="{{ item.public_title }}">
        </section>
        <aside class="detail-panel">
          <div class="muted">{{ item.timestamp_local }}</div>
          <h1 class="detail-title">{{ item.public_title }}</h1>
          <div class="muted">Video ID · {{ item.video_id }}</div>
          <div class="detail-actions">
            <a class="button-link" href="{{ item.youtube_url }}" target="_blank" rel="noopener noreferrer">Ver en YouTube</a>
            <a class="button-link secondary" href="/">Volver a vídeos</a>
          </div>
        </aside>
      </div>
      <section class="surface-card detail-summary-card">
        <div class="detail-summary-label">Resumen visible</div>
        <div class="detail-summary-text">{{ summary_html|safe }}</div>
      </section>
      {% if analysis_sections %}
      <section class="detail-section-grid">
        {% for section in analysis_sections %}
        <article class="detail-section-card">
          <div class="detail-section-head">
            <div class="detail-section-icon">{{ section.icon }}</div>
            <div class="detail-section-title">{{ section.title }}</div>
          </div>
          <div class="detail-section-body">{{ section.body_html|safe }}</div>
        </article>
        {% endfor %}
      </section>
      {% elif fallback_analysis_html %}
      <section class="surface-card detail-fallback">
        <div class="detail-summary-label">Análisis completo</div>
        <div class="summary-body">{{ fallback_analysis_html|safe }}</div>
      </section>
      {% endif %}
    </div>""" + PAGE_END
    return render_template_string(
        html,
        item=item,
        summary_html=summary_html,
        analysis_sections=analysis_sections,
        fallback_analysis_html=fallback_analysis_html,
    )


TRIGGER_LABELS = {
    'cycle': 'Cycle',
    'monitor': 'Monitor (server)',
    'executor': 'Executor (phone)',
    'monitor_executor': 'Monitor Executor (phone)',
    'summarizer': 'Beecthor Summaries (phone)',
}

PHONE_SSH = ['ssh', '-p', '2222', '-o', 'StrictHostKeyChecking=no', 'u0_a647@localhost']
PHONE_REPO_CMD = "bash -lc 'cd ~/beecthor-summary && git pull --ff-only >/dev/null 2>&1 || true && python {script}'"


@app.route('/private/trigger/<process>', methods=['POST'])
@require_private
def trigger_process(process: str):
    if process == 'cycle':
        subprocess.Popen(
            ['bash', '/root/run_polymarket_cycle.sh'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif process == 'summarizer':
        subprocess.Popen(
            PHONE_SSH + [PHONE_REPO_CMD.format(script='phone/beecthor_summarizer.py')],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif process == 'monitor':
        subprocess.Popen(
            ['python', str(REPO_ROOT / 'polymarket_assistant' / 'run_monitor.py')],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif process == 'executor':
        subprocess.Popen(
            PHONE_SSH + [PHONE_REPO_CMD.format(script='phone/polymarket_executor.py')],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif process == 'monitor_executor':
        subprocess.Popen(
            PHONE_SSH + [PHONE_REPO_CMD.format(script='phone/polymarket_monitor_executor.py')],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        return redirect(url_for('private_polymarket'))
    return redirect(url_for('private_polymarket', triggered=process))


@app.route('/refresh')
def refresh_repo():
    subprocess.run(
        ['git', '-C', str(REPO_ROOT), 'pull', '--ff-only', 'origin', 'main'],
        capture_output=True, timeout=30,
    )
    next_page = request.args.get('next', 'public_index')
    destinations = {
        'polymarket': 'private_polymarket',
        'logs': 'private_logs',
    }
    return redirect(url_for(destinations.get(next_page, 'public_index')))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('authenticated'):
        return redirect(url_for('private_polymarket'))
    error = None
    if request.method == 'POST':
        if CHAT_PASSWORD and request.form.get('password') == CHAT_PASSWORD:
            session['authenticated'] = True
            append_jsonl_event('app.auth', 'login_success', 'info', 'Private dashboard login succeeded')
            return redirect(url_for('private_polymarket'))
        error = 'Wrong password.'
        append_jsonl_event('app.auth', 'login_failure', 'warning', 'Private dashboard login failed')
    return render_template_string(LOGIN_HTML, error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/private')
@require_private
def private_root():
    return redirect(url_for('private_polymarket'))


@app.route('/private/polymarket')
@require_private
def private_polymarket():
    snapshot = build_polymarket_snapshot()
    trace_lanes = build_private_trace_lanes()
    manual_sell = request.args.get('manual_sell', '').strip()
    manual_sell_market = request.args.get('manual_sell_market', '').strip()
    manual_sell_outcome = request.args.get('manual_sell_outcome', '').strip()
    manual_sell_fraction = safe_float(request.args.get('manual_sell_fraction', '1.0'), 1.0)
    manual_sell_feedback = build_manual_sell_feedback(manual_sell, manual_sell_market, manual_sell_outcome, manual_sell_fraction)
    html = page_start('Polymarket | Beecthor') + """
    <div class="shell private-shell">
      <div class="private-header">
        <div>
          <h1 class="private-title">Zona privada</h1>
          <div class="section-subtitle">Panel de control inspirado en Polymarket para cartera, operativa y observabilidad.</div>
        </div>
        <div class="nav"><a href="/">Pública</a><a href="/private/polymarket" style="font-weight:700;color:#fff">Polymarket</a><a href="/private/logs">Logs</a><a href="/private/chat">Chat</a><a href="/logout">Logout</a><a class="button-link secondary" href="/refresh?next=polymarket" style="font-size:.85rem;padding:8px 14px">↻ Actualizar</a></div>
      </div>
      <div class="private-strip">
        <section class="metric-panel">
          <div class="metric-label">{{ metrics[0].label }}</div>
          <div class="metric-value">{{ metrics[0].value }}</div>
          <div class="metric-foot">{{ metrics[1].caption }}</div>
        </section>
        <section class="pnl-panel">
          <div class="metric-label">{{ metrics[2].label }}</div>
          <div class="metric-value {{ metrics[2].css_class }}">{{ metrics[2].value }}</div>
          <div class="metric-foot">{{ metrics[2].caption }}</div>
        </section>
      </div>
      <div class="private-grid">
        {% for metric in metrics[1:] %}
        <section class="metric-card">
          <div class="metric-label">{{ metric.label }}</div>
          <div class="big {{ metric.css_class }}">{{ metric.value }}</div>
          <div class="muted">{{ metric.caption }}</div>
          {% if metric.open_positions is defined and metric.open_positions %}
          <details style="margin-top:8px">
            <summary style="cursor:pointer;font-size:.78rem;color:#aaa;list-style:none">▸ ver abiertas</summary>
            <div style="margin-top:6px;display:flex;flex-direction:column;gap:4px">
              {% for pos in metric.open_positions %}
                            <div class="position-open-item">
                                <div class="position-open-head">
                                    <div class="position-open-info">
                                        <span class="position-open-title" title="{{ pos.title }}">{{ pos.outcome }} · {{ pos.title }}</span>
                                        <div class="position-open-meta">
                                            <span>{{ pos.prob }}</span>
                                            <span class="{{ 'good' if pos.pnl >= 0 else 'bad' }}">{{ '%+.2f$' % pos.pnl }}</span>
                                            <span class="position-open-shares">{{ '%.2f' % pos.shares }} sh</span>
                                        </div>
                                    </div>
                                    {% if pos.can_sell %}
                                    <div class="position-open-action">
                                        <button
                                            type="button"
                                            class="sell-trigger"
                                            data-market-slug="{{ pos.market_slug }}"
                                            data-outcome="{{ pos.outcome }}"
                                            data-title="{{ pos.title }}"
                                            data-shares="{{ '%.2f' % pos.shares }}"
                                            data-prob="{{ pos.prob }}"
                                            data-pnl="{{ '%+.2f$' % pos.pnl }}"
                                        >SELL...</button>
                                    </div>
                                    {% endif %}
                                </div>
                            </div>
              {% endfor %}
            </div>
          </details>
          {% endif %}
        </section>
        {% endfor %}
      </div>
            {% if manual_sell_feedback %}
            <div style="margin-bottom:18px;padding:12px 18px;border-radius:14px;background:{{ manual_sell_feedback.bg }};border:1px solid {{ manual_sell_feedback.border }};color:{{ manual_sell_feedback.color }};font-weight:600;font-size:.93rem">
                {{ manual_sell_feedback.text }}
            </div>
            {% endif %}
      {% if triggered %}
      <div style="margin-bottom:18px;padding:12px 18px;border-radius:14px;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.25);color:#4ade80;font-weight:600;font-size:.93rem">
        ✓ {{ triggered_label }} lanzado en background — revisa los logs en unos minutos.
      </div>
      {% endif %}
      <div class="trace-grid">
        {% for lane in trace_lanes %}
        <section class="trace-lane">
          <div class="trace-lane-head" style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
            <div>
              <h2 class="trace-lane-title">{{ lane.title }}</h2>
              <div class="trace-lane-subtitle">{{ lane.subtitle }}</div>
            </div>
            {% if lane.triggers is defined %}
            <div style="display:flex;gap:6px;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end">
              {% for t in lane.triggers %}
              <form method="POST" action="/private/trigger/{{ t.process }}">
                <button type="submit" style="background:{% if t.primary %}#1f6feb{% else %}#22272d{% endif %};color:#f3f4f6;border:none;border-radius:999px;padding:6px 12px;cursor:pointer;font-weight:700;font-size:.75rem;white-space:nowrap">{{ t.label }}</button>
              </form>
              {% endfor %}
            </div>
            {% endif %}
          </div>
          <div class="trace-stack">
            {% for entry in lane.entries %}
            <div class="trace-entry {{ entry.tone }}">
              <div class="trace-time">{{ entry.timestamp }}</div>
              <div class="trace-eyebrow">{{ entry.eyebrow }}</div>
              <div class="trace-title">{{ entry.title }}</div>
              {% if entry.meta %}
              <div class="trace-meta">{{ entry.meta }}</div>
              {% endif %}
            </div>
            {% else %}
            <div class="trace-entry info">
              <div class="trace-title">No hay trazas recientes en este carril.</div>
            </div>
            {% endfor %}
          </div>
        </section>
        {% endfor %}
      </div>
            <div id="sell-modal-backdrop" class="sell-modal-backdrop" hidden>
                <div class="sell-modal" role="dialog" aria-modal="true" aria-labelledby="sell-modal-title">
                    <div class="sell-modal-head">
                        <div>
                            <div class="sell-modal-kicker">Manual SELL</div>
                            <h2 id="sell-modal-title" class="sell-modal-title">Selecciona un porcentaje</h2>
                        </div>
                        <button type="button" id="sell-modal-close" class="sell-modal-close">Cerrar</button>
                    </div>
                    <div class="sell-modal-body">
                        <div id="sell-modal-position" class="sell-modal-position"></div>
                        <div id="sell-modal-stats" class="sell-modal-stats"></div>
                        <div class="sell-option-grid">
                            {% for option in [0.25, 0.5, 0.75, 1.0] %}
                            <form class="sell-option-form" method="POST" action="/private/position/sell" data-percent="{{ (option * 100)|int }}">
                                <input type="hidden" name="market_slug">
                                <input type="hidden" name="outcome">
                                <input type="hidden" name="fraction" value="{{ option }}">
                                <button type="submit" class="sell-option-button{{ ' full' if option == 1.0 else '' }}">SELL {{ (option * 100)|int }}%</button>
                            </form>
                            {% endfor %}
                        </div>
                        <div class="sell-modal-note">La orden se encolará como venta manual y lanzará el executor del móvil en background.</div>
                    </div>
                </div>
            </div>
            <script>
                (function () {
                    var backdrop = document.getElementById('sell-modal-backdrop');
                    if (!backdrop) {
                        return;
                    }
                    var titleEl = document.getElementById('sell-modal-title');
                    var positionEl = document.getElementById('sell-modal-position');
                    var statsEl = document.getElementById('sell-modal-stats');
                    var closeBtn = document.getElementById('sell-modal-close');
                    var optionForms = Array.prototype.slice.call(backdrop.querySelectorAll('.sell-option-form'));
                    var optionButtons = Array.prototype.slice.call(backdrop.querySelectorAll('.sell-option-button'));
                    var currentState = null;

                    function buildPositionLabel() {
                        if (!currentState) {
                            return 'esta posición';
                        }
                        return [currentState.outcome, currentState.title].filter(Boolean).join(' en ');
                    }

                    function closeSellModal() {
                        backdrop.hidden = true;
                        backdrop.classList.remove('is-open');
                        backdrop.setAttribute('aria-hidden', 'true');
                        document.body.style.overflow = '';
                        currentState = null;
                    }

                    function openSellModal(trigger) {
                        currentState = {
                            marketSlug: trigger.dataset.marketSlug || '',
                            outcome: trigger.dataset.outcome || '',
                            title: trigger.dataset.title || '',
                            shares: trigger.dataset.shares || '',
                            prob: trigger.dataset.prob || '',
                            pnl: trigger.dataset.pnl || '',
                        };
                        titleEl.textContent = 'Selecciona un porcentaje';
                        positionEl.textContent = [currentState.outcome, currentState.title].filter(Boolean).join(' · ');
                        statsEl.textContent = [
                            currentState.shares ? currentState.shares + ' sh' : '',
                            currentState.prob,
                            currentState.pnl,
                        ].filter(Boolean).join(' · ');
                        optionForms.forEach(function (form) {
                            form.querySelector('input[name="market_slug"]').value = currentState.marketSlug;
                            form.querySelector('input[name="outcome"]').value = currentState.outcome;
                        });
                        backdrop.hidden = false;
                        backdrop.classList.add('is-open');
                        backdrop.setAttribute('aria-hidden', 'false');
                        document.body.style.overflow = 'hidden';
                        if (optionButtons.length) {
                            optionButtons[0].focus();
                        }
                    }

                    document.querySelectorAll('.sell-trigger').forEach(function (button) {
                        button.addEventListener('click', function () {
                            openSellModal(button);
                        });
                    });

                    closeBtn.addEventListener('click', closeSellModal);

                    backdrop.addEventListener('click', function (event) {
                        if (event.target === backdrop) {
                            closeSellModal();
                        }
                    });

                    document.addEventListener('keydown', function (event) {
                        if (event.key === 'Escape' && !backdrop.hidden) {
                            closeSellModal();
                        }
                    });

                    optionForms.forEach(function (form) {
                        form.addEventListener('submit', function (event) {
                            var percent = form.dataset.percent || '';
                            var message = 'Confirmar SELL ' + percent + ' para ' + buildPositionLabel() + '?\n\nEsto encolará una orden manual para el executor del móvil.';
                            if (!window.confirm(message)) {
                                event.preventDefault();
                            }
                        });
                    });
                })();
            </script>
    </div>""" + PAGE_END
    triggered = request.args.get('triggered', '')
    triggered_label = TRIGGER_LABELS.get(triggered, triggered)
    return render_template_string(
        html,
        trace_lanes=trace_lanes,
        triggered=triggered,
        triggered_label=triggered_label,
        manual_sell_feedback=manual_sell_feedback,
        **snapshot,
    )


@app.route('/private/position/sell', methods=['POST'])
@require_private
def private_sell_position():
    market_slug = request.form.get('market_slug', '').strip()
    outcome = request.form.get('outcome', '').strip()
    fraction = safe_float(request.form.get('fraction', '1.0'), 1.0)
    valid_fractions = {0.25, 0.5, 0.75, 1.0}
    if not market_slug or not outcome:
        return redirect(url_for('private_polymarket', manual_sell='error', manual_sell_market=market_slug, manual_sell_outcome=outcome, manual_sell_fraction=fraction))

    if fraction not in valid_fractions:
        return redirect(url_for('private_polymarket', manual_sell='invalid', manual_sell_market=market_slug, manual_sell_outcome=outcome, manual_sell_fraction=fraction))

    if active_manual_sell_order(market_slug, outcome):
        return redirect(url_for('private_polymarket', manual_sell='duplicate', manual_sell_market=market_slug, manual_sell_outcome=outcome, manual_sell_fraction=fraction))

    live_positions = [normalize_live_position(item) for item in fetch_live_positions()]
    target = next(
        (pos for pos in live_positions if pos['market_slug'] == market_slug and pos['position_side'] == outcome),
        None,
    )
    if not target:
        append_jsonl_event(
            'app.polymarket',
            'manual_sell_missing',
            'warning',
            'Manual SELL requested for a position that is no longer open',
            {'market_slug': market_slug, 'outcome': outcome, 'fraction': fraction},
        )
        return redirect(url_for('private_polymarket', manual_sell='missing', manual_sell_market=market_slug, manual_sell_outcome=outcome, manual_sell_fraction=fraction))

    amount = round(target['shares'] * fraction, 8)
    if amount <= 0:
        return redirect(url_for('private_polymarket', manual_sell='invalid', manual_sell_market=market_slug, manual_sell_outcome=outcome, manual_sell_fraction=fraction))

    order = {
        'order_id': utc_now(),
        'status': 'pending_phone_execution',
        'type': 'CLOSE_POSITION' if fraction >= 1.0 else 'REDUCE_POSITION',
        'token_id': target['token_id'],
        'side': 'SELL',
        'amount': amount,
        'market': target['market_title'],
        'market_slug': market_slug,
        'outcome': outcome,
        'fraction': fraction,
        'source': 'dashboard_manual_sell',
    }

    try:
        enqueue_pending_order(order)
        append_jsonl_event(
            'app.polymarket',
            'manual_sell_enqueued',
            'info',
            'Manual SELL order enqueued from dashboard',
            {
                'market_slug': market_slug,
                'outcome': outcome,
                'amount': amount,
                'shares': target['shares'],
                'fraction': fraction,
                'token_id': target['token_id'],
            },
        )
        subprocess.Popen(
            PHONE_SSH + [PHONE_REPO_CMD.format(script='phone/polymarket_executor.py')],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        append_jsonl_event(
            'app.polymarket',
            'manual_sell_error',
            'error',
            f'Manual SELL failed: {exc}',
            {'market_slug': market_slug, 'outcome': outcome, 'fraction': fraction},
        )
        return redirect(url_for('private_polymarket', manual_sell='error', manual_sell_market=market_slug, manual_sell_outcome=outcome, manual_sell_fraction=fraction))

    return redirect(url_for('private_polymarket', manual_sell='queued', manual_sell_market=market_slug, manual_sell_outcome=outcome, manual_sell_fraction=fraction))


@app.route('/private/logs')
@require_private
def private_logs():
    filters = {'source': request.args.get('source', '').strip(), 'event_type': request.args.get('event_type', '').strip(), 'level': request.args.get('level', '').strip()}
    items = read_jsonl_logs(source=filters['source'], event_type=filters['event_type'], level=filters['level'])
    html = page_start('Logs | Beecthor') + """
    <div class="shell private-shell">
      <div class="private-header">
        <div>
          <h1 class="private-title">Logs</h1>
          <div class="section-subtitle">Observabilidad unificada del servidor, del móvil y de la propia app web.</div>
        </div>
        <div class="nav"><a href="/">Pública</a><a href="/private/polymarket">Polymarket</a><a href="/private/logs" style="font-weight:700;color:#fff">Logs</a><a href="/private/chat">Chat</a><a href="/logout">Logout</a></div>
      </div>
      <form class="surface-card log-controls" method="GET">
        <input type="text" name="source" placeholder="source" value="{{ filters.source }}">
        <input type="text" name="event_type" placeholder="event type" value="{{ filters.event_type }}">
        <select name="level"><option value="">all levels</option>{% for option in ['info','warning','error'] %}<option value="{{ option }}" {{ 'selected' if filters.level == option else '' }}>{{ option }}</option>{% endfor %}</select>
        <button>Filtrar</button>
      </form>
      <section class="surface-card">
        <h2 class="section-title">Structured events</h2>
        <div class="table-wrap">
          <table class="table">
            <thead><tr><th>Timestamp</th><th>Source</th><th>Event</th><th>Level</th><th>Message</th><th>Payload</th></tr></thead>
            <tbody>
              {% for item in log_items %}
              <tr><td>{{ item.timestamp }}</td><td>{{ item.source }}</td><td>{{ item.event_type }}</td><td class="{{ 'bad' if item.level == 'error' else 'warn' if item.level == 'warning' else '' }}">{{ item.level }}</td><td>{{ item.message }}</td><td><code>{{ item.payload_preview }}</code></td></tr>
              {% else %}
              <tr><td colspan="6">No matching events.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </section>
      <div class="panel-grid" style="margin-top:18px">
        <section class="surface-card"><h2 class="section-title">Operator log tail</h2><div class="raw">{{ operator_tail }}</div></section>
        <section class="surface-card"><h2 class="section-title">Latest cycle file</h2><div class="raw">{{ cycle_tail }}</div></section>
      </div>
    </div>""" + PAGE_END
    return render_template_string(html, log_items=items, filters=filters, operator_tail=load_recent_operator_tail(), cycle_tail=load_latest_cycle_tail())


@app.route('/chat')
def legacy_chat():
    return redirect(url_for('private_chat'))


@app.route('/private/chat')
@require_private
def private_chat():
    reconcile_bridge_requests(load_history, save_history, append_jsonl_event)
    history = visible_chat_history()
    html = page_start('Chat | Beecthor') + """
    <div class="shell private-shell">
      <div class="private-header"><div><h1 class="private-title">Chat</h1><div class="section-subtitle">Bridge hacia esta misma conversación de Codex en VS Code.</div></div><div class="nav"><a href="/">Pública</a><a href="/private/polymarket">Polymarket</a><a href="/private/logs">Logs</a><a href="/private/chat" style="font-weight:700;color:#fff">Chat</a><a href="/logout">Logout</a></div></div>
            <div class="panel-grid">
                <section class="stream-card">
                    <h2 class="section-title">Bridge chat</h2>
                    <div class="chat" id="history">{% for msg in history %}<div class="bubble {{ 'user' if msg.role == 'user' else 'bot' }}">{{ msg.text }}<div class="muted" style="margin-top:8px">{{ msg.timestamp }}</div></div>{% else %}<div class="muted">No messages yet.</div>{% endfor %}</div>
                    <div class="chat-card" style="margin-top:16px"><textarea id="input" placeholder="Message to Codex..." style="width:100%;height:92px"></textarea><button id="btn" style="margin-top:10px" onclick="send()">Send</button><div id="status" class="status-line"></div></div>
                </section>
                <section class="stream-card">
                    <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap;margin-bottom:14px">
                        <div>
                            <h2 class="section-title" style="margin-bottom:8px">VS Code display</h2>
                            <div class="section-subtitle">Vista read-only del display del servidor. El refresco se dispara solo desde este navegador.</div>
                        </div>
                        <div class="inline-controls">
                            <label class="muted" for="previewInterval">Refresh</label>
                            <select id="previewInterval">
                                <option value="0">Manual</option>
                                <option value="3000">3 s</option>
                                <option value="5000" selected>5 s</option>
                                <option value="10000">10 s</option>
                            </select>
                            <button type="button" class="button-link secondary" onclick="refreshPreview(true)">Refresh now</button>
                        </div>
                    </div>
                    <div id="previewMeta" class="muted" style="margin-bottom:12px">Waiting for first capture...</div>
                    <div class="display-preview-shell">
                        <img id="displayPreview" class="display-preview-image" alt="Read-only VS Code display preview">
                    </div>
                </section>
            </div>
    </div>
    <script>
      const hist=document.getElementById('history'); hist.scrollTop=hist.scrollHeight;
      function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
      function appendBubble(role,text,timestamp){const el=document.createElement('div'); el.className='bubble '+(role==='user'?'user':'bot'); el.innerHTML=esc(text)+'<div class="muted" style="margin-top:8px">'+esc(timestamp)+'</div>'; hist.appendChild(el); hist.scrollTop=hist.scrollHeight;}
      async function waitForBridgeReply(requestId){
        const status=document.getElementById('status');
        const started=Date.now();
        while((Date.now()-started) < 180000){
          const resp=await fetch('/api/private/chat/status/'+encodeURIComponent(requestId));
          const data=await resp.json();
          if(data.status === 'completed' || data.status === 'failed' || data.status === 'timeout'){
            appendBubble('bot', data.response || '(empty response)', data.timestamp || (new Date().toISOString().slice(0,16).replace('T',' ') + ' UTC'));
            status.textContent='';
            return;
          }
          status.textContent='Waiting for Codex...';
          await new Promise(resolve => setTimeout(resolve, data.poll_after_ms || 1500));
        }
        status.textContent='Bridge wait window expired. Refresh in a moment if Codex replies later.';
      }
      async function send(){const input=document.getElementById('input'); const btn=document.getElementById('btn'); const status=document.getElementById('status'); const text=input.value.trim(); if(!text) return; btn.disabled=true; input.value=''; status.textContent='Sending to Codex...'; appendBubble('user', text, new Date().toISOString().slice(0,16).replace('T',' ') + ' UTC'); try{const resp=await fetch('/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})}); const data=await resp.json(); if(data.error){status.textContent=data.error;} else if(data.request_id){await waitForBridgeReply(data.request_id);} else {status.textContent='Bridge did not return a request id.';}}catch(err){status.textContent='Network error';} btn.disabled=false; input.focus();}
            const preview=document.getElementById('displayPreview');
            const previewMeta=document.getElementById('previewMeta');
            const previewInterval=document.getElementById('previewInterval');
            let previewTimer=null;
            let previewPending=false;
            let previewObjectUrl='';
            function previewDelay(){return Number(previewInterval.value || 0);}
            function clearPreviewTimer(){if(previewTimer){clearTimeout(previewTimer); previewTimer=null;}}
            function schedulePreview(){clearPreviewTimer(); const delay=previewDelay(); if(delay <= 0 || document.hidden) return; previewTimer=setTimeout(()=>refreshPreview(false), delay);}
            function setPreviewMeta(text){previewMeta.textContent=text;}
            async function refreshPreview(manual){if(previewPending) return; previewPending=true; setPreviewMeta(manual?'Refreshing preview...':'Updating preview...'); try{const resp=await fetch('/api/private/chat/display.png?ts='+Date.now(), {cache:'no-store'}); if(!resp.ok) throw new Error('Preview unavailable'); const blob=await resp.blob(); const objectUrl=URL.createObjectURL(blob); if(previewObjectUrl) URL.revokeObjectURL(previewObjectUrl); previewObjectUrl=objectUrl; preview.src=objectUrl; setPreviewMeta('Last updated: '+new Date().toLocaleTimeString('es-ES',{hour12:false})+' · Browser-side refresh only');}catch(err){setPreviewMeta('Preview unavailable. The server captures only on demand when this page asks for it.');}finally{previewPending=false; schedulePreview();}}
            previewInterval.addEventListener('change', ()=>{const delay=previewDelay(); if(delay <= 0){clearPreviewTimer(); setPreviewMeta('Auto-refresh disabled. Use Refresh now when needed.'); return;} refreshPreview(false);});
            document.addEventListener('visibilitychange', ()=>{if(document.hidden){clearPreviewTimer(); return;} if(previewDelay() > 0){refreshPreview(false);}});
            refreshPreview(false);
    </script>""" + PAGE_END
    return render_template_string(html, history=history)


@app.route('/send', methods=['POST'])
@require_private
def send():
    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    if not message:
        return {'error': 'Empty message'}, 400
    meta, error = start_bridge_request(
        message,
        history_loader=load_history,
        history_saver=save_history,
        logger=append_jsonl_event,
    )
    if error:
        return {'error': error}, 409
    if not meta:
        return {'error': 'Bridge could not start'}, 500
    if meta.get('status') in {'failed', 'timeout'}:
        return {
            'request_id': meta['request_id'],
            'status': meta.get('status'),
            'response': meta.get('response_text', ''),
            'timestamp': meta.get('response_timestamp', datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')),
        }
    return {'request_id': meta['request_id'], 'status': 'pending'}


@app.route('/api/private/chat/status/<request_id>')
@require_private
def private_chat_status(request_id: str):
    payload, status = get_bridge_request_status(
        request_id,
        history_loader=load_history,
        history_saver=save_history,
        logger=append_jsonl_event,
    )
    return jsonify(payload), status


@app.route('/api/private/chat/display.png')
@require_private
def private_chat_display():
    image_bytes, error = capture_private_chat_display()
    headers = {
        'Cache-Control': 'no-store, max-age=0',
        'Pragma': 'no-cache',
        'Expires': '0',
    }
    if error or not image_bytes:
        return Response(error or 'Display preview unavailable', status=503, mimetype='text/plain', headers=headers)
    return Response(image_bytes, mimetype='image/png', headers=headers)


@app.route('/api/public/summaries')
def api_public_summaries():
    items = load_summary_entries()
    payload = [{'timestamp': item.get('timestamp'), 'video_id': item.get('video_id'), 'video_url': item.get('video_url'), 'robot_score': item.get('robot_score'), 'summary_html': item.get('summary_html')} for item in items]
    return jsonify(payload)


@app.route('/api/public/summaries/<video_id>')
def api_public_summary_detail(video_id: str):
    item = find_summary(video_id)
    if not item:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(item)


@app.route('/api/private/polymarket')
@require_private
def api_private_polymarket():
    return jsonify(build_polymarket_snapshot())


@app.route('/api/private/logs')
@require_private
def api_private_logs():
    source = request.args.get('source', '').strip()
    event_type = request.args.get('event_type', '').strip()
    level = request.args.get('level', '').strip()
    return jsonify(read_jsonl_logs(source=source, event_type=event_type, level=level))


@app.route('/api/mobile-log', methods=['POST'])
def api_mobile_log():
    data = request.get_json(silent=True) or {}
    provided_secret = request.headers.get('X-Log-Secret', '').strip() or data.get('secret', '').strip()
    if not MOBILE_LOG_API_SECRET or provided_secret != MOBILE_LOG_API_SECRET:
        append_jsonl_event('api.mobile', 'log_rejected', 'warning', 'Rejected mobile log event due to invalid secret')
        return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
    source = (data.get('source') or 'phone.unknown').strip()
    event_type = (data.get('event_type') or 'unspecified').strip()
    level = (data.get('level') or 'info').strip()
    message = (data.get('message') or '').strip()
    payload = data.get('payload') or {}
    stored = append_jsonl_event(source, event_type, level, message, payload)
    append_jsonl_event('api.mobile', 'log_received', 'info', 'Accepted mobile log event', {'source': source, 'event_type': event_type})
    return jsonify({'ok': True, 'stored': stored})


if __name__ == '__main__':
    if not CHAT_PASSWORD:
        print('[dashboard] WARNING: COPILOT_CHAT_PASSWORD not set — private area is unsafe.')
    if not MOBILE_LOG_API_SECRET:
        print('[dashboard] WARNING: MOBILE_LOG_API_SECRET not set — mobile log endpoint will reject all events.')
    app.run(host='0.0.0.0', port=5050, debug=False)
