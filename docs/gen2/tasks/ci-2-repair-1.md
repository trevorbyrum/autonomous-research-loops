# ci-2-repair-1: honest CI outcome reporting and runner regression strength (Astra round 1)

**Subject:** branch `sol/ci-2` at `51f8b01`, worktree `/home/trevor/work/arl-ci-2`. Astra's round-1 report is `private/reviews/gen2-ci-2-astra-review-20261018.md`.
- **Gate A BLOCK (B1, B2). Gate C BLOCK (B3).**
- These pass:
  - the same-pin identity comparison at `3fc5acf`;
  - partition conservation;
  - scope, with no production, workflow or infrastructure change.
- **Classification:** the quota-based worker fix is ROOT-CAUSE. The partial default CI execution is a **MITIGATION** until std v1.2 (task ci-cd-2) and image `:2`; it is pending operator acceptance.

## B1: a skipped subtest fabricates a parent failure
**Where:** `tools/gen2_ci_evidence.py:97/115`.
- **Defect:** `addSkip()` records the subtest, but never marks the parent as recorded. `stopTest()` then falls back to `fail`, while unittest itself reports success. The result is a spurious JUnit `<failure>` and a comparator rejection.
- **Required:**
  - distinguish a parent with skipped subtests from a really failed or erroring parent;
  - keep every skip identity and its exact reason;
  - preserve failure, error and repeated-occurrence behaviour;
  - add durable tests that check the unittest verdict, the recorded parent/subtest outcomes, JUnit and comparison together.

## B2: a successful default build doesn't say it's partial
**Required:**
- The executed build prominently prints **PARTIAL ACCEPTANCE — NOT FULL ACCEPTANCE**, naming:
  - what ran: T0, complete trigger-order, units 1/8;
  - what was omitted: unit partitions 2–8/8, all mutation work, all gateway modes.
- Carry that scope into structured evidence and into a Jenkins-visible result/test summary, through the supported consumer interface, with source, mode and shard identity.
- **If the platform can't set a status description,** write that up as an explicit platform request (feeds ci-cd-2).
- **Fold in NB1:** add SHA/tree and shard properties to the JUnit, so detached XML stays interpretable.

## B3: tests miss skips and lost repeated identities under real sharding
**Required:**
- A nested, multiple-class fixture with repeated identities.
- Partition it at several nontrivial totals and compare the union **as a multiset**.
- Verify per-shard order and class assignment.
- **Run the resulting suites,** so a failing repeated occurrence stays visible.
- The B1 skip regressions.
- Durable comparison tests for changed or removed skips and their reasons.
- **The killer:** Astra's counterfactual, dedup-by-id when `total > 1` (it drops 4,237 → 4,212 occurrences), must fail by assertion.
- **Fold in NB2:** narrow the unconditional fixture-preservation wording, or add a fixture-sensitive regression.

## Constraints
- Same as `docs/gen2/tasks/ci-2.md` and its amendment:
  - work on `sol/ci-2` in `/home/trevor/work/arl-ci-2`;
  - push only `sol/ci-2`;
  - no weakening of any test, mutant, control or gate;
  - no infrastructure or ci-cd change;
  - don't touch `.github/workflows`;
  - don't edit BUILD-STATE, REVIEW-LOG or DEBT-REGISTER;
  - limit any AGENTS.md lookup to the repository.
- **After the repair, push and get a green Jenkins build** whose console and evidence show the PARTIAL banner and scope.
- **Re-run the identity comparison** for the CI-executed modes at the new head.
- **Evidence:** `~/work/research-loops-public/private/evidence/ci-2-repair-1/`, with a COMPLETION.md.
