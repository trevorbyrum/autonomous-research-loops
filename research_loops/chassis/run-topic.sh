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
# See runners/README.md for the full Agent Runner contract. Summary: the runner receives
# (topic_dir, prompt_file) as argv plus RESEARCH_LOOP_* env vars, streams its transcript
# to stdout/stderr, may optionally write RESEARCH_LOOP_USAGE_FILE as JSON, and owns exit
# code 0 or any non-zero it wants classified as a transient failure. It must never itself
# use exit codes 3/4/5/78 — those belong to this chassis:
#   exit 0  = iteration completed (including iterations with an unchanged semantic
#             signature: the chassis MEASURES progress and reports it in the result
#             file below; whether unchanged signatures constitute a stall is the
#             queue's decision — its stall guard counts stall_limit CONSECUTIVE
#             unchanged runs. CONTRACT-CORE's evidence discipline makes
#             discovery-only iterations legitimate, so a single unchanged
#             signature is never, by itself, a failure.)
#   exit 3  = STOP file present (terminal; queue maps to completed/attention)
#   exit 4  = PAUSED file present
#   exit 5  = reserved (the pre-2026-09 chassis exited 5 on the FIRST unchanged
#             signature, pre-empting the queue's stall_limit and parking
#             contract-compliant discovery iterations; the chassis no longer
#             emits it, but the code stays reserved so old logs remain readable
#             and runners still must not use it)
#   exit 78 = invalid or unavailable runtime configuration
#
# Every completed runner invocation also writes $LOG_DIR/result-<stamp>.json
# (and the stable alias $LOG_DIR/latest-result.json): a small structured record
# of chassis-level facts — outcome, exit code, signature before/after,
# sources cited, STOP status, degraded capabilities. The queue prefers this
# file over scraping the transcript; treat it as the chassis→queue interface
# and keep it runner-agnostic.
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

# Agent assignment and gap-handling policy are both entirely optional and
# both default to today's baseline behavior (no secondary agent named,
# propose-only gap handling) when unset — see docs/operations.md and
# docs/governance.md#the-operator-owns-scope.
AGENT_NOTE=""
if [[ -n "${RESEARCH_LOOP_AGENT_SECONDARY:-}" ]]; then
  AGENT_NOTE=" DELEGATION: for independent, well-scoped legwork (discovery or extraction only, never final judgment — see CONTRACT-CORE.md step 4), delegate to: ${RESEARCH_LOOP_AGENT_SECONDARY}."
fi

GAP_POLICY="${RESEARCH_LOOP_GAP_POLICY:-review}"
GAP_AUTO_LIMIT="${RESEARCH_LOOP_GAP_AUTO_LIMIT:-0}"
GAP_POLICY_NOTE=" GAP POLICY: review — do not self-promote; a PROPOSAL row is the only sanctioned path."
if [[ "$GAP_POLICY" == "auto" ]]; then
  remaining="$(python3 "$CHASSIS/gap-policy.py" status "$TOPIC_DIR" --policy auto --limit "$GAP_AUTO_LIMIT" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["remaining"])')"
  if [[ "$remaining" -gt 0 ]]; then
    GAP_POLICY_NOTE=" GAP POLICY: auto ($remaining of $GAP_AUTO_LIMIT self-promotions remaining since the last operator review). If you find a real gap, you may self-promote it directly instead of only proposing it: \`python3 ${CHASSIS}/gap-policy.py promote ${TOPIC_DIR} --id <NEW-ID> --text \"<obligation text>\" --source-ref \"<where this gap came from>\" --auto --limit ${GAP_AUTO_LIMIT}\`. Still record why in the same iteration's ledger update; this budget still requires eventual operator review-reset, and running out mid-topic is expected and fine — the PROPOSAL path never goes away."
  else
    GAP_POLICY_NOTE=" GAP POLICY: auto, but this topic's self-promotion budget is used up ($GAP_AUTO_LIMIT/$GAP_AUTO_LIMIT since the last operator review) — append a PROPOSAL row instead and note that an operator review-reset is needed."
  fi
fi

# Citation policy (docs/citations.md) — internal citations are disabled by default;
# see RESEARCH_LOOP_INTERNAL_CITATIONS below for how a topic opts in.
CITATION_NOTE=" CITATIONS: every evidence_ref must resolve to a typed [SRC-NNN] citation block in SOURCE-LEDGER.md (external or local — see docs/citations.md). Internal citations (pointing at another topic's already-vetted source) are not enabled for this topic. A new external/local block only backs a disposition once a DIFFERENT agent visits the exact cited location and sets verified: true, or sets flagged: hallucination if it doesn't hold up — that check stops at the cited location, it never searches for a replacement source."
if [[ "${RESEARCH_LOOP_INTERNAL_CITATIONS:-0}" == "1" ]]; then
  CITATION_NOTE=" CITATIONS: every evidence_ref must resolve to a typed [SRC-NNN] citation block in SOURCE-LEDGER.md (external, local, or internal — see docs/citations.md). Internal citations are enabled for this topic: if the same source was already vetted in another topic, point at it (\`## [SRC-NNN] internal\` with \`topic:\`/\`ref:\` fields) instead of re-researching it. A new external/local block only backs a disposition once a DIFFERENT agent visits the exact cited location and sets verified: true, or sets flagged: hallucination if it doesn't hold up — that check stops at the cited location, it never searches for a replacement source."
fi

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
sources_before=$(python3 "$CHASSIS/semantic-state.py" source-count "$TOPIC_DIR" 2>/dev/null || echo 0)

sed \
  -e "s#\${TOPIC_DIR}#$TOPIC_DIR#g" \
  -e "s#\${CHASSIS}#$CHASSIS#g" \
  -e "s#\${DEGRADED_NOTE}#$DEGRADED_NOTE#g" \
  -e "s#\${AGENT_NOTE}#$AGENT_NOTE#g" \
  -e "s#\${GAP_POLICY_NOTE}#$GAP_POLICY_NOTE#g" \
  -e "s#\${CITATION_NOTE}#$CITATION_NOTE#g" \
  "$CHASSIS/ITERATION-PROMPT.md" >"$prompt_file"

export RESEARCH_LOOP_TOPIC_DIR="$TOPIC_DIR"
export RESEARCH_LOOP_USAGE_FILE="$usage"
export RESEARCH_LOOP_LOG="$log"
# RESEARCH_LOOP_PROFILE, RESEARCH_LOOP_AGENT_SECONDARY, RESEARCH_LOOP_GAP_POLICY,
# RESEARCH_LOOP_GAP_AUTO_LIMIT, RESEARCH_LOOP_COMPLETION_LOCK, RESEARCH_LOOP_INTERNAL_CITATIONS,
# and RESEARCH_LOOP_TOPICS_ROOT are deliberately NOT set here unless already present in
# the environment (the queue worker sets them per-item from agent_main/agent_secondary/
# gap_policy/gap_auto_limit/completion_lock/internal_citations) — the runner and prompt
# above already resolved what they mean; this chassis never invents a default beyond
# what's read above. Running a topic standalone without the queue and without setting
# RESEARCH_LOOP_COMPLETION_LOCK means DONE is checked structurally but not against a
# pinned obligation inventory — set it yourself (see `chassis/semantic-state.py lock`)
# if you want the same protection the queue gives by default. Likewise,
# RESEARCH_LOOP_INTERNAL_CITATIONS defaults to disabled standalone.

set +e
"$RUNNER" "$TOPIC_DIR" "$prompt_file" 2>&1 | tee "$log"
rc=${PIPESTATUS[0]}
set -e
rm -f "$prompt_file"

after=$("$CHASSIS/progress-signature.sh" "$TOPIC_DIR")
sources_after=$(python3 "$CHASSIS/semantic-state.py" source-count "$TOPIC_DIR" 2>/dev/null || echo 0)
sources_cited=$((sources_after - sources_before))

# The chassis→queue result record: chassis-level facts the queue classifies
# from instead of scraping LLM transcript prose. Written on every path where
# the runner actually ran, success or failure, and always runner-agnostic.
write_result() {
  RESULT_OUTCOME="$1" RESULT_EXIT="$2" RESULT_STAMP="$stamp" \
  RESULT_BEFORE="$before" RESULT_AFTER="$after" \
  RESULT_SOURCES_CITED="$sources_cited" RESULT_LOG="$log" \
  RESULT_RUNNER="$RUNNER_NAME" RESULT_TOPIC_DIR="$TOPIC_DIR" \
  RESULT_DEGRADED_FILE="${degraded_file:-}" \
  python3 - "$LOG_DIR" <<'PY' || echo "warning: could not write iteration result record" >&2
import json, os, sys

log_dir = sys.argv[1]
degraded = []
degraded_path = os.environ.get("RESULT_DEGRADED_FILE") or ""
if degraded_path and os.path.isfile(degraded_path):
    with open(degraded_path, encoding="utf-8") as fh:
        degraded = [line.strip() for line in fh if line.strip()]
stop_path = os.path.join(os.environ["RESULT_TOPIC_DIR"], "STOP")
stop_written = os.path.isfile(stop_path)
stop_first = None
if stop_written:
    with open(stop_path, encoding="utf-8") as fh:
        stop_first = (fh.readline() or "").strip()[:200] or None
result = {
    "schema_version": 1,
    "stamp": os.environ["RESULT_STAMP"],
    "outcome": os.environ["RESULT_OUTCOME"],
    "exit_code": int(os.environ["RESULT_EXIT"]),
    "runner": os.environ["RESULT_RUNNER"],
    "signature_before": os.environ["RESULT_BEFORE"],
    "signature_after": os.environ["RESULT_AFTER"],
    "signature_changed": os.environ["RESULT_BEFORE"] != os.environ["RESULT_AFTER"],
    "sources_cited": int(os.environ["RESULT_SOURCES_CITED"]),
    "stop_written": stop_written,
    "stop_first_line": stop_first,
    "degraded_capabilities": degraded,
    "log": os.environ["RESULT_LOG"],
}
payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
with open(os.path.join(log_dir, f"result-{result['stamp']}.json"), "w", encoding="utf-8") as fh:
    fh.write(payload)
latest = os.path.join(log_dir, "latest-result.json")
tmp = latest + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write(payload)
os.replace(tmp, latest)
PY
}

if [[ $rc -ne 0 ]]; then
  write_result runner_failed "$rc"
  echo "iteration failed rc=$rc log=$log" >&2
  exit "$rc"
fi
if [[ -f "$TOPIC_DIR/STOP" ]]; then
  first_token=$(awk 'NR==1 {gsub(/[[:punct:]]+$/, "", $1); print toupper($1)}' "$TOPIC_DIR/STOP")
  if [[ "$first_token" == "DONE" ]]; then
    lock_args=()
    if [[ -n "${RESEARCH_LOOP_COMPLETION_LOCK:-}" ]]; then
      lock_args=(--lock-sha256 "$RESEARCH_LOOP_COMPLETION_LOCK")
    fi
    if [[ "${RESEARCH_LOOP_INTERNAL_CITATIONS:-0}" == "1" ]]; then
      lock_args+=(--allow-internal-citations)
    fi
    if [[ -n "${RESEARCH_LOOP_TOPICS_ROOT:-}" ]]; then
      lock_args+=(--topics-root "$RESEARCH_LOOP_TOPICS_ROOT")
    fi
    if ! python3 "$CHASSIS/semantic-state.py" validate "$TOPIC_DIR" "${lock_args[@]}"; then
      write_result done_rejected 78
      echo "configuration error: DONE rejected by semantic completion validator" >&2
      exit 78
    fi
  fi
  echo "STOP written this iteration: $(head -n 1 "$TOPIC_DIR/STOP")"
fi
write_result ok 0
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) iteration $stamp: sources_cited=$sources_cited (total=$sources_after)" >> "$TOPIC_DIR/PROGRESS.md"
# Stable alias of this iteration's usage JSON so a queue item's usage_file
# can point at one fixed path (the runner's freshness check compares
# mtime/size before and after each run, so an unchanged copy is ignored).
if [[ -s "$usage" ]]; then
  cp -f "$usage" "$LOG_DIR/latest-usage.json"
fi
echo "iteration-ok log=$log usage=$usage sources_cited=$sources_cited"
