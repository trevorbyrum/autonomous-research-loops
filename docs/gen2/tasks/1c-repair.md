# Task 1c-repair: close the 1c findings (lifecycle, recovery, capacity, persistence, artifact validation)

Read first: `~/work/research-loops-public/private/reviews/gen2-1c-astra-review-20260927.md`. Each finding gives an exact reproduction, a required repair and an evidence file under `/tmp/gen2-1c-review-wc6mawb1/`. Astra's `regressions.py` there contains seven focused regressions that all fail today. Use them as a starting point where they're still present.

These are already settled and stay as they are:
- the accepted parts: import boundary, the 90-case lifecycle and 50-case crash matrices, and the write-once store predicates;
- the rulings on the coder's six questions (Q1, Q3 and Q4 accepted with conditions, Q2 and Q5 as ruled, Q6 **rejected**, which is finding A6).

## Findings to close, in the review's priority order
Follow each "Repair" paragraph as written. Each finding needs:
- all-kind tests where the review asks for them;
- whole-store read-back;
- an isolated negative plus a positive control;
- a bound mutant.

1. **A1 (HIGH).** Recovery and failed-start retries start work without a *current* launch-admission check (pause, expired/released/replaced lease, cancellation). Re-check before every actual start. Assert that **no executor starts**; a later rejection of its commit doesn't count.
2. **A3 (HIGH).** A parent's lease is released while its owned delegate is still running, which the parent's OS-session check can't see. Reconcile or terminate owned delegate jobs, and confirm their disposition, before shared capacity is released. This applies on success, failure, cancellation and restart.
3. **A6 (HIGH).** A recorded hash bypasses topic authorization, in both the staged and the already-recorded reference paths, including the transaction recheck. Physical dedup can stay if topic authorization is represented separately. Add tests: a same-topic recorded positive, a foreign-only recorded negative, and concurrent-insertion controls.
4. **A9 (HIGH).** Launcher loss during a router outage defeats the local deadline. Local deadline and group handling must cover uncertain and vanished launchers without a router response. Assert that the processes are dead *before* reconnecting.
5. **A2 (HIGH).** Cancellation after an uncertain spawn can't reconcile: the supervisor omits `failure_class`, and the router requires it. Fix the shared contract **without** inventing a failure class for a cancellation. Test end to end with the real supervisor request for the live, already-exited and never-started cases. Per the Q5 ruling, record factual confirmation that the group is empty; don't fabricate a signal.
6. **A4 (HIGH).** Failed durable writes escape without an incident: the execution record, termination and reconciliation records, and the journal. Handle persistence failure across the whole operation. Preserve the collected bytes and a recoverable phase, bound the retries, and raise an owned, deadlined control incident. If the incident store itself can't be written, raise an explicit out-of-band control failure.
7. **A5 (HIGH).** Successful status reads refill a failing write's retry budget. Budget the pending operation, or the outage episode, until *that* operation makes progress. Keep exhaustion across recovery, and test partial availability.
8. **A7 (HIGH).** An episode hold can be cleared without reconciliation, through generic operator hold clearance. Enforce the reverse rule in both the store and the router: clearing an `outcome_unknown` episode hold requires the matching reconciliation, whatever API is used. Keep ordinary operator hold clearance working.
9. **A8 (MEDIUM).** Conflicting lifecycle facts are reported as an identical replay: process identity, failure class and `unknown_cause` are left out of the comparison. Keep and compare the complete normalized factual request, before requiring any staged bytes, and recheck it under the transaction.
10. **A10 (MEDIUM).** Scratch validation doesn't detect changes to a file after it's opened. Validate a stable read: check the descriptor's metadata and link count before and after reading, and refuse detected changes. Add deterministic same-inode modification and link-count race tests, with unchanged-file controls. Keep the current descriptor-relative behavior, which Astra confirmed is correct.
11. **A11 (MEDIUM).** Exhausted spawn and commit retries end with no owned, deadlined incident. When a budget exhausts, persist an incident or hold that records the budget kind, the last refusal and the result reference.

## Test-gate findings
- **C1.** Make the preflight attest the *executing* child that supplies a kill: verify the target bytes and bind that evidence to the test and mutant. Refuse when the attestation is missing or wrong. Enforce a safe import root: `children.py`'s `setdefault(cwd)` currently lets a caller import unmutated code. Keep the source lint as a narrow lint and document it accurately.
- **C2.** The unidentified intermittent failure. Always keep full verbose output and subprocess stderr. Identify the old failure from the retained artifacts if you can; otherwise stress the crash and timing suites until it recurs, find the cause, and add a deterministic regression. Counting green runs does not close this. If you can't reproduce it after serious effort, report exactly what you tried and what the logging will now capture.
- **C3.** Register mutants that remove `read_scratch`'s `NAME.match` check and `_topic_fd`'s `O_NOFOLLOW` flag, bound to their existing tests.
- **B1.** Narrow the supervisor, router and mutation-runner README claims so they state only what is actually guaranteed. That includes the declared-digest wording ("checked data that cannot establish success") and the PID enumerate-to-signal interval in the identity limits. Document that the spool's aggregate quota is per instance, and that single ownership is a deployment restriction.

## Lower priority, after all findings above are closed: mutation runtime
The mutation step now takes roughly 26–35 minutes. Apply the review's recommendation:
- select declared killers plus paired positive controls for each mutant;
- deduplicate equivalent clean baselines by loading mode;
- run the full unmutated suite once;
- bound concurrency;
- stream results as they finish.

**It must not weaken the evidence.** Every required killer must still fail, real-child attestation stays, and timeouts must not be shrunk. Report before and after timings. If this risks the findings, leave it for a follow-up and say so.

## Constraints
- Branch gen2 only. Keep 1d/1e scope out: scheduling and retry policy, reservations, authentication.
- Never touch `gateway/`, gen-1, running services or main.
- Small commits, each with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never mask `make`'s exit status. Keep full output.
- Finish with the completion report as your final message; don't end your turn waiting on a background run. The report gives, for each finding: what changed, the reproduction now handled, and mutation evidence. Then add the C2 investigation outcome, the runtime result, and the final unpiped `make gen2-check` result.
