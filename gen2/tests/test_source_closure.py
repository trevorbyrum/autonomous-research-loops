"""Tests of the CLOSURE of the supported-source contract and of the effective-member model (task 2q-a-repair-4; Astra's 2q-a-repair-3 review F1, F2 and F3).

Three rounds of fixes for individual spellings showed the cause: the guard refused the forms it knew to be bad, and the index trusted everything else. The contract is now closed
(docs/gen2/SOURCE-CONTRACT.md, "Closure"): every construct that binds a name in a module or class namespace, or changes an attribute or member of a measured module or class, is a
recognised form with a recorded effect, and anything else is refused. These tests are of that closure, in three kinds of oracle that do not read the tool's output as the truth:

  * literal fixtures by structural POSITION and KIND of site (gen2/tests/source_closure_fixtures.py): a walrus in each position a header or an expression has, a `global` redirect of
    each kind of binding, each kind of binding in a class body, every kind of store on a module, a class, a namespace's dictionary; the category and the line are written by hand;
  * Astra's own probes (gen2/tests/source_probe_fixtures.py), each with a CONTROL the interpreter runs, so the verdict on the source is checked against what Python does with it;
  * the effective members of a class against Python itself: for every combination of a plain class and the three recorded dataclass forms with a body that defines `__eq__`, `__hash__`
    as a method, `__hash__ = None` or neither, whether the class dictionary ends with no `__hash__`, a `None`, or a function is the interpreter's answer, and the index's member is
    compared with it.

What this cannot show: that the recognised set is the whole of Python (it is closed on purpose; a form outside it is a refusal fixture, not an extension), or that a store through a call
the contract does not name as a producer of a namespace (a function that returns a class) is caught: that is indirection, which the contract excludes.
"""
from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from gen2.tests import children
from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.source_closure_fixtures import CLOSURE_ACCEPTS, CLOSURE_REFUSALS
from gen2.tests.source_contract_fixtures import Fixture
from gen2.tests.source_probe_fixtures import LOADER_CONTROL, LOADER_NAMES, LOCATOR_CONTROL, LOCATOR_DOC, LOCATOR_FILES, LOCATOR_SAYS, PROBES, Probe
from gen2.tests.test_source_contract import SERVICES, ContractCase, package
from gen2.tests.tool_repo_fixtures import Repo, py

LOADER = fx.REPO / "gateway" / "research_gateway" / "adapters" / "__init__.py"


def interpreter(repo: Repo, service: str, code: str) -> str:
    """What Python prints for `code` run in the fixture tree: standard output, then the last line of standard error if it failed."""
    prefix, name = SERVICES[service]
    done = fx.fixture_python(repo.root if service == "engine" else repo.root / "gateway", code.replace("{pkg}", name))
    return (done.stdout + (done.stderr.strip().splitlines()[-1] if done.returncode else "")).strip()


def measured_sites(repo: Repo, service: str) -> int:
    out = repo.root / "report"
    done = repo.run("report", str(out))
    assert done.returncode == 0, done.stderr
    return json.loads((out / "metrics-summary.json").read_text())["services"][service]["self_calls"]["sites"]


class ClosureCase(ContractCase):
    def diagnostics(self, view: dict) -> list[tuple[str, str, int]]:
        return [(d["category"], d["file"], d["line"]) for d in view["diagnostics"]]

    def refuses_each(self, fixtures: list[Fixture]) -> None:
        self.assertTrue(fixtures)
        for fixture in fixtures:
            for service, (prefix, _) in SERVICES.items():
                if fixture.only not in (None, service):
                    continue
                with self.subTest(fixture=fixture.name, service=service):
                    status, view = self.view(self.repo(package(service, fixture.files)))
                    self.assertEqual(status, 1, msg=f"{fixture.name} was not refused")
                    wanted = (fixture.category, prefix + fixture.where[0], fixture.where[1])
                    found = [d for d in view["diagnostics"] if (d["category"], d["file"], d["line"]) == wanted]
                    self.assertTrue(found, msg=f"wanted {wanted}; the diagnostics were {[(d['category'], d['file'], d['line'], d['construct']) for d in view['diagnostics']]}")
                    self.assertIn(fixture.construct, " ".join(d["construct"] for d in found))
                    self.assertTrue(all(d["remediation"].strip() for d in found), msg="a refusal says what to do")


class ClosureRefusalTest(ClosureCase):
    """Each family of refusal fixtures is refused in both services. One test per family (generated below, `test_refuses_<family>`)."""

    def test_every_family_has_fixtures_and_every_fixture_names_a_category_of_the_tool(self) -> None:
        tool = set(self.categories())
        for family, fixtures in CLOSURE_REFUSALS.items():
            self.assertTrue(fixtures, msg=family)
            for fixture in fixtures:
                self.assertIn(fixture.category, tool, msg=f"{family}: {fixture.name}")

    def categories(self) -> list[str]:
        repo = Repo({})
        self.addCleanup(repo.close)
        return list(json.loads(repo.run("--contract", tool=fx.CONTRACT_TOOL, root=False).stdout)["categories"])


def _refusal_test(family: str):
    def test(self) -> None:
        self.refuses_each(CLOSURE_REFUSALS[family])
    test.__name__ = f"test_refuses_{family}"
    test.__doc__ = f"every refusal fixture of the family {family!r}, in both services"
    return test


for _family in CLOSURE_REFUSALS:
    setattr(ClosureRefusalTest, f"test_refuses_{_family}", _refusal_test(_family))


class ClosureAcceptanceTest(ClosureCase):
    """The forms the contract records stay inside it, and the effective members the index records are the ones the text states."""

    def accepts_each(self, fixtures: list[Fixture]) -> None:
        self.assertTrue(fixtures)
        for fixture in fixtures:
            for service, (prefix, _) in SERVICES.items():
                if fixture.only not in (None, service):
                    continue
                with self.subTest(fixture=fixture.name, service=service):
                    status, view = self.view(self.repo(package(service, fixture.files)))
                    self.assertEqual((status, self.diagnostics(view)), (0, []), msg=fixture.name)
                    self.check_expectations(view, prefix, fixture.expect)

    def check_expectations(self, view: dict, prefix: str, expect: dict) -> None:
        full = lambda key: prefix + key if "::" in key else key
        classes = {c["class"]: c for c in view["classes"]}
        functions = {f["key"]: f for f in view["functions"]}
        if "functions" in expect:
            self.assertEqual(sorted(functions), sorted(prefix + k for k in expect["functions"]))
        for key in expect.get("classes", ()):
            self.assertIn(full(key), classes)
        for key, methods in expect.get("methods", {}).items():
            self.assertEqual(classes[full(key)]["methods"], methods)
        for key, family in expect.get("family", {}).items():
            self.assertEqual(classes[full(key)]["family"], [full(member) for member in family])
        for key, members in expect.get("members", {}).items():
            self.assertEqual({name: classes[full(key)]["members"].get(name) for name in members}, members, msg=f"the effective members of {key}")
        for key, names in expect.get("fields", {}).items():
            self.assertEqual(classes[full(key)]["fields"], names)


def _acceptance_test(family: str):
    def test(self) -> None:
        self.accepts_each(CLOSURE_ACCEPTS[family])
    test.__name__ = f"test_accepts_{family}"
    test.__doc__ = f"every accepted fixture of the family {family!r}, in both services"
    return test


for _family in CLOSURE_ACCEPTS:
    setattr(ClosureAcceptanceTest, f"test_accepts_{_family}", _acceptance_test(_family))


# --- the walker's table against the interpreter ----------------------------------------------------------------------------

ABSTRACT = {"AST", "mod", "stmt", "expr", "expr_context", "boolop", "operator", "unaryop", "cmpop", "excepthandler", "pattern", "type_ignore", "type_param", "slice"}
OBSOLETE = {"Num", "Str", "Bytes", "NameConstant", "Ellipsis", "_ast_Ellipsis", "Param", "AugLoad", "AugStore", "ExtSlice", "Index", "Suite"}   # classes a parser no longer produces
EVERY_FORM = py(
    "from __future__ import annotations", "import contextlib, os, sys", "from os import path as p, sep", "from . import sibling", "",
    "@contextlib.contextmanager", "def deco():", "    yield 1", "",
    "def plain(a, /, b=1, *args, c, d=2, **kw) -> int:", "    global G", "    G = 1", "    x = y = 0", "    x += 1", "    z: int = 2", "    w: int", "    del x",
    "    for i, (j, *k) in enumerate([(1, 2, 3)]):", "        if i and not j or k:", "            continue", "        elif i is not j:", "            break", "        else:", "            pass",
    "    else:", "        pass", "    while False:", "        pass", "    with open('f') as fh, open('g'):", "        pass", "    try:", "        raise ValueError('x') from None",
    "    except (KeyError, ValueError) as err:", "        pass", "    except Exception:", "        pass", "    else:", "        pass", "    finally:", "        pass", "    assert x, 'm'",
    "    return (lambda q=1, *r, s, **t: q)(1, s=2)", "",
    "async def coro(items):", "    async for item in items:", "        pass", "    async with items as ctx:", "        pass", "    await items", "    return [m async for m in items]", "",
    "def gen():", "    yield 1", "    yield from range(2)", "    n = yield", "    return n", "",
    "def comps(rows):", "    a = [r for r in rows if r]", "    b = {r for r in rows}", "    c = {r: 1 for r in rows}", "    d = (r for r in rows)", "    e = [(t := r) for r in rows]", "    return a, b, c, d, e", "",
    "def operators(a, b):", "    r = a + b - a * b / a // b % a ** b << a >> b | a & b ^ a @ b", "    s = -a, +a, ~a, not a", "    t = a < b <= a > b >= a == b != a in [b] not in [a]", "    u = a if b else a",
    "    v = (a and b) or a", "    v2 = a is b", "    w = {1: a, **{}}, {1, 2}, [1, *[2]], (3, 4), a[1:2:3], a[1], a.b", "    x = f'{a!r:>{b}} text'", "    y = 1, 2.5, 'x', b'y', None, True, ...", "    return r, s, t, u, v, v2, w, x, y", "",
    "def matching(value):", "    match value:", "        case 1 | 2:", "            pass", "        case None | True:", "            pass", "        case [a, *rest]:", "            pass", "        case {'k': v, **others}:", "            pass",
    "        case sys.maxsize:", "            pass", "        case os.PathLike(path=p) as like:", "            pass", "        case _ if value:", "            pass", "",
    "def starry():", "    try:", "        pass", "    except* ValueError as group:", "        pass", "",
    "def nonlocal_user():", "    count = 0", "    def inner():", "        nonlocal count", "        count += 1", "    return inner", "",
    "class Base:", "    attr = 1", "    def method(self):", "        return self.attr", "", "class Child(Base, object):", "    pass",
)


class TableTest(unittest.TestCase):
    def setUp(self) -> None:
        repo = Repo({})
        self.addCleanup(repo.close)
        self.tool = json.loads(repo.run("--contract", tool=fx.CONTRACT_TOOL, root=False).stdout)

    def concrete(self) -> set[str]:
        """The syntax node classes of this interpreter a parser can produce."""
        return {n for n, c in vars(ast).items() if isinstance(c, type) and issubclass(c, ast.AST)} - ABSTRACT - OBSOLETE

    def test_every_syntax_node_class_of_this_interpreter_is_recognised_or_refused_by_design(self) -> None:
        recognised, refused = set(self.tool["forms"]), set(self.tool["refused_by_design"])
        self.assertEqual(recognised & refused, set())
        self.assertEqual(sorted(self.concrete() - recognised - refused), [], msg="a node class of this Python the walker has no entry for: record it, or refuse it by design")
        self.assertEqual(sorted(n for n in recognised | refused if not hasattr(ast, n)), [], msg="an entry that is no node class of this Python")

    def test_the_forms_the_table_names_are_the_handlers_the_walker_has(self) -> None:
        self.assertEqual(sorted(set(self.tool["forms"].values())), sorted({"leaf", "generic", "function", "class", "lambda", "comprehension_scope", "assign", "augassign", "annassign", "delete", "loop",
                                                                            "compound", "withitem", "except_handler", "match_case", "capture", "import", "import_from", "declaration", "walrus",
                                                                            "name", "container", "attribute", "subscript", "call"}))

    def test_one_module_uses_every_node_class_the_table_records_and_the_contract_accepts_it_in_both_services(self) -> None:
        """The corpus the walker is exercised on: it holds every recognised node class a parser produces, so a handler the table names that does not exist, or one that crashes, is found here."""
        seen = {type(node).__name__ for node in ast.walk(ast.parse(EVERY_FORM))}
        wanted = self.concrete() - set(self.tool["refused_by_design"]) - {"Module", "Expression", "Interactive", "FunctionType", "TypeIgnore"}
        self.assertEqual(sorted(wanted - seen), [], msg="the module below does not use these node classes")
        for service in SERVICES:
            with self.subTest(service=service):
                repo = Repo(package(service, {"a.py": EVERY_FORM, "sibling.py": "x = 1\n"}))
                self.addCleanup(repo.close)
                done = repo.run(tool=fx.CONTRACT_TOOL)
                self.assertEqual(done.returncode, 0, msg=done.stderr)

    def test_the_binding_roles_and_the_recognised_kinds_are_the_tools_and_the_documents(self) -> None:
        text = (fx.REPO / "docs" / "gen2" / "SOURCE-CONTRACT.md").read_text(encoding="utf-8")
        self.assertEqual(len(self.tool["binding_roles"]), 14)
        self.assertIn("the fourteen roles", text)
        self.assertEqual(sorted(self.tool["class_forms"]), ["annotation", "assign", "augassign", "class", "def", "delete", "from", "import", "target", "walrus"])
        self.assertEqual(sorted(self.tool["store_forms"]), ["class", "data", "instance_dict", "namespace", "ns_dict", "receiver"])
        for name in ("Closure", "SRC-FORM-UNRECOGNISED", "FORMS", "CLASS_FORMS", "STORE_FORMS"):
            self.assertIn(name, text)


# --- the dispatchers' refusals that no valid source can reach, on synthetic syntax -------------------------------------------------------

TOOLS_PRELUDE = "import sys; sys.path.insert(0, {tools!r}); import ast, json, pathlib\nimport gen2_source_index as si, gen2_source_contract as c\n"


def in_the_tools(code: str) -> list:
    """Run `code` in a child that imports the index and the contract from the code tree's tools/ (the tree the mutation runner points children at) and return what it printed as JSON."""
    done = children.python(["-B", "-c", TOOLS_PRELUDE.format(tools=str(children.path("tools"))) + code], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


class WalkerUnitTest(unittest.TestCase):
    """A dispatcher refuses what has no recorded effect, including what no parser of this Python produces (a node class a later Python adds, a name stored where no statement
    says how, a binding role the contract has no record of). Valid source cannot reach these refusals, so their oracle is handcrafted syntax: the expectation is the rule itself."""

    def test_a_name_stored_where_no_statement_says_how_is_refused(self) -> None:
        said = in_the_tools('tree = ast.parse("x = 1")\ntree.body = [ast.Expr(value=ast.Name(id="y", ctx=ast.Store()))]\nast.fix_missing_locations(tree)\n'
                            'print(json.dumps([[d.category, d.construct] for d in si.FileIndex("gen2/a.py", tree).diagnostics]))')
        self.assertEqual(said, [["SRC-FORM-UNRECOGNISED", "the name y is written where no statement says how"]])

    def test_a_node_class_the_table_has_no_entry_for_is_refused_and_not_read_as_harmless(self) -> None:
        said = in_the_tools('class Unheard(ast.stmt):\n    _fields = ()\ntree = ast.parse("x = 1")\ntree.body.append(Unheard())\nast.fix_missing_locations(tree)\n'
                            'print(json.dumps([[d.category, d.construct] for d in si.FileIndex("gen2/a.py", tree).diagnostics]))')
        self.assertEqual(said, [["SRC-FORM-UNRECOGNISED", "the syntax Unheard has no recorded effect on a namespace"]])

    def test_a_node_class_inside_an_expression_is_refused_as_well(self) -> None:
        said = in_the_tools('class Unheard(ast.expr):\n    _fields = ()\ntree = ast.parse("f(1)")\ntree.body[0].value.args.append(Unheard())\nast.fix_missing_locations(tree)\n'
                            'print(json.dumps([d.category for d in si.FileIndex("gen2/a.py", tree).diagnostics]))')
        self.assertEqual(said, ["SRC-FORM-UNRECOGNISED"])

    def test_a_binding_role_the_contract_has_no_record_of_is_refused(self) -> None:
        said = in_the_tools('tree = ast.parse("x = 1")\nindex = si.FileIndex("gen2/a.py", tree)\nindex.module.bindings["x"][0].role = "frobnicate"\n'
                            'facts = si.Facts(pathlib.Path("."), {"all": ["gen2/a.py"], "engine": ["gen2/a.py"], "gateway": []}, {"gen2/a.py": "x = 1"}, {"gen2/a.py": index})\n'
                            'c.Contract(facts).bindings(index, index.module)\nprint(json.dumps([[d.category, d.construct] for d in facts.diagnostics]))')
        self.assertEqual(said, [["SRC-FORM-UNRECOGNISED", "the binding of x has the role frobnicate, which the contract does not record"]])

    def test_every_role_the_walker_gives_a_binding_is_one_the_contract_lists(self) -> None:
        said = in_the_tools(f'tree = ast.parse({EVERY_FORM + "from os import *" + chr(10)!r})\nindex = si.FileIndex("gen2/a.py", tree)\n'
                            'roles = sorted({b.role for s in index.scopes for bs in s.bindings.values() for b in bs})\nprint(json.dumps([roles, list(si.BINDING_ROLES)]))')
        roles, listed = said
        self.assertEqual(sorted(set(roles) - set(listed)), [])
        self.assertEqual(sorted(set(listed) - set(roles)), [], msg="the corpus binds in every way the walker records")


# --- Astra's probes, each with its interpreter control -----------------------------------------------------------------------------

class ProbeTest(ClosureCase):
    """Every probe of the review, in both services: the interpreter's control prints what Python does, and the contract's verdict agrees with it."""

    def test_each_probe(self) -> None:
        for probe in PROBES:
            for service, (prefix, _) in SERVICES.items():
                if probe.only not in (None, service):
                    continue
                with self.subTest(probe=probe.name, service=service):
                    repo = self.repo(package(service, probe.files))
                    self.assertEqual(interpreter(repo, service, probe.control), probe.says, msg=f"what Python does with {probe.name}")
                    status, view = self.view(repo)
                    found = self.diagnostics(view)
                    if probe.refused:
                        self.assertEqual(status, 1, msg=f"{probe.name} was accepted")
                        for category, file, line in probe.refused:
                            self.assertIn((category, prefix + file, line), found)
                    else:
                        self.assertEqual((status, found), (0, []), msg=f"{probe.name} is inside the contract")
                        if probe.sites is not None:
                            self.assertEqual(measured_sites(repo, service), probe.sites, msg=f"the cross-file self-call sites measured for {probe.name}")

    def test_the_probe_files_are_astras(self) -> None:
        names = [p.name for p in PROBES]
        self.assertEqual(len(names), len(set(names)))
        for needed in ("dataclass-field", "transitive-external", "module-overwrite", "annotation-rebind", "global-import-rebind", "loader-alias", "all-alias", "class-hook-alias", "class-loop-target",
                       "builtin-object-order"):
            self.assertIn(needed, names)
        self.assertEqual(sum(p.name.startswith(("ordinary-hash", "dataclass-hash")) for p in PROBES), 4, msg="both F1 cases, before and after")

    def test_a_qualified_owner_whose_namespace_has_been_replaced_satisfies_no_locator(self) -> None:
        """Her stale-locator probe: after `a.A = object`, Python says `hasattr(A, 'f')` is False, and the locator `pkg.a.A.f` must not pass (the refusal stage runs first and no locator is checked)."""
        for service, (prefix, name) in SERVICES.items():
            with self.subTest(service=service):
                repo = self.repo(package(service, LOCATOR_FILES) | {"docs/gen2/INVARIANTS.md": LOCATOR_DOC.replace("{pkg}", name), "docs/gen2/DEBT-REGISTER.md": "none\n"})
                self.assertEqual(interpreter(repo, service, LOCATOR_CONTROL), LOCATOR_SAYS)
                done = repo.run(tool=fx.LOCATORS_TOOL)
                self.assertEqual(done.returncode, 1, msg=done.stdout + done.stderr)
                self.assertIn("SOURCE REFUSED", done.stderr)
                self.assertIn("no locator was checked", done.stderr)
                self.assertNotIn("every file and function locator exists", done.stdout)


class LoaderBoundaryTest(ContractCase):
    """Astra's F3 probe: the real adapter loader with `continue` turned into `pass` under the unchanged skip condition loads 28 names, not 26, and was accepted."""

    def tree(self, loader: str) -> dict[str, str]:
        files = {"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/adapters/__init__.py": loader}
        files |= {f"gateway/research_gateway/adapters/{n}.py": "value = 1\n" for n in (*LOADER_NAMES, "base", "_private")}   # inert stubs
        return files

    def loaded(self, repo: Repo) -> list[str]:
        done = fx.fixture_python(repo.root / "gateway", LOADER_CONTROL)
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        return eval_list(done.stdout)

    def test_the_continue_turned_pass_loads_names_the_inventory_does_not_list_and_is_refused(self) -> None:
        real = LOADER.read_text(encoding="utf-8")
        changed = real.replace("            continue", "            pass")
        self.assertNotEqual(real, changed)
        before, after = self.repo(self.tree(real)), self.repo(self.tree(changed))
        self.assertEqual(self.loaded(before), sorted(LOADER_NAMES))
        self.assertEqual(sorted(set(self.loaded(after)) - set(LOADER_NAMES)), ["_private", "base"], msg="what Python does with the changed loader")
        self.assertEqual(self.view(before)[0], 0)
        status, view = self.view(after)
        self.assertEqual(status, 1)
        self.assertIn("SRC-LOADER-INVENTORY", [d["category"] for d in view["diagnostics"]])
        self.assertIn("not the reviewed implementation", " ".join(d["construct"] for d in view["diagnostics"]))

    def edits(self) -> dict[str, str]:
        real = LOADER.read_text(encoding="utf-8")
        return {"a statement added to the loop": real.replace("        mod = importlib", "        pass\n        mod = importlib"),
                "the key changed": real.replace('getattr(mod, "SOURCE_ID", info.name)', "info.name"),
                "a return added early": real.replace("    out: dict[str, ModuleType] = {}", "    out: dict[str, ModuleType] = {}\n    return out"),
                "the loop made a comprehension-free no-op": real.replace("    for info in pkgutil.iter_modules(__path__):", "    for info in list(pkgutil.iter_modules(__path__))[:3]:"),
                "the package path replaced at module level": real.replace("_SKIP = {\"base\"}", "_SKIP = {\"base\"}\n__path__ = ['/elsewhere']"),
                "a module-level name the loader reads rebound": real.replace("import pkgutil", "import pkgutil\nimportlib = None"),
                "an exception swallowed": real.replace("        mod = importlib.import_module(f\"{__name__}.{info.name}\")",
                                                       "        try:\n            mod = importlib.import_module(f\"{__name__}.{info.name}\")\n        except Exception:\n            continue")}

    def test_every_change_to_the_reviewed_loader_is_refused(self) -> None:
        real = LOADER.read_text(encoding="utf-8")
        for what, text in self.edits().items():
            with self.subTest(change=what):
                self.assertNotEqual(real, text, msg="the edit must change the real loader")
                status, view = self.view(self.repo(self.tree(text)))
                self.assertEqual(status, 1)
                self.assertTrue({"SRC-LOADER-INVENTORY", "SRC-DEF-REBOUND", "SRC-BINDING-COMPETING"} & {d["category"] for d in view["diagnostics"]}, msg=[d["category"] for d in view["diagnostics"]])

    def test_changes_that_are_not_the_implementation_are_not_refused(self) -> None:
        real = LOADER.read_text(encoding="utf-8")
        harmless = {"a comment": real.replace("    out: dict", "    # a comment\n    out: dict"), "the docstring": real.replace("Import every adapter module in this package, keyed by source id.", "Import them all."),
                    "the module docstring": real.replace("One module per source.", "A module per source."), "blank lines and spacing": real.replace("\n\n\n", "\n\n\n\n\n"),
                    "another function in the module": real + "\n\ndef helper(name):\n    return name\n"}
        for what, text in harmless.items():
            with self.subTest(change=what):
                self.assertNotEqual(real, text)
                status, view = self.view(self.repo(self.tree(text)))
                self.assertEqual((status, [d["category"] for d in view["diagnostics"]]), (0, []), msg=what)


def eval_list(text: str) -> list[str]:
    """The names a child printed as a list of strings (`['a', 'b']`)."""
    return list(ast.literal_eval(text.strip()))


# --- the effective members of a class against the interpreter ------------------------------------------------------------------------

FLAVOURS = {"plain": "", "dataclass": "@dataclass\n", "called": "@dataclass()\n", "frozen": "@dataclass(frozen=True)\n"}
BODIES = {"nothing": "    pass\n", "eq": "    def __eq__(self, other):\n        return True\n", "hash": "    def __hash__(self):\n        return 7\n",
          "eq_and_hash": "    def __eq__(self, other):\n        return True\n    def __hash__(self):\n        return 7\n", "none": "    __hash__ = None\n",
          "eq_and_none": "    __hash__ = None\n    def __eq__(self, other):\n        return True\n"}


def matrix_source() -> tuple[str, str, list[str]]:
    """The module of 24 subclasses, the module of their bases (A, which defines `__hash__`, and one `__hash__`-less base per class that sets `__hash__ = None`: a data member named like a
    method of the class family is refused, so no class shares a family with another's generated `__hash__`), and the class names."""
    names, parts, bases = [], [], ["class A:", "    def __hash__(self):", "        return 42", ""]
    for flavour, decorator in FLAVOURS.items():
        for body, text in BODIES.items():
            name = f"{flavour.capitalize()}_{body}"
            names.append(name)
            base = f"A0_{name}" if "= None" in text else "A"
            if base != "A":
                bases += [f"class {base}:", "    pass", ""]
            parts.append(f"{decorator}class {name}({base}):\n{text}")
    imports = ", ".join(b.split()[1].rstrip(":") for b in bases if b.startswith("class "))
    return f"from dataclasses import dataclass\nfrom {{pkg}}.a import {imports}\n\n" + "\n".join(parts), "\n".join(bases), names


MATRIX_CONTROL = ("import json\nfrom {pkg} import b\nout = {}\nfor name in %s:\n    value = vars(getattr(b, name)).get('__hash__', 'missing')\n"
                  "    out[name] = 'missing' if value == 'missing' else 'none' if value is None else 'function'\nprint(json.dumps(out, sort_keys=True))")


class EffectiveMemberTest(ContractCase):
    def test_the_hash_member_of_every_class_is_what_the_interpreter_builds(self) -> None:
        """For each of 24 classes - a plain class and the three recorded dataclass forms, each over six bodies - Python's answer for `vars(cls)['__hash__']` (absent, None, or a function) is
        the control, and the index's effective member must say the same: absent, a data member, or a method. The base class A defines a `__hash__` method of its own (the A0 classes, one per class that sets `__hash__ = None`, do not)."""
        source, bases, names = matrix_source()
        for service, (prefix, name) in SERVICES.items():
            with self.subTest(service=service):
                repo = self.repo(package(service, {"a.py": bases, "b.py": source}))
                python = json.loads(interpreter(repo, service, MATRIX_CONTROL % names))
                status, view = self.view(repo)
                self.assertEqual((status, [d["category"] for d in view["diagnostics"]]), (0, []))
                classes = {c["class"].split("::")[1]: c for c in view["classes"] if c["class"].startswith(f"{prefix}b.py")}
                indexed = {}
                for cls in names:
                    member = classes[cls]["members"].get("__hash__")
                    indexed[cls] = "missing" if member is None else "none" if member[0] == "data" else "function"
                self.assertEqual(indexed, python, msg="the index's effective __hash__ against Python's")
                self.assertEqual(sorted(set(python.values())), ["function", "missing", "none"], msg="the matrix reaches all three outcomes")

    def test_the_masked_call_is_attributed_to_nobody_in_both_services(self) -> None:
        for service, (prefix, name) in SERVICES.items():
            for flavour in ("plain", "dataclass", "called"):
                with self.subTest(service=service, flavour=flavour):
                    body = {"plain": "    def __eq__(self, other):\n        return False\n", "dataclass": "", "called": ""}[flavour]
                    decorator = {"plain": "", "dataclass": "@dataclass\n", "called": "@dataclass()\n"}[flavour]
                    source = f"from dataclasses import dataclass\nfrom {{pkg}}.a import A\n\n{decorator}class B(A):\n{body}    def run(self):\n        return self.__hash__()\n"
                    repo = self.repo(package(service, {"a.py": py("class A:", "    def __hash__(self):", "        return 42"), "b.py": source}))
                    self.assertEqual(measured_sites(repo, service), 0)

    def test_a_masking_member_is_data_for_every_name_and_not_only_hash(self) -> None:
        """The rule is general: a slot, a property and a data member each stop the lookup at their class, so an ancestor's method of that name is not what `self.name()` reaches. Python is the control."""
        for service, (prefix, name) in SERVICES.items():
            with self.subTest(service=service):
                a = py("class A:", "    def p(self):", "        return 'A.p'", "", "    def run(self):", "        return self.p(), self.q()")
                b = py("from {pkg}.a import A", "", "class B(A):", "    @property", "    def p(self):", "        return lambda: 'B.p'", "", "    def q(self):", "        return 'B.q'")
                repo = self.repo(package(service, {"a.py": a, "b.py": b}))
                self.assertEqual(interpreter(repo, service, "from {pkg}.b import B; print(B().run())"), "('B.p', 'B.q')")
                self.assertEqual(measured_sites(repo, service), 1, msg="A.run's call of q reaches B.q in b.py; its call of p reaches B's property, which is data, so it is no collaboration")

    def test_an_external_class_after_every_project_class_cannot_hide_a_project_name(self) -> None:
        for service, (prefix, name) in SERVICES.items():
            with self.subTest(service=service):
                files = {"a.py": py("from collections import UserDict", "", "class A(UserDict):", "    pass"), "b.py": py("class B:", "    def keys(self):", "        return 'project'"),
                         "c.py": py("from {pkg}.a import A", "from {pkg}.b import B", "", "class C(B, A):", "    def run(self):", "        return self.keys()")}
                repo = self.repo(package(service, files))
                self.assertEqual(interpreter(repo, service, "from {pkg}.c import C; print(C({'k': 1}).run())"), "project")
                self.assertEqual(self.view(repo)[0], 0)
                self.assertEqual(measured_sites(repo, service), 1)


if __name__ == "__main__":
    unittest.main()
