"""Black-box tests of the implicit-collaboration inventory of `tools/gen2_metrics.py`
(task 2q-a-repair F1; Astra's 2q-a review: the inventory resolved only a bare
class name or one attribute on a simple module alias, so rewriting the
Router's six bases as fully qualified names, which changes neither the
import graph nor the runtime method resolution order, took the measured 132
sites and 19 file pairs to zero, and `rebaseline` then recorded the zero).

The rules under test:
  * a base is resolved over the supported import and class surface (bare
    names, aliases, `import a.b`, `import a.b as x`, `from a import b`,
    relative imports, re-exports through packages and star imports, nested
    classes, subscripted generics), to the class it names;
  * a method resolves through Python's C3 linearization, not a depth-first
    walk, so a diamond dispatches the way the interpreter does;
  * a call site is counted once however many families contain it;
  * a base that cannot be followed to a class or to something outside the
    measured files is UNRESOLVED, and an unresolved base fails the check
    unless an exemption classifies it: losing recognition is not an
    improvement.

Every expectation is worked out by hand from the fixture's text. The diamond
is also run by the interpreter (the fixture's classes executed in one
namespace) so that its expectation does not rest on the tool or on a reading
of the MRO rules. What this cannot show: that the surface listed in
`Classes` is the whole of Python (it is a stated surface, and what lies
outside it is reported, not guessed).
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.test_metrics_measure import RepoTestCase, measured
from gen2.tests.test_metrics_ratchet import RatchetTestCase, exemption
from gen2.tests.tool_repo_fixtures import BASELINE, EXEMPTIONS, Repo, py

PAIR = {"gen2/p/use.py->gen2/p/base.py": 1}
BASE = py("class Base:", "    def f(self):", "        return 1")


def use(*head: str, bases: str = "Base") -> str:
    """use.py: Child(<bases>), one method whose one call is `self.f()`, defined in base.py."""
    return py(*head, "", f"class Child({bases}):", "    def g(self):", "        return self.f()")


def tree(use_text: str, **more: str) -> dict[str, str]:
    return {"gen2/p/__init__.py": "", "gen2/p/base.py": BASE, "gen2/p/use.py": use_text} | more


def calls(repo: Repo) -> dict:
    return measured(repo)[0]["services"]["engine"]["self_calls"]


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
        "inside an if": (("import typing", "if typing.TYPE_CHECKING:", "    from gen2.p.base import Base"), "Base"),
        "subscripted": (("from gen2.p.base import Base",), "Base[int]"),
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
            "a star re-export": ({"gen2/p/__init__.py": py("from gen2.p.base import *")}, ("from gen2.p import Base",), "Base"),
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


def run_in_the_interpreter(sources: list[str]) -> dict:
    """Execute the fixture's classes in one namespace, imports dropped: the interpreter's own answer, independent of the tool."""
    namespace: dict = {}
    exec("\n".join(re.sub(r"^(from gen2\S* import .*|import gen2.*)$", "", text, flags=re.M) for text in sources), namespace)   # noqa: S102
    return namespace


class MethodResolutionOrderTest(CollaborationCase):
    A = py("class A:", "    def f(self):", "        return 'A'")
    B = py("from gen2.p.a import A", "", "class B(A):", "    def run(self):", "        return self.f()")
    C = py("from gen2.p.a import A", "", "class C(A):", "    def f(self):", "        return 'C'")
    D = py("from gen2.p.b import B", "from gen2.p.c import C", "", "class D(B, C):", "    pass")

    def files(self) -> dict[str, str]:
        return {"gen2/p/a.py": self.A, "gen2/p/b.py": self.B, "gen2/p/c.py": self.C, "gen2/p/d.py": self.D}

    def test_the_interpreter_dispatches_the_diamond_to_the_second_base(self) -> None:
        namespace = run_in_the_interpreter([self.A, self.B, self.C, self.D])
        self.assertEqual([c.__name__ for c in namespace["D"].__mro__], ["D", "B", "C", "A", "object"])
        self.assertEqual((namespace["B"]().run(), namespace["D"]().run()), ("A", "C"))   # the oracle for the next test

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
        namespace = run_in_the_interpreter([self.A, self.B, self.C, swapped])
        self.assertEqual(namespace["D"]().run(), "C")   # C first: C.f is found before A.f, again
        found = self.inventory(self.files() | {"gen2/p/d.py": swapped})
        self.assertEqual(found["families"]["D (gen2/p/d.py)"]["pairs"], {"gen2/p/b.py->gen2/p/c.py": 1})

    def test_an_inconsistent_order_is_reported_not_guessed(self) -> None:
        """class X(A, B) with B(A) cannot be created (TypeError); statically it is an unresolved family, never a silent zero."""
        files = {"gen2/p/a.py": self.A, "gen2/p/b.py": self.B, "gen2/p/x.py": py("from gen2.p.a import A", "from gen2.p.b import B", "", "class X(A, B):", "    pass")}
        with self.assertRaises(TypeError):
            run_in_the_interpreter([self.A, self.B, py("class X(A, B):", "    pass")])
        found = self.inventory(files)
        self.assertEqual(list(found["unresolved"]), ["gen2/p/x.py::X(A, B)"])
        self.assertIn("no consistent method resolution order", found["unresolved"]["gen2/p/x.py::X(A, B)"])


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


class UnresolvedBaseTest(RatchetTestCase):
    """An unresolved base is a failure, not an absence of collaboration; an exemption is how it is classified."""

    def files(self, bases: str, *head: str) -> dict[str, str]:
        return {"gen2/p/base.py": BASE, "gen2/p/use.py": use(*head, bases=bases)}

    def test_a_base_the_tool_cannot_follow_fails_the_check_naming_the_class_and_why(self) -> None:
        cases = {
            "a project module that defines no such name": ("Missing", ("from gen2.p.base import Missing",), "defines no Missing"),
            "a first-party module that is not measured": ("Gone", ("from gen2.p.gone import Gone",), "gen2.p.gone is not a measured module"),
            "a call": ("make_base()", (), "make_base() is not a name"),
            "a name that is not defined at all": ("Nowhere", (), "Nowhere is neither defined nor imported"),
            "a name bound twice": ("Base", ("from gen2.p.base import Base", "Base = None"), "Base is bound more than once"),
            "a module, not a class": ("base", ("from gen2.p import base",), "is a module, not a class"),
        }
        for name, (bases, head, why) in cases.items():
            with self.subTest(case=name):
                repo = Repo(self.files(bases, *head))
                self.addCleanup(repo.close)
                self.assertEqual(repo.run("rebaseline").returncode, 0)   # the first baseline never holds an unresolved base
                self.assertEqual(self.check(repo, 1).stderr.count("METRICS REGRESSION: unresolved_base"), 1)
                done = repo.run("check")
                self.assertIn(f"unresolved_base engine:gen2/p/use.py::Child({bases}): 1 against a baseline of 0; ", done.stderr)
                self.assertIn(why, done.stderr)

    def test_an_unresolved_base_is_not_recorded_by_a_rebaseline_and_refuses_it_when_new(self) -> None:
        repo = self.baselined({"gen2/p/base.py": BASE, "gen2/p/use.py": use("from gen2.p.base import Base")})
        before = (repo.root / BASELINE).read_bytes()
        repo.write({"gen2/p/use.py": use(bases="Missing")})
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 1)
        self.assertIn("unresolved_base engine:gen2/p/use.py::Child(Missing)", done.stderr)
        self.assertEqual((repo.root / BASELINE).read_bytes(), before)

    def test_the_syntax_that_erased_the_inventory_is_now_a_resolved_base_and_an_unfollowable_one_is_a_failure_not_a_zero(self) -> None:
        repo = self.baselined(self.files("Base", "from gen2.p.base import Base"))
        self.assertEqual(repo.baseline()["services"]["engine"]["self_calls"], PAIR)
        repo.write(self.files("gen2.p.base.Base", "import gen2.p.base"))
        self.check(repo, 0)                                        # a different spelling of the same class: nothing changed
        repo.write(self.files("gen2.p.base.Renamed", "import gen2.p.base"))   # the class is no longer there under that name
        done = self.check(repo, 1)
        self.assertIn("unresolved_base engine:gen2/p/use.py::Child(gen2.p.base.Renamed)", done.stderr)
        self.assertIn("gen2.p.base defines no Renamed", done.stderr)

    def test_an_exemption_classifies_it_and_a_stale_one_fails(self) -> None:
        files = self.files("Missing")
        text = exemption("EX-1", metric="unresolved_base", location="engine:gen2/p/use.py::Child(Missing)", limit=None,
                         reason="a generated base the tool cannot follow, classified as external by the 2q review",
                         removal="resolve the base or remove the class, then delete this entry")
        repo = Repo(files | {EXEMPTIONS: text})
        self.addCleanup(repo.close)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        done = self.check(repo, 0)
        self.assertIn("exempted by EX-1: unresolved_base engine:gen2/p/use.py::Child(Missing)", done.stdout)
        repo.write(self.files("Base", "from gen2.p.base import Base"))   # now it resolves: the exemption is needed by nothing
        self.assertIn("EX-1: no regression needs this exemption", self.check(repo, 1).stderr)

    def test_bases_outside_the_measured_files_are_classified_without_an_exemption(self) -> None:
        text = py("import abc", "import typing", "import unittest", "from typing import Generic, Protocol, TypeVar", "from some_package import Thing", "",
                  "T = TypeVar('T')", "class A(abc.ABC):", "    pass", "class B(Exception):", "    pass", "class C(typing.Generic[T], dict):", "    pass",
                  "class D(Protocol):", "    pass", "class E(Thing):", "    pass", "class F(unittest.TestCase, metaclass=abc.ABCMeta):", "    pass", "class G(object):", "    pass")
        found = calls(self.repo_for({"gen2/p/use.py": text}))
        self.assertEqual((found["sites"], found.get("unresolved", {})), (0, {}))

    def test_a_base_from_the_other_service_is_reported(self) -> None:
        files = {"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/b.py": BASE,
                 "gen2/p/use.py": use("from research_gateway.b import Base")}
        found = calls(self.repo_for(files))
        self.assertEqual(list(found["unresolved"]), ["gen2/p/use.py::Child(Base)"])
        self.assertIn("outside this service", found["unresolved"]["gen2/p/use.py::Child(Base)"])

    def repo_for(self, files: dict[str, str]) -> Repo:
        repo = Repo(files)
        self.addCleanup(repo.close)
        return repo


if __name__ == "__main__":
    unittest.main()
