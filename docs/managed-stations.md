# Managed stations: operator interface

Managed mode is explicitly initialized at `state/control.sqlite3`. Configuration,
queue, and work ledger are separate logical records in one transactional database.
Legacy `queue.json`, `stations.json`, per-topic models, and per-topic intervals do
not override it. Do not edit the database or those legacy files to operate managed
stations. See [deployment and recovery](managed-deployment.md) before cutover.

## Fields and ownership

| Record | Operator input | Controller-owned output |
|---|---|---|
| Station configuration | active count, five station profiles/intervals, shared checkpoint policy | configuration revision and effective profiles |
| Profile registry | stable profile ID, adapter, model, executable, argv | validated registry entry |
| Queue | full ordered ID list with expected queue revision, pause/resume | stable IDs, admission/eligibility, current and desired assignments |
| Work ledger | standardized decisions, failed-checkpoint retry, explicit allowance reset | completed research count, next ordinal, trigger/episode history, budgets, proposals, capabilities |
| Intake | brief, reviewed discovery result, standardized decision | draft revision/hash, discovery task, publication intent, approved queue registration |

Integers never accept booleans. Unknown fields reject. Profile IDs are registry
references, not executable commands or guessed model aliases. An `actor` field
never authenticates a caller; Unix peer credentials do. All examples below use
illustrative values and do not choose production models or intervals.

## Profiles and station updates

A profile registration file contains exactly these fields:

```json
{"profile_id":"terra","adapter":"codex","model":"gpt-5.6-terra","executable":"/opt/agents/bin/codex","argv":[]}
```

The model is an exact provider model identifier. `argv` is an array of literal
arguments, never a shell command. Register every referenced profile before use.
The packaged ordinary adapters are `codex`, `claude`, and `hermes`; executable
availability and provider authentication must also be verified at deployment.

```sh
research-loops profile-register --file profile.json
research-loops stations --show
research-loops stations --ids 1,3 --primary terra --secondary luna
research-loops stations --all --primary terra --secondary luna
research-loops stations --ids 2 --secondary haiku
research-loops stations --active-count 2
research-loops stations --intervals 60,120,180,240,300
```

Set `RESEARCH_LOOP_CONTROLLER_SOCKET` for CLI or MCP clients running as an
operator account. Socket operations do not open the protected database locally.
`stations --show` returns the current controller revision, configuration, effective
shared checkpoint pair, assignments, completed counts, next ordinals, and holds.

`stations --file update.json` accepts an **update object**, not the complete
configuration snapshot. Its allowed fields are `station_ids` (integer array),
`all_stations` (boolean), `primary_profile`, `secondary_profile`, `intervals`
(exactly five integers), `active_count` (0–5), and `checkpoints` (complete policy).
Omitted update fields preserve existing settings. All provided changes commit
atomically. A complete interval chain is required even when only one value changes.
For example:

```json
{
  "active_count":2,
  "all_stations":true,
  "primary_profile":"terra",
  "secondary_profile":"luna",
  "intervals":[60,120,180,240,300],
  "checkpoints":{"enabled":true,"every_research_iterations":25,"on_deepening_entry":true,"agent_source":"station_1"}
}
```

Station IDs must be exactly 1–5 in a complete configuration. Active count N enables
1 through N. Intervals satisfy 1 ≤ 2 ≤ 3 ≤ 4 ≤ 5 by station position; equal values
are allowed. Reordering and capacity changes reconcile at safe iteration boundaries.
Existing writers finish or drain before their replacements acquire the topic.

To configure a separate shared checkpoint pair, use this complete policy:

```json
{"enabled":true,"every_research_iterations":25,"on_deepening_entry":true,"agent_source":"explicit","primary_profile":"terra","secondary_profile":"luna"}
```

`station_1` forbids explicit pair fields. Every episode snapshots its full resolved
pair; later profile edits affect new episodes, not an existing episode's retries.
The complete configuration and registry record shapes are published in
[station-configuration.schema.json](../research_loops/schema/station-configuration.schema.json)
and [agent-profile.schema.json](../research_loops/schema/agent-profile.schema.json).
Configuration schema version is 1; station update operations have the exact update
shape above and do not accept a `schema_version` field.

## Queue order and checkpoints

```sh
research-loops queue-reorder --file order.json
research-loops pause topic-a
research-loops resume topic-a
```

`order.json` contains exactly:

```json
{"expected_queue_revision":12,"ordered_ids":["topic-a","topic-c","topic-b"]}
```

Supply every existing queue ID exactly once, including retained intake/history
records. A stale revision, omitted ID, duplicate ID, or unknown ID rejects the whole
operation. Queue order is canonical priority; waiting for review never appends or
recreates the topic. An explicit reorder while waiting remains authoritative.

After successful ordinary research 25, the ledger records count 25 and next 26.
The separate checkpoint does not change either number. First deepening entry can
also create a checkpoint; coincident cadence/deepening triggers share an episode.
A complete zero-proposal result resumes eligibility automatically. Pending proposals
release capacity while preserving the queue ID/order. Final operator resolution
restores that same item's eligibility, leaving unrelated pauses intact. Incomplete
or invalid reviews cannot claim zero-proposal success.

```sh
research-loops checkpoint-decide --file decision.json
research-loops checkpoint-reset --file reset.json
```

A decision requires `schema_version`, unique `request_id`, current
`expected_revision`, `topic_id`, `episode_id`, and a nonempty `decisions` array.
Each decision has `proposal_id`, exact `proposal_version`, `action`, and `reason`.
Actions are `approve`, `approve_with_edits`, or `reject`. Only `approve_with_edits`
accepts `edits`, containing the complete final change object for that proposal kind.
Partial decisions retain the hold and report remaining proposals. Replay the same
request ID and payload after interruption; changing content under that ID rejects.

```json
{"schema_version":1,"request_id":"decision-1","expected_revision":42,"topic_id":"topic-a","episode_id":"checkpoint-example","decisions":[{"proposal_id":"proposal-example","proposal_version":1,"action":"reject","reason":"Already covered by the approved obligation."}]}
```

Proposal allowance is separate from cadence and is not refilled by a decision.
An explicit reset is operator-only:

```json
{"schema_version":1,"request_id":"reset-1","expected_revision":43,"topic_id":"topic-a","reason":"Authorize another bounded proposal allowance."}
```

The reset restores the existing two-proposal allowance, records its rationale,
and changes neither research count nor queue priority. Scope requests are recorded
for explicit new-authority work; the obligation publisher rejects attempts to use
an obligation approval as a mission rewrite. Addition/amendment publication validates
the complete bundle before changing approved files.

## Checkpoint recovery

After repairing a checkpoint capability or interface failure, use
`research-loops checkpoint-retry --file retry.json`. The exact envelope is:

```json
{"schema_version":1,"request_id":"retry-1","expected_revision":44,"topic_id":"topic-a","episode_id":"checkpoint-example","reason":"The reported capability is repaired; retry this same episode."}
```

This operator-only operation accepts `needs_attention` or `retry_wait` episodes
without live leases, reserved delegate calls, or unresolved proposals. It preserves
the episode, research count, priority, invocation history, remaining budgets, and
any independent operator pause. Duplicate identical requests return the same
result. It does not refill budgets or approve proposals.

## Intake and exact schemas

```sh
research-loops intake-submit --file brief.json
research-loops intake-result --file discovery-result.json
research-loops intake-approve --file intake-decision.json
```

Submitting a brief automatically creates its discovery task in the capped intake
lane. The discovery runner records its structured result automatically; the result
command is also available to the authenticated operator. Approved intake registers
research automatically. Never use generic add/sync/relock or legacy draft approval
to admit a managed topic.

| Input | Exact schema |
|---|---|
| Brief (`focused` or `broad`) | [intake-brief](../research_loops/schema/intake-brief.schema.json) |
| Discovery result (six criteria IDs `1`–`6`, exact draft revision/hash) | [intake-discovery-result](../research_loops/schema/intake-discovery-result.schema.json) |
| Intake decision | [intake-decision](../research_loops/schema/intake-decision.schema.json) |
| Checkpoint result/proposals | [checkpoint-result](../research_loops/schema/checkpoint-result.schema.json) |
| Checkpoint operator decision | [interface-checkpoint-decision](../research_loops/schema/interface-checkpoint-decision.schema.json) |

Discovery findings use `{finding, source_ref}` records; proposed obligations use
`{text, source_ref}`. Traceability records contain exactly `intent_ref`,
`contract_ref`, `status` (`pass` or `flagged`), and `explanation`. Broad discovery
requires its additional findings/exclusions/obligations fields. Intake
`approve_with_edits` supplies exactly `draft_authority`, `draft_topic`, and
`draft_semantic_state` as complete strings; the last contains complete JSON text.
No manually authored QA file is required to substitute for the structured result.

Validation errors preserve their code, field path, explanation, and recovery
instruction through the controller transport. Refresh status after a stale revision;
correct malformed inputs against the schema. Retrying a durable publication uses
the identical request ID and payload. It does not require a new queue insertion.

## Explicit migration input

`control-migrate --file migration.json` is a no-write validation report;
`--apply` explicitly initializes managed state. Its exact envelope contains
`configuration`, `agent_profiles`, `baseline_counts`, and optional
`checkpoint_history`. `configuration` follows the complete configuration schema;
`agent_profiles` maps profile IDs to `{adapter,model,executable,argv}` records.
`baseline_counts` maps **every existing queue ID** to a reviewed nonnegative count
of completed ordinary research iterations, never attempts.

`checkpoint_history` maps IDs to optional `last_checkpoint_iteration` and
`reviewed_inventory_versions`. Explicit reviewed inventory history is required for
legacy records already marked deepening. An overdue active topic gets one catch-up
episode without changing its count/next ordinal. Completed historical topics stay
completed. Migration refuses running legacy records and preserves existing order,
IDs, approved text, and inventory locks. Provision protected execution only while
active count is zero, following [managed-deployment.md](managed-deployment.md).
