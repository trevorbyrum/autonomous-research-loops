# Task 2a-repair — close F1–F4 of the 2a review; make the authorized INVARIANTS locator updates

Read: `~/work/research-loops-public/private/reviews/gen2-2a-astra-review-20260929.md` in full — F1–F4 each have exact reproductions and a required repair; evidence under `/tmp/gen2-2a-astra-20260929/` (including Astra's independent chain script). All seven of your earlier choices were ruled (1–5 ACCEPT, 6 mixed: the checkpoint-closure fence is REJECTED as F2, the rest ACCEPT; 7 AUTHORIZED as locator-only updates). The operator-surface hand-off list is ruled complete. Don't reopen accepted items.

## Findings (follow each "Required repair" as written)
1. **F1 (HIGH) — a materially superseded brief still authorizes the S2/S3 hand-offs.** `_recorded_references` checks the historical confirming decision, not whether that brief still stands; the initial-draft check only tests queue status; scope and contract approval consume the old brief. Check the referenced brief's standing when writing drafts and again when consuming the scoping report and initial contract approval; a material replacement or closure must block advancement under the old brief.
2. **F2 (HIGH) — timestamps don't bind a checkpoint to the episode it was admitted to review.** Bind the checkpoint to its episode(s), or an immutable ordered review snapshot, at admission; validate closure against that binding. Test a later episode at an equal and an adjacent timestamp.
3. **F3 (MEDIUM) — method-design provenance joins two unrelated facts.** Retain and validate an attributable proposal/commit binding for the exact document and the proposing primary invocation, including the permitted kind — not the global artifact's first-stager column.
4. **F4 (MEDIUM) — "newest report" is inferred from wall time and per-report version.** Select the current report by durable commit order (the committed operation's topic state revision is available) or an explicit current-report reference.

## Also (authorized)
INVARIANTS locator-only corrections: G-4 (`open_brief`), G-12 (signal/open/close implementations and limits), C-12 (new workflow writes, adoption, link and report checks), G-13's stored-subject coverage (scoping reports, source proposals), and E-3 may locate `register_works`. Don't alter normative rule text; don't describe F1–F4 as repaired in locators until they are.

## Budget
Production is 9,060/10,000 and the remaining Phase 2 allocations exceed the headroom (an operator budget decision is pending). Keep this repair lean; report net lines.

## Constraints
Branch gen2 only. Never touch gen-1, the live gateway service, running services or main. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (per finding: what changed, reproduction now refused/handled, mutant evidence; the locator updates; net lines; final unpiped `make gen2-check`). Don't end your turn waiting on a background run.
