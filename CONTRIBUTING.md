# Contributing

Thanks for looking at this. A few things that make a change easy to accept:

## Running the tests

```bash
PYTHONPATH=. python3 -m unittest discover -s tests -p 'test_*.py'
```

No dependencies to install — the engine is pure standard library, deliberately. A
change that requires adding one should explain why the standard library genuinely
can't do it, not just that a library would be more convenient.

## What kind of changes fit where

- **`research_loops/`** — the queue engine (`queue.py`, `runner.py`, `dashboard.py`,
  the `new-topic`/`approve-topic` CLI subcommands). Changes here affect every topic and
  every runner; they should come with a test, and should not encode any assumption
  about which LLM CLI, storage backend, or provider is in use.
- **`research_loops/chassis/`** — the per-iteration contract. `CONTRACT-CORE.md` is
  meant to be read by a research agent every iteration, so keep it short and change it
  rarely; a topic's own `AUTHORITY.md` is where domain-specific rules belong instead.
- **`research_loops/runners/`** — adapters. See `research_loops/runners/README.md` for
  the interface. A new adapter is usually the easiest kind of contribution: copy
  `generic.sh`, adapt it to your CLI, and don't touch anything else.
- **`research_loops/topic_authoring.py`** — backs the `new-topic`/`approve-topic`
  subcommands. `split_brief()`'s obligation-decomposition is deliberately simple
  (semicolon/sentence splitting, no LLM call) — if you want a smarter version, propose
  it as an opt-in mode, not a replacement; the deterministic path is what makes review
  possible.
- **`tools/install-systemd`** — the only thing left under `tools/`; git-clone-deployment
  convenience, unrelated to topic authoring.

## Adding a runner adapter

1. Copy `research_loops/runners/generic.sh`.
2. Implement the interface in `research_loops/runners/README.md`: accept
   `(topic_dir, prompt_file)`, read `RESEARCH_LOOP_*` env vars as needed, exit 0 on
   success, never use exit codes 3/4/5/78 (chassis-reserved).
3. Add it to the table in `research_loops/runners/README.md`.
4. If practical, add a test under `tests/` exercising it against a fake/stubbed CLI
   rather than a real network call.

## Reporting a bad obligation decomposition

If `research-loops new-topic` splits a brief in a way that produces a nonsensical
obligation (a broken fragment, a merged pair of unrelated points), include the exact
brief text that produced it — `split_brief()` in `research_loops/topic_authoring.py` is
simple on purpose, and the fastest fix is usually rewording the brief with clearer
semicolon/sentence boundaries rather than making the splitter smarter and less
predictable.

## Code style

Match what's already there: `from __future__ import annotations`, type hints on public
functions, no framework-style abstraction for something that's used once. If you're
adding a comment, make sure it explains *why*, not what the code already says.
