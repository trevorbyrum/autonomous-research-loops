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
- limit: 16
- reason: Fan-out 13 to 16 is exactly the 2c-1 pure accounting component and row adapter plus the 2c-2a assessment collaborator, all within existing Router grants; no other fan-out growth authorized.
- task: 2c-2a

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
- limit: 9
- reason: Boundary fan-in grows by one for the new assessment collaborator using the single existing primary authority vocabulary.
- task: 2c-2a

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
