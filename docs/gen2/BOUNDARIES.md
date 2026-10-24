# Gen-2 Boundary Contract

The operational boundary specification the code must conform to; Astra's Gate A checks every phase diff against this file. Derived from the flow architecture §0 (amended 2026-09-25) and the adjudicated rulings. **Drift rule:** if code and this file disagree, that is a BOUNDARY-DRIFT finding — one of them changes through the amendment path; the code never silently wins.

Format per component: *Definition* (what it is) / *Owns* (decisions only it makes) / *Produces* (typed hand-off artifacts) / *Must never* / *Checked by*.

## Router
- **Definition:** the single logical writer to authoritative engine state; code, no model calls in its decision path.
- **Owns:** scheduling and leases; every state commit via `commit_outcome` (authenticated, revision-bound, idempotent envelopes; fenced finalization); checkpoint cadence and the coalesced signal queue; decision-policy application (mapping a provider answer + confidence + class to a permitted action); completion-candidate assembly; export outbox commits with immutable export manifests (operator ruling 2026-09-26: the one outbound path, `docs/gen2/EXPORT-API.md`).
- **Produces:** commit receipts (linking decision receipt ↔ transition ↔ evidence, one invocation ID); leases with generations; holds (typed, owned, deadlined); dossier snapshots; outbox events.
- **Must never:** exercise research judgment; execute agent-supplied code; accept caller-supplied role labels (authority derives from capability); write through any path other than its own transactions; soften or reinterpret a qualification.
- **Checked by:** Gate A on every diff; the deterministic replay audit (decision receipts vs retained raw provider responses; qualification recomputation); crash-fencing release gates.
- **Router composition (internal structure, tasks 2q-b2, 2q-b3, 2q-b6, 2q-b7, 2q-b8 and 2q-b10; no change to what the Router owns or may do):** `service.Router` is the core: it holds the store, the clock and every transaction (`_guarded`, `_snapshot`, `_transaction`), and keeps every public method name. A responsibility separated from it is an explicit **collaborator** the Router composes (`Status` in `status.py`, `Capabilities` in `capabilities.py`, `Registries` in `registries.py`, `Lifecycle` in `lifecycle.py`, `Scheduling` in `scheduling.py`, `Amendments` in `amendments.py` and `EvidenceWriter` in `evidence_writer.py`; the Router inherits no mixin). The pattern, applied exactly: (1) the collaborator declares, in its own module, the interface it takes of the core as a `typing.Protocol` (`StatusCore`, `CapabilityCore`, `RegistriesCore`, `LifecycleCore`, `SchedulingCore`, `AmendmentsCore`, `EvidenceCore`): only the members it uses, a member with no comment being the core's own and a comment naming a collaborator identifying the core delegate to its member; the Router implements it structurally and never inherits it; (2) it is constructed with the Router (`Status(self)`), holds that one reference (`self._core`) and reaches the store, the clock and the transaction only as `self._core.…`: it opens no transaction of its own and holds no store handle, and a collaborator that writes does so inside the transaction the core opened (the lifecycle, scheduling, amendments and the evidence writer open none: their write routes and every write of the Router's lifecycle members run in `_guarded`, as do the impact, replacement and fence members of amendments, inside the approval's transaction, and the evidence writer's rows, inside the commit's); (3) the store and schema handles are typed by narrow protocols of the collaborator's own (`Rows`, `Schemas`, and for the lifecycle `Spool`; the evidence writer declares `Rows` alone), so the interface adds no import edge; (4) the Router's public method delegates to the collaborator (`healthy`, `status`, `record_capability_probe`, `record_gateway_facts`, the registries' six public routes, the lifecycle's three, `request_cancel`, `reconcile`, `invocation_status`, scheduling's five, `requeue`, `open_reservation`, `open_review`, `create_topic`, `raise_signal`, and amendments' six, `version_brief`, `open_brief`, `mark_brief_overdue`, `propose_amendment`, `draft_contract`, `close_brief`), as does each non-public member the rest of the Router still reads (`_active_bundle`, `_bundle`, `_router_policy`, `_templates`; the lifecycle's `_evidence`, `_bind_evidence`, `_record_artifact`, `_require_delegates_ended`, `_release_capacity`, `_open_unknown_hold`, `_cancel_in_transaction`; scheduling's `_lane_last`, `_admit_lane`, `_draw`; amendments' `_open_topic`, `_pin_status`, `_brief_standing`, `_record_impact`, `_record_replacements`, `_recorded_references`, `_require_current_pins`; the evidence writer's `_write_evidence`); (5) `gen2/tests/test_router_composition.py` keeps the declaration true (every member used is declared, every declared member is used and the Router has it, the collaborator holds only the core, only the status module names `_snapshot`, a direct-member/module-use check). A collaborator that needs another collaborator's method takes it through the core like any other member (the core's member delegates to it); historically, while mixins remained, the same held of their methods. **What this is not (limits, stated so the pattern is not copied as a stronger claim; Astra's 2q-b2 review):** the composition tests compare member *names* (every `self._core.<name>` used is declared, every declared name is used and the Router has it); they do not check signatures, types, aliases, the members of the nested `Rows`/`Schemas` protocols or full `Protocol` conformance, and nothing at run time enforces the interface. `_snapshot()` is the Store's own writable transaction (`BEGIN IMMEDIATE`, the real Store yielded), not a read-only one: only the status read and the health probe take it (the test is a direct-member/module-use check: among the collaborator modules only `status.py` names `_snapshot`; it does not look inside a transaction body, so a write in one would not fail it, and those bodies stay a manual review), and what keeps them from writing is that they do not. A collaborator that writes reaches the write primitives through `self._core._store`, and the Store requires an active transaction, not specifically `_guarded`: every write of the capability record and of the registries is made inside `_guarded` (which reads the clock after the lock is held) except two in `registries.py`, which kept the transaction they always opened for themselves (the core's `_transaction()`, the same call): the dated fact a refused bundle leaves (a store error there propagates, it is not a second refusal) and a start's recovery fact (the clock is read only when there is an active bundle). The syntax-only import graph does not show a collaborator's dependency on the core, the injected store or the schema set; the protocol declarations do. Both are internal conventions for trusted Router code, not a security boundary.
- **Router evidence write (internal structure, tasks 2q-b9 and 2q-b10; no change to what the Router owns or may do):** `Router._write_evidence`, the evidence and governance rows of one commit, is a thin private delegate to `EvidenceWriter._write_evidence` in `evidence_writer.py` (task 2q-b10; a collaborator by the pattern above, `EvidenceCore` declaring the four core members it reads: `_store`, `_one`, `_pin_status` and `_work_of_topic`). The writer keeps the plain inserts (holds, receipts, screening assessments, review triggers, outbox events) and calls five private helpers of its own for the rest: `_write_claims`, `_promote_and_link_claims`, `_write_scoping_reports`, `_write_source_proposals` and `_close_review_episodes`. Each is a contiguous block of the original, split out verbatim by task 2q-b9 (extract-method only: no statement rewritten, reordered or merged, no error type changed) and moved with it into the writer by task 2q-b10 (apart from `self._core.` in front of the core's four members, the text is the same), takes as parameters the locals it read, is called once and in the original order, and runs inside the transaction `_commit_in_transaction` already holds (`_guarded`: `BEGIN IMMEDIATE`, the clock read after the lock, rollback and refusal as before): it opens no transaction, reads no clock and reaches the store only as `self._core._store`. Task 2q-b9's historical `tools/gen2_move_equivalence.py --inline` acceptance claim is **superseded**: the checker remains defective and advisory, and its `IDENTICAL` output supplies no behavioral guarantee ([Astra's 2q-b8/2q-b9 re-review](/home/trevor/work/research-loops-public/private/reviews/gen2-2q-b8-b9-astra-rereview-20261008.md)). Both tasks were accepted under the charter's [Refactor evidence standard](BUILD-CHARTER.md#review-throughput): rope output is untrusted, RefactoringMiner describes the changes through `tools/gen2_refactoring_detect.py`, and existing tests, mutants and the accepted exact replay gate behavior; `gen2/tests/test_router_evidence_wiring.py` covers both. Limit: neither a detector nor the replay establishes name-resolution equivalence, and unresolved replay scenarios supply no differential evidence; the wiring tests, mutants and manual review remain necessary.
- **Router refactor replay coverage:** the historical 2q-b8/2q-b9 record was **658 same / 0 different / 352 unresolved**. [Astra's 2q-b10 review](/home/trevor/work/research-loops-public/private/reviews/gen2-2q-b10-astra-review-20261008.md) verified the later measured **1,004 same / 0 different / 6 unresolved**, while explicitly withholding acceptance of the 2q-t4 seams and closure of DEBT-023 item 1. The subsequent [2q-t4b evidence](/home/trevor/work/research-loops-public/private/evidence/2q-t4b/README.txt) reports **1,003 same / 0 different / 7 unresolved** on `c02fa74` to `8bc87cc`: the five real-identity cases, one concurrent-probe case and one recovery polling case remain unresolved. That task's review is pending; these are reported results, not accepted additional coverage. Its natural-polling comparison reports **353 same / 0 different / 31 unresolved** in 384 supervisor scenarios, and the default first-look wait omits 1–3 running-job polls in 78 tests. The seam qualification and polling coverage disposition remain under DEBT-023 item 1; a reduced unresolved count alone does not close it.
- **Router commit transaction (internal structure, task 2q-b11; no change to what the Router owns or may do):** `Router._commit_in_transaction`, steps 3-4 of `commit_outcome`, keeps the replay check, the two lookups, the fault points, the audit event and the return, and calls nine private helpers of the Router, each a contiguous block of the original split out verbatim (extract-method only: no statement rewritten, reordered or merged, no error type changed), taking as parameters the locals it read, called once and in the original order: three fences that read and refuse (`_fence_against_current_state`, `_fence_outcome_kind`, `_fence_changes_since_validation`), two that decide (`_decide_effects`, `_decide_triggers_and_outbox`), `_build_receipt`, and three that write (`_write_topic_and_artifacts`, `_write_operation_receipt`, `_write_final_effects`). All nine run inside the transaction `_guarded` holds (`BEGIN IMMEDIATE`, the clock read after the lock and passed down as `now`, never read again, rollback and refusal as before) and reach the store as `self._store`, as the blocks did. The split was made under the charter's "Refactor evidence standard": rope's extract-method performed it (two faults in its output, a comprehension variable and an earlier loop's variable passed on as if they were defined, were removed by hand), RefactoringMiner described it (`tools/gen2_refactoring_detect.py --expect "Extract Method=9"`), and the existing tests, `gen2/tests/test_router_commit_wiring.py` (a refused write of each helper that writes rolls the whole commit back and leaves one `commit_rejected` audit event), the 2QB11 mutants and the accepted exact replay gate it. Limit: neither a detector nor the replay shows that a name resolves as it did, and the replay does not compare its unresolved scenarios; the tests and the mutants stand behind that.

The registries collaborator records the dated `tier-0 disabled` capability
fact in config activation/restoration transactions (2d-5, operator ruling
2026-10-10 / DEBT-037). It remains unknown, with no last success; ordinary
status reads expose it without writing. Bare opening/admission records no
capability fact; its lifecycle write is D part 3's generation epoch renewal
described under Evidence accounting below.

The Router also composes `Verification` in `verification.py` (2d-4 part 1),
with `VerificationCore` declaring only `_store` and `_one`. Its hold writer
runs inside the existing commit transaction, reached through the core's thin
`_write_verification_holds` delegate from EvidenceWriter. It maps attributed
adverse verification verdicts to existing typed holds: disagreements require
primary adjudication; missing required content requires remediation. Actual
claim production/lease records supply the primary owner and deadline. Receipt
and audit effects identify generated holds, exposed by the existing status
reader. Replay/collision/rollback use the existing commit mechanism; later
support never clears retained disagreement. No semantic judgment, clock,
transaction, provider call or escalation scheduler is added. SQL protects
existing hold shape/open creation/identity/clearance; verdict routing is a
Router responsibility. Re-access and acquisition/content-tier admission are implemented by SQL 14–19 and their Router consumers. SQL 20 adds the same recorded-full-text minimum for table citations across all three receipt methods, including insertion through the Router, with truthful insufficient access retaining the existing hold. SQL 21 establishes unique decoded names, exact member sets in the receipt objects used by SQL 03, and the cited-span/locator domain before raw table admission. Offset integrality and minima are checked from preserved numeral text, including decimal/exponent spellings, without REAL rounding. This establishes unambiguous bindings and exact span semantics; raw SQL does not enforce the entire JCS/C-13 serialization contract, which remains enforced by the Store/Router writers. Structured rows alone confer no table availability. Durable table-locator binding and detailed check receipts remain later 2d-4 work; deadline escalation remains 2e2.

`AcquisitionAdmission` in `acquisitions.py` (2d-4b2) admits fixture re-access
through `Router.admit_reaccess`. Its narrow core protocol includes the existing
snapshot/writer fence and a station-owned retained-exchange reader injected at
construction, never supplied in an agent request. It selects capture identity
from recorded rows, binds the actual attempted request and retained response
octets, and runs the pure validator outside the writer lock. Under the lock it
revalidates operands, verifier authority, live state, lease, pins and topic pause.
SQL 14 retains exact operands/lineage with verifier attribution; equal replay
adds nothing and conflicts roll back. SQL binds recorded relationships and size;
the Router authenticates and hashes bytes. This record supplies no tier, table,
extraction-validation or support authority. Canonical-byte receipts consume it
(SQL 15, task 2d-4b3 slice 1); durable table-locator binding remains subsequent 2d-4b3 work; trusted workflow capture execution
remains 2e2.

`ExtractionRecords` in `extractions.py` (2d-4b3e1) authenticates retained
output and comparison artifacts outside the writer lock, then writes through
the existing fenced outcome transaction after artifacts and its operation
receipt. Attribution comes from the committing capability. SQL 22 retains
immutable extraction inputs (the complete SQL 14 key), extractor identity and
version, output reference and content-capped tier, plus validator lineage,
method, policy version, comparison evidence and outcomes. Under the closed
`extraction-validation/1` policy, an independent method needs a distinct
extractor identity and a validator distinct from source producer and target
extractor, with its own extraction of the same acquisition. Equal output hashes
establish byte agreement; semantic agreement remains the validator's attributed
assessment. Failed results and same-extractor integrity replay never satisfy
method success. The /1 result view has no receipt or support consumer.
SQL 34 consumes only the SQL 32/33 durable bases described below. The store binds
records; it does not certify extraction execution or semantic correctness.
SQL 28 and `ExtractorRegistry` in `extractor_registry.py` (2d-4b3e2 part 1)
require every new extraction to pin an immutable operator-approved registry
revision and exact canonical tool identity. The authenticated operator surface
supplies the approving identity; its complete tool/family mapping and reason
are retained in an immutable audit event, with raw DDL binding revisions and
entries to that event. Changes require increasing revisions; identical requests
replay and conflicts refuse. Outcomes cannot maintain the registry. Canonical
tool/family names are lower-case ASCII; unknown tools, aliases and case,
whitespace or NUL-suffixed variants cannot satisfy admission. Historical rows
without a registry pin stay readable. Identity is still declared rather than
execution-derived; station execution checking remains 2e2. SQL 29 now installs successor
`extraction_validations_v2` records and their readback result view under
`extraction-validation/2`. Both operands retain non-NULL historical registered
pins. For comparison, both canonical tool identities must be registered under the validator extraction's
pinned operator-approved revision; missing common membership refuses, without
inheriting older mappings. Both families resolve under that one revision.
SQL 31 and ExtractionRecords require this pin to equal the current registry revision when a new /2
validation is admitted, checked inside the writer transaction after same-outcome
extractions. An operator update therefore takes effect at admission, including
updates after artifact authentication. Retained validations keep their original
interpretation and identical committed-operation replay remains readable.
Independent extraction requires different families there; a rename of the same
tool or a whole family across historical pins cannot manufacture independence.
Same-family replay permits byte equality or disagreement and remains integrity only, even across tool
identities/versions. Exact acquisition, independent validator/producer lineage,
retained evidence and byte-hash comparisons remain enforced in Router commits
and raw DDL. The optional successor outcome array authenticates evidence outside
the writer lock and derives attribution from the committing capability. SQL 30
guards its new comparison JSON column under the closed member-name family.
SQL 32 extends only the receipt domain's optional extraction_id member and
requires new verifier_extraction receipts to consume their own non-NULL-pinned
source_extractions row. Exact acquisition, work/version, verifier lineage,
extracting invocation, canonical tool and sufficient output tier must bind.
EvidenceWriter independently checks inside the writer transaction after receipt
insertion, with rollback on refusal; SQL 18/19 retain their earlier diagnostics.
SQL 33 requires validated_extraction receipts to consume a durable /2 validation
with method_succeeded = 1 and the receipt's verifier. Its target must match the
same acquisition, topic/work/version/verifier lineage, declared extracting
invocation and canonical tool, non-NULL registry pin and sufficient output tier.
EvidenceWriter independently checks these relationships and caps receipt access
by the exact validator extraction output tier inside the same writer transaction. validation_ref is an exact durable /2 ID; free text alone, /1-only,
failed, integrity-only/same-family, invented, foreign-lineage and NULL-pin bases
refuse. New validations obey SQL 31 at their admission; receipt consumption
preserves retained interpretation after later operator registry changes.
Positive controls for both extraction methods retain durable bases.
SQL 34 retires SQL 17's blanket fence and rechecks each receipt's durable
basis through bound_extraction_receipts. A load-bearing supports receipt may
authorize promotion through its verifier's own pinned extraction, or an exact
successful independent /2 validation, with all SQL 32/33 relationships intact.
That same receipt must meet the claim's required tier and performed V-8 checks,
with no tier-0 alarm. Validated authority is capped by both the target and exact
independent extraction output tiers and the acquired record content ceiling,
including retained receipts. Own extraction keeps its own output/acquisition
cap. A success label or adjudication cannot waive either operand ceiling;
low-tier and failed extraction/validation records remain history.
Historical unbound, free-text-only, /1, failed and integrity-only bases remain
fenced with SQL 17's diagnostic. SQL 12 and EvidenceWriter's governed-capture
checks remain canonical-only because extraction records supply no new governed
quote/span binding. Verification attention reads SQL 34 through the Store
read primitive after receipt insertion: supporting bound extraction receipts
create no unbound-extraction hold; fenced declarations retain that remediation.
Truthful insufficient access always creates missing-content remediation, even
with a bound basis. Verdicts partially_supports and does_not_support create
disagreement attention. Support
never clears earlier disagreement or remediation. The immutable operation
receipt plans hold IDs assuming successful SQL 32/33 and Router admission in
the same transaction, including same-outcome bases; failed admission leaves
no effects. Stored holds, operation effects and audit IDs agree, replay adds
nothing, and failures roll back all writes. Promotion gates are unchanged.

SQL 23 begins the store-wide JSON member-name domain: decoded names are unique
within each actual object under binary equality and contain no U+0000. NUL
in string values remains allowed. This first repair part covers extraction
output/comparison references and `quote_checks.match_result`, with INSERT and
UPDATE guards generated from one checked template. Router outcome admission
and Store preparation refuse these names before logical serialization/writes;
the matcher emits fixed result names. JSON2 part 1 adds both guards on the
three search_observations JSON columns. Its Observations collaborator in
observations.py admits logical names before hashing, through the same Router
transaction and existing capability/lease fences; service.py supplies only
construction and public delegation. ObservationCore declares the schema,
transaction, audit and existing observation-write members it uses. The composition
tests include this collaborator. A failed attempt whose request is not admissible
as logical JSON for any strict-parse reason retains the supplied request text as
exact UTF-8 bytes plus their SHA-256, alongside an explicit logical byte
reference, in the existing failed-attempt ledger. Router and Store recompute
the byte hash; SQL 24 binds its labels/exact member sets and failed/unobserved
shape, and SQL 25 requires the descriptor's own same-row bytes even when both
byte fields would otherwise be absent. Ordinary Router requests cannot carry
the reserved top-level retained_request member. Raw DDL does this without
claiming raw SQL proves SHA-256 truth. Replay compares the bytes; accounting
counts these observations with an unknown result count and no decoded page
after validating the whole bound representation; malformed bindings raise
an explicit error instead of being read as logical pages.
Repair-1 part 2 uses an opaque descriptor without a decoded request type or
page, independently of the refused document's discriminator. Duplicates are
never reparsed with last-value-wins. Existing typed descriptors stay bound and
readable. SQL 03 admits the opaque marker only through SQL 24/25's complete
binding. Ordinary observed requests retain the closed discriminator.
The client emits the text/byte-hash representation for refused request names.
Other callers with original octets supply their unchanged UTF-8 text. Before
whole-command normalization, object requests are isolated; after envelope
admission their existing JCS serialization supplies exact hand-off bytes and
the matching supplied identity. An already parsed object cannot prove an
earlier byte spelling. No original key or supplied octet is rewritten or dropped.
Authenticated failed attempts remain recorded regardless of strict-parser error
order, including numeric bounds/precision, decoder digit/nesting limits, syntax,
non-finite values, Unicode, duplicate and NUL names. The supplied hash, valid
failed/unobserved envelope, capability, running invocation and current lease
are still required. SQL 24's
historical member_name_domain descriptor tag remains unchanged; an
observation_request_refused audit event records the actual first refusal class
as a label, bound to the observation ID, byte hash and invocation, in the same
transaction. Replay adds no refusal audit. Classification never decodes the
refused document; observed/exhausted requests still require strict logical
numeric/name admission and the closed discriminator. The
store-wide JSON member-name rollout is complete: the static DDL check covers
all 37 logical JSON columns and has no pending entries. Member-domain
normalization is enabled by default for every Router document entry point and
for every Store JSON writer,
including contract confidence labels and every other admitted open map.
Store admission is independent of installed trigger coverage. SQL 23 covers
six columns, ordered additive SQL 26 covers eight more and SQL 27 covers the
final 22 of that rollout; SQL 30 adds the successor comparison column under
the same family. Every column has both INSERT and UPDATE guards. SQL 21's receipt
uniqueness predicate is now redundant under the whole-receipt member-domain
guard and remains unchanged; its span-shape and
preserved-numeral guarantees remain necessary and unchanged.
Retained provider/artifact/request BLOBs stay raw.

SQL 16 and SQL 19 (2d-4b3c2) cap every receipt method/verdict at its
consumed acquisition's recorded content: the selected record's nonblank abstract
or full-text body, with `metadata_only` unable to certify full text. Links,
record-kind labels and availability flags alone grant bibliographic access;
recorded content supplies no reproduction evidence. Both consumers reuse
SQL 16's `source_acquisition_content_tiers` selected-record rule. SQL 18 binds
both extraction methods to admitted input, independently of extractor identity.
This check runs in the
existing receipt insert transaction, including raw inserts. Nonblank means
`recorded-nonblank/1+ucd17.0.0`: a text field with a code point outside Unicode
17.0.0 White_Space and Default_Ignorable_Code_Point (DOSSIER repair-1 cites
the pinned standard). Whitespace/format-only bodies grant no content tier.
SQL 34 replaces SQL 17's fence only for receipts consuming their own pinned
extraction or a successful independent /2 validation with sufficient target
and exact independent output tiers and recorded content, load-bearing use
and all V-4/V-8 requirements. Historical
unbound declarations remain non-authoritative; new ones refuse admission.
SQL 12's capture consumer and EvidenceWriter remain canonical-only: an
extraction basis cannot preserve support against a later governed capture
without a matching canonical receipt. Verification creates unbound-extraction
remediation only for supporting extraction receipts outside SQL 34's bound
basis view, using the producer's owner/deadline. Bound support creates no new
verification hold.
Later support never clears existing disagreement or remediation holds. Truthful insufficient-access receipts
remain admissible and create the missing-content hold; inflated declarations are
refused. Durable table-locator binding remains subsequent 2d-4b3 work.

## Station supervisor

- **Definition:** the one lifecycle implementation for every execution kind (research pass, discovery, delegate, verification, checkpoint); code.
- **Owns:** launch intent records before spawn; process identity (invocation/job handle + host/boot/start fingerprint — never bare PID); deadlines, cancellation, descendant handling; result retention and durable delivery receipts; structural telemetry (progress signatures, capability probes, retrieval-event capture at retrieval time); snapshot assembly for checkpoints/decisions (typed records + extractive quotes only).
- **Produces:** invocation records `admitted→launching→running→result_ready→committed` (+ explicit cancelled/failed/`outcome_unknown`); staged immutable content-addressed artifacts in the protected spool; search observations with request identity/coverage/yield; screening-event records.
- **Must never:** trust agent self-reported completion; let an agent write authoritative state or the spool destination path; treat `outcome_unknown` as vanished/failed/retryable/done without reconciliation; compute *semantic* research judgments (novelty, applicability, entailment — those are labeled assessments by models).
- **Checked by:** Gate A; lifecycle release gates (spawn/receipt uncertainty, timeout, cancellation across all kinds); state-integrity audit sampling.

## Evidence accounting

The internal Store `capture_topic` primitive (2d-6a D part 1) copies a fixed set
of topic-related raw rows in a checked Store-owned read snapshot. Durable
capture opens a DML-prohibited reader of the same authoritative WAL file;
in-memory fixtures reuse their checked connection with temporary query-only
protection. Readers close before pure work, including on failure. The accounting
collaborator closes all three existing readers and branch provenance onto this
capture and pure conversion; other Router `_snapshot` paths retain their fence.
Frozen tuple/scalar
records retain JSON text, BLOBs, column metadata and empty groups; a separate
pure `dossier-input/1` hash binds that raw preimage and explicit history after
capture. It grants no write, completion, approval or commit-freshness authority.
Public accounting signatures/results and pre-contract inventory behavior are
preserved. D part 3's ordered SQL 43 maintains a durable singleton generation
for every row event on all 37 capture relations, including unrelated topics
and same-value updates; rollback removes its bumps. It protects the singleton
and refuses exhaustion or missing/incompatible schema guards. Checked durable
open renews its epoch under a writer fence; offline restore/DDL closes all
runtime handles before reopening. The epoch, schema cookie and admitted file
identity supply lifecycle invalidation that row triggers cannot. D part 4
owns their binding into capture, commit consumption and bounded recapture.
The internal `Router._dossier_inputs` read delegates to that collaborator,
requires a captured attributed approved contract, and returns immutable complete
raw history, typed coverage and a history-bound content hash after closure. It
refuses unknown topics and missing approval; existing pre-contract inventory
reads remain available. It performs no persistence, adjudication or gate change.
The original writer-capture D1 trial failed; the full assembly path is not ready.

- **Definition:** pure arithmetic over typed records; no model calls, ever.
- **Owns:** aggregation of novelty/yield/accrual/coverage/verification tiers from event-derived inventories; stopping-dossier assembly against the contract's declared profile; the four candidate units (retrieved records / deduplicated works / assessed candidates / accepted claims).
- **Produces:** versioned dossiers with per-rule operands and `satisfied / not_satisfied / unknown`; conjunctive-gate status; per-branch accrual views.
- **Must never:** treat unknown as zero (zero-assessed windows are UNKNOWN novelty); count failed/partial passes as saturation evidence; multiply evidence across overlapping lanes; accept an agent-written total as a denominator; pretend arithmetic establishes semantic novelty, independence, or sufficiency.
- **Checked by:** Gate A; denominator-zero / repeated-study / changed-protocol / unresolved-contradiction test fixtures (Gate C-reviewed).
- **Contract confidence declaration (2c-4a part 1):** Contract v2 optionally declares a closed, plan-specific categorical scheme with id/version and a rubric for every allowed label; no engine scale or implicit legacy default. The existing Router amendment collaborator treats the complete declaration as protocol content, including addition/removal, and the existing contract hash/approval and G-1 impact path bind it. `gen2/tests/test_confidence_contract.py` and schema counterfactuals cover this declaration; recorded-confidence admission, reconciliation and `/2` remain part 2 (ACCOUNTING.md).
- **Reconciliation operands (2c-4a2 first slice):** `gen2/accounting/reconciliation.py` defines explicit assessment/open records and a complete supplied history envelope. Its pure confidence check requires the exact supplied contract revision/hash and topic/protocol/framing pins, and scheme id/version/label membership; unknown keeps its reason, and open has no assessed confidence. These fixture operands establish consistency only, with no proof of approval, provenance or durable admission. DEBT-033 (2d) owns admission/assembly and DEBT-034 (2e2) judgment production. Tests are `gen2/tests/test_reconciliation_operands.py`, paired by 2C4A2 mutants. The lossless mapper/inverse into additive `export-bundle/2` (task 2c-4a3) is accepted: `gen2/schema/export-bundle-v2.schema.json`, checked by `gen2/tests/test_reconciliation_bundle.py` and paired 2C4A3 mutants, including the end-to-end unresolved-contradiction fixture at the explicit-operand scope; `/1` is byte-unchanged. No Router or export wiring is added; enabling `/2` on the approval/assembly path is DEBT-033 (2d).
- **Attributable operands (2c-2a):** `gen2/router/assessments.py` is a Router collaborator for the optional outcome/1 semantic-assessment section and its source-lineage extensions. `Assessments.validate` admits only contract-admitted primary invocations with matching protocol/framing pins and topic-retrieved subjects; the existing commit boundary binds evidence artifact references. `Assessments.write` repeats admission under the commit lock and appends immutable records with the invocation, operation and Router date. This records labels without producing judgments (2e), granting provider authority or changing work identity. `Router.evidence_inventory` reads these histories beside the four-unit inventories in one Store-owned capture, then converts after reader closure; lineage inherits exact attribution from its assessment. Current-framing/lifecycle/accrual selection is 2c-2b; this read exposes raw history only.

- **Dated lifecycle (2c-2b1):** The same collaborator appends `source_lifecycle` with primary authority and Router attribution, topic-retrieved subjects/related works, pinned protocol/framing, retained evidence and explicit same-subject predecessors. A successor must follow its predecessor in recording time. The inventory reads lifecycle history in its existing snapshot; pure `gen2/accounting.lifecycle_view` applies explicit replacements as of an exact UTC instant and retains competing active records. It does not grant support authority. Contradiction/branch dispositions, current-framing/accrual selection and G-1/E-9 remain 2c-2b2.

- **Registry histories (2c-2b2a):** `Assessments.write_dispositions` appends contradiction/branch records in `registry_dispositions`, using the same primary authority, protocol/framing pins and retained evidence. Registry identities are topic-local and kind-specific; a predecessor must match that identity and precede its successor in Router recording time. The typed inventory retains every judgment in its existing snapshot, including unresolved contradictions and disagreement. Branch promotion is a recorded proposal, granting no authority. Current-label/accrual selection and G-1/E-9 are the remaining 2c-2b2b slice (ACCOUNTING.md).

- **Accrual operands (2c-2b2b):** That inventory snapshot also reads the approved contract revision, recorded contract amendment standing and reopened exclusions, and reason-coded screening history. Pure `semantic_accrual` joins exact assessment lineage and work/version lifecycle; `branch_accrual` retains promote/park/drop history and dated explicit replacements, including reversals and competing judgments. `label_standing` consumes recorded standing only: compatibility permits reuse, invalidation remains stale across cycling, and missing standing yields unknown effective operands. `rescreening_view` exposes only recorded reopened exclusions with their original framing, reasons and attribution. No writes, protocol comparison, inferred impact, judgment production or scheduling authority. Existing accounting/adapter and instant-helper ledger admissions apply without a new budget (ML-0009–ML-0013, ML-0027/0030/0031).

- **Stopping signals (2c-3a):** Pure `gen2/accounting/stopping.py` retains typed per-rule operands with topic/contract/protocol pins and `stopping-result/1`. Descriptive yield makes no stopping predicate; coverage uses certain-answer bounds over scoped attempted windows, counting only E-4 distinct completed windows with usable recorded G-1 standing as eligible and retaining ineligible/indeterminate windows with reasons (`window_standings`, ACCOUNTING.md); known-item retrieval checks declared sentinel work identities against deduplicated works. Explicit recursive all/any and separately conjoined declared gates preserve unknown and refuse mismatched result pins for composition. Gate status/evidence are assembly inputs, not evidence generated here; no evaluator supplies scientific sufficiency. Ledger ML-0033–0036 admits the file and its existing accounting/core dependencies.

- **Stopping admission/bindings (2c-3b):** The existing amendment collaborator checks schema shape and pure evaluator bindings before draft/amendment admission; thin approval wiring repeats the check on the stored revision. Refusals name the rule and reason. Schema-reviewed-only families remain reviewed; statistical recall, diminishing-return thresholds, counterevidence rules and screening/both sentinels have no implemented automatic evaluator and are refused. Pure profile bindings preserve expressions, gates, prerequisites and parameters; reviewed rules have no automatic evaluator. The known-item retrieval binding requires the exact declared sentinel artifact reference before calling the 3a evaluator. Ledger ML-0037–0045 admits the support dependency and its transitive reach.

- **Additive vocabulary and reuse (2c-3b2):** Closed descriptive parameters declare no stopping predicate. Coverage requires a positive minimum and an explicit invocation scope; it remains an E-4 prerequisite beside coverage-integrity and sufficiency requirements. Both bind at the existing admission/approval boundaries. Pure profile composition may consume the Router's inventory snapshot and recorded G-1 standing to reuse current/compatible rule results with matching topic/protocol pins, retaining original contexts. Incompatible or unknown-standing results and their operands are omitted, so affected expression leaves are unknown until explicit current evaluation. Gate inputs require exact current pins; gate production/validation and sufficiency authority remain 2d/2e/operator. Router fixtures exercise stopping-protocol versioning, incompatible invalidation, current re-evaluation and compatible reuse; no Router surface or dependency is added.

- **Research-state views (2c-4b):** Pure `gen2/accounting/views.py` composes the existing typed inventory read into coverage and depth. Coverage retains four units, all attempted-window capture standings/reasons, exact observations/search identities and separate recorded G-1 standing. Branch coverage consumes explicit supplied snapshot links only; missing links/windows remain unknown. Depth retains exact semantic lineage, dated lifecycle history/active records, branch and contradiction histories including unresolved/competing records, recorded impacts and reopenings. The caller supplies the date; G-1 reflects the supplied snapshot. No clock, writes, provider calls, sufficiency predicate or new Router wiring. Checked by `gen2/tests/test_research_views.py` and paired 2C4B mutants; bundle reconciliation is the accepted 2c-4a codec (above).

- **Durable branch/window provenance (2d-2 / DEBT-032):** The existing `Assessments` collaborator admits optional outcome/1 `branch_windows` proposals only from contract-admitted primary invocations. It validates the exact same-topic branch registry identity and a real same-topic contract-admitted research-pass window, then appends Router invocation/operation/date attribution inside the existing commit fence. Ordered DDL retains and binds the record. `Router.coverage_snapshot` captures the inventory, admitted `BranchLink` operands and `WindowPin` revisions derived from each window's exact durable invocation/contract in one snapshot; view computation occurs after it returns. Missing/unverified provenance stays unknown. Pure fixture links/pins confer no authority for dossier assembly. Ledger ML-0057–0062 admits only the existing pure view types and their transitive reach; no arithmetic writer, provider authority or scientific verdict is added.

## Decision layer (DecisionProvider: Jev primary, LLM fallback)
- **Definition:** typed selection among enumerated options with criteria embedded in pinned, versioned questions; every call runs under a full DecisionSpec (class, provider, model/version, primitive semantics, question version, input-builder version, protocol, action-policy version).
- **Owns:** nothing autonomously. It answers; the router's policy acts.
- **Produces:** decision receipts — inputs, provider response (raw digest retained at the station/adapter boundary), policy, authorization, action, outcome; provider-specific uncertainty in provider-specific form (an LLM label never carries an invented probability).
- **Must never:** generate options; re-fetch evidence; see free prose it must trust (snapshots are code-assembled; retrieved text is data, never instructions); write state; carry governance authority; let fallback inherit Jev's qualification or pool uncertainty statistics across providers; default a missing confidence to a pass; act above advisory in any class that has not passed provider+class-specific held-out evaluation and shadow traffic (initial rollout: screening in shadow, method-selection advisory — nothing else).
- **Checked by:** Gate A; the §3.6 replay audit; blind-sample calibration protocol; pre-authority adversarial tests (altered distributions, mismatched policy versions, revoked qualifications ⇒ rejection or visible control incident).

## Primary agent (per-station frontier LLM)
- **Definition:** the research-judgment seat.
- **Owns:** reading evidence (action-bearing evidence raw, per SRC-106); relevance/confidence judgment within the protocol; integration and synthesis drafting; proposing typed transitions, obligations (inside templates), method designs (inside coherent templates), reframes, and semantic trigger observations.
- **Produces:** typed RPC proposals; recorded assessments with provenance; deviation self-reports in completion reports.
- **Must never:** write state directly; verify its own claims; expand scope; prune approved questions; author its own calibration labels.
- **Checked by:** Gate A; producer/verifier separation enforced at commit; facet audit (fresh-context, non-author).

## Secondary/delegate agents
- **Definition:** cheaper-model workers (discovery, extraction packets, librarian work); the counter-argument seat is a fresh *primary-class* invocation, not a secondary.
- **Owns:** producing candidate material and packets.
- **Produces:** extraction packets with locators; discovery results through the gateway only.
- **Must never:** hold evidence-write capability; make final judgments; have their unverified characterizations treated as rejection records.
- **Checked by:** Gate A; supervisor structural checks (packet schema, completeness fields, receipts).

## Verifier
- **Definition:** a separate invocation with its own capability, per claim.
- **Owns:** independent re-access of cited content; the claim-vs-source check at a recorded access tier.
- **Produces:** verification receipts binding claim revision, source version, spans, content hash, access tier, acquisition/extraction lineage, invocation identities.
- **Must never:** be the producer's invocation; certify above its access tier (abstract check ≠ full-text verification); rely on the producer's extraction; average disagreements (disagreement ⇒ typed adjudication hold).
- **Checked by:** Gate A; commit-time role-separation enforcement; sampled re-verification.

## Tier-0 checker (NLI, local)
- **Definition:** claim-vs-span entailment screen; runs after exact quote byte-matching, never instead of it.
- **Owns:** nothing. Screens and alarms.
- **Produces:** pass/alarm signals with versioned checker identity; quarantines quotes (not sources) pending re-capture/adjudication.
- **Must never:** promote a claim; gate load-bearing claims in place of verification; be trusted on numerics/negation without the independent checks; auto-tighten thresholds on regression (re-evaluate/narrow/suspend instead).
- **Checked by:** Gate A; sampled false-pass audits with denominators (numeric/negation/context traps).

## Gateway
- **Definition:** the only door to external research sources — licensed, metered, logged, provenance-carrying.
- **Owns:** lane dispatch, budgets/breakers, coverage facts, licensing/provenance fields, retrieval-event capture.
- **Produces:** records with provenance and coverage vocabulary (`searched_ok`/`searched_empty`/`provider_unavailable`/`auth_failed` — with their narrow meanings); call logs with invocation IDs.
- **Must never:** be bypassed by direct API calls from agents; report a failed secrets read as "no key configured" (a dated `secrets backend failing` capability fact instead — the 2026-09-21..24 vault outage is the fixture); translate unparseable payloads into zero results; let two different requests share a request identity.
- **Checked by:** Gate A; the repaired-defect regression fixtures (breaker persistence, budget ownership, SIGTERM, correlation IDs, request identity, payload validation, server-side policy).

## Exporter
*Operator ruling 2026-09-26: this entry replaces "Projector / publication" and adopts the 0c/0c-repair export amendment (proposed in §6 of the former EXPORT-SINKS.md, as refined by Astra's 0c reviews), minus everything specific to one deployment. External export is one standard API that any database connects to; no store is built in, and none gets its own path.*
- **Definition:** the outbox consumer that delivers each approved export manifest's bundle through the one connector contract to every connector the manifest names, identically for every connector (`docs/gen2/EXPORT-API.md`). An export is of the exact approved revision — its approved revision *is* its source revision — not merely of work that carries an approval id. Connectors are named by the operator and closed by type: the core ships the reference types `sql`, `jsonl_file` and `webhook`; a connector for any other database is an `extension`, reviewed code that lives outside the core and is never named in it.
- **Owns:** delivery ordered by the pair (generation, options revision), with equal-pair replay decided by the immutable manifest id and bundle content hash; per-connector delivery receipts, including the reconciliation of an `outcome_unknown` attempt by re-sending; the export bundle, assembled by code from committed state. Its authoritative records (delivery receipts, connector watermarks) are persisted through the router's controlled write interface; this ownership grants no direct store writes. The manifests themselves are the router's outbox commits.
- **Produces:** `export-delivery-receipt/2` per connector per attempt; the export delivery status the freshness envelope reports per connector.
- **Must never:** read research back from a connector or any external database, or serve any engine read (research retrieval, accepted evidence, status) from one — engine readers read the local record; overwrite newer material with an old retry; export unapproved work; change completion or surveillance because a delivery failed or its outcome is unknown (delivery status is still reported per connector: three independent facts — completion at revision R / export delivery / currency at T); count an unknown outcome as delivered, failed or zero; deliver source content unless the record says that exact exported content or provenance member may be redistributed, keeping its licence and attribution obligations; give one connector a different document or a different contract because of its type.
- **Checked by:** Gate A; the store's outbox, receipt and watermark constraints; export fixtures for re-delivery, equal-pair replay after a lost receipt (acknowledged without a rewrite; conflicting content refused as a conflict), stale ordering pairs, ignored tombstones, unknown outcomes, partial-count fidelity, licence omission, an undeclared connector type, and the binding of the publication approval to exported content; the webhook receiver acceptance cases (`EXPORT-API.md` §6.3); the standing review-process rule (review bundles pin hashes + corpus-access manifests).

## Operator
- **Definition:** the human authority.
- **Owns:** scope, framing and reframes, obligation and rating approval, phase transitions, completion, retirement, merges to main, anything contested; which export connectors are enabled and what each topic exports (operator ruling 2026-09-26).
- **Interface guarantees owed to the operator:** typed holds with owners and deadlines; status that answers why every waiting item waits; dated capability facts with transition alerts; dossiers that permanently carry their evidence; blind-sample protocol so advisory recommendations don't anchor the labels.
