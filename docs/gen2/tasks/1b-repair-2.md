# Task 1b-repair-2: close A5-R (small, likely final 1b round)

Read `~/work/research-loops-public/private/reviews/gen2-1b-repair-astra-review-20260927.md` §A5-R. Everything else in 1b is closed: A1–A4, C1–C3, both probe adjustments, the new hold rule, and `invocation_id` unchecked for this phase. Don't touch it.

## The defect
`record_transition` calls `boundary.staged(...)` for every `result_ready` request (`gen2/router/service.py` ~402). That happens *before* the lookup of an already-recorded transition and its full fact comparison (~418). Two consequences:
- An identical historical `result_ready` replay returns `refused/payload_missing` once the staged bytes are gone. The case: the result is committed, the router restarts, and the clock is past both lease and deadline.
- A changed, unstaged digest on a recorded key returns `payload_missing` instead of `transition_conflict`.

## Required repair (per the review)
- Resolve an already-recorded transition and compare its full facts *before* requiring staged bytes.
- Keep staging and hash validation for a genuinely new `result_ready`.
- Keep the in-transaction replay recheck for races.
- Keep byte reads outside the transaction (C-3/C-8).
- Add Astra's two cases as isolated regressions. Both need a durable store, a restart in a fresh process, expiry, and assertions that the store is unchanged:
  - (1) identical replay with the bytes unavailable → `replayed`, with state, timestamps, history and audit unchanged;
  - (2) recorded key with a changed, unstaged digest → `transition_conflict`.

  Astra's reference test is at `/tmp/gen2-1b-repair-astra-uQFm6P/result_ready_regression.py`, if it's still present.
- Bind a mutant that restores staging-before-replay, and show it is killed.
- Make the router README's transition-replay claim accurate.

## Constraints
- Branch gen2 only. No 1c work: spool, retention and reconciliation stay out.
- Never touch `gateway/`, gen-1, running services or main.
- Commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never mask `make`'s exit status.
- Finish with the completion report as your final message: what changed, both cases now passing, mutant evidence, and the final unpiped `make gen2-check` result. Don't end your turn waiting on a background run.
