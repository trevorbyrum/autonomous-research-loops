# Gen-2 Build Charter

Operator-authorized 2026-09-25. Governs the background build loop until the operator amends it.

## Authorities (fixed)
- **Orchestrator — Fable (this session's loop).** Sequences phases, writes task briefs, dispatches coders and reviewers, maintains BUILD-STATE.md and REVIEW-LOG.md, reports to the operator. Never writes engine code, never merges to main, never overrides a review verdict. Scope questions and authority changes escalate to the operator.
- **Coder — GPT-6.1-Sol or Claude Sonnet 5.5, chosen per dispatch to balance subscription usage** (the user, 2026-10-27: "Make sure you're mixing up SOL 6.1 with sonnet 5.5 so you're balancing out the subscription usage"). Sol is the paseo `codex` provider, model gpt-6.1-sol, thinking xhigh, mode full-access. Sonnet is `claude/claude-sonnet-5-5`, bypassPermissions. The orchestrator reads current usage before each dispatch, and with two coders prefers one of each. *(Earlier: Sol only, from 2026-10-09: "use sol for the coding instead of sonnet since usage is getting low with claude".)* Previously Claude Sonnet 5.5 (2026-10-05 to 2026-10-09), GPT-6.1-Sol (2026-10-03 to 2026-10-05), Sonnet 5.5 (from 2026-10-01) and Opus 5.5 before that; a task already running finishes on its model. A coder never reviews: Astra (gpt-6-astra) stays the reviewer, and a coder session is never reused as a reviewer. One coding agent at a time per worktree; **up to two coders at once on independent tasks** (operator ruling 2026-10-26), each in its own worktree with its own PR, verifier and Astra review, and never two coders on overlapping files. Coders work on a task branch `<agent>/<task>` in their own worktree and open a PR into `gen2`. CI is the execution record once the CI design's §4 qualification is met, and **the operator merges**. This narrow amendment was approved by the operator on 2026-10-05 (CI design D2); it does not authorise extra coders or agent merges. Until the PR workflow is live, coders keep working on `gen2` directly. Implements exactly its task brief; every brief names the flow-doc sections and BOUNDARIES.md entries it touches. Deviations from the brief are proposals in the completion report, not silent changes. Commits carry the standard attribution lines.
- **Reviewer — Astra (gpt-6-astra, xhigh, codex provider).** Gates below. Read-only on code + its own report file. A gate verdict of BLOCK stops the phase until resolved; the orchestrator may not soften a verdict, only route it (fix task, or escalate to operator).
- **Operator — the user.** Merges to main; approves phase transitions flagged `operator-gate`; resolves anything the charter doesn't settle.

## Source-of-truth documents (reviewers check against these, in this order)
1. `gen2-flow-architecture-20260924.md` (amended 2026-09-25) — stages, boundaries, decision ladder, observability.
2. `methodology-synthesis-20260924.md` (amended 2026-09-25) — research basis with [corpus]/[anchored]/[proposed] statuses.
3. `reviews/gen2-design-astra-review-20260922.md` and `reviews/flow-adjudication-astra-20260924.md` — settled constraints and rulings.
4. `docs/gen2/BOUNDARIES.md` (this repo) — the operational boundary contract; drift between code and this file is itself a review finding.

Items 1–3 are cited by document identity (file name and dates). They belong to the design record kept outside this repository, not to the repository itself; each review's input manifest records the copy it read and its SHA-256.

## Review gates (every phase; no exceptions)
**Gate A — Architecture/boundary conformance.** Astra reviews the phase diff in detail against the flow doc and BOUNDARIES.md: every component's role matches its boundary entry; no actor writes outside its authority; hand-off artifacts are typed as specified; the decision ladder and commit protocol match the amended design. Verdict per finding: CONFORMS / DEVIATION (with severity) / BOUNDARY-DRIFT (code and BOUNDARIES.md disagree — one of them must change via the amendment path).
**Gate B — Research-context audit.** Astra checks that every research claim the code or its comments/docs rely on is used within the scope the methodology synthesis records — and independently flags anything where OUR documents took the research out of context and the build inherited it. New findings of research misuse are logged to REVIEW-LOG.md and, where they affect the design docs, escalate to the operator.
**Gate C — Adversarial test review.** No test is accepted without a per-test verdict on: (1) what the test *actually* asserts, stated back independently; (2) whether that assertion tests the thing the test claims to test; (3) whether the oracle is independent (not derived from the implementation under test, no self-referential fixtures); (4) whether it would catch the enumerated failure modes it exists for (crash/replay/fencing/stale-lease etc. per the flow doc's release gates); (5) what it structurally cannot catch. Tests failing any of 1–4 are rejected with the rewrite stated. "Green suite" is never evidence by itself — gen-1's suite was green while testing contradictory behaviors in separate files.
**Gate D — Whole-system architecture and complexity review** (the user, 2026-09-30). Gates A–C review one task's diff, so drift that accumulates across tasks is never seen whole; Gate D reviews the entire built system. It runs **when a task is fully accepted (every repair round cleared) and at each phase end**, and a BLOCK stops the next task from starting. Astra checks: (1) **traceability** — every stage, boundary, hand-off and release gate in the flow doc is either implemented and tested (naming where) or explicitly scheduled for a later phase; anything built differently from the doc is a finding; (2) **complexity** — the automated architecture metrics below, with every regression since the last Gate D explained, plus accidental complexity the metrics can't see: two mechanisms for one job, parallel representations of one fact, special cases added by repairs; (3) **quality-attribute risks** — a lightweight scenario review of the flow doc's release gates (crash, replay, fencing, stale lease, outage), naming risks and sensitivity points.
**Gate D independence (the user, 2026-09-30: "I want a fresh Astra on the architecture review every time. I don't want other gates tainting it.").** Every Gate D run is a **new Astra session** that has never run another gate and is never resumed or reused for one, so no reviewer's working context carries over between gates. It works in the normal repository and may read anything there, including REVIEW-LOG.md and earlier review reports.

**Mutation testing (operator rulings 3, 2026-10-24, and mutation scope, 2026-10-25; replaces the hand-written mutant inventory, paired controls, reload and attestation reviews).**
- `make gen2-accept GEN2_BASE=<merge-base>` runs Cosmic Ray on the **production lines the change touched** (native `cr-filter-git` against the explicit merge-base). (Trigger-order, which used to run before it on DDL changes, was retired by S2-2 on 2026-10-27.)
- Any surviving mutant fails acceptance, unless the line carries `# pragma: no mutate` with a reason, which Astra reviews in Gate C.
- Timeouts, internal errors and syntax-invalid variants are never kills. Test errors are reported separately for review.
- Full-production campaigns (`make gen2-mutation-report`) are **report-only**, run at phase gates and Gate S, and never block.
- Gate C keeps its per-test oracle questions.

**Gate S — Whole-system simplification (the user, 2026-10-24: "you guys tend to get overly focused on single issues… code in general is not made good or better by adding and stacking code").** Gates A–C judge one slice against its own contract. Gate D runs only when a whole task closes; 2d ran for weeks as one open task, so Gate D never fired while slice-level fixes accumulated. Gate S keeps the end goal in view continuously.
- **Owner:** Fable (paseo `claude/claude-fable-5-1`), a **fresh session every run**, outside the coder/reviewer loop. It never codes, never gates a slice and never overrides an Astra verdict. A second independent opinion (for example a fresh Astra) is optional.
- **Triggers.** The orchestrator checks these on every wake, using `git diff --shortstat <last Gate S SHA>..origin/gen2`:
  1. Before any new task, slice or part is designed, so Gate S sees the plan before a contract is written.
  2. After about **2,000 lines of net growth** since the last Gate S, counting production, SQL, tests and tooling together.
  3. When a slice passes **2× its estimate**, or a **finding family recurs** in the same area. The orchestrator routes this to Gate S as a design question ("is there one change that resolves all of these?"), not to the coder as another patch.
  4. At every phase gate.
- **Each run answers:**
  - Does the next planned work trace to a binding requirement?
  - Is there one design that resolves the open findings together?
  - Which mechanisms overlap?
  - What can be deleted?
  - Is the checking machinery proportionate, or generating its own work?
  - What is the net size change since the last run?

  Its cut list feeds the next brief. Anything that would amend an invariant, a ruling or a contract goes to the operator as a decision.
- **Records:** each run gets a REVIEW-LOG entry. BUILD-STATE always shows the last Gate S SHA and the growth since.

**Always-on simplicity rules (every brief and review).**
- **Trace every obligation.** Each acceptance-contract item cites an invariant, an operator ruling or a DEBT-REGISTER entry. An item that can't be traced is cut, not built.
- **Astra's proportionality question.** Every slice review also asks: is this the simplest design that meets the contract, and does any part duplicate an existing mechanism?
- **Group before routing.** Before turning findings into a fix task, the orchestrator groups them by shared cause and looks for one design change. Recurring families go to Gate S.
- **Honest size.** Estimates given to the operator are adjusted for the growth actually observed, not the plan figure. Every task-boundary size report includes tests and tooling next to production.
- **Added code is a cost.** Prefer deletion and reuse. A slice that grows the total needs to justify it against the end goal.

## Architecture metrics (the user, 2026-09-30; amended by operator ruling 3, 2026-10-24, Gate S #1)
Enforced by `make gen2-check`:
- the **boundary graph** (`gen2-boundaries`);
- the **1,500-line file rule** and the **15,000-line production growth trigger** (`gen2-size`);
- the **debt gate** (`gen2-debt`);
- **`gen2-complexity`**: radon cyclomatic complexity, with a blocking per-function ceiling and a blocking mean ceiling. These are set in the Makefile at the current worst observed grade (2026-10-25: 48 and 10). Changing either is a reviewed Makefile edit, with no ledger or exemption file.

Radon raw and maintainability output is advisory evidence for Gate D and Gate S. The custom propagation-cost, instability, smell and identity-ledger ratchet was retired in batch S3.

## Build scaffolding: code graph and dependency map (the user, 2026-09-30)
"Think of the code graph as scaffolding. It's not meant to ship with the product but helps with building it." Two tools, installed outside the repo in `~/.local/share/gen2-scaffold/` (their own virtualenv; never in gen-2's requirements, Makefile or `make gen2-check`):
- **CodeGraphContext** (`~/.local/share/gen2-scaffold/venv/bin/cgc`): a queryable graph of modules, functions and calls, for call-level questions the import-level boundary checker can't answer ("what outside tests opens the store" — `cgc query` with Cypher and file paths; bare-name commands like `cgc analyze callers` conflate same-named functions across gen2 and gateway). Its database lives in `~/.codegraphcontext/`; the one file it writes into the repo (`.cgcignore`) is excluded locally via `.git/info/exclude`.
- **Emerge** (`~/.local/share/gen2-scaffold/run-emerge -c ~/.local/share/gen2-scaffold/emerge-gen2.yaml`): an interactive HTML dependency map with fan-in/fan-out and Louvain clustering, for comparing how the code actually clusters with the declared module boundaries. Output in `~/.local/share/gen2-scaffold/emerge-out/`.
Both are re-indexed from the reviewed commit before every Gate D and are available to reviewers and coders. They are views, not evidence: their parsers are approximate (Emerge counts `__future__` as a dependency), so any finding they suggest must be confirmed in the code. Enforcement stays with the boundary checker and the ratcheted metrics.

## Root-cause fixes, not patches (the user, 2026-09-30)
"A patch's name implies its meaning, temporarily used to hold out until an actual fix can be made. The problem with agents is as soon as they apply a patch, it never gets readdressed."
- Every repair's completion report states the root cause and why the change removes it rather than the symptom.
- Reviewers classify every correction as **ROOT-CAUSE** or **MITIGATION**. A mitigation is anything that makes the reproduction pass without removing the cause: special-casing the reproduced input, loosening an accepted invariant/rule/test so the fix fits, a disclosed "known limitation" left in place, a shim with no removal condition, or a deferral with no owning phase.
- **A MITIGATION always blocks and escalates to the operator. Only the operator can accept one**, and an accepted one is logged in `docs/gen2/DEBT-REGISTER.md` with its owning phase and removal condition; the build fails if that phase closes with the entry still open.
- Relaxing an accepted invariant, rule or test is an amendment in its own right, reviewed as such — never a side effect of a fix.
- Third round on the same defect family: stop narrowing the fix and redesign the structure (the 1c and 2a precedent).
- **The classification runs at family level, not only per finding** (the user, 2026-10-02, after 2b ran twelve review rounds: "I literally had you add a review pass that specifically was meant to catch patches"). Every re-review must also answer: do this round's findings share a root cause with earlier rounds of the same task? A series of individually correct fixes for one shared cause is itself a **MITIGATION of the family cause**, even when each fix is ROOT-CAUSE for its own finding. The reviewer names the family cause, and the next brief must target it. The orchestrator's briefs must ask this question explicitly. Restating the reviewer's per-finding repairs is not enough.
- **A task that keeps failing review triggers Gate D anyway.** On a task's third consecutive BLOCK, a fresh-session Gate D runs before the next repair is dispatched, so the whole-system review can't be postponed indefinitely by a task that never closes.

## Build throughput (operator ruling 2026-10-26)
- **Parallel tests.** The unit suite and the stage-2 full-suite mutation runs execute as parallel shards whose union is the complete suite, with merged coverage contexts. Rigor and verdicts are unchanged; only wall time changes.
- **Design review before code.** From 6b1 onward, a new slice's design (its contract, the code it changes, and which existing predicates it reuses) gets an Astra review against the existing code before the coder writes it. This is for semantic mismatches like S4 round 1's.
- **Coder pre-check.** For mutation-sensitive changes, the coder runs `make gen2-accept` on a disposable copy before pushing, and batches all survivors into one push. The independent verifier still runs afterwards.
- **Two coders** on independent tasks, as in Authorities.

## Checking-pipeline rules (operator ruling S2-7, 2026-10-27)
- **Harness changes.** After S2d, the mutation and acceptance pipeline changes only when a real campaign produced a wrong verdict: a survivor later shown killed, or a kill later shown false on clean code. A reviewer-constructed harness adversary is recorded as non-blocking unless the suite can produce the condition.
- **Cost before review.** A tooling repair states its cost budget in the brief and measures it before review (the S2b-C1 lesson).
- **Trigger-order is retired** (S2-2). S6's final DDL baseline passed at `ed21d5a` (242 triggers, 1,868 identical outcomes), and the tool, recipe and CI mode were removed in PR #55.

## Nightly test-portfolio review (Trevor, 2026-10-28; v2 rules 2026-10-28/29)
Every test is asked one question: is it important to the overall objective and architecture?

**How it runs**
- **Sol** runs nightly, read-only, at 08:00 UTC, with a full baseline first.
- **A fresh Fable session** verifies Sol's proposals and approves or rejects each one at 12:00 UTC.
- **Approved items** become coder batches.

**Tiers** (`private/reviews/test-portfolio/TIERS.md`)
- A test takes the tier of the most critical rule it protects.
- Tests of merge-gate machinery and test oracles inherit T1.
- The tier table is approved once by Trevor.

**What runs automatically, and what comes to Trevor**
- **Automatic:**
  - T3 and dead deletions with no catch record;
  - T2 and T3 moves of zero-reach tests to a nightly lane, once the lane is built after measurement;
  - merges into one keeper test with no lost assertion, at any tier;
  - strengthening and restoring at any tier.
- **Landing:**
  - **Removals** (deletion, move, exact-duplicate merge) land on a path allowlist, an inventory diff, the verifier and Jenkins, without Astra.
  - **Edits** keep Gate C.
- **To Trevor:**
  - T1 and T2 deletions;
  - any change to a test with a catch record;
  - traceability changes.
- **Production code** is not in this pass; Gate S keeps it.

**Sources**
- Plan: `private/reviews/test-portfolio/PLAN-v2-20261028.md`, including §8.
- Research basis: `Autonomous-Loop-Design/research/agentic-build-process-2026-10/06-gap-round-2-full-text/01-retiring-checks-and-tests.md` and `04-criticality-scaled-assurance.md`.

## Review throughput (the user, 2026-10-05)
Adopted after asking what research suggests for speeding up the build. The research: repair loops get most of their achievable gain within 3–4 rounds (arXiv 2607.05197). Review rounds and turnaround grow with change size (Google's modern code review study; Greptile's analysis). Expensive suites belong once at the gate, not on every iteration (Google's diff-based mutation testing; merge-queue practice). These rules apply from the next dispatch onward. They do not change a review already running.

- **Blocking findings, defined.** A finding blocks only if, in realistic operation, it could:
  - (a) produce a wrong research result or a false completeness, exhaustion or sufficiency signal;
  - (b) leak a credential or token, or widen a permission;
  - (c) lose or corrupt durable data;
  - (d) break an invariant or contract the operator ratified;
  - (e) let a check or test claim to enforce a blocking-class property when it doesn't.

  Everything else is **non-blocking**. The reviewer records it, and the orchestrator logs it in `docs/gen2/DEBT-REGISTER.md` with an owning task or phase and a removal condition. The operator accepts these entries in advance, by this rule, so they don't escalate one by one. The ROOT-CAUSE/MITIGATION classification still applies, and a MITIGATION of a blocking-class finding still blocks and escalates.
- **Re-reviews raise only blocking findings.** After a task's first review, a re-review judges the previous round's blocking findings and raises **new** findings only if they are blocking-class. New non-blocking observations go to the register, not the verdict.
- **Round cap.** On a task's **third consecutive BLOCK**, the orchestrator stops dispatching and sends the operator a short summary: what remains, its blocking class, and the family verdict. The operator decides whether to **accept the remainder as debt** (registered with owner and removal condition; the task closes) or **continue**. If the operator continues, the Gate D rule above runs before the next repair.
- **Small slices.** A brief scopes a change to a few hundred hand-written lines; a guide of ≤ ~500, excluding generated files such as the mutation-controls JSON. Larger work is split into sequential slices, each landed and reviewed on its own. A repair brief targets the blocking findings and their family cause, not every observation.
  - **Mechanical batches** (the user, 2026-10-22): a brief may declare one mechanical batch of up to about 800–1,200 hand-written repository lines. It must implement a single reviewed transformation, include the complete consumer closure, preserve assertion intent, and introduce no independent policy decision. New behavior keeps the ~500 guide. Private evidence is reported separately and doesn't count.
  - **Agree "done" before coding** (the user, 2026-10-22): every brief carries an acceptance contract. It names the property, the entry paths, the supported statement or mechanism set, the expected outcomes, the controls and the stated limits. Operator decisions are listed in a short decision table and asked before code. The reviewer judges against the contract; a real counterexample inside the ratified property still blocks.
- **One full test run per round, by an independent verifier** (the user, 2026-10-22; supersedes the earlier orchestrator-run landing). There are three separate roles:
  - **The coder** runs only static gates, the affected tests and the affected `--only` mutant families (including transitive fixture consumers) for what it changed. It doesn't run the full targets.
  - **The verifier** runs the full set once on the frozen candidate: `make gen2-check`, then `make gen2-gateway` when production or gateway inputs changed (otherwise gateway evidence is carried forward with its pin). It runs unpiped, on its own clean clone, and that is the round's execution record.
    - The verifier is neither the coder, the reviewer, nor the orchestrator. Until CI qualifies, it is a fresh Sonnet 5.5 agent per round, briefed by `docs/gen2/VERIFIER.md`. It can't edit the repository and reports raw exits and logs.
    - Once the CI design's §4 qualification is met, CI is the verifier and the sole routine full record.
  - **The reviewer** uses that record and doesn't rerun the full targets. It may rebuild specific mutants, run targeted tests, and request an independent rerun if it suspects the harness.

  If the verifier's run fails, the coder fixes it before review is accepted. The orchestrator routes results and keeps the state docs; it doesn't run or judge the full checks.
- **Refactor evidence standard** (operator authorisation 2026-10-08: "Okay, then do that"; research `docs/gen2/research/refactor-verification-20261008.md`; trial `docs/gen2/research/refactor-verification-trial-20261008.md`). Behaviour-preserving refactors use established tools, not per-slice custom proof tools:
  - **perform** the mechanical refactor with `rope` where it applies, and treat its output as untrusted, because the trial found a rope extract-method fault;
  - **describe** the change with RefactoringMiner (`tools/gen2_refactoring_detect.py`, pinned container, run offline), with expected refactoring counts;
  - **gate behaviour** with the existing test suite, diff-scoped automatic mutation, and Hypothesis `old == new` properties for pure functions.
  - **Amended 2026-10-24 (operator, Gate S #1 plan D2):** the exact replay oracle, the differential tool and the move/inline equivalence tools are retired. The Router refactors they certified are done, and their seams needed a repair for each new source of nondeterminism.

  The reviewer judges against this standard. Building or repairing a custom equivalence checker for a slice is no longer required. Existing accepted tools stay in place. Process identity and child-process determinism, which these libraries don't cover, still need a reviewed seam.
- **Research before re-briefing** (the user, 2026-10-05: "if issues crop up >1 time in reviews or we've circled through the cap of reviews, those things must be researched instead of assuming the coding agent is addressing them correctly"). The trigger is either of:
  - a finding family recurs in more than one review of a task;
  - a task reaches the round cap.

  Then, before writing the next brief or recommending debt, the orchestrator researches how the problem is best solved: the GraphRAG corpora, primary literature, and how established tools solve it. The result is written to `docs/gen2/research/`. The brief or recommendation cites it and says why the chosen approach is the best supported. The coder implements the researched design; it doesn't devise its own fix for a recurring family, and the reviewer judges against the cited research too.

## Separation practices (Trevor, 2026-10-27)
These are the reasons teams use separate repositories, adopted as process inside the one repository. **There's no code or repository restructuring; the repository-layout question is Trevor's to research.**
- **Each brief declares its component and file ownership:** the paths the coder may change, the paths it must not touch, and the components it may only read. One component per brief where possible. A brief spanning components says why.
- **Interfaces are changed contract-first.** A change to an interface between components (a BOUNDARIES.md entry, a schema, a Router or Store member another component calls, the gateway-client contract) is named in the brief. Where consumers in another component must change too, the interface change lands as its own small PR before or with them, never hidden inside unrelated work.
- **Briefs scope the agent's reading set** to its component, the contracts it touches and the binding documents. Agents don't roam the repository.
- **Already in place and unchanged:**
  - one worktree per coder, with disjoint file sets (2026-10-26);
  - small task PRs that land independently, each with its own verifier and review;
  - BOUNDARIES.md as the component contract;
  - size estimates with stop thresholds.

## Standing rules
- Build follows the adjudicated phase order (flow doc + Astra review §10): Phase 0 invariants/migration contract → 1 mechanical vertical slice (fake executors; crash/replay/cancel proven before model authority) → 2 one complete research workflow → 3 qualified automation/projections → 4 migration+canary. Phase transitions are operator-gates.
- Size rules (the user, 2026-09-29; replaces the earlier 10,000/12,000 total, which had been copied from the design review's *proposed* planning allocation without operator approval):
  - **Per-file limit: no hand-written file over 1,500 lines** (code, tests, tooling, SQL, config). It is enforced by `make gen2-check` over the gen-2 surface INVARIANTS B-3 lists (`gateway/` included since task 2b-repair; gen-1's `research_loops/` is not gen-2's and is outside it). Generated files (for example the mutation-control pairings and the generated catalog/env example) are exempt only by an explicit, reasoned allowlist entry.
  - **Total production code: 15,000 lines is a growth-review trigger.** When it is reached, the loop stops for a review with the user of what made it grow before building further. The total is reported at every task boundary. Tests, schemas, SQL, prompts and tooling are reported separately.
- Machine-checkable module-boundary graph in CI from the first commit; a boundary-graph violation fails the build.
- Jev is not a build dependency: everything must run and be testable with the decision layer disabled.
- No personal data in any live network call. Coders and reviewers never send the operator's email, name, accounts or credentials to a third-party service (for example a provider's contact or `mailto` field); use a placeholder or skip the live check. Tests use fixtures and fakes only.
- **Evidence is durable.** Coders and reviewers write probes, captures, fetched documentation and logs to `~/work/research-loops-public/private/evidence/<task-or-review>/`, never only to `/tmp` (a host reboot on 2026-10-01 wiped `/tmp` and lost 2b-repair-7's provider captures and the prior review's probes). Throwaway databases and scratch trees may stay in `/tmp`.
- **PR-only gen2** (the user, 2026-10-22). gen2 is a protected branch: a PR is required, the required check is `continuous-integration/jenkins/pr-merge`, and admins are enforced, so no direct pushes from anyone. main (gen-1) is not touched by the gen-2 build.
  - **Coders** branch from current `origin/gen2` as `task/<task-id>`, commit there, push the branch, open a PR **targeting gen2 directly**, and **do not enable auto-merge**. Once the independent verifier is green at the PR head **and** Astra has accepted, the orchestrator runs `gh pr merge <n> --auto --merge` (merge commits, not squash), and GitHub merges once Jenkins is green. The Jenkins PR check runs only T0 static gates, so it alone never licenses a merge (operator ruling 2026-10-23, after slice 5 auto-merged before review).
  - **No stacked PRs.** While a task's PR is still open, its repairs commit to the same branch, and the PR updates itself. After it has merged, a repair goes on a new `task/<task-id>-repair-<n>` branch from `origin/gen2`.
  - **The orchestrator** keeps records (BUILD-STATE, REVIEW-LOG, task files, DEBT-REGISTER) in its own worktree on `orch/records-<date>-<n>` branches. It batches updates into few PRs with auto-merge.
  - Reviews and the verifier pin exact commit SHAs, so merge lag doesn't change what they judge. Acceptance remains Astra's verdict, not the merge.
- No merging to main, ever, without the operator. No touching gen-1 runtime state, live topics, or the running gateway service.
- Loop hygiene: orchestrator wakes on agent notifications with a fallback timer; every wake updates BUILD-STATE.md; a stalled agent (no progress across two wakes) is nudged once, then reported to the operator.
