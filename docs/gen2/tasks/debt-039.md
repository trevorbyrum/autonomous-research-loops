# Task debt-039: make the gateway-client deadline tests independent of machine load

**Why.** DEBT-039 (`docs/gen2/DEBT-REGISTER.md`): `test_gateway_routes.DirectHttpOnly.test_a_redirect_is_never_followed_whatever_the_status_and_wherever_it_points` gives `GatewayClient` a 0.2-second wall-clock deadline. Under load it misses the deadline, and the mutation harness's child-tree baseline fails.
- It has now cost **two full landing cycles**: 2026-10-14 at `0cfb573` and 2026-10-19 at `04c7af7`.
- A gate that can fail on machine load hides real signal.

**Required (ROOT-CAUSE, as the register says):**
- Make every deadline-dependent assertion in the gateway-client and route tests deterministic under scheduler load:
  - inject the clock, or otherwise make the deadline logic testable without wall-clock races;
  - use an established approach (e.g. a fake monotonic clock passed to the client, or `time-machine`-style control) consistent with the charter's refactor evidence standard.
- **Do not just raise the timeout.**
- **Audit** the other deadline-dependent tests in `gen2/tests/` and gateway tests, and convert those with the same race.
- **Production behaviour is unchanged:** real deadlines are still enforced with the real clock by default. If a production seam is needed (e.g. an injectable clock parameter with a real default), keep it minimal and show that the default path is byte-for-byte the same behaviour.
- **Removal evidence:**
  - Run the affected tests under deliberate load, e.g. alongside a CPU stress (`stress-ng` if available, or parallel heavy test runs), many times, all green.
  - Run a loaded mutation baseline.
  - Paired mutants show the deadline assertions still kill a broken deadline: say, a client that ignores the deadline, or one that follows redirects.

**Constraints:**
- As in task 2d's constraints: full `gen2-test`, trigger-order, composition, affected `--only` families, `make gen2-gateway`, and the static gates.
- `service.py` is wiring only.
- Never push.
- Don't edit BUILD-STATE, REVIEW-LOG or DEBT-REGISTER. The orchestrator closes DEBT-039 after acceptance.
- Commits end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
- **Evidence:** `~/work/research-loops-public/private/evidence/debt-039/`, with a COMPLETION.md and, if interrupted, a PROGRESS.md.
