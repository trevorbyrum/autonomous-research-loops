"""SOURCE-CONTRACT version 2 (task 2q-a-repair-7; docs/gen2/SOURCE-CONTRACT.md, "Version 2: soundy by declaration"): the dynamic mechanisms the contract refuses, the exact statements it
excepts, the private names and the quoted class-body annotations it refuses, and Astra's 40 closure probes.

The guarantee is: exact for the supported forms; the named mechanisms refused wherever they are REFERENCED in production code; nothing else claimed. These tests are of that, with oracles that
do not read the tool's output as the truth:

  * literal fixtures by MECHANISM and spelling (gen2/tests/source_mechanism_fixtures.py): the category and the line are written by hand, and every fixture runs in both services;
  * the exceptions at their exact sites, built from the real statements, and the same statements in another function, another file, a second time and one character changed;
  * the real production tree, read here by a separate scan of the syntax: every reference to a banned name in it is in an excepted statement, each excepted statement is there exactly once,
    and it holds no private name and no quoted class-body annotation;
  * the interpreter: what `dataclasses` does with a quoted marker, and what Python does with each of Astra's closure probes (the four escaped-value forms are shown to be real counterexamples
    that version 2 declares outside its claim, and no test here says that accepting them is right).

What this cannot show: that the ban reads strings (`getattr(x, "__dict__")` is declared outside it), or that a value is never a module or a class by the time it is written through.
"""
from __future__ import annotations

import ast
import json
import unittest

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.source_contract_fixtures import Fixture
from gen2.tests.source_mechanism_fixtures import (BAN, CLOSURE_PROBES, ESCAPED_PROBES, FIELD_CONTROL, FIELD_SAYS, PRIVATE, PRIVATE_ACCEPTED, QUOTED, QUOTED_ACCEPTED)
from gen2.tests.test_source_closure import ClosureCase, ProbeCase, interpreter
from gen2.tests.test_source_contract import CONTRACT_DOC, SERVICES, ContractCase, package, table
from gen2.tests.tool_repo_fixtures import Repo, py

REAL = {"gateway/research_gateway/adapters/__init__.py", "gen2/supervisor/jobs.py", "gateway/research_gateway/core/payload.py"}


def contract_constants() -> dict:
    """The tool's own constants, asked of it in a child (`--contract`), as every consumer meets it."""
    repo = Repo({})
    try:
        return json.loads(repo.run("--contract", tool=fx.CONTRACT_TOOL, root=False).stdout)
    finally:
        repo.close()


def _family_test(prefix: str, name: str, fixtures: list[Fixture]):
    def test(self) -> None:
        self.refuses_each(fixtures)
    test.__name__ = f"test_refuses_{name}"
    test.__doc__ = f"every refusal fixture of {prefix} {name!r}, in both services"
    return test


class BannedMechanismTest(ClosureCase):
    """Every spelling of every banned mechanism is refused, in both services, wherever it is referenced. One test per family (generated below)."""

    def test_the_families_cover_each_banned_family_of_the_contract(self) -> None:
        self.assertEqual(sorted(BAN), ["attribute_protocol", "code_execution", "dunder_dict", "dynamic_import", "setattr_and_delattr", "sys_modules",
                                       "the_ban_is_on_the_reference_wherever_it_stands", "three_argument_type", "vars_globals_locals"])
        text = " ".join(f.name for fixtures in BAN.values() for f in fixtures)
        for needle in ("setattr", "delattr", "vars", "globals", "locals", "__dict__", "importlib", "import_module", "__import__", "exec", "eval", "compile", "__setattr__", "__delattr__",
                       "__getattribute__", "sys.modules", "type"):
            self.assertIn(needle, text, msg=f"no fixture names {needle}")

    def test_an_aliased_banned_name_is_itself_a_reference(self) -> None:
        """The ban is on the reference, not on values: an alias, a value passed, stored, defaulted, unpacked or bound by an assignment expression each refers to the name once, where it is written. (An inventory
        check that the families hold each of those spellings; the refusals themselves are the families' tests.)"""
        names = {f.name for fixtures in BAN.values() for f in fixtures}
        for wanted in ("globals aliased", "__import__ aliased", "exec aliased", "vars passed as a value", "vars stored in a container", "a loader passed as a default argument (Astra's loader-default)",
                       "a loader bound by an assignment expression (Astra's loader-walrus)", "a loader unpacked from a tuple", "eval passed as a value"):
            self.assertIn(wanted, names)


for _family, _fixtures in BAN.items():
    _test = _family_test("the banned mechanisms:", _family, _fixtures)
    setattr(BannedMechanismTest, _test.__name__, _test)


class PrivateNameTest(ClosureCase):
    """A private (name-mangled) identifier is refused in every position it can be written; ordinary dunders and single-underscore names are not private."""

    def test_the_accepted_names_are_accepted_in_both_services(self) -> None:
        for fixture in PRIVATE_ACCEPTED:
            for service, (prefix, _) in SERVICES.items():
                with self.subTest(fixture=fixture.name, service=service):
                    status, view = self.view(self.repo(package(service, fixture.files)))
                    self.assertEqual((status, self.diagnostics(view)), (0, []), msg=fixture.name)
                    classes = {c["class"]: c for c in view["classes"]}
                    for key, methods in fixture.expect.get("methods", {}).items():
                        self.assertEqual(classes[prefix + key]["methods"], methods)

    def test_the_rule_is_the_languages_and_the_interpreter_agrees(self) -> None:
        """Python mangles `__name` (no trailing `__`) in a class body and leaves a dunder, a single underscore and an already mangled spelling alone: the interpreter is the control."""
        repo = self.repo(package("engine", {"a.py": py("class C:", "    def run(self):", "        return [self.__a(), self.__b__(), self._c(), self._C__d(), self.__e_()]", "    def __a(self): return 'a'",
                                                          "    def __b__(self): return 'b'", "    def _c(self): return 'c'", "    def _C__d(self): return 'd'", "    def __e_(self): return 'e'")}))
        self.assertEqual(interpreter(repo, "engine", "from {pkg}.a import C; print(sorted(set(vars(C)) - set(vars(type('X', (), {}))) - {'run'}))"),
                         "['_C__a', '_C__d', '_C__e_', '__b__', '_c']", msg="what Python holds: `__a` and `__e_` are mangled, `__b__` and `_c` and `_C__d` are not")
        _status, view = self.view(repo)
        self.assertEqual(sorted({d["construct"].split("`")[1] for d in view["diagnostics"] if d["category"] == "SRC-PRIVATE-NAME"}), ["__a", "__e_"],
                         msg="the contract refuses exactly the two the language mangles")


for _family, _fixtures in PRIVATE.items():
    _test = _family_test("the private names:", _family, _fixtures)
    setattr(PrivateNameTest, _test.__name__, _test)


class QuotedAnnotationTest(ClosureCase):
    """A quoted annotation of a statement in a class body is refused; a quoted annotation that no dataclass reads as a field marker is not."""

    def test_the_accepted_quoted_annotations_are_accepted_in_both_services(self) -> None:
        for fixture in QUOTED_ACCEPTED:
            for service, (prefix, _) in SERVICES.items():
                with self.subTest(fixture=fixture.name, service=service):
                    status, view = self.view(self.repo(package(service, fixture.files)))
                    self.assertEqual((status, self.diagnostics(view)), (0, []), msg=fixture.name)
                    classes = {c["class"]: c for c in view["classes"]}
                    for key, names in fixture.expect.get("fields", {}).items():
                        self.assertEqual(classes[prefix + key]["fields"], names)

    def test_only_a_whole_string_annotation_hides_a_field_marker_from_the_contract_and_the_interpreter_says_so(self) -> None:
        """`dataclasses` reads `f: 'ClassVar[int]'` as no field (its text matches) and `Optional['ClassVar[int]']` as a field: only the whole-string form is a marker the contract cannot resolve."""
        repo = self.repo(package("engine", {"a.py": "x = 1\n"}))
        self.assertEqual(interpreter(repo, "engine", FIELD_CONTROL), FIELD_SAYS)


for _family, _fixtures in QUOTED.items():
    _test = _family_test("the quoted annotations:", _family, _fixtures)
    setattr(QuotedAnnotationTest, _test.__name__, _test)


# --- the exceptions, at their exact sites -------------------------------------------------------------------------------------------------------------------------------

JOBS_STATEMENT = "key, held = (stat.st_dev, stat.st_ino), _HELD.__dict__.setdefault('keys', set())"
PAYLOAD = py("class _Unread:", "    def __setattr__(self, name, value):", "        raise AttributeError(name)", "",
             "class Sealed(_Unread):", "    __slots__ = ('_value',)", "", "    def __init__(self, value):", "        object.__setattr__(self, '_value', value)", "",
             "class Passive(_Unread):", "    __slots__ = ('_value',)", "", "    def __init__(self, value=None):", "        object.__setattr__(self, '_value', value)")
JOBS = py("import threading", "", "_HELD = threading.local()", "", "class Job:", "    def hold(self, stat):", f"        {JOBS_STATEMENT}", "        return key, held")


class ExceptionTest(ContractCase):
    """Each excepted statement matches by file, enclosing function and exact normalised statement, and nothing else."""

    def refused(self, files: dict[str, str], service: str) -> list[tuple[str, str, int]]:
        status, view = self.view(self.repo(files))
        self.assertEqual(status, 1 if view["diagnostics"] else 0)
        return [(d["category"], d["file"], d["line"]) for d in view["diagnostics"]]

    def test_the_three_production_uses_are_accepted_at_their_exact_sites_and_the_definition_of_setattr_is_no_reference(self) -> None:
        self.assertEqual(self.refused({"gen2/__init__.py": "", "gen2/supervisor/__init__.py": "", "gen2/supervisor/jobs.py": JOBS}, "engine"), [])
        self.assertEqual(self.refused({"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/core/__init__.py": "", "gateway/research_gateway/core/payload.py": PAYLOAD}, "gateway"), [],
                         msg="`def __setattr__` of _Unread is a definition, and both __init__ statements are excepted")

    def test_the_same_statements_in_another_function_are_refused(self) -> None:
        moved_jobs = JOBS.replace("def hold(self, stat):", "def other(self, stat):")
        self.assertEqual(self.refused({"gen2/__init__.py": "", "gen2/supervisor/__init__.py": "", "gen2/supervisor/jobs.py": moved_jobs}, "engine"), [("SRC-DYNAMIC-MECHANISM", "gen2/supervisor/jobs.py", 7)])
        moved = PAYLOAD.replace("class Passive(_Unread):", "class Other(_Unread):")
        self.assertEqual(self.refused({"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/core/__init__.py": "", "gateway/research_gateway/core/payload.py": moved}, "gateway"),
                         [("SRC-DYNAMIC-MECHANISM", "gateway/research_gateway/core/payload.py", 15)], msg="only the statement in Passive.__init__ moved; Sealed's is still excepted")
        copied = JOBS + "\n\ndef elsewhere(stat):\n    " + JOBS_STATEMENT + "\n    return key, held\n"
        self.assertEqual(self.refused({"gen2/__init__.py": "", "gen2/supervisor/__init__.py": "", "gen2/supervisor/jobs.py": copied}, "engine"),
                         [("SRC-DYNAMIC-MECHANISM", "gen2/supervisor/jobs.py", 12)], msg="the same text copied into a function of the same file")

    def test_the_same_statements_in_another_file_are_refused(self) -> None:
        for path, text, line in (("gen2/supervisor/other.py", JOBS, 7), ("gen2/supervisor/jobs_copy.py", JOBS, 7)):
            with self.subTest(path=path):
                self.assertEqual(self.refused({"gen2/__init__.py": "", "gen2/supervisor/__init__.py": "", path: text}, "engine"), [("SRC-DYNAMIC-MECHANISM", path, line)])
        self.assertEqual(self.refused({"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/core/__init__.py": "", "gateway/research_gateway/core/other.py": PAYLOAD}, "gateway"),
                         [("SRC-DYNAMIC-MECHANISM", "gateway/research_gateway/core/other.py", 9), ("SRC-DYNAMIC-MECHANISM", "gateway/research_gateway/core/other.py", 15)])

    def test_a_changed_statement_is_refused_and_so_is_a_second_copy_in_the_same_function(self) -> None:
        changed = JOBS.replace("setdefault('keys', set())", "setdefault('other', set())")
        self.assertEqual(self.refused({"gen2/__init__.py": "", "gen2/supervisor/__init__.py": "", "gen2/supervisor/jobs.py": changed}, "engine"), [("SRC-DYNAMIC-MECHANISM", "gen2/supervisor/jobs.py", 7)])
        twice = JOBS.replace("        return key, held", f"        {JOBS_STATEMENT}\n        return key, held")
        self.assertEqual(self.refused({"gen2/__init__.py": "", "gen2/supervisor/__init__.py": "", "gen2/supervisor/jobs.py": twice}, "engine"), [("SRC-DYNAMIC-MECHANISM", "gen2/supervisor/jobs.py", 8)],
                         msg="an exception is one statement: its twin in the same function is refused")
        wider = JOBS.replace("        return key, held", "        vars(held)\n        return key, held")
        self.assertEqual(self.refused({"gen2/__init__.py": "", "gen2/supervisor/__init__.py": "", "gen2/supervisor/jobs.py": wider}, "engine"), [("SRC-DYNAMIC-MECHANISM", "gen2/supervisor/jobs.py", 8)],
                         msg="another banned reference beside the excepted statement is refused")
        also = PAYLOAD.replace("        object.__setattr__(self, '_value', value)\n\nclass Passive", "        object.__setattr__(self, '_value', value)\n        object.__delattr__(self, '_value')\n\nclass Passive")
        self.assertEqual(self.refused({"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/core/__init__.py": "", "gateway/research_gateway/core/payload.py": also}, "gateway"),
                         [("SRC-DYNAMIC-MECHANISM", "gateway/research_gateway/core/payload.py", 10)])

    def test_the_excepted_write_is_checked_like_any_write_through_the_receiver(self) -> None:
        """`object.__setattr__(self, '_value', ...)` sets an instance attribute: a method of the family named `_value` would be hidden by it."""
        hidden = py("class _Unread:", "    def __setattr__(self, name, value):", "        raise AttributeError(name)", "", "class Sealed(_Unread):", "    def _value(self):", "        return 1", "",
                    "    def __init__(self, value):", "        object.__setattr__(self, '_value', value)")
        found = self.refused({"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/core/__init__.py": "", "gateway/research_gateway/core/payload.py": hidden}, "gateway")
        self.assertEqual(found, [("SRC-ATTR-OVERRIDE", "gateway/research_gateway/core/payload.py", 10)], msg="the statement is excepted from the ban and its write is the receiver's: it hides the method `_value`")

    def test_the_loader_exceptions_are_the_real_loaders_statements_in_the_real_function(self) -> None:
        loader = (fx.REPO / "gateway/research_gateway/adapters/__init__.py").read_text(encoding="utf-8")
        names = ("bea", "bis", "bls", "census", "core", "crossref", "datacite", "doaj", "doi_org", "ecb", "europepmc", "fred", "globe", "govinfo", "harvard_dataverse", "huggingface",
                 "kaggle", "openaire", "openalex_snapshot", "opencitations", "openml", "qdr", "semanticscholar", "socrata", "unpaywall", "wms")
        files = {"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/adapters/__init__.py": loader, "gateway/research_gateway/adapters/base.py": "x = 1\n"}
        files |= {f"gateway/research_gateway/adapters/{n}.py": "x = 1\n" for n in names}
        self.assertEqual(self.refused(files, "gateway"), [])
        moved = loader.replace("def load_all()", "def load_everything()")
        self.assertIn("SRC-DYNAMIC-MECHANISM", [c for c, _, _ in self.refused(files | {"gateway/research_gateway/adapters/__init__.py": moved}, "gateway")],
                      msg="the loader statements are excepted in `load_all` only")

    def test_another_reference_inside_the_loader_function_is_refused_as_a_banned_mechanism_whatever_the_fingerprint_says(self) -> None:
        """The loader's exceptions are two statements, not the function: a second `import_module` call, an `eval`, and the one call changed or replaced, in `load_all`, are banned references of their own (and the fingerprint refuses the change too)."""
        loader = (fx.REPO / "gateway/research_gateway/adapters/__init__.py").read_text(encoding="utf-8")
        names = ("bea", "bis", "bls", "census", "core", "crossref", "datacite", "doaj", "doi_org", "ecb", "europepmc", "fred", "globe", "govinfo", "harvard_dataverse", "huggingface",
                 "kaggle", "openaire", "openalex_snapshot", "opencitations", "openml", "qdr", "semanticscholar", "socrata", "unpaywall", "wms")
        base = {"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/adapters/base.py": "x = 1\n"} | {f"gateway/research_gateway/adapters/{n}.py": "x = 1\n" for n in names}
        changes = {"a second import_module call": loader.replace("    return out", "    importlib.import_module('os')\n    return out"),
                   "an eval": loader.replace("    return out", "    eval('1')\n    return out"),
                   "the argument of the one call changed": loader.replace('f"{__name__}.{info.name}"', 'f"{__name__}.{info.name}x"'),
                   "the one call replaced by another": loader.replace('importlib.import_module(f"{__name__}.{info.name}")', 'importlib.import_module(info.name)')}
        for what, text in changes.items():
            with self.subTest(change=what):
                self.assertNotEqual(text, loader)
                found = self.refused(base | {"gateway/research_gateway/adapters/__init__.py": text}, "gateway")
                self.assertIn("SRC-DYNAMIC-MECHANISM", [category for category, _, _ in found], msg=found)


# --- the real production tree, read by a separate scan -----------------------------------------------------------------------------------------------------------------------

BANNED = {"setattr", "delattr", "vars", "globals", "locals", "exec", "eval", "compile", "__import__", "importlib", "import_module", "__dict__", "__setattr__", "__delattr__", "__getattribute__"}
ATTRIBUTES = {"__dict__", "__setattr__", "__delattr__", "__getattribute__", "import_module", "__import__", "modules"}   # the names banned as an attribute of anything (`re.compile` is no builtin `compile`)


def production_files() -> list[str]:
    import subprocess
    tracked = subprocess.run(["git", "-C", str(fx.REPO), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    return [p for p in tracked if p.endswith(".py") and (p.startswith("gateway/research_gateway/") or (p.startswith("gen2/") and not p.startswith("gen2/tests/")))]


class ProductionTest(unittest.TestCase):
    """The real tree of both services against the ban: this scan is written apart from the tool's, and counts references, private names and quoted class-body annotations itself."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.trees = {path: ast.parse((fx.REPO / path).read_text(encoding="utf-8"), path) for path in production_files()}

    def references(self) -> list[tuple[str, int, str, str]]:
        """(file, line, banned name, the nearest statement it is in) of every reference to a banned name: a name, an attribute, an import. A reference in the header of a compound statement is
        reported with the whole statement, which no exception is."""
        found = []
        for path, tree in self.trees.items():
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(tree):
                names = ([node.id] if isinstance(node, ast.Name) and node.id in BANNED else [node.attr] if isinstance(node, ast.Attribute) and node.attr in ATTRIBUTES else
                         [a.name for a in node.names if a.name.split(".")[0] in BANNED] if isinstance(node, ast.Import) else [])
                for name in names:
                    statement = node
                    while not isinstance(statement, ast.stmt):
                        statement = parents[statement]
                    found.append((path, node.lineno, name, ast.unparse(statement)))
        return found

    def test_every_reference_to_a_banned_name_in_production_is_in_one_of_the_five_excepted_statements(self) -> None:
        tool = contract_constants()
        excepted = {(e["file"], e["statement"]) for e in tool["exceptions"]}
        found = self.references()
        self.assertTrue(found, msg="the scan finds the excepted statements at least")
        self.assertEqual(sorted({(path, text) for path, _, _, text in found}), sorted(excepted), msg="a reference outside the excepted statements, or an exception no statement of production has")
        self.assertEqual(sorted({path for path, *_ in found}), sorted(REAL))

    def test_each_excepted_statement_is_in_its_function_exactly_once(self) -> None:
        tool = contract_constants()
        for entry in tool["exceptions"]:
            with self.subTest(file=entry["file"], function=entry["function"]):
                hits = []

                def walk(node: ast.AST, chain: tuple[str, ...]) -> None:
                    for child in ast.iter_child_nodes(node):
                        inner = chain + (child.name,) if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else chain
                        if isinstance(child, ast.stmt) and ".".join(chain) == entry["function"] and ast.unparse(child) == entry["statement"]:
                            hits.append(child.lineno)
                        walk(child, inner)

                walk(self.trees[entry["file"]], ())
                self.assertEqual(len(hits), 1, msg=f"{entry['statement']} in {entry['function'] or 'the module'}: {hits}")

    def test_production_has_no_private_name_and_no_quoted_class_body_annotation_and_no_type_call_the_ban_refuses(self) -> None:
        private = lambda n: isinstance(n, str) and n.startswith("__") and not n.endswith("__")
        for path, tree in self.trees.items():
            parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
            for node in ast.walk(tree):
                spelled = [getattr(node, field, None) for field in ("id", "attr", "name", "arg", "asname", "rest")] + list(getattr(node, "names", None) or []) + list(getattr(node, "kwd_attrs", []))
                spelled += [part for part in (getattr(node, "module", None) or "").split(".")]
                self.assertFalse([n for n in spelled if isinstance(n, str) and private(n)], msg=f"{path}:{getattr(node, 'lineno', 0)}")
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__slots__" for t in node.targets):
                    self.assertFalse([c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and private(c.value)], msg=f"{path}:{node.lineno} a private slot")
                if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Constant) and isinstance(node.annotation.value, str):
                    holder = parents[node]
                    while not isinstance(holder, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
                        holder = parents[holder]
                    self.assertNotIsInstance(holder, ast.ClassDef, msg=f"{path}:{node.lineno}")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "type":
                    self.assertTrue(len(node.args) == 1 and not node.keywords and not isinstance(node.args[0], ast.Starred), msg=f"{path}:{node.lineno}")


# --- Astra's 40 closure probes --------------------------------------------------------------------------------------------------------------------------------------------

class ClosureProbeTest(ProbeCase):
    """Her 20 sources in both services. Sixteen are refused (the interpreter's control shows what each does, and the refusal is checked against it); four are the escaped-value forms."""

    def test_the_sixteen_probes_the_contract_refuses_are_refused_in_both_services(self) -> None:
        self.check_each_probe(CLOSURE_PROBES)

    def test_the_four_escaped_value_probes_are_real_counterexamples_that_version_2_declares_outside_its_claim(self) -> None:
        """A module or a class that reaches a write through a call, a container or a parameter is not followed (SOURCE-CONTRACT: "What the contract does not claim"). Each probe is shown to do what it
        was reported to do - the interpreter says the module's class is gone - so this is a boundary the contract states and not a benign case; and the contract names the four forms. No
        assertion here says that accepting them is sound."""
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        section = text.split("## What the contract does not claim", 1)[1].split("\n## ", 1)[0]
        for probe in ESCAPED_PROBES:
            self.assertIn(f"`{probe.name}`", section, msg=f"the contract's list of what it does not claim names {probe.name}")
            for service in SERVICES:
                with self.subTest(probe=probe.name, service=service):
                    repo = self.repo(package(service, probe.files))
                    self.assertEqual(interpreter(repo, service, probe.control), probe.says, msg="what Python does: the class the module held is replaced or its method is gone")
                    status, view = self.view(repo)
                    self.assertEqual((status, self.diagnostics(view)), (0, []), msg=f"{probe.name}: version 2 follows no value, so the source stage has nothing to refuse")

    def test_the_forty_executions_are_the_twenty_sources_of_the_review_in_both_services(self) -> None:
        names = [p.name for p in CLOSURE_PROBES] + [p.name for p in ESCAPED_PROBES]
        self.assertEqual(len(names), 20)
        self.assertEqual(len(set(names)), 20)
        for needed in ("returned-module", "subscript-module", "unpacked-module", "parameter-module", "returned-class-delete", "dict-method-alias", "dict-dunder-mutator", "receiver-dict-alias",
                       "receiver-dict-dunder", "string-field-marker", "string-field-marker-shadow", "dunder-setattr", "getattr-installs-hook", "nonlocal-skips-nearest-function", "loader-unpack",
                       "loader-reexport", "loader-default", "loader-walrus", "loader-getattr", "type-star"):
            self.assertIn(needed, names)


# --- the document and the tool state one version-2 contract ---------------------------------------------------------------------------------------------------------------------

class VersionTwoDocumentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = contract_constants()
        self.text = CONTRACT_DOC.read_text(encoding="utf-8")

    def test_the_banned_names_are_the_documents_and_are_the_ones_the_ruling_lists(self) -> None:
        self.assertEqual(sorted(self.tool["banned"]), sorted(BANNED))
        section = self.text.split("## Dynamic mechanisms", 1)[1].split("\n## ", 1)[0]
        for name in BANNED:
            self.assertIn(f"`{name}`", section, msg=name)
        for needle in ("sys.modules", "three-argument", "definition and no reference", "`def __setattr__`", "In Defense of Soundiness", "PyCG", "import-linter"):
            self.assertIn(needle, self.text.replace("**", ""), msg=needle)

    def test_the_excepted_statements_are_the_documents(self) -> None:
        rows = table("Excepted statements")
        listed = [(r[0].strip("`"), "" if r[1] == "(module)" else r[1].strip("`"), r[2].strip("`"), [n.strip().strip("`") for n in r[3].split(",")]) for r in rows]
        ours = [(e["file"], e["function"], e["statement"], e["names"]) for e in self.tool["exceptions"]]
        self.assertEqual(sorted(listed), sorted(ours))
        self.assertTrue(all(len(r[4]) > 30 for r in rows) and all(len(e["reason"]) > 30 for e in self.tool["exceptions"]), msg="each exception has its reason")
        self.assertEqual(len(rows), 5, msg="the three production uses (the thread-local's dictionary and the two sealed classes' initialisers) and the loader's two statements")

    def test_the_exact_statement_rule_and_the_amendment_rule_are_stated(self) -> None:
        for needle in ("file, enclosing function and the exact normalised statement", "Adding an exception is a contract amendment", "a second copy of it in the same function"):
            self.assertIn(needle, self.text.replace("**", ""), msg=needle)

    def test_the_withdrawn_value_tracking_claims_and_the_open_item_are_gone_and_the_declared_exclusions_are_listed(self) -> None:
        for gone in ("returns a new object", "Those are the next slices of the repair and stay open", "recognised producers are `type(x)`"):
            self.assertNotIn(gone, self.text)
        section = self.text.split("## What the contract does not claim", 1)[1].split("\n## ", 1)[0]
        for needle in ("is **not followed**", "returned-module", "subscript-module", "parameter-module", "returned-class-delete", "Strings that name a mechanism"):
            self.assertIn(needle, section)

    def test_the_new_categories_are_in_the_tool_and_the_document(self) -> None:
        for category in ("SRC-DYNAMIC-MECHANISM", "SRC-PRIVATE-NAME", "SRC-QUOTED-ANNOTATION"):
            self.assertIn(category, self.tool["categories"])
            self.assertIn(f"`{category}`", self.text)
        self.assertEqual({k: v for k, v in self.tool["categories"].items() if k in ("SRC-DYNAMIC-MECHANISM", "SRC-PRIVATE-NAME", "SRC-QUOTED-ANNOTATION")},
                         {"SRC-DYNAMIC-MECHANISM": ["dynamic mechanisms", "a reference to a banned dynamic mechanism, outside the excepted statements"],
                          "SRC-PRIVATE-NAME": ["private names", "a private (name-mangled) identifier"], "SRC-QUOTED-ANNOTATION": ["class and method declarations", "a quoted annotation in a class body"]})


if __name__ == "__main__":
    unittest.main()
