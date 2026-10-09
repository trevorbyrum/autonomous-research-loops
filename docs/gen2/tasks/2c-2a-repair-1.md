# 2c-2a-repair-1: register the new Router member and collaborator (Astra 2c-2a, round 1, F1 and NB1)

**Source:** Astra's review `private/reviews/gen2-2c-2a-astra-review-20261009.md`, pinned to `bfe0975`.
- **Verdict:** A PASS, B PASS, C BLOCK, all classed ROOT-CAUSE.
- **This is round 1 of 3.** The next review checks only F1.
- **Nothing else is in question.** The design, storage, accounting, boundary and methodology all passed, so don't touch them.

## The failure
The orchestrator's landing run `gen2-check` at `bfe0975` exited 2: 2,490 tests, 3 failures.
- **Cause:** the new public method `Router.evidence_inventory` isn't in `PUBLIC_API` in `gen2/tests/test_router_composition.py`.
- **Which tests fail:** `test_the_router_composes_its_collaborators_and_keeps_its_public_methods` fails. The clean baselines of the two lifecycle/status mutation regression tests then fail on that same assertion.
- **Why it slipped through:** the targeted test set didn't include the composition tests.

## Required
1. **F1:** add `evidence_inventory` to `PUBLIC_API`, and keep the equality assertion.
2. **NB1:** add the assessment collaborator (`Assessments` / `AssessmentCore` / `_assessments`) to `COLLABORATORS`, so the generic interface, core-only storage and transaction-access checks examine it.
   - If those checks expose a real deviation from the collaborator pattern, fix the production code at the root cause and say so.
3. **Run before committing:**
   - `gen2/tests/test_router_composition.py` in full;
   - the two mutation regression tests that failed;
   - the 2c-2a and 2c-1 targeted sets;
   - `make gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.

   Run these **in addition to** the targeted set. Any change to a public Router member must include the composition tests from now on.

## Constraints
- **Coder:** GPT-6.1-Sol. **Branch:** gen2.
- **Tests:** targeted runs only. The orchestrator runs the full targets.
- **Don't edit:** BUILD-STATE.md, REVIEW-LOG.md, DEBT-REGISTER.md.
- **Safety:** no provider calls. Never touch the live gen-1 gateway or 127.0.0.1:8765.
- **Evidence:** `~/work/research-loops-public/private/evidence/2c-2a-repair-1/`.
- **Commit message:** ends with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`; commit with `git commit <paths>`.
