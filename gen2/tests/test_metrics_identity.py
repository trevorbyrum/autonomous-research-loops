"""Closed-accounting regressions from Astra R1–R4, with literal source oracles.

The negative probes assert refusal on ordinary source edits; controls assert
reviewed transitions preserve budgets and IDs. Runtime controls check Python's
selection independently: where Python's own selection differs from what a
static reading would pick (an assignment replacing a base, a competing re-export,
a conditional class), the source is REFUSED by the supported-source contract
(docs/gen2/SOURCE-CONTRACT.md) instead of guessed (task 2q-a-repair-3). These
fixtures cannot authenticate ledger review claims or establish the predictive
validity of the AST metrics (Gate A/D review).
"""
from __future__ import annotations

from gen2.tests import children
from gen2.tests.test_metrics_collaboration import BASE, calls, real_engine_files, tree, use
from gen2.tests.test_metrics_dependencies import CHAIN
from gen2.tests.test_metrics_offenders import scored
from gen2.tests.test_metrics_ratchet import RatchetTestCase
from gen2.tests.tool_repo_fixtures import BASELINE, Repo, py

LEDGER = "docs/gen2/metrics-ledger.md"


def entry(action, **fields):
    return {"action": action, **fields, "reason": "Explicit fixture transition for task 2q-a-repair-2", "task": "2q-a-repair-2"}


def write_ledger(repo, *fields, commit=True):
    text = "# Test ledger\n" + "".join(f"\n### ML-{i}\n" + "".join(f"- {k}: {v}\n" for k, v in f.items()) for i, f in enumerate(fields, 1))
    repo.write({LEDGER: text}, commit=commit)


def identity(repo, ref):
    return next(k for k, v in repo.baseline()["identities"].items() if v == ref)


def population(repo):
    """Explicitly admit/retire a fixture's population to isolate legacy numeric
    guards. Does not approve any score, fan-in/out or aggregate growth. Tests
    of identity/admission never use this helper to construct their oracle."""
    done = repo.run("admit")
    if done.returncode:
        raise AssertionError(done.stderr)
    text = (repo.root / LEDGER).read_text()
    sections = text.split("\n### ")
    text = sections[0] + "".join("\n### " + s for s in sections[1:] if "- action: admit\n" in s or "- action: retire\n" in s or "- metric: cycle_" in s)
    repo.write({LEDGER: text.replace("reason: TODO", "reason: Fixture population approved to isolate existing numeric guard").replace("task: TODO", "task: 2q-a-repair-2")})


class IdentityTest(RatchetTestCase):
    def test_ordinary_unchanged_source_passes_with_empty_ledger(self):
        repo = self.baselined(CHAIN)
        write_ledger(repo)
        self.check(repo)
        self.assertIn("nothing written", repo.run("rebaseline").stdout)

    def test_rename_and_move_with_crossed_scores_require_mapping_and_compare_both_scores(self):
        for move in (False, True):
            with self.subTest(move=move):
                repo = self.baselined({"gen2/p/a.py": scored(0, 20), "gen2/p/b.py": "v=1\n"})
                dest = "gen2/p/b.py::f" if move else "gen2/p/a.py::g"
                repo.write({"gen2/p/a.py": "v=1\n" if move else scored(7, 0, "g"), **({"gen2/p/b.py": scored(7, 0)} if move else {})})
                self.assertIn("missing", self.check(repo, 1).stderr)
                before = (repo.root / BASELINE).read_bytes()
                self.assertEqual(repo.run("rebaseline").returncode, 1)
                self.assertEqual((repo.root / BASELINE).read_bytes(), before)
                write_ledger(repo, entry("map", identity=identity(repo, "engine|function|gen2/p/a.py::f"), target="engine|function|" + dest))
                self.assertIn(f"function_cognitive engine:{dest}: 28 against a baseline of 0", self.check(repo, 1).stderr)
                self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_mapped_rename_passes_and_keeps_persistent_id_after_folding(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20)})
        ident = identity(repo, "engine|function|gen2/p/a.py::f")
        repo.write({"gen2/p/a.py": scored(0, 19, "g")})
        write_ledger(repo, entry("map", identity=ident, target="engine|function|gen2/p/a.py::g"))
        self.check(repo)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["identities"][ident], "engine|function|gen2/p/a.py::g")
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"]["gen2/p/a.py::g"], {"cyclomatic": 20, "cognitive": 0})
        self.assertNotIn("\n### ML-", (repo.root / LEDGER).read_text())
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), LEDGER: (repo.root / LEDGER).read_text()})
        self.check(repo)

    def test_mapped_file_rename_keeps_every_relation_budget_and_id(self):
        repo = self.baselined(CHAIN)
        registry = dict(repo.baseline()["identities"])
        repo.write({"gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b")})
        write_ledger(repo, *(entry("map", identity=ident, target=ref.replace("gen2/p/a.py", "gen2/p/renamed.py")) for ident, ref in registry.items() if "gen2/p/a.py" in ref))
        self.check(repo)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["identities"], {k: v.replace("gen2/p/a.py", "gen2/p/renamed.py") for k, v in registry.items()})
        self.assertEqual(repo.baseline()["services"]["engine"]["fan_out"]["gen2/p/renamed.py"], 1)

    def test_retirement_passes_and_clears_only_the_absent_obligation(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20)})
        ident = identity(repo, "engine|function|gen2/p/a.py::f")
        repo.write({"gen2/p/a.py": "v=1\n"})
        self.assertIn("missing", self.check(repo, 1).stderr)
        write_ledger(repo, entry("retire", identity=ident))
        self.check(repo)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertNotIn(ident, repo.baseline()["identities"])

    def test_reasonless_admission_fails_even_when_committed(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": "v=1\n"})
        write_ledger(repo, {**entry("admit", target="engine|file|gen2/p/new.py"), "reason": "TODO"})
        self.assertIn("reason missing or placeholder", self.check(repo, 1).stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_admitted_new_file_passes_and_draft_is_idempotent(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": py("import gen2.p.b", "import gen2.p.c")})
        self.assertIn("new budget", self.check(repo, 1).stderr)
        self.assertEqual(repo.run("admit").returncode, 0)
        text = (repo.root / LEDGER).read_text()
        self.assertIn("reason: TODO", text)
        self.assertIn("engine|file|gen2/p/new.py", text)
        self.assertIn("engine|edge|gen2/p/new.py->gen2/p/c.py", text)
        self.assertIn("- metric: fan_in\n- location: engine:gen2/p/c.py\n- limit: 2", text)
        self.assertEqual(repo.run("admit").returncode, 0)
        self.assertEqual((repo.root / LEDGER).read_text(), text)
        self.check(repo, 1)
        repo.write({LEDGER: text.replace("reason: TODO", "reason: Test admits two explicit dependencies").replace("task: TODO", "task: 2q-a-repair-2")})
        self.check(repo)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["fan_out"]["gen2/p/new.py"], 2)
        self.assertEqual(repo.baseline()["services"]["engine"]["fan_in"]["gen2/p/c.py"], 2)
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), LEDGER: (repo.root / LEDGER).read_text()})
        self.check(repo)

    def test_cycle_identities_can_be_mapped_to_the_smaller_cycle(self):
        repo = self.baselined({"gen2/a.py": py("import gen2.b", "import gen2.c"), "gen2/b.py": py("import gen2.a"), "gen2/c.py": py("import gen2.a")})
        old = dict(repo.baseline()["identities"])
        repo.write({"gen2/a.py": py("import gen2.b"), "gen2/c.py": "v=1\n"})
        transitions = []
        for ident, ref in old.items():
            if "|cycle_" in ref:
                transitions.append(entry("map", identity=ident, target=ref.removesuffix(",gen2/c.py").removesuffix(",gen2.c")))
            elif "->" in ref and "gen2/c.py" in ref:
                transitions.append(entry("retire", identity=ident))
        write_ledger(repo, *transitions)
        self.check(repo)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        baseline = repo.baseline()
        self.assertEqual(baseline["services"]["engine"]["cycles_file"], [["gen2/a.py", "gen2/b.py"]])
        for ident, ref in old.items():
            if "|cycle_" in ref:
                self.assertEqual(baseline["identities"][ident], ref.removesuffix(",gen2/c.py").removesuffix(",gen2.c"))

    def test_set_budget_admission_is_required_even_when_all_other_budgets_are_approved(self):
        from gen2.tests.test_metrics_ratchet import BASE as BOTH_SERVICES
        from gen2.tests.tool_repo_fixtures import hub_files
        cases = [
            ("cycle_", {"gen2/a.py": py("import gen2.b"), "gen2/b.py": "v=1\n", "gen2/c.py": "v=1\n"}, {"gen2/b.py": py("import gen2.a")}),
            ("smell_", hub_files(7, 6), hub_files(8, 6)),
            ("cross_service_import", BOTH_SERVICES, {"gen2/c.py": py("import research_gateway.m")}),
        ]
        for kind, before, after in cases:
            with self.subTest(kind=kind):
                repo = self.baselined(before)
                repo.write(after)
                self.assertEqual(repo.run("admit").returncode, 0)
                text = (repo.root / LEDGER).read_text()
                sections = text.split("\n### ")
                text = sections[0] + "".join("\n### " + section for section in sections[1:] if not ("- action: admit\n" in section and "|" + kind in section))
                repo.write({LEDGER: text.replace("reason: TODO", "reason: All other literal fixture budgets explicitly approved").replace("task: TODO", "task: 2q-a-repair-2")})
                result = self.check(repo, 1)
                self.assertIn("admission", result.stderr)
                self.assertIn("|" + kind, result.stderr)
                self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_an_admitted_isolated_file_is_a_positive_control(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": "v=1\n"})
        write_ledger(repo, entry("admit", target="engine|file|gen2/p/new.py"))
        self.check(repo)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["fan_out"]["gen2/p/new.py"], 0)

    def test_invalid_maps_retirements_and_stale_entries_fail_without_mutating_the_baseline(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20)})
        ident = identity(repo, "engine|function|gen2/p/a.py::f")
        before = (repo.root / BASELINE).read_bytes()
        cases = [entry("map", identity=ident, target="malformed"), entry("retire", identity=ident),
                 entry("admit", target="engine|file|gen2/p/a.py"), entry("retire", identity="MI-999999")]
        for fields in cases:
            with self.subTest(fields=fields):
                write_ledger(repo, fields)
                result = self.check(repo, 1)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(repo.run("rebaseline").returncode, 1)
                self.assertEqual((repo.root / BASELINE).read_bytes(), before)

    def test_duplicate_mapping_destinations_fail_closed(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20) + scored(0, 20, "g")})
        repo.write({"gen2/p/a.py": scored(0, 19, "h")})
        write_ledger(repo, *(entry("map", identity=identity(repo, "engine|function|gen2/p/a.py::" + old), target="engine|function|gen2/p/a.py::h") for old in ("f", "g")))
        self.assertIn("two identities map to one", self.check(repo, 1).stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_isolated_new_file_is_unadmitted_without_a_tool_crash(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/isolated.py": "v=1\n"})
        result = self.check(repo, 1)
        self.assertIn("admission engine|file|gen2/p/isolated.py", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_new_reach_needs_admission_even_when_edge_and_numeric_growth_are_approved(self):
        from gen2.tests.test_metrics_ratchet import BASE, exempt_each
        from gen2.tests.tool_repo_fixtures import EXEMPTIONS
        repo = self.baselined(BASE)
        repo.write({"gen2/c.py": py("import gen2.a"), EXEMPTIONS: exempt_each(("propagation_file", "engine", "0.4375"), ("propagation_component", "engine", "0.4375"), ("fan_out", "engine:gen2/c.py", "1"), ("reach_gained", "engine", "2"))})
        write_ledger(repo, entry("admit", target="engine|edge|gen2/c.py->gen2/a.py"))
        self.assertIn("admission engine|reach|gen2/c.py->gen2/b.py", self.check(repo, 1).stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_missing_edge_and_reach_cannot_be_called_improvements(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/a.py": "v=1\n"})
        result = self.check(repo, 1)
        self.assertIn("engine|edge|gen2/p/a.py->gen2/p/b.py: missing", result.stderr)
        self.assertIn("engine|reach|gen2/p/a.py->gen2/p/c.py: missing", result.stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_a_missing_pair_is_accounted_for_by_the_ledger_once_the_source_is_inside_the_contract(self):
        repo = self.baselined(tree(use("from gen2.p.base import Base")))
        repo.write({"gen2/p/use.py": use(bases="object")})   # the same method, no longer a member of the family: the pair is gone, which is not an improvement
        self.assertIn("engine|self_calls|gen2/p/use.py->gen2/p/base.py: missing", self.check(repo, 1).stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_duplicate_and_conditional_nested_classes_are_refused(self):
        for body, category in (("    class Inner: pass\n    class Inner: pass\n", "SRC-DEF-DUPLICATE"), ("    if True:\n        class Inner: pass\n", "SRC-CLASS-CONDITIONAL")):
            repo = self.baselined({"gen2/p/a.py": "class Outer: pass\n"})
            repo.write({"gen2/p/a.py": "class Outer:\n" + body})
            self.assertIn(f"gen2/p/a.py:", self.check(repo, 1).stderr)
            self.assertIn(category, self.check(repo, 1).stderr)
            self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_uncommitted_reasoned_ledger_fails(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": "v=1\n"})
        write_ledger(repo, entry("admit", target="engine|file|gen2/p/new.py"), commit=False)
        self.assertIn("must be committed", self.check(repo, 1).stderr)

    def test_renamed_importer_adding_an_edge_cannot_reset_fan_out(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b", "import gen2.p.c")})
        self.assertIn("missing", self.check(repo, 1).stderr)
        maps = []
        for ident, ref in repo.baseline()["identities"].items():
            if "gen2/p/a.py" in ref:
                maps.append(entry("map", identity=ident, target=ref.replace("gen2/p/a.py", "gen2/p/renamed.py")))
        write_ledger(repo, *maps)
        result = self.check(repo, 1)
        self.assertIn("fan_out engine:gen2/p/renamed.py: 2 against a baseline of 1", result.stderr)
        self.assertIn("engine|edge|gen2/p/renamed.py->gen2/p/c.py", result.stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_a_new_dependent_of_a_stable_target_is_counted(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": py("import gen2.p.c")})
        self.assertIn("fan_in engine:gen2/p/c.py: 2 against a baseline of 1", self.check(repo, 1).stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_real_normalized_module_requires_admission_despite_lower_normalized_cost(self):
        repo = self.baselined(real_engine_files())
        repo.write({"gen2/core/normalized.py": "import gen2.core.canonical\nimport gen2.core.instants\n"})
        result = self.check(repo, 1)
        self.assertIn("engine|file|gen2/core/normalized.py", result.stderr)
        self.assertIn("fan_in engine:gen2/core/canonical.py: 14 against a baseline of 13", result.stderr)
        self.assertIn("fan_in engine:gen2/core/instants.py: 7 against a baseline of 6", result.stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)


class BindingTest(RatchetTestCase):
    """Each form that makes Python select a different class than a static reading is run by the interpreter, and the tool refuses it by category."""

    def runtime(self, repo, code):
        code = "import sys; sys.path.insert(0, '.'); " + code
        result = children.python(["-B", "-c", code], cwd=repo.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def refused(self, repo, *categories):
        done = self.check(repo, 1)
        for category in categories:
            self.assertIn(category, done.stderr)
        self.assertIn("SOURCE REFUSED", done.stderr)
        self.assertNotIn("METRICS REGRESSION", done.stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_class_scope_assignment_cannot_leave_a_stale_nested_class_binding(self):
        source = "from gen2.p.base import Base\nclass Outer:\n    class Inner(Base): pass\nclass Child(Outer.Inner):\n    def g(self): return self.f()\n"
        repo = self.baselined(tree(source, **{"gen2/__init__.py": ""}))
        code = "from gen2.p.use import Child; print(hasattr(Child, 'f'))"
        self.assertEqual(self.runtime(repo, code).strip(), "True")
        repo.write({"gen2/p/use.py": source.replace("    class Inner(Base): pass\n", "    class Inner(Base): pass\n    Inner = object\n")})
        self.assertEqual(self.runtime(repo, code).strip(), "False")
        self.refused(repo, "SRC-DEF-REBOUND")

    def test_header_and_expression_writes_cannot_leave_a_stale_module_binding(self):
        for replacement in ("for Base in (object,): pass\n", "if (Base := object): pass\n",
                            "with __import__('contextlib').nullcontext(object) as Base: pass\n",
                            "match object:\n    case Base: pass\n", "del Base\n"):
            with self.subTest(replacement=replacement):
                source = use("from gen2.p.base import Base")
                repo = self.baselined(tree(source, **{"gen2/__init__.py": ""}))
                changed = source.replace("class Child", replacement + "class Child")
                if replacement == "del Base\n":
                    changed = changed.replace("class Child(Base)", "class Child(object)")
                repo.write({"gen2/p/use.py": changed})
                self.assertEqual(self.runtime(repo, "from gen2.p.use import Child; print(hasattr(Child, 'f'))").strip(), "False")
                if replacement != "del Base\n":
                    self.refused(repo, "SRC-BINDING-COMPETING", "SRC-LOADER-UNINVENTORIED" if "__import__" in replacement else "SRC-BINDING-COMPETING")
                else:
                    self.assertIn("missing", self.check(repo, 1).stderr)   # the source is inside the contract and the pair is gone: the ledger's question
                    self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_a_nested_class_base_uses_its_enclosing_class_namespace(self):
        source = "from gen2.p.base import Base\nclass Outer:\n    from gen2.p.other import Base\n    class Inner(Base):\n        def g(self): return self.f()\n"
        repo = self.baselined(tree(source, **{"gen2/__init__.py": "", "gen2/p/other.py": BASE.replace("return 1", "return 2")}))
        self.assertEqual(self.runtime(repo, "from gen2.p.use import Outer; print(Outer.Inner().g())").strip(), "2")
        self.assertEqual(calls(repo)["pairs"], {"gen2/p/use.py->gen2/p/other.py": 1})
        self.check(repo)
        repo.write({"gen2/p/use.py": source.replace("    from gen2.p.other import Base\n", "    Base = object\n")})
        self.assertEqual(self.runtime(repo, "from gen2.p.use import Outer; print(hasattr(Outer.Inner, 'f'))").strip(), "False")
        self.refused(repo, "SRC-BASE-ALIAS")

    def test_a_function_local_class_base_accounts_for_local_writes_and_parameters(self):
        source = "from gen2.p.base import Base\ndef build():\n    class Child(Base):\n        def g(self): return self.f()\n    return Child\n"
        repo = self.baselined(tree(source, **{"gen2/__init__.py": ""}))
        self.assertEqual(self.runtime(repo, "from gen2.p.use import build; print(build()().g())").strip(), "1")
        self.assertEqual(calls(repo)["pairs"], {"gen2/p/use.py->gen2/p/base.py": 1})
        self.check(repo)
        for changed in (source.replace("def build():", "def build(Base=object):"), source.replace("    class Child", "    Base = object\n    class Child")):
            repo.write({"gen2/p/use.py": changed})
            self.assertEqual(self.runtime(repo, "from gen2.p.use import build; print(hasattr(build(), 'f'))").strip(), "False")
            self.refused(repo, "SRC-BASE-ALIAS")

    def test_conditional_real_router_is_refused_while_the_runtime_mro_is_unchanged(self):
        repo = self.baselined(real_engine_files())
        code = 'from gen2.router.service import Router; print([c.__name__ for c in Router.__mro__]); print(hasattr(Router,"commit_outcome"))'
        before = self.runtime(repo, code)
        path = "gen2/router/service.py"
        original = (repo.root / path).read_text()
        start = original.index("class Router(")
        changed = original[:start] + "if True:\n" + "".join("    " + line if line.strip() else line for line in original[start:].splitlines(keepends=True)) + "\nelse:\n    class Router:\n        pass\n"
        repo.write({path: changed})
        self.assertEqual(self.runtime(repo, code), before)
        self.assertIn("True", before)
        self.refused(repo, "SRC-CLASS-CONDITIONAL", "SRC-DEF-DUPLICATE")

    def test_the_real_routers_method_under_if_true_is_refused_though_python_runs_it_unchanged(self):
        """Gate D #4 R2: only `Router._now` under `if True:` kept the bytecode and the runtime result and took 132 sites to 127 with every check green."""
        repo = self.baselined(real_engine_files())
        path = "gen2/router/service.py"
        original = (repo.root / path).read_text()
        start = original.index("    def _now(self")
        end = original.index("\n    def ", start + 10)
        block = original[start:end]
        changed = original[:start] + "    if True:\n" + "".join("    " + line if line.strip() else line for line in block.splitlines(keepends=True)) + original[end:]
        repo.write({path: changed})
        self.assertEqual(self.runtime(repo, "from gen2.router.service import Router; print(hasattr(Router, '_now'))").strip(), "True")
        self.refused(repo, "SRC-METHOD-CONDITIONAL")

    def test_competing_star_reexports_are_refused_for_both_interpreter_orders(self):
        for prefix, package in (("gen2/", "gen2"), ("gateway/research_gateway/", "research_gateway")):
            files = {prefix + "__init__.py": "", prefix + "p/a.py": BASE.replace("return 1", 'return "a"'), prefix + "p/z.py": BASE.replace("return 1", 'return "z"'),
                     prefix + "p/__init__.py": "from .a import Base\n", prefix + "p/use.py": use(f"from {package}.p import Base")}
            repo = self.baselined(files)
            code = f'import sys; sys.path.insert(0,"gateway"); from {package}.p.use import Child; print(Child().g())'
            for order, selected in (("from .z import *\nfrom .a import *\n", "a"), ("from .a import *\nfrom .z import *\n", "z")):
                repo.write({prefix + "p/__init__.py": order})
                self.assertEqual(self.runtime(repo, code).strip(), selected)   # python's selection changes with the order
                self.refused(repo, "SRC-STAR-IMPORT")

    def test_star_export_visibility_is_refused_whatever_python_exports(self):
        for declaration, exists in (("__all__ = ['Base']\n", True), ("__all__ = []\n", False), ("__all__ = [name for name in globals()]\n", True)):
            files = tree(use("from gen2.p import Base"), **{"gen2/__init__.py": "", "gen2/p/base.py": BASE + declaration, "gen2/p/__init__.py": "from .base import *\n"})
            repo = Repo(files)
            self.addCleanup(repo.close)
            self.assertEqual(self.runtime(repo, "import gen2.p as p; print(hasattr(p, 'Base'))").strip(), str(exists))
            done = repo.run("report", str(repo.root / "out"))
            self.assertEqual(done.returncode, 1)
            self.assertIn("SRC-STAR-IMPORT", done.stderr)
            if "globals" in declaration:
                self.assertIn("SRC-ALL-DYNAMIC", done.stderr)

    def test_an___all___outside_the_module_level_is_refused_and_is_not_a_module_export(self):
        for public, local in ((["Base"], []), ([], ["Base"])):
            for nested in (f"def private():\n    __all__ = {local!r}\n", f"class Private:\n    __all__ = {local!r}\n"):
                with self.subTest(public=public, nested=nested):
                    files = tree(use("from gen2.p import Base"), **{"gen2/__init__.py": "", "gen2/p/base.py": BASE + f"__all__ = {public!r}\n" + nested,
                                 "gen2/p/__init__.py": "from .base import Base\n"})
                    repo = Repo(files)
                    self.addCleanup(repo.close)
                    self.assertEqual(self.runtime(repo, "import gen2.p as p; print(hasattr(p, 'Base'))").strip(), "True")   # explicit re-export: independent of __all__
                    done = repo.run("report", str(repo.root / "out"))
                    self.assertEqual(done.returncode, 1)
                    self.assertIn("SRC-ALL-DYNAMIC", done.stderr)
                    self.assertIn("gen2/p/base.py:", done.stderr)

    def test_unique_reexport_matches_the_interpreter(self):
        repo = self.baselined(tree(use("from gen2.p import Base"), **{"gen2/__init__.py": "", "gen2/p/__init__.py": "from .base import Base\n"}))
        self.assertEqual(self.runtime(repo, "from gen2.p.use import Child; print(Child().g())").strip(), "1")
        self.assertEqual(calls(repo)["pairs"], {"gen2/p/use.py->gen2/p/base.py": 1})
        self.check(repo)

    def test_the_explicit_import_chains_the_contract_supports_match_the_interpreter(self):
        """Qualified bases, explicit re-exports and an aliased import each select the class Python selects."""
        for head, bases in ((("import gen2.p.base",), "gen2.p.base.Base"), (("from gen2.p import base",), "base.Base"), (("from gen2.p.base import Base as B",), "B"),
                            (("from gen2.q import Public",), "Public")):
            with self.subTest(bases=bases):
                files = tree(use(*head, bases=bases), **{"gen2/__init__.py": "", "gen2/q/__init__.py": "from gen2.p.base import Base as Public\n"})
                repo = Repo(files)
                self.addCleanup(repo.close)
                self.assertEqual(self.runtime(repo, "from gen2.p.use import Child; print(Child().g())").strip(), "1")
                self.assertEqual(calls(repo)["pairs"], {"gen2/p/use.py->gen2/p/base.py": 1})
