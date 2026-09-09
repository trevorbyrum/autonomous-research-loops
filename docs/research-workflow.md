# Research workflow reference — delegate roles, packets, triage, batching

Read the relevant section when doing that work; this is not per-iteration required
reading. CONTRACT-CORE owns the invariants; this document carries their working
detail. Model assignments: gpt-5.6-luna is the sole secondary (all seats below);
gpt-5.6-terra is only the checkpoint counter seat (`docs/obligations-checkpoint.md`).

## Roles and ownership

The primary selects the obligation, applies topic-specific quality rules, and owns
relevance, exhaustion, confidence, conclusions, and semantic-state updates. Delegate
bounded discovery, identity reconciliation, acquisition, extraction, and consistency
checks when they reduce duplicated work or improve evidence preparation. Delegate
work stays within the topic's source, access, storage, and usage constraints; it
does not authorize extra provider-credit consumption.

Before new discovery, reconcile identities, pending items, prior routes and dates,
and stale leads against the topic's ledgers. Reuse an adequate current librarian
packet or request a bounded Luna pass for what is missing. The primary examines
consequential exclusions; the librarian supplies facts and pointers, not an
exhaustion or relevance verdict.

Prefer Luna extraction packets for mechanical acquisition. A packet identifies the
fixed source/version and location, dates and retrieval outcomes, exact
claim-relevant passages with locators, methods and limitations, comparators and
denominators where relevant, contradictory passages, and consequential near-misses
or exclusions with reasons and locators. Include retained artifact pointers under
the topic's authorized storage rules. Research claims remain pending until
independently verified; identity and attempt pointers are aids to locating records,
not scientific evidence.

The primary reads the load-bearing passages and enough original context to judge
them. It need not repeat downloading or conversion merely to reproduce the
delegate's mechanics; it may inspect or retrieve additional original context when
necessary. The fresh verifier's independent visit is required and is not prohibited
duplication.

Librarian, discovery, extraction, advocate, and counter workers return packets or
proposed changes; they do not edit live ledgers or semantic state. Only the assigned
verifier has the narrow citation-field permission stated in the verification rule
(`docs/citations.md`). The primary performs all other live integration and state CLI
writes. Parallelize only independent work, and wait for each dependency before
consuming its result. Join delegates or record/cancel failed work before final
validation; do not finish the iteration with workers still able to mutate its
records.

If no permitted secondary is configured or available, continue independent primary
work that remains possible and leave claims requiring independent verification
pending; do not invent a model fallback or self-certify them.

## Overlap triage and comparison rows

Use the librarian's identity checks and the topic's explicit screening criteria to
triage raw search hits. Collapse confirmed duplicate records while preserving
distinct reports, versions, dates, and provenance. An uncertain identity remains a
candidate duplicate. Metadata or abstract facts may establish a clear screening
exclusion; record the decisive fact and locator. A delegate's unsupported relevance
verdict is not a screening fact.

For an in-scope, distinct source being considered for the selected obligation,
overlap with an existing source is not a rejection reason by itself. Before
substantively excluding it as redundant, the primary examines the relevant original
material or reads an extraction packet containing exact passages, locators, and
necessary methods/limitations. Compare only the dimensions that could change the
decision under the topic's quality rules: for example methods, population,
comparator, date, independent support, counterevidence, or a new boundary. First
discovery gives no priority, and recency or breadth alone does not establish
superiority.

Normally record one short comparison row, about 100 words or less, with the
candidate and comparator IDs, decisive distinction or lack of one, locator, and
disposition: superseding, complementary, contradicting, excluded with reason, or
queued for later examination. An accepted new citation remains subject to
verification. Reuse a prior comparison when the claim, source versions, and
assessment are unchanged. Give additional detail only for a consequential ambiguity
or disagreement. The row length is an attention target, not an evidence cap — never
apply it to erase a material contradiction or cut short a topic-required comparison.

The primary chooses a bounded candidate batch consistent with the topic's search
duties. Unexamined plausible leads remain queued; do not count them as rejected or
adequately searched. Neither a delegate's one-line verdict nor a processing budget
proves exhaustion.

## Delegate invocation timeouts

Delegate invocations are long-running: discovery and extraction packets routinely
take several minutes end to end. Set the shell tool's per-command timeout to AT
LEAST 900 seconds (900000 ms) for every `research-loops-luna-delegate` call; the
short default on some harnesses kills the invocation mid-flight, which surfaces as
a launch with no delivered report. A killed or timed-out invocation is a CAPABILITY
failure to record (the wrapper's ledger shows a launch with no usage line) — never
a searched-empty result, and never grounds for an absence claim. If a call is
killed twice at a generous timeout, record the capability failure and move on;
do not shrink the task to fit the timeout by dropping required coverage.

## Lookup packaging

Plan the selected obligation's lookups FIRST, then execute them GROUPED:
`research_batch` carries up to 20 independent resolve/enrich lookups in one call;
use a source's native multi-item form where it exists (one `research_data` call
carries up to 50 BLS series); reuse identifiers, continuation cursors, and sources
already in the topic's own ledgers before re-discovering them; discover parameters
through `research_sources`/`research_catalog` instead of guessing. One obligation
per iteration never means one query per iteration. A citation-index hit (where an
index exists — it is optional) is a LEAD only: examine the original citation and
check freshness before it backs anything.

## Phase markers (measurement)

Skip silently if `$RESEARCH_LOOP_PHASE_LOG` is unset. When you BEGIN each working
phase, append one marker line — `echo "$(date -u +%FT%TZ) <phase>" >>
$RESEARCH_LOOP_PHASE_LOG` — with `<phase>` one of
setup|discovery|extraction|verification|integration. Markers are timing only; they
never substitute for the state CLI and never indicate progress or iteration type.
