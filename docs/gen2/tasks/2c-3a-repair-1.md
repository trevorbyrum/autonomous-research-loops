# 2c-3a-repair-1: coverage over partly observed windows (Astra 2c-3a round 1, F1)

**Sources:**
- Astra's review `private/reviews/gen2-2c-3a-astra-review-20261009.md`, pinned `df1dffd`. Verdicts: A BLOCK, B PASS, C BLOCK. Classified as a MITIGATION and flagged as boundary drift against the Evidence-accounting unknown rule.
- **The research note to follow:** `docs/gen2/research/2c-coverage-unknown-20261009.md`.

This is **round 1 of 3**. The next review checks only F1.

**What passed and must stay:**
- strong-Kleene `combine()`;
- the gates conjoined into `evaluate_profile()`;
- the descriptive and known-item evaluators;
- purity and the ledger;
- all accepted tests and mutants.

## The defect
`coverage()` (`gen2/accounting/stopping.py:87`) treats the E-4 eligibility list as a complete denominator. Windows that were attempted but only partly observed disappear from it. Astra's probes (`private/evidence/astra-2c-3a/coverage_unknown_probe.py`, `coverage-unknown-results.json`) show four cases returning `not_satisfied` where the answer must be `unknown`:
- a committed pass with no capture;
- a partial page with an unknown end;
- an unobserved request;
- a complete page whose pagination end is unknown.

## Required (follow the research note)
1. **A window-standing view in `gen2/accounting`, beside `saturation_passes()`.**
   - It covers every attempted research window, including delegates.
   - Each window is **eligible**, **ineligible** (known, with a reason) or **indeterminate** (with a reason).
   - `saturation_passes()` and the E-4 exclusions stay unchanged.
2. **Coverage uses certain-answer bounds:**
   - **satisfied** iff `eligible ≥ N`;
   - **not_satisfied** iff `eligible + indeterminate < N`;
   - otherwise **unknown**.

   The operands show all three counts plus the indeterminate windows and their reasons. The scope is per rule, not a topic-wide flag. Unrelated valid historical windows are preserved.
3. **Tests, with hand-written expectations:**
   - Astra's four failing cases must give `unknown`. Add the same case on **delegate** work.
   - Controls:
     - no attempt gives `not_satisfied`;
     - one complete window gives `satisfied`;
     - enough eligible windows plus one indeterminate window gives `satisfied`;
     - too few windows, even counting the indeterminate ones, gives `not_satisfied`.
   - **Hypothesis law (knowledge monotonicity):** resolving an indeterminate window never flips a definite verdict.
   - Add a paired mutant for each new guard, for example: indeterminate counted as ineligible; indeterminate counted as eligible; standing dropped from the operands.
4. Update `docs/gen2/ACCOUNTING.md` for the standing view.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2.
- **Checks before committing:**
  - targeted tests;
  - the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - the six pre-commit gates.
- **Don't edit:** BUILD-STATE.md, REVIEW-LOG.md, DEBT-REGISTER.md.
- **No:** provider calls, live gateway access, or recursive search of `/home/trevor/work`.
- **Don't refresh the shared `.venv-gen2`** while mutants are running. Use a separate copy if you need a candidate environment.
- **Evidence:** `~/work/research-loops-public/private/evidence/2c-3a-repair-1/`.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`, and use `git commit <paths>`.
