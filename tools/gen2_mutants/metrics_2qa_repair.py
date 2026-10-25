"""Remaining debt, locator and tool-execution mutations after S3 retirement."""
from __future__ import annotations

from .base import Mutation

LM = 'test_locators.ModulePathTest.'
LOC = 'tools/check_gen2_locators.py'
LP = 'test_locators.DeletedPrefixTest.'
LU = 'test_locators.UnmarkedDottedNameTest.'


def r(mid: str, description: str, killers: tuple[str, ...], old: str, new: str, target: str = "tools/check_gen2_locators.py", also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2QR-{mid}", "2q-repair", description, killers, target=target, old=old, new=new, also=also)


MUTATIONS: list[Mutation] = [
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
