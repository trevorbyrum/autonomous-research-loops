# 2d-5-repair-1: account for the new capability row in every consumer (Astra Gate C, round 1)

**Subject:** 2d slice 5 (`d6376ad`, PR #4, branch `task/2d-5`).

**Astra round 1** (`private/reviews/gen2-2d-5-astra-review-20261022.md`): **A PASS, B PASS, C BLOCK.** The implementation is ROOT-CAUSE: the existing writer records `tier-0` `unknown`, "tier-0 disabled", on both configured-activation routes. Opening and history stay read-only.

**Verifier** (Sonnet `b02bd6e5`, clean clone of `d6376ad`):
- `gen2-check` **exit 2**: 4,403 tests, **1 failure**.
- `gen2-gateway` exit 0.

## B1 (blocking): an overlooked capability-table consumer
**Where:** `gen2/tests/test_router_ops.py:647`, `AckDeliveryTest.test_failures_raise_capability_facts_on_transitions`.
- The test expects `capability_facts` to hold only the connector fact. The new tier-0 row comes first, so it fails before it reaches its transition checks.

**Required (ROOT-CAUSE, family level):**
- Find **every** test or consumer that asserts the exact contents, count or order of capability facts or status capability lists after a configured activation or restoration. Fix each one so it accounts for the tier-0 row by capability identity, for example by selecting the capability under test or asserting the full expected set.
  - Don't special-case only the one failing fixture.
  - Don't weaken assertions.
- **Run the whole affected family:** every test module that reads `capability_facts` or status `capability_facts`. Use `grep` to find them, and list them in COMPLETION.md.

## NB1 (fold in): stale descriptions
`gen2/router/registries.py:108–110` and the restoration-test docstring in `test_router_registries.py` still say restoration without an active bundle writes nothing. Update both to describe the first disabled-fact recording versus idempotent restoration.

## Process
- **The PR is still open**, so commit the repair on the **same branch `task/2d-5`** and push. PR #4 updates itself and keeps auto-merge.
- **Checks:** targeted only, but including the whole capability-fact family above. The independent verifier then runs the full set.
- **Rules:** no production change unless a probe shows a real defect; if one does, stop and report. Look up AGENTS.md only inside the repository. No provider calls. Never touch gen-1 or `127.0.0.1:8765`. Don't edit BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. Stage explicit paths only.
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-5-repair-1/`, with a short COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
