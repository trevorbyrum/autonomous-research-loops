"""Black-box tests of the per-file dependency ratchet of `tools/gen2_metrics.py`
(task 2q-a-repair F5; Astra's 2q-a review: the charter lists per-module
fan-in/fan-out and instability among the ratcheted architecture metrics, but
the tool reported them and never gated them, so an import added to a real
engine file passed with edges 60 -> 61, that file's fan-out 2 -> 3 and its
instability 0.5 -> 0.6, and a dependency added together with an unrelated
file passed because the normalised propagation cost fell although the
reachable pairs grew).

The closed-accounting policy requires ledger transitions for missing identities
and new files/edges/reach. Fan-out cannot grow; previously stable targets count
all dependents, including new files. Explicitly admitted development may add
bounded budgets. Instability still depends on its causes and direction. Legacy
numeric tests admit their fixture population explicitly to isolate that guard.

Every number is worked out by hand from the fixture's text (the comment beside
each says how). What this cannot show: that the policy is the only possible
one (it is a stated reading of the charter's measures, not a derived
constant).
"""
from __future__ import annotations

import json

from gen2.tests.test_metrics_collaboration import real_engine_files
from gen2.tests.test_metrics_ratchet import BASE, RatchetTestCase, exempt_each
from gen2.tests.tool_repo_fixtures import BASELINE, EXEMPTIONS, Repo, py, rewrite_baseline


def engine(repo: Repo, key: str) -> dict:
    return repo.baseline()["services"]["engine"][key]


# a -> b -> c, nothing else: reach a {b, c}, b {c}; propagation 6 of 9
CHAIN = {"gen2/p/a.py": py("import gen2.p.b"), "gen2/p/b.py": py("import gen2.p.c"), "gen2/p/c.py": "v = 1\n"}
# c1 -> c2 -> ... -> c6: reach pairs 6 + 5 + 4 + 3 + 2 + 1 = 21 of 36 (0.5833): dense enough that a new file with a few imports LOWERS the propagation cost,
# so that what these tests see is the per-file rules and not the aggregate one
LONG = {f"gen2/c{i}.py": py(f"import gen2.c{i + 1}") if i < 6 else "v = 1\n" for i in range(1, 7)}


def pads(n: int) -> dict[str, str]:
    """n isolated files: they dilute the aggregate cost so that removing a connected file does not raise it."""
    return {f"gen2/pad{i}.py": "v = 0\n" for i in range(n)}


class AstrasProbesTest(RatchetTestCase):
    def test_an_import_of_something_already_reachable_raises_a_fan_out_and_is_a_regression(self) -> None:
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/a.py": py("import gen2.p.b", "import gen2.p.c")})   # a reached c through b already: the propagation cost does not move
        done = self.check(repo, 1)
        self.assertIn("METRICS REGRESSION: fan_out engine:gen2/p/a.py: 2 against a baseline of 1", done.stderr)
        # c has fan-in 1 (b) and fan-out 0: instability 0, stable; a second importer of it is a fan-in rise
        self.assertIn("METRICS REGRESSION: fan_in engine:gen2/p/c.py: 2 against a baseline of 1", done.stderr)
        self.assertNotIn("propagation", done.stderr)
        self.assertNotIn("reach_gained", done.stderr)

    def test_a_dependency_hidden_by_an_unrelated_file_is_counted_in_absolute_reachable_pairs(self) -> None:
        files = {"gen2/p/a.py": py("import gen2.p.b"), "gen2/p/b.py": "v = 1\n", "gen2/p/c.py": "v = 2\n"}   # reach pairs 2 + 1 + 1 = 4 of 9
        repo = self.baselined(files)
        repo.write({"gen2/p/c.py": py("import gen2.p.a"), "gen2/p/independent.py": "v = 3\n"})   # 3 + 2 + 1 + 1 = 7 of 16: the cost FALLS (0.4375 < 0.4444)
        done = self.check(repo, 1)
        self.assertIn("improved: propagation_file engine: 0.437500 is below the baseline 0.444444", done.stdout)
        self.assertIn("METRICS REGRESSION: reach_gained engine: 2 against a baseline of 0", done.stderr)   # c now reaches a and b
        self.assertIn("METRICS REGRESSION: fan_out engine:gen2/p/c.py: 1 against a baseline of 0", done.stderr)

    def test_the_production_engine_with_a_redundant_import_added_to_one_file(self) -> None:
        """Astra's real-tree probe: an import of a module a file already reaches, between two files of the production engine."""
        files = real_engine_files()
        probe = self.baselined(files)
        report = Repo(files)
        self.addCleanup(report.close)
        out = report.root / "out"
        self.assertEqual(report.run("report", str(out)).returncode, 0)
        graph: dict[str, set[str]] = {}
        for source, target, _line in json.loads((out / "import-edges.json").read_text()):   # the tool's edge table; what is reachable is worked out here
            graph.setdefault(source, set()).add(target)

        def reachable(start: str) -> set[str]:
            found, pending = set(), list(graph.get(start, ()))
            while pending:
                node = pending.pop()
                if node not in found:
                    found.add(node)
                    pending.extend(graph.get(node, ()))
            return found - {start}

        module = lambda path: path.removesuffix(".py").replace("/", ".").removesuffix(".__init__")
        candidates = [(a, b) for a in sorted(graph) for b in sorted(reachable(a)) if b not in graph[a] and a.startswith("gen2/router/") and b.startswith(("gen2/router/", "gen2/core/"))]
        self.assertTrue(candidates, "no file of the production router reaches a router or core module it does not import: update this test with the tree")
        a, b = candidates[0]
        probe.write({a: (probe.root / a).read_text(encoding="utf-8") + f"\nimport {module(b)}\n"})
        before = len(graph[a])
        done = self.check(probe, 1)
        self.assertIn(f"METRICS REGRESSION: fan_out engine:{a}: {before + 1} against a baseline of {before}", done.stderr)
        self.assertNotIn("propagation", done.stderr)   # the cost did not move, as Astra found: nothing but the per-file rule sees it


class FanOutTest(RatchetTestCase):
    def test_a_new_file_needs_bounded_admission_and_its_budget_is_then_enforced(self) -> None:
        from gen2.tests.test_metrics_identity import LEDGER
        repo = self.baselined(LONG)
        repo.write({"gen2/n.py": py("import gen2.c5", "import gen2.c6")})
        self.assertIn("engine|file|gen2/n.py", self.check(repo, 1).stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)
        self.assertEqual(repo.run("admit").returncode, 0)
        text = (repo.root / LEDGER).read_text().replace("reason: TODO", "reason: Bounded fixture development admits two imports").replace("task: TODO", "task: 2q-a-repair-2")
        repo.write({LEDGER: text})
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(engine(repo, "fan_out")["gen2/n.py"], 2)
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), LEDGER: (repo.root / LEDGER).read_text(), "gen2/n.py": py("import gen2.c5", "import gen2.c6", "import gen2.c4")})
        self.assertIn("fan_out engine:gen2/n.py: 3 against a baseline of 2", self.check(repo, 1).stderr)

    def test_an_existing_file_importing_a_new_file_takes_on_a_dependency(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/n.py": "v = 9\n", "gen2/c.py": py("import gen2.n")})   # c: 0 -> 1
        self.assertIn("fan_out engine:gen2/c.py: 1 against a baseline of 0", self.check(repo, 1).stderr)

    def test_replacing_one_import_by_another_is_no_rise(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/a.py": py("import gen2.c")})   # a imported b, now imports c: fan-out 1 and 1; reach: a reached b, now reaches c (a new pair)
        done = self.check(repo, 1)
        self.assertNotIn("fan_out", done.stderr)
        self.assertIn("reach_gained engine: 1 against a baseline of 0", done.stderr)   # the pair (a, c); nothing else is wrong with the swap

    def test_fewer_imports_pass_say_so_and_lower_the_ceiling(self) -> None:
        repo = self.baselined(BASE)
        repo.write({"gen2/a.py": "v = 1\n"})   # a no longer imports b: fan-out 0, reach pair (a, b) gone
        from gen2.tests.test_metrics_identity import population
        population(repo)
        done = self.check(repo, 0)
        self.assertIn("improved: dependencies engine: 1 file(s) with a lower fan-out and 0 reachable pair(s) gone", done.stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual((engine(repo, "fan_out")["gen2/a.py"], engine(repo, "reach")["gen2/a.py"]), (0, []))
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), "gen2/a.py": py("import gen2.b")})   # and it may not come back
        from gen2.tests.test_metrics_identity import population
        population(repo)
        self.assertIn("fan_out engine:gen2/a.py: 1 against a baseline of 0", self.check(repo, 1).stderr)

    def test_merging_a_file_into_the_one_it_imports_is_no_rise_for_its_importer(self) -> None:
        files = {"gen2/x.py": py("import gen2.d"), "gen2/d.py": py("import gen2.e"), "gen2/e.py": "v = 1\n"} | pads(20)   # x -> d -> e
        repo = self.baselined(files)
        repo.write({"gen2/d.py": None, "gen2/x.py": py("import gen2.e")})   # d is merged into e; x imports e: x's fan-out 1 -> 1, e's dependents {x} 1 -> 1
        from gen2.tests.test_metrics_identity import population
        population(repo)
        self.check(repo, 0)   # (x, e) was reachable through d: no pair is gained


class FanInTest(RatchetTestCase):
    """x -> m -> t [-> l]: x re-pointed from m to t keeps its fan-out and gives t a second dependent among the files that existed."""

    def swap(self, with_leaf: bool) -> Repo:
        files = {"gen2/x.py": py("import gen2.m"), "gen2/m.py": py("import gen2.t"), "gen2/t.py": py("import gen2.l") if with_leaf else "v = 1\n"}
        repo = self.baselined(files | ({"gen2/l.py": "v = 2\n"} if with_leaf else {}))
        repo.write({"gen2/x.py": py("import gen2.t")})
        return repo

    def test_a_stable_file_gaining_a_dependent_among_the_existing_files_is_a_regression(self) -> None:
        done = self.check(self.swap(False), 1)   # t imports nothing: instability 0, stable; its dependents {m} -> {m, x}
        self.assertIn("fan_in engine:gen2/t.py: 2 against a baseline of 1", done.stderr)
        self.assertNotIn("fan_out", done.stderr)   # x imports one file before and after
        self.assertNotIn("reach_gained", done.stderr)   # x reached t before

    def test_an_unstable_file_gaining_a_dependent_is_not(self) -> None:
        repo = self.swap(True)
        from gen2.tests.test_metrics_identity import population
        population(repo)
        done = self.check(repo, 0)   # t imports l: instability 1/2, above the stable limit of 30%
        self.assertNotIn("fan_in", done.stdout + done.stderr)

    def test_a_new_file_depending_on_a_stable_file_requires_admission(self) -> None:
        repo = self.baselined({"gen2/m.py": py("import gen2.t"), "gen2/t.py": "v = 1\n"})
        repo.write({"gen2/n.py": py("import gen2.t")})
        result = self.check(repo, 1)
        self.assertIn("fan_in engine:gen2/t.py: 2 against a baseline of 1", result.stderr)
        self.assertIn("engine|edge|gen2/n.py->gen2/t.py", result.stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)


class StableLimitTest(RatchetTestCase):
    """t has seven dependents and `leaves` imports of its own; x is then re-pointed from m to t (x's fan-out stays 1, t gains a dependent)."""

    def repointed(self, leaves: int) -> Repo:
        files = ({f"gen2/imp{i}.py": py("import gen2.t") for i in range(7)} | {"gen2/t.py": py(*(f"import gen2.l{i}" for i in range(leaves)))}
                 | {f"gen2/l{i}.py": "v = 1\n" for i in range(leaves)} | {"gen2/x.py": py("import gen2.m"), "gen2/m.py": "v = 2\n"})
        repo = self.baselined(files)
        repo.write({"gen2/x.py": py("import gen2.t")})
        return repo

    def test_exactly_the_stable_limit_is_stable(self) -> None:
        # fan-in 7, fan-out 3: instability 3 / 10 = 0.3, which is the limit and so stable: the eighth dependent is a regression
        self.assertIn("fan_in engine:gen2/t.py: 8 against a baseline of 7", self.check(self.repointed(3), 1).stderr)

    def test_one_import_more_is_not_stable(self) -> None:
        # fan-in 7, fan-out 4: 4 / 11 = 0.364: not stable, so its eighth dependent is not gated by the fan-in rule (x gaining reach of t's leaves still fails)
        done = self.check(self.repointed(4), 1)
        self.assertNotIn("fan_in", done.stderr)
        self.assertIn("reach_gained", done.stderr)


class InstabilityTest(RatchetTestCase):
    def test_instability_rising_because_dependents_left_is_not_a_regression(self) -> None:
        files = {f"gen2/p{i}.py": py("import gen2.m") for i in range(3)} | {"gen2/m.py": py("import gen2.l"), "gen2/l.py": "v = 1\n"}   # m: fan-in 3, fan-out 1 -> 1/4
        repo = self.baselined(files)
        repo.write({"gen2/p1.py": "v = 2\n", "gen2/p2.py": "v = 3\n"})   # m: fan-in 1, fan-out 1 -> 1/2: less stable, and nothing new is coupled
        from gen2.tests.test_metrics_identity import population
        population(repo)
        done = self.check(repo, 0)
        self.assertIn("improved: dependencies engine:", done.stdout)

    def test_instability_falling_because_dependents_arrived_is_not_one_either(self) -> None:
        repo = self.baselined({"gen2/m.py": py("import gen2.l"), "gen2/l.py": "v = 1\n"})   # m: 0 dependents, fan-out 1 -> instability 1
        repo.write({"gen2/n.py": py("import gen2.m")})
        from gen2.tests.test_metrics_identity import population
        population(repo)
        self.check(repo, 0)


class RecordingTest(RatchetTestCase):
    def test_an_exempted_rise_is_never_recorded(self) -> None:
        repo = self.baselined(BASE)
        both = exempt_each(("propagation_file", "engine", "0.4375"), ("propagation_component", "engine", "0.4375"),
                           ("fan_out", "engine:gen2/c.py", "1"), ("reach_gained", "engine", "2"))
        repo.write({"gen2/c.py": py("import gen2.a"), EXEMPTIONS: both})
        from gen2.tests.test_metrics_identity import population
        population(repo)
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual((engine(repo, "fan_out")["gen2/c.py"], engine(repo, "reach")["gen2/c.py"]), (0, ["gen2/a.py", "gen2/b.py"]))   # c -> a stays an exempted regression
        repo.write({EXEMPTIONS: "# no exemptions\n"})
        from gen2.tests.test_metrics_identity import population
        population(repo)
        done = self.check(repo, 1)
        self.assertIn("fan_out engine:gen2/c.py: 1 against a baseline of 0", done.stderr)
        self.assertNotIn("reach_gained", done.stderr)  # explicit reach admissions were folded

    def test_an_exempted_fan_in_rise_is_never_recorded(self) -> None:
        files = {"gen2/x.py": py("import gen2.m"), "gen2/m.py": py("import gen2.t"), "gen2/t.py": "v = 1\n"}   # t is stable: no imports, one dependent
        repo = self.baselined(files)
        repo.write({"gen2/x.py": py("import gen2.t"), EXEMPTIONS: exempt_each(("fan_in", "engine:gen2/t.py", "2"))})
        from gen2.tests.test_metrics_identity import population
        population(repo)
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(engine(repo, "fan_in")["gen2/t.py"], 1)   # x -> t stays an exempted regression
        repo.write({EXEMPTIONS: "# no exemptions\n"})
        from gen2.tests.test_metrics_identity import population
        population(repo)
        self.assertIn("fan_in engine:gen2/t.py: 2 against a baseline of 1", self.check(repo, 1).stderr)

    def test_the_baseline_holds_the_counts_the_reach_and_the_graph(self) -> None:
        repo = self.baselined(CHAIN)
        self.assertEqual(engine(repo, "fan_out"), {"gen2/p/a.py": 1, "gen2/p/b.py": 1, "gen2/p/c.py": 0})
        self.assertEqual(engine(repo, "fan_in"), {"gen2/p/a.py": 0, "gen2/p/b.py": 1, "gen2/p/c.py": 1})
        self.assertEqual(engine(repo, "reach"), {"gen2/p/a.py": ["gen2/p/b.py", "gen2/p/c.py"], "gen2/p/b.py": ["gen2/p/c.py"], "gen2/p/c.py": []})
        self.assertEqual(engine(repo, "graph"), {"gen2/p/a.py": ["gen2/p/b.py"], "gen2/p/b.py": ["gen2/p/c.py"], "gen2/p/c.py": []})


class UpgradeTest(RatchetTestCase):
    """A baseline of version 1 (before this ratchet) is refused by `check` and upgraded by `rebaseline`, which records the graph as it is."""

    def version_one(self, files: dict[str, str]) -> Repo:
        repo = self.baselined(files)

        def old(b: dict) -> None:
            b["version"] = 1
            for service in b["services"].values():
                for key in ("fan_out", "fan_in", "reach"):
                    del service[key]
        rewrite_baseline(repo, old)
        return repo

    def test_check_refuses_it_and_names_the_remedy(self) -> None:
        done = self.check(self.version_one(BASE), 2)
        self.assertIn("is version 1, before the identity ratchet", done.stderr)
        self.assertIn("make gen2-metrics-rebaseline", done.stderr)

    def test_rebaseline_upgrades_it_once(self) -> None:
        repo = self.version_one(BASE)
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertEqual(repo.baseline()["version"], 3)
        self.assertEqual(engine(repo, "fan_out"), {"gen2/__init__.py": 0, "gen2/a.py": 1, "gen2/b.py": 0, "gen2/c.py": 0})
        self.check(repo, 0)
        self.assertIn("nothing written", repo.run("rebaseline").stdout)

    def test_an_upgrade_does_not_forgive_a_regression_of_what_the_old_baseline_held(self) -> None:
        repo = self.version_one(BASE)
        before = (repo.root / BASELINE).read_bytes()
        repo.write({"gen2/c.py": py("import gen2.a")})   # propagation 5 of 16 -> 7 of 16, which version 1 already ratcheted
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 1)
        self.assertIn("identity migration refused", done.stderr)
        self.assertEqual((repo.root / BASELINE).read_bytes(), before)


class DocumentedPolicyTest(RatchetTestCase):
    def test_the_tool_states_the_policy_and_its_reasons(self) -> None:
        from gen2.tests import tool_repo_fixtures as fx
        text = fx.TOOL.read_text(encoding="utf-8")
        for phrase in ("Stable Dependencies Principle", "fan-out", "fan-in", "reach gained", "losing dependents", "blast radius"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase.lower(), text.lower())
