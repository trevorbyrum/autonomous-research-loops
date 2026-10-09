# 2c-2a-repair-2: re-anchor the two stale 2QB10 delegate mutants (Astra 2c-2a, round 2, F2)

**Source:** `private/reviews/gen2-2c-2a-r2-astra-review-20261009.md`, pinned to `c984af9`.
- F1 and NB1 are **closed**.
- This is round 3 of 3, the cap. After it, the operator decides.

## Failure
The orchestrator's landing `gen2-check` at `c984af9` exited 2.
- **What passed:** 2,490 tests and the trigger-order check. 2,428 of 2,430 mutants were killed.
- **What failed:** two mutants were **INVALID** (their mutation text was found 0 times):
  - `2QB10-router-delegate-drops-the-outbox`
  - `2QB10-router-delegate-drops-the-triggers`
- **Why:** both use `DELEGATE` in `tools/gen2_mutants/router_composition_2qb10.py`, which still reads `return self._evidence_writer._write_evidence(...)`. 2c-2a changed `Router._write_evidence` (`gen2/router/service.py:1155`) to assign that call to `written` and then append assessments.

## Required
1. Update the `DELEGATE` anchor to the current statement.
   - Keep the two separate counterfactuals: dropped outbox, and dropped triggers.
   - Keep their killers (`OUTBOX`, `CLOSURE`) and their paired controls.
   - Don't remove the mutants, and don't exempt INVALID verdicts.
2. Run `--only 2QB10`: all five mutants must be killed and their controls must pass.
3. **Re-check every other mutant for a stale anchor.**
   - Scope: every mutant that targets a file changed since `2339991` (`gen2/router/service.py`, `gen2/router/accounting.py`, `gen2/accounting/__init__.py`, the store schema).
   - Run `--only` on each of those mutant families. Report each one's kill and control result.
   - **Standing rule from now on:** any slice that edits a file must run `--only` on every mutant family that targets that file.
4. Run the composition tests and `make gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.

## Constraints
- **Coder:** GPT-6.1-Sol. **Branch:** gen2.
- **Testing:** targeted tests and `--only` mutants only. The orchestrator runs the full targets.
- **Don't edit** BUILD-STATE.md, REVIEW-LOG.md or DEBT-REGISTER.md.
- **No provider calls.** Never touch the live gen-1 gateway or 127.0.0.1:8765.
- **Evidence:** `~/work/research-loops-public/private/evidence/2c-2a-repair-2/`.
- **Commit message:** ends with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`. Commit with `git commit <paths>`.
