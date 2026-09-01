# Failure-topology fixes — implementation plan (2026-09-01)

Origin: two-model committee review (GLM 5.2 + Kimi K3, converged 2026-09-01) of the
research-loop migration, cross-checked by the operator's Claude session. Root cause,
jointly endorsed:

> The migration swapped a fault-tolerant topology (soft-fail, cheap retries) for a
> fault-brittle one (hard-fail → attempt-burn → permanent park), driven by governance
> projections that are structurally blind to contract-compliant discovery work. The
> harness choice is second-order.

All defects below were re-verified against THIS repo at commit `dcc8f28` before
planning. Fixes are ordered; each phase is independently landable and testable.

## Hard constraints

1. **Provider-neutral by construction.** This engine runs mixed agent pairs per topic
   (`agent_main: claude` / `agent_secondary: codex exec -m gpt-5.6-luna`, and future
   pairs like terra/haiku) through `research_loops/runners/{claude,codex,hermes,generic}.sh`.
   Every fix lives in the shared chassis (`research_loops/chassis/`) or the queue
   (`research_loops/queue.py`, `runner.py`) — never in a runner. Runners stay thin
   translation shims; the chassis-emitted structured result (Phase 3) is the only
   interface the queue reads. Nothing in the queue may branch on provider identity.
2. **Class fixes, not instance patches.** Each phase must make the *category* of bug
   impossible (e.g. a parity test that fails when a validated field is not projected),
   not just add the missing field.
3. **Every phase lands as reviewed commits on a branch** (`fix/failure-topology`) with
   tests, then PRs to `trevorbyrum/research-loops`. The running deployment tracks a
   revision, never a dirty tree.

## Phase 0 — Freeze (DONE / in progress)

- [x] Graceful queue stop: `pause --reason ...` → `stopping: true`; in-flight
  `craft-software-architecture` iteration finishes naturally, then all items land paused.
- [x] Worker unit `research-loops-worker@worker-1.service` stopped automatically after
  the in-flight iteration lands (watcher with post-exit state check).
- [x] Branch `fix/failure-topology` off `dcc8f28`; green baseline confirmed
  (248 tests + 34 subtests) before any change.

## Phase 1 — Single source of truth for semantic progress

Defect: `semantic_projection` (chassis/semantic-state.py:665-682) omits
`pending_evidence_refs`, per-obligation `evidence_refs`, and `adequate_search` — all
three of which the completion validator reasons over. The contract *requires*
discovery-only iterations that change only these fields, so compliant iterations look
stalled. (Committee: this is the deepest defect — it mislabels success as failure.)

Fix (not a patch): define ONE canonical field specification consumed by BOTH
`completion_errors` and `semantic_projection`, so the liveness signature is derived
from exactly the state the validator considers semantic. The signature and the
validator can never disagree again because they share the field set.

- Keep the *inventory lock* projection (identity fields: id/text/source_ref +
  deliverable identity) unchanged and separate — it is deliberately narrower.
- Tests: (a) discovery-only iteration (pending ref added) changes the signature;
  (b) true no-op iteration does not; (c) **parity test** that introspects the
  validator's field usage vs the projection spec and fails on drift.

## Phase 2 — One stall detector, owned by the queue; liveness never consumes attempts

Defects: chassis exits 5 on the FIRST unchanged signature (run-topic.sh:143-145),
pre-empting the queue's own `stall_limit`; runner.py:62 maps exit 5 →
`FailureKind.CONFIGURATION` (terminal park, attempts consumed).

Fix: the chassis measures, the queue decides.
- run-topic.sh: delete the exit-5 decision; report signature (via Phase 3 result file)
  and exit 0 on a successful no-change iteration.
- runner.py: remove `5: CONFIGURATION`; add a `LIVENESS` outcome patterned on the
  existing `SUBSCRIPTION_LIMIT` non-consuming semantics (`consume_failure` class):
  unchanged signature does NOT increment `consecutive_failures` or attempts; only
  `stall_limit` CONSECUTIVE unchanged signatures escalate to needs_attention with
  kind=liveness. One detector, one threshold, one owner.

## Phase 3 — Structured result contract (retire regex-over-prose as primary classifier)

Defect: the queue classifies failures by regexing the last 2KB of LLM transcript
(runner.py:33-46) — prose standing in for an exit contract; capability degradations
(the 2,600 silent web-search failures in the old deployment) are invisible to the queue.

Fix: run-topic.sh writes `$LOG_DIR/result-<stamp>.json` from chassis-level facts:
`{schema_version, outcome, exit_code, signature_before, signature_after,
sources_cited, stop_written, degraded_capabilities: [], error_class?}` —
`error_class` present only when the chassis itself knows the failure's
FailureKind (e.g. a rejected DONE is `configuration`); the queue treats it as
authoritative and prose-scans only in its absence.
- The queue classifies from this file first; the tail-regex path survives only as a
  fallback when the file is absent (back-compat with old iterations).
- `degraded_capabilities` is the structured home for capability facts (gateway down,
  web backend degraded); the queue ledger records them so capability loss is
  queryable, never only agent prose.
- Runners are untouched — they already just propagate exit codes; the result file is
  chassis-owned, which is what keeps this provider-neutral.

## Phase 4 — Resumption semantics: taxonomy stops being decoration

Defect: `error_kind` (transient/outage/rate_limit/configuration/auth) affects only
backoff delay; `mark_needs_attention` is terminal for every kind. Transient outages
permanently park topics; recovery requires an operator.

Fix:
- Enumerate the legal `(status, desired_state)` pairs in queue.py as data (committee:
  hand-written transitions are a stuck-state generator).
- Auto-resume rule: needs_attention with `last_error_kind` ∈ {transient, outage,
  rate_limit} re-queues after a configurable cooldown (default 30m), with attempts
  reset. `configuration`/`auth`/`liveness` stay parked for an operator.
- Tests: park→auto-resume on cooldown; liveness parks don't consume attempts;
  configuration parks never auto-resume.

## Phase 5 — Completion integrity is mandatory

Defect: all installed topics have no completion lock; run-topic.sh only validates a
`STOP DONE` when `RESEARCH_LOOP_COMPLETION_LOCK` happens to be set, and the queue will
mark `completed` regardless. A topic can self-declare DONE with zero semantic
validation — the exact failure class this engine exists to prevent.

Fix:
- Queue refuses DONE→completed unless `semantic-state.py validate` passes;
  validation is unconditional, lock check included when a lock exists.
- Per-topic lock becomes required config; add `research-loops lock <topic>` tooling to
  generate AND update locks through a sanctioned, operator-confirmed path (removes the
  lock-drift landmine: an operator scope edit currently bricks completion forever with
  no remedy but hand-editing hashes).
- Generate locks for the 3 installed topics as part of landing.

## Phase 6 — Land, verify, restart

- Full suite + new tests green; PR(s) merged; deployment updated to the merged revision.
- `systemctl --user start research-loops-worker@worker-1`; `research-loops resume`.
- Acceptance watch on `craft-software-architecture`: a discovery-only iteration must
  produce a changed signature (Phase 1) and, where genuinely unchanged, a LIVENESS
  outcome with zero attempts consumed (Phase 2); result JSON present per iteration
  (Phase 3).

## Explicit non-goals (this pass)

- Hermes web-backend keys: only the `hermes.sh` runner path is exposed to the keyless
  Tavily fallback; the current deployment (claude main / codex delegate) uses native
  harness search. Fix when/if a hermes-runner topic is scheduled.
- Old private deployment (`/home/trevor/work/loops`): superseded by this repo; port
  nothing backwards.
- Dependency-provenance re-derivation and Uptime-Kuma alert channels: tracked
  separately.
