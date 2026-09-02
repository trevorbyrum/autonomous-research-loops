#!/usr/bin/env bash
# run-discovery.sh — one bounded discovery pass for one DRAFT topic.
#
# Usage: run-discovery.sh <draft-topic-dir> [runner-name]
#
# Intake-lane counterpart of run-topic.sh: operates on a DRAFT (pre-approval)
# topic dir, mapping the topic space and pressure-testing the draft scope. The
# pass succeeds only if it produced SCOPE-PROPOSAL.md — a discovery run that
# writes nothing reviewable did not happen, whatever its transcript says.
#
#   exit 0  = discovery completed; SCOPE-PROPOSAL.md written
#   exit 65 = runner succeeded but produced no SCOPE-PROPOSAL.md
#   exit 78 = invalid runtime configuration (not a draft dir / runner missing)
#
# Same Agent Runner contract as run-topic.sh (runners/README.md); runners must
# not use exit codes 3/4/5/65/78.
set -euo pipefail

CHASSIS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$CHASSIS/.." && pwd)"
TOPIC_DIR="$(cd "$1" && pwd)"
RUNNER_NAME="${RESEARCH_LOOP_RUNNER:-${2:-generic}}"
LOG_DIR="$TOPIC_DIR/logs"
mkdir -p "$LOG_DIR"

# A pass runs against either a DRAFT (pre-approval intake) or an already
# APPROVED contract (operator-ordered contract review); the prompt differs.
if [[ -f "$TOPIC_DIR/DRAFT-TOPIC.md" ]]; then
  PASS_KIND=draft
  TEMPLATE="$CHASSIS/DISCOVERY-PROMPT.md"
  [[ -f "$TOPIC_DIR/QA-RECORD.md" ]] || { echo "configuration error: $TOPIC_DIR/QA-RECORD.md missing (re-run new-topic to scaffold it)" >&2; exit 78; }
elif [[ -f "$TOPIC_DIR/TOPIC.md" ]]; then
  PASS_KIND=review
  TEMPLATE="$CHASSIS/CONTRACT-REVIEW-PROMPT.md"
  if [[ ! -f "$TOPIC_DIR/QA-RECORD.md" ]]; then
    printf '# QA record\n\n## Mode\n\nreview\n\n## Questions for the operator\n\n## Operator confirmation\n\n' >"$TOPIC_DIR/QA-RECORD.md"
  fi
else
  echo "configuration error: $TOPIC_DIR has neither DRAFT-TOPIC.md nor TOPIC.md" >&2
  exit 78
fi

QA_MODE="$(sed -n '/^## Mode$/,/^## /p' "$TOPIC_DIR/QA-RECORD.md" | sed '1d;/^## /d;/^[[:space:]]*$/d' | head -1 | tr -d '[:space:]')"
QA_MODE="${QA_MODE:-broad}"

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

AGENT_NOTE=""
if [[ -n "${RESEARCH_LOOP_AGENT_SECONDARY:-}" ]]; then
  AGENT_NOTE=" DELEGATION: route survey searches and fetches to: ${RESEARCH_LOOP_AGENT_SECONDARY}."
fi

stamp=$(date -u +%Y%m%dT%H%M%SZ)
log="$LOG_DIR/discovery-$stamp.log"
usage="$LOG_DIR/discovery-$stamp-usage.json"
prompt_file="$LOG_DIR/.discovery-$stamp-prompt.txt"

python3 "$CHASSIS/render-prompt.py" "$TEMPLATE" \
  "TOPIC_DIR=$TOPIC_DIR" \
  "CHASSIS=$CHASSIS" \
  "AGENT_NOTE=$AGENT_NOTE" \
  "QA_MODE=$QA_MODE" \
  >"$prompt_file"

export RESEARCH_LOOP_TOPIC_DIR="$TOPIC_DIR"
export RESEARCH_LOOP_USAGE_FILE="$usage"
export RESEARCH_LOOP_LOG="$log"

set +e
"$RUNNER" "$TOPIC_DIR" "$prompt_file" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
set -e
rm -f "$prompt_file"

if [[ -s "$usage" ]]; then
  cp -f "$usage" "$LOG_DIR/latest-usage.json"
fi
if [[ $rc -ne 0 ]]; then
  echo "discovery failed rc=$rc log=$log" >&2
  exit "$rc"
fi
if [[ ! -s "$TOPIC_DIR/SCOPE-PROPOSAL.md" ]]; then
  echo "discovery produced no SCOPE-PROPOSAL.md — the pass did not happen; log=$log" >&2
  exit 65
fi
echo "discovery-ok proposal=$TOPIC_DIR/SCOPE-PROPOSAL.md log=$log"
