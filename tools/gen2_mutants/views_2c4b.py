"""View guards paired with independent hand-written accepted snapshots."""
from .base import Mutation

TARGET = "gen2/accounting/views.py"
TEST = "test_research_views.ViewsTest."
MUTATIONS = []
CONTROLS = {}


def guard(name, killer, old, new, control="test_control_current"):
    mid = "2C4B-" + name
    MUTATIONS.append(Mutation(mid, "2c-4b", name, (TEST + killer,), target=TARGET, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "Literal accepted view executes the changed selection statement or its guard and retains its expected records under the mutant."}


guard("duplicate-pin", "test_pins_and_standing", 'if len(revisions) != len(pins):', 'if False:')
guard("missing-pin", "test_pins_and_standing", 'if w.invocation_id in revisions else "unknown"', 'if w.invocation_id in revisions else "current"')
guard("g1", "test_pins_and_standing", 'a.label_standing(inventory, revisions[w.invocation_id])', '"current"')
guard("all-attempts", "test_attempts_and_unknown", 'for w in a.window_standings(inventory))', 'for w in a.window_standings(inventory) if w.state == "eligible")')
guard("search-identities", "test_control_current", 'a.window_search_knowledge(roots[w.invocation_id], inventory)', 'None', "test_control_missing_capture")
guard("branch-kind", "test_branch_links_only", 'if r.registry_kind == "branch"}', 'if True}')
guard("link-inventory", "test_branch_links_only", '    branch_ids.update(link.registry_id for link in branch_links)\n', '')
guard("branch-link-identity", "test_branch_links_only", 'if link.registry_id == registry_id)', 'if True)')
guard("branch-window-identity", "test_branch_links_only", 'if w.capture.invocation_id in ids)', 'if True)')
guard("missing-links", "test_branch_links_only", 'if not recorded:', 'if False:')
guard("missing-window", "test_branch_links_only", 'elif ids - {w.capture.invocation_id for w in selected}:', 'elif False:')
guard("registry-standing", "test_dated_lifecycle_lineage_and_reopenings", 'RegistryOperand(r, a.label_standing(inventory, r.contract_revision))', 'RegistryOperand(r, "current")')
guard("effective-registry", "test_dated_lifecycle_lineage_and_reopenings", 'if not self.active or any(o.standing not in ("current", "compatible") for o in self.active):', 'if not self.active:')
guard("empty-registry", "test_branch_history_and_empty_unknown", 'if not self.active or any(', 'if any(', "test_control_registry_labels")
guard("semantic-accrual", "test_control_current", 'for work, version in subjects for o in a.semantic_accrual(inventory, work, version, as_of)', 'for work, version in subjects for o in ()', "test_control_empty")
guard("lifecycle-date", "test_dated_lifecycle_lineage_and_reopenings", 'if utc_instant_ns(r.created_at) <= instant)\n    active', 'if True)\n    active')
guard("lifecycle-standing", "test_dated_lifecycle_lineage_and_reopenings", 'a.LifecycleOperand(r, a.label_standing(inventory, r.contract_revision))\n        for r in sorted', 'a.LifecycleOperand(r, "current")\n        for r in sorted')
guard("lifecycle-active", "test_dated_lifecycle_lineage_and_reopenings", 'a.lifecycle_view(inventory.source_lifecycle, as_of)', 'inventory.source_lifecycle')
guard("active-lifecycle-standing", "test_dated_lifecycle_lineage_and_reopenings", 'a.LifecycleOperand(r, a.label_standing(inventory, r.contract_revision))\n                   for r in a.lifecycle_view', 'a.LifecycleOperand(r, "current")\n                   for r in a.lifecycle_view')
guard("registry-date", "test_contradiction_history_and_competing_records", 'if utc_instant_ns(r.created_at) <= instant)\n    identities', 'if True)\n    identities')
guard("registry-kind", "test_contradiction_history_and_competing_records", '(r.registry_kind, r.registry_id) == (kind, registry_id)', 'r.registry_id == registry_id')
guard("registry-id", "test_registry_identity", '(r.registry_kind, r.registry_id) == (kind, registry_id)', 'r.registry_kind == kind')
guard("explicit-replacement", "test_contradiction_history_and_competing_records", 'if r.disposition_id not in replaced)', 'if True)')
guard("competing-records", "test_contradiction_history_and_competing_records", 'for r in history if r.disposition_id not in replaced)', 'for r in history[:1] if r.disposition_id not in replaced)')
guard("impact-date", "test_dated_lifecycle_lineage_and_reopenings", 'if utc_instant_ns(r.recorded_at) <= instant)', 'if True)')
guard("reopening-recorded", "test_dated_lifecycle_lineage_and_reopenings", 'if r.assessment_id in reopened and ', 'if ')
guard("reopening-date", "test_dated_lifecycle_lineage_and_reopenings", 'and utc_instant_ns(r.created_at) <= instant)', 'and True)')
