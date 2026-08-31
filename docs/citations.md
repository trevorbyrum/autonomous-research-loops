# Citation format

Every claim an obligation cites as evidence must resolve to a real, typed citation
block in that topic's `SOURCE-LEDGER.md` — not just a real file (already enforced by
`reference_exists()`), but a real, checkable record of *where the claim actually came
from*. This closes the gap between "the file exists" and "the file's content is an
actual citation, not just prose asserting something."

This only applies to topics with `schema_version >= 2` (see "Compatibility" below) —
`new-topic` stamps new topics with `schema_version: 2` automatically.

## The three citation types

A block starts at a heading matching exactly `## [SRC-NNN] <type>` and runs until the
next `## ` heading or end of file. Inside it, only lines matching `- key: value` are
read as fields; anything else (prose, blank lines) is ignored — a block is a strict
key/value record, not free text you can pad with narrative.

### `external` — a claim sourced from outside this topic entirely

```markdown
## [SRC-001] external
- url: https://developer.mozilla.org/en-US/docs/Web/HTML
- title: HTML: HyperText Markup Language
- retrieved: 2026-08-29
```

Required: `url` (must start `http://` or `https://`), `title`, `retrieved` (`YYYY-MM-DD`).

### `local` — a claim grounded in this topic's own ledgers

For something you measured or found yourself and logged elsewhere in this same topic
directory (a benchmark you ran, a finding you recorded in `FINDINGS-LOG.md`):

```markdown
## [SRC-003] local
- path: FINDINGS-LOG.md:L120-L134
```

Required: `path`, using the exact same `file:Lstart-Lend` syntax `evidence_refs` already
use.

### `internal` — this exact source was already cited in another topic

Points at a citation already recorded elsewhere in the portfolio, instead of
re-researching or re-typing a source you've already vetted once:

```markdown
## [SRC-002] internal
- topic: other-topic-id
- ref: SRC-007
```

Required: `topic` (another topic's id), `ref` (an `SRC-NNN` id in *that* topic's own
`SOURCE-LEDGER.md`). The target block must be `external` or `local` — never another
`internal` block, so a citation can never become a chain of pointers you have to follow
more than one hop to actually verify.

**`internal` citations are disabled by default and must be explicitly enabled**, per
topic or portfolio-wide, via `internal_citations` in the declarative config (see
`docs/operations.md#declarative-config`) — same `[defaults]` + per-`[topics.<id>]`
pattern as `gap_policy`. A well-formed `internal` block in a topic that hasn't enabled
this is rejected exactly like a malformed one, not silently accepted.

## Citing a block from `SEMANTIC-STATE.json`

An obligation's `evidence_refs` cite a block one of two ways:

- **Direct**: `"SOURCE-LEDGER.md#SRC-001"` — reuses the `#fragment` syntax already used
  for `source_ref` (`AUTHORITY.md#operator-brief-verbatim`).
- **Indirect**: `"FINDINGS-LOG.md:L42-L50"`, where the cited excerpt itself contains an
  inline `[SRC-001]` tag somewhere in that line range. This lets you cite the exact
  quoted excerpt you verified, with the structured citation metadata living once,
  centrally, in `SOURCE-LEDGER.md` — you don't have to also copy the URL/title into every
  place that excerpt gets used.

An `evidence_ref` that resolves to a real file but no recognized citation (directly or
via an inline tag) is **uncited** — `validate` rejects it, same family of error as an
open obligation or a missing acceptance summary.

## Source counts

Because every cited source is exactly one `[SRC-NNN]` block, counting them needs no
separate tracking:
- **Cumulative, per topic**: the number of blocks in that topic's `SOURCE-LEDGER.md` —
  grows monotonically (ledgers are append-only), so it's always the true total across
  every iteration that topic has ever run.
- **Per iteration**: the delta between the count before and after one iteration, the
  same way `progress-signature.sh` already diffs before/after for stall detection.
  Reported on the iteration's own summary line and in `PROGRESS.md`.
- **Portfolio-wide**: summed across every topic's `SOURCE-LEDGER.md` by `research-loops
  doctor` — a cheap on-demand walk over ledgers already on disk, no index required.

## Compatibility

`schema_version: 1` topics (everything approved before this feature existed) are
**not** retroactively checked — citation enforcement only applies at `schema_version >=
2`. To opt an existing topic in: add real `[SRC-NNN]` blocks for its existing evidence,
bump `schema_version` to `2`, then `research_loops/chassis/semantic-state.py rehash
<topic_dir>`.

## Index hits are leads, never evidence

If a cross-reference index has been built (`research_loops/chassis/citation-index.py`,
entirely optional — see `docs/operations.md`), a hit there tells you a source was
*already used somewhere in the portfolio*. It does not tell you the underlying claim
meets *this* topic's own evidence-quality bar — `AUTHORITY.md`'s tiers are topic-specific
by design (see `chassis/CONTRACT-CORE.md`'s evidence handling section). Treat an index
hit exactly like any other unverified lead: go read the original citation, verify it
independently, and cite it in the current topic (as `local`, `external`, or an
`internal` pointer to it) before it backs any disposition. An index miss is a capability
fact, not proof no other topic has relevant evidence.
