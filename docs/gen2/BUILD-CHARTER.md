# Gen-2 Build Charter

Operator-authorized 2026-09-25. Governs the background build loop until the operator amends it.

## Authorities (fixed)
- **Orchestrator — Fable (this session's loop).** Sequences phases, writes task briefs, dispatches coders and reviewers, maintains BUILD-STATE.md and REVIEW-LOG.md, reports to the operator. Never writes engine code, never merges to main, never overrides a review verdict. Scope questions and authority changes escalate to the operator.
- **Coder — Claude Opus (paseo `claude` provider; target model claude-opus-5-5, fallback claude-opus-5).** One coding agent at a time on this shared working tree, branch `gen2` only. Implements exactly its task brief; every brief names the flow-doc sections and BOUNDARIES.md entries it touches. Deviations from the brief are proposals in the completion report, not silent changes. Commits carry the standard attribution lines.
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

## Standing rules
- Build follows the adjudicated phase order (flow doc + Astra review §10): Phase 0 invariants/migration contract → 1 mechanical vertical slice (fake executors; crash/replay/cancel proven before model authority) → 2 one complete research workflow → 3 qualified automation/projections → 4 migration+canary. Phase transitions are operator-gates.
- Size rules (the user, 2026-09-29; replaces the earlier 10,000/12,000 total, which had been copied from the design review's *proposed* planning allocation without operator approval):
  - **Per-file limit: no hand-written file over 1,500 lines** (code, tests, tooling, SQL, config). It is enforced by `make gen2-check` over the gen-2 surface INVARIANTS B-3 lists (`gateway/` included since task 2b-repair; gen-1's `research_loops/` is not gen-2's and is outside it). Generated files (for example the mutation-control pairings and the generated catalog/env example) are exempt only by an explicit, reasoned allowlist entry.
  - **Total production code: 15,000 lines is a growth-review trigger.** When it is reached, the loop stops for a review with the user of what made it grow before building further. The total is reported at every task boundary. Tests, schemas, SQL, prompts and tooling are reported separately.
- Machine-checkable module-boundary graph in CI from the first commit; a boundary-graph violation fails the build.
- Jev is not a build dependency: everything must run and be testable with the decision layer disabled.
- No merging to main, ever, without the operator. No touching gen-1 runtime state, live topics, or the running gateway service.
- Loop hygiene: orchestrator wakes on agent notifications with a fallback timer; every wake updates BUILD-STATE.md; a stalled agent (no progress across two wakes) is nudged once, then reported to the operator.
