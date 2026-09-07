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
- Items without a `research_policy` field inject only `topic_id`: the gateway's
  personal-baseline default applies, which is also the pre-approval discovery posture.

## 2. Coverage state

One vocabulary for lane reporting and failure records — "searched and found nothing"
is never conflated with "not searched" or "unavailable":

| State                 | Meaning |
|-----------------------|---------|
| `searched_ok`         | lane dispatched and returned ≥ 1 record |
| `searched_empty`      | THIS successful query returned 0 records — never that the provider was down, refused, unreadable or skipped; and never proof the literature is silent beyond this query |
| `not_searched`        | lane exists but was not dispatched (commercial policy, budget, breaker) |
| `provider_unavailable`| outage, timeout, quota or an unreadable answer |
| `auth_failed`         | credentials rejected — or not configured at all (a keyless required tier is an auth problem, not an empty search) |
| `metadata_only`       | the record was found but the requested full text / file is not retrievable |
| `exhausted`           | a continuation: this lane already returned everything it has (its `next` sentinel skips it) |

- Gateway → client: every `lanes[]` entry in a find/resolve/enrich answer carries
  `coverage` (one of the states above) next to its existing `source` and `count`;
  prose `facts` remain for humans and never become the machine channel.
- Client → chassis: when `RESEARCH_LOOP_RESEARCH_ACTIVITY` names a writable file, the
  stdio dispatcher appends JSON lines
  `{"at": iso8601, "source": id, "request_type": t, "coverage": state, "query_or_identity": s}`
  — one per coverage-state TRANSITION, in order, keyed by the exact request
  (source + request type + query/identity). Recovery (fail → ok) is a transition and is
  never deduplicated away; capability-fact answers, transport failures and failed
  polled jobs all land here, not only lane lists.
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
