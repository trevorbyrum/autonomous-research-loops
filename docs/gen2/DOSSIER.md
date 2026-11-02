# Task 2d dossier design

Design written before code, against `f8754ba` on `gen2` (2026-10-10).
Authority: private `gen2-flow-architecture-20260924.md` S4, S7, S8 and §4.8;
`methodology-synthesis-20260924.md`; `reviews/gen2-phase2-plan-audit-astra-20260929.md`
F3/F7/F10; Gate D #6, “Readiness and finite follow-through for 2d”; the
charter, BOUNDARIES, INVARIANTS, ACCOUNTING, EXPORT-API, and task 2c-4's
operator rulings. This note schedules work; it grants no new authority.

## Existing enforcement and remaining work

Paths below are relative to `gen2/`. SQL numbers name ordered schema parts
under `store/schema/`. Tests describe structural guarantees, not scientific
validity or a qualified live workflow.

| Requirement | Existing DDL, code and tests | Missing / owning slice |
|---|---|---|
| V-1 receipt binding | `03-evidence-and-decisions.sql`, `verification_receipts` JSON/column checks and binding trigger; `router/service.py::_validate_commit`, `router/evidence_writer.py`; `tests/test_store_ddl_evidence.py::VerificationTest`, `tests/test_router_evidence.py` | Actual verifier re-access and typed byte/span hand-off; slices 3–4, producer in 2e2. |
| V-2 truthful tiers | SQL 03 promotion and receipt-use triggers; `router/boundary.py::TIER`, receipt schema; the same verification tests. `router/verification.py`, `tests/test_verification_attention.py` route missing-content verdicts to owned holds (2d-4 part 1). | Cross-check obtained tier against access route and source/table availability; 2d-4 part 2. Consume receipts in dossier gates; 6. |
| V-3 independent checking | SQL 03 receipt role/binding triggers authenticate canonical bytes and extraction lineage; `VerificationTest` tests producer-byte reuse and rejected unvalidated extraction | Runtime re-access/validated-extraction path; 2d-4 part 2, with workflow execution in 2e2. |
| V-4 provisional / accepted support | SQL 03 `claims_accepted_support_needs_receipt` and `verification_receipts_use_matches_claim`; `router/evidence_writer.py::_promote_and_link_claims`; `VerificationTest` sampling/partial-support promotion refusals | Required receipts must also be checked over the dossier's exact claim revisions; 6. |
| V-5 disagreement | Typed `holds` in SQL 02 and outcome schema; Router writes holds; `tests/test_router_evidence.py`. `router/verification.py`, thin service/evidence-writer wiring and `tests/test_verification_attention.py` implement owned adverse-verdict holds, receipt/audit/status effects, replay and rollback (2d-4 part 1). | Runtime attention implemented. Deadline scheduling/escalation belongs to 2e2. |
| V-6 byte checks before NLI | SQL 03 `quote_checks` mismatch/alarm quarantine and receipt binding; `VerificationTest::test_nli_alarm_quarantines_the_quote`, `test_quote_check_binding` | Perform byte/span/normalization computation rather than trust supplied match labels; persist result, notify capture owner, prevent mismatch adjudication bypass; 3. |
| V-7 tier-0 optional | Receipt schema and SQL 03 prevent alarm-based promotion; existing quote/receipt tests | Optional screen adapter, audit records with denominators and sampling probabilities, false passes/alarms and regression disposition; 5. Sampling workflow in 2e2, provider qualification in Phase 3. |
| V-8 independent detailed checks | Receipt schema, SQL 03 receipt CHECKs and promotion reread of units/denominators/negation/qualifications; `VerificationTest`. Part 1's attention tests retain unsuccessful receipts' unperformed/unavailable summary labels unchanged. | Typed detailed verifier production and actual unperformed/unavailable check handling; 2d-4 part 3, with dossier consumption in 6. Code never supplies semantic judgments. |
| V-9 three independences | SQL 03 `claim_source_links`, separate receipt invocation; SQL 05 semantic/source lineage; `tests/test_semantic_assessments.py`, `tests/test_router_workflow.py` | Carry all three independently into exact dossier/export; 6, 8. |
| V-10 protocol admission | SQL 03 `claims_accepted_support_needs_contract_admission`; `router/evidence_writer.py` reads G-1 standing; `tests/test_router_evidence.py::ProductionAndAdoptionTest`, `tests/test_router_amendments.py` | Reuse this gate; dossier assembly must retain stale/adopted history and cannot promote fixtures; 6. |
| G-8 exact completion approval | SQL 01 `queue_completion_needs_current_dossier_approval`; SQL 02 immutable dossiers and exact decision subjects; `router/service.py::_require_subject_hash_truth`, `_apply_decision`; `tests/test_router_ops.py`, `tests/test_store_ddl_contracts.py` | Authoritative full dossier generation/hash, material-change revalidation and fresh sufficiency-review binding; 6–7. Publication approval remains separate. |
| P-1 atomic manifest | SQL 04 immutable `outbox_events` approved source/JSON bindings; Router validates and writes manifest in commit; `tests/test_store_ddl_export.py::ExportOutboxTest`, `tests/test_router_evidence.py` | Exact-revision assembler and /2 enablement on this same path; 8. |
| P-2 ordered delivery | SQL 04 increasing pairs, one revision per generation, named connectors, watermarks; `ExportOutboxTest` | File destination's atomic pair/identity retention, replay, conflict, tombstones; 9. Other connectors Phase 3. |
| P-3 local served-revision read | `freshness-envelope.schema.json`, boundary graph prohibits connector reads; `router/status.py` supplies local status | Compute a truthful envelope with approved served revision and newer unapproved disclosure; 11. |
| P-4 independent facts | Separate dossier/outbox/receipt tables; freshness schema; `ExportOutboxTest` receipt shape/status checks | Combine completion, delivery and currency without changing one from another; 10–11. |
| P-5 approved corrections | SQL 04 exact `publication_approval`, artifact kinds and source/hash binding; `ExportOutboxTest::test_only_approved_work_is_exported` | Assemble corrections/checkpoints through the same manifest path; 8–9. |
| P-6 feed liveness | Freshness schema has per-feed issue reasons | Durable due time, success, cursor/coverage, result class, failure, owner and retirement evidence; 10. Poll/reopen scheduling is 2e2. |
| P-7 unknown effects | SQL 04 receipt status/count/tombstone rules; `router/service.py::ack_delivery`; `ExportOutboxTest::test_receipt_status_rules`, `test_written_count_rules` | Actual file attempt and reconcile by resend after ambiguous application/receipt loss; 9. No destination read by engine readers. |
| F3 real completion evidence | `accounting/stopping.py`, `tests/test_stopping.py`, `test_stopping_bindings.py`, `test_stopping_protocol.py` distinguish unknown/stale/bounds; existing admission and tier fences | Supplied GateResults are not proof. Admit actual successful challenge/competing-explanation packets, coverage provenance and fresh review, then enforce conjunctive gates; 6–7. Producers in 2e2. |
| F7 one export path | EXPORT-API and existing manifest/outbox authority; additive /2 schema, `accounting/reconciliation.py`, `tests/test_reconciliation_operands.py`, `test_reconciliation_bundle.py` | Durable records, licence-bound approved-revision assembly and one JSONL/file connector with complete guarantees; 1, 8–9. Update EXPORT-API's obsolete Phase-3-only text then. |
| F10 feed/read state | Status and freshness contract exist; no durable feed inventory | Persist facts and derive currency, including early failure and successful-empty; 10–11. Scheduling/health workflow remains 2e2. |
| Gate D F1 / DEBT-035 | Rich `accounting/stopping.py` result; /2 currently inherits /1 scalar stopping shape | Add a lossless rich-result representation: context, invocation scope, window pins, G-1 standing, reasons, raw uncertainty, bounds, sentinels and gate evidence; 6. Test satisfied bound + indeterminate windows, conservative unknown and stale. Preserve /1 rules/bytes. |
| Gate D F2 / DEBT-036 | `router/accounting.py::read_inventory` and `router/status.py` read under `_snapshot` (writer transaction); `service.py` has 89 lines of headroom; composition tests | Coherent input capture, computation outside writer lock, commit-time revision/hash revalidation and workload measurement; 6, 8. No cache/second store/query framework. |
| DEBT-032 | Pure `accounting/views.py` BranchLink/WindowPin operands and `tests/test_research_views.py`; durable branch registry/dispositions exist | Admit attributable branch/window links; validate topic/branch/window, derive revisions from invocation/contract, keep absent provenance unknown; 2. |
| DEBT-033 | Pure ObligationAssessment/OpenObligation and confidence checks in `accounting/reconciliation.py`; hash-locked per-plan scheme; `tests/test_confidence_contract.py` | Durable admission/retention with exact approved scheme and record attribution (1); historical approved-revision snapshot and authorized assembly (6, 8). Counts/prose/rule states never replace judgments. |

## Assembly and typed hand-offs

Router owns admission and commits. Private record helpers/collaborators use
narrow core protocols and the existing fenced `commit_outcome` transaction;
slice 1 uses private methods in the existing `Assessments` collaborator and
adds no responsibility or import to `service.py`. Accounting
keeps pure arithmetic. The exporter consumes approved typed artifacts, never
queries a second research store or becomes an accounting writer.

Assembly captures one coherent snapshot of topic state, approved/historical
contracts, immutable records and artifacts, G-1 impacts, claim/receipt/quote
revisions, challenge evidence, invocation/window provenance and registry
history. A short transaction pins a snapshot token and copies the operands;
the transaction ends before calculation, serialization, hashing or spool I/O.
No successive independent inventory reads stand in for a snapshot. If the
existing Store transaction is used to capture it, measure lock duration with
representative topic/global inventories before accepting the path; prefer
topic-filtered joins in the store over reading whole unrelated tables.

Pure assembly outside the lock returns typed dossier/bundle bytes and a token
identifying all material input revisions/hashes. The Router's commit rechecks
the active approved contract, state revision, relevant input identities and
hashes, approval subject, options revision and generation under its writer
fence. Any change refuses/rebuilds; approval never follows a mutable object.
Historical contracts remain available with their original schemes, while
current G-1 standing remains a distinct operand. Missing evidence is unknown.
No /1 scalar conversion may erase uncertainty behind a satisfied bound.
Any exporter import-grant amendment needs the normal boundary review.


## Sequential slice map

Re-ordered 2026-10-24 per the approved Gate S plan (Fable,
`private/reviews/gen2-simplification-plan-fable-20261024.md` §6; operator
approved all of D1–D12 and rulings 1–5). Estimates are hand-written lines
including tests, without mutants, controls, raw twins or ledger entries (the
checks batches S1–S3 retire those). Each brief refines its estimate and splits
again before exceeding about 500 lines. Documentation is additional.

| Slice | Status | Deliverable and approximate lines |
|---|---|---|
| 1 (2d-1) | Done | Durable obligation assessment/open-record admission. |
| 2 | Done | Durable branch/window association admission and provenance-derived window pins (DEBT-032 closed). |
| 3 | Done | Byte/span quote verification against the exact source artifact; quarantine and capture-owner notification (2d-3, 3b, 3b2, 3b3). |
| 4 | Done | Verifier typed re-access/extraction, tier/route/table checks, detailed-check receipts and disagreement holds (2d-4, 4b*, 4c; COMPLETE 2026-10-22). |
| 5 | Done | Dated `tier-0 disabled` capability fact only (2d-5; merged `72c4ac1`). |
| 6a parts 1–3 | Done | Checked WAL-read capture (part 1, `73a676f`, PR #8); detached conversion and dossier-input route (part 2, PR #11); Store-level generation counter (part 3, `dbbdced`, PR #14). |
| 6a part 4 | Next | Freshness binding: token bound to the capture, writer fence, bounded recapture. ≈ 250 (was 440). Scope under "Current contract". |
| 6b1 | After 6a part 4 | **Done** (PR #93): persist the rich dossier: one closed `dossier/2` document in the `dossiers` row through the internal freshness-fenced path (`Router.record_dossier` → `_commit_dossier_inputs`), not `commit_outcome`; DEBT-035 persistence leg. ≈ 350 (was 480). The `export-bundle/2` rich member moves to task 2g (DEBT-040). |
| 6b2 (6b3 merged) | After 6b1 | Completion gates: challenge/competing-explanation records and D3 adjudication admitted through `commit_outcome`; one Python gate evaluator over the detached capture. ≈ 450 (was 470 + 460). |
| 7 | After 6b2 | Completion approval binding: dossier hash recomputed against the decision subject; fresh-review record prerequisite; material change refuses. ≈ 200 (was 400). |
| 8 | Task 2g | Approved-revision /2 bundle assembly: DEBT-040. After 2f. |
| 9 | Task 2g | One JSONL/file connector with complete delivery guarantees: DEBT-041. After 2f. |
| 10 | Task 2g | Durable feed facts: DEBT-042. After 2f. |
| 11 | Task 2g | Freshness envelope and independent currency computation: DEBT-043. After 2f. |
| 12 | Removed | Dropped (ruling 4); it has no debt entry and needs none. |

Gate S batches interleave (plan §0): after PR #14, R1, then S1–S3 (checks
cut-back), 6a part 4, S4–S5, R2, S6 (if confirmed), then 6b1, 6b2, slice 7,
then 2e1, 2e2-minimum and 2f. Task 2g (phase 2, pending) follows 2f and owns
DEBT-040–043; DEBT-033/035 export legs are re-owned to it.

2e2 supplies attributable scientific judgments, real challenge/review execution,
polling/reopening and bounded audit scheduling. Phase 3 owns provider
qualification, additional connectors and automation; Phase 4 owns real-store
migration/canary. This dispatch exercises only new/in-memory disposable stores.

## Operator decisions

Every ratified ruling for task 2d, dated. Sources are the dossier history
(`private/evidence/dossier-history/DOSSIER-2d-history-20261024.md`, section
named) and the reviews in `private/reviews/`. No operator decision is open.

**Foundations**
- **Vocabulary and per-plan confidence authority** (task 2c-4, 2026-10-09): no built-in scale; caller evidence and judgment are retained without establishing completion.
- **Tier-0 off** (2026-10-10, `tasks/2d.md` ruling 1, DEBT-037): tier-0 stays disabled until a qualified checker and audit policy exist. Slice 5 records only the dated `tier-0 disabled` capability fact; checker selection, screening, sampling and enablement stay DEBT-037 / Phase 3.
- **Layered quote matching** (2026-10-10, `tasks/2d.md` ruling 2): (1) an exact byte match passes; (2) a named, versioned normalization followed by an exact match also passes, keeping the original and normalized text and the normalization's name and version (built as `quote-nfc-safe/2`: NFC plus whitespace, curly-quote, dash and soft-hyphen folds, no compatibility folds); (3) a non-exact match at ≥ 98% similarity after normalization is a "near match", held for review and never auto-passing; (4) any difference in a number, negation word or unit always fails. The similarity measure must be a named, established one.
- **Connector destination/options and feed cadence/ownership** are operator configuration under the approved contract, not engine defaults.

**Slice 4 (verification admission)**
- **Independent extraction** (2026-10-12, `history: tasks/2d-4b3e.md`, moved to the dossier-history evidence directory on 2026-10-27): only an independent extraction validates an extraction for load-bearing support (a separate validator invocation re-extracts from the same admitted acquisition bytes with a different tool or method, and the outputs are compared); same-extractor replay is an integrity result only. Closed policy `extraction-validation/1` with exactly two methods, `independent_extraction` and `same_extractor_replay`.
- **Extractor identity through a tool registry** (2026-10-14, settles Astra N1): an operator-maintained, versioned registry of approved extractor tools with families; extraction records must name a registered tool; independent validation needs a different family; registry changes are versioned, audited and never caller-supplied.
- **Latest registry revision governs new validations** (2026-10-15): new `/2` validations compare under the revision current at admission; reclassification takes effect immediately; retained validations keep their recorded interpretation.
- **Store-wide JSON member domain** (2026-10-13): logical member names must be NUL-free; string values may contain NUL; incompatible attempted requests still count, retaining exact original bytes and hash; no rewriting of names (history: "2d-4b3e1-repair-1 continuation").
- **Attributed assessment evidence** (2026-10-17): one closed `attributed-assessment/1` report as the immutable record's assessment JSON; performed outcomes need a topic-authorized evidence artifact equal to it (history: "2d-4c part 1").
- **Span-offset cap** (2026-10-18): receipt and assessment start/end values are at most 9,007,199,254,740,991; no rounding; no live migration.
- **Refuse until reconciled** (2026-10-20): retained accepted claims without qualifying detailed records block active use with a reconciliation diagnostic; history and readback are preserved; no installation DML, no silent grandfathering or demotion; the reconciliation procedure's scope returns to Trevor before it is built.
- **Guarded start and read-only history viewer** (2026-10-21): store-wide check at both Router construction paths and station startup (`reconciliation_required` diagnostic); a separate closed read-only history reader. Reaffirmed 2026-10-24 for part 3.
- **Ban native write/replace APIs, narrow the claim** (2026-10-22): `test_retained_support.py` guarantees observation of application-row changes through SQL statements only; native SQLite write-then-restore APIs are excluded because production never calls them.

**Slice 6 (coherent snapshot and rich dossier), 2026-10-23**
- **D1 = A** (6a workload and budgets): reference workload of one topic with 10,000 observations/retrievals/work links, 1,000 invocations, claim revisions and receipts, and 100,000 unrelated records per shared inventory table; 1 KiB typical JSON, 32 MiB selected JSON plus up to 32 MiB retained byte operands; cold plus 20 warm samples; **p95 writer-lock occupation ≤ 250 ms for capture and for revalidation, each**. The memory budget was first 128 MiB and is **restated 2026-10-23 as peak detached-input memory ≤ 3× the selected data: ≤ 192 MiB at the 32 MiB JSON plus 32 MiB BLOB workload**. A new bound failure stops for redesign; no caching, no tuning, no relaxing.
- **D2 = A** (6b1 shape): a new closed, versioned rich dossier artifact plus an explicit rich member in `export-bundle/2`; `/1` unchanged; retain every raw indeterminate window, context and provenance; refuse any projection that cannot be truthful. Switching to a new bundle version needs a new ruling. (The export member now belongs to DEBT-040, plan D8.)
- **D3 = A** (6b3, now merged into 6b2): unresolved `partially_supports` / `does_not_support` receipts leave the completion verification gate unknown until a durable attributed adjudication names each receipt, claim revision and resolution evidence; new support or generic hold clearance cannot manufacture it; promotion behaviour unchanged; 2e2 produces the judgments.
- **Option D** (redesign after the D1 stop, Astra-reviewed): capture inputs and one durable store-wide generation in one checked WAL read snapshot, compared under the Router's `BEGIN IMMEDIATE` before effects; contract amendments approved (checked read snapshot replaces `BEGIN IMMEDIATE` capture and full raw-preimage revalidation; unrelated-topic writes and restores may cause refusal; rolled-back and zero-row DML need not invalidate). Upgrade to topic-scoped or dependency-aware designs only on measured evidence before multi-topic production.
- **Two bounded recaptures**: an initial attempt plus at most two automatic recaptures, only after an effect-free typed generation-mismatch refusal, within one finite caller deadline; never retry authority, schema, integrity or ambiguous-effect failures; exhaustion is visible typed contention, not scientific uncertainty or success; no eventual-success guarantee is claimed.
- **R3 approved**: keep p95 ≤ 250 ms each for capture and revalidation (memory per the D1 restatement above); report read elapsed time, lock wait, fenced interval, maintenance cost, concurrent-writer progress and WAL effects separately; any new failed budget stops for redesign.
- **Part-2 memory ruling** (2026-10-23): memory bound restated as above; complete raw-snapshot retention during conversion is permitted; the A+B memory redesign is not adopted (documented later option).

**Slice 6 part 3 (2026-10-24)**
- **No writes on open** (2026-10-24): opening, startup admission, history viewing and capture write nothing; an already-WAL store opens beside an active writer; absent metadata reads as `(epoch=None, generation=0)`. Restore detection goes through the explicit offline `Store.maintain(path, operation)`, which rotates a random 128-bit maintenance epoch; restoring or replacing files outside it is unsupported.
- **A — the Router owns semantic rules** (Gate S ruling, 2026-10-24): the DDL keeps integrity (keys, FKs, immutability, role separation, existence bindings, state transitions); value-domain and support rules move to the Router (batches S4, S5, S6).
- **B — Store-level counter** (2026-10-24, after Gate S): each committed Store transaction that writes a covered table bumps the generation once; the 111 event triggers are retired; SQL 43 keeps only the table and the three singleton/step/exhaustion guards; the literal-DML gate allows only canonical primitive templates and `_bump_once`/`maintain`.
- **Gate S rulings 1–5** (2026-10-24): 1 Router owns semantic rules; 2 the counter redo (PR #14); 3 cut back the checking machinery (tiered checks, automatic mutation, retire the metrics ratchet); 4 Phase 2 reorder around 2f (slices 8–11 to task 2g, slice 12 dropped); 5 collapse the records, no rule changes.
- **D1–D12 plan decisions** (approved 2026-10-24, all): D1 mechanical-batch counting by file for whole-file deletions; D2 retire the exact replay oracle and equivalence tools in S1; D3 SQL 38/39 go in S5; D4 JSON member-domain DDL guards go in S6 (`Store._prepare` is the one enforcement point); D5 radon cyclomatic ceilings blocking; D6 checks first (S1→S2→S3 before 6a part 4); D7 slices 8–11 owned by new task `2g` after 2f; D8 `export-bundle/2` rich member deferred to slice 8 / DEBT-040; D9 Gate S #1 stands as the 15,000-line growth review; D10 `gen2/importer/dry_run.py` moves under `tools/` until Phase 4; D11 6b2 and 6b3 merge; D12 CI-DESIGN amendment text drafted in R2 for approval.
- **2026-10-25, mutation scope (S2):** the acceptance gate runs Cosmic Ray on changed production lines only. Surviving mutants fail acceptance unless accepted with an inline `# pragma: no mutate` plus a reason (Astra reviews). Full-file campaigns are report-only, at phase gates and Gate S.
- **2026-10-26, build throughput (Trevor approved all three):**
  1. **Parallel test execution.** The acceptance unit run and the stage-2 full-suite mutation runs execute as parallel shards, with merged coverage. The tests and verdict rules don't change.
  2. **Design review before code** for new slices, 6b1 onward: Astra reviews the slice design against the existing code before the coder starts.
  3. **Up to two coders at once** on independent tasks, each in its own worktree with its own PR, verifier and Astra review.
- **2026-10-27, Gate S #2 (Trevor: "I'm fine with all those recommendations"; report `private/reviews/gen2-gate-s2-fable-20261027.md`):**
  - **S2-1:** slice 7 is absorbed. 6b1′ = the `dossier/2` codec, persistence and hash truth. 6b2′ = typed completion records, including the fresh review, plus the gate evaluator with the approval prerequisite, landed as two parts.
  - **S2-2:** retire trigger-order after S6's final baseline run. This amends ruling 3 bullet 1.
  - **S2-3:** limit stage 2 to the child-spawning test modules, but only once at least 10 sharded campaigns show stage 2 never flips a verdict.
  - **S2-4:** 2e1 defers the subscription-window snapshot reader to Phase 3 (DEBT-015).
  - **S2-5:** 2e2-minimum scope per Gate S #2 §6.3. The deferred S5/S6 items go to Phase 3 (DEBT-044–048).
  - **S2-6 (option A):** INVARIANTS §13 changes so the live S1–S3 intake conversation is Phase 3. 2f runs under an operator-authored contract (DEBT-049). The INVARIANTS text changes in R2.
  - **S2-7:** charter rules on harness changes and on measuring cost before review.
  - **Also approved:** S6 widened to the value-domain DDL retained by S5 (SQL 22 `source_extractions_tier`, SQL 35 `detailed_check_records_domain`/`_spans`, their helper views), and deletion of the unused `.github/workflows/gen2-check.yml`.
- **2026-10-29, Trevor's rulings on the open items** (asked in the loop on 2026-10-28):
  1. **Mutation scope for refactors:** recognize moved code. Pure moves leave the blocking changed-line scope and are recorded in the report; the advisory full campaign stays the backstop. Stage 1 runs on parallel workers. This is an exception to S2-7.
  2. **Batch F:** option A. The operator-token boundary is checked on the final serialized response bytes.
  3. **CI-DESIGN:** R2's amendment proposals are approved, with the trigger-order line deleted (S2-2).
  4. **INVARIANTS C-4:** "evidence revision" becomes "the resulting topic state revision", per Astra's 6b1′ design review. No other meaning changes.
  5. **O-10:** approved. New `verification-receipt/1` admissions stop, readback of recorded `/1` receipts stays, and 2f runs on a fresh store.
  6. **Test pruning (PLAN-v2, `private/reviews/test-portfolio/`):**
     - Merges into one keeper test are allowed at every tier when no assertion is lost. Exact duplicates land mechanically; near-duplicate parametrization goes through Gate C.
     - The no-Astra landing covers removals only; edits keep Gate C.
     - Tests with a catch record stay in place, and any change to them comes to Trevor.
     - The production-code rows leave the pruning table (Gate S keeps them).
     - The 13 unlisted T1 protector groups become traceability locators.
     - The tier table is **not yet approved**: Trevor asked how it was tiered and on what research basis.
- **2026-10-29, later rulings (Trevor):**
  - **Batch F F2: option A.** Operator replies stop reflecting caller-supplied text. Refusals use fixed typed descriptions. JSON-RPC ids are admitted only from a closed plain grammar. The final-bytes check stays as a backstop.
  - **The tier table is approved:** `private/reviews/test-portfolio/TIERS-v2.md`, with Astra's two-way review taking precedence (L1 2,831 · L2 3 · L3 40 · L4 9).
    - No nightly-only lane is built.
    - The nightly review's focus moves to duplicates, near-duplicate parametrization, per-KIND repetition, weakened tests, and dead tests and helpers.
    - A one-off consolidation sweep runs under ruling 7.

- **2026-10-30, Trevor: mutation-caused errors count as kills** (chosen over "keep the strict rule" and "exempt case by case").
  - A test error counts as a kill (ERROR_KILL) when all three hold:
    - it qualifies under the clean control;
    - it is not a timeout, loader or infrastructure failure;
    - every error's innermost frame is in **the mutant's own target module**. This is Astra's EK-1 narrowing within the ruling, so an error raised from another production module or from test code stays TEST_ERROR and fails.
  - This supersedes, in part, the #73 rule that errors never count.
  - Implemented in PR #87 (`2c023be`). The limit is documented in CI-DESIGN: this is not a proof of semantic causation.

- **2026-10-31, Trevor's rulings on Gate S #3** (`private/reviews/gen2-gate-s3-fable-20261031.md` §9):
  - **S3-1, approved:** filter mutation-cost traps in the mutation tool: declaration-only lines (signatures, Protocol stubs, TypeVars) and string-literal ordering comparisons. Retire the code conventions written to dodge them.
  - **S3-2, approved:** S2-3, the stage-2 shrink, is withdrawn. Stage 2 did flip verdicts, all on lines S3-1 filters.
  - **S3-3, approved:** a critical-path lane (charter, Build throughput).
  - **S3-4, approved:** the nightly test-portfolio review is paused until after 2f.
  - **S3-5, approved:** `reaccess`, `acquisitions` and `gateway_capture` are frozen, with 2e2-minimum as their consumer or deleter (DEBT-051).
  - **S3-6, open:** whether 2e2-minimum's queue path uses one executor-run pre-contract scoping pass. It is to be asked again with the 2e2-minimum design.

- **2026-10-31, Trevor narrowed S3-1:** drop the string-ordering half and keep only the declaration-only filter (#96). A genuinely equivalent string comparison gets a clearer rewrite (dispatch or membership) or an Astra-approved same-line pragma.
- **2026-10-31, Trevor accepted the 6b2′ re-baseline:** about 1,450 lines planned, about 2,050 adjusted, in three PRs (private/reviews/gen2-gate-s3b-6b2-size-fable-20261031.md).
- **2026-10-31, Trevor's rulings for the 2e1 feasibility checkpoint:**
  - **Runner source:** an agent may download the official codex 0.153.2 release for read-only inspection, with its hash verified, never built or run. Done; kept under `private/inputs/codex-0.153.2/`.
  - **Host setup:** an agent writes the exact configuration for Astra's review first. Trevor then approves the exact host-change and undo list before an agent applies it.
  - **The genuine rejected-credential provider call (DEBT-004):** who, when, on which deployment and within what bounds is decided closer to 2f. The build makes no provider calls.
- **2026-11-01, Trevor's rulings on Gate S #3c** (private/reviews/gen2-gate-s3c-2e1-fable-20261031.md §7; Astra gen2-2e1-checkpoint-astra-20261031.md):
  - **S3c-1 (Astra, technical):** keep codex 0.153.2. Its `exec --json` has no typed auth field, so the typed rejection comes from a relay-bound exchange: the trusted relay retains the upstream 401, bound to the exact request. Astra accepted this in principle, subject to her binding and complete-log contract (R1).
  - **S3c-2, approved:** host provisioning and operational qualification are a separate, separately counted prerequisite: about 450 lines, stop 650, under `deploy/gen2/live/`, on the second coder slot. Approving the work package doesn't qualify its output.
  - **S3c-3, approved:** 2e1 PR 4a (the gateway output cut and the P9 transport) is deferred to the cleanup slot after the 2f start (DEBT-054). H-6 behaviour and capture/persistence ACK safety are kept regardless.
  - **S3c-4, approved:** the 2e1 application slice is re-baselined to about 2,000 lines (band 1,900–2,200). Stops: 2,400 total, 850 production, 1,000 tests; landings ≤600. The crossed v2 stops stay on record.
  - **S3c-5, acknowledged:** 2f moves to late November (about Nov 25–28), or early December if the Docker network premise fails.
  - **S3c-6, approved:** the estimating rules in the charter (Build throughput).
- **2026-11-01, Trevor's later 2e1 rulings:**
  - **Read-only downloads authorized:** the nginx source, image digests by registry lookup only, package files and metadata, and the Moby source (29.9.0) and BusyBox source. Nothing is built, installed or run. Kept under `private/inputs/`.
  - **The relay trust boundary is accepted:** the host administrator is trusted. Management goes only through the recorded steps, any unrecorded intervention invalidates the run, and no independent watcher is built.
  - **The +62 target variance is acknowledged;** the hard stops 2,400 / 850 / 1,000 are unchanged.
  - **The prerequisite stop is amended 650 → 665.**
  - **The READY host rows in `private/reviews/gen2-2e1-host-approval-package-20261101.md` are approved** as written, tied to the reviewed hashes. Applying them is a later, separate task, after the remaining design gates close. Built-image digests, activation and qualification aren't covered.

- **2026-11-02, Trevor's rulings on Gate S #4** (`private/reviews/gen2-gate-s4-fable-20261102.md` §10; all accepted):
  - **S4-1:** trim Decision T's management protocol: relay evidence is the access log, the fixture record and the runner failure.
  - **S4-2:** withdraw the missing-evidence acquisition; pin images by digest after one authorized pull and one build.
  - **S4-3:** apply the approved host rows minus storage, quota and guard; `--ulimit`, tmpfs sizes and a free-space floor bound the runner; kernel quotas go to a DEBT entry.
  - **S4-4:** design round cap of two; ACCEPTED WITH CHANGES counts; design rounds count toward the task total.
  - **S4-5:** Tiers + Trevor's approval on High.
  - **S4-6:** Gate S trigger 3 at a cumulative 1.3× instead of 2×.
  - **S4-7:** Gate B retired to Gate D and phase gates; the coder pre-check and the S2-7 harness-change bullet are deleted.
  - **S4-8:** mutation becomes a weekly report-only campaign; the per-PR gate is `gen2-check`.
  - **S4-9:** re-baselined 2e1: application about 1,950/2,150, prerequisite about 370/450; stops unchanged.
  - **S4-10:** ETA acknowledged: 2f Nov 28 (P50) / Dec 5 (P80); Phase 2 mid-December.
  - **S4-11:** the VM host is the fallback if the rootless Docker witnesses fail, replacing the nft fallback.

## Current contract

**No slice is in flight.** 6a parts 1–3 are done (part 3 merged as `dbbdced`,
PR #14). The coder's next job is S1 (tiered checks), then S2, S3; **6a part 4
is the next engine slice** and its contract is not yet written. Its scope, from
the approved plan §6.1 (≈ 250 lines; was 440), to be turned into an acceptance
contract before dispatch:

- **2026-10-27, Gate S full pass (Trevor: "Approve all"; reconcile report private/reviews/gen2-gate-s-full-reconcile-fable-20261027.md §5):**
  - **O-1:** the supervisor keeps one concurrency backstop: the per-job lock plus `_save`'s stale-journal check. The caller-copy re-reads in `_call`/`_incident` and their stale-copy matrix go.
  - **O-2:** operator tokens are constrained to `[A-Za-z0-9_-]{16,}`, and the decoding redaction is deleted. The DEPLOYMENT-CONTRACT §1.1 line changes in that batch.
  - **O-3:** retained-byte hash truth is the Router's only. `Store.insert`'s `request_bytes` digest recomputation goes.
  - **O-4:** restore stays a documented Python-level operator procedure in Phase 2 (two doc lines); an entry point comes with 2g.
  - **O-5:** BOUNDARIES "Router composition" is amended: one `gen2/router/protocols.py` replaces the 23 protocol copies, and the 33 private forwarders are dropped. This lands as one contract-first interface PR before 6b2′.
  - **O-6:** keep `schemas.py`; no `jsonschema` adoption.
  - **O-7:** freeze reservations and auto-promotion draws, which have Phase 3 consumers only (DEBT-050). Delete them only if a Phase 2 slice must touch them.
  - **O-8:** delete `test_schema_counterfactuals.py`; its two probes become example fixtures.
  - **O-9:** after S6's rule table, the six RAW twins are replaced by direct per-table integrity tests, and the raw-DDL classes leave the Router test modules.
  - **O-10:** drop `verification-receipt/1` from the schema enum and its isolation matrices **if** no store 2f opens holds a `/1` row, with Astra confirming the history rule first. One literal witness that a `/1`-shaped row is not support stays.
  - **O-11:** drop the four `RealRegisterTest` content pins and keep the armed phase-close test.
- **Trace:** R1:D as amended by ruling B (counter, once per committed covered write); the two-recapture ruling (2026-10-23); DEBT-036 (revalidate at commit); the 2026-10-24 no-writes-on-open ruling.
- **Contract:** capture reads `(epoch, generation, schema_cookie)` and the admitted device/inode inside the same read snapshot (part 1's `mode=ro` reader); the writer fence re-reads them under `BEGIN IMMEDIATE` before the operation's first `insert/update` (so before its own bump) with a fresh `stat`; any difference refuses with a typed stale-input refusal before effects; up to two automatic recaptures, then the operation's normal failure; the recapture count is written as an ordinary audit fact through the existing audit path.
- **Tests:** two-connection WAL fixtures with deterministic barriers (per-transaction counts), restore-via-`maintain` detected by epoch, cookie change detected, inode change detected, rollback leaves the counter unchanged, unrelated-topic write refuses (conservative, as ruled).
- **Cut (no trace):** a metrics table or telemetry beyond the audit fact; deadline/cancellation machinery beyond the supervisor's existing job deadline; full raw-preimage revalidation and the D1 lock budgets as new assertions (parts 1–2 evidence stands).
- **Size:** ≈ 60–80 production, ≈ 170 tests.

History: per-slice preflights, re-estimates, repair narratives and the earlier
slice map and decisions text are in
`~/work/research-loops-public/private/evidence/dossier-history/DOSSIER-2d-history-20261024.md`
(outside the repository).
