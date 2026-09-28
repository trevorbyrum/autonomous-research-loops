# Task 1c-repair-4: serialize per-job advancement; add the abandonment control

Read: `~/work/research-loops-public/private/reviews/gen2-1c-repair-3-astra-review-20260928.md` (BLOCK 1, BLOCK 2, Gate B row). Evidence: `/tmp/gen2-1c-repair3-review-qzeapn_8/`. Everything else in 1c is closed:
- the chokepoint gate (Astra found no call bypassing `_call()`);
- the sequential-bypass fixes;
- the tightened control rule;
- all earlier findings.

## BLOCK 1 (L-6, RG-3): overlapping advances erase an incident and refill the budget
**The defect.** `Supervisor._call()` reads the job's saved journal, checks it, then calls the backend. On failure, `_spend()`/`_save()` writes back the caller's *earlier* journal snapshot, overwriting the whole durable journal. When advance A has read its snapshot and advance B then exhausts the budget and opens an incident, A's later save deletes the incident and resets the counter.

Astra reproduced this for 4 kinds × {one shared instance, two instances sharing the jobs directory}. It fails 8/8. The result is 12 calls instead of 6, and the deadline moves. A temporary lock around whole advances fixes it.

**Required fix.** Serialize all mutation of one job's state. It must hold across processes, since two supervisor instances can share the jobs directory:
- Take a **per-job exclusive lock**, for example `fcntl` on the job's journal or a lock file in the job directory, around each complete `advance()` and `recover()` for that job, and around any other path that reads, then writes, that job's journal (including a parent acting on a delegate's journal).
- **Journal writes must not clobber newer state.** Do the read-modify-write under the lock. Consider a journal revision number, and reject or re-read on mismatch, as belt-and-braces.
- **Lock-order discipline for parent↔delegate.** Pick one order, such as parent before delegate, so that parent settle and delegate grant can't deadlock. Test that both interleavings complete.
- **Waiting on a lock must not consume any retry budget**, and must be bounded. A stale lock left by a crashed process must not wedge the job; `fcntl` locks release on process death, so prefer them.
- **Tests:**
  - add Astra's overlapping-advance regression for all four parent kinds, for both the shared-instance and the shared-directory variants;
  - add a parent/delegate concurrent interleaving test (no deadlock, correct result);
  - add a crashed-lock-holder test (the lock is released, and the next advance proceeds);
  - bind mutants that remove the lock and that save a stale snapshot.

## BLOCK 2 (C4): `no-abandon-handshake` has a passing control
Astra demonstrated a relevant accepted-path control for it. Add it and pair it, and correct the "no control possible" reason. Re-check the other 5 unpaired mutants against the same standard.

## Claim wording (Gate B)
State the incident-preservation and bounded-retry claims as true under the new serialization. Name the lock's scope and limits: per job; cross-process on one host; not across hosts.

## Constraints
- Branch gen2 only.
- Never touch `gateway/`, gen-1, running services or main.
- Commit with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never mask `make`'s exit status.
- Finish with the completion report as your final message: what changed, reproductions handled, mutant evidence, and the final unpiped `make gen2-check` result. Don't end your turn waiting on a background run.
