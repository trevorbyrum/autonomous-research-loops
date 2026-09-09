# Research-loop mechanics review — 2026-09-09

> Historical review. The operator subsequently clarified that research iteration 25
> completes **before** a separate checkpoint, which never increments the research
> count; a central station work ledger owns the counts/reviews; checkpoints use a
> shared pair defaulting to station 1; and implementation is limited to boundaries.
> The [detailed implementation plan](2026-09-09-station-boundaries-implementation-plan.md)
> supersedes this review's proposed design where they differ. The older
> replace-iteration-25 convention below must not be implemented.

This is a review and proposed design, not an implemented change or an approved
migration. The review covered the live queue/config/service definitions, queue and
runner code, station draft, CLI/MCP operations, intake and approval, chassis prompts,
checkpoint protocol, semantic-state gates, scope-change tools, dashboard, deployment
helpers, and relevant tests. Live workers continued running during inspection.

The requested separation is sound. The underlying problem is that station ownership
is documented more strongly than it is enforced. Several supported paths still
express the older per-topic execution model, and some supposedly universal rules
exist only in prompts. Adding another config file without removing those paths
would preserve the ambiguity.

## Observed deployment

- During inspection, systemd research worker services 1, 2, and 3 were
  running; worker 1 held `classification-labeling`, worker 3 held
  `research-leverage`, and worker 2 held no research topic. This does not reconstruct
  the earlier reported state with workers 2/3 active instead of 1.
- Live station profiles in `state/queue.json` had intervals `[0, 1800, 1800]` for
  workers 1–3. There were no profiles for workers 4/5. Every research item's
  `repeat_seconds` was zero at inspection. The current profile values themselves
  therefore obey the requested monotonic order; the enforcement gaps remain.
- `research-loops.toml` still says `workers = 1` and default topic repeat 900.
  The running systemd workers do not consume that count. Model defaults also exist
  in the installed systemd unit, separately from station profiles.
- All 47 research items had completion locks, schema version 2, and the expected
  TOPIC, AUTHORITY, QA, and scope-proposal files. Forty-four retained legacy
  `agent_main = claude` fields. File presence is not proof of validated intake.
- The checkout already contained untracked `research_loops/stations.py`. It is
  disconnected from the live implementation. This review did not modify it.

## Findings

| Priority | Finding and consequence | Evidence |
|---|---|---|
| High | No authoritative active-station count. `workers` is a process-launch convenience, not a claim eligibility rule. Independently launched workers can claim research regardless of that count. | `workers.py:start`; `__main__.py` workers/run branches; `queue.py:claim_next`; installed systemd template |
| High | Station interval validation covers only explicit interval updates against existing profiles with the same naming prefix. Missing profiles default to zero; profile clear and model-only creation can violate monotonicity. The five-station check applies to profile edits, not worker execution. | `queue.py:configure_worker_agents`, `_station_interval`, `claim_next` |
| High | Topic cadence still overrides the intended station separation: actual delay is `max(item.repeat_seconds, station.interval)`. A high-priority topic can consequently run less often than a lower-priority topic despite valid station profiles. | `runner.py:run_once`, around line 1294 |
| High | Queue reorder does not rebalance already-owned topics. The sticky-owned-topic path returns before cascade selection, so moving B ahead of A leaves fast station 1 working A while slower station 2 keeps B. Manual reassignment can likewise bypass priority. | `queue.py:move`, `claim_next`, `reassign_worker` |
| High | The tested boundary transfer is not the production boundary transfer. `mark_scheduled` honors reservations, but the live runner calls `finalize_run`, which does not transfer them. The former owner can reacquire before the faster worker polls. | `tests/test_cascade.py`; `queue.py:mark_scheduled`, `finalize_run`; `runner.py:run_once` |
| High | Reservations are overwritten without comparing existing reserved station priority. Worker 2 can replace worker 1's reservation on worker 3's topic. | `queue.py:claim_next` assignment to `reserved_for` |
| High | Success pacing and failure retries share `backoff`/`next_eligible_at`. Cascade clears the deadline for either, so it can erase a future subscription-limit retry deadline as though it were just station pacing. | `queue.py:claim_next`, `mark_scheduled`, `mark_backoff`, `finalize_run` |
| High | Checkpoints have no implemented scheduling/accounting state. No durable completed ordinal, due trigger, episode ID, inventory review marker, budget, or trusted run kind is supplied. A valid unchanged checkpoint would currently count toward saturation. | `docs/obligations-checkpoint.md`; `chassis/run-topic.sh` result writer; `runner.py` saturation branch |
| High | Research admission is bypassable through supported APIs. Generic `add` and `sync` do not require the intake workflow, a valid topic directory, or a completion lock. Generic one-shot jobs can occupy the research lane. | `queue.py:add`, `_definition_from`, `claim_next` |
| High | Approval and registration are not one recoverable operation. Approval renames drafts before structural validation. A validation failure leaves an apparently approved directory; an MCP queue-registration failure leaves a promoted but unqueued topic, and retrying approval refuses. | `topic_authoring.py:approve_topic`; `mcp_server.py:approve_and_queue` |
| Medium | Intake format is mostly a prose agreement. Approval checks headings and nonempty operator text, and requires a scope-proposal file, but does not validate a structured discovery result tied to the current draft. The discovery runner only checks a nonempty file, so stale output can satisfy a later no-op run. | `topic_authoring.py:approve_topic`; `chassis/run-discovery.sh`; discovery/review prompts |
| Medium | CLI and MCP intake diverge. CLI approval emits a hand-copied add command; MCP registers with its own hardcoded defaults. CLI discovery supports approved-topic review and removes/re-adds prior nonrunning passes; MCP discovery only accepts drafts and repeated IDs conflict. | `__main__.py` discover/approve branches; `topic_authoring.py` suggested command; `mcp_server.py:start_discovery`, `approve_and_queue` |
| Medium | Model assignment has multiple authorities. Topic fallback, station profile, service environment, adapter defaults, and model names embedded in prompts can disagree. A secondary-only station profile is ignored unless that profile also specifies `agent_main`. | `runner.py` child environment; `chassis/run-topic.sh` AGENT_NOTE/CITATION_NOTE; `chassis/CONTRACT-CORE.md`; installed service |
| Medium | Unknown config and manifest fields are not consistently rejected. Misspelled/new settings can be silently ignored. Topic scaffolding enforces lowercase hyphen slugs while generic queue admission accepts uppercase, underscores, and dots. | `config.py:load_config`, `_settings_from`; `queue.py:_definition_from`, `validate_item_id`; `topic_authoring.py:new_topic` |
| Medium | Scope mutation is still split across file edits, rehashing, and relocking. The gap tool uses recent log writes as an activity heuristic, takes the auto allowance from its caller, and does not enforce proposal origin or update the queue lock. This cannot enforce checkpoint promotion rules or a trusted proposal budget. | `chassis/gap-policy.py`; `queue.py:set_completion_lock`; agent-operations guidance |
| Medium | Operational documentation contradicts itself. Agent-operations still recommends the deprecated item `agents` command; config examples still teach per-topic cadence/models; architecture describes sticky ownership and station-only behavior together. Operations says sync refuses lock changes, but code permits them for nonrunning items. | `docs/agent-operations.md`; `config/research-loops.example.toml`; `docs/architecture.md`; `docs/operations.md`; `queue.py:sync` |
| Medium | The unfinished station module would introduce another partial authority. It uses a cap of 32 versus the live cap of 5, preserves the same missing-profile/clear holes, and claims migration behavior that the queue has not implemented. | untracked `research_loops/stations.py` |
| Medium | Status does not adequately distinguish configured, enabled, process-alive, assigned, waiting for cadence, reviewing, and awaiting a decision. MCP projects legacy per-topic model fields; `workers status` only sees workers launched by its PID-file manager. | `dashboard.py`; `mcp_server.py:_STATUS_FIELDS`; `workers.py:status` |

The checkpoint reference also lives in repository `docs/`, while package data ships
chassis prompts and templates but not those docs. Runtime instructions should not
depend on an unpackaged reference or private deployment-specific document.

## Recommended ownership

| Component | Owns | Does not accept from a research topic |
|---|---|---|
| Station configuration | Active research count; station identities; primary/secondary and review-role profiles; interval seconds; common checkpoint policy; retry/stall/saturation execution policy and operational hooks | Topic-specific model or cadence overrides |
| Topic contract | Operator intent, scope, exclusions, obligations, deliverables, true dependencies, approved research/access policy, approved inventory identity | Arbitrary runner commands or fleet control |
| Queue | Stable topic IDs, explicit priority order, eligibility/control state, assignment references | Hand-built execution definitions |
| Scheduler/runtime | Assignments and reservations; iteration leases; pacing and retry deadlines; run type; per-topic completed ordinals; checkpoint episodes/budgets and inventory review markers | Agent-selected run type, invented counters, caller-supplied budget resets |
| Intake and scope service | Validated draft records, discovery results, operator decisions, promotion/amendment transactions, canonical rendering and automatic registration | Freeform replacement of machine-owned files |

These are ownership boundaries, not a demand for five separately mutable files.
Use one canonical station config and one transactional runtime authority. If TOML is
the canonical operator config, CLI changes must update that same config through its
validator; do not keep independently authoritative TOML and station JSON copies.
SQLite can simplify runtime transactions, but converting storage alone would not
fix these rules. Generated Markdown/JSON views are useful for inspection and should
be treated as outputs.

### Station configuration and assignment

Use `active_count = N`, meaning exactly research stations 1 through N, with 0 allowed
for a stopped fleet and a maximum of 5 unless deliberately revised. Keep intake
capacity separate. Validate the entire proposed config atomically, including
defaults and inactive configured stations: `interval[1] <= ... <= interval[5]`.
Reject malformed/unknown keys and unknown research station identities. Never map a
missing profile to a zero-delay runnable station.

Store each role as explicit adapter/model/argument data. The primary and secondary
can use different models on each station or the same ones across the fleet. Keep
the independent verification invocation requirement separate from the model name.
Checkpoint preparation/counter roles should also be explicit configured roles;
generate prompt instructions from the resolved role configuration instead of
hardcoding Luna/Terra in otherwise configurable chassis text.

A single assignment operation should reconcile ranked eligible topics against
enabled stations at startup, reorder, enable/disable, completion, resume, config
change, and iteration boundaries. Deterministic station-number order should break
equal-interval ties. Exclude paused, awaiting-review, completed, dependency-blocked,
and retry-ineligible work according to explicit rules. Represent unhealthy enabled
stations visibly and recover their supervisor; do not silently redefine station
priority based on whichever process happened to poll first.

At a boundary, apply all pending ownership changes atomically. In-flight iterations
finish under their existing lease and configuration revision. Lowering active_count
drains higher stations and forbids further launches; increasing it enables the next
contiguous stations. Enforce this in the claim and spawn path, independently of
whether a process was started by systemd, CLI, or manually.

Use separate pacing and retry fields. A transfer may remove the previous station's
pacing wait. It must not silently remove a relevant failure retry restriction; a
provider-specific retry restriction can be reevaluated only through an explicit
policy when the execution profile changes.

Define interval precisely as the delay after an iteration finishes, matching the
current implementation. It orders configured pacing, not actual wall-clock
throughput: different models and topic tasks take different amounts of time.

### Checkpoints

One shared station policy should initially specify:

```toml
[stations.checkpoints]
enabled = true
every_completed_iterations = 25
on_deepening_entry = true
on_proposal = "await_operator"
```

This is proposed syntax, not a currently supported configuration.

The policy belongs to stations; checkpoint history belongs to the topic runtime.
Moving a topic, changing models, restarting a service, or changing active_count must
not reset the topic's count, pending checkpoint, reviewed inventory, or allowance.

Preserve the existing protocol's precise ordinal convention: after 24 accepted
completed passes, ordinal 25 is a review, not a 25th research pass followed by a
26th review. A successfully completed checkpoint counts once; failed/interrupted
attempts do not consume its ordinal. Persist a separate research-pass count if useful
for reporting. Trigger the first valid entry into deepening for each approved
inventory version, coalesce simultaneous triggers, and give already-deepening active
topics one catch-up review. Do not reopen completed topics solely for this purpose.

After finishing the current iteration, switch the same queued topic into
`obligation_review`. Retain the queue item, priority, and history. Supply the trusted
run type, ordinal, triggers, inventory identity, episode ID, prior review and
remaining budgets. Incomplete reconciliation keeps the checkpoint due. Successful
zero-proposal review resumes research automatically.

The user's requested behavior implies pausing when proposals are produced. Make
that `awaiting_operator_review`, not an ordinary failure or a STOP-file convention.
It keeps the topic's queue position but releases station capacity for other eligible
topics. An operator decision resumes it at the next safe assignment boundary;
approved scope changes update inventory and lock together. This differs from the
current protocol, which says optional pending proposals do not block completion.
The behavior change must therefore be explicit in both code and prompts. Continuing
approved work while proposals wait could be a future selectable policy, but should
not be an implicit exception to the requested pause.

Checkpoint-only work neither advances nor resets the saturation/stall streaks.
Actual evidence changes, changed inventory, invalid coverage, and research blockers
retain their normal invalidation effects. Completion must not slip past a due or
unfinished mandatory review. Validate a structured review result and enforce
delegate launches, deadline, proposal count, origin, and approval operations in code.
Persist budget charges before launching work so retries cannot refill them.

Keep versioned checkpoint prompts/protocol beside the station execution code and
ship them as package data. Preserve evidence/authority rules in the topic contract;
do not confuse configurable scheduling with permission to change scientific scope.

### Intake and queue operations

Expose one intake workflow used by both CLI and MCP:

`submit brief -> canonical draft -> discovery/criteria pass -> operator decision -> validate and promote -> automatic queue registration`.

Automate discovery-job registration when submitting a draft and research-topic
registration after promotion. Operator scope approval remains a distinct decision;
automatic insertion must not mean automatically accepting discovery proposals.

Use strict versioned schemas for draft contracts, QA/discovery output, decisions,
and proposals. Agents submit structured values through operations; code renders the
Markdown and semantic-state shape. Reject unknown fields, invalid IDs, missing
traceability and missing decision fields. Bind discovery results and approval to the
exact draft revision/hash. Schemas can enforce complete records and consistent
formats; they cannot prove that a scientific question is well chosen.

Validate before publishing binding files. Make promotion plus registration
idempotent and recoverable with a transaction/staged publication protocol; duplicate
requests should return the existing result. Repeated discovery should retain episode
history and reject stale output. All scope amendments should use the same protected
mutation boundary, including checkpoint proposals and any retained ordinary-gap
auto-promotion policy.

Remove generic job creation from the research admission surface. If generic jobs
must remain supported, give them an explicit separate kind/lane. Migration/import
must validate the same research schema; it cannot be a back door around admission.

Keep reorder separate from admission. Provide relative operations such as
`queue move classification-labeling --before research-leverage` and an atomic full
ordered-ID operation with an expected queue revision. These are proposed commands.
Reject invalid positions and duplicate/missing IDs instead of silently clamping or
rewriting definitions. Return the resulting order and any assignment changes that
will land after in-flight work. Deprecate `swap-active` or translate it into a valid
priority change; do not maintain a second priority authority through manual claims.

### Making the boundary enforceable

Today the workers run as the same user with unrestricted filesystem access.
Prompting an agent to use a CLI cannot prevent it from editing queue/config files
directly, calling a low-level Python API, or granting itself a larger gap budget.
The existing operator/read-only MCP split is useful but does not close that shell
access route.

If “agents cannot touch the file” is literal, the controller must be the only writer
under a separate permission boundary. Give research processes only topic work and
the permitted state/proposal operations; expose queue ordering, station config,
approval, relock, and budget reset only to the operator control surface. Apply that
separation to installed code and canonical contract files as well as runtime state.
A single-writer service with scoped CLI/MCP clients is an appropriate design. This
is the difference between enforcing a rule and relying on agent compliance.

## Verification and implementation order

Temporary-queue reproductions confirmed all of the following without changing live
queue state:

1. Unconfigured worker 4 claims the head topic at interval zero.
2. Clearing worker 2 changes valid intervals `[10, 20]` into `[10, 0]`.
3. Creating only worker 2's model profile also permits `[10, 0]`.
4. Moving B ahead of A does not move station 1 off A.
5. Worker 2 overwrites worker 1's reservation on worker 3's topic.
6. Cascade clears a retry deadline in 2099 and immediately claims the topic.
7. Generic research admission accepts a nonexistent topic directory with no lock or
   intake and an ID the scaffolder would reject.
8. An unknown manifest interval field is silently ignored.
9. Actual `finalize_run` leaves a reservation unapplied and permits the slower
   station to reclaim first.

`python3 -m unittest discover -s tests -q` ran 388 discovered test entries: 385 passed
and 3 errored because the optional `mcp` package is absent (two registration tests
and the wire-test module import). There were no assertion failures. Pytest is also
not installed. Existing passing cascade tests do not cover the production
finalization defect. The test output is at
`/tmp/research-mechanics-review-tests.log` for this session.

Recommended implementation sequence:

1. Freeze the new schema/ownership contract and migration rules. Inventory legacy
   topic cadence/model values and require an explicit conversion; never retain
   hidden compatibility overrides. Preserve history, locks and active child leases.
2. Implement active_count and transactional assignment reconciliation, then remove
   duplicate scheduling/finalization paths. Cover actual runner boundaries,
   concurrent claims, reservations, reorder, equal intervals, disabled/unknown
   workers, graceful drain, crashes and pacing/retry separation.
3. Unify intake and scope mutation behind strict schemas and recoverable operations;
   wire both transports to those same functions and close bypass paths.
4. Implement checkpoint execution and persisted accounting before enabling the
   shared default. Cover ordinal 25, deepening/coalescence, retries, moves, restarts,
   scope changes, zero proposals, pending decisions, budget exhaustion, and
   saturation/stall exclusion.
5. Apply the required process/filesystem boundary, then replace outdated docs,
   examples, runtime prompt references and status views in the same release. Status
   should expose config revision, enabled/alive/busy counts, ordered assignments,
   effective role profiles, pacing/retry reasons, next checkpoint and review state.

Only this review document was added. No live configuration, service, topic, queue,
or implementation file was changed by the review.
