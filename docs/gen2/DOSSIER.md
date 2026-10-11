# Task 2d dossier design

Design written before code, against `f8754ba` on `gen2` (2026-10-10).
Authority: private `gen2-flow-architecture-20260924.md` S4, S7, S8 and §4.8;
`methodology-synthesis-20260924.md`; `reviews/gen2-phase2-plan-audit-astra-20260929.md`
F3/F7/F10; Gate D #6, “Readiness and finite follow-through for 2d”; the
charter, BOUNDARIES, INVARIANTS, ACCOUNTING, EXPORT-API, and task 2c-4's
operator rulings. This note schedules work; it grants no new authority.

## Existing enforcement and remaining work

Paths below are relative to `gen2/`. SQL numbers name ordered schema parts
under `store/schema/`. Tests describe structural guarantees, not scientific
validity or a qualified live workflow.

| Requirement | Existing DDL, code and tests | Missing / owning slice |
|---|---|---|
| V-1 receipt binding | `03-evidence-and-decisions.sql`, `verification_receipts` JSON/column checks and binding trigger; `router/service.py::_validate_commit`, `router/evidence_writer.py`; `tests/test_store_ddl_evidence.py::VerificationTest`, `tests/test_router_evidence.py` | Actual verifier re-access and typed byte/span hand-off; slices 3–4, producer in 2e2. |
| V-2 truthful tiers | SQL 03 promotion and receipt-use triggers; `router/boundary.py::TIER`, receipt schema; the same verification tests | Cross-check obtained tier against access route and source/table availability, then consume receipts in dossier gates; 4, 6. |
| V-3 independent checking | SQL 03 receipt role/binding triggers authenticate canonical bytes and extraction lineage; `VerificationTest` tests producer-byte reuse and rejected unvalidated extraction | Runtime re-access/validated-extraction path; 4, with workflow execution in 2e2. |
| V-4 provisional / accepted support | SQL 03 `claims_accepted_support_needs_receipt` and `verification_receipts_use_matches_claim`; `router/evidence_writer.py::_promote_and_link_claims`; `VerificationTest` sampling/partial-support promotion refusals | Required receipts must also be checked over the dossier's exact claim revisions; 6. |
| V-5 disagreement | Typed `holds` in SQL 02 and outcome schema; Router writes holds; `tests/test_router_evidence.py` | Verification disagreement must generate an owned judgment hold; 4. Deadline scheduling/escalation belongs to 2e2. |
| V-6 byte checks before NLI | SQL 03 `quote_checks` mismatch/alarm quarantine and receipt binding; `VerificationTest::test_nli_alarm_quarantines_the_quote`, `test_quote_check_binding` | Perform byte/span/normalization computation rather than trust supplied match labels; persist result, notify capture owner, prevent mismatch adjudication bypass; 3. |
| V-7 tier-0 optional | Receipt schema and SQL 03 prevent alarm-based promotion; existing quote/receipt tests | Optional screen adapter, audit records with denominators and sampling probabilities, false passes/alarms and regression disposition; 5. Sampling workflow in 2e2, provider qualification in Phase 3. |
| V-8 independent detailed checks | Receipt schema, SQL 03 receipt CHECKs and promotion reread of units/denominators/negation/qualifications; `VerificationTest` | Typed verifier production and actual unperformed/unavailable check handling; 4, 6. Code never supplies semantic judgments. |
| V-9 three independences | SQL 03 `claim_source_links`, separate receipt invocation; SQL 05 semantic/source lineage; `tests/test_semantic_assessments.py`, `tests/test_router_workflow.py` | Carry all three independently into exact dossier/export; 6, 8. |
| V-10 protocol admission | SQL 03 `claims_accepted_support_needs_contract_admission`; `router/evidence_writer.py` reads G-1 standing; `tests/test_router_evidence.py::ProductionAndAdoptionTest`, `tests/test_router_amendments.py` | Reuse this gate; dossier assembly must retain stale/adopted history and cannot promote fixtures; 6. |
| G-8 exact completion approval | SQL 01 `queue_completion_needs_current_dossier_approval`; SQL 02 immutable dossiers and exact decision subjects; `router/service.py::_require_subject_hash_truth`, `_apply_decision`; `tests/test_router_ops.py`, `tests/test_store_ddl_contracts.py` | Authoritative full dossier generation/hash, material-change revalidation and fresh sufficiency-review binding; 6–7. Publication approval remains separate. |
| P-1 atomic manifest | SQL 04 immutable `outbox_events` approved source/JSON bindings; Router validates and writes manifest in commit; `tests/test_store_ddl_export.py::ExportOutboxTest`, `tests/test_router_evidence.py` | Exact-revision assembler and /2 enablement on this same path; 8. |
| P-2 ordered delivery | SQL 04 increasing pairs, one revision per generation, named connectors, watermarks; `ExportOutboxTest` | File destination's atomic pair/identity retention, replay, conflict, tombstones; 9. Other connectors Phase 3. |
| P-3 local served-revision read | `freshness-envelope.schema.json`, boundary graph prohibits connector reads; `router/status.py` supplies local status | Compute a truthful envelope with approved served revision and newer unapproved disclosure; 11. |
| P-4 independent facts | Separate dossier/outbox/receipt tables; freshness schema; `ExportOutboxTest` receipt shape/status checks | Combine completion, delivery and currency without changing one from another; 10–11. |
| P-5 approved corrections | SQL 04 exact `publication_approval`, artifact kinds and source/hash binding; `ExportOutboxTest::test_only_approved_work_is_exported` | Assemble corrections/checkpoints through the same manifest path; 8–9. |
| P-6 feed liveness | Freshness schema has per-feed issue reasons | Durable due time, success, cursor/coverage, result class, failure, owner and retirement evidence; 10. Poll/reopen scheduling is 2e2. |
| P-7 unknown effects | SQL 04 receipt status/count/tombstone rules; `router/service.py::ack_delivery`; `ExportOutboxTest::test_receipt_status_rules`, `test_written_count_rules` | Actual file attempt and reconcile by resend after ambiguous application/receipt loss; 9. No destination read by engine readers. |
| F3 real completion evidence | `accounting/stopping.py`, `tests/test_stopping.py`, `test_stopping_bindings.py`, `test_stopping_protocol.py` distinguish unknown/stale/bounds; existing admission and tier fences | Supplied GateResults are not proof. Admit actual successful challenge/competing-explanation packets, coverage provenance and fresh review, then enforce conjunctive gates; 6–7. Producers in 2e2. |
| F7 one export path | EXPORT-API and existing manifest/outbox authority; additive /2 schema, `accounting/reconciliation.py`, `tests/test_reconciliation_operands.py`, `test_reconciliation_bundle.py` | Durable records, licence-bound approved-revision assembly and one JSONL/file connector with complete guarantees; 1, 8–9. Update EXPORT-API's obsolete Phase-3-only text then. |
| F10 feed/read state | Status and freshness contract exist; no durable feed inventory | Persist facts and derive currency, including early failure and successful-empty; 10–11. Scheduling/health workflow remains 2e2. |
| Gate D F1 / DEBT-035 | Rich `accounting/stopping.py` result; /2 currently inherits /1 scalar stopping shape | Add a lossless rich-result representation: context, invocation scope, window pins, G-1 standing, reasons, raw uncertainty, bounds, sentinels and gate evidence; 6. Test satisfied bound + indeterminate windows, conservative unknown and stale. Preserve /1 rules/bytes. |
| Gate D F2 / DEBT-036 | `router/accounting.py::read_inventory` and `router/status.py` read under `_snapshot` (writer transaction); `service.py` has 89 lines of headroom; composition tests | Coherent input capture, computation outside writer lock, commit-time revision/hash revalidation and workload measurement; 6, 8. No cache/second store/query framework. |
| DEBT-032 | Pure `accounting/views.py` BranchLink/WindowPin operands and `tests/test_research_views.py`; durable branch registry/dispositions exist | Admit attributable branch/window links; validate topic/branch/window, derive revisions from invocation/contract, keep absent provenance unknown; 2. |
| DEBT-033 | Pure ObligationAssessment/OpenObligation and confidence checks in `accounting/reconciliation.py`; hash-locked per-plan scheme; `tests/test_confidence_contract.py` | Durable admission/retention with exact approved scheme and record attribution (1); historical approved-revision snapshot and authorized assembly (6, 8). Counts/prose/rule states never replace judgments. |

## Assembly and typed hand-offs

Router owns admission and commits. Private record helpers/collaborators use
narrow core protocols and the existing fenced `commit_outcome` transaction;
slice 1 uses private methods in the existing `Assessments` collaborator and
adds no responsibility or import to `service.py`. Accounting
keeps pure arithmetic. The exporter consumes approved typed artifacts, never
queries a second research store or becomes an accounting writer.

Assembly captures one coherent snapshot of topic state, approved/historical
contracts, immutable records and artifacts, G-1 impacts, claim/receipt/quote
revisions, challenge evidence, invocation/window provenance and registry
history. A short transaction pins a snapshot token and copies the operands;
the transaction ends before calculation, serialization, hashing or spool I/O.
No successive independent inventory reads stand in for a snapshot. If the
existing Store transaction is used to capture it, measure lock duration with
representative topic/global inventories before accepting the path; prefer
topic-filtered joins in the store over reading whole unrelated tables.

Pure assembly outside the lock returns typed dossier/bundle bytes and a token
identifying all material input revisions/hashes. The Router's commit rechecks
the active approved contract, state revision, relevant input identities and
hashes, approval subject, options revision and generation under its writer
fence. Any change refuses/rebuilds; approval never follows a mutable object.
Historical contracts remain available with their original schemes, while
current G-1 standing remains a distinct operand. Missing evidence is unknown.
No /1 scalar conversion may erase uncertainty behind a satisfied bound.
Any exporter import-grant amendment needs the normal boundary review.

## Sequential slice map

Estimates include hand-written implementation, schema/DDL, tests and mutants;
generated controls are excluded. Each later brief must refine its estimate
and split again before exceeding about 500 lines. Documentation is additional.

| Slice | Dependency | Deliverable and approximate lines |
|---|---|---|
| 1 (2d-1) | Existing commit/contract approval | Durable obligation assessment/open-record admission: exact scheme/pins, Router attribution, artifact evidence, predecessor and competing histories, immutable storage; paired adversarial controls. 430 (DDL 85, schema 40, admission 90, tests 150, mutants/ledger/fixtures 65). Stop here. |
| 2 | 1 | Durable branch/window association admission and provenance-derived window pins; missing/cross-topic/forged cases. 400. |
| 3 | Existing quote/receipt schema | Byte/span verification against exact source artifact with explicit normalization; quarantine and capture-owner notification before optional NLI. 430. |
| 4 | 3 | Verifier typed re-access/extraction and tier/route/table checks, independent detailed check receipts and disagreement holds; fixture execution only. 450. |
| 5 | 3–4 | Optional tier-0 screen/alarm and audit/regression records, no promotion; bounded sampling hand-off. 350. |
| 6 | 1–4 | Coherent snapshot/read adapter and lossless rich stopping dossier persistence with actual coverage/challenge/verification gates; concurrency/workload cases. 490; split snapshot and rich representation if estimate grows. |
| 7 | 6 | Fresh scientific-review record admission, exact dossier completion candidate/approval and material-change refusal. 400. |
| 8 | 6–7 | Approved-revision /2 bundle assembly, full history/licence binding and manifest enablement; /1 compatibility and short-lock tests. 480. |
| 9 | 8 | One JSONL/file export implementation, atomic pair/identity/tombstones, truthful counts, conflicts, ambiguous outcome and resend reconciliation. 490; split connector storage from delivery orchestration if needed. |
| 10 | Existing surveillance policy | Durable feed facts, success-empty/failure/cursor/coverage/owner/retirement admission. 380. |
| 11 | 9–10 | Local served-revision freshness envelope and independent completion/delivery/currency computation. 400. |
| 12 | All | Fixture integration and finite debt/removal evidence, including unknown/stale/bound dossier → exact approval → bundle, correction/replay and dead-feed cases. 350. |

2e2 supplies attributable scientific judgments, real challenge/review execution,
polling/reopening and bounded audit scheduling. Phase 3 owns provider
qualification, additional connectors and automation; Phase 4 owns real-store
migration/canary. This dispatch exercises only new/in-memory disposable stores.

## Operator decisions

None blocks slice 1: vocabulary and per-plan confidence authority are settled
by task 2c-4. There is no built-in scale. Caller evidence and judgment are
retained without pretending they establish completion.

Before optional tier-0 enablement, the operator must select a qualified checker
and regression/sampling policy (options: leave disabled with a capability fact,
or enable a separately qualified local checker with an approved audit policy).
Recommendation: keep disabled until the policy and qualification exist.
The sources require explicit quote normalization but name no algorithm/version;
before slice 3, settle supported normalization semantics (identity bytes only,
or an explicitly versioned transform with retained input/output provenance).
Recommendation: identity bytes for the initial path, explicit transforms only
by amendment; no implementation decision is taken here.
Connector destination/options and feed cadence/ownership are operator
configuration under the approved contract, not engine defaults. Missing
configuration permits no delivery/current claim. No new blocking policy
choice is inferred for the foundational admission slice.

## Validation for 2d-1

Run admission/DDL/schema/history tests, the full router composition module,
every mutant family targeting an edited file, and the six requested gates.
Record evidence in private `evidence/2d-1/`. Do not refresh the environment
during mutants. Leave BUILD-STATE, REVIEW-LOG and DEBT-REGISTER to their owner;
this slice alone does not discharge DEBT-033 or claim authoritative assembly.

## 2d-2: durable branch/window provenance

Design against `aa0bbb1` on gen2. Extend the existing `Assessments` governed
outcome path with branch/window associations, retaining Router invocation,
operation and date attribution. A new ordered-DDL append-only table binds
each association to a same-topic registered branch, a contract-admitted
research-pass window and the recording primary commit. Caller attribution
and revision fields are forbidden; pins are read from the window's immutable
invocation and exact approved/historical contract, including its protocol.
Admission validates these subjects under the existing writer fence; equal
operation replay uses the existing receipt mechanism and conflicting records
roll back. No live database migration is involved.

A thin Router coverage-snapshot method captures the inventory, admitted
`BranchLink` operands and derived `WindowPin` operands in one existing
snapshot. View computation remains outside that transaction. Missing or
unverified provenance supplies no link or pin and stays unknown. Pure view
operands remain useful for fixtures; caller-supplied links/pins confer no
authority for dossier assembly. This supplies DEBT-032's hand-off to 2e2,
without implementing dossier completion or changing registry judgments.

Estimate: **480 hand-written lines**, including DDL/schema (85), admission
and snapshot adapter/thin wiring (95), tests (205), paired mutants (65), and
fixture/ledger integration (30); generated controls and documentation excluded.
Run literal-oracle admission, replay, raw-DDL and unknown-provenance tests,
the full composition module, every mutant family touching edited files and
the six gates. Evidence belongs in private `evidence/2d-2/`.

## 2d-3: layered quote matching (design before code)

Design against `20ffba7` on gen2; task 2d ruling 2 and V-6 govern. The
existing evidence writer accepts verification receipts but has no quote-check
admission section. SQL 03 retains immutable checks and permits adjudication
only for an NLI alarm on matched bytes. The full slice is estimated at **760
hand-written lines**: matching 150, admission/notifications 100, ordered
DDL/schema 100, tests 250, mutants/integration/metrics 160. Split before code:
**2d-3a (this dispatch), about 390 lines**, supplies the pure matcher, literal
oracles, properties and paired mutants; **2d-3b, about 370 lines**, admits its
results through the governed writer, persists diagnostics/original bytes,
notifies the capture owner and tests disposition/adjudication refusal. Stop
after 3a; 2d-3 remains incomplete until 3b is accepted.

The pure hand-off checks SHA-256 artifact identity and half-open **byte**
offsets before decoding UTF-8. It retains quote/span bytes, offsets, artifact
hash, normalized forms, rule versions and mismatch diagnostics. It accepts
no supplied match label. An exact byte match passes; otherwise normalization
is `quote-nfc-safe/2`, using [Unicode UAX #15 NFC](https://www.unicode.org/reports/tr15/)
with the runtime Unicode database version recorded. Repair-1 replaces the
lossy compatibility transform: the [W3C Character Model, §2.2.1](https://www.w3.org/TR/charmod-norm/#unicodeNormalization)
explains that compatibility decomposition can change meaning, including
superscripts and subscripts; §3.2.5.1 recommends NFC for content authors.
Our explicit safe whitelist folds whitespace runs, curly quotation marks and
U+2010–U+2015 dashes. U+2212 mathematical minus remains distinct. Only an
explicit U+00AD soft hyphen followed by a line break permits rejoining;
hard-hyphen wraps retain the hyphen. No compatibility folds remain. NFC runs
last, after every deletion and whitespace fold, so new composition (including
Hangul jamo joined across a soft wrap) is completed in the first pass. The
whitelist is closed under its own output and cannot create another soft wrap.

Repair-2 implements the conservative edit rule in
[`2d-quote-protection-20261010.md`](research/2d-quote-protection-20261010.md),
retained on every result as **`quote-protection/3`**. The earlier lexer lost
structure inside compound words and used slots too coarse to retain digit
locations. A lexical fingerprint can reject a pair but cannot establish that
an edit is safe. The accepted extra lexical layer still compares original
decoded text after safe whitelist folds, before normalized equality or
diagnostic alignment. It retains complete numeric/unit spellings (precision,
grouping, exponents, operators and symbols) and rejects changed fingerprints.

A diagnostic additionally requires all four researched checks on the safely
normalized text: (a) identical ordered protected-character skeletons with the
exact number of intervening non-protected characters; (b) every diff edit,
extended on both operands to its enclosing maximal non-whitespace lexeme,
free of protected material; (c) no insertion/deletion covering a leading
`un`, `non`, `in`, `im`, `ir`, `il` or `dis` prefix; (d) no relocated substring
touching or crossing a protected lexeme. Replacement operands participate in
move detection too. Prefix checks compare the actual enclosing operands as
well as edit offsets, so diff alignment preserving the first of repeated
prefixes (`ununiform` versus `uniform`) cannot hide prefix removal.
A shared character at distinct edit regions is already a
possible one-character move, conservatively rejected when its path includes
protected material. The skeleton omits absolute leading/trailing offsets:
ordinary text before or after an unchanged expression can still earn a hint.
Enclosing edits reject within-lexeme digit moves even when all skeleton gaps
coincide. Anything failing these checks is a plain quarantined mismatch.

**Operator interpretation, 2026-10-10:** negation/unit tokens are whole
letter-bounded words, including each part of a hyphen-joined form (`not-yet`
contains `not`). Digits, signs, operators and superscripts/subscripts are
protected at every character position. Every edit to a lexeme containing one
is protected (`5mg` versus `5µg` is a plain mismatch). Prefix edits remain
protected by (c). `uniform` versus `uniforms` remains a useful ordinary near
control: the appended `s` is not a letter-bounded unit token. Unchanged
`uniform`, `under` or `discuss` beside an edit elsewhere do not block a hint;
`discuss` versus `cuss`, `information` versus `formation`, and `image` versus
`age` are conservatively plain mismatches because a leading prefix is removed.

Similarity is Python's [difflib SequenceMatcher ratio](https://docs.python.org/3/library/difflib.html#difflib.SequenceMatcher.ratio),
`2*M/(len(a)+len(b))`, with `autojunk=False`; record both directions' minimum
to avoid order-dependent optimism and the Python implementation version.
Its matching-block rather than edit-distance semantics are adequate for
review diagnostics because **no similarity score grants support**. At >=0.98
only an ordinary-text difference receives `near_match` and normalized
character-offset differing spans; every difference still quarantines. No
dependency is added. Explicit versioned English negative tokens follow
[Cambridge English Grammar Today](https://dictionary.cambridge.org/grammar/british-grammar/negation);
SI unit/prefix symbols follow the [BIPM SI Brochure, 9th edition](https://www.bipm.org/en/publications/si-brochure),
with separately named clinical display aliases informed by
[UCUM 2.2's clinical units](https://ucum.org/ucum) (no UCUM conformance claim).
Decimal numeric tokens use
[Python Decimal's decimal/exponent grammar](https://docs.python.org/3/library/decimal.html#decimal.Decimal),
validating the decimal core and retaining spelling so changed precision does not disappear.
Repair-2 records `decimal-expression/2`, `english-negation/3` and
`si9-2022+clinical/2`. Decimal validates the grouped token's decimal core;
the complete original spelling, including grouping and powers, is the comparison
identity. Other Unicode numeric characters retain their original character.
The versioned English negative-word list and `n't` remain protected;
the other operand's vocabulary no longer changes a word's classification.
The separate local prefix-edit check replaces shared-stem inference. Named
unit display words include time units.
These lists are lexical guards, not scientific or multilingual verification.

Repair-2 retains all 66 Astra round-1/round-2 probe rows as literal operands
with their original padding, both directions, plus input and normalization
probes. The three lookalike stem removals use the amended plain verdict.
Hypothesis laws compose normalization, then insert, delete, replace and move
protected material at every generated character position, including inside
lexemes and across hard hyphens. Negation/unit packets provide explicit
letter boundaries at each position under the operator interpretation; numeric,
sign, operator and super/subscript edits need no boundaries. Every effective
move destination is exercised, with both whitespace and hyphen word boundaries;
whitespace-only relocations yielding identical independently folded operands
are equivalent typography, rather than protected-material changes. Generated
contexts include Unicode letters/numerics/punctuation/symbols/marks, whitespace,
and existing protected compounds.
A utility property combines ordinary letter
insertions/deletions/replacements with whitespace and quotation typography.
Paired mutants cover (a)–(d), skeleton gaps and the retained extra lexical
layer. A full-result near control and a separate full-result below-threshold
control prevent mutations from passing through partial assertions. The
49-character plus two-insertion fixture gives difflib exactly 0.98 while
normalized Levenshtein would be 49/51, documenting the diagnostic measure.

3b must derive the expected artifact identity from the exact work/source
version and the owner from the capturing invocation under the existing
fence; pure operands alone confer no authority. Map `match` and
`match_normalized` to SQL's `matched`, everything else to `mismatch`. Preserve
the no-byte-mismatch-adjudication rule for every supporting disposition.
Run the matcher and existing V-6 tests, full composition module, affected
mutant families and six gates; evidence belongs in private `evidence/2d-3/`.

## 2d-3b: apostrophe boundaries first (design before code)

Design against `a3a1534` on gen2. The refined full estimate is **620
hand-written lines**: DEBT-038 about 100 (recognition/version 10, literal and
generated tests 65, paired mutant/control integration 25), then governed
admission about 520 (collaborator/thin wiring 120, ordered DDL/schema 110,
Router tests 215, mutants/integration 75). Documentation and generated control
JSON are additional. Split at the task's roughly 500-line guide: **this first
part implements only DEBT-038, then stops**. V-6 admission and its end-to-end
tests remain the next part, before any authoritative use of the matcher.

The researched conservative edit rule and the operator's letter-boundary
interpretation govern. Separate protection word recognition from the extra
lexical layer's contraction grouping: apostrophes, like hyphens and other
nonletters, separate the words inspected by `material()`. Both the enclosing
edit and relocation gates use that shared recognition. Preserve normalization,
numeric skeleton/relocation rules, negative prefixes and the extra lexical
fingerprint; bump only the protection rule to **`quote-protection/4`**.
Add independently specified straight/curly apostrophe literals for negation
insertion, deletion, replacement and movement, unit/unit-word movement and
`not'early` versus `early`. Extend the existing all-position soundness law
with both apostrophe wrappers, and pair a boundary-regression mutant with an
ordinary apostrophe letter-edit control that still earns a near diagnostic.

The preserved utility law also exercises deleting an ordinary word after
`trial's`: the unchanged letter-bounded `s` is now recognized as a unit.
At an edit endpoint, exclude an adjacent lexeme when the changed fragment
starts/ends with whitespace on that side; the edit cannot join that lexeme.
Keep overlapping lexemes and non-whitespace insertion contacts protected.
This refines only endpoint contact in safe edits, leaving the numeric
skeleton, relocation algorithm and normalization unchanged. Add a literal
utility oracle and a paired mutant for that endpoint condition.

Run Astra's two boundary scripts against this working tree using evidence
copies with only their checkout binding adapted; retain original script
hashes and the adaptation. Their expectations remain independent reference
evidence. Run targeted matcher/V-6 tests, full Router composition, every
mutant family targeting an edited file and the six gates. Evidence and the
completion report belong in private `evidence/2d-3b/`; the debt register stays
with its owner, and this part does not claim governed admission is complete.

## 2d-3b2: source artifact identity before governed matching

Design against `815f9c8` on gen2, before code. V-6 and tasks 2d/2d-3b
remain binding. Inspection finds no immutable work/source-version-to-artifact
mapping: `works` records bibliographic identity; semantic assessments and
source lifecycle records retain arrays of evidence, without identifying the
source bytes. Selecting one of those references would invent provenance.

Refined estimate: **750 hand-written lines** (identity admission 310,
computed checks/DDL 160, notification and support/adjudication gates 100,
remaining Router tests and paired mutants 180). Split before implementation:
**this first part, about 310 lines**, adds a typed `source_artifacts` outcome
section, an ordered-DDL immutable association, and admission/recording in the
existing registered `EvidenceWriter`. Only contract-admitted primary work can
record an association for a topic-retrieved work and a topic-authorized,
hash-checked artifact. The association retains the actual committing
invocation/operation/time. Its key is (topic, work, source version); changed
bytes require a new source version. Equal operation replay uses the existing
receipt path; a conflicting association rolls back rather than overwriting.
No supplied attribution is accepted. Repeated equal associations may be
referenced without replacing their original capture provenance.

The next part (about 440 lines, re-estimate before code) derives the expected
hash from this association, calls `quote_matching.check_quote` outside the
writer lock, persists its complete result with commit-time binding checks,
creates an owned quote hold through existing records, and enforces every
support/adjudication consequence, including re-capture and replay. This first
part grants no quote support and does not claim V-6 matching is complete.
The quote's capture owner comes from the claim revision's producing pass and
its lease, independently of this source association's original recorder.
Tests use literal bytes and raw SQL read-back through Router commits, cover
authentication, missing/forged/cross-topic artifacts, primary authority,
immutable version identity, attribution and replay, and pair each new guard
with an accepted control. Run the targeted tests, full composition module,
every affected mutant family and the six gates; evidence goes to private
`evidence/2d-3b2/`. Stop after this first part.

## 2d-3b3: governed computation and persistence first

Design before code against `4b119be` on gen2. Flow S4 step 4 and §6.7,
BOUNDARIES.md Router/Verifier, V-6, and task 2d's operator rulings govern.
The refined estimate is **680 hand-written lines**: computed admission and
persistence 100, ordered DDL/schema 100, quarantine/notification/adjudication
consumers 110, Router and DDL tests 260, mutants/integration/metrics 110.
Split before implementation: **this part, about 440 lines**, implements
governed computation, append-only persistence and its quarantine support
fence; **the next part, about 240 lines**, completes owner notification,
NLI adjudication refusal/allowance, all disposition consumers and re-capture
tests. Stop after the first part; the whole task remains incomplete.

Use the existing registered EvidenceWriter, with thin service wiring. A
verification outcome may propose quote-check operands: recorded claim
revision, work/source version, topic-authorized source artifact reference,
half-open byte span, and quote text. The engine derives the expected hash
from the immutable source binding, authenticates the referenced bytes and
calls the accepted `quote-protection/5` matcher outside the writer lock.
The claim revision identifies the capturing pass; no supplied producer or
match label confers authority (an optional match label is ignored). This
part records NLI as `not_run`, respecting the disabled Phase-2 checker.

Ordered DDL extends `quote_checks` with a canonical JSON result containing
lossless hexadecimal original/span bytes, normalized forms, offsets, both
artifact hashes, every matcher/version identity and near-match diagnostics.
Additional columns bind the result to topic/work/source version and the
actual verification invocation/operation. Historical rows remain retained;
new governed records revalidate the immutable source and claim bindings in
the transaction. SQL compares summary columns with the computed document.
Equal-operation replay writes no second check; conflicting check IDs refuse
atomically. A new supporting receipt cannot consume a governed quarantined
check, including via `partially_supports`. No source is quarantined.

Tests use literal expected results through Router commits and raw SQL,
covering exact/normalized/near/protected outcomes, source version/hash,
topic and invocation authority, ignored labels, result persistence, replay,
conflicts, immutability and the support fence. Pair the new guards with
mutants and accepted controls. Run targeted tests, full composition,
affected mutant families and the six gates; evidence belongs in private
`evidence/2d-3b3/`. Never migrate a real store.
