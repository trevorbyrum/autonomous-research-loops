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
CS, CN, CI, CM, CO, CR, CU = (f"test_metrics_collaboration.{c}." for c in (
    "SupportedSurfaceTest", "NestedClassTest", "SameFileIntermediateTest", "MethodResolutionOrderTest", "OverlappingFamiliesTest",
    "RouterInMiniatureTest", "UnresolvedBaseTest"))
OF = "test_metrics_offenders.BaselinedOffenderTest."
DA, DF, DI, DS, DR, DU = (f"test_metrics_dependencies.{c}." for c in ("AstrasProbesTest", "FanOutTest", "FanInTest", "StableLimitTest", "RecordingTest", "UpgradeTest"))
RB = "test_metrics_ratchet.BaselineFileTest."
LM, LU, LP = "test_locators.ModulePathTest.", "test_locators.UnmarkedDottedNameTest.", "test_locators.DeletedPrefixTest."

SPELL = CS + "test_every_spelling_of_a_base_is_resolved_to_the_class"
REEXPORT = CS + "test_a_reexport_through_a_package_is_followed"
UNFOLLOWED = CU + "test_a_base_the_tool_cannot_follow_fails_the_check_naming_the_class_and_why"


def r(mid: str, description: str, killers: tuple[str, ...], old: str, new: str, target: str = MET, also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2QR-{mid}", "2q-repair", description, killers, target=target, old=old, new=new, also=also)


MUTATIONS: list[Mutation] = [
    # --- F1: what a base is resolved over --------------------------------------------------------------------------------
    r("collab-subscripted-base", "a subscripted base (Base[int]) is not followed to its class", (SPELL,),
      "        if isinstance(node, ast.Subscript):\n            return self.expr(path, node.value)", "        if False:\n            return self.expr(path, node.value)"),
    r("collab-from-import-unbound", "a name brought in by `from m import n` is not followed to its class", (SPELL, REEXPORT),
      '        if kind == "from":\n            return self.member(self.module(rest[0]), rest[1], seen)', '        if kind == "from":\n            return ("external",)'),
    r("collab-import-alias-unbound", "a name bound by `import m` or `import m as x` is not followed to its module", (SPELL, CR + "test_the_composed_class_has_the_hand_counted_inventory_however_its_bases_are_written"),
      '        if kind == "module":\n            return self.module(rest[0])', '        if kind == "module":\n            return ("external",)'),
    r("collab-module-members-unread", "the names a measured module defines or imports are not looked up", (SPELL, REEXPORT),
      "            if attr in self.scope[path]:", "            if False:"),
    r("collab-star-reexport-dropped", "a name a package takes from a star import is not followed", (REEXPORT,),
      'for star in sorted(b[1] for b in self.scope[path].get("*", ()) if self.module(b[1])[0] in ("module", "package")):', "for star in []:"),
    r("collab-submodule-not-an-attribute", "a submodule is not an attribute of its package", (SPELL, REEXPORT),
      '        return self.module(sub) if sub in self.names or sub in self.packages else ("unresolved", f"{dotted} defines no {attr}")',
      '        return ("unresolved", f"{dotted} defines no {attr}")'),
    r("collab-nested-class-unfound", "a nested class is not found through its outer class", (CS + "test_a_nested_class_is_named_through_its_outer_class",),
      '            return ("class", ref[1], nested) if nested in self.classes[ref[1]] else ("unresolved", f"{ref[2]} defines no class {attr}")',
      '            return ("unresolved", f"{ref[2]} defines no class {attr}")'),
    r("collab-namespace-package-unknown", "a package without an __init__ is not a package", (SPELL, CR + "test_the_composed_class_has_the_hand_counted_inventory_however_its_bases_are_written"),
      '        if dotted in self.packages:\n            return ("package", dotted)', '        if False:\n            return ("package", dotted)'),
    # --- F1: the order, the count, what cannot be followed ---------------------------------------------------------------
    r("collab-depth-first-order", "a method resolves depth-first, not through the C3 order", (CM + "test_a_diamond_is_resolved_by_c3_not_depth_first",),
      "        self._mro[key] = [key] + c3_merge(sequences + [direct])",
      "        self._mro[key] = list(dict.fromkeys([key] + [member for seq in sequences for member in seq]))"),
    r("collab-inconsistent-order-guessed", "an inconsistent hierarchy takes its first candidate", (CM + "test_an_inconsistent_order_is_reported_not_guessed",),
      '        if head is None:\n            raise ValueError("no consistent method resolution order")', "        if head is None:\n            head = sequences[0][0]"),
    r("collab-site-counted-per-family", "a call site is counted once for each family that contains it", (CO + "test_a_site_in_two_families_is_one_site",
      CI + "test_a_class_whose_only_cross_file_ancestor_is_reached_through_a_same_file_base_is_still_a_family"),
      "            sites |= mine", "            sites += list(mine)", also=(("    sites: set[tuple[str, int, int, str]] = set()", "    sites: list = []"),)),
    r("collab-root-needs-a-direct-base-elsewhere", "a class is a family only if its own base is in another file", (CI + "test_a_class_whose_only_cross_file_ancestor_is_reached_through_a_same_file_base_is_still_a_family",),
      "            if not any(member[0] != path for member in order):\n                continue",
      '            if not any(ref[0] == "class" and ref[1] != path for _, ref in bases):\n                continue'),
    r("collab-nested-class-self-counted", "a nested class's self-calls count for its outer class", (CN + "test_a_nested_class_has_its_own_self",),
      "        node = stack.pop()\n        if isinstance(node, ast.ClassDef):\n            continue", "        node = stack.pop()\n        if False:\n            continue"),
    r("collab-unresolved-not-reported", "a base the tool cannot follow is not reported", (UNFOLLOWED, CU + "test_a_base_from_the_other_service_is_reported"),
      'if ref[0] == "unresolved" or (ref[0] == "class" and ref[1] not in in_service):', "if False:"),
    r("collab-other-service-base-accepted", "a base from the other service is not reported", (CU + "test_a_base_from_the_other_service_is_reported",),
      'if ref[0] == "unresolved" or (ref[0] == "class" and ref[1] not in in_service):', 'if ref[0] == "unresolved":'),
    r("collab-external-base-unresolved", "a builtin base is unresolved", (CU + "test_bases_outside_the_measured_files_are_classified_without_an_exemption",),
      '            return ("external",) if hasattr(builtins, name) else ("unresolved", f"{name} is neither defined nor imported in {path}")',
      '            return ("unresolved", f"{name} is neither defined nor imported in {path}")'),
    r("collab-unmeasured-first-party-module-external", "an import of a first-party module that is not measured is external", (UNFOLLOWED,),
      '        return ("unresolved", f"{dotted} is not a measured module") if dotted.partition(".")[0] in self.tops else ("external",)', '        return ("external",)'),
    r("collab-unresolved-not-gated", "an unresolved base is not a regression", (UNFOLLOWED, CU + "test_an_unresolved_base_is_not_recorded_by_a_rebaseline_and_refuses_it_when_new"),
      '"unresolved_bases": dict(s["self_calls"]["unresolved"]),', '"unresolved_bases": {},'),
    r("collab-unresolved-cannot-be-exempted", "an exemption may not name an unresolved base", (CU + "test_an_exemption_classifies_it_and_a_stale_one_fails",),
      '"cross_service_import", "unresolved_base", "smell_hub_like"', '"cross_service_import", "smell_hub_like"'),
    # --- F2: a baselined function, both dimensions ------------------------------------------------------------------------
    r("offender-tracked-dropped", "a baselined function is compared only while it is over a threshold", (OF + "test_astras_probe_a_function_that_leaves_both_thresholds_while_one_score_grows_fails",
      OF + "test_the_opposite_direction_across_the_thresholds_fails_too"),
      "        for key in sorted((tracked or {}).get(service, ())):", "        for key in ():"),
    r("offender-growth-needs-a-threshold", "a baselined function's growth counts only above a threshold", (OF + "test_astras_probe_a_function_that_leaves_both_thresholds_while_one_score_grows_fails",),
      "grown = [(metric, field_) for metric, field_, _ in pairs if now[field_] > was[field_]]",
      "grown = [(metric, field_) for metric, field_, limit in pairs if now[field_] > was[field_] and now[field_] > limit]"),
    r("offender-cognitive-growth-ignored", "a baselined function's cognitive growth is not compared", (OF + "test_astras_probe_a_function_that_leaves_both_thresholds_while_one_score_grows_fails",),
      "for metric, field_, _ in pairs if now[field_] > was[field_]]", "for metric, field_, _ in pairs[:1] if now[field_] > was[field_]]"),
    r("offender-cyclomatic-growth-ignored", "a baselined function's cyclomatic growth is not compared", (OF + "test_the_opposite_direction_across_the_thresholds_fails_too",),
      "for metric, field_, _ in pairs if now[field_] > was[field_]]", "for metric, field_, _ in pairs[1:] if now[field_] > was[field_]]"),
    r("offender-kept-after-it-improves", "a function that improved under both thresholds stays in the baseline", (OF + "test_both_scores_improving_passes_and_the_entry_leaves_the_baseline",),
      '                if grown or kept["cyclomatic"] > limits["function_cyclomatic"] or kept["cognitive"] > limits["function_cognitive"]:', "                if True:"),
    r("offender-dropped-with-an-exempted-growth", "an exempted growth drops the entry from the baseline", (OF + "test_an_exempted_growth_is_never_recorded_and_the_entry_stays_with_the_old_value",),
      '                if grown or kept["cyclomatic"] > limits["function_cyclomatic"] or kept["cognitive"] > limits["function_cognitive"]:',
      '                if kept["cyclomatic"] > limits["function_cyclomatic"] or kept["cognitive"] > limits["function_cognitive"]:'),
    r("offender-dropped-while-still-over", "a function still over a threshold leaves the baseline", (OF + "test_one_score_improving_and_the_other_unchanged_passes_and_records_the_lower_value",),
      '                if grown or kept["cyclomatic"] > limits["function_cyclomatic"] or kept["cognitive"] > limits["function_cognitive"]:', "                if grown:"),
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
    r("dep-fan-in-counts-new-files", "a new file depending on a stable file raises its fan-in", (DI + "test_a_new_file_depending_on_a_stable_file_is_not_a_regression",),
      '            now = sum(f in new["graph"][x] for x in survivors)', '            now = sum(f in new["graph"][x] for x in new["graph"])'),
    r("dep-reach-gain-ignored", "a pair that became reachable passes", (DA + "test_a_dependency_hidden_by_an_unrelated_file_is_counted_in_absolute_reachable_pairs",
      DF + "test_replacing_one_import_by_another_is_no_rise"), 'violations += [Violation("reach_gained", service, len(gained), 0)] if gained else []',
      'violations += [Violation("reach_gained", service, len(gained), 0)] if False else []'),
    r("dep-reach-compared-by-total", "reach gained is a larger total, so a swap of one pair for another passes", (DF + "test_replacing_one_import_by_another_is_no_rise",),
      '    gained, lost = pairs(new["reach"]) - pairs(old["reach"]), pairs(old["reach"]) - pairs(new["reach"])',
      '    gained = pairs(new["reach"]) - pairs(old["reach"]) if len(pairs(new["reach"])) > len(pairs(old["reach"])) else set()\n    lost = pairs(old["reach"]) - pairs(new["reach"])'),
    r("dep-new-files-are-baselined", "a file new since the baseline has a fan-out of zero to regress from", (DF + "test_a_file_new_since_the_baseline_may_import_what_it_likes_until_it_is_recorded",),
      '    survivors = set(old["fan_out"]) & set(new["fan_out"])', '    survivors = set(new["fan_out"])'),
    # --- F5: what a rebaseline records, and the upgrade ------------------------------------------------------------------
    r("rebaseline-fan-out-loosens", "a rebaseline records a higher fan-out", (DR + "test_an_exempted_rise_is_never_recorded",),
      'out["fan_out"] = {f: min(n, old["fan_out"][f]) if f in survivors else n for f, n in now["fan_out"].items()}', 'out["fan_out"] = dict(now["fan_out"])'),
    r("rebaseline-fan-in-loosens", "a rebaseline records a higher fan-in", (DR + "test_an_exempted_fan_in_rise_is_never_recorded",),
      'min(sum(f in now["graph"][x] for x in survivors), old["fan_in"][f])', 'sum(f in now["graph"][x] for x in survivors)'),
    r("rebaseline-reach-loosens", "a rebaseline records pairs that became reachable", (DR + "test_an_exempted_rise_is_never_recorded",),
      'out["reach"] = {f: sorted(t for t in targets if not (f in survivors and t in survivors) or t in old["reach"][f]) for f, targets in now["reach"].items()}',
      'out["reach"] = {f: sorted(targets) for f, targets in now["reach"].items()}'),
    r("rebaseline-new-file-unrecorded", "a rebaseline records a file new since the baseline with a fan-out of zero", (DF + "test_a_file_new_since_the_baseline_may_import_what_it_likes_until_it_is_recorded",),
      'out["fan_out"] = {f: min(n, old["fan_out"][f]) if f in survivors else n for f, n in now["fan_out"].items()}',
      'out["fan_out"] = {f: min(n, old["fan_out"][f]) if f in survivors else 0 for f, n in now["fan_out"].items()}'),
    r("upgrade-refusal-removed", "a baseline of version 1 is read by check", (DU + "test_check_refuses_it_and_names_the_remedy",),
      '    if isinstance(baseline, dict) and baseline.get("version") == 1 and not upgradable:', "    if False:"),
    r("upgrade-forgives-regressions", "an upgrade of a version-1 baseline does not compare what it held", (DU + "test_an_upgrade_does_not_forgive_a_regression_of_what_the_old_baseline_held",),
      "    violations, _ = compare(baseline, gated(at_old, tracked_of(baseline)))", "    violations = [] if upgrading else compare(baseline, gated(at_old, tracked_of(baseline)))[0]"),
    r("upgrade-reads-as-unchanged", "an upgrade of a version-1 baseline writes nothing", (DU + "test_rebaseline_upgrades_it_once",),
      '    if not upgrading and {k: v for k, v in updated.items() if k != "pin"} == {', '    if {k: v for k, v in updated.items() if k != "pin"} == {'),
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
      '            return f"{symbol} is not defined in {path}" if symbol and not defines(root, path, symbol) else None', "            return None", LOC),
    r("loc-module-path-shortest-module", "the shortest prefix that is a module is the module", (LM + "test_the_longest_module_is_the_module_so_a_package_does_not_swallow_its_submodule",),
      "    for length in range(len(parts), 1, -1):", "    for length in range(2, len(parts) + 1):", LOC),
    r("loc-namespace-package-not-a-module-path", "a package without an __init__ names no module", (LM + "test_a_full_module_path_names_a_module_and_a_name_in_it",),
      '    return None if any(m.startswith(name + ".") for m in modules) else "names no module of this repository"', '    return "names no module of this repository"', LOC),
    r("loc-marker-ignored", "a marked span is checked as if it were not marked", (LU + "test_a_marked_span_is_counted_and_not_checked",),
      "        if marked:\n            checked[marked.group(1)] += 1\n            continue", "        if False:\n            checked[marked.group(1)] += 1\n            continue", LOC),
    r("loc-marker-needs-no-space", "`code:x` is a marker", (LU + "test_a_marker_needs_a_space_and_text_after_it",),
      'MARKED = re.compile(r"^(code|history):\\s+\\S")', 'MARKED = re.compile(r"^(code|history):\\s*\\S")', LOC),
]
