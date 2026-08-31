# Operations

## Running one worker

```bash
bin/research-loops run                 # forever, polling
bin/research-loops run --once           # one claim-and-iterate cycle, then exit
```

## Running multiple workers

Each worker holds its own lock and only ever supervises the topic it claimed — a
second worker is purely additive, never contends for the same topic:

```bash
bin/research-loops run --worker worker-1 &
bin/research-loops run --worker worker-2 &
```

New-topic intake can be limited per worker (e.g. "this worker finishes what it's
already on, never starts anything new"):

```bash
bin/research-loops worker-policy worker-2 --claim-limit 0
```

## Queue control

```bash
bin/research-loops list --json                       # full state
bin/research-loops pause [item-id] [--reason "..."]   # whole queue, or one topic
bin/research-loops resume [item-id]
bin/research-loops restart <item-id>                  # clear a needs_attention/backoff state
bin/research-loops move <item-id> <position>          # reorder (see architecture.md)
bin/research-loops sync --manifest manifest.json      # the only sanctioned bulk-reshape
```

## Reshaping the queue from a manifest

Hand-editing `state/queue.json` is never the right move — it bypasses lock discipline
and the definition-field validation `sync` does up front. Write a JSON file with an
`items` array (each entry shaped like the arguments to `add`) and run:

```bash
bin/research-loops sync --manifest manifest.json           # update in place, add new
bin/research-loops sync --manifest manifest.json --prune   # also remove absent, non-running items
```

## Dashboard

```bash
bin/research-loops dashboard --output STATUS.md
```

Regenerate this on a cadence (cron, systemd timer — see `deploy/systemd/`) if you want a
standing status file rather than running it by hand. It's a generated file: manual edits
are overwritten on the next run.

## systemd deployment

`deploy/systemd/` has templates for a worker service and a dashboard-refresh timer.
Copy them to `~/.config/systemd/user/`, edit the `WorkingDirectory`/`ExecStart` paths
for your clone location, then:

```bash
systemctl --user daemon-reload
systemctl --user enable --now research-loops-worker@worker-1.service
systemctl --user enable --now research-loops-dashboard.timer
```

## Troubleshooting `needs_attention`

Read `last_error_kind` and `last_error` first (`bin/research-loops list --json`), then
the topic's own `logs/` directory for the actual iteration transcript:

- **`configuration`** — usually a genuine STOP with `NEEDS-OPERATOR`, a hash mismatch
  (see `docs/topic-authoring.md`'s `rehash` note), or the runner/command itself
  couldn't be found. Fix the underlying issue, then `restart`.
- **A stall escalation** (`last_error` mentions "stall guard") — the topic kept
  reporting success but its semantic state stopped actually changing. Read its
  `SEMANTIC-STATE.json` and recent `PROGRESS.md` entries before restarting; if the
  remaining obligations genuinely need something (a missing tool, an ambiguous scope
  question), fix that first or the next attempt will likely stall the same way.
- **An adopted-orphan escalation** (mentions a worker restart) — a process survived a
  worker restart, was supervised until it exited, and its exit status couldn't be
  observed. Check the topic's ledgers directly to see whether real progress happened;
  `restart` is safe either way since topics checkpoint their own state every iteration.
