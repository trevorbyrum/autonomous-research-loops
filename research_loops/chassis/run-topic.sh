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
  AGENT_NOTE=" DELEGATION: delegate through ${RESEARCH_LOOP_AGENT_SECONDARY}. Use its default gpt-5.6-luna for discovery, librarian work, extraction, proposal advocacy, and citation verification. Each verification runs in a fresh invocation distinct from the invocation that produced the citation. The sole additional assignment is a fresh gpt-5.6-terra invocation, through the same wrapper with --model gpt-5.6-terra, for the authorized counter-argument seat, including its permitted repair assessment. Terra is a primary-class counter assignment, not a second secondary model. The primary retains final judgment (see CONTRACT-CORE.md step 4). Use no other delegate model or native Agent/Task intermediary."
fi

GAP_POLICY="${RESEARCH_LOOP_GAP_POLICY:-review}"
GAP_AUTO_LIMIT="${RESEARCH_LOOP_GAP_AUTO_LIMIT:-0}"
GAP_POLICY_NOTE=" GAP POLICY: review. Record eligible proposals within the proposal-review allowance; only the operator may promote them. When the allowance is exhausted, preserve a short signal in the ordinary research record without issuing another proposal."
if [[ "$GAP_POLICY" == "auto" ]]; then
  remaining="$(python3 "$CHASSIS/gap-policy.py" status "$TOPIC_DIR" --policy auto --limit "$GAP_AUTO_LIMIT" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["remaining"])')"
  if [[ "$remaining" -gt 0 ]]; then
    GAP_POLICY_NOTE=" GAP POLICY: auto, with $remaining of $GAP_AUTO_LIMIT ordinary-gap self-promotions remaining. Only ordinary research gaps are eligible for the documented auto-promotion command: \`python3 ${CHASSIS}/gap-policy.py promote ${TOPIC_DIR} --id <NEW-ID> --text \"<obligation text>\" --source-ref \"<where this gap came from>\" --auto --limit ${GAP_AUTO_LIMIT}\`. Scout/checkpoint proposals and all amendments require operator promotion, including revised or later-resubmitted versions. Record the eligible gap's origin and rationale. The proposal-review allowance is separate; neither budget refills when a new iteration starts."
  else
    GAP_POLICY_NOTE=" GAP POLICY: auto, ordinary-gap allowance exhausted ($GAP_AUTO_LIMIT/$GAP_AUTO_LIMIT since the last operator review). Issue a proposal only within the remaining proposal-review allowance; otherwise preserve the signal and report the pending operator review. Scout/checkpoint proposals and all amendments always require operator promotion."
  fi
fi

# Citation policy (docs/citations.md) — internal citations are disabled by default;
# see RESEARCH_LOOP_INTERNAL_CITATIONS below for how a topic opts in.
CITATION_NOTE=" CITATIONS: for schema_version >= 2 topics, every evidence_ref must resolve to a typed [SRC-NNN] citation block in SOURCE-LEDGER.md (external or local — see docs/citations.md). Internal citations are not enabled for this topic. For a new or materially changed external/local citation claim, obtain verification through a fresh Luna invocation distinct from the citation-producing invocation: it independently visits the exact location and checks that claim (the later verification pass may occur in this same iteration). Use verified: true for confirmed support; use flagged: hallucination for an established wrong/dead location or unsupported claim. Temporary retrieval or quota failure leaves the affected claim unverified and records a capability problem — it is never a hallucination finding. The verifier checks the fixed citation and never searches for a replacement. See CONTRACT-CORE and docs/citations.md for role ownership and changed-claim handling."
if [[ "${RESEARCH_LOOP_INTERNAL_CITATIONS:-0}" == "1" ]]; then
  CITATION_NOTE=" CITATIONS: for schema_version >= 2 topics, every evidence_ref must resolve to a typed [SRC-NNN] citation block in SOURCE-LEDGER.md (external, local, or internal — see docs/citations.md). Internal citations are enabled for this topic: reuse an existing verified target when its checked passage supports the current claim with the required scope, qualifications, and freshness — examine the target record and relevant passage; matching the source identity alone is insufficient. The internal block inherits the target's verification status, but you still judge applicability; a materially different claim needs its own independently verified source record, and an unverified or flagged target cannot support a disposition. For a new or materially changed external/local citation claim, obtain verification through a fresh Luna invocation distinct from the citation-producing invocation: it independently visits the exact location and checks that claim (the later verification pass may occur in this same iteration). Use verified: true for confirmed support; flagged: hallucination for an established wrong/dead location or unsupported claim. Temporary retrieval or quota failure leaves the claim unverified as a capability problem — never a hallucination finding. The verifier checks the fixed citation and never searches for a replacement."
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
# 9·0 outcome metrics, measured AT SOURCE (the report never re-derives them), with the
# CITATION ACCEPTANCE RULES applied: a block is accepted only when it carries
# `verified: true` AND no `flagged:` mark (a flagged block is refused unconditionally —
# docs/citations.md), so a hallucination-flagged addition never counts as verified evidence.
# Flagged blocks are counted separately: their delta is the rejection signal.
ledger_counts() {
  python3 - "$CHASSIS" "$TOPIC_DIR" <<'PYEOF'
import importlib.util
import sys
from pathlib import Path

chassis, topic_dir = Path(sys.argv[1]), Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("semantic_state", chassis / "semantic-state.py")
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)
try:
    text = (topic_dir / "SOURCE-LEDGER.md").read_text(encoding="utf-8", errors="replace")
except OSError:
    print("0 0"); raise SystemExit
accepted = flagged = 0
# the SAME parser and acceptance rules the DONE gate uses (docs/citations.md): one
# identity per SRC id, blocks end at ANY next heading, a flagged block is refused
# unconditionally, and a verified block failing its type's required fields is NOT
# accepted evidence. Internal citations inherit their target's verification and add
# no own verified evidence, so they are counted in neither number by design.
for bid, block in ss.parse_source_ledger(text).items():
    fields = block.get("fields", {})
    if block.get("type") == "internal":
        continue   # internal citations inherit their target's state: in NEITHER counter
    if "flagged" in fields:
        flagged += 1
        continue
    if fields.get("verified") != "true":
        continue
    errs = ss.citation_errors_for_block(bid, block, topic_dir=topic_dir,
                                        topics_root=topic_dir.parent, allow_internal=True)
    if not errs:
        accepted += 1
print(accepted, flagged)
PYEOF
}
read -r verified_before flagged_before <<<"$(ledger_counts)"
verified_before=${verified_before:-0}; flagged_before=${flagged_before:-0}

# Literal substitution (render-prompt.py): sed's `&`/delimiter
# metacharacters corrupted prompts when values carried them (e.g. an
# agent_secondary of "codex exec ... 2>&1").
python3 "$CHASSIS/render-prompt.py" "$CHASSIS/ITERATION-PROMPT.md" \
  "TOPIC_DIR=$TOPIC_DIR" \
  "CHASSIS=$CHASSIS" \
  "DEGRADED_NOTE=$DEGRADED_NOTE" \
  "AGENT_NOTE=$AGENT_NOTE" \
  "GAP_POLICY_NOTE=$GAP_POLICY_NOTE" \
  "CITATION_NOTE=$CITATION_NOTE" \
  >"$prompt_file"

export RESEARCH_LOOP_TOPIC_DIR="$TOPIC_DIR"
export RESEARCH_LOOP_USAGE_FILE="$usage"
export RESEARCH_LOOP_LOG="$log"
# The research tool (gateway docs/STATION-CONTRACT.md §2) appends coverage states
# here; write_result reduces the file into the iteration result for the queue's
# saturation gate. Per-iteration file: a stale one never speaks for a fresh pass.
activity_file="$LOG_DIR/research-activity-$stamp.jsonl"
# 9·0 delegation coverage: the runner marks each iteration in the delegate ledger, so a
# marked window with zero launch events is EVIDENCE of zero delegation (the wrapper logs
# a launch line per invocation; launches without a usage line are unobserved outcomes)
printf '{"ts":"%s","event":"iteration","stamp":"%s"}\n' "$(date -u +%FT%TZ)" "$stamp" >> "$LOG_DIR/delegate-usage.jsonl" 2>/dev/null || true
export RESEARCH_LOOP_RESEARCH_ACTIVITY="$activity_file"
# 9·0 phase timings: the agent appends "<iso> <phase>" markers here; the throughput
# report turns them into per-phase durations (missing = unknown, never imputed)
export RESEARCH_LOOP_PHASE_LOG="$LOG_DIR/phases-$stamp.log"
# Downloads are TEMPORARY extraction space (8a): a per-iteration directory, removed on
# every exit path — normal or interrupted. What the agent keeps, it copies into the
# topic's own files during the iteration; retained source bytes never accumulate.
download_dir="$TOPIC_DIR/downloads/iter-$stamp"
export RESEARCH_LOOP_DOWNLOAD_DIR="$download_dir"
trap 'rm -rf "$download_dir"' EXIT
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
read -r verified_after flagged_after <<<"$(ledger_counts)"
verified_after=${verified_after:-0}; flagged_after=${flagged_after:-0}
# per-iteration provider-health context (9·0): the gateway's tokenless health aggregate,
# stamped at iteration end — counts only, and 'unavailable' is itself an observation
gateway_health=$(curl -s --max-time 5 "${RESEARCH_GATEWAY_URL:-http://127.0.0.1:8765}/v1/health" 2>/dev/null || true)
pending_refs=$(python3 -c "
import json
try:
    s = json.load(open('$TOPIC_DIR/SEMANTIC-STATE.json'))
    refs = s.get('pending_evidence_refs') or []
    print(json.dumps(refs if isinstance(refs, list) else []))
except Exception:
    print('null')" 2>/dev/null || echo null)
pending_count=$(python3 -c "
import json, sys
try:
    s = json.load(open('$TOPIC_DIR/SEMANTIC-STATE.json'))
    refs = s.get('pending_evidence_refs') or []
    print(len(refs) if isinstance(refs, list) else 'unknown')
except Exception:
    print('unknown')" 2>/dev/null || echo unknown)
# 9·0 phase timings need an END boundary or the last phase can never be measured;
# the runner owns iteration end, so the runner writes it (only when the agent wrote markers)
if [[ -n "${RESEARCH_LOOP_PHASE_LOG:-}" && -f "$RESEARCH_LOOP_PHASE_LOG" ]]; then
  echo "$(date -u +%FT%TZ) end" >> "$RESEARCH_LOOP_PHASE_LOG"
fi

# Chassis-measured DONE-gate probe (no lock — the queue re-validates with the
# pinned lock before acting). A loop that finishes its contract but fumbles
# the STOP file write must never idle: the chassis measures, the queue decides.
semantic_valid=false
if [[ -f "$TOPIC_DIR/SEMANTIC-STATE.json" ]] && \
   python3 "$CHASSIS/semantic-state.py" validate "$TOPIC_DIR" --topics-root "$(dirname "$TOPIC_DIR")" >/dev/null 2>&1; then
  semantic_valid=true
fi

# The chassis→queue result record: chassis-level facts the queue classifies
# from instead of scraping LLM transcript prose. Written on every path where
# the runner actually ran, success or failure, and always runner-agnostic.
# $3 (optional) = error_class: a FailureKind name recorded only when the
# CHASSIS knows the failure's class (e.g. a rejected DONE is configuration);
# the queue treats a recorded class as authoritative over prose scanning and
# falls back to the transcript tail when it is absent.
write_result() {
  RESULT_OUTCOME="$1" RESULT_EXIT="$2" RESULT_ERROR_CLASS="${3:-}" RESULT_STAMP="$stamp" \
  RESULT_BEFORE="$before" RESULT_AFTER="$after" \
  RESULT_SOURCES_CITED="$sources_cited" RESULT_LOG="$log" \
  RESULT_VERIFIED_ADDED="$((verified_after - verified_before))" \
  RESULT_FLAGGED_ADDED="$((flagged_after - flagged_before))" \
  RESULT_PENDING_COUNT="$pending_count" \
  RESULT_PENDING_REFS="$pending_refs" \
  RESULT_GATEWAY_HEALTH="$gateway_health" \
  RESULT_WORKER="${RESEARCH_LOOP_WORKER:-}" \
  RESULT_SECONDARY="${RESEARCH_LOOP_AGENT_SECONDARY:-}" \
  RESULT_RUNNER="$RUNNER_NAME" RESULT_TOPIC_DIR="$TOPIC_DIR" \
  RESULT_DEGRADED_FILE="${degraded_file:-}" \
  RESULT_SEMANTIC_VALID="$semantic_valid" \
  RESULT_ACTIVITY_FILE="${activity_file:-}" RESULT_CHASSIS="$CHASSIS" \
  python3 - "$LOG_DIR" <<'PY' || echo "warning: could not write iteration result record" >&2
import json, os, sys

log_dir = sys.argv[1]
sys.path.insert(0, os.environ.get("RESULT_CHASSIS") or ".")
from research_activity import summarize
activity = summarize(os.environ.get("RESULT_ACTIVITY_FILE"))
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
    "verified_added": int(os.environ.get("RESULT_VERIFIED_ADDED") or 0),
    "flagged_added": int(os.environ.get("RESULT_FLAGGED_ADDED") or 0),
    "pending_count": (int(os.environ["RESULT_PENDING_COUNT"])
                      if (os.environ.get("RESULT_PENDING_COUNT") or "").isdigit() else None),
    "pending_refs": (json.loads(os.environ["RESULT_PENDING_REFS"])
                     if (os.environ.get("RESULT_PENDING_REFS") or "").startswith("[") else None),
    "gateway_health": (json.loads(os.environ["RESULT_GATEWAY_HEALTH"])
                       if (os.environ.get("RESULT_GATEWAY_HEALTH") or "").startswith("{") else None),
    "worker": os.environ.get("RESULT_WORKER") or None,
    "agent_secondary": os.environ.get("RESULT_SECONDARY") or None,
    "stop_written": stop_written,
    "stop_first_line": stop_first,
    "semantic_valid": os.environ.get("RESULT_SEMANTIC_VALID") == "true",
    "degraded_capabilities": degraded,
    "research_failures": activity["failures"],
    "research_ok": activity["ok_keys"],
    "research_coverage": activity["coverage_by_source"],
    "log": os.environ["RESULT_LOG"],
}
error_class = os.environ.get("RESULT_ERROR_CLASS") or ""
if error_class:
    result["error_class"] = error_class
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
      write_result done_rejected 78 configuration
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
