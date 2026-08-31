# Architecture

Three layers, deliberately unaware of each other's internals.

```
research_loops/  (the queue)         chassis/  (the contract)        runners/  (the CLI)
  queue.py    -- atomic JSON state     CONTRACT-CORE.md -- invariants   claude.sh
  runner.py   -- claim/retry/classify  run-topic.sh     -- one iteration codex.sh
  dashboard.py-- STATUS.md rendering   semantic-state.py-- completion    hermes.sh
                                                            gate          generic.sh
```

The queue calls `chassis/run-topic.sh <topic-dir>` as a subprocess and only cares about
its exit code. `run-topic.sh` calls a runner adapter as a subprocess and only cares
about its exit code and stdout. A runner adapter calls whatever LLM CLI it wraps. Each
boundary is a real process boundary — you can replace any one layer without touching
the others.

## The queue's state machine

Every topic in `state/queue.json` is one of: `queued`, `running`, `backoff`,
`needs_attention`, `paused`, `completed`. The transitions that matter:

- **queued → running**: a worker claims it (`queue.py:claim_next`). Sticky ownership —
  one worker owns a topic through its whole cadence until it's terminal; a second
  worker is purely additive, never steals work.
- **running → backoff**: the iteration failed in a way worth retrying (rate limit,
  transient outage). `runner.py:classify_failure` distinguishes failure kinds and
  schedules the retry delay accordingly — a subscription-quota window gets a long fixed
  wait, not the exponential backoff that would burn through it in minutes.
- **running → needs_attention**: the failure isn't retryable (bad config, a STOP file
  with `NEEDS-OPERATOR`, or a crash-adopted orphan process whose real exit status can't
  be observed). This state fails closed: it never resolves itself, an operator has to
  look and explicitly `resume`/`restart`.
- **running → completed**: the topic wrote `STOP` starting `DONE` *and*
  `semantic-state.py validate` actually passed. If a topic writes `DONE` but the
  validator rejects it, the queue treats that as `needs_attention` (configuration
  error), not completion — an agent asserting "I'm done" is not the same as being done.

## Why liveness ≠ completion

`progress-signature.sh` hashes only the *semantic* content of `SEMANTIC-STATE.json`:
obligation dispositions, confidence, gap state, contradiction status, deliverable
status. It deliberately excludes prose edits, finding counts, and anything else that
can churn without anything actually being resolved. If that signature is identical
across `stall_limit` consecutive successful-looking runs, the queue escalates to
`needs_attention` — this is a liveness judgment ("nothing is actually changing"), and
it can *never* produce `DONE` on its own. Completion is a separate, positive check:
every obligation has a real terminal disposition, every deliverable exists. A loop that
never stalls but also never satisfies that check just keeps running; a loop that stalls
gets flagged for a human, not silently marked finished.

## `sync`, not remove-and-re-add

`research_loops.queue.sync()` is the only sanctioned way to bulk-reshape the queue from
a manifest file. It updates existing items in place, appends new ones, optionally
prunes ones no longer in the manifest, and reorders to match — but it never touches
`attempts`, timestamps, or error history for anything still present. Removing and
re-adding an item to change its command would silently erase all of that. If you find
yourself tempted to script "remove everything and add it back from a manifest," use
`sync` instead.

## Crash safety

If a worker process itself dies mid-iteration and restarts, it never blindly relaunches
a topic that might still be running under the old worker's child process. It checks the
recorded PID against a fingerprint captured at launch (boot ID + `/proc` start-time
ticks, immune to PID reuse across reboots): if that process is gone, the topic is
requeued (safe — topics checkpoint their own ledgers every iteration); if it's still
alive, the new worker adopts supervision of it rather than starting a second copy. An
adopted process that exits on its own goes to `needs_attention` rather than being
guessed at — a reparented orphan's real exit code isn't observable, and treating that
as success would be exactly the wrong kind of guess.

## Dependencies vs. scheduling preference

`depends_on` in a topic's queue definition is a hard claim-eligibility gate: a topic
with an unmet dependency is never claimed by any worker, full stop. Use it only when a
topic's own research is genuinely impossible without another topic's completed output
(a synthesis-of-everything topic depending on everything else, for instance). Use plain
queue *order* — the position in your manifest — for "I'd like this one worked on
first, all else equal." Conflating the two either creates false blocking (a topic
that could clearly proceed independently sits idle) or, worse, hides a real dependency
behind what looks like an arbitrary ordering choice. See `docs/topic-authoring.md`.
