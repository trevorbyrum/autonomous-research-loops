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
