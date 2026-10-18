# ci-cd-2-repair-1: std v1.2 interlock freshness and integration coverage (Astra round 1)

**Subject:** ci-cd stacked draft PRs.
- #13 (`0276dcc`): Gates A and C PASS as the scoped first layer.
- #14 (`4908993`): S1 found there, fixed in #15.
- #15 (`34db1c9`): **Gates A and C BLOCK on B1 and B2.**

Astra's report: `private/reviews/gen2-ci-cd-2-astra-review-20261018.md`.
- **Scalar backward compatibility PASS.** Ten normalized lifecycle/evidence snapshots are identical to v1.1 for every head.
- **Both repairs are ROOT-CAUSE.**

## B1 (HIGH): target freshness isn't revalidated after the evidence lookup
**Where:** `integrationObservation` (`lib/vars/standardPipeline.groovy` L291–307) and the final call from `runModes`.
- **Defect:** target HEAD is fetched once, then the queue and builds are enumerated and controller evidence is read. Nothing is fetched again before success is accepted.
- **Reproduction:** move the target inside `getBuilds` during the final observation. The PR finishes **SUCCESS** while recording the old `target_sha`.

**Required:**
- Bracket the supporting-evidence lookup with fresh target observations.
- Fail closed when the target has changed or is unavailable.
- Revalidate the relevant queue and latest-build state before accepting.
- Add an adversarial final-observation test: the target moves *within* the last observation.
- Document that GitHub landing freshness remains an operator-enforced requirement.

## B2 (HIGH): a mode label is treated as proof the integration workload ran
**Where:** `passingIntegration` (L318–325).
- **Defect:** it accepts `integration` **or** `nightly` records, requiring only that the executions present passed.
- **Reproduction:** with `integration: [full-one, full-two]` and `nightly: [smoke]`, a genuine nightly `smoke` record lets the PR pass. Neither integration command ran.

**Required:**
- Either qualify only completed **integration-mode** results, or define and enforce a trusted coverage contract before nightly evidence may substitute. Matching names is insufficient: event fallback can select different commands or images under the same names.
- **Never take the candidate PR's editable config as the authority for target coverage.**
- **Refusal tests for:**
  - a smaller nightly list;
  - omitted-nightly fallback;
  - same name with different effective work.
- **Plus a positive equivalent-nightly control,** if substitution is kept.

## Also
- **Preserve #15's S1 fix:** per-execution JUnit non-empty and the original failure.
- **N3 (docs):** the library is pinned by tag (`v1.0.0`, PR #11, overrides disabled). **A merge alone doesn't activate the stack**; a release tag and a JCasC repoint are operator steps. Make the PR text and the post-merge plan say so.
- **N2:** provide the consumer-aware release/rollback qualification checklist Astra describes. It covers:
  - scalar consumers and the durable forwarder;
  - failure, abort and publication paths;
  - queued pushes and timer removal;
  - the repaired race and coverage cases.

## Constraints
- As in `docs/gen2/tasks/ci-cd-2.md`.
- Dedicated clone `/home/trevor/work/ci-cd-gen2` only.
- Update the existing stacked branches and PRs. Don't merge them.
- No Jenkins, cir/cim or settings changes. No GitHub Actions.
- **Evidence:** `~/work/research-loops-public/private/evidence/ci-cd-2-repair-1/`, with a COMPLETION.md giving the new exact heads.
