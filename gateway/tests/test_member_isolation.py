"""Task 2b-repair-8 R7-2: member isolation is a property of the data, not of a name scan.

The defect came back three times (Socrata; then OpenCitations and eight more paths; then Hugging Face's file
siblings and ECB's data sets): one malformed member of a provider's list lost every readable member beside it,
because an adapter held its provider's list as a plain Python list and iterated, filtered, indexed or flattened it
before the member-by-member decoder ran. The check that was meant to prevent it scanned the source for loops that
call a record builder, so it missed a filter comprehension, a `while` loop, a builder under another name, `rows[0]`
and a helper outside adapters/ (Astra, 2b-repair-7 review). Each repair narrowed the same fix to the next spelling.

The structure now (core/payload.py): `Response.json` returns a VIEW. A provider's list is a `Members`, which has no
iteration, indexing, slicing or membership test, only decoding that isolates each member (`decode`, `first`,
`expand`); a provider's object is an `Obj`, whose values are views and which has no `items()` or `values()`. There
is nothing to preprocess with, so no spelling can do it. Three groups of tests hold that:

  * Views: the operations are absent, and a provider's list is refused where a decoded one is required.
  * Bypasses: each of Astra's checker-bypass shapes (and the old check's own forms) is RUN against a view and
    fails, not scanned for. The same source runs against the plain list the adapters used to hold, as the control:
    that is what makes each a real bypass, and shows that what stops it is the data and not the shape.
  * Doors: what the property does not cover is the one way out of a view, `plain()` (and the constructors
    `Members(...)` and `view(...)`, which wrap a list the caller already holds). A source check lists every use
    in the gateway with why it is not a provider's set of independent members: one record's own data, a table's
    rows, a catalogue's entries. A use that is not listed fails, whatever it is named: an alias, an import
    `as`, an attribute of a module. This is the check that remains, and it is small: it reads where a raw list may
    leave the wrapper, not what a loop does with it.

What it cannot see: a list reached by reflection (a `getattr` of a private name is refused in adapters), and a use
of `plain()` that is listed here with a reason that is wrong for the list it reads — whether a given list is one
record's data or a set of independent candidates is the author's declaration, and the reason beside it is where a
reviewer reads it. The behaviour of the lists that ARE members is tested in tests/test_member_decoding.py.
"""
from __future__ import annotations

import ast
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from research_gateway.adapters.base import first_member, members, need
from research_gateway.core import sdmx
from research_gateway.core.canonical import make_record
from research_gateway.core.payload import OMIT, Members, Obj, PayloadError, plain, view

ROOT = Path(__file__).resolve().parents[1] / "research_gateway"
DOORS = ("plain", "view", "listed")   # functions that hand a raw value back (`listed`: one record's own list, plain), or wrap one the caller holds
CONSTRUCTORS = ("Members",)       # `Members(items)` wraps a list the caller already holds
METHODS = ("each",)               # `Members.each(build)` hands back a plain list of whatever the builder returned

# Every use of a door in the gateway, by (file, function): how many there are there, and why they are not a pass over a
# provider's independent members. A use added to a function already listed changes its count, so it is read, not inherited.
USES = {
    ("adapters/base.py", "<module>"): (2, "NO_MEMBERS, the empty list, and the table from a kind to its view"),
    ("adapters/base.py", "members"): (1, "the one place that reads a list's members with each(): it keeps only records that name something and leaves the rest dropped"),
    ("adapters/base.py", "Response.json"): (1, "the one place a parsed answer becomes a view"),
    ("adapters/base.py", "listed"): (1, "the one place a record's own list is handed out as plain data: every call of `listed` is a use of it, listed below like plain()"),
    ("adapters/base.py", "need"): (2, "wraps what it is given (a plain dict or list handed to it is made a view, never read) and maps a requested kind to its view"),
    ("adapters/bea.py", "data"): (3, "BEA's rows and the table's notes are the payload of ONE table record, kept whole and never decoded one by one (Astra, 2b-repair-7)"),
    ("adapters/bea.py", "catalog.call"): (1, "a catalogue's entries, answered whole: one that cannot be read makes the catalogue unreadable, never a shorter one"),
    ("adapters/bis.py", "data.record"): (1, "the dimension attributes of ONE <Series> element"),
    ("adapters/bls.py", "_series"): (1, "the observations of ONE series: rows of one record"),
    ("adapters/bls.py", "_messages"): (1, "the answer's `message` strings, carried back to the caller"),
    ("adapters/bls.py", "catalog"): (2, "a catalogue's entries (surveys, a survey's popular series), answered whole"),
    ("adapters/census.py", "data"): (1, "the rows of ONE table record: a malformed row makes the table unreadable rather than shorter"),
    ("adapters/census.py", "catalog"): (3, "a catalogue's entries, answered whole, and each dataset entry's own path parts"),
    ("adapters/core.py", "_record"): (3, "ONE work's own download URLs and authors, and its payload minus the full text for the record's raw"),
    ("adapters/crossref.py", "_record"): (6, "ONE work's own authors, licences, ISSNs, titles and date parts"),
    ("adapters/datacite.py", "_record"): (3, "ONE DOI's own rights, titles and creators"),
    ("adapters/doaj.py", "_record"): (5, "ONE article's own identifiers, links, authors and licence"),
    ("adapters/doaj.py", "_journal"): (3, "ONE journal's own links, licence and subjects"),
    ("adapters/fred.py", "data"): (2, "ONE series' observations and its metadata list: rows of one record"),
    ("adapters/fred.py", "catalog"): (2, "a catalogue's entries, answered whole"),
    ("adapters/govinfo.py", "_record"): (1, "ONE package's download links"),
    ("adapters/harvard_dataverse.py", "dataset_record"): (1, "ONE dataset's citation fields"),
    ("adapters/huggingface.py", "_license"): (2, "ONE repository's licence value and tags (its files are members, read by fetch)"),
    ("adapters/huggingface.py", "_record"): (1, "ONE repository's own tags"),
    ("adapters/harvard_dataverse.py", "search_record"): (2, "ONE dataset hit's own authors and subjects"),
    ("adapters/openaire.py", "_record"): (6, "ONE product's own pids, instances (their alternate identifiers, pids and urls) and authors"),
    ("adapters/openml.py", "_list_record"): (1, "ONE dataset's own qualities"),
    ("adapters/openml.py", "_desc_record"): (1, "ONE dataset's own creators"),
    ("adapters/semanticscholar.py", "_record"): (2, "ONE paper's own authors and publication types"),
    ("adapters/socrata.py", "_vouched"): (1, "the portal-vouching predicate: a guarded security check that fails closed when the portal cannot be established, not a record-producing list"),
    ("adapters/socrata.py", "resolve"): (1, "ONE view's own columns"),
    ("adapters/unpaywall.py", "enrich"): (4, "an answer with no location list is its one best location: a list of one, built here from an object; and the two flags handed back"),
    ("core/canonical.py", "make_record"): (1, "a record is plain data: no view of the provider's answer ends up inside one"),
    ("core/canonical.py", "_text"): (1, "one typed field of a record, read as plain data to check its kind (never a candidate list)"),
    ("core/canonical.py", "_texts"): (1, "one list field of a record (authors, links), read as plain data to check its kind"),
    ("core/canonical.py", "_year"): (1, "one typed field of a record, read as plain data to check its kind"),
    ("core/canonical.py", "_identifiers"): (1, "one map field of a record, read as plain data to check its kind"),
    ("core/sdmx.py", "<module>"): (1, "NO_SERIES, the empty list"),
    ("core/sdmx.py", "series_xml"): (1, "the series of an XML message the gateway parsed itself, as members"),
    ("core/sdmx.py", "_held"): (1, "the message's shared structure definitions (its dimensions), read once and whole: every series needs them"),
    ("harvest/registries.py", "crossref_journals.build"): (3, "ONE journal's own ISSNs and subjects"),
    ("harvest/registries.py", "datacite_repositories.build"): (1, "ONE repository's own subjects"),
}


# ---- what a provider-data module may import (R8-3): closed over every import form, not over the names the checker happens to look for
STDLIB_ALLOWED = {"*": {"__future__", "re", "base64", "datetime", "time", "typing"}, "core/sdmx.py": {"xml.etree.ElementTree"},
                  "adapters/openaire.py": {"threading"}}   # no JSON parser, no `ast`, no `sys`/`importlib`
UNANALYSABLE_CALLS = ("eval", "exec", "compile", "vars", "globals", "locals", "__import__")


def provider_modules(root: Path = ROOT) -> list[Path]:
    """The modules that read a provider's answer: every adapter but the client, the SDMX helper, and the harvest loaders."""
    return sorted([*(p for p in (root / "adapters").glob("*.py") if p.name not in ("base.py", "__init__.py")), root / "core" / "sdmx.py",
                   *(p for p in (root / "harvest").glob("*.py") if p.name != "__init__.py")])


def literal_names(path: Path, name: str) -> list[str] | None:
    """The strings of the module-level `name = (...)` of the file, or None when it declares none."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets) and isinstance(node.value, (ast.Tuple, ast.List)):
            return [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def defined_names(path: Path) -> set[str]:
    """What the file defines at module level itself — a function, a class, a name assigned — and not what it imports."""
    out = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                out.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
    return out


def import_findings(root: Path = ROOT) -> list[tuple[str, str]]:
    """(file, what) for every import in a provider-data module that is not one the inventory admits. Every form is analysed, in every place it
    can stand (a function, a try block): a star import is refused (it names nothing), a stdlib module is admitted only if listed
    (STDLIB_ALLOWED: no JSON parser, so no provider answer is read by anything but Response.json), a name from adapters.base only if it is in
    its `__all__` (so no parser, module or helper it happens to import can be re-exported), and a name from any other module of the package only
    if that module defines it (not merely imports it)."""
    base = root / "adapters" / "base.py"
    api = set(literal_names(base, "__all__") or [])
    out = [] if api else [("adapters/base.py", "declares no __all__: nothing it exports is admitted")]
    for path in provider_modules(root):
        rel = path.relative_to(root).as_posix()
        strict = not rel.startswith("harvest/")
        allowed = STDLIB_ALLOWED["*"] | STDLIB_ALLOWED.get(rel, set())
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                out += [(rel, f"import {a.name}") for a in node.names if strict and a.name not in allowed]
            elif isinstance(node, ast.ImportFrom):
                if any(a.name == "*" for a in node.names):
                    out.append((rel, f"from {'.' * node.level}{node.module or ''} import *"))
                    continue
                if node.level == 0:
                    if strict and (node.module or "") not in allowed:
                        out.append((rel, f"from {node.module} import"))
                    continue
                package = path.parent
                for _ in range(node.level - 1):
                    package = package.parent
                where = package.joinpath(*(node.module or "").split(".")) if node.module else package
                module = where / "__init__.py" if where.is_dir() else where.with_suffix(".py")
                for a in node.names:
                    if where.is_dir() and (where / f"{a.name}.py").exists():
                        if a.name == "base":   # the client is imported by name, for then its `__all__` decides what is reached; as a module, anything is
                            out.append((rel, "from . import base (as a module: import what it exports by name)"))
                        continue   # any other module of the package, imported as one: its own imports are checked as its own
                    if not module.exists():
                        out.append((rel, f"from {'.' * node.level}{node.module or ''} import {a.name} (no such module)"))
                    elif module.name == "base.py" and module.parent.name == "adapters":
                        if a.name not in api:
                            out.append((rel, f"from base import {a.name} (not in its __all__)"))
                    elif a.name not in defined_names(module):
                        out.append((rel, f"from {'.' * node.level}{node.module or ''} import {a.name} (not defined there: a re-export)"))
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in UNANALYSABLE_CALLS:
                out.append((rel, f"{node.func.id}()"))
    return sorted(set(out))


def functions(tree: ast.AST):
    """(qualified name, node) for every function in the module, a method under its class."""
    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield ".".join((*scope, child.name)), child
                yield from visit(child, (*scope, child.name))
            elif isinstance(child, ast.ClassDef):
                yield from visit(child, (*scope, child.name))
            else:
                yield from visit(child, scope)
    return visit(tree, ())


def door_uses(root: Path = ROOT) -> dict[tuple[str, str], list[str]]:
    """{(file, innermost function or <module>): each door used there, one entry per use} for every module under `root` but the views' own.
    A door is used when the module imports it (under any name: `as`, from base, canonical or payload), calls it,
    passes it on or aliases it (a bare reference), reaches it as an attribute of a module (`payload.plain`), calls
    the one method that hands back a plain list (`.each`), or reaches for the views' private storage."""
    found: dict[tuple[str, str], list[str]] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == "core/payload.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        spans = sorted(((fn.lineno, fn.end_lineno, qual) for qual, fn in functions(tree)), key=lambda s: s[1] - s[0])   # the innermost function first

        def where(node) -> str:
            return next((qual for a, b, qual in spans if a <= node.lineno <= b), "<module>")

        def add(node, what: str) -> None:
            found.setdefault((rel, where(node)), []).append(what)

        local = {}   # the name this module gives each door
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in DOORS + CONSTRUCTORS:
                        local[alias.asname or alias.name] = alias.name   # importing is not using: the uses below are
        isinstance_args = {id(a) for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "isinstance"
                           for a in n.args}
        annotations = {id(n) for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                       for a in (*fn.args.args, *fn.args.kwonlyargs, fn.args.vararg, fn.args.kwarg, ) if a is not None and a.annotation
                       for n in ast.walk(a.annotation)}
        annotations |= {id(n) for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.returns
                        for n in ast.walk(fn.returns)}
        annotations |= {id(n) for st in ast.walk(tree) if isinstance(st, ast.AnnAssign) for n in ast.walk(st.annotation)}
        callee = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in local and not isinstance(node.ctx, ast.Store) and id(node) not in annotations:
                kind = local[node.id]
                if id(node) in callee:
                    add(node, f"call {kind}")
                elif not (kind in CONSTRUCTORS and id(node) in isinstance_args):
                    add(node, f"reference {kind}")
            elif isinstance(node, ast.Attribute) and node.attr in DOORS + CONSTRUCTORS + METHODS:
                add(node, f"attribute {node.attr}")
            elif isinstance(node, ast.Attribute) and node.attr in ("_d", "_items"):
                add(node, f"private {node.attr}")
            elif isinstance(node, ast.Attribute) and node.attr == "_parsed" and rel != "adapters/base.py":
                add(node, "private _parsed")
    return found


def reflection_in_adapters(root: Path = ROOT) -> list[tuple[str, str]]:
    """(file, what) for each adapter (and the SDMX helper) that parses JSON itself, evaluates, or reaches for a
    private name by reflection: other ways to a provider's raw list than Response.json."""
    out = []
    for path in sorted([*(root / "adapters").glob("*.py"), root / "core" / "sdmx.py"]):
        rel = path.relative_to(root).as_posix()
        if rel == "adapters/base.py" or not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import) and any(a.name.split(".")[0] == "json" for a in node.names):
                out.append((rel, "import json"))
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in ("json", "importlib"):
                out.append((rel, f"from {node.module} import"))
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("eval", "exec", "vars"):
                out.append((rel, f"{node.func.id}()"))
            elif isinstance(node, ast.Attribute) and node.attr in ("__getattribute__", "__getattr__", "__setattr__"):
                out.append((rel, node.attr))
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("getattr", "setattr", "delattr") and any(
                    isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith("_") for a in node.args[1:2]):
                out.append((rel, f"{node.func.id}() of a private name"))
            elif isinstance(node, ast.Attribute) and node.attr == "__dict__":
                out.append((rel, "__dict__"))
    return out


class Doors(unittest.TestCase):
    """The source check that remains: where a raw list may leave the wrapper."""

    def test_every_use_of_a_door_is_listed_with_its_reason_and_every_listed_use_is_there(self):
        found = {k: len(v) for k, v in door_uses().items()}
        self.assertEqual(sorted(set(found) - set(USES)), [], "a provider's list leaves its view here: say why it is one record's own data, "
                                                              "or decode it with members()/first_member()/expand()")
        self.assertEqual(sorted(set(USES) - set(found)), [], "a listed use that is no longer there")
        self.assertEqual({k: (found[k], n) for k, (n, _) in USES.items() if found[k] != n}, {},
                         "(uses found, uses listed): read the new use, and update the entry's count and reason")

    def test_no_use_is_unexplained(self):
        self.assertEqual([k for k, (n, why) in USES.items() if len(why.split()) < 3 or n < 1], [])

    def test_nothing_reaches_the_views_storage_or_parses_json_itself(self):
        found = door_uses()
        self.assertEqual({k: v for k, v in found.items() if any(w.startswith("private _d") or w.startswith("private _items") for w in v)}, {})
        self.assertEqual({k: v for k, v in found.items() if "private _parsed" in v}, {})
        self.assertEqual(reflection_in_adapters(), [])

    def test_control_the_check_finds_a_door_however_it_is_reached(self):
        """The check's own oracle: each way to a raw list is found, and what is not one is not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "adapters").mkdir()
            (root / "core").mkdir()
            (root / "adapters" / "new_lane.py").write_text(textwrap.dedent('''\
                import json
                from .base import need, plain, Members
                from .base import plain as unwrap
                from ..core import payload

                def a_call(rows):
                    return plain(rows)

                def an_alias(rows):
                    out = plain
                    return out(rows)

                def passed_on(rows):
                    return list(map(plain, rows))

                def an_import_as(rows):
                    return unwrap(rows)

                def a_module_attribute(rows):
                    return payload.plain(rows)

                def a_constructor(items):
                    return Members(items)

                def storage(rows):
                    return rows._items

                def reflection(rows):
                    return getattr(rows, "_items")

                def an_isinstance(rows):
                    return isinstance(rows, Members)

                def an_identity_decode(rows):
                    return [build(r) for r in rows.each(lambda member: member)]

                def by_the_back_door(rows):
                    return object.__getattribute__(rows, "_items")

                def reading(resp):
                    return need("x", resp.json, "results")
                '''))
            found = door_uses(root)
            by_function = {fn: sorted(v) for (_, fn), v in found.items() if fn != "<module>"}
            self.assertEqual(by_function, {"a_call": ["call plain"], "an_alias": ["reference plain"], "passed_on": ["reference plain"],
                                           "an_import_as": ["call plain"], "a_module_attribute": ["attribute plain"],
                                           "a_constructor": ["call Members"], "storage": ["private _items"],
                                           "an_identity_decode": ["attribute each"]})
            self.assertEqual(reflection_in_adapters(root), [("adapters/new_lane.py", "import json"),
                                                            ("adapters/new_lane.py", "getattr() of a private name"),
                                                            ("adapters/new_lane.py", "__getattribute__")])


class Imports(unittest.TestCase):
    """R8-3 (Astra, 2b-repair-8): the inventory above names the doors by what a module imports, so an import it cannot read — a star, a
    name re-exported by the client, `__import__` — walks a door in unseen, and two such mutants of OpenCitations passed every structural test.
    The rule is now closed over import forms: what is not admitted by name is refused, and an import that cannot be analysed is refused.
    Each of the reviewer's two complete mutants is a regression below, each with a permitted-import control."""

    @staticmethod
    def tree(root: Path, **edits: list) -> Path:
        copy = root / "research_gateway"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for rel, pairs in edits.items():
            path = copy / rel.replace("__", "/", 1)
            text = path.read_text(encoding="utf-8")
            for old, new in pairs:
                assert text.count(old) == 1, f"{rel}: {old!r} is found {text.count(old)} times"
                text = text.replace(old, new)
            path.write_text(text, encoding="utf-8")
        return copy

    OC = "adapters__opencitations.py"
    OC_IMPORT = "from .base import OMIT, Client, check, first_member, members, need, text"
    OC_READ = '    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, need(SOURCE_ID, resp.json), lambda row: _link(key, row))}'
    # the reviewer's first mutant: the rows are filtered with plain() before the decoder runs; the checker saw no `plain` because nothing named it
    STAR = [(OC_IMPORT, "from .base import *"),
            (OC_READ, '    rows = need(SOURCE_ID, [row for row in plain(need(SOURCE_ID, resp.json)) if row.get(key)])\n'
                      '    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, rows, lambda row: _link(key, row))}')]
    # the second: the body is parsed and filtered by a parser imported from the client, which uses no door at all
    PARSER = [(OC_IMPORT, OC_IMPORT + ", json as provider_json"),
              (OC_READ, '    rows = need(SOURCE_ID, [row for row in provider_json.loads(resp.body) if row.get(key)])\n'
                        '    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, rows, lambda row: _link(key, row))}')]

    def test_every_provider_data_module_imports_only_what_the_inventory_admits(self):
        self.assertEqual(import_findings(), [])

    def test_a_star_import_is_refused_and_so_is_the_reviewers_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = import_findings(self.tree(Path(tmp), **{self.OC: self.STAR}))
        self.assertEqual(findings, [("adapters/opencitations.py", "from .base import *")])

    def test_a_parser_re_exported_by_the_client_is_refused_and_so_is_the_reviewers_mutant(self):
        with tempfile.TemporaryDirectory() as tmp:
            findings = import_findings(self.tree(Path(tmp), **{self.OC: self.PARSER}))
        self.assertEqual(findings, [("adapters/opencitations.py", "from base import json (not in its __all__)")])

    def test_control_the_permitted_imports_are_not_refused(self):
        """What the same two edits do when they only use what the client exports: nothing is refused for the import — the one thing a name
        from `__all__` can still be is an unlisted door, which the inventory above catches by name, as it always did."""
        permitted = [(self.OC_IMPORT, self.OC_IMPORT + ", quote as q, optional")]   # a permitted re-export (quote), and a helper in __all__
        spelled_out = [(self.OC_IMPORT, self.OC_IMPORT + ", plain"), self.STAR[1]]
        real = door_uses()

        def changed(root: Path) -> list:
            found = door_uses(root)
            return sorted(k for k in found if found[k] != real.get(k))
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(Path(tmp), **{self.OC: permitted})
            self.assertEqual((import_findings(root), changed(root)), ([], []))
            root = self.tree(Path(tmp, "b"), **{self.OC: spelled_out})
            self.assertEqual(import_findings(root), [])
            self.assertEqual(changed(root), [("adapters/opencitations.py", "enrich")], "spelled out, the same body is an unlisted door the inventory reports")

    def test_every_other_form_an_import_can_take_is_refused_or_analysed(self):
        cases = {
            "an import of a parser": ("import json", [("adapters/new.py", "import json")]),
            "an aliased parser": ("import json as j", [("adapters/new.py", "import json")]),
            "a parser from a stdlib module": ("from json import loads", [("adapters/new.py", "from json import")]),
            "importlib": ("import importlib", [("adapters/new.py", "import importlib")]),
            "sys": ("import sys", [("adapters/new.py", "import sys")]),
            "the module the client imports it as": ("from .base import _parsed", [("adapters/new.py", "from base import _parsed (not in its __all__)")]),
            "a module of the client, by name": ("from .base import urllib", [("adapters/new.py", "from base import urllib (not in its __all__)")]),
            "the client as a module": ("from . import base", [("adapters/new.py", "from . import base (as a module: import what it exports by name)")]),
            "a star from another module": ("from ..core.canonical import *", [("adapters/new.py", "from ..core.canonical import *")]),
            "a name another module only re-exports": ("from ..core.canonical import PayloadError",
                                                      [("adapters/new.py", "from ..core.canonical import PayloadError (not defined there: a re-export)")]),
            "a module that is not there": ("from .nowhere import thing", [("adapters/new.py", "from .nowhere import thing (no such module)")]),
            "inside a function": ("def f():\n    import json", [("adapters/new.py", "import json")]),
            "inside a try": ("try:\n    import json\nexcept ImportError:\n    json = None", [("adapters/new.py", "import json")]),
            "by __import__": ("j = __import__('json')", [("adapters/new.py", "__import__()")]),
            "by eval": ("j = eval('1')", [("adapters/new.py", "eval()")]),
        }
        for name, (source, want) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = self.tree(Path(tmp))
                (root / "adapters" / "new.py").write_text(f"from __future__ import annotations\n{source}\n", encoding="utf-8")
                self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"], want)   # what is found in the new file, whatever else the tree holds
        with tempfile.TemporaryDirectory() as tmp:   # and the forms that are admitted: the names the client exports, a stdlib module that is listed
            root = self.tree(Path(tmp))
            (root / "adapters" / "new.py").write_text("from __future__ import annotations\nimport re\nfrom .base import Client, members, quote as q\n"
                                                      "from ..core.canonical import make_record\nfrom . import crossref\n", encoding="utf-8")
            self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"], [])

    def test_the_client_has_no_parser_to_re_export_and_exports_no_module(self):
        from types import ModuleType

        from research_gateway.adapters import base
        parsers = {"json", "ast", "simplejson", "orjson", "ujson", "yaml", "tomllib", "pickle", "marshal", "csv", "plistlib", "configparser", "xml"}
        self.assertEqual({n for n, o in vars(base).items() if isinstance(o, ModuleType) and o.__name__.split(".")[0] in parsers}, set())
        self.assertFalse(hasattr(base, "json"))
        declared = literal_names(ROOT / "adapters" / "base.py", "__all__")
        self.assertEqual(sorted(declared), sorted(base.__all__), "the checker reads the same __all__ the module has")
        for name in base.__all__:
            self.assertFalse(isinstance(getattr(base, name), ModuleType), name)

    def test_provider_data_modules_are_exactly_the_ones_that_read_an_answer(self):
        names = [p.relative_to(ROOT).as_posix() for p in provider_modules()]
        self.assertIn("adapters/crossref.py", names)
        self.assertIn("core/sdmx.py", names)
        self.assertIn("harvest/registries.py", names)
        self.assertNotIn("adapters/base.py", names)


BODY = [{"id": "a", "n": 1}, 7, {"id": "b", "n": 2}]


def fixture(source: str):
    """A function `run(rows)` compiled from adapter-shaped source, with the names an adapter has in hand."""
    scope = {"members": members, "make_record": make_record, "OMIT": OMIT, "need": need, "first_member": first_member, "build": build,
             "Members": Members}
    exec(textwrap.dedent(source), scope)
    return scope["run"]


def build(row):
    return make_record(identity=f"doi:10.1/{row['id']}", kind="citation", source_id="x")


# the shapes the old name scan missed (Astra, 2b-repair-7 review), and the forms it did catch
SHAPES = {
    "a filter comprehension before the decoder": '''
        def run(rows):
            rows = [r for r in rows if r.get("id")]
            return members("x", Members(rows), build)''',
    "a while loop over an index": '''
        def run(rows):
            out, i = [], 0
            while i < len(rows):
                out.append(build(rows[i]))
                i += 1
            return out''',
    "a record builder under another name": '''
        def run(rows):
            make = make_record
            return [make(identity=f"doi:10.1/{r['id']}", kind="citation", source_id="x") for r in rows]''',
    "the first row, indexed directly": '''
        def run(rows):
            return [build(rows[0])]''',
    "a for loop that builds": '''
        def run(rows):
            out = []
            for r in rows:
                out.append(build(r))
            return out''',
    "a comprehension that builds": '''
        def run(rows):
            return [build(r) for r in rows]''',
    "a map over the rows": '''
        def run(rows):
            return list(map(build, rows))''',
    "a slice, then a loop": '''
        def run(rows):
            return [build(r) for r in rows[:2]]''',
    "a copy of the list": '''
        def run(rows):
            return members("x", Members(list(rows)), build)''',
    "a sorted copy": '''
        def run(rows):
            return members("x", Members(sorted(rows, key=lambda r: str(r))), build)''',
    "a membership test": '''
        def run(rows):
            return 7 in rows''',
    "a generator expression": '''
        def run(rows):
            return members("x", Members(list(r for r in rows)), build)''',
}


class Bypasses(unittest.TestCase):
    """Run, not scanned for: each shape fails against a view, whatever it is called and wherever it stands."""

    def run_shape(self, source: str, body):
        return fixture(source)(view(body))

    def test_each_shape_is_impossible_against_a_providers_list(self):
        for name, source in SHAPES.items():
            with self.subTest(name):
                with self.assertRaises(TypeError):
                    self.run_shape(source, BODY)

    def test_each_shape_is_impossible_even_on_a_list_of_readable_members_only(self):
        """It is not that the body is malformed: the operation does not exist, for any list a provider sends."""
        for name, source in SHAPES.items():
            with self.subTest(name):
                with self.assertRaises(TypeError):
                    self.run_shape(source, [{"id": "a"}, {"id": "b"}])

    def test_control_each_shape_is_a_real_bypass_on_the_plain_list_the_adapters_used_to_hold(self):
        """On a plain list the same source runs: the readable members only, it builds what the shape builds; with a
        malformed member in the list it loses the answer (the defect) or reads past it. This is what the views take away."""
        working = {"a filter comprehension before the decoder", "a for loop that builds", "a comprehension that builds",
                   "a map over the rows", "a slice, then a loop", "a while loop over an index", "a record builder under another name",
                   "the first row, indexed directly"}
        for name in working:
            with self.subTest(name):
                run = fixture(SHAPES[name])
                self.assertTrue(run([{"id": "a"}, {"id": "b"}]), "the shape works on readable members")
                with self.assertRaises(Exception):   # a member that is not an object loses what the shape would have built
                    run(BODY) if name != "the first row, indexed directly" else run([7, {"id": "a"}])

    def test_the_decoder_refuses_a_plain_list(self):
        with self.assertRaises(TypeError):
            members("x", [{"id": "a"}], build)
        with self.assertRaises(TypeError):
            first_member("x", [{"id": "a"}], build)

    def test_the_accessor_gives_a_list_as_members_and_an_object_as_an_obj(self):
        answer = view({"results": [{"id": "a"}], "meta": {"total": 1}, "total": 3})
        self.assertIsInstance(need("x", answer, "results"), Members)
        self.assertIsInstance(need("x", answer, "meta", kind=dict), Obj)
        self.assertEqual(need("x", answer, "total", kind=int), 3)
        with self.assertRaises(PayloadError) as why:
            need("x", answer, "results", kind=dict)
        self.assertIn("is list, not dict", str(why.exception))


class Views(unittest.TestCase):
    """The operations are absent; what is left reads each member alone."""

    def test_a_list_cannot_be_iterated_indexed_sliced_or_searched(self):
        rows = view([{"id": "a"}, 7])
        for what in (lambda: iter(rows), lambda: list(rows), lambda: rows[0], lambda: rows[:1], lambda: 7 in rows, lambda: sorted(rows),
                     lambda: next(iter(rows)), lambda: [*rows], lambda: tuple(rows), lambda: max(rows), lambda: dict(enumerate(rows)),
                     lambda: reversed(rows)):
            with self.assertRaises(TypeError):
                what()
        self.assertEqual((len(rows), bool(rows), bool(view([]))), (2, True, False), "its length and truth are all it shows")

    def test_an_object_cannot_be_walked_to_get_at_its_values(self):
        """A keyed container holds members the same way a list does (ECB's series, keyed by position): looping over
        its keys and indexing each would be the same bypass, so there is nothing to loop over."""
        series = view({"0:0": {"observations": {}}, "0:1": 7})
        for what in (lambda: iter(series), lambda: list(series), lambda: series.keys(), lambda: series.items(), lambda: series.values(),
                     lambda: sorted(series), lambda: dict(series), lambda: {**series}, lambda: [series[k] for k in series]):
            with self.assertRaises(TypeError):
                what()
        self.assertEqual((len(series), "0:0" in series, "9" in series, series.get("9", "none")), (2, True, False, "none"),
                         "what is left reads one key at a time")
        self.assertIsInstance(series["0:0"], Obj)

    def test_a_list_inside_an_object_is_a_view_too(self):
        member = view({"siblings": [{"rfilename": "a"}], "tags": ["x"], "card": {"inner": [1]}})
        self.assertIsInstance(member["siblings"], Members)
        self.assertIsInstance(member["tags"], Members)
        self.assertIsInstance(member["card"]["inner"], Members)

    def test_each_member_is_read_alone(self):
        rows = view([{"id": "a"}, 7, {"id": "b"}, "x", {"boom": 1}, {"skip": 1}])

        def read(row):
            if "boom" in row:
                raise KeyError("id")
            if "skip" in row:
                return OMIT
            return row["id"]
        self.assertEqual(rows.each(read), ["a", None, "b", None, None])

    def test_the_first_member_is_read_like_any_other_and_never_replaced_by_the_next(self):
        self.assertIsNone(view([]).first(lambda r: r["id"]))
        self.assertEqual(view([{"id": "a"}, 7]).first(lambda r: r["id"]), "a")
        for rows in ([7], [7, {"id": "a"}], [{"boom": 1}, {"id": "a"}]):
            with self.assertRaises(PayloadError) as why:
                view(rows).first(lambda r: r["id"], "src")
            self.assertEqual(str(why.exception), "src: the answer's first result cannot be read")

    def test_members_held_by_members_unfold_with_each_unreadable_holder_one_loss(self):
        """Hugging Face's siblings and ECB's data sets: the container is a member too."""
        sets = view([{"files": [{"n": 1}, {"n": 2}]}, 7, {"files": 5}, {"files": [{"n": 3}]}])
        flat = sets.expand(lambda s: need("x", s, "files"))
        self.assertEqual((len(flat), flat.each(lambda f: f["n"])), (5, [1, 2, None, None, 3]),
                         "the two holders that cannot be unfolded are one loss each; the series of the others stand")

    def test_a_keyed_container_hands_its_members_as_entries(self):
        entries = view({"a": {"v": 1}, "b": 7}).entries()
        self.assertEqual(entries.each(lambda e: (e["key"], e["value"]["v"])), [("a", 1), None])
        self.assertEqual(len(entries), 2)

    def test_plain_is_the_one_way_out_and_a_record_is_plain(self):
        answer = view({"tags": ["x", "y"], "card": {"k": [1]}})
        self.assertEqual(plain(answer["tags"]), ["x", "y"])
        self.assertEqual(plain({"a": answer["tags"], "b": (answer["card"],)}), {"a": ["x", "y"], "b": ({"k": [1]},)})
        record = make_record(identity="doi:10.1/x", kind="citation", source_id="x", authors=answer["tags"], extra={"card": answer["card"]},
                             raw=answer)
        self.assertEqual((type(record["authors"]), type(record["card"]), type(record["raw"])), (list, dict, dict))
        self.assertEqual(record["raw"], {"tags": ["x", "y"], "card": {"k": [1]}})

    def test_the_views_compare_by_what_they_hold(self):
        self.assertEqual(view({"a": [1]}), {"a": [1]})
        self.assertEqual(view([1, 2]), [1, 2])
        self.assertNotEqual(view([1, 2]), [1, 3])


class Sdmx(unittest.TestCase):
    """core/sdmx.py is outside adapters/: its data sets flattened before the decoder ran (R7-2, ECB). Now a data set is a
    member too (series_members expands them), and every helper that reads the message takes views."""

    def test_the_helpers_take_and_give_views(self):
        message = view({"structure": {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}],
                                                      "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-01-01"}]}]}},
                        "dataSets": [{"series": {"0": {"observations": {"0": [1.25]}}}}, 7, {"series": 5}, {"series": {"0": 9}}]})
        found = sdmx.series_members(message)
        self.assertEqual(len(found), 4, "one series, two data sets that cannot be unfolded, one series that is not an object")
        read = sdmx.series_reader(message)
        self.assertEqual(found.each(read), [{"key": {"FREQ": "D"}, "observations": [("2026-01-01", 1.25)], "observations_raw": {"0": [1.25]}},
                                              None, None, None])

    def test_a_data_sets_that_is_not_a_list_is_an_unreadable_message_not_an_empty_one(self):
        for body in ({"dataSets": {"series": {}}}, {"dataSets": "x"}, {"data": {"dataSets": 5}}):
            with self.subTest(body=body):
                with self.assertRaises(PayloadError):
                    sdmx.datasets(view(body))
        for body in ({}, {"dataSets": None}, {"dataSets": []}, {"data": {"dataSets": []}}, {"data": {}}):
            with self.subTest(body=body):
                self.assertEqual(len(sdmx.datasets(view(body))), 0)


if __name__ == "__main__":
    unittest.main()
