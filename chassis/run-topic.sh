#!/usr/bin/env bash
# run-topic.sh — one bounded research iteration for one topic, via a pluggable runner.
#
# Usage: run-topic.sh <topic-dir> [runner-name]
#   topic-dir    directory under topics/ containing TOPIC.md + ledgers
#   runner-name  positional fallback naming a script under runners/ (default: generic).
#                RESEARCH_LOOP_RUNNER overrides it. Resolution order: an absolute/
#                relative path, then runners/<name> next to this chassis, then
#                <name> on PATH.
#
# See docs/runners.md for the full Agent Runner contract. Summary: the runner receives
# (topic_dir, prompt_file) as argv plus RESEARCH_LOOP_* env vars, streams its transcript
# to stdout/stderr, may optionally write RESEARCH_LOOP_USAGE_FILE as JSON, and owns exit
# code 0 or any non-zero it wants classified as a transient failure. It must never itself
# use exit codes 3/4/5/78 — those belong to this chassis:
#   exit 0  = iteration completed with ledger progress
#   exit 3  = STOP file present (terminal; queue maps to completed/attention)
#   exit 4  = PAUSED file present
#   exit 5  = liveness stall (semantic signature unchanged on rc=0)
#   exit 78 = invalid or unavailable runtime configuration
set -euo pipefail

CHASSIS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$CHASSIS/.." && pwd)"
TOPIC_DIR="$(cd "$1" && pwd)"
RUNNER_NAME="${RESEARCH_LOOP_RUNNER:-${2:-generic}}"
LOG_DIR="$TOPIC_DIR/logs"
mkdir -p "$LOG_DIR"

[[ -f "$TOPIC_DIR/TOPIC.md" ]] || { echo "configuration error: $TOPIC_DIR/TOPIC.md missing" >&2; exit 78; }
[[ -f "$TOPIC_DIR/SEMANTIC-STATE.json" ]] || { echo "configuration error: $TOPIC_DIR/SEMANTIC-STATE.json missing" >&2; exit 78; }

# Resolve the runner: absolute/relative path, then runners/<name>, then PATH.
if [[ -x "$RUNNER_NAME" ]]; then
  RUNNER="$RUNNER_NAME"
elif [[ -x "$REPO_ROOT/runners/$RUNNER_NAME" ]]; then
  RUNNER="$REPO_ROOT/runners/$RUNNER_NAME"
elif [[ -x "$REPO_ROOT/runners/$RUNNER_NAME.sh" ]]; then
  RUNNER="$REPO_ROOT/runners/$RUNNER_NAME.sh"
elif command -v "$RUNNER_NAME" >/dev/null 2>&1; then
  RUNNER="$(command -v "$RUNNER_NAME")"
else
  echo "configuration error: runner '$RUNNER_NAME' not found (checked path, runners/, PATH)" >&2
  exit 78
fi

# Preflight is entirely optional: run it only if this topic (or the repo) ships one.
# Nothing in this chassis requires external infrastructure to exist.
DEGRADED_NOTE=""
for candidate in "$TOPIC_DIR/preflight.sh" "$CHASSIS/preflight.sh"; do
  if [[ -x "$candidate" ]]; then
    degraded_file="$LOG_DIR/degraded-tools"
    "$candidate" "$RUNNER_NAME" "$degraded_file" || true
    if [[ -s "$degraded_file" ]]; then
      degraded_list="$(paste -sd, "$degraded_file")"
      DEGRADED_NOTE=" CAPABILITY NOTICE for this iteration: $degraded_list currently unreachable. This is a capability fact, never evidence of absence — do not treat any obligation as resolved or contradicted on this basis; work around it with what remains available, and defer rather than guess on anything that specifically requires the unreachable tool."
    fi
    break
  fi
done

if [[ -f "$TOPIC_DIR/STOP" ]]; then
  echo "STOP present: $(head -n 1 "$TOPIC_DIR/STOP")" >&2
  exit 3
fi
if [[ -f "$TOPIC_DIR/PAUSED" && "${ALLOW_PAUSED_RUN:-0}" != 1 ]]; then
  echo "PAUSED: set ALLOW_PAUSED_RUN=1 for one deliberate iteration" >&2
  exit 4
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
log="$LOG_DIR/iteration-$stamp.log"
usage="$LOG_DIR/iteration-$stamp-usage.json"
prompt_file="$LOG_DIR/.iteration-$stamp-prompt.txt"
touch "$TOPIC_DIR/PROGRESS.md"
before=$("$CHASSIS/progress-signature.sh" "$TOPIC_DIR")

sed \
  -e "s#\${TOPIC_DIR}#$TOPIC_DIR#g" \
  -e "s#\${CHASSIS}#$CHASSIS#g" \
  -e "s#\${DEGRADED_NOTE}#$DEGRADED_NOTE#g" \
  "$CHASSIS/ITERATION-PROMPT.md" >"$prompt_file"

export RESEARCH_LOOP_TOPIC_DIR="$TOPIC_DIR"
export RESEARCH_LOOP_USAGE_FILE="$usage"
export RESEARCH_LOOP_LOG="$log"
# RESEARCH_LOOP_PROFILE is deliberately NOT set here unless already present in the
# environment (the queue worker may set it per-worker) — the runner interprets it,
# this chassis never does.

set +e
"$RUNNER" "$TOPIC_DIR" "$prompt_file" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
set -e
rm -f "$prompt_file"

after=$("$CHASSIS/progress-signature.sh" "$TOPIC_DIR")
if [[ $rc -ne 0 ]]; then
  echo "iteration failed rc=$rc log=$log" >&2
  exit "$rc"
fi
if [[ "$before" == "$after" && ! -f "$TOPIC_DIR/STOP" ]]; then
  echo "stalled: semantic state unchanged; operator attention required; log=$log" >&2
  exit 5
fi
if [[ -f "$TOPIC_DIR/STOP" ]]; then
  first_token=$(awk 'NR==1 {gsub(/[[:punct:]]+$/, "", $1); print toupper($1)}' "$TOPIC_DIR/STOP")
  if [[ "$first_token" == "DONE" ]]; then
    if ! python3 "$CHASSIS/semantic-state.py" validate "$TOPIC_DIR"; then
      echo "configuration error: DONE rejected by semantic completion validator" >&2
      exit 78
    fi
  fi
  echo "STOP written this iteration: $(head -n 1 "$TOPIC_DIR/STOP")"
fi
echo "iteration-ok log=$log usage=$usage"
