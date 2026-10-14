# Architecture metrics ledger

Task 2q-a-repair-2 and 2q-a-repair-3; charter Architecture metrics and Root-cause fixes, not patches.

The baseline registry owns persistent identities. Each check accounts for every
identity as present, explicitly mapped, or explicitly retired. Missing identities
fail. New files, edges, reach pairs and collaboration/function budgets require
admission. Stable-target fan-in includes every dependent, including new files.
Normalised aggregates never authorise growth. Instability is judged by direction:
taking on dependencies differs from losing dependents (Stable Dependencies Principle).

Source outside the supported-source contract (docs/gen2/SOURCE-CONTRACT.md) is
refused before any measurement. Nothing in this ledger waives a refusal: an
unresolved or unsupported form is not classified here, it is changed.

`make gen2-metrics-admit` drafts what the current plan still lacks with reason: TODO;
drafts fail. Fill each reason and reviewing task, review the diff, and commit the
ledger before checking. The tool checks commitment, not the truth of the author's
review claim. Maps preserve the old identity and compare all old budgets at the new
location. A `move` entry states one explicit file move (or one directory prefix) and
expands deterministically to a map of every baseline identity that mentions the file;
nothing is inferred from similar bodies and nothing is admitted by a move. An identity
the move cannot map (it has no counterpart at the destination) needs its own `retire`
entry; an explicit `map` or `retire` always overrides the expansion for that identity.
Retirements require absence. Budget admissions name one metric/location and a bounded
limit. Exemptions remain temporary regressions and never loosen a recorded budget.
Identity loss and new population cannot be exempted.

Rebaseline consumes admitted, mapped, moved and retired transitions only after a passing
check, keeps persistent IDs, and clears those entries. Improved functions keep their
identity and both scores even below thresholds. An edge/reach/pair that disappears
requires retirement. Git retains consumed reasons in the committed ledger history. Initial
recording is the sole bootstrap; existing baselines can migrate only at their exact
production digest.

Entries are `### ML-...` sections with fields action (map, retire, admit, budget, move),
identity/target (as applicable), metric/location/limit (for budget), from/to (for move),
reason, and task. Targets use service|kind|location; file identities own fan-out and
fan-in; function IDs own both scores; edge, reach, self_calls, cycle, smell and aggregate
IDs own their respective budgets. Cross-service imports belong to repo.

### ML-0001
- action: admit
- target: engine|edge|gen2/router/accounting.py->gen2/accounting/__init__.py
- reason: The Router read adapter converts durable rows to accounting records through the already granted accounting dependency.
- task: 2c-1

### ML-0002
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/accounting/__init__.py
- reason: Thin Router wiring calls pure accounting and names its operand/result types; authorization and snapshots stay in the Router.
- task: 2c-1

### ML-0003
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/accounting.py
- reason: The Router delegates row conversion to its minimal read adapter, keeping arithmetic outside service.py.
- task: 2c-1

### ML-0004
- action: admit
- target: engine|file|gen2/accounting/__init__.py
- reason: Implement the declared accounting boundary with pure typed inventory, count, novelty and window functions; no internal imports or I/O.
- task: 2c-1

### ML-0005
- action: admit
- target: engine|file|gen2/router/accounting.py
- reason: A small Router read adapter uses existing Store.select paths; it owns no transaction or arithmetic.
- task: 2c-1

### ML-0006
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/accounting/__init__.py
- reason: Existing engine-to-Router wiring now reaches the accounting component; no new dependency between existing files.
- task: 2c-1

### ML-0007
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/accounting.py
- reason: Existing engine-to-Router wiring now reaches the row adapter; no new dependency between existing files.
- task: 2c-1

### ML-0008
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/accounting/__init__.py
- reason: Existing station-to-Router wiring now reaches the accounting component; no new dependency between existing files.
- task: 2c-1

### ML-0009
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/accounting.py
- reason: Existing station-to-Router wiring now reaches the row adapter; no new dependency between existing files.
- task: 2c-1

### ML-0010
- action: admit
- target: engine|reach|gen2/router/accounting.py->gen2/accounting/__init__.py
- reason: The row adapter reaches only the pure accounting types, an existing module grant.
- task: 2c-1

### ML-0011
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/accounting/__init__.py
- reason: The Router reaches the accounting component through thin read wiring, an existing module grant.
- task: 2c-1

### ML-0012
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/accounting.py
- reason: The Router reaches the row adapter it calls within its own read snapshot.
- task: 2c-1

### ML-0013
- action: budget
- metric: fan_out
- location: engine:gen2/router/service.py
- limit: 21
- reason: The original 13 to 16 increase covers the 2c-1 pure accounting component/row adapter and 2c-2a assessment collaborator. Task 2d-4 adds one Verification collaborator; service.py gains only construction, receipt effects and a thin private delegate, keeping new verdict routing outside the core. Task 2d-4b2 adds one acquisition admission collaborator (17 to 18) and only constructor/schema/public-delegate wiring. Task 2d-4b3e1 adds one ExtractionRecords collaborator (18 to 19), with only construction, authentication/write delegation and audit-result wiring. JSON2 adds one Observations collaborator (19 to 20), moving observation admission out of service.py and retaining its existing transaction writer. Task 2d-4b3e2 adds one ExtractorRegistry collaborator (20 to 21); service adds only construction/schema and operator/admission delegates.
- task: 2d-4b3e2 part 1

### ML-0014
- action: admit
- target: engine|edge|gen2/router/assessments.py->gen2/router/boundary.py
- reason: The assessment collaborator uses the existing primary-kind authority set and refusal vocabulary at the Router boundary.
- task: 2c-2a

### ML-0015
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/assessments.py
- reason: Thin Router wiring composes semantic admission and append-only recording into the existing fenced commit transaction.
- task: 2c-2a

### ML-0016
- action: admit
- target: engine|file|gen2/router/assessments.py
- reason: One small Router collaborator owns semantic record admission and recording without arithmetic, I/O or a separate transaction.
- task: 2c-2a

### ML-0017
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/assessments.py
- reason: Existing engine-to-Router composition reaches the assessment collaborator; no new engine authority or direct store access.
- task: 2c-2a

### ML-0018
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/assessments.py
- reason: Existing station-to-Router composition reaches the assessment collaborator; no provider or direct store access.
- task: 2c-2a

### ML-0019
- action: admit
- target: engine|reach|gen2/router/assessments.py->gen2/core/canonical.py
- reason: The collaborator reaches canonical helpers transitively through the existing Router boundary import; no new direct capability.
- task: 2c-2a

### ML-0020
- action: admit
- target: engine|reach|gen2/router/assessments.py->gen2/core/instants.py
- reason: The collaborator reaches instant helpers transitively through the existing Router boundary import; it reads no clock.
- task: 2c-2a

### ML-0021
- action: admit
- target: engine|reach|gen2/router/assessments.py->gen2/core/pagination.py
- reason: The collaborator reaches pagination vocabulary transitively through the existing Router boundary import; it performs no retrieval.
- task: 2c-2a

### ML-0022
- action: admit
- target: engine|reach|gen2/router/assessments.py->gen2/router/boundary.py
- reason: The collaborator reaches only the existing Router boundary for primary authority and refusals.
- task: 2c-2a

### ML-0023
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/assessments.py
- reason: The Router reaches the assessment collaborator it invokes in its existing commit transaction.
- task: 2c-2a

### ML-0024
- action: budget
- metric: fan_in
- location: engine:gen2/router/boundary.py
- limit: 13
- reason: The prior assessment collaborator raised boundary fan-in to 9. Acquisition admission adds one caller (9 to 10), reusing the same schema normalization and Refusal vocabulary under Router authority. Task 2d-4b3e1 adds one caller (10 to 11), reusing the existing staged-artifact authentication and typed refusal paths. JSON2 adds Observations (11 to 12), reusing normalization and observation checks before the existing writer transaction. Task 2d-4b3e2 adds ExtractorRegistry (12 to 13), reusing normalization and typed refusals for audited operator admission.
- task: 2d-4b3e2 part 1

### ML-0025
- action: budget
- metric: function_cyclomatic
- location: engine:gen2/router/service.py::Router._write_evidence
- limit: 2
- reason: The evidence-write wrapper conditionally reports newly appended assessment ids; it has one branch and keeps existing empty outcome responses unchanged.
- task: 2c-2a

### ML-0026
- action: budget
- metric: function_cognitive
- location: engine:gen2/router/service.py::Router._write_evidence
- limit: 1
- reason: One conditional in the thin evidence-write wrapper reports nonempty assessment writes; all admission and persistence remains in collaborators.
- task: 2c-2a

### ML-0027
- action: admit
- target: engine|edge|gen2/accounting/__init__.py->gen2/core/instants.py
- reason: Pure dated views compare exact UTC instants using the existing core validator, including fractional timestamps; no clock or I/O.
- task: 2c-2b1

### ML-0028
- action: admit
- target: engine|edge|gen2/router/assessments.py->gen2/core/instants.py
- reason: Admission compares the Router recording instant with the immutable predecessor using the existing exact time vocabulary.
- task: 2c-2b1

### ML-0030
- action: admit
- target: engine|reach|gen2/accounting/__init__.py->gen2/core/instants.py
- reason: Lifecycle arithmetic reaches the pure core instant comparison helper, with no store or clock capability.
- task: 2c-2b1

### ML-0031
- action: admit
- target: engine|reach|gen2/router/accounting.py->gen2/core/instants.py
- reason: The existing inventory adapter reaches pure instant comparison through accounting; snapshot ownership stays in the Router.
- task: 2c-2b1

### ML-0032
- action: budget
- metric: fan_in
- location: engine:gen2/core/instants.py
- limit: 9
- reason: The two 2c-2b1 callers (accounting and its admission collaborator) and the new 2c-4b views share exact instant comparison. The views add one direct caller to the admitted fan-in of 8; no clock capability or other caller growth is admitted.
- task: 2c-4b

### ML-0033
- action: admit
- target: engine|file|gen2/accounting/stopping.py
- reason: Pure typed stopping signals and explicit three-valued composition belong to evidence accounting; no store, clock, model or Router authority.
- task: 2c-3a

### ML-0034
- action: admit
- target: engine|edge|gen2/accounting/stopping.py->gen2/accounting/__init__.py
- reason: Reuse the accepted candidate units, E-4 windows and G-1-selected semantic operands within the existing accounting module.
- task: 2c-3a

### ML-0035
- action: admit
- target: engine|reach|gen2/accounting/stopping.py->gen2/accounting/__init__.py
- reason: Stopping arithmetic reaches existing pure inventory accounting, without a new module grant or Router wiring.
- task: 2c-3a

### ML-0036
- action: admit
- target: engine|reach|gen2/accounting/stopping.py->gen2/core/instants.py
- reason: Descriptive operands reuse dated semantic selection and its existing exact UTC comparison helper, without reading a clock.
- task: 2c-3a

### ML-0037
- action: admit
- target: engine|edge|gen2/router/amendments.py->gen2/accounting/stopping.py
- reason: Admission and approval share the pure binding support check; arithmetic stays in accounting under the existing Router grant.
- task: 2c-3b-part-1

### ML-0038
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/accounting/stopping.py
- reason: Existing engine composition reaches pure stopping bindings through the Router admission path.
- task: 2c-3b-part-1

### ML-0039
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/accounting/stopping.py
- reason: Existing station composition reaches pure stopping bindings through the Router admission path.
- task: 2c-3b-part-1

### ML-0040
- action: admit
- target: engine|reach|gen2/router/amendments.py->gen2/accounting/__init__.py
- reason: The support check reaches existing pure accounting operand types through stopping bindings, without store or clock authority.
- task: 2c-3b-part-1

### ML-0041
- action: admit
- target: engine|reach|gen2/router/amendments.py->gen2/accounting/stopping.py
- reason: The amendment collaborator reaches the pure stopping binder to refuse unsupported automatic rules.
- task: 2c-3b-part-1

### ML-0042
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/accounting/stopping.py
- reason: Thin approval wiring reaches the same support check and binder used at contract admission.
- task: 2c-3b-part-1

### ML-0043
- action: admit
- target: engine|reach|gen2/router/status.py->gen2/accounting/__init__.py
- reason: Existing status composition reaches accounting through the amendment module; no new status behavior or authority.
- task: 2c-3b-part-1

### ML-0044
- action: admit
- target: engine|reach|gen2/router/status.py->gen2/accounting/stopping.py
- reason: Existing status composition reaches stopping bindings through the amendment module; no new status behavior or authority.
- task: 2c-3b-part-1

### ML-0045
- action: budget
- metric: fan_out
- location: engine:gen2/router/amendments.py
- limit: 3
- reason: One additional dependency on the pure stopping binder closes G-11 without adding evaluator arithmetic to the Router.
- task: 2c-3b-part-1

### ML-0046
- action: admit
- target: engine|edge|gen2/accounting/views.py->gen2/accounting/__init__.py
- reason: Pure views compose the accepted typed accounting records and arithmetic, without I/O or new authority.
- task: 2c-4b

### ML-0047
- action: admit
- target: engine|edge|gen2/accounting/views.py->gen2/accounting/stopping.py
- reason: Views consume the existing typed WindowPin only; stopping predicates are not exposed as sufficiency.
- task: 2c-4b

### ML-0048
- action: admit
- target: engine|edge|gen2/accounting/views.py->gen2/core/instants.py
- reason: Depth views compare caller-supplied dates with the accepted exact UTC instant helper; no clock is read.
- task: 2c-4b

### ML-0049
- action: admit
- target: engine|file|gen2/accounting/views.py
- reason: A pure coverage/depth composition module implements flow S7 views over supplied snapshot operands.
- task: 2c-4b

### ML-0050
- action: admit
- target: engine|reach|gen2/accounting/views.py->gen2/accounting/__init__.py
- reason: Coverage and depth reach only existing pure inventory/arithmetic helpers and preserve unknown operands.
- task: 2c-4b

### ML-0051
- action: admit
- target: engine|reach|gen2/accounting/views.py->gen2/accounting/stopping.py
- reason: The supplied WindowPin type is the only stopping-module operand imported by the new views.
- task: 2c-4b

### ML-0052
- action: admit
- target: engine|reach|gen2/accounting/views.py->gen2/core/instants.py
- reason: Existing accounting helpers and the explicit date filter reach the pure instant parser without clock authority.
- task: 2c-4b

### ML-0053
- action: admit
- target: engine|edge|gen2/accounting/reconciliation.py->gen2/accounting/__init__.py
- reason: Explicit reconciliation operands reuse the accepted typed evidence and judgment histories without producing or selecting judgments.
- task: 2c-4a2

### ML-0054
- action: admit
- target: engine|file|gen2/accounting/reconciliation.py
- reason: A pure module holds fixture assessment/open operands and contract-pinned confidence consistency checks for the ruled reconciliation design.
- task: 2c-4a2

### ML-0055
- action: admit
- target: engine|reach|gen2/accounting/reconciliation.py->gen2/accounting/__init__.py
- reason: The operand envelope retains existing semantic, lineage, lifecycle, registry and G-1 records unchanged and adds no store or provider authority.
- task: 2c-4a2

### ML-0056
- action: admit
- target: engine|reach|gen2/accounting/reconciliation.py->gen2/core/instants.py
- reason: Reusing the accounting record module inherits its existing pure UTC parser dependency; the new confidence check reads no clock.
- task: 2c-4a2

### ML-0057
- action: admit
- target: engine|edge|gen2/router/accounting.py->gen2/accounting/views.py
- reason: The Router snapshot adapter constructs the existing pure BranchLink and WindowPin operands from admitted durable provenance without computing views.
- task: 2d-2

### ML-0058
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/accounting/views.py
- reason: The engine inherits the Router's typed coverage snapshot hand-off; it acquires no direct store or provider authority.
- task: 2d-2

### ML-0059
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/accounting/views.py
- reason: Station composition reaches the existing pure operand types through the Router adapter, without new scientific judgment or write authority.
- task: 2d-2

### ML-0060
- action: admit
- target: engine|reach|gen2/router/accounting.py->gen2/accounting/stopping.py
- reason: The views module exposes the accepted WindowPin type from stopping; this is a typed snapshot dependency and invokes no stopping evaluator under the lock.
- task: 2d-2

### ML-0061
- action: admit
- target: engine|reach|gen2/router/accounting.py->gen2/accounting/views.py
- reason: Durable branch/window associations are converted to the existing fixture operand types with derived revisions and conservative unknown handling.
- task: 2d-2

### ML-0062
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/accounting/views.py
- reason: Thin coverage snapshot wiring reaches pure types through the existing read adapter; view arithmetic runs only after the snapshot returns.
- task: 2d-2

### ML-0063
- action: admit
- target: engine|file|gen2/router/quote_matching.py
- reason: Task 2d-3a adds the planned pure V-6 matcher with retained byte/span and normalization operands; it has no internal dependencies or I/O and grants no admission authority.
- task: 2d-3a

### ML-0064
- action: admit
- target: engine|edge|gen2/router/evidence_writer.py->gen2/router/quote_matching.py
- reason: The existing evidence collaborator computes V-6 results with the accepted pure matcher during validation, outside the writer transaction.
- task: 2d-3b3

### ML-0065
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/quote_matching.py
- reason: Existing engine composition reaches the pure matcher through Router validation; no provider or additional writer is introduced.
- task: 2d-3b3

### ML-0066
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/quote_matching.py
- reason: Existing station commits reach the pure matcher through the governed Router path; the station supplies operands without match authority.
- task: 2d-3b3

### ML-0067
- action: admit
- target: engine|reach|gen2/router/evidence_writer.py->gen2/router/quote_matching.py
- reason: The registered collaborator uses the pure match result as its persistence operand, retaining all bytes and rule identities.
- task: 2d-3b3

### ML-0068
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/quote_matching.py
- reason: One thin validation call reaches the matcher through EvidenceWriter rather than adding matching responsibility to service.py.
- task: 2d-3b3

### ML-0069
- action: budget
- metric: fan_out
- location: engine:gen2/router/evidence_writer.py
- limit: 3
- reason: The collaborator adds the accepted pure matcher to its existing core and boundary dependencies; transaction ownership remains with Router.
- task: 2d-3b3

### ML-0070
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/verification.py
- reason: Thin Router composition delegates adverse-verdict hold production to a narrow collaborator inside the existing writer fence.
- task: 2d-4

### ML-0071
- action: admit
- target: engine|edge|gen2/router/verification.py->gen2/core/canonical.py
- reason: Existing canonical logical hashing derives bounded deterministic hold IDs from immutable receipt identities; no new hashing contract is introduced.
- task: 2d-4

### ML-0072
- action: admit
- target: engine|file|gen2/router/verification.py
- reason: V-5 and V-2 attention uses the existing hold mechanism without adding verdict routing responsibility to service.py or a second writer.
- task: 2d-4

### ML-0073
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/verification.py
- reason: Existing engine composition reaches owned verification holds through Router commits; no new application surface or provider authority is added.
- task: 2d-4

### ML-0074
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/verification.py
- reason: Station outcomes enter the existing Router fence, which now retains adverse verifier verdicts as owned holds.
- task: 2d-4

### ML-0075
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/verification.py
- reason: The core composes the verification collaborator and delegates hold writing and receipt identity reporting; it adds no verification semantics.
- task: 2d-4

### ML-0076
- action: admit
- target: engine|reach|gen2/router/verification.py->gen2/core/canonical.py
- reason: The collaborator reuses the engine's existing canonical hash to bind each generated hold to one exact verification receipt.
- task: 2d-4

### ML-0077
- action: budget
- metric: fan_in
- location: engine:gen2/core/canonical.py
- limit: 18
- reason: Task 2d-4 increased canonical fan-in from 14 to 15 for deterministic hold identity, and 2d-4b added the pure acquisition validator (15 to 16). Task 2d-4b2 adds the admission adapter (16 to 17), comparing trusted attempted-request octets with the existing canonical serializer; no second hashing or serialization mechanism. JSON2 adds Observations (17 to 18), using the same logical-member checks and exact-byte SHA-256 helper.
- task: 2d-4b3e1-json2

### ML-0078
- action: admit
- target: engine|edge|gen2/router/reaccess.py->gen2/core/canonical.py
- reason: Pure fixture acquisition validation reuses the existing byte digest, strict JSON parser and attempted-request hash authority.
- task: 2d-4b

### ML-0079
- action: admit
- target: engine|file|gen2/router/reaccess.py
- reason: The foundational V-3 hand-off validates retained fixture response lineage without I/O, state writes, semantic judgments or admission authority; Router integration remains the next split.
- task: 2d-4b

### ML-0080
- action: admit
- target: engine|reach|gen2/router/reaccess.py->gen2/core/canonical.py
- reason: Acquisition consistency needs only the shared canonical primitives, preserving a single hash and JSON implementation.
- task: 2d-4b

### ML-0081
- action: admit
- target: engine|edge|gen2/router/acquisitions.py->gen2/core/canonical.py
- reason: Acquisition admission shares canonical attempted-request serialization with recorded observations and the accepted validator, rather than trusting a recomputed caller hash or adding another serializer.
- task: 2d-4b2

### ML-0082
- action: admit
- target: engine|edge|gen2/router/acquisitions.py->gen2/core/gateway_capture.py
- reason: A frozen pure core hand-off and reader protocol let trusted station construction supply retained request/response octets without granting Router imports or writes to the capture adapter.
- task: 2d-4b2

### ML-0083
- action: admit
- target: engine|edge|gen2/router/acquisitions.py->gen2/router/boundary.py
- reason: Acquisition admission reuses Router request normalization, schema validation and typed refusal reporting under the existing boundary grant.
- task: 2d-4b2

### ML-0084
- action: admit
- target: engine|edge|gen2/router/acquisitions.py->gen2/router/reaccess.py
- reason: Authoritative fixture admission consumes the already accepted pure acquisition validator, so digest, identity, capture acknowledgement and retrieved-record checks have one implementation; app reach remains through Router.
- task: 2d-4b2

### ML-0085
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/acquisitions.py
- reason: The Router composes the acquisition admission collaborator, keeping trusted capture reads and validation outside its writer fence and new provenance logic outside service.py; existing app composition reaches it only through Router.
- task: 2d-4b2

### ML-0086
- action: admit
- target: engine|file|gen2/core/gateway_capture.py
- reason: A frozen pure core hand-off and reader protocol let trusted station construction supply retained request/response octets without granting Router imports or writes to the capture adapter.
- task: 2d-4b2

### ML-0087
- action: admit
- target: engine|file|gen2/router/acquisitions.py
- reason: The Router composes the acquisition admission collaborator, keeping trusted capture reads and validation outside its writer fence and new provenance logic outside service.py; existing app composition reaches it only through Router.
- task: 2d-4b2

### ML-0088
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/core/gateway_capture.py
- reason: A frozen pure core hand-off and reader protocol let trusted station construction supply retained request/response octets without granting Router imports or writes to the capture adapter.
- task: 2d-4b2

### ML-0089
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/acquisitions.py
- reason: The Router composes the acquisition admission collaborator, keeping trusted capture reads and validation outside its writer fence and new provenance logic outside service.py; existing app composition reaches it only through Router.
- task: 2d-4b2

### ML-0090
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/reaccess.py
- reason: Authoritative fixture admission consumes the already accepted pure acquisition validator, so digest, identity, capture acknowledgement and retrieved-record checks have one implementation; app reach remains through Router.
- task: 2d-4b2

### ML-0091
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/core/gateway_capture.py
- reason: A frozen pure core hand-off and reader protocol let trusted station construction supply retained request/response octets without granting Router imports or writes to the capture adapter.
- task: 2d-4b2

### ML-0092
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/acquisitions.py
- reason: The Router composes the acquisition admission collaborator, keeping trusted capture reads and validation outside its writer fence and new provenance logic outside service.py; existing app composition reaches it only through Router.
- task: 2d-4b2

### ML-0093
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/reaccess.py
- reason: Authoritative fixture admission consumes the already accepted pure acquisition validator, so digest, identity, capture acknowledgement and retrieved-record checks have one implementation; app reach remains through Router.
- task: 2d-4b2

### ML-0094
- action: admit
- target: engine|reach|gen2/router/acquisitions.py->gen2/core/canonical.py
- reason: Acquisition admission shares canonical attempted-request serialization with recorded observations and the accepted validator, rather than trusting a recomputed caller hash or adding another serializer.
- task: 2d-4b2

### ML-0095
- action: admit
- target: engine|reach|gen2/router/acquisitions.py->gen2/core/gateway_capture.py
- reason: A frozen pure core hand-off and reader protocol let trusted station construction supply retained request/response octets without granting Router imports or writes to the capture adapter.
- task: 2d-4b2

### ML-0096
- action: admit
- target: engine|reach|gen2/router/acquisitions.py->gen2/core/instants.py
- reason: The new acquisition adapter reaches existing instant and pagination helpers transitively through boundary/reaccess; it adds no direct clock, network or pagination authority.
- task: 2d-4b2

### ML-0097
- action: admit
- target: engine|reach|gen2/router/acquisitions.py->gen2/core/pagination.py
- reason: The new acquisition adapter reaches existing instant and pagination helpers transitively through boundary/reaccess; it adds no direct clock, network or pagination authority.
- task: 2d-4b2

### ML-0098
- action: admit
- target: engine|reach|gen2/router/acquisitions.py->gen2/router/boundary.py
- reason: Acquisition admission reuses Router request normalization, schema validation and typed refusal reporting under the existing boundary grant.
- task: 2d-4b2

### ML-0099
- action: admit
- target: engine|reach|gen2/router/acquisitions.py->gen2/router/reaccess.py
- reason: Authoritative fixture admission consumes the already accepted pure acquisition validator, so digest, identity, capture acknowledgement and retrieved-record checks have one implementation; app reach remains through Router.
- task: 2d-4b2

### ML-0100
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/core/gateway_capture.py
- reason: A frozen pure core hand-off and reader protocol let trusted station construction supply retained request/response octets without granting Router imports or writes to the capture adapter.
- task: 2d-4b2

### ML-0101
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/acquisitions.py
- reason: The Router composes the acquisition admission collaborator, keeping trusted capture reads and validation outside its writer fence and new provenance logic outside service.py; existing app composition reaches it only through Router.
- task: 2d-4b2

### ML-0102
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/reaccess.py
- reason: Authoritative fixture admission consumes the already accepted pure acquisition validator, so digest, identity, capture acknowledgement and retrieved-record checks have one implementation; app reach remains through Router.
- task: 2d-4b2

### ML-0103
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/extractions.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0104
- action: admit
- target: engine|file|gen2/router/extractions.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0105
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/extractions.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0106
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/extractions.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0107
- action: admit
- target: engine|reach|gen2/router/extractions.py->gen2/core/canonical.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0108
- action: admit
- target: engine|reach|gen2/router/extractions.py->gen2/core/instants.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0109
- action: admit
- target: engine|reach|gen2/router/extractions.py->gen2/core/pagination.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0110
- action: admit
- target: engine|reach|gen2/router/extractions.py->gen2/router/boundary.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0111
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/extractions.py
- reason: The narrow extraction-record collaborator reuses the existing staged-artifact authentication and fenced commit; app reach stays through Router, and core helper reach is transitive through boundary.py. No new execution, provider, clock or transaction authority.
- task: 2d-4b3e1

### ML-0112
- action: admit
- target: engine|edge|gen2/router/extractions.py->gen2/router/boundary.py
- reason: ExtractionRecords directly imports the existing staged-artifact authenticator and Refusal vocabulary for C-9 admission outside the writer lock.
- task: 2d-4b3e1

### ML-0113
- action: admit
- target: engine|edge|gen2/router/observations.py->gen2/core/canonical.py
- reason: The observation admission collaborator uses the existing canonical member-domain parser and exact-byte SHA-256 helper; no new hashing contract.
- task: 2d-4b3e1-json2

### ML-0115
- action: admit
- target: engine|edge|gen2/router/observations.py->gen2/router/boundary.py
- reason: The collaborator reuses Router schema/refusal/observation checks before the existing fenced transaction.
- task: 2d-4b3e1-json2

### ML-0116
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/observations.py
- reason: Service imports only construction and public observation delegation; the existing transactional observation writer stays in the core.
- task: 2d-4b3e1-json2

### ML-0117
- action: admit
- target: engine|file|gen2/router/observations.py
- reason: Observations moves admission out of service.py and owns attempted-byte retention validation, with no store, network or transaction authority of its own.
- task: 2d-4b3e1-json2

### ML-0118
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/observations.py
- reason: Engine reaches observation admission through its existing Router; no new app import or write path.
- task: 2d-4b3e1-json2

### ML-0119
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/observations.py
- reason: Station reaches observation admission through its existing Router; no new app import or write path.
- task: 2d-4b3e1-json2

### ML-0120
- action: admit
- target: engine|reach|gen2/router/observations.py->gen2/core/canonical.py
- reason: The collaborator reaches the existing canonical member-name validation and byte-hash helpers.
- task: 2d-4b3e1-json2

### ML-0121
- action: admit
- target: engine|reach|gen2/router/observations.py->gen2/core/instants.py
- reason: The collaborator reaches timestamp validation transitively through existing boundary checks; it reads no clock itself.
- task: 2d-4b3e1-json2

### ML-0122
- action: admit
- target: engine|reach|gen2/router/observations.py->gen2/core/pagination.py
- reason: The collaborator reaches the established pagination vocabulary for a failed-attempt label only.
- task: 2d-4b3e1-json2

### ML-0123
- action: admit
- target: engine|reach|gen2/router/observations.py->gen2/router/boundary.py
- reason: The collaborator reaches existing schema and typed-refusal validation under Router authority.
- task: 2d-4b3e1-json2

### ML-0124
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/observations.py
- reason: Router reaches its narrow observation admission collaborator through thin construction/delegation.
- task: 2d-4b3e1-json2

### ML-0125
- action: budget
- metric: fan_in
- location: engine:gen2/core/pagination.py
- limit: 6
- reason: Observations added one caller of the closed request-type vocabulary (4 to 5); repair-1 adds Accounting as the sixth caller for the pure same-row retained representation check. Neither adds I/O or pagination authority.
- task: 2d-4b3e1-json2-repair-1

### ML-0126
- action: admit
- target: engine|edge|gen2/router/accounting.py->gen2/core/pagination.py
- reason: Accounting reads the shared pure retained-row binding predicate before deciding whether a request is opaque; it gains no admission or write authority.
- task: 2d-4b3e1-json2-repair-1

### ML-0127
- action: admit
- target: engine|reach|gen2/router/accounting.py->gen2/core/canonical.py
- reason: Accounting reaches canonical transitively through pagination's existing cursor and request vocabulary; the retained-row reader binds labels without hashing or I/O.
- task: 2d-4b3e1-json2-repair-1

### ML-0128
- action: admit
- target: engine|reach|gen2/router/accounting.py->gen2/core/pagination.py
- reason: Accounting reaches the same-row retained representation check through its one new direct core import; no extra store, network or transaction authority.
- task: 2d-4b3e1-json2-repair-1

### ML-0129
- action: admit
- target: engine|edge|gen2/router/extractor_registry.py->gen2/router/boundary.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0130
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/extractor_registry.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0131
- action: admit
- target: engine|file|gen2/router/extractor_registry.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0132
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/extractor_registry.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0133
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/extractor_registry.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0134
- action: admit
- target: engine|reach|gen2/router/extractor_registry.py->gen2/core/canonical.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0135
- action: admit
- target: engine|reach|gen2/router/extractor_registry.py->gen2/core/instants.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0136
- action: admit
- target: engine|reach|gen2/router/extractor_registry.py->gen2/core/pagination.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0137
- action: admit
- target: engine|reach|gen2/router/extractor_registry.py->gen2/router/boundary.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1

### ML-0138
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/extractor_registry.py
- reason: The operator registry collaborator validates and audits immutable tool snapshots through the existing Router boundary and writer; service adds only construction and delegation. New reach is through that collaborator and its established boundary helpers, with no provider or execution authority.
- task: 2d-4b3e2 part 1
