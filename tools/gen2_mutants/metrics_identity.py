"""Mutations of closed identity accounting, admission, alternatives and scope.
All have independently specified refusal killers and accepted paired controls.
"""
from .base import Mutation

L, M, C = "tools/gen2_metrics_ledger.py", "tools/gen2_metrics.py", "tools/check_gen2_locators.py"
I = "test_metrics_identity.IdentityTest."
B = "test_metrics_identity.BindingTest."
Q = "test_locators.QualifiedScopeTest."

MUTATIONS = [
    Mutation("2QI-missing-means-improvement", "2q-repair-2", "missing identity is treated as improvement", (I + "test_missing_edge_and_reach_cannot_be_called_improvements",),
             target=L, old='            failures.append(violation("identity", ref, "missing; map or retire in committed ledger", ident))', new='            pass'),
    Mutation("2QI-reasonless-admission", "2q-repair-2", "TODO reason admits a new budget", (I + "test_reasonless_admission_fails_even_when_committed",),
             target=L, old=r'            if not f.get(key) or placeholder.match(f[key]) or (key == "reason" and re.search(r"\bTODO\b", f[key], re.I)):',
             new='            if key != "reason" and (not f.get(key) or placeholder.match(f[key])):'),
    Mutation("2QI-map-without-comparison", "2q-repair-2", "a map resets both score ceilings", (I + "test_rename_and_move_with_crossed_scores_require_mapping_and_compare_both_scores",),
             target=L, old='                s[field][dest] = value', new='                s[field][dest] = {"cyclomatic": 10000, "cognitive": 10000} if kind == "function" and ref in moves else value'),
    Mutation("2QI-last-entry-binding", "2q-repair-2", "competing reexports guess the last binding", (B + "test_competing_star_reexports_fail_for_both_interpreter_orders",),
             target=M, old='                return ("unresolved", f"{dotted}.{attr} has competing binding occurrences/re-exports")', new='                return candidates[-1]'),
    Mutation("2QI-qualified-short-name", "2q-repair-2", "a qualified locator uses flattened short names", (Q + "test_a_module_function_moved_into_a_closure_no_longer_satisfies_its_qualified_locator",),
             target=C, old='scoped_names(text) if qualified or "." in name else python_names(text)', new='python_names(text)'),
    Mutation("2QI-uncommitted-ledger", "2q-repair-2", "uncommitted admissions are accepted", (I + "test_uncommitted_reasoned_ledger_fails",),
             target=M, old='        if text != committed:', new='        if False:'),
    Mutation("2QI-pair-disappearance", "2q-repair-2", "classification erases missing collaboration obligations", (I + "test_classifications_do_not_replace_missing_pair_accounting",),
             target=L, old='        if dest not in present:', new='        if dest not in present and "|self_calls|" not in ref:'),
    Mutation("2QI-conditional-class", "2q-repair-2", "conditional class alternatives are not diagnosed", (I + "test_duplicate_and_conditional_nested_classes_are_unresolved",),
             target=M, old='found[name].append(("conditional", ref) if conditional else ref)', new='found[name].append(ref)',
             also=(('alternatives(path, child, uncertain or isinstance(node, _COMPOUND))', 'alternatives(path, child, False)'),)),
    Mutation("2QI-class-scope-occurrences", "2q-repair-2", "a replaced nested class still resolves to its stale declaration", (B + "test_class_scope_assignment_cannot_leave_a_stale_nested_class_binding",),
             target=M, old='            if self.class_scope[ref[1]][ref[2]].get(attr, []) != [("class", attr)]:', new='            if False:'),
    Mutation("2QI-lexical-base-scope", "2q-repair-2", "a nested class base guesses the module namespace", (B + "test_a_nested_class_base_uses_its_enclosing_class_namespace", B + "test_a_function_local_class_base_accounts_for_local_writes_and_parameters"),
             target=M, old='            ref = self.expr(path, node, qual.rpartition(".")[0])', new='            ref = self.expr(path, node)'),
    Mutation("2QI-locator-owner-binding", "2q-repair-2", "a qualified method survives replacement of its owning class", (Q + "test_a_replaced_class_owner_cannot_leave_a_stale_qualified_method",),
             target=C, old='            if len(options) != 1 or options[0][1]:', new='            if options[0][1]:'),
]
