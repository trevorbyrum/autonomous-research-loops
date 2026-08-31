# research-loops

A small, durable engine for running autonomous research topics to genuine completion —
not a fixed iteration count, not a token budget, an actual executable check that every
question you asked has a real answer (or an honest "unresolved, here's why").

You bring an LLM CLI you already have access to and a short brief describing what you
want researched. This engine handles the rest: queueing, crash-safe retry, liveness
detection, and a completion gate that a research agent cannot talk its way past.

**What this is not:** a RAG stack, a search engine, or an agent framework. It doesn't
ship a vector database or a knowledge graph, and it doesn't need one — a topic's local
markdown ledgers are always its evidence of record. Bring your own retrieval if you want
richer infrastructure; the default path needs nothing but a runner CLI and Python 3.12+.

## The idea in one paragraph

A **topic** is a finite, operator-approved list of obligations ("what must this
research establish") plus a small set of required deliverables. A **runner** (Claude
Code, Codex, Hermes, or anything else you point it at) does one bounded research
iteration at a time: read the topic, pick the highest-value open obligation, verify
evidence, update the topic's own state file. A **queue** schedules iterations across
however many topics and workers you're running, survives crashes, and classifies
failures correctly (a subscription quota window is not the same problem as a broken
config). None of these three pieces know about the other two's internals — swap any of
them independently.

## Quickstart

```bash
git clone <this-repo> research-loops && cd research-loops
python3 -m venv .venv && . .venv/bin/activate   # optional, no dependencies to install

# 1. Describe what you want researched
cat > /tmp/brief.md <<'EOF'
Research how to choose a static site generator for a personal blog under 50 posts.
Cover build speed and DX for Hugo, Eleventy, Astro, and Zola; hosting friction on
GitHub Pages, Netlify, and Cloudflare Pages; and migration cost if I later add a
little client-side interactivity. Exclude full SPA frameworks like Next.js.
EOF

# 2. Turn it into a draft topic (deterministic, no LLM call yet)
tools/new-topic my-first-topic --title "My First Topic" --brief /tmp/brief.md

# 3. Read topics/my-first-topic/DRAFT-*.md, edit anything you want, then:
tools/approve-topic my-first-topic

# 4. Queue it and run one bounded iteration with a real runner
bin/research-loops add --id my-first-topic --title "My First Topic" \
  --cwd "$(pwd)/topics/my-first-topic" --stop-file STOP \
  --max-attempts 8 --repeat-seconds 900 -- \
  "$(pwd)/chassis/run-topic.sh" "$(pwd)/topics/my-first-topic" claude
bin/research-loops run --once

# 5. Check status any time
bin/research-loops dashboard --output STATUS.md && cat STATUS.md
```

Already have a runnable example? See `examples/static-site-generator-choice/` — a
fully approved, never-run topic you can queue and run immediately without writing a
brief first.

## Layout

| Path | What |
|---|---|
| `research_loops/` | the queue engine: atomic state, crash-safe claim/retry, failure classification, dashboard |
| `chassis/` | the per-iteration contract every topic runs under (`CONTRACT-CORE.md`, `run-topic.sh`, the completion validator) |
| `runners/` | adapters translating the Agent Runner contract to a specific CLI (Claude Code, Codex, Hermes, or your own) |
| `tools/` | `new-topic` and `approve-topic` — brief in, reviewed hash-locked topic out |
| `templates/topic/` | the three-file shape (`TOPIC.md`, `AUTHORITY.md`, `SEMANTIC-STATE.json`) if you'd rather write one by hand |
| `schema/` | JSON Schema for `SEMANTIC-STATE.json` |
| `examples/` | one real, runnable, fully-approved topic |
| `docs/` | architecture, topic authoring, and operations detail |

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — the three layers, the state machine, why liveness ≠ completion
- [`docs/topic-authoring.md`](docs/topic-authoring.md) — the full topic contract, dependencies, and how to change scope safely
- [`runners/README.md`](runners/README.md) — the Agent Runner interface and how to add a new adapter
- [`docs/operations.md`](docs/operations.md) — running multiple workers, systemd deployment, troubleshooting
- [`docs/governance.md`](docs/governance.md) — why the operator owns scope, and why quota failure is never evidence of absence

## License

Apache License 2.0 — see [`LICENSE`](LICENSE). Research output your topics produce is
yours; this license covers the engine, not what it finds.
