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
| `searched_empty`      | lane dispatched successfully and returned 0 records |
| `not_searched`        | lane exists for this domain but was not dispatched (budget/refusal/policy) |
| `provider_unavailable`| dispatched; outage, timeout, quota or unreadable answer |
| `auth_failed`         | dispatched; the source rejected our credentials |
| `metadata_only`       | the record was found but the requested full text / file is not retrievable |

- Gateway → client: every `lanes[]` entry in a find/resolve/enrich answer carries
  `coverage` (one of the states above) next to its existing `source` and `count`;
  prose `facts` remain for humans and never become the machine channel.
- Client → chassis: when `RESEARCH_LOOP_RESEARCH_ACTIVITY` names a writable file, the
  stdio dispatcher appends one JSON line per non-`searched_ok`/`searched_empty` lane
  state and per failed tool call:
  `{"at": iso8601, "source": id, "request_type": t, "coverage": state, "query_or_identity": s}`.
- Chassis → queue: the iteration result record gains `research_failures` (the
  distinct `(source, coverage)` pairs from that file). The runner keeps
  `research_blockers` per item: a `provider_unavailable`/`auth_failed` entry adds the
  source; a later `searched_ok`/`searched_empty` for the same source clears it
  (historical failures are never permanent vetoes).
- Gate (one condition, used for BOTH saturation eligibility and automatic completion):
  an iteration that recorded a blocking coverage state and produced no qualifying
  semantic change does not advance the saturation streak and cannot be the completing
  pass. A completed topic stamps the coverage state it completed under
  (`completion_coverage`) so a later source-family addition can trigger a targeted
  refresh without invalidating the earlier research.
