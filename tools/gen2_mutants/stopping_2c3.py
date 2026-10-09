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
guard("nonwindow", "test_nonwindows_repetition_and_missing_pins", "test_control_coverage", 'for i in saturation_passes(inventory))', 'for i in (p.invocation_id for p in inventory.passes if p.state == "committed"))')
guard("window-pin", "test_nonwindows_repetition_and_missing_pins", "test_control_coverage", 'if i in revisions else "unknown"', 'if i in revisions else "current"')
guard("window-standing", "test_stale_unknown_and_empty_labels", "test_control_coverage", ' or any(w.standing not in ("current", "compatible") for w in windows)', '')
guard("window-legacy", "test_nonwindows_repetition_and_missing_pins", "test_control_coverage", 'inventory.history == "legacy_unknown" or ', '')
guard("window-threshold", "test_control_coverage", "test_control_short_coverage", 'len(windows) >= minimum_windows', 'len(windows) > minimum_windows')
guard("known-membership", "test_known_item_missing_and_unknown", "test_control_known_item", 'missing = declared.work_ids - found', 'missing = frozenset()')
guard("known-empty", "test_known_item_missing_and_unknown", "test_control_known_item", 'not declared.work_ids or ', '')
guard("known-unknown", "test_known_item_missing_and_unknown", "test_control_known_item", 'retrieved.value is None or ', '')
guard("known-pin", "test_evaluator_context", "test_control_known_item", ' or inventory.current_contract_revision != context.contract_revision:\n        state = "unknown"', ':\n        state = "unknown"')
