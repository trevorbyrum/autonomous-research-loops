# Operations

## Installing on PATH

Everything under `research_loops/` — the queue engine, `chassis/`, `runners/`,
`templates/`, `schema/` — ships in a real `pip install`, not just a git clone:

```bash
pip install -e .        # from a clone: research-loops on PATH, same source tree either way
pip install .            # a real (non-editable) install
python -m build --wheel  # or just build the wheel yourself
```

The two install modes differ in exactly one place: `--root`'s default. A git clone or
`pip install -e .` resolves it to the actual clone (`research-loops` on PATH still hits
the one queue in that clone, regardless of your current directory — the same behavior
`bin/research-loops` has always given you). A real `pip install` has no such clone to
fall back to, so it defaults to your current directory instead, the same convention
`git`/`npm` use — run it from the project directory you want it to operate on, or pass
`--root` explicitly. See `research_loops/__main__.py`'s `_default_root()` if you want the
exact detection logic.

`bin/research-loops` (used throughout this doc and the README) is still the right choice
for a git clone you don't want on PATH — it always passes `--root` explicitly and needs
no install step at all.

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

## Station profiles (worker-agents)

Cadence and agent assignment belong to the worker (the *station*), not to queue items.
Configure each station once:

```bash
bin/research-loops worker-agents worker-1 \
  --main codex --model gpt-5.6-terra \
  --secondary 'codex exec --model gpt-5.6-luna ...' \
  --flags '--sandbox danger-full-access -c approval_policy=never ...' \
  --interval 0          # 0 = continuous; seconds otherwise
bin/research-loops worker-agents worker-2 --interval 1800   # partial updates fine
```

The runner re-reads the profile at every iteration spawn, so changes take effect at
the next boundary with no restart. Station N+1 may never have a shorter interval than
station N (max 5 stations). Queue position is priority across stations — a faster
station takes the higher-priority topic off a slower one at an iteration boundary
(immediately if the slower station is idle between iterations, else it reserves the
topic and waits for the boundary). Use `swap-active <worker> <item>` for manual
reassignment; it lands the in-flight iteration first and refuses to steal from
another worker. The old per-item `agents` verb is deprecated and refuses to run.

## Declarative config

`bin/research-loops` primitives (`add`, `sync`, `run --worker`) are enough on their own;
`config/research-loops.example.toml` is a convenience layer on top for the settings you
tend to want to see and change together in one file rather than as scattered flags:
how many parallel workers run, how long between a topic's iterations, which runner
adapter leads a topic and which one it may delegate legwork to, and whether a topic may
self-promote a discovered research gap or must always route it through operator review.
It never replaces `add`/`sync` — those still own each item's title/cwd/command.

```bash
cp config/research-loops.example.toml research-loops.toml   # then edit it

bin/research-loops workers start --config research-loops.toml   # spawn `workers` run processes
bin/research-loops workers status                               # which are still alive
bin/research-loops workers stop                                 # terminate them

bin/research-loops config show  --config research-loops.toml <topic-id>   # resolved settings
bin/research-loops config apply --config research-loops.toml              # push them to the queue
```

`config apply` only touches topic ids explicitly listed under `[topics.*]` in the file —
it never reconfigures a queue item just because it exists. Fields it can set
(`repeat_seconds`, `max_attempts`, `stall_limit`, `agent_main`, `agent_secondary`,
`gap_policy`, `gap_auto_limit`, `internal_citations`, `topic_refresh`,
`topic_refresh_mode`) all take effect on the item's *next* iteration only; none of them
touch an iteration already in flight, so `config apply` is always safe to run against a
running queue.

`agent_main`/`agent_secondary`, `gap_policy`/`gap_auto_limit`, and `internal_citations`
can also be set per-item directly with `add --agent-main ... --gap-policy auto
--gap-auto-limit 3 --internal-citations` without a config file at all — the config is
purely a convenience for managing many topics' settings in one reviewable place. See
`docs/governance.md#the-operator-owns-scope` for what `auto` gap policy actually does
and why its default is `review`, and `docs/citations.md` for `internal_citations`.

### `topic_refresh`: keeping a completed topic current

By default (`topic_refresh = "off"`), a completed topic never runs again — the only way
to re-check it is `bin/research-loops refresh <item-id>`, run by hand whenever you want.
Set `topic_refresh = "weekly"` or `"monthly"` (per-topic, or in `[defaults]`) to have it
automatically requeued that often once it completes, to check for anything new.

`topic_refresh_mode` controls what actually gets reopened when a refresh fires (default
`"continue"`):

- `"light"` — appends exactly one new obligation asking the agent to check for new
  information since the last completion. Cheapest; nothing existing is touched.
- `"continue"` — resets every `supported` obligation back to `open` (these are the
  claims that could plausibly have gone stale); `contradicted`/`unresolved`/`deferred`
  obligations are left alone. Falls back to `light`'s single-obligation append if the
  topic has no `supported` obligations. This is the default because it's the closest
  match to "the topic just keeps going" rather than "add one narrow check."
- `"full"` — the same reset as `continue`, applied to every obligation regardless of
  disposition. A genuine do-over of the whole contract; most expensive.

`bin/research-loops refresh <item-id> [--mode light|continue|full]` triggers one refresh
immediately, on any completed item, regardless of its `topic_refresh` setting — this is
the manual escape hatch for `topic_refresh = "off"` topics, or for forcing an
out-of-schedule check on a scheduled one. It refuses on anything but a completed item.

The mechanism is entirely obligation-based, not a special runtime mode: `refresh-policy.py`
reopens/appends real obligations in `SEMANTIC-STATE.json` before the item is ever
requeued, so the agent discovers the new work exactly the way it discovers any other
open obligation. See `research_loops/chassis/refresh-policy.py`'s module docstring for
the exact mechanics of each mode.

## The completion hook (`on_completed_command`)

To feed a derived store (knowledge graph, vector index, anything) when a topic
finishes, give the item a hook:

```bash
bin/research-loops add ... --on-completed '["/home/you/bin/my-corpus-ingest"]'
# or later, per topic, via config apply:
#   [topics.my-topic]
#   on_completed_command = ["/home/you/bin/my-corpus-ingest"]
```

The worker runs it exactly once when the item lands `completed` (any path, including
the saturation gate), with `RESEARCH_LOOP_TOPIC_DIR`/`RESEARCH_LOOP_ITEM_ID` set,
30-minute timeout. Failure is ledgered as a `completion_hook` event and never
un-completes the item — make the command idempotent and re-run it by hand after
fixing whatever broke. Keep credentials in the hook's own config outside the repo.

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

## systemd deployment (Linux)

```bash
tools/install-systemd
```

Installs the dashboard-refresh timer for this exact clone (rewriting the
`deploy/systemd/*` templates' example path to wherever you actually cloned it),
enables it, and writes `STATUS.md` immediately rather than waiting for the timer's
first tick — so the root of your clone has a live status file as soon as you're
installed, the same way it's set up for a long-running portfolio. It never enables a
worker; starting real research iterations (and consuming real quota) stays a separate,
deliberate step, which the script prints at the end:

```bash
cp deploy/systemd/research-loops-worker@.service ~/.config/systemd/user/
sed -i "s#%h/research-loops#$(pwd)#g" ~/.config/systemd/user/research-loops-worker@.service
systemctl --user daemon-reload
systemctl --user enable --now research-loops-worker@worker-1.service
```

This is Linux/systemd-specific — see `docs/architecture.md`'s portability note for what
that means for crash recovery on other platforms. On a non-systemd platform, generate
`STATUS.md` on whatever schedule you have available (cron, a launchd agent, ...); the
underlying command is the same `bin/research-loops dashboard --output STATUS.md` shown
above.

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
- **`transient` / `outage` / `rate_limit`** — an external condition (a gateway down, a
  provider blip, a rate window) exhausted the retry budget. You usually don't need to
  do anything: the worker auto-resumes these parks after a 30-minute cooldown (each
  resume is an `auto_resume` event in the ledger). If you want one to STAY down,
  `pause` it — an explicit pause always wins over auto-resume.

Two things auto-resume never touches: `configuration`/`auth` (they won't heal on their
own) and stall escalations (liveness is a judgment call). Those wait for you.

## Changing an approved topic's scope

Operator scope edits (adding an obligation outside the gap-policy path, retiring one,
renaming a deliverable) change the completion inventory, and the pinned
`completion_lock` will then reject every future completion with "approved completion
inventory lock mismatch" — permanently, by design, until you re-pin it. The sanctioned
path after you've made and reviewed the edit:

```bash
bin/research-loops relock <item-id>
```

This recomputes the lock from the topic's current `SEMANTIC-STATE.json` and records
the previous lock in its output. `sync` deliberately refuses `completion_lock` changes
so a manifest edit can never re-pin what DONE means silently; `relock` is the explicit
per-item operator action that may.
