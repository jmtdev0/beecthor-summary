#!/usr/bin/env python3
"""
Copilot Chat Web Interface

Lightweight Flask app that mediates between a mobile browser and the
GitHub Copilot CLI session running on the server. Deployed via VS Code
Port Forwarding.

Setup:
  1. Add to polymarket_assistant/.env:
       COPILOT_CHAT_PASSWORD=your-password
       FLASK_SECRET_KEY=any-long-random-string
  2. pip install flask
  3. python server/copilot_chat.py
  4. Expose port 5050 via VS Code Port Forwarding (public visibility)
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, redirect, render_template_string, request, session, url_for

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / 'polymarket_assistant' / '.env'
HISTORY_FILE = Path(__file__).resolve().parent / 'copilot_chat_history.json'

load_dotenv(ENV_FILE)

CHAT_PASSWORD = os.environ.get('COPILOT_CHAT_PASSWORD', '')
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change-me-in-env')

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Copilot Chat</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;
         display:flex;align-items:center;justify-content:center;height:100dvh}
    .card{background:#161b22;border:1px solid #30363d;border-radius:12px;
          padding:2rem;width:100%;max-width:340px}
    h1{font-size:1.1rem;margin-bottom:1.5rem;text-align:center;color:#58a6ff}
    input{width:100%;padding:.75rem;background:#0d1117;border:1px solid #30363d;
          border-radius:8px;color:#e6edf3;font-size:1rem;margin-bottom:1rem}
    button{width:100%;padding:.75rem;background:#238636;border:none;
           border-radius:8px;color:#fff;font-size:1rem;cursor:pointer}
    button:hover{background:#2ea043}
    .err{color:#f85149;font-size:.85rem;margin-bottom:.75rem}
  </style>
</head>
<body>
  <div class="card">
    <h1>Copilot Chat</h1>
    {% if error %}<p class="err">{{ error }}</p>{% endif %}
    <form method="POST">
      <input type="password" name="password" placeholder="Password" autofocus autocomplete="current-password">
      <button type="submit">Enter</button>
    </form>
  </div>
</body>
</html>"""

CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Copilot Chat</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,sans-serif;background:#0d1117;color:#e6edf3;
         display:flex;flex-direction:column;height:100dvh}
    header{display:flex;align-items:center;justify-content:space-between;
           padding:.85rem 1rem;border-bottom:1px solid #30363d;background:#161b22;flex-shrink:0}
    header h1{font-size:.95rem;color:#58a6ff}
    header a{font-size:.8rem;color:#8b949e;text-decoration:none}
    #history{flex:1;overflow-y:auto;padding:1rem;display:flex;flex-direction:column;gap:.85rem}
    .wrap-user{display:flex;flex-direction:column;align-items:flex-end}
    .wrap-bot{display:flex;flex-direction:column;align-items:flex-start}
    .bubble{max-width:88%;padding:.7rem .95rem;border-radius:12px;font-size:.88rem;
            line-height:1.55;white-space:pre-wrap;word-break:break-word}
    .user{background:#1f6feb;border-bottom-right-radius:3px}
    .bot{background:#161b22;border:1px solid #30363d;border-bottom-left-radius:3px}
    .meta{font-size:.68rem;color:#8b949e;margin-top:.2rem}
    footer{padding:.85rem 1rem;border-top:1px solid #30363d;background:#161b22;flex-shrink:0}
    textarea{width:100%;padding:.7rem;background:#0d1117;border:1px solid #30363d;
             border-radius:8px;color:#e6edf3;font-size:.9rem;resize:none;height:72px;
             font-family:inherit}
    #btn{margin-top:.45rem;width:100%;padding:.6rem;background:#238636;border:none;
         border-radius:8px;color:#fff;font-size:.9rem;cursor:pointer}
    #btn:disabled{background:#21262d;color:#8b949e;cursor:not-allowed}
    #status{font-size:.75rem;color:#8b949e;margin-top:.35rem;min-height:1rem}
    .empty{color:#8b949e;font-size:.85rem;text-align:center;margin:auto}
  </style>
</head>
<body>
  <header>
    <h1>Copilot Chat</h1>
    <a href="/logout">Logout</a>
  </header>
  <div id="history">
    {% if not history %}
      <p class="empty">No messages yet.</p>
    {% endif %}
    {% for msg in history %}
      {% if msg.role == 'user' %}
        <div class="wrap-user">
          <div class="bubble user">{{ msg.text }}</div>
          <div class="meta">{{ msg.timestamp }}</div>
        </div>
      {% else %}
        <div class="wrap-bot">
          <div class="bubble bot">{{ msg.text }}</div>
          <div class="meta">{{ msg.timestamp }}</div>
        </div>
      {% endif %}
    {% endfor %}
  </div>
  <footer>
    <textarea id="input" placeholder="Message to Copilot..."></textarea>
    <button id="btn" onclick="send()">Send</button>
    <div id="status"></div>
  </footer>
  <script>
    const hist = document.getElementById('history');
    hist.scrollTop = hist.scrollHeight;

    function esc(t){
      return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }
    function ts(){return new Date().toISOString().slice(0,16).replace('T',' ')+' UTC';}
    function appendBubble(role, text, timestamp){
      const wrap = document.createElement('div');
      wrap.className = role==='user' ? 'wrap-user' : 'wrap-bot';
      wrap.innerHTML = `<div class="bubble ${role==='user'?'user':'bot'}">${esc(text)}</div>`
                     + `<div class="meta">${esc(timestamp)}</div>`;
      const empty = hist.querySelector('.empty');
      if(empty) empty.remove();
      hist.appendChild(wrap);
      hist.scrollTop = hist.scrollHeight;
    }

    async function send(){
      const input = document.getElementById('input');
      const btn   = document.getElementById('btn');
      const status= document.getElementById('status');
      const text  = input.value.trim();
      if(!text) return;

      btn.disabled = true;
      input.value  = '';
      appendBubble('user', text, ts());
      status.textContent = 'Waiting for Copilot...';

      try{
        const resp = await fetch('/send',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({message: text})
        });
        const data = await resp.json();
        if(data.error){
          status.textContent = 'Error: '+data.error;
        } else {
          appendBubble('bot', data.response, data.timestamp);
          status.textContent = '';
        }
      }catch(e){
        status.textContent = 'Network error.';
      }
      btn.disabled = false;
      input.focus();
    }

    document.getElementById('input').addEventListener('keydown', function(e){
      if(e.key==='Enter' && !e.shiftKey){e.preventDefault();send();}
    });
  </script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_history() -> list:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_history(history: list) -> None:
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')


def run_copilot(message: str) -> str:
    try:
        result = subprocess.run(
            ['copilot', '-p', message, '--continue', '-s', '--allow-all'],
            capture_output=True,
            text=True,
            encoding='utf-8',
            timeout=120,
            cwd=str(REPO_ROOT),
            env={**os.environ, 'HOME': '/root', 'LANG': 'en_US.UTF-8', 'PYTHONIOENCODING': 'utf-8'},
        )
        output = result.stdout.strip()
        if not output:
            output = result.stderr.strip() or f'(no output, exit code {result.returncode})'
        return output
    except subprocess.TimeoutExpired:
        return '(timeout — Copilot took more than 120 seconds)'
    except FileNotFoundError:
        return '(copilot CLI not found in PATH)'
    except Exception as exc:
        return f'(error: {exc})'


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/', methods=['GET', 'POST'])
def login():
    if session.get('authenticated'):
        return redirect(url_for('chat'))
    error = None
    if request.method == 'POST':
        if CHAT_PASSWORD and request.form.get('password') == CHAT_PASSWORD:
            session['authenticated'] = True
            return redirect(url_for('chat'))
        error = 'Wrong password.'
    return render_template_string(LOGIN_HTML, error=error)


@app.route('/chat')
def chat():
    if not session.get('authenticated'):
        return redirect(url_for('login'))
    return render_template_string(CHAT_HTML, history=load_history())


@app.route('/send', methods=['POST'])
def send():
    if not session.get('authenticated'):
        return {'error': 'Unauthorized'}, 401
    data = request.get_json()
    message = (data or {}).get('message', '').strip()
    if not message:
        return {'error': 'Empty message'}, 400

    response = run_copilot(message)
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')

    history = load_history()
    history.append({'role': 'user',   'text': message,  'timestamp': timestamp})
    history.append({'role': 'copilot','text': response, 'timestamp': timestamp})
    save_history(history)

    return {'response': response, 'timestamp': timestamp}


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


if __name__ == '__main__':
    if not CHAT_PASSWORD:
        print('[chat] WARNING: COPILOT_CHAT_PASSWORD not set — anyone can log in!')
    app.run(host='0.0.0.0', port=5050, debug=False)
