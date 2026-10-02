# Task 2b-repair-13d — engine: a whole-exchange deadline, the observation admission contract, the recorder-startup failure

**Source:** Astra's 13b review, `~/work/research-loops-public/private/reviews/gen2-2b-repair-13b-astra-review-20261002.md`, with evidence in `~/work/research-loops-public/private/evidence/astra-2b-repair-13b/`: `slow-exchange.json`, `late-done-handoff.json`, `bounded-exchange-demo.json`, `engine-probes.json`, `contract-edges.json`, `flake-probe.json`, `store-open-race.json`, `gate-c-test-audit.md`. Read them in full.

**Runs after 2b-repair-13c** (one coder at a time). Keep everything 13b got accepted: the `page_outcome`/`continuation` hand-off (ROOT-CAUSE for Gate D #3), the gated supervisor test, and inert `linkage_suggestions`. Engine (`gen2/`) and its tooling only.

## Family cause (engine side)
The engine's contract for turning retrieved evidence into durable facts is still incomplete. Representational validity stands in for the evidence an end needs. 13b added the missing information; this task makes sure nothing that lacks the evidence is admitted as an end.

## Required
1. **One deadline over the whole exchange (R13B-1).** An absolute deadline must bound every blocking step:
   - connect;
   - sending the request;
   - reading the status line and headers;
   - reading the body.

   A reply that trickles in, one chunk inside each socket timeout, must still stop at the deadline. **A terminal reply that completes after the deadline is a timeout observation, never a result.** Astra's reproduction persisted a late `done` as `searched_empty/complete/exhausted`.

   Choose a stdlib-only mechanism and justify it. Options:
   - a connection whose every blocking socket operation takes its timeout from the time remaining before the absolute deadline, so it can't be renewed per operation;
   - Astra's supervisor-owned I/O worker that is terminated and reaped at the deadline (lifecycle stays with the supervisor; `gateway_client` has no spawn capability).

   A thread left running after a timed wait is **not** acceptable. Tests:
   - a slow status line/headers;
   - a slow body;
   - a trickle;
   - a late terminal reply and a late non-terminal reply;
   - a timely positive control.

   Use real loopback sockets; a fake that already honours the timeout can't certify the transport.
2. **The observation admission contract (R13B-2).** Enforce at the router and the DDL alike what an admitted observation needs to assert an end:
   - **Capture acknowledgement.** `complete` and `exhausted` need a non-null `gateway_call_ref`. INVARIANTS (A1 locator under E-2/evidence accounting) already says an answer the gateway didn't durably capture is at most a partial lower bound, so the router must refuse what the client already never sends.
   - **Request discriminator.** A request type is required and must come from a closed set. The meaning of `end_unknown` is defined per request type: paged, end unknown, versus not a paged request. A non-paging request can never assert `exhausted`; Astra found non-find replies carrying `exhausted=true` produce it.
   - **Unobserved lanes.** An unobserved/no-count lane can't carry `page_outcome=exhausted`. Remove the client edge where a restatement with a malformed `next` produced it.
   - **One cursor domain, in the router and the DDL.** It must be the same in both, must refuse the `exhausted` sentinel as a cursor, and must apply the same rules to empty and negative values and to integers beyond the JSON bound.

   **Trust model, from the source of truth.** Pre-change-store refusal stays as it is. The design makes trusted station/gateway code the capture boundary:
   - flow architecture §S2, "the station/gateway captures retrieved candidate identities at retrieval time… the router persists these events";
   - BOUNDARIES' station supervisor: trusted code that must never trust *agent* self-report, checked by "state-integrity audit sampling";
   - flow §state integrity, "an independent agent re-derives sampled state entries from raw ledgers";
   - D-1, raw response retained at the trusted station/adapter boundary.

   So a well-formed command from trusted station code that *relabels* a captured outcome is detected by the state-integrity audit's re-derivation from the captured raw evidence, not by the router re-parsing the reply. **Write this trust model into INVARIANTS (E-2 and A1 locators) and `gen2/router/README` or the boundary docstring.** State exactly what the router enforces (coherence, the capture acknowledgement, the discriminator, the cursor domain) and what it does not (that a captured outcome is truthful, which is the audit's job). The next review judges whether this reading of the design is correct; don't present it as stronger than it is.
3. **Recorder-startup failure (R13B-3).**
   - In `test_a_report_recorded_after_a_newer_one_never_displaces_it` (and any sibling multi-process test with the same readiness pattern): use bounded readiness, retain the child's exit status and stderr on any handshake failure, and register cleanup before the handshake.
   - Then try to reproduce under stress: many iterations, parallel load, DELETE vs WAL journal modes. Find the cause.
   - If it's in `open_store`, fix it there at its root. If it's in the test, fix the test.
   - If it can't be reproduced after real instrumentation, say so plainly in Remaining, with the evidence. Don't claim a fix; that residual goes to the operator.
4. **Test claim (Gate C).** `test_a_poll_that_comes_back_after_the_deadline_still_ends_it` tests final-sleep arithmetic. Rename it accurately, and add the real after-deadline-reply test from item 1.

## Done means
- Astra's slow-exchange, late-done hand-off and contract-edge probes are rebuilt as regressions; they fail on `a5a2afb` and pass now.
- `make gen2-check` and `make gen2-gateway` exit 0 when run unpiped.
- No `gateway/` change.

## Constraints
- Branch gen2.
- No provider calls, no personal data.
- Never touch the live gen-1 gateway.
- Never run a migration against a real database.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-13d/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Completion report: each root cause in one sentence; the deadline mechanism and why it bounds every blocking step; the admission contract as enforced; the flake's diagnosis; engine net lines; a literally-true Remaining section.
