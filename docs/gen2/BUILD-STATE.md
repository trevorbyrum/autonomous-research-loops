# Gen-2 Build State

Maintained by the orchestrator loop. One entry per wake with material change; quiet wakes don't append.

## Current
*(This section is current state only; history is in REVIEW-LOG.md. Contract and rulings: DOSSIER.md.)*
- **Phase:** Phase 2 OPEN (since 2026-09-29): one complete single-topic research workflow. Phases 0 and 1 accepted. The decision layer is disabled and unqualified throughout.
- **Open task:** 2d, slice 6. 6a parts 1–3 complete. **The checks cut-back S1–S3 is complete:**
  - S1 merged `b7747e1`;
  - S3 PR #22 accepted;
  - S2 PR #25 accepted (Cosmic Ray changed-line gate), with auto-merge set.
  - **6a part 4** (`82befcb`, PR #28): **Astra ACCEPTED pending the mutation gate.**
  - **S2b** (mutation test selection, PR #30): mutation step about 25 min. **Astra BLOCK S2b-C1** (selected runs not qualified on clean source); repair in progress.
  - **Then:** S2b merges, part 4 merges gen2, then one full gen2-accept on part 4.
- **Last verifier result:** S2 `14c31e1`, gen2-accept exit 0 in **3,263 s** and gen2-gateway exit 0 in 1,012 s. Landing time went from about 7,900 s to 6,091, then 5,356, then 3,263 s.
- **Blockers:** none. **Open operator decisions:** none.
- **Gate S:** last run #1 at `65fb30e`. Since then, the batches have been net-negative (S1 −2,447; S3 −22,845).
- **What's next:** S2 (after the spike), then 6a part 4, S4–S5, R2 (INVARIANTS plus the CI-DESIGN amendment for operator approval, D12), S6, then 6b1, 6b2 and slice 7; then 2e1, a minimum 2e2, and 2f. Task 2g follows 2f.
- **Operator-side items outstanding:** the CI rollout (ci-cd #12→#15, tag v1.2.0, JCasC repoint) belongs to the operator and the ci-cd session.
- **Debt:** `DEBT-REGISTER.md` is authoritative; status is in `phase-status.json`.

## Phase 2 plan (approved order, Gate S plan 2026-10-24; supersedes the 2026-09-29 plan, which is preserved in REVIEW-LOG)
**Size rules (the user, 2026-09-29):** no hand-written file over 1,500 lines (enforced by `make gen2-check`); 15,000 total production lines is a growth-review trigger.
- **Done:** 2a (bootstrap chain), 2r (size rules), 2b (gateway input contract), 2q (architecture refactors), 2c (accounting views and confidence), and in 2d: slices 1–5 and 6a parts 1–3.
- **Remaining, in order** (S = Gate S simplification batch, R = records batch):
  1. ~~R1 records collapse~~ (done), ~~S1 tiered checks~~ (done), S2 automatic mutation, ~~S3 retire the metrics ratchet~~ (done).
  2. **2d slice 6a part 4** (freshness binding, ≈ 250).
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
- `make gen2-metrics` (part of `gen2-check`) ratchets the architecture metrics (engine and gateway apart) against `docs/gen2/metrics-baseline.json`, recorded at the production tree accepted with 2b (its digest equals that of `28a2e83`; version 2 since 2q-a-repair, which added each file's fan-out, fan-in and reach). Besides propagation cost, cycles, cross-file self-calls, smells and function complexity (a baselined function is compared in both scores whatever the thresholds say), it gates the charter's per-module dependency measures: a file's fan-out may not rise, the fan-in of a file that was stable may not rise through files that existed, and no pair of existing files may become reachable that was not (absolute pairs); instability is judged by its causes and direction, as `tools/gen2_metrics.py` states. Since 2q-a-repair-3 (in review), source outside the supported-source contract (`docs/gen2/SOURCE-CONTRACT.md`, v1; operator ruling 2026-10-05) is refused before any measurement, by `make gen2-source` and by every metrics and locator command. No exemption or ledger entry can waive a refusal, and the old `unresolved_base` classification has been removed. The only way past a regression is an entry in `docs/gen2/metrics-exemptions.md`; `make gen2-metrics-rebaseline` tightens and never loosens; `make gen2-hotspots OUT=<dir>` writes the change-coupling and hotspot report Gate D reads (it never fails the build). `make gen2-locators` fails on a file, symbol or module-path locator in INVARIANTS or the register that names something that is not there, and on a backticked dotted name that is neither one of those forms nor marked `code:` or `history:`.

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
