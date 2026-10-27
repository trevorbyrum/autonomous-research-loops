# Batch D2b completion

TO2 shares durable setup/reopen (all four suites, including amendments), lock-wait logic and `Refusing(once=True)`; the file-spool world keeps its spool/clock/IDs. The existing receipt-only `OwnCases` mixin moves to `store_fixtures.py` to provide headroom; no new TO1 families or re-export shims.
TO4 retains the authoritative refusal-spy witnesses below and adds both span shapes plus the existing reproduced-metadata/abstract operands before removing three duplicate matrices. TO5 removes four approved redundant tests and four no-op poll-host iterations. O-11 removes four pins and their unused parser; the armed phase-close test is unchanged.
TO6's 12-minute vector comparison removes only four exact duplicate refusal literals; extreme/long spellings, signed zero and the legacy-hash oracle remain. Detailed reasons and vector mappings are in `to6-vector-review.json`.

Base: `e1669ede5d668cfdd930e80187bb3c4643292bc6`. Evidence: `~/work/research-loops-public/private/evidence/batch-d2/d2b/`.

- AST preservation: passed; 3,607 retained function mappings and 6,714 assertion expressions. Approved removals and TO2 contract details are explicit in `ast-preservation.json` / `differential-helpers.json`.
- Refusal-double differential: 3,410 profiles passed against both old implementations.
- Collected IDs: 2,953 → 2,942, delta −11: 3 TO4 duplicates, 4 TO5 redundant tests, 4 O-11 pins; no additions. Complete ID/reason map: `collected-delta.json`.
- Cross-test imports: 59 → 59 statements; strict `from gen2.tests.test_X`: 29 → 29. Every remaining statement is accepted residue with its reason below.
- Focused verification: 421 tests passed; 22 canonical/decimal tests passed after TO6's final literal edit.
- Full disposable-copy `gen2-accept` (8 shards): **passed**, 2,942 tests; all gates green.
- Mutation scope: **empty**, no applicable production files or mutants.
- Tested code: `4719fda312d1388b73015f41482e372e652b82eb`; final evidence amendment changes only this file.
- Size: 802 touched / -82 net, including this file; Router fixtures 1,468 lines, workflow 1,360.

PR #63 exclusions are lifted. The active exclusions are the explicit D2a-1 test-file list below, all production/protected records/other worktrees, and the current open-PR diffs. PR #54's diff was checked against `origin/gen2`; all its files remain untouched. Accounting/research-view imports retain their earlier standing authorization.
TO5 kept witnesses: boundary reachability in `BoundaryCheckerTest.test_importer_cannot_reach_a_store_under_the_real_graph`; all redirect statuses/origins/polls in `DirectHttpOnly.test_a_redirect_is_never_followed_whatever_the_status_and_wherever_it_points`; ordinary endpoint matrices plus mapped/unmapped rendering tests in `TheEndpointForms`; supervisor runtime skip owners remain untouched. Only the source-text skip pin is removed.

Publication scope recheck: #65, #54; zero code/test overlaps. Newly reserved test files: `gen2/tests/test_traceability.py`. PR #65 also updates the required `COMPLETION.md` acceptance record; that shared metadata file is authorized by the completion contract. All other PR paths remain excluded; full inventory in `scope.json`.

# Batch D2b witness table (written before TO4 edits)

Base: `e1669ede5d668cfdd930e80187bb3c4643292bc6`.
Authoritative S4 Router-path witnesses stay in `test_router_insertion_rules.py`.
Its refusal spy proves the Router predicate raised `Refusal`, and each refused
operand has a committed control. Edge-case/readback/rollback witnesses in the
three content/table modules stay where they are.

| Rule | Refuse and commit witness (`RouterInsertionRulesTest`) | Literal coverage |
| --- | --- | --- |
| Canonical acquisition binding | `test_canonical_acquisition_binding` | producer, route, call reference, retrieval time; unmodified receipt commits |
| Canonical recorded-content ceiling | `test_canonical_content_ceiling` | bibliographic→abstract, abstract→full text, full text→reproduced; four verdicts; admitted tier commits |
| Extraction recorded-content ceiling | `test_extraction_content_ceiling` | same three ceilings and four verdicts for verifier/validated extraction; admitted tier commits |
| Table availability | `test_table_availability` | bibliographic/abstract, all three methods, three non-exempt verdicts; page-only commits; retain table-only and mixed span operands |
| Exemption and availability controls | `test_table_controls_and_hold_exemption` | recorded full text commits with table citations; cannot-assess commits and creates a hold |
| Acquisition-local content | `test_acquisition_time_does_not_pool_content` | earlier/later distracting full text cannot inflate the bound abstract; ceiling/table refusals plus page control |

| TO4 duplicate ID to remove | Kept witness |
| --- | --- |
| `test_canonical_content_tiers.ContentRouterTest.test_inflation_all_verdicts` | `test_router_insertion_rules.RouterInsertionRulesTest.test_canonical_content_ceiling` |
| `test_extraction_content_tiers.ExtractionContentRouterTest.test_inflation` | `test_router_insertion_rules.RouterInsertionRulesTest.test_extraction_content_ceiling` |
| `test_table_availability.TableRouterTest.test_insufficient_and_mixed` | `test_router_insertion_rules.RouterInsertionRulesTest.test_table_availability`, retaining both span shapes |

---

## Accepted TO1 residue

Each row is one AST import statement, including local imports and module aliases. These are accepted under Trevor's instruction to stop further TO1 parts, except the explicit ownership exclusions noted in the reasons. The full import text is in `accepted-residue.json`.

| Consumer | Imported test module/symbol | Reason |
| --- | --- | --- |
| `coverage_reference.py:12` | `test_coverage_dependencies.history,page` | Coverage history/page oracle builders; accepted remaining accounting family. |
| `coverage_reference.py:13` | `test_stopping.CTX,DATE` | Stopping inventory/context literals; accepted remaining family. |
| `test_acceptance_coverage.py:13` | `test_acceptance` | S2d acceptance files are explicitly excluded. |
| `test_bound_extraction_support.py:12` | `test_validated_extraction_receipts.ValidatedCases` | Validated-receipt base; further TO1 family moves are stopped. |
| `test_branch_windows.py:15` | `test_registry_dispositions.example_disposition` | Disposition document builder; marginal TO1 move intentionally stopped. |
| `test_canonical_decimal.py:8` | `test_canonical` | Published vectors/hash oracle retained after TO6; compatibility checks are distinct. |
| `test_capture_reader.py:11` | `test_topic_capture.group` | Capture table selector group; marginal TO1 move intentionally stopped. |
| `test_coverage.py:8` | `test_stopping.CTX,DATE,N,S,U,inventory` | Stopping inventory/context literals; accepted remaining family. |
| `test_coverage.py:218` | `test_accounting.WindowTest` | Accounting/window world; another TO1 family extraction is intentionally stopped. |
| `test_coverage_dependencies.py:7` | `test_stopping.CTX,DATE,N,S,U` | Stopping inventory/context literals; accepted remaining family. |
| `test_coverage_dependencies.py:109` | `test_accounting.WindowTest` | Accounting/window world; another TO1 family extraction is intentionally stopped. |
| `test_coverage_dependencies.py:137` | `test_accounting.WindowTest` | Accounting/window world; another TO1 family extraction is intentionally stopped. |
| `test_dossier_inputs.py:9` | `test_accounting` | Accounting/window world; another TO1 family extraction is intentionally stopped. |
| `test_dossier_inputs.py:12` | `test_branch_windows.World` | Branch World would exceed the remaining Router-fixture headroom; accepted TO1 residue. |
| `test_extraction_attention.py:6` | `test_bound_extraction_support.PromotionCases` | PromotionCases extraction fixture family; further TO1 moves are stopped. |
| `test_extraction_attention.py:8` | `test_validated_extraction_receipts.ValidatedCases` | Validated-receipt base; further TO1 family moves are stopped. |
| `test_failed_attempt_retention.py:14` | `test_attempted_request_bytes` | Batch A files are explicitly excluded. |
| `test_generation_lifecycle.py:8` | `test_capture_reader` | Capture-reader generation harness; further TO1 family moves are stopped. |
| `test_mandatory_detailed_receipts.py:5` | `test_detailed_check_receipts` | ReferenceCases/literal detailed receipts; accepted remaining family. |
| `test_obligation_admission.py:11` | `test_confidence_contract.declare,SCHEME` | Confidence declare/SCHEME operands; marginal TO1 move intentionally stopped. |
| `test_opaque_attempts.py:12` | `test_attempted_request_bytes` | Batch A files are explicitly excluded. |
| `test_operator_mcp.py:218` | `test_operator_auth.raw_exchange` | raw_exchange deferred: owned by Batch F's file (open PR #54). |
| `test_quote_attention.py:11` | `test_store_governed_quotes` | Raw governed-quote matrix; module alias preserves collected test ownership. |
| `test_receipt_summary_domain.py:8` | `test_detailed_check_receipts.ReferenceCases` | ReferenceCases/literal detailed receipts; accepted remaining family. |
| `test_reconciliation_bundle.py:13` | `test_reconciliation_operands.SCHEME` | Shared SCHEME literal; marginal TO1 move intentionally stopped. |
| `test_remaining_router_detailed_fixtures.py:11` | `test_router_amendments` | Literal amendment regression harness; retained under its test owner. |
| `test_remaining_router_detailed_fixtures.py:12` | `test_span_cap` | Literal span-cap regression harness; retained under its test owner. |
| `test_research_views.py:8` | `test_accrual` | Accrual/research-view world; another TO1 family extraction is intentionally stopped. |
| `test_retained_support.py:15` | `test_router_detailed_support` | Detailed-support seed/selectors; accepted remaining receipt family. |
| `test_retained_support.py:18` | `test_receipt_summary_domain.METHODS` | SummaryCases/METHODS receipt basis; accepted remaining family. |
| `test_router_amendments_wiring.py:24` | `test_router_lifecycle_wiring.Spy` | Spy remains with its call-forwarding tests; TO2 consolidates only Refusing. |
| `test_router_commit.py:33` | `test_router_schemas.verdicts` | Schema-verdict driver; accepted test-tool residue. |
| `test_router_commit_wiring.py:15` | `test_router_evidence_wiring` | Rollback harness stays with its evidence tests; its store double is now shared. |
| `test_router_detailed_support.py:8` | `test_receipt_summary_domain.SummaryCases` | SummaryCases/METHODS receipt basis; accepted remaining family. |
| `test_router_detailed_support.py:9` | `test_detailed_check_receipts` | ReferenceCases/literal detailed receipts; accepted remaining family. |
| `test_router_detailed_support.py:13` | `test_receipt_summary_domain.METHODS` | SummaryCases/METHODS receipt basis; accepted remaining family. |
| `test_router_evidence.py:28` | `test_router_schemas.verdicts` | Schema-verdict driver; accepted test-tool residue. |
| `test_router_evidence_wiring.py:18` | `test_router_evidence` | Evidence/ScreeningBase/qualification fixtures; further TO1 family moves are stopped. |
| `test_router_registries.py:31` | `test_router_evidence.T,ScreeningBase,qual_ref` | Evidence/ScreeningBase/qualification fixtures; further TO1 family moves are stopped. |
| `test_router_scheduling_wiring.py:19` | `test_router_scheduling` | Scheduling ContractWorld test harness; accepted remaining family. |
| `test_router_scheduling_wiring.py:22` | `test_router_lifecycle_wiring.Spy` | Spy remains with its call-forwarding tests; TO2 consolidates only Refusing. |
| `test_router_support_basis.py:8` | `test_router_detailed_support` | Detailed-support seed/selectors; accepted remaining receipt family. |
| `test_router_support_basis.py:13` | `test_receipt_summary_domain.METHODS` | SummaryCases/METHODS receipt basis; accepted remaining family. |
| `test_semantic_assessments.py:207` | `test_registry_dispositions.example_disposition` | Disposition document builder; marginal TO1 move intentionally stopped. |
| `test_span_cap.py:11` | `test_router_workflow` | ClaimSourceLinkTest scenario harness; retains its literal test owner. |
| `test_stopping_bindings.py:8` | `test_stopping` | Stopping inventory/context literals; accepted remaining family. |
| `test_stopping_protocol.py:6` | `test_accounting, test_stopping` | Accounting/window world; another TO1 family extraction is intentionally stopped. Stopping inventory/context literals; accepted remaining family. |
| `test_stopping_protocol.py:7` | `test_stopping_bindings` | Stopping binding harness; accepted remaining family. |
| `test_store_acquisition_relationships.py:9` | `test_store_acquisitions` | Acquisition DDL rejection matrix; retains its literal test owner. |
| `test_store_detailed_checks.py:9` | `test_detailed_checks.RecordMatrix` | RecordMatrix DDL rejection matrix; retains its literal test owner. |
| `test_store_extraction_records.py:6` | `test_extraction_records` | Extraction record rejection matrix; retains its literal test owner. |
| `test_store_extraction_validations_v2.py:7` | `test_extraction_validations_v2` | Validation-v2 operands/case family; further TO1 moves are stopped. |
| `test_store_extraction_validations_v2.py:8` | `test_store_extraction_records` | Raw extraction-record matrix; module alias preserves collected test ownership. |
| `test_store_extractor_registry.py:6` | `test_extractor_registry.approval` | Extractor approval builder; marginal TO1 move intentionally stopped. |
| `test_store_extractor_registry.py:7` | `test_store_extraction_records` | Raw extraction-record matrix; module alias preserves collected test ownership. |
| `test_store_validation_current_registry.py:2` | `test_validation_current_registry` | Current-registry validation case family; accepted remaining family. |
| `test_store_validation_current_registry.py:3` | `test_store_extraction_validations_v2` | Raw validation matrix is reused by module alias to preserve collection ownership. |
| `test_topic_capture.py:15` | `test_semantic_assessments` | Instantiated SemanticTest needs a helper-only base extraction; further TO1 is stopped. |
| `test_validation_current_registry.py:5` | `test_extraction_validations_v2` | Validation-v2 operands/case family; further TO1 moves are stopped. |

---

# Batch D2a-3 completion

This TO1 slice moves `QuotesCase`, `CanonicalQuotesCase`, `CaptureCase`,
verification `AttentionCase`, and their literals into `router_fixtures.py`,
with every moved-name consumer updated. The intermediate
`canonical_quotes_fixtures.py` is removed after its class and consumers
move. Its `STAMP` reuses the identical existing fixture literal; local
receipt-fixture imports avoid a module-initialization cycle. No re-export
shims, production changes, test deletions or assertion changes.

Remaining TO1: branch/window, `Spy`/`Refusing`, and remaining
Router/gateway/other helpers. D2b has not begun. `raw_exchange`:
**deferred: owned by Batch F's file**; its definition/importers are unchanged.
`router_fixtures.py` is 1,498 lines, leaving two lines of headroom.
Further TO1 slices need a permitted fixture home within the file-size cap.

Base: `1dc3cbddda348dff7e9915afbed920f9e3238e07` (#61 merged).
Evidence: `~/work/research-loops-public/private/evidence/batch-d2/d2a3/`.

- AST: 6 mapped nodes (4 classes, `HOLD`, identical existing `STAMP`),
  3,619 functions and 6,730 assertion expressions preserved. Zero failures.
- Collected IDs: 2,953 → 2,953; delta 0. No IDs added or removed and no
  duplicate collections; original test classes retain their literal tests.
- Cross-test import statements: 65 → 59; strict
  `from gen2.tests.test_X` statements: 35 → 29. Complete inventories kept.
- Consumer closure: zero moved-name imports/references through test modules.
- Focused verification: 171 tests passed across all nine consumer modules.
- Full disposable-copy sharded `gen2-accept`: **passed**, 2,953 tests / 8 shards.
- Mutation scope: **empty**, no applicable production files or mutants.
- Tested code: `fcbcb02a6f270b86e48b469667181ab816e7cad5`; the final evidence amendment changes only this file.
- Size: 548 touched / +78 net, including this completion update.

Open PR #54 (Batch F) and #62 (records) were checked with
`gh pr list --state open --base gen2` and each branch's
`git diff --name-only origin/gen2...origin/<branch>`. All their files and
the prior exclusion list below remain untouched. Consumer-only files
receive imports or fixture-reference changes; every assertion is preserved.
The additional 6b1′ exclusions, including its schema examples, are:

```text
gen2/tests/store_fixtures.py
gen2/tests/test_router_ops.py
gen2/tests/test_router_amendments.py
gen2/tests/test_sqlite_gate.py
gen2/store/schema/02-invocations-and-records.sql
gen2/store/api.py
gen2/router/service.py
gen2/schema/commit-outcome.schema.json
gen2/schema/examples/commit-outcome/invalid-caller-supplied-role.json
gen2/schema/examples/commit-outcome/invalid-contract-and-brief-mixed.json
gen2/schema/examples/commit-outcome/invalid-interim-receipt-with-ordinal.json
gen2/schema/examples/commit-outcome/invalid-invocation-id-in-operation-slot.json
gen2/schema/examples/commit-outcome/invalid-lease-generation-beyond-bound-exponent.json
gen2/schema/examples/commit-outcome/invalid-missing-expected-state-revision.json
gen2/schema/examples/commit-outcome/invalid-missing-lease-generation.json
gen2/schema/examples/commit-outcome/invalid-oversized-payload.json
gen2/schema/examples/commit-outcome/invalid-pre-contract-without-confirmation.json
gen2/schema/examples/commit-outcome/invalid-receipt-unfrozen-canonicalization.json
gen2/schema/examples/commit-outcome/invalid-receipt-unfrozen-fingerprint-contract.json
gen2/schema/examples/commit-outcome/invalid-receipt-without-hash-contract.json
gen2/schema/examples/commit-outcome/invalid-receipt-without-validation-binding.json
gen2/schema/examples/commit-outcome/invalid-rejection-carrying-receipt.json
gen2/schema/examples/commit-outcome/invalid-rejection-negative-state-revision.json
gen2/schema/examples/commit-outcome/invalid-rejection-unlisted-reason.json
gen2/schema/examples/commit-outcome/invalid-rejection-without-state-revision.json
gen2/schema/examples/commit-outcome/invalid-state-revision-beyond-bound-decimal.json
gen2/schema/examples/commit-outcome/invalid-unversioned-admission-context.json
gen2/schema/examples/commit-outcome/valid-final-outcome-envelope.json
gen2/schema/examples/commit-outcome/valid-pre-contract-envelope.json
gen2/schema/examples/commit-outcome/valid-receipt-final.json
gen2/schema/examples/commit-outcome/valid-response-rejected-unknown-topic.json
gen2/schema/examples/commit-outcome/valid-response-rejected.json
gen2/schema/examples/commit-outcome/valid-response-replayed.json
```

The existing exclusions below still apply, including S2d, Batch A, Batch B,
Batch F, supervisor tests, `ddl_fixtures.py`, and protected records.
The pagination docstring rider is already merged in D2a-1 and stays intact.

---

# Batch D2a-2 completion

This capped TO1 slice moves `AcquisitionCase`, `ReceiptCase`,
`AttributedReceiptCase`, `RecordCase`, `CheckCase`, `OwnCases`, and their
shared acquisition, receipt, content and span builders into
`gen2/tests/router_fixtures.py`, with the complete moved-name consumer
closure. `content_document` and `EXTRACTION_METHODS` distinguish formerly
module-local names. No re-export shims or production changes.

Still pending: capture/quote, branch/attention, accounting/window,
remaining Router/gateway/other helpers, and `Spy`/`Refusing`. D2b has not
begun; subsequent slices must branch fresh after this PR merges.
`raw_exchange`: **deferred: owned by Batch F's file**. PR #54 was open at scope check;
its two test files and all exclusions listed in the prior record below
remain untouched. Its diff was checked against `origin/gen2`.

Base: `d7ccd2d028335182a70dce74f6ef1a8d599b19fc` (D2a-1 #60 merged).
Evidence: `~/work/research-loops-public/private/evidence/batch-d2/d2a2/`.

- AST preservation: 30 moved nodes, 3,619 retained functions and 6,730
  assertion expressions preserved. No test method or assertion deleted.
  Only imports and exact fixture references are normalized in the audit.
- Collected IDs: 2,953 → 2,953; delta 0, no additions, removals or duplicate
  collections. The moved `OwnCases` mixin keeps its existing test owners.
- Cross-test import statements: 118 → 65; strict
  `from gen2.tests.test_X` statements: 81 → 35. Remaining imports belong
  to pending families and explicit exclusions.
- Focused verification: 70 tests passed, including the patched span-fixture
  consumer and the receipt/acquisition/record suites.
- Full disposable-copy sharded `gen2-accept`: **passed**, 2,953 tests / 8 shards; `accept/accept.log`.
- Mutation scope: **empty**, no applicable production files or mutants.
- Tested code: `815d4622de6d63dde85d9a112003119acaa39ea0`; final evidence amendment changes only this file.
- Size: 1190 touched / +76 net, including this completion update.
  `router_fixtures.py`: 1,278 lines; `test_router_workflow.py`: 1,360.

The evidence directory contains the move map, complete AST comparisons,
collected inventories/delta, cross-import inventories and scope/closure
checks. Full acceptance uses eight shards and the base above.

---

# Batch D2a-1 completion

This is the first standalone TO1 family from Batch D2: `Workflow`,
`ContractWorld`, their document builders and shared literals now live in
`gen2/tests/router_fixtures.py`. Every importer of those moved names now
uses fixtures directly. The shared `verification_receipt` builder moved
unchanged from `AuthorityTest` to `RouterTestCase`; no re-export shims.
Receipt/acquisition cases and the remaining TO1 families await later D2a
PRs, each branched fresh after the previous part merges. D2b is deferred
until D2a merges and Trevor gives the go-ahead; no stacked PRs.

The sole production edit changes the `retained_request` docstring from
"Router/Store admission" to "Router admission", as requested under O-3.

## Evidence

Base: `40f0200d0c31d815741e7bafddb9c42eaff58893` (Batch E #58 merged).
Evidence directory: `~/work/research-loops-public/private/evidence/batch-d2/`.

- AST preservation: 20 moved nodes, all 3,619 retained test-side functions
  and all 6,730 assertion expressions compare equal. Normalization covers
  qualified fixture references, import placement, and the unchanged receipt
  builder's new fixture-base home. No assertion or test method deleted.
- Discovery: 2,953 unique IDs / occurrences before and after; no additions,
  removals or duplicate collections. See `d2a-1-collected-delta.json` and
  the complete `collected-before.json` / `collected-after.json` inventories.
- Cross-test imports: 143 → 118 statements, including module-alias imports;
  strict `from gen2.tests.test_X` statements: 99 → 81.
  The remaining imports belong to later families or explicit exclusions.
  Full inventories: `d2a-1-cross-imports.json`.
- Focused verification: 186 workflow, amendment, operator-command/status,
  and acquisition tests passed. Full-suite evidence is required below.
- Full sharded acceptance on a disposable copy: **passed**, 2,953 tests
  across 8 shards; all static and size gates passed. Command:
  `make gen2-accept GEN2_BASE=40f0200d0c31d815741e7bafddb9c42eaff58893 GEN2_TEST_WORKERS=8`.
  Logs, union inventory and mutation report: `d2a-1-accept-final/`.
  Tested code: `1275d622a6bfb8799ffa0d82fe9bb3c73ac1b13d`; the final amendment
  only records these results in this file.
- Mutation: **0 selected**; all 154 generated candidates were FILTERED_GIT.
  The production edit is docstring-only; no mutations were executed.
- Size: 832 touched / +94 net lines, including this file;
  `test_router_workflow.py` is 1,360 lines; `router_fixtures.py` is 782.

## Exclusions

`raw_exchange`: **deferred: owned by Batch F's file**. Its definition and
importers remain unchanged. The initial PR check found #54 (Batch F) and
#59 (records); their diffs were checked against `origin/gen2`. Before
publication only #54 remained open; its diff was rechecked. No excluded
file was modified. Test modules outside this family's owners receive only
imports or fixture-reference updates; their assertions are preserved.

The explicitly excluded test-side files are:

```text
gen2/tests/ddl_fixtures.py
gen2/tests/test_acceptance.py
gen2/tests/test_acceptance_coverage.py
gen2/tests/test_attempted_request_bytes.py
gen2/tests/test_automatic_mutation.py
gen2/tests/test_ci_runner.py
gen2/tests/test_failed_attempt_retention.py
gen2/tests/test_instants.py
gen2/tests/test_opaque_attempts.py
gen2/tests/test_operator_auth.py
gen2/tests/test_operator_mcp.py
gen2/tests/test_router_composition.py
gen2/tests/test_supervisor_budgets.py
gen2/tests/test_supervisor_crash.py
gen2/tests/test_supervisor_delegates.py
gen2/tests/test_supervisor_jobs.py
gen2/tests/test_supervisor_lifecycle.py
gen2/tests/test_supervisor_requeue.py
gen2/tests/test_supervisor_serialization.py
gen2/tests/test_supervisor_spool.py
gen2/tests/supervisor_fixtures.py
```

The open PRs also exclude `gen2/operator/auth.py`,
`gen2/operator/service.py`, `docs/gen2/DEPLOYMENT-CONTRACT.md`,
`docs/gen2/BOUNDARIES.md`, `docs/gen2/BUILD-STATE.md` and
`docs/gen2/REVIEW-LOG.md`. All protected records remain untouched.
All production is excluded except the explicitly authorized pagination
sentence. `ddl_fixtures.py` / DDL_TEXT behavior is unchanged.
