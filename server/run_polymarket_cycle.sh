#!/bin/bash
set -euo pipefail

REPO_ROOT=/root/beecthor-summary
VENV_PYTHON=/root/beecthor-summary/.venv/bin/python
RUN_CYCLE=/root/beecthor-summary/polymarket_assistant/run_cycle_codex.py
SNAPSHOT_HELPER=/root/beecthor-summary/polymarket_assistant/export_context_snapshot.py
PROMPT_TEMPLATE=/root/beecthor-summary/doc/polymarket_assistant/codex_cycle_prompt.md
CODEX_CLI=${CODEX_CLI:-/usr/bin/codex}
CODEX_MODEL=${CODEX_MODEL:-gpt-5.5}
CODEX_REASONING_EFFORT=${CODEX_REASONING_EFFORT:-xhigh}
CODEX_SANDBOX=${CODEX_SANDBOX:-read-only}
COPILOT_CLI=${COPILOT_CLI:-copilot}
COPILOT_MODEL=${COPILOT_MODEL:-gpt-5.4}
COPILOT_EFFORT=${COPILOT_EFFORT:-high}
PHONE_SSH_USER=${PHONE_SSH_USER:-u0_a647}
PHONE_TUNNEL_PORT=${PHONE_TUNNEL_PORT:-2222}
MONITOR_TIMER_NAME=${MONITOR_TIMER_NAME:-polymarket-monitor.timer}

LOG_DIR=/var/log/polymarket-operator
RUNTIME_DIR=/var/lib/polymarket-operator
LOCK_FILE=${RUNTIME_DIR}/cycle.lock

DECISION_TIMEOUT_SEC=${CODEX_DECISION_TIMEOUT_SEC:-420}

export DISPLAY="${DISPLAY:-:10}"
export HOME="${HOME:-/root}"
export LANG="${LANG:-en_US.UTF-8}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

mkdir -p "$LOG_DIR" "$RUNTIME_DIR"

TIMESTAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)
LOG_FILE="${LOG_DIR}/cycle-${TIMESTAMP}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[cycle] Starting at $(date -u +%Y-%m-%dT%H:%M:%SZ)"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "[cycle] Another cycle is already running. Exiting."
  exit 0
fi

PASSTHROUGH_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --deferred)
      # Kept for compatibility with any old deferred systemd units still queued.
      ;;
    *)
      PASSTHROUGH_ARGS+=("$arg")
      ;;
  esac
done

validate_decision_file() {
  local decision_file="$1"
  local run_id="$2"
  python3 - "$decision_file" "$run_id" <<'PY'
import json
import sys
from pathlib import Path

decision_path = Path(sys.argv[1])
run_id = sys.argv[2]
if not decision_path.exists():
    raise SystemExit(1)

try:
    payload = json.loads(decision_path.read_text(encoding='utf-8'))
except Exception:
    raise SystemExit(1)

required_top = {'run_id', 'action', 'confidence', 'summary', 'rationale'}
if not required_top.issubset(payload):
    raise SystemExit(1)

if payload.get('run_id') != run_id:
    raise SystemExit(1)

if payload.get('action') not in {'NO_ACTION', 'OPEN_POSITION', 'CLOSE_POSITION', 'REDUCE_POSITION'}:
    raise SystemExit(1)

default_management = {
    'should_manage_existing': False,
    'target_market_slug': '',
    'target_outcome': '',
    'reason': 'none',
    'reduce_fraction': 0.5,
}
default_new_position = {
    'should_open': False,
    'event_slug': '',
    'market_slug': '',
    'outcome': '',
    'direction': 'neutral',
    'strike': 0,
    'stake_usd': 0,
    'max_entry_probability': 0.0,
}
default_new_floor_position = {
    'should_open': False,
    'event_slug': '',
    'market_slug': '',
    'outcome': 'Yes',
    'floor_level': 0,
    'stake_usd': 0,
    'max_entry_probability': 0.0,
}

raw_managements = payload.get('position_managements')
raw_new_positions = payload.get('new_positions')
if raw_managements is not None and not isinstance(raw_managements, list):
    raise SystemExit(1)
if raw_new_positions is not None and not isinstance(raw_new_positions, list):
    raise SystemExit(1)

managements = []
for item in raw_managements or []:
    if not isinstance(item, dict):
        raise SystemExit(1)
    managements.append(item)

new_positions = []
for item in raw_new_positions or []:
    if not isinstance(item, dict):
        raise SystemExit(1)
    new_positions.append(item)

legacy_management = payload.get('position_management')
if legacy_management is not None and not isinstance(legacy_management, dict):
    raise SystemExit(1)
legacy_new_position = payload.get('new_position')
if legacy_new_position is not None and not isinstance(legacy_new_position, dict):
    raise SystemExit(1)
legacy_new_floor_position = payload.get('new_floor_position')
if legacy_new_floor_position is not None and not isinstance(legacy_new_floor_position, dict):
    raise SystemExit(1)

if not managements and isinstance(legacy_management, dict):
    if (
        legacy_management.get('should_manage_existing')
        and legacy_management.get('target_market_slug')
        and legacy_management.get('target_outcome')
    ):
        managements.append({
            'should_manage_existing': True,
            'action': payload.get('action', 'CLOSE_POSITION'),
            'target_market_slug': legacy_management.get('target_market_slug', ''),
            'target_outcome': legacy_management.get('target_outcome', ''),
            'reason': legacy_management.get('reason', 'none'),
            'reduce_fraction': legacy_management.get('reduce_fraction', 0.5),
        })

if not new_positions:
    if isinstance(legacy_new_position, dict) and legacy_new_position.get('should_open'):
        new_positions.append({
            'should_open': True,
            'position_kind': 'price_hit',
            'market_type': legacy_new_position.get('market_type', ''),
            'event_slug': legacy_new_position.get('event_slug', ''),
            'market_slug': legacy_new_position.get('market_slug', ''),
            'outcome': legacy_new_position.get('outcome', ''),
            'direction': legacy_new_position.get('direction', 'neutral'),
            'strike': legacy_new_position.get('strike', 0),
            'floor_level': 0,
            'stake_usd': legacy_new_position.get('stake_usd', 0),
            'max_entry_probability': legacy_new_position.get('max_entry_probability', 0.0),
        })
    if isinstance(legacy_new_floor_position, dict) and legacy_new_floor_position.get('should_open'):
        new_positions.append({
            'should_open': True,
            'position_kind': 'floor',
            'market_type': 'floor',
            'event_slug': legacy_new_floor_position.get('event_slug', ''),
            'market_slug': legacy_new_floor_position.get('market_slug', ''),
            'outcome': legacy_new_floor_position.get('outcome', 'Yes'),
            'direction': 'neutral',
            'strike': 0,
            'floor_level': legacy_new_floor_position.get('floor_level', 0),
            'stake_usd': legacy_new_floor_position.get('stake_usd', 0),
            'max_entry_probability': legacy_new_floor_position.get('max_entry_probability', 0.0),
        })

if not isinstance(legacy_management, dict):
    legacy_management = dict(default_management)
if managements and not legacy_management.get('target_market_slug'):
    first = managements[0]
    legacy_management.update({
        'should_manage_existing': True,
        'target_market_slug': first.get('target_market_slug', ''),
        'target_outcome': first.get('target_outcome', ''),
        'reason': first.get('reason', 'none'),
        'reduce_fraction': first.get('reduce_fraction', 0.5),
    })

if not isinstance(legacy_new_position, dict):
    legacy_new_position = dict(default_new_position)
if not isinstance(legacy_new_floor_position, dict):
    legacy_new_floor_position = dict(default_new_floor_position)

for item in new_positions:
    if item.get('position_kind') == 'floor':
        if not legacy_new_floor_position.get('market_slug'):
            legacy_new_floor_position.update({
                'should_open': True,
                'event_slug': item.get('event_slug', ''),
                'market_slug': item.get('market_slug', ''),
                'outcome': item.get('outcome', 'Yes'),
                'floor_level': item.get('floor_level', 0),
                'stake_usd': item.get('stake_usd', 0),
                'max_entry_probability': item.get('max_entry_probability', 0.0),
            })
    else:
        if not legacy_new_position.get('market_slug'):
            legacy_new_position.update({
                'should_open': True,
                'event_slug': item.get('event_slug', ''),
                'market_slug': item.get('market_slug', ''),
                'outcome': item.get('outcome', ''),
                'direction': item.get('direction', 'neutral'),
                'strike': item.get('strike', 0),
                'stake_usd': item.get('stake_usd', 0),
                'max_entry_probability': item.get('max_entry_probability', 0.0),
                'market_type': item.get('market_type', ''),
                'position_kind': item.get('position_kind', 'price_hit'),
                'floor_level': item.get('floor_level', 0),
            })

payload['position_managements'] = managements
payload['new_positions'] = new_positions
payload['position_management'] = legacy_management
payload['new_position'] = legacy_new_position
payload['new_floor_position'] = legacy_new_floor_position

decision_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
PY
}

normalize_llm_decision_file() {
  local raw_file="$1"
  local decision_file="$2"
  "$VENV_PYTHON" - "$raw_file" "$decision_file" <<'PY'
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path('polymarket_assistant').resolve()))
import run_cycle as base  # noqa: E402

raw_path = Path(sys.argv[1])
decision_path = Path(sys.argv[2])
text = raw_path.read_text(encoding='utf-8', errors='replace').strip()
if text.startswith('```'):
    text = re.sub(r'^```(?:json)?', '', text).strip()
    text = re.sub(r'```$', '', text).strip()

def extract_json_object(value: str) -> str:
    try:
        json.loads(value)
        return value
    except Exception:
        pass
    start = value.find('{')
    if start < 0:
        raise ValueError('No JSON object found in LLM output')
    depth = 0
    in_string = False
    escape = False
    for idx, char in enumerate(value[start:], start=start):
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return value[start:idx + 1]
    raise ValueError('Unterminated JSON object in LLM output')

payload = json.loads(extract_json_object(text))
payload = base.normalize_decision(payload)
decision_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
PY
}

write_no_action_decision() {
  local decision_file="$1"
  local run_id="$2"
  local reason="$3"
  python3 - "$decision_file" "$run_id" "$reason" <<'PY'
import json
import sys
from pathlib import Path

decision_path = Path(sys.argv[1])
run_id = sys.argv[2]
reason = sys.argv[3]
payload = {
    'run_id': run_id,
    'action': 'NO_ACTION',
    'confidence': 0.0,
    'summary': 'Automatic LLM cycle fallback: NO_ACTION.',
    'rationale': reason,
    'position_managements': [],
    'new_positions': [],
    'position_management': {
        'should_manage_existing': False,
        'target_market_slug': '',
        'target_outcome': '',
        'reason': 'none',
        'reduce_fraction': 0.5,
    },
    'new_position': {
        'should_open': False,
        'event_slug': '',
        'market_slug': '',
        'outcome': '',
        'direction': 'neutral',
        'strike': 0,
        'stake_usd': 0,
        'max_entry_probability': 0.0,
    },
    'new_floor_position': {
        'should_open': False,
        'event_slug': '',
        'market_slug': '',
        'outcome': 'Yes',
        'floor_level': 0,
        'stake_usd': 0,
        'max_entry_probability': 0.0,
    },
}
decision_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
PY
}

trigger_phone_order_executor() {
  local order_count="$1"
  local phone_cmd
  phone_cmd=(
    ssh
    -p "$PHONE_TUNNEL_PORT"
    -o BatchMode=yes
    -o StrictHostKeyChecking=no
    -o ConnectTimeout=15
    "${PHONE_SSH_USER}@localhost"
    "bash -lc 'cd ~/beecthor-summary && git pull --ff-only >/dev/null 2>&1 || true; nohup python3 phone/polymarket_executor.py >> ~/polymarket_executor.log 2>&1 </dev/null &'"
  )

  echo "[cycle] Triggering phone order executor via tunnel for ${order_count} queued order(s)."
  if "${phone_cmd[@]}"; then
    echo "[cycle] Phone order executor started via tunnel."
    return 0
  fi

  local rc=$?
  echo "[cycle] WARN: phone order executor trigger failed with exit code ${rc}."
  return "$rc"
}

activate_monitor_timer() {
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "[cycle] WARN: systemctl not found; monitor timer not activated."
    return 1
  fi

  if systemctl enable --now "$MONITOR_TIMER_NAME"; then
    echo "[cycle] Monitor timer activated: ${MONITOR_TIMER_NAME}"
    return 0
  fi

  echo "[cycle] WARN: failed to activate monitor timer: ${MONITOR_TIMER_NAME}"
  return 1
}

summary_queued_order_count() {
  python3 - "$SUMMARY_FILE" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
try:
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
except Exception:
    print(0)
    raise SystemExit(0)

execution = summary.get('execution') or {}
if not execution.get('performed'):
    print(0)
    raise SystemExit(0)

details = execution.get('details')
if isinstance(details, list):
    queued = [
        item for item in details
        if isinstance(item, dict) and item.get('status') == 'pending_phone_execution'
    ]
    print(len(queued))
elif isinstance(details, dict) and details.get('status') == 'pending_phone_execution':
    print(1)
else:
    print(0)
PY
}

summary_queued_open_order_count() {
  python3 - "$SUMMARY_FILE" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
try:
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
except Exception:
    print(0)
    raise SystemExit(0)

execution = summary.get('execution') or {}
if not execution.get('performed'):
    print(0)
    raise SystemExit(0)

details = execution.get('details')
if isinstance(details, dict):
    details = [details]
if not isinstance(details, list):
    details = []

count = 0
for item in details:
    if not isinstance(item, dict):
        continue
    if item.get('status') != 'pending_phone_execution':
        continue
    if item.get('type') != 'OPEN_POSITION':
        continue
    count += 1
print(count)
PY
}

cd "$REPO_ROOT"
git pull --ff-only origin main 2>/dev/null || true

ACTIVE_STRATEGY=$(python3 - <<'PY'
import json
import os
from pathlib import Path

paths = [
    Path(os.environ.get('POLYMARKET_STRATEGY_STATE_PATH') or 'server_runtime_logs/strategy_state.json'),
    Path('polymarket_assistant/strategy_state.json'),
]
state = {}
for path in reversed(paths):
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        raw = {}
    if isinstance(raw, dict):
        state.update(raw)
print(state.get('active_strategy') or 'beecthor')
PY
)
CURRENT_UTC_HOUR=$(date -u +%H)
if [ "$ACTIVE_STRATEGY" = "far_dip_radar" ] && [ "$CURRENT_UTC_HOUR" != "06" ] && [ "$CURRENT_UTC_HOUR" != "08" ]; then
  SKIP_TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  echo "[cycle] strategy_window_skipped active_strategy=${ACTIVE_STRATEGY} utc_hour=${CURRENT_UTC_HOUR}"
  python3 - "$LOG_DIR/strategy.jsonl" "$REPO_ROOT/server_runtime_logs/strategy.jsonl" "$SKIP_TS" "$ACTIVE_STRATEGY" "$CURRENT_UTC_HOUR" <<'PY'
import json
import sys
from pathlib import Path

paths = [Path(sys.argv[1]), Path(sys.argv[2])]
event = {
    'timestamp': sys.argv[3],
    'source': 'server.operator',
    'event_type': 'strategy_window_skipped',
    'level': 'info',
    'message': 'Skipped Polymarket cycle because the active strategy is outside its UTC window.',
    'payload': {
        'active_strategy': sys.argv[4],
        'utc_hour': int(sys.argv[5]),
        'allowed_utc_hours': [6, 8],
    },
}
seen = set()
for path in paths:
    resolved = path.resolve()
    if resolved in seen:
        continue
    seen.add(resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + '\n')
PY
  exit 0
fi

eval "$(python3 - <<'PY'
import json
import os
import shlex
from pathlib import Path

path = Path(os.environ.get('POLYMARKET_LLM_PROVIDER_STATE_PATH') or 'server_runtime_logs/llm_provider_state.json')
default = {
    'active_provider': 'codex',
    'settings': {
        'codex_model': os.environ.get('CODEX_MODEL', 'gpt-5.5'),
        'codex_reasoning_effort': os.environ.get('CODEX_REASONING_EFFORT', 'xhigh'),
        'copilot_model': os.environ.get('COPILOT_MODEL', 'gpt-5.4'),
        'copilot_effort': os.environ.get('COPILOT_EFFORT', 'high'),
    },
}
try:
    state = json.loads(path.read_text(encoding='utf-8'))
except Exception:
    state = {}
if not isinstance(state, dict):
    state = {}
settings = default['settings']
if isinstance(state.get('settings'), dict):
    settings.update({k: str(v) for k, v in state['settings'].items() if v})
provider = str(state.get('active_provider') or default['active_provider']).strip()
if provider not in {'codex', 'copilot'}:
    provider = 'codex'
values = {
    'ACTIVE_LLM_PROVIDER': provider,
    'ACTIVE_CODEX_MODEL': settings.get('codex_model') or default['settings']['codex_model'],
    'ACTIVE_CODEX_REASONING_EFFORT': settings.get('codex_reasoning_effort') or default['settings']['codex_reasoning_effort'],
    'ACTIVE_COPILOT_MODEL': settings.get('copilot_model') or default['settings']['copilot_model'],
    'ACTIVE_COPILOT_EFFORT': settings.get('copilot_effort') or default['settings']['copilot_effort'],
}
for key, value in values.items():
    print(f'{key}={shlex.quote(str(value))}')
PY
)"
export POLYMARKET_LLM_PROVIDER="$ACTIVE_LLM_PROVIDER"
if [ "$ACTIVE_LLM_PROVIDER" = "codex" ]; then
  export POLYMARKET_LLM_PROVIDER_MODEL="$ACTIVE_CODEX_MODEL"
  export POLYMARKET_LLM_PROVIDER_EFFORT="$ACTIVE_CODEX_REASONING_EFFORT"
else
  export POLYMARKET_LLM_PROVIDER_MODEL="$ACTIVE_COPILOT_MODEL"
  export POLYMARKET_LLM_PROVIDER_EFFORT="$ACTIVE_COPILOT_EFFORT"
fi
echo "[cycle] LLM provider=${POLYMARKET_LLM_PROVIDER} model=${POLYMARKET_LLM_PROVIDER_MODEL} effort=${POLYMARKET_LLM_PROVIDER_EFFORT}"

RUN_ID=$(date -u +%Y-%m-%dT%H-%M-%SZ)
CONTEXT_FILE="${RUNTIME_DIR}/context_${RUN_ID}.json"
PROMPT_FILE="${RUNTIME_DIR}/prompt_${RUN_ID}.txt"
DECISION_FILE="${RUNTIME_DIR}/decision_${RUN_ID}.json"
RAW_DECISION_FILE="${RUNTIME_DIR}/decision_raw_${RUN_ID}.txt"

"$VENV_PYTHON" "$SNAPSHOT_HELPER" --run-id "$RUN_ID" --output "$CONTEXT_FILE"

LLM_CONTEXT_FILE="$CONTEXT_FILE"
if [ "$ACTIVE_LLM_PROVIDER" = "copilot" ]; then
  # Copilot CLI cannot reliably read /var/lib runtime files. Keep the canonical
  # snapshot there, but give Copilot an ignored repo-local copy it can open.
  COPILOT_CONTEXT_DIR="${REPO_ROOT}/server_runtime_logs/polymarket_operator_contexts"
  mkdir -p "$COPILOT_CONTEXT_DIR"
  COPILOT_CONTEXT_FILE="${COPILOT_CONTEXT_DIR}/context_${RUN_ID}.json"
  cp "$CONTEXT_FILE" "$COPILOT_CONTEXT_FILE"
  LLM_CONTEXT_FILE="$COPILOT_CONTEXT_FILE"
fi

python3 - "$PROMPT_TEMPLATE" "$PROMPT_FILE" "$RUN_ID" "$LLM_CONTEXT_FILE" "$DECISION_FILE" <<'PY'
import sys
from pathlib import Path

template_path = Path(sys.argv[1])
prompt_path = Path(sys.argv[2])
run_id = sys.argv[3]
context_file = sys.argv[4]
decision_file = sys.argv[5]

prompt = template_path.read_text(encoding='utf-8')
prompt = prompt.replace('{{RUN_ID}}', run_id)
prompt = prompt.replace('{{CONTEXT_FILE}}', context_file)
prompt = prompt.replace('{{DECISION_FILE}}', decision_file)
prompt_path.write_text(prompt, encoding='utf-8')
PY

LLM_LOG_FILE="${LOG_DIR}/${ACTIVE_LLM_PROVIDER}-cli-${RUN_ID}.log"
if [ "$ACTIVE_LLM_PROVIDER" = "codex" ]; then
  if ! command -v "$CODEX_CLI" >/dev/null 2>&1; then
    echo "[cycle] Codex CLI not found at ${CODEX_CLI}. Falling back to NO_ACTION."
    write_no_action_decision "$DECISION_FILE" "$RUN_ID" "Codex auto-cycle fallback: Codex CLI was not available."
  else
    echo "[cycle] Running Codex CLI for run_id=${RUN_ID} model=${ACTIVE_CODEX_MODEL} effort=${ACTIVE_CODEX_REASONING_EFFORT} sandbox=${CODEX_SANDBOX}"
    if timeout "$DECISION_TIMEOUT_SEC" "$CODEX_CLI" \
      --ask-for-approval never \
      exec \
      --model "$ACTIVE_CODEX_MODEL" \
      -c "model_reasoning_effort=\"${ACTIVE_CODEX_REASONING_EFFORT}\"" \
      --sandbox "$CODEX_SANDBOX" \
      --output-last-message "$RAW_DECISION_FILE" \
      - < "$PROMPT_FILE" > "$LLM_LOG_FILE" 2>&1; then
      echo "[cycle] Codex CLI finished. Log: ${LLM_LOG_FILE}"
      if ! normalize_llm_decision_file "$RAW_DECISION_FILE" "$DECISION_FILE"; then
        echo "[cycle] Codex CLI output could not be normalized. Log: ${LLM_LOG_FILE}"
      fi
    else
      LLM_RC=$?
      echo "[cycle] Codex CLI failed or timed out with exit code ${LLM_RC}. Log: ${LLM_LOG_FILE}"
      tail -80 "$LLM_LOG_FILE" || true
    fi
  fi
elif [ "$ACTIVE_LLM_PROVIDER" = "copilot" ]; then
  if ! command -v "$COPILOT_CLI" >/dev/null 2>&1; then
    echo "[cycle] Copilot CLI not found at ${COPILOT_CLI}. Falling back to NO_ACTION."
    write_no_action_decision "$DECISION_FILE" "$RUN_ID" "Copilot auto-cycle fallback: Copilot CLI was not available."
  else
    echo "[cycle] Running Copilot CLI for run_id=${RUN_ID} model=${ACTIVE_COPILOT_MODEL} effort=${ACTIVE_COPILOT_EFFORT}"
    if timeout "$DECISION_TIMEOUT_SEC" "$VENV_PYTHON" - "$PROMPT_FILE" "$RAW_DECISION_FILE" "$COPILOT_CLI" "$ACTIVE_COPILOT_MODEL" "$ACTIVE_COPILOT_EFFORT" > "$LLM_LOG_FILE" 2>&1 <<'PY'
import os
import subprocess
import sys
from pathlib import Path

prompt_file = Path(sys.argv[1])
raw_file = Path(sys.argv[2])
copilot_cli = sys.argv[3]
model = sys.argv[4]
effort = sys.argv[5]
prompt = prompt_file.read_text(encoding='utf-8')
env = {
    **os.environ,
    'HOME': os.environ.get('HOME', '/root'),
    'LANG': os.environ.get('LANG', 'en_US.UTF-8'),
    'PYTHONIOENCODING': os.environ.get('PYTHONIOENCODING', 'utf-8'),
}
cmd = [
    copilot_cli,
    '--continue',
    '-p',
    prompt,
    '--model',
    model,
    f'--effort={effort}',
    '-s',
    '--no-ask-user',
]
result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', env=env, cwd=str(Path.cwd()))
print(result.stderr or '', file=sys.stderr)
raw_file.write_text(result.stdout, encoding='utf-8')
raise SystemExit(result.returncode)
PY
    then
      echo "[cycle] Copilot CLI finished. Log: ${LLM_LOG_FILE}"
      if ! normalize_llm_decision_file "$RAW_DECISION_FILE" "$DECISION_FILE"; then
        echo "[cycle] Copilot CLI output could not be normalized. Log: ${LLM_LOG_FILE}"
      fi
    else
      LLM_RC=$?
      echo "[cycle] Copilot CLI failed or timed out with exit code ${LLM_RC}. Log: ${LLM_LOG_FILE}"
      tail -80 "$LLM_LOG_FILE" || true
    fi
  fi
else
  echo "[cycle] Unknown LLM provider ${ACTIVE_LLM_PROVIDER}. Falling back to NO_ACTION."
  write_no_action_decision "$DECISION_FILE" "$RUN_ID" "LLM auto-cycle fallback: unknown provider ${ACTIVE_LLM_PROVIDER}."
fi

if ! validate_decision_file "$DECISION_FILE" "$RUN_ID"; then
  echo "[cycle] No valid decision received from ${ACTIVE_LLM_PROVIDER}. Falling back to NO_ACTION."
  write_no_action_decision "$DECISION_FILE" "$RUN_ID" "${ACTIVE_LLM_PROVIDER} auto-cycle fallback: no valid decision file was produced."
fi

source .venv/bin/activate
python "$RUN_CYCLE" --decision-file "$DECISION_FILE" "${PASSTHROUGH_ARGS[@]}"

SUMMARY_FILE="polymarket_assistant/last_run_summary.json"
PHONE_ORDER_COUNT=0
PHONE_OPEN_ORDER_COUNT=0
if [ -f "$SUMMARY_FILE" ]; then
  ACTION=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print(d['decision']['action'])" 2>/dev/null || echo "UNKNOWN")
  SUMMARY=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print(d['decision']['summary'][:120])" 2>/dev/null || echo "")
  BTC=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print(d['binance_spot_price'])" 2>/dev/null || echo "?")
  DRY=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print('[DRY RUN] ' if d['dry_run'] else '')" 2>/dev/null || echo "")
  PHONE_ORDER_COUNT=$(summary_queued_order_count)
  PHONE_OPEN_ORDER_COUNT=$(summary_queued_open_order_count)
  COMMIT_MSG="${DRY}polymarket: ${ACTION} (BTC \$${BTC})\n\n${SUMMARY}"
else
  COMMIT_MSG="polymarket: cycle $(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

git add \
  polymarket_assistant/account_state.json \
  polymarket_assistant/trade_log.json \
  polymarket_assistant/last_run_summary.json \
  doc/polymarket_assistant/last_run_summary.md \
  polymarket_assistant/pending_orders.json 2>/dev/null || true
if ! git diff --staged --quiet 2>/dev/null; then
  git config user.name "polymarket-operator[bot]"
  git config user.email "polymarket-operator[bot]@users.noreply.github.com"
  git commit -m "$COMMIT_MSG"
  if git push origin main; then
    echo "[cycle] Committed and pushed: ${ACTION}"
    if [ "${PHONE_ORDER_COUNT:-0}" -gt 0 ]; then
      if trigger_phone_order_executor "$PHONE_ORDER_COUNT"; then
        if [ "${PHONE_OPEN_ORDER_COUNT:-0}" -gt 0 ]; then
          activate_monitor_timer || true
        fi
      fi
    fi
  else
    echo "WARN: git push failed"
    echo "[cycle] Commit created locally only: ${ACTION}"
    if [ "${PHONE_ORDER_COUNT:-0}" -gt 0 ]; then
      echo "[cycle] Phone order executor not triggered because pending_orders.json was not pushed."
    fi
  fi
else
  echo "[cycle] No state changes to commit"
fi

echo "[cycle] Done at $(date -u +%Y-%m-%dT%H:%M:%SZ). Log: ${LOG_FILE}"
