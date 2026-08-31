# Changelog

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
