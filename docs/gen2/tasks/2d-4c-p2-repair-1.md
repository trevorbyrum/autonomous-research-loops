# 2d-4c-p2-repair-1: the receipt-reference test experiments (Astra Gate C, round 1)

**Subject:** 2d-4c part 2 (`f149947`, `6c145ae`).

**Astra round 1** (`private/reviews/gen2-2d-4c-p2-astra-review-20261017.md`):
- Gates A and B PASS. The production change is ROOT-CAUSE at its optional-binding scope.
- **Gate C BLOCK** on two experiment-construction defects. Both are charter blocking class (e): the evidence claims a property its experiment doesn't establish.
- **No production escape was shown.** Both repairs are ROOT-CAUSE test repairs.
  - A bigger count, another green run, or narrower wording that keeps the gap would be a MITIGATION, which only Trevor can accept.

## C1: fixture setup defeats trigger reversal
**Where:** `ReferenceCases.setUp` (`gen2/tests/test_detailed_check_receipts.py:19`).

**The defect:**
- The fixture rebuilds and seeds from `db.schema_text()`, which discards the DDL the reversal runner supplied.
- It then reinstalls three guards in a fixed tuple order.
- Astra observed the same 334-trigger creation order after normal and "reversed" setup.
- So all 20 raw receipt cases get no reversed-order credit.

**Required:**
- After any unmutated seeding, restore the **complete requested installed-trigger set in its requested order**, keeping dropped or mutated definitions.
- **Assert the actual `sqlite_schema` trigger order before the subject write.**
- Run the receipt matrix against the ordered DDL and its exact reversal.
- Add a regression that fails if setup silently resets either.
- Prefer one shared fixture helper over a local patch.

**Family audit (required):** other modules use the same `DDL_TEXT`/`db.schema_text()` reseed pattern, at least:
- `test_bound_extraction_support`, `test_validated_extraction_receipts`, `test_own_extraction_receipts`;
- `test_store_json_rollout`, `test_store_json_member_domain`, `test_store_observation_domain`, `test_store_detailed_checks`.

For every such module, determine with an actual order probe, not by reading, whether its reversed run really runs reversed.
- **Fix every defeated module with the same shared helper** if the total stays within about 250 additional hand-written lines.
- **Otherwise,** fix the receipt module and the shared helper, list the remaining defeated modules with probe evidence in COMPLETION.md, and stop. The orchestrator will route them.

## C2: validated target and validator bytes are indistinguishable
**Where:** `test_detailed_check_receipts.py:117`.

**The defect:**
- Both extraction methods seed identical canonical, target and validator hashes.
- With the selector changed from the validation's target to its validator, every receipt test still passed: all 21 Router tests (SQL binding trigger removed) and all 20 raw tests (Router bypassed).
- Astra's reproduction: `private/evidence/astra-2d-4c-p2/probes.py` and `probe-results.json`.

**Required:**
- Add distinct-output `semantic_agreement` cases with **three distinct byte identities** (canonical input, target output, independent validator output) to **both** the Router and raw-DDL matrices.
- Isolate one optional reference at a time, for every kind:
  - records examining canonical or validator bytes must be refused;
  - records examining the target must be admitted.
- **Add selector mutants in both layers:**
  - Router: target → validator in `DetailedChecks.require_receipt`;
  - SQL: target → validator in SQL 37's validated-extraction binding branch.
- Pair each with a **separate accepted validated-extraction control that still passes under the mutation**, such as the existing byte-equal control.
- Keep qualified traces through the validated-selection branch.
- The distinct-output cases are the killers. They must fail by assertion, not by error.

## Constraints
- **No production change** unless a probe shows a real defect. If it does, stop and report.
- Other constraints are as in `docs/gen2/tasks/2d-4c.md`:
  - all pre-commit gates, including the full `gen2-test`, `gen2-trigger-order`, the composition module, `--only` on affected families (including transitive fixture imports), and the static gates;
  - copy the venv with `cp -a` and never symlink it;
  - wait for `gen2-landing-*` units before heavy runs;
  - limit any AGENTS.md lookup to the repository;
  - don't edit BUILD-STATE, REVIEW-LOG or DEBT-REGISTER;
  - end commits with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4c-p2-repair-1/`, with a COMPLETION.md.
- Add a short DOSSIER §2d-4c repair note.
