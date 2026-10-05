# gen-2 CI design — revision 2

Status: **APPROVED by the operator 2026-10-05** (D1–D3 and D5–D11 as recommended; D4 changed to no GitHub Actions). Revision 2.1 (orchestrator, 2026-10-04). Revision 2 was re-reviewed by Astra and judged **SOUND-WITH-CHANGES** (`private/reviews/gen2-ci-design-rev2-astra-review-20261004.md`). 2.1 applies RR1–RR3 and its first-slice additions. Nothing is enabled until the operator rules on §9.

- **Revision 1:** `5ae3d49` plus the §3.9 addendum `d087225`. Astra reviewed it with verdict **SOUND-WITH-CHANGES** (`private/reviews/gen2-ci-design-astra-review-20261004.md`; evidence in `private/evidence/astra-ci-design/`).
- **This revision** adopts all ten of Astra's findings, its research corrections, its changes to the gaps list and its implementation order. §10 maps each finding to where it is addressed.

**Builds on the existing platform**, `trevorbyrum/ci-cd`: two VMs (ci-manager and ci-worker), the `std` library, archgate, and the Zones G/M/W/A trust model, in which agents have no merge, Replay or write rights. Nothing here changes that topology or trust model.

**The operator's requirements:**
1. Don't just move the current routine onto CI. Decide from evidence what CI should do for this build.
2. Note what we don't cover.
3. Put architecture complexity and coupling checks in **every** tier, light where speed matters and deeper where time allows, and produce what helps the architecture review (Gate D).

**What CI will and will not claim.** CI reduces duplicated execution and gives earlier, clearer feedback. It does **not** close structural defect families, prove future code correct, validate the oracle, or replace Astra's semantic and adversarial review or the fresh-session Gate D.

## 0. What exists today (verified)

| Thing | Verified state |
|---|---|
| **Jenkins gen2 job** | The `Jenkinsfile` makes one `standardPipeline` call: image `ci-py312-noble:1`, a *mutable tag*; lint `gen2-boundaries gen2-size`; build `gen2-venv`; unit `gen2-check`; 50-minute timeout. Build #1 at `ea5a699` took **31.94 min**: engine tests 644 s, mutation 1,209 s. **No gateway target runs.** Mutation used **7 workers under a 2-CPU quota**, because `tools/gen2_mutations.py:595` takes the default from host-visible `os.cpu_count()`. |
| **Status names** | `continuous-integration/jenkins/pr-merge` and `continuous-integration/jenkins/branch`. `ci/std` is a future name in the platform design. PR builds run the **merge commit** (JCasC strategy), not the PR head. |
| **Library and workspace** | JCasC loads library `main`, not an immutable tag; build #1 actually ran library revision `716e6de`. `checkout scm` has no explicit workspace reset. `HOME=$WORKSPACE/.ci-home` persists across builds of a branch. The venv marker is keyed on requirements timestamps, not on the interpreter or image. `ci-results/v0` has stages but no source identity. Only three named JSON artifacts are archived. |
| **GitHub Actions `gen2-check.yml`** | Runs every push on `ubuntu-latest`, Python **3.12.14**, and **fails** on `TheEndpointForms`. 3.12.14's `IPv6Address.__str__` renders IPv4-mapped addresses as dotted quads; 3.12.3 does not. The failure is confirmed as a representation/acceptance defect in `gen2/gateway_client/client.py:195` (`str(ip)`). It is not a wrong-destination or token leak. |
| **Orchestrator reruns** | Manual, about 45–60 min per landing, on the shared tree. |
| **Astra target reruns** | About 35–40 min per review round, on top of its probes. |

## 1. Problems this build has hit → requirements

Each requirement below is tied to a recorded problem. R8 and R11 are **preventive**: no incident occurred, so they are justified by the standing charter rule and the Gate D principle respectively.

| # | Recorded problem | Requirement |
|---|---|---|
| R1 | Coder claims needed an independent check that cost about 45–60 min of manual work and occupied the shared tree. | CI becomes the **authoritative record of the specified executions**, after the qualification in §4. Independent execution does not validate the oracle. |
| R2 | The oracle needed hand-run diff checks each round. Tests encoded rejected exemptions (2q-a-repair R5). | Protected-path and test-integrity **review signals** (§3.4). Authorisation and semantic review stay human/Astra. |
| R3 | Mutants were "killed" by subprocess crashes that an outer test's assertion reported (2q-a-repair-2 R4; reproduced in Astra's `nested-crash-probe.json`). | **Mutation-outcome validity at the subprocess boundary** (§3.5). |
| R4 | A review reproduction existed only as a probe until a coder rebuilt it. Already practice, but untraced. | Accepted reproductions are tests with **durable finding/family IDs** and owners, traced in CI evidence. Tests alone did not stop the circling; the charter's family rule did. |
| R5 | Full runs on every change (about 32 min engine, about 16 min gateway). | Earlier, bounded feedback with a **full backstop that comes first** (§3.3). |
| R6 | Timing races found by chance: supervisor start-grace, recorder startup, readiness. | No auto-retry; flips recorded as *candidates*; scheduled stress runs with recorded seeds; quarantine is a **mitigation** (§3.7). |
| R7 | The canonical-origin defect was invisible on the pinned interpreter. | A pinned **reference gate**, plus a controlled, report-only drift qualification that is routed to tasks with response deadlines. |
| R8 | *Preventive*: "no live calls" is enforced only by briefs and a Python guard. | **No external provider egress from the defined execution boundary** (§3.6). This is not a claim to confine every future agent or dependency. |
| R9 | The gateway suite isn't in CI. | Run the gateway suites, without and with a database, in CI, with the required prerequisites pinned (§3.2). |
| R10 | The metrics analyser met Python forms it couldn't model (three BLOCKs on 2q-a). | CI enforces **whatever Gate D #4 rules**. It does not pre-accept the blocked analyser and does not silently permit under-approximation. |
| R11 | *Preventive*: two complexity measures (gen2-metrics and archgate/lizard) for one property. | **One authoritative ratchet per property**. Today archgate is observe-only, so there aren't two blocking ratchets. |
| R12 | Evidence was lost from `/tmp` on the 2026-10-01 reboot. | A **controller-bound, retained evidence bundle**, including raw and failure evidence (§3.8). |
| R13 | *(new)* Review/authority transitions were remembered by people, not recorded. These are: Gate D triggers, the third-BLOCK rule, family redesign. | CI and the workflow **preserve and record the charter state machine** (§5). |

## 2. Principles

- **P1 — External execution evidence, plus independent semantic review.** CI supplies the execution; Astra and Gate D supply the judgment.
- **P2 — Feedback at diff time, never at the expense of the backstop.** Reduced per-change coverage only after a full pre-merge or integration backstop exists and is interlocked.
- **P3 — Determinism.** Failures are real until shown otherwise; flake candidates are recorded, not assumed.
- **P4 — Guarantees by construction where cheap, with stated boundaries.** Each guarantee states its exact scope.
- **P5 — An explicit analysis boundary.** An exact analysis inside a declared subset, with refusal outside it, is a *proposed* contract that has to be established independently. It is not the same as the industry's "soundy" practice.
- **P6 — One authoritative mechanism per property.** Different measures can coexist when one is explicitly diagnostic.
- **P7 — Findings become traced tests.**
- **P8 — Signals are not authorisation.** Machine-generated banners draw review attention. They never grant permission.

## 3. Design

### 3.1 Identity and environment, the foundation for everything else

Every run records these separately:
- source head, target head, merge base and the executed merge/tree SHA;
- the run attempt;
- library revision;
- image **digest**;
- the resolved interpreter, SQLite, PostgreSQL, psycopg/libpq and openssl versions.

The run starts from **fresh source and runtime state**:
- workspace cleaned;
- an explicit cache boundary: a wheelhouse or image-provided dependencies, never a persisted `HOME` venv;
- venv identity keyed on the interpreter and image as well as the requirements.

Required git history is fetched (`gateway/tests/test_provenance.py:370` uses `git archive` on an old commit, and the hotspot report needs history). A target-branch update invalidates any earlier integration result. Status names stay the platform's real ones until the platform migrates them deliberately.

**Reference gate:** ENVIRONMENT.md's environment through a **digest-pinned** image with versioned packages. The image adds:
- PostgreSQL 16 server binaries;
- pinned psycopg/libpq for the gateway interpreter, which resolves ENVIRONMENT.md's open gateway lock;
- `openssl`.

A missing required capability is a **failure**, not an extra skip.

### 3.2 Command graph (modes)

Each mode is a defined workload. They are alternatives, not cumulative layers, so the 60-minute ceiling is judged per mode.

| Mode | Runs | Budget (to be **measured** at real caps before it is relied on) |
|---|---|---|
| **push** | T0 gates (§3.3) | a few minutes |
| **PR** (phase 1 — 3) | T0 + **full** engine acceptance + **full** gateway acceptance (no DB, then DB) | measured. Build #1 plus the local gateway figure gives roughly 48 min, mixing environments, so it isn't a bound. Split across executions if needed. |
| **PR** (phase 6+, after selection is validated) | T0 + full test suites + **conservative diff-selected mutation** | measured |
| **integration** (merge into `gen2`) | the full acceptance workload, with an **interlock**: a pending, failed, aborted or missing integration result blocks the next merge | measured; must not be aborted by later merges |
| **nightly** | full acceptance + bounded stress + drift + absolute audit + deep architecture analyses + Gate D pack | bounded, with room for cleanup and publication |

Engine work fixes **worker budgeting**: mutation jobs come from the container's CPU quota, not `os.cpu_count()`, and the engine and gateway get an explicit aggregate budget. The gateway command is split into explicit modes (no-DB suite, DB suite, mutants), each with **one DB owner per shard**.

### 3.3 Tiers and the mutation selector

- **T0 (every push):**
  - `gen2-sqlite`, `gen2-boundaries`, `gen2-size`, `gen2-schemas`, `gen2-ddl`, `gen2-catalog-check`, `gen2-metrics`, `gen2-debt`, `gen2-locators`;
  - the supported-source guard, `gen2-source` (`docs/gen2/SOURCE-CONTRACT.md`; operator ruling 2026-10-05, Gate D #4 option B);
  - the protected-path and test-integrity reports;
  - a secret and personal-data scan.

  It runs inside the no-egress boundary (§3.6), because these are candidate-controlled checkers.
- **Acceptance tests:** the engine suite, the gateway suite without a DB and the gateway suite with a DB. JUnit for each. A report of **executed test identities and unexpected skips**, compared against the expected set.
- **Mutation:** full in phases 1–5. Conservative diff selection only from phase 6, *after* it has been validated against full runs (§7). The **selector contract** (versioned):
  - It computes over **both base and candidate inventories**. A mutant is selected when any of these changed: an edited target, a killer, a control, an explicit fixture dependency, its own definition, or its pairing record.
  - Gateway-relative paths are normalised. Multi-file targets are expanded (35 gateway mutants edit several files). Symbolic engine targets (`ddl`, `connection`, special-loading files) are mapped explicitly. Deletes and renames are handled.
  - **Full affected inventory, or both inventories when impact is unclear**, on any change to shared fixtures, loaders, runners, controls generation, toolchains, dependencies, broad contracts or unclassified paths.
  - Trigger-order testing follows changes to store tests, fixtures and connection behaviour as well as DDL.
  - Unmutated baselines, every selected killer and control, child attestation and global inventory-integrity checks are all kept. (`--only` currently suppresses the engine's full trigger-coverage check; the selector must not.)
  - Selected and omitted IDs are recorded with reasons. Unknown IDs and an unavailable comparison base are **rejected**. "No applicable mutants" is reported distinctly from a broken selector. Engine `--only` currently matches prefixes and gateway `--only` matches exact IDs; both are normalised.
  - **High-risk changes always get the full run.** "High-risk" is defined in the selector policy.
  - The map cannot prove complete transitive impact. The integration and nightly full runs exist to catch what it misses.

### 3.4 Protected-path and test-integrity review signals (R2)

- **Protected set:** exact repository-relative paths with owners. Changes are evaluated against the **trusted base policy**, so a candidate can't silently change what is protected. The set:
  - the oracle (`gateway/tests/oracle/**`, `gateway/tests/test_oracle.py`);
  - metrics state (`metrics-baseline.json`, `metrics-ledger.md`, `metrics-exemptions.md`);
  - `DEBT-REGISTER.md`, `phase-status.json`;
  - `gen2/boundaries.toml`, `docs/gen2/BOUNDARIES.md`, INVARIANTS, BUILD-CHARTER, ENVIRONMENT.md and the supported-source contract;
  - the Makefile, test discovery and runners, mutant definitions and controls JSON;
  - the policy checker and its config, requirements and the image contract;
  - `Jenkinsfile`, `.github/**`.

  Deletions and renames count as changes.
- **Test-integrity report:**
  - methods removed or renamed;
  - new skips or expected failures;
  - assertion-count drops;
  - test files deleted;
  - killer/control list changes;
  - changes to discovery or runner configuration;
  - the executed set against the expected set.

  Known limits, stated: this misses changed expectations, tautologies, early returns, altered fixtures, mocks, discovery filters, dynamic tests and failures swallowed by helpers. **Semantic review of changed assertions, fixtures and mutation intent stays with Astra.**
- **Trailers are explanations, not approval.** Approval and oracle-task separation are verified from reviewed task/PR metadata bound to the current SHA.
- **The secret/personal-data scan** also covers artifacts **before publication**. Private deny-list values never go into this public repo; they live in the controller's credentials or private config.

### 3.5 Mutation-outcome validity (R3)

- Outcomes are classified **at the subprocess/tool boundary**: tools invoked by tests emit structured termination evidence (exit cause, exception type, signal, timeout, malformed result, behaviour reached), and the mutation verdict consumes it.
- A **valid kill** is a policy refusal or the intended behavioural counterexample. An unexpected exception, a signal, a timeout, a malformed result or failure to reach the target behaviour is **INVALID**: distinct from SURVIVED, and also failing acceptance.
- **Repair the six 2q-a-repair-2 crash mutants into executable behavioural counterfactuals.** Relabelling them as crashes is not a repair.
- **Narrow, reviewed expectations** cover deliberately tested process failures and the engine's documented non-setup SQLite `IntegrityError` case. There is **no** generic `kill: error` escape.
- This belongs with 2q-a's harness work, and its owner is the mutation harness.

### 3.6 No-egress execution boundary (R8)

- The **trusted library** creates the execution container: no external network; only the workspace and artifact mounts it needs; **no usable host-control sockets** (Docker socket, forwarding Unix sockets) or credentials; bounded privileges.
- The effective mounts and permissions of the current `--volumes-from` agent arrangement must be **established before** any isolation is claimed. Platform C4.
- It covers **all candidate-controlled execution**, T0 checkers included.
- **Dependency provisioning is separate:** a controlled build step or an image/wheelhouse, not inside the isolated container. The vulnerability audit uses a separately acquired or dated offline advisory database.
- **IPv6:** Docker's `none` network has no IPv6 loopback. Tests that need IPv6 sockets are listed, and their skips are declared expected, or the library provides IPv6 loopback.
- A gen2-side wrapper that launches sibling containers through Docker is **ruled out**, because it would undermine both isolation and resource caps.
- The Python offline guard stays as defence in depth and for local runs.

### 3.7 Flakes and quarantine (R6)

- No automatic retries. A same-SHA flip is a **candidate**, not proof of a harmless flake.
- Nightly stress keeps denominators, schedules and seeds. Five repeats is a stress sample, not a reliability estimate.
- **Quarantine is a mitigation under the charter.** It needs the operator's acceptance, an owner, a removal condition and a DEBT-REGISTER entry.
- Quarantined tests **keep running**. Losing a mutant's required killer or control stays visible and non-passing unless explicitly waived. (The platform's 5-test / 14-day cap is a proposal, not implemented behaviour.)

### 3.8 Evidence bundle (R12)

- **Contents:**
  - `gen2-evidence.json` (versioned);
  - raw logs and JUnit;
  - the selector manifest;
  - **per-mutant outcomes** with their validity class;
  - executed tests and skips;
  - subprocess failure evidence;
  - the protected and integrity reports;
  - metrics deltas and ledger entries;
  - the finding-regression set;
  - artifact checksums.

  Incomplete and aborted runs are included.
- **The controller binds the bundle** to its build identity (§3.1) and final result, through a manifest. Repository reports supply the measurements. **Missing required evidence prevents acceptance.**
- **Retention and durable export:** evidence for accepted reviews is exported to durable storage beyond Jenkins rotation. The platform needs a C5 sanctioned artifact set, and publication must sit outside the timeout that would cut it off.

### 3.9 Architecture checks in every tier (operator requirement)

Every check below has an **owner**, a **measured cost**, an **exact claim**, its **known omissions**, and **promotion criteria**. Promotion means calibration on representative good changes and known violations, not just "a few merges" in observe mode. Measurements are computed once per mode and reused across tiers.

| Tier | Checks | Claim / limit | Blocking |
|---|---|---|---|
| **T0** | `gen2-boundaries` (import boundaries), `gen2-size`, `gen2-metrics` (edges, fan-in/out, reach, propagation cost, cycles, smells, per-function complexity, ledgered), and the Gate D #4 supported-source guard. **Change-impact summary:** edges added or removed, components touched, reverse-reach (blast radius) of changed files, complexity deltas. **CONTRACT / LEDGER / PROTECTED** banners. | The import graph is gen2-metrics' declared semantics; it excludes injected protocols and calls (`gen2_metrics.py:15–20`). Blast radius is reverse import reach, not runtime impact. | the existing gates yes; the summary and banners are signals |
| **Acceptance (PR)** | **Interface-change report:** each component's public surface (exported names and signatures), `gen2/schema` JSON schemas, DDL tables and columns, gateway HTTP/MCP routes, diffed against the merge base. A compatibility policy has to be defined before it can block. **Observed runtime coupling:** cross-component *module import* edges recorded during tests, compared like-for-like with the static import graph. A runtime-only *call* through injection is a separately classified observation, not a blind spot. **Test locality / impact map.** | Dynamic traces are coverage-bound: they supplement the static graph and are never ground truth or a complete test-selection oracle. They are **not** the 2q-a root repair, which stays the supported-source contract plus adversarial analyser fixtures. Tracing overhead on timing-sensitive tests is measured first. | reports first; promotion per criteria. A runtime-only import edge not in the static graph is an analyser finding that needs a fix or a reviewed rule amendment. |
| **T2 (gateway DB)** | Contracts for gateway database authority and schema (roles, `servable_records` view, DDL), with their integration-test evidence linked into the bundle. | Covers what the DB suite exercises. | the DB suite yes |
| **Mutation** | Rule mutants for the boundary and metrics checkers (they already exist for gen2-metrics). | Measures checker test strength. | yes |
| **Integration / nightly (deep)** | **Absolute audit** report, under its own policy: thresholds, accepted historical debt, escalation. Making existing debt a blocker is an amendment. **Change coupling and hotspots:** a review lead, *not* proof of hidden coupling, since shared task commits and generated files co-change. **Duplication** (token/AST clones; scope and exclusions defined). **Dead code** (reviewed allow-list). **Boundary type contracts** (annotation coverage and type-checking of boundary modules; `Any` and unchecked dependencies don't count as proof). **Stability:** reuse gen2-metrics' existing measures (`gen2_metrics.py:22, :69–74`). **Abstractness/cohesion:** new, advisory. | Detectors produce false positives, and a baseline controls old findings only. Each has scope, exclusions, reviewed exceptions and evidence of being actionable. | absolute audit report-only until its policy is approved. Hotspots stay **advisory** per BUILD-CHARTER:27 unless the operator amends it. The others are report-only until calibrated. |
| **Nightly Gate D pack** | **Trend series** (every merge's numbers). **Traceability table** generated from a **reviewed mapping** with pinned document identities, separating *declared implementation* from *verified coverage*. The locator check only proves that locators exist. A **sourced Gate D input bundle:** trends, smells, hotspots, observed-coupling findings, interface changes since the last Gate D, duplication/dead-code deltas, the traceability table, defect-family history from REVIEW-LOG, and the debt register. | **Gate D keeps its fresh-session semantic judgment.** The pack lists deltas and explanations; Gate D judges completeness and adequacy. Private flow documents are not published. | report-only |
| **Scaffolding** | CodeGraphContext and Emerge, regenerated in a **separately provisioned advisory job** that is never a product-build dependency (BUILD-CHARTER:29–33), with source, tool and config identities attached. | Approximate views; any finding must be confirmed in code. | never |

**Gate D pack freshness (RR2).**
- The pack is prepared nightly, but it is **assembled or refreshed on every Gate D trigger**: task acceptance, phase end and the third BLOCK.
- It is bound to:
  - the declared review SHA;
  - the previous Gate D comparison pin;
  - the identities of the documents and the reviewed mapping;
  - the analyser, tool and config versions.
- An existing result is reused only when all of those identities match. Absent or stale optional analyses are shown explicitly, never as clean results. Required inputs are refreshed, or obtained independently, before Gate D issues its verdict.
- Scaffolding (CodeGraphContext/Emerge) is refreshed **for the same review pin**, as BUILD-CHARTER:33 requires.

**First-slice additions (from the re-review):**
- **Non-import coupling.** Include deltas of gen2-metrics' implicit collaboration (C3-attributed self-calls) alongside import reach, keeping the two edge meanings distinct. Compute impact over **both base and candidate** graphs, so deleted edges don't erase their former dependents.
- **Support for Gate D's semantic questions.** A short, reviewed change/risk note and a **release-scenario table** covering crash, replay, fencing, stale lease and outage: the boundaries affected, the named test evidence, and remaining risks or the later phases that own them. Add prompts for duplicate mechanisms, parallel representations and special cases created by repairs. Clone counts and import graphs can't answer these questions.
- **Trend comparability.** Annotate changes to the analyser, contracts and baseline. Compare on a common analyser version where needed. A discontinuity caused by a change in measurement is never reported as an architectural improvement.
- **Complexity of the verification tooling,** as a separate **advisory** view: the metrics analyser, the mutation runners and the CI harness. 2q-a showed complexity accumulating there. This is never folded into the production ratchet.

**Start with** the impact and interface reports and the sourced Gate D pack, kept advisory and calibrated on known violations and legitimate changes. The pack is useful from day one, with sections that aren't available yet marked as such. Add deeper detectors (tracing, clones, dead code, boundary typing) as they prove their value.

### 3.10 The architecture ratchet: one authority per property (R11)

- gen2's `gen2-boundaries`, `gen2-size` and `gen2-metrics` stay **blocking in lint** under the current contract. They enforce different properties: gen2-metrics does not replace boundaries or size.
- Platform archgate stays **observe-only**, with its lizard CCN marked **advisory, a different measure**. Its tool and config errors are handled as infrastructure failures, separately from findings.
- A **narrow, library-owned adapter contract (C3)** is requested only after the gen2 checker is accepted. It names the required checks, normalises reports and exit semantics, and keeps the platform's enforcement slot. There will be **no** general per-repo "disable archgate" switch.
- **CI never folds ledger entries or rebaselines** (Makefile:57). Only reviewed changes do.

## 4. Qualification before CI becomes the verifier of record (R1)

The original criterion of five agreeing landings is replaced by a **qualification checklist plus a shadow-run window**:
1. **Identity, cleanliness and evidence (§3.1, §3.8) are implemented and checked.**
2. **Failure-path drills**, each producing the correct non-passing, evidenced result:
   - a missing DB or TLS prerequisite;
   - omitted tests;
   - a bad selector;
   - a crash-kill;
   - a protected edit;
   - a stale result after a target update;
   - a timeout or abort;
   - a publication failure.
3. **Full-target equivalence at the same execution pin.** Expected test and mutant **identities and outcomes** match the orchestrator's run. Totals or durations alone don't count.
4. **A shadow window.** The orchestrator's reruns continue in parallel and the agreement record is kept. Five agreeing landings is *supporting* evidence only.

After qualification, routine local reruns stop. The orchestrator re-runs when CI is unavailable, disagrees, or the harness, selection, environment or evidence is suspect.

**Astra after qualification (D3).** Astra may cite complete, pinned CI runs instead of re-running targets. What is lost is an independent checkout, environment, invocation and interpretation of results. What Astra keeps:
- Gate C's independent semantic and oracle review;
- independent reproductions and controls;
- **mandatory reruns** whenever the verification machinery is suspect.

Gate D stays fresh-session. A CI pass is never acceptance of the tests or of the task's scope.

## 5. Workflow and the charter state machine (R13)

- **Task branches and worktrees with PRs into `gen2`.** **One coder** to start. **The operator merges**: platform ARCHITECTURE.md denies agents merge rights, and any change to that is a separate trust-policy decision.
- **Stable task and family IDs.** Astra issues verdicts against reviewed SHAs. A CI failure or PR update is not an Astra BLOCK, and renaming or replacing a branch doesn't reset a task's history. The third-BLOCK Gate D trigger, the family redesign rule and the fresh-session rule are recorded per task and family ID, not remembered.
- **Charter transitions, recorded rather than remembered (RR1).** The charter governs. This table records it:

| Event | Required action | What stops | Who records it | What permits continuation |
|---|---|---|---|---|
| Task accepted (Astra PASS at the reviewed SHA) | A fresh-session **Gate D** (unless an operator sequencing ruling says otherwise, e.g. the post-2b one) | the next task's dispatch | orchestrator: task ID, reviewed SHA, Gate D session ID | Gate D PASS / PASS-WITH-FINDINGS, or an operator ruling |
| Phase end | A fresh-session **Gate D**, then an **operator phase-transition approval** | all next-phase work | orchestrator | Gate D verdict **and** operator approval |
| Third consecutive reviewer **BLOCK** on a task (CI failures, PR updates and branch replacement don't count and don't reset) | A fresh-session **Gate D** before the next repair | repair dispatch for that task | orchestrator, against the **task ID** | the Gate D verdict and its finish line |
| Third round in a **defect family** | A **family-level redesign** brief (not another narrow repair) | narrow repairs in that family | orchestrator, against the **family ID**, kept separately from the task's BLOCK history | the redesign brief is dispatched and reviewed |

  Each record carries the reviewed SHA and, for Gate D, the fresh session's identity.

  When D2 is approved, the charter's "branch `gen2` only" coder line is narrowly amended to allow task branches and worktrees. That amendment does not authorise extra coders or agent merges.

- **The orchestrator owns shared state** (BUILD-STATE, REVIEW-LOG, phase-status) and **serialises** acceptance, integration and phase transitions.
- After a rebase onto the accepted integration head, mutation controls and metrics state are **regenerated**. Baselines are never mechanically merged, identity serials are never reused, and stale traces are never accepted.
- **WIP limit** on the review queue.
- **A second coder** only after measuring review and CI capacity, and only for tasks that are disjoint in *contracts and shared metadata*, not just file paths.
- **Recorded:** review rounds, family reopenings, queue time, compute time and agent usage as each agent reports it. Account-wide subscription-window changes are never attributed to a single review (per the usage-attribution rule). The product's usage obligations (2e1 capture, the Phase 3 estimator) stay separately owned.

## 6. Platform requests (revised, in priority order)

1. **C4 — the execution boundary.** Library-created no-egress containers, an audit of the effective mounts and privileges, and dependency provisioning kept separate.
2. **C5 — evidence.** A sanctioned artifact set for a versioned `gen2-evidence.json` and raw evidence, a controller-bound manifest with the final result and incomplete states, retention and export, and publication outside the cut-off.
3. **Prerequisites:**
   - workspace and cache cleanliness;
   - an immutable library and image identity recorded per run;
   - correct check-to-SHA binding (merge commit against head);
   - durable failure artifacts;
   - the **integration interlock**, which must not be aborted by `abortPrevious`.
4. **C1 (minimal) — a platform-owned scheduled mode** with gen2 opt-in for nightly. Arbitrary repo-defined stages aren't needed: repository orchestration runs under the fixed lint/build/unit order, with JUnit.
5. **C2 — resource class or shards**, only after worker budgeting is fixed and costs are measured. Tower capacity is not the worker's 8 vCPU / 16 GB and two executors.
6. **C3 — a narrow boundary/metrics adapter**, after gen2's checker is accepted.
7. **C6 — none initially.** The policy reports are repository logic under lint, compared against a trusted base policy. Common mechanics move to the library only after experience with them.

## 7. Implementation order (Astra's order, adopted)

1. **Ratify the execution/acceptance boundary** and keep the charter's authority over acceptance. **Fix the canonical-origin defect** (§8) and settle the reference environment versus the supported environments.
2. **A reproducible, complete CI environment:**
   - gateway dependency lock, PostgreSQL, psycopg/libpq, openssl;
   - clean runtime state and the required history;
   - explicit worker budgets, including the `os.cpu_count()` fix;
   - split gateway modes.
3. **Evidence and trust:** evidence publication, correct status/SHA binding, no-egress execution (C4), and failure-path drills. **Full engine and gateway acceptance on every PR.**
4. **Review signals and early architecture reports:**
   - protected-path and test-integrity reports;
   - **subprocess-aware mutation validity**, including repairing the six crash mutants;
   - the architecture impact and interface reports;
   - the sourced Gate D pack, including the T2 contribution.

   New checks are observed and calibrated before reviewed enforcement.
5. **Workflow:** task branches and worktrees, one coder, operator merges, a serialised review and integration queue. Complete the §4 qualification and shadow window, then retire routine local reruns.
6. **Integration interlock:** full integration verification with its pending/red/aborted interlock. **Validate conservative diff selection against full runs**, then use it to cut eligible PR-update work.
7. **Nightly work:** bounded nightly stress, drift and absolute-audit jobs, and progressively deeper architecture analyses. Settle the absolute-audit and hotspot policy and the scaffolding boundary. Consider higher caps, the adapter and a second coder only when the measurements justify them.

Each step is a build-out on a branch, tested there, and merged into `gen2` only after operator confirmation.

## 8. Immediate finding: canonical origin (outside the CI work)

`gen2/gateway_client/client.py:195` renders addresses with `str(ip)`, and CPython 3.12.14 changed that output for IPv4-mapped IPv6 addresses.
- **Root fix:** a **project-owned canonical serialisation** of each parsed address's value and family. Use it consistently for the origin, the host and the admitted-address representation, and keep the accepted spelling unless the contract is deliberately amended.
- **Not a fix:** `.compressed` also delegates to string rendering, and changing the expected string just swaps which interpreter the code depends on.
- **Test:** equivalent dotted and hex mapped inputs, and the other accepted and refused forms, on the reference interpreter and on newer ones.
- **Also pin the reference environment precisely.** Pinning serves reproducibility; on its own it would be a portability **mitigation**.
- **Severity:** a representation/acceptance defect only. It doesn't cause a wrong-destination connection or a token leak.

## 9. Decisions for the operator

| # | Decision | Recommendation (Astra and orchestrator agree) |
|---|---|---|
| D1 | CI as the authoritative execution record | **Yes, after the §4 qualification.** |
| D2 | Task branches/worktrees/PRs | **Yes, with one coder and operator merges.** Concurrency and merge authority are separate, later decisions. |
| D3 | Astra cites CI runs instead of rerunning | **Yes, after D1's prerequisites.** Gate C/Gate D independence kept, with mandatory reruns when the machinery is suspect. |
| D4 | GitHub Actions | **Operator ruling 2026-10-05: no GitHub Actions at all** (no paid minutes). The drift job (current 3.12.x, 3.13, latest SQLite) runs in the **Jenkins nightly** mode instead, as variant images. `.github/workflows/gen2-check.yml` will be removed or disabled once the operator confirms which. |
| D5 | Canonical origin | **Root fix and pin the reference.** |
| D6 | Platform requests | **The revised, prioritised set in §6.** |
| D7 | Pre-merge full verification and the integration interlock | **Approve.** |
| D8 | Owners of protected paths, oracle amendments, and who can authorise quarantine | **Operator** for the oracle and quarantine; owners named per path. |
| D9 | Evidence retention and drift-response deadlines | to set |
| D10 | CI/review WIP and spend budgets before any parallel coding | to set |
| D11 | Which §3.9 architecture measures may become blocking, and under what reviewed thresholds | **New blocking thresholds are deferred until calibration.** These apply now: hotspots stay advisory (BUILD-CHARTER:27), scaffolding stays external (BUILD-CHARTER:29–33), and Gate D freshness follows §3.9 RR2. |

## 10. Disposition of Astra's findings and corrections

**Findings:**

| Astra finding | Where addressed |
|---|---|
| 1 HIGH: T3 selector and backstop ordering | §3.2 modes, §3.3 selector contract, §7 steps 3 and 6 |
| 2 HIGH: crash-kills are subprocess-boundary failures | §3.5 |
| 3 HIGH: identity, cleanliness, evidence; five landings not enough | §3.1, §3.8, §4 |
| 4 HIGH: network isolation scope | §3.6, R8 rescoped, §6 item 1 |
| 5 MED: signals, not authorisation | §3.4, P8 |
| 6 MED: adapter reading too broad; absolute audit and hotspot policy | §3.9, §3.10, D11 |
| 7 MED: timings are budgets; gateway env underspecified; `cpu_count` | §0, §3.1, §3.2, §7 step 2 |
| 8 MED: preserve the charter state machine | §5, R13, D2, D8, D10 |
| 9 MED: canonical-origin root fix | §8, D5 |
| 10 MED: overclaimed §3.9 conclusions; T2 missing; `gen2/schema` path | §3.9 rewritten |

**Research corrections**, absorbed throughout:
- TDAD's regression cut is test-level only, so no expected reduction is imported.
- PyCG's recall is specific to its evaluation.
- Soundiness is distinct from the proposed exact-subset contract (P5).
- F109 and F113 qualifications are kept: low-to-moderate confidence, and defect prediction rather than a blocking threshold.
- JENKINS-47103 is not load-bearing.
- **The SLSA "self-hosted ⇒ L2 ceiling" claim is deleted.** Levels depend on provenance and isolation properties; this platform hasn't demonstrated L3.
- §12 gives URLs, full corpus keys, the capture date and links to the retained records, with the inference drawn from each (RR3).

## 11. What we don't cover today (revised gap list)

1. **Supply chain:**
   - dependency audit across gen2's locked packages, **the gateway interpreter's packages, OS packages and CI tools**;
   - record build inputs and image provenance now; formal SLSA attestation waits for release needs.
2. **Claim drift:** generate execution counts and check *current* claims against them. Historical review counts are never rewritten automatically.
3. **Performance budgets:** decode-cost and run-time regressions, measured, not assumed.
4. **Migration rehearsal:** refusal of altered schemas is already tested (`test_sqlite_gate.py:305`). The gap is a named **historical-store migration rehearsal contract** on synthetic old stores, for Phase 4.
5. **Deployment integration:** `deploy/gen2` already has an image, compose and an auth demo. What's missing is network-isolated compose-based integration verification before 2f.
6. **CI self-tests:**
   - omitted work;
   - corrupted or stale evidence;
   - cancellation and cleanup;
   - failure publication;
   - fixture and oracle provenance;
   - schema and version compatibility of evidence;
   - an **owned response deadline and routing** for drift and stress findings.
7. **Operational claims stay phase-owned:** provider qualification (Phase 4), actual runner isolation (2e1), usage/budget accounting (2e1 and Phase 3), retrieval-audit evidence (2e2). Offline CI can't settle them.
8. **Deferred:** blanket advisory LLM review and model leaderboards. Attribution and cost data are collected first, because cross-task, cross-harness model comparisons are confounded.

## 12. Evidence used

Corpus records were queried on 2026-10-04 through homelab GraphRAG `hybrid_search`. Astra's retained copies, hashes and its read-only Cypher verification are in `private/evidence/astra-ci-design/` (start with `input-manifest.json`).

| Inference | Source |
|---|---|
| External execution feedback beats self-correction; test-feedback loops raise both genuine passes and cheating | GraphRAG `llm-performance-evidence`: self-correction findings (`method:finding:f108eff0-7a2e-5bdd-9cff-5fb0a69bb670`); Conflicting-SWE-bench (`method:finding:100fabe9-4067-57a1-9fbb-7b200bf8afd7`); primary: ImpossibleBench §5.3, https://arxiv.org/html/2510.20270v1. EvilGenie, https://arxiv.org/abs/2511.21654 (a deliberately gameable benchmark: supports oracle ownership, not a claim about this build's coders). |
| Diff-time delivery of analysis findings | `codegraph-evidence` `cg:finding:ffece4b7-1ffd-50e4-acd8-e531b18f42d6` (Infer at Facebook; primary CACM page returned 403, so the stored record was verified). Does not establish selector correctness. |
| Diff-scoped mutation needs full backstops | cargo-mutants https://mutants.rs/in-diff.html; Mull incremental docs, https://mull.readthedocs.io/en/latest/IncrementalMutationTesting.html; `agentic` Branch 14 (`96179b10-1a16-516f-8525-20996a08986f`). |
| Test-impact context | TDAD, https://arxiv.org/html/2603.17973v1, Table 4 (test-level regression only; instance-level not improved); `agentic` `32d049f7-224d-5b97-9ed2-308904596693`. |
| Limits of static analysis; static and dynamic graphs complement each other | `codegraph-evidence` soundiness (`cg:finding:057df12d-17af-5c2b-a6f1-bf4791749ce4`, `cg:finding:4b09b961-69c2-5a05-a9c3-2f8265848990`; https://yanniss.github.io/Soundiness-CACM.pdf); PyCG (`cg:finding:cac73dae-e89b-5f43-ab2f-7b0b456a75d5`, https://arxiv.org/abs/2103.00587; its benchmark's recall only); dynamic baselines are coverage-bound (`cg:finding:64f4de3f-911d-5b0c-a011-1999f015d5bf`); combining tools (`cg:finding:10f70b31-6bc6-5a57-898f-4166d782c631`). |
| Flake discipline | `agentic` Branch 14 (`18df2bc7-bde0-5159-b3f3-2f15e2774cca`) and Branch 17 (`a326f662-810c-588d-9fa5-403e3ebca027`); platform ARCHITECTURE F4. |
| Agent code duplicates more, reuses less | *More Code, Less Reuse*, https://arxiv.org/abs/2601.21276; GitClear 2025, https://gitclear-public.s3.us-west-2.amazonaws.com/AI-Copilot-Code-Quality-2025.pdf (aggregate trends, not per-change cause). |
| Network centrality as an investigation priority | Zimmermann & Nagappan; `software-architecture` ORIG-4.10/SRC-115 (F113); defect prediction on Windows Server 2003, not a blocking threshold. |
| Enforcement turns routing-around into reviewable diffs | `software-architecture` ORIG-4.1 F109 (low-to-moderate confidence, single practitioner source). |
| SLSA | https://slsa.dev/spec/v1.2/build-requirements. |
| Docker `none` network has no IPv6 loopback; Jenkins Docker volume inheritance | https://docs.docker.com/engine/network/drivers/none/; https://www.jenkins.io/doc/book/pipeline/docker/. |
| Platform facts | `trevorbyrum/ci-cd` at `3a8d29f`: ARCHITECTURE.md (Zones, F1–F6, Layers 0–2), `standardPipeline.groovy`, `docs/archgate.md`, `docs/agent-ci-guide.md`, `infra/cim/casc/jenkins.yaml`. Jenkins gen2 build #1 console and results (in Astra's evidence). GitHub Actions run 37178375414 (Python 3.12.14). |
