# 2d-4c-p4b2c2-closure: close C1 by construction (operator ruling 2026-10-22)

**Subject:** 2d-4c part 4b2c2: the guard and history viewer (`5b01b6e`), with test repairs `d954236` and `fca05ef`.

**Astra round 3** (`private/reviews/gen2-2d-4c-p4b2c2-r3-astra-review-20261022.md`):
- **A PASS, B PASS, maintainability PASS. C BLOCK.**
- C1 is open only because native SQLite APIs can change a row and restore it between the test's observation points without being seen: `Connection.blobopen(...).write` and `Connection.backup` (plus the same family).
- Production gen2 code calls none of them; the orchestrator checked with grep.
- The round cap was reached and the slice was escalated.

## Operator ruling 2026-10-22 (Trevor): ban the APIs and narrow the claim
1. **Make the property hold by construction.**
   - Add a cheap static gate to the existing `make gen2-check` static set. It fails the build if gen-2 production code (the engine surface INVARIANTS B-3 lists, excluding `gen2/tests/`) uses any SQLite native write or replace API: `blobopen`, `backup`, `deserialize`, and extension loading (`enable_load_extension`, `load_extension`).
   - The gate must catch attribute access and calls whatever the receiver is named, plus `getattr` with a literal name. Test code is exempt.
2. **Narrow the test's stated claim to match.**
   - `test_retained_support.py`'s no-application-write guarantee, and its DOSSIER description, now state their scope exactly. The test covers application-row changes made through SQL statements on any connection, and final and intermediate SQL-boundary state.
   - Native write and replace APIs are excluded **because the static gate forbids them in production**. Cite the gate.
   - **Don't weaken** anything the test already checks.

## Acceptance contract (agreed before coding)
- **Property:** gen-2 production code can't modify application rows through SQLite native write or replace APIs, and the no-write test's claim matches what it observes.
- **The gate must:**
  - fail on each banned API in production code, whether called directly, accessed as an attribute on any receiver name, or reached via `getattr(..., "blobopen")`;
  - pass on current production;
  - ignore `gen2/tests/`;
  - pass on unrelated names (for example a local variable called `backup`).
- **Required regressions** for the gate, each with an assertion-based expected outcome:
  - one fixture per banned API;
  - the `getattr` form;
  - an aliased receiver;
  - a test-path exemption;
  - an unrelated-name negative.
- **The test's existing 73 fixtures and all 17 methods stay unchanged.** Only the claim text and the DOSSIER description change.
- **Limits:** dynamic code generation (`eval`/`exec` of strings) is out of scope. Record it as a stated limit, unless an existing gate already forbids it, in which case cite that gate.
- **Size:** about 150 hand-written lines.

## Process (charter 2026-10-22)
- **The coder runs targeted checks only:** the new gate's tests, `test_retained_support`, the static gates, and the affected mutant families if the gate tool has any.
- **The full run is done by the independent verifier** per `docs/gen2/VERIFIER.md`.
- Astra reviews against this contract.

## Constraints
- **Production code is unchanged except the new static gate.**
- Look up AGENTS.md only inside the repository.
- No provider calls. Never touch gen-1 runtime state or `127.0.0.1:8765`.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. Don't push or merge.
- **Stage explicit paths only.**
- **Evidence:** `~/work/research-loops-public/private/evidence/2d-4c-p4b2c2-closure/`, with a short COMPLETION.md.
- **Commits:** end the message with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
