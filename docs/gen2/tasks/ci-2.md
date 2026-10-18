# Task ci-2: make Jenkins the routine gen2 test runner (CI design §7 steps 2–3, first slice)

**Why.**
- CI-DESIGN was approved on 2026-10-05, and the platform pieces landed (ci-cd PRs #5–#11).
- The gen2 side stalled after 2026-10-06. Jenkins still runs the old `Jenkinsfile` (image `:1`, a bare `make gen2-check`, a 50-minute limit). Meanwhile:
  - `gen2-check` now takes about 80–95 minutes;
  - the gateway suite doesn't run in CI at all;
  - the orchestrator reruns everything by hand on every landing.
- **Operator, 2026-10-18:** "Push + queue CI task." gen2 is pushed again (`2bf8bbe`) and is pushed after every accepted task.

**Goal of this slice.** Every push to `gen2` (and every task branch) gets a CI result that **finishes inside its limit**, under the CI design's mode and tier model. The full acceptance workload must run in CI as well, split across executions if it has to be.

## Required
1. **Modes (§3.2) and tiers (§3.3).**
   - **push:** T0 gates only:
     - `gen2-sqlite`, `gen2-boundaries`, `gen2-size`, `gen2-schemas`, `gen2-ddl`, `gen2-catalog-check`, `gen2-metrics`, `gen2-debt`, `gen2-locators`, `gen2-source`;
     - the secret/personal-data scan, if the platform already provides it.
     - Budget: a few minutes.
   - **full acceptance:**
     - engine unit tests;
     - trigger-order;
     - the full mutation inventory;
     - the gateway suite without a DB, then with a DB.
     - Split it into separate executions or parallel stages so **each stays within the platform limit**. Measure it; don't guess.
     - Full mutation stays **full** (design: phases 1–5). No diff selection in this slice.
   - Map the modes to how Jenkins triggers builds today (branch builds, PR merge builds). Document the mapping.
   - If the platform can't express a mode yet (e.g. nightly), write it down as a platform change request, not a hack.
2. **Reproducible CI environment (§7 step 2).**
   - **Gateway dependencies:** a hash-locked install of the gateway's Python dependencies, including psycopg.
   - **Worker budgets from the container's CPU quota**, not `os.cpu_count()`, with an explicit aggregate budget for engine and gateway.
   - **Split gateway modes** (no-DB, DB, mutants), with one DB owner per shard.
   - **Behaviour is unchanged locally,** except for the worker budget. A local `make gen2-check` / `make gen2-gateway` must produce the same test and mutant identities and outcomes.
3. **Jenkinsfile v2.**
   - Start from branch `ci/gen2-jenkinsfile-v2` (`55ccf60`): image `ci-py312-noble:2`, `cleanWorkspace`, `recordIdentity`.
   - **Image `:2` must exist on cir.** Building it is an operator step (ci-cd PR #5 runbook). **If it isn't built, stop and report.** Don't work around it.
4. **Status binding.** Every result is bound to the exact commit, and the PR merge vs head identity is recorded (already in the platform's `recordIdentity`).
5. **Measure and compare (feeds §4).**
   - Run the full acceptance workload in CI at one pinned commit.
   - Compare its **test identities, mutant identities and outcomes** against the orchestrator's local landing at the same commit; the orchestrator supplies the local run.
   - Record agreement or each difference.
   - **Totals or durations alone don't count.**

## Out of scope (later CI slices)
- **Next slices:** the §4 qualification drills and shadow window; the protected-path and test-integrity reports; diff-selected mutation; nightly and drift; switching coders to task-branch PRs.
- **`.github/workflows/gen2-check.yml`** (D4: removal or disablement awaits the operator's choice). Don't touch it.
- **Any ci-cd platform change** goes as a separate PR to `trevorbyrum/ci-cd`, from the dedicated clone `/home/trevor/work/ci-cd-gen2`. It must be opt-in and backward compatible, and **the operator merges it**. Never touch `~/work/ci-cd`.

## Constraints
- **Branch and worktree.**
  - Work on branch `sol/ci-2`, in a separate worktree (`git worktree add`), not the shared gen2 checkout.
  - **You may push `sol/ci-2` to origin**, to get Jenkins results. Never push `gen2` or `main`, and never open or merge a PR into them.
  - The orchestrator asks the operator before merging `sol/ci-2` into gen2.
- **Test semantics are unchanged.** You may not remove, skip or weaken any test, mutant, control or gate to make CI fit. Splitting and parallelising are fine. Anything that changes what is executed must be shown identical, by identity comparison.
- **No production behaviour change** in `gen2/` beyond the worker-budget function. Any other production change: stop and report.
- **Copy the venv:** disposable snapshots copy `.venv-gen2` with `cp -a`. Never symlink it.
- **Landing units:** wait until no `gen2-landing-*` unit is active before heavy local runs.
- **Gen-1 is off-limits.** Never touch the live gen-1 gateway, its DB, research-gateway.service or 127.0.0.1:8765.
- **No provider calls.**
- **Tower and Jenkins VMs:** don't change Jenkins, cir/cim or repo settings. Read-only inspection of Jenkins build logs and status is fine.
- **AGENTS.md lookup:** look only inside the repository.
- **Don't edit** BUILD-STATE, REVIEW-LOG or DEBT-REGISTER.
- **Before committing**, run `make gen2-ddl gen2-schemas gen2-debt gen2-locators gen2-source gen2-boundaries gen2-metrics gen2-size`.
- **Commits** end with `Co-Authored-By: GPT-6.1-Sol <noreply@openai.com>`.
- **Evidence:** `~/work/research-loops-public/private/evidence/ci-2/`, with a COMPLETION.md covering:
  - per-mode measured durations;
  - Jenkins build URLs and their statuses;
  - the identity comparison;
  - any platform change requests;
  - deviations.

## Amendment (2026-10-18, orchestrator): proceed on image `:1` while `:2` is pending
**Fresh probe:** `sol/ci-2` at `9008299` (Jenkinsfile v2 on `:2`). Build #1 failed in 8.6 s. `docker image inspect ci-py312-noble:2` failed on cir, then pull access was denied.
- **Image `:2` is not deployed.** Building it on cir is the operator's step (ci-cd runbook `images/py312-noble`, "Trevor's post-merge cir rebuild"). This has been requested.

**Until `:2` exists, implement and measure everything that doesn't need PostgreSQL on image `:1`:**
- push/T0 mode;
- the split full-engine modes (unit, trigger-order, full mutation), each within the limit;
- the worker budget from the CPU quota;
- `cleanWorkspace` / `recordIdentity`;
- the gateway no-DB mode, if it runs on `:1`. Determine this; don't assume it.
- the identity comparison for the engine modes.

The image switch to `:2`, the gateway DB mode and the hash-locked psycopg install go in a follow-up once `:2` is confirmed on cir. Keep them ready on the branch if useful, but **off** the default path.

Every push of `sol/ci-2` should produce a green, in-limit build for what it runs.
