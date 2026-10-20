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

### 2d-4b3e2: registry first (design and re-estimate before code, 2026-10-14)

The two operator rulings supersede the historical identity-label policy above.
Re-estimate: **about 970 handwritten lines**, split into **part 1 about 495**
(additive registry DDL 85, registry collaborator/operator wiring 105, extraction
admission/schema/fixture compatibility 55, Router/raw/operator tests 185,
predicate mutants 65), then **part 2 about 475** for successor records and
both receipt consumers, their isolated controls and receipt-fixture migration.
Documentation and generated controls are additional. This dispatch implements
only part 1 and stops. SQL 17 replacement remains a separate following task.

Part 1 introduces empty-by-default, immutable registry snapshots with an exact
integer revision and canonical lower-case ASCII tool identities and families.
The authenticated operator command supplies operator identity; an immutable
audit event retains the reason and complete approved tool/family mapping.
Registry revisions and entries must match that audit event in raw DDL.
Revision replay is identical-content only; changes require a new increasing
revision and another audit. No outcome can write registry entries. The Router
checks exact membership, without trimming, case folding or alias resolution;
an additive nullable extraction revision column keeps historical rows readable
while every new extraction must pin a registered tool in a specific snapshot.
Snapshots never relabel old extraction records. These checks bind declarations;
actual execution identity checking remains station work in 2e2.

**Successor policy definition: extraction-validation/2.** Independence requires
all SQL 22 acquisition, verifier, producer separation and retained-artifact
bindings, plus unequal **registered families**, read using each extraction's
immutable registry revision. Different identities or versions within one
family cannot establish independence. Its closed methods are
`independent_extraction` and `same_family_replay`; both operands must have
registered tools. Same-family replay requires equal registered families and
permits only byte equality or disagreement, with no semantic-agreement result.
It is integrity only, regardless of tool identity or version within the family;
the successor must retain its independent output and comparison evidence and
must not expose replay as method success. Success additionally requires
`succeeded` with `byte_equal` (equal output hashes) or attributed
`semantic_agreement`; semantic correctness is never store-proven. Historical
`/1` remains readable and never becomes receipt/support authority. Part 1
defines this policy; it does not install `/2` validation records or consumers.
Part 2 must use additive successor records because SQL 22's immutable `/1`
table has a fixed policy CHECK; it must refuse invented, failed, same-family,
foreign and `/1`-only receipt bases in Router and raw DDL, audit every positive
extraction receipt fixture and retain all SQL 21 member/span predicates.

No new JSON columns are planned in part 1: the complete approval uses the
already classified and guarded audit-event detail. Recheck the closed JSON
inventory and repin its DDL hashes after additive SQL. Test registry authority,
canonical identities, membership, revision binding, immutable readback,
replay/conflict and atomic rollback, with predicate-level paired mutants.
Run the full test/order/composition suites, every edited-target and transitive
shared-fixture mutant family, and all eight required Make gates. Before heavy
runs wait for no active gen2-landing-* unit; disposable snapshots copy the
venv, never symlink or refresh it during mutants. No provider, live gateway,
real-database migration or main merge. Evidence:
`/home/trevor/work/research-loops-public/private/evidence/2d-4b3e2/`.

### 2d-4b3e2 continuation part 2: re-estimate before code, 2026-10-14

Registry part 1 is accepted at `23440ec`. Read the complete continuation,
both operator rulings, this dossier from §2d-4b3e onward, the named private
design authority and part-1/repair evidence. The old 475-line estimate omits
the additive successor table, its complete independently isolated raw guards,
NULL-pin history refusal, and receipt-fixture migration. Revised estimate:
**about 930 handwritten lines**, excluding documentation and generated
SQL/control/catalog data. Split again and stop after its first part:

1. **This dispatch, about 490 lines:** SQL 29 successor records/view and
   registry-family/lineage/artifact guards 105; typed outcome shape and narrow
   ExtractionRecords wiring 30; Router/raw records, historical pins, replay,
   conflict, rollback and immutable controls 235; predicate mutants and traced
   pairing/classification/scope evidence scripts 120.
2. **Next dispatch, about 440 lines:** both receipt consumers and additive
   receipt-domain extension 100; isolated Router/raw refusal and accepted
   controls 160; complete positive receipt-fixture migration 110; paired
   mutants and path traces 70. Re-estimate at dispatch. SQL 17 replacement
   remains a separate following task.

SQL 22 has a fixed `/1` CHECK and stays byte-unchanged. Install immutable
`extraction_validations_v2` and `extraction_validation_results_v2`, with the
same retained comparison/output and exact SQL 14 acquisition/validator/producer
bindings. Both operands must retain non-NULL historical registered revision
pins. As repaired by F1 below, both canonical identities must additionally be
registered under the validator extraction's pinned operator-approved revision;
resolve both families under that one comparison revision, refusing missing
common membership without inheriting older mappings. `/2` admits only
`independent_extraction` (different families) and `same_family_replay` (equal
families). Replay permits byte equality or disagreement and is integrity only,
including different identities/versions in one family. Byte equality requires
equal hashes; semantic agreement remains an attributed assessment. A failed
record never satisfies method success. Historical `/1` records stay readable;
neither result view has a receipt/support consumer in this slice.

Expose a separate optional `extraction_validations_v2` outcome array, deriving
validator attribution from the committing invocation, authenticating evidence
outside the writer lock, and writing after extractions in the existing fenced
transaction. `service.py` needs no logic change. Classify and guard the one new
JSON column under the closed member-name family in a new generated SQL part,
retaining SQL 23–28 unchanged and explicitly reviewing/repinning both hashes.

The receipt-fixture audit records every positive declaration as pending next
dispatch; no nonexistent durable receipt enforcement is claimed. BOUNDARIES
and V-3 must describe only the installed records and the still-pending
consumers. Free-text validation_ref grants no authority. **SQL 17 still fences
every extraction-based load-bearing support.** Trace each new separate control
through its changed predicate/successful SQL event, following the C1 repair.
Before committing run full gen2-test, trigger-order, full composition, all
edited-target and transitively edited-fixture mutant families with --only,
and all eight static gates. Heavy runs wait for no active gen2-landing-* unit;
snapshots copy .venv-gen2 and never refresh it during mutants. No provider,
live gen-1/8765, real migration, protected-register edit or main merge.
Evidence: private/evidence/2d-4b3e2-part2/COMPLETION.md. Overall continuation
remains INCOMPLETE at this requested first-part stop.

**Continuation first slice implemented; stop here, 2026-10-14.** SQL 29
retains immutable `/2` validation records and its result view, with independent
registered families, same-family integrity replay, both pinned operands, exact
acquisition/validator/producer lineage and retained comparison artifacts. The
existing ExtractionRecords collaborator authenticates successor evidence outside
the writer lock and writes through the existing fenced commit. SQL 30 covers
the new comparison JSON with both member-domain guards. Catalog review proves
every old object unchanged and exactly one new table, one view and eight
triggers; classification is **37 JSON / 37 covered / zero pending, 504 scalar
TEXT and three unchanged retained BLOB identities**. Both hashes were explicitly
repinned. SQL 01–28, service.py and the protected registers are byte-unchanged.

This slice adds **452 handwritten repository lines**, removing nine;
documentation and generated SQL/control/catalog data are additional. The scope
script is new; the path audit reuses the accepted C1 repair script with family
and count adaptations plus successful-view-read instrumentation. The history
fixture gains only a successor record and its append-only oracle entry; its
receipt operands and all prior assertions remain unchanged. All 3,394 old
control entries are unchanged, and 41 new pairings have individual path traces.
The receipt audit explicitly retains every positive extraction declaration's
durable-basis migration as pending next dispatch. Both receipt consumers remain
unimplemented; free-text validation_ref and `/1` confer no authority, and
**SQL 17 still fences every extraction-based load-bearing support**. This
continuation is **INCOMPLETE** at the requested first-part stop. Final validation,
probe-isolation repairs, per-ID mutant reconciliation and commit identity are
in private/evidence/2d-4b3e2-part2/COMPLETION.md.

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

### 2d-4b3e1-json2: attempted-request retention and continued domain rollout

**Design and re-estimate before code, 2026-10-14.** The accepted SQL 23
template and repair-2 exhaustive catalog classification remain the mechanism.
The operator's rulings authorize NUL-free logical member names, including
open maps, while every failed attempt remains recorded with its exact refused
request bytes and their hash. Read the two preceding repair designs, SQL 21/23,
the generator/manifest/checker, and the named flow S4 step 8, adjudication
resolution 5/K-A2 and methodology sections 3–4. Extraction authority and the
caller-declared identity prerequisite remain unchanged.

The earlier 560-line estimate undercounts retention representation, replay,
Store hash truth, client hand-off and paired coverage. Revised estimate:
**about 900 handwritten lines** plus generated SQL/control/catalog data and
documentation. **Part 1 about 490**: observation collaborator/wiring and raw
request hand-off 130 (including the existing observation admission moved out
of service.py), additive retention DDL and Store byte/hash check 55, isolated
Router/Store/raw-DDL/readback/replay/rollback tests 220, predicate mutants and
inventory/composition adjustments 85. Stop after part 1. **Part 2 about 410**:
global Router/Store admission and confidence/open-map cases 80, remaining-table
raw controls 235, paired guards and final inventory removal 95. Re-estimate
part 2 at dispatch; do not silently enlarge this part.

Part 1 adds nullable `request_bytes` BLOB and `request_bytes_hash` scalar TEXT
to search_observations through ordered additive SQL 24. Existing rows keep
NULLs. The observation command accepts the attempted-request document either
as its existing object or as exact UTF-8 JSON text. The client emits text and a
byte digest when the member domain refuses its request. The Router validates
logical requests before hashing; refused text is retained without changing a
byte, including whitespace, escape spellings and duplicate names. A typed
member-name error distinguishes this refusal from other canonical errors.
The existing request column then contains an explicit retained-byte reference
and the request-type discriminator, never a representation claiming to be the
original request. The original is wholly present in the BLOB. Only a failed,
unobserved, payload_invalid attempt with no retrieval events can use this path;
it can confer no acquisition or support authority. request_identity is its
exact byte hash on this path, and remains the existing JCS hash otherwise.
The Router and Store recompute byte hash truth; raw DDL binds the reference,
identity and failure shape but cannot establish SHA-256 truth on its own.
Replay compares the bytes too; no second attempt is created by redelivery.

Install generated INSERT and UPDATE domain guards for search_observations
request, obligation_ids and continuation only after that writer handles refused
requests and normalizes the rest with the member domain. Store preparation
already discovers covered columns and refuses them before serialization.
All 30 other pending entries are reassigned explicitly to
**2d-4b3e1-json2 part 2** in the checked manifest. This part does not claim
global admission or completion. SQL 21 is byte-unchanged: its receipt uniqueness
is **not yet redundant**, since verification_receipts.receipt remains pending;
it will be redundant when that column is covered, while its span-shape and
preserved-numeral guarantees remain necessary and unchanged.

Re-review every stored column and JSON consumer against the complete ordered
DDL and SQLite catalog after each schema change. Existing 36 JSON and 488
scalar TEXT identities remain classified; the new byte hash is scalar TEXT,
and only the exact new BLOB identity joins the retained-byte exclusions.
Explicitly update both reviewed hashes, never via the generator. Retain the
classification review and old/new hashes in evidence. Validate the new table
coverage with literal/escaped duplicate names and top-level/nested NUL names,
INSERT/UPDATE paired controls readable through Store.select, exact raw readback
and SHA-256, failed-attempt inventory, replay/conflict and rollback. Add
separately paired mutants for each new guard and retention predicate.

Before committing run full make gen2-test, trigger-order, composition, all
edited-file and transitive-fixture mutant families with --only, and all eight
requested static gates. Before heavy runs verify no gen2-landing-* unit is
active; never refresh the environment during mutants, use a real database,
call providers, touch the live gateway, or merge main. Evidence belongs in
/home/trevor/work/research-loops-public/private/evidence/2d-4b3e1-json2/.

**Part 1 implemented; stop here.** 486 handwritten added lines (33 removed),
plus 96 generated SQL lines, catalog/control data and documentation. The
observation ledger now retains refused request text as exact UTF-8 bytes and
its SHA-256; the Router returns a typed logical-request refusal alongside the
recorded attempt. Store admission checks byte hash truth. Normal request
identities remain JCS. Accounting retains these failed observations without
asserting a decoded page. The client emits the raw-text hand-off for NUL names.
Six JSON columns are covered; all thirty remaining manifest entries explicitly
belong to **2d-4b3e1-json2 part 2**. Global admission and the final rollout remain
incomplete. SQL 21 is unchanged and its receipt uniqueness is not yet redundant.
The classification review confirms 36 JSON / 6 covered / 30 pending and 489
scalar TEXT columns, with both hashes explicitly repinned. Existing positional
observation-copy fixtures now name their original columns. The disposable
upgrade proof compares all original values and both newly added NULL fields.
Validation and final commit details are retained in evidence/COMPLETION.md.
The full 3,543-test suite passes with two existing skips; 241 reversed triggers
produce identical outcomes for 2,931 store tests/subtests. All 2,621 required
mutants are killed, including the 25 new separately paired cases, after a
130-case corrected rerun. The full composition module and all eight static
gates pass (metrics checked on a committed disposable snapshot before the
gen2 commit, then on gen2). No dependency refresh, provider call, live gateway
access, real-database migration, protected-register edit or main merge occurred.

### 2d-4b3e1-json2-repair-1 part 2: F2 continuation, design before code

**Re-estimate, 2026-10-14, against bc6fffa on gen2:** about **440
handwritten lines**: Router/object hand-off and bound opaque reader 90,
schema predicates 25, isolated Router/raw-DDL/producer/denominator/replay/
authorization tests 235, paired mutants and integration 90. Generated controls,
classification data and documentation are additional. This closes F2 in the
same observation ledger; the thirty-column JSON2 rollout is a separate task.

Every newly retained member-domain refusal uses exactly
`{"retained_request":{"bytes_hash":digest,"reason":"member_name_domain"}}`.
It asserts neither a decoded request type nor a page. No duplicate document is
reparsed with last-value-wins, even to choose a descriptor. Accounting binds
the complete representation before returning a nullable request type and page;
failed/unobserved records keep coverage and all result denominators unknown.
Existing typed retained descriptors remain readable, bound and failed-only.

Before whole-command member normalization, the observation collaborator lifts
only the attempted-request object into UTF-8 text. For existing object callers,
that hand-off uses their existing JCS serialization, whose byte hash equals
their supplied logical identity; these are the exact bytes created at the
object hand-off, not a claim about an earlier wire spelling. Raw-text callers
keep their supplied text byte-for-byte. The client already emits its exact
text and byte hash; its full search-to-router hand-off receives coverage.
The envelope still passes strict member/schema admission; only a refused
attempted request gets the failed/unobserved/payload_invalid exception. Keep
byte-hash truth, capability, running state, lease, topic and transaction fences.

The SQL 03 request CHECK currently requires a known discriminator on every
row, so a descriptor without an invented type cannot satisfy it. Narrowly
extend that fresh-store definition to permit a retained marker, whose same-row
bytes, identity, exact descriptor shape and failed-only shape are independently
required by SQL 24/25. Extend SQL 24's exact shape predicate to accept both the
new opaque and existing typed descriptors. No table/column is removed, no
migration or data rewriting is supplied or run. Ordinary requests continue to
require the original closed discriminator. Re-review these two changed catalog
objects and all classifications, and explicitly repin both DDL/catalog hashes.

Tests independently assert literal bytes/hashes, one row per structural-NUL,
duplicate-discriminator and object-filter attempt, equal replay/conflict,
unknown inventory and no retrievals. Raw-DDL controls/negatives exercise opaque
shape and ordinary discriminator separately. Existing F1/F3 mutants and
controls stay relevant; add separate controls for each new predicate and
audit any changed pairing. Before committing run the full gen2-test,
trigger-order, composition, all edited-target/transitive-fixture mutant families
with --only, and the eight static gates. Evidence appends to
private/evidence/2d-4b3e1-json2-repair-1/COMPLETION.md.

**Part 2 implemented, 2026-10-14.** F2 now records structural-NUL,
duplicate-discriminator and object-filter failures in the existing ledger,
with exact hand-off bytes/hash and no invented decoded type/page. Ordinary
discriminators remain required; legacy typed descriptors remain bound and
readable. The production search-to-Router hand-off is covered with an injected
transport. There are 291 handwritten repository additions (23 removed), plus
generated classification/control data, documentation and retained evidence
scripts. Seven separately paired guards were added; all 3,221 prior control
entries remain byte-equivalent as parsed records. Six existing mutant match
expressions follow the changed predicates without changing their IDs, negative
oracles or controls. Classification remains 36 JSON / six covered / thirty
pending, 489 scalar TEXT and three unchanged BLOB exclusions, with both hashes
explicitly repinned. ML-0114 is removed because Observations no longer imports
pagination to decode a discriminator. No service.py authority was added.
Final checks and commit are recorded in evidence/COMPLETION.md. An accidental
venv clear through the disposable snapshot's symlink interrupted validation;
the environment was restored after stopping those runs, and fresh validation
supersedes them. The evidence retains the incident and unsuccessful logs.
The separate thirty-column rollout and round-2 review remain outstanding.

### 2d-4b3e1-json2-repair-1: review repair, design before code

**Design and re-estimate, 2026-10-14, against 0c1c8fb on gen2.** Read Astra's
full round-1 report and reference/storage/retention probes and controls audit.
Flow S4 step 2 and methodology §§5–6 require durable attempts and unknown
capture to remain unknown; adjudication's capture ruling gives no authority
to a decoded reference or invented page. F1 and F2 are distinct gaps in the
submitted representation/admission design. The operator's every-attempt and
exact-byte rulings remain requirements, including the currently failing cases.

Re-estimate the whole repair at **about 850 handwritten lines**, excluding
generated control/catalog data and documentation. **Part 1, this dispatch,
about 450 lines:** bidirectional representation binding and accounting 80,
ordered additive DDL 40, isolated Router/raw-DDL/readback/retrieval and accepted
controls 190, paired mutants/control audit and fixture integration 140.
This part closes F1 and repairs/audits F3. **Part 2, about 400 lines**, owns F2:
explicit opaque failed representation without a decoded discriminator, narrow
schema evolution preserving the ordinary discriminator, object/raw producer
handoff before whole-command normalization, and structural-NUL/duplicate/
object-path byte-exact denominator/replay/unknown-inventory controls and paired
mutants. Re-estimate part 2 at dispatch. Stop after part 1; the repair remains
INCOMPLETE until F2 is implemented and reviewed. The existing 30-column rollout
continues to belong to 2d-4b3e1-json2 part 2, a separate pending obligation.

Part 1 reserves the top-level retained_request member for the retained-byte
representation. Ordinary object/text requests carrying that member are refused
at Router admission. Retained rows require their own BLOB/hash pair, exact
reference member sets (no foreign observation or column), matching reference,
byte-hash and request-identity labels, and unknown/unobserved/payload_invalid/
failed shape. Install an additional SQL 25 trigger after SQL 24 so both absent
byte fields cannot bypass the binding. Keep SQL 24's
existing label/failure checks and Router/Store SHA-256 truth checks; no old
schema part is rewritten or real database migrated. Existing retrieval guards
already reject an unobserved row; add an isolated attempted retrieval assertion
and positive observed-event control. Immutable old rows are not backfilled.

A shared pure predicate in core/pagination checks the complete retained row
representation. Accounting selects opaque only from that bound representation;
a stray descriptor or byte/hash column is an explicit invalid-representation
error, never a decoded page. Positive ordinary and retained inventories and
malformed read-adapter operands exercise both directions. The retained descriptor
still carries a known request_type in part 1: this is the reviewed limitation,
not a solution to F2. No duplicate last-value-wins decoding is introduced; its
existing admission use is explicitly pending removal in repair part 2.

F3 gets a separate accepted numeric-cursor test covering 0, 1 and 2**53-1 for
both continuation outcomes. Pin that control for 2B13-cursor-beyond-the-bound
through the existing manual-control registry. Prove it reaches the integer
predicate, fails when every integer is rejected, and passes under the intended
bound-widening mutant. Audit the other reviewed re-pair (cursor-with-nul) with
a relevant premature-string-refusal counterfactual, the unchanged negative
oracle and the intended mutant; record any new re-pair in the same audit.

After DDL changes, review all JSON/scalar/retained-BLOB classifications and
consumers against the complete ordered DDL and parsed catalog; explicitly
repin both hashes and record old/new values. Counts stay 36 JSON / 6 covered /
30 pending, 489 scalar TEXT. C-13 and BOUNDARIES must disclose the remaining
F2 retention gap while describing the actual F1 binding. Before committing:
full gen2-test, trigger-order, composition, --only for every edited-target and
transitively edited-fixture family, and all eight required static gates. Wait
for no active gen2-landing-* unit before heavy runs; never alter their units or
clones, refresh the environment during mutants, call providers, touch the live
gen-1 gateway/8765, migrate real data, edit protected registers or merge main.
Evidence: /home/trevor/work/research-loops-public/private/evidence/2d-4b3e1-json2-repair-1/.

**Repair part 1 implemented; stop here, 2026-10-14.** F1 is bound in both
representations by Router reservation, additive SQL 25 and Accounting's pure
whole-row check. F3 uses the separately accepted numeric boundary control
through the existing family/manual registry. Both reviewed re-pairings have
predicate traces and premature-refusal counterfactuals; no other old control
list or in-killer/no-control guarantee changed. Seven paired guards were added.
This part adds 182 handwritten repository lines and 209 evidence-script lines;
generated control/catalog data and documentation are additional. F2 remains
unimplemented in **2d-4b3e1-json2-repair-1 part 2**, with its three disappearing
attempt families reproduced in the evidence. The separate 30-column rollout
remains owned by **2d-4b3e1-json2 part 2**. Every-attempt retention is still an
unmet requirement, not narrowed by this split.

Validation passes: full make gen2-test (3,552 tests, two existing skips),
trigger-order (242 triggers; 2,946 identical Store tests/subtests), full
composition in the final 68-test targeted run, all 2,189 required mutants from
29 edited-target/fixture-dependent families (2,176 separate controls passing;
13 retain their existing documented treatment), and all eight static gates on
a committed disposable gen2 snapshot. An initial full run failed because one
disposable child could not import rfc8785 before its assertions; the isolated
case and the fresh full run passed without dependency refresh or weakened
tests. The catalog still has 36 JSON / 6 covered / 30 pending and 489 scalar
TEXT identities; both hashes are explicitly repinned, with no old objects or
columns changed. SQL 03/21/23/24 remain byte-unchanged. Detailed logs, audits,
probe results, commit identity and the INCOMPLETE hand-off are in the named
repair evidence directory's COMPLETION.md. No provider call, live gateway or
8765 access, real migration, protected-register edit or main merge occurred.

### 2d-4b3e1-json2-repair-2: final F2 repair, design before code

**Design and re-estimate, 2026-10-14, against db85860 on gen2.** Read the
round-2 Astra report and both retention-edge probe files. F1/F3 and the SQL,
classification, C-11 and control audit remain accepted. F2's root cause is
Observations' exception partition: only MemberNameError retains bytes; an
earlier numeric or other CanonicalizationError returns before the ledger write.
Flow S4 step 2 and adjudication's event-derived denominator require durable
attempts; unknown capture never establishes zero yield. The operator's exact
bytes/every-attempt ruling applies regardless of strict-parser error order.

Re-estimate this single repair at **about 290 handwritten lines**: collaborator
and refusal-label recording 40; isolated retention/order/ordinary-admission,
authorization/hash/rollback tests and separate controls 220; predicate mutants
and existing adapter updates 30. Documentation and generated control data are
additional. No split is needed. No DDL, classification, producer or shared
fixture change is planned; SQL 24/25 and both classification pins stay intact.
The separately owned thirty-column rollout remains JSON2 part 2's obligation.

Catch every CanonicalizationError from parse_json_strict, including its
MemberNameError subclass. For a schema-valid unknown/unobserved/payload_invalid/
failed envelope with no retrieval events, retain the original UTF-8 text bytes
and their independently checked supplied byte identity, using the existing
opaque descriptor. No parser result, discriminator, page or count is inferred.
Other envelopes still refuse, and successfully parsed requests still pass all
existing logical JCS/C-13, reserved-marker, discriminator and page checks.
This trigger is exactly a failed attempt whose request is not admissible as
logical JSON for **any strict-parse reason**, including malformed syntax,
precision loss, numeric bounds, invalid Unicode, duplicate and NUL names.
Already parsed objects keep the existing JCS hand-off contract; objects that
cannot produce those bytes do not claim an unavailable original spelling.

SQL 24 fixes the descriptor's historical reason label to member_name_domain;
keep that representation/binding unchanged. Record the actual first reported
refusal class separately as a label (member_name_domain or logical_json_invalid)
in an observation_request_refused audit event, bound to observation ID,
request byte hash and invocation, in the **same guarded transaction** as the
observation. Do not decode or serialize the refused document to classify it.
Include that label in request_refusal replies. The historical descriptor reason
is a storage tag, not a claim that all retained documents failed the name rule.
The audit fires only for a newly recorded opaque attempt, never for replay or
refusal. An audit failure rolls back both records. Declare the existing audit
member in ObservationCore; service.py remains unchanged. Existing capability,
running/current-lease, hash, rollback and replay/conflict checks remain authoritative.

Tests use a new module and unchanged shared fixtures: both numeric/member
orders for oversized integers with NUL and duplicate names; precision-losing
floats with NUL and duplicates, including NUL-first/numeral-second; plain
numeric, malformed, non-finite and Unicode failures. Every retention regression
asserts exact byte readback/independent SHA-256, one denominator row, replay and
conflict, no type/page/count, unknown inventory and durable refusal label.
Separate controls admit interoperable numeric boundaries and exact floats as
logical observed/exhausted requests. Observed/exhausted invalid numeric/name
requests must still refuse atomically. Test forged capability, non-running
invocation, expired lease, wrong hash, invalid failed envelopes and audit
rollback on the newly retained general-error path. Add a predicate mutant
restricting the catch back to MemberNameError, paired with a separate retained
name-only control which reaches that catch and passes under the mutant; pair
any new audit predicates separately. Preserve existing mutation IDs/oracles/
controls and adapt only textual selectors made stale by the collaborator change.

Before committing: full make gen2-test, gen2-trigger-order, full composition,
--only for every family targeting an edited file and every control dependency
on an edited shared fixture (transitive imports included), then the eight named
static gates. Inventory/audit evidence will name the selected families and show
old controls unchanged. Heavy runs wait for no active gen2-landing-* units.
Use disposable snapshots with cp -a .venv-gen2 and touch their installed marker;
never symlink or refresh the venv during mutants. No provider/live-gen1/8765,
real migration, protected-register edit, main merge or out-of-scope search.
Evidence: private/evidence/2d-4b3e1-json2-repair-2/, ending with COMPLETION.md
and the gen2 commit hash.

**Pre-final-validation design extension, 2026-10-14.** Direct probes found
that Python's JSON integer-digit limit raises ValueError and its nesting limit
raises RecursionError rather than CanonicalizationError. These are also
strict-parse refusals, so catch ValueError (including CanonicalizationError)
and RecursionError around the strict parser only; label the non-member cases
logical_json_invalid. Add byte/denominator/replay/unknown regressions for both
limits, ordinary observed refusals and a paired predicate restricting retention
to CanonicalizationError. Re-estimate **about 320 handwritten lines**. The first
disposable full run is superseded, stopped before completion; recreate final
validation evidence after this extension without refreshing the copied venv.

**Implemented and validated, 2026-10-14.** F2 now retains exact UTF-8 bytes for
any strict-parse refusal, including the decoder's own digit/nesting limits,
without extracting a discriminator or inventing a page/count. The valid failed
shape, supplied byte hash and existing authorization/transaction fences still
apply. The first reported refusal class is an immutable same-transaction audit
label; replay creates no additional audit. Ordinary observed/exhausted logical
requests keep strict numeric/name and discriminator admission. service.py,
SQL 24/25, classification and both pins are unchanged. This repair adds 284
handwritten repository lines and removes nine, excluding documentation and
35 generated control lines. The separate thirty-column rollout remains owned
by 2d-4b3e1-json2 part 2; no broader acceptance is claimed here.

Validation: 54 focused tests; all nine original reviewer edge probes now
record exact bytes and replay; full make gen2-test passes 3,589 tests with two
existing skips; reversed creation of 242 triggers gives identical outcomes
for 2,966 Store tests/subtests; full composition passes six tests. The --only
1B,JSON2 run kills 230/230 mutants with all separate controls passing and 639
baseline tests green: it covers every one of the 199 required exact-family
members plus 31 additional prefix matches. Five paired predicates were added;
all 3,228 old control entries remain unchanged, and only the existing clock
adapter's textual selector changes, with its ID/oracles/control intact. All
eight static gates pass; final document formatting and this execution note
receive one final static run before the gen2 commit. The pre-extension aborted
full run and the pre-correction decoder-limit focused failure are retained
under evidence/superseded and are not credited as validation. The final runs
use a copied, never symlinked or refreshed venv and recorded landing-unit waits.
Evidence/COMPLETION.md records the final commit and complete execution audit.

### 2d-4b3e1-json2b: global admission and remaining guards (design before code)

**Inventory and re-estimate, 2026-10-14, against 6b5fd3c on gen2.** Read the
json2b brief, repair-1 operator rulings, every dossier section from repair-1
through json2-repair-2, accepted SQL 23–25, and the generator, exhaustive
classification, Store writers and Router collaborators. No code changed before
this inventory/design. Existing classification is 36 logical JSON columns,
six covered, thirty pending, 489 scalar TEXT columns and three exact retained
BLOB exclusions. The complete column inventory above remains applicable.

**Router entry-point inventory.** Every public document/command surface is
listed here, including reads that accept logical JSON:

| Entry points | Admission before schema/hash/write |
|---|---|
| status | Status.status, boundary.normalize |
| record_capability_probe, record_gateway_facts | Capabilities, boundary.normalize |
| admit_reaccess | Acquisitions.admit, boundary.normalize |
| activate_config_bundle | Registries.activate_config_bundle, boundary.normalize |
| record_qualification, revoke_qualification | Registries._registry_command, boundary.normalize |
| request_cancel, reconcile, invocation_status | Lifecycle, boundary.normalize |
| requeue, open_reservation, open_review, create_topic, raise_signal | Scheduling._scheduling_command, boundary.normalize |
| version_brief, open_brief, mark_brief_overdue, propose_amendment, draft_contract, close_brief | Amendments._amendment_command, boundary.normalize |
| claim, record_transition, register_works, apply_operator_decision, ack_delivery | Router, boundary.normalize |
| commit_outcome | envelope normalization before fingerprint; staged outcome normalization before logical payload admission |
| record_observation | Observations: isolate attempted object first, normalize envelope, strict-parse request; any refused exact text can use the authenticated failed-attempt ledger |

The remaining public surfaces accept scalar identifiers or no documents:
open/close, healthy, candidate_units, evidence_inventory, coverage_snapshot,
config_bundle, restore_config_bundle, is_qualified and receipt. They do not
admit caller open maps. Constructor dependencies are internal collaborators,
not logical document admission. Lifecycle's staged execution evidence also
normalizes before use. All internally generated logical JSON writes converge
on Store.insert/update through Store._prepare; insert and update prepare
all supplied values before SQL. No direct Router JSON decoder bypass was found.

**Admission design.** Enable the shared member domain by default in
boundary.normalize, retaining its typed Refusal reasons. Enforce it on every
Store JSON column independently of installed domain-trigger names, with typed
StoreWriteError before serialization/SQL. Preserve canonical's explicit optional
member-domain contract: Observations must still serialize an attempted object
as its existing JCS hand-off bytes before refusing its logical names. That path
is the already accepted exception for retaining bytes, never logical admission.
No canonical default change, provider call, bytes rewriting or retention-schema
change is needed. Contract confidence labels and source-proposal coverage maps
are now refused at whole-document admission before content hashing. NUL values,
binary-distinct names and reuse of names under distinct actual parents stay valid.

**Re-estimate and split.** The earlier 410-line estimate omits the exhaustive
entry-point oracles and the separate fixtures needed to isolate receipt/span
predicates without weakening their other guards. Re-estimate **about 810
handwritten lines** plus generated SQL/control/catalog data and documentation.
**Part 1, this dispatch, about 490:** shared admission 15; Router/all-column
Store refusal and accepted open-map/retention controls 175; eight-table raw
INSERT/UPDATE pairs/readback and selective fixture isolation 220; separately
paired mutants, inventory/owner and integration changes 80. Stop after part 1.
**Part 2 about 320:** remaining 22 columns' table-specific receipt/array/history
fixtures 240, paired mutants and final classification/pending removal 80.
Re-estimate that part at dispatch. Raw fixtures remove only named content
immutability guards for UPDATE and deletion guards to prepare INSERT templates
in disposable memory; semantic INSERT bindings and column CHECKs remain active.
Assert each fixture's installed transformed objects/order, preserving mutations
and reversed creation order. Every negative must fail atomically for the member
domain predicate and pair with a separately readable accepted record.

Part 1 covers amendment_impacts.document, audit_events.detail,
config_bundles.document, contract_revisions.document,
invocation_transitions.facts, scoping_reports.document,
screening_assessments.criterion_results and source_proposals.document.
Their writers receive global admission first; then ordered additive SQL 26
contains the existing checked template for these eight columns. Keep SQL 23–25
byte-unchanged. Extend checked generation to assign accepted six guards to
SQL 23 and these eight to SQL 26. After the DDL change re-review all catalog
classifications/JSON consumers and explicitly repin both hashes, retaining old
and new hashes in evidence. Counts become 36 / 14 covered / 22 pending, with
489 scalar TEXT and three unchanged BLOB identities. All remaining columns
must be named in the manifest, owned by **2d-4b3e1-json2b part 2**. The static
check must continue to reject missing, stale, changed or unclassified guards.

SQL 21 remains byte-unchanged: verification_receipts.receipt is still pending,
so its uniqueness is not yet redundant. Upon that column's eventual coverage
its whole-receipt uniqueness becomes redundant; its span-shape and preserved
numeral guarantees remain necessary and cannot be weakened. No extraction
receipt consumption, SQL 17 fence or identity trust policy changes here.
C-13/BOUNDARIES must distinguish completed global writer admission from the
22 explicitly pending raw-DDL columns. Validate full gen2-test, trigger-order,
composition, every edited-target and transitive-fixture --only mutant family,
and all eight required static gates, after waiting for no active landing units.
Disposable snapshots copy .venv-gen2 with cp -a and touch their installed marker;
never symlink/refresh it. Evidence: private/evidence/2d-4b3e1-json2b/COMPLETION.md.

**Part 1 implemented; stop here, 2026-10-14.** Global Router document
normalization and all 36 Store JSON writers now refuse incompatible member
names before serialization/hash admission or SQL, independently of raw guard
coverage. The accepted attempted-object/raw-text byte-retention hand-off is
unchanged. Eight columns receive both generated event guards through additive
SQL 26; the classification is 36 JSON / 14 covered / 22 pending, with 489
unchanged scalar TEXT identities and three unchanged retained BLOB identities.
Every remaining column is named and owned by **2d-4b3e1-json2b part 2** in the
manifest. SQL 21 and SQL 23–25, service.py and the protected registers are
byte-unchanged. SQL 21's uniqueness remains necessary at raw admission until
its receipt column is covered; span-shape/numeral guarantees remain intact.
No extraction authority or identity trust policy changes here.

This slice adds 344 handwritten repository lines (23 removed), plus 116
lines in the evidence scope/validation scripts: about 460 handwritten lines.
Generated SQL, control/classification data and documentation are additional.
The classification review verifies all old catalog objects and JSON consumers
are unchanged, with exactly sixteen new triggers, and records both old/new
hashes. Both reviewed hashes were explicitly repinned, never by the generator.

Validation passes on the corrected tree: 162 focused tests; full make gen2-test
with 3,647 tests and two existing skips; 258 reversed triggers with 3,094
identical Store tests/subtests; the full six-test composition module; all eight
static Make gates. The audited --only selection covers 1,067 mutants: 1,032
unchanged old-family mutants killed in the broad sweep plus the corrected
35-mutant JSON2B rerun, all separately paired. All 1,063 separate controls pass;
four pre-existing documented unpaired cases retain their accepted treatment.
All 3,233 old control records remain unchanged. Five old textual selectors
follow the new explicit/default admission flags without changing IDs, negative
oracles or controls.

The first broad sweep exposed six duplicate probes masked by a stray comma in
empty-object documents, and one stale Store-module/exception-class fixture.
Corrected probes assert json_valid=1 before every negative; the global Store
killer and control explicitly adopt the current module, including its mutant.
The corrected 35-mutant run kills every added guard; the entire corrected
full suite and trigger-order check were then rerun. Evidence retains the
unsuccessful logs and reconciles every required mutant by ID. Final document
changes receive another static run before the gen2 commit. Every heavy check
waited for no active landing units. Validation used a copied, never symlinked
or refreshed venv. No provider call, live gen-1/8765 access, real migration,
protected-register edit or main merge occurred. Overall rollout remains
**INCOMPLETE** at this requested first-part stop. Final commit and complete
logs/audits: private/evidence/2d-4b3e1-json2b/COMPLETION.md.

**Continuation part 2 re-estimate before code, 2026-10-14, against 90e7e69.**
Part 1 at a28c7e2 is accepted. Read the complete continuation brief and the
part-1 completion, classification review and validation/scope evidence. The
remaining obligation is exactly the manifest's 22 pending columns. Estimate
**about 420 handwritten lines**: table/array/receipt-specific raw-DDL fixtures
and independent inventory assertions 240; paired predicate mutants and registry
wiring 55; generator partitioning 15; evidence classification/writer/scope and
validation scripts 110. Generated SQL/control/manifest data and documentation
are additional, as in the accepted first part. This dispatch should fit one
part below the approximately 500-line split; stop after this part. If fixture
isolation exceeds that budget, leave every uncovered column explicitly named
and owned by the next part of this task, and report the remaining obligation.

Install ordered additive **SQL 27**, retaining SQL 23–26 byte-for-byte. Partition
checked generation into the accepted six SQL-23 columns, accepted eight SQL-26
columns, and the final 22 SQL-27 columns. Before adding DDL verify every column
is recognized by Store._json_columns and every production writer converges on
Store.insert/update and its unconditional member-domain preparation; retain
the per-column writer/admission review in evidence. No writer logic change is
expected. Raw fixtures must keep semantic INSERT bindings and column CHECKs,
remove only explicitly named immutable/deletion fences in disposable memory,
retain mutant/reversed trigger definitions, and read accepted records through
Store.select. Object-valued, array-valued, nullable and mirrored receipt fields
need probes that preserve their existing shapes/bindings. Literal/escaped
duplicates and top-level/nested NUL names each get atomic refusals and valid
controls. Pair each new INSERT/UPDATE duplicate/NUL predicate separately.

After SQL 27, review all catalog objects and JSON consumers, record the exact
44 added triggers and unchanged tables/scalar/BLOB classifications, then
explicitly repin both schema and DDL hashes. Final classification must be
36 JSON / 36 covered / zero pending, 489 scalar TEXT and three retained BLOB
identities. SQL 21 remains byte-unchanged: its receipt uniqueness predicate is
then redundant under whole-receipt member-domain admission; its span-shape and
preserved-numeral guarantees remain necessary. C-13 and BOUNDARIES must state
the completed rollout. Run the full test and trigger-order suites, composition,
all edited-target/transitive-fixture --only mutant families, and eight static
gates on a disposable snapshot with a copied .venv-gen2, after each heavy-run
landing-unit preflight. Evidence goes to
private/evidence/2d-4b3e1-json2b-part2/COMPLETION.md. No provider, real database,
live gen-1 gateway, protected register, or main merge is in scope.

**Fixture isolation refinement, before validation.** Retain all production
DDL unchanged. In disposable raw-predicate fixtures, additionally remove only
the explicitly named overlapping receipt span-domain, facet/document binding,
and question/bundle binding triggers, and sibling domain guards for mirrored
receipt/manifest fields. These existing rules otherwise mask the single-column
mutant (closed shapes refuse extra object names; facets normally admit strings).
Column CHECKs and every other semantic INSERT guard remain installed, with
exact transformed trigger/order assertions. These fixtures establish the new
member-name predicates, not full receipt/facet admissibility. The full unchanged
span/receipt/facet suites still check production shape, numeral and binding
guarantees. Select a rating-approval payload rather than a nullable non-rating
decision, and an awaiting-confirmation brief rather than a decided insertion.

The first baseline also exposed existing SQL-21 fixtures whose specific
duplicate/NUL diagnostics were masked by the newly redundant SQL-27 guards.
Their shared SpanDDLTest setup now explicitly removes only the two SQL-27
receipt/cited-span INSERT guards in disposable memory, asserting exact remaining
definitions/order; SQL 21 and all its shape/numeral assertions remain intact.
Its transitive paired-control users are added to the required family sweep.
The control-registration tool remains at its accepted 1,500-line limit by
extending the existing registration statement, without adding physical lines.

**Continuation part 2 complete; stop here, 2026-10-14.** Ordered additive
SQL 27 installs all 44 remaining INSERT/UPDATE guards, generated by the checked
SQL-23 template. All 22 named columns across 17 tables are covered; the manifest
now has **36 JSON / 36 covered / zero pending**, with 489 unchanged scalar TEXT
identities and three unchanged retained BLOB identities. Each writer/column was
reviewed against the already accepted Store admission before the new guards;
decision_specs has no current production writer and remains subject to the
same Store preparation contract. The replayable catalog review proves every
old object unchanged and exactly 44 new triggers. Both schema and DDL hashes
were explicitly repinned after this one DDL change, independently of generation.
SQL 21 and SQL 23–26, service.py and the protected registers are byte-unchanged.
SQL 21's whole-receipt uniqueness predicate is now redundant and retained;
its span-shape and preserved-numeral guarantees remain necessary and unchanged.
C-13 and BOUNDARIES state the completed rollout. No pending part remains.

This part adds 234 handwritten repository lines (three removed), plus 158
durable evidence-script lines: **392 handwritten lines**, below the split
budget. Generated SQL/control/classification data and documentation are counted
separately, as in accepted part 1. Existing 3,268 control records are unchanged;
89 new separately paired mutants cover all 88 event/name predicates and the
final generated-output comparison. Raw fixtures explicitly isolate mirrored
and closed domains while preserving target definitions/order and all column
CHECKs. The old SQL-21 fixtures isolate its retained predicates from redundant
SQL-27 guards, without weakening their assertions or production DDL.

Final validation: 340 focused tests; full make gen2-test with **3,781 tests
and two existing skips**; **302 reversed triggers / 3,447 identical Store
tests and subtests**; all six composition tests; **369/369 selected mutants
killed with all 369 separate paired controls passing**, including both
transitive span-fixture families; all eight static gates on the corrected
snapshot and gen2. Initial fixture/size failures and the interrupted initial
full run remain in evidence and are not credited. Final documentation receives
another static check before commit. Disposable validation copied .venv-gen2;
it was never symlinked or refreshed during mutants. Every heavy-run preflight
waited for no active gen2-landing-* unit. No provider call, live gen-1/8765
access, real migration, protected-register edit or main merge occurred.
Commit and complete audits/logs:
private/evidence/2d-4b3e1-json2b-part2/COMPLETION.md.


### 2d-4b3e2-p2-repair-1: F1 design and re-estimate before code, 2026-10-15

Design against HEAD `1696d49` (reviewed code `0cfb573`) on gen2, after
reading the repair dispatch, Astra's review and all three family-probes files,
both operator rulings, and the named flow/adjudication/methodology passages.
The defect is comparison of family labels under two different interpretations:
a rename can make unchanged tools appear independent. Unequal identities alone
would leave Astra's two-tool reproduction open.

**Choose (a), one common approved comparison interpretation.** Keep each
extraction's historical registry pin and its existing membership guard. For
validation, resolve **both canonical tool identities under the validator
extraction's pinned registry revision**. Both must be registered there; absence
of either, a NULL historical pin, or an unresolved operand refuses admission.
The registry's immutable `(revision, identity)` key makes the interpretation
unique, and authenticated audited operator registration remains its sole source.
Compare the two families from that one revision: unequal for independent
extraction, equal for integrity-only same-family replay. No labels from separate
revisions are compared. Thus the same identity, or two tools renamed together,
cannot acquire independence by mixing extraction pins. The comparison revision
is recoverable from the immutable validator extraction; no caller-selected
revision, new column, or new JSON is needed. An approved registry can describe
new relationships, but admission always requires a coherent classification of
both tools in the selected revision; a partial snapshot never inherits mappings.

This approach uses the existing operator-approved versioned registry directly.
Stable family lineage (b) would require new family identifiers, transition
semantics and operator tooling beyond F1; that expansion is unnecessary for a
single common interpretation. Later registry updates cannot reinterpret a
retained validation because its validator extraction pin is immutable.

**DDL choice:** edit undeployed SQL 29 in its existing ordered additive slot.
Add a narrowly scoped common-membership refusal and change the method guard's
target-tool join to the common revision. SQL 01–28 and generated SQL 30 remain
unchanged. Explicitly repin the ordered-DDL hash after reviewing the unchanged
column classification; both hashes change because the catalog hash includes trigger SQL as well
as columns; the exhaustive column identities and classifications stay unchanged. Never apply DDL to a real database.

**Re-estimate: about 245 handwritten lines:** SQL guards/comments 20; isolated
Router/raw refusals for both reproductions and absent common membership, stable
same/cross-revision accepted controls and replay checks 110; predicate mutants
25; retained scope/catalog/control-path audit scripts 90. Documentation and
generated control/hash records are additional. This fits one repair slice below
500 lines; both receipt consumers, their fixture migration and SQL 17 replacement
remain later work. Semantic agreement remains attributed assessment, and SQL 17
continues to fence every extraction-based load-bearing support.

Before commit run full gen2-test, trigger-order, the full composition module,
--only for every edited-target and transitive edited-fixture mutant family,
and the eight required static gates. Trace each new paired control through a
successful guard/table event and result-view read. Heavy runs must first wait
for no active gen2-landing-* user unit. Disposable snapshots copy .venv-gen2
with cp -a and touch .gen2-installed; never symlink or refresh during mutants.
Evidence: private/evidence/2d-4b3e2-p2-repair-1/. No providers, live gen-1/8765,
real migrations, protected-register edits or main merge.


**F1 implementation, 2026-10-15.** Undeployed SQL 29 now refuses a target
identity missing from the validator extraction's comparison revision, and the
method guard resolves both tool families under that same revision. The original
registered guard still checks both historical memberships. The two rename
reproductions refuse independently through Router and raw DDL; stable different
families accept with equal or unequal extraction pins. Renamed one-/two-tool
families accept only as integrity replay. Ambiguous common membership refuses
for both methods. Historical pins are read back unchanged.

The new common guard redundantly refuses a NULL validator pin. A separate raw
fixture removes only that guard to isolate the old registered-validator-pin
predicate for its existing mutant; the production-path historical-pin tests keep
all guards. No rename or missing-common-membership test removes a guard.
Eight new predicate mutants cover all four common-membership relationships,
both method-side revision interpretations and both tool identity joins.
All 49 successor pairings have separate passing controls with retained successful
SQL event/view-read or Python line/arc traces. All 3,435 previous control entries
are unchanged.

The replayable catalog audit finds one changed method trigger and one added
membership trigger, from 394 to 395 objects, with every column unchanged.
Classification stays 37 JSON / 37 covered / zero pending and 504 scalar TEXT;
SQL 01–28, SQL 30, service.py and the protected registers are byte-unchanged.
Both catalog and ordered-DDL hashes are explicitly repinned, because the catalog
hash also includes trigger SQL. The repair adds 96 handwritten repository lines
and retains 338 evidence-script lines (including the reused control auditor and
reviewer probe), conservatively **434 lines**, below the split budget. Docs and
generated control/hash data are additional. Both receipt consumers and their
fixture migration remain pending; SQL 17 still fences extraction-based support.


**F1 repair validation complete, 2026-10-15.** Full gen2-test passes **3,976
tests with two existing skips**. Trigger-order passes with **319 reversed
triggers / 3,708 identical Store tests and subtests**. The full composition
module passes. Exact ordered-DDL source resolution and transitive fixture
imports require 50 mutant IDs; their complete two families select **106/106
killed, all 106 separate controls passing**, with a green 957-test Store
baseline. All 49 successor control traces qualify. The twelve retained reviewer
probes produce the repaired matrix; its old partial cross-revision control now
refuses missing common membership, while the complete stable cross-revision
controls accept on both paths. All eight static gates pass, with another check
of the final documentation before commit. The tested code and copied venv bytes
are verified unchanged throughout validation. Every heavy-run preflight finds
no active gen2-landing-* unit; no venv refresh, provider, live gen-1/8765 access,
real migration, protected-register edit or main merge occurred. F1 repair is
**COMPLETE**; the already documented later receipt/SQL-17 work is unchanged.
Commit and final evidence: private/evidence/2d-4b3e2-p2-repair-1/COMPLETION.md.

### 2d-4b3e2 part 2 slice 2: design and re-estimate before code, 2026-10-15

Against `fddac16` (accepted code `50cff2e`) on gen2, read the complete dispatch, all three operator
rulings, this dossier from §2d-4b3e onward, slice-1 and F1 repair evidence,
and the named flow/adjudication/methodology authority. The latest ruling
supersedes the repair's older-comparison acceptance for **new** validations.
The existing common interpretation remains the validator extraction's pin,
but admission must now require that pin to equal the current registry revision.

Re-estimate **about 900 handwritten lines**, including retained evidence scripts,
excluding documentation and generated control/hash data. Split at the policy
dependency and stop after the first part:

1. **This dispatch, about 480 lines:** additive latest-revision DDL and fenced
   ExtractionRecords admission 35; isolated Router/raw stale/current, merge,
   history/replay/conflict, same-outcome and rollback/race controls 190;
   predicate mutants, fixture isolation and registration 55; retained catalog,
   transitive scope, trace and validation evidence scripts 200.
2. **Next part, about 420 lines:** both durable receipt consumers and receipt
   domain/schema extension 100; isolated invalid-basis and accepted Router/raw
   controls 150; positive receipt-fixture migration 100; paired mutants/traces
   70. Re-estimate that part at dispatch. SQL 17 replacement remains separate.

Install ordered additive SQL 31; leave SQL 01–30 unchanged. Its INSERT guard
requires the validator extraction to exist and pin `max(registry_version)`
from the immutable operator registry. In ExtractionRecords, check the same
relationship inside the existing writer transaction immediately before each
successor insert, after any extractions in the outcome have been retained.
No snapshot read during artifact authentication can substitute for this check:
an operator merge between authentication and the writer fence takes effect.
The existing common-membership and family guards still refuse a newly pinned
same-family independent validation. Integrity-only and failed /2 attempts also
require the current revision; /1 admission is unchanged.

Retained validations continue reading the immutable validator extraction pin,
without joining current registry state. Identical operation replay remains a
read of the committed result after a registry update; a new validation ID or
operation must pass current admission. Test merges with stale historically
independent tools, current same-family refusal/integrity acceptance, and a
current genuinely independent control. Keep a separate historical-readback
control and transactional rollback assertion. Add predicate-level paired
mutants with successful SQL/Python control traces, preserving prior pairings.

No new column or JSON consumer is planned. Re-review the complete catalog and
unchanged classifications, explicitly repinning both DDL/catalog hashes.
BOUNDARIES and V-3 must name the current-at-admission rule and history exception.
Both receipt consumers and their fixture migration remain pending at this split;
free-text validation_ref and /1 provide no authority, and SQL 17 still fences
every extraction-based load-bearing support. Run full gen2-test, trigger-order,
composition, all edited-target/transitive-fixture mutant families with --only,
and all eight static gates after landing-unit idle preflights. Use a copied
.venv-gen2 in disposable evidence snapshots, never symlink or refresh it.
Evidence: private/evidence/2d-4b3e2-part2-s2/COMPLETION.md. No providers, live
gen-1/8765, real database migration, protected-register edits or main merge.

**First part implemented; stop here, 2026-10-15.** Additive SQL 31 and
ExtractionRecords independently require the validator extraction to pin the
highest admitted operator registry revision for every new /2 record, including
failed and integrity-only attempts. The Router checks within its existing
writer transaction, after same-outcome extractions; an operator update after
artifact authentication is observed. Historical target pins remain valid when
both identities exist in the current comparison registry. Retained validations
and their result-view interpretation are unchanged by later operator merges;
identical-operation replay remains readable, while new stale bases refuse.

Seven predicate mutants cover raw and Router selection, latest aggregation,
pin equality and Router dispatch, with separate accepted controls and path
traces. The formerly accepted older-comparison case now refuses atomically.
Only explicitly named in-memory predicate-isolation fixtures remove overlapping
guards. The catalog audit proves one added trigger, unchanged old objects and
columns, 37 JSON / 37 covered / zero pending and 504 scalar TEXT; both reviewed
hashes are repinned. SQL 01–30, service.py and the protected registers stay
byte-unchanged. There are 214 handwritten repository additions and 263 retained
evidence-script lines: **477**, within the split; docs and generated data are
additional. Final validation, provenance and commit details are recorded in
private/evidence/2d-4b3e2-part2-s2/COMPLETION.md.

**INCOMPLETE overall at the requested split.** Both durable receipt consumers,
their positive fixture migration and invalid-basis controls remain the next
part. No receipt schema, helper, operand or assertion is changed in this part.
Free-text validation_ref and /1 remain non-authoritative, and SQL 17 still
fences every extraction-based load-bearing support. Fence replacement remains
a separate following task.

### 2d-4b3e2 consumers: re-estimate before code, 2026-10-15

Against accepted latest-revision code `ad1cc4a` on gen2, read the complete
continuation, all operator rulings, this dossier from §2d-4b3e onward, the
named flow/adjudication/methodology authority and earlier slice evidence.
The former 420-line estimate omits copying SQL 21's complete closed domain
into an additive successor, independently preserving earlier diagnostics, and
migrating shared raw receipt controls. Revised estimate: **about 850 handwritten
lines**, excluding documentation and generated mutation-control/hash data.
Split by receipt method and stop after the first part:

1. **This dispatch, about 495 lines:** additive receipt-domain extension and
   verifier-extraction guard 155; typed schema and fenced Router check 40;
   shared verifier receipt basis fixtures and migration 100; isolated Router/raw
   controls, readback/replay/conflict/rollback 135; paired mutants/trace and
   catalog/scope evidence 65. The validated consumer remains pending.
2. **Next part, about 355 lines:** successful bound /2 validation consumption
   at Router/raw DDL, validated fixture migration, failed/integrity/same-family,
   /1 and NULL-pin refusals, separately paired mutants and traces. Re-estimate
   at dispatch. SQL 17 replacement remains a separate following task.

Add optional typed `extraction.extraction_id`, interpreted as an immutable
source_extractions key. New verifier_extraction receipts must name their own
non-NULL-pinned extraction, matching exact topic/work/version/acquisition event,
verifier lineage, declared canonical tool and extracting invocation, with output
tier sufficient for the receipt. Resolve the consumed acquisition by the existing
hash/call/time/route selectors. Existing SQL 18 missing-acquisition and SQL 19
content-ceiling diagnostics retain precedence independently of trigger order.
The Router check runs in the existing writer transaction after extraction writes;
no new service.py authority or external work is added. Historical receipts remain
readable; new missing/invented/foreign/unpinned bases refuse for every verdict.

SQL 01–31 remain byte-unchanged. SQL 32 replaces only SQL 21's trigger with an
otherwise byte-identical definition allowing the optional extraction_id member,
then adds the verifier consumer. Preserve every decoded-name/member/span/numeral
predicate. No stored column or JSON classification changes; review the catalog
and explicitly repin both hashes. Update positive verifier fixtures with durable
setup without weakening their assertions; inventory all positive validated
controls explicitly as pending next part. Do not claim their /2 migration done.
Free-text validation_ref and /1 confer no authority; **SQL 17 still fences every
extraction-based load-bearing support**, including newly bound verifier receipts.

Before commit run full gen2-test, trigger-order, composition, every edited-target
and transitive edited-fixture mutant family with --only, plus all eight static
gates. Trace each new pairing through its changed guard. Heavy runs wait for no
active gen2-landing-* unit. Disposable snapshots copy .venv-gen2 with cp -a and
touch their installed marker; never symlink or refresh during mutants. Evidence:
private/evidence/2d-4b3e2-consumers/. No providers, live gen-1/8765, real database
migration, protected-register edit or main merge.

Implementation integration note: the additive domain successor has a distinct
trigger name, so existing span predicate mutants now target its live definition
with unchanged IDs, killers and controls. The trigger-order tool must preserve
retired CREATE/DROP pairs in place and reverse installed triggers only; add a
literal replacement regression. This is included in the first-part budget.

**First consumer part implemented; requested stop, 2026-10-15.** The dispatch
base is `81364d9` (accepted latest-revision code `ad1cc4a`). SQL 32 replaces
SQL 21's installed domain trigger with an otherwise identical successor allowing
optional extraction.extraction_id; a regression compares their complete bodies.
It then requires new verifier_extraction receipts to consume a pinned durable
own extraction bound to the selected acquisition, work/version, verifier,
extracting invocation, canonical tool and sufficient output tier. EvidenceWriter
independently checks after insertion within the existing transaction; refusal
rolls back the receipt and successful effects. SQL 18/19 retain their diagnostic
precedence in either trigger order. New missing, invented, foreign, unpinned,
wrong-tool, insufficient-output and non-text references have isolated controls.

Positive verifier fixtures now retain durable setup, with authenticated Router
commits where the fixture uses Router admission. The authority, amendment and
capture controls retain all their original assertions. The receipt-fixture audit
explicitly leaves every positive validated_extraction /2 migration pending.
All 26 new pairings have accepted path traces. The work-dimension mutant removes
both redundant work checks; its unchanged killer retains the full FK/state oracle.
Existing span mutants target the live successor without changing IDs or controls.
The order tool preserves retired CREATE/DROP pairs and reverses installed guards.

This part adds **474 handwritten repository lines plus 33 retained evidence-script
lines: 507 total**, excluding documentation and generated control/hash data.
SQL 01–31, service.py and the protected registers stay byte-unchanged. Catalog
review proves the one intended domain replacement and added receipt guard, all
columns unchanged, 37 JSON / 37 covered / zero pending and 504 scalar TEXT; both
reviewed hashes are explicitly repinned. Validation results and the commit are
recorded in private/evidence/2d-4b3e2-consumers/COMPLETION.md.

**INCOMPLETE overall at this split.** The validated_extraction consumer still
must require a successful, bound durable /2 validation and refuse failed,
integrity-only/same-family, /1-only, unbound and NULL-pin bases; its fixture
migration remains next. Free-text validation_ref and /1 grant no authority.
**SQL 17 still fences every extraction-based load-bearing support**, including
newly bound own-extraction receipts. Fence replacement remains separate work.

The broad sweep exposed three old capture mutants masked by the new independent
Router consumer and two rank-four mutants breaking fixture output construction.
RouterGuardTest's existing capture isolation now stubs only the own-extraction
consumer during substitution negatives; production-path controls keep it active.
Receipt fixture outputs cap at full_text even under a widened input-view mutant.
No old ID, control, assertion or production predicate changes. Corrected complete
families, final full tests, traces and trigger-order results are retained in the
completion evidence, with per-ID reconciliation against the broad sweep.

### 2d-4b3e2 consumers part 2: design and re-estimate before code, 2026-10-16

Against dispatch `4d1ba11` (accepted consumers/trigger-inventory repair
`0364453`) on gen2, read
2d-4b3e2 in full, all three operator rulings, this dossier from §2d-4b3e onward,
the named independence authority and consumers-part-1/repair evidence.
Re-estimate **about 495 handwritten lines**: additive SQL 33 consumer 45;
EvidenceWriter admission 40; shared durable validation fixtures/migration 85;
isolated Router/raw controls and history/replay/conflict/rollback 175;
predicate mutants/registration 75; retained audit/trace wrappers 75.
Documentation and generated control/hash data are additional. Implement this
first part and stop; **SQL 17 replacement remains the next task part**.
If the slice grows materially beyond 500 lines, split the remaining work again.

Keep the existing wire spelling extraction.validation_ref, but interpret it
only as an exact extraction_validations_v2.validation_id. A nonempty string
alone supplies no authority. Require its immutable result-view row to have
method_succeeded = 1, with validator equal to the receipt verifier. Resolve the
target extraction and require its exact topic/work/version/acquisition event/
verifier lineage, declared extracting invocation and canonical tool, non-NULL
registry pin and sufficient output tier. The admitted validation already binds
its independent comparison extraction, both registered pins/families and the
latest revision at validation admission. Do not compare retained validations
to today's registry: later operator merges retain historical interpretation.
Historical /1-only, failed, integrity-only/same-family, missing/invented,
foreign-lineage and NULL-pin bases cannot satisfy the consumer.

Install ordered additive SQL 33 without changing SQL 01–32. Its AFTER INSERT
guard follows SQL 32's acquisition/content diagnostic precondition so SQL 18/19
retain precedence in either trigger order. EvidenceWriter independently checks
inside the existing writer transaction after receipt insertion and same-outcome
record writes. No service.py change, new column or JSON classification is
needed. Review the full catalog and explicitly repin both reviewed hashes.
Migrate every positive validated receipt fixture to an already retained /2
basis; attachment never creates a record during a receipt attempt. Preserve
all old negative and promotion/hold assertions. Trace each new mutant's separate
passing control through its changed code, and run the full mutation inventory
without --only because SQL 33 adds a trigger, in addition to required targeted,
composition, full test, order and eight static gates. Full inventory covers
all edited-file and transitive shared-fixture families.

SQL 17 remains byte-unchanged and fences every extraction-based load-bearing
support. Free text and /1 remain non-authoritative; admission does not promote.
Heavy runs wait for no active gen2-landing-* user unit. Any disposable snapshot
copies .venv-gen2 with cp -a and touches its installed marker, never symlinks or
refreshes it during mutation. Evidence: private/evidence/2d-4b3e2-consumers2/.
No providers, live gen-1/8765, real migrations, protected-register edits or main
merge are authorized or needed.

**Consumer implemented and validated; requested stop, 2026-10-16.** SQL 33
consumes only extraction_validation_results_v2.method_succeeded = 1 and binds
the target to the receipt's acquisition, topic/work/version/verifier lineage,
extracting invocation, canonical tool, non-NULL pin and sufficient output tier.
EvidenceWriter independently computes the same /2 method-success predicate from
the immutable table (Store reads tables, not views) and checks target bindings
inside the writer transaction. New validation admission still obeys SQL 31;
receipt readback/consumption preserves historical interpretation after a later
registry merge. Free text and /1-only records supply no authority.

All positive validated fixtures now retain successful independent /2 bases
before receipt attempts, with capability-derived Router attribution where used.
The table/span helpers retain the target's actual producer attribution rather
than declaring it to be the verifier's own extraction. Original negative,
receipt-mirror, hold, promotion, replay/conflict and rollback assertions remain.
Both consumer paths have isolated invalid-basis tests and accepted tier/history
controls. All 29 new predicate mutants have separate passing controls with
retained path traces; their early probe kills all 29. SQL 01–32, service.py
and the protected registers remain byte-unchanged. Catalog review finds exactly
one added trigger and unchanged columns/classifications (37 JSON / 37 covered /
zero pending; 504 scalar TEXT), with both hashes explicitly repinned.

The slice adds **354 handwritten repository lines and 31 retained evidence
script lines: 385 total**, excluding documentation and generated control/hash
data. Stop after this consumer part. **SQL 17 still fences every extraction-based
load-bearing support**; replacing that fence remains the next task part.
Final gate results and commit identity will be retained in
private/evidence/2d-4b3e2-consumers2/COMPLETION.md.

The first complete mutation sweep killed 3,504/3,505; the sole invalid old
pair was SQL 20's independent-extractor predicate. The migrated producer target
was also the acquirer, so that validated killer no longer exercised independence
from acquisition. Its existing test now retains all original cases and adds an
admitted target from a third invocation, a successful /2 validation and the same
insufficient-table refusal plus accepted page control. The old mutant ID,
killers, controls and production predicates are unchanged. The isolated rerun
kills it with both paired controls passing; fresh full gates follow this repair.

**Final validation complete, 2026-10-16.** Fresh full gen2-test passes
**4,080 tests with two existing skips**. Final trigger-order passes with
**322 installed triggers reversed / 3,757 identical Store tests and subtests**.
The complete composition module passes separately and in the final 219-test
table/span/composition run. The final full make gen2-mutation, without --only,
passes **3,505/3,505**, with all **3,488** separately paired mutants' controls
passing, green 1,002-test Store and 25 file-target baselines, and every installed
DDL trigger covered. All 29 new control traces qualify. All eight static gates
pass; the final documentation receives one final static check before commit.
The required --only sweep is reconciled per ID: 2,753 kills in the broad run,
plus the corrected complete 20/20 table family, cover all 2,754 selected IDs.
The earlier broad exit 1 is retained and is not described as a green run.
All 3,476 old control entries remain unchanged.

The source and venv bytes stayed frozen through the final full runs. Earlier
interrupted/baseline-failing attempts and their diagnoses remain in evidence.
Every heavy command had an idle landing-unit preflight; no repository snapshot,
venv refresh, provider call, live gen-1/8765 access, real migration, protected
register edit or main merge occurred. **COMPLETE for consumers part 2; stop
here. SQL 17 replacement remains the next task part.** Commit, complete logs,
catalog/fixture/control audits and provenance:
private/evidence/2d-4b3e2-consumers2/COMPLETION.md.

### 2d-4b3e3: bound-basis promotion, design and re-estimate before code (2026-10-16)

Dispatch HEAD on gen2 follows accepted SQL 32/33 consumers. Read the task,
all three operator rulings, this dossier from §2d-4b3e onward, SQL 17 and its
§2d-4b3b-repair-1 design, the installed-trigger mechanism, SQL 12/32/33,
V-1–V-8 and the named private independence authorities. The earlier 310-line
estimate omits historical-receipt predicate isolation, same-receipt V-4
qualification, installed-trigger retirement and control-path evidence.
Re-estimate **about 690 handwritten lines**, excluding documentation and
generated control/hash data. Split and stop after the first part:

1. **This dispatch, about 490 lines:** ordered SQL 34 basis consumption and
   SQL 17 retirement 85; Router/raw historical-basis and promotion controls,
   V-4/check/tier refusal, replay/conflict/rollback and existing promotion
   fixture updates 250; predicate mutants/registration 90; retained catalog,
   fixture/scope/control-path audit wrappers 65.
2. **Following part, about 200 lines:** remove the obsolete unbound-extraction
   attention classification for newly admitted bound support; missing-content,
   disagreement, receipt/audit hold effects and replay/rollback tests; paired
   attention mutants and traces. Re-estimate at dispatch. This first part
   deliberately retains the current remediation holds even for bound support;
   the complete task remains INCOMPLETE until attention is adjusted.

SQL 01–33 stay byte-unchanged. Add SQL 34, dropping SQL 17's trigger and
installing a distinctly named successor so the accepted installed-trigger
inventory/reversal mechanism sees only the live definition. A read-only view
resolves each extraction receipt's exact durable basis: own pinned extraction
for verifier_extraction, or the exact successful independent /2 validation's
target for validated_extraction. Recheck topic/work/version, verifier and
extracting invocation, canonical tool, non-NULL pin, acquisition hash/call/time/
route, extraction output tier and recorded-content ceiling. Preserve historical
validation interpretation; never join the latest registry at consumption.
The existing SQL 32/33 and EvidenceWriter admission guards stay intact.

The successor keeps SQL 17's activation and unbound-extraction diagnostic.
Its qualifying receipt must itself be canonical or consume that bound basis,
with the same claim/revision, supports verdict and load-bearing use. Extraction
qualification also reads the claim's own required tier and the receipt's
performed V-8 checks, preventing a low/sampled bound receipt from lending its
basis to another historical unbound receipt. SQL 03 remains independently
responsible for V-4 and contract admission. No new basis waives tier-0 handling,
quote checks, role separation, standing, or any other existing guard.
Historical missing/free-text-only,/1-only, failed and integrity-only receipts
remain readable but cannot supply extraction authority. Newly submitted ones
still refuse at Router/raw admission. Historical fixtures temporarily remove only the SQL 32/33 admission consumers
to seed old declarations, preserving all other constraints and restoring their
exact definitions. The promotion fixture installs and asserts the requested
live view and complete trigger definitions/order, including mutants and reversal.

SQL 12 and EvidenceWriter's governed-capture consumers remain canonical-only:
a retained extraction/output does not supply a new governed quote/span domain,
and cannot preserve accepted support against an unmatched later capture.
Audit every promotion fixture using extraction methods and record the exact
positive/negative purpose rather than silently converting a historical negative
into a newly bound control. Trace every new mutant's separate accepted path.
Run full gen2-test, trigger-order, composition, full uncovered-trigger inventory
(or full gen2-mutation), affected/transitive-fixture --only families and all
eight required static gates. Each heavy run waits for no active gen2-landing-*
unit. No environment refresh, provider/live gateway/8765, real migration,
protected-register edit or main merge. Disposable snapshots, if needed, copy
.venv-gen2 with cp -a, never symlink it. Evidence:
/home/trevor/work/research-loops-public/private/evidence/2d-4b3e3/COMPLETION.md.

**First part implemented and validated; requested stop, 2026-10-16.**
SQL 34 retires SQL 17's installed trigger and consumes the exact SQL 32/33
basis through bound_extraction_receipts. Both methods promote at bibliographic,
abstract and full-text tiers only with their own bound receipt, sufficient
output/recorded content, load-bearing use, performed V-8 checks and no tier-0
alarm. Historical unbound, /1-only, failed and integrity-only declarations stay
fenced. Retained /2 interpretation survives later operator registry merges.
SQL 12 and EvidenceWriter's governed-capture consumers stay canonical-only.

The promotion fixture asserts the requested complete trigger definitions/order
and basis view, including mutants, instrumentation and reversed installation.
Raw counterfactuals explicitly isolate consuming predicates from admission;
foreign acquisitions retain matching record identities and sufficient output
so another guard cannot mask their binding refusals. The receipt/promotion
fixture audit retains every old negative oracle; the formerly fenced Router
positive now promotes because it already carries a durable basis. Its existing
hold assertions remain unchanged pending the next part. All 3,505 prior control
records are unchanged, and 26 new pairings have accepted control-path traces.

Validation passes: full gen2-test **4,100 tests, two existing skips**;
trigger-order **322 installed triggers / 3,821 identical Store tests/subtests**;
full composition; all **183/183** selected mutants killed with separate controls
passing and a green 1,012-test Store baseline; the full uncovered-trigger
inventory (the task's permitted alternative to full gen2-mutation); and all
eight static gates. Final dossier notes receive the static gates again before
commit. Initial failed/interrupted attempts and fixture diagnoses remain in
evidence and are superseded by these final green runs.

This part adds **389 handwritten repository lines plus 75 retained evidence
script lines: 464 total**, excluding documentation and generated control/hash
data. Catalog review proves one retired trigger, one successor and one added
view, with unchanged columns/classifications (37 JSON / 37 covered / zero
pending; 504 scalar TEXT), and both reviewed hashes explicitly repinned.
SQL 01–33, service.py and the protected registers remain byte-unchanged.
Source and non-cache venv bytes stayed frozen through final validation; no
snapshot or environment refresh was needed. Heavy runs had idle landing-unit
preflights. No providers, live gen-1/8765, real migration or main merge occurred.

**INCOMPLETE overall; stop after this first part.** Bound support still creates
the old unbound-extraction remediation hold. Removing that obsolete attention,
while retaining truthful missing-content holds and earlier disagreement, remains
part 2 (about 200 lines, to be re-estimated before code). Commit and complete
logs/audits: private/evidence/2d-4b3e3/COMPLETION.md.

### 2d-4b3e3-repair-1 — two-operand validated-support ceiling

**Design and re-estimate before code, 2026-10-16.** Read Astra's review of
ba94b99 and its retained tier-matrix source/results. F1 is a consumption gap:
the successful /2 comparison names an independent extraction, but SQL 34 reads
only the target's output tier. A successful semantic-agreement assessment
cannot supply content absent from either operand. Validated receipt authority
must be capped by the minimum of the exact target output tier, the exact
validator extraction output tier, and the recorded acquisition content tier.
The own-extraction path retains its existing output/acquisition ceiling.

Edit **undeployed SQL 34 in place**, as this repair explicitly permits. Its
bound-receipt view will resolve validation.validator_extraction_id to the exact
source_extractions row and require that row's tier to cover receipt access on
the validated branch. The installed promotion trigger already consumes that
view for the same receipt; retained validations and receipts therefore receive
the new ceiling without rewriting history or relying on admission. Add the
same independent-output comparison to EvidenceWriter's validated receipt check
inside its current transaction. SQL 01–33, especially SQL 31's current-at-
admission rule, stay unchanged. Raw historical receipts can remain stored but
cannot acquire authority above either operand. Low-tier and failed extraction/
validation records remain history. No success, adjudication or later registry
change waives either ceiling; retained registry interpretation stays intact.
Canonical capture and the already accepted retirement/binding rules stay intact.

Re-estimate **about 240 handwritten lines**: SQL 34 and Router checks 15;
asymmetric promotion/history and receipt tests 130; paired predicate mutants
and corrected N1 rationale strings 25; retained audit/control-trace scripts 70.
Documentation and regenerated classification/control records are additional.
No split is needed for this repair; the original task's pending-attention part
remains outside it. Fix test_bindings to lower only the selected target/own
basis, then add independent-only cases. Admit low-tier independent outputs and
semantic comparisons through authenticated Router commits, leaving the target
and acquisition at full text. Test all three insufficient tier pairs through
Router and raw promotion, including already retained receipts; reverse-order
execution must preserve those refusals. Equal/higher-tier independent controls
must promote. Isolate the Router admission comparison with SQL receipt guards
removed, as in the existing receipt suite. Pair each new comparison mutant
with a separate accepted control and retain its qualified path trace. Correct
the two method mutants' rationale to describe their actual opposite-method,
full-text controls and regenerate records.

Before committing: full gen2-test, gen2-trigger-order, full composition,
affected-family --only sweeps, complete uncovered-trigger inventory, and all
eight static gates. Review the unchanged table/JSON classification and explicitly
repin catalog and ordered-DDL hashes. Check no gen2-landing-* user unit is active
before every heavy run. Any disposable snapshot copies .venv-gen2 with cp -a;
no provider calls, live gen-1/8765 access, real-database migration, protected
register edits or main merge. Evidence and COMPLETION.md belong under
private/evidence/2d-4b3e3-repair-1/.

**Repair implemented and validated, 2026-10-16.** Edited undeployed SQL 34
in place. Its view resolves the exact validator_extraction_id and requires
that independent output to cover receipt access, in addition to the target
output and exact acquired-record ceiling. The unchanged promotion trigger
consumes this view for retained receipts. EvidenceWriter applies the same
independent-output cap through a small transaction-local helper. SQL 01–33,
including SQL 31, the own-extraction cap, retained registry interpretation,
canonical capture, service.py and the protected registers remain unchanged.
Low-tier extraction/comparison history remains retained; successful comparison
or adjudication supplies no missing tier. The earlier attention split remains
outside this repair.

The fixture now admits asymmetric independent outputs and semantic comparisons
through ordinary authenticated Router commits. test_bindings lowers only the
selected target/own basis. Three insufficient pairs refuse promotion across
Router, raw and reversed-trigger paths with full-text targets and acquisitions;
six sufficient pairs per path promote. The retained matrix records **9/9
refusals and 18/18 accepted controls**, and Router admission refuses the three
new over-tier receipts. Four new exact-reference/tier mutants have separate
passing controls; all **30/30** retained control-path traces qualify. N1's two
method-control rationales now accurately describe opposite-method full-text
controls; all other **3,529** prior entries are unchanged.

Final validation: full gen2-test **4,106 tests, two existing skips**; full
trigger-order **322 installed triggers / 3,832 identical Store tests/subtests**;
full composition **6 tests**; the fresh complete selected sweep **785/785
killed**, **782** with separate passing controls and three existing documented
exceptions, with green **1,014-test Store and seven file-target baselines**.
The transitive audit requires 169 IDs and selects complete affected families.
The full installed-trigger inventory has zero uncovered triggers across all
322 live definitions. All eight static gates pass and are repeated after this
final documentation update. Catalog review finds only the basis view changed:
all table columns, 37 covered JSON columns, zero pending and 504 scalar TEXT
classifications are unchanged; both catalog and ordered-DDL hashes were
explicitly repinned.

Superseded records remain in evidence: the first Router expression exceeded
the complexity limit and was extracted into the small helper; the first broad
sweep was **784/785**, with one invalid cross-join mutant whose control duplicated
rows. That mutant now selects the wrong exact operand, preserving cardinality;
its fresh probe and complete 785-mutant rerun pass. Interrupted full runs are
not credited; the final full run uses the final frozen source and inventory.

Actual size is **91 repository code/test/mutant lines plus 339 retained audit
script lines: 430 total**, conservatively counting reused auditors and excluding
documentation/generated records. No snapshot or environment refresh was needed.
Heavy runs had idle landing-unit preflights. No provider calls, live gen-1/8765
access, real-database migration or main merge occurred. **This repair is
COMPLETE**; the original task's deferred attention part remains separate.
Commit identity, checks and retained artifacts are recorded in
private/evidence/2d-4b3e3-repair-1/COMPLETION.md.

### 2d-4b3e3 part 2 — pending-extraction attention (design before code, 2026-10-16)

Read the continuation task in full, §2d-4b3e3 and repair-1, accepted SQL 34,
SQL 32/33 consumers, Verification.write_holds, commit ordering, V-2/V-4 and
the named private independence authorities. Re-estimate **about 440 handwritten
lines**: attention/store read primitive and wiring 35; bound/fenced,
missing-content, disagreement, same-outcome, replay/conflict/rollback tests 225;
predicate mutants and registration 65; retained scope/control-path auditors
115. Documentation and generated control records are additional. This fits
one part below the approximately 500-line split; stop after this part. If
additional work would cross that boundary, record it as a following part.

Keep SQL 01–34 and promotion unchanged. Add a narrow read-only Store primitive
for membership in SQL 34's bound_extraction_receipts view; the hold writer
uses that exact receipt ID after insertion. Thus both output operands and the
acquisition ceiling, exact lineage, pins and retained /2 interpretation remain
canonical, without copying their predicates into attention. Supporting canonical
or bound extraction receipts create no new verification hold. All other
supporting extraction receipts retain the existing unbound-extraction cause.
Cannot-assess always creates missing-content remediation, even with a bound
basis; partially_supports and does_not_support always create disagreement
attention. No support
receipt clears an earlier hold, including earlier unbound remediation.

The immutable operation receipt is built before its referenced evidence, so
its hold-ID planning call must explicitly assume successful admission. Every
new extraction receipt must subsequently pass SQL 32/33 and EvidenceWriter's
checks inside the same writer fence; failed admission rolls back the entire
operation. The actual hold writer does not assume admission: it reads SQL 34
for the persisted receipt. Keep the ordinary hold_ids default on this durable
path, and use the explicit admission-planning flag only at the composition
root's existing receipt-building call. The two paths must agree for every
committed Router operation, including extraction/validation records supplied
in that same outcome. Historical fenced cases are tested through the actual
hold writer over memory-only retained receipts, with ordinary Router refusal
unchanged. Audit effects, ownership/deadlines, replay, and injected failure
rollback remain required. Canonical capture stays unchanged.

Run full gen2-test, trigger-order, composition, affected-family --only sweeps,
and all eight static gates after idle gen2-landing-* preflights. No trigger
changes are planned, so full uncovered-trigger inventory is not required;
retain it as a cheap additional audit. Trace each new mutant's separate control
through the changed predicate and preserve prior generated controls. No
provider, live gen-1/8765, real migration, protected-register edit, environment
refresh or main merge. No disposable snapshot is planned; any needed snapshot
must copy .venv-gen2, never symlink it. Evidence:
private/evidence/2d-4b3e3-part2/COMPLETION.md.

**Implemented and validated; COMPLETE, 2026-10-16.** Verification now reads
SQL 34 membership through a narrow read-only Store primitive, using the exact
persisted receipt ID. Supporting canonical and bound extraction receipts add
no verification hold. Historical fenced extraction support retains the exact
unbound-extraction remediation cause. cannot_assess_at_required_tier always
creates missing-content remediation, even with a bound basis; partially_supports
and does_not_support create disagreement attention. New support clears no
previous disagreement or remediation. SQL 01–34, promotion, both operand/output
ceilings, retained registry interpretation and canonical capture are unchanged.

The composition root explicitly plans hold IDs assuming successful admission;
actual hold writes consume the durable SQL 34 predicate after receipt insertion.
SQL 32/33 and Router admission still roll back invalid new bases. Same-outcome
extraction/validation controls prove that receipt effects, stored holds and audit
IDs agree even when the basis does not exist during planning. Both methods and
all three supported tiers, fenced history, missing access, earlier disagreement,
exact receipt selection, replay/conflict and rollback have controls. Three old
assertion sites now expect no obsolete hold for already-bound receipts; capture
quarantine and every other promotion/readback/replay assertion remain intact.
The first full suite exposed two of those stale sites (four failures including
inheritance/subtests); the corrected focused modules and a fresh full suite pass.

Final checks: full gen2-test **4,116 tests, two existing skips**; trigger-order
**322 installed triggers / 3,832 identical Store tests/subtests**; full composition
**six tests**; full harness modules **29 tests**; all **1,404/1,404** selected mutants
killed, **1,400** with separate passing controls and four unchanged documented
exceptions, with a green **1,014-test Store and 12 file-target baselines**. The
transitive audit requires 372 IDs and selects their complete families. All nine
new predicates and two retargeted old attention predicates have separate passing
control-path traces (**11/11 qualified**). Store mutants now reload service and
Router fixtures so their changed query actually reaches the tested consumer.
All 3,533 other old control records remain unchanged. The complete installed-
trigger inventory has zero uncovered triggers; DDL and classifications are
unchanged, requiring no repin. All eight static gates pass and are repeated
after this final dossier note before commit.

Actual size: **272 repository code/test/mutant additions plus 115 retained
script lines = 387**, excluding documentation and generated control/hash data.
This completes one part below the requested split; no further implementation
part remains in **2d-4b3e**, which is now **COMPLETE**. No provider call, live
gen-1/8765 access, real-database migration, protected-register edit, environment
refresh, disposable environment symlink or main merge occurred. One initial
AGENTS.md filename lookup incorrectly included ~/.agents; it returned no files
and no contents were read there. This reading-scope deviation and all superseded
failed/interrupted attempts are disclosed in the evidence, rather than claiming
complete procedural compliance. Final source/venv/protected-file proof, commit
and full logs: private/evidence/2d-4b3e3-part2/COMPLETION.md.

### 2d-4c: attributed detailed V-8 records (design and re-estimate; stopped)

Design before code against `528494011286ba7b4c5c5a4fb1de1ae002bfa203` on
`gen2`, 2026-10-16. Read task 2d-4c, this dossier's §2d-4 and accepted
2d-3 quote-protection/capture work, V-4/V-8, SQL 03's receipt and promotion
predicates, SQL 34 in full, and the named private flow architecture,
adjudication and methodology synthesis in full. **INCOMPLETE: design only.**
The task's Required 4 explicitly requires stopping after DOSSIER when the
authority leaves a design choice open. No implementation part starts here.

**Open question requiring an operator ruling.** What retained evidence and
method-specific conditions make each of `numeric_units`, `denominators`,
`negation` and `qualifications` a performed check, including a justified
`not_applicable`? Is an attributed, versioned verifier assessment with its
evidence sufficient, and must `not_applicable` retain an explicit reason and
the context examined? Alternatively, must some kinds use a specified
deterministic procedure or a prescribed observation/comparison artifact?
The required record fields settle attribution and binding, but do not settle
this minimum evidence or applicability policy. Choosing it determines which
records can satisfy V-4 and cannot be supplied silently by the coder.

Flow S4 step 4 and adjudication (c) suggestion 2 require the four independent
checks; S4 step 8 and adjudication (b) resolution 5 settle exact source/claim
bindings, acquisition lineage and role separation. Methodology §4 distinguishes
claim-level verification from tier-0 screening and warns about numeric and
negation limitations. V-8 permits `not_applicable` and adjudicated performed
failures while prohibiting unperformed load-bearing support; V-4 rechecks
performance at consumption. None specifies the evidence contract for these
four assessments or an applicability rationale requirement. These are limits
of the named authority, not a claim about every private design record.

**Recommendation, pending that ruling.** Approve one initial closed,
versioned attributed-assessment method. Require a retained, topic-authorized,
hash-authenticated evidence artifact for every performed outcome (`succeeded`,
`failed`, `not_applicable`), recording the assessment, method/version and
examined context. Require an explicit reason for `not_applicable`; absence
of a recognized token alone must not establish applicability. Numeric/unit
assessments should identify the quantities and unit interpretation; denominator
assessments the population/base; negation assessments the polarity and scope;
qualification assessments the limiting context. These are recommended report
contents, not store-proven scientific correctness or approved new rubrics.
Keep `not_checked` and `unavailable` truthful and non-authorizing; evidence of
an access failure is not evidence of a completed substantive check.

The accepted matcher in `gen2/router/quote_matching.py` supplies
`quote-protection/5`, `decimal-expression/2`, `english-negation/3` and
`si9-2022+clinical/2`. Its lexical output can be retained as supplementary
evidence with those versions. It protects quote fidelity and diagnostics;
it does not establish a correct denominator, negation scope, unit
interpretation or adequate surrounding qualifications. Do not manufacture a
V-8 success or `not_applicable` from a quote match or an empty token list.

**Conditional structural design.** Once the operator settles that policy:

- Add immutable detailed-check records in ordered additive DDL after SQL 34,
  with `-- trace:` markers. Each record carries an ID, one of the four kinds,
  one of the task's five outcomes, exact claim revision, topic/work/source
  version, examined artifact identity, complete cited-span binding, method
  and version, evidence references, and actual performing invocation,
  committing operation and time. Retain additional examined context spans
  separately from the exact cited-span list, so examining context does not
  rewrite the citation. Apply the accepted span/locator domain, including
  decoded unique member names and exact integral offsets.
- Derive attribution from the authenticated committing verification
  invocation; require contract admission, the claim's topic and a performer
  distinct from its actual producer. Authenticate retained source/evidence
  bytes outside the writer lock through existing C-9 handling; recheck
  immutable bindings and write inside the existing commit transaction.
  Canonical source identity and any consumed extraction/acquisition must
  agree with the receipt's own basis; do not equate canonical source bytes
  with extraction output bytes. DDL independently binds the declared rows;
  it does not certify execution, semantic truth or artifact hash truth.
- Add explicit per-kind receipt references. A load-bearing `supports` or
  `partially_supports` receipt must consume a matching durable record for
  every successful/applicable-exempt check. A performed failure used through
  adjudication must also have its attributed record: an invented failure
  label must not stand in for performing a check. Any supplied reference,
  including on an unsuccessful verdict, must resolve and match kind,
  outcome, claim revision, full cited spans, artifact and verifier. Missing
  or foreign bindings refuse atomically. Unsuccessful verdicts may continue
  reporting `not_checked`/`unavailable` without claiming performance.
- Resolve the wire vocabulary explicitly in the successor receipt design:
  SQL 03 and the current schema use `checked_ok`/`checked_problem`; the task
  requires durable outcomes `succeeded`/`failed`. Authoritative receipt
  check outcomes must equal record outcomes exactly. Retain historical
  receipt bytes and distinguish any legacy summary projection from the
  authoritative detailed outcome; never implement equality by silently
  accepting those spellings as interchangeable. Account for SQL 03's
  installed CHECK constraints, SQL 21/32's closed object shapes and the
  versioned schema when implementing this representation. This is concrete
  compatibility work included below, not an in-place rewrite of history.
- Use one exact durable-binding relation at receipt admission and at each
  promotion consumer, with an independent Router check. SQL 03's successor
  must require a qualifying receipt for the claim's own load-bearing flag
  and tier. SQL 34's successor must require the same receipt to have both
  its SQL 32/33 bound extraction basis and its detailed checks. Separate
  receipts cannot pool qualifications. Preserve acquired-content ceilings,
  both validated output ceilings, required/obtained tiers, load-bearing use,
  tier-0 rules, contract admission and canonical-only governed captures.
  Adjudication cannot waive an absent or unperformed check. Historical
  self-declarations remain readable and supply no new detailed-check
  authority. This dispatch changes none of those existing consumers.
- Put logic in a narrow Router collaborator; `service.py` receives wiring
  only under DEBT-036. Register new JSON columns in the closed member-name
  inventory and guard them before admission; repin both DDL hashes whenever
  DDL changes. Replay uses the existing committed-operation boundary,
  conflicting IDs refuse, and failures roll back records, receipts, holds
  and operation effects together.

**Re-estimate and split before implementation.** The old approximately
300-line estimate omits raw-DDL parity, receipt vocabulary compatibility,
both promotion consumers and the shared positive-fixture conversion.
Conditional estimate: **about 1,900 handwritten implementation/test/mutant
lines**, excluding documentation and generated controls. Re-estimate each
dispatch and split again if its concrete scope exceeds approximately 500:

1. **First part, about 480 lines:** durable record admission only (ordered
   DDL/member guards 115, schema 45, collaborator/wiring 95, Router/raw-DDL
   record tests 165, paired mutants/integration 60). Records grant no new
   receipt or promotion authority. Stop after this first implementation part.
2. **About 480 lines:** explicit successor receipt representation and
   optional record references, exact binding when present, legacy readback,
   schema/domain compatibility, Router/raw tests and paired mutants. Keep
   activation of mandatory detailed consumption for the last part.
3. **About 460 lines:** audit and convert positive load-bearing Router,
   raw-DDL, quote, acquisition and extraction receipt fixtures, including
   shared/transitively imported fixtures and their paired controls. Prove
   the conversion preserves the intended accepted paths before activation.
4. **About 480 lines:** mandatory receipt consumption and both promotion
   consumers, same-receipt/non-pooling tests, adjudication refusal,
   replay/conflict/rollback, historical-receipt controls and predicate
   mutants with control-path traces. No intermediate part claims the whole
   V-8 requirement is implemented.

**Validation and evidence.** For every kind, Router and raw-DDL matrices
must cover every outcome, missing records, foreign claim/revision/span/source/
verifier, producer performance, outcome mismatch and accepted controls.
Promotion needs canonical and both extraction methods with and without
records, preserved tier/use/tier-0/bound-basis failures, historical records,
and attempted adjudication of unperformed checks. Audit every positive
load-bearing receipt fixture; a schema example that names record IDs is not
proof those records exist in a durable fixture. Keep replay/conflict/rollback
and predicate-mutant accepted-path traces explicit.

Before committing, run the task's full gen2-test, trigger-order and composition
module, affected `--only` families (including transitive shared-fixture
controls), and all eight named static gates. Any trigger addition/replacement/
retirement also requires the full uncovered-trigger inventory or full
gen2-mutation. This design-only dispatch edits no such file or fixture and
has no affected mutation family or hash repin. Wait for no active
`gen2-landing-*` unit before heavy runs; copy `.venv-gen2` with `cp -a` into
any disposable snapshot. Evidence and COMPLETION.md belong in
`/home/trevor/work/research-loops-public/private/evidence/2d-4c/`.
The operator's evidence/applicability ruling is required before part 1;
the entire 2d-4c brief remains **INCOMPLETE**.

#### 2d-4c part 1 — operator ruling and re-estimate (2026-10-17; before code)

The task's 2026-10-17 operator ruling approves the recommendation above and
settles the evidence/applicability question. Re-estimate this dispatch at
**about 495 handwritten lines**: ordered DDL 155, schema 50, collaborator and
wiring 65, Router/raw record matrices 170, paired mutants/integration 55.
Generated member guards, catalog classifications, hashes and control records
are additional. Stop after durable admission; parts 2–4 remain deferred.

Use one closed `attributed-assessment/1` report, retained as the immutable
record's assessment JSON. It contains kind/outcome, exact claim revision,
work/source version and canonical source hash, the separate examined artifact
reference, cited spans, additional context spans, assessment text, kind-specific
context description and an explicit applicability reason (nonempty for
not_applicable). `context_examined` describes quantities/unit interpretation,
population/base, polarity/scope or limiting context according to kind; the store
checks its presence, never whether the prose is scientifically adequate.
Performed outcomes require a topic-authorized evidence artifact whose parsed
JSON equals that complete report, so its assessment, method/version, context
and bindings cannot drift from the record. Lexical diagnostics may be retained
as supplementary artifacts; none is interpreted as performing a check.
Unperformed outcomes may retain evidence but supply no performance authority.

The two new JSON columns are `assessment` and nullable `evidence_ref`; classify
both and generate additive member-domain guards. Raw DDL independently checks
the closed report domain, exact integral span/locator domain, authorized artifact
metadata, claim/source/topic, independent contract verifier and operation
attribution. Router authenticates examined and evidence bytes outside the writer
lock and checks report equality, then writes within the existing fenced commit.
A canonical source identity and examined extraction bytes remain separate;
receipt-specific acquisition/extraction matching belongs to the later consumer.
No receipt schema, fixture, SQL 03/34 consumer or promotion authority changes.

Validation: full task gates, full installed-trigger inventory, complete affected
mutation families (including service/schema/tool targets and transitive fixture
imports), and separate accepted control traces for new predicates. Only repository
AGENTS.md lookup is used (none found). No disposable snapshot is planned; if
needed its venv will be copied. Evidence: private/evidence/2d-4c-part1/.

**Part 1 implemented and validated, 2026-10-17.** SQL 35 retains immutable
`attributed-assessment/1` reports with an independently attributed committing
verifier, exact claim revision, canonical source identity, separate examined
artifact, cited spans and additional context spans. Performed outcomes need a
retained evidence artifact containing the complete report; not_applicable also
needs an explicit reason. Assessment/context/reason presence uses SQL 16's
recorded-nonblank/1+ucd17.0.0 rule. SQL 21's span object, locator and exact numeral
expression is reused byte for byte for both arrays. These are structural and
relationship checks, never certification of execution or scientific correctness.

DetailedChecks authenticates examined/evidence bytes outside the writer lock,
compares the retained evidence report, then rechecks claim/source/producer
relationships and writes inside the existing fenced transaction. service.py adds
only four wiring lines (1,447 total). SQL 36 guards the two new JSON columns;
the reviewed catalog now has 39 covered JSON columns, zero pending and 509 scalar
TEXT classifications. Both ordered-DDL and SQLite-catalog hashes are repinned.
SQL 01–34, receipt representations, promotion and the tier/use/bound-basis/tier-0
gates are unchanged. New records have no receipt or promotion authority;
**parts 2–4 remain deferred**, and the whole 2d-4c requirement is not complete.

Final functional validation: full gen2-test **4,146 tests, two existing skips**;
trigger-order **332 installed triggers / 3,929 identical Store tests/subtests**;
full composition **six tests**. The complete affected-family --only sweep kills
**3,053/3,053** mutants with green **1,029-test Store and 23 file-target baselines**:
3,037 separate passing controls, 11 existing accepted cases inside killers and
five unchanged documented exceptions. All **29 new mutants** have separate
passing controls and qualified control-path traces. All **3,544 prior control
records** remain unchanged. The full installed-trigger inventory has zero
uncovered guards. Eight static gates pass and are repeated after this note.

Actual footprint is **605 non-generated repository additions**, above the
495-line estimate; raw-DDL isolation/member tests and shared history/catalog
oracles account for the overrun. Another **134 retained script lines**, mostly
reused validation drivers/auditors, give a conservative 739-line total. Generated
guards, catalog/control data and documentation are additional. This stops at the
first logical implementation part; no successor receipt or consumer work starts.

Superseded attempts are retained and not credited: initial fixture/schema-wrapper
errors; the required committed metrics-ledger checkpoint and a two-line tool-size
overflow; stale whole-store/catalog oracles; and a new-mutant probe with one
masked verifier-topic case and four malformed duplicate predicates. Artifact
catalog setup now uses a stable topic owner to isolate verifier attribution;
valid aggregate predicates preserve the four duplicate-mutant controls. A later
control-reason clarification changes no mutation definition or control binding.
Final source, scope, hashes, logs and commit are in
private/evidence/2d-4c-part1/COMPLETION.md. No provider call, live gen-1/8765 access,
real-database migration, protected-register edit, environment refresh, venv
symlink or main merge occurred; AGENTS.md lookup stayed inside this repository.


#### 2d-4c part 2 — re-estimate (before code)

2026-10-17, against `28fec14` and accepted part 1 `89401a7`; read the whole
task, operator ruling, part 1 notes/code and Astra's NB1. Estimate **500
handwritten lines**: additive SQL domain/binding 80, schema compatibility 45,
collaborator/wiring 55, Router/raw tests including NB1 230, paired mutants 65,
history/hash/control integration 25. Also retain an approximately 85-line exact
copy of the installed SQL 32 span guard when replacing its root member shape;
generated control data and documentation are additional. This is the optional
reference slice only; fixture conversion and mandatory consumption remain
parts 3/4. Re-split if implementation reveals materially greater scope.

Exact representation: `verification-receipt/2` retains the existing `checks`
summary and requires a closed `detailed_checks` object with all four kind keys.
Each entry has an authoritative-vocabulary `outcome` and an optional `record_id`
(nonempty string; omission means no reference). An explicit checked mapping is
`succeeded -> checked_ok`, `failed -> checked_problem`, with the other three
spellings identical; reject inconsistent pairs, legacy spellings in outcomes,
and detailed fields on `/1`. Never rewrite retained `/1` JSON. Optional references
must resolve with exact kind/outcome, topic, claim revision, complete ordered
cited spans including locators, canonical source identity and verifier. The
examined artifact must be the obtained canonical artifact, own extraction output,
or validated target extraction output according to the receipt's actual basis.
No new JSON columns; the existing receipt member guards cover nested members.

Files: `gen2/store/schema/37-detailed-check-receipts.sql` and `order.txt`,
`gen2/schema/verification-receipt.schema.json`, `gen2/router/detailed_checks.py`
and wiring-only `service.py`; new `test_detailed_check_receipts.py` and
`test_store_detailed_check_receipts.py`, NB1 in `test_detailed_checks.py`,
`test_store_history.py`; `tools/gen2_mutants/detailed_check_receipts.py`, mutant
registration/control files and the two hash pins. Metrics ledger/baseline only
if the existing gates require attributable admission. No promotion consumer or
shared positive receipt fixture changes. Validation uses all task gates,
transitive affected-family selection, full uncovered-trigger inventory and
separate passing controls with traces for every new mutant. Evidence goes to
private/evidence/2d-4c-part2/; no private inputs are committed.


**Part 2 implemented and validated, 2026-10-17.**
`verification-receipt/2` retains the legacy `checks` summaries and adds a closed
`detailed_checks` object with all four kinds. Each entry supplies an exact durable
outcome and an optional `record_id`. Schema, Router and SQL explicitly check the
projection `succeeded -> checked_ok`, `failed -> checked_problem`, with the other
three spellings unchanged. A referenced record's outcome equals the detailed
outcome exactly; legacy spellings are refused there. `/1` retains its original
shape and readback, and cannot silently carry `/2` fields.

SQL 37 replaces the installed span guard with v3, preserving its span/locator/
numeral predicates and changing only the root member allowance for `/2`. Two new
guards enforce the successor domain and exact optional references: kind, outcome,
topic, claim revision, entire ordered cited-span array including locators,
canonical work/version/hash and performing verifier. Examined bytes bind to the
obtained canonical artifact, own extraction output, or validated target extraction
output according to the receipt's actual basis. DetailedChecks independently
checks these relationships inside the existing writer transaction. Wiring admits
same-operation records before their receipts; service.py is 1,448 lines. Tests
include distinct canonical/extraction bytes, replay, conflict and atomic rollback.
These checks bind recorded relationships, never certify scientific correctness.

No JSON columns were added; the existing receipt member guards cover nested
successor fields. Both ordered-DDL and SQLite-catalog hashes are repinned. SQL 03,
SQL 34 and promotion collaborators are unchanged. Optional references apply to any
verdict; absent references remain admissible. **Mandatory consumption and promotion
changes remain OFF.** Positive-fixture conversion and activation remain parts 3/4;
this completes part 2, not the whole 2d-4c requirement.

Astra's NB1 now has focused Router regressions for corrupt already-recorded
examined bytes, corrupt previously recorded evidence omitted from result_refs,
and a check-ID collision under a fresh operation. Accepted controls accompany
these cases; refusals preserve substantive table state apart from rejection audit.

Validation: full gen2-test **4,191 tests, two existing skips** (45 new tests);
full trigger-order **334 installed triggers / 3,949 identical Store tests/subtests**;
composition **six tests**, focused modules **90 tests**, and all eight static gates.
The transitive affected-family sweep kills **2,091/2,091** mutants with green
**1,049-test Store and 18 file-target baselines**. It retains 2,078 separate passing
controls, nine existing accepted cases inside killers and four existing documented
exceptions. All **29 new mutants** have separate passing controls and qualified
traces. One extraction control was tightened to traverse the extraction branch;
the complete new family was rerun **29/29** with that final pairing. All **3,573**
prior control records are unchanged. Full installed-trigger inventory: zero
uncovered; complete mutant inventory: 3,602. Static gates are repeated after this
note before committing.

Footprint: **464 handwritten repository additions**, against 500 estimated, plus
**85 unchanged copied span-guard lines**, against 85 anticipated: **549 total
non-generated additions**. Another **135 retained helper-script lines**, mostly
reused from part 1, give a conservative total of 684. Generated controls, hash data
and documentation are additional. The guard rename also required two existing
span-mutant scopes and three test oracles to follow v3. No history-table or metrics
ledger change was needed. Superseded fixture/control attempts and stopped early
runs are retained without passing credit; the final product code/tests remained
unchanged during the last control-pair refinement. Evidence and COMPLETION.md:
private/evidence/2d-4c-part2/. No provider calls, real-database migration, gen-1/live
gateway access, protected-register edits or main merge occurred. AGENTS.md lookup
stayed inside the repository; no disposable checkout or venv symlink was created.

**Part 2 Gate C repair 1 (2026-10-17).** C1 is repaired at fixture setup:
one shared helper restores the complete requested trigger definitions/order after
unmutated seeding, then asserts the actual SQLite catalog. Reset regressions cover
normal/reversed order and dropped/mutated definitions. Actual order probes cover
14 modules / 25 fixture classes; all nine defeated reseeding owners are repaired,
including the two additional extraction-record fixtures found in the family audit.
C2 now distinguishes canonical, target and independent-validator byte identities
under `semantic_agreement`, with one optional reference per kind in both matrices.
Router and SQL target-to-validator selector mutants each have a separate surviving
byte-equal validated control, qualified branch traces and assertion-only killers.
Production and optional-reference scope are unchanged. Gate counts, per-module
catalog evidence, footprint and execution disclosures are retained in
private/evidence/2d-4c-p2-repair-1/COMPLETION.md.

#### 2d-4c part 3 — re-estimate (before code)

2026-10-17, on `gen2`, against accepted `89401a7`, `6c145ae` and repair
`927b32d`. Read the complete task, operator ruling, both continuations, this
section including the repair note, accepted admission/binding code, shared
`ddl_fixtures.restore_triggers`, and Astra's part-2 round-2 acceptance.
Repository-only AGENTS.md lookup found none. No production change is needed.

**Audit before code.** Receipt construction has four roots: raw
`store_fixtures.StoreTestCase.verify` (including `populate_every_table` history),
Router `test_router_commit.AuthorityTest.verification_receipt`, Router
`test_canonical_receipt_admission.ReceiptCase.document`, and quote
`test_governed_quotes.QuotesCase.receipt_document` (schema-example based).
`extraction_receipt_fixtures.seed/seed_validation/attach` supplies shared admitted
extractions, not detailed checks. Trace both local imports and module-level
imports; do not treat the small raw wrapper modules as independent fixtures.
The concrete audit list is:

- Canonical/acquisition/content: `test_canonical_receipt_admission`,
  `test_canonical_content_tiers`, `test_extraction_acquisitions`,
  `test_extraction_content_tiers`, `test_store_canonical_receipts`,
  `test_store_content_tiers`, `test_store_extraction_acquisitions`, and
  `test_store_extraction_content_tiers`.
- Quote/capture/verdict: `canonical_quotes_fixtures`, `test_governed_quotes`,
  `test_capture_support`, `test_quote_attention`, `test_verification_attention`,
  `test_store_governed_quotes`, `test_store_capture_support` and the raw
  adjudication/hold classes imported from the attention modules.
- Own/validated/promotion/attention: `test_own_extraction_receipts`,
  `test_validated_extraction_receipts`, `test_bound_extraction_support`,
  `test_extraction_attention`, `test_store_own_extraction_receipts`,
  `test_store_validated_extraction_receipts`, `test_store_bound_extraction_support`,
  plus `test_pending_extraction_support` (Router positives and raw historical
  unbound declarations). `independent_tier_fixtures` changes validation operands.
- Table/span controls: `test_table_availability`, `test_span_domain`,
  `test_exact_spans`, `test_store_table_availability`, `test_store_span_domain`,
  `test_store_exact_spans`; each has canonical/own/validated consumers.
- Global raw admission/promotion: `test_store_ddl_evidence.VerificationTest`,
  `ContractAdmittedSupportTest`, and `store_fixtures.verify` callers above.
  History/replacement/JSON consumers inherit `store_fixtures` through
  `test_store_history`, `test_store_json_rollout`, `test_store_json_completion`,
  `test_store_json_member_domain` and `test_store_observation_domain`.
- Already detailed: `test_detailed_check_receipts.ReferenceCases` and its raw
  wrapper `test_store_detailed_check_receipts`; retain explicit optional-reference,
  single-reference, legacy readback and byte-equal selector controls. These are
  historical/optional-admission experiments, not converted mandatory consumers.
  `test_store_fixture_order` transitively instantiates the raw receipt fixture.
- Non-positive matches: `test_detailed_checks`, `test_extraction_records`,
  `test_extraction_validations_v2`, `test_extractor_registry` assert no receipts;
  `router_fixtures`, `test_router_amendments`, `test_store_ddl_export` supply
  infrastructure or commit receipts. Frozen router-mixin snapshots and schema
  examples remain explicit historical structural controls, not admitted receipts.

The private static inventory retains **41 direct-match modules**, their owner
classes/functions and receipt locations, the complete import graph, and each
paired mutant's killers/controls. First-slice imports reach **16 modules**;
**133 directly affected mutants** require the complete `2D4ATTN`, `2D4B3B`,
`2D4B3E2OWN`, `2D4B3E2VAL`, `2D4B3E3` and `2D4C2` --only families. Recompute
this closure after edits. A receipt-free import is still included for gate
selection. Unconverted positive fixtures are pending, never relabeled historical.

**Honest full estimate: about 1,050 handwritten lines**, excluding documentation
and generated data: shared record/basis builders 150, Router canonical/quote/
span/table conversion 270, global raw conversion/isolation 230, extraction and
promotion wiring 80, admission/promotion/discrimination regressions 220, retained
private audit/trace drivers 100. This is well above 500; split and implement only
**part 3a, extraction consumer fixtures**, estimated **480 lines**: admitted
record helper 100, own/validated/promotion/attention wiring and explicit historical
controls 80, focused binding/promotion/operand tests 190, private audit/trace
checks 110. Stop after this coherent sub-part; the remaining audit groups belong
to part 3b and must be re-estimated before conversion.

Seed real attributed assessments through Router admission under unmutated DDL
before restoring the requested catalog with `restore_triggers`. Bind each kind's
performed outcome to the actual claim/source/spans/verifier and selected output;
retain evidence and explicit applicability reasons. Attach existing admitted
records without hidden writes at receipt submission, preserving rollback/replay
snapshots. Keep `/1` unbound/history/isolation probes explicit, and keep existing
byte-equal controls separate from distinct canonical/target/validator operand
experiments. Prove unchanged accepted promotions and paired-control reachability
with traces. Run every required gate and record counts/footprint/deviations in
private/evidence/2d-4c-part3/COMPLETION.md. Mandatory consumption and promotion
changes stay OFF; production code/DDL/pins remain untouched. A production need
would stop this dispatch. No trigger edit is planned.

**Part 3a implementation, 2026-10-17 (fixture conversion only).** The own and
validated receipt mixins, bound promotion mixin and inherited extraction-attention
fixture now supply `/2` receipts with real, admitted records for every performed
kind. This reaches seven existing Router/raw consumer classes in seven modules;
three raw wrappers inherit the change without edits. A test-only helper admits
all twelve kind/performed-outcome combinations through Router authentication,
retains exact assessment evidence and applicability reasons, and attaches existing
records without submission-time writes. Source, examined bytes, claim revision,
full spans and independent verifier remain bound by accepted production code.

Existing extraction refusal and unbound/corrupt promotion operands explicitly
remain `/1` historical isolation controls. Attention's canonical fallback
reattaches records, and changed unperformed summaries receive matching detailed
outcomes. Raw INSERTs now serialize receipt objects, spans and acquisition JSON
canonically, matching the already admitted reports. All assertions in the 58
existing edited-module test methods are unchanged; three bodies add explicit
fixture conversion calls. New regressions exercise retained evidence, performed
failure/exemption, all promotion tiers, distinct canonical/target/validator/
comparison bytes, optional and historical consumption, and requested catalogs
with reversal plus dropped/mutated definitions. Every reseeding owner still uses
`restore_triggers`; no production trigger is changed.

The final scope expansion selects **181 mutants in seven prefixes**, adding the
older `2D4-` family when completing the six directly affected generator families.
Qualified accepted-path traces cover **133/133 directly affected pairings**, using
20 distinct passing controls; bound-view controls record returned rows separately
from successful trigger entries and Python changed-line/direct-guard arcs. All
3,604 existing mutation-control records remain unchanged. Private evidence keeps
the complete import/control mapping and the converted/historical/pending audit.

Footprint: **263 handwritten repository additions / 10 removals**, plus **188
retained private Python driver lines**, including reused tracing infrastructure:
**451 additions against the 480-line slice estimate**, excluding documentation;
no generated repository data changes. Stopped attempts exposed overlong fixture
IDs and noncanonical raw JSON; the trace driver also needed view observations,
raw-control selection by target rather than filename, and tuple normalization
when reloading JSON. None is credited as a passing gate. No production change was
needed. **Part 3b remains pending**, as does part 4 mandatory consumption and
promotion activation; both activation changes remain OFF.

**Part 3a validated before implementation commit.** Full gen2-test passes
**4,206 tests, two existing skips**; trigger-order checks **334 triggers / 4,011
identical Store tests/subtests** in both orders; composition passes **six tests**.
The complete seven-prefix affected-family sweep kills **181/181 mutants**, all
with separate passing controls, over a green **1,061-test Store baseline**.
All eight static gates pass and are repeated after this final note. The unchanged
full trigger inventory has **zero uncovered** guards. Focused execution passes
110 tests plus the separately added performed-outcome regression (111 total).
All six code files retain the exact tested source hashes. Evidence, audit,
commits, gate logs, footprint and deviations are retained in
private/evidence/2d-4c-part3/COMPLETION.md. No provider call, real-database migration,
gen-1/runtime/8765 access, protected-register edit, main merge or disposable
checkout/venv symlink occurred. This completes **part 3a only**; stop here.

#### 2d-4c part 3b — re-estimate (before code)

2026-10-17, on `gen2` at `8cc01c2`. Read the entire task (constraints,
operator ruling and every continuation), this section including the part 3
audit and part 3a notes, accepted `9416fd6` helpers and Astra's first 3a review.
Repository-only AGENTS.md lookup found none. NB1 is a pending **positive**:
`AuthorityTest.test_a_producer_cannot_verify_its_own_work` ends with accepted
load-bearing support and must acquire admitted records while preserving its
four distinct authority refusals.

The prior 570-line remainder was subtraction, not a concrete implementation
estimate. Re-audit separates Router owners from raw owners: converting the
canonical base indiscriminately would change unfinished table/span and optional
reference experiments, and raw owners need authenticated bytes rather than
invented record IDs. **Remaining estimate: 970 handwritten lines**, excluding
documentation/generated data: canonical/acquisition/content Router wiring 100,
shared fixture isolation 120, authority NB1 30, quote/capture/verdict (including
raw adjudication/hold owners) 150, table/span operands 100, global raw admission/
promotion/history conversion 170, discrimination/promotion regressions 200,
private audit/trace drivers 100. This is well above 500; split again.

**Implement only part 3b: canonical/acquisition/content Router consumers plus
the authority-root positive**, estimated **470 handwritten additions**: explicit
converted Router owner and acquisition/content wiring 120, authenticated seeding
and requested-catalog restoration 70, NB1 authority conversion 30, binding/tier/
promotion/rollback/discrimination regressions 150, retained private audit/trace
drivers 100. Reuse `seed_checks`, `assessment_binding`, `attach_checks` and
`restore_triggers`; do not copy their implementation. An explicit converted
owner keeps unfinished consumers on their pending fixture, never reclassifies
them as historical. Seed before subject snapshots, under production DDL, then
restore the requested trigger catalog. Submission only attaches existing rows.

Concrete audit/disposition for this split:

- Convert `ReceiptTest`, `OtherAcquirerReceiptTest`, `ContentRouterTest`,
  `ExtractionRouterTest`, `ExtractionContentRouterTest`, and NB1's accepted
  authority control. Preserve their accepted tiers, replay/rollback and refusal
  assertions; prove canonical/own/validated promotions and distinct selected
  bytes in focused regressions. The extraction acquisition/content fixtures'
  misleading "pending" prose does not make their accepted receipts historical.
- Pending **part 3c**: `PendingRouterTest` (its bound accepted promotions),
  `TableRouterTest`, `SpanRouterTest`, `ExactSpanRouterTest`; quote root
  `QuotesCase`, `CanonicalQuotesCase`, `CaptureCase`, both attention owners and
  their raw wrappers/adjudication/hold classes; global `StoreTestCase.verify`,
  `VerificationTest`, `ContractAdmittedSupportTest`, raw canonical/content/
  acquisition/table/span owners and raw pending/history/JSON/replacement owners.
- Already converted part 3a: own/validated/bound-promotion/extraction-attention
  owners and raw wrappers. Keep their completed coverage intact.
- Retain explicit `/1` authority/acquisition refusal operands and existing legacy,
  optional-reference, frozen-mixin and schema examples as historical/structural
  controls. Pending positives above remain pending; no historical relabeling.

Recompute the full transitive import/control closure after edits, expand every
affected generator family, and qualify accepted paired-control traces. Run the
full gen2-test, trigger-order, composition and all eight static gates before the
implementation commit; retain full trigger inventory even though no trigger
change is planned. Wait for no user/system `gen2-landing-*` activity before heavy
runs. No snapshot is planned; any disposable venv must use `cp -a`.
Mandatory detailed consumption and promotion changes stay **OFF**. Production,
DDL and pins remain untouched; stop and report if production work is required.
Evidence: private/evidence/2d-4c-part3b/, including the full pending audit and
honest footprint/deviations. Stop after this slice; part 3c and part 4 remain.

**Part 3b implementation (fixture conversion only), 2026-10-17.** Six existing
consumer classes now use attributed `/2` positives: ReceiptTest,
OtherAcquirerReceiptTest, ContentRouterTest, ExtractionRouterTest,
ExtractionContentRouterTest and NB1's AuthorityTest accepted support. The first
five opt into AttributedReceiptCase/attributed_fixture; unfinished consumers keep
their explicit pending base fixture. Records are admitted through the existing
3a helpers, before subject snapshots; both new reseeding owners restore the
requested trigger definitions/order through `restore_triggers`. Receipt building
only selects existing records. Production, DDL, schema, hash pins and all 3,604
mutation-control records are unchanged; mandatory consumption/promotion changes
remain **OFF**.

The same-report/new-verifier positive exposed a fixture-ID collision: seed_checks
now includes the performing invocation in its deterministic fixture ID. Reports,
authenticated evidence and exact binding are unchanged. The canonical sender uses
the actual verifier invocation. The reused readback oracle now selects named
claim/source keys rather than depending on JSON member order. Authority's four
existing refusal operands and acquisition refusals remain explicit `/1` isolation
controls. All existing assertions in the 77 methods of edited modules survive.

Five new regressions cover nine method/tier promotion-and-rollback combinations,
three distinct replacement-verifier combinations, six historical/optional
promotions with an actually empty detailed-record store, NB1's retained evidence,
and both reseeding owners' exact reversed/dropped/mutated catalogs. The existing
six 3a regressions also pass, including distinct canonical/target/validator/
comparison bytes; ordinary byte-equal controls claim no selector discrimination.

**Audit correction and pending scope.** ContractWorld.verify in
`test_router_amendments` also admits genuine load-bearing supports via the
authority-root builder. Its ImpactTest compatible-work completion/promotion and
protocol-change fencing controls are pending positives, not infrastructure-only
or historical. The earlier part-3 audit description was too broad. This dispatch
selected NB1's own accepted control before code; carry these two additional
callers explicitly into part 3c alongside PendingRouterTest, table/span/exact,
quote/capture/verdict and global raw/history/JSON owners. Re-estimate part 3c
before code; this slice does not complete part 3 or activate part 4.

Footprint: **207 handwritten repository additions / 35 removals**, plus **235
retained private Python driver lines** (including reused infrastructure): **442
additions against the 470-line slice estimate**, excluding documentation and
generated evidence. No generated repository data changes. Private AUDIT.md and
the before/after AST inventories record all converted/historical/pending owners.
The initial regression run exposed the sender/oracle/catalog-setup errors above;
its failure log is retained without passing credit. Two overly broad tracing
attempts were interrupted and retained. Trace scope cuts the CommitCase import
edge that does not execute NB1, while the full affected-family gate retains all
1,164 directly affected IDs / 2,181 expanded IDs across 71 prefixes and 72 modules.
All **136/136 receipt-consumer pairings** qualify through 22 retained passing
controls; all six newly converted accepted controls also have direct fixture-line
and successful SQL-entry traces. The first explicit authority instrumentation
attempt failed catalog identity during setup; the final driver adopts production
DDL before restoring instrumentation with the accepted helper. That failed trace
attempt is retained without credit. The unchanged full inventory has **334
triggers, zero uncovered guards**.

**Part 3b validated before implementation commit.** Full gen2-test passes
**4,211 tests, two existing skips**, in 2,825.404 seconds. Trigger-order passes
**334 triggers / 4,034 identical Store tests/subtests** in both orders; the full
composition module passes **six tests**. The complete affected-family --only
sweep kills **2,181/2,181** mutants over green **1,066-test Store / 14 file-target
baselines**: 2,173 separate passing controls, three existing in-killer accepted
cases and five unchanged documented exceptions. All eight static gates pass and
are repeated after this note. All eight code files match their tested hashes.
Final counts, commits, source/trace audits and deviations are retained in
private/evidence/2d-4c-part3b/COMPLETION.md. No provider call, real-database
migration, gen-1/runtime/8765 access, protected-register edit, main merge or
manual disposable snapshot/venv symlink occurred. This completes **the selected
part 3b slice only**; part 3c conversion (including the two amendment positives)
and part 4 activation remain pending. Stop here.

#### 2d-4c part 3c — re-estimate (before code)

2026-10-17, on `gen2` at `3e87590`. Read the whole task, constraints,
operator ruling and every continuation; this entire section and all part 3
audit/implementation notes; accepted `9416fd6`/`1bfb9a9` fixtures and shared
helpers; and Astra's accepted part-3b review. Repository-only AGENTS.md lookup
found none. The remainder still needs a split; no pending positive becomes
historical to reduce the estimate.

**Concrete remaining estimate: 1,140 handwritten additions**, including retained
private drivers, excluding documentation/generated data: PendingRouter bound
claim and Router table/span/exact-span setup/wiring 160; raw table/span/exact-span
authenticated seeding and literal-JSON isolation 150; quote/capture/verdict and
raw adjudication/hold owners 180; global raw admission/promotion/history/
replacement/JSON owners 220; the two ContractWorld.verify amendment positives
50; independent binding/tier/promotion/catalog regressions 240; audit/trace/gate
drivers 140. Raw fixtures currently use literal artifact hashes; their conversion
requires authenticated bytes and Router admission, not invented record IDs.
Span fixtures also require separate admitted bindings for their different
accepted spans, including the exponent control. This is well above 500.

**Implement only the first coherent group set, part 3c: Router pending-bound,
table, span and exact-span consumers.** Estimate **495 additions**: scoped
AttributedReceiptCase/attributed_fixture opt-in and pre-snapshot seeding 90;
bound-claim setup and four consumer wiring changes 70; binding/promotion/tier/
span-discrimination/rollback/catalog regressions 100; retained private audit,
trace and gate drivers (including reused infrastructure) 235. Reuse seed_checks,
assessment_binding, attach_checks and restore_triggers without forking them.
Admission happens under unmutated DDL; restore the complete requested trigger
catalog before the subject runs. Receipt submission only selects admitted rows.
Malformed span probes keep their original defect and a separately bound accepted
control. Distinct accepted spans get distinct record IDs; ordinary byte-equal
method controls do not claim to distinguish source/target/validator bytes.
Retain the accepted distinct-output regression for that separate claim.

Audit disposition after this slice is planned as follows:

- Convert PendingRouterTest's four bound receipt/promotion/rollback paths and
  TableRouterTest, SpanRouterTest and ExactSpanRouterTest, including their paired
  accepted controls. Preserve the same accepted promotions and content tiers.
- Already converted: part 3a extraction/validation/bound-promotion/attention
  owners and raw wrappers; part 3b canonical/acquisition/content Router consumers
  and NB1 authority support. Preserve their accepted assertions and bindings.
- Still pending for **part 3d or later**: all raw table/span/exact-span owners;
  QuotesCase, CanonicalQuotesCase, CaptureCase, quote/verdict attention consumers
  and raw quote/capture/adjudication/hold owners; StoreTestCase.verify and
  populate_every_table, VerificationTest, ContractAdmittedSupportTest, raw
  canonical/content/acquisition/pending/history/replacement/JSON consumers; both
  ContractWorld.verify amendment callers (compatible completion/promotion and
  ImpactTest protocol-change fencing). None is credited as converted here.
- Existing explicit `/1` unbound/refusal/history, optional-reference experiments,
  frozen mixin snapshots and schema examples remain historical/structural
  controls. Raw pending declarations stay explicit unbound controls; their
  accepted canonical/distractor receipts remain pending conversion.

Recompute affected mutation families over the complete transitive import closure;
retain qualified predicate/control and direct converted-path traces. Run full
gen2-test, trigger-order, composition and all eight static gates before the
implementation commit. Check user/system landing units before heavy runs.
No snapshot is planned; any disposable venv must be copied with cp -a.
Production, DDL, schema and pins stay unchanged; stop if production work is needed.
Mandatory consumption and promotion changes stay **OFF**. Evidence and exact
remaining audit: private/evidence/2d-4c-part3c/COMPLETION.md. This split does not
finish part 3; stop after the selected Router group set.

**Part 3c implementation (selected Router group set), 2026-10-17.**
PendingRouterTest, TableRouterTest, SpanRouterTest and ExactSpanRouterTest now
opt into the accepted attributed fixture path. Bound claims and each accepted
span variant receive real Router-admitted records before subject snapshots;
submission only attaches existing rows. The manual borrowed-work/version table
owner also opts in. The shared record/binding helpers are reused unchanged, and
both new reseeding owners use restore_triggers after unmutated admission.
Production, DDL, schema, pins and all 3,604 mutation-control records are unchanged.
Mandatory consumption and promotion changes remain **OFF**.

Four existing Router classes cover 15 methods, 13 with accepted receipt controls.
All original assertions across the four edited modules' 18 existing methods
(including three unchanged raw PendingDDLTest methods) survive; the exponent
assertion adds its explicit decoded binding while retaining the same acceptance
and stored-exponent expectations. Malformed span/duplicate/NUL probes keep their
original defects and diagnostics. Distinct page, table, mixed and exponent spans
receive distinct records. Ordinary byte-equal method controls make no artifact
selector discrimination claim; the accepted four-distinct-hash 3a regression
remains the separate source/target/validator/comparison experiment.

Five new regressions exercise 39 accepted receipts, six bound promotions across
three methods/two tiers, three foreign-span refusals with matching accepted
controls, and both exact reversed/mutated/dropped requested catalogs. The accepted
independent readback oracle checks every kind's binding, retained authenticated
assessment evidence, verifier/producer separation and recording operation.
Two counterfactuals fail at assertions with zero errors: downgrading bound
receipts to `/1` (six failures), and collapsing distinct spans (nine failures).
An earlier span-downgrade probe produced KeyErrors and receives no evidence credit.

The 19-module transitive import/control closure selects 133 direct IDs, expanded
to 181 mutants in seven complete prefixes. All 181 are killed, with separate
passing controls, over a green 1,071-test Store/two file-target baseline.
All 133 predicate/control pairings qualify through 20 paired controls; five
additional converted controls have successful SQL-entry traces and independently
checked hits in the changed seeding/building functions. Full unchanged trigger
inventory: 334 installed, zero uncovered guards.

Footprint: **171 repository code additions / 29 removals**, plus **294 retained
private Python driver lines**, including reused infrastructure: **465 additions
against 495 estimated**, 30 below estimate, excluding documentation/generated
evidence. Wiring is 84/160 estimated, regressions 87/100, private drivers 294/235;
the private overrun is included, not excluded from the total. Initial discovery
imported TestCase classes and was interrupted; module
aliases prevent duplicate discovery. The next regression run exposed short
fixture IDs; those were corrected. A prematurely started gate run was stopped
and retained without full-gate credit. Five final new regressions and eight
retained regressions pass. Private AUDIT.md records all attempts and limits.

**Exactly what is still pending for part 3d or later:** raw table/span/exact-span
owners; quote/capture/verdict roots and consumers (including raw quote/capture/
adjudication owners and the independent hold-only owner audit); StoreTestCase.verify
and populate_every_table, raw admission/promotion/canonical/content/acquisition,
PendingDDLTest's accepted canonical/distractor receipts and history/replacement/JSON
consumers; both ContractWorld.verify amendment
positives (compatible-work completion/promotion and ImpactTest protocol-change
fencing). These remain pending positives, never historical relabelings. The
private inventory names their modules, classes and amendment methods. Existing
explicit `/1` unbound/refusal/history and optional-reference controls retain their
purposes. This slice does not finish part 3; part 4 activation also remains pending.
The fixture-order audit is already detailed through ReferenceCases' four
Router-admitted records; its import-closure coverage does not make it a pending
global-raw positive. No pending `/1` positive is reclassified by this correction.

**Part 3c validated before implementation commit.** Full gen2-test passes
**4,216 tests, two existing skips**, in 3,088.921 seconds. Trigger-order passes
**334 triggers / 4,062 identical Store tests and subtests** in both orders;
composition passes **six tests**. The complete affected-family sweep is
**181/181 killed**, each with a separate passing control; all eight static
gates pass and are repeated after this note. All five code files retain their
tested hashes. Commands, landing-unit checks, counts, traces, audit, footprint,
attempts and commits are retained in private/evidence/2d-4c-part3c/COMPLETION.md.
No provider call, real-database migration, gen-1/live-gateway access,
protected-register edit, private commit or main merge occurred. AGENTS.md lookup
stayed inside the repository; no manual disposable snapshot or venv symlink was
created. This completes **the selected Router slice only**. Stop here; part 3d
or later must convert the pending positives above, and part 4 remains OFF.

#### 2d-4c part 3d — re-estimate (before code)

2026-10-17, on `gen2` at `3d09787`. Read the whole task, constraints,
operator ruling and every continuation; all of §2d-4c including the part 3
audit/implementation notes; accepted `9416fd6`, `1bfb9a9`, `d140c23`, the
shared detailed/DDL helpers and explicit AttributedReceiptCase opt-in; and
Astra's accepted 3c review. Repository-only AGENTS.md lookup found none.
Valid bound support prevents a new missing-basis hold; it never clears an
existing hold. ExtractionAttentionTest retains the fenced-basis matrix.

**Remaining estimate: 1,090 handwritten additions**, excluding documentation
and generated evidence: raw table admission bridge/wiring 160; raw span/exact
literal bindings 170; quote/capture/verdict and raw adjudication 180; global
raw admission/promotion/canonical/content/acquisition/pending/history/
replacement/JSON 220; both ContractWorld.verify amendment positives 50;
independent regressions 170; retained audit/trace/gate drivers 140. The raw
owners still use literal hash labels and zero-duration leases; authenticated
record admission requires real examined bytes and a live verifier. This is
well above 500, so split again; no pending positive is relabelled historical.

**Implement only part 3d: the raw table owner group**, TableDDLTest,
ExtractionTableDDLTest and ValidatedTableDDLTest. Estimate **495 additions**:
raw-to-Router assessment bridge and authenticated examined bytes 95; scoped
raw-table wiring and preservation of refusal diagnostics 65; independent
binding/tier/promotion/rollback/catalog regressions 110; retained private
inventory/trace/gate drivers, including reused infrastructure, 225. Raw span
and exact-span subclasses explicitly stay pending on their existing base
path. This is a scope opt-in, following AttributedReceiptCase, not historical
reclassification. Stop after this coherent group set.

Reuse seed_checks, assessment_binding, attach_checks, historical_receipt and
restore_triggers; do not fork them. Admit all performed kinds/outcomes and
separate PAGE/TABLE/ordered mixed-span bindings through Router under unmutated
DDL before subject snapshots, then restore requested trigger definitions and
order. Raw INSERTs only select those admitted records. Preserve raw relational
content/acquisition counterfactuals and their diagnostics; their recorded
response bytes do not claim transport authentication. Authenticate the actual
examined source/output bytes independently. Ordinary byte-equal extraction
outputs claim no artifact-selector discrimination; keep the accepted distinct
source/target/validator/comparison experiment. Retain explicit /1 refusal and
legacy controls and the same accepted tiers/promotions. Every claimed pair
must have distinct operands and accepted paths must have traces.

**Exactly what remains pending after this slice:** raw SpanDDLTest,
ExtractionSpanDDLTest, ValidatedSpanDDLTest, ExactSpanDDLTest,
ExtractionExactSpanDDLTest and ValidatedExactSpanDDLTest; QuotesCase,
CanonicalQuotesCase, CaptureCase and their quote/capture/verdict attention
consumers and raw quote/capture/adjudication owners; StoreTestCase.verify and
populate_every_table, VerificationTest, ContractAdmittedSupportTest, raw
canonical/content/acquisition/extraction-content owners, PendingDDLTest's
accepted canonical/distractor receipts, and history/replacement/JSON/member/
observation consumers; both ImpactTest ContractWorld.verify amendment positives
(compatible-work completion/promotion and protocol-change fencing). HoldDDLTest
stays a hold-only owner. Already converted 3a/3b/3c consumers and explicit
historical/optional/schema controls retain their accepted purposes. Part 3
will remain incomplete; its final sub-part must supply the repository-wide
receipt-builder inventory showing no pending positive.

No production, DDL, schema or hash-pin change; stop and report if required.
Mandatory consumption and promotion changes stay **OFF**. Recompute full
transitive import/control closure and expand affected --only families. Before
the implementation commit run full gen2-test, trigger-order, composition and
all eight static gates; retain the unchanged full trigger inventory as well.
Wait for no user/system gen2-landing-* activity before heavy runs. Any disposable
venv uses cp -a. Evidence, exact audit/counts/footprint/deviations and COMPLETION.md:
private/evidence/2d-4c-part3d/. No private file is committed.

**Part 3d implementation (selected raw table group), 2026-10-17.**
TableDDLTest, ExtractionTableDDLTest and ValidatedTableDDLTest now consume `/2`
receipts with real Router-admitted assessments. A test-only bridge adopts the
same disposable raw store, makes its existing independent verifier live/running,
and aligns the queue revision with the raw operation history. Under unmutated
DDL it authenticates real examined bytes and retained assessment evidence through
the accepted seed_checks helper: four distinct PAGE/TABLE/ordered mixed/BEA
bindings, twelve performed-kind/outcome records each, 48 records per fixture.
restore_triggers restores the complete requested definitions/order before the
subject. Receipt insertion only selects existing records with attach_checks.
The helpers and AttributedReceiptCase opt-in remain unchanged; no implementation
is forked. SpanDDLTest's explicit opt-out keeps all six raw span/exact owners
pending, never reclassifies their positives as historical.

Raw acquisition response rows retain their relationship-counterfactual purpose:
they do not claim transport authentication or that varied responses actually hash
to the fixed examined artifact. The newly referenced examined source/output bytes
and retained assessment evidence are authenticated. Full-text promotion controls
also use response bytes equal to that artifact. Ordinary extraction outputs are
byte equal and claim no artifact-selector discrimination; the accepted 3a
distinct-output experiment remains the separate proof. The store binds recorded
relationships, not scientific truth. Explicit `/1` acquisition-diagnostic refusal
operands retain isolation; no accepted pending positive is moved to history.

All 13 original test method definitions (12 base methods and the validated
independent-target override) retain their assertions, except canonical JSON
serialization of the same mixed-span tuple. Four new regressions cover 42
accepted receipt writes (including six rolled-back captures), three full-text
support promotions, three foreign-span refusals with complete-state snapshots,
three truthful unperformed receipts/promotion refusals and three exact catalog
comparisons. Distinct spans receive disjoint records; tiers remain explicit.
Downgrade-to-/1 and collapsed-span counterfactuals each produce nine assertion
failures and zero errors. The first regression attempt guessed a promotion
message; its three regex failures are retained without passing credit, and the
final assertion uses the existing V-4 diagnostic.

The nine-module transitive fixture closure selects 52 direct mutant IDs, expanded
to 54 in the three complete 2D4B3D/2D4B3DR1/2D4B3DR2 prefixes. All 54 are killed
with passing paired controls over green 1,075-Store/one-file-target baselines.
All 148 affected predicate/control pairings qualify through 15 passing controls;
four direct converted controls also trace changed fixture lines and successful
SQL entries, including promotion. All 3,604 mutation-control records are unchanged.
The complete unchanged inventory has 334 installed triggers, zero uncovered.

Footprint: **188 repository code additions / nine removals**, plus **240 retained
private Python driver lines**, including reused infrastructure: **428 additions
against 495 estimated**, 67 under, excluding documentation/generated evidence.
Wiring/bridge is 88 against 160, regressions 100 against 110, private drivers 240
against 225. The documentation-only pre-code estimate commit preceded functional
gates; required functional gates cover the implementation candidate before its
commit. Evidence preserves that timing rather than claiming a pre-code test run.
Production, DDL, schema, pins and promotion policy are unchanged. Mandatory
consumption/promotion activation remains **OFF**. No production need was found.

**Exactly what is still pending for part 3e or later:** the six raw span/exact
owners; quote/capture/verdict roots/attention consumers and raw quote/capture/
adjudication owners; StoreTestCase.verify/populate_every_table, VerificationTest,
ContractAdmittedSupportTest, raw canonical/content/acquisition/extraction-content,
PendingDDLTest's accepted canonical/distractor receipts, history/replacement/JSON/
member/observation consumers; both ImpactTest ContractWorld.verify positives
(compatible-work completion/promotion and protocol-change fencing). HoldDDLTest
remains hold-only. The private AUDIT.md names all classes/modules/callers. Part 3
is incomplete; its final sub-part must inventory all receipt-builder call sites
and show no pending positive. This slice stops after the raw table group.

**Follow-up constraint for the pending span audit.** A validation-time probe of
the existing canonical helper refuses the raw span/exact-span accepted integer
operands 9007199254740993 and 9223372036854775809. The next pre-code audit must
resolve their exact expression without rounding or silently relabelling pending
positives historical; this limited probe does not exhaust fixture expressions
or establish that production must change. The selected raw table group has no
such operand. No production change was needed or attempted here. Exact probe
results are retained in private/evidence/2d-4c-part3d/pending-precision-audit.json.

**Reading-record correction.** Initial long output truncated some earlier part-2
notes; targeted rereads completed them during validation. The complete task,
all part-3 audit/implementation notes, accepted fixture code and named 3c review
were read before code. Evidence discloses this timing rather than treating the
initial truncated output as a complete read of every earlier note.

**Part 3d validated before implementation commit.** Full gen2-test passes
**4,220 tests, two existing skips**, in **3,213.458 seconds**. Trigger-order
passes **334 triggers / 4,084 identical Store tests/subtests**; full composition
passes **six tests**. The complete affected-family sweep kills **54/54** mutants,
all with passing paired controls, over green **1,075-Store/one-file-target**
baselines. All eight static gates pass and are repeated after this note. All four
code files retain their tested hashes. Commands, source/audit/trace inventories,
counts, footprint, deviations and commits are retained in
private/evidence/2d-4c-part3d/COMPLETION.md. No provider call, real-database
migration, gen-1/live-gateway access, protected-register edit, private commit,
push or main merge occurred. AGENTS.md lookup stayed inside the repository;
no manual disposable snapshot or venv symlink was created. This completes the
selected raw table group only; the pending groups and precision constraint above
remain for the next pre-code audit. Part 4 stays **OFF**. Stop after this slice.

#### 2d-4c part 3e — re-estimate (before code)

2026-10-17, on `gen2` at `880c020`. Read the whole task, Constraints,
operator ruling and every continuation, including the OPEN OPERATOR DECISION;
all of this section and its part 3 audit/implementation notes; accepted
`9416fd6`, `1bfb9a9`, `d140c23`, `1faacfb` and their shared fixtures; and
Astra's complete 3d review. Repository-only AGENTS.md lookup found none.
The precision gap is an open production-domain decision: no rounding, domain
narrowing or activation is authorized here.

**Remaining estimate: 980 handwritten additions**, excluding documentation
and generated evidence: Router quote/capture/verdict admission and binding
wiring 115; raw quote/capture/adjudication authenticated setup 130; global raw
admission/promotion/canonical/content/acquisition/pending/history/replacement/
JSON/member/observation conversion 200; both amendment positives 45; focused
binding/promotion/attention/catalog regressions 150; retained audit/trace/gate
drivers 270; six raw span/exact owners 70 (provisional, blocked by the operator
decision, not an implementable estimate). The actionable remainder is 910,
well above 500. **Split again; implement only the Router quote/capture/verdict
group in part 3e**, estimated **495 additions**: wiring 115, independent
binding/promotion/attention/catalog regressions 110, retained private drivers
270, including reused infrastructure. Stop after this coherent group set.

Convert CanonicalQuotesCase's admitted quote root and the inherited CaptureCase,
CaptureTest/RouterGuardTest, quote AttentionCase/AttentionTest/SharedOwnerTest/
RouterGuardTest, and verdict AttentionCase/AttentionTest/SharedOwnerTest.
AdmissionTest's accepted extraction receipt uses CanonicalQuotesCase too.
Bare QuotesCase has only receipt refusals; keep those explicit `/1` isolation
controls, and preserve quote-only tests. No pending positive becomes historical.

Reuse seed_checks, assessment_binding, attach_checks and restore_triggers.
Admit real assessments under unmutated DDL before receipt snapshots, including
each distinct claim revision and ordered single/multiple-span binding. Building
or submitting a receipt only selects admitted records. After reseeding, restore
the exact requested trigger definitions/order, including subject-local drops.
Reattach after a legitimate revision/span/method/outcome change; explicit `/1`
refusals continue isolating the original guard. Keep the same promotions, full
text tier, holds, replay/conflict and rollback behavior. Distinct revisions and
span arrays must consume disjoint record sets. Ordinary byte-equal extraction
controls claim no artifact-selector discrimination; the accepted distinct-output
experiment retains that separate responsibility.

**Exactly what remains pending after this slice:** raw quote DDLTest,
CaptureDDLTest and AdjudicationDDLTest (HoldDDLTest stays hold-only);
StoreTestCase.verify/populate_every_table, VerificationTest,
ContractAdmittedSupportTest, raw canonical/content/acquisition/extraction-content
owners, PendingDDLTest's accepted canonical/distractor receipts, all raw
history/replacement/JSON/member/observation consumers; both ImpactTest callers
of ContractWorld.verify (compatible completion/promotion and protocol fencing).
Also pending, **blocked by the operator decision and untouched**: SpanDDLTest,
ExtractionSpanDDLTest, ValidatedSpanDDLTest, ExactSpanDDLTest,
ExtractionExactSpanDDLTest and ValidatedExactSpanDDLTest. Previously converted
owners and explicit historical/optional/schema controls retain their purposes.

Back the dispositions with a repository-wide receipt-builder call-site inventory
and full transitive import/control closure. Run full gen2-test, trigger-order,
composition, every affected complete --only family and the eight static gates
before the implementation commit; retain passing control traces and unchanged
trigger inventory. Wait for no active user/system gen2-landing-* units before
heavy runs. Any disposable venv is copied with cp -a. No production, DDL, schema
or pin change; stop and report a new representability gap or production need.
Mandatory consumption and promotion changes remain **OFF**; part 4 is blocked.
Evidence and exact pending inventory: private/evidence/2d-4c-part3e/COMPLETION.md.
This documentation-only estimate commit precedes implementation and its gates.

**Part 3e implementation (selected Router quote/capture/verdict group),
2026-10-17.** CanonicalQuotesCase now seeds authenticated attributed assessments
under unmutated DDL using the accepted helpers. CaptureCase seeds distinct
single/mixed-span bindings for each new claim revision, then restores the exact
requested trigger definitions/order, including subject-local drops. Receipt
building only selects admitted records. The four fixture layers reach six
concrete classes with accepted receipts: AdmissionTest, CaptureTest and its
RouterGuardTest, quote AttentionTest, and verdict AttentionTest/SharedOwnerTest.
Quote-only and refusal-only consumers preserve their roles. Explicit `/1`
capture/adjudication refusal operands retain the original guard isolation;
no pending positive has been relabelled historical.

All 132 original assertion-call ASTs in the five edited existing files survive
unchanged. Five new regressions cover 15 accepted receipt writes, six full-text
promotions, foreign-revision binding refusal with substantive-state preservation,
truthful unperformed attention without invented references, and three requested
trigger-catalog comparisons. Two capture owners also preserve subject-local
drops across later reseeding. Revisions 2/3 and single/ordered mixed spans use
three disjoint four-record sets. Existing hold, replay and rollback assertions
remain. Downgrading to `/1` causes four assertion failures; collapsing spans
causes one, both with zero errors. These are negative experiments, not green
application tests. Byte-equal ordinary extraction outputs claim no artifact
selector discrimination; the accepted distinct-output experiment is unchanged.

The six-module transitive fixture closure selects 54 directly affected IDs,
expanded to 526 mutants in 32 complete prefixes. All 526 are killed: 525 have
separate passing controls and one retains its existing in-killer accepted case,
over green 1,080-Store/five-file-target baselines. All 54 directly affected
predicate/control pairings qualify through 23 passing controls. Seven explicit
converted paths also have changed-fixture-function hits and successful SQL
entries. The schema control records the actual loaded JSON schema and accepted
validation call. All 3,604 mutation-control records remain unchanged; the full
unchanged trigger inventory is 334 installed, zero uncovered.

The repository-wide inventory retains 256 textual matches in 62 files, plus
55 candidate test modules with enclosing symbols and the complete test import
graph; 285 candidate builder calls are retained explicitly across 45 modules. Adding the population-root search exposed eight modules missed by the
receipt-name-only scan. The pending global group explicitly includes the
population setups in branch-window, obligation, registry, semantic, lifecycle,
source-artifact, JSON rollout and JSON member tests; none is credited as
converted. ObservationDomainTest writes observations, no verification receipts;
HoldDDLTest remains hold-only. These are non-receipt classifications, not
historical relabelling of positives. The private inventory lists all 30 generated
JSON rollout/completion owner names as pending population consumers.

**Exactly what remains pending:** the six untouched raw SpanDDLTest/
ExtractionSpanDDLTest/ValidatedSpanDDLTest and ExactSpanDDLTest/
ExtractionExactSpanDDLTest/ValidatedExactSpanDDLTest owners, **blocked by the
OPEN OPERATOR DECISION**; raw quote DDLTest, CaptureDDLTest and
AdjudicationDDLTest; StoreTestCase.verify/populate_every_table, VerificationTest,
ContractAdmittedSupportTest, raw canonical/content/acquisition/extraction-content
owners, PendingDDLTest's accepted canonical/distractor receipts and every
history/replacement/JSON/member/population consumer listed in the private
AUDIT.md and COMPLETION.md; both ImpactTest ContractWorld.verify amendment
positives (compatible completion/promotion and protocol-change fencing).
No production, DDL, schema, pins or promotion policy changed. Mandatory
consumption and promotion changes stay **OFF**; part 4 remains blocked.

Footprint: **158 repository code additions / nine removals**, plus **295
retained private Python driver lines**, including reused infrastructure:
**453 additions against 495 estimated**, 42 under, excluding documentation and
generated evidence. Wiring is 48/115, regressions 110/110, private drivers
295/270. The documentation-only estimate commit preceded code and functional
gates. Initial focused/regression runs passed. Trace-only repairs addressed
instrumentation before Store adoption, JSON-schema observation and fragment
lookup; superseded logs are retained without passing credit. No repository code
changed during those repairs. Direct older design-authority/V-4/V-8 rereads were
completed during validation, after code; required task/dossier/accepted-fixture/
3d-review reads preceded code. No production need or new representability gap
was found in the selected group. Stop after this split; part 3 is incomplete.

**Part 3e validated before implementation commit.** Full gen2-test passes
**4,225 tests, two existing skips**, in **3,241.873 seconds**. Trigger-order
passes **334 installed triggers / 4,098 identical Store tests/subtests**;
composition passes **six tests**; affected complete families kill **526/526**
mutants with the controls/baselines described above. All eight static gates pass
and are repeated after this note. All six code files retain their tested hashes.
Evidence, exact pending owners, inventories, attempts, counts, footprint and
commits: private/evidence/2d-4c-part3e/COMPLETION.md. No provider calls, real-database
migration, gen-1/live-service/8765 access, protected-register edit, private commit,
push or main merge occurred. AGENTS.md lookup stayed inside the repository;
no manual disposable snapshot or venv symlink was created. This completes only
the selected Router group; raw/global/amendment positives remain pending and
the six raw-span owners plus part 4 remain blocked by the operator decision.


#### 2d-4c span-offset cap — re-estimate (before code)

2026-10-18, branch `gen2`. Read the entire task, both operator rulings and
all continuations; this section and the accepted 2d-4b3d exact span-domain
notes; SQL 21/32/37, C-13, boundary.py and Astra's complete 3d review.
Repository-only AGENTS.md lookup found none. The 2026-10-18 operator ruling
amends the formerly unbounded span domain and settles NB1: start/end values
are at most 9,007,199,254,740,991, with no rounding and no live migration.

Estimate **495 handwritten additions**, including retained private drivers:
ordered replacement guards 180 (including about 140 copied existing guard
lines), schema/Router admission 25, fixture turnover 25, boundary/parity and
exact-binding tests 145, paired predicate mutants/registration 40, private
scope/inventory/trace/gate drivers 80. Documentation, generated controls and
the two hash pins are additional. This is one coherent production slice;
re-estimate and split before expanding materially beyond this budget.

Files: new `gen2/store/schema/38-span-offset-cap.sql` and `order.txt`;
`gen2/schema/verification-receipt.schema.json` (also supplies detailed-record
cited/context spans and outcome spans by reference); `gen2/router/boundary.py`
and `detailed_checks.py`; existing raw/Router span and exact-span test files;
new span-cap test modules and `tools/gen2_mutants/span_cap.py`; inventory and
control registration/data; both DDL/catalog hash pins. Quote-check offsets
already have the same schema maximum and byte-range admission. Locator values
are schema strings, not numeric offsets: numeric locator inputs stay refusals,
and digit strings remain labels. No invented numeric locator representation.

Replace the two installed receipt/detailed-record span guards through ordered
DDL, preserving their names, decoded-name rules, exact integrality/minima,
locator domain and diagnostics. Compare preserved decimal numeral text by its
normalized significant-digit length and lexicographic value against the cap;
never convert offsets to REAL or round them. Schema maxima and independent
Router checks cover receipt spans and both assessment arrays. Existing
above-cap positives become boundary refusals; exact-limit controls replace
their accepted role without historical relabeling.

Prove the literal matrix (limit-1, limit, limit+1, both NB1 values, negative,
zero, decimal/exponent and extreme-exponent cases) in schemas, Router and raw
DDL, across all three receipt methods and both trigger orders. Store-admitted
spans must parse under C-13 and bind exactly to an admitted detailed record.
Reseeding uses restore_triggers. Add separate passing predicate controls and
control-path traces. Run full gen2-test, trigger-order, composition, complete
affected --only families over transitive imports, full uncovered-trigger
inventory, gen2-gateway, all static gates, and repin both hashes. Check user
and system landing units before heavy runs; copy any snapshot venv with cp -a.
Evidence and COMPLETION.md: private/evidence/2d-4c-cap/. Mandatory consumption
and promotion changes remain OFF; remaining part-3 conversion is separate.

**Span-offset cap implementation, 2026-10-18–19.** The operator's 2026-10-18
ruling now caps receipt and assessment start/end values at 9,007,199,254,740,991.
SQL 38 replaces the installed receipt and detailed span guards with explicit
successors v4 and spans_v2, preserving decoded member sets, exact integrality,
minima, locator strings and existing relationships. Accepted SQL 01–37 is
unchanged. Preserved numeral text is compared by decimal magnitude and digits;
no offset is cast to REAL or rounded. New raw link and quote offset guards
cover the other numeric admission locations. Quote end>start already bounds
start once end is capped. No JSON columns or classifications were added;
both ordered-DDL and SQLite-catalog hashes are repinned.

The receipt schema's maxima also cover both receipt versions, detailed cited
and context spans, and outcome link spans through their existing references.
Router receipt admission and detailed authentication independently enforce the
same bound. Quote operands already have schema maxima and byte-range checking.
Numeric locator values remain invalid; digit strings remain labels. Above-cap
span/exponent positives become explicit refusals, and exact-limit controls
retain acceptance and authenticated attributed-record binding. Mandatory
consumption and promotion activation stay OFF. The six raw span owners are
unblocked for subsequent part-3 conversion, not converted by this cap slice.

The complete literal matrix runs through schemas, actual staged Router
commits and raw SQL under full requested catalogs: both receipt versions,
normal/reversed trigger order, all three methods and both assessment arrays.
There are 48 passing proof test invocations, 3,456 literal verdict checks and
12 authenticated exact-limit binding controls. Every accepted raw matrix row
passes the production C-13 parser; the accompanying integer-domain argument
establishes exact canonical representability throughout the amended offset
interval. This does not claim raw SQLite enforces every unrelated canonical
JSON lexical restriction. Reseeding uses restore_triggers.

All 11 new predicate mutants have separate passing controls and qualified
control-path traces. All 3,604 existing control records remain unchanged.
The transitive affected-family audit conservatively includes every DDL target,
selecting 2,565 mutants in complete families. Full installed-trigger inventory:
336 installed, zero uncovered. Successor names keep the existing mutation
harness's scopes unambiguous; the inherited preservation/isolation oracles and
mutant selectors now follow the installed successors. The preservation oracle
continues comparing the remaining guard with accepted SQL 21 independently.

Footprint: 491 non-generated repository additions / 22 removals, including all
copied SQL, plus 123 retained private Python driver lines: 614 additions against
495 estimated. Full version/order proof instrumentation, auxiliary raw numeric
admission coverage and successor catalog/oracle integration account for the
119-line overrun. No additional 2d-4c implementation part was activated.
Superseded attempts remain in evidence without passing credit: the initial
one-line registration size overflow; a fractional-tail cap omission found by
the auxiliary test; a stale guard-preservation oracle; and duplicate same-name
mutation scopes/schema-target loading. Final gates use the final source hashes.
Validation counts and exact commands: private/evidence/2d-4c-cap/COMPLETION.md.

No provider calls, real-database migration, Gen-1/runtime/8765 access,
protected-register edits, private commit, push or main merge occurred. Lookup
of AGENTS.md stayed inside this repository. No manual disposable snapshot or
venv symlink was created. This completes only the span-offset cap production
slice; remaining part-3 conversion and mandatory-consumption work stay pending.

**Span-offset cap validated before implementation commit, 2026-10-19.**
Full gen2-test passes **4,249 tests, two existing skips**, in 3,350.758 seconds.
Trigger-order passes **336 installed triggers / 4,563 identical Store tests
and subtests**; composition passes **six tests**. The affected complete-family
sweep kills **2,565/2,565** mutants over green **1,099-Store / 22 file-target
baselines**: 2,552 separate passing controls, nine existing accepted cases in
killers and four unchanged documented exceptions. The gateway's offline and
throwaway-PostgreSQL suites pass, with **413/413** gateway mutants killed.
All eight static gates pass; SQLite compatibility and source-catalog checks
also pass. The static gates are repeated after this note. Evidence, final
hashes, attempts, footprint and commits are retained in the private cap
COMPLETION.md. The cap slice is complete; mandatory consumption remains OFF.

### 2d-4c span-offset cap repair-1: pre-code estimate (2026-10-19)

Read the full task and continuations, both operator rulings, Astra's round-1
report and its independent/staged evidence, SQL 38 at f19725a and the retained
cap proof/completion, canonical.py and C-13. B1 requires an additive raw-link
string-value guard; numeric locator values are refused, including values below
the cap, while digit-string labels remain accepted. B2 requires replacing the
Decimal-capacity-dependent comparison with exact decimal significand/exponent
comparison against the existing float representation. Compare preserved digits
and exponent text without expanding powers or parsing unbounded exponents;
zero significands are exact for every exponent. Preserve the existing parser's
accepted decimal equivalence, float result, canonical bytes and hashes.

Estimate **about 390 handwritten lines**: ordered SQL/order/pins 20; canonical
comparison 45; independent numeral oracle and hash-compatibility regressions
95; locator schema/Router/raw and version/order parity tests 125; paired mutants,
control traces and private proof/scope drivers 105. Documentation and generated
controls/pins are additional. This is one coherent repair below the split
threshold; no fixture-conversion or mandatory-consumption phase is activated.

Regress both receipt versions, all six raw span owners, both detailed arrays
and both trigger orders, including extreme signed zero, nonzero underflow,
overflow and inexact numerals. Preserve hashes across the existing RFC, portal,
ECMAScript and span numeral catalogs using the prior acceptance oracle. Add a
separate accepted string-label control for the new raw predicate. Run full
 gen2-test, trigger-order, composition, complete affected --only families using
transitive canonical imports, full uncovered-trigger inventory, gen2-gateway
and the required static gates; repin both hashes. Heavy runs wait for no user
or system gen2-landing-* unit; snapshot venvs use cp -a. Evidence and resumable
PROGRESS.md stay under private/evidence/2d-4c-cap-repair-1/. No Gen-1, provider,
real-database migration, protected-register edit, private commit, push or main
merge is authorized.

**Span-offset cap repair-1 implementation, 2026-10-19.** B1 is repaired by
additive SQL 39: every raw link locator value must be JSON text. Numeric
values below, at and above the cap, including decimal/exponent forms, refuse;
over-limit digit-string labels remain accepted and retained exactly. SQL
01–38 is byte-unchanged. No JSON column was added; both ordered-DDL and parsed
SQLite-catalog pins are repinned. Existing immutability and member-name guards
remain installed. The isolated ClaimSpansTest member-name fixture excludes
only the new semantic guard when appending its arbitrary object probes;
full-catalog numeric-locator tests independently enforce the new predicate.

B2 is repaired at canonical._exact_float. Normalize the sign, significant
digits and decimal-power adjustment, then compare the submitted exponent as
text against the bounded exponent derived from repr(value). No submitted
exponent is converted to int, no power is expanded, and no Decimal capacity
limits participate. An all-zero significand is exact signed zero for every
exponent; nonzero underflow, overflow and precision loss remain refusals.
The existing decimal-equivalence policy, float result, JCS bytes, hash contract
and C-13 text are preserved. A legacy-parser oracle over the existing RFC,
portal, ECMAScript and span numeral catalogs checks every prior accepted
numeral's identical canonical bytes and SHA-256. Signed extreme zero and a
5,000-digit exponent have explicit regressions.

The expanded independent rational offset oracle covers 30 literal spellings.
Both receipt versions, all six raw owners, all three methods, both assessment
arrays and both full trigger orders pass 60 proof invocations. Astra's separate
38-numeral audit now has zero numeric-domain and C-13 parser-domain mismatches
across 2,538 observations; numeric locators agree with the string schema.
All 14 cap mutants are assertion-killed with separate passing controls; all
16 new/retained changed pairings have qualified traces. The two older R1
mutants now target the replacement comparison. All 3,615 prior control records
are unchanged. Full uncovered-trigger inventory: 337 installed, zero uncovered.

The canonical import closure is broad, so the complete --only selection is a
conservative superset containing every mutation family. Private evidence retains
scope reasons, source hashes, exact commands/exits, complete logs and resumable
progress under private/evidence/2d-4c-cap-repair-1/. First attempts are disclosed
without passing credit: the zero mutant initially caused a test error (fixed
to assert refusal), and the raw JSON baseline exposed the member-name fixture's
semantic isolation requirement. The earlier full test/order runs were stopped
for that fixture fix; final engine gates use the repaired source.

Footprint: 195 non-generated repository additions / 19 removals plus 290 retained
private driver lines, totaling 485 additions against 390 estimated. The extra
95 lines cover independent replay, full version/order proof, conservative scope
and the final gate driver after fixture isolation repair; this remains below
the approximate split threshold. Mandatory consumption and promotion activation
stay OFF. No remaining positive fixture was relabelled historical. No provider
calls, real-database migrations, Gen-1 access, protected-register edits, private
commit, push or main merge. AGENTS.md lookup stayed in the repository. No manual
snapshot or venv symlink was created.

**Repair-1 validation before implementation commit.** Full gen2-test passes
4,256 tests with two existing skips (3,324.686 test seconds). Trigger-order
passes 337 installed triggers and 4,693 identical Store tests/subtests;
composition passes six tests. The complete-family --only sweep kills
3,618/3,618 mutants, with 3,601 separate passing controls and green baselines
of 1,101 Store tests and 26 file targets. Gateway passes both 1,540-test runs
and kills 413/413 mutants. The eight static gates, SQLite compatibility and
source-catalog checks pass; static checks are repeated after this note.
No unresolved repair-1 issue remains. Completion evidence records exact
commands, exits, source/pin checks, attempts, footprint and commit identities.

**DEBT-039 plan, 2026-10-19.** Replace scheduler-dependent gateway-client
test time with the existing VirtualTime clock, mechanically moved with rope.
Use stdlib mock at blocking socket boundaries for exchange-time arithmetic;
retain real loopback HTTP/TLS route witnesses. Production source stays byte
identical. Estimated 450 added/changed handwritten lines across test helpers,
deadline tests and this dossier; no new runtime dependency or service wiring.
Audit all gen2/gateway deadline tests, repeat affected suites under deliberate
CPU load, run loaded mutation baselines and paired deadline/redirect mutants,
then all task gates. Evidence and resumable steps live in
private/evidence/debt-039/ outside this repository.

**DEBT-039 implementation and re-estimate.** The family cause was mixing
short real deadlines with fake/shortened sleeps and scheduled wire arrivals.
VirtualTime now drives the deadline assertions; stdlib mocks script blocking
socket time using the socket's actual armed budget. Real route, token and TLS
certificate witnesses remain. The complete route setup includes the direct
one-second transport calls. Ownership, Vault failure classification and batch
overlap use the same controlled-time or event-based approach. No timeout was
raised, no dependency added, and all 119 production Python files and real-clock
defaults remain byte-identical. Production stays at 13,449 engine lines and
12,256 gateway lines.

Re-estimate: 391 additions / 289 removals including final validation
notes, versus the initial 450 added/changed-line estimate. The wider audit
includes the Vault/batch races and all direct route budgets; most removals
replace wall-clock fixtures. Rope moved the 21-line clock unchanged; the new
socket/clock fixture is 111 lines. No custom equivalence checker was built.
Eight complete final-source loaded pairs pass (1,328 client and 48 gateway
cases), with two more passing pairs finishing after load ended. The loaded
mutation run passes its 1,101-test Store and child-tree baselines and kills
165/165 mutants with all paired controls passing, including broken deadlines
and followed redirects. Existing trace/choose requalifies all 143 Python-target
controls without changing pairings. Accepted replay is EQUIVALENT: 31 successful tests in each of four runs,
258 calls and 159 immediate readable store snapshots, zero unresolved. An
initial nonexistent composition-module selector produced equal import errors;
those recordings were discarded and the corrected runs checked independently
for zero failures/errors. The replay tooling itself is unchanged.

**DEBT-039 validation before implementation commit.** Full gen2-test passes
4,256 tests with two existing skips (3,290.671 test seconds). Trigger-order
passes 337 triggers and 4,693 identical Store tests/subtests; composition passes
six tests. Gateway passes both 1,540-test runs on the prescribed no-DB and
disposable-DB paths and kills 413/413 mutants, none invalid or unrun. The eight
static gates, SQLite compatibility and generated-catalog checks pass with no
metrics regression or new exemption. Interrupted/incorrect-command attempts
are retained without passing credit in private/evidence/debt-039/COMPLETION.md.
Runtime code, service wiring and production budgets remain unchanged.


#### 2d-4c part 3f — re-estimate (before code)

2026-10-19, branch `gen2`, starting at `7138dd6`. Read the whole task,
Constraints, both operator rulings and every continuation; this section's
part 3 audits/implementation and span-cap notes; accepted `9416fd6`,
`1bfb9a9`, `d140c23`, `1faacfb`, `2bf8bbe`, `f19725a`, `04c7af7` and
shared detailed/raw/DDL fixture helpers; Astra's complete 3e review. Repository-
only AGENTS.md lookup found none. The adopted cap and canonical exact-zero
repair are implemented and accepted: **all six raw span owners are unblocked**.
The dated OPEN OPERATOR DECISION summaries above are historical chronology,
not the active status; no second cap decision or implementation is pending.

**Remaining estimate: 900 handwritten additions**, including retained private
drivers, excluding documentation/generated evidence: six raw span/exact owners
and literal/canonical pairing 100; raw quote/capture/adjudication 130; global
raw admission/population/canonical/content/acquisition/pending/history/JSON
conversion 200; both amendment positives 45; independent binding/promotion/
rollback/catalog regressions 160; retained audit/trace/gate drivers 265.
This is well above 500; split again. **Implement only part 3f: the six raw
span/exact owners**, estimated **495 additions**: wiring and literal pairing
100, independent regressions 130, retained private drivers 265. Stop after
this coherent group; no pending positive becomes historical to fit the budget.

Selected owners: test_store_span_domain's SpanDDLTest, ExtractionSpanDDLTest,
ValidatedSpanDDLTest and test_store_exact_spans's ExactSpanDDLTest,
ExtractionExactSpanDDLTest, ValidatedExactSpanDDLTest. Reuse RawAssessmentFixture,
seed_checks, assessment_binding, attach_checks, historical_receipt and
restore_triggers. Admit real evidence and examined bytes through Router under
unmutated DDL before subject snapshots, then restore requested definitions/order
and the existing subject-local omissions. Distinct complete ordered spans,
locator strings, exact-limit and exact-zero values get distinct bindings.
Ordinary extraction outputs remain byte equal and claim no selector discrimination;
the accepted distinct-output regression retains that separate responsibility.

SQL 37 compares serialized span arrays, while Router admission canonicalizes
reports. Preserve literal raw numeric/name guard experiments as explicit /1
compatibility/refusal operands; pair **every accepted value** with its /2
canonical receipt and real admitted records. A /1 literal probe is rolled back
before retaining the /2 positive. Thus no pending accepted value is relabeled
historical and no raw numeral guard is silently bypassed by normalization.
Former over-cap operands remain refusals under the accepted ruling. Receipt
construction selects existing records only; no assessment creation or repair
occurs at submission. Preserve accepted tiers, promotions and rollback/conflict.

**Exactly what stays pending for part 3g or later:** raw quote DDLTest in
 test_store_governed_quotes, CaptureDDLTest in test_store_capture_support,
AdjudicationDDLTest in test_quote_attention (HoldDDLTest remains hold-only);
StoreTestCase.verify/populate_every_table, VerificationTest and
ContractAdmittedSupportTest; CanonicalDDLTest, ContentDDLTest, ExtractionDDLTest,
ExtractionContentDDLTest, ValidatedContentDDLTest, PendingDDLTest's accepted
canonical/distractor receipts; EveryTableSweepTest and RecordIdentityTest;
branch-window, obligation, registry, semantic, lifecycle and source-artifact
population consumers; QuoteTest in test_store_json_member_domain, all eight
RolloutPairs and 22 CompletionPairs generated owners; both ImpactTest callers
of ContractWorld.verify (compatible completion/promotion and protocol fencing).
ObservationDomainTest writes observations and no verification receipt. Already
converted 3a–3e owners and explicit legacy/optional/schema controls keep their
purposes. Part 3 is incomplete; the final sub-part still owes a repository-wide
receipt-builder call-site inventory showing no pending positive.

No production, DDL, schema, pin or promotion-policy change. Stop and report if
one is required. Mandatory consumption and promotion changes stay **OFF**.
Recompute the full transitive import/control closure and expand complete --only
families; retain qualified predicate/control and direct converted-path traces.
Before the implementation commit run full gen2-test, trigger-order, composition
and all eight static gates. No production trigger changes, so no new trigger-
inventory gate is triggered; retain the unchanged full inventory. Wait for no
active user/system gen2-landing-* unit before heavy runs. Any snapshot venv uses
cp -a. Evidence and current exact next steps: private/evidence/2d-4c-part3f/,
with COMPLETION.md and PROGRESS.md. This estimate commit precedes code/gates.


**Part 3f implementation (selected six raw span/exact owners), 2026-10-19.**
SpanDDLTest, ExtractionSpanDDLTest, ValidatedSpanDDLTest, ExactSpanDDLTest,
ExtractionExactSpanDDLTest and ValidatedExactSpanDDLTest now retain current `/2`
positives with real Router-admitted assessments for every performed kind. The
accepted RawAssessmentFixture, seed_checks, assessment_binding, attach_checks
and restore_triggers mechanisms are reused unchanged. The raw table parent
exposes an accepted-binding catalog hook; each actual subject seeds its declared
controls under unmutated DDL before snapshots. Generic probe owners and the broad
schema-edge matrix retain all 30 bindings / 360 records. A normal page control
needs one binding / 12 records. Receipt construction selects existing rows only.

SQL 37 binds canonical array text. Each accepted literal is first exercised as
an explicit sampled `/1` compatibility control inside a rolled-back savepoint,
then retained as a canonical `/2` receipt with the same exact decoded spans and
admitted references. Every pending positive value gains its current counterpart;
none is relabeled historical. Negative member/numeral probes retain their literal
`/1` isolation and original diagnostics. The adopted cap's over-limit values stay
refusals. No value is rounded. Requested trigger definitions/order and the two
existing subject-local omissions survive reseeding through restore_triggers.

All 31 original assertion-call ASTs across the three edited existing files are
unchanged. Four new regressions cover all six owners: retained authenticated
reports and read-only catalogs checked before rollback, four distinct ordered
span bindings with 16 disjoint selected record IDs, literal exact-limit/exact-zero
spellings alongside current references, foreign-span atomic refusal followed by
six matching full-text promotions, and exact reversed/mutated/dropped catalogs.
Ordinary extraction outputs remain byte equal and claim no artifact-selector
discrimination; the accepted distinct-output experiment is unchanged. These are
synthetic attributed assessments and relationship/binding proofs, not scientific
correctness or real transport-authentication claims. Full-text promotion controls
consume response bytes equal to the actual authenticated examined artifact.

The ten-module transitive fixture closure selects 57 directly affected mutants,
expanded to 68 in the complete 2D4B3D, 2D4B3DR1, 2D4B3DR2 and 2D4CCAP prefixes.
All 68 are killed with separate passing controls over green 1,105-Store/two
file-target baselines. All 153 predicate/control pairings qualify through 15
passing controls, with seven explicit converted paths. All six raw owner controls
also hit the actual positive attachment line and detailed-binding trigger.
Downgrade, span-collapse, binding-removal and restoration-removal counterfactuals
each produce six assertion failures and zero errors. All 3,618 prior control
records are unchanged. The full unchanged inventory has 337 triggers, zero
uncovered guards. Production, ordered DDL, schemas, pins and policy are unchanged;
mandatory consumption and promotion activation remain **OFF**.

The first full run reported ERROR in its nested serial mutation test at the
existing 900-second deadline. Bulk admission of every span variant for every
subject was the inferred cause from timing and the test's timeout; its traceback
was not printed before interruption. Superseded full/order runs receive no
passing credit. Upfront subject catalogs fix the fixture cost without changing
any timeout, assertion or admission helper. The focused run falls from 533.176s
to 161.575s; both nested serial mutation checks pass on final source. A post-audit
prefix filter initially counted the cap control along with the six owners; the
corrected explicit-owner filter qualifies all six, without a repository change.

**Part 3f validated before implementation commit.** Full gen2-test passes
**4,260 tests, two existing skips**, in **3,681.366 test seconds**. Trigger-order
passes **337 triggers / 4,721 identical Store tests/subtests**; composition passes
**six tests**; affected complete families pass **68/68**, in 551.1s. All eight
static gates pass and are repeated after this note. All four code files match
their final tested hashes. Footprint: **186 repository additions / 15 removals**
plus **297 retained private driver lines**, totaling **483 additions against 495
estimated**, excluding documentation/generated evidence. This stops after the
selected six-owner group; part 3 remains incomplete.

**Exactly what remains pending for part 3g or later:** raw quote DDLTest,
CaptureDDLTest and AdjudicationDDLTest; StoreTestCase.verify/populate_every_table,
VerificationTest, ContractAdmittedSupportTest; raw canonical/content/acquisition/
extraction-content owners, PendingDDLTest's accepted canonical/distractor receipts,
history/replacement and every JSON/member/population consumer listed in the
private COMPLETION.md (including all 30 generated owners); both ImpactTest
ContractWorld.verify amendment positives. The newer
`test_span_cap.SpanCapTest.test_receipt_router_matrix` also still builds current
accepted `/1` receipts through the pending root and is explicitly pending. It
postdates 3e's inventory; it is not relabeled historical. HoldDDLTest stays
hold-only; ObservationDomainTest writes no verification receipt. Previously
converted owners and explicit historical/optional/schema controls retain their
purposes. The cap is implemented and accepted; no cap decision is open. The final
part-3 slice still owes the repository-wide no-pending-positive inventory.

Evidence, exact pending owners, attempts, source/control inventories, gate commands
and commits: private/evidence/2d-4c-part3f/COMPLETION.md. PROGRESS.md is current.
No provider calls, real-database migrations, Gen-1 access, protected-register
edits by this slice, push or main merge occurred. AGENTS.md lookup stayed inside
the repository. No manual disposable snapshot or venv symlink was created.

#### 2d-4c part 3g — re-estimate (before code)

2026-10-19, branch `gen2`. Read the whole task, Constraints, both operator
rulings and every continuation; all of §2d-4c, including every part-3 audit
and implementation note; part-3f COMPLETION.md and population-owners.json;
the accepted detailed/raw/DDL helpers and newest raw-span regressions.
Repository-only AGENTS.md lookup found none. No pending positive is historical.

The concrete remainder is **about 850 handwritten additions**, including
retained private drivers: raw quote/capture/adjudication 130; global raw
admission/population and all population consumers 230; raw canonical/content/
acquisition/extraction-content/pending owners 140; remaining Router amendment
and cap wiring 65; independent regressions 135; audit/trace/gate drivers 150.
This remains well above 500, so split before code. **Implement only the
remaining Router group in 3g:** both ImpactTest callers of ContractWorld.verify
and SpanCapTest.test_receipt_router_matrix. Selected estimate **440 additions**:
wiring/catalog admission 65, independent evidence/binding/promotion/rollback/
catalog regressions 125, retained private inventory/trace/gate drivers 250.
Stop after this coherent group. Part 3 will remain incomplete.

**Items 2 and 4 are one coupled future conversion, never independent credit.**
Leave StoreTestCase.verify/populate_every_table and every population consumer
explicitly pending together: EveryTableSweepTest (replacement/delete sweeps),
RecordIdentityTest; the six branch-window/obligation/registry/semantic/lifecycle/
source-artifact DDL owners; member-domain QuoteTest; all eight RolloutPairs and
22 CompletionPairs owners in part-3f population-owners.json. Their receipt
histories remain pending even when their subject is another table. That slice
must authenticate the population's actual examined bytes, convert its receipt
builder and all inherited accepted paths atomically, preserve each consumer's
isolation/old-DDL experiment, and run the widened transitive mutation closure.
No consumer can be reported converted while its population root is pending.
VerificationTest and ContractAdmittedSupportTest stay in that global audit;
raw quote/capture/adjudication inheritance must be included when changing it.
The independently constructed raw canonical/content/acquisition/extraction-
content/PendingDDL positives also remain pending, with the exact list retained
in this slice's COMPLETION.md. Nothing is silently opted out or relabelled.

Reuse seed_checks/assessment_binding/attach_checks and restore_triggers.
Amendment controls retain real examined/evidence bytes and all accepted
promotion/fencing assertions; seed under unmutated DDL before receipt snapshots,
then restore requested definitions/order. The cap matrix admits distinct
in-range ordered span bindings upfront, then selects existing records at
submission; literal boundary refusal operands and exact-zero/limit acceptance
remain. Preserve explicit /1 and optional-reference historical controls.
Ordinary byte-equal extraction outputs claim no artifact-selector distinction;
the accepted distinct-output regression retains that separate responsibility.

Recompute transitive imports/paired controls, expand complete affected --only
families, and retain successful changed-path traces. Run full gen2-test,
trigger-order, composition and all eight static gates before the implementation
commit. No trigger is changed; retain the unchanged inventory. Heavy runs wait
for no active user/system gen2-landing-* unit (one is active during reading).
Any disposable venv uses cp -a. Production/DDL/schema/pins stay unchanged;
mandatory consumption and promotion changes stay OFF. Stop and report if a
production change is needed. Evidence and current PROGRESS.md live under
private/evidence/2d-4c-part3g/. This documentation-only commit precedes code.

**Part 3g plan addendum, operator NB1 (2026-10-19; after code).** Astra
accepted part 3f and identified another item-4 population consumer:
`test_store_span_cap.AuxiliaryCapTest.setUp` calls populate_every_table.
Include this owner explicitly in the coupled global-root/population conversion
plan and the final receipt-builder inventory. Under the committed 3g split it
remains pending with that entire group; its setup receipt is not historical
and is not credited as converted. The selected Router amendment/cap slice and
its running gates are unchanged. The static call-site inventory already finds
this call; the named pending-owner list is now corrected as well.

**Part 3g implementation (selected remaining Router group), 2026-10-19.**
Both ImpactTest amendment positives and SpanCapTest.test_receipt_router_matrix
now consume current /2 receipts with real Router-admitted attributed records
for every performed kind. The accepted helpers are reused unchanged. Amendment
assessments are admitted under unmutated DDL before the receipt transaction,
then restore_triggers restores the requested definitions/order. The cap matrix
admits each distinct exact in-range ordered span binding upfront; submission
only selects existing records. Literal boundary probes remain literal, repeated
equivalent spellings reuse their exact binding, and no value is rounded.
Production, DDL, schemas, pins and promotion policy are unchanged; mandatory
consumption and promotion activation remain OFF. Explicit historical /1 and
optional-reference controls retain their purposes.

All 197 original assertion-call ASTs survive (179 amendment, 18 cap). Four new
regressions check retained authenticated assessment evidence, independent
verifier attribution, all three receipt methods, disjoint span bindings,
the original accepted promotion/protocol fencing, foreign-span atomic refusal,
rollback/replay with unchanged record catalogs, and exact requested catalogs.
The new catalog fixture adopts normal DDL before restoring the requested
reversed/mutated/dropped catalog. Ordinary extraction outputs remain byte equal;
the accepted distinct-output regression retains artifact-selector coverage.
These synthetic attributed judgments establish binding, not scientific truth.

The 77-module reverse-import closure selects 1,169 direct IDs, expanded to
2,195 mutants in 72 complete prefixes. All are killed: 2,187 have passing
paired controls, three retain accepted cases inside killers, and five retain
unchanged documented exceptions; the 1,105-Store/15-file-target baselines are
green. All 3,618 control records are unchanged. Twenty passing controls are
traced: all three converted paths hit their actual fixture calls and the
detailed-binding trigger; 80 predicate/control pairings qualify, with two
existing documented by-hand delegate exceptions reported separately. The
initial qualifier incorrectly demanded coverage from those non-reaching
exceptions; its failed attempt is retained. The corrected driver passes end
to end without a fixture/control/production change. Four downgrade/binding/
restoration counterfactuals produce six assertion failures and zero errors.
The unchanged inventory has 337 installed triggers and zero uncovered guards.

**Part 3g validated before implementation commit.** Full gen2-test passes
4,264 tests with two existing skips (3,699.718 test seconds); trigger-order
passes 337 triggers / 4,721 identical Store tests/subtests; composition passes
six tests. Focused modules pass 57 tests; affected mutations pass 2,195/2,195.
All eight static gates pass and are repeated after this note. All three code
files match their tested hashes. Footprint: 134 repository additions / one
removal plus 264 retained private driver lines, totaling 398 against 440
estimated, excluding documentation/generated evidence. Heavy runs waited for
the landing unit to finish; each start has empty user/system observations.
Small development tests and lightweight static checks during that wait are
disclosed separately. Required task/dossier/helper reads preceded code; direct
older-authority rereads completed during the wait, with exact timing disclosed.

**Exactly what remains pending:** raw quote/capture/adjudication; the global
StoreTestCase.verify/populate_every_table group, VerificationTest and
ContractAdmittedSupportTest; raw canonical/content/acquisition/extraction-
content and PendingDDLTest's accepted canonical/distractor receipts; every
history/replacement/JSON/member/population consumer named in COMPLETION.md,
including all 30 generated owners and NB1's AuxiliaryCapTest.setUp. The root
and its consumers remain pending together. Nothing pending became historical.
HoldDDLTest remains hold-only; ObservationDomainTest writes no verification
receipt. The two amendment positives and Router cap matrix are converted.
This completes only the selected split: part 3 remains INCOMPLETE. The final
part-3 slice still owes the repository-wide no-pending-positive demonstration.

Evidence, exact owner/call-site inventories, attempts, commands, source hashes
and commits: private/evidence/2d-4c-part3g/COMPLETION.md; PROGRESS.md is current.
Operator commit 69e84da updated BUILD-STATE/REVIEW-LOG during validation; those
changes are neither reverted nor included in this implementation commit. No
provider call, real-database migration, Gen-1 access, protected-register edit
by this slice, push or main merge occurred. Repository-only AGENTS lookup
found none; no manual disposable checkout or venv symlink was created.

#### 2d-4c part 3h — re-estimate (before code)

2026-10-19, branch `gen2`. Read the whole task, Constraints, operator rulings
and every continuation; all DOSSIER §2d-4c notes and part-3 audits; part-3g
COMPLETION.md; part-3f population-owners.json and Astra's full 3f review,
including NB1; the accepted detailed/raw/DDL helpers and raw-span/remaining-
Router regressions. Repository-only AGENTS.md lookup found none.

**Remaining estimate: 820 handwritten additions**, including private drivers,
excluding documentation/generated evidence: raw quote/capture/adjudication 140;
global root and all population consumers 240; independent raw canonical/
acquisition/content/extraction-content/pending families 160; regressions 140;
audit/trace/gate drivers 140. This is well above 500. Split along consumer
families. **Implement only the raw content family in 3h:** ContentDDLTest,
ExtractionContentDDLTest and ValidatedContentDDLTest, including all inherited
content-shape, tier, Unicode, lineage, record-selection and retention controls.
Selected estimate **490 additions**: authenticated setup/receipt wiring 90,
independent evidence/binding/promotion/rollback/catalog regressions 120,
retained inventory/trace/gate drivers 280, including reused infrastructure.

**Safe staging and coupling:** StoreTestCase.verify/populate_every_table and
every population consumer remain pending together; this stage does not modify
that root or claim any of its consumers converted. Those consumers include
EveryTableSweepTest (replacement/delete sweeps), RecordIdentityTest; the six
branch-window/obligation/registry/semantic/lifecycle/source-artifact owners;
member-domain QuoteTest; all eight RolloutPairs and 22 CompletionPairs owners
in population-owners.json; and explicitly NB1 AuxiliaryCapTest.setUp and its
four controls. VerificationTest and ContractAdmittedSupportTest remain pending.
Raw quote DDLTest/CaptureDDLTest/AdjudicationDDLTest (including inherited
population), CanonicalDDLTest, ExtractionDDLTest, and PendingDDLTest's accepted
canonical/distractor receipts also remain pending. Nothing pending is relabelled
historical. Part 3 remains INCOMPLETE after this selected family.

Reuse RawAssessmentFixture, seed_checks, assessment_binding, attach_checks and
restore_triggers without forking them. Admit real retained examined/evidence
bytes under unmutated DDL before subject snapshots, then restore the complete
requested trigger definitions/order. Submission selects already admitted rows.
Keep raw acquisition counterfactuals as relationship operands and preserve
their diagnostics; they do not prove transport authenticity. Matching full-text
promotion controls must use response bytes equal to the authenticated examined
artifact. Keep the accepted distinct-output regression for artifact-selector
discrimination; ordinary equal-byte controls make no such claim. Explicit
refusal-only isolation operands retain their guard; pending positives do not
become historical. Preserve all existing accepted tiers and retention behavior.

No production, DDL, schema, pins or policy change; stop and report if needed.
Mandatory consumption and promotion changes stay OFF. Run full gen2-test,
trigger-order, composition, the full mutation inventory (a conservative superset
of the transitive affected --only families), and all eight static gates. Retain
successful converted-path traces and the unchanged trigger inventory. Heavy
runs wait for no active user/system gen2-landing-* unit; one is active during
reading. Any disposable venv uses cp -a. Evidence and current PROGRESS.md:
private/evidence/2d-4c-part3h/. This documentation-only commit precedes code.

**Part 3h implementation (selected raw content family), 2026-10-19.**
ContentDDLTest, ExtractionContentDDLTest and ValidatedContentDDLTest now retain
current /2 positives with Router-admitted assessments for every performed kind.
The accepted RawAssessmentFixture, seed_checks, assessment_binding, attach_checks
and restore_triggers helpers are reused unchanged. Examined/evidence bytes are
authenticated under unmutated DDL before subject snapshots; submission only
selects admitted records. Full-text promotion controls use response bytes equal
to the examined artifact. Other raw response counterfactuals prove relationships,
not transport authentication. Ordinary equal-byte extraction controls make no
selector-discrimination claim; the accepted distinct-output regression passes.
Production, DDL, schemas, pins and policy are unchanged; mandatory consumption
and promotion activation remain OFF.

The first full mutation run exposed two fixture-isolation errors: trigger-only
restoration left unmutated views installed (36 surviving shared-view mutants),
and PendingDDLTest inherits the converted content base (nine invalid controls).
The fixture now restores exact requested views before restore_triggers.
PendingDDLTest explicitly retains its original pending path through ATTRIBUTED
False; its claim/revision/distractor and inherited content positives remain
pending, never historical. The global StoreTestCase.verify/populate_every_table
root and every population consumer are unchanged and pending together. No
consumer receives conversion credit from an unconverted root.

All 38 original assertion calls in the three existing edited modules survive;
one view-catalog assertion is additional. Three new regressions independently
check retained authenticated reports, verifier attribution, every performed
outcome at every tier, unchanged record catalogs through insertion/conflict/
rollback, foreign-span atomic refusal followed by three matching full-text
promotions, full unmutated admission, and exact requested views plus reversed,
mutated and dropped triggers. Removing view or trigger restoration each causes
three assertion failures; binding removal causes three and receipt downgrade
27, all with zero errors. Nine original accepted controls trace the actual
attachment call and successful detailed-binding entry; 96/96 predicate/control
pairings qualify through successful trigger/view observations. All 3,618 control
records are unchanged. Full trigger inventory: 337 installed, zero uncovered.

**Part 3h validated before implementation commit.** Full gen2-test passes
4,267 tests with two existing skips (3,786.581 test seconds); trigger-order
passes 337 triggers / 4,760 identical Store tests/subtests; composition passes
six tests; focused modules pass 84 tests. The conservative full-inventory
--only sweep kills 3,618/3,618 mutants, with 3,601 paired controls passing,
11 existing in-killer accepted cases and six unchanged documented exceptions,
over green 1,108-Store / 26-file-target baselines. All eight static gates pass
and are repeated after this note. All four code files match tested hashes.
Footprint: 186 repository additions / seven removals plus 284 retained private
driver lines, totaling 470 against 490 estimated, excluding documentation.

Prior attempts remain in evidence without passing credit: the first mutation
failure and stopped engine run; private view-qualifier/module-alias mistakes;
and a binding-removal experiment whose trigger drop was rolled back. The full
required gates and corrected evidence drivers pass on the repaired candidate.
Heavy runs waited for the landing unit to finish and retain empty user/system
observations at each start. No production change or new exception was needed.

**Exactly what remains pending:** raw quote DDLTest, CaptureDDLTest and
AdjudicationDDLTest; StoreTestCase.verify/populate_every_table, VerificationTest
and ContractAdmittedSupportTest; CanonicalDDLTest, ExtractionDDLTest (both
methods), and PendingDDLTest's canonical/distractor/inherited content positives;
every history/replacement/member/JSON/population consumer named in COMPLETION.md,
including all 30 generated owners and explicitly Astra 3f NB1 AuxiliaryCapTest
with its four controls. HoldDDLTest stays hold-only; ObservationDomainTest writes
no verification receipt. Previously converted owners retain their purposes.
Part 3 remains INCOMPLETE; its final sub-part still owes the repository-wide
no-pending-positive demonstration. This stage stops after the raw content family.

Evidence, exact pending owner/call-site inventories, attempts, commands, hashes
and commits: private/evidence/2d-4c-part3h/COMPLETION.md; PROGRESS.md is current.
Operator commit 29eeafd accepted part 3g and updated BUILD-STATE/REVIEW-LOG
during validation; those changes are neither reverted nor included here.
No provider call, real-database migration, Gen-1 access, protected-register edit
by this slice, push or main merge occurred. Repository-only AGENTS lookup found
none; no manual disposable checkout or venv symlink was created.


#### 2d-4c part 3i — re-estimate (before code)

2026-10-19, branch `gen2`. Read the whole task (Constraints, both operator
rulings and every continuation, including the 3h coupling rule); all of this
section, every part-3 audit and implementation note; part-3h COMPLETION.md;
part-3f population-owners.json; and all six named accepted detailed/raw/DDL
fixture and regression helpers. Repository-only AGENTS.md lookup found none.
Nothing pending is relabelled historical. No code has changed for this stage.

**Remaining estimate: about 780 handwritten additions**, including retained
private drivers, excluding documentation/generated evidence: raw canonical/
acquisition wiring and isolation 150; global root and all population consumers
220; raw quote/capture/adjudication 130; PendingDDLTest canonical/distractor/
inherited-content conversion 60; independent regressions 100; audit/trace/gate
drivers 120. This is well above 500. **Split along consumer families; implement
only CanonicalDDLTest and ExtractionDDLTest (both extraction methods) in 3i.**
Selected estimate **495 additions**: authenticated setup, real source identity,
per-operand admission and receipt wiring 150; independent retained-evidence,
binding/rollback/method/catalog regressions 120; retained inventory/trace/gate
drivers, including reused infrastructure, 225. Stop after this coherent family.

Reuse RawAssessmentFixture, seed_checks, assessment_binding, attach_checks and
restore_triggers without forking them. Each accepted source/work/verifier
operand must exist before Router admission of its exact records. The selector
loops currently use outer savepoints, incompatible with Router transactions;
give each operand a fresh disposable in-memory fixture instead. Admit records
under unmutated DDL before receipt snapshots, then restore exact requested views
and trigger definitions/order. Submission only attaches admitted rows. Preserve
the accepted canonical/own/validated receipts, distinct selector operands and
original refusal diagnostics. Explicit refusal-only /1 operands keep isolation;
all accepted controls acquire current /2 references. Real examined bytes and
retained evidence are authenticated. Ordinary byte-equal extraction controls
make no artifact-selector discrimination claim; retain the accepted separate
distinct-output experiment. No production change is anticipated or authorized.

**Coupling and exact remaining scope after this stage:** StoreTestCase.verify /
populate_every_table and every population consumer remain pending together,
unchanged: VerificationTest, ContractAdmittedSupportTest, EveryTableSweepTest
(including replacement/delete), RecordIdentityTest; branch-window, obligation,
registry, semantic, lifecycle and source-artifact DDL owners; member-domain
QuoteTest; all eight RolloutPairs and 22 CompletionPairs owners named in
population-owners.json; explicitly NB1 AuxiliaryCapTest.setUp and its four
controls. Raw quote DDLTest, CaptureDDLTest and AdjudicationDDLTest (including
inherited population) also remain pending, as do PendingDDLTest's canonical,
distractor and inherited content positives. Previously converted raw content,
span/table and Router owners keep their accepted paths. HoldDDLTest remains
hold-only; ObservationDomainTest writes no verification receipt. This stage
does not finish part 3; its final stage still owes the repository-wide inventory
showing no pending positive. No pending consumer receives conversion credit here.

Mandatory consumption and promotion changes stay **OFF**. Production, ordered
DDL, schemas, pins and policy remain untouched; stop and report if any change
is needed. Run full gen2-test, trigger-order, composition, complete affected
--only families (including transitive shared-fixture controls), and all eight
static gates. Retain qualified original-control traces, unchanged trigger
inventory, exact pending list, footprint and attempts. Heavy runs wait for no
active user/system gen2-landing-* unit; 4c3h is active during reading. Any
disposable snapshot copies .venv-gen2 with cp -a, never a symlink. Evidence and
current PROGRESS.md: private/evidence/2d-4c-part3i/. This documentation-only
commit precedes code and implementation gates. No Gen-1, provider call, real
database migration, protected-register edit, push or main merge is authorized.


**Part 3i implementation (selected raw canonical/acquisition family), 2026-10-19.**
CanonicalDDLTest and ExtractionDDLTest (both methods) now retain current /2
receipts with real Router-admitted assessments for every performed kind. All
25 original positive writes are converted: nine canonical and sixteen own/
validated extraction controls. The accepted RawAssessmentFixture, seed_checks,
assessment_binding, attach_checks and restore_triggers helpers are unchanged.
Real examined bytes replace the old source hash label; retained reports and
evidence are authenticated under full unmutated DDL. Requested views and exact
trigger definitions/order are restored before the receipt subject. Submission
only selects admitted rows. Production, ordered DDL, schemas, pins and policy
are unchanged; mandatory consumption and promotion activation remain **OFF**.

The selector loops now use a fresh disposable in-memory fixture per operand:
Router transactions cannot nest inside the original outer savepoint. Receipt
conflict/rollback savepoints remain. The alternate verifier's existing lease
fixture now has the eighth suffix character required by Router schema. All 18
original assertion-call expressions and multiplicities are preserved. Explicit
/1 refusal operands keep their original diagnostics; no accepted positive is
retained that way or relabelled historical.

Four new regressions independently check retained authenticated reports, actual
performer attribution, distinct work/verifier records, each performed outcome
for numeric_units across three methods, unchanged assessment catalogs through receipt
insertion/conflict/rollback, foreign-span atomic refusal followed by matching
acceptance, full unmutated admission and exact requested views plus reversed,
mutated and dropped triggers. Ordinary outputs equal the authenticated canonical
bytes and claim no artifact-selector discrimination. The accepted distinct-output
and promotion regressions pass in the focused gate. These synthetic assessments
prove recorded relationships, not scientific correctness.

**Part 3i validated before implementation commit.** Full gen2-test passes
**4,271 tests, two existing skips**, in **3,932.080 test seconds**. Trigger-order
passes **337 triggers / 4,775 identical Store tests/subtests**; composition passes
six tests; focused modules pass 21. The complete affected-family --only sweep
kills **68/68**, all with passing paired controls, over a green **1,112-test
Store baseline**, in 669.9 mutation seconds. All eight static gates pass and are
repeated after this note. All three code files match their tested hashes.

The three-module reverse-import closure selects 24 directly affected IDs,
expanded to three complete prefixes. Three passing controls qualify all 24
predicate/control pairings. Both converted control tests (three receipt methods)
hit the actual attachment call and detailed-binding trigger. SQL entries are
successful-guard observations, not branch traces of every SQL subexpression.
Four downgrade/binding/view-restoration/trigger-restoration counterfactuals each
cause three assertion failures and zero errors. All 3,618 control records are
unchanged. Full unchanged trigger inventory: 337 installed, zero uncovered.

Footprint: **207 repository additions / 32 removals** plus **195 retained private
Python driver lines**, totaling **402 against 495 estimated**, excluding docs
and generated evidence. Prior development attempts are disclosed in COMPLETION:
a redundant queue-revision jump, the short alternate-verifier lease suffix,
and an assertion audit whose traversal-order assumption did not survive loop
restructuring. Exact-expression multiplicities now verify all original assertions.
Required task/dossier/helper/evidence reads preceded code; direct older-authority
rereads completed during the landing wait. No production need was found.

**Exactly what remains pending:** raw quote DDLTest, CaptureDDLTest and
AdjudicationDDLTest, including inherited population positives; the unchanged
StoreTestCase.verify / populate_every_table root and every consumer together,
including VerificationTest, ContractAdmittedSupportTest, EveryTableSweepTest
(replacement/delete sweeps), RecordIdentityTest, branch-window/obligation/
registry/semantic/lifecycle/source-artifact DDL owners, member-domain QuoteTest,
all eight RolloutPairs and 22 CompletionPairs owners, and explicitly NB1
AuxiliaryCapTest.setUp and its four controls; PendingDDLTest's accepted canonical,
distractor and inherited content positives. COMPLETION.md and population-owners.json
name every owner. HoldDDLTest stays hold-only; ObservationDomainTest writes no
verification receipt. Previously converted owners retain their purposes. Part 3
remains **INCOMPLETE**; its final stage still owes the repository-wide inventory
showing no pending positive. Stop after this selected family.

Evidence, exact pending list, call/import inventories, attempts, hashes, gate
commands and commits: private/evidence/2d-4c-part3i/COMPLETION.md; PROGRESS.md is
current. Every required start has fresh empty user/system landing observations;
heavy runs waited for the prior landing to finish successfully. No Gen-1,
provider call, real-database migration, protected-register edit, push or main
merge occurred. Repository-only AGENTS lookup found none. No manual disposable
checkout or venv symlink was created. This completes the selected family only.

Operator commit 4740d5d668b903ac4dbe1a7272d44a0aae4b3ae8 accepted part 3h
and updated BUILD-STATE/REVIEW-LOG during validation. Those changes are neither
edited nor included by this slice; DEBT-REGISTER is byte unchanged. All protected
registers have no working-tree edit. final-inputs.json retains both hash sets
and the external commit separately from this implementation.


#### 2d-4c part 3j — re-estimate (before code)

2026-10-19, branch `gen2`. Read the whole task, Constraints, both operator
rulings and every continuation including the coupling rule; all of §2d-4c,
every part-3 audit/implementation note; part-3i COMPLETION.md and part-3f
population-owners.json; accepted detailed/raw/DDL helpers and all four raw
detailed-fixture regression modules. Repository-only AGENTS.md lookup found
none. The named flow S4, adjudication (b)5/(c)2, methodology §4 and V-4/V-8
were also read before code. Nothing pending is relabelled historical.

**Remaining estimate: about 690 handwritten additions**, including retained
private drivers, excluding docs/generated inventories: global root plus every
population consumer 240; raw quote/capture/adjudication 130; PendingDDLTest
canonical/distractor/inherited-content setup and wiring 85; independent
regressions 110; audit/trace/gate drivers 125. This is well above 500. Split
along consumer families. **Implement only the independent PendingDDLTest
family in 3j**, estimated **465 additions**: authenticated setup, distinct
claim/revision operands and receipt wiring 85; independent evidence/binding/
promotion/rollback/catalog regressions 130; retained inventory/trace/gate
drivers 250, including reused infrastructure. Stop after this coherent stage.

Enable the accepted attributed content base for all inherited positives. Seed
revision 2 and the foreign-claim distractor through the existing Router bridge
and seed_checks under unmutated DDL before subject savepoints, then restore
requested views and exact trigger definitions/order with restore_triggers.
Use fresh in-memory fixtures for variable-tier operands rather than nesting
Router commits in savepoints. Submission only selects already admitted rows.
Preserve original canonical promotion and distractor/unbound-extraction
refusals. Existing explicit pre-consumer unbound declarations keep their
historical isolation mechanism; every pending current canonical/distractor
and inherited content positive receives /2 references. Distinct claims and
revisions get disjoint records. Real examined/evidence bytes are authenticated;
ordinary equal-byte outputs make no artifact-selector discrimination claim.

**Coupling and exact pending scope after this stage:** leave the global
StoreTestCase.verify/populate_every_table root and every consumer unchanged
and pending together: VerificationTest, ContractAdmittedSupportTest;
EveryTableSweepTest (including replacement/delete), RecordIdentityTest;
branch-window, obligation, registry, semantic, lifecycle and source-artifact
DDL owners; member-domain QuoteTest; all eight RolloutPairs and 22
CompletionPairs owners named in population-owners.json; NB1
AuxiliaryCapTest.setUp and its four controls. Raw quote DDLTest,
CaptureDDLTest and AdjudicationDDLTest, including inherited population
positives, also remain pending. No consumer receives conversion credit from
an unconverted root. HoldDDLTest stays hold-only; ObservationDomainTest
writes no verification receipt. Previously converted consumers retain their
purposes. Part 3 remains INCOMPLETE; the final stage still owes a repository-
wide receipt-builder inventory showing no pending positive.

Reuse RawAssessmentFixture, seed_checks, assessment_binding, attach_checks and
restore_triggers without forking them. Production, ordered DDL, schemas, pins
and policy stay unchanged; stop and report if production is needed. Mandatory
consumption and promotion changes stay **OFF**. Run full gen2-test, trigger-
order, composition, complete affected --only families including transitive
imports/paired controls, and all eight static gates before implementation
commit. Retain converted-path traces, unchanged trigger inventory, exact
pending inventory, attempts and footprint. Heavy starts wait for no active
user/system gen2-landing-* unit; 4c3i is active while reading. Any disposable
snapshot copies .venv-gen2 with cp -a. Evidence and current PROGRESS.md:
private/evidence/2d-4c-part3j/. This documentation-only commit precedes code.

**Part 3j implementation (selected PendingDDLTest family), 2026-10-19–20.**
PendingDDLTest now inherits the accepted attributed content fixture, converting
all twelve inherited content methods and its canonical/distractor positives.
Revision 2 and the foreign-claim distractor receive real Router-admitted
assessments under unmutated DDL before subject savepoints. Variable-tier
operands use fresh in-memory stores rather than nesting Router transactions.
Requested views and exact trigger definitions/order are restored through the
accepted methods and restore_triggers. Receipt submission only selects admitted
records. RawAssessmentFixture, seed_checks, assessment_binding and attach_checks
are reused unchanged. Production, ordered DDL, schemas, pins and policy are
unchanged; mandatory consumption and promotion changes remain **OFF**.

The existing pending() path already used the explicit pre-consumer historical
context and disabled extraction attachment. Its unbound declarations retain that
same /1 non-authority isolation; the keyword is now explicit when opting into
the attributed parent. No pending positive becomes historical. Every current
canonical/distractor and inherited content positive gains /2 references.
All 23 original assertion-call expressions and multiplicities are preserved.

Four new regressions check eight original current writes across canonical,
distractor and inherited-tier controls; disjoint records for three claim/revision
bindings; all twelve performed kind/outcome combinations; authenticated retained
reports and actual independent verifier attribution; unchanged record catalogs
through insertion/conflict/rollback; two foreign-reference atomic refusals and
matching full-text promotion; and exact requested views plus reversed/mutated/
dropped triggers. Matching promotion uses response bytes equal to the examined
artifact. Other raw response counterfactuals prove relationships, not transport
authentication. Ordinary equal-byte outputs claim no selector discrimination;
the accepted distinct-output regression also passes. Synthetic assessments prove
recorded relationships, not scientific correctness.

**Validated before implementation commit.** Full gen2-test passes **4,275 tests,
two existing skips**, in **3,973.396 test seconds**. Trigger-order passes **337
triggers / 4,791 identical Store tests and subtests**; composition passes six
tests; focused execution passes 41. The 27-module reverse-import closure selects
136 direct IDs, expanded to 195 mutants in eight complete families. All **195/195**
are killed with paired controls passing over a green **1,116-test Store baseline**
(740.4 mutation seconds). All eight static gates pass and are repeated after this
note. Both code files match their tested hashes. All 3,618 control records and
mutation definitions are unchanged; the full inventory has zero uncovered guards.

Twenty-three unchanged controls pass tracing; all **136/136** predicate/control
pairings qualify. The three selected original controls hit actual attachment and
detailed-binding; canonical/distractor controls also hit the new preparation
call. Returned view rows are observed separately from successful trigger entries;
these are not branch traces of every SQL subexpression. Four counterfactuals
produce 12/1/1/1 assertion failures and zero errors. The initial private qualifier
omitted bound-view observations; its failed attempt and initial driver exit 1
are retained. Corrected full tracing, explicit preparation-line qualification and
the final validator exit 0, with no repository source/control change or repeated
engine gate. An extra call-difference audit also needed to account for the
existing pending() call's explicit keyword; no new unconverted owner was found.

Footprint: **154 repository additions / five removals**, plus **266 retained
private driver lines**, totaling **420 against 465 estimated**, excluding docs
and generated inventories. Required task/section/helper/evidence reads preceded
code; broader methodology and accepted quote-work rereads completed during the
landing wait. Initial required starts have fresh empty user/system landing
observations. Small development checks during the wait are separate from gates.

**Exactly what remains pending:** raw quote DDLTest, CaptureDDLTest and
AdjudicationDDLTest, including inherited population positives; the unchanged
StoreTestCase.verify/populate_every_table root and every population consumer
together: VerificationTest, ContractAdmittedSupportTest, EveryTableSweepTest
(including replacement/delete), RecordIdentityTest; branch-window, obligation,
registry, semantic, lifecycle and source-artifact DDL owners; member-domain
QuoteTest; all eight RolloutPairs and 22 CompletionPairs owners; and explicitly
NB1 AuxiliaryCapTest.setUp and its four controls. COMPLETION.md and
pending-owners.json name every owner. HoldDDLTest stays hold-only;
ObservationDomainTest writes no verification receipt. Previously converted
owners retain their purposes. Part 3 remains **INCOMPLETE**; its final stage still
owes the repository-wide receipt-builder inventory showing no pending positive.
This stage stops after the independent PendingDDLTest family.

Evidence, exact pending list, call/control inventories, attempts, commands,
hashes and commits: private/evidence/2d-4c-part3j/COMPLETION.md; PROGRESS.md is
current. Operator commit 5ec987b accepted 3i and updated BUILD-STATE/REVIEW-LOG;
those changes are neither edited nor included here. DEBT-REGISTER is unchanged;
all protected registers have no working-tree edit. No Gen-1, provider call,
real-database migration, manual snapshot/venv symlink, push or main merge occurred.


#### 2d-4c part 3k — re-estimate (before code)

2026-10-20, branch `gen2`. Read the complete task, Constraints, both operator
rulings and every continuation, including the coupling rule and orchestrator
clarification: the slice guide counts repository handwritten changes only.
Read all of this section's audits/notes, part-3j COMPLETION.md, part-3f
population-owners.json and the accepted detailed/raw/DDL/regression helpers.
Repository-only AGENTS.md lookup found none. No code has changed for this stage.

**Repository estimate: about 480 handwritten added/changed lines**, including
this estimate and final implementation note: global population/authenticated
admission and exact requested-catalog isolation 140; raw verification and
quote/capture/adjudication wiring 100; independent binding, retained-evidence,
promotion, rollback and catalog regressions 160; dossier notes 80.
**Private estimate: about 350 retained driver lines**, including reused audit,
trace and gate infrastructure; generated inventories/logs are additional.
Private evidence does not count against the repository slice guide. Both final
groups fit about 500 repository lines, so implement both and finish part 3.
Re-estimate before expanding beyond this coherent scope if necessary.

Convert StoreTestCase.verify/populate_every_table, VerificationTest and
ContractAdmittedSupportTest together with every population consumer: history
and replacement/delete sweeps, RecordIdentityTest; branch-window, obligation,
registry, semantic, lifecycle and source-artifact DDL owners; member QuoteTest;
AuxiliaryCapTest and its four controls; all eight RolloutPairs and 22
CompletionPairs owners named in population-owners.json. Convert raw quote
DDLTest, CaptureDDLTest and AdjudicationDDLTest including inherited positives.
Nothing pending becomes historical. Existing old-DDL installation, explicit
refusal/isolation and optional-reference controls retain their purposes.

Reuse RawAssessmentFixture, seed_checks, assessment_binding, attach_checks and
restore_triggers. Real examined/evidence bytes and every performed outcome are
admitted through Router under unmutated DDL before subject snapshots; receipt
submission only selects admitted records. Preserve requested table constraints,
views and complete trigger definitions/order, including local omissions, so
admission cannot mask predicate mutants. Any in-memory copy retains the actual
Router-admitted rows, never invented IDs. Distinct claim/revision/span/verifier
operands receive distinct records. Preserve promotions, holds, rollback and
original refusal diagnostics; ordinary equal-byte outputs claim no selector
discrimination. Keep the accepted distinct-output regression.

Run full gen2-test, trigger-order, composition, **full mutation inventory**,
static gates and successful original-control traces. Heavy starts wait for no
active user/system gen2-landing-* unit; 4c3j is active while reading. Any
snapshot copies .venv-gen2 with cp -a. Final COMPLETION.md must carry the
repository-wide receipt-builder call-site inventory and demonstrate no pending
positive remains. Evidence and current PROGRESS.md:
private/evidence/2d-4c-part3k/. Mandatory consumption and promotion changes stay
**OFF**. No production, DDL, schema, pins or policy change is authorized; stop
and report if needed. No Gen-1, provider calls, real-database migration,
protected-register edits, push or main merge. This note is committed before code.


#### 2d-4c part 3k — implementation: final coupled groups

2026-10-20, branch `gen2`; pre-code estimate committed as `d368f47`.
Both final groups fit the clarified repository-only guide and are converted
in one slice. Part 3 is **COMPLETE: no pending positive owner remains**.
StoreTestCase.verify/populate_every_table, both evidence classes, all forty
population consumers (including AuxiliaryCapTest and thirty generated JSON
owners), and raw quote/capture/adjudication including inherited positives now
use the accepted detailed/raw helpers. Twelve real Router-admitted performed
records replace the manual check-history placeholder. Source hashes authenticate
the actual retained bytes; unrelated raw-artifact operands keep their roles.

Admission runs under full unmutated DDL on an in-memory mirror, with foreign
keys/recursive triggers enabled and CHECK constraints enforced. Exact actual
admitted rows return to the owner; no invented IDs. Requested tables, views,
connection flags and complete trigger definitions/order, including mutations
and local drops, survive restore_triggers. Submission only attaches existing
records. Claim/revision/span/verifier variants receive distinct records.

Six regressions cover every population, original promotions, independent
verifiers/adoption, all kinds/performed outcomes and three methods, atomic
foreign-reference refusal, conflict/rollback and requested-catalog preservation.
All 207 original assertion expressions survive the explicit source-hash operand
substitution. Existing old-DDL, refusal, isolation and accepted part-2 optional/
historical experiments retain their purpose; no pending positive is relabelled.
Raw response counterfactuals prove relationships; examined/assessment bytes are
authenticated. Equal-byte outputs claim no selector discrimination; the accepted
distinct-output regression passes. No scientific-correctness claim is made.

**Validation before commit:** full gen2-test passes **4,281 tests**,
two existing skips, in **4,720.911 test seconds**;
trigger-order 337 triggers / 4,884 identical Store tests/subtests; composition
six; focused 361. Full inventory **3,618/3,618 killed**, all 3,601 paired controls
passing over the green 1,122-test Store / 26-file-target baseline (2,770.4s).
All eight static gates pass and repeat after this note. Fifty-one original
controls reach actual attachment and successful detailed-binding entry, including
all thirty generated owners; these observations do not trace every SQL branch.
Counterfactuals fail at 9/9/1/1 assertions, zero errors; the queue delete probe
also fails at one assertion/zero errors when its guard is removed.

Initial full mutations found one queue-delete survivor: the advanced root revision
made its replacement operand hit an intake guard first. A pristine unreferenced
first queue row restores the original delete probe without resetting root state
or changing assertions. Initial attempt archived; unfinished full suite receives
no passing credit. Every gate reran on the repaired ten-file candidate.

Repository footprint: 480 additions / 75 removals including both dossier notes;
private final drivers: 304 lines, separate from archived/generated evidence.
The 147-module import closure affects 2,708 mutation definitions; full inventory
is the required superset. COMPLETION.md carries 356 candidate calls across 71
classified modules, broader text inventory and 34 inherited-owner resolutions.
Mandatory consumption/promotion remain **OFF**; part 4 is deferred. No production,
DDL/schema/pin/policy, Gen-1, provider, real-database, protected-register, push or
main-merge change occurred. Required heavy starts observed empty user/system
landing units; disposable work uses no venv symlink. Evidence, exact commands,
hashes, attempts, inventories and commits: private/evidence/2d-4c-part3k/COMPLETION.md;
PROGRESS.md is current. Operator acceptance `8aa8611` is retained separately.

#### 2d-4c part 4 — re-estimate before code (2026-10-20)

Branch `gen2`, starting at `c95b0ee`. Read the complete task and operator
rulings, BUILD-CHARTER, BOUNDARIES Router/Verifier/Tier-0, flow S4 steps 4/8/9,
adjudication (b)5/(c)2, methodology §4, V-4/V-8, this entire section including
every part-3 note, and accepted part-3k completion/review. Repository-only
AGENTS.md lookup found none. The existing BUILD-STATE working edit is external
and will be left untouched. No unresolved design choice is needed: the ruling
settles retained evidence/applicability, and the original design explicitly
requires records for performed failures used through adjudication too.

**Re-estimate: about 820 handwritten repository additions/changes**, excluding
generated controls/pins: mandatory receipt admission in SQL/Router 55;
optional/legacy experiment dispositions and stale comments 105; shared exact
SQL binding relation and both successor promotion triggers 155; independent
Router promotion consumption 85; admission/promotion/history/non-pooling and
rollback regressions 240; paired mutants/integration 70; dossier notes 110.
Private retained audit/trace/gate drivers are estimated separately at 350 lines.
This is well above about 500. Split and stop after the first coherent sub-part.

**Implement part 4a only: mandatory receipt admission**, estimated **390
repository lines**: additive SQL 40/order/pins 25, independent DetailedChecks
admission 20, existing optional/legacy experiment dispositions and NB-1 comments
105, focused per-kind admission/outcome/atomicity tests 110, paired mutants and
integration 45, dossier estimate/completion notes 85. Reuse SQL 37 and the
existing independent Router exact-binding checks; do not duplicate their
relationship predicates. No new JSON column or member-name classification is
needed. Both DDL/catalog hashes must be repinned.

New load-bearing-use supports/partially_supports receipts must supply all four
performed outcomes and record references, including a performed failure allowed
by the existing verdict/adjudication rules. `/1` cannot supply these and is
refused for that new use. Any supplied record still binds exactly to kind,
outcome, topic, claim/revision, full spans, source/version/hash, selected examined
artifact and verifier. Legacy summary projection remains explicit. Sampled and
truthful unsuccessful receipts retain optional references; not_checked and
unavailable never authorize support. The schema remains a structural format
and historical readback contract; SQL/Router enforce current admission policy.
No retained receipt is rewritten and no live database is migrated.

Re-dispose the part-2 single-reference controls as sampled binding experiments,
keeping every supplied reference tested; distinct validated selector probes
retain four references with only the examined selector varying. Optional/legacy
load-bearing admission experiments must now assert atomic refusal. Keep explicit
historical promotion fixtures by installing their old receipts in disposable
memory with the new admission guard omitted, then restoring the requested
catalog. These fixtures remain inputs for the next promotion-consumer slice,
not evidence that part 4 is complete. Fix all three p3k NB-1 comments.

**Exactly deferred to part 4b:** the common durable-binding relation at
consumption, SQL 03 and SQL 34 successors, independent Router promotion check,
same-receipt/non-pooling and historical promotion refusals across canonical,
own and validated extraction; preserved tier/use/tier-0/content/output/bound-
basis/contract/governed-capture gates; adjudication of unperformed checks and
their predicate mutants. Existing promotion behavior is intentionally unchanged
in 4a. Part 4 and the whole mandatory-consumption requirement remain INCOMPLETE
until that separately estimated/reviewed slice lands.

Before the implementation commit: full gen2-test, trigger-order, composition,
full mutation inventory (a conservative superset of affected --only families),
the eight static gates and gen2-gateway because production/DDL changes. Retain
per-predicate passing control-path traces and the full uncovered-trigger
inventory. Every heavy start waits for no active gen2-landing-* user unit;
any disposable snapshot copies .venv-gen2 with cp -a. Evidence, attempts, exact
commands, hashes and current PROGRESS.md: private/evidence/2d-4c-part4/.

**4a fixture-isolation addendum, before additional code.** Focused predicates
and current positives pass, but independent probes find the old Python/DDL
capture-span mutants survive: their deliberately `/1` refusal operands now fail
the new admission guard before the capture predicate. The family cause is the
activation of an admission rule over previously explicit historical isolation
experiments. Preserve their original predicates/assertions through one named
test-only historical-admission context, used only at those existing isolation
call sites. It omits the new SQL guard and independent Router presence rule,
then restores the exact requested trigger catalog/order, including mutations
and local drops. Current positive and mandatory-refusal paths never use it.

Re-estimate 4a at **about 470 repository lines** including documentation:
the existing candidate is 284 non-generated additions including the estimate;
allow 55 for shared context/catalog support and explicit legacy call sites,
55 for restoration/current-policy regressions and 75 for this addendum plus
completion notes. This remains one coherent admission slice under about 500;
4b stays deferred. Freeze source before rerunning full gates. Initial full
handoff execution overlapped the last test/mutant edit and is uncredited;
the frozen-source discovery control passes. The subsequent engine runs are
also stopped for this independently reproduced fixture defect. Gateway source
is unchanged and its independent run may finish. Retain both attempts.

#### 2d-4c part 4a — implementation and validation (2026-10-20)

SQL 40 and independent DetailedChecks now require durable references for every
performed kind in new load-bearing supports/partially_supports receipts,
including failed checks used through adjudication. SQL 37 and the existing
Router bindings still enforce exact relationships and explicit outcome
projection; SQL 03 retains the unperformed/unavailable prohibition. Historical
readback stays available. No semantic-correctness authority is claimed.

Former optional/legacy load-bearing positives now assert atomic refusal;
sampled binding experiments remain explicit. The three p3k NB-1 comments are
fixed. Historical isolation restores exact requested trigger definitions/order,
including mutations, drops and local sentinels. Its raw-root activation matches
SQL 40, avoiding irrelevant sampled DDL churn without relaxing assertions or
timeouts. Full inventory also exposed stale Refusal aliases: all three harness
routes reloading boundary now reload its captured-exception collaborators.
Import-graph/identity-reload tests cover that family. Isolation/restoration
counterfactuals fail at four assertions each; missing reload fails at one,
all with zero errors. Stopped/development attempts remain uncredited in evidence.

Validation: full gen2-test **4,300 tests**, two existing skips, 4,757.909s;
trigger-order **338 triggers / 4,926 identical Store tests/subtests**; composition
six; focused 101. Full inventory **3,632/3,632 killed**, 3,615 paired controls,
green 1,130-Store/26-file-target baselines; all 14 new predicates have qualified
passing control traces. Full trigger inventory: zero uncovered. All eight
static gates pass and repeat before commit; gateway two 1,540-test suites and
413 mutants pass. All 923 frozen source hashes match. Audit: 502 calls across
78 classified modules, no pending current positives; SQL 01–39 and all 3,618
prior control records unchanged. Both hashes are repinned; service.py untouched.

**4a COMPLETE; whole part 4 INCOMPLETE.** Both SQL promotion successors and the
independent Router consumer remain deferred to 4b as estimated above. Evidence,
attempts, footprint, commands, hashes and remaining scope are retained in
private/evidence/2d-4c-part4/COMPLETION.md; PROGRESS.md is current. No provider,
Gen-1/runtime/8765, real-database migration, protected-register, push or merge
action occurred. Required heavy starts observed no active landing units.

#### 2d-4c part 4a repair 1 — design before code (2026-10-20)

Read Astra round 1 including its executable B1 reproduction, prior 4a completion,
repair/parent briefs and operator rulings, charter/boundaries, flow S4 steps 4/8,
adjudication (b)5/(c)2, methodology §4 and V-4/V-8. Repository-only AGENTS.md
lookup found none. The retained reproduction asserts refusal and currently
fails in both trigger orders: raw /1 `succeeded` commits with all 338 triggers,
foreign keys enabled and zero detailed records. No repository code changed
before this note. The external BUILD-STATE working edit is left untouched.

**Choose the explicit closed-domain option.** SQL 41 adds a BEFORE INSERT guard
for the four legacy summary fields on every current load-bearing positive
receipt, independent of receipt version and extraction method. Each field must
be JSON text in the closed summary vocabulary (`checked_ok`, `checked_problem`,
`not_applicable`, `not_checked`, `unavailable`). SQL 03 continues to refuse the
last two for these verdicts. Thus every remaining operand reaches SQL 40's
all-four performed-reference requirement; SQL 37 independently enforces /2
shape, explicit outcome projection and exact durable binding. /1 cannot carry
references and is refused for this new use. This removes the family cause:
raw admission previously trusted an open summary domain before branching on it.
It covers arbitrary strings and JSON types, rather than enumerating bypasses.

An unconditional replacement of SQL 40 would also close B1, but a separate
closed-domain guard keeps the accepted performed-outcome predicates and their
mutation controls intact and makes raw/Router operand parity explicit. No new
representation, duplicated binding relation, Router logic, JSON column or
promotion authority is introduced. Valid sampled/unsuccessful receipts and
historical readback remain; promotion consumption stays owned by 4b. Classify
B1 as ROOT-CAUSE once discriminating evidence and required gates pass.

NB1 is ROOT-CAUSE: restore the extraction-history helper's complete saved
ordered catalog with restore_triggers(case, None, catalog=definitions), including
exceptional exits. Probe both orders with actual mutated/dropped definitions.
Audit other receipt/capture/quote and promotion consumers by executable probes;
repair any receipt-admission gap, and record promotion-only gaps for 4b.

Estimate **about 360 handwritten repository lines**, including both dossier
notes: SQL/order 20, domain matrix and admitted controls 160, historical helper
and regressions 45, mutant/control wiring 15, documentation 100; generated pins
and control JSON are separate. Private evidence drivers about 250 lines. Stop
and report after DOSSIER if scope grows above about 500. Freeze source before
full gen2-test, trigger-order, composition, full mutation inventory, static and
gateway gates; repin both hashes and qualify the separate accepted control trace.
Heavy starts wait for no active gen2-landing-* user unit. Disposable snapshots
copy .venv-gen2 with cp -a. No provider/Gen-1/runtime/8765/real migration,
protected-register edit, push or merge. Evidence and current progress:
private/evidence/2d-4c-p4a-repair-1/.

#### 2d-4c part 4a repair 1 — implementation and validation (2026-10-20)

Pre-code design: `7111c61`. **B1 ROOT-CAUSE:** additive SQL 41 closes the JSON
text/summary domain on every new load-bearing positive, regardless of receipt
version or extraction method. SQL 03 refuses the two unperformed outcomes;
SQL 40 requires all four remaining performed references; SQL 37 preserves /2
projection and exact binding. Arbitrary strings, mixed vocabularies and JSON
non-strings cannot skip this policy. No production Python, JSON column, accepted
SQL 01–40 or promotion policy changes. Both hashes are repinned.

The exact B1 operand failed the retained refusal regression before code in both
orders and passes afterward, with zero detailed records. Raw/Router matrices
cover all four kinds, both receipt versions, all three methods, adjudicated
supports and unadjudicated partial support; real-record accepted controls and
sampled/unsuccessful/readback behavior remain. The domain-bypass mutant is
assertion-killed with a separate accepted control and qualified SQL 41 trace.
All 3,632 previous control records remain identical; one new pairing is added.

**NB1 ROOT-CAUSE:** the extraction-history helper now restores its entire saved
ordered catalog through the shared restore_triggers helper. Normal/exceptional
exit tests cover both orders and mutated/dropped definitions. Substituting the
old helper yields two assertion failures, zero errors, beside a green baseline.

Frozen-source gates: **4,313 engine tests**, two existing skips (4,910.039s);
**339 triggers / 5,826 identical Store tests/subtests**; composition six; focused
56; **3,633/3,633 mutants killed**, all 3,616 paired controls passing over green
1,136-Store/26-file-target baselines. Gateway: two 1,540-test suites and 413/413
mutants. All eight static gates pass and repeat before commit. All **965 frozen
inputs** match the snapshot and repository; all protected input hashes match.

Executable family audit: 40 malformed quote/capture admissions refuse under
SQL 41, while the same 40 commit if only SQL 41 is omitted. **Still owned by
4b:** six historical canonical/own/validated promotion probes admit support
without references; two sole-receipt historical capture probes also preserve
support through the final commit refence. These explicitly installed old-domain
operands are readback/consumption gaps, not current receipt admission. Both
promotion successors, independent Router consumption and same-receipt binding
remain for 4b; whole part 4 is not complete. No new promotion authority is added.

Initial private mutant/trace fixture-adoption errors and the extra capture
probe's raw-query helper error are retained without passing credit. Final
fixture preparation admits under pristine DDL, then restores the exact subject
catalog, retaining mutations and instrumentation. No source edit followed the
frozen runs; this final dossier note alone is appended afterward. No mitigation
is introduced. No provider, Gen-1/runtime/8765, real migration, protected-register,
push or merge action occurred. Required heavy starts observed empty landing
units; the isolated snapshot's venv was copied with cp -a. Evidence and exact
commands/exits: private/evidence/2d-4c-p4a-repair-1/COMPLETION.md; progress is current.

#### 2d-4c part 4b — design and re-estimate; stopped before code (2026-10-20)

Branch `gen2`, design against `b4dd74c`. Read the complete task and operator
rulings, BUILD-CHARTER/BOUNDARIES, flow architecture (especially S4 steps 4/8/9),
adjudication (b)5/7 and (c)2, methodology synthesis (especially §4), V-4/V-8,
all of this section including the 4a notes, both 4a completion records and
Astra reviews, and repair-1's family/capture-history probes and drivers.
Repository-only AGENTS.md lookup found none. **INCOMPLETE: design only.**
The newest continuation explicitly requires stopping after DOSSIER if the
authority leaves a necessary choice open. No implementation sub-part starts.

**Open operator choice: activation over already-promoted historical claims.**
When a retained load-bearing claim is already `accepted_support` and its only
support is a historical receipt without qualifying detailed records, must
activation refuse that store pending reconciliation, or may that status remain
effective until a later scoped operation rechecks it? If reconciliation is
required, what explicit authority and transaction perform it? No live gen-2
data exists under the 2026-10-18 ruling; this is a specified compatibility
behavior and a fixture question, not a request to migrate a real database.

The authority settles rejection of new promotions using those receipts, but
does not select this treatment of existing acceptance. In particular:

- SQL 03/34 guard an UPDATE of status; installing successor predicates alone
  does not inspect or revoke earlier acceptance.
- SQL 12's final commit refence quarantines only already accepted governed
  captures checked by that operation. An untouched claim, including an
  ungoverned claim, receives no such recheck. Updating its shared relation
  cannot make this an activation-wide reconciliation.
- The accepted §2d-3b3-repair-2 decision says installation declares schema
  only. `CaptureDDLTest.test_installation_no_dml` preserves an accepted row
  across installation even with a mismatching capture. A blanket installation
  UPDATE would contradict that accepted boundary.
- `accounting.candidate_units` selects accepted claims directly by stored
  status. Merely calling retained acceptance "historical" would not prevent
  it from being counted as accepted evidence. Store opening currently checks
  schema identity and connection compatibility, not detailed support of rows.

Flow S4/V-4 and the 4b brief establish the consuming gate; flow S8 preserves
historical completion at its approved revision. Neither supplies the missing
activation/reconciliation policy. The 4a reviews expressly defer promotion
consumption and do not ratify grandfathering or retroactive demotion. This is
an identified limit of these authorities, not an absence claim about other
private records. Do not silently select either policy or change accounting.

**Recommendation, pending the operator ruling:** keep installation schema-only
and immutable receipts/readback intact. Permit normal activation of fresh
stores and stores whose already-accepted load-bearing claims satisfy the new
complete support relation. Refuse active use of a retained store with an
unqualified accepted claim, with an explicit reconciliation diagnostic; do not
silently grandfather its authority or demote it while opening the store.
Preserve it for historical inspection. An explicit, audited Router procedure
would have to reverify or quarantine affected claims before active use; its
authority/scope must be ratified rather than invented here. No live migration
is needed. This recommendation changes admission of retained state and is
therefore a proposal, not an implementation choice already authorized by V-4.

**Settled consumer design, conditional on that ruling.** Add ordered SQL 42+
without editing SQL 01–41. One exact durable-binding relation selects receipts
with all four named performed checks and real records, closed `/2` outcome and
summary projection, matching kind/outcome/topic/claim revision/full ordered
spans/source version and hash/verifier, and the basis-selected examined artifact.
Require actual record presence, not an aggregate that can succeed on an empty
or partial object. Reuse the accepted SQL 37 relationships; an invented `/1`
summary, missing reference or unperformed outcome contributes no authority.
An adjudicated performed failure still needs its exactly bound record.

SQL 03's successor uses the claim's own flag/tier. SQL 34's successor requires
the same candidate receipt to meet detailed checks and the existing SQL 32/33
bound basis; no receipt pooling. Retain tier/use, required/obtained tiers,
acquisition content and both validated-output ceilings, tier-0, contract
admission and canonical-only governed captures. SQL 12's governed-capture
promotion relation and operation-scoped final refence consume that same
qualified receipt. Independent Router checks must read actual records and
bases inside the existing writer transaction, including completed capture
refencing; they must not use the new SQL view as their sole oracle. Reuse
DetailedChecks/EvidenceWriter collaborators; service.py stays wiring-only.
No judgment-quality guarantee, new provider call or JSON column is proposed.

**Conditional estimate: about 880 handwritten repository added/changed lines**:
shared SQL relation and promotion/capture consumers 180; independent Router
consumption/refence 100; exact history preparation and existing fixture/control
dispositions 80; discriminating Router/raw regressions 290; predicate mutants
and control integration 80; a retained-state activation guard/tests if the
recommendation is approved 40; dossier design/completion notes 110. Generated
controls/pins are additional. Retained private drivers are about 300 lines,
reported separately and excluded from the repository guide. A different
reconciliation ruling may enlarge this estimate and must be re-estimated.

This is well above about 500. After the ruling, proposed **4b1 is the SQL
consumer family only, about 470 repository lines**: common relation and both
promotion successors plus SQL 12 capture consumption/refence 180; exact
history preparation 30; raw regressions 140; paired mutants/integration 40;
dossier notes 80. Stop after that coherent SQL slice. **4b2, about 410 lines**,
would add the independent Router promotion/capture/final-refence consumers,
Router/DDL-isolated regressions and retained-state policy implementation.
Neither an estimate nor 4b1 acceptance could claim whole part 4 complete.
This split is conditional; the current dispatch stops before either slice.

Preserve the six claim-promotion and two capture probes as failing-before/
passing-after regressions, with exact ordered catalog restoration on normal
and exceptional exits. Raw records come only from real Router admission
under unmutated DDL. Test both orders/layers, all methods, every kind's exact
bindings/outcomes, historical and adjudicated unperformed checks, same-receipt
non-pooling, every preserved gate, separate accepted controls and replay/
conflict/rollback. Newly ratified activation behavior also needs positive and
refusal controls, unchanged history and no-installation-DML assertions.

Implementation gates remain full gen2-test, trigger-order, composition, full
mutation inventory and uncovered-trigger coverage, separate accepted control
traces, gen2-gateway and all eight static gates, with both hashes repinned.
Every heavy start must wait for no active gen2-landing-* unit; copy snapshot
venvs with cp -a. This documentation-only stop has no affected code/trigger/
fixture or mutation family and needs no functional rerun. Evidence, the input
manifest and resumable next steps: private/evidence/2d-4c-part4b/COMPLETION.md
and PROGRESS.md. Commit this design alone; report INCOMPLETE with the open
choice and recommendation. No protected register is changed by this task.

#### 2d-4c part 4b1 — SQL consumer implementation (2026-10-20)

Implements the SQL-only split designed in `2aeef44`, under the newest operator
continuation. SQL 42 adds one exact detailed-support relation, replaces SQL 03
and SQL 34's promotion guards, and replaces the blocked-capture relation read
by SQL 12's unchanged promotion and operation-scoped final-audit triggers.
All four named, performed, projected outcomes must bind actual records to the
same receipt's topic, claim/revision, full ordered spans, source/version/hash,
verifier and basis-selected examined bytes. Canonical support rechecks its
exact acquisition/content ceiling; extraction support retains SQL 34's bound
basis on that same candidate. Tier/use, output ceilings, contract admission,
tier-0 and canonical-only governed capture gates remain. No scientific judgment
is certified. SQL 01–41, production Python and service.py are unchanged.

Raw regressions retain the six historical claim operands and both capture
operands, testing capture promotion and final refencing independently. Before
SQL 42, all ten refusal assertions fail with zero errors. Real Router-admitted
records supply controls, including distinct target/validator/canonical bytes.
Per-kind binding/outcome, missing/partial/extra references, adjudication,
non-pooling, rollback and exact normal/exceptional catalog restoration are
covered. Earlier historical predicate experiments explicitly isolate the new
relation while retaining their original assertions and mutated definitions;
current detailed-support controls use the complete subject schema. Canonical
tier-0 adjudication remains permitted as before; SQL 34 retains its extraction
no-alarm gate. Paired
mutants cover the new consumers and relation. Both classification pins are
repinned; there are no new JSON columns. Validation results follow in evidence.

**4b1 only. Whole part 4 remains INCOMPLETE.** Independent Router consumers and
retained-state activation remain 4b2; no opening guard, installation DML,
reconciliation or accounting policy is selected here. Evidence and resumable
progress: private/evidence/2d-4c-part4b1/. Stop after this SQL slice.

**4b1 validation integration addendum, before the harness change.** The complete
339-trigger/6,149-subtest order check passes. Full mutation baselines are green,
but the engine's serial module-mutation regression reaches its unchanged
900-second child deadline. Its CLI unconditionally reruns every Store test,
even for selections containing only Python modules. This couples the serial
contamination regression to an unrelated, growing SQL baseline. The harness's
own documented contract assigns Store baselines to DDL/connection loading and
file-target baselines to file loading. Select before choosing baselines: retain
the full Store baseline for any SQL/connection selection, and retain every
selected file-target baseline. Full inventory still runs both. Preserve all
kill/control assertions and the 900-second deadline; add baseline-refusal
regressions and paired mutants. Allow about 60 extra integration lines beyond
the SQL slice's roughly 570, reported separately; no activation policy changes.

**Validation fixture correction, before code.** The next full inventory passed
baselines but ended 3,563/3,661 killed with 98 INVALID cases. A retained probe
traced this to the new baseline-mode test helper: its copied CLI inserted
`/tmp` into `sys.path`, and subsequent Router reloads selected stale scratch
code. Restoring only that search path restores the real mutant/control result.
Isolate the entire helper, including harness loading, in its own search-path
copy and add a preservation regression (about ten lines). Withdraw the
ineffective generic baseline-restoration change; production harness behavior
changes only in the loading-mode selection already described. Require fresh
full engine/inventory runs, with the failed attempts retained in evidence.

**4b1 validation complete.** The final frozen source passes 4,330 engine tests
(two skips), all 3,661 mutation cases (3,644 paired controls; 11 in-killer and
six existing documented exceptions), and all eight static gates. All 28 new
mutants have a separate passing accepted control and a qualifying path trace.
All 339 installed triggers are covered; 6,149 Store tests/subtests pass
identically in both trigger orders. The six composition tests, both 1,540-test
gateway suites and all 413 gateway mutants pass. The retained before-SQL42
counterfactual produces exactly ten assertion failures and zero errors.

The SQL family and required validation integration exceed the original slice
estimate; the exact handwritten/generated/private-driver footprint and frozen
input proofs are retained in private/evidence/2d-4c-part4b1/COMPLETION.md.
The SQL implementation was captured by concurrent commit `9788093`; this coder
follow-up records its verification and completes the harness integration.
**4b1 is implemented; whole part 4 remains INCOMPLETE.** Independent Router
consumers and the operator-ruled retained-state refusal remain for 4b2. No
activation guard, opening change, installation DML or reconciliation is added.
