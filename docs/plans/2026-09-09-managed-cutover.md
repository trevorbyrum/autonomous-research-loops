# Managed research station cutover — 2026-09-09

The operator authorized fixing research-leverage and bringing every queued item
into the new setup, following the earlier implementation, merge, and push.
This receipt supplements the implementation review's pre-deployment evidence.

## Applied configuration

- Canonical authority: protected `state/control.sqlite3`, accessed by operators
  through `/run/research-loops/control.sock`. Legacy JSON is retained as history,
  not a writable fallback authority.
- Active count: **2**. Stations 1 and 2 form the enabled prefix; stations 3–5
  remain configured and disabled. Every station currently uses Terra primary and
  Luna secondary. Registered models are `gpt-5.6-terra` and `gpt-5.6-luna`.
- Intervals by station: **0, 1800, 1800, 1800, 1800 seconds**, preserving the
  existing effective pacing while satisfying the cascade.
- Checkpoints: enabled every 25 successful research completions and on deepening
  entry; shared pair inherited from station 1. Checkpoints have their own episode,
  delegate budget, results, proposals, decisions, and retry history.

## Queue and history reconciliation

All **94 existing records** retain their IDs and canonical order: 47 research
topics and 47 historical completed intake records. The 43 intentional research
pauses and two historical completed research topics remain intact. Classification
and research-leverage are the two topics selected to resume. Historical admission
records are preserved; new admissions use the strict intake application service.

All 47 approved research contracts passed structural checks and matched their
queue inventory locks. Every queue command now names the root-owned installed
chassis, and legacy per-item agents, intervals, and checkpoint counters were
removed. Successful counts and next ordinals live consistently in the work ledger.
No research authority, approved obligation, finding, or acceptance criterion was
rewritten for this cutover.

Count backfill uses unique successful ordinary execution records, excluding
explicit STOPs and structured provider/capability failures. Attempts and checkpoint
executions are not research completions. The migration baseline is 489 for
classification and 313 for research-leverage. Research-leverage's earlier manual
checkpoint is recorded at successful count 286 with its reviewed inventory, so
its overdue cadence-300 checkpoint remains required. Classification's overdue
cadence and observed deepening share one catch-up episode.

## Execution and integrations

Root-owned installed code is in `/opt/research-loops/venv`; provider children run
as the separate `research-loops-agent` account. Workers can write topic evidence
but cannot directly write the controller database or approved contracts. The
execution account has its own provider authentication and scoped research gateway
access; it does not receive the operator's Vault credential. Operator read ACLs
preserve access to research evidence and approved files.

System services replace the legacy same-user workers:

- `research-loops-controller.service`
- `research-loops-station@1.service` and `research-loops-station@2.service`
- `research-loops-managed-intake.service`
- `research-loops-managed-dashboard.timer` and its oneshot service

The legacy research/intake services and user dashboard timer are disabled. The
operator CLI and MCP bridge use the controller socket. A read-only event projection
feeds the existing PostgreSQL exporter without exposing writable controller state;
the exporter was corrected to ignore non-usage delegate launch records. Research
completion ingestion keeps its existing trusted hook.

## Defects repaired during live verification

1. Legacy workers had loaded an intermediate mutable-checkout script and parked
   research-leverage with `managed secondary profile is invalid`. The cutover
   archived that configuration STOP and restored a valid registered pair.
2. Source-coverage blockers incorrectly prevented research recovery. They remain
   evidence/completion constraints without independently forbidding research.
3. Zero-exit blocked/provider-failed attempts were incorrectly eligible for count
   increments. Managed accounting now excludes those unsuccessful executions.
4. Checkpoint context lacked delegate IDs while its protocol forbade inventing
   them. The controller now supplies exact role IDs, exact delegate response
   fields, JSON broker output, and usable bounded call timeouts.
5. A second delegate could fail because its report directory already existed.
   Report publication now supports sequential preparation/counter calls.
6. Released checkpoint leases left stale queue execution status. Finalization
   now clears the claimant/PID and restores queued or intentionally paused state.
7. Long checkpoint/discovery calls did not feed the systemd watchdog. Managed
   adapter calls now send periodic heartbeats with cleanup on success or failure.
8. Recovery now has a standard `checkpoint-retry --file` operation, with strict
   payload/revision/idempotency checks and no current lease or pending proposal.
   Successful same-episode delegate IDs replay their recorded results. Recovery
   preserves research counts, priority, proposal allowance, and spent launch slots.
9. The managed dashboard's active rows used attempt counts as iteration numbers.
   They now use the central completed count and current/next research ordinal,
   with separate checkpoint labels. Historical attempts remain history.

Ordinary worker research algorithms and scientific prompts remain outside these
repairs. Checkpoint prompts changed only to explain the controller interfaces and
recovery behavior.

## Backup and evidence

Durable private cutover evidence is under
`~/.local/state/research-loop-cutovers/20260909T165715Z/`: pre-drain and drained
state copies, a complete drained topics archive, prior user service definitions,
count provenance, conformance checks, deployment checks, and test output. These
private artifacts are not committed to the public repository.

## Live verification

At 17:28 UTC, both catch-up checkpoints were `complete_without_proposals`.
Classification completed research ordinal 490 after its checkpoint and was running
491 on station 1. Research-leverage resumed ordinary research ordinal 314 on
station 2. Both retained their queue positions and recorded successful independent
Terra counters. Research-leverage's counter survived the interrupted primary review;
retry did not refill or spend another counter slot.

The staged supervisor restart briefly reassigned the waiting review to station 1
while classification drained. Restarting that still-old supervisor interrupted the
review again. The same episode was recovered through the standard retry interface
after both supervisors loaded the fix; counts, counter evidence, and budgets were
preserved. No proposal decision was manufactured or approved during recovery.

The final conformance audit verifies all 94 IDs and their order, 43 intentional
pauses, historical completions, central count/next-ordinal consistency, removal of
legacy item mechanics, installed chassis commands, and all 47 contract locks and
filesystem protections. Both worker services and the controller are active. The
dashboard and PostgreSQL event projection/exporter refresh successfully. Installed
package files were compared byte-for-byte with the reviewed source.

Validation: **486 tests and 55 subtests passed** in the complete research-loop
suite after watchdog/replay repairs. The final dashboard display correction also
passes its focused suite. Real provider execution verifies authentication, managed
primary/secondary launch, controller-mediated independent counter review,
checkpoint completion, and ordinary research resumption; it is not a claim that
either topic's remaining scientific obligations are complete.
