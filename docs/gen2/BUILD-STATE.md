# Gen-2 Build State

Maintained by the orchestrator loop. One entry per wake with material change; quiet wakes don't append.

## Current
- **Phase:** 0 — invariants & migration contract (operator-gate to Phase 1 at completion)
- **Branch:** `gen2` @ dev workspace (/home/trevor/work/autonomous-research-loops)
- **Landed:** 0a (nine commits, a42cfe7..83a6513) — INVARIANTS.md, 9 schemas + 75 examples, store DDL (30 tables), boundary graph + checker in make/CI, size accounting. `make gen2-check` green (orchestrator-verified). Line baseline: 0 production / 827 tests / 1,878 schema / 2,596 fixtures / 1,251 SQL.
- **In review:** Astra gate review of 0a (A+B+C incl. 86 tests), agent f299bc53, brief+report under research-loops-public/private/reviews/gen2-0a-*.md. Eight coder deviations + hash-canonicalization, lease-concurrency, and deferred-item-phasing rulings requested.
- **Queued:** 0b (store + dry-run importer skeleton) after 0a review verdicts; 0c (deployment contract, generated key catalog/.env.example, export sinks, source-proposal pathway — operator-requested 2026-09-25) after 0a review lands.
- **Operator items:** first push to GitHub (activates the new CI workflow) is the operator's call; three stale methodology-doc citations found by coder 0a were fixed by the orchestrator (lines 93/161/193), re-verification included in Astra's Gate B.

## Phase plan (adjudicated order — charter §Standing rules)
0. Invariants & migration contract → **0a** specs/schemas/CI-boundary-graph → **0b** minimal normalized store + dry-run importer skeleton
1. Mechanical vertical slice (router + sole-writer transactions + supervisor + fake executors; crash/replay/cancel proven)
2. One complete research workflow (gateway observations repair → discovery→…→publication receipt on one test topic)
3. Qualified automation & projections (decision layer shadow/advisory; governed GraphRAG generations; gateway budget/shutdown repairs)
4. Migration & canary (replay recorded snapshots; freeze; import; reconcile; single-writer cutover)

## Log
- 2026-09-25: Loop initialized. Charter, boundary contract, build state committed on `gen2`. Task 0a dispatched.
