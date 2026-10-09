# Task 2q-b9b: make the inline-back checker enforce its helper/call grammar (closes 2q-b9's C1)

**Superseded; not an active repair task.** The operator dropped this checker repair on 2026-10-08 under the charter's [Refactor evidence standard](../BUILD-CHARTER.md#review-throughput), as confirmed by [Astra's 2q-b8/2q-b9 re-review](/home/trevor/work/research-loops-public/private/reviews/gen2-2q-b8-b9-astra-rereview-20261008.md). The unchanged checker is advisory and `IDENTICAL` supplies no behavioral guarantee. The documentation/accounting closeout is owned by task 2q-t5; the brief below is historical.

**Source:** Astra's 2q-b9 review (`~/work/research-loops-public/private/reviews/gen2-2q-b9-astra-review-20261007.md`), C1 and its "Required repair", plus NB2. The production extraction is ROOT-CAUSE and is **not** changed. L1 (the inherited 2q-b8 test failures) is fixed separately by 2q-b8b.

Astra's counterexamples (`private/evidence/astra-2q-b9/checker-counterexamples.json`, `review_probes.py`) all pass `--inline` as IDENTICAL while changing behaviour:
- `return claims` → `return (claims,)`;
- `claims = …` → `claims, = …`;
- adding `@staticmethod`;
- `async def`.

**Review-throughput rules apply:** small; targeted runs only; the orchestrator runs the full targets at landing. **No production change.**

## Required
1. **Define and enforce the accepted helper/call grammar** in `tools/gen2_move_equivalence.py --inline` **before** removing any syntax:
   - keep scalar versus tuple shape, arity and ordered names when matching assignment targets to returned values;
   - require ordinary synchronous, undecorated helper methods, with any other callable form refused, or given a separately justified rule;
   - audit every helper field that gets discarded against the grammar, and refuse on mismatch.
2. **Controls:**
   - literal-source and CLI negative controls for each of Astra's four counterexamples, plus the shape and callable-kind variants;
   - the valid 2q-b9 extraction as a positive control;
   - show that disabling each new validation is detected, with mutants and paired controls.
3. **Documentation:** keep the stated manual name-resolution and transaction review limits; AST expansion is not a general semantic-equivalence proof.
4. **NB2:** correct the wiring-test docstring to 106/108 branches, and the evidence summary's count of unique mutants.

## Constraints
- Branch gen2. Change only tools, tests, docs and evidence.
- No provider calls. Never touch the live gen-1 gateway. Don't search `/home/trevor/work` recursively.
- Don't edit BUILD-STATE.md, REVIEW-LOG.md or DEBT-REGISTER.md.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-b9b/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>`.
