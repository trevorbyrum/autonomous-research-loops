# Task 2b-repair-17 — engine: one endpoint-authority owner; direct HTTP/HTTPS only (Gate D #3 finish line)

**Source:** Gate D #3, `~/work/research-loops-public/private/reviews/gen2-gate-d-3-astra-review.md`. Use its §3 route inventory and its §5 checklist items 0–7, plus its evidence in `private/evidence/gate-d-3/`. Also read Astra's 2b-repair-16 review (`gen2-2b-repair-16-astra-review-20261002.md`, R16-1/R16-2) with its probes (`private/evidence/astra-2b-repair-16/`). Read them all in full.

**This is the finite finish line for the engine side of 2b.** The gateway side is closed. Keep everything already accepted:
- the page outcome hand-off;
- admission;
- whole-exchange deadlines;
- late-reply refusal;
- readiness;
- sequential withdrawal;
- no exchange-time DNS.

## Operator rulings in force
- **Trust model B.**
- **The frozen format policy.**
- **DNS, option (a):** the client is constructed and `resolve()` called only inside supervised job children. 2e1 owns this.
- **NEW, 2026-10-03, client model:** a **`GatewayClient` instance is serial**. It runs one public operation (`search`, including all its pages and polls; `grant`; `resolve`) at a time. An overlapping or re-entrant call on the **same instance** is refused locally, with a documented error, before any network I/O.

  **Separate instances must run fully concurrently.** Many stations and jobs, each with its own client, talk to the gateway in parallel. The operator's condition: *"as long as concurrent connections can run"*. **Prove it with a test:** N clients against one loopback gateway have overlapping requests in flight (the server sees them overlap), and nothing serializes them across instances. That means no lock shared between instances, no global opener, and no module-level state.
- **Ambient proxies are ignored.** No ruling is needed: DEPLOYMENT-CONTRACT §1 has the engine reaching its dedicated gateway directly.

## Required (Gate D #3 §5)
- **0. One client contract.** In the `gen2/gateway_client` docs and INVARIANTS (E-2/RG-4 area), state:
  - the guarantee: a durable observation states only what a request to the currently authorized endpoint actually returned, within the deadline;
  - the supported endpoint forms: an `http`/`https` URL whose host is a name or an IP literal; other schemes are refused before I/O;
  - the serial-per-instance ownership and concurrency across instances;
  - the withdrawal transitions;
  - response attribution.

  Keep B and the DNS rule.
- **1. One authority owner.** Whether the client may do I/O is derived from a single endpoint state. Cached addresses and diagnostic history can't authorize anything independently. The owner covers:
  - `resolve`, `grant`, whole searches (pages and polls), and every address attempt;
  - the full address iteration and the connect/send lifetime, not just the mapping lookup.

  Tests:
  - the R15 sequential withdrawal and NXDOMAIN reproductions;
  - both R16 cases, using Astra's probes;
  - overlap on the same instance before connect, after connect and before send, and during resolution: each is refused with no bytes sent by the refused operation;
  - the original-listener and move-to-B controls.

  Bytes already sent can't be revoked; say so.
- **2. Close the routing surface.** Direct HTTP/HTTPS only:
  - no `ProxyHandler`, so ambient proxy variables, their case variants, `no_proxy` and CGI `REQUEST_METHOD` have no effect;
  - redirects refused, including same-origin ones;
  - no challenge-driven auth or cookie replay;
  - no global opener;
  - FTP/file/data/unknown handlers removed or provably unreachable.

  Tests:
  - listeners that assert the exact destination, the request count and whether the synthetic token arrived;
  - HTTP and HTTPS proxy cases, case and bypass variants, CGI, and an FTP-valued proxy (with no DNS at exchange time);
  - **positive direct controls still work with hostile-looking proxy settings in the environment.**
- **3. Bounded lifetimes.** No reusable connection outlives its authority; keep one connection per exchange, as now. No background resolver, thread or process. Overlap is refused, not waited on, so no ownership wait can escape a bound.

  Tests:
  - multi-address failover and failure of every address;
  - before-send withdrawal schedules;
  - direct IP-literal controls;
  - a timeout followed by a timely recovery (a timeout need not withdraw);
  - no surviving test sockets or threads.
- **4. Keep the timing contracts:**
  - the whole-exchange budget;
  - the remaining poll budget on every poll and sleep;
  - late terminal replies refused;
  - DNS only at explicit construction or `resolve`.

  Document the three scopes (the exchange deadline, the job's poll deadline, the supervisor's whole-job deadline) without inventing a fourth.
- **5. Keep the typed hand-off and the gateway contract:**
  - all five page outcomes;
  - partial and lower-bound results;
  - invocation/attempt echo;
  - missing capture;
  - non-paging request rules;
  - router and direct-DDL rejection;
  - identity-only merging;
  - readiness;
  - the gateway oracle unedited.
- **6. Validation.**
  - Run `make gen2-check` and `make gen2-gateway` unpiped.
  - Add mutants with paired valid controls:
    - remove ownership (allow overlap);
    - restore proxy dispatch;
    - re-add a non-HTTP handler;
    - share state across instances.

    The last one is killed by the concurrency test.
  - Give per-test assertions and limits.
- **7. A family account against the §3 inventory.** Say how every route is covered or removed. Record the remaining phase owners accurately: 2e1 for construction sites and runner isolation, 2e2 for the retrieval audit.

## Constraints
- Branch gen2. Engine (`gen2/`), its tests and tooling only. `gateway/` and the oracle stay unchanged.
- No provider calls, no personal data.
- Never touch the live gen-1 gateway. Don't search `/home/trevor/work` recursively.
- Evidence goes to `~/work/research-loops-public/private/evidence/2b-repair-17/`.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Completion report:
  - the root cause in one sentence;
  - the route-by-route coverage;
  - the concurrency proof;
  - net lines;
  - a literally-true Remaining section.

  Any concrete defect left unfixed is a MITIGATION and needs the operator's acceptance.
