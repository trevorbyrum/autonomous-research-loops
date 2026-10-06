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
- action: retire
- identity: MI-000233
- reason: capabilities.py no longer inherits registries.py: it is an explicit collaborator the Router composes (task 2q-b2), and reaches `_active_bundle` and `_router_policy` through `self._core`, the CapabilityCore interface it declares; the two flows are gone as self-calls (a collaborator's call through a declared interface is not an implicit mixin call)
- task: 2q-b2

### ML-0002
- action: retire
- identity: MI-000234
- reason: capabilities.py no longer inherits service.py's Router: the nine calls (`_one`, `_guarded`, `_audit`, `_capability`, `_require_current_lease`) go through `self._core`, the CapabilityCore interface it declares and a test keeps true (task 2q-b2); the collaborator holds no store handle of its own and opens no transaction (`_guarded` is the core's)
- task: 2q-b2

### ML-0003
- action: retire
- identity: MI-000245
- reason: status.py no longer inherits amendments.py: it is an explicit collaborator the Router composes (task 2q-b2) and reaches `_pin_status` through `self._core`, the StatusCore interface it declares
- task: 2q-b2

### ML-0004
- action: retire
- identity: MI-000246
- reason: status.py no longer inherits registries.py: `_active_bundle` is reached through `self._core`, the StatusCore interface it declares (task 2q-b2)
- task: 2q-b2

### ML-0005
- action: retire
- identity: MI-000247
- reason: status.py no longer inherits scheduling.py: `_lane_last` is reached through `self._core`, the StatusCore interface it declares (task 2q-b2)
- task: 2q-b2

### ML-0006
- action: retire
- identity: MI-000248
- reason: status.py no longer inherits service.py's Router: the nine calls (`_now`, `_one`, `_lease_of`, `_launch_refusal`, `_admission_json`) and the read transaction (`_snapshot`, the core's) go through `self._core`, the StatusCore interface it declares and a test keeps true (task 2q-b2); the read stays one transaction that writes nothing
- task: 2q-b2

