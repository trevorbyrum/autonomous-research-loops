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
- identity: MI-000249
- reason: the component cycle research_gateway.adapters / core / registry is broken (task 2q-b1): core no longer imports adapters (the exception classes moved to core/payload.py, the router's client is its own MeteredClient protocol) or registry (DOMAINS moved to core/request_identity.py), so every dependency between the three components now points at core
- task: 2q-b1

### ML-0002
- action: retire
- identity: MI-000406
- reason: core/request_identity.py no longer imports registry/load.py: DOMAINS, the one domain vocabulary, is defined in core/request_identity.py itself (task 2q-b1); the dependency runs registry -> core
- task: 2q-b1

### ML-0003
- action: retire
- identity: MI-000407
- reason: core/router.py no longer imports adapters/base.py: the three adapter exception classes it classified moved to core/payload.py (next to PayloadError, re-exported by adapters/base.py as before) and its `Client` annotation is its own MeteredClient protocol (task 2q-b1); the dependency runs adapters -> core
- task: 2q-b1

### ML-0004
- action: retire
- identity: MI-000418
- reason: core/router.py no longer imports registry/load.py: DOMAINS is read from core/request_identity.py, which the router already imports (task 2q-b1)
- task: 2q-b1

### ML-0005
- action: retire
- identity: MI-000899
- reason: gone with the edge it ran through (task 2q-b1): clients/mcp_stdio.py reached registry/load.py only through core/router.py's import of it
- task: 2q-b1

### ML-0006
- action: retire
- identity: MI-000921
- reason: gone with the edge it ran through (task 2q-b1): core/request_identity.py -> registry/load.py is the edge that is gone
- task: 2q-b1

### ML-0007
- action: retire
- identity: MI-000922
- reason: gone with the edge it ran through (task 2q-b1): core/router.py -> adapters/base.py is the edge that is gone
- task: 2q-b1

### ML-0008
- action: retire
- identity: MI-000924
- reason: gone with the edge it ran through (task 2q-b1): core/router.py reached core/broker.py only through adapters/base.py
- task: 2q-b1

### ML-0009
- action: retire
- identity: MI-000935
- reason: gone with the edge it ran through (task 2q-b1): core/router.py reached core/uri.py only through adapters/base.py
- task: 2q-b1

### ML-0010
- action: retire
- identity: MI-000937
- reason: gone with the edge it ran through (task 2q-b1): core/router.py -> registry/load.py is the edge that is gone
- task: 2q-b1

### ML-0011
- action: admit
- target: gateway|edge|gateway/research_gateway/registry/load.py->gateway/research_gateway/core/request_identity.py
- reason: the one new dependency of the fix, in the direction the components' roles give: the registry's seed validator (registry/load.py) checks a seed row's domains against the vocabulary that core/request_identity.py now owns, as registry/migrate.py already depends on core. core/request_identity.py has no first-party imports, so this edge adds nothing to any reach set but the two pairs admitted below (task 2q-b1)
- task: 2q-b1

### ML-0012
- action: admit
- target: gateway|reach|gateway/research_gateway/registry/docs.py->gateway/research_gateway/core/request_identity.py
- reason: registry/docs.py imports registry/load.py, which now imports core/request_identity.py (task 2q-b1)
- task: 2q-b1

### ML-0013
- action: admit
- target: gateway|reach|gateway/research_gateway/registry/load.py->gateway/research_gateway/core/request_identity.py
- reason: the reach of the admitted edge registry/load.py -> core/request_identity.py (task 2q-b1)
- task: 2q-b1

### ML-0014
- action: budget
- metric: fan_in
- location: gateway:gateway/research_gateway/core/request_identity.py
- limit: 4
- reason: core/request_identity.py gained one dependent, registry/load.py, the admitted edge (task 2q-b1); its own dependencies are unchanged (none first-party)
- task: 2q-b1

### ML-0015
- action: budget
- metric: fan_out
- location: gateway:gateway/research_gateway/registry/load.py
- limit: 1
- reason: registry/load.py depends on core/request_identity.py for the domain vocabulary, the admitted edge (task 2q-b1); it had no first-party import before
- task: 2q-b1

### ML-0016
- action: budget
- metric: reach_gained
- location: gateway
- limit: 2
- reason: the two reach pairs admitted above, both through the one admitted edge; the same task retires six pairs and one cycle, so reachability falls overall: gateway component propagation 49 -> 43 of 100 and file propagation 551 -> 547 of 4624 (task 2q-b1)
- task: 2q-b1

