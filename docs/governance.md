# Governance

Short, because the rules are short. This is the page that most determines whether the
engine produces trustworthy output or just confident-sounding output.

## The operator owns scope

An agent can tick obligations, cite evidence, and write ledgers. It cannot create a new
obligation, delete one, reword one, or redefine what counts as done. Every one of those
is a human decision, recorded as a `DECISIONS-LOG.md` entry and a hash update (see
`docs/topic-authoring.md`). This isn't distrust for its own sake — it's the only way to
make "the research is done" mean something. A system that lets its own research agent
adjust the definition of done under pressure will eventually adjust it exactly when
pressure is highest, which is precisely when you need it not to.

`TOPIC.md`/`AUTHORITY.md` hashes alone don't cover this: they prove those two files
weren't rewritten, not that `SEMANTIC-STATE.json`'s own obligation/deliverable inventory
still matches what was approved. `tools/approve-topic` and `research-loops add` both pin
a completion-inventory lock by default for exactly that reason — see
`docs/topic-authoring.md#the-completion-lock-why-topicmdauthoritymd-hashes-arent-enough-on-their-own`.

**The one configurable exception, and why it doesn't actually break the rule above.**
A topic's `gap_policy` defaults to `review`: an agent that finds a real, uncovered gap
may only propose it (a `PROPOSAL` row in `DECISIONS-LOG.md`); an operator promotes it,
by hand or with `chassis/gap-policy.py promote`. Setting `gap_policy = "auto"` (per
topic, via `add --gap-policy auto --gap-auto-limit N` or the declarative config — see
`docs/operations.md#declarative-config`) lets an agent self-promote a gap directly, but
only up to `gap_auto_limit` times since the operator's last review. Past that budget it
falls back to proposing only, and `chassis/gap-policy.py promote --auto` enforces the
cap itself — there's no path that bypasses it. Every self-promotion is tagged
`AUTO-PROMOTED` in `DECISIONS-LOG.md`, permanently distinguishable from an
operator-reviewed `PROMOTED` entry, and still goes through the exact same hash-relock
(`rehash`) as a manual edit. `auto` trades the *timing* of review (before the obligation
exists vs. within the next `gap_auto_limit` additions) for research throughput; it never
trades away the audit trail, the cap, or the fact that an operator's review-reset is what
lets the budget continue. Default to `review`; reach for `auto` only for a topic where
you've decided a small, bounded amount of self-directed scope expansion between reviews
is worth more than catching each one before it happens.

## The output is evidence, not a verdict

The engine doesn't decide anything. Its job ends at "every obligation has a graded,
evidence-backed disposition" — `supported`, `contradicted`, `unresolved`, or `deferred`,
each with its own evidence trail. It deliberately stops short of "and therefore the
answer is X" or "and therefore build it this way." That judgment call — weighing
sometimes-contradictory graded evidence into an actual decision — stays with whoever
reads the synthesis, same as scope stays with the operator. A topic that quietly
collapsed its own disposition into a single recommendation would be doing exactly the
thing §Contradictions warns against below: hiding the disagreement instead of assessing
it.

## Quota and tool failure are never evidence

If a search comes back empty because a rate limit hit, that is a fact about the
*capability* available this iteration — not a fact about whether the claim is true,
false, or unsearched. `CONTRACT-CORE.md` states this explicitly and `chassis/run-topic.sh`
propagates a capability notice into the prompt when a preflight check finds something
degraded (see `runners/README.md`), so an agent knows the difference between "I looked
and found nothing" and "I couldn't look." Conflating the two produces a false
`unresolved` disposition that looks identical to a real one until someone checks.

## Liveness and completion are different questions

A topic can be alive (making real changes every iteration) without being close to done.
A topic can also *stop* making changes without being done — that's a stall, and the
correct response is escalation to a human, never a mechanical `DONE`. No iteration
count, token budget, or elapsed time substitutes for the actual completion check. See
`docs/architecture.md` for the mechanism; this page is about why that mechanism exists
at all — a fixed budget is an invitation to declare victory at the budget, regardless of
what's actually been established.

## Contradictions are preserved, not smoothed over

If two admitted sources disagree, both stay recorded, with the disagreement itself
noted. A later iteration may resolve it with better evidence; nothing may quietly pick
a winner and discard the other. A research corpus that only ever shows agreement isn't
more reliable than one that shows its disagreements — it's one where the disagreements
were deleted.

## Pending-first review

Newly admitted evidence starts `pending`. A *later* iteration reviews and either
approves, corrects, or rejects it — never the same pass that admitted it. This is a
small, deliberate friction: a second look, even by the same kind of agent, catches
things a single pass under time pressure won't.
