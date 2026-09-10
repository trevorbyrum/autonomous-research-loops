# Checkpoint protocol

This is the packaged protocol for the separate checkpoint adapter. It is not an
ordinary research prompt and it never consumes an ordinary research ordinal. The
controller supplies the episode ID, topic and inventory identity, trigger IDs,
shared primary/secondary profiles, distinct invocation IDs, prior review reference,
and remaining budget. Do not invent any of those values.

## Scope and evidence

Read the operator mission, exclusions, approved obligations, prior decisions, and
the supplied inventory version. A checkpoint cannot change binding scope. Debate,
proposal, and operator approval records are decision provenance, never terminal
scientific evidence. Claims still need the topic's ordinary source and independent
verification rules.

Reconcile pending evidence before substantive review. If a necessary reconciliation
cannot finish, return an incomplete result with its exact prerequisite and limitation;
never present it as a complete zero-proposal review. Reuse a prior complete review
only where approved framing, material evidence/coverage, discipline, and operator
feedback are unchanged. Log growth and timestamps are not material context.

## Review procedure

Perform framing review before scouting: examine whether the approved questions use
the right construct, comparison, unit, population, outcome, and decision
consequence; whether wording presupposes an answer or hides a live alternative; and
whether a context-bound conclusion is being treated as universal. Record the primary's
provisional assessment and what would make a candidate unnecessary before the
counter's response.

Candidate cards require exact corpus anchors and locators, a separation of observed
fact from motivating inference, evidence target and route (support, complication,
null, and unresolved outcomes), nearest approved obligation/prior proposal and
non-duplication explanation, decision consequence, strongest objection/response,
and dependencies. Additions include exact new obligation text and source reference.
Amendments include target ID, current/proposed text, framing defect, and effects on
burden, acceptance, deliverables, and evidence. A mission change is a scope request,
not an ordinary addition.

The secondary prepares the bounded slate when needed. A fresh primary-class counter
invocation independently reconstructs each candidate's strongest rationale, gives its
strongest objection with locator or explicit inference, and compares the slate with
existing work, amendment, and no change. The primary reads the complete exchange and
load-bearing passages, dispositions objections, and explains the competing direction.
A materially changed candidate needs the single permitted repair exchange: a fresh
secondary response followed by a fresh primary-class assessment. Keep invocation
identities distinct even when configured profiles resolve to the same model.

## Enforced limits

Use zero to three candidate cards, at most two final proposals, one counter pass,
and at most one repair exchange. Preserve the controller budget across retries:
at most four delegate launches for the episode, including preparation, counter,
repair, retry, and proposal-only citation work. If fewer than two launches remain,
omit the repair exchange. Exhaustion or an unresolved admission prerequisite leaves a
signal; it does not make a proposal ready. Keep the existing approximate packet,
token, and time targets as targets, not new rejection conditions.

## Result

Return the strict checkpoint-result object required by the adapter. Include episode
ID, run ID, reviewed inventory version, all trigger IDs, explicit `complete`,
findings, limitations, protocol evidence references, and an explicit proposals array.
A zero-proposal result is valid only when `complete` is true and `proposals` is `[]`.
An incomplete result cannot issue proposals. Checkpoint work does not alter ordinary
research counts, stall/saturation streaks, or the ordinary completion predicate.

The exact packaged schema is `research_loops/schema/checkpoint-result.schema.json`.
Checkpoint reset is a controller operator operation, never a result field: submit
`{"schema_version":1,"request_id":"...","expected_revision":0,"topic_id":"...","reason":"..."}`.

The result has exactly these keys:

```json
{"episode_id":"...","run_id":"...","inventory_version":"...","trigger_ids":["..."],"complete":true,"findings":[],"limitations":[],"protocol_evidence_refs":[],"proposals":[]}
```

To run a bounded delegate, invoke `python3 -m research_loops.checkpoints.delegate`
with `--episode-id`, `--lease-id`, `--invocation-id`, `--role` (`preparation`,
`counter`, `repair_response`, or `repair_assessment`), and `--prompt`. The controller
uses the current lease capability from the environment, selects the matching snapped
profile, and records the launch before it starts. Do not run delegate provider CLIs
directly or invent an invocation ID/role outside this interface.

Use the exact ID at `delegate_invocation_ids[role]` in the supplied context.
One exception: if a role's call just failed for INFRASTRUCTURE reasons (broker
exit 70 or 124 — timeout, spawn failure, or empty response) and the broker
reports a refunded launch slot, you may retry that same uncompleted role once
with the same ID plus a `-retry` suffix; the broker enforces every budget, and
a semantically invalid result (exit 78) is never retryable this way.
`--lease-id` is the supplied `run_id`; `--episode-id` is `episode_id`.
The `counter` invocation is required even for a zero-candidate/no-change review,
unless the controller supplies a valid `prior_review_reference` and the final
result explicitly uses `reuse_of`. Preparation is optional when no candidate
slate needs it. Set the shell command timeout to at least 930 seconds so the
broker can finish its bounded delegate call. Broker output is JSON and includes
the recorded invocation and its output reference; inspect the complete report.
On a retry of this same episode, inspect the supplied `invocations` first.
A finished successful role already satisfies that role's invocation requirement:
read its recorded report and findings, and continue the review. Its supplied
delegate ID replays the recorded response without launching or spending another
slot. Do not request a second successful counter for the same episode.

Preserve the existing proposal discipline: no more than two pending proposals; no
issuance refill on retry, revision, withdrawal, or individual promotion; and no
resubmission of a rejected idea without named material change in evidence, capability,
approved framing, or operator feedback. Keep the complete bounded checkpoint manifest,
candidate versions, delegate outputs, final dispositions, invocation identities,
failures, and coverage limitations. Capability failure, missing context, or budget
exhaustion leaves a signal or incomplete review; none makes a proposal ready. Question
signals, debate, and pending proposals are decision records, never semantic evidence
or qualifying deepening. Controller-assigned checkpoint work is excluded from ordinary
saturation accounting while actual evidence changes and blockers retain ordinary rules.
