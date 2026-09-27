# Task 1b-repair — close A1–A5 and C1–C3 (router corrections, no new scope)

Read first: `~/work/research-loops-public/private/reviews/gen2-1b-astra-review-20260927.md`. Findings A1–A5 and C1–C3 each have exact reproductions and required repairs; follow them as written. Also read the "Rulings on the ten Gate A proposals" and "Boundary and scope rulings" sections. Everything the review accepted stays as it is: proposals 1–7 and 9–10, the scope split, and Gate B. Reviewer probe scripts are under `/tmp/gen2-1b-astra-5Vl1HF/`; use them to reproduce if they are still present.

## Findings
- **A1 (HIGH): lock waits invalidate the time checks in claim, launch and observation.** Sample the clock *after* acquiring the transaction, for each new time-sensitive action. An operation that is already recorded keeps replay-before-current-authority semantics. Add synchronized lock-wait tests, varying the lease and the deadline so that they expire during the wait.
- **A2 (HIGH): delivery receipts lose information, and conflicting documents replay.**
  - Persist the immutable full canonical receipt and bind its projected columns to it.
  - Compare the complete semantic content on replay.
  - Preserve the observed, partial and unknown count states and the optional references.
  - Add restart/read-back tests and isolated conflict negatives.
- **A3 (HIGH): a qualified screening spec can name a different contract.** Before authoritative screening is accepted, bind the spec's full protocol context to the committing invocation and the selected contract: topic, contract revision and hash, and eligibility protocol version. Add schema-valid negatives, one per field.
- **A4 (MEDIUM): artifact metadata checks miss nested references and have no in-transaction recheck.** Apply one binding rule to every embedded artifact reference, including raw responses. Inside the fenced transaction, recheck metadata equality when a previously absent artifact has appeared. Keep byte reads and hashing outside the transaction (C-3/C-8).
- **A5 (MEDIUM): transition replay works only while the target is still current.** Recognize a previously recorded transition and compare its immutable facts before attempting a new one. An identical historical replay succeeds with no change to state, timestamps, history or audit. Altered facts conflict.
- **C1: exact time and interleaving coverage.**
  - Add fixed-clock controls at E−1 ns, E and E+1 ns. Astra's `>=`→`>` mutant must now be killed.
  - Add the A1 lock-wait cases.
  - Add an expired-lease observation case on an otherwise-running invocation, so that invocation state can't hide lease enforcement.
- **C2: the payload-digest negative is not isolated.**
  - Rewrite it with a schema-valid wrong-hash input (Astra's `next_queue_state` example, with the size corrected). Keep the separate size and missing-byte cases.
  - Repair the duplicate-key subcase so that it is otherwise schema-valid.
- **C3: provider-screening controls.** Replace the shared spec builder with a complete, correctly pinned, schema-valid DecisionSpec. Derive neither the expected verdict nor the required pin from the checker under test. Rerun each negative so that only its named defect is present, and add A3's and A4's comparisons.

## Also
- Correct the router README claims that A1–A5 showed to be overstated.
- Expand the rule-9 README with the ordinary re-export and alias chains Astra listed. The rule is architectural lint, not runtime isolation, and the README must say so.
- Keep the in-process trust limit explicit: bearer capabilities, and trusted operator/exporter callers only, until 1e.

## Constraints
- Branch gen2 only.
- Stay within the scope above. Registries, amendment impact and brief versioning are 1d; spool and reconciliation are 1c.
- Never touch `gateway/`, gen-1, running services or main.
- Small commits, each with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never mask `make`'s exit status.
- Finish with the completion report as your final message, and don't end your turn waiting on a background run. For each finding, report: what changed, the reproduction now refused or handled, and the mutation evidence. End with the final unpiped `make gen2-check` result.
