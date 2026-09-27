# Task 1c-repair-3 — close the recursive-grant budget bypass (structurally) and tighten C4 control selection

Read: `~/work/research-loops-public/private/reviews/gen2-1c-repair-2-astra-review-20260927.md` (BLOCK 1, BLOCK 2, and the Gate B row). Evidence: `/tmp/gen2-1c-repair2-review-6aht5a2s/`. Relevant files there: `recursive_grant_regression.py`, `control_audit.py`, `control_counterexamples.py`.

Everything else in 1c is closed and stays as is:
- A5-R's original fix and the C5 coverage;
- the two new budgets (Astra verified them with 13 policy probes);
- the runner's rejection of failed, skipped or unrun controls, and child attestation;
- the collected-end cleanup gap, which Astra ACCEPTED as an operator escalation.

## BLOCK 1 (L-6, RG-3): fix it at the chokepoint, not at another call site
The bug: `Supervisor._grant()` (`gen2/supervisor/supervisor.py` ~544) recursively grants a delegate's parent without checking whether that parent has an open incident. Each delegate advance then makes another failing parent claim, and the parent's incident is overwritten with a new deadline. Astra reproduced this for 4/4 parent kinds, with 12 extra calls each.

This is the **third** path found this way, after A5 and A5-R. So close the class, not the instance:
- **Gate at the single chokepoint.** Every router control call goes through one place (`_call()` or equivalent). That place must refuse to make the call when the *owning job* has an open incident, unless it is running under a budgeted `recover()`. The refusal must not raise or recreate the incident.
- **An open incident's `since` and deadline are write-once.** No path may renew them. Make that structural in the incident writer too.
- **Tests.** Add Astra's four-parent regression. Add a test that the chokepoint refuses for a stalled job whatever the caller: direct advance, parent settle, recursive grant, recovery without budget. Add bound mutants: one that removes the chokepoint gate, and one that lets the incident writer renew the deadline.
- **Check what legitimately still happens while stalled.** Local deadline enforcement, and explicit `recover()`, must still work (Astra's deadline and recovery controls).

## BLOCK 2 (C4): controls must exercise the affected guard's accepted path
- **Tighten the tracer's evidence rule.** `tools/gen2_mutation_controls.py` `evidence_lines()`/`choose()` currently credit any enclosing `if`/`while`. Require the control to execute the changed guard line itself (or the line the mutant changes), on its accepted path. Reaching the surrounding branch is not enough.
- **Fix Astra's three examples:** `1C-router-found-result-other-digest`, `1C-sup-cancelled-exit-unconfirmed`, `1C-sup-no-abandon-handshake`. Curate or split controls as needed.
- **Add Astra's three controls for "no-control" mutants:** `R1-content-hash-covers-itself` (split out or reorder the existing assertion), `1C-router-ended-delegate-counts-live`, `1C-router-evidence-not-recorded`.
- **Re-audit the whole inventory with the tightened rule.** Report the counts honestly. Don't describe inventory totals as N semantically verified controls unless each one is verified. Say what the rule establishes and what it doesn't.

## Claim wording (Gate B)
- The bounded-retry claim must be true after BLOCK 1.
- The paired-control claim must match BLOCK 2's actual guarantee.

## Constraints
- Branch gen2 only.
- Never touch `gateway/`, gen-1, running services or main.
- Commit with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never mask `make`'s exit status.
- Finish with the completion report as your final message. It covers what changed, the reproductions now handled, the mutant evidence, the re-audit counts, and the final unpiped `make gen2-check` result. Don't end your turn waiting on a background run.
