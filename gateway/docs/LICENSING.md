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
- None of this is legal advice. The verdicts are documented readings of
  published terms so that a deployment can make its own decision with the
  evidence in front of it.
