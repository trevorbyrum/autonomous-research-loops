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
- target: engine|edge|gen2/router/evidence_writer.py->gen2/core/canonical.py
- reason: evidence_writer.py is a new collaborator file (task 2q-b10) holding `_write_evidence` and its five helpers, moved from service.py: `_write_source_proposals` calls `canonical.logical_hash`, so the file imports `canonical`; service.py keeps its own uses of `canonical`, so this edge is added and none leaves
- task: 2q-b10

### ML-0002
- action: admit
- target: engine|edge|gen2/router/evidence_writer.py->gen2/router/boundary.py
- reason: the six moved methods raise `Refusal` (and the Router's `_guarded` still turns it into a refusal): evidence_writer.py imports it from `boundary`, as the other collaborators do; service.py keeps its own import, so the edge is added and none leaves
- task: 2q-b10

### ML-0003
- action: admit
- target: engine|edge|gen2/router/service.py->gen2/router/evidence_writer.py
- reason: service.py composes the new collaborator (`EvidenceWriter(self)` in `Router.__init__`) and delegates `_write_evidence` to it, as it does for the six earlier collaborators
- task: 2q-b10

### ML-0004
- action: admit
- target: engine|file|gen2/router/evidence_writer.py
- reason: the new file of task 2q-b10: `EvidenceWriter`, `EvidenceCore` and `Rows` (189 lines); service.py gives up 149 lines of it (1,498 -> 1,349), which is the headroom the next slices of this file need under the 1,500-line rule
- task: 2q-b10

### ML-0005
- action: admit
- target: engine|reach|gen2/app/engine.py->gen2/router/evidence_writer.py
- reason: transitive: engine.py imports `router.service`, which now imports evidence_writer.py (the same way it reaches amendments.py and scheduling.py)
- task: 2q-b10

### ML-0006
- action: admit
- target: engine|reach|gen2/app/station.py->gen2/router/evidence_writer.py
- reason: transitive: station.py imports `router.service`, which now imports evidence_writer.py (the same way it reaches amendments.py and scheduling.py)
- task: 2q-b10

### ML-0007
- action: admit
- target: engine|reach|gen2/router/evidence_writer.py->gen2/core/canonical.py
- reason: the direct edge ML-0001, as a reach pair
- task: 2q-b10

### ML-0008
- action: admit
- target: engine|reach|gen2/router/evidence_writer.py->gen2/core/instants.py
- reason: transitive: evidence_writer.py -> boundary.py -> instants.py; no new path to `instants` for any other file
- task: 2q-b10

### ML-0009
- action: admit
- target: engine|reach|gen2/router/evidence_writer.py->gen2/core/pagination.py
- reason: transitive: evidence_writer.py -> boundary.py -> pagination.py; no new path to `pagination` for any other file
- task: 2q-b10

### ML-0010
- action: admit
- target: engine|reach|gen2/router/evidence_writer.py->gen2/router/boundary.py
- reason: the direct edge ML-0002, as a reach pair
- task: 2q-b10

### ML-0011
- action: admit
- target: engine|reach|gen2/router/service.py->gen2/router/evidence_writer.py
- reason: the direct edge ML-0003, as a reach pair
- task: 2q-b10

### ML-0012
- action: budget
- metric: fan_in
- location: engine:gen2/core/canonical.py
- limit: 14
- reason: a new dependent: evidence_writer.py imports `canonical` (ML-0001); fan-in 13 -> 14. No other file's dependency on it changed
- task: 2q-b10

### ML-0013
- action: budget
- metric: fan_in
- location: engine:gen2/router/boundary.py
- limit: 8
- reason: a new dependent: evidence_writer.py imports `boundary` (ML-0002); fan-in 7 -> 8. No other file's dependency on it changed
- task: 2q-b10

### ML-0014
- action: budget
- metric: fan_out
- location: engine:gen2/router/service.py
- limit: 13
- reason: service.py imports the new collaborator (ML-0003); fan-out 12 -> 13. It still imports everything it imported before (`canonical`, `boundary` and the rest are used by the code that stayed)
- task: 2q-b10

