# Task 2b-repair-16 — engine: a failed re-resolution withdraws the endpoint; constructor-mutant control

**Source:** Astra's 2b-repair-15 review, `~/work/research-loops-public/private/reviews/gen2-2b-repair-15-astra-review-20261002.md`, with evidence in `private/evidence/astra-2b-repair-15/` (`engine_probes.py`, `checkout-engine.json`, `old-checkout-engine.json`, `constructor-control-*.json`). Read them in full.

**State:**
- **Gateway input contract:** ROOT-CAUSE, closed under trust model B. Don't touch `gateway/`.
- **Engine:** F1, F3 and F4 are closed. F2 (no name resolution at exchange time) is ROOT-CAUSE.
- **The DNS time residual is already ruled** (operator, 2026-10-02, option (a)): the client is constructed and `resolve()` called only inside supervised job children. 2e1 owns that wiring. Don't build anything for it here.

## Required
1. **R15-1 (HIGH): a known-stale endpoint is no longer used for connections.** Today `GatewayClient.resolve()` keeps the previous addresses when a re-lookup returns nothing or raises `gaierror`. It marks `endpoint_stale`, but `_exchange()` ignores the flag and connects to the old address anyway. In Astra's probe, an unrelated listener at that address received the bearer token and returned an answer recorded as `searched_empty/complete/0/exhausted`.
   - **Root fix:** after a connection failure or a failed resolution, the endpoint is unusable for exchanges until the owner's `resolve()` succeeds again. While it's unusable:
     - an exchange makes **no connection and sends no request**, so no token goes out;
     - the exchange gives `transport_failure` → `unknown/unobserved/null count/failed`.
   - Old addresses may be kept as diagnostic history only.
   - Keep resolution outside every exchange and poll deadline. The valid move to a new address (successful re-resolution to B) and the TLS-name controls must still pass.
   - Rewrite `test_a_lookup_that_finds_nothing_keeps_the_addresses_the_last_good_one_found` so it asserts that **no request reaches the stale listener** and the result is unobserved with a null count.
   - Reverse or remove the mutant that treats wiping the old addresses as a defect; add a mutant that keeps them in use, with a paired control.
   - Rebuild Astra's R15-1 probe as a regression. It should fail on `0d53bfc` and pass now.
2. **R15-2 (LOW): constructor-mutant control.** Pair `2B15-construction-does-not-look-the-name-up` with `test_an_ip_literal_is_never_resolved`, which Astra verified reaches the constructor's guard. Update both the maintained generator (`tools/gen2_mutation_controls.py`) and the JSON.

## Done means
- The R15-1 regression and the rewritten test pass.
- `make gen2-check` and `make gen2-gateway` exit 0 when run unpiped.
- `gateway/` and the oracle are unchanged.

## Constraints
- Branch gen2. Engine (`gen2/`), its tests and tooling only.
- No provider calls, no personal data.
- Never touch the live gen-1 gateway.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-16/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Completion report: the root cause in one sentence; net lines; a literally-true Remaining section.
