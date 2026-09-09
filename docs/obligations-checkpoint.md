# Obligations checkpoint — framing review and proposal protocol

Read this when the queue or operator assigns a checkpoint, or when a ready
ordinary-research proposal needs its bounded challenge. It is not per-iteration
reading. Nothing here changes binding scope: scout/checkpoint-origin proposals, their
revisions, and ALL amendments require operator promotion regardless of gap_policy.
An eligible ORDINARY research gap retains the contract's documented `gap_policy=auto`
exception within its remaining allowance; using this document's admission/challenge
procedure does not erase or change a proposal's origin. (Adopted from the operator-accepted design in
`private/reviews/scout-debate-design-astra.md`, as amended by the 2026-09-08 prompt
review; model seats now resolve from the shared checkpoint primary/secondary
configuration, with fresh invocation identities preserved.)

## Scheduling (station-owned)

The central station work ledger records completed research iterations per topic.
With the default cadence, research 25 completes first, then a separate checkpoint
runs, and research resumes at 26. Checkpoints, decisions, discovery and failed or
interrupted research attempts never increment that count. The next cadence
checkpoint follows completed research 50. A queued topic retains its identity and
priority while proposals await a standardized operator decision.

Also schedule the first entry into deepening for each approved-inventory version.
Persist that entry marker; ordinary status churn does not reset it. Coalesce
coincident cadence and entry triggers. Give an active topic already in deepening one
catch-up checkpoint if that inventory has not been reviewed. Do not restart a
completed topic or prolong its run just to reach a checkpoint.

Reconcile pending evidence before substantive checkpoint review. If reconciliation
consumes the pass, record that the review remains incomplete and due. Reuse a prior
complete review with zero delegate calls when approved framing, material
evidence/coverage, discipline, and operator feedback are unchanged. Growing logs and
timestamps are not changed research context; incomplete coverage cannot be reused as
a complete review.

The station controller supplies the execution kind, completed research ordinal, triggers, inventory
version, checkpoint episode ID, prior review reference, remaining proposal
allowance, and remaining episode budget. Until those inputs are supplied, do not
invent a cadence, allowance, or reset from model memory. Continue authorized
ordinary research and preserve signals; run a checkpoint only with an explicit
operator assignment that supplies its limits.

## Signals (ordinary iterations)

During ordinary evidence work, preserve at most one supported question-shaping
signal, about 100 words, when one arises; do not generate filler. A signal names:
exact anchor; the assumption or question it challenges; the nearest existing
obligation; the possible consequence; the uncertainty. First route it to existing
approved work if that work already covers it. A source author's "future work"
suggestion is a lead, not automatic eligibility. A retrieval outage is a capability
signal, not an evidential gap. A fruitless deepening pass does not itself launch a
checkpoint.

## Review procedure

Read the current operator mission, exclusions, approved obligation texts, and
proposal decisions directly. Use the current inventory version; invalidate older
novelty assessments after any promotion or amendment. An approved new obligation
becomes ordinary research work and is no longer a scout candidate; its proposal or
debate provenance does not verify the eventual research claims.

Framing review comes before gap scouting: do the existing questions identify the
right construct, comparison, unit of analysis, population, outcome, and decision
consequence? Does any wording presuppose an answer, combine incompatible
comparisons, exclude a live alternative, or treat a context-dependent answer as
universal? A framing defect may call for amending one obligation, acknowledging a
bound, or doing nothing.

Before reading the counter, the primary records a short provisional framing
assessment and what would make any candidate unnecessary. Give the counter the
operator mission and exclusions, complete concise inventory, candidate cards without
preference ranks, relevant corpus passages and limitations, prior proposal
decisions, and material negative searches or near-misses. Include directions absent
from the advocate's shortlist; zero advocate cards still warrants a framing check at
a due full checkpoint.

The fresh configured-primary counter reconstructs each candidate's strongest rationale, gives its
strongest substantive objection with a locator or explicit inference, and compares
the slate with amendment, existing work, and no change. Label objections EVIDENCE,
INFERENCE, SCOPE, DUPLICATE, CAPABILITY, or PRIORITY. It may offer one overlooked
alternative under the same admission rules and within the slate cap. Do not
manufacture opposition or treat an unknown answer as a defective proposal. If
essential context is missing, name the missing passage and report limited
assessment.

The primary reads the complete bounded exchange and the load-bearing passages,
dispositions each material objection, and explains why the best competing direction
loses or remains a trade-off. It may disagree with either delegate. State what
changed from the provisional assessment and why.

A counter-originated alternative or materially new primary rewrite/merge is a new
candidate version, not an independently reviewed result. If it is to become a final
proposal, use the single remaining repair exchange, if available: a fresh configured-secondary
invocation prepares that fixed version and its strongest case; a fresh configured-primary
invocation, distinct from any invocation that originated it, challenges that
version. Apply the same budget and admission rules. If that review cannot fit or a
further material change remains unchallenged, retain a signal instead of issuing an
approval-ready proposal. Minor wording corrections that preserve the question and
reasoning do not require another launch.

## Admission (before ranking)

Apply the next-question discipline before ranking candidates. Each candidate must
include: (1) exact corpus anchors and locators, separating established observations
from the inference that motivates the question; (2) the evidence target and
legitimate route, including support, complication, null, and unresolved outcomes;
(3) the nearest existing obligation and prior proposal, and why ordinary work under
that obligation cannot answer this question; (4) what each plausible answer would
change for the topic; and (5) the strongest objection or competing direction, the
primary's response, and unresolved access or capability dependencies. A missing
admission requirement cannot be averaged away by novelty or priority.

For an addition, give the exact proposed obligation text. For an amendment, give the
target ID, exact current and proposed text, the framing defect, and changes to
research burden, acceptance criteria, deliverables, and reusable evidence. Scope
changes outside the current mission go to an explicit operator scope request.
Ordinary status or confidence corrections remain ordinary evidence work. Rank only
admissible cards; route covered questions to existing work, and permit no change.

Use the reviewed operational version of the next-question discipline. Until that
version is published, the operator-provided `private/next-question-discipline-draft.md`
is advisory context, including its explicitly provisional examples; it does not
supersede topic authority or authorize new research.

## Budgets and limits

Use zero to three candidate cards, at most 250 words each. Include amendments in
that count. The counter may offer at most one alternative within the same three-card
working limit; record why a card was displaced. Produce zero to two final proposals
per episode, no more than two newly issued proposals per topic between explicit
operator review/resets, and no more than two pending proposals at once.
Ordinary-research proposals and amendments share these limits. A retry, checkpoint,
revision, withdrawal, or individual promotion does not by itself refill the issuance
allowance. Do not resubmit a rejected idea without a named material change in
evidence, capability, approved framing, or operator feedback.

A normal full checkpoint uses one configured-secondary preparation/advocacy invocation, if needed,
and one fresh configured-primary counter invocation over the entire slate. Reuse an adequate
preparation packet instead of requiring a new secondary call. After that counter pass,
the primary may name one decisive dispute for one repair exchange: one fresh secondary
response followed by one fresh primary assessment. There is no per-card debate loop,
second repair exchange, or consensus requirement.

Allow at most four delegate launches for the checkpoint/associated proposal episode,
including its preparation, counter, repair, retries, and any citation checks needed
solely to admit its proposals. Preserve the episode identity and spent budget across
retries. If fewer than two launches remain, omit the two-call repair exchange. Keep
unresolved admission prerequisites as signals; budget exhaustion does not make a
proposal ready. Required work on already approved obligations remains governed by
its ordinary duties, not by this optional proposal budget.

Target a 6–8k-token evidence packet and a task-visible request below 12k tokens per
delegate. Keep preparation output near 1.5k tokens, counter output near 1k, and each
repair reply near 600; target about 4k generated tokens for the whole exchange.
Preserve complete concise inventory coverage; report limitations if essential
context cannot fit. Target five minutes for the episode and stop optional expansion
at ten; bound each delegate by roughly three minutes and the remaining episode time.
Runtime limits require runner support; these prose targets are not a claim of
enforced termination.

When allowance is exhausted, preserve ordinary findings and signal pointers,
identify the pending operator decisions, and skip new card development and debate.
Zero proposals is a valid result.

## Records and accounting

Debate supplies decision arguments, not scientific evidence. The primary may record
candidate dispositions, objections, and a reference to the bounded exchange in
DECISIONS-LOG.md as decision provenance. Cite the underlying corpus records
separately for factual premises. A debate transcript, model agreement, or operator
promotion never serves as a semantic evidence_ref or verifies a research claim. Any
new or corrected factual claim entering the research evidence ledgers follows
ordinary sourcing and independent verification. Delegates return their arguments;
the primary writes the decision records and proposals.

Keep one complete bounded checkpoint record (`logs/obligations-checkpoint-<stamp>.md`)
with the manifest (topic, ordinal and triggers, inventory version,
evidence/packet identity, prior review, remaining allowance, roles, launch identity
where available, failures, coverage limits), candidate versions, verbatim short
delegate outputs, and final dispositions. Preserve even a zero-card full counter
assessment. If a repair exchange occurs, record it in `logs/scout-debate-<stamp>.md`
and link it; no repair exchange means no debate file. Do not fabricate unavailable
launch or observed-model telemetry.

Question signals, debate, and pending proposals are decision records, not scientific
evidence or semantic progress by themselves. Do not add them to
pending_evidence_refs or use debate transcripts as evidence_refs. Keep pending
proposals visible for operator review without making their approval a new completion
requirement.

A checkpoint/scout review is not a qualifying deepening pass merely because the
semantic state is valid and unchanged. Report its iteration type accurately. The
saturation exclusion belongs to station mechanics. The controller records a
separate checkpoint lease and durable episode in `state/control.sqlite3`, then
invokes the packaged `checkpoints/prompts/protocol.md` through the shared resolved
pair. It does not launch an ordinary research iteration or increment/reset its
saturation/stall streak. Defaults are cadence 25 and deepening-entry enabled;
configure them through `stations --file` (see [managed stations](managed-stations.md)).
Only a station-assigned separate checkpoint receives this exclusion:
self-reported type or progress flags cannot supply it, and checkpoint-only work
must never run inside an ordinary self-initiated pass. Actual evidence changes
and research blockers retain their ordinary effects under the queue's rules. If a
checkpoint also reconciles material evidence, report that work separately; do not
relabel the whole pass "deepening" to make it eligible.
