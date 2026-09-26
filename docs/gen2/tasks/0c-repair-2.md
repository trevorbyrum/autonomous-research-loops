# Task 0c-repair-2 — close the three narrow BLOCKs (spec/test repair, no engine logic)

Read first: `~/work/research-loops-public/private/reviews/gen2-0c-repair-astra-review-20260926.md` (BLOCK 1–3 give exact counterexamples and required repairs; follow them as written). Everything else in 0c/0c-repair is CLOSED or ACCEPTED: A1, A3, A4, A5's SQL contract, A6, the schema-level A2 fix, the counting checker, and the 0a audit fixture edits (ACCEPTED as bounded redundant-guard checks). Don't reopen them.

## BLOCK 1 (HIGH): the webhook ack overclaims (EXPORT-SINKS.md ~§5.3)
A 2xx, e.g. `202 Accepted`, doesn't prove the whole manifest and its tombstones were applied, and a 4xx doesn't prove nothing was applied. Specify the receiver protocol a webhook sink must implement to be admissible:
- which success response means durable application of the entire manifest and tombstones;
- which refusals guarantee no partial application;
- an asynchronous or queued acceptance stays `outcome_unknown` pending reconciliation until stronger evidence arrives.

If you intend durable enqueueing to count as delivery, define that boundary explicitly and make the receipt's count and tombstone semantics match it. Never equate enqueueing with applying. An echoed idempotency key is not required (Astra's ruling). Name Phase-3 acceptance cases: queued-then-rejected, whole-request acknowledgement, atomic refusal.

## BLOCK 2 (HIGH): webhook ordering doesn't implement the four branches
Engine-side receipt watermarks plus per-key dedup fail in two ways, both of which Astra showed with a real receiver:
1. same pair, different manifest ID and content → applied instead of `conflict`;
2. an older in-flight request lands after a newer one → state regresses.

Required: the webhook receiver itself must retain and atomically enforce the per-topic ordering pair, the immutable manifest/content identity and the tombstone evidence, i.e. the same four branches as SQL §5.1. Alternatively, specify an equivalent protocol that proves all four under crash and concurrency. Engine-side skipping may stay as an optimization, but it isn't the correctness boundary. Don't relax the no-stale-overwrite invariant for generic endpoints; an endpoint that can't honor it isn't an admissible webhook sink. Add both counterexample traces as named Phase-3 acceptance cases. Keep the receipt schema consistent with whatever you specify.

## BLOCK 3 (MEDIUM, Gate C): identity-member coverage can be fooled by errors trading places
Add three isolated negatives, each starting from `valid-research-pass-running.json` and removing only `/process_identity/host_id`, only `boot_id`, or only `start_fingerprint` (each yields exactly one `required` error). Bind a mutation to each. Show that Astra's compensated mutant (remove `host_id` from `process_identity.required` and add `"allOf":[{"required":["boot_id"]}]`) is now rejected; add it to the declared inventory or an equivalent counterfactual test. Keep the bare-identity regression. Fix `gen2/tests/test_schema_counterfactuals.py` lines ~18–20: the blanket claim that every kill means its negative validates is false for the count-based audit kills. State what each kind of kill proves.

## Constraints (unchanged)
Branch gen2 only. No engine logic. Never touch `gateway/`, gen-1, running services or main. Don't edit BOUNDARIES.md or INVARIANTS.md. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status: run it with output redirected and read `$?` directly.

## Completion report
For each BLOCK: what changed, how each counterexample is now excluded (spec clause, or fixture/mutation), and the final unpiped `make gen2-check` exit status and counts. Write the report as your final message. Don't end your turn waiting on a background run.
