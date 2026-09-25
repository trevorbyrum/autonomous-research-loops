# Gen-2 Build State

Maintained by the orchestrator loop. One entry per wake with material change; quiet wakes don't append.

## Current
- **Phase:** 0 — invariants & migration contract (operator-gate to Phase 1 at completion)
- **Branch:** `gen2` @ dev workspace (/home/trevor/work/autonomous-research-loops)
- **0a review verdict: BLOCK (all 3 gates).** Full report: research-loops-public/private/reviews/gen2-0a-astra-review-20260925.md (pinned SHA-256 manifest). Astra ran independent DB probes, not just re-review: found history-rewrite paths (REPLACE bypasses receipt immutability), decision-authorization not bound to subject/topic/hash, facet importance unrepresentable in schema, pre-contract discovery FK-blocked, and 8 of 86 tests need rewrite (3 mutations independently survived beyond the coder's claimed set). 78/86 tests and all 8 coder deviations ACCEPTED. Full findings + rulings logged: docs/gen2/REVIEW-LOG.md.
- **Doc corrections applied same session** (Gate B found 6 overclaims in the methodology synthesis beyond the 3 already-fixed citations): tier-0 NLI "verifies mechanically"/"guarantee" wording removed; Jev importance score "calibrated" language corrected to proposed/operator-authoritative; VoI-lite "resource-rational by construction" reworded as proposed heuristic; method-selection Noul battery now scores coherent templates, not independent per-family answers; stale "reviewers' verdicts were false" phrasing corrected to match the adjudication's actual ruling. All in methodology-synthesis-20260924.md.
- **Landed:** 0a-repair (17 commits, 5d59476..885f805) — all A1–A11 fixed, all 16 named tests (D06–D55, B20) rewritten, R1–R3 rulings implemented. `make gen2-check` green (orchestrator-independently-verified): 345/345 mutants killed, 177 unit tests, first production code in (193 lines, gen2/core helpers). Coder self-reported 2 process slips (make|tail hid a failing check twice) — both caught and amended before final commit.
- **In review:** Astra re-review of 0a-repair, agent 0a30199a, brief+report under research-loops-public/private/reviews/gen2-0a-repair-*.md. Re-running original probes, not just diff review.
- **Operator items pending:** (1) coder installed `rfc8785` via `pip --user --break-system-packages` directly on the build host — packaging approach needs a decision before Phase 1 (venv/lockfile/CI-managed). (2) Coder flagged as operator call: retired topics cannot be revived without a new topic or explicit amendment — confirm this is the intended policy.
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
