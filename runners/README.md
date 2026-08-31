# Runner adapters

A runner is any executable that speaks this contract. The queue and chassis never know
or care which LLM CLI is actually behind it.

## Interface

**Invocation:** `<runner> <topic_dir> <prompt_file>`

**Environment provided by `run-topic.sh`:**

- `RESEARCH_LOOP_TOPIC_DIR` — same as argv[1], absolute path
- `RESEARCH_LOOP_USAGE_FILE` — path the runner may write usage JSON to (optional)
- `RESEARCH_LOOP_LOG` — path of the log file the chassis is already tee-ing stdout to
- `RESEARCH_LOOP_PROFILE` — opaque string a worker may set; the runner interprets it
  (or ignores it) however it wants — the chassis never inspects its value

**Output:** the transcript on stdout/stderr. Optionally, valid JSON written to
`RESEARCH_LOOP_USAGE_FILE`. All usage fields are optional; a missing field means
"unavailable," never zero (see `research_loops/dashboard.py`'s coverage reporting).

**Exit codes:** a runner owns `0` (success) and any other code it wants classified as a
transient failure by `research_loops/runner.py`'s failure-pattern matching. It must
**never** use `3`, `4`, `5`, or `78` — those are reserved by `chassis/run-topic.sh` for
STOP/PAUSED/stall/configuration-error respectively. Returning one of those by accident
will misclassify a real failure as one of those terminal states.

## Included adapters

| Adapter | Backs | Requires |
|---|---|---|
| `generic.sh` | anything | `RESEARCH_LOOP_RUNNER_CMD` set to a command that reads the prompt on stdin |
| `claude.sh` | Anthropic Claude Code CLI | `claude` on PATH, already authenticated |
| `codex.sh` | OpenAI Codex CLI | `codex` on PATH, already authenticated |
| `hermes.sh` | Hermes CLI | `hermes` on PATH, a configured profile |

Pick one with `RESEARCH_LOOP_RUNNER=<name>` (env var) or the second positional argument
to `run-topic.sh`; default is `generic`.

## Writing a new adapter

Copy `generic.sh` as a starting point. The only hard requirements: accept the two
positional args, exit 0 on success, never emit the four reserved exit codes, and don't
assume anything about what's already running — `run-topic.sh` invokes a fresh process
per iteration, so credentials/session setup has to work from a cold start.
