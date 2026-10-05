"""Black-box tests of the implicit-collaboration inventory of `tools/gen2_metrics.py`
(task 2q-a-repair F1; Astra's 2q-a review: the inventory resolved only a bare
class name or one attribute on a simple module alias, so rewriting the
Router's six bases as fully qualified names, which changes neither the
import graph nor the runtime method resolution order, took the measured 132
sites and 19 file pairs to zero, and `rebaseline` then recorded the zero).

The rules under test:
  * a base is resolved over the supported import and class surface of the
    source contract (bare names, aliases, `import a.b`, `import a.b as x`,
    `from a import b`, relative imports, explicit re-exports through packages,
    nested classes), to the class it names;
  * a method resolves through Python's C3 linearization, not a depth-first
    walk, so a diamond dispatches the way the interpreter does;
  * a call site is counted once however many families contain it, by
    (site, defining file);
  * a base the contract cannot make certain (a name a measured module does not
    define, a first-party module outside the inventory, a call, an alias, a
    module, a competing or conditional binding, a project base in the other
    service, an inconsistent hierarchy) is REFUSED before anything is measured:
    exit 1 with a diagnostic naming file, line, construct and remediation. It
    is never read as "no collaboration", and nothing classifies it (task
    2q-a-repair-3: the repair-2 classification is withdrawn).

Every expectation is worked out by hand from the fixture's text. The diamond,
the qualified bases, the explicit re-exports, the same-file intermediates and
the closures that capture the receiver are also run by the interpreter (the
fixture package imported in a fresh process) so that no expectation rests on
the tool or on a reading of the MRO rules. What this cannot show: that the
contract's surface is the whole of Python (it is a stated surface, and what
lies outside it is refused, not guessed).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from gen2.tests import children, tool_repo_fixtures as fx
from gen2.tests.test_metrics_measure import RepoTestCase, measured
from gen2.tests.test_metrics_ratchet import RatchetTestCase
from gen2.tests.tool_repo_fixtures import BASELINE, Repo, py

PAIR = {"gen2/p/use.py->gen2/p/base.py": 1}
BASE = py("class Base:", "    def f(self):", "        return 1")


def use(*head: str, bases: str = "Base") -> str:
    """use.py: Child(<bases>), one method whose one call is `self.f()`, defined in base.py."""
    return py(*head, "", f"class Child({bases}):", "    def g(self):", "        return self.f()")


def tree(use_text: str, **more: str) -> dict[str, str]:
    return {"gen2/p/__init__.py": "", "gen2/p/base.py": BASE, "gen2/p/use.py": use_text} | more


def calls(repo: Repo) -> dict:
    return measured(repo)[0]["services"]["engine"]["self_calls"]


def refusals(files: dict[str, str]) -> list[dict]:
    """The contract's diagnostics for a fixture (the stage on its own, as a child), for the fixture whose point is that it is refused."""
    repo = Repo(files)
    try:
        done = repo.run("--json", tool=fx.CONTRACT_TOOL)
        assert done.returncode == 1, done.stderr
        return json.loads(done.stdout)["diagnostics"]
    finally:
        repo.close()


class CollaborationCase(RepoTestCase):
    def inventory(self, files: dict[str, str]) -> dict:
        return calls(self.repo(files))


class SupportedSurfaceTest(CollaborationCase):
    """Each spelling of the one base is one call site from use.py into base.py."""

    SPELLINGS = {   # name -> (the lines that bring Base into scope, the base expression)
        "bare name": (("from gen2.p.base import Base",), "Base"),
        "aliased name": (("from gen2.p.base import Base as B",), "B"),
        "aliased module": (("import gen2.p.base as pb",), "pb.Base"),
        "fully qualified": (("import gen2.p.base",), "gen2.p.base.Base"),
        "module imported from its package": (("from gen2.p import base",), "base.Base"),
        "module imported from its package, aliased": (("from gen2.p import base as pb",), "pb.Base"),
        "relative name": (("from .base import Base",), "Base"),
        "relative module": (("from . import base",), "base.Base"),
    }

    def test_every_spelling_of_a_base_is_resolved_to_the_class(self) -> None:
        for name, (head, bases) in self.SPELLINGS.items():
            with self.subTest(spelling=name):
                found = self.inventory(tree(use(*head, bases=bases)))
                self.assertEqual((found["pairs"], found["sites"], found.get("unresolved", {})), (PAIR, 1, {}))

    def test_the_spelling_changes_nothing_else(self) -> None:
        """The same class under different spellings has the same family, so a rewrite of the base expression cannot move the measure."""
        seen = {name: self.inventory(tree(use(*head, bases=bases)))["families"] for name, (head, bases) in self.SPELLINGS.items()}
        self.assertEqual(len({str(v) for v in seen.values()}), 1, msg=seen)

    def test_a_reexport_through_a_package_is_followed(self) -> None:
        cases = {
            "from-import of the re-exported name": ({"gen2/p/__init__.py": py("from .base import Base")}, ("from gen2.p import Base",), "Base"),
            "the package attribute": ({"gen2/p/__init__.py": py("from .base import Base")}, ("import gen2.p",), "gen2.p.Base"),
            "the package imported from its parent": ({"gen2/p/__init__.py": py("from .base import Base")}, ("from gen2 import p",), "p.Base"),
            "a renamed re-export": ({"gen2/p/__init__.py": py("from .base import Base as Public")}, ("from gen2.p import Public",), "Public"),
            "a re-export of a re-export": ({"gen2/p/__init__.py": py("from gen2.p.mid import Public"), "gen2/p/mid.py": py("from gen2.p.base import Base as Public")},
                                           ("from gen2.p import Public",), "Public"),
            "a re-exported module": ({"gen2/q/__init__.py": py("from gen2.p import base")}, ("from gen2.q import base",), "base.Base"),
        }
        for name, (extra, head, bases) in cases.items():
            with self.subTest(case=name):
                found = self.inventory(tree(use(*head, bases=bases), **extra))
                self.assertEqual((found["pairs"], found["sites"], found.get("unresolved", {})), (PAIR, 1, {}))

    def test_a_nested_class_is_named_through_its_outer_class(self) -> None:
        base = py("class Outer:", "    class Inner:", "        def f(self):", "            return 1")
        found = self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": use("from gen2.p.base import Outer", bases="Outer.Inner")})
        self.assertEqual((found["pairs"], found.get("unresolved", {})), (PAIR, {}))

    def test_a_base_in_the_same_file_is_no_family_and_no_failure(self) -> None:
        found = self.inventory({"gen2/p/use.py": py("class Base:", "    def f(self):", "        return 1", "class Child(Base):", "    def g(self):", "        return self.f()")})
        self.assertEqual((found["sites"], found["families"], found.get("unresolved", {})), (0, {}, {}))


class NestedClassTest(CollaborationCase):
    def test_a_nested_class_has_its_own_self(self) -> None:
        text = py("from gen2.p.base import Base", "", "class Child(Base):", "    class Inner:", "        def h(self):", "            return self.f()")   # Inner is no Base: no f of its own
        found = self.inventory({"gen2/p/base.py": BASE, "gen2/p/use.py": text})
        self.assertEqual((found["sites"], found["pairs"]), (0, {}))   # the call is the Inner object's, not the Child's


class SameFileIntermediateTest(CollaborationCase):
    def test_a_class_whose_only_cross_file_ancestor_is_reached_through_a_same_file_base_is_still_a_family(self) -> None:
        text = py("from gen2.p.base import Base", "", "class Mid(Base):", "    def m(self):", "        return self.f()",     # site 1: use.py -> base.py
                  "", "class Leaf(Mid):", "    def k(self):", "        return self.f()")                                # site 2: Leaf's own call, f is Base's
        found = self.inventory({"gen2/p/base.py": BASE, "gen2/p/use.py": text})
        self.assertEqual((found["sites"], found["pairs"]), (2, {"gen2/p/use.py->gen2/p/base.py": 2}))
        # Mid alone sees its own call (1); Leaf sees Mid's and its own (2); the site of Mid.m is one site, not two
        self.assertEqual({k: v["sites"] for k, v in found["families"].items()}, {"Leaf (gen2/p/use.py)": 2, "Mid (gen2/p/use.py)": 1})

    def test_an_override_in_the_same_file_binds_the_calls_of_the_base_to_that_file(self) -> None:
        text = py("from gen2.p.base import Base", "", "class Mid(Base):", "    def f(self):", "        return 2",
                  "", "class Leaf(Mid):", "    def k(self):", "        return self.f()")   # Mid.f is in use.py: not a cross-file call from Leaf
        found = self.inventory({"gen2/p/base.py": py("class Base:", "    def f(self):", "        return 1", "    def run(self):", "        return self.f()"),
                                "gen2/p/use.py": text})
        # Base.run's self.f() reaches Mid.f in use.py under both Mid and Leaf: base.py -> use.py, once
        self.assertEqual(found["pairs"], {"gen2/p/base.py->gen2/p/use.py": 1})


def run_in_the_interpreter(sources: list[str], probe: str) -> subprocess.CompletedProcess:
    """Run the fixture's classes (their gen2 imports dropped) and `probe` in a fresh interpreter: the interpreter's own answer, independent of the tool."""
    text = "\n".join(re.sub(r"^(from gen2\S* import .*|import gen2.*)$", "", source, flags=re.M) for source in sources) + "\n" + probe + "\n"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "fixture.py"
        script.write_text(text, encoding="utf-8")
        return children.python([str(script)], capture_output=True, text=True, timeout=60)


class SameFileIntermediateInterpreterTest(CollaborationCase):
    """The same-file intermediate cases, run by the interpreter: the answer the hand count rests on is Python's, not a reading of the tool."""

    BASE_RUN = py("class Base:", "    def f(self):", "        return 'base'")

    def test_a_leaf_reaches_the_cross_file_base_through_its_same_file_parent(self) -> None:
        text = py("from gen2.p.base import Base", "", "class Mid(Base):", "    def m(self):", "        return self.f()", "", "class Leaf(Mid):", "    def k(self):", "        return self.f()")
        done = run_in_the_interpreter([self.BASE_RUN, text], "print(Leaf().k(), Leaf().m())")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "base base"), msg=done.stderr)   # both calls reach Base.f: two sites into base.py
        found = self.inventory({"gen2/p/base.py": self.BASE_RUN, "gen2/p/use.py": text})
        self.assertEqual(found["pairs"], {"gen2/p/use.py->gen2/p/base.py": 2})

    def test_an_override_in_the_same_file_binds_both_calls_to_that_file(self) -> None:
        text = py("from gen2.p.base import Base", "", "class Mid(Base):", "    def f(self):", "        return 'mid'", "", "class Leaf(Mid):", "    def k(self):", "        return self.f()")
        base = py("class Base:", "    def f(self):", "        return 'base'", "    def run(self):", "        return self.f()")
        done = run_in_the_interpreter([base, text], "print(Leaf().k(), Leaf().run())")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "mid mid"), msg=done.stderr)   # Mid.f is first in the order for Leaf's own call and for Base.run's
        found = self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": text})
        self.assertEqual(found["pairs"], {"gen2/p/base.py->gen2/p/use.py": 1})   # Base.run's call binds to use.py; Leaf.k's call is use.py -> use.py, which is no cross-file pair


class MethodResolutionOrderTest(CollaborationCase):
    A = py("class A:", "    def f(self):", "        return 'A'")
    B = py("from gen2.p.a import A", "", "class B(A):", "    def run(self):", "        return self.f()")
    C = py("from gen2.p.a import A", "", "class C(A):", "    def f(self):", "        return 'C'")
    D = py("from gen2.p.b import B", "from gen2.p.c import C", "", "class D(B, C):", "    pass")

    def files(self) -> dict[str, str]:
        return {"gen2/p/a.py": self.A, "gen2/p/b.py": self.B, "gen2/p/c.py": self.C, "gen2/p/d.py": self.D}

    def test_the_interpreter_dispatches_the_diamond_to_the_second_base(self) -> None:
        done = run_in_the_interpreter([self.A, self.B, self.C, self.D], "import json\nprint(json.dumps({'mro': [c.__name__ for c in D.__mro__], 'b': B().run(), 'd': D().run()}))")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertEqual(json.loads(done.stdout), {"mro": ["D", "B", "C", "A", "object"], "b": "A", "d": "C"})   # the oracle for the next test

    def test_a_diamond_is_resolved_by_c3_not_depth_first(self) -> None:
        found = self.inventory(self.files())
        # B.run's one call site binds to A.f when B is composed alone (b.py -> a.py) and to C.f when D is (b.py -> c.py): once per file.
        # A depth-first walk (D, B, A, C) would bind the site to A under D too and never see c.py.
        self.assertEqual(found["pairs"], {"gen2/p/b.py->gen2/p/a.py": 1, "gen2/p/b.py->gen2/p/c.py": 1})
        self.assertEqual({k: v["pairs"] for k, v in found["families"].items()},
                         {"B (gen2/p/b.py)": {"gen2/p/b.py->gen2/p/a.py": 1}, "D (gen2/p/d.py)": {"gen2/p/b.py->gen2/p/c.py": 1},
                          "C (gen2/p/c.py)": {}})

    def test_the_order_of_the_bases_decides(self) -> None:
        swapped = self.D.replace("class D(B, C)", "class D(C, B)")
        done = run_in_the_interpreter([self.A, self.B, self.C, swapped], "print(D().run())")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "C"), msg=done.stderr)   # C first: C.f is found before A.f, again
        found = self.inventory(self.files() | {"gen2/p/d.py": swapped})
        self.assertEqual(found["families"]["D (gen2/p/d.py)"]["pairs"], {"gen2/p/b.py->gen2/p/c.py": 1})

    def test_an_inconsistent_order_is_refused_not_guessed(self) -> None:
        """class X(A, B) with B(A) cannot be created (TypeError); statically it is a refusal, never a silent zero."""
        files = {"gen2/p/a.py": self.A, "gen2/p/b.py": self.B, "gen2/p/x.py": py("from gen2.p.a import A", "from gen2.p.b import B", "", "class X(A, B):", "    pass")}
        done = run_in_the_interpreter([self.A, self.B, py("class X(A, B):", "    pass")], "")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("TypeError", done.stderr)
        refused = refusals(files)
        self.assertEqual([(d["category"], d["file"], d["line"]) for d in refused], [("SRC-BASE-HIERARCHY", "gen2/p/x.py", 4)])
        self.assertIn("no consistent method resolution order", refused[0]["construct"])


class OverlappingFamiliesTest(CollaborationCase):
    def test_a_site_in_two_families_is_one_site(self) -> None:
        mid = py("from gen2.p.base import Base", "", "class Mid(Base):", "    def m(self):", "        return self.f()")
        leaf = py("from gen2.p.mid import Mid", "", "class Leaf(Mid):", "    pass")
        found = self.inventory({"gen2/p/base.py": BASE, "gen2/p/mid.py": mid, "gen2/p/leaf.py": leaf})
        # one call site in the source; both Mid and Leaf contain it
        self.assertEqual((found["sites"], found["pairs"]), (1, {"gen2/p/mid.py->gen2/p/base.py": 1}))
        self.assertEqual({k: v["sites"] for k, v in found["families"].items()}, {"Leaf (gen2/p/leaf.py)": 1, "Mid (gen2/p/mid.py)": 1})

    def test_two_calls_on_one_line_are_two_sites(self) -> None:
        text = py("from gen2.p.base import Base", "", "class Child(Base):", "    def g(self):", "        return self.f() + self.f()")
        self.assertEqual(self.inventory({"gen2/p/base.py": BASE, "gen2/p/use.py": text})["sites"], 2)


MIXINS = {   # a router in miniature: three mixins and the class that composes them
    "gen2/r/__init__.py": "",
    "gen2/r/a.py": py("class A:", "    def a1(self):", "        self.b1()", "        return self.r1()"),
    "gen2/r/b.py": py("class B:", "    def b1(self):", "        return self.c1()"),
    "gen2/r/c.py": py("class C:", "    def c1(self):", "        self.a1()", "        return self.a1()"),
}
# a1 -> b1 (a.py -> b.py) and r1 (a.py -> r.py); b1 -> c1 (b.py -> c.py); c1 -> a1 twice (c.py -> a.py); r1 -> a1 (r.py -> a.py): six sites, five pairs
MIXIN_PAIRS = {"gen2/r/a.py->gen2/r/b.py": 1, "gen2/r/a.py->gen2/r/r.py": 1, "gen2/r/b.py->gen2/r/c.py": 1, "gen2/r/c.py->gen2/r/a.py": 2, "gen2/r/r.py->gen2/r/a.py": 1}


def router(head: tuple[str, ...], bases: str) -> dict[str, str]:
    return MIXINS | {"gen2/r/r.py": py(*head, "", f"class R({bases}):", "    def r1(self):", "        return self.a1()")}


class RouterInMiniatureTest(CollaborationCase):
    SPELLINGS = {
        "bare names": (("from gen2.r.a import A", "from gen2.r.b import B", "from gen2.r.c import C"), "A, B, C"),
        "fully qualified names": (("import gen2.r.a", "import gen2.r.b", "import gen2.r.c"), "gen2.r.a.A, gen2.r.b.B, gen2.r.c.C"),
        "aliases": (("from gen2.r.a import A as X", "import gen2.r.b as bb", "from gen2.r import c"), "X, bb.B, c.C"),
        "qualified names beside the bare imports": (("from gen2.r.a import A", "from gen2.r.b import B", "from gen2.r.c import C",
                                                     "import gen2.r.a", "import gen2.r.b", "import gen2.r.c"), "gen2.r.a.A, gen2.r.b.B, gen2.r.c.C"),
    }

    def test_the_composed_class_has_the_hand_counted_inventory_however_its_bases_are_written(self) -> None:
        for name, (head, bases) in self.SPELLINGS.items():
            with self.subTest(spelling=name):
                found = self.inventory(router(head, bases))
                self.assertEqual((found["sites"], found["pairs"], found.get("unresolved", {})), (6, MIXIN_PAIRS, {}))

    def test_rewriting_the_bases_is_neither_an_improvement_nor_recorded_by_a_rebaseline(self) -> None:
        """Astra's probe in miniature: the baseline holds the budgets; the qualified spelling is the same code and must leave them alone."""
        bare, qualified = self.SPELLINGS["bare names"], self.SPELLINGS["fully qualified names"]
        repo = Repo(router(*bare))
        self.addCleanup(repo.close)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], MIXIN_PAIRS)
        repo.write(router(*qualified) | {BASELINE: (repo.root / BASELINE).read_text()})
        done = repo.run("check")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.assertNotIn("improved: self_calls", done.stdout)
        self.assertIn("nothing written", repo.run("rebaseline").stdout)
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], MIXIN_PAIRS)


def real_engine_files() -> dict[str, str]:
    tracked = subprocess.run(["git", "-C", str(fx.REPO), "ls-files", "gen2"], capture_output=True, text=True, check=True).stdout.splitlines()
    return {p: (fx.REPO / p).read_text(encoding="utf-8") for p in tracked if p.endswith(".py") and not p.startswith("gen2/tests/") and (fx.REPO / p).is_file()}


class TheRealRouterTest(CollaborationCase):
    """Astra's real-tree probe: the production Router's bases rewritten without changing a line of what runs."""

    def rewritten(self, files: dict[str, str], how: str) -> dict[str, str]:
        text = files["gen2/router/service.py"]
        modules: dict[str, str] = {}
        for match in re.finditer(r"^class (\w+)\(((?:\w+, )*\w+)\):$", text, flags=re.M):   # the class composed of classes imported from the router's own modules
            names = [n.strip() for n in match.group(2).split(",")]
            found = {n: re.search(rf"^from (gen2\.router\.\w+) import (?:[\w, ]*\b)?{n}\b", text, flags=re.M) for n in names}
            if all(found.values()):
                modules = {n: m.group(1) for n, m in found.items()}
                break
        else:
            raise AssertionError("no class in gen2/router/service.py is composed of classes imported by `from gen2.router.<module> import`: update this test with the router")
        if how == "qualified":
            head = "\n".join(f"import {m}" for m in sorted(set(modules.values())))
            bases = ", ".join(f"{modules[n]}.{n}" for n in names)
        else:
            head = "\n".join(f"from {modules[n]} import {n} as {n}_" for n in names)
            bases = ", ".join(f"{n}_" for n in names)
        rewritten = text[:match.start()] + head + "\n\n" + f"class {match.group(1)}({bases}):" + text[match.end():]
        return files | {"gen2/router/service.py": rewritten}

    def test_a_syntax_only_rewrite_of_the_production_routers_bases_leaves_the_inventory_exactly_as_it_was(self) -> None:
        files = real_engine_files()
        before = calls(self.repo(files))
        self.assertGreater(before["sites"], 0, "the production Router no longer has cross-file self-calls: this test has nothing left to protect")
        for how in ("qualified", "aliased"):
            with self.subTest(how=how):
                after = calls(self.repo(self.rewritten(files, how)))
                self.assertEqual((after["sites"], after["pairs"], after.get("unresolved", {})), (before["sites"], before["pairs"], {}))


class RefusedBaseTest(RatchetTestCase):
    """A base the contract cannot make certain is a refusal, not an absence of collaboration, and nothing classifies it."""

    def files(self, bases: str, *head: str) -> dict[str, str]:
        return {"gen2/p/base.py": BASE, "gen2/p/use.py": use(*head, bases=bases)}

    def test_a_base_the_contract_cannot_follow_is_refused_naming_the_class_the_category_and_why(self) -> None:
        cases = {
            "a project module that defines no such name": ("Missing", ("from gen2.p.base import Missing",), "SRC-NAME-UNRESOLVED", "defines no Missing"),
            "a first-party module that is not measured": ("Gone", ("from gen2.p.gone import Gone",), "SRC-NAME-UNRESOLVED", "gen2.p.gone is a first-party module that is not in the production inventory"),
            "a call": ("make_base()", (), "SRC-BASE-SHAPE", "make_base() is not a name or an attribute chain"),
            "a name that is not defined at all": ("Nowhere", (), "SRC-NAME-UNRESOLVED", "Nowhere is neither defined nor imported"),
            "a name bound twice": ("Base", ("from gen2.p.base import Base", "Base = None"), "SRC-BINDING-COMPETING", "Base has competing or conditional bindings"),
            "a module, not a class": ("base", ("from gen2.p import base",), "SRC-BASE-ALIAS", "base names a module, not a class"),
        }
        for name, (bases, head, category, why) in cases.items():
            with self.subTest(case=name):
                repo = self.baselined(self.files("Base", "from gen2.p.base import Base"))
                baseline = (repo.root / BASELINE).read_bytes()
                repo.write(self.files(bases, *head))
                done = repo.run("check")
                self.assertEqual(done.returncode, 1, msg=done.stderr)
                self.assertIn(f"SOURCE REFUSED: gen2/p/use.py:", done.stderr)
                self.assertIn(f": {category}: class Child has the base {bases}: ", done.stderr)
                self.assertIn(why, done.stderr)
                self.assertNotIn("METRICS REGRESSION", done.stderr)   # nothing was measured, so nothing is compared
                self.assertEqual(repo.run("rebaseline").returncode, 1)
                self.assertEqual((repo.root / BASELINE).read_bytes(), baseline)

    def test_control_a_name_a_measured_module_does_not_define_is_refused_with_that_reason(self) -> None:
        """The path through the member lookup that finds no submodule either: a measured module that defines no such name. Alone, so that it is
        the accepted path a mutant of the submodule lookup leaves as it was."""
        refused = refusals(self.files("Missing", "from gen2.p.base import Missing"))
        self.assertEqual([(d["category"], d["file"], d["line"]) for d in refused], [("SRC-NAME-UNRESOLVED", "gen2/p/use.py", 3)])
        self.assertIn("gen2.p.base defines no Missing", refused[0]["construct"])

    def test_a_refused_base_is_not_recorded_by_a_rebaseline_and_never_baselines_a_zero(self) -> None:
        repo = self.baselined({"gen2/p/base.py": BASE, "gen2/p/use.py": use("from gen2.p.base import Base")})
        before = (repo.root / BASELINE).read_bytes()
        repo.write({"gen2/p/use.py": use(bases="Missing")})
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 1)
        self.assertIn("SRC-NAME-UNRESOLVED", done.stderr)
        self.assertEqual((repo.root / BASELINE).read_bytes(), before)
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], PAIR)

    def test_the_syntax_that_erased_the_inventory_is_now_a_resolved_base_and_an_unfollowable_one_is_a_refusal_not_a_zero(self) -> None:
        repo = self.baselined(self.files("Base", "from gen2.p.base import Base"))
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], PAIR)
        repo.write(self.files("gen2.p.base.Base", "import gen2.p.base"))
        self.check(repo, 0)                                        # a different spelling of the same class: nothing changed
        repo.write(self.files("gen2.p.base.Renamed", "import gen2.p.base"))   # the class is no longer there under that name
        done = self.check(repo, 1)
        self.assertIn("SRC-NAME-UNRESOLVED: class Child has the base gen2.p.base.Renamed", done.stderr)
        self.assertIn("gen2.p.base defines no Renamed", done.stderr)

    def test_bases_outside_the_measured_files_are_leaves_outside_project_collaboration(self) -> None:
        text = py("import abc", "import typing", "import unittest", "from typing import Generic, Protocol, TypeVar", "from some_package import Thing", "",
                  "T = TypeVar('T')", "class A(abc.ABC):", "    pass", "class B(Exception):", "    pass", "class C(typing.Generic[T], dict):", "    pass",
                  "class D(Protocol):", "    pass", "class E(Thing):", "    pass", "class F(unittest.TestCase):", "    pass", "class G(object):", "    pass")
        found = calls(self.repo_for({"gen2/p/use.py": text}))
        self.assertEqual((found["sites"], found["families"]), (0, {}))

    def test_a_base_from_the_other_service_is_refused(self) -> None:
        files = {"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/b.py": BASE,
                 "gen2/p/use.py": use("from research_gateway.b import Base")}
        refused = refusals(files)
        self.assertEqual([(d["category"], d["file"]) for d in refused], [("SRC-BASE-HIERARCHY", "gen2/p/use.py")])
        self.assertIn("in the other service", refused[0]["construct"])

    def test_a_classify_entry_is_an_invalid_action_and_cannot_waive_anything(self) -> None:
        from gen2.tests.test_metrics_identity import entry, write_ledger
        repo = self.baselined({"gen2/p/use.py": "class Child: pass\n"})
        write_ledger(repo, entry("classify", metric="unresolved_base", location="engine:gen2/p/use.py::Child(Missing)"))
        done = self.check(repo, 1)
        self.assertIn("invalid action (classification is withdrawn", done.stderr)

    def repo_for(self, files: dict[str, str]) -> Repo:
        repo = Repo(files)
        self.addCleanup(repo.close)
        return repo


class PropertyAndGeneratedMethodTest(CollaborationCase):
    """The effect each recorded transformation has on attribution (the contract's records), against the text and the interpreter."""

    def test_a_property_is_a_data_attribute_so_a_call_of_it_is_no_project_collaboration(self) -> None:
        base = py("class Base:", "    @property", "    def p(self):", "        return lambda: 1")
        use_text = py("from gen2.p.base import Base", "", "class Child(Base):", "    def g(self):", "        return self.p()")
        done = run_in_the_interpreter([base, use_text], "print(Child().g())")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "1"), msg=done.stderr)   # the call is a call of the VALUE the property returned
        found = self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": use_text})
        self.assertEqual((found["sites"], found["pairs"]), (0, {}))
        plain = self.inventory({"gen2/p/base.py": base.replace("    @property\n", ""), "gen2/p/use.py": use_text})
        self.assertEqual(plain["pairs"], PAIR)   # the same code as a plain method is the collaboration the contract counts

    def test_a_property_found_first_hides_a_method_behind_it(self) -> None:
        base = py("class Base:", "    def p(self):", "        return 'base'")
        mid = py("from gen2.p.base import Base", "", "class Mid(Base):", "    @property", "    def p(self):", "        return lambda: 'mid'")
        leaf = py("from gen2.p.mid import Mid", "", "class Leaf(Mid):", "    def g(self):", "        return self.p()")
        done = run_in_the_interpreter([base, mid, leaf], "print(Leaf().g())")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "mid"), msg=done.stderr)
        found = self.inventory({"gen2/p/base.py": base, "gen2/p/mid.py": mid, "gen2/p/leaf.py": leaf})
        self.assertEqual(found["pairs"], {})   # Mid's property is first in the order: the call does not reach Base.p

    def test_a_static_method_is_called_through_self_and_counts(self) -> None:
        base = py("class Base:", "    @staticmethod", "    def s():", "        return 1")
        use_text = py("from gen2.p.base import Base", "", "class Child(Base):", "    def g(self):", "        return self.s()")
        self.assertEqual(run_in_the_interpreter([base, use_text], "print(Child().g())").stdout.strip(), "1")
        self.assertEqual(self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": use_text})["pairs"], {"gen2/p/use.py->gen2/p/base.py": 1})

    def test_a_class_method_has_the_class_for_its_receiver_and_its_calls_are_not_instance_self_calls(self) -> None:
        base = py("class Base:", "    def f(self):", "        return 1", "", "    @classmethod", "    def make(cls):", "        return cls.f")
        use_text = py("from gen2.p.base import Base", "", "class Child(Base):", "    @classmethod", "    def build(cls):", "        return cls.f")
        self.assertEqual(self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": use_text})["sites"], 0)

    def test_the_receiver_is_the_methods_own_first_parameter_not_the_name_self(self) -> None:
        base = py("class Base:", "    def f(this):", "        return 1")
        use_text = py("from gen2.p.base import Base", "", "class Child(Base):", "    def g(this):", "        return this.f()", "", "    def h(self):", "        return self.f()")
        self.assertEqual(run_in_the_interpreter([base, use_text], "print(Child().g(), end='')").stdout, "1")
        found = self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": use_text})
        # h's parameter is `self`, and `self.f()` in h is a call on h's own receiver: both calls are on their receivers, two sites
        self.assertEqual(found["sites"], 2)

    def test_a_dataclass_generates_methods_owned_by_its_own_file(self) -> None:
        base = py("from dataclasses import dataclass", "", "@dataclass", "class Base:", "    x: int = 0")
        use_text = py("from gen2.p.base import Base", "", "class Child(Base):", "    def g(self):", "        return self.__repr__()", "", "    def __repr__(self):", "        return 'child'")
        found = self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": use_text})
        self.assertEqual(found["sites"], 0)   # Child defines __repr__ itself: its own method, first in the order
        no_repr = use_text.split("\n    def __repr__")[0] + "\n"
        done = run_in_the_interpreter([base, no_repr], "print(Child().g())")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "Child(x=0)"), msg=done.stderr)
        self.assertEqual(self.inventory({"gen2/p/base.py": base, "gen2/p/use.py": no_repr})["pairs"], {"gen2/p/use.py->gen2/p/base.py": 1})

    def test_a_closure_that_captures_the_receiver_is_counted_and_a_nested_class_is_not(self) -> None:
        use_text = py("from gen2.p.base import Base", "", "class Child(Base):", "    def g(self):", "        def inner():", "            return self.f()", "        return inner() + (lambda: self.f())()",
                      "", "    def h(self):", "        class Other:", "            def k(self):", "                return self.f()", "        return Other")
        done = run_in_the_interpreter([BASE, use_text], "print(Child().g())")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "2"), msg=done.stderr)
        found = self.inventory({"gen2/p/base.py": BASE, "gen2/p/use.py": use_text})
        self.assertEqual((found["sites"], found["pairs"]), (2, {"gen2/p/use.py->gen2/p/base.py": 2}))   # the closure and the lambda: Other.k's self is another object


if __name__ == "__main__":
    unittest.main()
