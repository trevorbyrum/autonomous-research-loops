# Task 2b-repair-13b — engine: carry the page outcome; bound polling; deterministic supervisor test

**Sources:**
- Gate D #1 findings 3 and 4: `~/work/research-loops-public/private/reviews/gen2-gate-d-1-astra-review.md`, with the `pagination` and `poll_deadline` probes in `.../evidence/gate-d-1/`.
- Astra's supervisor-timing ruling in `gen2-2b-repair-12-astra-review-20261002.md`, with `.../evidence/astra-2b-repair-12/supervisor_timing_probe.py`.

Runs after 2b-repair-13a lands.

## Required
1. **Typed page outcome, carried end to end (Gate D #3).** Persist, per page observation, why pagination ended or continued:
   - provider-reported end (exhausted);
   - continuation available (with the cursor);
   - end unknown;
   - page or resource limit reached;
   - failed.

   The outcome must travel through `gateway_client` (`client.py`), `observe.py`, the router command and the store (`store/schema/03-evidence-and-decisions.sql`), using DDL, the boundary check and the commit protocol as for any other evidence field. Keep *this page was read completely* distinct from *the search population is exhausted*. An unknown end or a page/resource cap stays unknown/incomplete for coverage. Preserve replay identity, attempted-request identity and the partial records already observed. Coordinate the field shape with what 2c's accounting will need (see BUILD-STATE's 2c entry); don't build 2c.
2. **Absolute poll deadline (Gate D #4).** Use one monotonic deadline for the whole poll. Subtract request time, clamp each exchange's timeout to the remaining time, and bound sleeps. Keep refusal and timeout observations. Add a virtual-time test that reproduces Gate D's 3.3 s overrun on a 1 s deadline and shows it fixed.
3. **Deterministic supervisor test (`1C-sup-no-start-grace`).** Its killer races a 0.3 s shell delay against recovery. Replace the race with deterministic synchronization that establishes the intended recovery-before-identity ordering, plus a normal-start control. Show the mutant is killed under the controlled schedule that let it survive Astra's probe. A green rerun is not a fix.

## Constraints
- Branch gen2.
- Engine (`gen2/`) and its tooling only, plus the gateway-client contract fixtures if needed.
- Never touch the live gen-1 gateway.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-13b/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Finish with `make gen2-check` and `make gen2-gateway` unpiped, exit 0.
- Completion report: each root cause in one sentence; engine net lines (against the 15,000 trigger); a literally-true Remaining section.
