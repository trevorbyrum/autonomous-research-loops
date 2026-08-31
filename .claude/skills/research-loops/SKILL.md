---
name: research-loops
description: Use when adding, querying, or managing topics in this repo's research-loops queue (new-topic, approve-topic, add, move, depends-on, gap-policy, dashboard, etc.) — points to the authoritative, runner-agnostic instructions.
---

The real instructions live in [`docs/agent-operations.md`](../../../docs/agent-operations.md)
— read that file, not this one. It's written to work for any agent/runner pointed at
this chassis (Claude Code, Codex, Hermes, or your own), not just Claude Code, so the
canonical copy stays there rather than duplicated here.

Short version of what's in it: how to scaffold and approve a new topic
(`research-loops new-topic` / `approve-topic`), the naming convention, how to add scope
to an already-queued or already-running topic, `--depends-on` vs. `move` for ordering,
and a running list of what's still ad hoc pending later phases (graceful pause, worker
reassignment, `doctor`).
