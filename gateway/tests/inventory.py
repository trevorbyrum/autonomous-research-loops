"""THE inventory of the gateway's provider-input discipline (task 2b-repair-14; Astra Gate D #2, checklist item 6). One owner, one table, one set of scans.

Before this file there were three overlapping inventories — of the openers (tests/test_openers.py: every parse call and who calls an opener), of the reads (tests/test_member_isolation.py: every
place a decoded answer leaves the decoder, with `plain`, `.raw`, `each` ...) and of the client's reads of a response's bytes (tests/test_opaque_provenance.py) — each with its own scan, table and
spellings, and none claiming exactly what it showed. This module replaces them. It is what the trust model B of INVARIANTS B-1 relies on for first-party adapters (the operator's ruling of
2026-10-02): the adapters are trusted, reviewed code; this inventory is how a reviewer SEES what that code is doing with provider input, and a change that adds a site fails until a person
classifies it here, beside its reason.

WHAT IT IS. Five scans of the package's own source (`gateway/research_gateway`), each finding SITES — (kind, file, function, what) with a count:

  parse        a reference to a parser entry point of a library (`json.loads`, `json.JSONDecoder`, `csv.reader`, `xml.etree.ElementTree.XMLParser`, `tomllib.load` ...), a call or not,
               under any import spelling the module's own import statements resolve (`import json as j`, `from json import loads as l`, `from xml.etree import ElementTree as ET`, `json.decoder.JSONDecoder`),
               in every module of the package. A parser OBJECT is a parse site where it is made: `json.JSONDecoder().decode(x)` and `d = json.JSONDecoder(); d.raw_decode(x)` are found at `json.JSONDecoder`
               (the spelling the 13c review found the old scan missed).
  opener       a reference to one of core/wire.py's openers (`open_json`, `open_xml`, `open_csv`) from outside it: who may turn a provider's bytes into structure.
  door         where a decoded answer, or a list of it, leaves the decoder in a provider-data module (adapters, core/sdmx.py, core/identity.py, the harvest loaders): a MemberList / Sealed /
               Passive / Rec construction, `each`, `at`, `unreadable`, `without`, the two sanctioned questions `empty` and `same_as`, `.raw` outside a `raw=` argument, a response's
               `download`, the private storage of a decoded value. The scan the 12/13a/13c rounds called the reads.
  body         a read of a Response's `_body`, the bytes: the client's own bookkeeping and the decoder.
  materialize  a reference to `plain`, the ONE materialization (core/payload.py), anywhere in the package but payload.py.
  dynamic      `__import__`, `importlib.import_module`, `eval`, `exec`, `compile`, anywhere: code the scans cannot read.
  network      a reference to a library's connection-making entry point (`urllib.request.Request`, `urlopen`, `build_opener` ...): every place the package reaches over a network. The one that
               receives a PROVIDER's bytes is adapters/base.py `Transport`; the others are the gateway's own client, its secret store and its alerts, and are classified as such.
  response     a construction of a `Response`, the one carrier of a provider's bytes into adapters: the transport (bodies read by `_read_body`), the test transport, and the client's own
               refusals (empty bodies).
  netread      a read of a connection's stream in adapters/base.py: `_read_body`, and nowhere else.

Each site found must be listed in SITES with a ROLE and a reason, and each listed site must be found; ROLES says where each role may stand (RULES, held by tests/test_inventory.py). The guards
that are not inventories live here too, because they are this module's scans' neighbours and share their syntax machinery: `import_findings` (what a provider-data module may import),
`reflection_in_adapters` (the spellings that reach for a payload by reflection).

WHAT IT IS NOT. It is a finite syntax guard over this package's own source, written for review. It resolves names through each module's own import statements and finds the listed entry points
and doors; it does not follow a value through a variable (`m = json; m.loads(x)` is not found, and tests/test_inventory.py says so), through a container or a call's result, through a name
computed at run time or through code built as a string, and it proves nothing about arbitrary Python: `dynamic` sites are found so that a person looks at them, not because they are analysed. It
is evidence that the code a reviewer reads is the code that opens provider bytes, materializes them and compares them, not a proof that no other code could. A site is a place a person has
looked at; the independence of the looking is the review's (Gate C), and the independent oracle (tests/oracle) is the evidence the behaviour is right.
"""
from __future__ import annotations

import ast
import functools
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "research_gateway"

# ----------------------------------------------------------------------------------------------------------------------------------------------------- what the scans look for
# parser entry points by (module, name): a library call that turns text or bytes into structure
PARSERS = {"json": {"loads", "load", "JSONDecoder"}, "json.decoder": {"JSONDecoder"}, "json.scanner": {"make_scanner", "py_make_scanner"},
           "csv": {"reader", "DictReader", "Sniffer"},
           "xml.etree.ElementTree": {"fromstring", "XML", "parse", "iterparse", "XMLParser", "XMLPullParser", "fromstringlist", "TreeBuilder"},
           "xml.etree.cElementTree": {"fromstring", "XML", "parse", "iterparse", "XMLParser", "XMLPullParser", "fromstringlist"},
           "xml.dom.minidom": {"parseString", "parse"}, "xml.dom.pulldom": {"parseString", "parse"}, "xml.sax": {"parseString", "parse", "make_parser"}, "xml.parsers.expat": {"ParserCreate"},
           "html.parser": {"HTMLParser"}, "tomllib": {"load", "loads"}, "ast": {"literal_eval"}, "pickle": {"loads", "load", "Unpickler"}, "marshal": {"loads", "load"},
           "yaml": {"load", "safe_load"}, "plistlib": {"loads", "load"}, "configparser": {"ConfigParser"}}
INDIRECT_NAMES = {name for names in PARSERS.values() for name in names} | {"decode", "raw_decode"}   # a constant that names a parser, given to getattr
NETWORK = {"urllib.request": {"Request", "urlopen", "build_opener", "OpenerDirector", "HTTPRedirectHandler"}, "http.client": {"HTTPConnection", "HTTPSConnection", "HTTPResponse"},
           "socket": {"create_connection", "socket"}}   # connection-making entry points (DNS lookups and exception classes carry no payload and are not listed)
STREAM_READS = ("read", "read1", "readinto", "readline", "recv")
OPENERS = ("open_json", "open_xml", "open_csv")   # core/wire.py: the one place a provider's bytes become structure
DYNAMIC_CALLS = ("__import__", "eval", "exec", "compile")
DYNAMIC_DOTTED = ("importlib.import_module", "importlib.__import__")

# the doors of a decoded value in a provider-data module
CONSTRUCTORS = ("MemberList", "Sealed", "Passive", "Rec")   # `MemberList(items)` wraps a list the caller already holds; a Sealed, a Passive or a Rec an adapter builds is no decoder-issued value (core/payload.py)
METHODS = ("each", "at", "unreadable", "without", "empty", "same_as")   # a MemberList's ways to a plain list or one member (each() hands back a plain list of whatever the builder returned), Sealed.without(), and the two sanctioned questions about a decoded object: did it hold anything (empty), is it the same provider object as another (same_as)
PRIVATE = ("_items", "_v", "_value", "_raw", "_body", "_frozen")   # the storage of a MemberList, a Rec, a Passive/Sealed/Unreadable and a Response
ANSWER = ("json", "json_or_none", "_parsed", "_body", "text", "body", "download", "content")   # what a Response held or holds of the provider's answer (the first are gone: nothing is there to find)
DECODERS = ("decode", "data_xml", "flows", "dimensions_xml", "message")   # the calls an answer may be an argument of
MATERIALIZER = "plain"

# what a provider-data module may import (R8-3): closed over every import form, not over the names the checker happens to look for
STDLIB_ALLOWED = {"*": {"__future__", "re", "base64", "datetime", "time", "typing"}, "adapters/openaire.py": {"threading"}}   # no JSON parser, no `ast`, no `sys`/`importlib`
WIRE = "wire"                               # core/wire.py: the byte openers are the decoder's (2b-repair-13c); of the provider modules only the snapshot loader, which reads files and not a Response, opens its lines with them
OPENER_USERS = {"harvest/openalex_snapshot.py"}
UNANALYSABLE_CALLS = ("eval", "exec", "compile", "vars", "globals", "locals", "__import__")


# ----------------------------------------------------------------------------------------------------------------------------------------------------- syntax machinery
@functools.lru_cache(maxsize=None)
def parsed(path: Path, mtime_ns: int, size: int) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def source_tree(path: Path) -> ast.Module:
    """The syntax tree of a file, parsed once per version of it (the source checks below read every module of a tree many times)."""
    stat = path.stat()
    return parsed(path, stat.st_mtime_ns, stat.st_size)


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


def dotted(node) -> str | None:
    """`a.b.c` for a chain of attributes on a name, else None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else None


def aliases_of(tree: ast.AST) -> dict:
    """What each name the module's import statements bind stands for: `import json as j` → j: json; `from json import loads as l` → l: json.loads; `from ..core import wire` → wire: core.wire."""
    out: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                out[a.asname or a.name] = f"{node.module or ''}.{a.name}".lstrip(".")
    return out


def references(tree: ast.AST):
    """(node, the dotted name it resolves to through the module's imports) for every Name and Attribute read that resolves to anything: a call or not, every prefix of a chain."""
    aliases = aliases_of(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            name = dotted(node)
            if name:
                head, _, rest = name.partition(".")
                yield node, (aliases[head] + "." + rest if head in aliases else name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in aliases:
            yield node, aliases[node.id]


def innermost(tree: ast.AST):
    """The function that holds a node, by line: its qualified name, `<module>` when none."""
    spans = sorted(((fn.lineno, fn.end_lineno, q) for q, fn in functions(tree)), key=lambda s: s[1] - s[0])
    return lambda node: next((q for a, b, q in spans if a <= node.lineno <= b), "<module>")


def modules(root: Path):
    """(relative path, tree, where) for every module of the package."""
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        yield path.relative_to(root).as_posix(), tree, innermost(tree)


def provider_modules(root: Path = ROOT) -> list[Path]:
    """The modules that read a provider's answer: every adapter but the client, the SDMX helper, the doi.org registration-agency lookup (core/identity.py: a lookup the
    router makes itself, with no adapter around it, which the first inventory missed — R12-1), and the harvest loaders."""
    return sorted([*(p for p in (root / "adapters").glob("*.py") if p.name not in ("base.py", "__init__.py")), root / "core" / "sdmx.py", root / "core" / "identity.py",
                   *(p for p in (root / "harvest").glob("*.py") if p.name != "__init__.py")])


# ----------------------------------------------------------------------------------------------------------------------------------------------------- the five scans
def parse_sites(root: Path = ROOT) -> Counter:
    """{(file, function, the parser entry point): references} over every module of the package. See the module docstring for what a site is."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        for node, full in references(tree):
            module, _, attr = full.rpartition(".")
            if attr in PARSERS.get(module, ()):
                out[(rel, where(node), full)] += 1
    return out


def opener_sites(root: Path = ROOT) -> Counter:
    """{(file, function, opener): references} to core/wire.py's openers from outside core/wire.py."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        if rel == "core/wire.py":
            continue
        for node, full in references(tree):
            module, _, attr = full.rpartition(".")
            if attr in OPENERS and (module.rpartition(".")[2] == WIRE or module == WIRE):
                out[(rel, where(node), attr)] += 1
    return out


def body_sites(root: Path = ROOT) -> Counter:
    """{(file, function, "_body"): reads} of a Response's bytes, everywhere but the HTTP front door (api/http.py has a request body of its own) and core/payload.py (where the storage is declared)."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        if rel.startswith("api/") or rel == "core/payload.py":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "_body":
                out[(rel, where(node), "_body")] += 1
    return out


def materializer_sites(root: Path = ROOT) -> Counter:
    """{(file, function, "plain"): references} to the one materialization, in every module but core/payload.py (which defines it): imported by name, under another name, or as an attribute of the module."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        if rel == "core/payload.py":
            continue
        aliases = aliases_of(tree)
        bound = {name for name, full in aliases.items() if full.rpartition(".")[2] == MATERIALIZER and full.rpartition(".")[0].rpartition(".")[2] in ("payload", "")}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id in bound:
                out[(rel, where(node), MATERIALIZER)] += 1
            elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr == MATERIALIZER:
                head = dotted(node.value)
                if head and aliases.get(head.split(".")[0], head).rpartition(".")[2] in ("payload",):
                    out[(rel, where(node), MATERIALIZER)] += 1
    return out


def dynamic_sites(root: Path = ROOT) -> Counter:
    """{(file, function, the call): calls} of `__import__`, `eval`, `exec`, `compile`, `importlib.import_module` and `getattr` of a name that is a parser's: code the scans cannot read."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        aliases = aliases_of(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = dotted(node.func)
            if isinstance(node.func, ast.Name) and node.func.id in DYNAMIC_CALLS:
                out[(rel, where(node), node.func.id)] += 1
            elif name:
                head, _, rest = name.partition(".")
                full = aliases[head] + ("." + rest if rest else "") if head in aliases else name
                if full in DYNAMIC_DOTTED:
                    out[(rel, where(node), full)] += 1
            if isinstance(node.func, ast.Name) and node.func.id == "getattr" and any(isinstance(a, ast.Constant) and a.value in INDIRECT_NAMES for a in node.args[1:2]):
                out[(rel, where(node), "getattr of a parser")] += 1
    return out


def network_sites(root: Path = ROOT) -> Counter:
    """{(file, function, entry point): references} to a library's connection-making entry points, anywhere in the package."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        for node, full in references(tree):
            module, _, attr = full.rpartition(".")
            if attr in NETWORK.get(module, ()):
                out[(rel, where(node), full)] += 1
    return out


def response_sites(root: Path = ROOT) -> Counter:
    """{(file, function, "Response"): constructions} of the client's Response, anywhere in the package (in adapters/base.py by its bare name, elsewhere through the module's imports)."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        aliases = aliases_of(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = dotted(node.func)
            if name is None:
                continue
            head, _, rest = name.partition(".")
            full = aliases[head] + ("." + rest if rest else "") if head in aliases else name
            if (rel == "adapters/base.py" and full == "Response") or full.endswith("base.Response"):
                out[(rel, where(node), "Response")] += 1
    return out


def netread_sites(root: Path = ROOT) -> Counter:
    """{(file, function, the read): references} to a stream read (`read`, `read1`, `readinto`, `readline`, `recv`) in adapters/base.py, the module that holds the transport."""
    out: Counter = Counter()
    for rel, tree, where in modules(root):
        if rel != "adapters/base.py":
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in STREAM_READS:
                out[(rel, where(node), node.attr)] += 1
    return out


def door_sites(root: Path = ROOT) -> dict[tuple[str, str], list[str]]:
    """{(file, innermost function or <module>): each place the answer or a list of it leaves the decoder, one entry per use} for every provider-data module:
      * a construction of a MemberList, a Sealed, a Passive or a Rec, however imported (`isinstance` tests and annotations are not constructions);
      * a method that hands back a plain list or one member (`each`, `at`, `unreadable`), takes fields out of a sealed object (`without`), or asks the two sanctioned questions (`empty`, `same_as`);
      * the private storage of a MemberList, a Rec, a Passive, a Sealed or a Response;
      * `.raw` anywhere but as (part of) the value of a `raw=` argument: `raw` is for storing, and a record's raw is the one thing it is stored in;
      * the answer itself — `.json`, `.json_or_none`, `.text`, `.body`, `._parsed`, `.download` of a response — anywhere but as an argument of a call to a decoder (`download` is a door by design)."""
    found: dict[tuple[str, str], list[str]] = {}
    package_modules = {p.stem for p in root.rglob("*.py")}
    for path in provider_modules(root):
        rel = path.relative_to(root).as_posix()
        tree = source_tree(path)
        where = innermost(tree)
        parents = {id(child): parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}

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

        imported_modules = {a.asname or a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level for a in n.names if a.name in package_modules}   # a package module imported AS a module (`S.text` is a constructor)
        local = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in CONSTRUCTORS:
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
                elif id(node) not in isinstance_args:
                    add(node, f"reference {kind}")
            elif isinstance(node, ast.Attribute):
                of_a_module = isinstance(node.value, ast.Name) and node.value.id in imported_modules
                if node.attr in CONSTRUCTORS and of_a_module:
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


def scan(root: Path = ROOT) -> Counter:
    """Every site of every kind: {(kind, file, function, what): count}. The table SITES is held equal to this."""
    out: Counter = Counter()
    for kind, found in (("parse", parse_sites(root)), ("opener", opener_sites(root)), ("body", body_sites(root)), ("materialize", materializer_sites(root)), ("dynamic", dynamic_sites(root)),
                        ("network", network_sites(root)), ("response", response_sites(root)), ("netread", netread_sites(root))):
        for (rel, function, what), n in found.items():
            out[(kind, rel, function, what)] += n
    for (rel, function), whats in door_sites(root).items():
        for what, n in Counter(whats).items():
            out[("door", rel, function, what)] += n
    return out


# ----------------------------------------------------------------------------------------------------------------------------------------------------- the guards beside the scans
def literal_names(path: Path, name: str) -> list[str] | None:
    """The strings of the module-level `name = (...)` of the file, or None when it declares none."""
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets) and isinstance(node.value, (ast.Tuple, ast.List)):
            return [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


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
    (STDLIB_ALLOWED: no JSON parser, so no provider answer is read by anything but the decoder), a name from adapters.base only if it is in
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
        tree, imported = source_tree(path), {}   # imported: the name this file gives each package module it imports as a module
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
                if module.name == f"{WIRE}.py" and rel not in OPENER_USERS:
                    out += [(rel, f"from {'.' * node.level}{node.module or ''} import {a.name} (the byte openers are the decoder's)") for a in node.names]
                    continue
                for a in node.names:
                    if a.name == WIRE and where.is_dir() and rel not in OPENER_USERS:
                        out.append((rel, f"from {'.' * node.level}{node.module or ''} import {a.name} (the byte openers are the decoder's)"))
                        continue
                    if a.name.startswith("_"):   # a private name is the module's own: the decoder's openers, a class's storage — never an adapter's (2b-repair-13a)
                        out.append((rel, f"from {'.' * node.level}{node.module or ''} import {a.name} (a private name)"))
                        continue
                    if where.is_dir() and (where / f"{a.name}.py").exists():
                        if a.name == "base":   # the client is imported by name, for then its `__all__` decides what is reached; as a module, anything is
                            out.append((rel, "from . import base (as a module: import what it exports by name)"))
                        else:   # any other module of the package, imported as one: what is done with it is checked below
                            imported[a.asname or a.name] = where / f"{a.name}.py"
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
            if isinstance(node, ast.Name) and node.id in imported:
                use = parents.get(id(node))
                if isinstance(use, ast.Attribute) and use.value is node and isinstance(node.ctx, ast.Load):
                    if use.attr not in defined_names(imported[node.id]):
                        out.append((rel, f"{node.id}.{use.attr} (not defined in {imported[node.id].relative_to(root).as_posix()}: a module's imports are not its exports)"))
                else:
                    out.append((rel, f"{node.id} (a module, used as a value: what it reaches cannot be bounded)"))
    return sorted(set(out))


def parser_imports_outside_wire(root: Path = ROOT) -> list[tuple[str, str]]:
    """(file, import) for every import of a CSV reader or an XML/HTML parsing library outside core/wire.py, whatever it is bound to. ElementTree is imported by core/payload.py and core/schema.py for
    the element TYPE, which opens nothing, and by core/wire.py, which parses with it; the other formats' readers are wire's alone."""
    out = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(source_tree(path)):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for name in names:
                if name.split(".")[0] == "csv" or name.startswith(("xml.sax", "xml.dom", "xml.parsers", "html.parser", "lxml")):
                    out.append((rel, name))
                if name == "xml.etree.ElementTree" and rel not in ("core/wire.py", "core/payload.py", "core/schema.py"):
                    out.append((rel, name))
    return out


def reflection_in_adapters(root: Path = ROOT) -> list[tuple[str, str]]:
    """(file, what) for each adapter (and the SDMX helper) that parses JSON itself, evaluates, or reaches for a private name by reflection: other ways to a
    provider's raw answer than a decoder."""
    out = []
    for path in sorted([*(root / "adapters").glob("*.py"), root / "core" / "sdmx.py", root / "core" / "identity.py"]):
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
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("getattr", "setattr", "delattr", "hasattr") and any(
                    isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value in ANSWER for a in node.args[1:2]):
                out.append((rel, f"{node.func.id}() of an answer accessor"))   # Astra's spelling (2b-repair-12 R12-5): there is nothing public to find any more, and it is still not written
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("getattr", "setattr", "delattr", "hasattr") and len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant):
                out.append((rel, f"{node.func.id}() of a name computed at run time"))
            elif isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("dir", "vars", "globals", "locals"):
                out.append((rel, f"{node.func.id}()"))
            elif isinstance(node, ast.Attribute) and node.attr == "__dict__":
                out.append((rel, "__dict__"))
    return out


# ----------------------------------------------------------------------------------------------------------------------------------------------------- the classifications
# A ROLE says what a site is for, and RULES (below) where a role may stand: a reviewer classifies a new site by choosing the role, and the rule for that role is then held against it.
ROLES = {
    "PAYLOAD-OPENER": "opens a provider's bytes; stands in core/wire.py alone",
    "DECODER": "the decoder reads a provider's answer through its declared schema; stands in core/schema.py alone",
    "LOADER": "a harvest loader reads a local file of provider records with the strict openers (it has no Response)",
    "BOOKKEEPING": "the client's own accounting of a call (a count of results for the call log), never a decision about provider data",
    "CALLER": "input that is a caller's, not a provider's: a request body, command-line arguments, an MCP host's message",
    "GATEWAY": "the gateway's own API answering its own client",
    "AUTH": "the claims of a token the gateway signed, the secret store's answer: credentials, not provider data",
    "CONFIG": "the operator's own settings and registry files",
    "CLIENT-READ": "the client reads a response's bytes for the CALL (failure text, an HTML refusal, a diagnostic): it can only make a lane unavailable or describe the call, never produce a record or an answer",
    "SEALED-STORE": "the bytes or the raw object leave only sealed, to be stored and never read",
    "DOWNLOAD-BYTES": "the bytes of a file a caller asked to download: content handed on sealed to the router, not a payload",
    "OWN-DATA": "a list or a table that is one record's own data, built or kept whole here, not a pass over independent members",
    "FAIL-CLOSED-GUARD": "a predicate that fails closed when it cannot establish what it asks (nothing it cannot read vouches for anything)",
    "POSITION-LOOKUP": "a lookup whose position is the data (a series names its dimension values by index)",
    "REPORTING": "reports what was skipped: reasons, never content",
    "SANCTIONED-PREDICATE": "Rec.empty: whether a decoded object held anything; used only at the reviewed provider-shape predicates",
    "SANCTIONED-COMPARISON": "Rec.same_as: whether two decoded provider objects are the same one; used only for the intended comparison, never for a value an adapter wrote",
    "MATERIALIZER": "the one materialization (`plain`): where the gateway serializes or stores a result",
    "DISCOVERY": "imports the gateway's own adapter modules by name from its own package directory",
    "TEST-TRANSPORT": "the test transport copies a canned answer into a new Response",
    "PROVIDER-TRANSPORT": "receives a provider's bytes over the network: adapters/base.py `Transport`, whose every body comes from `_read_body` (the message is complete or it is an error Response)",
    "ALERT-SINK": "the gateway's own outbound alert (a webhook post): no provider data, the response is not read",
    "EMPTY-BODY": "a Response the client makes itself (a refusal, a redirect failure, an HTML challenge): it carries no provider body",
}


def _in(*places):
    return lambda file, function, what: (file, function) in places


RULES = {
    "PAYLOAD-OPENER": lambda file, function, what: file == "core/wire.py",
    "DECODER": lambda file, function, what: file == "core/schema.py",
    "LOADER": lambda file, function, what: file.startswith("harvest/"),
    "BOOKKEEPING": lambda file, function, what: file == "adapters/base.py",
    "CLIENT-READ": lambda file, function, what: file == "adapters/base.py" and what == "_body",
    "TEST-TRANSPORT": lambda file, function, what: file == "adapters/base.py" and function.startswith("FakeTransport."),
    "SEALED-STORE": lambda file, function, what: what in ("_body", "method without", "raw"),
    "DOWNLOAD-BYTES": lambda file, function, what: what == "answer .download" and function.startswith("fetch"),
    "SANCTIONED-PREDICATE": lambda file, function, what: what == "method empty",
    "SANCTIONED-COMPARISON": lambda file, function, what: what == "method same_as",
    "MATERIALIZER": _in(("core/router.py", "execute"), ("core/cache.py", "Cache.put_record"), ("harvest/index.py", "upsert")),
    "DISCOVERY": _in(("adapters/__init__.py", "load_all")),
    "CALLER": lambda file, function, what: file in ("api/http.py", "clients/cli.py", "clients/mcp_stdio.py"),
    "GATEWAY": lambda file, function, what: file == "clients/http_client.py",
    "PROVIDER-TRANSPORT": lambda file, function, what: file == "adapters/base.py" and (function in ("<module>", "_read_body") or function.startswith("Transport.")),
    "ALERT-SINK": lambda file, function, what: file == "core/alerts.py",
    "EMPTY-BODY": lambda file, function, what: file == "adapters/base.py" and what == "Response",
    "AUTH": lambda file, function, what: file in ("core/principals.py", "core/secrets.py"),
    "CONFIG": lambda file, function, what: file in ("app.py", "registry/load.py"),
    "OWN-DATA": lambda file, function, what: what == "call MemberList",
    "FAIL-CLOSED-GUARD": _in(("adapters/socrata.py", "_vouched")),
    "POSITION-LOOKUP": lambda file, function, what: what == "method at",
    "REPORTING": lambda file, function, what: what == "method unreadable",
}
# the sanctioned predicates stand exactly where the operator's ruling of 2026-10-02 puts them
SANCTIONED_EMPTY = {("adapters/bea.py", "_error"), ("adapters/unpaywall.py", "enrich"), ("core/sdmx.py", "has_content")}
SANCTIONED_SAME_AS = {("adapters/unpaywall.py", "enrich.location")}

# (kind, file, function, what) -> (count, role, why)
SITES = {
    # ---------------------------------------------------------------- parse: every parser entry point of a library, in the whole package
    ("parse", "core/wire.py", "open_json", "json.loads"): (1, "PAYLOAD-OPENER", "a provider's JSON: UTF-8, no NaN/Infinity, finite floats and exact integers, each name once, nesting bounded"),
    ("parse", "core/wire.py", "open_xml", "xml.etree.ElementTree.XMLParser"): (1, "PAYLOAD-OPENER", "a provider's SDMX-ML: expat's well-formedness, UTF-8 read as UTF-8, a 1.x declaration, no DOCTYPE, nesting bounded"),
    ("parse", "core/wire.py", "<module>", "xml.etree.ElementTree.TreeBuilder"): (1, "PAYLOAD-OPENER", "the tree builder the XML opener hands expat, which refuses a document type declaration where expat would read an internal subset and skip an external one"),
    ("parse", "api/http.py", "Handler._body", "json.loads"): (1, "CALLER", "a caller's request body to the gateway, checked at the front door (app.py: plain JSON, no NaN/Infinity)"),
    ("parse", "clients/cli.py", "payload_from", "json.loads"): (2, "CALLER", "the operator's own command-line arguments"),
    ("parse", "clients/http_client.py", "GatewayClient._call", "json.loads"): (2, "GATEWAY", "the gateway's own API answering its own command-line client"),
    ("parse", "clients/http_client.py", "raw_observation", "json.loads"): (1, "GATEWAY", "the gateway's own API answering its own command-line client"),
    ("parse", "clients/mcp_stdio.py", "main", "json.loads"): (1, "CALLER", "an MCP host's JSON-RPC message on standard input"),
    ("parse", "core/principals.py", "Grants.verify", "json.loads"): (1, "AUTH", "the claims of a token the gateway signed itself, read after its signature verified"),
    ("parse", "core/secrets.py", "VaultBackend._fetch", "json.loads"): (1, "AUTH", "the secret store's answer, which the operator runs: credentials, not provider data"),
    ("parse", "core/secrets.py", "VaultBackend._not_found", "json.loads"): (1, "AUTH", "the secret store's error document"),
    ("parse", "app.py", "load_settings", "tomllib.load"): (1, "CONFIG", "the operator's settings file"),
    ("parse", "registry/load.py", "read_seed", "tomllib.load"): (1, "CONFIG", "the operator's source registry file"),
    # ---------------------------------------------------------------- opener: who calls core/wire.py's openers
    ("opener", "core/schema.py", "_open_json", "open_json"): (1, "DECODER", "the decoder: every provider's JSON answer"),
    ("opener", "core/schema.py", "parse_xml", "open_xml"): (1, "DECODER", "the decoder: SDMX-ML messages"),
    ("opener", "core/schema.py", "decode_csv", "open_csv"): (1, "DECODER", "the decoder: DOAJ's CSV dump"),
    ("opener", "adapters/base.py", "_count_of", "open_json"): (1, "BOOKKEEPING", "the call log's count of results: bookkeeping, through the same opener, so an answer the decoder refuses has no count either"),
    ("opener", "harvest/openalex_snapshot.py", "read_snapshot", "open_json"): (1, "LOADER", "the OpenAlex snapshot's JSON lines: each line opened on its own, a refused line reported"),
    # ---------------------------------------------------------------- body: the client's reads of a response's bytes, and the decoder's
    ("body", "core/schema.py", "_open_json", "_body"): (1, "DECODER", "the decoder: a provider's JSON"),
    ("body", "core/schema.py", "_bytes_or_text", "_body"): (1, "DECODER", "the decoder: the bytes the SDMX-ML and CSV openers read"),
    ("body", "adapters/base.py", "Response.download", "_body"): (1, "SEALED-STORE", "returns the bytes sealed, for a file the caller asked to download: content handed to the router and never read"),
    ("body", "adapters/base.py", "Response.__repr__", "_body"): (1, "CLIENT-READ", "the length of the body, for a diagnostic"),
    ("body", "adapters/base.py", "_text_of", "_body"): (1, "CLIENT-READ", "the text of a 401/403 body, to classify the failure of the CALL (calllog.classify); it never leaves the client"),
    ("body", "adapters/base.py", "_count_of", "_body"): (2, "BOOKKEEPING", "the number of results, for the call log, through the decoder's own opener: a count and nothing else"),
    ("body", "adapters/base.py", "check", "_body"): (2, "CLIENT-READ", "the first bytes of a success answer, to refuse an HTML page wearing it: it can only make a lane unavailable, never produce a record or an empty answer"),
    ("body", "adapters/base.py", "FakeTransport.request", "_body"): (1, "TEST-TRANSPORT", "the test transport copies a canned answer's body into a new Response"),
    # ---------------------------------------------------------------- materialize: the one materialization
    ("materialize", "core/router.py", "execute", "plain"): (1, "MATERIALIZER", "the answer and everything cached or written from it are plain where the router serializes them (after every lane has run and every selection, coverage and licence decision is made)"),
    ("materialize", "core/cache.py", "Cache.put_record", "plain"): (1, "MATERIALIZER", "the cache persists a record: its provenance becomes data where it is stored"),
    ("materialize", "harvest/index.py", "upsert", "plain"): (1, "MATERIALIZER", "the storage boundary: a loader's record carries its provenance sealed until the index writes it, and is plain data from here"),
    # ---------------------------------------------------------------- dynamic: code the scans cannot read
    ("dynamic", "adapters/__init__.py", "load_all", "importlib.import_module"): (1, "DISCOVERY", "imports each adapter module of the package by name from the package's own directory: the gateway's code, not provider data"),
    # ---------------------------------------------------------------- network: every place the package reaches over a network, and which of them receives a provider's bytes
    ("network", "adapters/base.py", "<module>", "urllib.request.HTTPRedirectHandler"): (1, "PROVIDER-TRANSPORT", "the redirect handler that hands a 3xx back to the metered client instead of following it underneath it"),
    ("network", "adapters/base.py", "<module>", "urllib.request.build_opener"): (1, "PROVIDER-TRANSPORT", "the one opener of provider requests, built with the no-redirect handler"),
    ("network", "adapters/base.py", "Transport.request", "urllib.request.Request"): (1, "PROVIDER-TRANSPORT", "the request a provider's call makes: the only one in the package that receives a provider's bytes"),
    ("network", "clients/http_client.py", "GatewayClient._call", "urllib.request.Request"): (1, "GATEWAY", "the gateway's own command-line client calling the gateway's own API"),
    ("network", "clients/http_client.py", "GatewayClient._call", "urllib.request.urlopen"): (1, "GATEWAY", "the gateway's own command-line client calling the gateway's own API"),
    ("network", "core/alerts.py", "ntfy_sender.send", "urllib.request.Request"): (1, "ALERT-SINK", "the alert post to the operator's notification endpoint"),
    ("network", "core/alerts.py", "ntfy_sender.send", "urllib.request.urlopen"): (1, "ALERT-SINK", "the alert post to the operator's notification endpoint"),
    ("network", "core/secrets.py", "<module>", "urllib.request.HTTPRedirectHandler"): (1, "AUTH", "the secret store's opener refuses redirects: credentials go nowhere else"),
    ("network", "core/secrets.py", "<module>", "urllib.request.build_opener"): (1, "AUTH", "the secret store's opener, which the operator runs: credentials, not provider data"),
    ("network", "core/secrets.py", "VaultBackend._fetch", "urllib.request.Request"): (1, "AUTH", "the request for a secret from the store the operator runs"),
    # ---------------------------------------------------------------- response: where a Response, the carrier of a provider's bytes into adapters, is made
    ("response", "adapters/base.py", "Transport.request", "Response"): (5, "PROVIDER-TRANSPORT", "the transport's Responses: every body in them is `_read_body`'s (the message complete) or empty; checked line by line by tests/test_inventory.py"),
    ("response", "adapters/base.py", "FakeTransport.add", "Response"): (1, "TEST-TRANSPORT", "the test transport records a canned answer"),
    ("response", "adapters/base.py", "FakeTransport.request", "Response"): (2, "TEST-TRANSPORT", "the test transport copies a canned answer into a new Response"),
    ("response", "adapters/base.py", "Client._call", "Response"): (4, "EMPTY-BODY", "a refusal (breaker, budget, policy) or a redirect failure: the client's own words for it, no provider body"),
    ("response", "adapters/base.py", "check", "Response"): (1, "EMPTY-BODY", "an HTML page wearing a success status becomes an unavailable answer with no body"),
    # ---------------------------------------------------------------- netread: the one read of a provider's stream
    ("netread", "adapters/base.py", "_read_body", "read"): (1, "PROVIDER-TRANSPORT", "the bounded read of a response's body, followed by the framing's completeness check (RFC 9112 §6.3)"),
    # ---------------------------------------------------------------- door: where a decoded answer leaves the decoder in a provider-data module
    ("door", "adapters/bea.py", "data", "raw"): (1, "SEALED-STORE", "BEA's rows are the payload of ONE table record, kept whole for its `rows` and never decoded one by one (Astra, 2b-repair-7)"),
    ("door", "adapters/bea.py", "_error", "method empty"): (1, "SANCTIONED-PREDICATE", "whether the error object BEA states beside its results says anything: an empty `{}` is no error"),
    ("door", "adapters/core.py", "_record", "method without"): (1, "SEALED-STORE", "the record's raw is the payload less its full text (I-7): a sealed object less one field, handed on to be stored and never read"),
    ("door", "adapters/globe.py", "fetch", "answer .download"): (1, "DOWNLOAD-BYTES", "the bytes of a file the caller asked to download: content, not a payload"),
    ("door", "adapters/govinfo.py", "fetch", "answer .download"): (1, "DOWNLOAD-BYTES", "the bytes of a file the caller asked to download: content, not a payload"),
    ("door", "adapters/harvard_dataverse.py", "fetch_in", "answer .download"): (1, "DOWNLOAD-BYTES", "the bytes of a file the caller asked to download: content, not a payload"),
    ("door", "adapters/huggingface.py", "fetch", "answer .download"): (1, "DOWNLOAD-BYTES", "the bytes of a file the caller asked to download: content, not a payload"),
    ("door", "adapters/kaggle.py", "fetch", "answer .download"): (1, "DOWNLOAD-BYTES", "the bytes of a file the caller asked to download: content, not a payload"),
    ("door", "adapters/openml.py", "fetch", "answer .download"): (1, "DOWNLOAD-BYTES", "the bytes of a file the caller asked to download: content, not a payload"),
    ("door", "adapters/socrata.py", "_vouched", "method each"): (1, "FAIL-CLOSED-GUARD", "the portal-vouching predicate: a guarded security check that fails closed when the portal cannot be established, not a record-producing list"),
    ("door", "adapters/unpaywall.py", "enrich", "call MemberList"): (1, "OWN-DATA", "an answer with no location list is its one best location: a list of one, built here from the decoded object"),
    ("door", "adapters/unpaywall.py", "enrich", "method empty"): (1, "SANCTIONED-PREDICATE", "whether the best location the answer states holds anything (an empty one is none)"),
    ("door", "adapters/unpaywall.py", "enrich.location", "method same_as"): (1, "SANCTIONED-COMPARISON", "whether this listed location IS the best one the answer also states: the two decoded objects, compared (the provider repeating itself)"),
    ("door", "core/sdmx.py", "datasets", "call MemberList"): (1, "OWN-DATA", "no data sets: an empty list, built here"),
    ("door", "core/sdmx.py", "flows", "raw"): (1, "SEALED-STORE", "the flow's element, handed to the second decode that reads its references"),
    ("door", "core/sdmx.py", "has_content", "method empty"): (1, "SANCTIONED-PREDICATE", "whether a structure the message states says anything (an empty `{}` structure says nothing)"),
    ("door", "core/sdmx.py", "series_reader.read", "method at"): (1, "POSITION-LOOKUP", "the value at a position of a dimension's lookup table: the position is the data (a series names its values by index)"),
    ("door", "core/sdmx.py", "series_xml.convert", "call MemberList"): (1, "OWN-DATA", "one <Series> element read whole into one series, as a list of one"),
    ("door", "harvest/registries.py", "_built", "method unreadable"): (1, "REPORTING", "the rows the loader reports it skipped: their reasons, never their content"),
}
