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

## Addendum 1 (2026-10-09, after Astra round 2 on 2c-3a): dependencies between windows

**What round 2 showed:** the counting rule above is right only when its three counts really are lower and upper bounds. With E-4 they aren't, for two reasons:
- **Order-dependent distinctness.** E-4 credits a window to the *earliest* root that completes a search identity. An indeterminate root that comes earlier, in any scope, could complete with the same searches and turn a later "eligible" root into a repetition. Astra's case: `p0` missing, then `p1` on q1 and `p2` on q2, gives `satisfied`. If `p0` completes on q1 and q2, the result is `not_satisfied`.
- **Recoverable chains are marked ineligible.** An exhausted page 2 whose page 1 is missing is a chain that could still be completed, so it is indeterminate. It isn't provably invalid.

**Established practice: sound approximation of certain answers.** Computing exact certain answers is often intractable. The literature therefore accepts *sound* approximations: a definite verdict is returned only when every admissible completion agrees, and `unknown` is returned otherwise. This removes false positives and false negatives at the cost of extra unknowns. See:
- Libkin, ICDT 2015, §§4–5;
- Console, Guagliardo and Libkin (AAAI), whose principle is that more knowledge about the input may only add knowledge to the output;
- Console, Guagliardo, Libkin and Toussaint, PODS 2020, on approximation schemes.

Exactness is not required. Soundness is.

**The counting unit stays as E-4 defines it** (roots that complete a new distinct search). The bounds change:
- **Upper bound** = eligible + indeterminate. Resolving an earlier root can only take credit away from later roots, never add it. A root that is currently a repetition repeats an earlier *eligible* root, and that earlier root stays eligible.
- **Lower bound.** An eligible root counts only if no earlier indeterminate root, in **global order across all scopes**, could take its credit.
  - If an earlier indeterminate root has recorded request or search identities (it is partially observed), only roots whose searches all fall inside that recorded set are at risk.
  - If an earlier indeterminate root has unknown searches (capture missing entirely), every later eligible root is at risk.
  - For a root at risk, also take the minimum over the resolutions of the indeterminate root that could take its credit: failed (takes nothing, adds nothing) or complete (takes credit, and adds 1 if it is in scope). If the indeterminate root is in scope, its own completion contributes the window it takes. The scope boundary is where Astra's scoped probe failed.
- **Chain knowledge.** Classify each chain as one of:
  - **provably invalid:** a contradiction that no added page can repair (for example, a page > 1 with a null incoming cursor, or conflicting pages);
  - **recoverable:** missing prefix or interior pages that are consistent with what was observed. Count it as indeterminate;
  - **complete.**
- **Verdict:** satisfied iff lower ≥ N; not_satisfied iff upper < N; otherwise unknown. A conservative lower bound is acceptable. A lower bound that some admissible completion falls below is not.

**Validation, a standard reference-model (differential) test.** On small inventories, enumerate every admissible completion of every indeterminate root over a finite search universe: the inventory's own search identities plus one fresh one, each root either failed or complete, and recoverable chains either completed or not. Then assert:
- the implementation's definite verdicts agree with every completion;
- every case where all completions agree but the implementation says `unknown` is a permitted approximation, reported by the test as a count.

Generate the cases with Hypothesis, placing indeterminate roots before, between and after observed ones, with overlapping and disjoint searches, multi-search roots, missing prefix and interior pages, delegates, scope boundaries and G-1 standings. This is a test oracle, not a proof tool.
