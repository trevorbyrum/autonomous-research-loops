# 2d-4c-p4b2c2-repair-1: the zero-DML oracle misses executed writes (Astra Gate C, round 1)

**Subject:** 2d-4c part 4b2c2 (`5b01b6e`; diff base `cf52bd1`).

**Astra round 1** (`private/reviews/gen2-2d-4c-p4b2c2-astra-review-20261021.md`):
- **Gate A PASS, Gate B PASS, Gate C BLOCK.**
- The guarded admission, the detached history reader and the temporal-fixture correction are **ROOT-CAUSE** and conform to the 2026-10-20 and 2026-10-21 operator rulings.
- **Source inspection found no opening or installation DML in production.** The defect is in the regression guarantee only.
- Astra did not require a further split on size.
- Landing at `5b01b6e` was green: `gen2-check` 7,532 s, `gen2-gateway` 1,018 s.

## C1 (blocking): the zero-DML test passes despite executed writes
**Where:** `gen2/tests/test_retained_support.py:234`, `test_snapshot_and_no_dml`.

**The defect:**
- The test recognizes DML only by a first-keyword regex on trace strings: `r'\s*(INSERT|UPDATE|DELETE|REPLACE)\b'`.
- SQLite keeps leading comments in trace strings, and DML can begin with `WITH`.
- Astra reproduced the gap against the unchanged test:
  - a bare opening `UPDATE` fails, as it should, which shows the assertion runs;
  - a comment-prefixed `UPDATE`, a CTE-led `UPDATE`, and a comment-prefixed installation `INSERT` (in the repository's own `-- trace:` style) all **pass**, even though rows really changed.
- The exact canaries are in the review.
- This is charter blocking class (e): a test claims to enforce an operator-ratified property it doesn't enforce.

**Required (ROOT-CAUSE):**
- Replace the first-keyword regex with **database-aware observation of application-table writes** that tells them apart from legitimate schema-catalog operations. Examples: compare the full application-table contents or change counters before and after, or use the SQLite authorizer or update hooks.
- **Stripping one comment spelling is not enough.** It would leave the defect family open.
- **Qualify the oracle** with bare, comment-prefixed and CTE-led DML canaries. Each must produce an assertion failure with no unrelated errors.
- Cover the installation, admission (including refusal) and history-readback paths. Keep the existing snapshot assertions.

## NB1 (fold in): mock-induced errors in the original-code comparison
- Running all 13 new tests against the original `service.py`/`station.py` gave 14 assertion failures across six methods, but also **four errors**, one in each startup subcase, caused by mocks.
- **Required:** give the startup mocks valid downstream return values, so the original code fails by assertion without mock-induced errors. Keep the real no-effects assertions.

## Constraints
- **Test-only repair.** No production change, unless a probe shows a real production defect; if one does, stop and report.
- Other constraints are as in `docs/gen2/tasks/2d-4c.md`:
  - the full `gen2-test`, `gen2-trigger-order`, the composition module, the affected mutation families (or the full inventory if shared fixtures change), the startup/station/engine suites, and all eight static gates;
  - copy the venv with `cp -a`;
  - wait for `gen2-landing-*` units before heavy runs.
- Look up AGENTS.md only inside the repository. No provider calls. Never touch gen-1 runtime state or `127.0.0.1:8765`.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. Don't push or merge.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4c-p4b2c2-repair-1/`, with PROGRESS.md and COMPLETION.md. Class every fix ROOT-CAUSE or MITIGATION.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
