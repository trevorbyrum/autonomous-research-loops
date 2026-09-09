# Station boundaries, queue admission, and separate checkpoints

Status: implementation authorized by the operator's subsequent instruction to
execute with Terra agents and review their work. This document remains the scope
contract; implementation evidence and deployment limits are recorded in
[the final review](2026-09-09-station-boundaries-review.md). Live cutover has not
been applied. The operational interface is documented in
[managed stations](../managed-stations.md).

This plan incorporates the operator's corrections after the mechanics review. It
supersedes that review's proposed checkpoint counting and ownership, and narrows
the work to the boundaries described below. The review remains historical evidence
of the code inspected at that time, not the specification for implementation.

## 1. Binding scope and interpretation

The work changes the machinery that admits, assigns, schedules, records, pauses,
and resumes research. It does not redesign how a worker conducts research.

The operator's requirements, used as acceptance identifiers throughout this plan:

| ID | Requirement |
|---|---|
| R01 | Each numbered research station has its own primary and secondary agent configuration and interval. |
| R02 | One operation can apply the same agent pair to all stations or a specified subset; either role can also be updated independently. |
| R03 | One active count enables the contiguous prefix 1 through N; higher/unconfigured stations cannot claim or launch work. |
| R04 | Intervals are nondecreasing by station number. Equal intervals are allowed. Queue priority maps to station priority at safe boundaries. |
| R05 | A central station work ledger owns topic-keyed completed research counts, checkpoint episodes, proposal state, and decisions. Topic folders do not own checkpoint scheduling. |
| R06 | Research iteration 25 completes before its checkpoint. The checkpoint is separate and does not increment the research count. The next research iteration is 26. |
| R07 | First entry into deepening also triggers a checkpoint when enabled, independently of the multiple-of-25 trigger. Coincident triggers are handled once. |
| R08 | All checkpoints use one shared agent policy, regardless of the hosting station's ordinary agent pair. Default: inherit station 1's primary and secondary. |
| R09 | A complete checkpoint with no proposals resumes automatically. Proposals wait for a standardized operator decision and then resume without changing the next research ordinal. |
| R10 | Waiting for a decision releases station capacity but preserves the same queue item and priority. The decision restores eligibility and causes cascade reconciliation, not tail insertion. |
| R11 | Intake, proposals, decisions, configuration, and queue operations have exact schemas, field ownership, validation, examples, and actionable errors. Agents do not invent file formats. |
| R12 | CLI and MCP use the same application operations. Approval automatically registers research work. Supported alternate entry points cannot bypass admission. |
| R13 | Ordinary worker methods and prompts remain unchanged except narrowly required role substitution, checkpoint handoff/location, and field/format/interface instructions. |
| R14 | Preserve existing topic authority, evidence standards, verification independence, substantive review procedure, failure classifications, and research completion criteria. |
| R15 | Remove ambiguous legacy execution authorities and enforce the managed-write boundary. Do not claim that a prompt prohibition prevents direct filesystem writes. |
| R16 | Existing state, iteration history, queue order, approved content, and in-flight work must survive migration without invented counts or silent scope changes. |

### Explicit exclusions

The following are out of scope even if nearby code could benefit from changes:

- Research work selection or prioritization *within* a topic; search strategy,
  breadth, extraction, evidence reconciliation, citation verification, synthesis,
  scientific judgment, and ordinary delegation choreography.
- Editing the questions, obligations, exclusions, deliverables, authority text, or
  acceptance criteria of existing topics as part of migration or cleanup.
- Choosing new production models, changing reasoning effort, tuning prompts,
  benchmarking models, or optimizing token use/throughput.
- New sourcing rules, different verification duties, or relaxing fresh-invocation
  independence because two roles happen to use the same model.
- New checkpoint argumentation/scouting methodology, changed candidate admission
  standards, or changed debate rounds and proposal limits. Existing substantive
  protocol is preserved; its scheduling, role names, records, and boundaries change.
- Changes to normal research retry delays, retry budgets, stall thresholds,
  saturation thresholds, completion predicate, or refresh research content.
- A redesign of the research gateway, adapters, retrieval cache, gateway database,
  corpus formats, or citation ledger system.
- Renaming existing topics to match a new naming rule; deleting old history;
  automatically accepting discovery proposals or pending scope proposals.
- General UI redesign, telemetry project, packaging cleanup, or refactoring
  unrelated modules. Status changes are limited to making the new mechanics visible.
- Automatic notifications to other people, deployment during plan creation,
  service changes during plan creation, or modification of concurrent work.

Boundary wrappers may call existing worker tools differently only to enforce the
authorized interface. They may not replace those tools' research semantics.

## 2. Ownership and physical storage

There will be one controller write boundary and three logical records: station
configuration, queue, and station work ledger. Logical separation does not require
independent state files with inconsistent transactions.

Recommended implementation: a controller-owned SQLite database at
`state/control.sqlite3`, using the standard library. Keep the three records in
separate tables and expose separate commands/views. This permits one transaction to
record iteration completion, create a due checkpoint, retain priority, and release
an assignment. Do not introduce a second database for research evidence or change
the gateway's storage. Existing store interfaces can be adapted to this persistence
layer without rewriting the ordinary runner algorithm.

| Record | Canonical owner | Contents |
|---|---|---|
| Station configuration | Controller, operator operations only | Active count, five station definitions, agent profile references, intervals, common checkpoint policy, configuration revision |
| Queue | Controller, operator/intake operations | Immutable item identity, ordered topic IDs, contract reference, dependencies, eligibility/control state, queue revision |
| Station work ledger | Controller runtime | Topic-keyed research count and run history, assignments/leases, checkpoint triggers/episodes, proposals, decisions, budgets, pending handoffs |
| Approved topic contract | Existing topic content, controller-mediated identity changes | Existing authority, obligations, deliverables, inventory identity; no cadence or model override |
| Working research evidence | Existing worker interfaces | Findings, citations, synthesis, semantic assessments, and allowed state transitions; scientific rules unchanged |

Specific storage rules:

1. Canonical configuration is written through the controller. TOML/JSON imports are
   validated inputs; human-readable config and queue exports are generated views,
   not competing live authorities. A config file on disk does not silently override
   a controller setting because a worker restarts.
2. The central work ledger has one topic record regardless of its current station.
   Changing stations changes an assignment reference, not the count or checkpoint
   state. No checkpoint control files are required inside a topic directory.
3. Checkpoint reports may be projected into topic logs for inspection, but changing
   such a projection cannot complete a checkpoint or approve a proposal.
4. Each mutation records operation ID, actor, input revision, committed revision,
   timestamp, affected IDs, and outcome. Secrets are not included in audit records.
5. Accepted research completions, checkpoint finalizations, and operator decisions
   are unique by durable IDs. Delivery may be retried; state transitions commit once.
6. Publishing changed approved files uses a recoverable staged-publication record.
   SQLite and several filesystem renames are not falsely described as one atomic
   filesystem transaction. The controller keeps the topic ineligible until the
   database and published contract version agree, and recovery completes the same
   operation before allowing a worker to launch.
7. Do not maintain two writable queue/config stores during migration. Archive legacy
   input; any retained `queue.json`/station JSON compatibility view is clearly an
   export and cannot accept managed writes.

## 3. Station profiles and shared checkpoint agents

### Configuration schema

Every managed input has `schema_version`; unknown fields are errors. Explicit null
is accepted only for fields documented nullable. Integer fields reject booleans.

| Field | Type and requirement | Meaning |
|---|---|---|
| `schema_version` | Required integer, initially 1 | Input contract version |
| `active_count` | Required integer 0–5 | Exactly stations 1..N may host new research/checkpoint executions |
| `stations` | Required array of five unique station definitions | Configuration persists even while a station is inactive |
| `stations[].id` | Required integer 1–5 | Canonical identity; aliases normalize at the CLI boundary |
| `stations[].primary_profile` | Required registered profile ID | Ordinary research primary |
| `stations[].secondary_profile` | Required registered profile ID | Ordinary research secondary |
| `stations[].interval_seconds` | Required integer >= 0 | Pacing delay after a research iteration completes; 0 means continuous |
| `checkpoints.enabled` | Required boolean, default true for the new complete implementation | Enables automated checkpoints; not activated in deployment until implementation/migration is ready |
| `checkpoints.every_research_iterations` | Required positive integer, default 25 | Cadence measured only in completed ordinary research iterations |
| `checkpoints.on_deepening_entry` | Required boolean, default true | Additional first-entry trigger per approved inventory version |
| `checkpoints.agent_source` | Required enum `station_1` or `explicit`, default `station_1` | Resolves one pair for every checkpoint |
| `checkpoints.primary_profile` | Required only for `explicit`; forbidden for `station_1` | Shared checkpoint primary |
| `checkpoints.secondary_profile` | Required only for `explicit`; forbidden for `station_1` | Shared checkpoint secondary |

Registered agent profiles explicitly identify adapter, exact configured model ID,
existing executable/wrapper, and argument array. A friendly name such as `terra`
is a profile ID, not an instruction for an agent to guess a current model string.
Resolve executable and credentials through trusted deployment configuration. Do not
silently translate an unsupported model/profile into a default provider.

Example intended ordinary mapping, using profile labels rather than new model pins:

| Station | Primary | Secondary | Checkpoint pair when source is `station_1` |
|---|---|---|---|
| 1 | Terra | Haiku | Terra / Haiku |
| 2 | Sonnet | Luna | Terra / Haiku |
| 3 | Terra | Luna | Terra / Haiku |

Changing all ordinary stations to Terra/Luna also changes inherited checkpoint
agents to Terra/Luna. With `agent_source = explicit`, checkpoint profiles remain
independent of ordinary station edits.

### Update behavior

Proposed operations include:

```text
stations agents --stations 1 --primary terra --secondary haiku
stations agents --stations 2 --primary sonnet --secondary luna
stations agents --stations 1,3 --secondary luna
stations agents --all --primary terra --secondary luna
stations active-count 3
stations intervals --values 0,900,1800,1800,1800
stations checkpoints agents --from-station 1
stations checkpoints agents --primary terra --secondary luna
stations show --effective
```

- `--all` updates all five configured research stations, including inactive ones;
  it does not change active_count or the intake worker. A subset is explicit.
- Role-only edits leave intervals and the other role unchanged. Agent updates do
  not reset counts, priorities, or checkpoint episodes.
- Multi-station edits validate the complete resulting configuration and commit all
  changes together or none. They do not depend on an order of incremental edits.
- Validate the interval chain for all five definitions. Missing profiles, clearing
  required profiles, duplicate station IDs, and unknown stations are errors.
- Existing in-flight ordinary iterations keep their resolved launch configuration.
  Subsequent ordinary launches use the new config revision.
- Resolve and snapshot checkpoint agents when an episode is first launched; persist
  that pair for retries and permitted repair calls. Later config edits affect new
  episodes, not a half-finished one. A due but never-launched episode resolves the
  configuration when it actually starts.
- Inheriting station 1 means reading its configuration, not using its live process,
  conversation, memory, or execution slot. A checkpoint hosted on station 3 can use
  station 1's pair while station 1 continues its assigned ordinary work.
- Map the existing checkpoint primary/preparation/counter/repair roles onto this
  pair. Preparation uses the shared secondary; the fresh primary-class counter uses
  the shared primary model in a distinct invocation. Preserve the existing role
  independence, call limits, and adjudication procedure. No extra permanent third
  model is introduced.

## 4. Active capacity, priority, and assignment

The scheduler is one authoritative assignment function under the controller's
transaction boundary. Workers request a lease; they do not independently steal or
reserve topics based on polling order.

### Rules

1. Only station IDs 1 through active_count may acquire new leases. Validate both at
   claim and immediately before spawn. Manually starting a higher station does not
   create capacity. Intake remains a separately capped lane.
2. Each active station hosts at most one primary execution: ordinary research or a
   checkpoint. Existing delegates are part of that execution, not extra stations.
   No separate, unbounded checkpoint fleet is introduced.
3. Rank eligible research topics by canonical queue order and assign them in station
   number order. Equal intervals use the same deterministic station-number order.
4. A checkpoint is work on an existing topic, never a second research queue item.
   Its due status takes precedence over that topic's next ordinary iteration.
5. Awaiting-decision topics retain queue position but are excluded from executable
   assignments. Paused, completed, true dependency-blocked, and failure-retry-blocked
   topics retain their documented exclusions. Station pacing alone does not turn
   into a reason to run a different lower-priority topic on the same station.
6. Preserve manual pause/global stop independently from review status. Resolving a
   proposal clears only the review hold; it cannot undo an operator pause or a real
   dependency/capability restriction.
7. Reconcile at startup/recovery, queue reorder, enable/disable, config change,
   completion, pause/resume, retry eligibility, and checkpoint/decision transitions.
8. In-flight work finishes under its existing lease. Publish a desired assignment
   and pending handoff, then move ownership at a safe boundary. No forced kill for
   routine reordering, checkpoint resumption, or active-count changes.
9. Once a priority change requires a station to hand off, it cannot launch another
   ordinary pass on the displaced topic. That is how the restored head topic avoids
   indefinite postponement by repeated lower-priority iterations.
10. On decreasing active_count, higher stations drain existing executions and then
    release capacity. Report desired count and draining executions separately;
    never pretend immediate zero occupancy while real children still run.
11. If an enabled station is unhealthy, show it as unhealthy and recover supervision.
    Do not silently let station 2 impersonate priority tier 1. Crash adoption must
    retain the existing protections against duplicate work and PID reuse.

### Stable-priority example

Canonical order starts `A, B, C, D`; three stations run A, B, C. A finishes research
iteration 25 and completes a checkpoint with proposals. A enters review wait.

```text
Canonical order:          A, B, C, D     (unchanged throughout)
While A awaits decision:  station 1 -> B, station 2 -> C, station 3 -> D
Decision resolves A:      desired 1 -> A, desired 2 -> B, desired 3 -> C
After safe handoffs:      station 1 runs A research iteration 26
```

If B is still running on station 1 at decision time, its current iteration finishes,
then station 1 takes A. B cannot start another iteration there first. Other moves
follow without concurrent writers on the same topic. If the operator explicitly
reorders A during its review wait, honor that new order; do not restore a stale
saved numeric index over the operator's later decision.

### Pacing and retries

- Separate `pacing_ready_at` from `retry_not_before`, including the existing retry
  reason. Preserve failure classification/delay behavior.
- A routine checkpoint runs after the triggering research iteration finishes and
  before the next research launch; do not insert the normal station interval before
  starting the checkpoint itself.
- On the same station, the next research launch is no earlier than the previous
  research completion plus that station's interval, and no earlier than completion
  of the checkpoint/decision. Review elapsed time can satisfy that pacing wait; do
  not add another full interval just because the checkpoint ended.
- A boundary transfer does not inherit the old station's pacing wait. It also does
  not erase an applicable failure retry restriction.
- Surface reasons and timestamps so an eligible restored topic cannot look
  mysteriously stuck. A real retry or operator pause is distinct from lost priority.

### Queue-order operations

Provide relative move (`--before`/`--after`) and atomic full ordered-ID replacement
with `expected_queue_revision`. Reject duplicate, missing, foreign IDs and invalid
positions; do not silently clamp them. Reordering changes no topic definition.

The return value includes committed order, desired assignment changes, current
in-flight blockers to handoff, and revision. Remove independent `swap-active`
priority authority: adapt it to an explicit valid order change or return a migration
error with the supported command. Do not preserve a manual claim bypass.

## 5. Central station work ledger and research counting

### Required runtime records

| Record | Required controller-owned fields |
|---|---|
| Topic work summary | `topic_id`, `research_iterations_completed`, `next_research_ordinal`, `inventory_version`, `lifecycle_generation`, `review_state`, `active_episode_id`, `last_accepted_run_id`, row revision |
| Research run | `run_id`, `topic_id`, `ordinal`, `attempt_id`, `station_id`, `lease_generation`, resolved configuration revision, start/end timestamps, accepted outcome, completion accounting status |
| Trigger | `trigger_id`, `topic_id`, kind (`cadence`/`deepening_entry`), research ordinal, inventory version, episode ID, handled state |
| Checkpoint episode | `episode_id`, `topic_id`, triggering research ordinal, trigger IDs, inventory version, state, resolved agent pair, prompt/protocol version, attempt history, remaining budgets, prior-review reference, result reference |
| Proposal/decision | Stable IDs and versions, episode/topic/inventory references, structured content, operator action, resolution/publication state, audit metadata |
| Assignment | Station ID, topic ID, execution kind, current lease, desired next assignment, pacing/retry fields, drain/handoff reason |

### Counting rules

- Count only accepted completed ordinary research iterations. A successful unchanged
  research pass still counts. A failed/interrupted attempt, discovery pass,
  checkpoint attempt, operator decision, and status refresh do not count.
- Use the engine's accepted execution outcome, not the agent's final prose or a
  source/finding count. Required scientific validation remains unchanged; ordinary
  research can complete a pass without finishing the topic.
- Increment once when the controller accepts the run's completion. Retried
  completion delivery with the same run ID returns the original result.
- Research iteration numbers remain stable through station movement, model changes,
  checkpoint retries, process restarts, and proposal decisions.
- A normal topic refresh continues the recorded historical count; lifecycle and
  inventory versions identify the new research episode separately. Do not overload
  the existing `restart` command to zero historical counters.
- Preserve attempt counters separately. Never initialize a completed-research count
  by blindly copying `attempts`.

### Cadence trigger transaction

On accepted research completion, in one transaction:

1. Validate lease/run identity and reject duplicate/stale completion.
2. Record outcome and increment completed research count once.
3. Evaluate positive multiples of the configured cadence and deepening entry using
   the approved inventory version and existing coverage gate.
4. Create/coalesce due trigger records and at most one unresolved checkpoint episode
   for that topic/version context.
5. Prevent another ordinary launch while the checkpoint is due/running/waiting.
6. Commit the next scheduler action and audit event.

Never implement only `count % 25 == 0` without the handled-trigger record. Otherwise
count 25 remains true after a checkpoint and causes repeated reviews forever.

## 6. Separate checkpoint state machine

Checkpoint states are separate from ordinary research counts:

```text
due -> running -> complete_without_proposals -> research eligible
                -> awaiting_operator -> publishing_decision -> research eligible
                -> retry_wait -> running (same episode/budget)
                -> needs_attention (explicit reason; never silent success)
```

Detailed behavior:

1. Research 25 ends. Ledger count becomes 25 and next research ordinal becomes 26.
2. Checkpoint episode starts with `triggered_after_research_iteration = 25`.
3. Throughout review, retries, proposal wait, and decision processing, count remains
   25 and next research ordinal remains 26.
4. A validated complete zero-proposal result closes the episode and makes the topic
   executable under its preserved priority. A missing/incomplete result is not a
   zero-proposal result.
5. A complete result with proposals releases the station and enters
   `awaiting_operator`. Record the precise pending proposal IDs/versions.
6. Once every proposal needing a decision is resolved and any approved publication
   succeeds, release the review hold and reconcile assignments in the same logical
   operation. Never call remove/add or append-at-tail to resume.
7. A valid rejection is a completed decision and resumes existing approved work.
   Approval publishes the exact accepted change and resumes with that inventory.
8. An operator hold or unrelated pause is explicit and visible; do not treat a
   missing answer as approval or a failed publication as a resolved episode.
9. Due cadence/deepening triggers coalesce into one episode with both reasons. Mark
   all covered triggers handled only after an adequate review, not on launch.
10. A failed checkpoint does not consume another cadence boundary or replenish any
    episode/proposal allowance. Reuse completed preparation where existing protocol
    permits it; preserve invocation identities and outputs across recovery.
11. An unresolved required evidence reconciliation keeps substantive review due.
    Preserve the existing checkpoint reconciliation procedure and report any real
    evidence changes separately for validation/invalidation. The execution remains
    a checkpoint and does not increment the research count. Do not silently launch
    ordinary research 26 while claiming the checkpoint is still blocking it. If the
    existing procedure cannot complete the review, record the exact prerequisite
    and recovery state rather than inventing a new research workflow.

### Deepening and inventory identity

- Use the existing validated coverage/deepening determination; do not introduce an
  alternative scientific readiness rule in the scheduler.
- Record first entry for each approved inventory version. Status churn alone cannot
  reset it. Once new approved obligations are covered, entry for the new version
  may trigger a review.
- Active topics already in deepening at migration get at most one explicitly
  recorded catch-up review if no adequate review for that inventory is recorded.
- Do not reopen topics already completed before the migration solely for a review.
- A proposal decision must not instantly reissue the same checkpoint before
  research can resume at 26. Record the relationship between reviewed inventory,
  approved publication, and next genuine deepening transition. A new inventory is
  not by itself proof that another research transition has occurred.

### Completion and accounting

- Checkpoint-only activity changes neither research ordinal nor stall/saturation
  streaks. It is a distinct execution kind assigned by the controller.
- If the checkpoint discovers/causes actual evidence or inventory changes, preserve
  the existing invalidation rules. Do not freeze stale saturation evidence through
  a substantive scope change.
- At a research boundary where a checkpoint becomes due, the due review takes
  precedence over final completion. Hold any pending completion disposition;
  checkpoint completion or an operator decision does not itself complete research.
  Resume the next ordinary ordinal and evaluate the unchanged research completion
  gate there. This is the narrow scheduling consequence of the required 25 ->
  checkpoint -> 26 sequence, not a new completion threshold.
- Ordinary research that is already terminal and has no due checkpoint retains its
  existing completion behavior. Do not add an unconditional final checkpoint.
- Keep completion hooks from firing while a mandatory checkpoint/decision is still
  pending. Retain existing hook semantics on actual research completion.

### Policy edits while work exists

- Disabling checkpoints suppresses new automated triggers; it does not approve or
  discard a pending proposal, cancel an in-flight episode, or release an unresolved
  operator-decision hold. Any explicit cancellation must be an audited operator
  disposition that preserves proposal and episode history.
- Changing the cadence applies to future accepted research completions under the
  new configuration revision. It does not erase an already-due checkpoint or replay
  every historical multiple of the new value. Responses show the next boundary.
- Turning deepening-entry reviews back on may create one catch-up review for an
  active, currently deepening inventory that has not been reviewed. Existing handled
  markers still prevent duplication.
- Changing active_count or role profiles never changes a pending review's priority,
  research ordinal, proposals, or operator decision. Pending episodes wait for valid
  active capacity when active_count is zero.

### Checkpoint agent/protocol packaging

Place the executable checkpoint entry point and packaged prompt/protocol resources
under the station execution boundary, for example
`research_loops/checkpoints/{runner.py,prompts/...}`. Keep a short operator-facing
reference in docs that points to the canonical packaged protocol.

The new entry point receives a structured episode context and returns a structured
result. It uses the shared checkpoint pair, existing adapter/wrapper capabilities,
and existing substantive review procedure. Do not run checkpoint-only work by
secretly calling the ordinary iteration prompt and hoping its self-report excludes
it from counting.

Retain the current proposal slate, final-proposal, invocation, repair-exchange, and
time/size limits. Translate existing enforceable limits to controller counters and
checkpoint launch supervision; do not invent new limits. Where the current protocol
expresses approximate targets rather than hard constraints, label them as targets
instead of silently treating them as new rejection criteria.

## 7. Exact agent-facing formats

Every operation must have a checked-in schema and field reference that includes
name, type, required/conditional/optional status, default, enum values, example,
ownership, and error behavior. Generate CLI help/MCP schema information from the
same definitions where possible. Provide a complete minimal valid example and
invalid examples showing each conditional rule.

Common mutation envelope:

| Field | Requirement |
|---|---|
| `schema_version` | Required supported integer |
| `request_id` | Required idempotency identifier; same ID/same payload replays result; same ID/different payload conflicts |
| `expected_revision` | Required for edits/decisions/reorders; create operations have an explicitly documented create-only form |
| Object identity | Required stable topic/station/episode/proposal ID appropriate to the operation |
| Operation body | Required typed object; unknown fields rejected recursively |

The authenticated caller supplies identity through the control channel. An agent
cannot authorize itself by putting `actor = operator` into its payload.

### Intake records

| Record | Required semantic fields | Controller-generated fields |
|---|---|---|
| Brief submission | `topic_id`, `title`, `operator_brief`, `mode` (`focused`/`broad`) | Draft ID/revision, creation metadata, discovery task registration |
| Draft contract | Mission/brief reference, explicit exclusions array, obligation records, deliverable records, dependency IDs | Canonical files, draft hash, semantic-state scaffolding |
| Obligation input | `id`, exact `text`, `source_ref` traceable to brief/approved decision | Initial disposition/evidence/assessment fields using existing scaffolder defaults |
| Deliverable input | `id`, exact `description`, `path`, explicit `required_headings` array | Initial missing status and existing acceptance-field defaults |
| Discovery result | Draft revision/hash, pass kind, restated intent, per-criterion findings, traceability findings, questions; broad mode additionally requires topic-space findings, proposed obligations/exclusions | Result ID, accepted execution reference, timestamps |
| Intake decision | Draft/result revisions, explicit decision, exact accepted draft reference or complete edited content, operator rationale/answers | Authenticated decision ID, approved inventory/lock, queue registration |

Empty arrays are valid only where the underlying process allows no entries. For
example, a no-question result uses `questions: []`, not a missing key or a placeholder
string. Existing obligation/deliverable scientific requirements are reused, not
replaced by new substantive criteria. Focused mode remains focused; standardizing
format does not turn it into a broad scope challenge.

The implementation must enumerate the current discovery criteria into stable IDs
without rewriting their meaning. Discovery results name each criterion and supply
`pass` or `flagged` plus the required explanation. No catch-all Markdown blob stands
in for required structured findings, though a rendered report is generated.

### Checkpoint result and proposal records

A checkpoint result requires episode ID, reviewed inventory version, trigger IDs,
review completeness, findings/coverage limitations, protocol evidence references,
and an explicit proposals array. The controller owns model/invocation/budget
telemetry and validates the result against those records. A self-reported `done`
does not close an incomplete episode.

Proposal fields make the existing protocol explicit:

| Field | Requirement |
|---|---|
| Proposal ID/version, episode/topic ID, base inventory | Required stable references |
| `origin` | Controller-established provenance; not editable to evade checkpoint governance |
| `kind` | Required enum `addition`/`amendment`/`scope_request` |
| Corpus anchors/locators | Required structured records; observations and motivating inferences separate |
| Evidence target and route | Required; preserve support, complication, null, unresolved outcome handling |
| Nearest approved obligation/prior proposal | Required references or explicit documented absence; explanation of non-duplication |
| Consequence | Required explanation of what plausible answers would change |
| Counterargument/response/dependencies | Required existing-protocol fields, including explicit empty dependencies where applicable |
| Addition content | Exact new obligation text and source reference; required for addition |
| Amendment content | Target ID, exact current/proposed text, framing defect and burden/acceptance/deliverable/evidence implications; required for amendment |
| Scope request content | Exact requested mission change and rationale; never silently promoted as an ordinary addition |

No terminal scientific evidence references may point to debate or approval records
as if they verified a research claim. Existing citation rules remain in force.

### Standardized operator decisions

Proposed operation: `checkpoint decide --file decision.json`, also exposed through
the same application service in MCP. A decision bundle contains:

```json
{
  "schema_version": 1,
  "request_id": "operator-decision-unique-id",
  "expected_revision": 42,
  "topic_id": "classification-labeling",
  "episode_id": "checkpoint-unique-id",
  "decisions": [
    {
      "proposal_id": "proposal-unique-id",
      "proposal_version": 1,
      "action": "reject",
      "reason": "The approved obligations already cover this question."
    }
  ]
}
```

- Actions are `approve`, `approve_with_edits`, or `reject`. `approve` accepts the
  exact identified version. `approve_with_edits` requires the exact complete final
  allowed change object for that proposal kind; prose such as “make it narrower”
  is insufficient to publish binding scope. `reject` cannot carry scope edits.
- Bind decisions to current episode/proposal/inventory versions. A stale decision
  returns a conflict with the current reviewable version, without applying a subset.
- A decision can resolve a subset, but the topic remains awaiting review until every
  proposal requiring a decision is resolved. Responses list the remaining IDs.
  An all-proposal bundle is validated and committed together.
- Approved changes publish through the shared contract mutation operation, with
  inventory and completion lock updated together. Rejections change neither.
- A decision does not implicitly refill proposal issuance or delegate budgets.
  Existing operator review/reset authority gets its own explicit typed operation.
- The result reports each disposition, publication state, preserved queue position,
  next research ordinal, eligibility/hold reason, desired station, and pending
  boundary handoff. The operator can see that the next iteration is still 26.

### Error and recovery contract

Errors return a stable code, exact field path, expected type/allowed values,
received category, concise explanation, and valid next operation. Codes include
`VALIDATION_ERROR`, `REVISION_CONFLICT`, `DUPLICATE_REQUEST_CONFLICT`,
`DRAFT_RESULT_STALE`, `AWAITING_OPERATOR`, `CAPACITY_DISABLED`, and
`PUBLICATION_PENDING`.

An error must not recommend raw file edits, constructing an arbitrary `add` command,
dropping locks, or bypass flags. After repeated failed submissions the agent can
inspect its draft/result and validation report; it cannot escape into a less strict
write path. Fixing a formatting error preserves request history and valid draft
work. State validation is not delegated to a model guessing whether text looks OK.

## 8. One intake workflow and protected mutations

1. Submitting a brief validates it, creates a canonical draft, and automatically
   creates its discovery/criteria task. Both focused and broad modes keep their
   current substantive procedure.
2. Discovery runs through the existing intake lane and adapter configuration, emits
   the structured result, and is accepted only against the exact draft revision.
   Repeated discovery creates a new execution record without deleting prior history.
3. An operator reviews the generated draft/result and submits a standardized ruling.
   The model may prepare the ruling payload, but cannot grant operator authority.
4. Validate the final contract and all required process records before publishing
   approved files. Stage publication; pin its lock; automatically register the topic
   once. Default insertion is at the tail for a *new* topic, or a specified relative
   position committed as part of the same operation. This is unrelated to resuming
   an existing reviewed topic, whose position never changes.
5. Registration derives the canonical research execution definition. It takes no
   topic model/interval/custom command from an agent.
6. CLI and MCP call these same functions, with equivalent results/errors. Eliminate
   copy-the-suggested-add-command as the normal approval flow.
7. Generic `add`, `sync`, import, approved-topic review, relock, and scope amendment
   cannot bypass research admission or writer authorization. Retain generic jobs
   only as an explicitly separate kind; never as an unlocked research topic.
8. Existing ordinary-gap policy is preserved substantively. Its mutation wrapper
   obtains allowance and authority from controller state rather than a caller's
   `--limit` or filesystem activity heuristic. Checkpoint proposals remain subject
   to operator decisions regardless of ordinary-gap auto policy.

## 9. Prompt and worker-process change guard

Before implementation, capture the ordinary prompt templates, rendered prompt
fixtures for representative profiles, and relevant worker process settings. Review
the semantic diff, not just whether tests still pass.

| Surface | Allowed edit | Forbidden edit |
|---|---|---|
| Ordinary iteration prompt | Location/interface/field references and narrow handoff instructions; configurable role references where necessary | Research steps, priority within a topic, search/evidence requirements, new reflection/scouting duties |
| Core contract | Correct station-vs-topic role source and packaged checkpoint pointer; remove obsolete checkpoint accounting statements | Rewriting scientific rules, substantive review method, citation acceptance or verification independence |
| Ordinary runner | Resolve station config, obtain lease/context, send trusted run result, separate research/checkpoint dispatch | Different research prompt selection/content, new ordinary delegation rounds, changed normal failure/stop/completion rules |
| Discovery prompt | Structured output field names, schema/location, validation instructions | Different discovery criteria, broad/focused behavior, new research tasks |
| Checkpoint resources | Move/package protocol, correct separate counting, shared agents, typed context/result/decision references | New argumentation method, larger debate, new proposal policy |
| Semantic-state CLI | Narrow transport/writer-boundary adaptation if required; existing validation reused | New terminal criteria, evidence interpretation, source formats, or renamed existing obligations |
| Adapters/wrappers | Structured configured role arguments and protected launch context | Replacing working providers, tuning models, changing ordinary worker tool permissions beyond managed-write isolation |

If changing an ordinary prompt sentence cannot be classified in an allowed cell,
leave it unchanged and record the issue as outside this plan. Do not use
“standardization” as permission to rewrite all prose.

## 10. Permission boundary and deployment compatibility

The controller owns mutable config/queue/work-ledger storage and the code that
enforces those operations. Research processes must not have write access to them.
Protecting only MCP while leaving a writable database, Python module, or legacy
JSON file reachable from the worker's shell is insufficient.

Implementation should use a separate service identity or equivalent filesystem
isolation for managed control state/code. Preserve the workers' research tools,
network access, evidence workspaces, and existing credentials through the deployment
mechanism; do not solve queue isolation by disabling research capability.

Where a single semantic-state file combines mutable research assessments and
protected inventory identity, preserve the current state CLI behavior but route
managed writes through operations that authorize fields separately. A research
caller can perform its existing valid assessment transitions; it cannot alter
approved text/IDs, station config, counters, approvals, or proposal origin.

Operator sessions have queue/config/decision authority through the operator
interface. Intake/checkpoint/research callers receive only their execution-scoped
operations. Authorize from the control channel and lease, not a forgeable payload
field or an environment variable alone. Revoke an old lease when a handoff commits.

Test the same protected operations through shell, Python API, CLI, and MCP. A worker
must not acquire operator capabilities by starting a local `--operator` MCP server.
Local offline standalone tools may remain available for unregistered workspaces;
they must refuse managed-store mutations without controller authorization.

This deployment work is part of implementing the boundary, not permission to alter
ordinary worker research methodology. Deployment happens only after the code and
migration are concrete and validated, not during planning.

## 11. Migration and coexistence with current work

At plan creation, the checkout contains concurrent uncommitted changes to station,
queue, runner, config, CLI, MCP, dashboard, throughput, and ordinary prompt files,
plus `stations.py` and station tests. Preserve that work. Do not treat the original
review findings as proof those files still have their old behavior.

Implementation starts by re-reading the actual diff and current code, recording
which requirements are already met, and adapting this plan's work items. Existing
changes do not automatically become approved by appearing in the checkout.

Migration procedure:

1. Inventory source versions and live state without mutation. Record config/model
   sources, service identities, queue IDs/order/status, topic locks, in-flight PID
   fingerprints, counts/events, checkpoint/proposal records, and unsupported shapes.
2. Produce a dry-run migration report and backups with a restore recipe. Include
   the exact target active_count/profile/interval configuration; do not infer desired
   active_count merely from how many systemd services happen to exist.
3. Validate current central completed-research counts against their producers. If a
   counter is reliable, preserve it. If reconstruction is required, use deduplicated
   accepted ordinary execution records, excluding failures, discovery and review.
   Mark unreconstructable history explicitly and require a recorded operator
   baseline; do not silently set it to zero or copy attempts.
4. Preserve existing topic IDs, all approved text, completion locks, priority,
   ordinary runtime history, pending decisions, and explicit pauses. Legacy IDs
   remain readable/addressable even if new intake naming is stricter.
5. Convert old item-level model/interval settings in the report. Target configuration
   has station authority only. Conflicting source values require an explicit target
   choice, not a hidden legacy floor or fallback.
6. Drain or safely adopt in-flight work using the existing process protections. Do
   not start two supervisors or overwrite a result written under an old lease.
7. Commit the controller state, publish verified projections, then switch supported
   clients and worker launchers together. Retire legacy writes; remove redundant
   model/cadence sources from service configuration without changing chosen values.
8. Seed future cadence boundaries from the preserved count. Do not replay every
   historical multiple of 25. If exactly at an unreviewed boundary, create one due
   episode; if historical counts are incomplete, record the explicit baseline.
   Handle deepening catch-up as defined above without reopening completed topics.
9. Verify protected writes, resolved roles, counts, assignments and decisions in the
   deployed environment. Roll back only after reconciling any post-cutover accepted
   work; restoring an old snapshot over new research would lose history.

## 12. Implementation phases and allowed files

Each phase has a scope check before edits and an acceptance check afterward. The
file list is an allowlist of purposes, not blanket permission to rewrite each file.
Proposed modules can be split only when their ownership remains as specified.

| Phase | Work and likely surfaces | Exit evidence |
|---|---|---|
| P0: reconcile baseline | Read current diff, review/plan, current config and interfaces; create requirement-to-code map | No concurrent work overwritten; each existing behavior labeled implemented/partial/missing |
| P1: contracts and persistence | New control storage/operations/schema modules; narrow adapters in `queue.py`, `stations.py`, `config.py`; packaged schema files | Strict schemas, atomic/idempotent operations, one writable authority, migration dry run |
| P2: station configuration | Station profile/group operations; CLI/MCP bindings; launcher eligibility in `workers.py`/runner | Independent/all/subset profile tests, whole-chain intervals, active-count enforcement |
| P3: assignment | One reconciliation/finalization path in queue/controller and runner boundary adapters | Real production-path cascade, reorder, drain, retry separation, stale-lease/crash tests |
| P4: intake/decisions | Shared intake service, `topic_authoring.py`, CLI/MCP, discovery result adapter/templates, scoped contract mutation wrapper | Equivalent transport behavior; stale/malformed/bypass rejection; recoverable approval+registration |
| P5: checkpoint execution | New packaged checkpoint runner/prompts/protocol; central ledger/state machine; narrow ordinary runner dispatch | Separate counts, shared agents, durable triggers/episodes/budgets, decisions and priority restoration |
| P6: deployment boundary | Controller entry point, scoped client, managed-file permissions, systemd/install integration; narrow state CLI transport | Workers retain research functionality but cannot mutate operator state through alternate paths |
| P7: docs/status/integration | `docs/operations.md`, `docs/agent-operations.md`, architecture/intake references, example config, dashboard/MCP projections, package-data list | Accurate effective-state view; installed runtime can locate checkpoint protocol; obsolete paths documented/rejected |
| P8: migration validation | Disposable migration rehearsals, end-to-end fixtures, deployment report | All acceptance checks below satisfied; live cutover is a separate concrete operation |

Ordinary prompt files are allowed only for the narrow purposes in section 9.
Gateway adapters, gateway database code, topic evidence content, and unrelated
throughput calculations are excluded. If reporting needs a new checkpoint kind,
change only its classification/display so checkpoints are not reported as research
iterations; do not redesign metrics.

## 13. Acceptance matrix

These checks remain unchecked until implementation evidence exists. A passing old
test suite alone does not satisfy a check. Use fake adapters and disposable stores
for automated integration; no real research/model spend is needed for these proofs.

| Check | Observable acceptance behavior | Requirements |
|---|---|---|
| A01 | Stations 1/2/3 launch ordinary work with Terra/Haiku, Sonnet/Luna, Terra/Luna respectively, with no item/env fallback | R01, R13 |
| A02 | All/subset/one-role updates change only the targeted profiles and are atomic | R02 |
| A03 | Missing profile, profile clear, model-only creation, unknown station, and invalid interval chain all reject without partial changes | R03, R04, R11 |
| A04 | Active count 2 allows stations 1/2 only across systemd/manual/CLI claim and spawn paths | R03, R15 |
| A05 | Active count 0 and downscale drain existing work; no subsequent launch slips through an old lease | R03, R16 |
| A06 | Equal intervals still yield deterministic station-number priority independent of polling order | R04 |
| A07 | Reorder reassigns occupied stations at safe boundaries; the old owner cannot reacquire ahead of the new assignment | R04 |
| A08 | Concurrent reservations/handoffs cannot replace a higher-priority claimant or duplicate topic writers | R04, R16 |
| A09 | Production runner finalization, not only a helper, performs the tested handoff | R04 |
| A10 | Transfer clears only pacing; future applicable failure backoff remains enforced | R04, R14 |
| A11 | Research 24 -> research 25 -> checkpoint -> research 26; central count remains 25 throughout checkpoint | R05, R06 |
| A12 | Repeated result delivery/crash recovery counts research 25 once and creates one checkpoint | R05, R06 |
| A13 | Failed/interrupted ordinary attempts, discovery, review, and operator decisions do not increment research count | R05, R06 |
| A14 | Count 25 does not retrigger after its episode is handled; next cadence trigger is after research 50 | R06 |
| A15 | A checkpoint on station 3 uses station 1's pair, while ordinary station 3 work still uses its own pair | R01, R08 |
| A16 | Explicit checkpoint pair applies fleet-wide; station-1 edits affect new inherited episodes, not in-flight retries | R08 |
| A17 | Shared primary/secondary mapping retains independent invocation identities and existing counter/repair limits | R08, R14 |
| A18 | Deepening alone triggers once for the approved inventory; simultaneous cadence/deepening coalesces | R07 |
| A19 | Reassignment/model change/restart cannot reset counts, triggers, episode budget, or priority | R05, R16 |
| A20 | Complete zero proposals resumes automatically; missing/invalid/incomplete result cannot masquerade as zero proposals | R09, R11 |
| A21 | Proposals release station capacity, preserve A/B/C/D order, and move B/C/D up at safe boundaries | R09, R10 |
| A22 | Reject/approve/approve-with-edits resolves the exact proposal version; once all resolve, A restores to station 1 and research 26 | R09, R10, R11 |
| A23 | Partial decision lists remaining proposals; stale or malformed decision commits no unintended scope change | R09, R11 |
| A24 | Replayed operator decision does not republish scope, duplicate obligations, reset count, or append topic at tail | R09, R10, R16 |
| A25 | Explicit reorder during review wait is preserved on decision; unrelated operator pause remains in force | R10, R14 |
| A26 | Checkpoint-only work neither increments nor resets saturation/stall; actual inventory/evidence invalidation still applies | R06, R14 |
| A27 | Due checkpoint is not skipped by same-boundary completion; next ordinary pass uses the unchanged completion predicate | R06, R09, R14 |
| A28 | Malformed intake, unknown fields, missing criteria, and stale draft discovery return exact actionable errors | R11 |
| A29 | CLI and MCP submit/discover/approve/reorder/decide have matching state changes and errors | R12 |
| A30 | Approval failure or crash at each publication/registration step is recoverable without half-approved runnable work | R12, R16 |
| A31 | Generic add/sync/import/relock and directly invoked managed tools cannot bypass required approval or schema | R11, R12, R15 |
| A32 | Repeated discovery preserves history and cannot reuse a stale nonempty file as current success | R11, R12 |
| A33 | Prompt diff contains only allowed interface/role/location/checkpoint edits; ordinary research steps are unchanged | R13, R14 |
| A34 | Protected controller files/code cannot be written by research identity; operator payload impersonation fails | R15 |
| A35 | Research identity still performs existing valid state/evidence operations using existing scientific validation | R13, R14, R15 |
| A36 | Installed package can run a checkpoint without a source checkout or private protocol file dependency | R08, R11 |
| A37 | Status shows configured/active/alive/draining separately, current/desired assignments, count/next ordinal, shared checkpoint roles, and precise hold reason | R03, R05, R10, R11 |
| A38 | Migration preserves existing approved text/locks/IDs/order/count evidence and does not infer completed count from attempts | R16 |
| A39 | Completed historical topics stay completed; catch-up reviews are bounded and auditable | R07, R16 |
| A40 | Invalid/all-or-nothing group updates and stale queue revisions never leave a partially applied fleet/order | R02, R04, R11 |

Run relevant existing queue/runner/intake/state tests with the new boundary tests.
Run MCP wire tests in an environment containing the optional dependency; the
earlier review's missing-dependency errors are not an acceptable final pass claim.
Use production-path integration for counting and cascade, process/crash injection
for recovery, permission tests for bypasses, and installed-package checks for prompt
locations. Do not create tests that merely echo setter implementation.

## 14. Mandatory self-check during implementation

Before every coherent edit group, record:

```text
Phase:
Requirement IDs addressed:
Acceptance checks to demonstrate:
Files and exact allowed edit purpose:
Ordinary-worker semantics affected: none / explain permitted boundary change
Existing concurrent edits inspected and preserved:
```

After the edit group, record:

```text
What changed:
Evidence/tests and actual result:
Ordinary prompt semantic diff reviewed:
Topic authority/evidence content changed by this implementation: no
New configuration/state authority accidentally introduced: no
Known unresolved issues:
Next bounded edit group:
```

Use a companion implementation progress record when implementation begins. Do not
check items off because code was written; link the evidence that demonstrates each
acceptance behavior. Retain failed checks until corrected and rerun.

Drift rules:

1. Every edited hunk must map to an R requirement and an allowed purpose in sections
   9/12. Remove or defer unrelated improvements discovered along the way.
2. If an internal research behavior change seems necessary, stop that dependent
   change and explain the conflict. Do not silently broaden this plan. Independent
   authorized boundary work may continue.
3. Preserve unrelated/concurrent edits; never use blanket restore/reset or wholesale
   prompt replacement to achieve a clean diff.
4. Do not add extra agent seats, review rounds, scientific rules, blanket permissions,
   topic fields, fallback formats, or tuning knobs merely because they are convenient.
5. When a schema/error is hard to satisfy, fix the schema implementation or user-facing
   guidance; do not add a bypass or tell an agent to hand-edit managed state.
6. Re-read R06/R08/R10/R13 before checkpoint, model, resumption, or prompt edits:
   complete 25 first; use the shared pair; restore preserved priority; preserve the
   ordinary research process.
7. At each phase exit, report the acceptance IDs proved, remaining failures, and any
   explicit design deviation. Amend the plan visibly if an implementation detail
   changes; do not alter the operator's scope by updating a checklist after the fact.

## 15. Definition of done and deliverables

Implementation is complete only when:

- All R01–R16 requirements have implementation evidence and all applicable A01–A40
  checks pass, including production finalization and permission tests.
- There is one authoritative station configuration, queue order, and central work
  ledger; no supported fallback can restore per-topic cadence/models or bypass intake.
- The operator's exact routine is demonstrated end to end: research 25, separate
  shared-agent checkpoint, optional standardized decision wait, preserved-priority
  cascade, research 26.
- Ordinary worker prompt/method diff is within the narrow allowlist, and existing
  approved topic/evidence content is unchanged by migration.
- CLI/MCP field references, examples, errors, status, and packaged checkpoint
  resources agree with the implemented schemas and behavior.
- Migration dry run, backups/recovery procedure, configuration preview, test results,
  and remaining deployment limitations are concrete and reviewable.

Deliverables: the bounded implementation diff, canonical schemas and examples,
packaged checkpoint resources, acceptance evidence/progress record, updated boundary
documentation/status, and migration/deployment procedure. Planning itself adds this
document and a supersession notice to the earlier review only; it does not launch
implementation or change live workers.
