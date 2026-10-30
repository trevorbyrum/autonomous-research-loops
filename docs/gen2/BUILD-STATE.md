# Gen-2 Build State

Maintained by the orchestrator loop. One entry per wake with material change; quiet wakes don't append.

## Current
*(This section is current state only; history is in REVIEW-LOG.md. Contract and rulings: DOSSIER.md.)*
- **Phase:** Phase 2 OPEN (since 2026-09-29): one complete single-topic research workflow. Phases 0 and 1 accepted. The decision layer is disabled and unqualified throughout.
- **Open task:** 2d, slice 6. 6a is complete. The checks cut-back S1–S6, S2b–S2d and the gateway-mutant and trigger-order retirements are complete.
  - **Complete:** the Gate S full-pass batches C, C-fu, D1, D2 (a1–a3, b), E, O-9 (a, b), B; R2 (INVARIANTS rules plus generated traceability); 6b1′ PR 0; O-10, Docs-1, Prune-1 (2026-10-29); move-aware mutation scope (#73); Str-A, Str-B, Str-C and CS-1 (2026-10-30; collected ids 2,868 → 2,848).
  - **Done 2026-10-30 (later):** Str-D (#84), Batch F (#54), ERROR_KILL (#87).
  - **In flight:**
    - Batch A (PR #85): accepted by Astra through r3; round-4 mutation repairs are going in now, then Astra review of those production changes and the verifier;
    - the nightly test-portfolio review, in its dry-run week.
  - **Plan:** `private/reviews/gen2-batch-plan-20261027.md`.
- **Last verifier result:** ERROR_KILL `ddd6b10`, gen2-accept exit 0 in 901 s (8 shards, 2,867 tests).
- **Blockers:** none. Trevor ruled on 2026-10-29 (DOSSIER): mutation scope, Batch F option A, CI-DESIGN, C-4, O-10, and test-pruning items 7–11. The tier table is approved (TIERS-v2 plus Astra), and Batch F option A was chosen.
- **Gate S:** last run was the **full pass at `3a579af`** (2026-10-27; rulings O-1 to O-11 approved). Gate S #2's rulings S2-1 to S2-7 were approved 2026-10-27.
- **What's next:** Batch A merge → O-5 → 6b1′ PR 1 → 6b2′ → 2e1-minimum → 2e2-minimum → 2f. Batch F, then `raw_exchange`, on the second coder. Task 2g follows 2f.
- **Operator-side items outstanding:** the CI rollout (ci-cd #12→#15, tag v1.2.0, JCasC repoint) belongs to the operator and the ci-cd session.
- **Debt:** `DEBT-REGISTER.md` is authoritative; status is in `phase-status.json`.

## Phase 2 plan (approved order, Gate S plan 2026-10-24; supersedes the 2026-09-29 plan, which is preserved in REVIEW-LOG)
**Size rules (the user, 2026-09-29):** no hand-written file over 1,500 lines (enforced by `make gen2-check`); 15,000 total production lines is a growth-review trigger.
- **Done:** 2a (bootstrap chain), 2r (size rules), 2b (gateway input contract), 2q (architecture refactors), 2c (accounting views and confidence), and in 2d: slices 1–5 and 6a parts 1–3.
- **Remaining, in order** (S = Gate S simplification batch, R = records batch):
  1. ~~R1 records collapse~~, ~~S1 tiered checks~~, ~~S2 automatic mutation~~, ~~S3 retire the metrics ratchet~~ (all done); ~~S2b mutation test selection~~ (done); ~~S2c coverage reuse through make~~ (done).
  2. ~~**2d slice 6a part 4**~~ (freshness binding; accepted 2026-10-26).
  3. S4 Router owns the three insertion-time rules, S5 delete the semantic DDL, R2 INVARIANTS and traceability table, S6 JSON member-domain DDL guards (only if confirmed).
  4. **2d 6b1** persist the rich dossier (≈ 350), **6b2** completion gates (6b2 + 6b3 merged, ≈ 450), **slice 7** completion approval binding (≈ 200).
  5. **2e1** live-execution preflight (F1, F5, §4(d)); **2e2** real executors and the S4–S7 workflow (F3, F10), minimum scope first; **2f** the supervised live single-topic run (operator inputs needed: test question and deliverable, spend ceiling, provider/runner configuration, allowed lanes, one JSONL export destination).
  6. **2g** (new, phase 2, pending, after 2f): slices 8–11 moved here: /2 bundle assembly (DEBT-040), one JSONL/file connector (DEBT-041), durable feed facts (DEBT-042), freshness envelope and currency (DEBT-043). Slice 12 is removed.
  7. **Phase 2→3 operator gate** once all of these are accepted.
- 2f reports scientific completion at a dossier revision, export delivery `not_attempted`, and surveillance currency `unknown` with DEBT-040–043 as the owners of the gap (plan §3.2).
- **Carried to Phase 3 — usage estimator** (operator request 2026-09-29): estimate API cost and subscription-plan share for a topic profile and cadence; deferred until usage records exist.

## Phase plan (adjudicated order — charter §Standing rules)
0. Invariants & migration contract → **0a** specs/schemas/CI-boundary-graph [**ACCEPTED 2026-09-25**, 4 review rounds] → **0b** minimal normalized store + dry-run importer skeleton [**ACCEPTED 2026-09-25**, 3 review rounds] → **0c** deployment contract, key catalog, export sinks, source-proposal pathway [**ACCEPTED 2026-09-26**, 3 review rounds]  → **PHASE 0 COMPLETE; awaiting operator gate**
1. Mechanical vertical slice (router + sole-writer transactions + supervisor + fake executors; crash/replay/cancel proven)
2. One complete research workflow (gateway observations repair → discovery→…→publication receipt on one test topic)
3. Qualified automation & projections (decision layer shadow/advisory; export API connectors (generic reference connectors: SQL, JSONL/file, webhook); gateway budget/shutdown repairs)
4. Migration & canary (replay recorded snapshots; freeze; import; reconcile; single-writer cutover)

## Log
- 2026-09-25: Loop initialized. Charter, boundary contract, build state committed on `gen2`. Task 0a dispatched.

## Debt register, phase status and architecture metrics (task 2q-a)
- `docs/gen2/DEBT-REGISTER.md` holds every operator-accepted mitigation (none has been accepted) and every obligation an operator ruling or review has assigned to a later task or phase (15 entries: the 2e1 construction rule and client model, the §4(d) rejected-credential demonstration, the 2e2 retrieval-audit evidence, the Phase 3 and Phase 4 items below, the importer's inventory of unexamined files that must exist before a dry-run report is used as migration-planning evidence (DEBT-014), and the Phase 3 usage estimator (DEBT-015)), each with an owner and a removal condition. The inclusion test is whether the build could lose the obligation, not who assigned it (an operator ruling, a review at any gate, or an operator request); a "before X is used" prerequisite is part of the entry. `make gen2-debt` (part of `gen2-check`) fails when a closed task or phase owns an open entry.
- **Closing a task or a phase:** set it to `closed` in `docs/gen2/phase-status.json` in the same commit that records its acceptance here. That is what arms the check; it cannot tell a task was accepted unless it is told. Closing a register entry takes `status: closed` and a `closed by`. A new operator ruling, review ruling or operator request that assigns something to a later task adds its register entry in the same commit as the ruling.
- The architecture-metrics ratchet, the supported-source contract check and the hotspot report were retired by S3 (2026-10-25); `make gen2-complexity` (radon per-function ceiling 48, mean 10) replaces them. `make gen2-locators` still fails on a file, symbol or module-path locator in INVARIANTS or the register that names something that is not there.

## Phase 4 release items
  - (from Astra 13b review) Stores written before 13b are refused by the current opener (schema mismatch, same user_version). Any import/restore must keep the old counts and identities and mark unrecoverable end knowledge `unknown`; never infer exhaustion from old `complete` rows. (operator rulings 2026-09-30, from the 2b review chain)
- **Real-data migration of old gateway records** (`gateway/research_gateway/registry/migrate.py`): owned by Phase 4, run only at a release the operator approves; complete only at zero unconverted records.
- **Stopping and fencing every old gen-1 writer** (gateway, loaders, maintenance jobs) before that migration, and never restarting one against the converted database: owned by Phase 4. The operator will decide the procedure when Phase 4 arrives ("Can we address this when we're there"). Astra showed an old writer running after conversion re-loosens restrictions, so this step can't be skipped.
- **Gen-1's unrecoverable non-lead restrictions:** purge the affected regenerable cache rows at cutover and refetch with current writers (the root-cause option). They are not carried forward.
- **Database privilege separation for gateway serving** (Astra, 2b-repair-5 review): the serving principal can read stored records only through `gateway.servable_records`, never the base table; harvest, migration and writers get separate privileges. Phase 4 deployment/cutover qualification must include a refused direct-table read and a successful view read. Until then the source-level check in `tests/test_record_gate.py` is not runtime access control.
- **Live provider canary qualification** (Astra, 2b-repair-6 review): Phase 4 verifies each provider's end and continuation behaviour live, and checks for provider drift. It does not replace the provider-grounded end rules task 2b must establish now.

## Phase 3 items (operator rulings 2026-10-01, from the 2b review chain)
- **Gateway adapter compatibility task:** move the OpenAIRE adapter off the deprecated `/graph/v1/researchProducts` endpoint version, and migrate or qualify Kaggle's listing (its official client now uses `POST /v1/datasets.DatasetApiService/ListDatasets`; the adapter uses the legacy `GET /api/v1/datasets/list`). Done before Phase 4's live canary qualifies those lanes.
- **Catalogue partial-result contract (commissioned):** BLS/FRED/Census/BEA catalogues keep readable entries and report dropped ones, with an explicit entry/drop/continuation contract, instead of failing the whole answer closed.
- **Gateway capability revision lifetime** (Astra, 2b-repair-3 review, REVIEW-LOG 2026-09-30; carried here by Gate D #1 finding 6): the revision counter lives in gateway process memory, so a restart within the same second, or two gateway processes, can reproduce stale current status. Ordering must survive a restart and more than one process; owned by Phase 3's gateway lifecycle work (`DEBT-REGISTER.md`, DEBT-011).
