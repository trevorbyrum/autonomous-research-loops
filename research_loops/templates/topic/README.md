# Topic template

Most people should use `research-loops new-topic` + `research-loops approve-topic`
instead of copying this directory by hand — see
[`docs/topic-authoring.md`](../../../docs/topic-authoring.md). This exists for the case
where you'd rather write a topic's contract yourself, or want to see the exact shape
those commands produce.

- **`TOPIC.md.example`**, **`AUTHORITY.md.example`** — commented reference versions.
  Copy, rename (drop `.example`), and fill in.
- **`SOURCE-LEDGER.md`, `FINDINGS-LOG.md`, `DECISIONS-LOG.md`, `NEEDS-SOURCE.md`,
  `PROGRESS.md`, `SYNTHESIS.md`** — empty ledger stubs a research agent writes into.
  Copy these as-is into a new topic directory.

There's no `SEMANTIC-STATE.json.example` here on purpose: it has to be generated after
`TOPIC.md`/`AUTHORITY.md` exist, since it hash-links to their exact content. Once you've
written both by hand, initialize it and lock the hashes with:

```bash
python3 research_loops/chassis/semantic-state.py rehash path/to/your-topic
```

(That command updates the hash fields on an existing `SEMANTIC-STATE.json` — for a
brand-new hand-written topic, start from `research_loops/schema/semantic-state.schema.json`'s
shape, set the obligation/deliverable lists yourself, put placeholder hashes in, then run
`rehash` once to make them real.)
