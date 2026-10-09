"""E-6/E-4/G-1 guards with independent accepted-path controls."""
from .base import Mutation

TARGET = "gen2/accounting/stopping.py"
TEST = "test_stopping.StoppingTest."
MUTATIONS = []
CONTROLS = {}


def guard(name, killer, control, old, new):
    mid = "2C3-" + name
    MUTATIONS.append(Mutation(mid, "2c-3a", name, (TEST + killer,), target=TARGET, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "Hand-written control executes the changed guard and retains its accepted result under this mutant."}


guard("unknown-false", "test_truth_tables", "test_control_satisfied",
      'if "unknown" in states:\n        return "unknown"', 'if "unknown" in states:\n        return "not_satisfied"')
guard("empty-unknown", "test_truth_tables", "test_control_satisfied", 'if not states:\n        return "unknown"', 'if not states:\n        return "satisfied"')
guard("majority", "test_all_is_not_majority", "test_control_satisfied", 'if decisive in states:', 'if states.count(decisive) > len(states) / 2:')
guard("gate-vote", "test_gates_override_any_and_unknown", "test_control_gate_pass", 'state = combine("all", (rules_state,', 'state = combine("any", (rules_state,')
guard("missing-gate", "test_gates_override_any_and_unknown", "test_control_gate_pass", 'gate_states.get(g, "unknown")', 'gate_states.get(g, "satisfied")')
guard("missing-rule", "test_expressions_and_pins", "test_control_satisfied", 'states.get(expression.rule, "unknown")', 'states.get(expression.rule, "satisfied")')
guard("rule-pin", "test_expressions_and_pins", "test_control_satisfied", 'r.state if r.context == context else "unknown"', 'r.state')
guard("gate-pin", "test_expressions_and_pins", "test_control_gate_pass", 'g.state if g.context == context else "unknown"', 'g.state')
guard("stale-label", "test_stale_unknown_and_empty_labels", "test_control_descriptive", '[o.labels[0]]', '[o.assessment.novelty]')
guard("descriptive-pin", "test_evaluator_context", "test_control_descriptive", ' if inventory.current_contract_revision == context.contract_revision else None', '')
guard("nonwindow", "test_nonwindows_repetition_and_missing_pins", "test_control_coverage", 'state, reason = window.state, window.reason', 'state, reason = "eligible", window.reason')
guard("window-pin", "test_nonwindows_repetition_and_missing_pins", "test_control_coverage", 'if i in revisions else "unknown"', 'if i in revisions else "current"')
guard("window-standing", "test_stale_unknown_and_empty_labels", "test_control_coverage", 'if standing == "stale":', 'if False:')
guard("window-legacy", "test_nonwindows_repetition_and_missing_pins", "test_control_coverage", ' or inventory.history == "legacy_unknown"', '')
guard("window-threshold", "test_control_coverage", "test_control_short_coverage", 'lower >= minimum_windows', 'lower > minimum_windows')
guard("known-membership", "test_known_item_missing_and_unknown", "test_control_known_item", 'missing = declared.work_ids - found', 'missing = frozenset()')
guard("known-empty", "test_known_item_missing_and_unknown", "test_control_known_item", 'not declared.work_ids or ', '')
guard("known-unknown", "test_known_item_missing_and_unknown", "test_control_known_item", 'retrieved.value is None or ', '')
guard("known-pin", "test_evaluator_context", "test_control_known_item", ' or inventory.current_contract_revision != context.contract_revision:\n        state = "unknown"', ':\n        state = "unknown"')


def repair(name, killer, control, old, new, target=TARGET):
    mid = "2C3R-" + name
    prefix = "test_coverage.CoverageTest."
    MUTATIONS.append(Mutation(mid, "2c-3a-repair-1", name, (prefix + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [prefix + control], "why": "Literal coverage inventory exercises the changed standing/bound operand on a path this mutant still accepts."}


ACCOUNTING = "gen2/accounting/__init__.py"
repair("indeterminate-as-ineligible", "test_missing_capture", "test_control_complete",
       'eligible + indeterminate < minimum_windows', 'eligible < minimum_windows')
repair("indeterminate-as-eligible", "test_between_bounds", "test_control_lower_bound",
       'if lower >= minimum_windows:', 'if upper >= minimum_windows:')
repair("upper-bound-equality", "test_between_bounds", "test_control_upper_bound",
       'elif eligible + indeterminate < minimum_windows:', 'elif eligible + indeterminate <= minimum_windows:')
repair("blanket-unknown", "test_control_lower_bound", "test_between_bounds",
       'if lower >= minimum_windows:', 'if lower >= minimum_windows and not indeterminate:')
repair("scope", "test_rule_scope", "test_control_complete",
       'if scope is None or w.invocation_id in scope)', 'if True)')
repair("standing-operands", "test_missing_capture", "test_control_complete",
       'standings = window_standings(inventory)', 'standings = tuple(w for w in window_standings(inventory) if w.state == "eligible")')
repair("standing-reasons", "test_missing_capture", "test_control_complete",
       'standing, state, reason)', 'standing, state, "" if state == "indeterminate" else reason)')
repair("ineligible-count", "test_known_exclusions", "test_control_complete",
       'ineligible = sum(w.state == "ineligible" for w in windows)', 'ineligible = 0')
repair("g1-blanket-unknown", "test_g1_bounds", "test_control_complete",
       'if inventory.current_contract_revision != context.contract_revision or inventory.history == "legacy_unknown":',
       'if inventory.current_contract_revision != context.contract_revision or inventory.history == "legacy_unknown" or any(w.standing != "current" for w in windows):')
repair("g1-unknown", "test_g1_unknown_upper_bound", "test_control_complete",
       'elif standing == "unknown":', 'elif False:')
repair("known-exclusion-standing", "test_known_ineligible_without_pin", "test_control_complete",
       'if state != "ineligible":', 'if True:')
repair("nonresearch-standing", "test_discovery_is_not_window", "test_control_complete",
       'for p in inventory.passes if p.kind == "research_pass")', 'for p in inventory.passes)', ACCOUNTING)
repair("eligible-standing", "test_control_complete", "test_control_nonpaging",
       'if p.invocation_id in eligible else _excluded_window(p, inventory)', 'if False else _excluded_window(p, inventory)', ACCOUNTING)
repair("drop-delegates", "test_delegate_uncertainty", "test_control_nonpaging",
       'members = (root, *_descendants(root, inventory))', 'members = (root,)', ACCOUNTING)
repair("window-membership", "test_between_bounds", "test_control_nonpaging",
       'if o.invocation_id in member_ids)', 'if True)', ACCOUNTING)
repair("missing-delegate-standing", "test_delegate_uncertainty", "test_control_nonpaging",
       'missing = tuple(p.invocation_id for p in members[1:] if p.invocation_id not in observed)', 'missing = ()', ACCOUNTING)
repair("nonpaging-standing", "test_control_nonpaging", "test_unknown_end",
       'if o.request_type == "find")', 'if True)', ACCOUNTING)
repair("unknown-end-guard", "test_unknown_end", "test_control_nonpaging",
       'any(o.page_outcome == "end_unknown" for o in finds)', 'False', ACCOUNTING)
repair("continuation-guard", "test_unknown_end", "test_control_nonpaging",
       'max(chain, key=lambda o: o.page.number).page_outcome == "continuation"', 'False', ACCOUNTING)
repair("failed-standing", "test_failed_delegate_is_known", "test_control_nonpaging",
       'if any(p.state in ("failed", "cancelled") for p in members):', 'if False:', ACCOUNTING)
repair("capped-standing", "test_known_exclusions", "test_control_nonpaging",
       'elif any(o.page_outcome in ("failed", "limit_reached") for o in observations):', 'elif False:', ACCOUNTING)
repair("unfinished-standing", "test_unfinished_and_metadata", "test_control_nonpaging",
       'if any(p.state != "committed" for p in members):', 'if False:', ACCOUNTING)
repair("legacy-standing", "test_unfinished_and_metadata", "test_control_nonpaging",
       'if inventory.history == "legacy_unknown":\n        return "indeterminate", "legacy historical capture unknown"',
       'if False:\n        return "indeterminate", "legacy historical capture unknown"', ACCOUNTING)
repair("missing-standing", "test_missing_capture", "test_control_nonpaging",
       'if missing or not observations:', 'if False:', ACCOUNTING)
repair("unobserved-standing", "test_unobserved_request", "test_control_nonpaging",
       'if any(o.completeness == "unobserved" for o in observations):', 'if False:', ACCOUNTING)
repair("partial-standing", "test_partial_capture", "test_control_nonpaging",
       'if any(not _captured(o, inventory) for o in observations):', 'if False:', ACCOUNTING)
repair("metadata-standing", "test_unfinished_and_metadata", "test_control_nonpaging",
       'return "indeterminate", "search page metadata missing"', 'return "ineligible", "search page metadata missing"', ACCOUNTING)
repair("end-standing", "test_unknown_end", "test_control_nonpaging",
       'return "indeterminate", "pagination end unknown"', 'return "ineligible", "pagination end unknown"', ACCOUNTING)
repair("attempt-universe", "test_unfinished_and_metadata", "test_control_complete",
       'for p in inventory.passes if p.kind == "research_pass")', 'for p in inventory.passes if p.kind == "research_pass" and p.state == "committed")', ACCOUNTING)


def dependency(name, killer, control, old, new, target=TARGET):
    mid = "2C3D-" + name
    prefix = "test_coverage_dependencies.DependencyTest."
    MUTATIONS.append(Mutation(mid, "2c-3a-repair-2", name, (prefix + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [prefix + control], "why":
                     "Literal disjoint history or provably invalid chain executes the changed guard and retains its expected verdict."}


dependency("drop-discount", "test_overlap_probe", "test_control_disjoint",
           'lower = _coverage_lower_bound(inventory, standings, global_operands, scope)', 'lower = eligible')
dependency("known-as-unknown", "test_known_search_discount", "test_control_invalid_chain",
           'earlier[w.invocation_id] = searches', 'earlier[w.invocation_id] = None')
dependency("unknown-as-known", "test_overlap_probe", "test_control_disjoint",
           'earlier[w.invocation_id] = searches', 'earlier[w.invocation_id] = searches or frozenset()')
dependency("recoverable-invalid", "test_recoverable_prefix_and_interior", "test_control_invalid_chain",
           'return "indeterminate", "pagination pages missing"', 'return "ineligible", "pagination pages missing"', ACCOUNTING)
dependency("scope-before-dependency", "test_scoped_overlap_probe", "test_control_disjoint",
           '_credit_risks(inventory, standings, operands, scope)',
           '_credit_risks(inventory, tuple(w for w in standings if scope is None or w.invocation_id in scope), operands, scope)')
dependency("drop-replacement", "test_overlap_probe", "test_control_disjoint",
           'return safe + replacements', 'return safe')
dependency("ignore-combined-thieves", "test_combined_thieves_and_existing_credit", "test_control_disjoint",
           'not credit <= possible', 'not any(keys is None or credit <= keys for keys in earlier.values())')
dependency("stale-thief-counts", "test_stale_thief", "test_control_disjoint",
           'and operands[i].standing == "current"', '')
