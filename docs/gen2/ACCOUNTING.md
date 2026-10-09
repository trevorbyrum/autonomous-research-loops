# Evidence accounting design

Written before implementation for task 2c-1. The boundary is pure arithmetic
over typed durable records: no store handle, writes, model, clock or agent totals.
The Router retains snapshots, authorization and transactions. SOURCE-CONTRACT v2
and the existing accounting import grant apply; no framework or grant changes.

Sources: flow architecture S4–S7 and §3 step 5 (the requested §3.5), methodology
synthesis §§4–6, plan audit F3/F9, BOUNDARIES “Evidence accounting”, INVARIANTS
E-1…E-9/G-1/G-11, and Gate D #5 F1. The external sources are the September 24
flow/methodology documents and September 29/October 9 reviews named in
`docs/gen2/tasks/2c.md`.

| Slice | Types and durable inventories | Outputs and enforcement |
|---|---|---|
| 2c-1 | Typed observations, retrieval events, record/work identity links, screening assessments, claim revisions and invocation outcomes. Existing Store.select reads search_observations, retrieval_events, record_work_links, works, screening_assessments, claims and invocations in the Router's snapshot. Explicit historical-capture provenance distinguishes native inventories from unknown legacy history. | Four separate counts with retained known identities and an unknown reason; zero-assessed novelty is unknown. E-1/E-2/E-3/E-4/E-5/E-8 enforced by accounting; no semantic novelty inferred from counts. |
| 2c-2 | Attributable semantic assessment records (actor/invocation, subject revision, protocol/framing, evidence references); source/version/study lineage; dated lifecycle, contradiction and branch dispositions; semantic accrual. Read these new durable inventories alongside slice 1. | Labeled novelty/independence/applicability/contribution and branch accrual operands. F3 and E-7: judgments are recorded by authorized actors, arithmetic consumes them. E-9: reason-coded reversible screening remains durable; reframe handling consumes G-1 impact dispositions. Identity deduplication alone never merges distinct papers sharing a study origin. |
| 2c-3 | Typed rule operands/results and implemented descriptive, coverage and known-item profiles; contract/protocol pins, observations, assessments, verification/challenge evidence, known-item inventories and amendment impact_records. | Versioned three-valued rule results showing operands and explicit AND/OR, with conjunctive gates (E-6). G-11 evaluator support refused at contract admission and approval in the Router. G-1 invalidation/compatibility applied before reuse; E-4 completed distinct search windows only. Changed-protocol fixture. No automatic meaning saturation, capture-recapture, VoI/EVPI or SAFE. |
| 2c-4 | Typed disposition/confidence and research-state views; slice 2 assessments, slice 3 dossier, branch/contradiction inventories and canonical export inputs. | F9 lossless reconciliation into the bundle (export-bundle/2 if incompatible), explicit unknown confidence, resource/capability/judgment outcomes distinct. E-7 never upgrades arithmetic into sufficiency; unresolved-contradiction fixture and coverage/depth views. |

Slice 1 counts retrieval event identities, exact work identities linked to those
events, distinct assessed work identities, and accepted current claim identities.
Re-screening/stages do not multiply assessed candidates. The latest claim revision
represents its current disposition. Claims need not correspond one-to-one to works.
Unlinked records leave the deduplicated denominator unknown, retaining its known
subset. Study-group annotations do not establish semantic equivalence.

Unknown/partial capture leaves retrieval and work denominators unknown, preserving
the captured subset. A stored result_count is checked only for capture coherence,
never summed as a denominator. Missing observations for an admitted invocation
cannot establish capture completeness. Known assessment/claim inventories remain
separate from retrieval uncertainty. Legacy history makes historical totals unknown
even when some new records are available: no reconstruction or invented zero.
The audited migration path is Phase 4; until then the read API requires explicit
history provenance and cannot detect an import from a queue row alone.

Saturation eligibility is a prerequisite view, not a stopping verdict. A window
is one committed research invocation and its transitive delegates, read in the
same Router snapshot. Delegates must be committed and have captured work; the
parent may coordinate a search performed entirely by delegates. Failed, partial,
missing and unknown work invalidates that window, without poisoning unrelated
historical windows. All captures retain their exact request/replay identities.

Typed search identities separately mirror the gateway's effective `find` form
(`core/request_identity.py`): domain resolution, booleans, defaults and sorted
lane selection, preserving query, kind, filters and population. The engine's
boundary forbids importing gateway code, so a test pins this minimal mirror to
the gateway form. Page size does not change the searched population; cursors
and the outer page number are pagination operands, not search identity.
Window membership uses the observation's actual lane as
its population: automatic and explicit selection of that same lane, and the
other requested lanes' cursors, do not change its identity. Each lane/search
chain must start at declared page 1 with no cursor, have consecutive pages
whose continuation equals the next cursor,
and terminate exhausted. Every page must be fully captured. No cursor-bounded
subwindows are supported, and pages from another research invocation cannot
supply a missing prefix. Repeated lane/search identities earn no new window.

Successful resolve/enrich/fetch/data work belongs to the invocation's capture
inventory but adds no paging window and does not erase a completed find chain;
its failures and partial capture still invalidate the window. Novelty arithmetic
accepts separately supplied labeled judgments; absent judgments and empty
assessed windows are unknown. This window model enforces E-4 in slice 2c-1;
slice 2c-3 consumes it when evaluating stopping rules.

Validation: independently hand-calculated zero-denominator and repeated-study /
overlapping-lanes fixtures; Hypothesis identity/idempotence and unknown laws;
paired-control mutants for unknown→zero, cross-lane multiplication, partial passes,
missing identity links, deferral and legacy history, plus Router window regressions
and mutants for search normalization, ancestry, chain bounds/continuity and
non-paging membership. Targeted tests and --only
mutants; boundary/source/metrics checks and explicit ledger admissions. Later
slices extend this note when their concrete inventories are defined.

## 2c-2: attributable assessments and lineage

Design recorded before code (2026-10-09). Full-slice estimate: about 900
hand-written lines (records/DDL/schema 240, Router admission and wiring 160,
typed reads/arithmetic 120, tests/properties 260, mutants/ledger/docs 120).
This exceeds the approximately 500-line guide: implement **2c-2a only**,
estimated at about 490 lines, then stop for its independent review.

**2c-2a records.** New append-only `semantic_assessments` records name a
retrieved work and its explicit source version, novelty (novel/not_novel/
unknown), independence (independent/shared_origin/unknown), applicability
(applicable/not_applicable/unknown), and contribution (the existing
claim-source contribution vocabulary plus unknown). New append-only
`source_lineage` extensions, keyed to an assessment, name either a study-origin id
(`shared_study_origin`), another work/version (`version_of`), or an acquisition
origin (`derived_from`, another work/version). The assessment retains its
record id, invocation/primary actor, contract revision, eligibility-protocol
version, framing version, evidence artifact references, operation receipt and
Router recording date; its lineage extension inherits that exact attribution
and subject version through its foreign key. Source versions are explicit labels, as in existing
claim-source and verification records; evidence references bind retained
bytes, not an inferred version. No new work identity or source-version table
is needed. `works`, retrieval links and screening assessments remain the
four-unit inventories; the legacy `works.study_group_id` annotation supplies
no authority and is not consumed. Explicit shared-origin records keep two
papers as two works, never merge their identities (E-3/V-9).

**Admission and authority.** An optional additive `semantic_assessments`
outcome/1 section, with an optional lineage extension on each record, enters
through the existing fenced, atomic, replay-safe `commit_outcome`. A new
Router collaborator validates and inserts them; service.py adds thin wiring.
Only contract-admitted primary-class research_pass/checkpoint
invocations may record these judgments, with actor identity taken from the
capability's invocation, never supplied in the payload. Delegates, verifiers,
code and advisory providers cannot claim primary authority. Protocol/framing
fields are required and must equal the pinned contract. Subjects and related
works must be retrieved by this topic; evidence references must be staged in
the commit or already authorized for its topic, with exact size/media type.
Record-id reuse cannot overwrite; DDL also forbids updates/deletes. Distinct
records may disagree: duplicates are retained, never silently resolved.
Human and qualified-provider judgment production/routing belongs to 2e;
this slice provides the authorized primary recording path without extending
operator decisions or granting automatic provider authority.

**Reads.** Extend the 2c-1 typed Inventory and Router read adapter with both
inventories inside the same `_snapshot()`. A public inventory read exposes
attributed operands without writes or a clock. Novelty consumes these explicit
labels through the existing `NoveltyJudgment` arithmetic: absent, unknown or
multiple labels remain unknown (E-7). Semantic records do not enlarge the
screened-candidate denominator. No arithmetic creates independence or other
semantic labels, and no semantic label establishes saturation eligibility.

**2c-2b remaining.** Add dated reversible source lifecycle chains (add, keep,
supersede, coexist, quarantine, duplicate-report), contradiction and branch
dispositions, and typed semantic/branch accrual operands. Later records reverse
dispositions without changing earlier dated views; tests include supersede
then reversal. Read these with slice 1 and 2a in the same snapshot. Consume
the existing G-1 impact dispositions to invalidate/reopen old-framing labels
and reason-coded screening exclusions (E-9), without comparing protocols or
re-deriving impact judgments. Until then 2a exposes raw attributed history,
not a current-framing or lifecycle view; 2c-3 consumes the completed operands.

DDL uses the existing ordered schema mechanism and exact-identity opening
gate; there is no in-place migration/backfill mechanism. Old stores are
refused, and migration remains Phase 4. Tests use only in-memory fixtures.
Validation uses hand-written expectations, Router refusals (unauthorized actor,
missing revision/framing, overwrite, wrong pins/topic/evidence), shared-origin
and explicit-novelty fixtures, append-only laws, and paired guard mutants.
