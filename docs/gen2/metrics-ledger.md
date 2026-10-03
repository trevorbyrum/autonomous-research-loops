# Architecture metrics ledger

Task 2q-a-repair-2; charter Architecture metrics and Root-cause fixes, not patches.

The baseline registry owns persistent identities. Each check accounts for every
identity as present, explicitly mapped, or explicitly retired. Missing identities
fail. New files, edges, reach pairs and collaboration/function budgets require
admission. Stable-target fan-in includes every dependent, including new files.
Normalised aggregates never authorise growth. Instability is judged by direction:
taking on dependencies differs from losing dependents (Stable Dependencies Principle).

`make gen2-metrics-admit` drafts current changes with reason: TODO; drafts fail.
Fill each reason and reviewing task, review the diff, and commit the ledger before
checking. The tool checks commitment, not the truth of the author's review claim.
Maps preserve the old identity and compare all old budgets at the new location.
File moves require maps for affected function, edge, reach and collaboration
identities too; there is no guessed correspondence. Retirements require absence.
Budget admissions name one metric/location and a bounded limit. Exemptions remain
temporary regressions and never loosen a recorded budget. Identity loss and new
population cannot be exempted. Classifications of unresolved bindings remain in
this ledger while needed; they do not certify any collaboration inventory.

Rebaseline consumes admitted, mapped and retired transitions only after a passing
check, keeps persistent IDs, and clears those entries. Classifications remain.
Improved functions keep their identity and both scores even below thresholds.
An edge/reach/pair that disappears requires retirement. Git retains consumed
reasons in the committed ledger history. Initial recording is the sole bootstrap;
existing baselines can migrate only at their exact production digest.

Entries are `### ML-...` sections with fields action, identity/target (as applicable),
metric/location/limit (for budget or classify), reason, and task. Targets use
service|kind|location; file identities own fan-out and fan-in; function IDs own
both scores; edge, reach, self_calls, cycle, smell and aggregate IDs own their
respective budgets. Cross-service imports belong to repo.

