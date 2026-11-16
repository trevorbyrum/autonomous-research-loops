# Gen-2 standing brief constraints

Every coder, fixer and records brief cites this file with one line and restates none of it. Each item names the recorded failure it comes from (Gate S #15, change #2, 2026-11-16). Authority order: a later operator ruling, then BUILD-CHARTER, then this file. A brief may add constraints for its own task and may not relax these.

Roots are environment variables, never literal paths: `$GEN2_REPO` (the checkout), `$GEN2_EVIDENCE` (the evidence root, outside the repository), `$GEN2_HEAVY_LOCK` (the heavy-suite lock file).

## Never in the repository
1. **No operator-specific paths.** No home-directory paths of any user, no private-tree paths and no host-specific roots in any changed line; use the environment variables above. *Trace: nine public files under docs/gen2 and deploy/gen2 carried an operator path (S15 §1, verifier row).*
2. **No completion, progress or evidence files.** Evidence goes under `$GEN2_EVIDENCE`, never into the repository. *Trace: COMPLETION.md reached public gen2 on 2026-10-27.*
3. **No secrets, ever.** Never print, retain, log or copy a secret or a rendered environment. Renders use `--no-env-resolution`. *Trace: an equivalence render wrote the dedicated stack's secrets to world-readable `/tmp` files (2026-11-12).*
4. **No sudo from an agent.** Host steps run files from the operator set. *Trace: four sudo runs in T9 receipts, found by review on 2026-11-16.*

## Commits and records
5. **Stage explicit paths only.** Never `git add -A` or `commit -a`. *Trace: a coder was active on a shared tree when `commit -am` swept its files in.*
6. **The attribution trailer** the session's reminder gives ends every commit message and PR body.
7. **Debt entries** follow `tools/check_gen2_debt.py`: `### DEBT-<n> <title>` with `kind`, `status`, `owner`, `what`, `removal`, then `source` (obligation) or `found by` and `accepted by` (mitigation), and `closed by` when closed. The owner is a `task <id>` or `phase <id>` that `docs/gen2/phase-status.json` names. *Trace: the records brief omitted these rules and the verifier failed #189.*

## What "done" means
8. **Operational predicates.** Each acceptance item states its source, its aggregation, that absence is never "none", and one worked example from a retained artifact. *Trace: #180's "classify foreign, pre-prepare, corrupt" ran eight rounds and +263 lines against a +5 estimate; S12's oracles passed vacuously on authored `refs: []`.*
9. **Lifecycle invariants.** A stateful change states the positive completion state, its retry and terminal exceptions, and a transition table before any fixture is written. *Trace: family D, a confirmed physical end the Router never learns of, recurred across S10, S12 and S14.*
10. **Consumer claims.** A deletion or a signature change greps tests, INVARIANTS locators, `traceability.toml`, BOUNDARIES, DEBT-REGISTER and docs, and claims every consumer in the brief. A changed refusal code or file mode means grepping every test. *Trace: the verifier exited on a test the fixer had not run, on #181 and #185; R2's locator went stale after D2b's move.*
11. **Fixtures replay retained artifacts.** A fixture of an external interface replays a retained artifact, not an authored value. *Trace: fixtures manufacturing the fact under test, S7 family C, S12, S14 family K; the five production defects found natively all sat at manufactured seams.*
12. **Targeted checks by semantic impact.** When `db.connect`, DDL or a shared fixture changes, the brief requires the targeted checks for that impact (openers, no-DML, full-state, crash and restart, lock-wait, replay, supervisor) and not only the checks for the files touched. *Trace: file-following missed 382 failures.*

## Required brief sections
Component; owned and forbidden paths; reading set; acceptance contract (each item traced to an invariant, a ruling or a DEBT entry); risk tier and its test budget; size stop; checks; delivery; limits.

Briefs also carry the separation practices (BUILD-CHARTER): one component where possible, interface changes contract-first, and a reading set scoped to the component.
