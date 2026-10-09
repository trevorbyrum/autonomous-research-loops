# Gen-2 debt register

Charter, "Root-cause fixes, not patches" (the operator, 2026-09-30): *a MITIGATION always blocks and escalates to the operator. Only the operator can accept one, and an accepted one is logged here with its owning phase and removal condition; the build fails if that phase closes with the entry still open.*

This register holds two kinds of entry, and nothing else:

- **mitigation**: a correction that makes a reproduction pass without removing its cause, accepted by the operator, with the review that found it, the operator's acceptance and its date, an owner, and the condition that removes it.
- **obligation**: something an operator ruling or a review has already assigned to a later task or phase, written down so it cannot be lost: a rule that task must satisfy, a release step that phase must run. An obligation is not a mitigation and nothing in the code is pretending to be finished; it is a promise with an owner.

**What goes in.** The test is whether the build could lose it, not who assigned it: an obligation assigned by an operator ruling, by a review at any gate (Astra's A, B, C or D, or a re-review's ruling on a coder question), or by an operator request that a later phase carries, has an entry, with its owner and the condition that closes it. A prerequisite is part of the obligation: where a ruling says something must exist BEFORE something else is used (DEBT-014), the entry says so in `what` and `removal`, because the phase-close check can enforce only a deadline (an open entry when its owner closes) and cannot see an early use; whoever reviews the early use reads the entry. An item recorded only in BUILD-STATE or REVIEW-LOG prose is not in the register until it has an entry.

**What is not debt.** An epistemic fact is neither. Under trust model B (operator ruling 2026-10-02, "Operator rulings on Gate D #2", item 1) Python's language limits (identity checks, private-field access, importable helpers, a monkeypatched standard library), finite testing, the frozen supported-format and resource policy (item 2) and the two sanctioned predicates are documented boundaries of the design, stated where they apply (INVARIANTS B-1, H-5, H-6 "What this does not establish"), not obligations to be paid. They have no entries here.

## How this is checked

`make gen2-debt` (run by `make gen2-check`; `tools/check_gen2_debt.py`) reads the entries below and `docs/gen2/phase-status.json`. It fails when:

- an entry is `open` and its owner is a closed task or phase, or a task of a closed phase (the phase-close check);
- an entry is incomplete, malformed or duplicated, or names an owner that `phase-status.json` does not;
- an entry is `closed` without `closed by`: the evidence that its removal condition was met;
- a phase is marked closed while one of its tasks is not.

**Whoever records a task's or a phase's acceptance in BUILD-STATE.md sets it to `closed` in `phase-status.json` in the same commit.** That is what arms the check; the check cannot tell that a task was accepted if nobody says so. Closing an entry is a change to this file: `status: closed` and a `closed by`, reviewed like any other.

## Accepted mitigations

### DEBT-018 - 2q-a source-guard gaps open at the round cap (2q)
- kind: mitigation
- status: closed
- owner: task 2q
- what: Task 2q-a closed at the round cap, by operator acceptance, with these findings from Astra's 2q-a-repair-7 review open:
  - **R7-1** (blocking class): an ordinary alias or re-export of `builtins` (for example `bi = builtins; bi.setattr(A, ...)`) bypasses the SOURCE-CONTRACT v2 mechanism ban. The planned fix is to refuse any reference to the `builtins` module, which production never uses, or to resolve ban references through the shared identity resolver.
  - **R7-2** (blocking class): an exact payload exception statement can write through a different parameter, or from a static method. The planned fix is to pin each exception's whole function (signature and body) the way the loader is pinned.
  - **Non-blocking:** a file-wide builtin-alias set falsely refuses an unrelated `import re as b` in another function.

  Production is unaffected: the metrics are unchanged and nothing in production is refused.
- found by: Astra, private/reviews/gen2-2q-a-repair-7-astra-review-20261006.md (R7-1, R7-2, non-blocking item 1)
- accepted by: the operator, 2026-10-06 ("Close and move on"), at the round cap after the orchestrator recommended closing 2q-a with these fixes owned by task 2q
- removal: a 2q tooling slice, together with DEBT-016 and DEBT-017, makes these fixes, with interpreter-backed regressions and controls; its review confirms them before 2q closes and before Gate D #5.

Before this entry, the operator had accepted no mitigation. The record: the two mitigations Astra found in 2b-repair-3 (F1, the relaxed A9 store rule; F2, read-time reinterpretation of legacy rows) were escalated and the operator ruled "fix both properly; neither is accepted as debt" (2026-09-30), and both were repaired in 2b-repair-4 and -5; after 2b-repair-11 the operator was offered "accept them as debt and close 2b" and chose to fix the bugs ("or why don't we try to address the bugs", 2026-10-02); the language-level residuals of 13a were ruled documented boundaries, not debt (2026-10-02, above). A later mitigation enters here only on the operator's acceptance.
- closed by: task 2q-t1 (`32489d9`), whose removal conditions Astra confirmed in private/reviews/gen2-2q-t1-astra-review-20261006.md ("2q-t1 is ACCEPTED; DEBT-016, DEBT-017 and DEBT-018 are closable"), 2026-10-06

## Owned obligations

### DEBT-001 - gateway-client construction site (2e1)
- kind: obligation
- status: open
- owner: task 2e1
- what: A `GatewayClient`, and any call to its `resolve()`, is constructed only inside a supervised job child, so that the supervisor's job `deadline_at` termination (`gen2/supervisor/supervisor.py` decides on the deadline; `gen2/supervisor/jobs.py` ends the job's process group, SIGTERM then SIGKILL) bounds the name lookup that the client's own deadlines do not reach (`getaddrinfo`). Nothing enforces the placement today: no code in `gen2/` outside the client package and its tests constructs a client, so 2e1's wiring makes the first construction site.
- source: operator ruling 2026-10-02, option (a) for the 2b-repair-15 F2 DNS residual (REVIEW-LOG.md "Operator ruling: the DNS residual"; BUILD-STATE.md 2e1 entry; INVARIANTS H-6 "Authority and withdrawal")
- removal: The 2e1 review verifies that no other construction site exists (the engine process, the router and the operator tools have none): every construction and every `resolve()` call in `gen2/` outside tests is inside a supervised job child.

### DEBT-002 - one client instance per station or job (2e1)
- kind: obligation
- status: open
- owner: task 2e1
- what: A `GatewayClient` instance is serial: an overlapping or re-entrant call on one instance is refused before any I/O (`ClientBusy`), while separate instances, one per station or job, run fully concurrently. The client is built and proven (task 2b-repair-17: `gen2/tests/test_gateway_ownership.py`, mutants `2B17-*`; INVARIANTS H-6 "Ownership"). The owned remainder is the wiring: each station or job gets its own client, and no instance is shared between concurrent callers, which would turn their overlap into refusals. The operator's requirement is the concurrency ("as long as concurrent connections can run"), not an instance count.
- source: operator ruling 2026-10-03 (REVIEW-LOG.md "Operator ruling: the client model"; INVARIANTS H-6)
- removal: The 2e1 review verifies, in the same site inventory as DEBT-001, that each station or job constructs its own instance and none is shared by concurrent callers.

### DEBT-003 - retrieval-audit evidence requirement (2e2)
- kind: obligation
- status: open
- owner: task 2e2
- what: Before real workflow acceptance, 2e2 must give the sampled state-integrity audit an independently checkable evidence requirement for retrieval: what the trusted capture retains of each retrieval so that a sample can be re-derived without trusting the claim, a missing required item being itself an audit failure. Today `gateway_call_ref` acknowledges a durable call row of the gateway (the request, its correlation and telemetry), not a response artifact, and D-1's raw-response retention is for decision receipts, not retrieval. No new router writer and no duplicated provider parser in the router. The relabel case disclosed in 2b-repair-13d awaits it.
- source: Gate D #2 finding F6 (private/reviews/gen2-gate-d-2-astra-review.md), recorded by task 2b-repair-14 (BUILD-STATE.md 2e2 entry)
- removal: 2e2's sampled-state audit has that evidence requirement, implemented and tested, before real workflow acceptance, and the 2e2 review (Gates A and C) confirms it.

### DEBT-004 - the genuine rejected-credential demonstration (2e1)
- kind: obligation
- status: open
- owner: task 2e1
- what: DEPLOYMENT-CONTRACT §4(d) as the operator amended it: the offline scope of the Phase 1 demonstration ((a), (b), (c), (d1), (d2a); AUTH-DEMO.md) was accepted, and the residual (a revoked credential, or one that expired without declaring it; AUTH-DEMO.md F1, d2b) is a binding requirement gating the first live provider execution. A real invocation's authentication failure records a dated `failing` fact and a typed hold and the invocation ENDS FAILED with retained evidence, never a zero-result pass, shown with the pinned runner against a genuinely rejected credential before any productive call.
- source: operator decision 2026-09-29, "OPERATOR DECISIONS at the Phase 1→2 gate" (REVIEW-LOG.md; BUILD-STATE.md 2e1 entry)
- removal: 2e1's demonstration passes with the pinned runner before any productive call is admitted, and 2e1 is accepted.

### DEBT-005 - stores written before 2b-repair-13b (Phase 4)
- kind: obligation
- status: open
- owner: phase 4
- what: Stores written before 13b are refused by the current opener (schema mismatch, same `user_version`). Any import or restore must keep the old counts and identities, mark unrecoverable end knowledge `unknown`, and never infer exhaustion from old `complete` rows.
- source: Astra's 2b-repair-13b review (private/reviews/gen2-2b-repair-13b-astra-review-20261002.md), recorded in BUILD-STATE.md "Phase 4 release items"
- removal: Phase 4's import or restore of such a store is run and shows the counts and identities kept and no exhaustion inferred from an old `complete` row.

### DEBT-006 - real-data migration of old gateway records (Phase 4)
- kind: obligation
- status: open
- owner: phase 4
- what: The real-data migration of old gateway records (`gateway/research_gateway/registry/migrate.py`) runs only at a release the operator approves, on disposable databases until then, and is complete only at zero unconverted records.
- source: operator ruling 2026-09-30, "OPERATOR RULINGS on the Phase 4 release items", (a) (REVIEW-LOG.md; BUILD-STATE.md "Phase 4 release items")
- removal: the migration has run at an operator-approved release and its completion check reports zero unconverted records.

### DEBT-007 - stopping and fencing every old gen-1 writer (Phase 4)
- kind: obligation
- status: open
- owner: phase 4
- what: Every old gen-1 writer (gateway, loaders, maintenance jobs) is stopped and fenced before that migration, and none is ever restarted against the converted database: Astra showed that an old writer running after conversion re-loosens restrictions. The procedure is the operator's to decide when Phase 4 arrives.
- source: operator ruling 2026-09-30, "OPERATOR RULINGS on the Phase 4 release items", (b) (REVIEW-LOG.md; BUILD-STATE.md "Phase 4 release items")
- removal: the operator has decided the procedure, every old writer is stopped and fenced before the migration, and none is restarted against the converted database.

### DEBT-008 - gen-1's unrecoverable non-lead restrictions (Phase 4)
- kind: obligation
- status: open
- owner: phase 4
- what: The affected regenerable cache rows (gen-1 recorded no non-lead member restrictions) are purged at cutover and refetched with current writers. They are not carried forward as if preserved.
- source: operator ruling 2026-09-30, "OPERATOR RULINGS on the Phase 4 release items", (c) (REVIEW-LOG.md; BUILD-STATE.md "Phase 4 release items")
- removal: the affected rows are purged at cutover and refetched, and none is carried forward.

### DEBT-009 - database privilege separation for gateway serving (Phase 4)
- kind: obligation
- status: open
- owner: phase 4
- what: The serving principal can read stored records only through `gateway/research_gateway/registry/schema.sql::servable_records`, never the base table; harvest, migration and writers have separate privileges. Until then the source-level check in `gateway/tests/test_record_gate.py` is not runtime access control.
- source: Astra's 2b-repair-5 review (private/reviews/gen2-2b-repair-5-astra-review-20260930.md), recorded in BUILD-STATE.md "Phase 4 release items"
- removal: Phase 4 deployment and cutover qualification include a refused direct-table read and a successful view read by the serving principal.

### DEBT-010 - live provider canary qualification (Phase 4)
- kind: obligation
- status: open
- owner: phase 4
- what: Phase 4 verifies each provider's end and continuation behaviour live and checks for provider drift. This does not replace the provider-grounded end rules that 2b established.
- source: Astra's 2b-repair-6 review (private/reviews/gen2-2b-repair-6-astra-review-20261001.md), recorded in BUILD-STATE.md "Phase 4 release items"
- removal: Phase 4's live canary has qualified every lane's end and continuation behaviour and checked it for drift.

### DEBT-011 - gateway capability revision lifetime (Phase 3)
- kind: obligation
- status: open
- owner: phase 3
- what: The gateway's capability-revision counter lives in process memory. A restart within the same second, or two gateway processes, can reproduce stale current status; within one gateway lifetime the ordering is sound (2b-repair-3 to -5). Ordering must survive a restart and more than one process.
- source: Astra's 2b-repair-3 review (private/reviews/gen2-2b-repair-3-astra-review-20260930.md), assigned to Phase 3's gateway lifecycle work (REVIEW-LOG.md 2026-09-30); carried into BUILD-STATE.md by Gate D #1 finding 6
- removal: Phase 3's gateway lifecycle work makes revision ordering survive a restart and several processes, and its review runs a restart and a second process against it.

### DEBT-012 - gateway adapter compatibility (Phase 3)
- kind: obligation
- status: open
- owner: phase 3
- what: Move the OpenAIRE adapter off the deprecated `/graph/v1/researchProducts` endpoint version, and migrate or qualify Kaggle's listing (its official client now uses `POST /v1/datasets.DatasetApiService/ListDatasets`; the adapter uses the legacy `GET /api/v1/datasets/list`). Done before Phase 4's live canary qualifies those lanes.
- source: operator rulings 2026-10-01 on the 2b review chain (REVIEW-LOG.md; BUILD-STATE.md "Phase 3 items")
- removal: both adapters are off the deprecated and legacy endpoints, or qualified against them, before Phase 3 closes.

### DEBT-013 - catalogue partial-result contract (Phase 3)
- kind: obligation
- status: open
- owner: phase 3
- what: The BLS, FRED, Census and BEA catalogues keep their readable entries and report the dropped ones, with an explicit entry, drop and continuation contract, instead of failing the whole answer closed.
- source: operator ruling 2026-10-01, commissioned for Phase 3 (REVIEW-LOG.md; BUILD-STATE.md "Phase 3 items")
- removal: the four catalogues implement that contract, tested, before Phase 3 closes.

### DEBT-014 - the importer's inventory of unexamined files (Phase 4)
- kind: obligation
- status: open
- owner: phase 4
- what: The dry-run importer's report lists only the files it tried to read (`sources`). An extra state file, a topic log that is not JSONL, or an unknown topic file under the gen-1 root is invisible to it (Astra's 0b-repair re-review put all three in a synthetic root). The report must list every entry under the gen-1 root that it never examined, each with a reason, from a no-follow metadata walk from the root descriptor with its scope stated; the walk parses and imports nothing. This inventory must exist BEFORE any dry-run report is used as completeness or reconciliation evidence for Phase 4 migration planning: until it exists a report is not evidence of whole-tree completeness, and the accepted 40-record inventory fixture covers only its own input families (`gen2/store/README.md`). A deadline at Phase 4's close alone would be too late, because the planning that relies on the report comes first. No importer change is required before that use.
- source: Astra's 0b-repair re-review, ruling on coder question 3 (private/reviews/gen2-0b-repair-astra-review-20260925.md), accepted into `gen2/store/README.md` and carried by Gate D #1; recorded by Astra's 2q-a review F3 (private/reviews/gen2-2q-a-astra-review-20261003.md)
- removal: The importer's report carries that inventory, tested against a synthetic root holding an extra state file, a non-JSONL topic log and an unknown topic file, and it exists before the first use of a dry-run report as migration-planning evidence; Phase 4 does not close without it.

### DEBT-015 - the cadence usage estimator (Phase 3)
- kind: obligation
- status: open
- owner: phase 3
- what: Given a topic profile and a cadence, estimate the API cost and the subscription-plan share (for example, the percent of a weekly window) that the cadence brings. It is calibrated from the Phase 2+ usage records (task 2e1 captures them per invocation and attempt: tokens, model, provider-reported cost when there is one, wall time, correlated gateway calls and credits, kind, topic and cadence), by fitting tokens per percent-of-window from quiet-account windows, and it reports RANGES with the calibration's uncertainty, never a bare point; an unreported value is `unknown`, not zero. A provider's subscription window is account-wide, shared by everything that uses the account, so the before and after readings 2e1 stores are context and never per-run attribution: the estimator may use them only through the quiet-account calibration and must not present a per-run (or per-agent) share read from them. One Phase 2 run cannot calibrate it, which is why it waits for Phase 3.
- source: operator request 2026-09-29, "OPERATOR REQUEST: per-run usage metrics sufficient to estimate cadence cost (API and subscription share)" (REVIEW-LOG.md; BUILD-STATE.md "Carried to Phase 3 - usage estimator"); recorded by Astra's 2q-a review F3 (private/reviews/gen2-2q-a-astra-review-20261003.md)
- removal: Phase 3 delivers the estimator with its calibration method, reporting ranges and the uncertainty of the fit, and with account-wide readings never attributed to a run; the Phase 3 review confirms it before Phase 3 closes.

### DEBT-016 - 2q-a non-blocking review findings (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-a-repair-4 review, classified under the charter's "Review throughput" rule (operator 2026-10-05). The operator accepts these entries in advance through that rule. They are:
  - (1) the loader fingerprint omits the definition-time effects of other definitions in the loader module (defaults and class bodies), so qualify the fingerprint claim and guard or document the bound;
  - (2) the transformation composition `property(classmethod(...))` is not recognised;
  - (3) `test_the_probe_files_are_astras` checks names and counts, not source identity;
  - (4) `test_a_masking_member_is_data_for_every_name_and_not_only_hash` claims slots and data but exercises only a property and a method;
  - (5) the loader tests' closure claim overstates their listed edits;
  - (6) the "tracer-only failure" disclosure is wrong, because both supervisor tests skip in plain and traced runs;
  - (7) the completion record detects accidental incomplete execution, not deliberate same-process forgery (trust model B), so state that boundary in the docs.
- source: private/reviews/gen2-2q-a-repair-4-astra-review-20261005.md (Gate C, F2, F3, completion validity, and "Follow-up 2026-10-05")
- removal: a 2q tooling and documentation slice corrects the claims and guards or documents each bounded limitation, and its review confirms it before 2q closes.
- closed by: task 2q-t1 (`32489d9`), whose removal conditions Astra confirmed in private/reviews/gen2-2q-t1-astra-review-20261006.md ("2q-t1 is ACCEPTED; DEBT-016, DEBT-017 and DEBT-018 are closable"), 2026-10-06

### DEBT-017 - 2q-a slice A non-blocking review findings (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-a-repair-6 and 6b reviews, accepted in advance under the charter's "Review throughput" rule:
  - (1) the parenthesised annotated target `(x): int` is falsely refused as `SRC-FORM-UNRECOGNISED`; it fails closed;
  - (2) the scope-pairing validation is a consistency check, not proof against every wrong pairing, so narrow the "proved both ways" wording and keep the control for equal identifiers with different flags;
  - (3) the 6b corpus evidence wording ("about 6,700" against 5,993 logged files; filtered fuzz cases);
  - (4) scope correspondence is validated only for CPython 3.12.3, and must be revalidated at any interpreter upgrade.
- source: private/reviews/gen2-2q-a-repair-6-astra-review-20261005.md and private/reviews/gen2-2q-a-repair-6b-astra-review-20261005.md (non-blocking lists)
- removal: a 2q tooling and documentation slice corrects (1) to (3), and (4) is carried into the interpreter-upgrade task's acceptance criteria; its review confirms this before 2q closes.
- closed by: task 2q-t1 (`32489d9`), whose removal conditions Astra confirmed in private/reviews/gen2-2q-t1-astra-review-20261006.md ("2q-t1 is ACCEPTED; DEBT-016, DEBT-017 and DEBT-018 are closable"), 2026-10-06

### DEBT-019 - 2q-b1 non-blocking review findings (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-b1 review, accepted in advance under the charter's "Review throughput" rule:
  - (NB-1) `gateway/tests/test_core_foundations.py` hard-codes `correlation` in `DECLARED`, so deleting `code: LaneClient.correlation()` leaves the interface tests green; derive the declared methods from the protocol and add a method-omission mutant with a control;
  - (NB-2) the moved exceptions' `__module__` is now `research_gateway.core.payload`, so new pickles of these classes don't load on the old tree; there is no production pickle consumer, but document the compatibility bound;
  - (NB-3) the consumed ledger prose has small inaccuracies (`MeteredClient` should be `LaneClient`; ML-0005's reach path; ML-0014's "unchanged"), and the error-path driver repeats the stale protocol name.
- source: private/reviews/gen2-2q-b1-astra-review-20261006.md (NB-1 to NB-3)
- removal: a 2q slice makes these corrections, and its review confirms them before 2q closes.
- closed by: task 2q-t2 (`642a0ef`), whose removal conditions Astra confirmed in private/reviews/gen2-2q-t2-astra-review-20261007.md ("2q-t2 is ACCEPTED; DEBT-019, DEBT-021 and DEBT-022 are closable"), 2026-10-07

### DEBT-020 - 2q-b2 non-blocking review findings (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-b2 review, accepted in advance under the charter's "Review throughput" rule:
  - (1) the 2q-b2 evidence summaries are stale (the comparison summary's counts; `healthy` missing from the coverage; `StatusCore` has 11 members, not 10), so regenerate them from the archived data with input hashes;
  - (2) the Router differential's masks can erase semantic differences (all long numerals and broad hash and id patterns; `invocation_status` omitted), so use field-aware normalisation that preserves identity relationships, add a negative control showing a semantic change is detected, and describe results as equality under the stated normalisation; this is owned by the next Router slice;
  - (3) don't widen the collaborator pattern's enforcement claims: the name-set checks don't enforce full Protocol conformance or nested `Rows`/`Schemas`, and `_snapshot` is writable. State those limits, keep the consumer-owned minimal interfaces, keep every write going through `_guarded` with `BEGIN IMMEDIATE` and the post-lock clock read, and don't widen `_snapshot` use.
- source: private/reviews/gen2-2q-b2-astra-review-20261006.md (non-blocking findings 1 to 3)
- removal: (2) in the next Router slice; (1) and (3) in the Router follow-on slices, with documentation reconciled; the review confirms them before 2q closes.
- closed by: task 2q-t3 (`a3d1b34`..`8f8e8d2`), confirmed by Astra in private/reviews/gen2-2q-t3-astra-review-20261007.md ("2q-t3 is ACCEPTED", landing confirmation 2026-10-08 on the combined run at `623576e`), 2026-10-08

### DEBT-021 - 2q-t1 non-blocking review finding (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: SOURCE-CONTRACT's "What the ban does not see" paragraph still gives `__builtins__["eval"]` as an unseen example, but the 2q-t1 name ban now refuses it; replace the example and keep the real string-reflection boundary. Accepted in advance under the charter's "Review throughput" rule.
- source: private/reviews/gen2-2q-t1-astra-review-20261006.md (non-blocking item 1)
- removal: the example agrees with the demonstrated refusal, confirmed by the next 2q review.
- closed by: task 2q-t2 (`642a0ef`), whose removal conditions Astra confirmed in private/reviews/gen2-2q-t2-astra-review-20261007.md ("2q-t2 is ACCEPTED; DEBT-019, DEBT-021 and DEBT-022 are closable"), 2026-10-07

### DEBT-022 - 2q-b4 non-blocking review findings (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-b4 review, accepted in advance under the charter's "Review throughput" rule:
  - (NB-1) the decoder dispatch now checks `_SCALARS` before `_NORMALIZERS`, so a hypothetical `token` normalizer would no longer take precedence; production registers only `year` and `number`. Restore the original precedence with a regression case, or document the supported extension policy;
  - (NB-2) the 2q-b4 handoff says 51 re-anchored mutants where the true count is 50;
  - (NB-3) the name of control `test_control_a_list_of_members_and_a_keyed_container_that_are_readable_hold_what_was_sent` overstates its assertion, which checks cardinality only.
- source: private/reviews/gen2-2q-b4-astra-review-20261006.md (NB-1 to NB-3)
- removal: a 2q slice makes these corrections, and its review confirms them before 2q closes.
- closed by: task 2q-t2 (`642a0ef`), whose removal conditions Astra confirmed in private/reviews/gen2-2q-t2-astra-review-20261007.md ("2q-t2 is ACCEPTED; DEBT-019, DEBT-021 and DEBT-022 are closable"), 2026-10-07

### DEBT-023 - 2q-b3b non-blocking review findings (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-b3b review, accepted in advance under the charter's "Review throughput" rule:
  - (1) 352 replay scenarios per change remain UNRESOLVED (real job-process identity in `start_fingerprint`, plus 3 concurrency or replacement-process races), so they are outside the replay verdict; the remaining Router work, especially Lifecycle and Scheduling, must supply deterministic process and concurrency fixtures at the seams or separately accepted contract-level evidence;
  - (2) the reversed capability-fact order and global-hold order are undetected for lack of stable multi-row fixtures, so add fixtures with at least two distinguishable rows and show that each reversal is detected;
  - (3) replay summaries should count readable row snapshots separately from closed-store markers.
  - Progress 2026-10-08: items (2) and (3) are done by task 2q-t3 and accepted by Astra. Item (1), the 352 unresolved scenarios, stays open.
- source: private/reviews/gen2-2q-b3b-astra-review-20261007.md (non-blocking list)
- removal: the remaining 2q Router and replay slices meet each item, and the review confirms them before 2q closes.
- closed by: item 1 by task 2q-t4b (`5ef2130`, `e9d090e`, `5de8d7f`; Astra private/reviews/gen2-2q-t4b-astra-review-20261009.md: "2q-t4b is ACCEPTED. DEBT-023 item 1 is closable with the explicit dispositions", with 7 named unresolved scenarios bounded by contract evidence); items 2 and 3 by task 2q-t3 (Astra, 2026-10-08), 2026-10-09

### DEBT-024 - 2q-b5 non-blocking documentation finding (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Astra's 2q-b5 NB2, still open after 2q-e1: the `_response.py` module introduction says `base.py` imports both `_transport.py` and `_links.py` when it imports only the transport, and `base.py`'s retained step 5 still describes returning parsed JSON although `Response` is sealed and decoding is explicit. These are prose corrections only, accepted in advance under the charter's "Review throughput" rule.
- source: private/reviews/gen2-2q-b5-astra-review-20261006.md (NB2); private/reviews/gen2-2q-e1-astra-review-20261007.md (non-blocking list)
- removal: the descriptions match the imports and the sealed-response API, confirmed by the next 2q review.
- closed by: task 2q-t3 (`a3d1b34`..`8f8e8d2`), confirmed by Astra in private/reviews/gen2-2q-t3-astra-review-20261007.md ("2q-t3 is ACCEPTED", landing confirmation 2026-10-08 on the combined run at `623576e`), 2026-10-08

### DEBT-025 - 2q-b6 non-blocking review findings (2q)
- kind: obligation
- status: closed
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-b6 review, accepted in advance under the charter's "Review throughput" rule:
  - (NB1) serial mutation-harness contamination: `tools/gen2_mutations.py --only 2QB6 --jobs 1` reports 5 of 6 killed, because `_run_file_mutation` leaves replaced modules loaded between serial cases, so a later control reads a deleted temporary file. It reproduces on the earlier base, and the parallel runs used for landing are unaffected;
  - (NB2) the `Rows` protocol docstring in `gen2/router/lifecycle.py` says its use is inside the core's transaction, but `invocation_status` selects outside one, as it did before.

  The carried 352-scenario replay coverage and the ordering fixtures are already DEBT-023.
- source: private/reviews/gen2-2q-b6-astra-review-20261007.md (non-blocking list)
- removal: the harness unloads replaced modules between serial cases, with a regression test, and the docstring distinguishes reads from writes; the next 2q review confirms both.
- closed by: task 2q-t3 (`a3d1b34`..`8f8e8d2`), confirmed by Astra in private/reviews/gen2-2q-t3-astra-review-20261007.md ("2q-t3 is ACCEPTED", landing confirmation 2026-10-08 on the combined run at `623576e`), 2026-10-08

### DEBT-026 - 2q-b8/2q-b9 documentation follow-through (2q)
- kind: obligation
- status: open
- owner: task 2q
- what: Non-blocking follow-through from Astra's 2q-b8 and 2q-b9 re-review, accepted in advance under the charter's "Review throughput" rule:
  - (1) `docs/gen2/BOUNDARIES.md` (around line 14) and the 2q-b9 evidence README (private evidence, outside the repo) still credit the `--inline` checker with checking the declared plumbing; mark those claims superseded and advisory, citing the re-review and the charter's "Refactor evidence standard";
  - (2) close out the remaining documentation: the historical mixin prose; the 2q-b8 README's replacement-rollback overstatement; the 2q-b9 branch and mutant accounting (106/108 branches; the unique-mutant count).

  The 352 unresolved replay scenarios are already DEBT-023 item 1.
- source: private/reviews/gen2-2q-b8-b9-astra-rereview-20261008.md (non-blocking follow-through)
- removal: the corrections land and the next 2q review confirms them before 2q closes.

### DEBT-027 - 2q-b10/2q-r1 non-blocking review findings (2q)
- kind: obligation
- status: open
- owner: task 2q
- what: Non-blocking findings from Astra's 2q-b10 and 2q-r1 review, accepted in advance under the charter's "Review throughput" rule:
  - (NB2) an intermittent `test_mutation_verdict` failure with lost diagnostics: `code: SerialRunTest.serial()` discards the child's stderr, and `verdicts()` asserts stdout before showing the return code. Keep the command, exit code, stdout and stderr on failure, and fix any cause that reproduces;
  - (NB3) `docs/gen2/ENVIRONMENT.md` still says the venv import check names only rfc8785/jsonschema, and its blanket transitive-dependency claim is too strong. Describe the actual import check and the separately verified dependency closure. The BOUNDARIES replay paragraph should separate the historical 352-scenario limit from the current 6 unresolved scenarios and the seam coverage that hasn't been reviewed;
  - (NB4) `tools/gen2_refactoring_detect.py` exits 1 (the count-mismatch status) on an invalid revision, where it documents exit 2. Align the error categories without changing how expectations are enforced.

  NB1 is DEBT-023 item 1.
- source: private/reviews/gen2-2q-b10-astra-review-20261008.md (non-blocking list)
- removal: a 2q tooling and documentation slice makes the corrections, and its review confirms them before 2q closes.

### DEBT-028 - readiness test flaky under load (2q)
- kind: obligation
- status: open
- owner: task 2q
- what: `gen2/tests/test_children.py::ReadinessTest.test_a_child_that_died_before_saying_it_fails_the_test_with_its_exit_status_and_stderr` failed once in the 2q-b11 landing run under machine load. A child that exited with status 3 ("database is locked") was classified as "still running when stopped, waited 0.0s" rather than "it had exited". It passes 10 out of 10 runs alone, and the code hasn't changed since `dd3b920`. Update 2026-10-09: the cause, from reading `gen2/tests/children.py::started`, is a race. After the child's stdout reaches EOF, `code: child.poll()` is called at once, and an exiting child can still be unreaped, so it's classified as "still running when stopped" and killed. Its scripted stderr ("database is locked") isn't a real database. Two of four full runs at 2q-b11's pin failed this way; the two reproduction runs on the 24-vCPU VM and one at 2q-b10 passed. The fix is to wait (bounded) for the child's exit after EOF before classifying. Make the classification deterministic: check exit status before the deadline verdict, or use an injectable clock. Add a regression that forces the race.
- source: the orchestrator 2q-b11 landing run of 2026-10-08, attempt 1 (private/evidence/2q-b11/orchestrator-attempt1/)
- removal: a deterministic classification with a forced-race regression, confirmed by a 2q review before 2q closes.

### DEBT-029 - 2q-t4b non-blocking review findings (phase 2)
- kind: obligation
- status: open
- owner: phase 2
- what: Non-blocking findings from Astra's 2q-t4b review, accepted in advance under the charter's "Review throughput" rule:
  - (NB1) the 2q-t4b evidence wording: the Router-call total should read 15,349 and 15,344; opt-out zero counts describe inactive accounting; counted first looks are distinct from positive-duration waits; the four supplemental negative-control inputs should point at the reviewer's retained archive;
  - (NB2) two replay-seam test titles promise more than their assertions (the stock-child poll check; ended-job "no second wait"), so narrow them or add the assertions.

  These are owned by phase 2 rather than task 2q so that 2q can close; they're documentation and test titles only.
- source: private/reviews/gen2-2q-t4b-astra-review-20261009.md (non-blocking findings)
- removal: the corrections land in a phase 2 maintenance slice, and its review confirms them before phase 2 closes.
