# Task 2b-repair-6 — local-index results must never claim exhaustion they didn't observe (F3)

Read first, in full: `~/work/research-loops-public/private/reviews/gen2-2b-repair-5-astra-review-20260930.md` (finding F3), with evidence under `/tmp/gen2-2b-repair-5-astra-review-20260930/` (`serving_probe.py`, `serving_probe.json`, `serving_summary.json`). Then read the charter section "Root-cause fixes, not patches", `gateway/docs/STATION-CONTRACT.md` §2 (the meaning of `exhausted` and the skip sentinel), and `docs/gen2/INVARIANTS.md` RG-4.

**F1 and F2 are ACCEPTED as ROOT-CAUSE.** Everything else in 2b is accepted. Touch only what F3 needs. Phase 3 and Phase 4 items are owned elsewhere.

## F3 — the defect
With five converted matching venues, a local-index (`openalex_snapshot`) find at `limit=2` returns two records marked `searched_ok`, `completeness: complete`, `exhausted: true`, with continuation `{"openalex_snapshot":"exhausted"}`. Following that continuation returns nothing, so the remaining three are skipped. This reproduces on HTTP `/v1/find`, HTTP MCP, queued jobs and stdio MCP. The engine `GatewayClient` with `pages=3` makes one request and records a complete observation.

The adapter (`gateway/research_gateway/adapters/openalex_snapshot.py`, ~line 43) applies SQL `LIMIT` and computes the full matching count, but returns no continuation or truncation signal. The lane router (`core/router.py`, ~line 623) treats "no continuation" on an otherwise complete answer as exhaustion. **Root cause: the absence of a cursor is used as proof that the lane returned everything, even when the adapter knows it didn't.**

## Required
- **Make truncation explicit at the adapter/lane contract.** Either a genuine continuation that preserves page semantics, or an honestly partial result with its reason and no exhausted sentinel. Never a fake cursor, a larger fixed limit, or asserted exhaustion. Retain the identities actually read.
- **Fix it where exhaustion is decided, not only in this adapter.** Exhaustion should be asserted only when an adapter positively reports that nothing remains, never inferred from a missing cursor. That way any adapter, now or later, that truncates without a cursor can't produce false exhaustion. Check every adapter against the corrected rule and state which return a genuine continuation, which positively report completion, and which are now partial.
- If a truncated result is reported as partial, it stays out of the complete-result search cache.
- **Tests:**
  - strictly more converted matches than `limit`, through the assembled gateway on all four doors;
  - a control where everything fits on the final page;
  - the interaction with withheld (unconverted) matches;
  - the engine client's continuation behavior across pages;
  - a mutant bound to the truncation/exhaustion decision, with a paired control.

## Completion report (charter rule)
The root cause in one sentence, and why the change removes it for every adapter, not just `openalex_snapshot`. List every remaining limitation, with where it lives and its owning phase.

## Budget and constraints
Engine 9,713, gateway 9,295. Keep it narrow; report net lines separately. Branch gen2 only. Never run any migration against a real database, and never touch `~/work/staging/research-gateway-wt`, its database, or `research-gateway.service`. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with final unpiped `make gen2-check` and `make gen2-gateway`. Don't end your turn waiting on a background run.
