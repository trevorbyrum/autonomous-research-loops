"""Mutations of closed identity accounting, admission, alternatives and scope.
All have independently specified refusal killers and accepted paired controls.

Task 2q-a-repair-3 re-anchored these on the shared source facts (tools/gen2_source_index.py), the supported-source contract (tools/gen2_source_contract.py) and the
effective transition plan (tools/gen2_metrics_ledger.py): the guards the repair-2 resolver held (conditional and rebound classes, competing bindings, class-scope
and lexical base scope) are now refusals of the index and the contract.
"""
from .base import Mutation

L, M, C = "tools/gen2_metrics_ledger.py", "tools/gen2_metrics.py", "tools/check_gen2_locators.py"
IDX, CON = "tools/gen2_source_index.py", "tools/gen2_source_contract.py"
I = "test_metrics_identity.IdentityTest."
B = "test_metrics_identity.BindingTest."
Q = "test_locators.QualifiedScopeTest."
CU = "test_metrics_collaboration.RefusedBaseTest."

MUTATIONS = [
    Mutation("2QI-missing-means-improvement", "2q-repair-2", "missing identity is treated as improvement", (I + "test_missing_edge_and_reach_cannot_be_called_improvements",),
             target=L, old='        plan.failures.append(violation("identity", ref, "missing; map or retire in committed ledger", ident))', new='        pass'),
    Mutation("2QI-reasonless-admission", "2q-repair-2", "TODO reason admits a new budget", (I + "test_reasonless_admission_fails_even_when_committed",),
             target=L, old=r'            if not f.get(key) or placeholder.match(f[key]) or (key == "reason" and re.search(r"\bTODO\b", f[key], re.I)):',
             new='            if key != "reason" and (not f.get(key) or placeholder.match(f[key])):'),
    Mutation("2QI-map-without-comparison", "2q-repair-2", "a map resets both score ceilings", (I + "test_rename_and_move_with_crossed_scores_require_mapping_and_compare_both_scores",),
             target=L, old='                s[field_][dest] = value', new='                s[field_][dest] = {"cyclomatic": 10000, "cognitive": 10000} if kind == "function" and ref in moves else value'),
    Mutation("2QI-last-entry-binding", "2q-repair-2", "competing bindings of a base guess the first", (CU + "test_a_base_the_contract_cannot_follow_is_refused_naming_the_class_the_category_and_why",
                                                                                                   B + "test_header_and_expression_writes_cannot_leave_a_stale_module_binding"),
             target=IDX, old='        if len(distinct) > 1 or all(b.conditional for b in bindings):', new='        if False:'),
    Mutation("2QI-qualified-short-name", "2q-repair-2", "a qualified locator uses flattened short names", (Q + "test_a_module_function_moved_into_a_closure_no_longer_satisfies_its_qualified_locator",),
             target=C, old='        if qualified or "." in name:\n            return source.module_attribute(', new='        if False:\n            return source.module_attribute('),
    Mutation("2QI-uncommitted-ledger", "2q-repair-2", "uncommitted admissions are accepted", (I + "test_uncommitted_reasoned_ledger_fails",),
             target=M, old='        if text != committed:', new='        if False:'),
    Mutation("2QI-pair-disappearance", "2q-repair-2", "a missing collaboration pair is not an identity failure", (I + "test_a_missing_pair_is_accounted_for_by_the_ledger_once_the_source_is_inside_the_contract",),
             target=L, old='    if dest not in present:', new='    if dest not in present and "|self_calls|" not in ref:'),
    Mutation("2QI-conditional-class", "2q-repair-2", "a class declared inside a compound statement is not refused", (I + "test_duplicate_and_conditional_nested_classes_are_refused",),
             target=IDX, old='        if nested:\n            self.diagnose("SRC-CLASS-CONDITIONAL"', new='        if False:\n            self.diagnose("SRC-CLASS-CONDITIONAL"'),
    Mutation("2QI-class-scope-occurrences", "2q-repair-2", "a defined name that is bound again is not refused", (B + "test_class_scope_assignment_cannot_leave_a_stale_nested_class_binding",),
             target=IDX, old='            if defs and others:', new='            if False:'),
    Mutation("2QI-lexical-base-scope", "2q-repair-2", "a nested class base guesses the module namespace", (B + "test_a_nested_class_base_uses_its_enclosing_class_namespace", B + "test_a_function_local_class_base_accounts_for_local_writes_and_parameters"),
             target=CON, old='                ref = self.facts.expr(path, cls.parent, node)', new='                ref = self.facts.expr(path, index.module, node)'),
    Mutation("2QI-locator-owner-binding", "2q-repair-2", "a qualified method survives replacement of its owning class", (Q + "test_a_replaced_class_owner_cannot_leave_a_stale_qualified_method",),
             target=IDX, old='        if len(bindings) != 1 or bindings[0].conditional or bindings[0].role not in CERTAIN:', new='        if not bindings or bindings[0].conditional or bindings[0].role not in CERTAIN:'),
]
