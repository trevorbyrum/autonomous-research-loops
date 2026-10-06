# Task 2q-b3b: the Router behaviour-preservation oracle, rebuilt (closes 2q-b3's Gate C block)

**Research basis:** `docs/gen2/research/2q-b-differential-20261006.md`. Implement that design.

**Source:** Astra's 2q-b3 review (`~/work/research-loops-public/private/reviews/gen2-2q-b3-astra-review-20261006.md`): C1, C2, NB1, NB2 and the "Rulings for Lifecycle, Scheduling and Amendments". The Registries production change is already judged sound: Gate A passed and both deviations were accepted. **This task rebuilds only the evidence tooling,** and then re-runs it on 2q-b3's change.

**Review-throughput rules apply:** target ≤ ~500 hand-written lines; targeted runs only; the orchestrator runs the full targets at landing. **No production change.**

## Required
1. **The mechanical-move equivalence tool,** reusable, in `tools/` with tests. Given a before and after tree, a class or module mapping, and a declared list of rewrites (`self._core.X`→`self.X`, `_core._transaction()`→`_store.transaction()`), it verifies that each moved method body is AST-identical after only those rewrites, and lists every other added or changed function for review. Apply it to 2q-b2 and 2q-b3.
2. **An exact deterministic replay,** replacing the masking harness.
   - Determinise at the seams: a fixed clock, deterministic ids and any randomness, injected into the Router under test. Find every source; don't scrub output.
   - Snapshot inputs before each call and results when returned (deep copies), fixing the aliasing probe.
   - Compare exactly: every recorded call, `invocation_status` poll, answer and store observation, plus an immediate store observation after each registry write route (NB2).
   - **Fail closed:** if two baseline runs disagree, the result is "unresolved", naming the source, never success. Remove the outcome-only and timing tiers.
3. **Comparator self-tests:** a changed answer, a removed store observation, a changed status answer, a reordered ordered list, a changed duration, a changed id namespace and a changed content hash must each fail. Archive the raw inputs durably under the evidence directory, not `/tmp`.
4. **Re-run on 2q-b3's change** (`d2151d9` against `8e73b42`) and on 2q-b2's (`be5b2f1` against `193ee7b`). Report the exact result per test, and the unresolved ones with their sources.
5. **NB1:** rename or reword the snapshot test and the BOUNDARIES.md wording to "direct-member/module-use check".

## Constraints
- Branch gen2. Change only tools, tests, docs and evidence; no production change.
- No provider calls. Never touch the live gen-1 gateway or 127.0.0.1:8765. Don't search `/home/trevor/work` recursively.
- Don't edit BUILD-STATE.md, REVIEW-LOG.md or DEBT-REGISTER.md.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-b3b/`.
- Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Use `git commit <paths>`.
- The completion report covers: the seams determinised; the comparator self-tests; per-change results; hand-written net lines; a literally true Remaining section.
