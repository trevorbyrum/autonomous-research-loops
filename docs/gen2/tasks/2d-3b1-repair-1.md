# 2d-3b1-repair-1: remove the unsound endpoint relaxation (Astra 2d-3b part 1, round 1, B1-1)

**Source:** `private/reviews/gen2-2d-3b1-astra-review-20261011.md`, pinned at f722a39.
- **Gates:** A BLOCK, B PASS, C PASS.
- **Round:** this is round 1 of 3.
- **Accepted, and stays as is:** the apostrophe-boundary repair itself. That covers protection recognition splitting at apostrophes, the 14 literals, the apostrophe-wrapped soundness law, and Astra's 120-case boundary matrix passing.

## B1-1
- **What happens:** the new endpoint exception in `safe_edits()` (`gen2/router/quote_matching.py:170`) treats whitespace in a *removed* fragment as if it still separated the words afterwards.
- **Examples:** `alpha'not early` vs `alpha'notearly`, and `early not'alpha` vs `earlynot'alpha`.
  - Deleting the space joins the protected negation onto the next word.
  - The result still gets a near-match diagnostic.
- **Scale:** Astra's `private/evidence/astra-2d-3b1/review_endpoint_probes.json` has 480 of 480 boundary cases failing. The Hypothesis law `review_endpoint_property.py` fails too.

## Required: the conservative fix
1. **Remove the endpoint relaxation completely.** Go back to the inclusive check: any edit region that touches a protected lexeme's endpoint counts as protected.
   - This follows the adopted principle in `docs/gen2/research/2d-quote-protection-20261010.md`: when unsure, return the safe answer, which is a plain mismatch.
   - **Orchestrator amendment:** the `trial's` ↔ `trial's a` utility case (deleting an ordinary word next to a possessive) becomes a **plain mismatch, by design**. That is acceptable over-protection; the quote is quarantined either way.
   - Update that utility control to show it, and keep every other utility control.
   - Bump the identity to `quote-protection/5`.
2. **Tests:**
   - Literals for every B1-1 case: whitespace deletion, insertion and replacement creating or removing a protected word's letter boundary, on both sides, in both directions, with both apostrophe forms.
   - A generated law for the same.
   - A paired mutant that restores the relaxation, killed by these literals.
   - Re-run Astra's `review_endpoint_probes.py` and `review_endpoint_property.py`, and the earlier boundary probes, as reference.
   - Keep all 66 earlier regression literals and the 14 apostrophe literals.

## Constraints
- **Coder:** GPT-6.1-Sol, on branch gen2. Leave `service.py` unchanged.
- **Before committing, run:** the targeted tests, the full composition module, `--only` on every mutant family that targets an edited file, and the six gates.
- Don't refresh `.venv-gen2` while mutants are running.
- Read only the repo's AGENTS.md and the paths named here. Never search `/home/trevor` or `/home/trevor/work` recursively.
- No provider calls.
- Don't edit BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- Evidence goes to `~/work/research-loops-public/private/evidence/2d-3b1-repair-1/`.
- Commit messages end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
