# 2d-3a-repair-1: lossless protection in the quote matcher (Astra 2d-3a round 1: A1–A4, C1)

**Source:** `private/reviews/gen2-2d-3a-astra-review-20261010.md`, pinned 0a8238e.
- **Verdict:** A BLOCK, B PASS, C BLOCK. The fix needs to be ROOT-CAUSE.
- **This is round 1 of 3.**
- **Reproductions:** Astra's probes are in `private/evidence/astra-2d-3a/` (`review_probes.py`, `review_extra_probes.py` and their JSON).

**Accepted, keep:**
- the input checks (artifact SHA-256, half-open spans, UTF-8 boundaries, fail-closed);
- the difflib diagnostic with its exact 0.98 boundary;
- the citations and version identities;
- the split, with governed integration left to 2d-3b;
- placement under `gen2/router/`.

## Root cause
Normalization **loses information before protection runs**, and protection is **coupled to how the diagnostic matcher aligns the text**. Raising the threshold or adding words to lists won't fix either.

## Required
1. **Use canonical, not compatibility, normalization by default (A1, C1).**
   - The W3C *Character Model for the World Wide Web: String Matching* recommends canonical (NFC) equivalence for matching. Compatibility forms (NFKC) are lossy: 10² becomes 102, m² becomes m2.
   - Use **NFC plus an explicit whitelist** of safe typographic equivalences: whitespace runs, curly vs straight quotes, and typographic dash variants **other than U+2212 MINUS SIGN**, which is mathematical.
   - Any compatibility fold you keep needs a cited justification. It must never apply to digits, superscripts, subscripts or unit symbols.
   - The transformation must be **idempotent by construction**. Add the Hangul regression (`"ᄀ-\nᅡ"`) and the soft-hyphen variant, plus generated examples that compose the rules.
2. **Line-break dehyphenation (A2): fail closed when it's ambiguous.**
   - The text alone can't distinguish a discretionary break from a real hyphen. So rejoin across a line break **only for an explicit soft hyphen (U+00AD)**.
   - A hard hyphen at a line break stays a hyphen, so `re-\nsign` vs `resign` is a mismatch.
   - Never touch the minus sign or other operators.
   - Controls: a permitted soft-hyphen wrap, next to cases for a genuine compound, a negative prefix, and a mathematical operator.
3. **Protected tokens are compared on the original text, in order, independently of alignment (A3, A4).**
   - Tokenize the **pre-normalization** text, apart from the safe whitelist folds, into protected tokens:
     - **complete grouped numbers**, including separators, decimals, exponents and signs;
     - **unit expressions**, including the operators `/ · × ^` and superscripts;
     - **negations**, including the versioned prefixes `non-`, `un-`, `in-`/`im-`/`ir-`/`il-`, `dis-` and `n't`.
   - **Negation-prefix rule:** treat a prefix as negation only when it appears on a versioned word list, or when you can show the stem is shared across the quote and the source. Add positive controls such as "uniform", "under" and "discuss", which must not be classed as negation.
   - **Compare the ordered protected-token sequences** of the quote and the source span. Any difference, including a **relocation**, means a plain mismatch with **no** near-match diagnostic.
   - Use the diagnostic matcher only after the protected sequences are already equal.
   - Required literal cases: `not early if later` vs `later if not early`; `measure mg then rate` vs `rate then measure mg`; `1;000` vs `1,000`; `mg/kg` vs `mg·kg`; `seconds` vs `minutes`; `non-effective` vs `effective`; `unavailable` vs `available`.
4. **Versions.** Bump the identities of the normalization and token rules (for example `quote-nfc-safe/2` and `english-negation/2`), and record them in the results.
5. **Gate C.**
   - Write independent literals for every case in A1–A4.
   - Add generated properties: idempotence over composed rules, and the law that inserting, removing or moving a protected token never yields a pass or a diagnostic.
   - Pair each new guard with a mutant.
   - Replace the shallow `test_near_control` with a control that checks the **full result**.
   - Add the contrasting fixture that separates difflib from normalized Levenshtein (Astra's non-blocking note).

## Constraints
- Coder: GPT-6.1-Sol, branch gen2. `service.py` stays unchanged.
- Run before committing:
  - the targeted tests;
  - the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - the six gates.
- Don't refresh `.venv-gen2` while mutants are running.
- Read only the repo's AGENTS.md and the paths named here. Never search `/home/trevor` or `/home/trevor/work` recursively.
- No provider calls.
- Don't edit BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- Evidence goes to `~/work/research-loops-public/private/evidence/2d-3a-repair-1/`.
- Commit messages end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
