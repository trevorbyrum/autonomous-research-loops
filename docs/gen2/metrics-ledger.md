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
- limit: 15
- reason: Fan-out 13 to 15 is exactly the pure accounting component and minimal row adapter, within existing Router grants; no other fan-out growth authorized.
- task: 2c-1

