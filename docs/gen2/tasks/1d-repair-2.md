# Task 1d-repair-2: obligation removal/replacement joins impact classification; unmounted-restoration recovery (narrow, likely final 1d round)

Read: `~/work/research-loops-public/private/reviews/gen2-1d-repair-astra-review-20260928.md` in full — findings 1 and 2, the rulings on the three classification choices, and the required-closure section. Evidence: `/tmp/gen2-1d-repair-astra-review-20260928/` (`reviewer_probes.py`). Everything else in 1d is closed: the framing-content and stale-revival repairs work, findings 2/3/4/6 of the first review are closed, and the seven earlier rulings stand. Don't reopen them.

## Finding 1 (HIGH): obligation removal/replacement gets blanket `compatible`
The classifier compares obligation definitions only for IDs present in both revisions, and the framing projection omits coverage cells. Astra's two probes, both through the real proposal/approval APIs:
- **Removal:** rev 3 removes obligation `O-2` and marks its cell `deliberately_out` → `compatible`; the scoped observation and claim stay `valid`; running work completes; its result commits.
- **Replacement:** the same substantive change that is `protocol_changed` under a kept ID becomes `compatible` when the question is re-issued as `O-new` with an updated cell reference; the old cost claim then promotes to `accepted_support` without adoption.

**Required repair (per the review):** removed and replaced obligations, and scope-removing coverage-cell changes, must participate in impact classification. At Phase 1's revision-wide scope, **conservatively fencing affected revisions is sufficient** — item-level reconciliation is a later design option, not required now. Follow the review's exact closure list: the two probes must classify as protocol/framing-affected (not compatible), fence the affected work, leave the scoped observation/claim non-valid for promotion without adoption, with isolated negatives, bound mutants, and genuinely compatible additions (G-5-style, inside an existing facet) still passing as controls. Check the rulings section for how Astra settled the three classification choices and implement what it ruled, not what the docstring said.

## Finding 2 (MEDIUM): unmounted restoration never records recovery
The unmounted startup branch installs the active bundle's resolver but skips the activation/replay path, so capability history stays `failing` forever on that path. **Repair:** restoring the usable persisted active bundle records recovery once, keeping the failure history. Tests: invalid mount → omitted-mount restoration → repeated omitted-mount restarts, with unchanged pin/budget assertions, and a mutant that suppresses recovery only on this path. No new bundle version required.

## Constraints
Branch gen2 only. Never touch `gateway/`, gen-1, running services or main. Small commits with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never mask `make`'s exit status. Finish with the completion report as your final message (per finding: what changed, Astra's probes now refused/fenced, mutant evidence, final unpiped `make gen2-check` result). Don't end your turn waiting on a background run.
