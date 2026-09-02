# State access: how agents read and write SEMANTIC-STATE.json

`SEMANTIC-STATE.json` is the topic's source of truth, but agents must not
read it whole or rewrite it whole. Two reasons, both measured on real
deployments:

- **Tokens.** The file accumulates terminal obligations' full prose
  (acceptance/counterevidence/search records) forever. Reading it whole
  drags tens of thousands of tokens of finished work into the iteration
  context, where the conversation's triangular re-read amplifies it by the
  session's turn count.
- **Safety.** Whole-file rewrites by ad-hoc scripts are a corruption
  vector: one malformed write bricks the topic, and a subtly wrong terminal
  record is only discovered at the DONE gate, iterations later.

## Read paths

```bash
semantic-state.py select <topic_dir>      # the work-selection view
semantic-state.py get <topic_dir> <id>    # one full record by id
```

`select` returns open (non-terminal) obligations in full, terminal ones as
`{id, disposition, confidence}` skeletons, pending evidence refs, open
contradictions in full, and deliverable statuses. That is everything work
selection needs. A revalidation pass that needs a terminal record fetches
exactly that record with `get`.

## Write paths (guarded, atomic)

```bash
semantic-state.py transition <topic_dir> <obligation_id> [--disposition ...] \
    [--confidence ...] [--gap-state ...] [--acceptance-summary ...] \
    [--counterevidence-summary ...] [--counterevidence-reviewed true|false] \
    [--add-evidence-ref REF]... [--adequate-search JSON] [--experiment JSON]
semantic-state.py pending <topic_dir> --add REF | --remove REF
semantic-state.py deliverable <topic_dir> <id> --status ... \
    [--acceptance-summary ...] [--add-acceptance-ref REF]...
semantic-state.py contradiction <topic_dir> --open ID | --resolve ID --resolution TEXT
```

The guarantees that make this the mandated path:

- **A terminal transition must be complete in one call.** The updated
  record is checked with `obligation_terminal_errors()` — the *same
  implementation* the DONE gate runs — and nothing is written if it fails.
  A terminal state the completion gate would later reject cannot land.
- **Identity is operator-owned.** `id`/`text`/`source_ref` are not writable
  here; scope changes go through the operator's `rehash`/`relock` path.
- **References must exist** at write time (evidence, pending, acceptance).
- **Writes are atomic** (tmp + rename); a crashed write never half-updates
  the file.

Deliverable required-heading checks stay at the DONE gate: they read the
artifact's content, which is legitimately still in flight mid-iteration.

## Design note

This CLI is deliberately an *interface* over the file, not a new format:
all engine consumers (validator, signature, lock, gap/refresh policies,
doctor, MCP server) keep reading the file directly. Once agents speak only
through the CLI, the on-disk representation can evolve (e.g., a hot/cold
split of terminal records) behind `_load()` without touching agents again.
