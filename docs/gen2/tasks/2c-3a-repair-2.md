# 2c-3a-repair-2: sound coverage bounds under window dependencies (Astra 2c-3a round 2, F1 continued)

**Source:** `private/reviews/gen2-2c-3a-r2-astra-review-20261009.md`, pinned `4f5a91e`.
- **Verdicts:** A BLOCK, B PASS, C BLOCK. F1 remains open as a MITIGATION.
- **Round 3 of 3, the cap.** After this the operator decides.
- **Representation:** follow **Addendum 1** of `docs/gen2/research/2c-coverage-unknown-20261009.md` exactly.

**Accepted; keep it:**
- `window_standings()` rows and reasons;
- the four original F1 cases;
- delegates;
- G-1 stale = known-ineligible (Astra accepted this);
- per-rule scope;
- the unchanged `saturation_passes()` and E-4 exclusions;
- all 48 accepted stopping mutants;
- the 21 accepted coverage tests.

## Failures to fix
1. **Overlap order.** An earlier indeterminate root can take credit from later eligible roots, so the eligible count isn't a lower bound. In Astra's `reviewer_probe.py` and `router_overlap_probe.py`, `satisfied` flips to `not_satisfied`. This also happens across a rule-scope boundary.
2. **Recoverable chains.** An exhausted page 2 with a consistent incoming cursor but a missing page 1 is classed as known-ineligible. It must be indeterminate (`missing_prefix_probe.py`).

## Required
1. **Bounds** per Addendum 1:
   - upper = eligible + indeterminate;
   - lower discounts any eligible root whose credit an earlier indeterminate root could take, in global order across scopes;
   - if the earlier root's searches are known, discount only the roots those searches cover;
   - if they are unknown, discount every later root;
   - take the minimum over that root's failed or complete resolution, counting its own contribution when it is in scope.

   A conservative lower bound is acceptable. An unsound one is not.
2. **Chain classes:** provably invalid, recoverable (counted as indeterminate), or complete. The E-4 eligibility view is unchanged; recoverable chains stay out of the present eligibility list.
3. **Reference-model test:**
   - Enumerate the admissible completions on small inventories, as Addendum 1 describes.
   - Hypothesis generates the cases, placing indeterminate roots before, between and after the others, with overlap and disjoint searches, multi-search roots, missing prefix and interior pages, delegates, scope and G-1 standings.
   - Assert that no definite verdict disagrees with any completion.
   - Report the count of permitted approximations.
   - Include Astra's three probes as literal cases with hand-written expectations: `unknown` for the overlap case, both scoped and unscoped, and `unknown` for the missing prefix. Keep their positive and negative controls.
   - Replace the restricted `test_properties` monotonicity claim with this test. Its arithmetic coverage may stay.
4. **Mutants:** paired mutants for:
   - dropping the earlier-indeterminate discount;
   - treating known-search roots as unknown, or the reverse, where that matters;
   - classifying a recoverable chain as invalid;
   - applying scope before the dependency.

   Controls: valid disjoint history and a provably invalid chain.
5. **Documentation:** update ACCOUNTING.md to describe the bounds and chain classes.

## Constraints
- **Coder:** GPT-6.1-Sol, branch gen2.
- **Before committing:**
  - the targeted tests;
  - the full composition module;
  - `--only` on every mutant family that targets an edited file;
  - the six gates.
- **Shared environment:** don't refresh the shared `.venv-gen2` during a mutant run.
- **Don't edit:** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **No:** provider calls, live gateway access, or recursive search of `/home/trevor/work`.
- **Evidence:** `~/work/research-loops-public/private/evidence/2c-3a-repair-2/`.
- **Commits:** the message ends with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`. Use `git commit <paths>`.
