"""Black-box tests of the ratchet in `tools/gen2_metrics.py` (task 2q-a; charter
"Architecture metrics": "a baseline is recorded, and any regression fails the
check unless a reviewed, reasoned exemption entry covers it").

What is asserted is the tool's exit status and what it prints, on throwaway git
repositories of literal files (gen2/tests/tool_repo_fixtures.py). The oracle is
the rule in the charter and the tool's docstring: against the baseline a
metric worse, a cycle not inside a baselined one, a self-call pair with more
sites, a new smell, or a new or worse function over the thresholds fails;
anything better passes and is only recorded by an explicit `rebaseline`, which
never loosens; the one way past a regression is a complete, matching, still
needed exemption entry. Numbers are worked out by hand in each test.

What this cannot show: that the baseline recorded for the real repository is
the right one (it is the state at the 2q-a pin, reviewed as a diff), or that
the metrics measure what a reviewer needs (that is test_metrics_measure.py and
Gate D).
"""
from __future__ import annotations

import json
import unittest

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.tool_repo_fixtures import BASELINE, EXEMPTIONS, Repo, component_files, hub_files, py, unstable_files, with_branches

# Engine: init, a -> b, c (4 files, 1 edge; reach: a 1; sum of 1 + reach = 1 + 2 + 1 + 1 = 5 of 4 * 4 = 16 pairs).
# Gateway: init, n -> m (3 files; reach n 1; 1 + 2 + 1 = 4 of 9).
BASE = {
    "gen2/__init__.py": "",
    "gen2/a.py": py("import gen2.b"),
    "gen2/b.py": "v = 1\n",
    "gen2/c.py": "v = 2\n",
    "gateway/research_gateway/__init__.py": "",
    "gateway/research_gateway/m.py": "v = 3\n",
    "gateway/research_gateway/n.py": py("import research_gateway.m"),
}


class RatchetTestCase(unittest.TestCase):
    def baselined(self, files: dict[str, str]) -> Repo:
        repo = Repo(files)
        self.addCleanup(repo.close)
        repo.measured = repo.git("rev-parse", "HEAD").strip()
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        repo.write({BASELINE: (repo.root / BASELINE).read_text()})   # the baseline is committed, as it would be
        return repo

    def check(self, repo: Repo, expect: int = 0):
        done = repo.run("check")
        self.assertEqual(done.returncode, expect, msg=f"{done.stdout}\n{done.stderr}")
        return done


class BaselineFileTest(RatchetTestCase):
    def test_the_first_rebaseline_records_one_and_a_second_changes_nothing(self) -> None:
        repo = self.baselined(BASE)
        first = (repo.root / BASELINE).read_bytes()
        self.assertIn(b'"digest"', first)
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertIn("nothing written", done.stdout)
        self.assertEqual((repo.root / BASELINE).read_bytes(), first)

    def test_the_baseline_records_the_pin_the_gated_numbers_and_the_thresholds(self) -> None:
        repo = self.baselined(BASE)
        baseline = repo.baseline()
        self.assertEqual(baseline["pin"]["commit"], repo.measured)   # the commit that was measured, not the one that carries the baseline
        self.assertRegex(baseline["pin"]["production_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(baseline["services"]["engine"]["propagation_file"], {"reach_pairs": 5, "nodes": 4})   # 5 of 16, worked out above BASE
        self.assertEqual(baseline["services"]["gateway"]["propagation_file"], {"reach_pairs": 4, "nodes": 3})
        self.assertEqual(baseline["thresholds"]["function_cyclomatic"], 20)
        self.assertEqual(baseline["version"], 1)
        self.assertEqual(baseline["cross_service_imports"], [])

    def test_a_clean_tree_passes(self) -> None:
        done = self.check(self.baselined(BASE))
        self.assertIn("gen2-metrics: no regression against the baseline", done.stdout)

    def test_a_missing_baseline_is_a_tool_failure_with_the_remedy(self) -> None:
        repo = Repo(BASE)
        self.addCleanup(repo.close)
        done = repo.run("check")
        self.assertEqual(done.returncode, 2)
        self.assertIn("no baseline", done.stderr)
        self.assertIn("make gen2-metrics-rebaseline", done.stderr)

    def test_a_baseline_edited_by_hand_fails_even_when_the_edit_is_a_loosening_that_would_pass(self) -> None:
        repo = self.baselined(BASE)
        baseline = repo.baseline()
        baseline["services"]["engine"]["propagation_file"]["reach_pairs"] = 16   # a hand edit that would make any regression "pass"
        (repo.root / BASELINE).write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n")
        done = self.check(repo, 2)
        self.assertIn("edited by hand", done.stderr)

    def test_an_unreadable_or_other_version_baseline_is_a_tool_failure(self) -> None:
        repo = self.baselined(BASE)
        fx.rewrite_baseline(repo, lambda b: b.update(version=2))
        self.assertIn("is not version 1", self.check(repo, 2).stderr)
        (repo.root / BASELINE).write_text("{not json")
        self.assertIn("cannot be read", self.check(repo, 2).stderr)

    def test_a_source_that_does_not_parse_is_a_tool_failure(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/c.py": "def (:\n"})
        self.assertIn("gen2/c.py does not parse", self.check(repo, 2).stderr)


class PropagationTest(RatchetTestCase):
    def test_a_higher_propagation_cost_fails_in_the_file_and_component_graphs(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/c.py": py("import gen2.a")})   # c reaches a and b: sum of 1 + reach = 1 + 2 + 1 + 3 = 7 of 16 (was 5 of 16)
        done = self.check(repo, 1)
        self.assertIn("METRICS REGRESSION: propagation_file engine: 0.437500 against a baseline of 0.312500", done.stderr)
        self.assertIn("METRICS REGRESSION: propagation_component engine: 0.437500 against a baseline of 0.312500", done.stderr)
        self.assertNotIn("gateway", done.stderr.split("gen2-metrics:")[0])

    def test_a_gateway_regression_is_named_for_the_gateway_only(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gateway/research_gateway/n.py": py("import research_gateway.m", "import research_gateway")})   # n reaches m and the package: 1 + 1 + 3 = 5 of 9
        done = self.check(repo, 1)
        self.assertIn("propagation_file gateway: 0.555556 against a baseline of 0.444444", done.stderr)
        self.assertNotIn("propagation_file engine", done.stderr)

    def test_a_change_that_leaves_the_graph_alone_is_no_regression(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/a.py": py("import gen2.b", "# only a comment changed")})
        self.check(repo, 0)

    def test_a_lower_cost_passes_says_so_and_names_the_remedy(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/d.py": "v = 4\n"})   # an isolated file: 6 of 25 = 0.24, below 5 of 16 = 0.3125
        done = self.check(repo, 0)
        self.assertIn("improved: propagation_file engine: 0.240000 is below the baseline 0.312500", done.stdout)
        self.assertIn("make gen2-metrics-rebaseline", done.stdout)

    def test_cost_is_compared_without_rounding(self) -> None:
        repo = self.baselined(BASE)
        # the tree is 5 of 16 = 0.3125; a baseline of 312499 of 1000 * 1000 = 0.312499 is lower by one part in a million, which only an
        # unrounded comparison sees as a regression
        fx.rewrite_baseline(repo, lambda b: b["services"]["engine"]["propagation_file"].update(reach_pairs=312499, nodes=1000))
        self.assertIn("propagation_file engine: 0.312500 against a baseline of 0.312499", self.check(repo, 1).stderr)


class CycleTest(RatchetTestCase):
    CYCLE = {"gen2/a.py": py("import gen2.b"), "gen2/b.py": py("import gen2.a"), "gen2/c.py": "v = 1\n", "gen2/d.py": "v = 2\n"}

    def test_a_new_file_cycle_fails_with_its_members(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/b.py": py("import gen2.a")})
        done = self.check(repo, 1)
        self.assertIn("cycle_file engine:gen2/a.py,gen2/b.py: 2 against a baseline of 0", done.stderr)

    def test_a_new_component_cycle_fails_at_component_level(self) -> None:
        files = {"gen2/x/a.py": py("import gen2.y.b"), "gen2/y/b.py": "v = 1\n", "gen2/y/c.py": "v = 2\n", "gen2/x/d.py": "v = 3\n"}
        repo = self.baselined(files)
        repo.write({"gen2/y/c.py": py("import gen2.x.d")})   # gen2.x -> gen2.y -> gen2.x, over files that stay acyclic
        done = self.check(repo, 1)
        self.assertIn("cycle_component engine:gen2.x,gen2.y: 2 against a baseline of 0", done.stderr)
        self.assertNotIn("cycle_file", done.stderr)

    def test_a_baselined_cycle_stays_allowed(self) -> None:
        done = self.check(self.baselined(self.CYCLE))
        self.assertNotIn("regression", done.stderr)

    def test_a_cycle_that_grows_or_a_second_cycle_is_new(self) -> None:
        repo = self.baselined(self.CYCLE)
        repo.write({"gen2/a.py": py("import gen2.b", "import gen2.c"), "gen2/c.py": py("import gen2.a")})   # {a, b, c}: not inside the baselined {a, b}
        self.assertIn("cycle_file engine:gen2/a.py,gen2/b.py,gen2/c.py", self.check(repo, 1).stderr)
        repo.write({"gen2/a.py": py("import gen2.b"), "gen2/c.py": py("import gen2.d"), "gen2/d.py": py("import gen2.c")})   # {c, d} beside {a, b}
        self.assertIn("cycle_file engine:gen2/c.py,gen2/d.py: 2 against a baseline of 0", self.check(repo, 1).stderr)

    def test_a_cycle_that_shrinks_or_disappears_is_an_improvement_and_rebaseline_records_it(self) -> None:
        repo = self.baselined(self.CYCLE)
        repo.write({"gen2/b.py": "v = 3\n"})   # the cycle is gone
        done = self.check(repo, 0)
        self.assertIn("improved: cycle_file engine: the baseline cycle gen2/a.py,gen2/b.py is gone or smaller", done.stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["cycles_file"], [])
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), "gen2/b.py": py("import gen2.a")})   # and it may not come back
        self.assertIn("cycle_file engine:gen2/a.py,gen2/b.py", self.check(repo, 1).stderr)


class CycleShrinkTest(RatchetTestCase):
    def test_a_cycle_that_shrinks_but_remains_is_inside_the_baselined_one(self) -> None:
        # baselined: a <-> b and a <-> c, one set {a, b, c}; then c leaves the cycle: {a, b} is inside the baselined set, and better
        both = {"gen2/a.py": py("import gen2.b", "import gen2.c"), "gen2/b.py": py("import gen2.a"), "gen2/c.py": py("import gen2.a")}
        repo = self.baselined(both)
        repo.write({"gen2/a.py": py("import gen2.b"), "gen2/c.py": "v = 1\n"})
        done = self.check(repo, 0)
        self.assertIn("improved: cycle_file engine: the baseline cycle gen2/a.py,gen2/b.py,gen2/c.py is gone or smaller", done.stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["cycles_file"], [["gen2/a.py", "gen2/b.py"]])


PAIR = "engine:gen2/router/service.py->gen2/router/lifecycle.py"


def family_files(calls: int, extra: bool = False) -> dict[str, str]:
    """Router(Lifecycle[, Status]) in service.py, calling `self.a()` `calls` times (and `self.s()` once with `extra`)."""
    lifecycle = py("class Lifecycle:", "    def a(self):", "        return 1")
    status = py("class Status:", "    def s(self):", "        return 1")
    bases = "Lifecycle, Status" if extra else "Lifecycle"
    service = py("from gen2.router.lifecycle import Lifecycle", *(["from gen2.router.status import Status"] if extra else []), "",
                 f"class Router({bases}):", "    def go(self):", *(["        self.a()"] * calls), *(["        self.s()"] if extra else []), "        return 1")
    return {"gen2/router/__init__.py": "", "gen2/router/lifecycle.py": lifecycle, "gen2/router/status.py": status, "gen2/router/service.py": service}


class CollaborationTest(RatchetTestCase):
    def test_more_cross_file_self_calls_on_a_baselined_pair_fail(self) -> None:
        repo = self.baselined(family_files(2))
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], {"gen2/router/service.py->gen2/router/lifecycle.py": 2})
        self.check(repo, 0)
        repo.write(family_files(3))
        self.assertIn(f"self_calls {PAIR}: 3 against a baseline of 2", self.check(repo, 1).stderr)

    def test_unchanged_self_calls_are_no_regression(self) -> None:
        repo = self.baselined(family_files(2))
        repo.write({"gen2/router/service.py": family_files(2)["gen2/router/service.py"] + "# only a comment changed\n"})
        self.check(repo, 0)

    def test_a_new_directed_pair_fails(self) -> None:
        repo = self.baselined(family_files(2))
        repo.write(family_files(2, extra=True))   # Router now also reaches Status through self.s()
        self.assertIn("self_calls engine:gen2/router/service.py->gen2/router/status.py: 1 against a baseline of 0", self.check(repo, 1).stderr)

    def test_fewer_calls_are_an_improvement_and_the_lower_count_becomes_the_limit(self) -> None:
        repo = self.baselined(family_files(3))
        repo.write(family_files(1))
        done = self.check(repo, 0)
        self.assertIn("improved: self_calls engine:gen2/router/service.py->gen2/router/lifecycle.py: 1 sites, baseline 3", done.stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], {"gen2/router/service.py->gen2/router/lifecycle.py": 1})
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), **family_files(2)})
        self.assertIn(f"self_calls {PAIR}: 2 against a baseline of 1", self.check(repo, 1).stderr)


class SmellTest(RatchetTestCase):
    def test_a_new_hub_fails(self) -> None:
        repo = self.baselined(hub_files(7, 6))   # fan-in 7: one short of the thresholds
        repo.write(hub_files(8, 6))
        self.assertIn("smell_hub_like engine:gen2/hub.py: 1 against a baseline of 0", self.check(repo, 1).stderr)

    def test_a_baselined_hub_stays_allowed_and_leaving_it_is_an_improvement(self) -> None:
        repo = self.baselined(hub_files(8, 6))
        self.check(repo, 0)
        repo.write({"gen2/imp7.py": "v = 1\n"})   # fan-in 7: no longer a hub (the file stays, so the graph's cost falls too)
        self.assertIn("improved: smell_hub_like engine: gen2/hub.py is gone", self.check(repo, 0).stdout)

    def test_a_new_unstable_dependency_fails(self) -> None:
        repo = self.baselined(unstable_files(9, 0, 4, 1))   # A 1/10 = 0.1, B 1/6 = 0.1667: a gap of 0.0667
        repo.write({"gen2/ib3.py": None})                   # B's fan-in 4: 1/5 = 0.2, a gap of exactly 0.1
        self.assertIn("smell_unstable_dependency engine:gen2/a.py->gen2/b.py: 1 against a baseline of 0", self.check(repo, 1).stderr)

    def test_a_new_god_component_fails(self) -> None:
        repo = self.baselined(component_files(3000, 4))
        repo.write({"gen2/user4/u.py": py("import gen2.big.m")})
        self.assertIn("smell_god_component engine:gen2.big: 1 against a baseline of 0", self.check(repo, 1).stderr)


class FunctionTest(RatchetTestCase):
    def source(self, branches: int, asserts: int = 0, name: str = "f") -> str:
        return with_branches(branches, name) + "".join("    assert a\n" for _ in range(asserts))

    def test_a_new_function_over_the_cyclomatic_threshold_fails(self) -> None:
        repo = self.baselined({"gen2/m.py": self.source(19)})   # cyclomatic 20: at the limit
        repo.write({"gen2/n.py": self.source(20)})                # 21: over it
        self.assertIn("function_cyclomatic engine:gen2/n.py::f: 21 against a baseline of limit 20, not an offender", self.check(repo, 1).stderr)

    def test_a_new_function_over_the_cognitive_threshold_fails(self) -> None:
        nest = py("def g(a):", *(f"{'    ' * (i + 1)}if a:" for i in range(8)), f"{'    ' * 9}pass")   # cognitive 36, cyclomatic 9
        repo = self.baselined({"gen2/m.py": "v = 1\n"})
        repo.write({"gen2/m.py": nest})
        done = self.check(repo, 1)
        self.assertIn("function_cognitive engine:gen2/m.py::g: 36 against a baseline of limit 30, not an offender", done.stderr)
        self.assertNotIn("function_cyclomatic", done.stderr)

    def test_a_baselined_offender_may_stay_but_not_grow_in_either_metric(self) -> None:
        repo = self.baselined({"gen2/m.py": self.source(20)})   # cyclomatic 21, cognitive 20: an offender at the baseline
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"], {"gen2/m.py::f": {"cyclomatic": 21, "cognitive": 20}})
        self.check(repo, 0)
        repo.write({"gen2/m.py": self.source(20, asserts=1)})   # an assert adds a branch and no nesting: cyclomatic 22, cognitive 20
        done = self.check(repo, 1)
        self.assertIn("function_cyclomatic engine:gen2/m.py::f: 22 against a baseline of 21", done.stderr)
        self.assertNotIn("function_cognitive", done.stderr)
        repo.write({"gen2/m.py": self.source(20).replace("def f(a):", "def f(a):\n    x = 1 if a else 2")})   # a ternary: +1 cyclomatic, +1 cognitive
        done = self.check(repo, 1)
        self.assertIn("function_cyclomatic engine:gen2/m.py::f: 22", done.stderr)
        self.assertIn("function_cognitive engine:gen2/m.py::f: 21 against a baseline of 20", done.stderr)

    def test_an_offender_that_improves_is_recorded_and_may_not_return(self) -> None:
        repo = self.baselined({"gen2/m.py": self.source(20)})
        repo.write({"gen2/m.py": self.source(19)})   # cyclomatic 20: no longer over the threshold
        self.assertIn("improved: function engine:gen2/m.py::f is no longer over the thresholds", self.check(repo, 0).stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"], {})
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), "gen2/m.py": self.source(20)})
        self.assertIn("function_cyclomatic engine:gen2/m.py::f: 21 against a baseline of limit 20, not an offender", self.check(repo, 1).stderr)

    def test_a_shrinking_offender_lowers_its_baseline_value(self) -> None:
        repo = self.baselined({"gen2/m.py": self.source(22)})   # 23
        repo.write({"gen2/m.py": self.source(20)})                # 21, still over
        self.assertIn("improved: function engine:gen2/m.py::f: 21/20, baseline 23/22", self.check(repo, 0).stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"], {"gen2/m.py::f": {"cyclomatic": 21, "cognitive": 20}})

    def test_two_functions_of_one_qualified_name_are_kept_apart(self) -> None:
        source = self.source(20) + "if True:\n" + "".join("    " + line + "\n" for line in self.source(20).splitlines())
        repo = self.baselined({"gen2/m.py": source})
        self.assertEqual(set(repo.baseline()["services"]["engine"]["functions"]), {"gen2/m.py::f", "gen2/m.py::f#2"})
        grown = self.source(20) + "if True:\n" + "".join("    " + line + "\n" for line in self.source(20, asserts=1).splitlines())
        repo.write({"gen2/m.py": grown})
        self.assertIn("function_cyclomatic engine:gen2/m.py::f#2: 22 against a baseline of 21", self.check(repo, 1).stderr)

    def test_the_thresholds_are_the_baselines_not_the_tools(self) -> None:
        repo = self.baselined({"gen2/m.py": self.source(24)})   # cyclomatic 25 is an offender under the tool's limit of 20
        def loosen(b: dict) -> None:
            b["thresholds"]["function_cyclomatic"] = 30
            b["services"]["engine"]["functions"] = {}
        fx.rewrite_baseline(repo, loosen)
        done = self.check(repo, 0)   # under the baseline's own limit of 30 the function is not one
        self.assertIn("thresholds function_cyclomatic", done.stdout)   # the tool notes its own are tighter

    def test_the_smell_thresholds_are_the_baselines_too(self) -> None:
        repo = self.baselined(hub_files(8, 6))   # a hub at the tool's thresholds (fan-in 8, fan-out 6)
        def stricter(b: dict) -> None:
            b["thresholds"]["hub_fan_in"] = 9    # the baseline was recorded under a hub threshold of 9, where this file is not a hub
            b["services"]["engine"]["smells"]["hub_like"] = []
        fx.rewrite_baseline(repo, stricter)
        self.check(repo, 0)

    def test_rebaseline_adopts_tighter_thresholds_and_the_offenders_they_find_are_not_regressions(self) -> None:
        repo = self.baselined({"gen2/m.py": self.source(24)})   # cyclomatic 25, cognitive 24
        def loosen(b: dict) -> None:
            b["thresholds"]["function_cyclomatic"] = 30
            b["services"]["engine"]["functions"] = {}
        fx.rewrite_baseline(repo, loosen)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        baseline = repo.baseline()
        self.assertEqual(baseline["thresholds"]["function_cyclomatic"], 20)
        self.assertEqual(baseline["services"]["engine"]["functions"], {"gen2/m.py::f": {"cyclomatic": 25, "cognitive": 24}})

    def test_rebaseline_never_loosens_a_threshold_to_the_tools(self) -> None:
        repo = self.baselined({"gen2/m.py": self.source(14)})   # cyclomatic 15: not an offender at 20
        def tighten(b: dict) -> None:
            b["thresholds"]["function_cyclomatic"] = 10
            b["services"]["engine"]["functions"] = {"gen2/m.py::f": {"cyclomatic": 15, "cognitive": 14}}
        fx.rewrite_baseline(repo, tighten)
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["thresholds"]["function_cyclomatic"], 10)
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"], {"gen2/m.py::f": {"cyclomatic": 15, "cognitive": 14}})


class CrossServiceTest(RatchetTestCase):
    def test_an_import_between_the_services_fails(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/a.py": py("import gen2.b", "import research_gateway.m")})
        self.assertIn("cross_service_import repo:gen2/a.py->gateway/research_gateway/m.py: 1 against a baseline of 0", self.check(repo, 1).stderr)


class BaselinedCrossServiceTest(RatchetTestCase):
    def test_a_baselined_import_between_the_services_stays_allowed(self) -> None:
        repo = self.baselined(BASE | {"gen2/c.py": py("import research_gateway.m")})
        self.assertEqual(repo.baseline()["cross_service_imports"], ["gen2/c.py->gateway/research_gateway/m.py"])
        self.check(repo, 0)


class RebaselineTest(RatchetTestCase):
    def test_a_regression_refuses_the_rebaseline_and_leaves_the_file_alone(self) -> None:
        repo = self.baselined(BASE)
        before = (repo.root / BASELINE).read_bytes()
        repo.write({"gen2/c.py": py("import gen2.a")})
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 1)
        self.assertIn("refused", done.stderr)
        self.assertIn("propagation_file engine", done.stderr)
        self.assertEqual((repo.root / BASELINE).read_bytes(), before)

    def test_an_improvement_tightens_the_baseline_and_the_old_level_is_then_a_regression(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/d.py": "v = 4\n"})   # 6 of 25
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertEqual(repo.baseline()["services"]["engine"]["propagation_file"], {"reach_pairs": 6, "nodes": 5})
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), "gen2/d.py": None})   # back to 5 of 16: worse than 6 of 25
        self.assertIn("propagation_file engine: 0.312500 against a baseline of 0.240000", self.check(repo, 1).stderr)

    def test_it_does_not_rewrite_the_baseline_for_a_new_commit_alone(self) -> None:
        repo = self.baselined(BASE)
        before = (repo.root / BASELINE).read_bytes()
        repo.write({"docs/note.md": "a note\n"})   # a commit that touches no measured file
        self.assertIn("nothing written", repo.run("rebaseline").stdout)
        self.assertEqual((repo.root / BASELINE).read_bytes(), before)

    def test_a_regression_covered_by_an_exemption_is_never_recorded(self) -> None:
        files = {"gen2/m.py": with_branches(20)}
        repo = self.baselined(files)
        repo.write({"gen2/m.py": with_branches(20) + "    assert a\n", EXEMPTIONS: exemption("EX-1", limit="22")})
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"]["gen2/m.py::f"]["cyclomatic"], 21)   # the old value stays
        repo.write({EXEMPTIONS: "# no exemptions\n"})
        self.assertIn("function_cyclomatic engine:gen2/m.py::f: 22 against a baseline of 21", self.check(repo, 1).stderr)


EXEMPTION_DEFAULTS = {"metric": "function_cyclomatic", "location": "engine:gen2/m.py::f", "limit": None,
                      "reason": "the phase-3 split is not scheduled before 2q-b closes",
                      "accepted_by": "Astra Gate D #4, gen2-gate-d-4-astra-review.md (2026-10-05)", "removal": "split the function in 2q-b, then delete this entry"}


def exempt_each(*entries: tuple[str, str, str | None]) -> str:
    """One file of entries EX-1.. for (metric, location, limit)."""
    parts = [exemption(f"EX-{n}", metric=m, location=loc, limit=limit) for n, (m, loc, limit) in enumerate(entries, 1)]
    return parts[0] + "".join(more(p) for p in parts[1:])


def exemption(ident: str, **given: str | None) -> str:
    """A well-formed entry with defaults; a field given as None is left out, one given as text replaces the default."""
    fields = EXEMPTION_DEFAULTS | given
    lines = [f"### {ident} - an exemption"]
    lines += [f"- {'accepted by' if key == 'accepted_by' else key}: {value}" for key, value in fields.items() if value is not None]
    return "# Exemptions\n\n" + "\n".join(lines) + "\n"


def more(text: str) -> str:
    """A further entry to append to a file made by `exemption` (its heading line dropped)."""
    return text.split("\n\n", 1)[1]


class ExemptedRegressionsAreNeverRecordedTest(RatchetTestCase):
    """`rebaseline` keeps the old value wherever an exemption covers a regression, so the exemption stays needed until the cause is fixed."""

    def regress_and_rebaseline(self, files: dict[str, str], regression: dict[str, str | None], exemptions: str) -> Repo:
        repo = self.baselined(files)
        repo.write(regression | {EXEMPTIONS: exemptions})
        self.check(repo, 0)                                   # the exemptions cover everything that regressed
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), EXEMPTIONS: "# no exemptions\n"})
        return repo

    def test_a_propagation_regression(self) -> None:
        repo = self.regress_and_rebaseline(BASE, {"gen2/c.py": py("import gen2.a")},
                                           exempt_each(("propagation_file", "engine", "0.4375"), ("propagation_component", "engine", "0.4375")))
        self.assertEqual(repo.baseline()["services"]["engine"]["propagation_file"], {"reach_pairs": 5, "nodes": 4})
        self.assertEqual(repo.baseline()["services"]["engine"]["propagation_component"], {"reach_pairs": 5, "nodes": 4})
        self.assertIn("propagation_file engine: 0.437500 against a baseline of 0.312500", self.check(repo, 1).stderr)

    def test_a_self_call_regression(self) -> None:
        repo = self.regress_and_rebaseline(family_files(2), family_files(3), exempt_each(("self_calls", PAIR, "3")))
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], {"gen2/router/service.py->gen2/router/lifecycle.py": 2})
        self.assertIn("3 against a baseline of 2", self.check(repo, 1).stderr)

    def test_a_cycle_regression(self) -> None:
        files = {"gen2/x/a.py": py("import gen2.y.b"), "gen2/y/b.py": "v = 1\n", "gen2/y/c.py": "v = 2\n", "gen2/x/d.py": "v = 3\n"}
        # c -> d closes gen2.x -> gen2.y -> gen2.x: the file graph goes from 5 of 16 to 6 of 16 (0.375), the component graph from 3 of 4 to 4 of 4
        repo = self.regress_and_rebaseline(files, {"gen2/y/c.py": py("import gen2.x.d")},
                                           exempt_each(("propagation_file", "engine", "0.375"), ("propagation_component", "engine", "1"),
                                                       ("cycle_component", "engine:gen2.x,gen2.y", None)))
        self.assertEqual(repo.baseline()["services"]["engine"]["cycles_component"], [])
        self.assertIn("cycle_component engine:gen2.x,gen2.y: 2 against a baseline of 0", self.check(repo, 1).stderr)

    def test_a_new_function_over_the_threshold(self) -> None:
        repo = self.regress_and_rebaseline({"gen2/m.py": with_branches(20)}, {"gen2/n.py": with_branches(20, "g")},
                                           exempt_each(("function_cyclomatic", "engine:gen2/n.py::g", "21")))
        self.assertEqual(set(repo.baseline()["services"]["engine"]["functions"]), {"gen2/m.py::f"})   # g is not recorded
        self.assertIn("function_cyclomatic engine:gen2/n.py::g: 21 against a baseline of limit 20, not an offender", self.check(repo, 1).stderr)

    def test_a_smell_regression(self) -> None:
        repo = self.regress_and_rebaseline(hub_files(7, 6), hub_files(8, 6), exempt_each(("smell_hub_like", "engine:gen2/hub.py", None)))
        self.assertEqual(repo.baseline()["services"]["engine"]["smells"]["hub_like"], [])
        self.assertIn("smell_hub_like engine:gen2/hub.py", self.check(repo, 1).stderr)

    def test_a_cross_service_import_regression(self) -> None:
        repo = self.regress_and_rebaseline(BASE, {"gen2/c.py": py("import research_gateway.m")},
                                           exempt_each(("cross_service_import", "repo:gen2/c.py->gateway/research_gateway/m.py", None)))
        self.assertEqual(repo.baseline()["cross_service_imports"], [])
        self.assertIn("cross_service_import repo:gen2/c.py->gateway/research_gateway/m.py", self.check(repo, 1).stderr)


class ExemptionTest(RatchetTestCase):
    """The regression: one function's cyclomatic value 21 -> 22 (an assert adds a branch and no nesting), nothing else."""

    LOCATION = "engine:gen2/m.py::f"

    def regressed(self, text: str | None) -> Repo:
        repo = self.baselined({"gen2/m.py": with_branches(20)})
        files: dict[str, str | None] = {"gen2/m.py": with_branches(20) + "    assert a\n"}
        if text is not None:
            files[EXEMPTIONS] = text
        repo.write(files)
        return repo

    def test_without_an_exemption_the_regression_fails(self) -> None:
        self.assertIn("function_cyclomatic engine:gen2/m.py::f: 22 against a baseline of 21", self.check(self.regressed(None), 1).stderr)

    def test_a_complete_matching_entry_lets_the_regression_pass_and_is_reported(self) -> None:
        done = self.check(self.regressed(exemption("EX-1", limit="22")), 0)
        self.assertIn("note: exempted by EX-1: function_cyclomatic engine:gen2/m.py::f: 22 against a baseline of 21", done.stdout)
        self.assertIn("(1 exempted)", done.stdout)

    def test_a_value_beyond_the_limit_is_not_exempt(self) -> None:
        done = self.check(self.regressed(exemption("EX-1", limit="21")), 1)
        self.assertIn("22 against a baseline of 21 (exemption EX-1 accepts up to 21)", done.stderr)

    def test_each_required_field_is_required(self) -> None:
        for field in ("metric", "location", "reason", "accepted_by", "removal"):
            with self.subTest(field=field):
                done = self.check(self.regressed(exemption("EX-1", limit="22", **{field: None})), 1)
                self.assertIn(f"METRICS EXEMPTION PROBLEM: EX-1: field {field} is missing or a placeholder", done.stderr)
                self.assertIn("function_cyclomatic engine:gen2/m.py::f: 22", done.stderr)   # an invalid entry exempts nothing

    def test_a_placeholder_is_not_a_reason(self) -> None:
        for text in ("TODO", "n/a", "tbd", "-", "none"):
            with self.subTest(text=text):
                done = self.check(self.regressed(exemption("EX-1", limit="22", reason=text)), 1)
                self.assertIn("field reason is missing or a placeholder", done.stderr)

    def test_the_acceptance_must_cite_a_review(self) -> None:
        done = self.check(self.regressed(exemption("EX-1", limit="22", accepted_by="the operator said it was fine")), 1)
        self.assertIn("accepted_by must cite the accepting review", done.stderr)
        for cited in ("gen2-gate-d-4-astra-review.md", "Gate D #4", "review of 2026-10-05"):
            with self.subTest(cited=cited):
                self.check(self.regressed(exemption("EX-1", limit="22", accepted_by=cited)), 0)

    def test_the_removal_condition_must_be_a_condition(self) -> None:
        done = self.check(self.regressed(exemption("EX-1", limit="22", removal="later")), 1)
        self.assertIn("removal must state a condition", done.stderr)

    def test_a_numeric_metric_needs_its_limit_and_a_set_metric_takes_none(self) -> None:
        done = self.check(self.regressed(exemption("EX-1")), 1)
        self.assertIn("EX-1: function_cyclomatic is a number, so `limit` (the highest value accepted) is required as an integer", done.stderr)
        done = self.check(self.regressed(exemption("EX-1", limit="twenty-two")), 1)
        self.assertIn("required as an integer", done.stderr)
        repo = self.baselined(hub_files(7, 6))
        repo.write({**hub_files(8, 6), EXEMPTIONS: exemption("EX-1", metric="smell_hub_like", location="engine:gen2/hub.py", limit="1")})
        self.assertIn("smell_hub_like names one instance, so it takes no `limit`", self.check(repo, 1).stderr)

    def test_an_unknown_metric_or_field_is_a_problem(self) -> None:
        done = self.check(self.regressed(exemption("EX-1", metric="function_length", limit="22")), 1)
        self.assertIn("metric 'function_length' is not one of", done.stderr)
        text = exemption("EX-1", limit="22") + "- owner: nobody\n"
        self.assertIn("unknown field 'owner'", self.check(self.regressed(text), 1).stderr)

    def test_a_set_metric_entry_names_the_instance_and_lets_it_pass(self) -> None:
        repo = self.baselined(hub_files(7, 6))
        repo.write({**hub_files(8, 6), EXEMPTIONS: exemption("EX-1", metric="smell_hub_like", location="engine:gen2/hub.py")})
        self.assertIn("exempted by EX-1: smell_hub_like engine:gen2/hub.py", self.check(repo, 0).stdout)

    def test_a_propagation_exemption_takes_a_decimal_limit_and_the_value_must_not_exceed_it(self) -> None:
        repo = self.baselined(BASE)
        both = exemption("EX-1", metric="propagation_file", location="engine", limit="0.4375") + more(exemption("EX-2", metric="propagation_component", location="engine", limit="0.4375"))
        repo.write({"gen2/c.py": py("import gen2.a"), EXEMPTIONS: both})   # 7 of 16 = 0.4375 in both graphs
        self.check(repo, 0)
        short = exemption("EX-1", metric="propagation_file", location="engine", limit="0.43") + more(exemption("EX-2", metric="propagation_component", location="engine", limit="0.4375"))
        repo.write({EXEMPTIONS: short})
        self.assertIn("(exemption EX-1 accepts up to 0.43)", self.check(repo, 1).stderr)

    def test_an_entry_no_regression_needs_is_stale_and_fails(self) -> None:
        repo = self.baselined({"gen2/m.py": with_branches(20)})
        repo.write({EXEMPTIONS: exemption("EX-1", limit="22")})   # the code did not regress
        done = self.check(repo, 1)
        self.assertIn("EX-1: no regression needs this exemption (metric function_cyclomatic, location engine:gen2/m.py::f): remove it", done.stderr)

    def test_an_entry_that_names_the_wrong_location_exempts_nothing_and_is_stale(self) -> None:
        done = self.check(self.regressed(exemption("EX-1", location="engine:gen2/m.py::g", limit="22")), 1)
        self.assertIn("function_cyclomatic engine:gen2/m.py::f: 22 against a baseline of 21", done.stderr)
        self.assertIn("EX-1: no regression needs this exemption", done.stderr)

    def test_two_entries_for_one_regression_are_a_problem(self) -> None:
        both = exemption("EX-1", limit="22") + more(exemption("EX-2", limit="22"))
        self.assertIn("EX-2: duplicates EX-1", self.check(self.regressed(both), 1).stderr)

    def test_an_example_inside_a_fenced_block_is_not_an_entry(self) -> None:
        text = "# Exemptions\n\n```\n" + more(exemption("EX-9", limit="22")) + "```\n"
        done = self.check(self.regressed(text), 1)
        self.assertIn("function_cyclomatic engine:gen2/m.py::f: 22", done.stderr)
        self.assertNotIn("EX-9", done.stderr)

    def test_a_wrapped_value_continues_on_indented_lines(self) -> None:
        # `later` alone is no condition (under fifteen characters); with its continuation line it is one
        text = exemption("EX-1", limit="22", removal="later") + "  then delete this entry after the split\n"
        self.check(self.regressed(text), 0)
        self.check(self.regressed(exemption("EX-1", limit="22", removal="later")), 1)

    def test_a_wrapped_reason_is_one_value_too(self) -> None:
        text = exemption("EX-1", limit="22", reason="the split is not scheduled").replace("scheduled", "scheduled\n  before 2q-b closes")
        self.assertIn("  before 2q-b closes", text)
        self.check(self.regressed(text), 0)

    def test_the_exemption_file_is_optional(self) -> None:
        self.check(self.baselined(BASE), 0)


if __name__ == "__main__":
    unittest.main()
