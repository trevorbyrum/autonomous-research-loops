# Task 1e-repair-2 — close the three remaining 1e items (narrow, likely final 1e round)

Read: `~/work/research-loops-public/private/reviews/gen2-1e-repair-astra-review-20260928.md` in full — findings 1–3 there (they are original findings 2, 3 and 7, as refined), with reproductions and evidence under `/tmp/gen2-1e-repair-rereview-20260928/`. Original findings 4, 5, 6 and 8 are closed; don't touch them. Finding 1 of the original review (the auth-volume demonstration) stays with the operator.

## 1 (HIGH): an unfinished recovery is durably recorded as closed
`Supervisor.recover_incident` saves `incident: null` and a recovery entry with `outcome: null` *before* `_advance`, and the replay predicate treats any outcome except `termination_unconfirmed` — including `None` — as complete. Astra's reproduction: real engine process, fault at `_advance` entry via `os._exit(71)`, replacement engine; retries then return `replayed` with `outcome: null` forever, the episode stays `outcome_unknown` with an open hold and an unreleased lease, and the incident vanishes from the supervisor's list.

**Repair (per the review):** persist an explicitly *unfinished* recovery; resume it under the same job lock after a lost response or replacement; return a completed replay only after the recorded work has actually completed. Keep pending-recovery visibility (the incident, or a pending-recovery record, must show in status), old evidence, the reconciliation-only hold rule, and the budget accounting. Tests: the exact process-exit reproduction (fault before reconciliation), a fault after reconciliation but before the reply, replacement-engine retries completing the work, and status visibility throughout; a bound mutant that restores complete-on-null.

## 2 (MEDIUM): credentials escape through MCP serialization and numeric IDs
Redaction runs before nested serialization, so a configured token inside a semantic MCP tool reply, and token-bearing request IDs (including numeric/encoded representations), can still escape. **Repair:** apply credential removal to semantic tool replies *before* nested serialization; cover the supported ID and encoding representations at the response boundary; define a safe refusal for credential-bearing IDs if preserving them conflicts with secrecy. Tests per representation, asserting absence in every log, reply and header.

## 3 (MEDIUM, Gate C): startup secrecy tests discard the first stdout line
The readiness-discovery read consumes the first stdout line before collection, so the secrecy assertion never sees it. **Repair:** every stdout byte consumed during startup discovery joins that engine's collected output; assertions run over the complete stdout+stderr. Keep unique filenames, collection-before-assertion, and the non-empty count. Astra added a startup-stdout mutant — make sure it's bound and killed.

## Constraints
Branch gen2 only. Never touch `gateway/`, gen-1, running services or main. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (per finding: what changed, the reproduction now handled, mutant evidence, final unpiped `make gen2-check` result). Don't end your turn waiting on a background run.
