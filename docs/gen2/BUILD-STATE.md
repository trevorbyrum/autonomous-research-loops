# Gen-2 Build State

Maintained by the orchestrator loop. One entry per wake with material change; quiet wakes don't append.

## Current
- **Phase:** 0 — invariants & migration contract (operator-gate to Phase 1 at completion)
- **Branch:** `gen2` @ dev workspace (/home/trevor/work/autonomous-research-loops)
- **0a review verdict: BLOCK (all 3 gates).** Full report: research-loops-public/private/reviews/gen2-0a-astra-review-20260925.md (pinned SHA-256 manifest). Astra ran independent DB probes, not just re-review: found history-rewrite paths (REPLACE bypasses receipt immutability), decision-authorization not bound to subject/topic/hash, facet importance unrepresentable in schema, pre-contract discovery FK-blocked, and 8 of 86 tests need rewrite (3 mutations independently survived beyond the coder's claimed set). 78/86 tests and all 8 coder deviations ACCEPTED. Full findings + rulings logged: docs/gen2/REVIEW-LOG.md.
- **Doc corrections applied same session** (Gate B found 6 overclaims in the methodology synthesis beyond the 3 already-fixed citations): tier-0 NLI "verifies mechanically"/"guarantee" wording removed; Jev importance score "calibrated" language corrected to proposed/operator-authoritative; VoI-lite "resource-rational by construction" reworded as proposed heuristic; method-selection Noul battery now scores coherent templates, not independent per-family answers; stale "reviewers' verdicts were false" phrasing corrected to match the adjudication's actual ruling. All in methodology-synthesis-20260924.md.
- **Active:** task 0a-repair dispatched (docs/gen2/tasks/0a-repair.md) — fixes A1–A11, 8 named test rewrites, R1 (RFC 8785 JCS canonicalization), R2 (6 README choices), R3 (phase assignments for deferred items). Coder: new Opus instance. 0a is NOT accepted; 0b does not start until 0a-repair passes Gate A+B+C.
- **Queued:** 0c (deployment contract, generated key catalog/.env.example, export sinks, source-proposal pathway) — after 0a-repair lands, since its schema references depend on 0a's corrected schemas.
- **Operator items:** first push to GitHub (activates CI workflow) is the operator's call. Orchestrator model switched Fable→Sonnet mid-build via operator's own /model command (matches CLAUDE.md: orchestration is Sonnet/Fable, never Opus) — coder (Opus 5.5) and reviewer (Astra) assignments unchanged throughout.

## Phase plan (adjudicated order — charter §Standing rules)
0. Invariants & migration contract → **0a** specs/schemas/CI-boundary-graph → **0b** minimal normalized store + dry-run importer skeleton
1. Mechanical vertical slice (router + sole-writer transactions + supervisor + fake executors; crash/replay/cancel proven)
2. One complete research workflow (gateway observations repair → discovery→…→publication receipt on one test topic)
3. Qualified automation & projections (decision layer shadow/advisory; governed GraphRAG generations; gateway budget/shutdown repairs)
4. Migration & canary (replay recorded snapshots; freeze; import; reconcile; single-writer cutover)

## Log
- 2026-09-25: Loop initialized. Charter, boundary contract, build state committed on `gen2`. Task 0a dispatched.
