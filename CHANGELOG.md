# Changelog

## Unreleased

- **Breaking (semantics): completion is saturation-only for research topics.** A
  recurring item carrying `SEMANTIC-STATE.json` completes exclusively through the
  saturation gate — `saturation_limit` (default 3) consecutive semantically-valid
  deepening passes with an unchanged semantic signature, re-validated against the
  pinned completion lock. An agent-written `STOP DONE` is discarded (file unlinked,
  `ignored_stop_done` on the event) instead of completing or parking the item; the
  DONE instruction is gone from `ITERATION-PROMPT.md`/`CONTRACT-CORE.md`.
  `NEEDS-OPERATOR` keeps full escalation authority. Bounded one-shots and generic
  loops keep accept-on-DONE (no saturation signal exists for them).
- Reactivating a completed item (`refresh`, `restart` out of completed) now deletes
  its leftover terminal STOP file — previously the chassis's stale-STOP rule parked a
  re-opened topic on its first iteration back.
- **`on_completed_command`:** optional per-item argv run exactly once when an item
  lands completed (any completion path), with `RESEARCH_LOOP_TOPIC_DIR`/
  `RESEARCH_LOOP_ITEM_ID` exported; result ledgered as a `completion_hook` event;
  failure never un-completes the item. Settable via `add --on-completed`, `sync`,
  `configure_topic`, and `config apply`.
- **Stations:** cadence and agent assignment moved from queue items to worker
  profiles (`research-loops worker-agents`; the per-item `agents` verb now refuses
  with a deprecation error). Queue position is priority across stations: a
  faster station claims the higher-priority topic off a slower one at an iteration
  boundary (`reserved_for` wait if mid-iteration), up to 5 stations with a monotonic
  cadence invariant. `swap-active` performs manual reassignment landing the in-flight
  iteration first.

- **Breaking:** `chassis/`, `runners/`, `templates/`, and `schema/` moved under
  `research_loops/` (e.g. `chassis/run-topic.sh` is now
  `research_loops/chassis/run-topic.sh`), and `[tool.setuptools.package-data]` now
  ships them — a real (non-editable) `pip install` previously produced a
  `research-loops` command with none of these assets reachable at all; verified in a
  real venv/wheel build both before and after this fix.
- **Breaking:** `tools/new-topic`/`tools/approve-topic` are now `research-loops
  new-topic`/`research-loops approve-topic` subcommands (backed by
  `research_loops/topic_authoring.py`) instead of standalone scripts — a real
  `pip install` had no way to invoke them at all before this change, since only
  `research-loops` itself was ever exposed as a console script. `tools/` now contains
  only `install-systemd`.
- `--root`'s default now distinguishes a source tree (git clone or `pip install -e .`,
  detected via a sibling `pyproject.toml`) from a real wheel install: the former keeps
  today's behavior (the same one queue regardless of cwd); the latter now defaults to
  the current directory instead of silently resolving into `site-packages`.
- New `--lock-sha256`/`completion_lock`: `research-loops add` and `approve-topic` now
  pin a completion-inventory lock by default, so an agent can't reach `DONE` by adding,
  removing, or renaming an obligation/deliverable directly in `SEMANTIC-STATE.json` —
  see `docs/topic-authoring.md#the-completion-lock-why-topicmdauthoritymd-hashes-arent-enough-on-their-own`.
- `tools/install-systemd` installs the dashboard-refresh timer for the current clone
  and writes `STATUS.md` immediately instead of waiting for the timer's first tick.
- Declarative config (`research_loops/config.py`, `research-loops config`/`workers`
  subcommands): per-topic scheduling/agent-assignment/gap-policy settings and worker
  parallelism in one file — see `config/research-loops.example.toml`.

## 0.1.0 — initial release

- Queue engine (`research_loops/`): atomic JSON state, crash-safe claim/adopt/retry,
  correct failure classification (subscription quota vs. rate limit vs. outage vs.
  config error), stall detection independent of a topic's own progress claims,
  history-preserving manifest `sync`, Markdown status dashboard.
- Chassis (`chassis/`): `CONTRACT-CORE.md` universal invariants, runner-agnostic
  `run-topic.sh`, extracted `ITERATION-PROMPT.md`, `semantic-state.py` completion
  validator with `validate`/`signature`/`lock`/`rehash`/`check` subcommands.
- Agent Runner contract (`runners/`) with four adapters: `generic.sh` (any CLI via
  `RESEARCH_LOOP_RUNNER_CMD`), `claude.sh`, `codex.sh`, `hermes.sh`.
- Topic authoring tools (`tools/`): `new-topic` (deterministic brief-to-obligations
  decomposition) and `approve-topic` (hash-locking promotion), both with test coverage.
- One fully approved, runnable example topic
  (`examples/static-site-generator-choice/`), verified end-to-end before publication.
- Documentation: architecture, topic authoring, operations, governance, runner
  interface, contributing.
- 133 tests passing. No third-party dependencies. Apache-2.0.
