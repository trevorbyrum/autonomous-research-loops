# Research: coverage rules over partly observed search windows (2c-3a F1; a recurring family with 2c-1 F1–F3)

**Trigger:** the charter's "Research before re-briefing". 2c-3a F1 is the second finding in one family. 2c-1 F1–F3 was the first. In both, a lossy projection of search windows drops what is needed to tell the cases apart:
- 2c-1: complete versus distinct windows.
- 2c-3a: known-ineligible versus unobserved windows.

So this note settles the representation before the repair brief is written. It doesn't rely on the coder to rediscover it.

## The defect class
- `coverage()` counts `saturation_passes(inventory)`. That function is an eligibility filter: incomplete, partial, unobserved and unknown-end windows are dropped before counting.
- An empty eligible list therefore can't tell "nothing was searched" apart from "searched, but we don't know whether it finished".
- Astra's probe: four partly observed cases return `not_satisfied`. The correct answer is `unknown`.

## Established practice
1. **Certain answers over incomplete data.** This is the standard semantics for queries on incomplete databases (Imieliński and Lipski, 1984; Libkin, "SQL's Three-Valued Logic and Certain Answers", ICDT 2015, LIPIcs 31:94–109; Console, Guagliardo, Libkin and Toussaint, PODS 2020 survey).
   - **Certainly true:** the answer holds in every completion of the unknowns.
   - **Certainly false:** it fails in every completion.
   - **Unknown:** otherwise.
   - Libkin shows that plain three-valued evaluation can return false negatives. A corrected classification removes them.
   - **The governing principle:** more knowledge about the input may only add knowledge to the output. Resolving an unknown never flips a definite verdict (Console, Guagliardo and Libkin, AAAI, many-valued approximation of certain answers).
2. **Systematic-review accounting (PRISMA 2020; Page et al., BMJ 2021;372:n71).**
   - Records whose status can't be established go in their own box ("reports not retrieved"). They are counted and reported. They are neither silently dropped from the denominator nor counted as exclusions.
   - Every record is accounted for at each step.

## Representation the repair should use
- **One standing per attempted window, with its reason.** The window universe is every research invocation, including its delegates (2c-1's ancestry):
  - **eligible:** completed and distinct (E-4, unchanged);
  - **ineligible (known):** failed, capped, repeated, or not current under G-1;
  - **indeterminate (reason):** capture missing, capture partial or unknown, request unobserved, pagination end unknown.
- **A "≥ N windows" coverage rule then uses certain-answer bounds:**
  - **satisfied** iff `eligible ≥ N`;
  - **not_satisfied** iff `eligible + indeterminate < N`;
  - **unknown** otherwise.

  The operands show all three counts and list the indeterminate windows with their reasons, as in PRISMA's separate box.
- **Scope:** it's per rule. An unrelated indeterminate window counts only if it is in the rule's scope. A topic-wide failure flag would be a mitigation.
- **What stays the same:** `saturation_passes()` stays the E-4 eligibility view, unchanged. Coverage stops treating that view as a complete denominator.
- **Law to test with Hypothesis (knowledge monotonicity):** resolving any indeterminate window to eligible or ineligible never changes a `satisfied` or `not_satisfied` verdict. It can only resolve an `unknown`.

## Relation to the 2c-1 family
2c-1 F1–F3 fixed the projection that decides eligibility. This finding is about a consumer of that projection. Both are fixed by keeping the full window inventory, with standings, available to every consumer. The repair should expose the standing view next to `saturation_passes()`, so that 2c-3b and 2c-4 inherit it.
