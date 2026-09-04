# Topic authoring

A topic is three files plus a handful of ledgers, all in one directory:

- **`AUTHORITY.md`** — operator-owned, human-readable ground truth. Your brief, your
  scope, your evidence-quality rules. This is what you actually wrote or approved.
- **`TOPIC.md`** — the machine-facing projection: a finite obligations list, required
  deliverables, dependencies, and the exit condition. References `AUTHORITY.md` by its
  SHA-256.
- **`SEMANTIC-STATE.json`** — the executable state. Fields meant to be immutable per
  obligation (`id`, `text`, `source_ref`) plus agent-writable fields (`disposition`,
  `confidence`, `evidence_refs`, ...). `research_loops/chassis/semantic-state.py validate` is the
  completion gate — see `research_loops/schema/semantic-state.schema.json` for the full shape. "Meant
  to be" is enforced, not just asked-nicely, only when a completion lock is pinned (see
  below) — `approve-topic` and `research-loops add` both do this by default.

## The fast path: `new-topic` + `approve-topic`

```bash
bin/research-loops new-topic my-topic --title "My Topic" --brief path/to/brief.md
# review/edit topics/my-topic/DRAFT-AUTHORITY.md and DRAFT-TOPIC.md
bin/research-loops approve-topic my-topic
```

`new-topic` doesn't call an LLM. It deterministically splits your brief on semicolon and
sentence boundaries into candidate obligations — the same decomposition approach used
throughout this project's own topic corpus. Write your brief as a list of distinct,
checkable points (separated by semicolons, or as separate sentences) and it decomposes
cleanly; one dense run-on paragraph becomes one big obligation, which is a sign to add
punctuation to your brief, not a bug in the tool.

Nothing is binding until `approve-topic` runs. That command recomputes both hashes from
whatever you actually left in the DRAFT files — edit them freely first. This is the one
moment scope is allowed to become fixed.

## Naming convention

Bare, descriptive slugs — no family/portfolio prefix, no phase numbers.
`static-site-generator-choice`, not `myproject-static-site-generator-choice` or
`phase2-static-site-generator-choice`. A prefix describing "which batch this was added
in" rather than "what this topic is about" is exactly the kind of naming debris this
convention exists to prevent: it accretes fast (every new topic copies the last one's
prefix by habit, whether or not it still means anything) and buys nothing the queue and
directory structure don't already give you. See `docs/agent-operations.md#naming-convention`
for the agent-facing version of this same rule.

## Changing scope safely after approval

`TOPIC.md` and `AUTHORITY.md` are operator-owned. A research agent must never rewrite
them. If *you* edit them later:

```bash
python3 research_loops/chassis/semantic-state.py rehash topics/my-topic
```

This is a deliberate, explicit action — "yes, I changed the scope on purpose" — never
something that happens automatically. Without it, the next `validate` call will report
a hash mismatch and refuse completion, by design: an unnoticed scope change is exactly
the failure this is meant to catch.

## The completion lock: why `TOPIC.md`/`AUTHORITY.md` hashes aren't enough on their own

`contract_sha256`/`authority_sha256` prove `TOPIC.md` and `AUTHORITY.md` weren't
rewritten. They prove nothing about `SEMANTIC-STATE.json`'s own `obligations`/
`deliverables` arrays — nothing stops an agent from deleting an inconvenient
`contradicted` obligation from that array, inventing a new one and marking it
`supported`, or editing a deliverable's `required_headings` to something already in its
own draft, all without touching either hashed file. `validate` catches malformed or
incomplete entries, but not a *plausible*, well-formed, silently altered inventory.

The completion lock closes that gap: `research_loops/chassis/semantic-state.py lock topics/my-topic`
hashes the exact `id`/`text`/`source_ref` of every obligation and `id`/`description`/
`path`/`required_headings` of every deliverable, and `validate --lock-sha256 <hash>`
refuses completion if that hash no longer matches — catching exactly the tampering above,
whether or not `TOPIC.md`/`AUTHORITY.md` changed. `approve-topic` computes this
lock and bakes `--lock-sha256` straight into the `research-loops add` command it prints;
`research-loops add --lock-sha256 ...` and a manifest's `completion_lock` field both
store it in the queue's own state (never the agent-writable topic directory), and
`research_loops/chassis/run-topic.sh` passes it into every `validate` call automatically from there.
Running a topic outside the queue (invoking `run-topic.sh` directly)? Export
`RESEARCH_LOOP_COMPLETION_LOCK` yourself, or you're only getting the structural checks,
not the pinned-inventory ones.

## What makes a good obligation

Checkable, not open-ended. "Research authentication options" isn't an obligation — it
never has a terminal state. "Compare session-cookie and JWT-based authentication for a
server-rendered app with under 10k daily users, on session-fixation risk and revocation
latency" is: it can end up supported, contradicted, unresolved after an honest search,
or deferred as a specific experiment. Every obligation ends in exactly one of those four
states — never left `open` and never smoothed over.

## Ongoing gap-filling: proposals, not silent scope creep

If a research agent hits real coverage it thinks should be in scope but isn't — a
genuine gap, not scope creep it's inventing — it appends a `PROPOSAL` row to
`DECISIONS-LOG.md` (see `CONTRACT-CORE.md`'s governance section) instead of just
covering it unofficially. Review pending proposals across your topics, and promote the
ones you actually want:

```bash
grep -l PROPOSAL topics/*/DECISIONS-LOG.md   # find pending proposals

research_loops/chassis/gap-policy.py promote topics/my-topic \
  --id NEW-07 --text "The proposed obligation text." --source-ref "DECISIONS-LOG.md#proposal-row"
```

`promote` does exactly what you'd otherwise do by hand — append the bullet to `TOPIC.md`,
append the matching entry to `SEMANTIC-STATE.json`, and rehash — as one auditable command
instead of three manual edits that can drift out of sync with each other.

**Auto gap policy.** A topic can instead be configured with `gap_policy = "auto"` (see
`docs/operations.md#declarative-config` and `docs/governance.md#the-operator-owns-scope`),
which lets the research agent call `research_loops/chassis/gap-policy.py promote --auto --limit N`
itself for a bounded number of gaps since your last review, tagged `AUTO-PROMOTED` in
`DECISIONS-LOG.md` so it's always distinguishable from a promotion you reviewed first.
Once that budget is used, further gaps fall back to `PROPOSAL` rows until you run:

```bash
research_loops/chassis/gap-policy.py review-reset topics/my-topic --note "reviewed the last 3, all legitimate"
```

Default is always `review` — `auto` is something you opt a specific topic into, not a
global behavior change.

## Dependencies vs. order

Only set `depends_on` (in the manifest entry you pass to `research-loops add`/`sync`)
when a topic's research is genuinely impossible without another topic's *completed*
output. For "I'd like this worked on first, all else equal," use queue position
instead — `research-loops move <id> <position>`. See `docs/architecture.md` for why
conflating the two is a real failure mode, not just a style preference. A real example
worth studying: a topic whose whole job is synthesizing everything else legitimately
depends on all of it; almost nothing else does.

## A worked example

`examples/static-site-generator-choice/` is a complete, approved, never-run topic. Read
its `AUTHORITY.md` and `TOPIC.md` side by side to see the brief-to-obligations mapping
in a real case, then queue it and run one iteration yourself (see the main
[README](../README.md#quickstart)).

## The QA round

A contract binds research for days; approving one on a misread brief wastes
all of it. Every draft therefore carries a `QA-RECORD.md`, and
`approve-topic` / the MCP `approve_and_queue` tool structurally refuse until
the operator has ruled.

Two modes, chosen at `new-topic --mode` (`draft_topic(mode=...)` over MCP):

- **broad** (the default — assumptions are addressed unless the operator
  says otherwise): the QA agent restates the intent, runs the traceability
  review (every intent element covered by an obligation; every obligation
  traceable to intent — the draft's formatting must never scope research
  below what was actually asked), surfaces the assumptions the draft
  silently encodes, and a **discovery pass** maps the topic space before
  scoping. Approval requires both an answered `## Operator confirmation`
  and an answered `## Scope decision`.
- **focused** (formerly `scoped`; the old name is still accepted): the
  operator knows exactly what they want. The stated frame
  is FIXED — QA clarifies within it (breadth, exclusions, what done looks
  like) and never questions premises. Approval requires an answered
  `## Operator confirmation` only.

Fixed premises live in AUTHORITY.md's `## Assumptions` section: the
**Operator-fixed** list is binding (research agents and discovery must
never revisit it); **Surfaced and answered** records QA/discovery findings
with the operator's ruling, so future rescopes can see what was decided
versus what was silently inherited.

### Discovery passes (broad mode)

`research-loops discover <topic-id>` (or the `start_discovery` MCP tool)
queues one bounded pass on the **intake lane** — a separate queue lane a
dedicated worker serves (`research-loops run --worker intake-1 --lanes
intake`), so discovery runs in parallel with the research fleet without
competing for it. The intake lane itself serializes: at most one discovery
pass runs at a time by default, however many drafts are waiting. Raise it
deliberately via `[lanes] intake_max_active` in research-loops.toml
(`config apply`). The pass writes `SCOPE-PROPOSAL.md` (traceability
findings, a topic-space map, a keep/add/reword/drop obligation set,
proposed exclusions) and appends its surfaced questions to `QA-RECORD.md`;
a pass that produces no proposal fails (exit 65) rather than counting.
