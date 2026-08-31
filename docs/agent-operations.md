# Agent operations

For an agent with zero prior context on this system. Not a tutorial — a reference:
exact commands, exact flags, the mistakes that actually happen. If you're a human,
`docs/topic-authoring.md`/`docs/operations.md` explain the *why*; this page is the
*what to type*. Runner-agnostic on purpose — nothing here assumes Claude Code
specifically, since this same doc applies whether you're Claude, Codex, Hermes, or
anything else pointed at this chassis.

Every command below is `research-loops <verb> ...` (or `bin/research-loops` /
`PYTHONPATH=. python3 -m research_loops` from a git clone — see
`docs/operations.md#installing-on-path` for when each form applies). All output is JSON
on stdout unless noted.

## Adding a new topic

Three steps, always in this order. Do not hand-write `TOPIC.md`/`AUTHORITY.md`/
`SEMANTIC-STATE.json` yourself — the scaffolding tool produces the exact shape the
completion validator expects, including hashes you cannot compute correctly by hand.

```bash
# 1. Scaffold from a brief (deterministic, no LLM call — just semicolon/sentence splitting)
research-loops new-topic <topic-id> --title "Human-Readable Title" --brief path/to/brief.md

# 2. Review/edit topics/<topic-id>/DRAFT-AUTHORITY.md and DRAFT-TOPIC.md by hand if needed

# 3. Promote — this is the ONLY moment scope becomes binding
research-loops approve-topic <topic-id>
```

`approve-topic`'s JSON output includes a `suggested_command` field — a complete,
ready-to-run `research-loops add ...` command with `--lock-sha256` already filled in.
**Copy that command exactly.** Do not reconstruct it by hand, and do not omit
`--lock-sha256` — without it, `DONE` is only checked structurally, not against the
approved obligation/deliverable inventory (see `docs/topic-authoring.md#the-completion-lock`).

Common mistakes:
- Skipping `approve-topic` and trying to `add` the `DRAFT-*.md` files directly — they
  aren't real until promoted; `TOPIC.md`/`AUTHORITY.md`/`SEMANTIC-STATE.json` won't
  exist yet.
- Editing `SEMANTIC-STATE.json`'s hashes by hand after editing `TOPIC.md`/`AUTHORITY.md`
  post-approval — always run `research_loops/chassis/semantic-state.py rehash <dir>`
  instead (see `docs/topic-authoring.md#changing-scope-safely-after-approval`).
- Choosing a topic id with a family/portfolio prefix (`myproject-foo`, `phase3-bar`).
  Don't. See "Naming convention" below.

## Naming convention

**Bare, descriptive slugs. No family or portfolio prefix, no phase numbers.**
`static-site-generator-choice`, `authentication-approach`, `vendor-comparison` — not
`myproject-static-site-generator-choice` or `phase2-authentication-approach`. A prefix
that describes "which batch this was added in" rather than "what this topic is about"
is exactly the naming debris this convention exists to prevent — it accretes fast (every
subsequent topic copies the last one's prefix by habit) and buys nothing once you have
more than a handful of topics, since the queue and directory structure already group
them. `research-loops new-topic` doesn't currently reject a prefixed id outright, but
don't add one — it's a one-way door once other topics start `depends_on`-referencing it.

## Adding to an already-queued or already-running topic's scope

Two different needs, two different tools — pick the one that matches:

- **You found a genuine gap while researching, want it added properly**: append a
  `PROPOSAL` row to that topic's `DECISIONS-LOG.md` (see
  `chassis/CONTRACT-CORE.md`'s governance section), then either an operator promotes it
  by hand, or — if this topic's `gap_policy` is `auto` (check `research-loops config show
  --config <file> <topic-id>` or the item's `gap_policy` field via `list --json`) — call
  `research_loops/chassis/gap-policy.py promote <topic_dir> --id <NEW-ID> --text "..." --source-ref "..." --auto --limit <gap_auto_limit>`
  yourself. It refuses once the budget is used; fall back to the `PROPOSAL` row if it does.
- **An operator is amending scope directly** (not a self-discovered gap): the same
  `gap-policy.py promote` command works without `--auto` for this — it's the one
  sanctioned way to add an obligation to `TOPIC.md`/`SEMANTIC-STATE.json` and keep the
  hashes consistent, regardless of whether the topic is queued or actively running.
  Editing `SEMANTIC-STATE.json` while an agent is mid-iteration writing to the same
  file is a real race, so a manual (non-`--auto`) `promote` refuses by default if
  `logs/` has a file modified in the last 60 seconds — a filesystem-only best-effort
  signal, since `gap-policy.py` has no queue awareness. `research-loops pause <id>`
  first (graceful by default — the iteration finishes naturally, no lost work) is the
  safe fix; `--force` bypasses the check for the rare case you're certain it's fine.
  Amending a queued-but-not-running topic never hits this check at all.

## Dependencies vs. scheduling order

`--depends-on` (on `add`) is for **genuine content dependency only** — this topic's
research is impossible without another topic's *completed* output. It is never for "I'd
like this worked on sooner, all else equal" — use `research-loops move <id> <position>`
for that instead. See `docs/topic-authoring.md#dependencies-vs-order` for why conflating
the two is a real failure mode, not a style preference.

```bash
research-loops add --id <id> --title "..." --cwd <dir> --stop-file STOP \
  --lock-sha256 <hash> --depends-on other-id-1,other-id-2 -- <command...>
```

A dependency may reference an id that doesn't exist in the queue yet — it only has to
exist by the time this item is actually claimed. If it never gets added, the item stays
uncalimed and `claim_next()` raises a clear error identifying the missing id; it does not
fail silently.

## Portfolio health audit

```bash
research-loops doctor [--topics-root DIR]
```

Non-mutating, one report: structural validity per topic, which items are missing a
completion lock, dependency-integrity problems (a `depends_on` referencing a
nonexistent id, or a cycle), orphaned topic directories (a dir under `--topics-root`
that no queue item's `cwd` points at — default `<root>/topics`), and per-topic plus
portfolio-wide cited-source counts. Run this before assuming a portfolio is in good
shape, not just when something already looks wrong.

## Pausing

```bash
research-loops pause [item-id] [--reason "..."]   # graceful (default): finish the
                                                   # current iteration, then stop --
                                                   # never kills an in-flight child
research-loops pause [item-id] --now              # immediate: SIGTERM an in-flight
                                                   # iteration right away instead
```

A non-running (queued/backoff) item pauses immediately either way — there's nothing
in flight to protect. `--now` is for when you genuinely need the process gone right
away; the default is almost always what you want, since it never discards in-progress
work or risks a half-written ledger from a mid-write kill.

## Swapping an item's agents

```bash
research-loops agents <item-id> --main hermes --secondary codex   # set both
research-loops agents <item-id> --main hermes                     # only main, leave secondary
research-loops agents <item-id> --secondary ""                    # clear secondary
```

Thin wrapper over `configure_topic()` — same "next iteration only, never touches
in-flight" guarantee `config apply`/`add --agent-main` already have (see
`docs/operations.md#declarative-config`). Swapping an item's agents while it's
actively running changes what launches *next*; the current iteration keeps running
under whichever agent it already started with.

## Moving a worker to a different topic

```bash
research-loops swap-active <worker> <target-item-id>
```

If `<worker>` currently owns a running item, that iteration finishes naturally (never
killed) and is released back to the normal unclaimed pool — not paused, still
schedulable for any worker later, it just loses this worker's sticky claim.
`<target-item-id>` is pre-claimed for `<worker>` immediately, so its very next
`claim_next()` picks it up first. Refuses outright (no partial effect) if the target
is already claimed by a *different* worker, or isn't currently in a claimable state
(paused, completed, needs_attention, or still waiting out a backoff timer). If the
worker owns nothing running, this just claims the target immediately — no release
step needed.
