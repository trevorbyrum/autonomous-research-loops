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
| V-2 truthful tiers | SQL 03 promotion and receipt-use triggers; `router/boundary.py::TIER`, receipt schema; the same verification tests. `router/verification.py`, `tests/test_verification_attention.py` route missing-content verdicts to owned holds (2d-4 part 1). | Cross-check obtained tier against access route and source/table availability; 2d-4 part 2. Consume receipts in dossier gates; 6. |
| V-3 independent checking | SQL 03 receipt role/binding triggers authenticate canonical bytes and extraction lineage; `VerificationTest` tests producer-byte reuse and rejected unvalidated extraction | Runtime re-access/validated-extraction path; 2d-4 part 2, with workflow execution in 2e2. |
| V-4 provisional / accepted support | SQL 03 `claims_accepted_support_needs_receipt` and `verification_receipts_use_matches_claim`; `router/evidence_writer.py::_promote_and_link_claims`; `VerificationTest` sampling/partial-support promotion refusals | Required receipts must also be checked over the dossier's exact claim revisions; 6. |
| V-5 disagreement | Typed `holds` in SQL 02 and outcome schema; Router writes holds; `tests/test_router_evidence.py`. `router/verification.py`, thin service/evidence-writer wiring and `tests/test_verification_attention.py` implement owned adverse-verdict holds, receipt/audit/status effects, replay and rollback (2d-4 part 1). | Runtime attention implemented. Deadline scheduling/escalation belongs to 2e2. |
| V-6 byte checks before NLI | SQL 03 `quote_checks` mismatch/alarm quarantine and receipt binding; `VerificationTest::test_nli_alarm_quarantines_the_quote`, `test_quote_check_binding` | Perform byte/span/normalization computation rather than trust supplied match labels; persist result, notify capture owner, prevent mismatch adjudication bypass; 3. |
| V-7 tier-0 optional | Receipt schema and SQL 03 prevent alarm-based promotion; existing quote/receipt tests | Optional screen adapter, audit records with denominators and sampling probabilities, false passes/alarms and regression disposition; 5. Sampling workflow in 2e2, provider qualification in Phase 3. |
| V-8 independent detailed checks | Receipt schema, SQL 03 receipt CHECKs and promotion reread of units/denominators/negation/qualifications; `VerificationTest`. Part 1's attention tests retain unsuccessful receipts' unperformed/unavailable summary labels unchanged. | Typed detailed verifier production and actual unperformed/unavailable check handling; 2d-4 part 3, with dossier consumption in 6. Code never supplies semantic judgments. |
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

## 2d-3b3-repair-1: capture-bound consumption

Design against `1c0f3f5`, before code. Estimate: about 490 hand-written lines
(collaborator 65, ordered DDL 95, Router/DDL tests 220, mutants 70,
integration/metrics 40), excluding documentation and generated controls.
F1 binding and F2 quarantine enforcement land together. Notification and
byte-mismatch adjudication refusal remain in 2d-3b3 part 2.

The existing immutable `(claim_id, revision)` is the explicit capture identity.
Its governed checks form its retained quotation evidence. Any quarantined
check blocks that capture; adding a matching check cannot clear it. Re-capture
writes a new claim revision and new checks, preserving the old revision/checks.
No check means non-quote evidence under the existing receipt rules.

A receipt consuming a governed capture must anchor its reference to one cited
span and bind topic, work/version, obtained and expected artifact hashes,
normalization and status. Each additional cited span must have its own check
with these identities, matched and unquarantined for support. Admission and
promotion use this relationship in EvidenceWriter and ordered DDL. A SQL view
of invalid receipts reuses the same relation at both SQL consumers, including
receipts recorded before checks existed. A later check also re-fences already
accepted support, as does installation of the ordered DDL over existing rows.
Quarantine remains scoped to the claim revision, not its source.
Literal Router/raw-DDL substitutions, promotion, rollback, multiple spans,
existing receipts and matching re-capture controls exercise both layers.

## 2d-3b3-repair-2: reconcile completed evidence

Round 3 of 3, brief against `9c2351f`. The capture relationship, admission
binding and promotion consumers remain as accepted in round 2. Its per-check
disposition and installation rewrite above are superseded: installation
declares schema only, and the completed commit settles affected captures.

The operation receipt precedes evidence because evidence records bind to it.
`Router._commit_in_transaction` writes the `commit_outcome` audit row last,
after `_write_evidence` has written all checks and receipts and the assessment
collaborator has returned, inside the same writer transaction. Ordered DDL 12
uses that existing row as its reconciliation boundary, bound to the operation
receipt's declared audit identity, topic and invocation. One update quarantines
only already accepted captures checked by that operation and blocked by the
completed relationship. Other dispositions and immutable evidence stay intact.
No new writer, transaction, public interface or service responsibility is added.

About 300 hand-written lines including tests and mutants. Router phase probes
verify the write ordering; literal Router/raw-DDL tests cover accepted single
and multiple-span late verification, provisional controls, mismatches, missing
and invalid receipts, whole-store changes/rollback, and operation scoping.
Retain all 22 repair mutant identities: late-check removal now drops the final
reconciliation trigger, and installation mutation now reintroduces the forbidden
DML. Pair reconciliation with valid already accepted evidence; additional
mutants cover intermediate disposition, operation scope and status scope.
Run targeted tests, full composition, affected mutant families and six gates.
Evidence belongs in private `evidence/2d-3b3-repair-2/`; owner notification and
adjudication remain in part 2.

## 2d-3b4: capture-owner attention and byte-mismatch refusal

Design before code against `43ebb5a`. Estimate: **about 450 hand-written
lines** (collaborator/thin wiring 65, ordered DDL 45, Router/raw-DDL tests
245, paired mutants/integration/metrics 95), plus documentation and generated
control JSON. This completes the remaining V-6 consequences in one slice.

Use existing `holds`, exposed by the existing status reader, for durable
attention. Each quarantined governed check creates a deterministic
`hold_quote_<check_id>` with subject `quote:<check_id>`, class `judgment`,
primary authority and remediation recovery. Resolve the capture's producer
from its immutable claim revision, then the owner from that producer's lease
(`primary:<station_id>`); retain its existing invocation deadline. Attribute
the hold to the verification commit and instant. Replay uses the existing
operation receipt and writes nothing. The hold names matching re-capture as
its remediation; the old capture/check remains quarantined. Deadline
escalation belongs to the existing workflow follow-through in 2e2.

Reject receipt adjudication whenever its byte status, referenced check or any
governed check of that capture is a mismatch, including near matches and
omitted references. Historical checks retain their original per-check binding.
Quarantines without matched bytes and an actual NLI alarm cannot be adjudicated.
Reject approved clearance decisions for byte-mismatch quote holds, and raw
updates attempting to clear them. Implement independent Router and ordered
DDL guards. Preserve explicit adjudication of matched-byte NLI alarms and
existing non-quote V-8 adjudication; no NLI checker or provider runs here.

NB2 responsibility split: the Router authenticates source bytes, invokes the
accepted matcher, constructs and persists the complete result (original and
span byte hex, normalized forms, offsets, artifact identities, status/reason,
normalization/protection/token versions and diagnostic score/differing spans).
DDL 11 checks valid JSON, expected hash, offsets, recognized status, its
agreement with the match summary, and normalization identity. Its binding
trigger checks topic/claim/source version, expected source hash, obtained
artifact authorization, verifier kind/admission, operation/contract pins and
`nli_signal = not_run`. SQL does not compute matching or validate the entire
result shape, byte hex, normalized text, protection/token identities or
diagnostic contents. SQL 03 enforces quarantine for mismatch/alarm; DDL 12
enforces capture-bound admission/support and commit reconciliation.

Raw-path boundary: DDL 12 reconciliation relies on the single Router writer
protocol: the declared `commit_outcome` audit is the last evidence boundary
inside its transaction. Arbitrary raw DML can omit that audit or write checks
after it, leaving an existing disposition unreconciled. The blocked view and
promotion fence still detect the capture; this is not a SQLite-wide deferred
constraint guarantee. Raw-DDL reconciliation tests follow the writer protocol.
Document this accepted boundary only; do not change its implementation.

## 2d-4: verification admission and owned attention (design before code)

Design against `bf866f05` on gen2. The refined estimate is **about 1,050
hand-written lines**, including tests, paired mutants and integration, with
documentation and generated controls additional. Split before code:
**part 1 (this dispatch), about 350 lines**, implements V-5 disagreement
and V-2 missing-content attention; **part 2, about 400 lines**, validates
fixture re-access/extraction lineage and obtained tiers against recorded
routes/source/table availability; **part 3, about 300 lines**, admits
attributed detailed V-8 check receipts. Re-estimate each subsequent brief.
Stop after part 1; 2d-4 remains incomplete.

Part 1 uses the existing immutable verification verdict, without adding a
second disagreement flag or computing semantic judgments. `partially_supports`
and `does_not_support` create judgment/adjudication holds;
`cannot_assess_at_required_tier` records a missing-content cause on a judgment hold.
`supports` creates none. A new registered `Verification` collaborator derives
one deterministic `hold_<sha256>` per adverse receipt (the canonical logical
hash of `{"verification_receipt_id": <id>}`, keeping the hold ID within its
existing length limit). It resolves the actual claim revision's producer and
that producer's lease: owner from producer lease (`primary:<station_id>`),
deadline from producer invocation (`deadline_at`). Creation is attributed to
the verification commit's operation and instant.
The subject names the immutable receipt. Primary adjudication is required;
missing content instead requires independent verification with the required
content. Deadline scheduling and escalation remain 2e2. Holds remain visible
in the existing status reader; no queue transition or scientific disposition
is inferred. Later supportive receipts do not clear an earlier disagreement.

The collaborator takes only narrow core protocols and writes inside the
existing writer fence. Service adds composition and thin delegation/wiring
only. Commit receipts and audit effects name every generated hold, and the
existing replay boundary prevents duplicate writes. Failed hold persistence
or a conflicting deterministic identity rolls back the entire commit. SQL 02
continues to enforce hold shape, open creation, immutable identity and
attributed clearance; SQL 03 enforces receipt identity/roles. As with the
accepted V-6 owner notification, deriving a hold from a verifier verdict is
the Router's responsibility, not a new SQLite-wide constraint. Raw-DDL tests
exercise the existing hold constraints; they do not claim automatic verdict
routing on arbitrary raw inserts.

Literal Router tests cover all four verdicts, actual capture ownership with
a different verifier station/deadline, unavailable/unperformed check labels
on unsuccessful verdicts, receipt/audit/status readback, replay, competing
receipts, collision and transaction rollback. Pair routing, ownership,
deadline, write wiring and receipt effects with accepted-path mutants.
Run targeted tests, the full composition module, every mutant family targeting
an edited file and the six gates. Evidence belongs in private `evidence/2d-4/`.
No provider calls, real-store migration or workflow execution is involved.

Inventory refinement: V-5's runtime attention lands in part 1; V-2's actual
tier/route/table admission remains part 2, beyond its missing-content cause
on a judgment hold.
V-3's canonical-byte reuse and validated extraction runtime path also remain
part 2. V-8 currently retains summary labels under SQL 03; attributed detailed
check production and unavailable/unperformed handling remain part 3. Exact
dossier consumption remains slice 6; producers/scheduling remain 2e2.

### 2d-4b: authenticate retained fixture acquisition first

Design before code against `712f2c2` on gen2. Inspection refines part 2 to
**about 850 hand-written lines**: canonical acquisition computation 110,
Router admission/wiring and extraction validation 150, ordered DDL/schema
120, Router/raw-DDL/literal tests 330, mutants/integration/metrics 140.
Documentation and generated controls are additional. Split before code:
**this first part, about 380 lines**, implements the pure canonical
acquisition validator, literal fixture oracles and paired mutants; **the next
part, about 470 lines**, integrates it with the fenced Router, durable
extraction validation, recorded tier/table checks, replay and raw-DDL tests.
Re-estimate that next part before code. Stop after this first part; 2d-4b is
incomplete until admission and its end-to-end tests land.

SQL 03 currently authenticates canonical reuse with a non-null gateway-call
reference and an artifact hash. `search_observations` retains the attempted
request, lane, invocation, attempt and capture acknowledgement, but explicitly
does not retain response bytes. SQL 10 supplies immutable source-version bytes,
without distinguishing transport content from an extraction. Gateway canonical
records also include link-only `full_text` records (Semantic Scholar), whereas
CORE can return actual `text`; neither a route name nor a media type alone
establishes full text or table availability. A caller's validation reference
likewise identifies no existing validation authority. Reusing these labels
would reproduce the provenance gap rather than enforce V-2/V-3.

The foundational pure hand-off consumes existing source/artifact/observation,
retrieval-event and work-link rows plus **retained fixture gateway response
bytes**. It rehashes those bytes, requires the recorded JSON media type, binds
the exact topic/work/source version and retrieval identity, and checks the
response's captured call, invocation and attempt against the recorded
observation. It requires that the selected lane actually retrieved that
identity and that the response contains its canonical record. It returns
immutable acquisition lineage, including the recorded lane/request type,
artifact identity and actual acquiring invocation. Producer-acquired bytes
are allowed; selected summaries and unauthenticated response shapes refuse.
No caller receipt route/tier/extractor label is an input. It performs no I/O,
semantic judgment, extraction or state write and grants no support authority.
As with the accepted pure quote matcher, only the later Router adapter can
select authenticated operands and persist admission under its writer fence.

The next part must bind retained response bytes at the trusted station capture
boundary; an observation's call reference alone cannot invent that binding.
It must distinguish actual content from links/abstracts, bind each cited table
to recorded availability, retain validated extraction input/output and verifier
attribution, and refuse invented validation references. Workflow execution
remains 2e2. Pure fixtures in this part prove structural consistency, not that
an arbitrary agent-supplied JSON document came from a gateway. No new DDL or
live gateway/provider/database access occurs in this part.

Run the new literal validators, existing V-1/V-3 tests, the full composition
module, every affected mutant family and all six gates. Evidence and
COMPLETION.md belong in private `evidence/2d-4b/`.

### 2d-4b2: trusted acquisition admission (design before code)

Re-estimate against `52655aa`: **about 1,050 hand-written lines** remain,
including independent tests and paired mutants. The earlier 470-line estimate
did not account for authenticating the attempted request at the station boundary,
durable capture operands, or isolated raw-DDL and fencing controls. Split again:
**this dispatch, about 490 lines** (adapter/protocol/wiring 150, ordered DDL 65,
Router/raw-DDL tests 190, mutants and integration 85), lands trusted fixture
acquisition admission only. **Next part, about 560 lines**, must be re-estimated
and, if necessary, split: receipt consumption and recorded content/table tiers,
then durable extraction input/output/validation attribution. Stop after this
first part; 2d-4b and the unsplit 2d-4b2 obligations remain incomplete.

The Router receives a station-owned retained-exchange reader at construction,
like its trusted spool. This is a fixture adapter seam, not agent input or a new
RPC capture command; absent a reader, admission refuses. Workflow construction
of that reader and gateway execution remain 2e2. A frozen core hand-off contains
topic, acquiring invocation, attempt, call reference, exact attempted-request
document bytes (lane/page/sent request) and exact response bytes. The Router
selects the lookup key from recorded source/event/observation/work-link rows;
the caller supplies only its capability and source/event identities. It compares
the retained request itself to the recorded observation, closing Astra's coherent
request-rehash probe. The call reference alone supplies no authentication.

An `AcquisitionAdmission` collaborator reads the operands in one snapshot,
performs retained capture lookup and the accepted pure validator outside the
writer lock, then revalidates the operands and live verifier capability, lease,
topic, cancellation and running state under the Router's existing writer fence.
Only contract-admitted verification may admit this record. The acquiring
invocation may be the producer or another acquirer; producer summaries are never
substituted for retained response bytes. Thin service wiring preserves DEBT-036.

Ordered DDL 14 stores the validated acquisition and exact retained request and
response bytes, with verifier attribution and admission time. Its natural key is
topic/work/source version/event/verifier. Equal replay preserves the original
row and audit; changed captured operands conflict and roll back. DDL binds source,
artifact, event, work link, observation request and acquiring invocation, and
contract-admitted verifier role/topic, and forbids update/delete. SQL can enforce
these recorded relationships and response size; it cannot authenticate a gateway
or compute the byte digest. Capture authentication and rehashing are Router
responsibilities, as quote computation is in the accepted quote adapter.

Literal Router controls will assert exact retained bytes and hand-written lineage,
producer-byte reuse, another acquirer, durable readback, replay, audit, cancellation
and stale-lease fencing, conflicts and rollback. Isolated negatives include absent
trusted capture, coherent request forgery, wrong capture attribution, forged source
bytes and producer summary. Raw-DDL counterparts exercise each new recorded-row
binding and append-only guard; paired mutants cover the new guards and wiring.
No receipt tier, table, extraction-validation or support authority is granted by
this admission. Existing receipt paths are unchanged until the next part makes
them consume it. Tests and evidence must not claim otherwise. Run targeted tests,
the full composition module, every affected mutant family and the six gates.
Evidence belongs in private `evidence/2d-4b2/`.

### 2d-4b3: consume canonical acquisitions first (design before code)

Re-estimate against `9f30fb6`: **about 1,050 hand-written lines** remain:
canonical receipt consumption 350, recorded content/table tiers 300, and
durable extraction validation plus extracted-receipt consumption 400.
Tests, predicate mutants and integration are included; documentation and
generated controls are additional. Split before code and stop after the
first part. The complete 2d-4b3 and unsplit 2d-4b2 remain incomplete.

**This dispatch, about 350 lines:** consume SQL 14's admitted acquisitions
on the existing `canonical_bytes` receipt path. Ordered DDL 15 adds a
consuming trigger inside the existing Router commit transaction. An acquisition
must match topic, work, source version, verifier, obtained hash, acquiring
invocation, gateway call, retrieval time and route (`gateway:` plus the
recorded lane). These existing receipt fields select the retained acquisition;
no second acquisition identity or agent-supplied admission label is added.
Producer-acquired canonical octets remain permitted. A staged artifact or
call reference alone no longer authorizes a canonical receipt. Service adds
no code: its existing evidence writer already inserts receipts under the
writer fence. SQL 14 remains the sole admission and capture authority.

The new trigger explicitly orders itself after SQL 03's artifact-existence
and non-null-call checks, preserving their established refusal diagnostics
and isolated mutant controls regardless of SQLite trigger order. It checks
each relationship independently through paired raw-DDL predicates; Router
tests use the literal trusted exchange from 2d-4b2 and assert durable receipt
readback, producer and other-acquirer reuse, rejection, replay and rollback.
Existing tests that equated staging with authenticated acquisition are
updated to assert the stronger refusal, with new accepted Router controls.
No migration is run against a real database.

**Next part, about 300 lines:** derive content tiers from admitted response
records (actual text versus abstracts or links), bind every cited table to
recorded availability, and refuse inflated claims. Route names, record kinds
and media types alone never grant content or reproduction authority.
**Following part, about 400 lines:** retain validated extraction input,
output and verifier attribution, require those records on both existing
extraction receipt paths, and bind each to its admitted acquisition. These
parts must be re-estimated before code. This first part grants no new tier,
table, extraction-validation or workflow authority; current noncanonical
receipt paths and their provenance gap remain scheduled for the extraction
part, not claimed as enforced. Workflow execution remains 2e2.

Run targeted receipt/acquisition/legacy verification tests, full Router
composition, every mutant family targeting changed files, and the eight
requested Make gates. Evidence belongs in private `evidence/2d-4b3/`.

### 2d-4b3b: recorded canonical content tiers (design before code)

Re-estimate against `7742d84`: **about 850 hand-written lines** for the
complete content/table brief, including independent Router/raw-DDL cases,
predicate mutants, fixture updates and documentation. Split before code:
**this dispatch, about 450 lines**, establishes canonical content ceilings;
**next part, about 400 lines**, needs recorded table availability and ceilings
on both extraction paths, in dependency order with durable extraction
validation (the following 2d-4b3 part). Stop after the first part. The whole
2d-4b3b brief remains incomplete; no table/extraction guarantee is claimed.

SQL 16 derives the ceiling directly from SQL 14's immutable response bytes,
selecting the record by the admitted provider-record identity, and consuming
SQL 15's acquisition operands. Its work/version selectors and SQL 14's source
binding imply the same immutable content hash; verifier identity implies topic,
so these two redundant equalities are not repeated. A record with real nonblank
`abstract` text supports abstract; a `full_text` record with real nonblank
`text` supports full text only on a recorded `searched_ok` route. A
`metadata_only` route cannot certify full text. Links, kind labels, availability
flags, media types, raw provider metadata and other records in the response
grant no content tier. Everything else supports bibliographic access only.
Canonical acquisition alone supplies no reproduction evidence, so even actual
full text refuses `reproduced`; its accepted control belongs to the durable
reproduction/extraction work, not a fabricated capture flag. The trigger applies
to every verdict, with SQL 15 retaining the missing-acquisition diagnosis.
No derived authority table, Router API, Python production change or migration
is added. Flow S4 step 8 and BOUNDARIES Router/Verifier remain the authorities.

Literal trusted Router fixtures cover the three obtainable tiers, inflation,
link-only records, metadata-only routes, unrelated records, refusal isolation,
replay/conflict and rollback. Isolated raw-DDL predicate pairs cover record
selection, content shape/nonblankness, route availability, tier ordering and
each acquisition selector, including same-response distractor acquisitions.
New mutants each have a separately accepted control. Existing canonical raw
controls declare bibliographic access, the tier their empty fixtures actually
record; their acquisition-lineage negatives remain unchanged.
Both noncanonical methods still have their pre-existing tier/provenance gap;
the next part must close it with durable acquisition/extraction consumption,
and bind every cited table to retained acquired content. Trusted workflow
execution remains 2e2. Run targeted tests, full Router composition, all affected
mutant families and the eight requested gates; evidence is `evidence/2d-4b3b/`.

### 2d-4b3b-repair-1: nonblank content and pending extraction authority

Re-estimate from `ee2c482`: about **800 lines** for the complete repair,
including extraction acquisition selectors, ceiling predicates, independent
controls and legacy fixture changes. Split: **first part, about 500 lines**,
lands R1 and R2's non-authority fence; **next part, about 300 lines**, binds
both extraction methods to admitted acquisition/content operands. Full durable
extraction/validation storage remains the following 2d-4b3 slice. Stop after
this first part; the repair and the unsplit content/table brief stay incomplete.

The named rule **recorded-nonblank/1+ucd17.0.0** requires a text field containing
at least one code point outside Unicode 17.0.0 `White_Space` and
`Default_Ignorable_Code_Point`. Sources: [PropList.txt](https://www.unicode.org/Public/17.0.0/ucd/PropList.txt)
and [DerivedCoreProperties.txt](https://www.unicode.org/Public/17.0.0/ucd/DerivedCoreProperties.txt).
Default-ignorable characters, including zero-width space, joiners, variation
selectors and formatting controls, cannot by themselves establish content.
They are preserved inside substantive text; format characters excluded from
the Unicode property remain outside the blank set. This is a presence rule,
with no minimum length or completeness/semantic guarantee. SQL 16 uses a
named pattern view containing the complete explicit Unicode code-point ranges;
the same predicate gates Router receipt insertion and direct SQL insertion.

SQL 17 fences load-bearing promotion: a qualifying receipt must be canonical
until durable extraction evidence exists. Both extraction methods may retain
their declarations, including an alleged reproduction tier, but these records
are non-authoritative. Router retention of an unbound supporting declaration
creates the existing missing-content remediation hold, bound to the producer's
owner/deadline, and never clears earlier disagreement. No caller validation
reference can lift this fence. The next acquisition/content part caps the
declarations themselves; the extraction slice may admit authority only after
recording and consuming a sufficient extraction/validation basis. Flow S4 step
8 and BOUNDARIES Router/Verifier remain the authorities; no service core code,
API, migration or workflow execution is added.

SQL 12's governed-capture consumer and EvidenceWriter also require canonical
support, so a pending receipt cannot preserve an older accepted claim against
a newly governed capture whose canonical receipt no longer binds it.
Independent Router/raw-DDL cases cover Unicode separators and ignorables,
substantive controls, both method switches, full-text/reproduction promotion,
claim/revision/sampled/adverse canonical distractors, missing-content holds, replay and
rollback. Existing support controls will use recorded canonical content while
retaining their original refusal assertions. Work/version/hash capture negatives
use pending methods to isolate capture binding from canonical acquisition guards;
their accepted controls remain admitted canonical receipts. Predicate mutants pair each guard
with a separately accepted control. Evidence: `evidence/2d-4b3b-repair-1/`.

### 2d-4b3c: extraction acquisition binding (design before code)

Re-estimate against `4eefd5c`: **about 750 hand-written lines**, including
independent Router/raw-DDL predicates, accepted controls, legacy fixture
dependencies and paired mutants. The 300-line estimate omitted the existing
extraction controls without acquisitions and capture-predicate isolation.
Split before code: **first part, about 460 lines** (ordered DDL 30, tests 180,
fixture/control repairs 140, mutants/integration 75, documentation 35), binds
both extraction methods to SQL 14 acquisitions. **Next part, about 290 lines**,
applies SQL 16's recorded-content ceiling to their declarations, with tier,
Unicode/record-selection controls and counterfactuals; re-estimate at dispatch.
Stop after the first part; 2d-4b3c and the complete repair remain incomplete.

Ordered SQL 18 adds one extraction receipt consumer, using SQL 15's work,
source-version, verifier, obtained-hash, gateway-call, retrieval-time and route
operands. SQL 14/03's verifier bindings imply topic equality. Extraction's
`produced_by_invocation_id` names the extractor, so it cannot also select the
acquirer: a verifier may extract producer-acquired bytes. Canonical receipts
retain SQL 15's existing acquirer selector. No new agent-supplied acquisition
identity, API, authority representation or production Python change is needed.
An AFTER INSERT guard preserves the existing BEFORE/row-CHECK diagnostics;
its ABORT rolls back the receipt and enclosing Router commit. This is ordered
DDL on disposable fixture stores only, never a real database migration.

New tests isolate each selector for both methods, with literal admitted raw
operands and trusted Router exchange controls, independent extraction/acquirer
identities, durable readback, replay and rollback. Legacy verification tests
receive explicit raw acquisition setup, never auto-admission inside `verify`.
Capture-only counterfactuals remove the independent acquisition consumer so
that their original capture guards remain the tested refusal. Shared fixtures
keep every-table/history/installation assertions and D28's separate-acquirer
control; sweep every family targeting edited DDL or using edited fixtures in
paired controls. SQL 17, canonical support consumers and missing-content hold
behavior stay intact. Acquisition binding alone does not cap declarations or
grant extraction/validation/reproduction authority; those guarantees remain
scheduled. Trace: flow S4 step 8; BOUNDARIES Router/Verifier; V-1/V-2/V-3.
Evidence: `evidence/2d-4b3c/`.

### 2d-4b3c2: extraction declaration content ceilings (design before code)

Re-estimate against `7c66231` (SQL 18 accepted at `7b5aaae`): **about 490
hand-written lines** (shared SQL
rule/ordered consumer 55, Router/raw-DDL tests 240, receipt-fixture repairs 70,
predicate mutants/integration 85, documentation 40). The earlier 290-line
estimate omitted the complete receipt-fixture audit and transitive mutant
controls. This dispatch completes only the declaration ceiling part of
2d-4b3c; recorded table availability and durable extraction/validation remain
later slices. Split and stop after the first part if implementation exceeds
the approximately 500-line scope.

Factor SQL 16's existing record selection, coverage and named nonblank rule
into one shared acquisition-content view. Canonical receipts retain their
existing selectors and diagnostic. Ordered SQL 19 caps both extraction
methods using SQL 18's consumed acquisition, without confusing extractor and
acquirer identities. Include the obtained-hash selector even on invalid
receipts to preserve SQL 18's diagnostic; verifier identity implies topic. Missing acquisitions
remain SQL 18's refusal. Recorded content never establishes reproduction.
No Python production/API change or real database migration is needed.

Independently isolate each inflated declaration, Unicode blank/near-blank
body, unrelated record, route and acquisition selector, with accepted literal
controls, durable readback, replay/conflict and rollback. Truthful insufficient
access still creates the existing missing-content hold. SQL 17 continues to
fence pending extraction support, including validated declarations without a
durable validation record. Audit every receipt-example/helper/raw-verify user;
repair recorded content or tier while retaining its original assertions.
Run targeted tests, full Router composition, all edited-target/shared-fixture
mutant families (including transitive imports), and the eight required Make
gates. Before each mutant run wait for no active `gen2-landing-*` user unit;
never modify those units/clones or refresh the venv during mutation runs.
Evidence: `evidence/2d-4b3c2/`.

### 2d-4b3d: recorded table availability (design before code)

Re-estimate against `0170d6e`: **about 460 hand-written lines** (ordered DDL
30, Router/raw-DDL tests 320, predicate mutants/integration 65, documentation
and fixture audit 45). This fits one dispatch; split and stop after the first
part if the implementation exceeds approximately 500 lines. SQL 14–19 remain
accepted, including the shared content rule and SQL 17 authority fence.

For this conservative slice, a substantive receipt citing any `table` locator
requires its consumed acquisition's `source_acquisition_content_tiers` rank
to be at least 3 (`full_text`). SQL 16's selected-record, coverage and
`recorded-nonblank/1+ucd17.0.0` rule is reused unchanged. This establishes
recorded content access, not the correctness of a table label or its claims;
durable extraction/validation and table identity matching remain later work.
Gateway CORE enrichment records full text in `text`. BEA `data` emits a
`series` record with a `table:bea:` identity, `rows`, `row_count`, `notes`,
`method`, `query` and opaque `raw`; its metadata listings use the same
record shape. Census similarly records `columns`/`rows`. There is no durable
binding from a receipt's arbitrary table locator value to those structured
rows, and SQL 16 grants them no full-text tier. Refuse them in this slice;
neither structured rows nor identities, locator labels, routes, kinds, media
types, links or flags alone grant table availability.

Ordered additive SQL 20 uses an AFTER INSERT guard for all three methods,
matching work, version, verifier, obtained hash, gateway call, retrieval time
and route; only canonical bytes additionally match the acquiring invocation.
Verifier identity implies topic through SQL 14/03. A missing match defers to
SQL 15/18's existing acquisition diagnostic, irrespective of trigger order.
SQL 16/19 already refuse inflated full-text/reproduction declarations. The
new guard handles lower-tier declarations, preserving those ceiling diagnostics
even when an inflated declaration also cites a table.
Every cited span is examined, including tables after non-table spans.
`cannot_assess_at_required_tier` reports unavailable content rather than
certifying it, so it is exempt from the table guard; existing acquisition and
tier ceilings still apply, and truthful lower-tier reports retain the existing
missing-content hold. No production Python/API or real migration is needed.

Independent Router/raw-DDL cases cover both insufficient tiers, all methods,
substantive verdicts, mixed spans, unrelated records/acquisitions/works,
structured rows, accepted controls, truthful missing access, readback, replay,
conflict, rollback and retained diagnostics. Each new guard has a paired
predicate mutant. Audit all receipt example/helper/raw-verify consumers,
including transitive fixtures, without weakening their original assertions.
Run targeted tests, full composition, every affected mutant family (`--only`)
after no `gen2-landing-*` user unit is active, then the eight required Make
gates. Do not refresh the venv during mutation runs. Evidence:
`/home/trevor/work/research-loops-public/private/evidence/2d-4b3d/`.

### 2d-4b3d-repair-1: unambiguous raw cited spans (design before code)

Re-estimate against `29f71bf` (reviewed code `9cece22`): **about 480 hand-written lines** (additive
DDL 65, raw/Router regression-control pairs 220, fixture repairs/audit 35,
paired predicate mutants/integration 90, design/status documentation 70).
Keep this repair in one dispatch within approximately 500 lines; split and
stop if the implementation requires a materially larger scope. Astra's full
first review and both probe files were read before this design. F1's cause
is SQL 20 depending on a discriminator whose input domain storage does not
enforce, rather than a missing special case in table detection.

Ordered additive SQL 21 establishes that domain with a BEFORE INSERT guard,
so SQL 20's AFTER INSERT availability decision sees only well-formed spans.
Reject duplicate member names throughout the **whole receipt document**,
not only its cited spans: otherwise SQL 03's column-to-document matching
can select one of conflicting top-level or nested bindings. SQL 03's exact
JSON matching carries this uniqueness to the cited-spans column. Group decoded object member names by
their actual parent identity using SQLite's JSON tree, with binary name
comparison; different objects may reuse names, and escaped spellings of the
same name are duplicates. This adopts the unique-name requirement of
[I-JSON, RFC 7493 §2.3](https://www.rfc-editor.org/rfc/rfc7493.html#section-2.3),
which defines equality after decoding escapes. [RFC 8259 §4](https://www.rfc-editor.org/rfc/rfc8259.html#section-4)
explains that duplicate-name handling varies across implementations. This
repair adopts that object constraint, not unrelated I-JSON numeric limits.

Match `verification-receipt.schema.json`'s cited-spans domain: a nonempty
array of at most 50 objects, each with exactly start/end/locator; integral
numeric offsets at the schema's minima (start >= 0, end >= 1), including
integral real JSON spellings; exactly kind/value in each locator; the six
case-sensitive enum values; and a string value of 1–500 Unicode characters
(the referenced common short_text definition). Count embedded NUL characters
as characters too. Do not add end > start, byte bounds, whitespace trimming,
nonempty substantive labels, machine-integer bounds or table identity claims.
Use guarded CASE expressions before traversing objects, so primitive span
and locator inputs are refused cleanly. Existing SQL 03 JSON/column matching
remains authoritative; SQL 14–20, their diagnostics, the shared content view,
SQL 17's pending-extraction fence and truthful insufficient-access admission
remain unchanged. No service wiring, API or real-database migration is needed.
The first DDL gate requires every JSON function to have a compatibility
probe; `json_tree` is new to the DDL. Before adding that probe, re-estimate
this repair at **about 490 hand-written lines**. Add a literal compatibility
probe for decoded names, duplicate retention and grouping by parent, extend
the existing missing-function regression, and rerun the SQLC and 1C mutant
families that target `compat.py`. The gate's decision logic stays unchanged.

Raw pairs isolate every structural predicate across all three methods,
including duplicate names inside/outside spans, escaped names, missing and
extra members, wrong container/scalar types, offsets, enum case and string
length. Each refusal checks unchanged rows, then admits a nearby valid
control in an isolated savepoint. Separate schema-valid controls demonstrate
all enum members, reordered members, repeated names in different objects,
integral real offsets, NUL/Unicode labels and unconstrained offset ordering.
Router regressions exercise schema refusals and strict duplicate parsing at
the actual boundary. Predicate mutants have separately passing controls.
Repair capture fixtures with truthful page/section locators while preserving
their capture assertions; audit every receipt example/helper/raw-verify user
and transitive fixture consumer. Update V-2's implementation note and Router
status per NB1, describe SQL 21's structural domain, and keep the outstanding
table-identity/extraction limitation. Run targeted tests, full composition,
all affected mutant families after landing units are inactive (without venv
refresh), and all eight required Make gates. Evidence:
`/home/trevor/work/research-loops-public/private/evidence/2d-4b3d-repair-1/`.

### 2d-4b3d-repair-2: decoded names and exact numeral validation (before code)

Read Astra's complete round-2 report and both reproduction files. Verified
the premise in `Store._prepare` (`gen2/store/api.py`): both receipt and
cited_spans are discovered JSON columns and every API write serializes them
through `canonical.parse_json_strict` (text input) and `canonical_bytes`.
Router `boundary.normalize` also uses these helpers. C-13 accurately states
the parser's duplicate, Unicode, non-finite, precision-loss and integer-notation
restrictions; the raw SQL route does not call that parser.

There is a material exception to the proposed numeral shortcut: integral JCS
numbers are not always bounded plain integers. On the pinned implementation,
strict parsing then JCS writes `5.0` as `5`, `9007199254740992.0` as
`9007199254740992`, and `1e30` as `1e+30`. The Store accepts these float values.
C-13's integer-notation bound applies to the parser's input, not to every
numeral the serializer can emit from a float. [RFC 8785 section 3.2.2.3 and
Appendix B](https://www.rfc-editor.org/rfc/rfc8785#section-3.2.2.3) confirm
binary64 serialization, including large integer and exponent output. No API
writer preserves a noncanonical input spelling, but that fact cannot justify
a digits-only rule or a blanket offset bound of 2^53-1. Choose the brief's
exact lexical alternative: retain schema-valid integral decimal/exponent
spellings and large integers, with no new schema maximum. Raw admission will
establish exact span integrality/minima and unambiguous decoded bindings;
it will not claim to implement the entire JCS serializer or all C-13 parser
restrictions. The Store/Router continue enforcing C-13 on their own routes.

Re-estimate from `276bf69` (working HEAD recorded in evidence): **about 490
hand-written lines**: undeployed SQL 21/name and numeral repair 95, isolated
raw/Router tests 170, compat probes/tests 35, predicate mutants and control
integration 120, documentation/evidence 70. Keep one dispatch within about
500 lines; split if materially larger. Edit undeployed SQL 21 rather than
adding a second overlapping trigger; retain its trace marker and every SQL
14–20 consumer, diagnostic, shared view, SQL 17 fence and cannot-assess path.

Before any path-dependent guard, reject U+0000 in decoded member names
through complete binary name equality and check required/allowed name sets
of the receipt objects SQL 03 reads, including optional tier0/adjudication
objects. Span/locator sets also use complete decoded names with binary
equality; valid NUL in locator values remains allowed. Retain whole-document
duplicate detection. Offset validation uses preserved numeral text from `->`:
split mantissa/exponent, remove the decimal point, and compare decimal scale
against trailing zero count. Nonzero negative numbers fail start/end minima;
zero fails end's minimum. Only the exponent is converted to INTEGER for a
scale comparison; overflow saturation preserves its ordering against the
string lengths, which SQLite bounds far below int64. No offset is converted
to REAL before validation. Pin decoded-NUL equality/detection and numeral-text
preservation on SQLite 3.45.1 in fail-closed compatibility probes.

Isolated raw pairs run across all three methods, including the split receipt,
aliases throughout bindings, rounded fractions, underflow, and late spans;
Router pairs stage literal payload bytes, then commit valid controls. New
mutants each have separate admitted controls; update existing numeric mutant
selectors while preserving their killers/control mappings. Reaudit JSON
fixtures if representations change. The legacy SQL 03 missing-key CHECK test
isolates those predicates by removing SQL 21 on its disposable connection;
full-trigger required-member refusals have separate new tests. No admitted
fixture JSON representation changes. Run targeted tests/full composition,
every edited-target or transitive fixture-dependent mutant family with --only
after landing units become inactive, and the eight required Make gates.
Evidence: `/home/trevor/work/research-loops-public/private/evidence/2d-4b3d-repair-2/`.

### 2d-4b3e: durable extraction basis (design and re-estimate; implementation stopped)

**Operator ruling encoded before implementation, 2026-10-12; dispatch
2d-4b3e1.** Trevor's ruling at the end of `tasks/2d-4b3e.md` closes the
historical open question below. The closed validation policy is
`extraction-validation/1` (stored `policy_version = 1`), with exactly two
methods: `independent_extraction` and `same_extractor_replay`. Unknown methods
or versions are refused. Independence requires a different extractor
**identity** (tool or method), not another version of the same identity, and
a contract-admitted verification invocation distinct from both the source's
recorded producer and the target extraction's extracting invocation. The
producer here is the immutable source artifact's capture invocation. The
validator has no controlling parent, matches the acquisition's verifier, and
performs its own comparison extraction from the same complete SQL 14 key.
The comparison record's extracting invocation must be the validator itself.

For `independent_extraction`, the method-success predicate is: those bound
independent relationships, authenticated output and comparison artifacts,
`outcome = succeeded`, and comparison `byte_equal` or `semantic_agreement`.
Retain the validator's own immutable extraction/output reference and a C-9
comparison-evidence artifact, alongside the comparison outcome. `byte_equal`
additionally requires equal output hashes, which establishes byte agreement;
`semantic_agreement` is an attributed validator assessment whose rationale
is retained, never store-proven semantic correctness. `disagreement` requires
`failed`; failed records remain immutable and never satisfy method success.
`same_extractor_replay` requires the same identity and version, records byte
equality or disagreement with the same retained evidence, and never satisfies
the authorizing predicate, even when its integrity outcome is `succeeded`.
The part-1 result view exposes this predicate for testing only; no receipt or
support consumer reads it. SQL 17 continues fencing every extraction receipt.

**Dispatch re-estimate before code:** about **500 handwritten lines** for
part 1 (DDL 145, typed shapes 50, collaborator 55, wiring 10, isolated
Router/raw tests 180, paired mutants 60). Documentation and generated mutation
controls are additional. Implement records only and stop; the following
receipt-consumption (~460) and SQL 17 replacement (~310) parts stay pending.
Use optional outcome arrays, with actual attribution derived from the
committing invocation, artifact authentication outside the writer lock,
and writes after the operation receipt and before existing evidence writes.
All existing receipt consumers and accepted SQL 14–21 stay unchanged. The
shared history-sweep population fixture only appends the two new record types;
its receipt operands and assertions stay unchanged. Its transitive paired
controls expand the required mutant sweep.
Evidence: `/home/trevor/work/research-loops-public/private/evidence/2d-4b3e1/`.

Design against `d7be82b3a07978942eea885b12e6c4bfd96a8311`, after reading
the named flow architecture, adjudication and methodology synthesis in full,
V-1 through V-4, C-9, BOUNDARIES Router/Verifier, the preceding 2d-4b3
designs and accepted SQL 14–21. **INCOMPLETE: design only.** The authority
settles canonical-byte reuse and recorded lineage, but does not settle which
extraction-validation methods may authorize support. The task expressly
requires stopping here when that choice is open. No implementation, schema,
fixture or invariant change accompanies this design.

**Open question and recommendation.** Does a fresh validator invocation
rerunning the producer's identical extractor/version on identical acquired
bytes and reproducing its output hash count as successful validation for
load-bearing support, or must validation independently check the extraction
with another extraction/checking procedure? What method-specific success
predicate and retained evidence establish that check? Flow S4 step 8 permits
identical *canonical* bytes; it does not approve identical extraction logic
as a sufficient validation method. Adjudication (a) K-A2 and (b) resolution 5
say independence must match the error tested: different URLs can share faulty
OCR/extraction. Methodology sections 3–4 distinguish checking, evidence origins
and analytical methods, and warn that readers of one extraction share its
omissions. None enumerates accepted validation methods or their success
criteria. The task itself calls deterministic re-extraction a candidate,
not an approved method.

Recommend an initial closed, versioned method for **independent extraction
from canonical input**, retaining the independent output and the validator's
comparison evidence. Its input must be the admitted acquisition, not the
producer's selected output; matching output hashes can establish byte agreement,
while any semantic comparison remains an attributed verifier assessment.
Recommend retaining same-extractor deterministic replay as an integrity result
without granting it support authority by itself: it can reproduce a systematic
omission. The design authority must approve the method set, its success
criteria and what makes an extraction procedure independent before these are
encoded. These recommendations are proposals, not new accepted policy.

**Re-estimate and split before code.** Conditional on that ruling, about
**1,250 hand-written implementation/test/mutant lines**, replacing the old
400-line estimate; design documentation and generated controls are additional.
The estimate now includes C-9 artifact authentication, independent raw guards,
receipt-domain compatibility, the full fixture audit and transitive mutant
controls. Split into three dependent parts, re-estimating each at dispatch:

1. **First part, about 480 lines:** durable extraction and validation records
   (ordered DDL 95, schemas 50, collaborator 95, thin wiring 10, isolated
   Router/raw record tests 175, predicate mutants 55). Keep every receipt and
   SQL 17 support consumer fenced. Stop after this first implementation part.
2. **Next part, about 460 lines:** consume those records on both receipt paths
   (ordered consumers/domain extension 65, receipt schema/examples 35,
   collaborator 45, Router/raw receipt tests 210, audited fixture repairs 65,
   mutants 40). Admission alone grants no promotion; SQL 17 remains.
3. **Following part, about 310 lines:** replace SQL 17 only with bound-basis
   consumption and adjust pending-extraction attention (DDL 35, collaborator
   25, promotion/hold/replay/rollback tests 170, mutants 50, fixture repairs 30).
   SQL 12 and EvidenceWriter's governed-capture consumers remain canonical.

If a part grows materially past approximately 500 lines, split it again before
implementation and stop after its first part. This dispatch stops before part
1 because the method ruling is absent; the entire 2d-4b3e brief stays incomplete.

**Durable records.** Add ordered SQL after 21 with `-- trace:` markers,
STRICT tables, foreign keys, unconditional update/delete refusal and no
REPLACE path. An extraction ID identifies one immutable `source_extractions`
row. Its input is the complete SQL 14 acquisition key
`(topic_id, work_id, source_version, event_id, verifier_invocation_id)`, enforced
by a composite foreign key; retain no alternative caller-supplied input hash
as acquisition authority. Record extractor identity and version separately,
the actual extracting invocation, an output artifact reference, its supported
output tier, recording operation and time. Bind the extractor invocation to
the topic and recorded execution, rather than letting a recorder impersonate
another invocation. The acquisition's acquirer and extractor may differ.

Stage output bytes in the protected topic-scoped C-9 spool. The Router
authenticates/re-hashes the artifact and checks size/media type outside the
writer lock, then commits the reference and topic authorization atomically
with the record. Raw DDL checks artifact existence, topic authorization and
reference metadata; it does not claim to recompute a hash or prove that the
named invocation actually executed the extractor. Preserve the acquisition
hash as the receipt's `obtained_content_hash`; output has its own hash.
Cap the extraction's supported tier by that exact acquisition's row in
`source_acquisition_content_tiers`. Output-content adequacy remains an
attributed assessment; the store only establishes the cap and relationships.
Valid tiers here are bibliographic, abstract and full_text. Hash reproduction
of extraction output never supplies scientific `reproduced` access, and SQL
16/19's rank-three ceiling remains in force.

An immutable `extraction_validations` row identifies the target extraction,
validator invocation, approved method and policy version, outcome, retained
method evidence (including a second extraction/output when required), recording
operation and time. Only a contract-admitted verification invocation of the
same topic, without controlling parentage, may record validation. It must be
different from the target extraction's invoking producer. It must bind the
acquisition's verifier lineage; any comparison extraction must consume that
same exact acquisition and have independent recorded attribution. Keep failed
attempts as failed records; retries get new IDs, never update the old outcome.
Schema and raw guards enforce the approved closed method/evidence shapes.
Success is the authenticated validator's method-specific recorded result,
not a store certification of semantic correctness. Unknown methods, missing
evidence and an arbitrary success label cannot substitute for its durable basis.

**Router admission and consumption.** Put validation, artifact binding and
record writes in a narrow collaborator using the existing core protocols;
`service.py` adds delegates/wiring only. Use optional typed extraction and
validation arrays in the existing outcome envelope, writing artifacts and
extractions before validations, and validations before receipts. The extracting
or validating invocation is the authenticated committing invocation; an ID in
a document cannot record work on behalf of another invocation. Authenticate
through its capability, and use the existing short writer fence to recheck
operands, live lease, pins, cancellation and pause. No transaction spans
extraction, external I/O or expensive comparison. Replaying an identical
operation and payload returns the stored commit; a different payload or
conflicting record ID is refused. Refused writes and injected faults roll back
records, artifact authorization and successful audit effects.
Fixture execution only; provider execution and scheduling remain 2e2.

Add a typed extraction-record reference to extraction receipts. Retain the
`validation_ref` wire spelling only as a typed durable validation ID consumed
by a relational guard, removing all authority from a non-null free-text value.
Use ordered additive columns/guards and a narrowly extended receipt-domain
guard for SQL 21's extraction member set; preserve every duplicate-name,
decoded-name, exact numeral, span and other object-shape predicate. Do not edit
accepted SQL 14–21 in place or rewrite historical receipts.
`verifier_extraction` must name the verifier's own extraction record.
`validated_extraction` must name a succeeded approved validation of that
specific extraction, whose validator is this verifier. Both consumers require
the exact acquisition key and its work/version/input hash/call/time/route,
extractor identity/invocation, the record's pinned extractor version and output
reference, and sufficient output tier to bind. Acquisition selectors alone
never select arbitrary output.
Apply these guards to all verdicts through the Router and raw receipt insertion;
missing, foreign, unbound or failed references abort rather than being retained
as newly accepted declarations. Preserve SQL 15/18's missing-acquisition and
SQL 16/19's inflated-tier diagnostics independently of trigger order.

**Authority and attention.** The final part replaces SQL 17's method fence
with an exact-revision qualifying receipt that consumes its immutable durable
basis. Retain SQL 03's load-bearing use, claim-required tier, substantive checks
and role separation, plus contract standing and every other promotion guard.
Historical extraction declarations without a basis remain fenced. Bound
support may stop generating a pending-extraction hold; truthful cannot-assess
still creates owned missing-content remediation, and disagreement stays
retained. Refusal of an invented reference does not fabricate a hold or commit.
Keep SQL 12's governed-capture binding and EvidenceWriter's canonical-method
checks intact: an extraction basis supplies no new quote/span domain, and
cannot preserve accepted support against an unmatched later governed capture.

**Acceptance work after the ruling.** Independently isolate Router/raw
negatives for missing IDs, each foreign relationship (topic, work, version,
event/acquisition and verifier), failed validation, extractor/validator identity,
producer self-validation, output artifact authorization/metadata and tier
inflation. Pair every guard predicate with a separately accepted nearby control.
Cover both methods at all three valid tiers, producer-acquired-byte reuse,
promotion with/without a basis, historical declarations, governed captures,
readback, equal replay, conflict and transactional rollback. Audit every receipt
schema-example loader, `receipt_document`, `verification_receipts=` and raw
`verify` helper/caller, including transitive imports; migrate positive extraction
controls to explicit durable setup without weakening their existing assertions.
Run targeted tests and full `gen2.tests.test_router_composition`, every family
targeting an edited file or sharing an edited fixture with `--only`, and the
eight task Make gates. Before each mutant run wait for no active
`gen2-landing-*` user unit, never touching units/clones or refreshing the venv
during mutation. No provider calls, live gateway, real database migration or
main merge. Evidence: `/home/trevor/work/research-loops-public/private/evidence/2d-4b3e/`.

### 2d-4b3e1-repair-1: store-wide JSON member domain (design before code; stopped)

Design against `250e2fca69a2ec499b652df29635d885d6ded102c`, after reading
Astra's full round-1 report, its artifact/member/identity/trigger-order probes
and results, the named flow/adjudication/methodology authorities, and accepted
SQL 21 with the two preceding repair designs. Trevor's 2026-10-13 ruling
requires one domain for every stored JSON column, not field-specific patches.
**INCOMPLETE: documentation only. Requirement 1's compatibility stop applies.**
No guard, generator, static check or fixture repair has been implemented.

**Write-path compatibility finding and open decision.** Duplicate decoded
names are already refused by `canonical.parse_json_strict`; Python object
writes cannot preserve duplicate dictionary keys. However, `canonical._validate`
checks Unicode validity without excluding U+0000 from keys, and JCS preserves
such names. `boundary.normalize` and `Store._prepare` both use that contract.
The Router observation command admits `request` as an open object, and
`record_observation` stores the attempted request, including its filters, not
merely a provider-approved request. `gateway_client/observe.py` explicitly
requires retention of attempted requests even when no answer exists. An
in-memory probe recorded a nested filter named `field\u0000suffix` through
the Router, then read that exact name through `Store.select`. The proposed
NUL predicate selects it. A separate direct Store insert/readback preserves
the same name in `audit_events.detail`.

There are also scientific open maps: `contract-v2` confidence-scheme labels
use `common.short_text` property names, which have length bounds but no NUL
prohibition; `source-proposal.motivation.observed_coverage` uses that same
name domain. These are admitted names under the current interface, not
duplicate-name decoder attacks. It is therefore impossible to confirm that
the existing Router and Store writers can never produce a value the proposed
domain refuses. Raw provider response objects are separately retained in BLOBs
and are not themselves a reason to guard or rewrite those bytes.

The task says: **"If any open-ended JSON object (provider metadata, for
example) could legitimately contain such a name, stop and report rather than
refusing it silently."** Stop before implementation. The open decision is
how to preserve arbitrary attempted-request data and currently admitted open
map names while making all logical JSON writes satisfy the new member domain.
Recommend an explicit, documented NUL-free logical-member admission contract,
enforced before Router hashing and Store writes, with exact original attempted
requests retained as bytes when their logical representation cannot be stored.
That requires operator approval of the interface/retention change; do not
delete, truncate, rename or escape decoded keys as an implicit repair. NUL in
string values must remain allowed. The ruling's uniqueness/NUL requirements
themselves are settled; this compatibility policy is the remaining choice.

**Proposed shared mechanism, conditional on that decision.** Generate ordered
additive SQL 23 from one checked template, with `-- trace:` markers. For each
inventoried column generate BEFORE INSERT and BEFORE UPDATE guards (SQL NULL
remains allowed only where the existing column permits it). Refuse non-NULL
invalid JSON explicitly. Feed `json_tree` a CASE-selected valid document or
JSON `null`, so malformed inputs cannot depend on trigger execution order.
For duplicates use SQL 21's accepted predicate:
`typeof(key) = 'text' GROUP BY parent, key COLLATE BINARY HAVING count(*) > 1`.
The parent is the actual tree node identity, not its JSON path; different
objects may reuse names, integer array indices are not object names, and
literal/escaped spellings of one decoded name are equal. This adopts RFC 7493
section 2.3's member-uniqueness rule without changing numeric limits.
For NUL use `typeof(key) = 'text' AND instr(CAST(key AS BLOB), x'00') > 0`;
never apply it to string values or rely on SQLite TEXT length/path truncation.
Keep validity, duplicates and NUL as separate mutant-testable predicates.

SQL 21 stays byte-unchanged, including whole-receipt uniqueness, complete
object member sets, cited-span/locator shapes, exact preserved-numeral
integrality/minima and locator-value character counting. Its uniqueness
predicate becomes logically redundant once `verification_receipts.receipt`
has the shared guard; retain it, with its existing tests and mutants. The
shared domain supplies no replacement for SQL 21's shape or numeral rules.
No receipt consumer, extraction authority or SQL 17 fence changes here.

**Complete JSON-column inventory: 36 columns in 29 tables.** Derived from
the combined ordered DDL executed only in memory, including SQL 11's ALTER,
and Store's `_json_columns` discovery; cross-checked every distinct first
operand of the DDL's `json_*` calls. All stored JSON operands have a
`json_valid(column)` declaration and are serialized by Store. Qualified
aliases refer to the columns below; tree/each `.value` operands and SQL 21
shape lists are derived values, not additional stored columns. SQL 16's
`source_acquisitions.response_bytes` remains a raw BLOB exclusion even though
its content is inspected with JSON functions. `request_bytes` is also retained
raw bytes, not a JSON column. No other DDL column is a stored JSON operand.

| Schema part | Table | JSON columns | Proposed repair part |
|---|---|---|---|
| 01 | intake_briefs | document | 2 |
| 01 | scoping_reports | document | 2 |
| 01 | source_proposals | document | 2 |
| 01 | contract_revisions | document | 2 |
| 01 | obligations | facet_ids | 2 |
| 02 | invocation_reconciliations | request | 2 |
| 02 | invocation_transitions | facts | 2 |
| 02 | operator_decisions | payload | 2 |
| 02 | operation_receipts | receipt | 2 |
| 02 | capability_facts | affected_lanes | 2 |
| 03 | search_observations | request, obligation_ids, continuation | 2 |
| 03 | screening_assessments | criterion_results | 2 |
| 03 | claim_source_links | spans | 2 |
| 03 | verification_receipts | cited_spans, acquisition, receipt | 2 |
| 03 | decision_specs | document | 2 |
| 03 | decision_receipts | answer, receipt | 2 |
| 04 | config_bundles | document | 2 |
| 04 | questions | document | 2 |
| 04 | amendment_impacts | document | 2 |
| 04 | outbox_events | expected_connectors, manifest | 2 |
| 04 | export_delivery_receipts | receipt | 2 |
| 04 | audit_events | detail | 2 |
| 05 | semantic_assessments | evidence_refs | 2 |
| 06 | source_lifecycle | evidence_refs | 2 |
| 07 | registry_dispositions | evidence_refs | 2 |
| 08 | obligation_assessments | confidence, evidence_refs | 2 |
| 11 (ALTER) | quote_checks | match_result | 1 |
| 22 | source_extractions | output_ref | 1 |
| 22 | extraction_validations | comparison_evidence_ref | 1 |

These part assignments are a proposal, not installed coverage or a live
static-check exemption. **Every one of the 36 columns remains pending** at
this documentation-only stop. Conditional part 1 would protect the two F1
fields and the fixed-shape SQL 11 result, leaving 33 named column entries
owned by `2d-4b3e1-repair-1` part 2. Part 2 must remove all pending entries.

**Proposed static check.** Extend `check_gen2_schemas.py --part ddl` to derive
the JSON-column set independently from executed schema objects and every
resolved stored `json_*` operand. Fail closed on unresolved operands or a
new JSON column absent from guarded/pending sets; compare against Store's
serialization discovery to prevent either route escaping the inventory.
Require exactly the template's INSERT and UPDATE guards per covered column
and verify committed generated SQL equals fresh tool output. A named pending
manifest records task owner and part, prints every outstanding column in
`make gen2-ddl`, and rejects stale/unknown/overlapping entries. Test the check
by adding an uncovered JSON column and by removing either event guard or
either member predicate; a generated-file match alone cannot discover a
new column omitted from the inventory. No pending list has been installed yet.

**F2 fixture design.** Build a disposable reference connection with the
requested transformed DDL. Select only objects belonging to the two extraction
tables (their tables, indexes and triggers) and the result view, in their
actual creation order from `sqlite_schema`. After seeding normal admitted
operands, drop the corresponding normal objects and install those selected
transformed objects. Do not select a physical DDL suffix. Assert the installed
SQL and trigger order match the transformed reference, including mutants;
exercise both raw classes under normal and reversed orders. Existing
mutations, requested order and cases must survive without suppression/fallback.

**Re-estimate before any code.** Conditional implementation is about **960
handwritten lines**, plus generated SQL/controls and this documentation:
part 1 about **490** (shared generator/inventory/static check 180, F2 fixture
repair/order assertions 45, isolated raw/readback/static-check tests 200,
predicate paired mutants 65); part 2 about **470** (remaining-table raw/control
fixtures and compatibility admission tests 340, paired mutants 90, final
inventory/pending removal 40). Part 1 covers the three columns named above
and stops; generated guards do not justify expanding the handwritten slice.
Re-estimate after the compatibility ruling, including any approved original
request retention change, and split further if it exceeds this guide.
For each covered table/field test literal and escaped duplicates, top-level
and nested NUL-suffixed names, accepted nearby controls, binary case distinction,
reuse of names in different parents and allowed NUL values. Refusals leave
the store unchanged and valid controls remain readable through `Store.select`.
Pair every predicate guard with its own mutant/control. Required landing
checks and transitive fixture-dependent `--only` sweeps remain mandatory
when implementation resumes.

**N1 identity boundary, effective now.** SQL 22 compares `extractor_identity`
as exact, case-sensitive caller-declared labels. It neither derives identity
from execution nor resolves aliases (case/whitespace changes are different
labels). Version-only changes under one exact identity are not independent.
Settle identity trust and canonicalization policy **before part 2 of 2d-4b3e,
receipt consumption, can grant any authority**; arbitrary unequal declarations
cannot stand in for demonstrated method independence. Same-extractor replay
remains integrity only and the result view still has no authority consumer.
Evidence: `/home/trevor/work/research-loops-public/private/evidence/2d-4b3e1-repair-1/`.

#### Continuation under the 2026-10-13 operator ruling (design before code)

Re-estimate against `7003471eba53a2caffbe7f3e11104b61e2a452d9`.
The new ruling answers the compatibility stop above: logical member names
must be NUL-free; string values may contain NUL. Incompatible attempted
requests must still count, retaining exact original bytes and their byte hash.
No rewriting of names is authorized or needed. This replaces the open policy
question, but does not claim the complete write-path rollout has landed.

Part 1 is about **495 handwritten lines**: generator/manifest/inventory and
static check 185, scoped C-13 admission 35, F2 fixture 25, raw/control/readback
and checker/write-path tests 190, paired mutants/registration 60. Generated
SQL and mutation-control entries are additional. Stop after the three columns
in the table above; do not expand coverage. Part 2 is now about **560 lines**
(attempted-request byte retention/admission 130, remaining guards and fixtures
290, paired mutants 100, final pending removal/checks 40). Re-estimate at its
dispatch; any further split must explicitly reassign the pending entries.

Implement the proposed SQL 23 template unchanged in principle: separate JSON
validity, decoded-name uniqueness by actual parent/BINARY, and BLOB-based NUL
predicates, for INSERT and UPDATE. A checked manifest names the three covered
columns and all 33 pending columns, each owned by this repair's part 2. The
checker compares generated bytes and installed trigger SQL, independently
inventories Store-serialized columns and stored operands of every DDL JSON
function, and fails on unclassified expressions/new or uncovered columns.
Derived tree/shape operands and the retained response BLOB are explicit
exclusions; suffix resolution conservatively includes every stored column
with that operand name, rather than missing an alias. SQL 21 remains unchanged:
its uniqueness becomes redundant only when its receipt is covered in part 2;
its span-shape and numeral guarantees are never replaced by this domain.

Stage write-path admission with coverage, before installing guards. Add an
explicit member-domain option to the existing canonical parser/serializer and
Router normalization, recursively checking keys before JCS serialization.
Store discovers covered JSON columns from their generated guard names and
uses that option before SQL. Router outcome payload normalization uses it
before any logical payload hashing or extraction authentication. Quote-result
names are fixed by the matcher; Store also checks its generated result. These
paths cannot produce refused names; raw artifact/provider bytes remain raw.
Other Router entry points and pending Store columns retain their current
admission until part 2 supplies attempted-request byte retention and enables
the domain everywhere, including contract confidence labels and other open
maps. Turning on a global refusal now would break the denominator guarantee.
Document this rollout accurately in C-13 and BOUNDARIES.

F2 installs only the extraction tables' schema objects and the result view
from an in-memory transformed reference, preserving creation order, mutant
SQL, and exact installed-object assertions. Required reversed-order execution
must run the existing cases successfully. Tests pair each domain predicate
with literal/escaped duplicates, top-level/nested NUL names and independent
accepted/readable controls on all three columns, including NUL string values,
binary-distinct names and different actual parents. No extraction authority
consumer changes; N1's identity trust/canonicalization prerequisite above
remains mandatory before 2d-4b3e part 2 can grant receipt authority.

**Part 1 implemented; stop here.** About 450 handwritten added lines, plus
96 generated SQL lines, 112 generated control lines and documentation.
F1's two references and the quote-result column have both event guards and
pre-serialization Router/Store refusal. F2's transformed-object fixture now
executes and asserts the requested order. Derived-value exclusions fail closed
if a new stored column shares their name; the raw-response exclusion requires
a BLOB. SQL 21/22 are unchanged. All 33 manifest entries remain owned by part 2.
Targeted/composition tests, the full trigger-order check and all eight Make
gates pass; 2,111 required mutants are killed across the broad sweep and the
corrected 16-mutant family rerun. Detailed results and first-run test corrections
are retained in the evidence directory's continuation logs and COMPLETION.md.

### 2d-4b3e1-repair-2 — complete catalog classification (design before code)

R2-1's cause is incomplete SQL tokenization and unresolved alias exclusions.
Replace the scanner entirely with the brief's **fail-closed classification of
every stored TEXT column**. SQLite parses the DDL; its catalog supplies actual
table/column/type identities. No SQL spelling determines whether a TEXT column
enters the candidate inventory.

**Research and choice.** SQLite's [compile-time authorizer](https://www.sqlite.org/c3ref/set_authorizer.html)
and [action codes](https://www.sqlite.org/c3ref/c_alter_table.html) expose resolved
column reads and functions, with the innermost view/trigger context. Python's
[sqlite3 authorizer](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.set_authorizer)
provides this without a dependency. I evaluated it seriously in an isolated
in-memory table: EXPLAIN SELECT from a JSON-consuming view reports the actual
table and column, but EXPLAIN INSERT/UPDATE on a column CHECK containing quoted,
comment-separated json_valid reports neither the function nor the CHECK read.
Callbacks also do not associate a function's arguments with individual reads.
Using their order as an operand parser would recreate the unsound mechanism.
The probe and callback output will be retained in this repair's evidence.

[SQLite table_xinfo](https://www.sqlite.org/pragma.html#pragma_table_xinfo)
includes generated and hidden columns, unlike table_info. The
[schema catalog](https://www.sqlite.org/schematab.html) retains each installed
object's SQL. Use these authoritative catalogs to classify every TEXT column,
including columns never currently consumed by a JSON function. Keep the accepted
three covered and 33 owned-pending JSON classifications. Explicitly name the
remaining **488 scalar TEXT columns** in the manifest; they are exclusions only
for the exact reviewed schema, bound to SHA-256 of a deterministic serialization
of every installed user object (type/name/table/SQL). This intentionally trades
automatic operand precision for conservative completeness. Any added, removed,
or modified object invalidates all scalar exclusions, fails the check, and
reports unclassified TEXT columns. Updating that hash requires reviewing the
whole schema's classifications; the generator must never update it implicitly.
This catches adding JSON use to an existing scalar column as well as new columns,
without depending on quoted names, comments, aliases, or function spelling.

Only the exact resolved BLOB identities source_acquisitions.request_bytes and
source_acquisitions.response_bytes are retained-byte exclusions, and each must
still have BLOB type. No other BLOB or ANY column gets an implicit exclusion.
Cross-check the Store's serialized-column set: it cannot intersect scalar or
retained-byte exclusions. The logical JSON inventory remains **36 / 3 / 33**;
the broader candidate inventory is **524 TEXT columns**. Scalar names do not
become new pending JSON columns, and part 2's ownership does not change.

Prepare [EXPLAIN](https://www.sqlite.org/lang_explain.html) INSERT, UPDATE of all
writable columns, DELETE for every table and SELECT for every view in the empty
disposable connection. This checks SQLite can resolve all trigger/view bodies
without executing writes. Any preparation failure is a check failure. CHECKs,
indexes and generated expressions are parsed by schema installation and covered
by the schema-bound exhaustive classification. No unanalysed schema receives a
passing fallback; absent classifications mean every TEXT column is uncovered.

**Re-estimate before code:** about **330 handwritten lines**: catalog/hash and
preparation checks 100, isolated regression/control and decision tests 140,
predicate mutants/registration 65, fixture classifications 23 and R2-2 diagnostics
2. The 488 explicit scalar names are generated catalog data, plus generated
mutation-control entries and this documentation. No dependency or environment
refresh is needed. This is one slice under the approximately 500-line guide.

**Pre-final hardening within the same design:** also bind classifications to
SHA-256 of the complete ordered DDL text, including statements that leave no
catalog object. Explicitly refuse attached databases and temporary user objects;
classification covers the main durable schema only. Use GLOB's literal reserved
sqlite_ prefix, since LIKE's underscore wildcard excludes legitimate user names.
Add direct paired cases/mutants for these decisions. Revised estimate **370
handwritten lines**; the catalog data and 36 / 3 / 33 split remain unchanged.

R2-2 changes only the two diagnostic literals producing thirty NUL-name
subtests. Keep their refusals, unchanged-state assertions, accepted controls and
retained spans. Validation: each of Astra's five isolated regression/control
pairs, ordinary unquoted refusal, existing-scalar new consumption, retained-BLOB
identity/type, generated columns, missing classifications, and preparation
failure; mutants target each inventory decision, independently paired with an
accepted control. Run targeted/composition tests, full gen2-test, trigger-order,
the affected/transitively fixture-dependent mutant families, and all eight
required static gates after waiting for no active gen2-landing-* units. Evidence:
/home/trevor/work/research-loops-public/private/evidence/2d-4b3e1-repair-2/.

**Implemented, 2026-10-14.** About 330 handwritten added lines, plus explicit
catalog data and generated control entries. No SQL scanner remains in operand
discovery. The 36 / 3 / 33 logical classification is unchanged; 488 scalar TEXT
exclusions require both reviewed hashes. Actual retained BLOB identities,
generated columns, literal sqlite_ prefix, temporary/attached scope, and all
preparation failures have direct decision coverage. All six original full-schema
probes now exit 1 and name the uncovered operand. The two NUL-diagnostic literals
are updated without changing any other exact-span assertions. Required validation
passes: 54 targeted/composition tests; the full 3,511-test suite (two skips);
234 triggers reversed with 2,873 identical store tests/subtests; all 855 mutants
from the six affected families killed, including 22 new separately paired
inventory mutants; all eight static Make gates. No dependency/environment
refresh or further guard rollout. Completion and full logs are in the evidence
directory above; part 2 still owns the same 33 pending columns.
