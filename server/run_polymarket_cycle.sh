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
    'summary': 'Automatic Codex cycle fallback: NO_ACTION.',
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

cd "$REPO_ROOT"
git pull --ff-only origin main 2>/dev/null || true

ACTIVE_STRATEGY=$(python3 - <<'PY'
import json
from pathlib import Path

path = Path('polymarket_assistant/strategy_state.json')
try:
    state = json.loads(path.read_text(encoding='utf-8'))
except Exception:
    state = {}
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

RUN_ID=$(date -u +%Y-%m-%dT%H-%M-%SZ)
CONTEXT_FILE="${RUNTIME_DIR}/context_${RUN_ID}.json"
PROMPT_FILE="${RUNTIME_DIR}/prompt_${RUN_ID}.txt"
DECISION_FILE="${RUNTIME_DIR}/decision_${RUN_ID}.json"

"$VENV_PYTHON" "$SNAPSHOT_HELPER" --run-id "$RUN_ID" --output "$CONTEXT_FILE"

python3 - "$PROMPT_TEMPLATE" "$PROMPT_FILE" "$RUN_ID" "$CONTEXT_FILE" "$DECISION_FILE" <<'PY'
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

CODEX_LOG_FILE="${LOG_DIR}/codex-cli-${RUN_ID}.log"
if ! command -v "$CODEX_CLI" >/dev/null 2>&1; then
  echo "[cycle] Codex CLI not found at ${CODEX_CLI}. Falling back to NO_ACTION."
  write_no_action_decision "$DECISION_FILE" "$RUN_ID" "Codex auto-cycle fallback: Codex CLI was not available."
else
  echo "[cycle] Running Codex CLI for run_id=${RUN_ID} model=${CODEX_MODEL} effort=${CODEX_REASONING_EFFORT} sandbox=${CODEX_SANDBOX}"
  if timeout "$DECISION_TIMEOUT_SEC" "$CODEX_CLI" \
    --ask-for-approval never \
    exec \
    --model "$CODEX_MODEL" \
    -c "model_reasoning_effort=\"${CODEX_REASONING_EFFORT}\"" \
    --sandbox "$CODEX_SANDBOX" \
    --output-last-message "$DECISION_FILE" \
    - < "$PROMPT_FILE" > "$CODEX_LOG_FILE" 2>&1; then
    echo "[cycle] Codex CLI finished. Log: ${CODEX_LOG_FILE}"
  else
    CODEX_RC=$?
    echo "[cycle] Codex CLI failed or timed out with exit code ${CODEX_RC}. Log: ${CODEX_LOG_FILE}"
    tail -80 "$CODEX_LOG_FILE" || true
  fi
fi

if ! validate_decision_file "$DECISION_FILE" "$RUN_ID"; then
  echo "[cycle] No valid decision received from Codex CLI. Falling back to NO_ACTION."
  write_no_action_decision "$DECISION_FILE" "$RUN_ID" "Codex auto-cycle fallback: no valid decision file was produced by Codex CLI."
fi

source .venv/bin/activate
python "$RUN_CYCLE" --decision-file "$DECISION_FILE" "${PASSTHROUGH_ARGS[@]}"

SUMMARY_FILE="polymarket_assistant/last_run_summary.json"
if [ -f "$SUMMARY_FILE" ]; then
  ACTION=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print(d['decision']['action'])" 2>/dev/null || echo "UNKNOWN")
  SUMMARY=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print(d['decision']['summary'][:120])" 2>/dev/null || echo "")
  BTC=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print(d['binance_spot_price'])" 2>/dev/null || echo "?")
  DRY=$(python3 -c "import json; d=json.load(open('$SUMMARY_FILE')); print('[DRY RUN] ' if d['dry_run'] else '')" 2>/dev/null || echo "")
  COMMIT_MSG="${DRY}polymarket: ${ACTION} (BTC \$${BTC})\n\n${SUMMARY}"
else
  COMMIT_MSG="polymarket: cycle $(date -u +%Y-%m-%dT%H:%M:%SZ)"
fi

git add \
  polymarket_assistant/account_state.json \
  polymarket_assistant/trade_log.json \
  polymarket_assistant/last_run_summary.json \
  doc/polymarket_assistant/last_run_summary.md \
  polymarket_assistant/pending_orders.json \
  polymarket_assistant/strategy_state.json 2>/dev/null || true
if ! git diff --staged --quiet 2>/dev/null; then
  git config user.name "polymarket-operator[bot]"
  git config user.email "polymarket-operator[bot]@users.noreply.github.com"
  git commit -m "$COMMIT_MSG"
  if git push origin main; then
    echo "[cycle] Committed and pushed: ${ACTION}"
  else
    echo "WARN: git push failed"
    echo "[cycle] Commit created locally only: ${ACTION}"
  fi
else
  echo "[cycle] No state changes to commit"
fi

echo "[cycle] Done at $(date -u +%Y-%m-%dT%H:%M:%SZ). Log: ${LOG_FILE}"
