# Research: deciding when a quote difference may get a near-match diagnostic (2d-3a, A3 and A4 recurring)

**Why this note exists.** The charter says to research before re-briefing. 2d-3a has had two BLOCK rounds in the same family: protected tokens slip through.
- Round 1 (NFKC loss, alignment coupling) was fixed.
- Round 2 found new bypasses in the lexer:
  - hyphenated negations: `not-yet`, `no-effect`, `cannot-act`;
  - signs separated from their numbers by spaces: `- 5` vs `+ 5`;
  - numbers moved inside a single word: `abc1def` vs `abcde1f`;
  - an over-broad negative-prefix rule: `discuss` vs `cuss`.

Each round enumerates more token shapes, and each new shape opens new gaps. Round 3 is the cap.

## The defect class
The matcher tries to **positively recognise every protected construct** (complete numbers, unit expressions, negations) with a lexer, and then lets everything else earn a diagnostic. That is a completeness problem. Any shape the lexer misses becomes a false "safe" verdict.

## Established practice
1. **Sound, conservative approximation.** This is already adopted in `2c-coverage-unknown-20261009.md` Addendum 1 (Libkin, ICDT 2015; Console, Guagliardo, Libkin, PODS 2020).
   - When exact classification is hard, return the safe answer whenever unsure.
   - Here the safe answer is a **plain mismatch with no diagnostic**. The quote is quarantined either way (V-6), so over-protecting costs only a convenience hint, never correctness.
2. **Classify the edit, not the token.** A character diff yields explicit edit regions: insert, delete and replace opcodes (Myers, "An O(ND) Difference Algorithm and Its Variations", *Algorithmica* 1986; Python `difflib.SequenceMatcher.get_opcodes`).
   - Deciding whether *those regions* are harmless is a **closed, local question**: is the edited text, plus its enclosing lexeme, free of protected material?
   - The open question it replaces is whether a lexer has understood the whole sentence.
3. **W3C *Character Model: String Matching*** (canonical equivalence) stays the basis for the safe normalization. That part is accepted (A1, A2 and C1 are closed).

## The rule the repair should implement
A **near-match diagnostic is allowed only if every one of these holds**. Otherwise the result is a plain mismatch.
- **(a) Equal protected skeletons.** After safe normalization, the two strings have identical **protected-character skeletons**. A skeleton is the ordered sequence of every digit, sign or operator character (`+ - − ± × · / ^ % ‰ = < > ≤ ≥`), and every superscript or subscript, together with the **exact count of non-protected characters between consecutive protected characters**.
  - This catches relocation inside a word (`abc1def` vs `abcde1f`), sign flips, and spaced signs, without any lexing.
- **(b) Safe edit regions.** No diff edit region, **extended to its enclosing lexeme** (maximal run of non-whitespace), contains:
  - any protected character;
  - any token from the versioned negation list, matched as a substring on letter boundaries inside the lexeme, including hyphen-joined forms (`not-yet`, `no-effect`, `cannot`);
  - any unit-list token.
- **(c) Negative prefixes.** An edit that deletes or inserts a leading `un-`, `non-`, `in-`, `im-`, `ir-`, `il-` or `dis-` on a lexeme counts as protected.
  - This is **deliberately conservative**. `discuss` vs `cuss` becoming a plain mismatch is an acceptable over-protection.
  - **This amends the earlier brief's lookalike requirement.** The required lookalike controls are now:
    - *unchanged* words that happen to start with those letters must not affect anything (`uniform` vs `uniform` with an edit elsewhere still gets a diagnostic);
    - a case where the prefix itself is edited (`discuss` vs `cuss`) gives a plain mismatch. **This is acceptable by design.**
- **(d) No relocation.** No deleted region's text reappears as an inserted region elsewhere, which would be a move. A move of any length that touches a lexeme with protected material is a plain mismatch.

**Soundness law (Hypothesis).** For any string and any single protected-material edit (insert, delete, replace or move of a digit, sign, operator, negation token or unit token, anywhere, including inside a lexeme or across a hyphen), the result is never a match and never a diagnostic.

**Utility law.** Edits that touch only whitespace, typography or letters, with no protected material in the enclosing lexeme, still get a diagnostic when the text is ≥98% similar.

Exactness is not required; soundness is.
