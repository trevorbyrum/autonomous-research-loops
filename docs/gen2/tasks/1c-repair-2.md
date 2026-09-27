# Task 1c-repair-2: close A5-R, C4, C5 and the remaining claim wording (narrow)

Read: `~/work/research-loops-public/private/reviews/gen2-1c-repair-astra-review-20260927.md`. It covers A5-R, C4 and C5 and the Gate B row, with evidence under `/tmp/gen2-1c-rereview-bg824437/` (`delegate_budget_regression.py`, `delegate_replacement.py`). Everything else in 1c is closed; don't touch it. That includes A1–A4, A6–A11, C1–C3, the C2 investigation, the mutation-runtime structure, and the B1 corrections Astra accepted.

## A5-R: parent cleanup bypasses a stalled delegate's outage budget
`_settle_delegates()` (`gen2/supervisor/supervisor.py` ~530) calls `_grant`/`_status`/`request_cancel` before `advance()`'s stalled-job guard. After the delegate's budget is exhausted, every parent advance makes another failing call. `_call()` then recreates the incident with a new `since` and deadline, which pushes the deadline back. Astra reproduced this for all 4 parent kinds × 2 failure points: 8/8, with 12 extra failing calls each.

**Repair:**
- Route parent-driven delegate work through the same stall/recovery gate as direct advancement.
- Keep local deadline observation running while stalled.
- Keep the original incident and its original deadline.
- Require budgeted recovery before any retry of its control calls.

**Tests:**
- Add all-parent-kind negatives for partial outage and restart, beside a reconnect-and-recover control.
- Bind a mutant that restores the bypass.
- Assert that the incident deadline is unchanged.

## C4: mutation selection omits paired positive controls
`tools/gen2_mutations.py` ~3185 selects exactly `m.killers`. Fix it one of two ways:
- explicitly select each mutant's paired controls, kept separate from killers since controls must pass under the mutant; or
- move the accepted cases into the killer methods.

Keep per-test child attestation. **Audit the whole inventory**, not only Astra's two examples, and report how many mutants gained controls. Narrow the docstring to what the mechanism actually does. Report the runtime impact.

## C5: "replaced lease" is reachable for a delegate
Keep the justified research-pass skip. Add delegate replacement under a replaceable parent scope (discovery, verification or checkpoint parent). Assert that no executor starts. Include the unchanged-authority recovery control. No production change is expected.

## Claim wording (Gate B)
- The universal bounded-retry claim must hold after A5-R. If any retry path is still unbounded, say so.
- The per-mutant positive-control claim must match C4's result.
- Describe the 7-minute mutation figure as a recorded run on an idle host, not a dependable duration. Observed runs so far: 434 s, 737 s and 1,219 s, depending on host load.

## Constraints
- Branch gen2 only. Do not touch `gateway/`, gen-1, running services or main.
- Commit message trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never mask `make`'s exit status. Keep full logs.
- Finish with the completion report as your final message; don't end your turn waiting on a background run. The report must cover: what changed, the reproduction now handled, mutant evidence, the C4 audit counts, and the final unpiped `make gen2-check` result.
