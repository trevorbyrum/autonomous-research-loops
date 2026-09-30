# Licensing: how the verdicts are derived and enforced

Every source in the registry carries a commercial-use verdict with a link to
the terms it was read from. The gateway routes on that verdict; nothing about
licensing is left to convention.

## The baseline

**Personal, non-commercial research use is the baseline.** A source is only
in the registry if it has a programmatic interface, its terms of use were
read, and the permitted usage is understood to cover non-commercial research.
Sources that fail any of those three tests are documented (if useful to know
about) but never scheduled.

## The one flag: `commercial`

A request, or the topic it belongs to, may be flagged `commercial`. The
router then applies the source's verdict:

- `allow` — the source's own terms permit commercial use of what the gateway
  retrieves (public-domain government data, CC0 or CC-BY metadata, attribution
  licences).
- `per-item` — the platform permits it, but each record carries its own
  licence (dataset hubs, article platforms with per-article Creative Commons
  variants). The lane is used only if the caller opts in, and every record
  without an allow-listed licence is dropped before it is returned.
- `deny` — the terms forbid commercial use, or require a paid tier. The lane
  is skipped and the response records that as a capability fact.
- `unknown` — no reuse terms could be located. Treated as `deny`. Unknowns
  are stated as unknown in `docs/SOURCES.md`, never guessed.

## Redistribution and caching

Independently of the commercial flag, a source's terms decide whether the
gateway may *keep* what it retrieved. Sources that forbid redistribution or
repackaging (for example Semantic Scholar's API licence) are cached in memory
only for at most an hour, never written to the database, and never exported.
Public-domain and open-licence sources may be persisted with provenance.

## Four facts per record, never one flag (task 2b)

Availability, access, storage and redistribution are separate questions, and every
returned record — and each provenance member of a merged record — answers each one
separately in its `permissions` (computed from the registry and the member's own content
licence on every answer, cache hits included; `core/licenses.py`):

- `availability` — `content` when the gateway delivered the item itself (full text, rows,
  file bytes), `metadata` when it delivered a description of it — a file or full-text
  record that carries only its links is a description (task 2b-repair A3);
- `access` — `commercial_use` when the source's verdict and the member's own licence let
  it be used commercially (with per-item acceptance), `personal_use` otherwise;
- `storage` — `persist` when the gateway may keep it (the rules above), `transient` when
  it is only delivered (and held in memory for at most an hour);
- `redistribution` — whether the CONTENT may travel downstream (an export, a quote),
  decided by the content licence alone: `permitted` (an exactly identified allow-listed
  licence), `conditional` (identified, with share-alike / non-commercial /
  no-derivatives / copyleft conditions), `prohibited` (the source's terms forbid it), or
  `unknown` (absent or unidentifiable — never read as permitted).

A merged record carries the most restrictive of its members' facts. Records also carry
their source's `metadata_license` and `freshness_lag` beside their own content `license`
and `retrieved_at`. In `gateway.record_sources`, `redistributable` is true only when
`redistribution` is `permitted`; before this it was true for every persisted row, and
meant only that the gateway could keep it. Its `license` is the member's CONTENT licence
(unknown when absent); the licence of the registry data a harvest loader read (DOAJ's CC0
catalogue, a CC0 snapshot) is `metadata_license`, and never stands in for it. A source's
own statements about a member — its terms forbid redistribution, third-party terms — are
kept with every stored member summary, so a record reloaded from the database and
annotated again re-derives the same restriction (task 2b-repair A3). Rows stored before
that (`gateway.records.restriction_inputs` false) are converted once, before a gateway will
open the database: `python -m research_gateway.registry.migrate` (task 2b-repair-4). A lead
member's statements come from the record's own fields; task 2b's stored `prohibited` is the
source's prohibition, its one cause; a stored `personal_use` nothing else explains is kept
as `inferred_personal_use` — inferred from legacy data, never presented as a statement of
the source. An upgrade never widens a stored restriction. Running it on a real database is
a release step the operator approves. Every read that serves a stored record, and every count
of them, goes through one view, `gateway.servable_records`, which withholds a row not yet
converted (its canonical NULL); a withheld match makes its lane partial, or unobserved when
nothing else matched — never a complete answer (task 2b-repair-5; tests/test_record_gate.py
fails on any other serving read of `gateway.records`).

## Attribution

Several `allow` verdicts are conditional on attribution (FRED, BEA, ECB, BIS,
OpenAIRE, CC-BY sources). Records from those sources carry an `attribution`
field in the canonical record so downstream outputs can cite correctly.
FRED additionally flags series with third-party restrictions per series.

## Caveats

- Verdicts were read from the sources' terms on the dates given in the seed;
  terms change. Re-check when a source announces new terms, and record the
  new evidence link.
- A verdict describes the *source's* terms, not the content's. A CC0
  metadata record may describe a copyrighted paper; the gateway returns
  links to content, not the content (`PLAN.md` I-7).
- A record's `license` field — and each provenance member's — is the CONTENT
  licence that source reported for the work itself. The licence covering the
  source's *metadata* is a per-source registry verdict (this document and the
  seed), never a per-record field: the two answer different questions and the
  gateway does not conflate them (STATION-CONTRACT.md, 8a).
- None of this is legal advice. The verdicts are documented readings of
  published terms so that a deployment can make its own decision with the
  evidence in front of it.
