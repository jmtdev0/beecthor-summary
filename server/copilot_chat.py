#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

_CET = ZoneInfo('Europe/Madrid')
from functools import wraps
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for

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
.metric-card-link{
  display:block;
  color:inherit;
  text-decoration:none;
}
.metric-card-link:hover .metric-card{
  border-color:rgba(62,166,255,.28);
  transform:translateY(-2px);
}
.metric-card-link .metric-card{
  transition:border-color .18s ease, transform .18s ease;
}
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
.timeline-list{display:flex;flex-direction:column;gap:14px}
.timeline-item{
  background:rgba(255,255,255,.03);
  border:1px solid rgba(255,255,255,.06);
  border-radius:18px;
  padding:16px 18px;
}
.timeline-top{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}
.timeline-title{font-weight:700;line-height:1.4;color:#eef4ff}
.timeline-meta{font-size:.9rem;color:#98a7bb;margin-top:8px;line-height:1.5}
.badge{
  display:inline-flex;align-items:center;justify-content:center;
  border-radius:999px;padding:6px 10px;font-size:.76rem;font-weight:800;
  letter-spacing:.04em;text-transform:uppercase;white-space:nowrap
}
.badge.good{background:rgba(34,197,94,.14);color:#7cf29f}
.badge.bad{background:rgba(239,68,68,.14);color:#ff9a9a}
.badge.warn{background:rgba(245,158,11,.14);color:#ffd27a}
.badge.info{background:rgba(62,166,255,.14);color:#91cbff}
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


def save_history(history: list[dict[str, Any]]) -> None:
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def load_history() -> list[dict[str, Any]]:
    return load_json(HISTORY_FILE, [])


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


def _format_detail_timestamp(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).astimezone(_CET)
        return dt.strftime('%d/%m/%Y %H:%M')
    except Exception:
        return timestamp


def _format_epoch_timestamp(timestamp: Any) -> str:
    try:
        dt = datetime.fromtimestamp(float(timestamp), tz=UTC).astimezone(_CET)
        return dt.strftime('%d/%m/%Y %H:%M')
    except Exception:
        return str(timestamp)


def _format_probability(probability: Any) -> str:
    value = safe_float(probability, default=-1.0)
    if value < 0:
        return ''
    return f'{value:.2f}'


def _normalize_execution_details(raw_details: Any) -> list[dict[str, Any]]:
    if isinstance(raw_details, list):
        return [item for item in raw_details if isinstance(item, dict)]
    if isinstance(raw_details, dict) and raw_details:
        return [raw_details]
    return []


def build_operations_timeline() -> list[dict[str, Any]]:
    trade_log = load_json(TRADE_LOG_PATH, [])
    closed_positions = fetch_closed_positions_live()

    close_reason_map: dict[str, str] = {}
    for entry in trade_log:
        if entry.get('type') != 'trade_closed':
            continue
        market_slug = entry.get('market_slug', '')
        if market_slug and market_slug not in close_reason_map:
            close_reason_map[market_slug] = str(entry.get('close_reason', '')).strip()

    timeline: list[dict[str, Any]] = []

    for entry in trade_log:
        entry_type = entry.get('type')
        if entry_type == 'trade_opened':
            market_title = entry.get('market_title') or entry.get('market_slug') or 'Unknown market'
            side = entry.get('position_side') or '?'
            stake = safe_float(entry.get('entry_cost_usd'))
            probability = _format_probability(entry.get('entry_probability'))
            meta_bits = [f'{stake:.2f}$ {side}']
            if probability:
                meta_bits.append(f'at {probability} chance')
            timeline.append(
                {
                    'timestamp': entry.get('timestamp', ''),
                    'timestamp_label': _format_detail_timestamp(entry.get('timestamp', '')),
                    'title': market_title,
                    'status': 'OPEN',
                    'status_class': 'info',
                    'details': ' '.join(meta_bits),
                    'market_slug': entry.get('market_slug', ''),
                }
            )
            continue

        if entry_type == 'force_bet':
            decision = entry.get('decision') or {}
            new_position = decision.get('new_position') or {}
            if not (entry.get('execution') or {}).get('performed'):
                continue
            market_title = new_position.get('market_slug') or 'Unknown market'
            side = new_position.get('outcome') or '?'
            stake = safe_float(new_position.get('stake_usd'))
            timeline.append(
                {
                    'timestamp': entry.get('timestamp', ''),
                    'timestamp_label': _format_detail_timestamp(entry.get('timestamp', '')),
                    'title': market_title,
                    'status': 'OPEN',
                    'status_class': 'info',
                    'details': f'{stake:.2f}$ {side} via force-bet',
                    'market_slug': new_position.get('market_slug', ''),
                }
            )
            continue

        if entry_type != 'cycle_run':
            continue

        decision = entry.get('decision') or {}
        if decision.get('action') != 'OPEN_POSITION':
            continue
        if not (entry.get('execution') or {}).get('performed'):
            continue

        details_list = _normalize_execution_details((entry.get('execution') or {}).get('details'))
        for details in details_list:
            market_slug = details.get('market_slug', '')
            outcome = details.get('outcome', '')
            stake = safe_float(details.get('stake_usd'))
            probability = _format_probability((decision.get('new_position') or {}).get('max_entry_probability'))
            detail_text = f'{stake:.2f}$ {outcome}'.strip()
            if probability and probability != '0.00':
                detail_text += f' at {probability} chance'
            timeline.append(
                {
                    'timestamp': entry.get('timestamp', ''),
                    'timestamp_label': _format_detail_timestamp(entry.get('timestamp', '')),
                    'title': market_slug or 'Unknown market',
                    'status': 'OPEN',
                    'status_class': 'info',
                    'details': detail_text,
                    'market_slug': market_slug,
                }
            )

    for item in closed_positions:
        market_slug = item.get('slug', '')
        pnl = safe_float(item.get('realizedPnl'))
        close_reason = close_reason_map.get(market_slug, '')
        if close_reason == 'take_profit':
            status = 'TAKE PROFIT'
            status_class = 'warn'
        elif pnl > 0:
            status = 'WON'
            status_class = 'good'
        elif pnl < 0:
            status = 'LOST'
            status_class = 'bad'
        else:
            status = 'CLOSED'
            status_class = 'info'
        probability = _format_probability(item.get('curPrice'))
        details = []
        if probability:
            details.append(f'at {probability} chance')
        details.append(f'PnL {pnl:+.2f}$')
        timeline.append(
            {
                'timestamp': str(item.get('timestamp', '')),
                'timestamp_label': _format_epoch_timestamp(item.get('timestamp')),
                'title': item.get('title') or market_slug or 'Unknown market',
                'status': status,
                'status_class': status_class,
                'details': ' · '.join(details),
                'market_slug': market_slug,
            }
        )

    timeline.sort(key=lambda item: item.get('timestamp', ''), reverse=True)
    return timeline


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
                'title': p.get('title', p.get('market_slug', '')),
                'outcome': p.get('outcome', ''),
                'prob': f"{safe_float(p.get('cur_price')) * 100:.0f}¢",
                'pnl': safe_float(p.get('cash_pnl_usd')),
            }
            for p in open_positions
        ]},
        {'label': 'Aciertos / fallos', 'value': f'{wins} / {losses}', 'caption': 'closed positions', 'css_class': ''},
        {'label': 'Win rate', 'value': f'{win_rate:.1f}%', 'caption': 'closed positions', 'css_class': 'good' if win_rate >= 50 else 'bad'},
        {'label': 'Daily / Weekly', 'value': f'{daily_count} / {weekly_count}', 'caption': 'classified positions', 'css_class': ''},
    ]
    for metric in metrics:
        if metric['label'] == 'Operaciones':
            metric['url'] = url_for('private_operations')
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
}

PHONE_SSH = ['ssh', '-p', '2222', '-o', 'StrictHostKeyChecking=no', 'jmart@localhost']


@app.route('/private/trigger/<process>', methods=['POST'])
@require_private
def trigger_process(process: str):
    if process == 'cycle':
        subprocess.Popen(
            ['bash', '/root/run_polymarket_cycle.sh'],
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
            PHONE_SSH + ['python ~/polymarket_executor.py'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif process == 'monitor_executor':
        subprocess.Popen(
            PHONE_SSH + ['python ~/polymarket_monitor_executor.py'],
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
        {% if metric.url is defined %}
        <a class="metric-card-link" href="{{ metric.url }}">
        {% endif %}
        <section class="metric-card">
          <div class="metric-label">{{ metric.label }}</div>
          <div class="big {{ metric.css_class }}">{{ metric.value }}</div>
          <div class="muted">{{ metric.caption }}</div>
          {% if metric.open_positions is defined and metric.open_positions %}
          <details style="margin-top:8px">
            <summary style="cursor:pointer;font-size:.78rem;color:#aaa;list-style:none">▸ ver abiertas</summary>
            <div style="margin-top:6px;display:flex;flex-direction:column;gap:4px">
              {% for pos in metric.open_positions %}
              <div style="font-size:.78rem;padding:5px 7px;background:#1e1e1e;border-radius:6px;display:flex;justify-content:space-between;gap:8px">
                <span style="color:#ccc;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px" title="{{ pos.title }}">{{ pos.outcome }} · {{ pos.title }}</span>
                <span style="white-space:nowrap">
                  <span style="color:#888">{{ pos.prob }}</span>
                  <span style="margin-left:6px;{{ 'color:#4caf50' if pos.pnl >= 0 else 'color:#f44336' }}">{{ '%+.2f$' % pos.pnl }}</span>
                </span>
              </div>
              {% endfor %}
            </div>
          </details>
          {% endif %}
        </section>
        {% if metric.url is defined %}
        </a>
        {% endif %}
        {% endfor %}
      </div>
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
    </div>""" + PAGE_END
    triggered = request.args.get('triggered', '')
    triggered_label = TRIGGER_LABELS.get(triggered, triggered)
    return render_template_string(html, trace_lanes=trace_lanes, triggered=triggered, triggered_label=triggered_label, **snapshot)


@app.route('/private/operations')
@require_private
def private_operations():
    timeline = build_operations_timeline()
    html = page_start('Operaciones | Beecthor') + """
    <div class="shell private-shell">
      <div class="private-header">
        <div>
          <h1 class="private-title">Operaciones</h1>
          <div class="section-subtitle">Histórico combinado de aperturas y resoluciones usando el log local y Polymarket live.</div>
        </div>
        <div class="nav"><a href="/">Pública</a><a href="/private/polymarket">Polymarket</a><a href="/private/operations" style="font-weight:700;color:#fff">Operaciones</a><a href="/private/logs">Logs</a><a href="/private/chat">Chat</a><a href="/logout">Logout</a></div>
      </div>
      <section class="surface-card">
        <h2 class="section-title">Timeline completo</h2>
        <div class="timeline-list">
          {% for item in timeline %}
          <article class="timeline-item">
            <div class="timeline-top">
              <div>
                <div class="muted">{{ item.timestamp_label }}</div>
                <div class="timeline-title">{{ item.title }}</div>
                <div class="timeline-meta">{{ item.details }}</div>
              </div>
              <div class="badge {{ item.status_class }}">{{ item.status }}</div>
            </div>
          </article>
          {% else %}
          <article class="timeline-item">
            <div class="timeline-title">No operations found.</div>
          </article>
          {% endfor %}
        </div>
      </section>
    </div>""" + PAGE_END
    return render_template_string(html, timeline=timeline)


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
    history = load_history()
    html = page_start('Chat | Beecthor') + """
    <div class="shell private-shell">
      <div class="private-header"><div><h1 class="private-title">Chat</h1><div class="section-subtitle">Superficie técnica para seguir usando la sesión de Copilot del servidor.</div></div><div class="nav"><a href="/">Pública</a><a href="/private/polymarket">Polymarket</a><a href="/private/logs">Logs</a><a href="/private/chat" style="font-weight:700;color:#fff">Chat</a><a href="/logout">Logout</a></div></div>
      <div class="chat" id="history">{% for msg in history %}<div class="bubble {{ 'user' if msg.role == 'user' else 'bot' }}">{{ msg.text }}<div class="muted" style="margin-top:8px">{{ msg.timestamp }}</div></div>{% else %}<div class="muted">No messages yet.</div>{% endfor %}</div>
      <div class="chat-card" style="margin-top:16px"><textarea id="input" placeholder="Message to Copilot..." style="width:100%;height:92px"></textarea><button id="btn" style="margin-top:10px" onclick="send()">Send</button><div id="status" class="status-line"></div></div>
    </div>
    <script>
      const hist=document.getElementById('history'); hist.scrollTop=hist.scrollHeight;
      function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
      function appendBubble(role,text,timestamp){const el=document.createElement('div'); el.className='bubble '+(role==='user'?'user':'bot'); el.innerHTML=esc(text)+'<div class="muted" style="margin-top:8px">'+esc(timestamp)+'</div>'; hist.appendChild(el); hist.scrollTop=hist.scrollHeight;}
      async function send(){const input=document.getElementById('input'); const btn=document.getElementById('btn'); const status=document.getElementById('status'); const text=input.value.trim(); if(!text) return; btn.disabled=true; input.value=''; status.textContent='Waiting for Copilot...'; appendBubble('user', text, new Date().toISOString().slice(0,16).replace('T',' ') + ' UTC'); try{const resp=await fetch('/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})}); const data=await resp.json(); if(data.error){status.textContent=data.error;} else {appendBubble('bot', data.response, data.timestamp); status.textContent='';}}catch(err){status.textContent='Network error';} btn.disabled=false; input.focus();}
    </script>""" + PAGE_END
    return render_template_string(html, history=history)


@app.route('/send', methods=['POST'])
@require_private
def send():
    data = request.get_json(silent=True) or {}
    message = data.get('message', '').strip()
    if not message:
        return {'error': 'Empty message'}, 400
    response = run_copilot(message)
    timestamp = datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')
    history = load_history()
    history.append({'role': 'user', 'text': message, 'timestamp': timestamp})
    history.append({'role': 'copilot', 'text': response, 'timestamp': timestamp})
    save_history(history)
    append_jsonl_event('app.chat', 'message_saved', 'info', 'Chat history updated')
    return {'response': response, 'timestamp': timestamp}


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
