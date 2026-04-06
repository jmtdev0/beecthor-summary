#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template_string, request, session, url_for

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
DATA_API_HOST = 'https://data-api.polymarket.com'
LOG_DIR = Path(os.environ.get('DASHBOARD_LOG_DIR') or (REPO_ROOT / 'server_runtime_logs'))
LOG_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.secret_key = SECRET_KEY

STYLE = """
<style>
body{margin:0;font-family:-apple-system,Segoe UI,sans-serif;background:#0b1220;color:#e6edf7}
a{color:#7cb7ff;text-decoration:none} .shell{max-width:1120px;margin:0 auto;padding:24px}
.top{display:flex;justify-content:space-between;gap:12px;align-items:center;border-bottom:1px solid #243044;padding-bottom:16px;margin-bottom:20px}
.nav{display:flex;gap:12px;flex-wrap:wrap}.card{background:#111827;border:1px solid #243044;border-radius:14px;padding:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}.list{display:flex;flex-direction:column;gap:12px}
.item{background:#0f172a;border:1px solid #243044;border-radius:12px;padding:12px}.muted{color:#99a9bf}.good{color:#22c55e}.bad{color:#ef4444}.warn{color:#f59e0b}
.big{font-size:1.8rem;font-weight:700;margin:6px 0}.table{width:100%;border-collapse:collapse}.table th,.table td{padding:10px 12px;border-bottom:1px solid #243044;text-align:left;vertical-align:top}
.table th{color:#99a9bf;font-size:.85rem}.table-wrap{overflow:auto;border:1px solid #243044;border-radius:12px}.chat{display:flex;flex-direction:column;gap:10px;max-height:60dvh;overflow:auto}
.bubble{padding:12px;border-radius:12px;white-space:pre-wrap}.user{background:#1d4ed8}.bot{background:#0f172a;border:1px solid #243044}.raw{background:#08101c;border:1px solid #243044;border-radius:12px;padding:12px;white-space:pre-wrap;max-height:260px;overflow:auto}
input,select,textarea{background:#0b1220;color:#e6edf7;border:1px solid #243044;border-radius:10px;padding:10px 12px} button{background:#2563eb;color:#fff;border:none;border-radius:10px;padding:10px 14px;cursor:pointer}
</style>
"""

LOGIN_HTML = STYLE + """
<div class="shell"><div class="card" style="max-width:360px;margin:10vh auto 0">
<h1>Zona privada</h1><p class="muted">Polymarket, logs y chat</p>
{% if error %}<p class="bad">{{ error }}</p>{% endif %}
<form method="POST"><input type="password" name="password" placeholder="Password" style="width:100%;margin:12px 0"><button style="width:100%">Entrar</button></form>
</div></div>"""


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


def timestamp_to_local(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.astimezone().strftime('%Y-%m-%d %H:%M')
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


def load_summary_entries() -> list[dict[str, Any]]:
    entries = load_json(ANALYSES_LOG_PATH, [])
    items = []
    for entry in reversed(entries):
        message = entry.get('message', '')
        items.append({
            **entry,
            'timestamp_local': timestamp_to_local(entry.get('timestamp', '')),
            'summary_html': extract_message_section(message, '📌 <b>Resumen</b>', '🔍 <b>Análisis completo</b>') or '<span class="muted">Sin resumen visible</span>',
            'message_html': message,
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
    if re.search(rf'on-{month}-\d{{1,2}}', normalized) or re.search(rf'on {month} \d{{1,2}}', normalized):
        return 'daily'
    if re.search(rf'{month}-\d{{1,2}}-{month}-\d{{1,2}}', normalized):
        return 'weekly'
    return 'unknown'


def fetch_closed_positions_live() -> list[dict[str, Any]]:
    user = POLY_FUNDER or POLY_SIGNER_ADDRESS
    if not user:
        return []
    try:
        response = requests.get(f'{DATA_API_HOST}/closed-positions', params={'user': user, 'limit': 200, 'offset': 0}, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception:
        return []


def build_polymarket_snapshot() -> dict[str, Any]:
    account_state = load_json(ACCOUNT_STATE_PATH, {})
    trade_log = load_json(TRADE_LOG_PATH, [])
    pending_orders = load_json(PENDING_ORDERS_PATH, [])
    open_positions = account_state.get('open_positions', [])
    closed_positions = fetch_closed_positions_live()
    portfolio_value = round(float(account_state.get('cash_available', 0.0)) + sum(float(p.get('current_value_usd', 0.0)) for p in open_positions), 6)
    unrealized_pnl = round(sum(float(p.get('cash_pnl_usd', 0.0)) for p in open_positions), 6)
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
        {'label': 'Portfolio', 'value': f'{portfolio_value:.2f}$', 'caption': 'cash + open positions', 'css_class': ''},
        {'label': 'Cash', 'value': f"{float(account_state.get('cash_available', 0.0)):.2f}$", 'caption': '', 'css_class': ''},
        {'label': 'PnL realizado', 'value': f"{float(account_state.get('realized_pnl', 0.0)):.2f}$", 'caption': '', 'css_class': 'good' if float(account_state.get('realized_pnl', 0.0)) >= 0 else 'bad'},
        {'label': 'PnL no realizado', 'value': f'{unrealized_pnl:.2f}$', 'caption': 'posiciones abiertas', 'css_class': 'good' if unrealized_pnl >= 0 else 'bad'},
        {'label': 'Operaciones', 'value': str(total_operations), 'caption': f'{total_closed} cerradas · {len(open_positions)} abiertas', 'css_class': ''},
        {'label': 'Aciertos / fallos', 'value': f'{wins} / {losses}', 'caption': 'closed positions', 'css_class': ''},
        {'label': 'Win rate', 'value': f'{win_rate:.1f}%', 'caption': 'closed positions', 'css_class': 'good' if win_rate >= 50 else 'bad'},
        {'label': 'Daily / Weekly', 'value': f'{daily_count} / {weekly_count}', 'caption': 'classified positions', 'css_class': ''},
    ]
    positions = [{
        **position,
        'category': classify_market_bucket(position.get('event_slug') or position.get('market_slug') or ''),
        'shares': round(float(position.get('shares', 0.0)), 4),
        'avg_price': round(float(position.get('avg_price', 0.0)), 4),
        'current_price': round(float(position.get('current_price', 0.0)), 4),
        'current_value_usd': round(float(position.get('current_value_usd', 0.0)), 4),
        'cash_pnl_usd': round(float(position.get('cash_pnl_usd', 0.0)), 4),
    } for position in open_positions]
    recent_operations = []
    for entry in reversed(trade_log):
        execution = entry.get('execution') or {}
        details = execution.get('details') or {}
        if entry.get('type') == 'trade_opened':
            market_slug = entry.get('market_slug', '')
            recent_operations.append({'timestamp': entry.get('timestamp', ''), 'type': 'trade_opened', 'market_slug': market_slug, 'category': classify_market_bucket(entry.get('event_slug') or market_slug), 'status': entry.get('status', '')})
        elif details:
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
    html = STYLE + """
    <div class="shell">
      <div class="top"><div><h1 style="margin:0">Beecthor Dashboard</h1><div class="muted">Galería pública de resúmenes</div></div><div class="nav"><a href="/">Resúmenes</a><a href="/login">Zona privada</a></div></div>
      <div class="grid">
        {% for item in items %}
        <article class="card">
          <div class="muted">{{ item.timestamp_local }}</div>
          <h2><a href="{{ url_for('public_video_detail', video_id=item.video_id) }}">{{ item.video_id }}</a></h2>
          <div class="muted">Robot score {{ item.robot_score }}</div>
          <div style="margin-top:12px">{{ item.summary_html|safe }}</div>
        </article>
        {% endfor %}
      </div>
    </div>"""
    return render_template_string(html, items=items)


@app.route('/videos/<video_id>')
def public_video_detail(video_id: str):
    item = find_summary(video_id)
    if not item:
        return ('Not found', 404)
    html = STYLE + """
    <div class="shell">
      <div class="top"><div><h1 style="margin:0">{{ item.video_id }}</h1><div class="muted">{{ item.timestamp_local }}</div></div><div class="nav"><a href="/">Volver</a><a href="/login">Zona privada</a></div></div>
      <div class="card">{{ item.message_html|safe }}</div>
    </div>"""
    return render_template_string(html, item=item)


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
    html = STYLE + """
    <div class="shell">
      <div class="top"><div><h1 style="margin:0">Zona privada</h1><div class="muted">Polymarket dashboard</div></div><div class="nav"><a href="/">Pública</a><a href="/private/polymarket">Polymarket</a><a href="/private/logs">Logs</a><a href="/private/chat">Chat</a><a href="/logout">Logout</a></div></div>
      <div class="grid">{% for metric in metrics %}<div class="card"><div class="muted">{{ metric.label }}</div><div class="big {{ metric.css_class }}">{{ metric.value }}</div><div class="muted">{{ metric.caption }}</div></div>{% endfor %}</div>
      <div class="grid" style="margin-top:16px">
        <div class="card"><h2>Posiciones abiertas</h2><div class="list">{% for position in positions %}<div class="item"><strong>{{ position.market_title or position.market_slug }}</strong><div class="muted">{{ position.position_side }} · {{ position.category }}</div><div>Shares: <b>{{ position.shares }}</b> · Avg: <b>{{ position.avg_price }}</b> · Now: <b>{{ position.current_price }}</b></div><div>Value: <b>{{ position.current_value_usd }}$</b> · PnL: <span class="{{ 'good' if position.cash_pnl_usd >= 0 else 'bad' }}">{{ position.cash_pnl_usd }}$</span></div></div>{% else %}<div class="item">No open positions.</div>{% endfor %}</div></div>
        <div class="card"><h2>Pipeline server → móvil</h2><div class="item"><strong>Pending actions</strong><div>{{ pipeline.pending_count }} pending order(s)</div></div><div class="list">{% for item in pipeline.pending_orders %}<div class="item"><strong>{{ item.type }} · {{ item.market_slug }}</strong><div class="muted">{{ item.order_id or 'no-order-id' }}</div><div>{{ item.side }} · {{ item.outcome }} · {{ item.status }}</div></div>{% else %}<div class="item">No pending actions.</div>{% endfor %}</div></div>
      </div>
      <div class="card" style="margin-top:16px"><h2>Operaciones recientes</h2><div class="table-wrap"><table class="table"><thead><tr><th>Timestamp</th><th>Type</th><th>Market</th><th>Category</th><th>Status</th></tr></thead><tbody>{% for item in recent_operations %}<tr><td>{{ item.timestamp }}</td><td>{{ item.type }}</td><td>{{ item.market_slug }}</td><td>{{ item.category }}</td><td>{{ item.status }}</td></tr>{% else %}<tr><td colspan="5">No recent operations.</td></tr>{% endfor %}</tbody></table></div></div>
    </div>"""
    return render_template_string(html, **snapshot)


@app.route('/private/logs')
@require_private
def private_logs():
    filters = {'source': request.args.get('source', '').strip(), 'event_type': request.args.get('event_type', '').strip(), 'level': request.args.get('level', '').strip()}
    items = read_jsonl_logs(source=filters['source'], event_type=filters['event_type'], level=filters['level'])
    html = STYLE + """
    <div class="shell">
      <div class="top"><div><h1 style="margin:0">Zona privada</h1><div class="muted">Logs dashboard</div></div><div class="nav"><a href="/">Pública</a><a href="/private/polymarket">Polymarket</a><a href="/private/logs">Logs</a><a href="/private/chat">Chat</a><a href="/logout">Logout</a></div></div>
      <form class="card" method="GET" style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px"><input type="text" name="source" placeholder="source" value="{{ filters.source }}"><input type="text" name="event_type" placeholder="event type" value="{{ filters.event_type }}"><select name="level"><option value="">all levels</option>{% for option in ['info','warning','error'] %}<option value="{{ option }}" {{ 'selected' if filters.level == option else '' }}>{{ option }}</option>{% endfor %}</select><button>Filtrar</button></form>
      <div class="card"><h2>Structured events</h2><div class="table-wrap"><table class="table"><thead><tr><th>Timestamp</th><th>Source</th><th>Event</th><th>Level</th><th>Message</th><th>Payload</th></tr></thead><tbody>{% for item in log_items %}<tr><td>{{ item.timestamp }}</td><td>{{ item.source }}</td><td>{{ item.event_type }}</td><td class="{{ 'bad' if item.level == 'error' else 'warn' if item.level == 'warning' else '' }}">{{ item.level }}</td><td>{{ item.message }}</td><td><code>{{ item.payload_preview }}</code></td></tr>{% else %}<tr><td colspan="6">No matching events.</td></tr>{% endfor %}</tbody></table></div></div>
      <div class="grid" style="margin-top:16px"><div class="card"><h2>Operator log tail</h2><div class="raw">{{ operator_tail }}</div></div><div class="card"><h2>Latest cycle file</h2><div class="raw">{{ cycle_tail }}</div></div></div>
    </div>"""
    return render_template_string(html, log_items=items, filters=filters, operator_tail=load_recent_operator_tail(), cycle_tail=load_latest_cycle_tail())


@app.route('/chat')
def legacy_chat():
    return redirect(url_for('private_chat'))


@app.route('/private/chat')
@require_private
def private_chat():
    history = load_history()
    html = STYLE + """
    <div class="shell">
      <div class="top"><div><h1 style="margin:0">Zona privada</h1><div class="muted">Copilot chat</div></div><div class="nav"><a href="/">Pública</a><a href="/private/polymarket">Polymarket</a><a href="/private/logs">Logs</a><a href="/private/chat">Chat</a><a href="/logout">Logout</a></div></div>
      <div class="chat" id="history">{% for msg in history %}<div class="bubble {{ 'user' if msg.role == 'user' else 'bot' }}">{{ msg.text }}<div class="muted" style="margin-top:8px">{{ msg.timestamp }}</div></div>{% else %}<div class="muted">No messages yet.</div>{% endfor %}</div>
      <div class="card" style="margin-top:16px"><textarea id="input" placeholder="Message to Copilot..." style="width:100%;height:92px"></textarea><button id="btn" style="margin-top:10px" onclick="send()">Send</button><div id="status" class="muted" style="margin-top:10px"></div></div>
    </div>
    <script>
      const hist=document.getElementById('history'); hist.scrollTop=hist.scrollHeight;
      function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
      function appendBubble(role,text,timestamp){const el=document.createElement('div'); el.className='bubble '+(role==='user'?'user':'bot'); el.innerHTML=esc(text)+'<div class="muted" style="margin-top:8px">'+esc(timestamp)+'</div>'; hist.appendChild(el); hist.scrollTop=hist.scrollHeight;}
      async function send(){const input=document.getElementById('input'); const btn=document.getElementById('btn'); const status=document.getElementById('status'); const text=input.value.trim(); if(!text) return; btn.disabled=true; input.value=''; status.textContent='Waiting for Copilot...'; appendBubble('user', text, new Date().toISOString().slice(0,16).replace('T',' ') + ' UTC'); try{const resp=await fetch('/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})}); const data=await resp.json(); if(data.error){status.textContent=data.error;} else {appendBubble('bot', data.response, data.timestamp); status.textContent='';}}catch(err){status.textContent='Network error';} btn.disabled=false; input.focus();}
    </script>"""
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
