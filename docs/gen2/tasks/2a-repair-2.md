# Task 2a-repair-2 — F1-R: narrow the post-approval brief-standing exemption (single finding; final 2a round)

Read: `~/work/research-loops-public/private/reviews/gen2-2a-repair-astra-review-20260929.md` — F1-R, the two judgment-call rulings, and the limit rulings. Evidence: `/tmp/gen2-2a-repair-astra-20260929/` (`tree/astra_amendment_basis.py` and its results). F2–F4 are closed; the automatic return-to-scoping is ACCEPTED; both stated limits are ACCEPTED. Don't touch them.

## The defect
At `gen2/router/amendments.py` ~480, finding any approved contract disables the brief-standing refusal altogether — for amendment proposals and for the approval-time recheck (`service.py` ~1195). Astra reproduced, through the router with genuine decisions: after contract r2 under brief v1, a materially changed brief v2 is confirmed; an amendment r3 still naming v1 is proposed and approved (and, in the second timing, approved after v2's confirmation), classified `compatible`, while r2-pinned research keeps running and commits. 1d's brief-impact branch doesn't catch it (contract-admitted work has null brief pins; the contract-to-contract comparison sees the same decision record).

## Required repair (per the review)
- Keep the accepted path: archiving the intake brief after contract approval and continuing to amend that contract.
- A **confirmed material replacement** must prevent a new amendment proposal or approval from silently retaining the obsolete brief basis. Check at proposal and at consumption.
- Route the updated decision record through the existing framing/version and reframe-approval rules (Astra's positive control: an amendment naming current v2 with a new framing version is accepted via `reframe_approval`, impact `reframed`, and old work then refuses `amendment_pending`).
- Tests: replacement before proposal; replacement between proposal and approval; archival-then-amend still accepted; lineage-only (owner/deadline) replacement still accepted; the reframe positive control. Bind mutants for the narrowed exemption.

## Constraints
Branch gen2 only; lean (production 9,091/10,000). Never touch gen-1, the live gateway, running services or main. Commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (what changed, both reproductions refused, the accepted paths still working, mutant evidence, net lines, final unpiped `make gen2-check`). Don't end your turn waiting on a background run.
