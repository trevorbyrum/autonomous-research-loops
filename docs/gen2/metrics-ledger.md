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
- identity: MI-000231
- reason: registries.py is a collaborator the Router composes, no longer a mixin (task 2q-b3): amendments.py's one call of `_templates` is now a call of the Router's own delegating member (counted under amendments.py->service.py, below)
- task: 2q-b3

### ML-0002
- action: retire
- identity: MI-000235
- reason: registries.py is a collaborator, no longer a mixin (task 2q-b3): lifecycle.py's one call of `_router_policy` is now a call of the Router's own delegating member (counted under lifecycle.py->service.py, below)
- task: 2q-b3

### ML-0003
- action: retire
- identity: MI-000237
- reason: registries.py is a collaborator, no longer a mixin (task 2q-b3): its 17 calls of the core (`_one`, `_audit`, `_guarded`, `_now`) are `self._core.<member>` calls through RegistriesCore, which the metric does not count; the dependencies are declared in that protocol, not removed
- task: 2q-b3

### ML-0004
- action: retire
- identity: MI-000239
- reason: registries.py is a collaborator, no longer a mixin (task 2q-b3): scheduling.py's six calls of `_active_bundle` and `_router_policy` are now calls of the Router's own delegating members (counted under scheduling.py->service.py, below)
- task: 2q-b3

### ML-0005
- action: retire
- identity: MI-000243
- reason: registries.py is a collaborator, no longer a mixin (task 2q-b3): service.py's three calls of `_active_bundle`, `_bundle` and `is_qualified` are now calls of members service.py itself defines (delegating to the composed Registries)
- task: 2q-b3

### ML-0006
- action: budget
- metric: self_calls
- location: engine:gen2/router/amendments.py->gen2/router/service.py
- limit: 20
- reason: 1 site of amendments.py's calls of registries members moved here when registries.py stopped being a mixin (task 2q-b3): the Router keeps the members the rest of the Router reads (`_active_bundle`, `_router_policy`, `_templates`) as its own, delegating to the composed Registries. A flow moved from a mixin pair to the core pair, not new coupling: the engine's cross-file self-call sites fall 109 -> 89 and its file pairs 13 -> 8 in the same change
- task: 2q-b3

### ML-0007
- action: budget
- metric: self_calls
- location: engine:gen2/router/lifecycle.py->gen2/router/service.py
- limit: 24
- reason: 1 site of lifecycle.py's calls of registries members moved here when registries.py stopped being a mixin (task 2q-b3): the Router keeps the members the rest of the Router reads (`_active_bundle`, `_router_policy`, `_templates`) as its own, delegating to the composed Registries. A flow moved from a mixin pair to the core pair, not new coupling: the engine's cross-file self-call sites fall 109 -> 89 and its file pairs 13 -> 8 in the same change
- task: 2q-b3

### ML-0008
- action: budget
- metric: self_calls
- location: engine:gen2/router/scheduling.py->gen2/router/service.py
- limit: 26
- reason: 6 sites of scheduling.py's calls of registries members moved here when registries.py stopped being a mixin (task 2q-b3): the Router keeps the members the rest of the Router reads (`_active_bundle`, `_router_policy`, `_templates`) as its own, delegating to the composed Registries. A flow moved from a mixin pair to the core pair, not new coupling: the engine's cross-file self-call sites fall 109 -> 89 and its file pairs 13 -> 8 in the same change
- task: 2q-b3

