# Station boundaries: implementation and root review

The operator authorized execution with Terra agents followed by root review. Terra
implemented the control/scheduling, checkpoint, and intake boundaries. Root reviewed
and reconciled those changes with Fable's `85db4a1` handoff, corrected integration
and recovery defects, and ran the checks below. The scope contract is
[the implementation plan](2026-09-09-station-boundaries-implementation-plan.md).
This record describes code and disposable-environment validation, not a live cutover.

## Final architecture and scope

- Managed `state/control.sqlite3` owns configuration, queue, and the central work
  ledger. Legacy JSON remains an unmanaged compatibility path; it is not a fallback
  authority after explicit managed initialization.
- Five station profiles carry exact primary/secondary registry references and
  monotonic intervals. Active count enables only the contiguous prefix. Group
  updates are atomic. Assignment/lease reconciliation enforces priority at safe
  boundaries and prevents two stations from owning the same topic.
- Successful ordinary completions are accepted exactly once by run identity.
  Separate checkpoints retain the ordinary count, next ordinal, and saturation
  history. The shared checkpoint pair defaults to station 1 and is snapshotted per
  episode. Explicit shared pairs are also supported.
- Checkpoint proposals and standardized operator decisions live in the work ledger.
  Awaiting decisions releases capacity without deleting/reinserting/reordering the
  topic. A deliberate reorder during the wait remains authoritative.
- Strict intake schemas feed one application service behind CLI/MCP. Submission
  registers discovery, and approval registers research. Legacy admission/relock
  shortcuts reject in managed mode. Complete approved publication bundles are
  staged and recorded before actual inventory changes.
- The trusted controller owns state and approved inventory. Provider processes run
  under a separate OS execution identity. Unix peer credentials plus a current
  topic/lease capability authorize allowed semantic operations and checkpoint
  delegation. A caller-supplied role or actor grants no authority.

Ordinary search, extraction, citation acceptance, scientific interpretation,
semantic transition validation, completion criteria, retry/stall/saturation
thresholds, and substantive checkpoint admission/counter/repair rules were not
redesigned. Prompt edits replace model/role wiring and describe the new interfaces
and separate checkpoint handoff. Existing topic authority/evidence files were not
edited as part of this work.

## Findings corrected during root review

1. Replaced the preliminary checkpoint-as-ordinary-iteration implementation with a
   separate execution that follows research 25 and leaves research 26 next.
2. Reconnected managed research to the existing production runner. Preserved live
   PID/fingerprint adoption and prevented a resumed lease from increasing attempts
   or relaunching the same child.
3. Corrected assignment races, active-count launch checks, occupied-station
   handoffs, dependency/blocker eligibility, and pacing that incorrectly blocked
   lower stations while one higher-priority topic waited for its interval.
4. Corrected shared checkpoint adapter selection and full model/executable/argv
   propagation. Installed provider adapters and the delegate wrapper preserve
   literal argv and report child failure. Removed remaining contradictory fixed
   model names from the ordinary role contract.
5. Required actual successful recorded independent counter execution. A model's
   final assertion cannot substitute for broker evidence or reset invocation
   budgets. Incomplete results and missing counters retain distinct holds/retries.
6. Made checkpoint decisions a durable intent, validated publication, and final
   ledger commit. Tested interruption after file publication and after database
   commit, partial decisions, duplicate requests, and invalid multi-change bundles.
7. Moved intake validation into an isolated staged publication. A failed approval
   cannot promote actual files before validation; replay after files but before
   queue registration inserts one research item. Removed the need to hand-edit a
   QA file to compensate for missing application wiring.
8. Repaired Unix boundary integration: output file ownership, account environment,
   state-command signature forwarding, approved-file mode/owner preservation,
   symlink-resistant replacement, and protected checkpoint reports.
9. Routed remote operator CLI/MCP before private database/usage-ledger probes.
   Preserved structured controller diagnostics, blocked legacy admission helpers,
   and made checkpoint policy plus interval updates one transaction.
10. Preserved central proposal allowance across decisions. Added an explicit
    versioned operator reset. Prior-review reuse checks material files, inventory,
    decisions, and resets; transcript growth alone is insufficient to demand a new
    debate, while changed material or an incomplete prior review forbids reuse.
11. Made automatic gap publication stage the original chassis operation, commit its
    validated bundle before publication, serialize approved writes, and commit
    inventory/queue lock/budget together. Exact replay neither duplicates the
    obligation nor spends the budget twice. Pending publication blocks further
    semantic writes until recovered.
12. Corrected migration catch-up episodes to use the full runtime episode schema,
    including delegate budgets and attempt history. Seeded reviewed deepening
    entries into the actual trigger ledger, and excluded historical completed
    topics from catch-up review scheduling.

## Acceptance evidence against the plan

The acceptance IDs below group related assertions. Tests validate deterministic
mechanics using disposable state and fake provider executables; they are not live
model quality or provider-account tests.

| Plan checks | Evidence and result |
|---|---|
| A01–A03, A15–A17, A40 | `test_control_store`, `test_station_scheduler`, `test_managed_delegate`, `test_checkpoint_lifecycle`: exact registered pairs, shared-pair snapshots, all/subset/role changes, invalid configuration rollback, atomic policy+interval update, bounded independent delegate records. |
| A04–A10 | `test_station_scheduler`: active-prefix claim and spawn guards, downscale between claim/launch, equal-interval deterministic priority, occupied reordering, production finalization, duplicate-writer guard, pacing transfer versus preserved failure delay, existing PID adoption. |
| A11–A14, A18–A20 | `test_checkpoint_lifecycle`, `test_managed_execution`: exactly-once count, cadence/deepening coalescing, no checkpoint count, strict incomplete-result behavior, no-proposal resumption, replay and material-reuse checks. |
| A21–A25 | `test_station_scheduler`, `test_checkpoint_lifecycle`, `test_publication_recovery`: review hold leaves canonical order, capacity reassignment, final decision restores eligibility, partial decisions remain awaiting operator, stale/malformed/replayed decisions, recoverable inventory publication. |
| A26–A27 | Managed production runner review plus `test_managed_execution`, existing `test_stall_guard`, `test_iteration_result`, `test_completion_hook`: separate checkpoint branch precedes ordinary completion handling and leaves ordinary streaks/counts unchanged. |
| A28–A32 | `test_intake_boundaries`, `test_interface_contract`, `test_operator_transport`, `test_mcp_wire`, `test_mcp_server`, `test_cli`: schema examples accepted by actual validators, unknown fields rejected, fresh draft result identity, automatic registration, staged failure/replay, legacy shortcut denial, shared remote dispatch. |
| A33 | Diff inspected against `c11a004` and Fable `85db4a1`: worker algorithm remains the existing runner/chassis; role substitutions and controller interfaces are explicitly identified above. |
| A34–A35 | `test_controller_access` and `test_managed_execution`: real separate UID denied direct database/access/contract writes and unlink; payload impersonation denied; allowed original state CLI operations succeed through authenticated socket. |
| A36 | Wheel package includes checkpoint protocol, schemas, delegate wrapper and adapters; disposable non-editable installation exercised outside checkout during Terra/root integration. |
| A37 | Station status exposes configuration/effective shared pair/current+desired assignments/central counts/hold state. Dashboard distinguishes all configured stations from enabled capacity and draining. Process liveness is explicitly `unknown` where no verified observation exists. |
| A38–A39 | `test_control_store`: migration dry-run performs no initialization, explicit successful-count baselines ignore attempts, overdue review starts with full runtime budget, reviewed deepening is not repeated, completed historical records remain completed. |

The strongest integration test launches the real ordinary chassis and default
checkpoint adapter through a real controller socket under a separate execution UID.
The fake provider emits production-shaped final output, and the checkpoint primary
calls the actual delegate broker to launch its counter process. Observed counts are
`25, 25, 26`, with outcomes ordinary scheduled, checkpoint complete without proposals,
ordinary scheduled, and next ordinal 27. Proposal/decision publication is separately
covered with real SQLite and filesystem crash injection.

Final validation on 2026-09-09:

- `.venv/bin/python -m pytest -q tests`: **479 passed, 55 subtests passed**
  in 56.70 seconds. The distinct-UID integration tests executed without skips.
- `git diff --check`, Python compilation, and shell syntax checks passed.
- A wheel built successfully; inspection confirmed the packaged checkpoint
  protocol, new schemas, delegate wrapper, controller, and deployment entry code.
- Captured local test output: `/tmp/station-boundaries-final-suite.log`.

## Deployment boundary and explicit limitations

No live migration, account provisioning, service restart, model selection, approved
topic edit, or production count backfill was performed. The reviewed procedure is
[managed-deployment.md](../managed-deployment.md); exact operator payloads are in
[managed-stations.md](../managed-stations.md). The legacy same-user service template
cannot enforce the managed filesystem boundary and must not be advertised as doing
so. Managed bootstrap starts at active count zero and requires explicit production
profile pins, active count, monotonic intervals, and audited successful-count and
checkpoint-history inputs.

The implementation retains unmanaged compatibility rather than silently migrating
running workers. Historical Fable JSON migration behavior is not the managed cutover
path. Migration refuses in-flight legacy work; it requires an explicit drain and
backup, not guessed process adoption or inferred successful counts.

Approved additions and amendments publish through the obligation decision path.
A `scope_request` records a proposed mission change but cannot use that path to
rewrite authority; explicit new-authority work remains outside this change. Unknown
process liveness remains visibly unknown. Provider availability, credentials, and
actual configured production model behavior need verification at cutover.

The independent `gateway/` project was not changed. Running unqualified pytest
collects its separate suite, which cannot import optional `psycopg` in this
research-loop environment. The complete relevant suite command is
`.venv/bin/python -m pytest -q tests`; no gateway pass is claimed.

The operator subsequently authorized committing and merging this reviewed work
after Fable's `85db4a1` commit. Git history records the implementation commit and
merge into `main`. Live deployment remains separate from that repository merge.
