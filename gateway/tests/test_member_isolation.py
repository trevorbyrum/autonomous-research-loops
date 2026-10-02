"""Task 2b-repair-12 (R7-2, restated for the decoder): a malformed member never costs the readable members beside it, and nothing reads a provider's answer
except through its declared schema.

The defect came back three times in 2b-repair-7 and -8 (Socrata; then OpenCitations and eight more paths; then Hugging Face's file siblings and ECB's data sets):
one malformed member of a provider's list lost every readable member beside it, because an adapter held its provider's list as a plain Python list and iterated,
filtered, indexed or flattened it before the member-by-member decoder ran. Repair-8 made the list a view that could not be iterated. Repair-12 removes the deeper
cause (core/payload.py, core/schema.py): every operation declares the payload it supports, ONE decoder checks the whole payload before any adapter logic runs, and an
adapter receives only what the decoder returns:

  * a provider's list of members is a `MemberList`: every member already decoded alone, and the list cannot be iterated, indexed, sliced or searched — only read
    through members(), first_member(), take() and expand(), which isolate each member (Views and Bypasses below, run, not scanned for);
  * a provider's object is a `Rec` holding exactly its declared fields: reading another raises UndeclaredRead, which is not a member's loss (Decoded);
  * an answer is reached only through `decode(...)`: no adapter parses, subscripts or `.get`s `resp.json` (Reads below, a source check of where an answer or
    a list may leave the decoder — each place listed with its reason, so a reviewer reads it).

What the source check cannot see: a use of `.raw` or `each` whose listed reason is wrong for the list it reads. Whether a given list is one record's own data
(`own(...)` in the schema) or a set of independent candidates (`members(...)`) is the schema author's declaration; the reason beside it is where a reviewer
reads it, and tests/test_schema_corruption.py corrupts every position the schema declares. The behaviour of the lists that ARE members is tested in
tests/test_member_decoding.py.
"""
from __future__ import annotations

import ast
import functools
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from research_gateway.adapters.base import first_member, members
from research_gateway.core import schema as S, sdmx
from research_gateway.core.canonical import make_record
from research_gateway.core.payload import MemberList, OMIT, PayloadError, Rec, UndeclaredRead, Unreadable, plain

ROOT = Path(__file__).resolve().parents[1] / "research_gateway"
DOORS = ("plain",)                       # functions that hand a decoded value back as plain data
CONSTRUCTORS = ("MemberList",)           # `MemberList(items)` wraps a list the caller already holds
METHODS = ("each", "at", "unreadable")   # a MemberList's ways to a plain list or one member: each() hands back a plain list of whatever the builder returned
PRIVATE = ("_items", "_v")               # the storage of a MemberList and of a Rec
ANSWER = ("json", "json_or_none", "_parsed", "text", "body")   # what a Response holds of the provider's answer
DECODERS = ("decode", "data_xml", "flows", "dimensions_xml", "message")   # the calls an answer may be an argument of

# Every place in the gateway where the provider's answer, or a list of it, leaves the decoder, by (file, function): how many uses there are there, and why that
# is not a pass over a provider's independent members. A use added to a function already listed changes its count, so it is read, not inherited.
USES = {
    ("adapters/bea.py", "_error"): (1, "whether the error object beside the results is empty: tested for emptiness only, an object the provider left empty says nothing"),
    ("adapters/bea.py", "data"): (1, "BEA's rows are the payload of ONE table record, kept whole for its `rows` and never decoded one by one (Astra, 2b-repair-7)"),
    ("adapters/globe.py", "fetch"): (1, "the bytes of a file the caller asked to download: content, not a payload"),
    ("adapters/govinfo.py", "fetch"): (1, "the bytes of a file the caller asked to download: content, not a payload"),
    ("adapters/harvard_dataverse.py", "fetch_in"): (1, "the bytes of a file the caller asked to download: content, not a payload"),
    ("adapters/huggingface.py", "fetch"): (1, "the bytes of a file the caller asked to download: content, not a payload"),
    ("adapters/kaggle.py", "fetch"): (1, "the bytes of a file the caller asked to download: content, not a payload"),
    ("adapters/openml.py", "fetch"): (1, "the bytes of a file the caller asked to download: content, not a payload"),
    ("adapters/openml.py", "find"): (1, "an error answer that cannot be read is no `no results`: read for its error code through a schema when it is an object, below"),
    ("adapters/socrata.py", "_vouched"): (1, "the portal-vouching predicate: a guarded security check that fails closed when the portal cannot be established, not a record-producing list"),
    ("adapters/unpaywall.py", "enrich"): (3, "an answer with no location list is its one best location: a list of one, built here from the decoded object; and what each listed location is compared with"),
    ("adapters/unpaywall.py", "enrich.location"): (1, "whether this location IS the best one: the two objects as the provider sent them, compared"),
    ("core/sdmx.py", "context"): (1, "the structural context kept with each record's raw (I-8): the structure's own definitions, stored and never read"),
    ("core/sdmx.py", "datasets"): (1, "no data sets: an empty list, built here"),
    ("core/sdmx.py", "flows"): (1, "the flow's element, handed to the second decode that reads its references"),
    ("core/sdmx.py", "has_content"): (1, "whether the structure says anything: tested for emptiness only"),
    ("core/sdmx.py", "series_reader.read"): (1, "the value at a position of a dimension's lookup table: the position is the data (a series names its values by index)"),
    ("core/sdmx.py", "series_xml.convert"): (1, "one <Series> element read whole into one series, as a list of one"),
    ("harvest/registries.py", "_built"): (1, "the rows the loader reports it skipped: their reasons, never their content"),
    ("harvest/registries.py", "doaj_journals"): (1, "DOAJ's CSV dump, parsed by the csv module; each of its rows is decoded against the row schema"),
}


# ---- what a provider-data module may import (R8-3): closed over every import form, not over the names the checker happens to look for
STDLIB_ALLOWED = {"*": {"__future__", "re", "base64", "datetime", "time", "typing"}, "adapters/openaire.py": {"threading"}}   # no JSON parser, no `ast`, no `sys`/`importlib`
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


@functools.lru_cache(maxsize=None)
def parsed(path: Path, mtime_ns: int, size: int) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def source_tree(path: Path) -> ast.Module:
    """The syntax tree of a file, parsed once per version of it (the source checks below read every module of a tree many times)."""
    stat = path.stat()
    return parsed(path, stat.st_mtime_ns, stat.st_size)


def schema_value(node: ast.AST, functions_: set[str]) -> bool:
    """Whether `node` builds a schema from the constructors in core/schema.py (`S.obj(...)`, `S.text()`, ...), literals, names and the module's own functions:
    a schema is data, so a name bound to one is the module's own, however it is built. A call of anything else, an attribute of anything else (`json.loads`), a lambda:
    not."""
    if isinstance(node, (ast.Constant, ast.Name)):
        return True
    if isinstance(node, (ast.Dict, ast.Tuple, ast.List, ast.Set)):
        parts = [*getattr(node, "keys", []), *getattr(node, "values", []), *getattr(node, "elts", [])]
        return all(p is None or schema_value(p, functions_) for p in parts)
    if isinstance(node, ast.Starred):
        return schema_value(node.value, functions_)
    if isinstance(node, (ast.DictComp, ast.ListComp, ast.SetComp)):
        parts = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        return all(schema_value(p, functions_) for p in [*parts, *(g.iter for g in node.generators)])
    if isinstance(node, ast.Call):
        callee = node.func
        known = (isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name) and callee.value.id == "S") or (isinstance(callee, ast.Name) and callee.id in functions_)
        return known and all(schema_value(a, functions_) for a in [*node.args, *(k.value for k in node.keywords)])
    return False


def defined_names(path: Path) -> set[str]:
    """What the file offers other modules, and nothing it merely imports: a function, a class, a name bound to a literal (text, a number, a tuple, list, dict or set of
    them), or a name bound to a schema built from the constructors in core/schema.py (`schema_value`). A name assigned anything else may hold what the module imports
    (`loads = json.loads`, `parse = cache.json`), so it is not offered: that is a re-export by another spelling."""
    out = set()
    tree = source_tree(path)
    functions_ = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
            try:
                ast.literal_eval(node.value)
            except ValueError:
                if not schema_value(node.value, functions_):
                    continue
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                out.update(n.id for n in ast.walk(t) if isinstance(n, ast.Name))
    return out


def import_findings(root: Path = ROOT) -> list[tuple[str, str]]:
    """(file, what) for every import in a provider-data module that is not one the inventory admits. Every form is analysed, in every place it
    can stand (a function, a try block): a star import is refused (it names nothing), a stdlib module is admitted only if listed
    (STDLIB_ALLOWED: no JSON parser, so no provider answer is read by anything but Response.json), a name from adapters.base only if it is in
    its `__all__` (so no parser, module or helper it happens to import can be re-exported), and a name from any other module of the package only
    if that module defines it (not merely imports it). A package module imported AS a module (`from ..core import cache`) is analysed through what is
    done with it: only `module.name` where the module defines `name`, so `cache.json` (the parser that module imports) is refused as `from ..core.cache
    import json` is, and the module used as a value (passed on, aliased, `getattr(module, ...)`) is refused, for what it reaches cannot be bounded."""
    base = root / "adapters" / "base.py"
    api = set(literal_names(base, "__all__") or [])
    out = [] if api else [("adapters/base.py", "declares no __all__: nothing it exports is admitted")]
    for path in provider_modules(root):
        rel = path.relative_to(root).as_posix()
        strict = not rel.startswith("harvest/")
        allowed = STDLIB_ALLOWED["*"] | STDLIB_ALLOWED.get(rel, set())
        tree, modules = source_tree(path), {}   # modules: the name this file gives each package module it imports as a module
        for node in ast.walk(tree):
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
                        else:   # any other module of the package, imported as one: what is done with it is checked below
                            modules[a.asname or a.name] = where / f"{a.name}.py"
                        continue
                    if not module.exists():
                        out.append((rel, f"from {'.' * node.level}{node.module or ''} import {a.name} (no such module)"))
                    elif module.name == "base.py" and module.parent.name == "adapters":
                        if a.name not in api:
                            out.append((rel, f"from base import {a.name} (not in its __all__)"))
                    elif a.name not in defined_names(module):
                        out.append((rel, f"from {'.' * node.level}{node.module or ''} import {a.name} (not defined there: a re-export)"))
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in UNANALYSABLE_CALLS:
                out.append((rel, f"{node.func.id}()"))
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in modules:
                use = parents.get(id(node))
                if isinstance(use, ast.Attribute) and use.value is node and isinstance(node.ctx, ast.Load):
                    if use.attr not in defined_names(modules[node.id]):
                        out.append((rel, f"{node.id}.{use.attr} (not defined in {modules[node.id].relative_to(root).as_posix()}: a module's imports are not its exports)"))
                else:
                    out.append((rel, f"{node.id} (a module, used as a value: what it reaches cannot be bounded)"))
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


def reads(root: Path = ROOT) -> dict[tuple[str, str], list[str]]:
    """{(file, innermost function or <module>): each place the answer or a list of it leaves the decoder, one entry per use} for every provider-data module:
      * a door: `plain` (called, passed on or aliased, however it is imported), the `MemberList` constructor, a method that hands back a plain list or one member
        (`each`, `at`, `unreadable`), the private storage of a MemberList or a Rec;
      * `.raw` anywhere but as (part of) the value of a `raw=` argument: `raw` is for storing, and a record's raw is the one thing it is stored in;
      * the answer itself — `.json`, `.json_or_none`, `.text`, `.body`, `._parsed` of a response — anywhere but as an argument of a call to a decoder."""
    found: dict[tuple[str, str], list[str]] = {}
    package_modules = {p.stem for p in root.rglob("*.py")}
    for path in provider_modules(root):
        rel = path.relative_to(root).as_posix()
        tree = source_tree(path)
        spans = sorted(((fn.lineno, fn.end_lineno, qual) for qual, fn in functions(tree)), key=lambda s: s[1] - s[0])   # the innermost function first
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

        def where(node) -> str:
            return next((qual for a, b, qual in spans if a <= node.lineno <= b), "<module>")

        def add(node, what: str) -> None:
            found.setdefault((rel, where(node)), []).append(what)

        def stored(node) -> bool:   # inside the value of a `raw=` keyword
            while id(node) in parents:
                node = parents[id(node)]
                if isinstance(node, ast.keyword) and node.arg == "raw":
                    return True
            return False

        def decoded(node) -> bool:   # a direct argument of a call to a decoder
            parent = parents.get(id(node))
            return isinstance(parent, ast.Call) and node in parent.args and (getattr(parent.func, "id", None) in DECODERS or getattr(parent.func, "attr", None) in DECODERS)

        modules = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level for a in n.names if a.name in package_modules}   # a package module imported AS a module (`S.text` is a constructor)
        local = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in DOORS + CONSTRUCTORS:
                        local[alias.asname or alias.name] = alias.name
        annotations = {id(n) for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                       for a in (*fn.args.args, *fn.args.kwonlyargs, fn.args.vararg, fn.args.kwarg) if a is not None and a.annotation
                       for n in ast.walk(a.annotation)}
        annotations |= {id(n) for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.returns for n in ast.walk(fn.returns)}
        annotations |= {id(n) for st in ast.walk(tree) if isinstance(st, ast.AnnAssign) for n in ast.walk(st.annotation)}
        isinstance_args = {id(a) for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "isinstance" for a in n.args}
        callee = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in local and not isinstance(node.ctx, ast.Store) and id(node) not in annotations:
                kind = local[node.id]
                if id(node) in callee:
                    add(node, f"call {kind}")
                elif not (kind in CONSTRUCTORS and id(node) in isinstance_args):
                    add(node, f"reference {kind}")
            elif isinstance(node, ast.Attribute):
                of_a_module = isinstance(node.value, ast.Name) and node.value.id in modules
                if node.attr in DOORS + CONSTRUCTORS and of_a_module:
                    add(node, f"attribute {node.attr}")
                elif node.attr in METHODS:
                    add(node, f"method {node.attr}")
                elif node.attr in PRIVATE:
                    add(node, f"private {node.attr}")
                elif node.attr == "raw" and not stored(node):
                    add(node, "raw")
                elif node.attr in ANSWER and not of_a_module and not decoded(node):
                    add(node, f"answer .{node.attr}")
    return found


def reflection_in_adapters(root: Path = ROOT) -> list[tuple[str, str]]:
    """(file, what) for each adapter (and the SDMX helper) that parses JSON itself, evaluates, or reaches for a private name by reflection: other ways to a
    provider's raw answer than Response.json through a decoder."""
    out = []
    for path in sorted([*(root / "adapters").glob("*.py"), root / "core" / "sdmx.py"]):
        rel = path.relative_to(root).as_posix()
        if rel == "adapters/base.py" or not path.exists():
            continue
        for node in ast.walk(source_tree(path)):
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


class Reads(unittest.TestCase):
    """The source check that remains: where an answer, or a list of it, may leave the decoder."""

    def test_every_place_an_answer_leaves_the_decoder_is_listed_with_its_reason_and_every_listed_use_is_there(self):
        found = {k: len(v) for k, v in reads().items()}
        listed = {k: n for k, (n, _) in USES.items() if n}
        self.assertEqual(sorted(set(found) - set(listed)), [], "a provider's answer or list leaves the decoder here: say why it is one record's own data or content, "
                                                               "or read it through decode() and members()/first_member()")
        self.assertEqual(sorted(set(listed) - set(found)), [], "a listed use that is no longer there")
        self.assertEqual({k: (found[k], n) for k, n in listed.items() if found[k] != n}, {}, "(uses found, uses listed): read the new use, and update the entry's count and reason")

    def test_no_use_is_unexplained(self):
        self.assertEqual([k for k, (n, why) in USES.items() if n and len(why.split()) < 3], [])

    def test_nothing_reaches_the_storage_or_parses_json_itself(self):
        found = reads()
        self.assertEqual({k: v for k, v in found.items() if any(w.startswith("private ") for w in v)}, {})
        self.assertEqual({k: v for k, v in found.items() if "answer ._parsed" in v}, {})
        self.assertEqual(reflection_in_adapters(), [])

    def test_control_the_check_finds_an_answer_or_a_list_however_it_is_reached(self):
        """The check's own oracle: each way out is found, and what is not one is not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "adapters").mkdir()
            (root / "core").mkdir()
            (root / "core" / "schema.py").write_text("")
            (root / "core" / "sdmx.py").write_text("")
            (root / "adapters" / "new_lane.py").write_text(textwrap.dedent('''\
                import json
                from .base import decode, plain, MemberList
                from .base import plain as unwrap
                from ..core import schema as S

                def a_call(rows):
                    return plain(rows)

                def an_alias(rows):
                    out = plain
                    return out(rows)

                def passed_on(rows):
                    return list(map(plain, rows))

                def an_import_as(rows):
                    return unwrap(rows)

                def a_constructor(items):
                    return MemberList(items)

                def storage(rows):
                    return rows._items

                def reflection(rows):
                    return getattr(rows, "_items")

                def an_isinstance(rows):
                    return isinstance(rows, MemberList)

                def an_identity_pass(rows):
                    return [build(r) for r in rows.each(lambda member: member)]

                def a_position(table):
                    return table.at(0)

                def by_the_back_door(rows):
                    return object.__getattribute__(rows, "_items")

                def storing(w, make):
                    return make(raw=w.raw)

                def reading_the_raw(w):
                    return w.raw["x"]

                def decoding(resp):
                    return decode("x", S.obj({"a": S.text()}), resp.json)

                def reading_by_hand(resp):
                    return resp.json["results"]

                def reading_the_text(resp):
                    return resp.text.split()

                def a_schema_constructor():
                    return S.text()
                '''))
            found = reads(root)
            by_function = {fn: sorted(v) for (_, fn), v in found.items() if fn != "<module>"}
            self.assertEqual(by_function, {"a_call": ["call plain"], "an_alias": ["reference plain"], "passed_on": ["reference plain"],
                                           "an_import_as": ["call plain"], "a_constructor": ["call MemberList"], "storage": ["private _items"],
                                           "an_identity_pass": ["method each"], "a_position": ["method at"], "reading_the_raw": ["raw"],
                                           "reading_by_hand": ["answer .json"], "reading_the_text": ["answer .text"]})
            self.assertEqual(reflection_in_adapters(root), [("adapters/new_lane.py", "import json"),
                                                            ("adapters/new_lane.py", "getattr() of a private name"),
                                                            ("adapters/new_lane.py", "__getattribute__")])


class Imports(unittest.TestCase):
    """R8-3 (Astra, 2b-repair-8): the inventory above names the doors by what a module imports, so an import it cannot read — a star, a
    name re-exported by the client, `__import__` — walks a door in unseen, and two such mutants of OpenCitations passed every structural test.
    The rule is now closed over import forms: what is not admitted by name is refused, and an import that cannot be analysed is refused.
    Each of the reviewer's two complete mutants is a regression below, each with a permitted-import control.

    R9-3 (Astra, 2b-repair-9; closed in 2b-repair-10b): a package module imported AS a module was admitted and not looked into, so
    `from ..core import cache as provider_helpers` reached `provider_helpers.json.loads` — a parser — with every structural test passing. A module
    import is now analysed through what is done with it (`module.name` where the module defines `name`; anything else is refused), and a name a
    module only assigns from something it imports is no more offered than a name it imports."""

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
    OC_IMPORT = "from .base import OMIT, Client, check, decode, first_member, members"
    OC_READ = '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], resp.json)\n'
    OC_RETURN = '    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, rows, lambda row: _link(key, row))}\n'
    # the reviewer's first mutant: the rows are filtered with plain() before the decoder runs; the checker saw no `plain` because nothing named it
    STAR = [(OC_IMPORT, "from .base import *"),
            (OC_READ + OC_RETURN, '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], [row for row in plain(resp.json) if row.get(key)])\n' + OC_RETURN)]
    # the second: the body is parsed and filtered by a parser imported from the client, which uses no door at all
    PARSER = [(OC_IMPORT, OC_IMPORT + ", json as provider_json"),
              (OC_READ + OC_RETURN, '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], [row for row in provider_json.loads(resp.body) if row.get(key)])\n' + OC_RETURN)]

    # the third (R9-3): the body is parsed by a parser that an admitted package module imports, reached as an attribute of that module
    CACHE_IMPORT = "from ..core import cache as provider_helpers"
    CACHE_MODULE = [(OC_IMPORT, OC_IMPORT + "\n" + CACHE_IMPORT),
                    (OC_READ + OC_RETURN, '    rows = decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], [row for row in provider_helpers.json.loads(resp.body) if row.get(key)])\n' + OC_RETURN)]
    # and what the same import does when it only uses what the module defines
    DOI_LINE = '    return normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)'
    MODULE_USE = [(OC_IMPORT, OC_IMPORT + "\nfrom ..core import identity as ids"),
                  (DOI_LINE, '    return ids.normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)')]

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

    def test_a_parser_an_admitted_module_imports_is_refused_and_so_is_the_reviewers_complete_mutant(self):
        """R9-3: `provider_helpers.json.loads` — the parser `core/cache.py` imports, reached through the module — and no structural test saw it."""
        with tempfile.TemporaryDirectory() as tmp:
            findings = import_findings(self.tree(Path(tmp), **{self.OC: self.CACHE_MODULE}))
        self.assertEqual(findings, [("adapters/opencitations.py", "provider_helpers.json (not defined in core/cache.py: a module's imports are not its exports)")])

    def test_control_a_module_used_for_what_it_defines_is_not_refused(self):
        """The same import, using `identity.normalize_doi` (a function that module defines): nothing is refused, and no door is used."""
        real = reads()
        with tempfile.TemporaryDirectory() as tmp:
            root = self.tree(Path(tmp), **{self.OC: self.MODULE_USE})
            found = reads(root)
            self.assertEqual((import_findings(root), sorted(k for k in found if found[k] != real.get(k))), ([], []))

    def test_control_the_permitted_imports_are_not_refused(self):
        """What the same two edits do when they only use what the client exports: nothing is refused for the import — the one thing a name
        from `__all__` can still be is an unlisted door, which the inventory above catches by name, as it always did."""
        permitted = [(self.OC_IMPORT, self.OC_IMPORT + ", quote as q, identified")]   # a permitted re-export (quote), and a helper in __all__
        spelled_out = [(self.OC_IMPORT, self.OC_IMPORT + ", plain"), self.STAR[1]]
        real = reads()

        def changed(root: Path) -> list:
            found = reads(root)
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
            "the client's private parser": ("from .base import _parsed", [("adapters/new.py", "from base import _parsed (not in its __all__)")]),
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
            "a parser an admitted module imports, as its attribute": ("from ..core import cache\nrows = cache.json.loads('[]')",
                                                                     [("adapters/new.py", "cache.json (not defined in core/cache.py: a module's imports are not its exports)")]),
            "the same through an alias of the import": ("from ..core import cache as helpers\nrows = helpers.json.loads('[]')",
                                                        [("adapters/new.py", "helpers.json (not defined in core/cache.py: a module's imports are not its exports)")]),
            "a module's own import under another name": ("from ..core import canonical\nrows = canonical.PayloadError",
                                                         [("adapters/new.py", "canonical.PayloadError (not defined in core/canonical.py: a module's imports are not its exports)")]),
            "a module passed to getattr": ("from ..core import cache\nloads = getattr(cache, 'json')",
                                           [("adapters/new.py", "cache (a module, used as a value: what it reaches cannot be bounded)")]),
            "a module aliased by assignment": ("from ..core import cache\nhelpers = cache\nrows = helpers.json",
                                               [("adapters/new.py", "cache (a module, used as a value: what it reaches cannot be bounded)")]),
            "a module's name rebound": ("from ..core import cache\ncache = 5",
                                        [("adapters/new.py", "cache (a module, used as a value: what it reaches cannot be bounded)")]),
        }
        for name, (source, want) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                root = self.tree(Path(tmp))
                (root / "adapters" / "new.py").write_text(f"from __future__ import annotations\n{source}\n", encoding="utf-8")
                self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"], want)   # what is found in the new file, whatever else the tree holds
        with tempfile.TemporaryDirectory() as tmp:   # and the forms that are admitted: the names the client exports, a stdlib module that is listed
            root = self.tree(Path(tmp))
            (root / "adapters" / "new.py").write_text("from __future__ import annotations\nimport re\nfrom .base import Client, members, quote as q\n"
                                                      "from ..core.canonical import make_record\nfrom . import crossref\n"
                                                      "from ..core import canonical, identity as ids\nbuilt = canonical.make_record\nnormal = ids.normalize_doi\n",
                                                      encoding="utf-8")
            self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"], [])
        with tempfile.TemporaryDirectory() as tmp:   # a name that a module assigns from what it imports is no more offered than the import itself
            root = self.tree(Path(tmp))
            (root / "core" / "helper.py").write_text("import json\nloads = json.loads\nLIMIT = 5\n", encoding="utf-8")
            (root / "adapters" / "new.py").write_text("from __future__ import annotations\nfrom ..core.helper import loads, LIMIT\nfrom ..core import helper\n"
                                                      "x = helper.loads\ny = helper.LIMIT\n", encoding="utf-8")
            self.assertEqual([f for f in import_findings(root) if f[0] == "adapters/new.py"],
                             [("adapters/new.py", "from ..core.helper import loads (not defined there: a re-export)"),
                              ("adapters/new.py", "helper.loads (not defined in core/helper.py: a module's imports are not its exports)")])

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
ROW = S.obj({"id": S.text(), "n": S.any_()})


def decoded(body):
    """A provider's list of members, as the decoder hands it to an adapter."""
    return S.decode("x", S.members(ROW), body)


def fixture(source: str):
    """A function `run(rows)` compiled from adapter-shaped source, with the names an adapter has in hand."""
    scope = {"members": members, "make_record": make_record, "OMIT": OMIT, "first_member": first_member, "build": build, "MemberList": MemberList}
    exec(textwrap.dedent(source), scope)
    return scope["run"]


def build(row):
    return make_record(identity=f"doi:10.1/{row['id']}", kind="citation", source_id="x")


# the shapes the old name scan missed (Astra, 2b-repair-7 review), and the forms it did catch
SHAPES = {
    "a filter comprehension before the decoder": '''
        def run(rows):
            rows = [r for r in rows if r["id"]]
            return members("x", MemberList(rows), build)''',
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
            return members("x", MemberList(list(rows)), build)''',
    "a sorted copy": '''
        def run(rows):
            return members("x", MemberList(sorted(rows, key=lambda r: str(r))), build)''',
    "a membership test": '''
        def run(rows):
            return 7 in rows''',
    "a generator expression": '''
        def run(rows):
            return members("x", MemberList(list(r for r in rows)), build)''',
}


class Bypasses(unittest.TestCase):
    """Run, not scanned for: each shape fails against a provider's list as the decoder hands it over, whatever it is called and wherever it stands."""

    def test_each_shape_is_impossible_against_a_providers_list(self):
        for name, source in SHAPES.items():
            with self.subTest(name):
                with self.assertRaises(TypeError):
                    fixture(source)(decoded(BODY))

    def test_each_shape_is_impossible_even_on_a_list_of_readable_members_only(self):
        """It is not that the body is malformed: the operation does not exist, for any list a provider sends."""
        for name, source in SHAPES.items():
            with self.subTest(name):
                with self.assertRaises(TypeError):
                    fixture(source)(decoded([{"id": "a"}, {"id": "b"}]))

    def test_control_each_shape_is_a_real_bypass_on_the_plain_list_the_adapters_used_to_hold(self):
        """On a plain list the same source runs: the readable members only, it builds what the shape builds; with a malformed member in the list it loses the
        answer (the defect) or reads past it. This is what the member list takes away."""
        working = {"a filter comprehension before the decoder", "a for loop that builds", "a comprehension that builds",
                   "a map over the rows", "a slice, then a loop", "a while loop over an index", "a record builder under another name",
                   "the first row, indexed directly"}
        for name in working:
            with self.subTest(name):
                run = fixture(SHAPES[name])
                self.assertTrue(run([{"id": "a"}, {"id": "b"}]), "the shape works on readable members")
                with self.assertRaises(Exception):   # a member that is not an object loses what the shape would have built
                    run(BODY) if name != "the first row, indexed directly" else run([7, {"id": "a"}])

    def test_the_helpers_refuse_a_plain_list(self):
        with self.assertRaises(TypeError):
            members("x", [{"id": "a"}], build)
        with self.assertRaises(TypeError):
            first_member("x", [{"id": "a"}], build)

    def test_the_decoder_gives_a_list_of_members_as_a_member_list_and_a_record_s_own_list_as_a_list(self):
        answer = S.decode("x", S.obj({"results": S.members(ROW), "tags": S.own(S.text()), "meta": S.obj({"total": S.whole()})}),
                          {"results": [{"id": "a"}], "tags": ["x"], "meta": {"total": 1}})
        self.assertIsInstance(answer["results"], MemberList)
        self.assertEqual(answer["tags"], ["x"])
        self.assertIsInstance(answer["meta"], Rec)


class Views(unittest.TestCase):
    """The operations are absent; what is left reads each member alone."""

    def test_a_list_cannot_be_iterated_indexed_sliced_or_searched(self):
        rows = decoded([{"id": "a"}, 7])
        for what in (lambda: iter(rows), lambda: list(rows), lambda: rows[0], lambda: rows[:1], lambda: 7 in rows, lambda: sorted(rows),
                     lambda: next(iter(rows)), lambda: [*rows], lambda: tuple(rows), lambda: max(rows), lambda: dict(enumerate(rows)),
                     lambda: reversed(rows)):
            with self.assertRaises(TypeError):
                what()
        self.assertEqual((len(rows), bool(rows), bool(decoded([]))), (2, True, False), "its length and truth are all it shows")

    def test_an_object_holds_its_declared_fields_and_nothing_else(self):
        rec = S.decode("x", S.obj({"id": S.text(), "inner": S.obj({"n": S.whole()})}), {"id": "a", "inner": {"n": 1}, "undeclared": 5})
        self.assertEqual((rec["id"], rec["inner"]["n"], rec.raw["undeclared"]), ("a", 1, 5))
        for what in (lambda: rec["undeclared"], lambda: rec.get("undeclared"), lambda: rec["inner"]["m"]):
            with self.assertRaises(UndeclaredRead):
                what()
        for what in (lambda: iter(rec), lambda: list(rec)):
            with self.assertRaises(TypeError):
                what()
        self.assertFalse(issubclass(UndeclaredRead, (PayloadError, KeyError, AttributeError, TypeError, ValueError, IndexError)),
                         "an undeclared read is a failure, never a member's loss: no builder's net catches it")

    def test_a_keyed_container_hands_its_members_as_entries(self):
        entries = S.decode("x", S.entries(S.obj({"v": S.whole()})), {"a": {"v": 1}, "b": 7})
        self.assertEqual(entries.each(lambda e: (e["key"], e["value"]["v"])), [("a", 1), None])
        self.assertEqual(len(entries), 2)

    def test_a_list_inside_a_member_is_a_member_list_too(self):
        member = S.decode("x", S.obj({"siblings": S.members(ROW), "tags": S.own(S.text())}), {"siblings": [{"id": "a"}], "tags": ["x"]})
        self.assertIsInstance(member["siblings"], MemberList)

    def test_each_member_is_read_alone(self):
        rows = S.decode("x", S.members(S.obj({"id": S.text(), "boom": S.any_(), "skip": S.any_()})),
                        [{"id": "a"}, 7, {"id": "b"}, "x", {"boom": 1}, {"skip": 1}])

        def read(row):
            if row["boom"]:
                raise KeyError("id")
            if row["skip"]:
                return OMIT
            return row["id"]
        self.assertEqual(rows.each(read), ["a", None, "b", None, None])

    def test_the_first_member_is_read_like_any_other_and_never_replaced_by_the_next(self):
        self.assertIsNone(decoded([]).first(lambda r: r["id"]))
        self.assertEqual(decoded([{"id": "a"}, 7]).first(lambda r: r["id"]), "a")
        for rows in ([7], [7, {"id": "a"}]):
            with self.assertRaises(PayloadError) as why:
                decoded(rows).first(lambda r: r["id"], "src")
            self.assertEqual(str(why.exception), "src: the answer's first result cannot be read")
        def boom(row):
            raise KeyError("id")
        with self.assertRaises(PayloadError):   # the first cannot be built
            decoded([{"id": "a"}, {"id": "b"}]).first(boom)

    def test_members_held_by_members_unfold_with_each_unreadable_holder_one_loss(self):
        """Hugging Face's siblings and ECB's data sets: the container is a member too."""
        sets = S.decode("x", S.members(S.obj({"files": S.members(S.obj({"n": S.whole()}))})), [{"files": [{"n": 1}, {"n": 2}]}, 7, {"files": 5}, {"files": [{"n": 3}]}])
        flat = sets.expand(lambda s: s["files"])
        self.assertEqual((len(flat), flat.each(lambda f: f["n"])), (5, [1, 2, None, None, 3]),
                         "the two holders that cannot be unfolded are one loss each; the series of the others stand")

    def test_a_decoded_value_is_plain_data_in_a_record(self):
        answer = S.decode("x", S.obj({"tags": S.own(S.text()), "card": S.obj({"k": S.any_()})}), {"tags": ["x", "y"], "card": {"k": [1]}})
        self.assertEqual(plain(answer["tags"]), ["x", "y"])
        self.assertEqual(plain({"a": answer["tags"], "b": (answer["card"],)}), {"a": ["x", "y"], "b": ({"k": [1]},)})
        record = make_record(identity="doi:10.1/x", kind="citation", source_id="x", authors=answer["tags"], extra={"card": answer["card"]}, raw=answer)
        self.assertEqual((type(record["authors"]), type(record["card"]), type(record["raw"])), (list, dict, dict))
        self.assertEqual(record["raw"], {"tags": ["x", "y"], "card": {"k": [1]}})

    def test_an_unreadable_member_says_why_and_what_it_was(self):
        (bad,) = decoded([7]).unreadable()
        self.assertIsInstance(bad, Unreadable)
        self.assertEqual(bad.value, 7)
        self.assertIn("where an object belongs", bad.reason)


class Sdmx(unittest.TestCase):
    """core/sdmx.py is outside adapters/: its data sets flattened before the decoder ran (R7-2, ECB). Now a data set is a member too (series_members expands
    them), and every helper that reads the message takes the decoded message."""

    def test_the_helpers_take_and_give_decoded_values(self):
        message = sdmx.message("ecb", {"structure": {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}],
                                                                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-01-01"}]}]}},
                                       "dataSets": [{"series": {"0": {"observations": {"0": [1.25]}}}}, 7, {"series": 5}, {"series": {"0": 9}}]})
        found = sdmx.series_members(message)
        self.assertEqual(len(found), 4, "one series, two data sets that cannot be unfolded, one series that is not an object")
        read = sdmx.series_reader(message)
        self.assertEqual(found.each(read), [{"key": {"FREQ": "D"}, "observations": [("2026-01-01", 1.25)], "observations_raw": {"0": [1.25]}}, None, None, None])

    def test_a_data_sets_that_is_not_a_list_is_an_unreadable_message_not_an_empty_one(self):
        for body in ({"dataSets": {"series": {}}}, {"dataSets": "x"}, {"data": {"dataSets": 5}}):
            with self.subTest(body=body):
                with self.assertRaises(PayloadError):
                    sdmx.message("ecb", body)
        for body in ({}, {"dataSets": None}, {"dataSets": []}, {"data": {"dataSets": []}}, {"data": {}}):
            with self.subTest(body=body):
                self.assertEqual(len(sdmx.datasets(sdmx.message("ecb", body))), 0)


if __name__ == "__main__":
    unittest.main()
