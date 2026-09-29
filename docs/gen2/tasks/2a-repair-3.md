# Task 2a-repair-3 — F1-R continued: make "the contract's brief basis was superseded" a durable fact (structural fix; final 2a round)

Read: `~/work/research-loops-public/private/reviews/gen2-2a-repair-2-astra-review-20260929.md` in full. Evidence: `/tmp/gen2-2a-repair-2-astra-20260929/` — `tree/astra_amendment_edges.py` (26-case matrix), `tree/astra_cross_brief_regression.py` (four failing router-only tests), and the structured results.

## Why a structural fix this time
This is the third round of the same defect family (F1 → F1-R → F1-R continued). Each repair reconstructed "is the old brief still a valid basis?" from brief history, filtered by brief ID, and each missed a sequence: this time, confirming a *different* replacement brief (brief-2) and then archiving it makes the obsolete brief-1 usable again — six failing cases across both timings, owner/deadline successors, and multi-version replacements. Reconstructing from history keeps missing cases. Close the class instead (same lesson as the supervisor's retry chokepoint in 1c):

## Required repair
- **Record supersession as a durable, monotonic fact at the moment it happens.** When a brief (any ID) is confirmed on a topic that already has an approved contract based on a different or materially different brief, write a durable record that the contract's brief basis is superseded — in the same transaction as the confirmation. The record never reverts because a brief is later archived.
- **The only way to clear it is incorporation:** an amendment naming the current confirmed basis through the existing framing/version and reframe-approval rules (Astra's positive control). Archive-only (archiving the basis brief with no replacement ever confirmed) and compatible-lineage (owner/deadline-only successors) paths keep working, as accepted previously.
- **Distinguish a later replacement from a brief already archived before the contract's own basis was confirmed** (the review names this case).
- **Check the durable fact** at amendment proposal and at approval (consumption); drop the history reconstruction it replaces rather than layering both.
- Tests: Astra's four router-only regressions and the 26-case matrix, plus both timing negatives for directly archived originals and archived compatible successors, with whole-store refusal checks; a replacement's later versions; the accepted archive-only, compatible-lineage and reframe paths as controls. Bind mutants: removing the record write, allowing archival to revert it, and skipping the check at each consumption point.

## Also (authorized by the review)
Locator-only INVARIANTS updates at C-12 (~line 92) and G-4 (~line 237) to describe the actual rule once it holds.

## Sequencing note
Task 2r (per-file refactor, which will split `gen2/store/schema.sql`) runs *after* this task. If you add DDL, add it to `schema.sql` as usual; 2r will split afterward.

## Constraints
Branch gen2 only; lean. Never touch gen-1, the live gateway, running services or main. Commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (the structure of the new fact, all reproductions refused, accepted paths working, mutant evidence, net lines, final unpiped `make gen2-check`). Don't end your turn waiting on a background run.
