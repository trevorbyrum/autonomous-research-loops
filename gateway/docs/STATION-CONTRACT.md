# Station contract — topic policy and research coverage across the gateway/chassis seam

Phase 8·0 (plan: research-loops `private/phase8-plan-draft.md` v3). One page, two
definitions. The gateway track (8a/8b) and the chassis track (8c/8d) both implement
against this file; a change here is a change to both.

## 1. Topic policy fields

| Field             | Type | Owner (single writer)             | Enforcement |
|-------------------|------|-----------------------------------|-------------|
| `topic_id`        | str  | queue item identity (`items[].id`) | injected; conflicting argument rejected |
| `commercial`      | bool | queue item `research_policy`       | injected; conflicting argument rejected |
| `accept_per_item` | bool | queue item `research_policy`       | injected; conflicting argument rejected |
| `domain`          | str  | queue item `research_policy`       | injected when absent; agent MAY override (routing hint, not policy) |

- The queue item is the only writer: policy is operator-controlled execution state.
  `SEMANTIC-STATE.json` and everything else agent-writable is never an enforcement
  source.
- Flow: queue item → runner child environment (`RESEARCH_TOPIC_ID`,
  `RESEARCH_TOPIC_COMMERCIAL`, `RESEARCH_TOPIC_ACCEPT_PER_ITEM`,
  `RESEARCH_TOPIC_DOMAIN`; booleans as `"0"`/`"1"`) → station MCP launcher (passes its
  environment through) → the stdio dispatcher (`research_gateway.clients.mcp_stdio`),
  which applies the enforcement column above to every `tools/call`, batch members
  included.
- Rejection is in-band: the dispatcher returns a tool error naming the bound field —
  an agent under a commercial-bound topic that passes `commercial: false` gets
  `policy-bound: commercial is set by the topic, not the agent`, never a silent
  override in either direction.
- Absent environment = unbound session (operator CLI, ad-hoc use): the tools behave
  exactly as before this contract.
- **Server-side enforcement (task 2b).** The dispatcher's injection is a convenience, not
  the boundary: an agent holding a client token could call the HTTP API directly. A
  station is therefore given a GRANT, not a client token: the grantor mints it for one
  invocation of one topic (`POST /v1/grants`, docs/OPERATIONS.md), carrying `topic_id`,
  `commercial`, `accept_per_item`, the advisory `domain` and the invocation id. The server
  applies the enforcement column above to every request under that grant on every door
  (`/v1` sync and async, the MCP endpoint's tool calls, batch entries and downloads, job
  polls): bound fields injected, a conflicting value refused (403 / an in-band tool error
  naming the field), jobs visible only to the same topic under the posture in force, and
  requests carrying the grant's invocation (another one named is refused).
- Items without a `research_policy` field inject only `topic_id`: the gateway's
  personal-baseline default applies, which is also the pre-approval discovery posture.

## 2. Coverage state

One vocabulary for lane reporting and failure records — "searched and found nothing"
is never conflated with "not searched" or "unavailable":

| State                 | Meaning |
|-----------------------|---------|
| `searched_ok`         | lane dispatched and returned ≥ 1 record |
| `searched_empty`      | THIS successful query returned 0 records — never that the provider was down, refused, unreadable or skipped; and never proof the literature is silent beyond this query |
| `not_searched`        | lane exists but the OPERATOR'S POLICY excluded it (commercial verdict) — never a capacity refusal |
| `provider_unavailable`| outage, timeout, quota, an unreadable answer, or a budget/breaker refusal — required research that COULD NOT run |
| `auth_failed`         | credentials rejected — or not configured at all (a keyless required tier is an auth problem, not an empty search) |
| `metadata_only`       | the record was found but the requested full text / file is not retrievable |
| `exhausted`           | a continuation: this lane already returned everything it has (its `next` sentinel skips it) |

- Gateway → client: every `lanes[]` entry in a find/resolve/enrich answer carries
  `coverage` (one of the states above) next to its existing `source`;
  prose `facts` remain for humans and never become the machine channel. Each entry
  also says what was OBSERVED (task 2b; INVARIANTS H-5, RG-4, RG-U):
  - `completeness`: `complete` (the answer was read whole), `partial` (it was read, but
    some of it was unreadable: `count` is then a LOWER BOUND, never the total) or
    `unobserved` (no result set was read: every degraded state, `not_searched`,
    `exhausted`);
  - `count` exists only for an observed result set — a lane that could not run, or
    whose answer was unreadable, has no count, never a zero — and `retrieved` lists the
    identities it counts, in the lane's own rank order, before any merge;
  - `error_class` names why a lane is degraded or partial, in the engine store's
    vocabulary (`payload_invalid`, `timeout`, `rate_limited`, `breaker_open`,
    `budget_refused`, `provider_outage`, `credentials_rejected`,
    `credentials_not_configured`, `secrets_backend_failing`, `transport_failure`);
  - find lanes echo the `cursor` they were asked with, so a failed continuation page
    is retried from where it failed; a failed page gets no `next` and is never
    `exhausted`.
  An unreadable successful answer (unparseable, empty, or without the container its
  results live in) and a search endpoint's 404 are `provider_unavailable` with
  `payload_invalid` / `provider_outage` — never `searched_empty`. An answer with any
  degraded or partial lane is never served again from the search cache.
- Client → chassis: when `RESEARCH_LOOP_RESEARCH_ACTIVITY` names a writable file, the
  stdio dispatcher appends JSON lines
  `{"at": iso8601, "source": id, "request_type": t, "coverage": state, "query_or_identity": s,
  "request_identity": sha256}` — one per observation, in order, keyed by the exact request.
  The key is the COMPLETE effective request (task 2b; H-5): a request that sets nothing
  beyond its query/identity/target keeps that bare text; any other field the gateway acts
  on (kind, cursor, filters, limit, posture, a catalogue browse) makes it a JSON key, so two
  different requests never share one. Recovery (fail → ok) is a transition and is
  never deduplicated away; capability-fact answers, transport failures and failed
  polled jobs all land here, not only lane lists.
- The `gateway` source (lines marked `"scope": "gateway"`) is not a lane: it records the
  gateway transport for the request. `provider_unavailable` there means the gateway itself
  did not answer; `searched_ok` there means ONLY that it answered this request — never that
  any lane searched or found anything (lane lines carry that) — and it is not written for an
  answer still pending (`queued`/`running`). A line with `coverage: unknown` and
  `request_type: telemetry` announces activity lines that could not be written (their
  count and why): lost telemetry is explicit, never silent, and the tool result that lost
  them carries `activity_capture: {"captured": false, "loss": ...}`.
- Chassis → queue: the result record carries `research_failures` (requests whose FINAL
  state is degraded, each with its key), `research_ok` (keys whose final state
  cleared), and `research_coverage` (each source's last state — accumulated on the item
  for the completion stamp). The runner keeps `research_blockers` per item, KEYED BY
  REQUEST: a `provider_unavailable`/`auth_failed` final state adds the request; only
  the SAME request succeeding clears it — a success on an unrelated query never does.
  Historical failures still never become permanent vetoes: the operator releases a
  blocker explicitly with `research-loops resolve-research <id> --reason ...` (a
  recorded evidence decision). An ordinary pause/resume never touches blockers.
- Gate (one condition, used for BOTH saturation eligibility and every automatic
  completion branch): an iteration that recorded a blocking coverage state and
  produced no qualifying semantic change does not advance the saturation streak and
  cannot be the completing pass; reaching the streak limit with unresolved blockers
  HOLDS completion. A completed topic stamps the accumulated coverage map and policy
  it completed under (`completion_coverage`) so a later source-family addition can
  trigger a targeted refresh without invalidating the earlier research.
- Station downloads are TEMPORARY: the chassis provides a per-iteration directory
  (`RESEARCH_LOOP_DOWNLOAD_DIR`) and removes it on every exit path; the agent copies
  what it keeps into the topic's own files during the iteration. Names carry the
  file/revision identity and are created exclusively — never overwritten.

## 3. Discoverability (D-31)

The surface teaches; an agent never has to guess a source's shape:

- `research_sources` is the registry projected for agents — capabilities, domains,
  commercial verdicts, and each statistical source's EXACT declared data contract
  (adapter-owned `DATA_PARAMS`, pinned by tests). Public-safe fields only.
- `research_data` validates against the declared contract BEFORE any budget is spent;
  a bad call returns the contract and a working example instead of an upstream error.
- `research_files` listings carry a ready-made `download_request` per file — the
  arguments pass straight to `research_download`.
- Under a bound topic, the operator-owned policy fields are enforced but not
  advertised in tool schemas.

## 4. Correlation and observation (task 2b; INVARIANTS H-1, H-5)

- The caller's invocation and attempt travel in headers on BOTH front doors (`/v1/*` and
  `POST /mcp`): `X-Research-Invocation` (1–128 of `A-Za-z0-9._:-`) and
  `X-Research-Attempt` (a positive integer: the caller's attempt at this exact request —
  1, then one more for each retry). They travel together; a malformed or half-given pair
  is refused with 400, never dropped. They never enter the payload, cache keys or the job
  dedup hash. The stdio client sends them when `RESEARCH_INVOCATION_ID` is set, numbering
  each repeat of the same effective request as the next attempt.
- Every call row (`gateway.calls`: lane dispatches, redirect hops, cache hits, local-index
  lookups, request and coalesce rows) carries `invocation_id`, `attempt` and
  `request_identity`; a queued job keeps its CREATOR's. The schema's trigger refuses any
  later change to them (immutable once written).
- Every answer names its `effective_request` and `request_identity`, and carries the
  caller's own `observation`: `invocation_id`, `attempt`, `request_identity`, `served`
  (`dispatched`, `coalesced` onto another caller's in-flight job — then `dispatched_by`
  names that caller —, `cache`, `queued`, `rejected`), `job_id`, and the durable-capture
  acknowledgement: `captured` with the caller's own request row `call_ref`, or
  `capture_loss` saying why it was not written (no database; a failed write). The
  observation is added per caller at the front door, never inside cached or stored
  content, so shared content keeps the dispatcher's identity. A raw-bytes download
  carries it in the `X-Research-Observation` header.
