# Architecture

Three layers, deliberately unaware of each other's internals.

```
research_loops/  (the queue)         research_loops/chassis/            research_loops/runners/
  queue.py    -- atomic JSON state     CONTRACT-CORE.md -- invariants   claude.sh
  runner.py   -- claim/retry/classify  run-topic.sh     -- one iteration codex.sh
  dashboard.py-- STATUS.md rendering   semantic-state.py-- completion    hermes.sh
                                                            gate          generic.sh
```

All three live under `research_loops/` so they ship together in a real `pip install`,
not just a git clone (see `docs/operations.md#installing-on-path`) — but they remain
three independent layers at runtime, not one module: the queue calls
`chassis/run-topic.sh <topic-dir>` as a subprocess and only cares about
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
- **running → completed**: only through the **saturation gate**. Once
  `semantic-state.py validate` passes (coverage: every obligation terminal, every
  deliverable present), iterations become deepening passes; each pass that leaves the
  semantic signature unchanged extends a streak, any change resets it, and
  `saturation_limit` consecutive valid, unchanged passes (default 3) complete the
  topic — after the queue re-validates against the pinned completion lock. A research
  agent writing `STOP DONE` has no effect: the file is discarded, the discard is
  recorded on the event (`ignored_stop_done`), and the loop reschedules. Coverage is
  necessary but not sufficient; the agent can observe coverage, only the queue can
  observe saturation. (Bounded one-shot items and generic loops without a
  `SEMANTIC-STATE.json` keep their original completion behavior — they have no
  saturation signal.) When an item lands completed, its optional
  `on_completed_command` hook fires once (see below). Reactivating a completed item
  (`refresh`, `restart`) deletes its leftover terminal STOP file, so a re-opened topic
  doesn't get parked by its own previous completion.

## Why liveness ≠ completion

`progress-signature.sh` hashes only the *semantic* content of `SEMANTIC-STATE.json`:
obligation dispositions, confidence, gap state, contradiction status, deliverable
status. It deliberately excludes prose edits, finding counts, and anything else that
can churn without anything actually being resolved. If that signature is identical
across `stall_limit` consecutive successful-looking runs, the queue escalates to
`needs_attention` — this is a liveness judgment ("nothing is actually changing"), and
it can *never* produce completion on its own. Completion is a separate, positive
check with the *opposite* sign: the same unchanged signature that counts toward a stall
while the validator fails counts toward saturation while it passes. The two thresholds
are deliberately ordered (`saturation_limit` 3 < `stall_limit` 6) so a genuinely
finished topic saturates before the stall guard could park it. A loop that never
stalls but never reaches coverage just keeps running; a loop that stalls gets flagged
for a human, not silently marked finished.

## Stations and the cascade

Workers are **stations**: cadence and agent assignment are properties of the worker,
never of the queue item. Each station has a profile —
`research-loops worker-agents <worker> --main codex --model ... --secondary ...
--flags ... --interval <seconds>` — that the runner reads fresh at every iteration
spawn, exporting `RESEARCH_LOOP_RUNNER`, the runner's model/flags variables, and the
delegate command. Interval `0` means continuous; a positive interval paces that
station's iterations. Station numbering carries a monotonic invariant (station N+1 may
never be faster than station N, max 5 stations).

Queue position is priority *across* stations. At claim time a faster station takes the
highest-priority eligible topic even if a slower station holds it: if the slower
station is between iterations the transfer is immediate; if it's mid-iteration the
fast station reserves the topic (`reserved_for`) and idles until the boundary rather
than interrupting real work. Transfers never inherit a pause. `swap-active` exists for
manual reassignment; it lands the current iteration first (`desired=releasing`) and
refuses to steal an item another worker still holds.

## The completion hook

`on_completed_command` (per item; settable at `add --on-completed`, via `sync`,
`configure_topic`, or `config apply`) is an argv the worker runs exactly once when the
item's outcome lands `completed` — any completion path, including the saturation gate
— with `RESEARCH_LOOP_TOPIC_DIR` and `RESEARCH_LOOP_ITEM_ID` in the environment. It
exists so derived stores (a knowledge graph, a vector index) are fed by one mechanical
step at completion instead of an LLM writing mid-loop. The hook is derivative by
definition: failure is recorded as a `completion_hook` event (`ok: false`, output
tail) and never un-completes the item. Commands must be idempotent and finish inside
the 30-minute timeout.

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

**Portability note:** the fingerprint above reads `/proc/<pid>/stat`'s start-time ticks
plus the boot ID, so crash-adoption specifically (surviving a worker restart without
double-launching or losing track of an in-flight iteration) is Linux-only, and
`deploy/systemd/` is the only supplied deployment model. On another OS the queue itself
still runs — claim/backoff/retry/stall-detection are all pure Python with no `/proc`
dependency — but a worker restart while an iteration is in flight will not be able to
distinguish "still running" from "gone," so treat that combination (non-Linux + a worker
process that can restart mid-iteration) as unsupported rather than assuming the same
safety guarantee holds.

## Dependencies vs. scheduling preference

`depends_on` in a topic's queue definition is a hard claim-eligibility gate: a topic
with an unmet dependency is never claimed by any worker, full stop. Use it only when a
topic's own research is genuinely impossible without another topic's completed output
(a synthesis-of-everything topic depending on everything else, for instance). Use plain
queue *order* — the position in your manifest — for "I'd like this one worked on
first, all else equal." Conflating the two either creates false blocking (a topic
that could clearly proceed independently sits idle) or, worse, hides a real dependency
behind what looks like an arbitrary ordering choice. See `docs/topic-authoring.md`.
