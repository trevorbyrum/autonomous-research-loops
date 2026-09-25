# Gen-2 Build State

Maintained by the orchestrator loop. One entry per wake with material change; quiet wakes don't append.

## Current
- **Phase:** 0 — invariants & migration contract (operator-gate to Phase 1 at completion)
- **Branch:** `gen2` @ dev workspace (/home/trevor/work/autonomous-research-loops)
- **Active task:** 0a (dispatched 2026-09-25) — behavioral invariants doc, ID/authority scheme, contract-v2 schema, module-boundary graph in CI, normalized-store DDL draft. Coder: Opus (paseo claude provider). No engine logic in 0a.
- **Gates pending:** Gate A+B on 0a deliverables when the coder lands; Gate C not yet applicable (no tests in 0a; boundary-graph CI check itself gets a Gate C review when written).

## Phase plan (adjudicated order — charter §Standing rules)
0. Invariants & migration contract → **0a** specs/schemas/CI-boundary-graph → **0b** minimal normalized store + dry-run importer skeleton
1. Mechanical vertical slice (router + sole-writer transactions + supervisor + fake executors; crash/replay/cancel proven)
2. One complete research workflow (gateway observations repair → discovery→…→publication receipt on one test topic)
3. Qualified automation & projections (decision layer shadow/advisory; governed GraphRAG generations; gateway budget/shutdown repairs)
4. Migration & canary (replay recorded snapshots; freeze; import; reconcile; single-writer cutover)

## Log
- 2026-09-25: Loop initialized. Charter, boundary contract, build state committed on `gen2`. Task 0a dispatched.
