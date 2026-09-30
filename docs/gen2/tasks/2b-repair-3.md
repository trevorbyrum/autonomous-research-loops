# Task 2b-repair-3 — close R2's current-snapshot residual

Read: `~/work/research-loops-public/private/reviews/gen2-2b-repair-2-astra-review-20260930.md` in full — R2's remaining defect has two exact reproductions and a required repair; evidence and a runnable repro bundle under `/tmp/gen2-2b-repair-2-astra-review-20260930/` (`probes.py` functions `r2_sequential`, `r2_race`, `r2_repeated_content`; run with `python3 -B /tmp/gen2-2b-repair-2-astra-review-20260930/probes.py`). **R1 is CLOSED — don't touch it.** A1, A2, A4, A5, A7, A8 remain accepted — don't reopen them. Gate B PASSED. The live gen-1 gateway boundary held through all three prior rounds and must keep holding — never touch `~/work/staging/research-gateway-wt` or `research-gateway.service`.

**This is narrower than the prior round's disclosed limitation.** The 2b-repair-2 coder disclosed a "brief" ordering gap as an acceptable residual. Astra's independent reproduction shows it's not brief — the current status fact can stay stale **indefinitely**, through both a genuine race and, separately, through fully ordered normal recording when a failure detail returns to a value seen earlier in the same outage. This needs an actual fix, not just disclosure.

## The finding (follow the "Required repair" as written)

**R2, remaining (MEDIUM) — the engine's *current* capability fact can remain stale after reordered recording or an ordinary return to previously observed contents.**

`gateway_fact_id` (`gen2/core/canonical.py:157`) identifies an outage episode plus its *mutable contents* (state, affected lanes, failure detail) — it does not identify *when* that snapshot occurred. The router (`gen2/router/capabilities.py:193`) treats any **previously unseen** ID within an episode as the new current snapshot, and any **previously seen** ID as a pure replay that leaves current untouched. Two concrete failure modes result:

1. **Reordering:** invocation A observes a narrow snapshot (FRED only) before invocation B observes a wider one (FRED+GovInfo) from the same outage, but B's write lands first. B correctly becomes current. A's delayed write is a previously-unseen ID too, so it also "supersedes" — leaving current back at the *narrower* snapshot, even though B's wider snapshot is objectively newer and has since been reconfirmed by a fresh GovInfo request.
2. **Recurrence, no race at all:** a single invocation, fully sequential, observes state 403 (fred) → 403 (fred+govinfo) → 503 (fred+govinfo) → a **fresh, later** read that happens to return 403 (fred+govinfo) again. That fourth read is a brand-new gateway call and a brand-new observation — but its content hashes to the *second* snapshot's already-seen fact ID, so the router treats it as a pure replay and leaves the *third* snapshot (503) as current, even though the fourth read is objectively the most recent information.

Every affected observation still correctly links to its own accepted fact (history is fine) and stays `provider_unavailable`/no-count (this is not a false-evidence or permission-widening bug) — only the router status surface's notion of "current" gets stuck.

**Required repair:** distinguish a snapshot's *source ordering/occurrence* from its *contents* and the outage's *onset* — or provide an equivalent governed representation that achieves the same thing. Specifically:
- A delayed write from the same episode must retain the history its own observation needs, without incorrectly replacing an objectively newer current snapshot (fixes reproduction 1).
- A genuinely later occurrence of previously-seen content must be distinguishable from an exact idempotent replay of the same recorded fact (fixes reproduction 2) — i.e., "the gateway told us this again, now" is not the same event as "the same recorded fact command was resubmitted."
- Preserve everything that already works: the outage's onset time, each observation's reference to its own accepted snapshot, exact replay behavior, refusal of a previously-unseen genuinely older episode, and the same-onset/different-state conflict check.
- **Do not** just make every previously-unseen-by-content submission always become current unconditionally on replay — Astra explicitly warns this reintroduces the original delayed-retry regression this whole finding chain started from.

Add both of Astra's reproductions as regression tests — the two-process reordering race and the single-invocation sequential-recurrence case — asserting on **current status**, not just on historical observation joins (the existing tests only checked the latter, which is why this slipped through).

## Budget
Engine 9,690, gateway service 9,158 — both well under their limits/triggers. Keep this repair narrow; report net lines.

## Constraints
Branch gen2 only. Never touch gen-1's live deployment, running services, or main. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (what changed, both reproductions now handled correctly, mutant evidence, net lines, final unpiped `make gen2-check` and `make gen2-gateway`). Don't end your turn waiting on a background run.
