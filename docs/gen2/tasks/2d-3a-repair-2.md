# 2d-3a-repair-2: a sound near-match rule, classifying the edit and not the token (Astra 2d-3a round 2: R2-1, R2-2)

**Source:** `private/reviews/gen2-2d-3a-r2-astra-review-20261010.md`, pinned 040373d.
- Gates: A BLOCK, B PASS, C BLOCK (A and C classed as MITIGATION).
- **This is round 3 of 3, the cap.** If it fails, the operator decides.
- **Representation to implement:** `docs/gen2/research/2d-quote-protection-20261010.md`, the research note required before this re-brief because the family recurred.

**Closed and must stay closed:**
- A1, A2 and C1: NFC plus the safe whitelist, soft-hyphen-only rejoining, and idempotence.
- The input checks, the difflib boundary, citations, the split, the placement, and the version identities.

## Still failing (Astra's new probes)
Probes: `private/evidence/astra-2d-3a-r2/review_new_probes.py` and `review_new_probes.json`.
- **R2-1:** hyphenated negations (`not-yet`, `no-effect`, `cannot-act`) and spaced signs (`- 5` vs `+ 5`, `5 - 3` vs `5 + 3`) get diagnostics. The negative-prefix rule also misfires on `discuss`/`cuss`, `information`/`formation` and `image`/`age`.
- **R2-2:** numbers moved inside one lexeme (`abc1def` vs `abcde1f`, `BRCA1-positive` vs `BRCA-positive1`, `abc1def2ghi3jzz` vs `abcd1efg2hij3zz`) get diagnostics.

## Required
1. Implement rules (a)–(d) from the research note. They gate the diagnostic:
   - (a) equal **protected-character skeletons**, including the count of non-protected characters between consecutive protected characters;
   - (b) **safe edit regions**, each extended to its enclosing lexeme;
   - (c) a **conservative negative-prefix** rule;
   - (d) **no relocation**.

   Anything else is a **plain mismatch**. The existing protected-token comparison may stay as an extra layer, but it must not be the only gate.
2. **Lookalike controls, amended in the note:**
   - an unchanged `uniform`, `under` or `discuss` alongside an edit elsewhere still earns a diagnostic;
   - an edit to the prefix itself (`discuss` vs `cuss`) is a plain mismatch, by design.
3. **Tests:**
   - Literal cases for every R2-1 and R2-2 probe row.
   - All of Astra's round-1 and round-2 probes as regression literals.
   - The **soundness law** as a Hypothesis property. Generate protected-material edits of every kind (insert, delete, replace, move) at every position, including inside lexemes and across hyphens. The result must never be a match or a diagnostic.
   - The **utility law** as a property, with harmless typography and letter-only edits.
   - A paired mutant for each of rules (a)–(d).
4. Bump the rule identity (for example `quote-protection/3`) and update DOSSIER §2d-3.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2. Leave `service.py` unchanged.
- **Before committing, run:**
  - the targeted tests;
  - the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - the six gates.
- **Don't refresh `.venv-gen2`** while mutants run.
- **Reading:** only the repo's AGENTS.md and the paths named here. Never search `/home/trevor` or `/home/trevor/work` recursively.
- **No:** provider calls.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-3a-repair-2/`.
- **Commit messages:** end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
