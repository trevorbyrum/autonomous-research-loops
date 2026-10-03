# Task 2q-a-repair — make the ratchet hold against ordinary source changes

**Source:** Astra's 2q-a review, `~/work/research-loops-public/private/reviews/gen2-2q-a-astra-review-20261003.md` (F1–F7). Evidence is in `private/evidence/astra-2q-a/`: `probes.json`, `real-probes/`, `offender-probe.json`, `threshold-operating-points.json`, and the snapshot logs. Read them all in full.

**Accepted at 2q-a:** the historical reproduction (27/27 tables byte-identical), the phase-close mechanism, the 13 register entries, and the locator reconciliation. Keep them. No production change.

## Required (one root fix each)
1. **F1 (HIGH): the collaboration inventory must survive ordinary inheritance syntax.**
   - Define the supported import and class surface, then resolve it. That covers:
     - bare names;
     - aliased imports;
     - fully qualified bases (`gen2.router.lifecycle.Lifecycle`);
     - re-exports;
     - intermediate bases in the same file.
   - Attribute `self.` calls using Python's **C3** MRO, not depth-first traversal.
   - Count each overlapping family's call site **once**.
   - **An unresolved project base is a reported failure, not "no collaboration".** It fails the check unless it is explicitly classified.
   - Test against independent expectations:
     - Astra's qualified-Router patch must keep its 132 sites and 19 pairs;
     - a diamond (`D(B, C)`, `B(A)`, `C(A)`);
     - a re-export;
     - aliases;
     - same-file intermediates.
   - Don't hardcode the Router's names.
2. **F2 (HIGH): a baselined offender can't escape by crossing a threshold.**
   - Keep current values for every baselined function, in **both** dimensions, until both have been compared with the baseline.
   - Apply thresholds separately, only to decide new offenders.
   - Remove a baselined entry only when neither dimension grew.
   - Test:
     - Astra's probe (CC 21/cog 0 → CC 8/cog 28) must fail;
     - opposite-direction changes across both thresholds;
     - a positive control where both scores improve.
3. **F3 (MEDIUM): two missing register entries.**
   - **The importer's inventory of unexamined files** (Phase 4). It must exist **before** a dry-run report is used as completeness or reconciliation evidence for migration planning; a phase-close deadline alone is too late. Cite the store README and the 0b review chain.
   - **The Phase 3 usage estimator** (operator request, 2026-09-29). Cover its uncertainty, and the distinction between account-wide subscription readings and per-run attribution.

   Fix the register's stated inclusion rule to match.
4. **F4 (MEDIUM): a locator is recognised independently of whether it resolves.**
   - Define an explicit file and symbol grammar. Convert the current dotted citations to it.
   - Give historical references and ordinary code expressions an explicit marker.
   - Add negative tests:
     - the module or class is deleted while the citation stays;
     - a full module path `gen2...` is cited;
     - an unknown prefix.
5. **F5 (MEDIUM): ratchet the charter's dependency measures.**
   - The charter lists per-module fan-in/fan-out and instability as ratcheted, so enforce them. There is no operator amendment, so reporting-only is not an option.
   - Define the regression policy:
     - a new import edge;
     - a per-file fan-out increase;
     - a per-file fan-in increase on a stable module;
     - reach gained transitively.
   - Changes hidden by transitive reach or denominator growth must count: compare absolute reachable pairs as well as the normalised cost.
   - Don't treat every instability change as bad; state which direction regresses and why (Martin's stable-dependencies principle).
   - Test:
     - Astra's real-tree probe (`router/amendments.py` → `core/instants.py`, edges 60→61) must fail;
     - the denominator probe;
     - positive controls.
6. **F6 (LOW):** correct the threshold rationale. `fake_executor.run` is CC 19 with cognitive 40, so "every cognitive offender ≥40 is a CC offender" is false. Don't loosen the thresholds.
7. **F7 (LOW):**
   - Make `test_the_helper_runs_children_from_the_named_tree` respect, or deliberately clear and restore, an incoming `GEN2_CHILD_ROOT`.
   - Correct the 2q-a evidence: one test depended on the environment and two were intentional skips.

## Done means
- Every Astra probe above is rebuilt as a regression. Each must fail on `1e8dc9f` and pass now.
- Add mutants with paired controls for each new rule.
- Rebaseline only if the stricter rules require new baseline fields, and show the diff.
- `make gen2-check` and `make gen2-gateway` exit 0, run unpiped.
- No production change.

## Constraints
- Branch gen2: tools, tests, docs and the register only.
- No provider calls.
- Never touch the live gen-1 gateway or 127.0.0.1:8765.
- Don't search `/home/trevor/work` recursively.
- Evidence goes to `~/work/research-loops-public/private/evidence/2q-a-repair/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- The completion report gives each root cause in one sentence, net lines, and a literally-true Remaining section.
