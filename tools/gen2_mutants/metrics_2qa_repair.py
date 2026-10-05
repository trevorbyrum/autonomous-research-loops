"""Mutants of task 2q-a-repair: the rules added to the architecture-metrics
tool (tools/gen2_metrics.py) and the locator check (tools/check_gen2_locators.py)
for Astra's 2q-a review F1, F2, F4 and F5, each guard removed or weakened alone.

  2QR-collab-*    F1: the class and import surface a base is resolved over,
                  the C3 order, the once-only count of a call site, the
                  classification of what cannot be followed (unresolved);
  2QR-offender-*  F2: a baselined function compared in both dimensions before
                  the thresholds apply, and what a rebaseline keeps of it;
  2QR-dep-*       F5: the per-file dependency ratchet (fan-out, fan-in of a
                  stable file, reach among the files that existed);
  2QR-rebaseline-*, 2QR-upgrade-*  what a rebaseline records of it, and the
                  upgrade of a version-1 baseline;
  2QR-loc-*       F4: the locator grammar (marked spans, full module paths,
                  the unmarked dotted name).

Every killer is a black-box test of the tool on a throwaway repository: it
fails by assertion. A killer that sees the tool crash fails on the exit
status it asserts, not on the exception.
"""
from __future__ import annotations

from .base import Mutation

MET, LOC = "tools/gen2_metrics.py", "tools/check_gen2_locators.py"
IDX, CON, LED = "tools/gen2_source_index.py", "tools/gen2_source_contract.py", "tools/gen2_metrics_ledger.py"
CONT = "test_source_contract.RefusalTest."
CS, CN, CI, CM, CO, CR, CU = (f"test_metrics_collaboration.{c}." for c in (
    "SupportedSurfaceTest", "NestedClassTest", "SameFileIntermediateTest", "MethodResolutionOrderTest", "OverlappingFamiliesTest",
    "RouterInMiniatureTest", "RefusedBaseTest"))
OF = "test_metrics_offenders.BaselinedOffenderTest."
DA, DF, DI, DS, DR, DU = (f"test_metrics_dependencies.{c}." for c in ("AstrasProbesTest", "FanOutTest", "FanInTest", "StableLimitTest", "RecordingTest", "UpgradeTest"))
RB = "test_metrics_ratchet.BaselineFileTest."
LM, LU, LP = "test_locators.ModulePathTest.", "test_locators.UnmarkedDottedNameTest.", "test_locators.DeletedPrefixTest."

SPELL = CS + "test_every_spelling_of_a_base_is_resolved_to_the_class"
REEXPORT = CS + "test_a_reexport_through_a_package_is_followed"
UNFOLLOWED = CU + "test_a_base_the_contract_cannot_follow_is_refused_naming_the_class_the_category_and_why"


def r(mid: str, description: str, killers: tuple[str, ...], old: str, new: str, target: str = MET, also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2QR-{mid}", "2q-repair", description, killers, target=target, old=old, new=new, also=also)


MUTATIONS: list[Mutation] = [
    # --- F1: what a base is resolved over --------------------------------------------------------------------------------
    r("collab-subscripted-base", "a subscripted project base is accepted by erasure", (CONT + "test_refuses_src_base_subscript",),
      '                if inner[0] != "external" or inner[1] not in MODELLED_TYPING:', "                if False:", CON),
    r("collab-from-import-unbound", "a name brought in by `from m import n` is not followed to its class", (SPELL, REEXPORT),
      '        if binding.role == "from":\n            return self.member(self.module_ref(binding.ref[1]), binding.ref[2], seen, assignments)', '        if binding.role == "from":\n            return ("external", "x")', IDX),
    r("collab-import-alias-unbound", "a name bound by `import m` or `import m as x` is not followed to its module", (SPELL, CR + "test_the_composed_class_has_the_hand_counted_inventory_however_its_bases_are_written"),
      '        if binding.role == "import":\n            return self.module_ref(binding.ref[1])', '        if binding.role == "import":\n            return ("external", "x")', IDX),
    r("collab-module-members-unread", "the names a measured module defines or imports are not looked up", (SPELL, REEXPORT),
      "            if attr in module.bindings:", "            if False:", IDX),
    r("collab-star-import-accepted", "a star import is not reported", (CONT + "test_refuses_src_star_import",),
      "            for line in self.index.star_imports:", "            for line in ():", IDX),
    r("collab-submodule-not-an-attribute", "a submodule is not an attribute of its package", (SPELL, REEXPORT),
      "        if sub in self.names or sub in self.packages:\n            return self.module_ref(sub)", "        if False:\n            return self.module_ref(sub)", IDX),
    r("collab-nested-class-unfound", "a nested class is not found through its outer class", (CS + "test_a_nested_class_is_named_through_its_outer_class",),
      "            if fact is None or attr not in fact.scope.bindings:\n                raise Unresolved(\"SRC-NAME-UNRESOLVED\", f\"class {ref[2]} defines no {attr}\")", "            if True:\n                raise Unresolved(\"SRC-NAME-UNRESOLVED\", f\"class {ref[2]} defines no {attr}\")", IDX),
    r("collab-namespace-package-unknown", "a package without an __init__ is not a package", (SPELL, CR + "test_the_composed_class_has_the_hand_counted_inventory_however_its_bases_are_written"),
      '        if dotted in self.packages:\n            return ("package", dotted)', '        if False:\n            return ("package", dotted)', IDX),
    # --- F1: the order, the count, what cannot be followed ---------------------------------------------------------------
    r("collab-depth-first-order", "a method resolves depth-first, not through the C3 order", (CM + "test_a_diamond_is_resolved_by_c3_not_depth_first",),
      "        self._mro[key] = [key] + (c3_merge(sequences + [direct]) if direct else [OBJECT])", "        self._mro[key] = list(dict.fromkeys([key] + [member for seq in sequences for member in seq]))", IDX),
    r("collab-inconsistent-order-guessed", "an inconsistent hierarchy takes its first candidate", (CM + "test_an_inconsistent_order_is_refused_not_guessed",),
      '        if head is None:\n            raise ValueError("no consistent method resolution order")', '        if head is None:\n            head = sequences[0][0]', IDX),
    r("collab-site-counted-per-family", "a call site is counted once for each family that contains it", (CO + "test_a_site_in_two_families_is_one_site",
      CI + "test_a_class_whose_only_cross_file_ancestor_is_reached_through_a_same_file_base_is_still_a_family"),
      "            sites |= mine", "            sites += list(mine)", also=(("    sites: set[tuple[str, int, int, str]] = set()", "    sites: list = []"),)),
    r("collab-root-needs-a-direct-base-elsewhere", "a class is a family only if its own base is in another file", (CI + "test_a_class_whose_only_cross_file_ancestor_is_reached_through_a_same_file_base_is_still_a_family",),
      "            if not any(member[0] != path for member in order):\n                continue",
      '            if not any(ref[0] == "class" and ref[1] != path for _, ref in cls.bases):\n                continue'),
    r("collab-nested-class-self-counted", "a nested class's self-calls count for its outer class", ("test_metrics_collaboration.PropertyAndGeneratedMethodTest.test_a_closure_that_captures_the_receiver_is_counted_and_a_nested_class_is_not",),
      "        node = stack.pop()\n        if isinstance(node, ast.ClassDef):\n            continue", "        node = stack.pop()\n        if False:\n            continue"),
    r("collab-unresolved-not-reported", "a base the contract cannot follow is not reported", (UNFOLLOWED, CU + "test_a_base_from_the_other_service_is_refused"),
      '            self.refuse(exc.category, path, node.lineno, f"class {cls.qual} has the base {text}: {exc.why}", REMEDY[exc.category])\n            return', "            return", CON),
    r("collab-other-service-base-accepted", "a base from the other service is accepted", (CU + "test_a_base_from_the_other_service_is_refused",),
      '            if ref[0] == "class" and self.facts.service_of(ref[1]) != self.facts.service_of(path):', "            if False:", CON),
    r("collab-external-base-unresolved", "a builtin base is unresolved", (CU + "test_bases_outside_the_measured_files_are_leaves_outside_project_collaboration",),
      '        if hasattr(builtins, name):\n            return ("external", f"builtins.{name}")', "        if False:\n            return (\"external\", f\"builtins.{name}\")", IDX),
    r("collab-unmeasured-first-party-module-external", "an import of a first-party module that is not measured is external", (UNFOLLOWED,),
      '        if dotted.partition(".")[0] in self.tops:', "        if False:", IDX),
    r("collab-refusal-exits-zero", "a refusal of the source ends the command with exit 0", ("test_source_contract.EveryCommandTest.test_check_refuses",),
      "        print_refusal(exc.diagnostics)\n        return EXIT_FAIL", "        print_refusal(exc.diagnostics)\n        return EXIT_OK"),
    r("collab-classify-accepted", "a classification is an action the ledger accepts", (CU + "test_a_classify_entry_is_an_invalid_action_and_cannot_waive_anything",),
      'ACTIONS = ("map", "retire", "admit", "budget", "move")', 'ACTIONS = ("map", "retire", "admit", "budget", "move", "classify")', LED),
    # --- F2: a baselined function, both dimensions ------------------------------------------------------------------------
    r("offender-tracked-dropped", "a mapped destination is not compared with the budget that followed it", ("test_metrics_plan.RenameAndNewFileTest.test_a_rename_that_raises_a_score_above_the_old_ceiling_still_fails_after_the_map",
      "test_metrics_identity.IdentityTest.test_rename_and_move_with_crossed_scores_require_mapping_and_compare_both_scores"),
      '            out["services"][service]["functions"][key] = out["services"][service]["all_functions"][key]', '            out["services"][service]["functions"].pop(key, None)', LED),
    r("offender-growth-needs-a-threshold", "a baselined function's growth counts only above a threshold", (OF + "test_astras_probe_a_function_that_leaves_both_thresholds_while_one_score_grows_fails",),
      "grown = [(metric, field_) for metric, field_, _ in pairs if now[field_] > was[field_]]",
      "grown = [(metric, field_) for metric, field_, limit in pairs if now[field_] > was[field_] and now[field_] > limit]"),
    r("offender-cognitive-growth-ignored", "a baselined function's cognitive growth is not compared", (OF + "test_astras_probe_a_function_that_leaves_both_thresholds_while_one_score_grows_fails",),
      "for metric, field_, _ in pairs if now[field_] > was[field_]]", "for metric, field_, _ in pairs[:1] if now[field_] > was[field_]]"),
    r("offender-cyclomatic-growth-ignored", "a baselined function's cyclomatic growth is not compared", (OF + "test_the_opposite_direction_across_the_thresholds_fails_too",),
      "for metric, field_, _ in pairs if now[field_] > was[field_]]", "for metric, field_, _ in pairs[1:] if now[field_] > was[field_]]"),
    r('offender-kept-after-it-improves', 'a function that improved under both thresholds stays in the baseline', ('test_metrics_offenders.BaselinedOffenderTest.test_both_scores_improving_passes_and_identity_remains',),
      '                out["functions"][key] = kept  # identity persists below thresholds', '                if grown or kept["cyclomatic"] > limits["function_cyclomatic"] or kept["cognitive"] > limits["function_cognitive"]:\n                    out["functions"][key] = kept', 'tools/gen2_metrics.py'),
    r('offender-dropped-with-an-exempted-growth', 'an exempted growth drops the entry from the baseline', ('test_metrics_offenders.BaselinedOffenderTest.test_an_exempted_growth_is_never_recorded_and_the_entry_stays_with_the_old_value',),
      '                out["functions"][key] = kept  # identity persists below thresholds', '                if not grown:\n                    out["functions"][key] = kept', 'tools/gen2_metrics.py'),
    r('offender-dropped-while-still-over', 'a function still over a threshold leaves the baseline', ('test_metrics_offenders.BaselinedOffenderTest.test_one_score_improving_and_the_other_unchanged_passes_and_records_the_lower_value',),
      '                out["functions"][key] = kept  # identity persists below thresholds', '                if grown:\n                    out["functions"][key] = kept', 'tools/gen2_metrics.py'),
    # --- F5: the per-file dependency ratchet ------------------------------------------------------------------------------
    r("dep-fan-out-ignored", "a file's fan-out may rise", (DA + "test_an_import_of_something_already_reachable_raises_a_fan_out_and_is_a_regression",
      DA + "test_the_production_engine_with_a_redundant_import_added_to_one_file"), 'if new["fan_out"][f] > old["fan_out"][f] else []', "if False else []"),
    r("dep-fan-out-equal-fails", "an unchanged fan-out is a regression", (RB + "test_a_clean_tree_passes",), 'if new["fan_out"][f] > old["fan_out"][f] else []', 'if new["fan_out"][f] >= old["fan_out"][f] else []'),
    r("dep-fan-in-ignored", "a stable file's fan-in may rise", (DI + "test_a_stable_file_gaining_a_dependent_among_the_existing_files_is_a_regression", DS + "test_exactly_the_stable_limit_is_stable"),
      'if now > old["fan_in"][f] else []', "if False else []"),
    r("dep-fan-in-gated-for-every-file", "an unstable file's fan-in is gated too", (DI + "test_an_unstable_file_gaining_a_dependent_is_not", DS + "test_one_import_more_is_not_stable"),
      '        if total and Fraction(old["fan_out"][f], total) <= stable_max:', "        if total:"),
    r("dep-stable-limit-exclusive", "a file at exactly the stable limit is not stable", (DS + "test_exactly_the_stable_limit_is_stable",),
      'Fraction(old["fan_out"][f], total) <= stable_max', 'Fraction(old["fan_out"][f], total) < stable_max'),
    r('dep-fan-in-counts-new-files', 'new dependents are omitted from a stable target fan-in', ('test_metrics_dependencies.FanInTest.test_a_new_file_depending_on_a_stable_file_requires_admission',),
      '            now = sum(f in new["graph"][x] for x in new["graph"])', '            now = sum(f in new["graph"][x] for x in survivors)', 'tools/gen2_metrics.py'),
    r("dep-reach-gain-ignored", "a pair that became reachable passes", (DA + "test_a_dependency_hidden_by_an_unrelated_file_is_counted_in_absolute_reachable_pairs",
      DF + "test_replacing_one_import_by_another_is_no_rise"), 'violations += [Violation("reach_gained", service, len(gained), 0)] if gained else []',
      'violations += [Violation("reach_gained", service, len(gained), 0)] if False else []'),
    r("dep-reach-compared-by-total", "reach gained is a larger total, so a swap of one pair for another passes", (DF + "test_replacing_one_import_by_another_is_no_rise",),
      '    gained, lost = pairs(new["reach"]) - pairs(old["reach"]), pairs(old["reach"]) - pairs(new["reach"])',
      '    gained = pairs(new["reach"]) - pairs(old["reach"]) if len(pairs(new["reach"])) > len(pairs(old["reach"])) else set()\n    lost = pairs(old["reach"]) - pairs(new["reach"])'),
    r("dep-new-files-are-baselined", "new file budgets are implicitly admitted without ledger entries", ("test_metrics_identity.IdentityTest.test_isolated_new_file_is_unadmitted_without_a_tool_crash",),
      '        elif not drafting:', '        elif False:', LED),
    # --- F5: what a rebaseline records, and the upgrade ------------------------------------------------------------------
    r("rebaseline-fan-out-loosens", "a rebaseline records a higher fan-out", (DR + "test_an_exempted_rise_is_never_recorded",),
      'out["fan_out"] = {f: min(n, old["fan_out"][f]) if f in survivors else n for f, n in now["fan_out"].items()}', 'out["fan_out"] = dict(now["fan_out"])'),
    r('rebaseline-fan-in-loosens', 'a rebaseline records a higher fan-in', ('test_metrics_dependencies.RecordingTest.test_an_exempted_fan_in_rise_is_never_recorded',),
      'min(sum(f in now["graph"][x] for x in now["graph"]), old["fan_in"][f])', 'sum(f in now["graph"][x] for x in now["graph"])', 'tools/gen2_metrics.py'),
    r("rebaseline-reach-loosens", "a new reach pair is admitted without a ledger entry", ("test_metrics_identity.IdentityTest.test_new_reach_needs_admission_even_when_edge_and_numeric_growth_are_approved",),
      '        elif not drafting:', '        elif not drafting and "|reach|" not in ref:', LED),
    r("rebaseline-new-file-unrecorded", "a rebaseline records a file new since the baseline with a fan-out of zero", ("test_metrics_dependencies.FanOutTest.test_a_new_file_needs_bounded_admission_and_its_budget_is_then_enforced",),
      '                s[field_][location] = now[field_][location]', '                s[field_][location] = 0 if field_ == "fan_out" else now[field_][location]', LED),
    r("upgrade-refusal-removed", "a version-1 baseline is read by check, its missing dependency maps taken as empty", ("test_metrics_dependencies.UpgradeTest.test_check_refuses_it_and_names_the_remedy",),
      '    if isinstance(baseline, dict) and baseline.get("version") in (1, 2) and not upgradable:', "    if False:", MET,
      also=(("    return baseline\n\n\ndef make_baseline", '    if baseline["version"] in (1, 2):   # read as a current baseline, its missing dependency maps empty (after the digest check)\n        for s in baseline["services"].values():\n            for key in ("fan_out", "fan_in", "reach", "graph"):\n                s.setdefault(key, {})\n    return baseline\n\n\ndef make_baseline'),)),
    r('upgrade-forgives-regressions', 'an upgrade of a version-1 baseline does not compare what it held', ('test_metrics_dependencies.UpgradeTest.test_an_upgrade_does_not_forgive_a_regression_of_what_the_old_baseline_held',),
      '        if baseline["pin"]["production_sha256"] != at_old.report["pin"]["production_sha256"]:', '        if False:', 'tools/gen2_metrics.py'),
    r('upgrade-reads-as-unchanged', 'an upgrade of a version-1 baseline writes nothing', ('test_metrics_dependencies.UpgradeTest.test_rebaseline_upgrades_it_once',),
      '    if unchanged and not upgrading and not entries:', '    if unchanged and not entries:', 'tools/gen2_metrics.py'),
    # --- F4: the locator grammar -----------------------------------------------------------------------------------------
    r("loc-unmarked-dotted-name-passes", "a dotted name that is neither a locator nor marked is not reported",
      (LU + "test_a_dotted_name_that_is_neither_a_locator_form_nor_marked_is_an_error_whatever_its_prefix", LP + "test_a_shorthand_naming_the_module_or_the_class_is_an_error_in_both_states"),
      '                problems.append(f"{doc}:{line_of(start)}: `{span}`: UNMARKED DOTTED NAME: write', '                [].append(f"{doc}:{line_of(start)}: `{span}`: UNMARKED DOTTED NAME: write', LOC),
    r("loc-every-dotted-name-a-module-path", "a dotted name of any prefix is read as a module path", (LU + "test_a_dotted_name_that_is_neither_a_locator_form_nor_marked_is_an_error_whatever_its_prefix",),
      '            if name.partition(".")[0] not in PACKAGES:', "            if False:", LOC),
    r("loc-first-party-package-narrowed", "research_gateway is not a first-party package", (LM + "test_a_full_module_path_names_a_module_and_a_name_in_it",),
      'PACKAGES = ("gen2", "research_gateway")', 'PACKAGES = ("gen2",)', LOC),
    r("loc-module-path-unchecked", "a full module path is not looked for", (LM + "test_a_name_that_is_not_defined_or_a_module_that_is_not_there_fails", LP + "test_a_full_module_path_is_checked_and_stops_passing_when_the_module_goes"),
      "            if why:\n                fail(start, span, why)", "            if False:\n                fail(start, span, why)", LOC),
    r("loc-module-path-name-unchecked", "the name after a module path is not looked for", (LM + "test_a_name_that_is_not_defined_or_a_module_that_is_not_there_fails",
      LM + "test_a_name_is_looked_for_where_it_is_defined_not_where_it_is_inherited"),
      "            reason = why_not(sources, path, symbol, qualified=True) if symbol else None", "            reason = None", LOC),
    r("loc-module-path-shortest-module", "the shortest prefix that is a module is the module", (LM + "test_the_longest_module_is_the_module_so_a_package_does_not_swallow_its_submodule",),
      "    for length in range(len(parts), 1, -1):", "    for length in range(2, len(parts) + 1):", LOC),
    r("loc-namespace-package-not-a-module-path", "a package without an __init__ names no module", (LM + "test_a_full_module_path_names_a_module_and_a_name_in_it",),
      '    return None if any(m.startswith(name + ".") for m in modules) else "names no module of this repository"', '    return "names no module of this repository"', LOC),
    r("loc-marker-ignored", "a marked span is checked as if it were not marked", (LU + "test_a_marked_span_is_counted_and_not_checked",),
      "        if marked:\n            checked[marked.group(1)] += 1\n            continue", "        if False:\n            checked[marked.group(1)] += 1\n            continue", LOC),
    r("loc-marker-needs-no-space", "`code:x` is a marker", (LU + "test_a_marker_needs_a_space_and_text_after_it",),
      'MARKED = re.compile(r"^(code|history):\\s+\\S")', 'MARKED = re.compile(r"^(code|history):\\s*\\S")', LOC),
]
