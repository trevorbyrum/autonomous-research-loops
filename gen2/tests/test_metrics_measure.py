"""Black-box tests of what `tools/gen2_metrics.py` measures (task 2q-a; charter
"Architecture metrics"): the import graph, propagation cost, cycles at file
and component level, the implicit collaboration between the classes of one
inheritance family, the smells, the function complexity proxies and the git
history report.

Each test writes a throwaway git repository of literal files
(gen2/tests/tool_repo_fixtures.py), runs `report` or `hotspots` on it as a
subprocess and compares the tables it writes with numbers WORKED OUT BY HAND
in the test from the fixture's text (the comment beside each says how), never
read back from the tool. The definitions are Gate D #1's
(private/evidence/gate-d-1/measure.py); a separate evidence run in
private/evidence/2q-a/ shows the tool's tables byte-identical to that script's
on the pinned commits of Gate D #1, #2 and #3.

What this cannot show: that a metric is the RIGHT one (the thresholds are
operating points, the tool's docstring says so) or that the proxies equal
McCabe's or SonarSource's; only that the tool computes what it says.
"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.tool_repo_fixtures import Repo, component_files, hub_files, padding, py, unstable_files, with_branches


def rows(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def measured(repo: Repo) -> tuple[dict, Path]:
    """`report` on the repository: the summary and the directory the tables went to."""
    out = Path(tempfile.mkdtemp(dir=repo.root.parent, prefix="out-"))
    done = repo.run("report", str(out))
    if done.returncode:
        raise AssertionError(done.stderr)
    return json.loads((out / "metrics-summary.json").read_text()), out


def by_module(out: Path) -> dict[str, dict]:
    return {r["module"]: r for r in rows(out / "file-dependencies.csv")}


class RepoTestCase(unittest.TestCase):
    def repo(self, files: dict[str, str], **kwargs) -> Repo:
        repo = Repo(files, **kwargs)
        self.addCleanup(repo.close)
        return repo


# Seven files. Edges, by hand (an import of `gen2.X` names the file, a from-import also names the package and `package.name`):
#   a -> b                                  `import gen2.b` (`json` is external)
#   b -> __init__, c, d                     `from gen2 import c` (the package and gen2.c), and a function-local `from gen2.d import x`
#   c -> e                                  an import under TYPE_CHECKING counts
#   f -> __init__, a, b                     `from . import a` (package gen2, gen2.a), `from .b import late`
#   d and e import nothing (e names itself: a self edge is no edge); the test module's `import gen2.f` is no edge (tests are not measured)
GRAPH = {
    "gen2/__init__.py": "",
    "gen2/a.py": py("import gen2.b", "import json"),
    "gen2/b.py": py("from gen2 import c", "", "def late():", "    from gen2.d import x", "    return x"),
    "gen2/c.py": py("from typing import TYPE_CHECKING", "if TYPE_CHECKING:", "    from gen2.e import E"),
    "gen2/d.py": "x = 1\n",
    "gen2/e.py": py("import gen2.e", "class E: pass"),
    "gen2/f.py": py("from . import a", "from .b import late"),
    "gen2/tests/test_x.py": py("import gen2.f"),
}


class GraphTest(RepoTestCase):
    def test_edges_fan_in_out_instability_and_reach_are_those_worked_out_by_hand(self) -> None:
        summary, out = measured(self.repo(GRAPH))
        engine = summary["services"]["engine"]
        self.assertEqual((engine["files"], engine["edges"]), (7, 8))
        # reach (self excluded): init 0, a {b,init,c,d,e} 5, b {init,c,d,e} 4, c {e} 1, d 0, e 0, f {init,a,b,c,d,e} 6
        expected = {  # fan_in, fan_out, instability (out/(in+out), blank when isolated), out_reach, in_reach
            "gen2/__init__.py": ("2", "0", "0.0", "0", "3"),   # imported by b, f; reached by a (via b) too: {a, b, f}
            "gen2/a.py": ("1", "1", "0.5", "5", "1"),
            "gen2/b.py": ("2", "3", "0.6", "4", "2"),
            "gen2/c.py": ("1", "1", "0.5", "1", "3"),          # reached by b, a, f
            "gen2/d.py": ("1", "0", "0.0", "0", "3"),
            "gen2/e.py": ("1", "0", "0.0", "0", "4"),          # c, b, a, f
            "gen2/f.py": ("0", "3", "1.0", "6", "0"),
        }
        table = by_module(out)
        self.assertEqual(set(table), set(expected))
        for module, values in expected.items():
            with self.subTest(module=module):
                row = table[module]
                self.assertEqual((row["fan_in"], row["fan_out"], row["instability"], row["out_reach"], row["in_reach"]), values)

    def test_propagation_cost_counts_self_reach_over_all_ordered_pairs(self) -> None:
        summary, _ = measured(self.repo(GRAPH))
        engine = summary["services"]["engine"]["propagation_file"]
        # sum over files of (1 + reach) = 1 + 6 + 5 + 2 + 1 + 1 + 7 = 23, over 7 * 7 = 49 ordered pairs
        self.assertEqual((engine["reach_pairs"], engine["nodes"]), (23, 7))
        self.assertAlmostEqual(engine["mean_other_reached"], 16 / 7, places=3)  # (0+5+4+1+0+0+6)/7, self excluded

    def test_the_summary_line_states_the_cost_as_a_percentage(self) -> None:
        repo = self.repo(GRAPH)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        done = repo.run("check")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertIn("engine: 7 files, 8 edges, propagation 46.9388%", done.stdout)  # 23/49

    def test_a_relative_import_from_a_subpackage_is_resolved(self) -> None:
        files = {"gen2/__init__.py": "", "gen2/a.py": "x = 1\n", "gen2/sub/__init__.py": "", "gen2/sub/m.py": py("from .. import a"), "gen2/sub/n.py": py("from . import m")}
        summary, out = measured(self.repo(files))
        table = by_module(out)
        # `from .. import a` in gen2.sub.m -> the package gen2 and gen2.a; `from . import m` in gen2.sub.n -> gen2.sub and gen2.sub.m
        self.assertEqual((table["gen2/sub/m.py"]["fan_out"], table["gen2/a.py"]["fan_in"], table["gen2/__init__.py"]["fan_in"]), ("2", "1", "1"))
        self.assertEqual((table["gen2/sub/n.py"]["fan_out"], table["gen2/sub/__init__.py"]["fan_in"], table["gen2/sub/m.py"]["fan_in"]), ("2", "1", "1"))

    def test_an_untracked_file_and_a_tracked_file_missing_from_disk_are_not_measured(self) -> None:
        repo = self.repo({"gen2/a.py": "x = 1\n", "gen2/gone.py": "y = 1\n"})
        repo.write({"gen2/gone.py": None}, commit=False)
        repo.write({"gen2/new.py": "import gen2.a\n"}, commit=False)
        summary, out = measured(repo)
        self.assertEqual(set(by_module(out)), {"gen2/a.py"})
        self.assertEqual(summary["services"]["engine"]["edges"], 0)

    def test_the_engine_and_the_gateway_are_measured_separately_and_tests_by_neither(self) -> None:
        files = {"gen2/a.py": py("import gen2.b"), "gen2/b.py": "x = 1\n", "gen2/tests/test_a.py": py("import gen2.a"),
                 "gateway/research_gateway/__init__.py": "", "gateway/research_gateway/core/__init__.py": "",
                 "gateway/research_gateway/core/x.py": py("from research_gateway.core import y"), "gateway/research_gateway/core/y.py": "z = 1\n",
                 "gateway/tests/test_x.py": py("import research_gateway.core.x")}
        summary, _ = measured(self.repo(files))
        engine, gateway = summary["services"]["engine"], summary["services"]["gateway"]
        self.assertEqual((engine["files"], engine["edges"]), (2, 1))
        # gateway: x -> core/__init__.py and y (`from research_gateway.core import y` names the package and the submodule)
        self.assertEqual((gateway["files"], gateway["edges"]), (4, 2))

    def test_an_import_between_the_services_is_reported_and_enters_neither_graph(self) -> None:
        files = {"gen2/a.py": py("import research_gateway.core.y"), "gateway/research_gateway/core/y.py": "z = 1\n",
                 "gateway/research_gateway/core/__init__.py": "", "gateway/research_gateway/__init__.py": ""}
        summary, _ = measured(self.repo(files))
        self.assertEqual(summary["cross_service_imports"], ["gen2/a.py->gateway/research_gateway/core/y.py"])
        self.assertEqual((summary["services"]["engine"]["edges"], summary["services"]["gateway"]["edges"]), (0, 0))


class CycleTest(RepoTestCase):
    def test_a_file_cycle_inside_one_component_is_not_a_component_cycle(self) -> None:
        files = {"gen2/p/__init__.py": "", "gen2/p/a.py": py("import gen2.p.b"), "gen2/p/b.py": py("import gen2.p.a")}
        engine = measured(self.repo(files))[0]["services"]["engine"]
        self.assertEqual(engine["cycles_file"], [["gen2/p/a.py", "gen2/p/b.py"]])
        self.assertEqual(engine["cycles_component"], [])

    def test_a_component_cycle_over_acyclic_files_is_found_at_component_level_only(self) -> None:
        # a (x) -> b (y) and c (y) -> d (x): no file cycle, but gen2.x -> gen2.y -> gen2.x
        files = {"gen2/x/a.py": py("import gen2.y.b"), "gen2/y/b.py": "v = 1\n", "gen2/y/c.py": py("import gen2.x.d"), "gen2/x/d.py": "v = 2\n"}
        engine = measured(self.repo(files))[0]["services"]["engine"]
        self.assertEqual(engine["cycles_file"], [])
        self.assertEqual(engine["cycles_component"], [["gen2.x", "gen2.y"]])

    def test_a_cycle_is_its_strongly_connected_set_and_not_the_files_that_lead_into_it(self) -> None:
        # a -> b -> c -> a is the cycle; d -> a reaches it but is not in it; e is reached from it and is not either
        files = {"gen2/a.py": py("import gen2.b", "import gen2.e"), "gen2/b.py": py("import gen2.c"), "gen2/c.py": py("import gen2.a"),
                 "gen2/d.py": py("import gen2.a"), "gen2/e.py": "v = 1\n"}
        engine = measured(self.repo(files))[0]["services"]["engine"]
        self.assertEqual(engine["cycles_file"], [["gen2/a.py", "gen2/b.py", "gen2/c.py"]])

    def test_the_gateways_cycle_is_not_the_engines(self) -> None:
        files = {"gen2/x.py": "v = 1\n", "gateway/research_gateway/core/__init__.py": "", "gateway/research_gateway/adapters/__init__.py": "",
                 "gateway/research_gateway/core/r.py": py("import research_gateway.adapters.b"), "gateway/research_gateway/adapters/b.py": py("import research_gateway.core.r")}
        summary = measured(self.repo(files))[0]["services"]
        self.assertEqual(summary["engine"]["cycles_file"] + summary["engine"]["cycles_component"], [])
        self.assertEqual(summary["gateway"]["cycles_component"], [["research_gateway.adapters", "research_gateway.core"]])


def family(*, lifecycle: str, service: str) -> dict[str, str]:
    return {"gen2/router/__init__.py": "", "gen2/router/lifecycle.py": lifecycle, "gen2/router/service.py": service}


class CollaborationTest(RepoTestCase):
    """The `self.` calls between the files of one inheritance family: the Router and its mixins in the engine."""

    def test_calls_between_the_files_of_one_family_are_counted_by_directed_pair(self) -> None:
        lifecycle = py("class Lifecycle:", "    def a(self):", "        self.b()", "        return self.on_service()",   # b: same file, not counted; on_service: service.py
                       "    def b(self):", "        return 1")
        service = py("from gen2.router.lifecycle import Lifecycle", "", "class Router(Lifecycle):",
                     "    def on_service(self):", "        self.a()", "        self.a()", "        self.unknown()", "        super().a()", "        self.helper.a()",
                     "        return 1")
        calls = measured(self.repo(family(lifecycle=lifecycle, service=service)))[0]["services"]["engine"]["self_calls"]
        # lifecycle -> service: 1 (self.on_service); service -> lifecycle: 2 (self.a twice). Not counted: self.b() (same file),
        # self.unknown() (defined nowhere), super().a() and self.helper.a() (not a call on self)
        self.assertEqual(calls["pairs"], {"gen2/router/lifecycle.py->gen2/router/service.py": 1, "gen2/router/service.py->gen2/router/lifecycle.py": 2})
        self.assertEqual(calls["sites"], 3)
        self.assertEqual(list(calls["families"]), ["Router (gen2/router/service.py)"])

    def test_a_method_resolves_the_way_the_composed_class_resolves_it(self) -> None:
        lifecycle = py("class Lifecycle:", "    def common(self):", "        return 1", "    def run(self):", "        return self.common()")
        service = py("from gen2.router.lifecycle import Lifecycle", "", "class Router(Lifecycle):", "    def common(self):", "        return 2")
        calls = measured(self.repo(family(lifecycle=lifecycle, service=service)))[0]["services"]["engine"]["self_calls"]
        # Lifecycle.run's self.common() reaches Router.common (the composed class's own definition first): lifecycle -> service, one site
        self.assertEqual(calls["pairs"], {"gen2/router/lifecycle.py->gen2/router/service.py": 1})

    def test_a_base_in_the_same_file_or_outside_the_project_is_no_family(self) -> None:
        one_file = py("class A:", "    def f(self):", "        return self.g()", "    def g(self):", "        return 1", "class B(A):", "    def h(self):", "        return self.f()",
                      "class E(Exception):", "    def k(self):", "        return self.args")
        calls = measured(self.repo({"gen2/x.py": one_file}))[0]["services"]["engine"]["self_calls"]
        self.assertEqual((calls["sites"], calls["pairs"], calls["families"]), (0, {}, {}))

    def test_a_base_named_through_a_module_attribute_is_found(self) -> None:
        for how in ("import gen2.router.lifecycle as lc", "from gen2.router import lifecycle as lc", "from gen2.router import lifecycle"):
            with self.subTest(how=how):
                name = "lifecycle" if how.endswith("lifecycle") and " as " not in how else "lc"
                lifecycle = py("class Lifecycle:", "    def a(self):", "        return self.on_service()")
                service = py(how, "", f"class Router({name}.Lifecycle):", "    def on_service(self):", "        return 1")
                calls = measured(self.repo(family(lifecycle=lifecycle, service=service)))[0]["services"]["engine"]["self_calls"]
                self.assertEqual(calls["pairs"], {"gen2/router/lifecycle.py->gen2/router/service.py": 1})

    def test_the_gateways_families_are_measured_apart_from_the_engines(self) -> None:
        files = {"gen2/x.py": "v = 1\n", "gateway/research_gateway/__init__.py": "", "gateway/research_gateway/a.py": py("class A:", "    def f(self):", "        return self.g()"),
                 "gateway/research_gateway/b.py": py("from research_gateway.a import A", "", "class B(A):", "    def g(self):", "        return 1")}
        summary = measured(self.repo(files))[0]["services"]
        self.assertEqual(summary["engine"]["self_calls"]["sites"], 0)
        self.assertEqual(summary["gateway"]["self_calls"]["pairs"], {"gateway/research_gateway/a.py->gateway/research_gateway/b.py": 1})


def fn_rows(out: Path) -> dict[str, tuple[int, int]]:
    return {f"{r['file']}::{r['function']}": (int(r["cyclomatic_proxy"]), int(r["cognitive_proxy"])) for r in rows(out / "function-complexity.csv")}


class ComplexityTest(RepoTestCase):
    """Gate D's proxies, each worked out by hand beside its fixture."""

    def measure_source(self, source: str) -> dict[str, tuple[int, int]]:
        _, out = measured(self.repo({"gen2/m.py": source}))
        return {k.split("::", 1)[1]: v for k, v in fn_rows(out).items()}

    def test_the_branches_nesting_and_comprehensions_of_one_function(self) -> None:
        source = py("def f(x, y):",
                    "    if x and y:",            # cyclomatic: if +1, `and` +1; cognitive: if 1+0, and 1
                    "        for i in y:",        # +1; cognitive 1+1
                    "            if i:",          # +1; cognitive 1+2
                    "                pass",
                    "    elif x:",                # +1; cognitive 1+0 (an elif is not nested)
                    "        pass",
                    "    return [k for k in y if k]")  # cyclomatic 1+1; cognitive 1+0+1
        # cyclomatic: 1 + 1 + 1 + 1 + 1 + 1 + 2 = 8; cognitive: 1 + 1 + 2 + 3 + 1 + 2 = 10
        self.assertEqual(self.measure_source(source), {"f": (8, 10)})

    def test_an_empty_function_and_a_straight_line_one(self) -> None:
        self.assertEqual(self.measure_source(py("def f():", "    pass", "def g(a):", "    return a + 1")), {"f": (1, 0), "g": (1, 0)})

    def test_nested_functions_and_lambdas_are_not_part_of_the_enclosing_function(self) -> None:
        source = py("def outer(a, b):",
                    "    def inner(c):",
                    "        if c:",
                    "            return 1",
                    "        return 2",
                    "    g = lambda z: (1 if z else 2)",
                    "    return inner(a)")
        # outer: 1 (the lambda and the nested def are not entered); outer.inner: if +1 -> 2, cognitive 1; the lambda is nobody's
        self.assertEqual(self.measure_source(source), {"outer": (1, 0), "outer.inner": (2, 1)})

    def test_methods_and_nested_classes_are_named_by_their_scope(self) -> None:
        source = py("class A:", "    def m(self, x):", "        if x:", "            return 1", "        return 0", "    class B:", "        def n(self):", "            return 1")
        self.assertEqual(self.measure_source(source), {"A.m": (2, 1), "A.B.n": (1, 0)})

    def test_only_except_handlers_count_not_try_else_or_finally(self) -> None:
        source = py("def f():", "    try:", "        x = 1", "    except ValueError:", "        x = 2", "    except KeyError:", "        x = 3", "    else:", "        x = 4", "    finally:",
                    "        x = 5", "    return x")
        self.assertEqual(self.measure_source(source), {"f": (3, 2)})  # 1 + 2 handlers; each handler 1 + 0

    def test_boolean_operators_count_their_operands_and_sequences(self) -> None:
        # `a and b and c or d` is Or(And(a, b, c), d): (2 - 1) + (3 - 1) = 3 operand steps, 2 sequences
        self.assertEqual(self.measure_source(py("def f(a, b, c, d):", "    x = a and b and c or d", "    return x")), {"f": (4, 2)})

    def test_a_ternary_an_assert_and_a_while(self) -> None:
        source = py("def f(a):", "    x = 1 if a else 2", "    assert x", "    while a:", "        a = a - 1", "    else:", "        pass", "    return x")
        # cyclomatic: 1 + ternary + assert + while = 4; cognitive: ternary 1, while 1 (assert adds none, the loop's else adds none)
        self.assertEqual(self.measure_source(source), {"f": (4, 2)})

    def test_match_counts_each_case_but_a_bare_wildcard(self) -> None:
        source = py("def f(v):", "    match v:", "        case 1:", "            return 1", "        case 2:", "            return 2", "        case other:", "            return other",
                    "        case _:", "            return 0")
        # cyclomatic: 1 + 3 (the capture `other` counts, `_` does not); cognitive: the match itself, 1 + 0
        self.assertEqual(self.measure_source(source), {"f": (4, 1)})

    def test_comprehension_generators_and_their_conditions(self) -> None:
        source = py("def f(b, d):", "    return [a for a in b if a if a > 1 for c in d]")
        # cyclomatic: 1 + (1 + 2 conditions) + (1 + 0) = 5; cognitive: (1 + 0 + 2) + (1 + 0 + 0) = 4
        self.assertEqual(self.measure_source(source), {"f": (5, 4)})

    def test_an_elif_chain_is_one_level_and_an_else_block_nests(self) -> None:
        chain = py("def f(a, b, c):", "    if a:", "        return 1", "    elif b:", "        return 2", "    elif c:", "        return 3", "    return 0")
        self.assertEqual(self.measure_source(chain), {"f": (4, 3)})  # 1 + 3 ifs; each 1 + 0
        nested = py("def f(a, b):", "    if a:", "        return 1", "    else:", "        for i in b:", "            return i", "    return 0")
        self.assertEqual(self.measure_source(nested), {"f": (3, 3)})  # if 1; the for inside its else: 1 + 1

    def test_an_async_function_and_an_async_for(self) -> None:
        self.assertEqual(self.measure_source(py("async def f(a):", "    async for i in a:", "        pass")), {"f": (2, 1)})

    def test_physical_lines_are_the_def_to_its_last_line(self) -> None:
        _, out = measured(self.repo({"gen2/m.py": py("x = 1", "def f(a):", "    b = a", "    return b", "y = 2")}))
        self.assertEqual([(r["function"], r["line"], r["physical_lines"]) for r in rows(out / "function-complexity.csv")], [("f", "2", "3")])


class SmellTest(RepoTestCase):
    def smells(self, files: dict[str, str]) -> dict:
        return measured(self.repo(files))[0]["services"]["engine"]["smells"]

    def test_a_hub_has_both_fan_in_and_fan_out_at_the_thresholds(self) -> None:
        self.assertEqual(self.smells(hub_files(8, 6))["hub_like"], ["gen2/hub.py"])   # exactly 8 and 6: flagged
        self.assertEqual(self.smells(hub_files(9, 7))["hub_like"], ["gen2/hub.py"])

    def test_one_below_either_threshold_is_not_a_hub(self) -> None:
        self.assertEqual(self.smells(hub_files(7, 6))["hub_like"], [])
        self.assertEqual(self.smells(hub_files(8, 5))["hub_like"], [])
        self.assertEqual(self.smells(hub_files(20, 0))["hub_like"], [])   # a foundation everyone imports is not a hub
        self.assertEqual(self.smells(hub_files(0, 12))["hub_like"], [])   # nor is an entry point that imports everything

    def test_a_stable_module_depending_on_a_much_less_stable_one_is_flagged(self) -> None:
        # A: fan-in 8, fan-out 1 -> 1/9 = 0.111; B: fan-in 1 (A), fan-out 3 -> 3/4 = 0.75; the gap is far over 0.1
        self.assertEqual(self.smells(unstable_files(8, 0, 0, 3))["unstable_dependency"], ["gen2/a.py->gen2/b.py"])

    def test_the_gap_of_exactly_ten_points_is_flagged_and_less_is_not(self) -> None:
        # A: fan-in 9, fan-out 1 -> 0.1; B: fan-in 4 (A + 3), fan-out 1 -> 1/5 = 0.2 : gap exactly 0.1 -> flagged
        self.assertEqual(self.smells(unstable_files(9, 0, 3, 1))["unstable_dependency"], ["gen2/a.py->gen2/b.py"])
        # B: fan-in 5 (A + 4), fan-out 1 -> 1/6 = 0.1667: gap 0.0667 -> not flagged
        self.assertEqual(self.smells(unstable_files(9, 0, 4, 1))["unstable_dependency"], [])

    def test_stable_means_instability_at_most_thirty_percent(self) -> None:
        # A: fan-in 7, fan-out 3 (B and two leaves) -> 0.3 exactly: stable; B: fan-in 1, fan-out 3 -> 0.75
        self.assertEqual(self.smells(unstable_files(7, 2, 0, 3))["unstable_dependency"], ["gen2/a.py->gen2/b.py"])
        # A: fan-in 6, fan-out 3 -> 0.333: not stable enough, so its dependency on B is not this smell
        self.assertEqual(self.smells(unstable_files(6, 2, 0, 3))["unstable_dependency"], [])

    def test_an_unstable_module_depending_on_a_more_unstable_one_is_not_this_smell(self) -> None:
        # A: fan-in 0, fan-out 1 -> 1.0, B: fan-in 1, fan-out 3 -> 0.75
        self.assertEqual(self.smells(unstable_files(0, 0, 0, 3))["unstable_dependency"], [])

    def test_a_god_component_is_big_and_imported_by_many_components(self) -> None:
        self.assertEqual(self.smells(component_files(3000, 5))["god_component"], ["gen2.big"])   # exactly 3,000 lines and 5 importing components
        self.assertEqual(self.smells(component_files(4000, 8))["god_component"], ["gen2.big"])

    def test_one_below_either_threshold_is_not_a_god_component(self) -> None:
        self.assertEqual(self.smells(component_files(2999, 5))["god_component"], [])
        self.assertEqual(self.smells(component_files(3000, 4))["god_component"], [])

    def test_components_are_counted_not_files_importing_them(self) -> None:
        files = {"gen2/big/m.py": padding(3000)} | {f"gen2/user/u{i}.py": py("import gen2.big.m") for i in range(9)}  # nine files, one component
        self.assertEqual(self.smells(files)["god_component"], [])

    def test_the_functions_over_the_thresholds_are_the_offenders(self) -> None:
        offenders = lambda src: measured(self.repo({"gen2/m.py": src}))[0]["services"]["engine"]["functions"]["offenders"]
        self.assertEqual(offenders(with_branches(19)), {})                                  # cyclomatic 20: at the limit, not over it
        self.assertEqual(list(offenders(with_branches(20))), ["gen2/m.py::f"])             # 21: over
        # cognitive 31, cyclomatic only 1 + 6: six `if`s each nested one deeper than the last: 1 + 2 + 3 + 4 + 5 + 6 = 21 -> add a seventh for 28, an eighth for 36
        nest = lambda depth: py("def g(a):", *(f"{'    ' * (i + 1)}if a:" for i in range(depth)), f"{'    ' * (depth + 1)}pass")
        self.assertEqual(offenders(nest(7)), {})                                       # cognitive 1+...+7 = 28 (<= 30)
        self.assertEqual(list(offenders(nest(8))), ["gen2/m.py::g"])                   # 36 (> 30), cyclomatic 9


class HistoryTest(RepoTestCase):
    """The git-history report: commits, churn (added + deleted), files that change together."""

    def history(self) -> Repo:
        a_v1 = py("def a(x):", "    if x:", "        return 1", "    return 0")                       # 4 lines, cyclomatic 2
        a_v2 = py("def a(x):", "    if x and x > 1:", "        return 1", "    return 0", "# note")  # 1 line replaced, 1 added: 2 + 1
        repo = self.repo({}, commit=False)
        repo.write({"gen2/a.py": a_v1, "gen2/b.py": "b1 = 1\nb2 = 2\n", "gen2/old.py": "o = 1\n"}, date="2026-09-20T10:00:00+00:00")  # before the gen-2 era
        repo.write({"gen2/a.py": a_v2, "gen2/b.py": "b1 = 1\nb2 = 2\nb3 = 3\n", "gen2/old.py": "o = 2\n"}, date="2026-09-26T10:00:00+00:00")
        repo.write({"gen2/a.py": a_v2 + "# again\n"}, date="2026-09-27T10:00:00+00:00")
        repo.write({"gen2/old.py": None, "gen2/tests/test_a.py": "t = 1\n"}, date="2026-09-28T10:00:00+00:00")  # old.py leaves production; a test file is never counted
        return repo

    def test_commits_churn_and_the_hotspot_score_per_file(self) -> None:
        repo = self.history()
        out = Path(tempfile.mkdtemp(dir=repo.root.parent))
        done = repo.run("hotspots", str(out))
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        full = {r["file"]: r for r in rows(out / "change-hotspots.csv")}
        # a.py: three commits; churn: 4 added; then 2 added + 1 deleted ("if" line replaced, "# note" added); then 1 added = 4 + 3 + 1 = 8; highest function cyclomatic 3
        self.assertEqual({k: (v["commits"], v["added_plus_deleted"], v["max_function_cc"], v["churn_times_cc"]) for k, v in full.items()},
                         {"gen2/a.py": ("3", "8", "3", "24"), "gen2/b.py": ("2", "3", "0", "0")})   # b.py: 2 added, then 1 added
        self.assertNotIn("gen2/old.py", full)   # not a current production file
        self.assertEqual(next(iter(full)), "gen2/a.py")   # ranked by churn x complexity
        era = {r["file"]: r for r in rows(out / "change-hotspots-gen2-era.csv")}
        # from 2026-09-25: a.py in the second and third commits (3 + 1 = 4), b.py in the second (1)
        self.assertEqual({k: (v["commits"], v["added_plus_deleted"]) for k, v in era.items()}, {"gen2/a.py": ("2", "4"), "gen2/b.py": ("1", "1")})

    def test_files_that_change_together_by_joint_commits_and_jaccard(self) -> None:
        repo = self.history()
        out = Path(tempfile.mkdtemp(dir=repo.root.parent))
        self.assertEqual(repo.run("hotspots", str(out)).returncode, 0)
        pair = rows(out / "change-coupling.csv")
        self.assertEqual([(r["file_a"], r["file_b"], r["joint_commits"], r["a_commits"], r["b_commits"]) for r in pair], [("gen2/a.py", "gen2/b.py", "2", "3", "2")])
        # Jaccard 2 / (3 + 2 - 2) = 0.6667; P(b | a) = 2/3; P(a | b) = 2/2
        self.assertEqual((pair[0]["jaccard"], pair[0]["p_b_given_a"], pair[0]["p_a_given_b"]), ("0.6667", "0.6667", "1.0"))
        era = rows(out / "change-coupling-gen2-era.csv")
        self.assertEqual([(r["joint_commits"], r["a_commits"], r["b_commits"], r["jaccard"]) for r in era], [("1", "2", "1", "0.5")])   # 1 / (2 + 1 - 1)

    def test_the_check_prints_the_history_but_it_never_changes_the_exit_status(self) -> None:
        repo = self.history()
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        done = repo.run("check")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertIn("change hotspots since 2026-09-25", done.stdout)
        self.assertIn("gen2/a.py: 2 commits", done.stdout)

    def test_a_repository_with_no_history_is_checked_without_it(self) -> None:
        repo = self.repo({"gen2/a.py": "x = 1\n"}, commit=False)
        repo.git("add", "-A")   # tracked, never committed: there is no HEAD to read a log from
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        done = repo.run("check")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertIn("history report: unavailable", done.stdout)


class DocumentedDefinitionsTest(unittest.TestCase):
    def test_the_tool_documents_every_definition_it_measures(self) -> None:
        """Task 2q-a asks that the definitions be documented: each measure the tool computes has its entry in the docstring."""
        text = fx.TOOL.read_text(encoding="utf-8")
        for term in ("Propagation cost", "Instability", "Cyclomatic proxy", "Cognitive proxy", "Hub-like file", "Unstable dependency", "God component",
                     "Implicit collaboration", "Components.", "Cycles."):
            with self.subTest(term=term):
                self.assertIn(term, text)


if __name__ == "__main__":
    unittest.main()
