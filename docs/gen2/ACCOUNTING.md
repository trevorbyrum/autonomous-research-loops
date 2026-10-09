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

### 2c-2b design addendum (2026-10-09, before implementation)

Full remaining estimate: about 950 hand-written lines (lifecycle 490;
contradiction/branch records, accrual and G-1/E-9 selection 460). Split into
**2c-2b1**, lifecycle chains and dated views, and **2c-2b2**, contradiction
and branch dispositions, semantic/branch accrual, G-1 selection and E-9
re-screening. Implement and commit **2b1 only**, then stop.

**2b1 storage/admission.** Append-only `source_lifecycle` is a new ordered
DDL part, not an alteration or migration of a live store. Each record names
its id, work/source version, contract/protocol/framing pins, one of add/keep/
supersede/coexist/quarantine/duplicate-report, reason and evidence references.
Supersede means the subject is replaced by the explicitly named related
work/version; coexist and duplicate-report also require that related pair.
Other actions have no related pair. These records neither merge identities
nor grant claim-support authority. Optional `supersedes_id` replaces an
earlier lifecycle record of the same topic and exact subject version; a
later keep can reverse supersede or quarantine. The predecessor must already
exist in durable history and have a strictly earlier Router recording time;
no forward links, cycles, backdating or in-place rewrites. Parallel records
may coexist and disagree: replacing one does not resolve the others.

The optional outcome/1 section uses the existing `Assessments` collaborator,
primary-only contract admission, topic-retrieved works and evidence binding.
The Router supplies actor, invocation, receipt and recording time; callers
cannot supply attribution or dates. DDL mirrors attribution/pins and forbids
updates/deletes; admission checks chain identity and time under the commit
lock. Record-id conflicts roll back, while exact operation replay writes
nothing. `service.py` adds one thin write call; no new public Router API.

**2b1 reads.** The existing inventory adapter reads typed lifecycle history
in the same `_snapshot()` as slices 1/2a. Pure `lifecycle_view(records, as_of)`
uses exact UTC instant comparison and returns all active records, canonically
ordered, after removing only explicitly replaced predecessors dated by that
instant. Empty history is empty/unknown, never an inferred add or keep.
The view takes no clock/store and never chooses a semantic judgment.

**2b2 next.** Attributed append-only contradiction/branch disposition records
extend their existing registries without rewriting prior judgments. Typed
accrual operands join those histories and assessments with existing G-1
impact dispositions in the same snapshot; explicit compatibility permits
reuse, invalidation leaves labels unknown/stale, and reframe dispositions
reopen durable old-framing reason-coded exclusions (E-9). No protocol diff
or inferred impact, and no silent resolution of disagreement. Judgment
production, provider qualification and escalation remain 2e (plan audit F3).

2b1 estimate breakdown: records/view/read 55, DDL/schema 100, admission and
wiring 60, tests/properties 170, mutants and documentation/ledger 105.
Validation: hand-written supersede/reversal and disagreement expectations,
dated-view Hypothesis law, admission/DDL/schema refusals with paired controls,
full composition module, every edited-file mutant family, and the six gates.

DDL uses the existing ordered schema mechanism and exact-identity opening
gate; there is no in-place migration/backfill mechanism. Old stores are
refused, and migration remains Phase 4. Tests use only in-memory fixtures.
Validation uses hand-written expectations, Router refusals (unauthorized actor,
missing revision/framing, overwrite, wrong pins/topic/evidence), shared-origin
and explicit-novelty fixtures, append-only laws, and paired guard mutants.

### 2c-2b2 design note (2026-10-09, before implementation)

Full estimate: about 800 hand-written lines (disposition histories 480;
typed accrual, G-1 selection, E-9 reopening and their tests/mutants 320).
Split into **2b2a**, implemented here, and **2b2b**, remaining; stop after
committing 2b2a. First-part estimate: DDL 65, schema 35, admission/wiring 40,
typed records/read 30, tests/properties 175, mutants 85, docs/ledger 50.

**2b2a.** The declared branch registry and contradiction ledger currently
have prose/export references, but no durable registry tables (store README
defers them to Phase 2). Extend that registry vocabulary with one ordered
DDL table, `registry_dispositions`: topic-local registry identity and kind
(contradiction/branch), subject text, disposition (unresolved/resolved/contested
or promote/park/drop), reason, evidence, pins and Router attribution. Promotion
records a proposal only; it grants no scope, support or scheduling authority.
Optional `supersedes_id` names a strictly earlier record of that exact topic,
kind and registry identity; reversals append, never update. Parallel judgments
remain visible, including an unresolved contradiction beside a resolution.
The existing Assessments collaborator admits these optional outcome/1 records
with the same primary/contract authority, evidence binding and exact pins.
Inventory reads expose all typed histories inside the existing `_snapshot()`.
Tests independently specify refusals, replay/rollback, disagreement and retained
history; Hypothesis checks that successful appends preserve the entire prefix.

**2b2b remaining.** Join these histories with semantic assessments, lineage,
dated lifecycle and existing `amendment_impacts` in that snapshot. Consume
recorded standing and dispositions only: explicit compatibility permits label
reuse; invalidation/missing standing yields stale/unknown, with no revival by
label cycling. Consume recorded reopened exclusions for E-9, retaining their
reason-coded old-framing assessments and an unaffected-framing control. No
protocol comparison, inferred impact or judgment production (2e; plan audit F3).

### 2c-2b2b design note (2026-10-09, before implementation)

Estimate: **about 480 hand-written lines**, without a further split: typed
operands/arithmetic 150, snapshot adapter 25, fixtures/properties 180,
paired mutants 85, documentation/ledger 40 (generated controls excluded).
No new write path, DDL, provider call or authority grant is needed.

The existing inventory snapshot additionally reads the recorded approved
contract revision, typed contract amendment standing/reopened exclusion IDs,
and reason-coded screening history. Pure accounting returns semantic operands
with retained assessment, exact assessment-linked lineage and exact work/version
lifecycle with each disposition's standing; branch operands retain promote/park/drop history and only explicitly
unreplaced dated dispositions. Competing records remain visible. These are
operands for 2c-3, never sufficiency or scheduling judgments.

Label selection uses revision identity and recorded standing only. A current
approved revision stands; an older revision needs explicit compatibility in
the impact naming the snapshot's current revision. Any recorded invalidation
is sticky, including across label cycling; missing standing is unknown.
Stale/unknown semantic operands expose unknown effective labels while retaining
the original labels. Missing or unusable branch records yield unknown operands,
never an inferred active/parked status. The supplied date limits semantic and
branch histories and lifecycle replacements; standing describes the current
snapshot context, not a reconstruction of historical approval authority.

E-9 returns the recorded reopened exclusion assessments, with original framing,
protocol, reason and attribution, without treating a changed framing as an
inferred reopening. Tests specify compatibility, invalidation, missing standing,
cycling, exact lineage/version joins, lifecycle/branch reversals, disagreement,
and reframe versus unaffected controls by hand. Hypothesis checks unrelated
append invariance, future-history invariance and unknown propagation. Every
selection guard has a paired mutant. Judgment production stays in 2e.

Implementation keeps the existing module graph and metric budgets; the current
accounting/adapter and instant-helper ledger admissions cover these reads. The
new context-read helper keeps snapshot assembly below its complexity threshold.

## 2c-3 design note (2026-10-09, before implementation)

Full estimate: **about 760 hand-written lines** (pure types/evaluators 200,
fixtures/properties 180, mutants 55, documentation/ledger 55, Router admission
and approval plus the changed-protocol fixture 270). Split as the brief directs:
implement **2c-3a only**, estimated at **about 490 lines**, then stop.
**2c-3b remains:** G-11 refusals at both Router boundaries, contract-to-evaluator
binding, and the changed-protocol/compatible-amendment integration fixture.

3a adds one pure accounting module. Results carry `stopping-result/1`, topic,
contract revision and protocol revision, the rule identity, and typed operands.
Descriptive arithmetic retains all four candidate units and attributed semantic
operands, using their G-1-selected effective labels for novelty; its rule state
is unknown because reporting yield declares no stopping predicate. Coverage
compares a declared minimum with E-4 completed distinct windows from the existing
inventory arithmetic. Explicit per-invocation contract pins select each window's
recorded G-1 standing; missing, stale or unknown pins cannot satisfy coverage.
Known-item retrieval compares an explicitly referenced, nonempty sentinel work
inventory with deduplicated works, retaining found/missing identities and unknown
capture. Finding sentinels says nothing about undiscovered literature. Screening
and both-mode sentinel checks are not implemented by this retrieval evaluator;
3b must refuse unsupported bindings rather than silently reinterpret them.

Typed recursive expressions accept only rule references and nonempty `all`/`any`
branches. Strong three-valued conjunction/disjunction preserve unknown except
where a decisive false/true operand determines the expression. Declared gates
are conjoined separately, including under an `any` rule expression. Missing
rules/gates or mismatched result pins yield unknown; operands remain inspectable.
Gate inputs retain evidence references and status supplied by the code-owned
assembly path; gate evidence production/validation remains 2d/2e, not invented
here. No evaluator produces meaning or a scientific sufficiency ruling (E-7).

The schema already closes expressions, requires completion gates and restricts
capture-recapture/VoI/SAFE/meaning saturation to reviewed judgments. 3b closes the
remaining implemented-support gap, including statistical recall, without schema
duplication. Tests in 3a use hand-built inventories and hand-written truth tables,
failing/unknown gates, stale/unknown labels, repeated/partial/non-search controls,
and sentinel membership. Hypothesis checks truth-order monotonicity and unknown
conjunction persistence. Paired mutants cover these guards. SOURCE-CONTRACT v2,
existing accounting grants and new-file/edge ledger admissions apply; no Router
wiring, DDL, migration, store, clock or provider call is added in 3a.

### 2c-3a repairs: standing and sound certain-answer bounds

The representation follows `research/2c-coverage-unknown-20261009.md` (F1).
`window_standings()` sits beside the unchanged E-4 `saturation_passes()`
eligibility view. It accounts for every attempted research invocation, with
its transitive delegates forming one window rather than additional windows.
Each standing retains its root identity, eligibility state and reason.
Completed distinct windows are eligible; failed/cancelled, capped, repeated,
non-search and provably invalid-chain windows are known ineligible. Missing, partial,
unobserved or incoherent capture, missing search metadata, unfinished work and
unknown pagination ends are indeterminate. A parent may coordinate completely
captured delegate searches without its own observation. Known failures exclude
the affected window even when another member is unobserved. Other historical
windows remain available.

Coverage applies the supplied invocation/contract pins to those standings:
recorded stale G-1 standing is known ineligible; missing/unknown standing is
indeterminate unless the window is already known ineligible. Compatible
historical revisions remain eligible. An optional explicit `scope` selects
research root IDs for each rule; omission includes every attempted window.
Pins record revision provenance and do not implicitly restrict scope.
Coverage operands retain every scoped window, its G-1 standing, eligibility
and reason, the three counts, the explicit scope, and lower/upper bounds. Indeterminate windows
remain visible even when the verdict is definite.

Addendum 1 of the research note governs completion dependencies. The upper
bound is eligible + indeterminate. The lower bound considers earlier
indeterminate roots in global inventory order, including roots outside the
rule's scope and roots with stale G-1 standing. `window_search_knowledge()`
retains the recorded lane/search populations of each root and its delegates;
missing searches or search metadata give an unknown population. Known searches
can consume only their recorded populations; unknown searches can consume any
later population. Known complete roots retain their global E-4 allocation even
when their results cannot be reused under the rule's contract.

The lower bound counts each scoped current eligible root whose new search
credit cannot all be consumed by earlier indeterminate roots. It considers
their combined populations, so several uncertain roots can jointly take a
multi-search root's credit. Vulnerable roots sharing possible earlier owners
form connected groups. Each group guarantees one window only if every possible
owner is current and in scope: failed/uncompleted owners leave the observed
windows intact, and a completing first owner contributes its own window.
Otherwise the group's conservative guarantee is zero. This takes the minimum
over failed and complete resolutions while allowing additional unknown verdicts;
it does not freeze allocation or change E-4's counting unit.

Chains with contradictions (null incoming cursor after page 1, a cursor on
page 1, conflicting page numbers, incompatible adjacent cursors, or exhaustion
before another page) are provably invalid. Consistent missing prefixes/interior
pages and unknown terminal pagination are recoverable and remain indeterminate.
Complete chains satisfy the existing captured-page and exhaustion requirements.
Recoverable chains remain absent from `saturation_passes()`, whose implementation
and exclusions are unchanged.

For minimum N, coverage is satisfied when lower >= N, not_satisfied when
upper < N, and unknown otherwise. Known stale windows
contribute to the ineligible count rather than forcing unrelated valid windows
unknown. Legacy history and an evaluator/snapshot contract mismatch still make
the result unknown because the attempted-window universe/context is untrusted.
No arithmetic establishes scientific sufficiency.

Literal tests retain the original F1 cases and add Astra's pure, scoped and
Router overlap probes and missing-prefix probe with positive/negative controls.
Hypothesis builds small inventories with uncertainty before, between and after
complete roots, overlap/disjoint and multi-search populations, prefix/interior
gaps, delegates, scope, and current/compatible/stale/unknown G-1 standings.
An independent finite oracle enumerates every admissible failed/uncompleted or
complete resolution over the inventory's populations plus one fresh population,
allocates first-owner credit globally, then applies scope and reuse standing.
Definite verdicts must agree with every completion; unknown verdicts where all
completions agree are counted and reported as permitted approximations. This
replaces the restricted monotonicity claim with differential soundness checks.
Paired mutants cover the earlier-owner discount, known/unknown populations,
recoverable chains, scope ordering, joint thieves, and replacement contributions.

## 2c-3b design note (2026-10-09, before implementation)

Full estimate: **about 650 hand-written lines** (bindings and boundary checks
140, contract vocabulary and snapshot/reuse assembly 150, Router integration
fixtures 220, mutants 80, documentation/ledger 60). Split as instructed:
implement **2c-3b part 1 only**, estimated at **about 400 lines**, then stop.
This part closes G-11 at draft/amendment admission and all contract approvals,
with a pure known-item retrieval binding and paired controls. The schema remains
the authority for rule shape and reviewed-only families; the support check
uses it and reports the offending rule identity, family and reason. Reviewed
rules retain their declared parameters and have no automatic evaluator.

The current schema has no descriptive or coverage family. Diminishing returns
declares an assessment-window threshold; counterevidence declares a challenge
scope and completed requests. Neither is implemented by 3a's descriptive yield
or E-4 window-count prerequisite, so their automatic forms must also be refused,
alongside statistical recall and screening/both sentinels. No family is silently
reinterpreted. Existing Router fixtures will explicitly request reviewed
judgments for those rules; the schema examples remain unchanged.

**Part 2 remains:** an explicit contract vocabulary for descriptive and coverage
bindings (including minimum N and invocation scope), and the changed-protocol
Router integration fixture with incompatible invalidation, B-current
re-evaluation and compatible reuse. That assembly must consume recorded G-1
standing before composing old results or operands, rather than comparing
documents again or relabeling old results as current. Gate evidence production
and scientific sufficiency remain with 2d/2e and the operator.

## 2c-3b2 design note (2026-10-09, before implementation)

Estimate: **about 460 hand-written lines** (schema/fixtures 100, pure bindings
and reuse 60, tests 180, paired mutants/tool wiring 90, docs/ledger 30).
Add two closed families without changing any existing declaration:
`descriptive` has empty parameters and always reports an unknown stopping
state; `coverage` requires positive `minimum_windows` and an explicit `scope`
array of invocation IDs (empty means no selected windows). Bind both to 3a;
coverage remains an E-4 prerequisite alongside the unchanged completion gates.

Extend pure binding dispatch with caller-supplied dated inventory/window pins.
Profile composition optionally consumes the Router's existing evidence snapshot
and recorded G-1 standing: only current/compatible rule results with matching
topic/protocol and current snapshot may contribute. Unusable results, including
their operands, are omitted, leaving affected expression leaves unknown;
compatible results retain their original contexts. Gate evidence still requires
the exact current context and is supplied by its existing authorities.

Use the existing Router admission, approval, observation, outcome and inventory
APIs for literal incompatible/compatible amendment fixtures. A stopping change
must take a new protocol version; after invalidation, explicit B evaluation
consumes B-current windows. No Router API, store format or authority changes.
Add isolated schema negatives, binding controls, N1's wrong-hash regression and
paired mutants; retain old schema fixtures byte-for-byte. This additive design
stays within Astra's Part-2 ruling and crosses no escalation boundary.

Existing ledger admissions ML-0033–0045 cover these accounting paths. This
slice adds no module, dependency edge, reachability, Router member or numeric
exemption; the baseline and committed metrics ledger need no changes.

## 2c-4 design note (2026-10-09, before implementation; BLOCKED)

Input tip: `0da76bdda79411f88fb90ce38a0331bc7383dad1`, branch `gen2`.
Sources: plan audit `gen2-phase2-plan-audit-astra-20260929.md` F9 and rows
31–32; flow architecture `gen2-flow-architecture-20260924.md` S7/S8;
`methodology-synthesis-20260924.md` §§4–6; design review
`gen2-design-astra-review-20260922.md` §8; 0c review September 25 §B and
September 26 repair review §B; EXPORT-API §2; BOUNDARIES “Evidence
accounting”; INVARIANTS E-7/G-8/G-9/P-1…P-7. The legacy semantic-state
schema corroborates the disposition names only; it supplies no gen-2
assessment authority or confidence scheme.

**Decision boundary.** F9 requires the four evidence distinctions, but
EXPORT-API still explicitly calls its vocabulary proposed. Its confidence
shape presupposes a contract-declared scheme; Contract v2 has no structured
scheme pin, permitted labels or rubric. Its statistical `confidence_level`
parameter is a different operand, not obligation confidence. The export
example's `contract-certainty` scheme/version is fixture data, not an approved
scheme definition. Neither the methodology nor the 0c rulings supplies a
validated certainty scale; those rulings expressly reject borrowing GRADE
bands without a justified mapping. Selecting a scheme or declaring new
obligation assessment semantics would therefore require an operator choice.
Task 2c-4's “Escalate rather than decide” instruction applies: **stop before
implementation**, retain this proposal, and report BLOCKED.

**Proposed reconciliation table, pending that choice.** The second column
describes a future `/2` mapping, not an adopted contract. Each judgment must
retain its identity, subject, attribution, evidence, pins, date, reason and
explicit predecessor; a display label alone is not a lossless mapping.

| Authoritative input distinction | Proposed bundle representation | Why `/1` cannot substitute |
|---|---|---|
| Supported obligation assessment | `supported`, with original support links and assessment | `/1` already has this label, but does not carry the complete assessment record. |
| Contradicted obligation assessment | `contradicted`, with its counterevidence and reason | `not_supported` does not distinguish contradiction from absence of support. |
| Unresolved obligation assessment | `unresolved`, retaining the stated epistemic/coverage limits and open contradiction records | `unknown` specifically means unestablished coverage; `insufficient_evidence` specifically asserts adequate search; `mixed` asserts a conflict with a hold. None is a universal substitute. |
| Deferred obligation assessment | `deferred`, with the recorded reason and pending work | No `/1` disposition represents deferral; resource/capability limits cannot become an evidence verdict. |
| Open/unassessed obligation | Preserve an explicit open state separately, if admitted by the chosen scheme | The legacy `open` state is distinct from a recorded unresolved assessment; no automatic open→unresolved judgment. |
| Contradiction `unresolved` / `resolved` / `contested` | Identity mapping of every registry record, retaining competing records and explicit replacements | A `mixed` obligation and hold ids do not preserve this registry history or establish that a resolution occurred. |
| Branch `promote` / `park` / `drop` | Identity mapping with proposal meaning and reason intact | No bundle field carries these records; promotion grants no new authority. |
| Lifecycle add/keep/supersede/coexist/quarantine/duplicate-report and semantic/lineage operands | Preserve typed dated records and recorded G-1 standing; retain original labels beside effective unknown labels | Claim status and rendered synthesis artifacts cannot replace these attributed histories. |
| `completed_with_qualified_conclusions` | Same outcome plus framing, coverage and discovery qualifications | Existing completion representation is retained; arithmetic supplies no sufficiency ruling. |
| `stopped_for_resources` | Same outcome plus residual uncertainty | Never map to qualified completion or saturation. |
| `capability_blocked` | Same outcome, with retained capability evidence | Never map to a resource stop or an evidence conclusion. |
| `awaiting_judgment` / `retired` | Same outcome, separately retained | `/1` has all five G-9 enum labels, but forces outcome to null when not completed; a recorded topic outcome needs independent preservation. |
| Unknown confidence | `{basis: unknown, reason: <retained reason>}` | The existing shape fits; no default label, zero or probability. |
| Recorded confidence | Original scheme id/version, label and assessing invocation, checked against the approved contract pin | The existing confidence shape fits syntactically, but the contract pin and scheme definition are missing. |

**Bundle decision.** `/1` cannot carry this reconciliation losslessly. After
the operator settles the scheme, introduce `export-bundle/2` additively;
keep `/1` schemas, fixtures and meanings unchanged. Do not disguise new
meanings in `/1` reason prose. Preserve recorded topic outcomes independently
of the scientific completion fact; carrying a blocked/awaiting outcome must
never require asserting completion. The accepted 2c-2 semantic records assess work
novelty/independence/applicability/contribution, not obligation disposition or
certainty; `contribution=confidence` is not a confidence rating. The 2c-3
rule/profile results likewise provide stopping operands, not those judgments.
The eventual mapper needs explicit attributable obligation-assessment inputs;
it must not infer them from claim counts, registry subject text or rule status.
Durable production of those judgments must be coordinated with 2d/2e.

**Operator options and recommendation.** For vocabulary, (A) retain the four
named evidence dispositions plus a separate open state and the complete
contradiction/defer records, or (B) approve separate evidence, adjudication and
deferral axes with an explicit mapping back to every original disposition.
Recommend A for the smaller mapping and preservation of the named source
distinctions; B needs additional definitions and tests. Neither option permits
an unresolved contradiction to disappear behind a single chosen judgment.

For confidence, (A) approve a per-contract categorical scheme with its actual
id/version, allowed labels and rubric, bound into the hash-locked contract,
or (B) explicitly authorize unknown-only confidence for this slice and assign
recorded-confidence support to a later task. Recommend A, with labels treated
as attributed judgments, never calibrated probabilities. B is a scope change,
not completion of the current requirement. No high/medium/low or GRADE scheme
is selected here. The operator must supply or approve the actual definition
and the contract-binding shape before reconciliation code can be written.

**Views and authority.** Coverage views expose the four candidate units,
completed/failed/indeterminate windows, recorded lane/search identities and
G-1 standing. Branch coverage requires recorded branch links; do not infer
them from prose. Depth views expose accepted semantic accrual, exact lineage,
dated lifecycle and branch/contradiction histories, plus recorded reopenings.
Both are pure read-only views of supplied typed snapshot operands, without a
clock, store writes, provider calls or automatic sufficiency (E-7). Mapping
lives in `gen2/accounting`; approved-bundle assembly remains the Phase-3
Router/export path in EXPORT-API. No new exporter, connector or approval path
is authorized by this proposal; service.py needs no change for this note.

**Provisional size and split.** Full post-decision estimate: **about 820
hand-written lines**, excluding generated controls. Split into **2c-4a**
(mapping/types 90, additive schema and contract binding 150, round-trip and
compatibility tests 140, paired mutants 60, docs/ledger 50: **490**) and
**2c-4b** (views 150, end-to-end unresolved-contradiction and view tests 110,
paired mutants 40, docs/ledger 30: **330**). Re-estimate once the approved
scheme and durable assessment inputs are known; split 4a again if necessary.
Implementation is blocked before 4a, so this commit contains design only.
After the decision, implement only 4a and stop for review. 4b retains the
research-state views and remaining fixtures, including the contradiction
visible in the dossier, mapping and bundle. Tests must use hand-written
expected records, prove an exact round trip, preserve explicit unknown
confidence and old `/1` meaning, and pair every new guard with a mutant.

## 2c-4b: snapshot coverage and depth views (2026-10-09, before code)

Input tip: `d182608`, branch `gen2`; operator ruling 3 builds views first.
Estimate: **about 450 hand-written lines** (pure views/types 140, fixtures and
properties 210, paired mutants/tool registration 65, design/boundary/ledger 35).
Implement this slice together; the dossier-to-bundle contradiction fixture
belongs to 2c-4a, as the 4b brief specifies.

Coverage composes the accepted four-unit counts and 2c-3a window standings,
retaining capture reasons, exact observation/request/page identities and
recorded lane populations. G-1 standing is shown separately beside each
window's supplied contract pin; capture completion does not imply usable
current-framing credit. Typed branch-to-invocation links are explicit supplied
snapshot operands, like window pins: existing inventories have no durable
branch/search link table. Missing links or linked windows leave branch coverage
unknown; registry subjects never establish links. No new admission/storage path.

Depth composes semantic accrual and its exact lineage joins, complete dated
lifecycle history plus active records, and branch/contradiction histories with
explicit replacements and competing judgments retained. An unresolved record
can leave the active set only through an explicit successor and remains in
history. The caller supplies `as_of`; it clips record dates, while G-1 reflects
the supplied snapshot's current standing, as accepted accrual already does.
Recorded amendment impacts and reopened exclusions remain inspectable.

Both functions live in `gen2/accounting/views.py` and consume the existing
`Router.evidence_inventory` snapshot plus typed supplied operands. No Router
API/wiring, clock, writes, provider calls, sufficiency predicate or export
authority is added. Hand-written positive/negative oracles, isolated Hypothesis
laws, read-only/topic-isolation fixtures and paired controls cover the guards.
