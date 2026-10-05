"""The supported-source contract, version 1 (tasks 2q-a-repair-3 and 2q-a-repair-4; docs/gen2/SOURCE-CONTRACT.md, ratified by the operator on 2026-10-05).

The architecture metrics are exact over a DECLARED subset of Python (Gate D #4, option B), not over arbitrary Python. This module is the one place the subset
is stated as code: the refusal categories, the records of the transformations and external terminals the subset allows (resolved identity, allowed argument
shape, effect on the metrics), and the one inventoried dynamic loader. `load(root)` indexes the production inventory of BOTH services once
(tools/gen2_source_index.py) and runs the contract over it; every diagnostic names file, line, construct and remediation. A refusal happens BEFORE any
measurement and nothing waives it: no numeric exemption, identity transition or ledger entry exists for it, and no command writes a baseline or a ledger
over refused source. Discovering another valid Python form outside this subset is a new refusal test, not an extension of the analyser.

The contract does not interpret arbitrary Python. It constrains what decides measured identities, bindings and attribution: lexical definitions, class
declarations and bases, imports and exports, decorators, the receiver of a method's self-calls, reflective writes to class and module namespaces, and dynamic
loading. Ordinary control flow, data processing, `getattr` on data, `type(x)` and data-field initialisation are not restricted.

It is CLOSED, not a list of known-bad forms (task 2q-a-repair-4; Astra's 2q-a-repair-3 review F2): every construct that can bind or rebind a name in a module or class
namespace, or change an attribute or member of a measured module or class, is one of the recognised forms below, each with an effect the index records, and anything else
is refused (SRC-FORM-UNRECOGNISED) in whichever structural position it appears. The dispatchers are
  * the walker's table of syntax forms (tools/gen2_source_index.py `FORMS`): a node class with no entry is refused;
  * `Contract.CLASS_FORMS`: each kind of binding in a class body, with its rule (a hook name, a family method's name, an alias of a method), or refused;
  * `Contract.STORE_FORMS`: each kind of store base (the receiver, data, a class, a module or namespace, a namespace's dictionary), or refused;
  * the call forms: class-making calls, `setattr` and its spellings, loader calls, mutators of a namespace's dictionary.
A new form gets in only by a contract amendment, never by the tool's default.

Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import collections
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gen2_source_index as source
from gen2_source_index import Binding, ClassFact, Diagnostic, Facts, FileIndex, FunctionFact, Member, Unresolved

CONTRACT_VERSION = 1
CONTRACT_ID = f"source-contract/{CONTRACT_VERSION}"

# (row of the contract's table, what is refused): the closed list of refusal categories. A diagnostic's category is always one of these.
CATEGORIES = {
    "SRC-INV-PARSE": ("source inventory", "a production file that does not parse"),
    "SRC-INV-MODULE": ("source inventory", "two files with one module name, or a path that is not a module path"),
    "SRC-INV-UNTRACKED": ("source inventory", "a production candidate that is neither tracked nor ignored"),
    "SRC-DEF-DUPLICATE": ("function identity", "two definitions of one name in one lexical scope, in any branches"),
    "SRC-DEF-REBOUND": ("function identity", "a defined name bound again in its scope"),
    "SRC-CLASS-CONDITIONAL": ("class and method declarations", "a class declared inside a compound statement"),
    "SRC-METHOD-CONDITIONAL": ("class and method declarations", "a method declared inside a compound statement of its class"),
    "SRC-CLASS-DYNAMIC": ("class and method declarations", "a class made by a call, not a class statement"),
    "SRC-METHOD-ALIAS": ("class and method declarations", "a class-body assignment that aliases a method"),
    "SRC-STAR-IMPORT": ("imports and exports", "a star import, in either service"),
    "SRC-ALL-DYNAMIC": ("imports and exports", "an `__all__` that is not one module-level literal list or tuple of strings"),
    "SRC-BINDING-COMPETING": ("imports and exports", "a name with competing or conditional bindings used where one is needed"),
    "SRC-NAME-UNRESOLVED": ("imports and exports", "a first-party name that cannot be followed to one definition"),
    "SRC-BASE-SHAPE": ("inheritance", "a base that is not a name or an attribute chain"),
    "SRC-BASE-ALIAS": ("inheritance", "a base bound by an assignment, a function or a module"),
    "SRC-BASE-SUBSCRIPT": ("inheritance", "a subscripted base that is not a modelled typing form"),
    "SRC-BASE-MIXED": ("inheritance", "a project base mixed with an external base the contract does not model"),
    "SRC-BASE-HIERARCHY": ("inheritance", "an inconsistent or cyclic hierarchy, or a base in the other service"),
    "SRC-CLASS-HOOK": ("inheritance", "a class keyword (a metaclass) or a hook that changes classes or attribute lookup"),
    "SRC-DECORATOR-UNKNOWN": ("decorators and descriptors", "a decorator with no record in the contract"),
    "SRC-DECORATOR-SHADOWED": ("decorators and descriptors", "a decorator name whose identity cannot be established"),
    "SRC-DECORATOR-ARGS": ("decorators and descriptors", "a known decorator with an argument shape the record does not allow"),
    "SRC-RECEIVER-REBOUND": ("receiver calls and attributes", "a method's receiver name bound again inside the method"),
    "SRC-ATTR-OVERRIDE": ("receiver calls and attributes", "a data write that overrides a method of the class family"),
    "SRC-REFLECTIVE": ("receiver calls and attributes", "reflective mutation of a class, module or method namespace"),
    "SRC-LOADER-UNINVENTORIED": ("non-graph mechanisms", "a dynamic import or code-loading call with no inventory entry"),
    "SRC-LOADER-INVENTORY": ("non-graph mechanisms", "an inventoried loader whose implementation changed, or whose discovered files differ from the inventory"),
    "SRC-FORM-UNRECOGNISED": ("closure of every row", "a syntax form, binding or store with no recognised effect"),
}

# --- transformations and external terminals ------------------------------------------------------------------------

MODELLED_TYPING = ("typing.Generic", "typing.Protocol")        # a base whose subscript is erased, and which adds no project method
MIXABLE_EXTERNAL = ("builtins.object", *MODELLED_TYPING)       # an external base a project base may be mixed with
HOOKS = ("__init_subclass__", "__mro_entries__", "__getattribute__")   # a class that defines one can change classes or every attribute lookup
LOADER_CALLS = ("importlib.import_module", "builtins.__import__", "importlib.reload", "importlib.util.spec_from_file_location", "importlib.util.module_from_spec",
                "importlib.machinery.SourceFileLoader", "runpy.run_module", "runpy.run_path", "builtins.exec", "builtins.eval", "builtins.compile",
                "pkgutil.iter_modules", "pkgutil.walk_packages")
SET_CALLS = ("builtins.setattr", "builtins.delattr", "builtins.object.__setattr__", "builtins.object.__delattr__", "builtins.type.__setattr__")
MUTATORS = ("update", "setdefault", "pop", "popitem", "clear", "append", "extend", "insert", "remove", "sort", "reverse")
STRUCTURAL = ("__class__", "__bases__", "__dict__", "__mro__")
FORM_REMEDY = source.FORM_REMEDY
REFLECTIVE_FIX = "declare the class or module member in source: a namespace changed at run time is not in the facts"


def _no_arguments(node: ast.expr) -> bool:
    return not isinstance(node, ast.Call)


def _dataclass_arguments(node: ast.expr) -> bool:
    return not isinstance(node, ast.Call) or (not node.args and all(k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords))


def _one_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Call) and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and not node.keywords


def _serial_arguments(node: ast.expr) -> bool:
    return (isinstance(node, ast.Call) and len(node.args) == 1 and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
            and all(k.arg == "within" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, bool) for k in node.keywords))


@dataclass(frozen=True)
class Transform:
    identity: str                  # the resolved dotted identity (never the spelling)
    applies_to: tuple[str, ...]    # class | function (any def) | method (a def directly in a class body)
    shape: str                     # the allowed argument shape, as the contract prints it
    effect: str                    # what it does, as far as the metrics are concerned
    allowed: Callable[[ast.expr], bool]
    role: str = ""                 # the role it gives a method: property | static | class


TRANSFORMS = (
    Transform("dataclasses.dataclass", ("class",), "`@dataclass`, `@dataclass()` or `@dataclass(frozen=True)`; no other argument, so never `slots=True`, `eq=False`, `unsafe_hash=True` or `order=True`",
              "returns the decorated class object; generates `__init__`, `__repr__` and `__eq__` as methods of that class unless its body defines them; sets `__hash__` by the "
              "dataclasses documentation (eq is true): to `None` unless the body defines `__hash__` for `@dataclass` and `@dataclass()`, to a generated method unless the body "
              "defines `__hash__` for `frozen=True`, which also generates `__setattr__` and `__delattr__`; each annotated field (not a `ClassVar`, `InitVar` or `KW_ONLY`) is an "
              "instance attribute the generated `__init__` writes, so a field named like a method of the class family is refused as SRC-ATTR-OVERRIDE",
              _dataclass_arguments),
    Transform("builtins.property", ("method",), "no argument", "the name becomes a data attribute: `self.name()` calls its value, never a project method of that name",
              _no_arguments, role="property"),
    Transform("builtins.staticmethod", ("method",), "no argument", "the method keeps its name and has no receiver", _no_arguments, role="static"),
    Transform("builtins.classmethod", ("method",), "no argument", "the method keeps its name; its receiver is the class, so its calls are not instance self-calls", _no_arguments, role="class"),
    Transform("contextlib.contextmanager", ("function", "method"), "no argument", "the name stays bound to a callable that returns a context manager; the authored body is the "
              "generator and is measured as written", _no_arguments),
    Transform("functools.wraps", ("function",), "exactly one positional name, no keyword", "copies metadata onto the wrapper it decorates; the wrapper's body is measured as written",
              _one_name),
    Transform("gen2.gateway_client.client._serial", ("method",), "one positional string literal, and optionally `within=True` or `within=False`",
              "the method name stays bound to a callable wrapper (`run`, measured as written) that calls the decorated function; the decorated body is the method's",
              _serial_arguments),
)
BY_IDENTITY = {t.identity: t for t in TRANSFORMS}


@dataclass(frozen=True)
class Loader:
    file: str
    function: str
    call: str
    discovery: str
    argument: str
    package: str
    skip_names: tuple[str, ...]
    skip_prefix: str
    condition: str
    discovered: tuple[str, ...]
    fingerprint: str = ""   # SHA-256 of the reviewed implementation (`fingerprint()` below)


LOADERS = (
    Loader("gateway/research_gateway/adapters/__init__.py", "load_all", "importlib.import_module", "pkgutil.iter_modules", "f'{__name__}.{info.name}'", "research_gateway.adapters",
           ("base",), "_", "info.name in _SKIP or info.name.startswith('_')",
           ("bea", "bis", "bls", "census", "core", "crossref", "datacite", "doaj", "doi_org", "ecb", "europepmc", "fred", "globe", "govinfo", "harvard_dataverse", "huggingface",
            "kaggle", "openaire", "openalex_snapshot", "opencitations", "openml", "qdr", "semanticscholar", "socrata", "unpaywall", "wms"),
           "d92736324e8162a92f838d37cfc5f55df496ae08374f1b1627857558522ff842"),
)


class SourceRefused(Exception):
    """The production source is outside the contract: `diagnostics` say where and why; nothing may be measured, recorded or certified."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        super().__init__(f"{len(diagnostics)} source contract refusal(s)")
        self.diagnostics = diagnostics


# --- decorators ----------------------------------------------------------------------------------------------------

def decorator_transform(path: str, scope, node: ast.expr, applies: str) -> Transform:
    """The record of one decorator, or Unresolved with the refusal category."""
    target = node.func if isinstance(node, ast.Call) else node
    identity = source.identify(path, scope, target)
    record = BY_IDENTITY.get(identity)
    if record is None or applies not in record.applies_to and not (applies == "method" and "function" in record.applies_to):
        raise Unresolved("SRC-DECORATOR-UNKNOWN", f"{identity} is not a transformation the contract records for a {applies}")
    if not record.allowed(node):
        raise Unresolved("SRC-DECORATOR-ARGS", f"{identity} is recorded only as {record.shape}; here it is {ast.unparse(node)}")
    return record


def class_owner_ok(index: FileIndex, cls: ClassFact) -> bool:
    """Whether a class is an owner a qualified locator may descend through: no metaclass or other keyword, and only recorded class decorators."""
    if cls.node.keywords:
        return False
    try:
        for decorator in cls.node.decorator_list:
            decorator_transform(index.path, cls.parent, decorator, "class")
    except Unresolved:
        return False
    return True


# --- the check -----------------------------------------------------------------------------------------------------

def load(root: Path) -> Facts:
    """Index the production inventory of both services once and run the contract over it. The Facts carry every diagnostic; `require` refuses them."""
    paths = source.production_files(root)
    texts, indexes, found, absent = {}, {}, [], set()
    for path in paths["all"]:
        if not (root / path).is_file():
            absent.add(path)   # tracked but absent from the working tree: not measured, and the ledger asks for the retirement of what it held
            continue
        try:
            texts[path] = (root / path).read_text(encoding="utf-8")
            indexes[path] = source.index_text(path, texts[path])
        except (SyntaxError, UnicodeDecodeError, ValueError) as exc:
            found.append(Diagnostic("SRC-INV-PARSE", path, getattr(exc, "lineno", 0) or 0, f"the file does not parse: {exc}", "fix the syntax, or remove the file from the production inventory"))
    paths = {key: [p for p in value if p not in absent] for key, value in paths.items()}
    facts = Facts(root, paths, texts, indexes)
    facts.diagnostics.extend(found)
    inventory(facts)
    Contract(facts).run()
    facts.diagnostics.sort(key=lambda d: (d.file, d.line, d.category, d.construct))
    return facts


def require(facts: Facts) -> Facts:
    if facts.diagnostics:
        raise SourceRefused(facts.diagnostics)
    return facts


def inventory(facts: Facts) -> None:
    seen: dict[str, str] = {}
    for path in facts.paths["all"]:
        module = source.module_name(path)
        if not all(part.isidentifier() for part in module.split(".")):
            facts.diagnose("SRC-INV-MODULE", path, 0, f"{path} is not a module path ({module})", "rename the file so every path part is an identifier")
        if module in seen:
            facts.diagnose("SRC-INV-MODULE", path, 0, f"{path} and {seen[module]} are both module {module}", "keep one: a module and a package of one name are ambiguous")
        seen[module] = path
    for path in source.untracked_candidates(facts.root):
        facts.diagnose("SRC-INV-UNTRACKED", path, 0, f"{path} is a production candidate that git does not track", "`git add` the file (a local check must see what CI will see)")


KINDS = ("class", "namespace", "ns_dict", "instance_dict", "unknown", "receiver", "data")   # what an expression denotes, worst first (a name with several bindings is the worst of them)
PURE_READERS = ("builtins.len", "builtins.sorted", "builtins.list", "builtins.tuple", "builtins.set", "builtins.frozenset", "builtins.iter", "builtins.enumerate", "builtins.reversed")
READ_METHODS = ("copy", "count", "index")   # the methods of a list that read it
CALLABLE = ("method", "static", "class", "property")   # the roles of a member that is a `def`; any other member is data (or a slot)
FIELD_MARKERS = ("typing.ClassVar", "dataclasses.InitVar", "dataclasses.KW_ONLY")   # an annotation that makes a name no instance field


def normalised(node: ast.AST | list | object):
    """A structural form of syntax that ignores positions, comments and docstrings, and every field that is empty: the same loader on another Python's tree dumps the same."""
    if isinstance(node, ast.AST):
        return [type(node).__name__, [[name, normalised(value)] for name, value in ast.iter_fields(node) if not (value is None or (isinstance(value, list) and not value))]]
    if isinstance(node, list):
        return [normalised(item) for item in node]
    return repr(node)


def without_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    return body[1:] if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str) else body


def fingerprint(tree: ast.Module, function: str) -> str | None:
    """The reviewed implementation of a loader, as a SHA-256: the normalised syntax of the function and of every statement of its module that is not another definition
    (its imports, its constants, any rebinding of a name it reads), docstrings aside. None when the module has no such function."""
    parts, found = [], False
    for statement in without_docstring(tree.body):
        if isinstance(statement, source.FUNCTIONS) and statement.name == function:
            found = True
            parts.append(normalised(ast.FunctionDef(**{**{name: getattr(statement, name) for name in statement._fields}, "body": without_docstring(statement.body)})))
        elif not isinstance(statement, (*source.FUNCTIONS, ast.ClassDef)):
            parts.append(normalised(statement))
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode("utf-8")).hexdigest() if found else None


class Contract:
    """The rows of the contract over one set of facts. One method per row; each only adds diagnostics and fills the facts the metrics read."""

    CLASS_FORMS = {"def": "member_method", "class": "member_data", "assign": "member_data", "augassign": "member_data", "target": "member_data", "walrus": "member_data",
                   "delete": "member_data", "import": "member_data", "from": "member_data", "annotation": "member_annotation"}   # what each kind of binding in a class body is, or it is refused
    STORE_FORMS = {"receiver": "store_receiver", "data": "store_data", "class": "store_namespace", "namespace": "store_namespace", "ns_dict": "store_namespace",
                   "instance_dict": "store_namespace"}   # what each kind of store base is, or the store is refused ("unknown" is not recognised)

    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self.component: dict[tuple[str, str], int] = {}
        self.family_methods: dict[int, set[str]] = collections.defaultdict(set)
        self.family_names: set[str] = set()   # the method names of every family of more than one class: the names a write through data must not take
        self.owner_of = {id(cls.scope): cls for cls in facts.classes.values()}   # the class whose body a scope is
        self.method_of = {id(fn.scope): fn for fn in facts.functions}            # the function whose body a scope is

    def refuse(self, category: str, path: str, line: int, construct: str, remediation: str) -> None:
        assert category in CATEGORIES, category
        self.facts.diagnose(category, path, line, construct, remediation)

    def run(self) -> None:
        facts = self.facts
        for index in facts.indexes.values():
            self.exports(index)
            for cls in index.classes.values():
                self.declaration(index, cls)
        for index in facts.indexes.values():
            for fn in index.functions:
                self.function(index, fn)
        self.families()
        for index in facts.indexes.values():
            for cls in index.classes.values():
                self.hierarchy(index, cls)
                self.namespace(index, cls)
            for scope in index.scopes:
                self.bindings(index, scope)
            for site in index.stores:
                self.store(index, site)
            for site in index.calls:
                self.call(index, site)
            self.pinned(index)

    # -- class declarations: bases, keywords, decorators, hooks -------------------------------------------------------------

    def declaration(self, index: FileIndex, cls: ClassFact) -> None:
        path, node = index.path, cls.node
        for keyword in node.keywords:
            self.refuse("SRC-CLASS-HOOK", path, node.lineno, f"class {cls.qual} has the keyword {keyword.arg or '**'}=", "declare the class without a metaclass or class keywords")
        for base in node.bases:
            self.base(index, cls, base)
        for decorator in node.decorator_list:
            try:
                record = decorator_transform(path, cls.parent, decorator, "class")
            except Unresolved as exc:
                self.refuse(exc.category, path, decorator.lineno, f"class {cls.qual} is decorated {ast.unparse(decorator)}: {exc.why}", REMEDY[exc.category])
                continue
            cls.transforms.append(record.identity)
            if record.identity == "dataclasses.dataclass":
                cls.dataclass_kind = "frozen" if isinstance(decorator, ast.Call) and bool(decorator.keywords) else "plain"

    def base(self, index: FileIndex, cls: ClassFact, node: ast.expr) -> None:
        path, text = index.path, ast.unparse(node)
        try:
            if isinstance(node, ast.Subscript):
                inner = self.facts.expr(path, cls.parent, node.value)
                if inner[0] != "external" or inner[1] not in MODELLED_TYPING:
                    raise Unresolved("SRC-BASE-SUBSCRIPT", f"{text} is subscripted and {ast.unparse(node.value)} is not a modelled typing form ({', '.join(MODELLED_TYPING)})")
                ref = inner
            else:
                ref = self.facts.expr(path, cls.parent, node)
            if ref[0] in ("module", "package"):
                raise Unresolved("SRC-BASE-ALIAS", f"{text} names a module, not a class")
            if ref[0] == "function":
                raise Unresolved("SRC-BASE-ALIAS", f"{text} names a function: a class made by a call is not a class declaration")
            if ref[0] == "class" and self.facts.service_of(ref[1]) != self.facts.service_of(path):
                raise Unresolved("SRC-BASE-HIERARCHY", f"{text} is defined in {ref[1]}, in the other service")
        except Unresolved as exc:
            self.refuse(exc.category, path, node.lineno, f"class {cls.qual} has the base {text}: {exc.why}", REMEDY[exc.category])
            return
        cls.bases.append((text, ref))

    def hierarchy(self, index: FileIndex, cls: ClassFact) -> None:
        projects = [ref for _, ref in cls.bases if ref[0] == "class"]
        if not projects:
            return
        mixed = [ref[1] for _, ref in cls.bases if ref[0] == "external" and ref[1] not in MIXABLE_EXTERNAL]
        if mixed:
            self.refuse("SRC-BASE-MIXED", index.path, cls.node.lineno, f"class {cls.qual} mixes project bases with {', '.join(mixed)}",
                        "an external base's methods precede or follow the project's in an order the analysis does not model: compose by attribute instead")
            return
        try:
            order = self.facts.mro(cls.key)
        except (ValueError, KeyError) as exc:
            self.refuse("SRC-BASE-HIERARCHY", index.path, cls.node.lineno, f"class {cls.qual} has an unusable hierarchy ({exc})", "make the bases consistent and acyclic")
            return
        external = None
        for entry in order[1:]:   # an external class's place in the order, through ANY ancestor, is a place where a name the project attribution claims could be supplied
            if entry[0] == "base" and entry[1] not in MIXABLE_EXTERNAL:
                external = external or entry[1]
            elif entry[0] != "base" and external:
                self.refuse("SRC-BASE-MIXED", index.path, cls.node.lineno, f"class {cls.qual}: the external class {external}, an ancestor of one of its bases, comes before the project class "
                            f"{entry[0]}::{entry[1]} in its resolution order", "its names could be found before the project's, and the analysis cannot know which: compose by attribute instead")
                return

    # -- decorators of functions and methods, receivers --------------------------------------------------------------------

    def function(self, index: FileIndex, fn: FunctionFact) -> None:
        in_class = fn.parent.kind == "class" and not fn.conditional
        applies = "method" if in_class else "function"
        for decorator in fn.node.decorator_list:
            try:
                record = decorator_transform(index.path, fn.parent, decorator, applies)
            except Unresolved as exc:
                self.refuse(exc.category, index.path, decorator.lineno, f"{fn.qual} is decorated {ast.unparse(decorator)}: {exc.why}", REMEDY[exc.category])
                continue
            fn.transforms.append(record.identity)
            fn.role = record.role or fn.role
        if in_class:
            fn.role = fn.role if fn.role != "function" else "method"
            args = fn.node.args
            positional = args.posonlyargs + args.args
            fn.receiver = positional[0].arg if positional and fn.role != "static" else None
            owner = self.owner_of.get(id(fn.parent))
            if owner is not None:
                owner.methods.setdefault(fn.name, fn)
            if fn.receiver and (line := self.rebinds(fn)):
                self.refuse("SRC-RECEIVER-REBOUND", index.path, line, f"the receiver {fn.receiver} of {fn.qual} is bound again inside the method",
                            "do not assign, shadow or delete the receiver: self-calls through it could not be attributed")

    @staticmethod
    def rebinds(fn: FunctionFact) -> int:
        """The line where a method binds its receiver's name again (an assignment, a parameter of a closure or lambda, a loop or `with` target, `except ... as`, a
        comprehension target, `global`, `nonlocal`, an import, a nested definition of that name), or 0. Nested class bodies have their own receivers and are not entered."""
        name = fn.receiver
        stack = list(fn.node.body)
        while stack:
            node = stack.pop()
            hit = ((isinstance(node, ast.Name) and node.id == name and isinstance(node.ctx, (ast.Store, ast.Del)))
                   or (isinstance(node, (ast.arg,)) and node.arg == name)
                   or (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name)
                   or (isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name == name)
                   or (isinstance(node, ast.MatchMapping) and node.rest == name)
                   or (isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names)
                   or (isinstance(node, ast.alias) and (node.asname or node.name.partition(".")[0]) == name))
            if hit:
                return getattr(node, "lineno", fn.node.lineno)
            if not isinstance(node, ast.ClassDef):
                stack.extend(ast.iter_child_nodes(node))
        return 0

    # -- the effective members of a class: what Python has built once the body has run and the transformations are applied -------------------------

    def effective(self, cls: ClassFact) -> None:
        """Fill `members`: the names a body binds (a `def` with its role, anything else as data; an annotation alone binds nothing), the IMPLICIT ones Python adds and the
        GENERATED ones a recorded transformation adds. Ownership and attribution use these, so a name an implicit member masks is not attributed to an ancestor.

        The implicit rule is the data model's (https://docs.python.org/3/reference/datamodel.html#object.__hash__): "A class that overrides `__eq__()` and does not define
        `__hash__()` will have its `__hash__()` implicitly set to `None`." """
        scope, members = cls.scope, {}
        for name, bindings in scope.bindings.items():
            if name in cls.methods:
                members[name] = Member(cls.methods[name].role, "authored")
            elif any(b.role != "annotation" for b in bindings):
                members[name] = Member("data", "authored")
        authored = set(members)
        cls.slots = self.slot_names(cls)
        members.update({name: Member("slot", "authored", "a __slots__ entry") for name in cls.slots if name not in members})
        if "__eq__" in authored and "__hash__" not in authored:   # the data model: a class that overrides __eq__ and does not define __hash__ gets __hash__ = None
            members["__hash__"] = Member("data", "implicit", "__eq__ without __hash__ sets __hash__ to None")
        if cls.dataclass_kind:
            self.dataclass_members(cls, members, authored)
        cls.members = members
        cls.generated = {name for name, member in members.items() if member.origin == "generated" and member.role == "method"}

    def slot_names(self, cls: ClassFact) -> list[str]:
        bindings = cls.scope.bindings.get("__slots__", [])
        if not bindings:
            return []
        source_ = bindings[0].source
        elements = source_.elts if isinstance(source_, (ast.Tuple, ast.List)) else [source_]
        if len(bindings) != 1 or bindings[0].role != "assign" or not all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elements):
            self.refuse("SRC-FORM-UNRECOGNISED", cls.path, bindings[0].line, f"`__slots__` of class {cls.qual} is not one literal tuple, list or string of names",
                        "write `__slots__` once, as a literal of names: the names it lists are members of the class")
            return []
        return [e.value for e in elements]

    def dataclass_members(self, cls: ClassFact, members: dict[str, Member], authored: set[str]) -> None:
        """What `dataclasses.dataclass` adds to a class (https://docs.python.org/3/library/dataclasses.html: "If eq and frozen are both true, by default `@dataclass` will generate a
        `__hash__()` method for you. If eq is true and frozen is false, `__hash__()` will be set to `None`" ... "Neither will it add or change an existing explicitly defined
        `__hash__()` method"; `__init__`, `__repr__` and `__eq__` are not added where the class already defines them; with `frozen=True` a `__setattr__` or `__delattr__` the body
        defines raises TypeError at class creation, so the class is never built and the body's is kept here; the contract records only `@dataclass`, `@dataclass()` and `@dataclass(frozen=True)`, so
        eq is true, init and repr are true, and unsafe_hash and order are false): `__init__`, `__repr__` and `__eq__` unless the body defines them; for frozen also
        `__setattr__` and `__delattr__`; and `__hash__` by the documented table - `None` for a non-frozen class, a generated method for a frozen one, in both cases unless the
        class has an EXPLICIT `__hash__` (one its body defines, other than the `None` Python sets for a body that defines `__eq__`). Each annotated field is an instance attribute."""
        frozen = cls.dataclass_kind == "frozen"
        for name in ("__init__", "__repr__", "__eq__", *(("__setattr__", "__delattr__") if frozen else ())):
            members.setdefault(name, Member("method", "generated"))
        for name in ("__dataclass_params__", "__dataclass_fields__", "__match_args__"):
            members.setdefault(name, Member("data", "generated"))
        authored_hash = [b for b in cls.scope.bindings.get("__hash__", []) if b.role != "annotation"]
        none_hash = bool(authored_hash) and isinstance(authored_hash[-1].source, ast.Constant) and authored_hash[-1].source.value is None
        explicit = bool(authored_hash) and not (none_hash and "__eq__" in authored)   # dataclasses: `class_hash is None and '__eq__' in cls.__dict__` is the None Python set, not an explicit one
        if not explicit:
            members["__hash__"] = Member("method", "generated", "frozen=True and eq=True: a generated __hash__") if frozen else \
                Member("data", "generated", "eq=True and frozen=False: __hash__ is None")
        for name, bindings in cls.scope.bindings.items():
            for binding in bindings:
                if binding.annotated is not None and not self.not_a_field(cls, binding.annotated):
                    cls.fields.append((name, binding.line))

    @staticmethod
    def not_a_field(cls: ClassFact, annotation: ast.expr) -> bool:
        """An annotation that does not make an instance field: `ClassVar[...]`, `InitVar[...]` and `KW_ONLY` (also written as a string)."""
        node = annotation.value if isinstance(annotation, ast.Subscript) else annotation
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value.partition("[")[0].strip().rpartition(".")[2] in ("ClassVar", "InitVar", "KW_ONLY")
        try:
            return source.identify(cls.path, cls.parent, node) in FIELD_MARKERS
        except Unresolved:
            return False

    # -- families: the data a method name must not be overridden by ---------------------------------------------------------

    def families(self) -> None:
        parent: dict[tuple[str, str], tuple[str, str]] = {key: key for key in self.facts.classes}

        def find(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        for key, cls in self.facts.classes.items():
            self.effective(cls)
            for _, ref in cls.bases:
                if ref[0] == "class" and (ref[1], ref[2]) in parent:
                    parent[find(key)] = find((ref[1], ref[2]))
        numbers: dict[tuple[str, str], int] = {}
        for key, cls in self.facts.classes.items():
            self.component[key] = numbers.setdefault(find(key), len(numbers))
            self.family_methods[self.component[key]] |= {name for name, member in cls.members.items() if member.role in CALLABLE}
        sizes = collections.Counter(self.component.values())
        for number, size in sizes.items():
            if size > 1:
                self.family_names |= self.family_methods[number]

    # -- the class namespace: every kind of binding in a class body is recognised, or refused -------------------------------------

    def namespace(self, index: FileIndex, cls: ClassFact) -> None:
        names = self.family_methods[self.component[cls.key]]
        defs = {name for name, bindings in cls.scope.bindings.items() if any(b.role == "def" for b in bindings)}
        for name, bindings in cls.scope.bindings.items():
            for binding in bindings:
                form = self.CLASS_FORMS.get(binding.role)
                if form is None:
                    self.refuse("SRC-FORM-UNRECOGNISED", index.path, binding.line, f"the {binding.role} binding of {name} in class {cls.qual} has no recorded effect",
                                "bind class members by a def, a class, an assignment or an import: the contract records those")
                else:
                    getattr(self, form)(index, cls, name, binding, defs, names)
        for name in cls.slots:
            if name in names:
                self.override(index.path, cls.node.lineno, f"the slot {name} of {cls.qual}", name)
        for name, line in cls.fields:
            if name in names:
                self.override(index.path, line, f"the dataclass field {name} of {cls.qual} (its generated __init__ writes it on every instance)", name)

    def member_method(self, index: FileIndex, cls: ClassFact, name: str, binding: Binding, defs: set[str], names: set[str]) -> None:
        if name in HOOKS:
            self.refuse("SRC-CLASS-HOOK", index.path, binding.line, f"class {cls.qual} defines {name}", f"do not define {name}: it changes how classes or attributes resolve")

    def member_annotation(self, index: FileIndex, cls: ClassFact, name: str, binding: Binding, defs: set[str], names: set[str]) -> None:
        return None   # an annotation alone binds nothing in the namespace (a dataclass's fields are read from it in `effective`)

    def member_data(self, index: FileIndex, cls: ClassFact, name: str, binding: Binding, defs: set[str], names: set[str]) -> None:
        """A name bound in a class body by anything but a `def`: a hook name, a family method's name and a value that names one of the body's methods are each refused,
        whatever statement bound it (an assignment, a loop or `with` target, an import, a walrus)."""
        if name in HOOKS:
            self.refuse("SRC-CLASS-HOOK", index.path, binding.line, f"class {cls.qual} binds {name} by {binding.role}", f"do not bind {name}: it changes how classes or attributes resolve")
        aliased = sorted({n.id for n in ast.walk(binding.source) if isinstance(n, ast.Name) and n.id in defs}) if binding.source is not None else []
        if aliased:
            self.refuse("SRC-METHOD-ALIAS", index.path, binding.line, f"the binding of {name} in class {cls.qual} from `{ast.unparse(binding.source)[:60]}` aliases the method {aliased[0]}",
                        "call the method by its own name: an alias is a second name the self-call attribution would not see")
        superseded = cls.members.get(name) is not None and cls.members[name].origin == "generated"   # a transformation replaces what the body bound (a frozen dataclass's `__hash__ = None`)
        if name in names and name not in defs and not superseded:
            self.override(index.path, binding.line, f"the class attribute {name} of {cls.qual}", name)

    def override(self, path: str, line: int, what: str, name: str) -> None:
        self.refuse("SRC-ATTR-OVERRIDE", path, line, f"{what} overrides a method named {name} of its class family",
                    "give the data its own name: a data attribute that hides a method would send calls to it, not to the method the analysis attributes")

    def bindings(self, index: FileIndex, scope: source.Scope) -> None:
        """Every binding in every scope has a recognised role: the closed list of source.BINDING_ROLES (a role added to the index and not to that list is refused here)."""
        for name, bindings in scope.bindings.items():
            for binding in bindings:
                if binding.role not in source.BINDING_ROLES:
                    self.refuse("SRC-FORM-UNRECOGNISED", index.path, binding.line, f"the binding of {name} has the role {binding.role}, which the contract does not record", FORM_REMEDY)

    # -- exports ----------------------------------------------------------------------------------------------------------------

    def exports(self, index: FileIndex) -> None:
        """`__all__` is one module-level literal, never written again and never mutated; it may be READ in the forms listed (an index, the pure readers, a comparison, an
        iteration, a copy): passing it on as a value (`exports = __all__`, a call argument) could hand someone the list to change, so it is refused too."""
        allowed = None
        for statement in index.tree.body:
            if (isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "__all__"):
                allowed = statement
        parents = {child: node for node in ast.walk(index.tree) for child in ast.iter_child_nodes(node)}
        count = 0
        for node in ast.walk(index.tree):
            named = (isinstance(node, ast.Name) and node.id == "__all__") or (isinstance(node, ast.Attribute) and node.attr == "__all__")
            if not named:
                continue
            up = parents.get(node)
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                count += 1
                literal = isinstance(up, ast.Assign) and up is allowed and isinstance(node, ast.Name) and _literal_strings(up.value)
                if not literal or count > 1:
                    self.refuse("SRC-ALL-DYNAMIC", index.path, node.lineno, f"`{ast.unparse(up)[:60]}` binds __all__ other than as one module-level literal list or tuple of strings",
                                "write __all__ once, at module level, as a literal list or tuple of strings (or have none)")
            elif (isinstance(up, ast.Attribute) and up.attr in MUTATORS) or (isinstance(up, ast.Subscript) and isinstance(up.ctx, (ast.Store, ast.Del))):
                self.refuse("SRC-ALL-DYNAMIC", index.path, node.lineno, f"`{ast.unparse(up)[:60]}` mutates __all__", "write __all__ once as a literal; do not extend or edit it")
            elif not self.reads_only(index, node, up):
                self.refuse("SRC-ALL-DYNAMIC", index.path, node.lineno, f"`{ast.unparse(up)[:60]}` passes __all__ on as a value, not as one of the recognised reads",
                            "read __all__ by index, comparison, iteration, copy, or len, sorted, list, tuple, set or frozenset: a list passed on can be changed where it lands")

    @staticmethod
    def reads_only(index: FileIndex, node: ast.expr, up: ast.AST | None) -> bool:
        """Whether `__all__` at `node`, inside `up`, is one of the recognised reads."""
        if isinstance(up, ast.Subscript):
            return up.value is node
        if isinstance(up, ast.Call):
            site = next((s for s in index.calls if s.node is up), None)
            return node in up.args and site is not None and _identity(index, site.scope, up.func) in PURE_READERS
        if isinstance(up, ast.Attribute):
            return up.value is node and up.attr in READ_METHODS
        if isinstance(up, (ast.For, ast.AsyncFor, ast.comprehension)):
            return up.iter is node
        return isinstance(up, (ast.Compare, ast.Starred, ast.BinOp))

    # -- what an expression denotes: the base of a store, the first argument of setattr ---------------------------------------------

    def context(self, scope: source.Scope) -> tuple:
        """What the code in `scope` knows of its receiver: (the class, the receiver's name, the method's role) inside a method, however deeply a closure, lambda or
        comprehension is nested in it, and nothing in a class body."""
        while scope is not None:
            if scope.kind == "class":
                return ()
            fn = self.method_of.get(id(scope))
            if fn is not None and fn.parent.kind == "class" and fn.receiver and not fn.conditional:
                return (self.owner_of[id(fn.parent)], fn.receiver, fn.role)
            scope = scope.parent
        return ()

    def kind_of(self, index: FileIndex, scope: source.Scope, node: ast.expr, context: tuple, seen: frozenset = frozenset()) -> str:
        """What `node` denotes, as far as a write through it is concerned: the method's own `receiver`; a `class`; `data` (an object the contract does not restrict); a
        `namespace` (a module, a package, a function or an external object); `ns_dict` (the dictionary of a namespace: `globals()`, `sys.modules`, `A.__dict__`);
        `instance_dict` (the receiver's own `__dict__`); or `unknown` (a name or an expression nothing recorded says what it is)."""
        if isinstance(node, ast.Name):
            return self.name_kind(index, scope, node, context, seen)
        if isinstance(node, ast.Attribute):
            if _identity(index, scope, node) == "sys.modules":
                return "ns_dict"
            base = self.kind_of(index, scope, node.value, context, seen)
            if node.attr in STRUCTURAL and node.attr != "__dict__":
                return "class"
            if node.attr == "__dict__":
                return {"data": "data", "receiver": "instance_dict", "class": "ns_dict", "namespace": "ns_dict"}.get(base, "unknown")
            if base in ("data", "receiver"):
                return "data"
            return self.member_kind(index, scope, node) if base in ("class", "namespace") else "unknown"
        if isinstance(node, ast.Subscript):   # an element of a container is data, except an element of a namespace's dictionary: a module or a class (`sys.modules[name]`)
            return "namespace" if self.kind_of(index, scope, node.value, context, seen) == "ns_dict" else "data"
        if isinstance(node, ast.Call):
            return self.call_kind(index, scope, node, context, seen)
        if isinstance(node, ast.NamedExpr):
            return self.value_kind(index, scope, node.value, context, seen)
        return "unknown"

    def member_kind(self, index: FileIndex, scope: source.Scope, node: ast.expr) -> str:
        """A member of a class or a module: a data member (bound by an assignment there) is data; a class the resolver follows to is a `class`; a module, a function or
        an external object it follows to is a `namespace`."""
        try:
            ref = self.facts.expr(index.path, scope, node)
        except Unresolved as exc:
            return "data" if exc.category == "SRC-BASE-ALIAS" else "unknown"
        except KeyError:
            return "unknown"
        return "class" if ref[0] == "class" else "namespace"

    def call_kind(self, index: FileIndex, scope: source.Scope, node: ast.Call, context: tuple, seen: frozenset) -> str:
        """What a call returns. The calls that hand out a class or a namespace are the recognised producers (`type(x)`, `globals()`, `locals()`, `vars(x)`, `getattr(x, ...)` and a
        method of a namespace's dictionary); any other call returns a new object, which is data."""
        identity = _identity(index, scope, node.func)
        if identity == "builtins.type" and len(node.args) == 1:
            return "class"
        if identity in ("builtins.globals", "builtins.locals") or (identity == "builtins.vars" and not node.args):
            return "ns_dict"
        if identity in ("builtins.vars", "builtins.getattr") and node.args:
            first = self.kind_of(index, scope, node.args[0], context, seen)
            if identity == "builtins.getattr":
                return first if first in ("class", "namespace") else "namespace" if first == "ns_dict" else "data"
            return {"data": "data", "receiver": "instance_dict", "class": "ns_dict", "namespace": "ns_dict"}.get(first, "unknown")
        if isinstance(node.func, ast.Attribute) and self.kind_of(index, scope, node.func.value, context, seen) == "ns_dict":
            return "namespace"
        return "data"

    def name_kind(self, index: FileIndex, scope: source.Scope, node: ast.Name, context: tuple, seen: frozenset) -> str:
        if context and node.id == context[1]:
            return "class" if context[2] == "class" else "receiver"
        holder = next((s for s in source.lexical_chain(scope) if node.id in s.bindings), None)
        if holder is None:
            return "namespace" if hasattr(builtins, node.id) else "unknown"
        if (id(holder), node.id) in seen:
            return "data"
        kinds = {self.binding_kind(index, holder, node.id, b, context, seen | {(id(holder), node.id)}) for b in holder.bindings[node.id]}
        return next(kind for kind in KINDS if kind in kinds)

    def binding_kind(self, index: FileIndex, holder: source.Scope, name: str, binding: Binding, context: tuple, seen: frozenset) -> str:
        if binding.role in ("import", "from"):   # followed to what it names: a class is a class, a module, a function or an external object a namespace
            try:
                return "class" if self.facts.bound(index.path, holder, name)[0] == "class" else "namespace"
            except Unresolved:
                return "namespace"
        if binding.role == "def":
            return "namespace"
        if binding.role == "class":
            return "class"
        if binding.role == "star":
            return "unknown"
        if binding.source is None:
            return "data"
        where = binding.origin or holder   # the source is evaluated where the statement ran, which is not the holder of a `global` or `nonlocal` write
        if binding.role == "target":   # a loop, `with` or comprehension target is bound to an ELEMENT of what it iterates
            return self.element_kind(index, where, binding.source, context, seen)
        return self.value_kind(index, where, binding.source, context, seen)

    def value_kind(self, index: FileIndex, scope: source.Scope, node: ast.AST, context: tuple, seen: frozenset) -> str:
        """What a name bound to `node` denotes: a name, attribute, item or call as `kind_of` says (a call that is no recognised producer returns data); the worst of the
        branches of a conditional; a literal collection is data (a container is not what it holds); anything else is data."""
        if isinstance(node, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
            kind = self.kind_of(index, scope, node, context, seen)
            return "data" if kind == "unknown" and isinstance(node, ast.Call) else kind
        branches = {ast.IfExp: lambda n: [n.body, n.orelse], ast.BoolOp: lambda n: n.values, ast.NamedExpr: lambda n: [n.value]}
        kinds = {self.value_kind(index, scope, part, context, seen) for part in branches[type(node)](node)} if type(node) in branches else set()
        return next((kind for kind in KINDS if kind in kinds and kind != "data"), "data")

    def element_kind(self, index: FileIndex, scope: source.Scope, node: ast.AST, context: tuple, seen: frozenset) -> str:
        """What an element of `node` denotes when it is iterated: for a literal collection the worst of its elements (a loop over `(A, B)` binds its target to a class),
        through a name bound to one; anything else yields data."""
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            kinds = {self.value_kind(index, scope, part, context, seen) for part in node.elts}
            return next((kind for kind in KINDS if kind in kinds and kind in ("namespace", "class", "ns_dict", "instance_dict")), "data")
        if isinstance(node, ast.Name):
            holder = next((s for s in source.lexical_chain(scope) if node.id in s.bindings), None)
            if holder is not None and (id(holder), node.id) not in seen:
                kinds = {self.element_kind(index, holder, b.source, context, seen | {(id(holder), node.id)}) for b in holder.bindings[node.id] if b.role == "assign" and b.source is not None}
                return next((kind for kind in KINDS if kind in kinds and kind != "data"), "data")
        return "data"

    # -- every store and every call: the recognised forms and their effects, or a refusal ------------------------------------------------

    def store(self, index: FileIndex, site: source.Store) -> None:
        """An attribute or an item written or deleted. The base it is written through is classified (`kind_of`); only the kinds in STORE_FORMS are recognised, and each has an
        effect: a write through the receiver is an instance attribute (it must not be a method of the class family), through data it is nothing the metrics read, through a
        class, a module, a namespace's dictionary or an external object it is a change to a namespace. Anything the classification cannot say is refused."""
        node, scope = site.node, site.scope
        context = self.context(scope)
        if isinstance(node, ast.Attribute) and node.attr in STRUCTURAL:
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{ast.unparse(node)}` writes {node.attr}", REFLECTIVE_FIX)
            return
        kind = self.kind_of(index, scope, node.value, context)
        form = self.STORE_FORMS.get(kind)
        if form is None:
            self.refuse("SRC-FORM-UNRECOGNISED", index.path, node.lineno, f"`{ast.unparse(node)}` writes through {ast.unparse(node.value)}, which nothing in the source says what it is",
                        FORM_REMEDY)
            return
        getattr(self, form)(index, site, kind, context)

    def store_data(self, index: FileIndex, site: source.Store, kind: str, context: tuple) -> None:
        """A write through data (a parameter, a local, a container's element) is nothing the metrics read - unless the name written is a method of a class family: the object may be
        an instance of it, and its own attribute of that name would hide the method from every `self.<name>()` call the attribution claims."""
        node = site.node
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and node.attr in self.family_names:
            self.override(index.path, node.lineno, f"`{ast.unparse(node)}` (a write through {ast.unparse(node.value)}, which may hold an instance of the family)", node.attr)

    def store_receiver(self, index: FileIndex, site: source.Store, kind: str, context: tuple) -> None:
        node = site.node
        if isinstance(node, ast.Attribute) and context and node.attr in self.family_methods[self.component[context[0].key]]:
            self.override(index.path, node.lineno, f"`{ast.unparse(node)}` in {context[0].qual}", node.attr)

    def store_namespace(self, index: FileIndex, site: source.Store, kind: str, context: tuple) -> None:
        node = site.node
        what = {"class": "writes the attribute {name} of a class", "namespace": "writes the attribute {name} of a module, a function or an external object",
                "ns_dict": "writes a namespace's dictionary (the dictionary of a class or a module, globals(), locals(), vars() or sys.modules)",
                "instance_dict": "writes the receiver's own namespace through its __dict__"}[kind].format(name=getattr(node, "attr", "an item"))
        if kind == "ns_dict" and isinstance(node.value, ast.Call):
            what = "writes a namespace through globals(), locals() or vars()"
        elif kind == "ns_dict" and _identity(index, site.scope, node.value) == "sys.modules":
            what = "writes sys.modules"
        elif kind == "ns_dict" and isinstance(node.value, ast.Attribute) and node.value.attr == "__dict__":
            what = "writes the namespace of a class"
        self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{ast.unparse(node)}` {what}", REFLECTIVE_FIX)

    def call(self, index: FileIndex, site: source.CallSite) -> None:
        node, scope = site.node, site.scope
        context = self.context(scope)
        identity = _identity(index, scope, node.func)
        if identity == "builtins.type" and len(node.args) == 3 or identity in ("types.new_class", "builtins.__build_class__"):
            self.refuse("SRC-CLASS-DYNAMIC", index.path, node.lineno, f"`{ast.unparse(node)[:80]}` makes a class by a call", "write a class statement")
        elif identity in SET_CALLS:
            self.set_call(index, scope, node, context)
        elif identity in LOADER_CALLS:
            self.loader(index, scope, node, identity)
        elif isinstance(node.func, ast.Attribute) and node.func.attr in MUTATORS:
            self.mutator(index, scope, node, context)

    def mutator(self, index: FileIndex, scope: source.Scope, node: ast.Call, context: tuple) -> None:
        holder, text = node.func.value, ast.unparse(node)[:80]
        kind = self.kind_of(index, scope, holder, context)
        if kind == "ns_dict":
            what = ("changes the namespace of a class" if isinstance(holder, ast.Attribute) and holder.attr == "__dict__" else
                    "changes a namespace through globals(), locals() or vars()" if isinstance(holder, ast.Call) else "changes sys.modules")
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` {what}", "declare the member in the class body" if "class" in what else "bind the name in source")
        elif kind == "instance_dict":
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` changes the receiver's own namespace through its __dict__", REFLECTIVE_FIX)
        elif isinstance(holder, ast.Attribute) and holder.attr == "__all__":
            self.refuse("SRC-ALL-DYNAMIC", index.path, node.lineno, f"`{text}` mutates __all__", "write __all__ once as a literal; do not extend or edit it")

    def set_call(self, index: FileIndex, scope: source.Scope, node: ast.Call, context: tuple) -> None:
        """`setattr`, `delattr` and their `object.__setattr__` spellings: not on a class or a namespace, never under a computed name, and a literal name not a family method."""
        text = ast.unparse(node)[:80]
        first = node.args[0] if node.args else None
        literal = len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
        name = node.args[1].value if literal else ""
        kind = self.kind_of(index, scope, first, context) if first is not None else "unknown"
        if kind == "class":
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` writes an attribute of a class", "declare the member in the class body")
        elif kind in ("namespace", "ns_dict"):
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` writes an attribute of a module or an external object", "declare the member in source")
        elif not literal:
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` writes an attribute under a computed name", "write the attribute with a literal name")
        elif kind == "unknown":
            self.refuse("SRC-FORM-UNRECOGNISED", index.path, node.lineno, f"`{text}` writes through {ast.unparse(first)}, which nothing in the source says what it is", FORM_REMEDY)
        elif self.hides_a_family_method(context, kind, name, _identity(index, scope, node.func)):
            self.override(index.path, node.lineno, f"`{text}`" + (f" in {context[0].qual}" if context else ""), name)

    def hides_a_family_method(self, context: tuple, kind: str, name: str, identity: str | None) -> bool:
        """Whether writing the attribute `name` by setattr hides a method of a class family: through the receiver, a method of the receiver's own family; through data, a method of any
        family of more than one class (a `delattr` removes an attribute and hides nothing)."""
        if context and name in self.family_methods[self.component[context[0].key]]:
            return True
        return kind == "data" and name in self.family_names and identity != "builtins.delattr"

    def pinned(self, index: FileIndex) -> None:
        """The reviewed implementation of each inventoried loader, not only the text the filter is written in: the normalised syntax of its function and of the statements of
        its module around it must be the recorded fingerprint, or the loader changed (Astra's 2q-a-repair-3 review F3: a `continue` turned into `pass` under the same condition)."""
        for entry in LOADERS:
            if entry.file != index.path:
                continue
            found = fingerprint(index.tree, entry.function)
            function = next((f for f in index.functions if f.qual == entry.function), None)
            if found is not None and found != entry.fingerprint:   # a module without the function holds no loader: any dynamic import left in it is refused as uninventoried
                self.refuse("SRC-LOADER-INVENTORY", index.path, function.node.lineno if function else 1,
                            f"the inventoried loader {entry.function} is not the reviewed implementation (fingerprint {found[:16]} against {entry.fingerprint[:16]})",
                            "restore the reviewed loader, or amend the loader inventory in docs/gen2/SOURCE-CONTRACT.md and tools/gen2_source_contract.py together (operator-reviewed)")

    # -- the one dynamic loader --------------------------------------------------------------------------------------------------

    def loader(self, index: FileIndex, scope: source.Scope, node: ast.Call, identity: str) -> None:
        site = next((entry for entry in LOADERS if entry.file == index.path and entry.function == scope.qual and identity in (entry.call, entry.discovery)), None)
        text = ast.unparse(node)[:80]
        if site is None:
            self.refuse("SRC-LOADER-UNINVENTORIED", index.path, node.lineno, f"`{text}` ({identity}) loads code or modules at run time",
                        "dynamic loading is outside the import graph: name the site in docs/gen2/SOURCE-CONTRACT.md's loader inventory (operator-reviewed) or import statically")
            return
        argument = ast.unparse(node.args[0]) if node.args else ""
        problems = []
        if identity == site.call and argument != site.argument:
            problems.append(f"the argument is not {site.argument}")
        if identity == site.discovery and argument != "__path__":
            problems.append("the discovery does not read the package's own __path__")
        if identity == site.call:
            problems += self.discovered(index, site)
        for problem in problems:
            self.refuse("SRC-LOADER-INVENTORY", index.path, node.lineno, f"the inventoried loader {site.function} changed: {problem}",
                        "amend the loader inventory in docs/gen2/SOURCE-CONTRACT.md and tools/gen2_source_contract.py together (operator-reviewed), or restore the loader")

    def discovered(self, index: FileIndex, site: Loader) -> list[str]:
        """What the loader's filter lets it find in its package, against the inventory: the files are the tracked modules and subpackages beside the loader."""
        function = next((f for f in index.functions if f.qual == site.function), None)
        problems = [why for why in (self.skip_set_problem(index, site),) if why]
        tests = [ast.unparse(n.test) for n in ast.walk(function.node) if isinstance(n, ast.If)] if function else []
        if site.condition not in tests:
            problems.append(f"the filter is not `{site.condition}`")
        selected = {n for n in self.package_modules(site) if n not in site.skip_names and not n.startswith(site.skip_prefix)}
        if selected != set(site.discovered):
            problems.append(f"the filter finds {sorted(selected ^ set(site.discovered))} that the inventory does not (or the reverse): the discovered files are {sorted(selected)}")
        return problems

    @staticmethod
    def skip_set_problem(index: FileIndex, site: Loader) -> str | None:
        literal = next((st.value for st in index.tree.body if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_SKIP" for t in st.targets)), None)
        try:
            if literal is None or tuple(sorted(ast.literal_eval(literal))) != tuple(sorted(site.skip_names)):
                return f"_SKIP is not {set(site.skip_names)}"
        except (ValueError, TypeError):
            return "_SKIP is not a literal set"
        return None

    def package_modules(self, site: Loader) -> set[str]:
        """The modules and subpackages the loader's package holds in the tracked production inventory (what `pkgutil.iter_modules` would list)."""
        prefix, found = site.file.rpartition("/")[0] + "/", set()
        for path in self.facts.paths["all"]:
            rest = path[len(prefix):].split("/") if path.startswith(prefix) else []
            name = rest[0].removesuffix(".py") if len(rest) == 1 else rest[0] if rest and rest[1] == "__init__.py" else None
            if name and name != "__init__":
                found.add(name)
        return found


REMEDY = {   # what to do about a refusal the resolver explains (`Unresolved.why` is the construct's explanation)
    "SRC-BASE-SHAPE": "write the base as a name or an attribute chain",
    "SRC-BASE-ALIAS": "inherit from the class by the name it is defined or imported under",
    "SRC-BASE-SUBSCRIPT": "drop the subscript, or use a modelled typing form",
    "SRC-BASE-HIERARCHY": "make the hierarchy consistent and inside one service",
    "SRC-NAME-UNRESOLVED": "import the name explicitly from the module that defines it, and keep that module in the production inventory",
    "SRC-BINDING-COMPETING": "bind the name once, unconditionally, by an explicit import or a class statement",
    "SRC-DECORATOR-UNKNOWN": "use a transformation the contract records, or amend the contract (docs/gen2/SOURCE-CONTRACT.md, operator-reviewed) before adding one",
    "SRC-DECORATOR-SHADOWED": "bind the decorator's name once, by an import or a definition, so its identity is certain",
    "SRC-DECORATOR-ARGS": "use the argument shape the transformation's record allows",
    "SRC-FORM-UNRECOGNISED": FORM_REMEDY,
}


def _identity(index: FileIndex, scope: source.Scope, node: ast.expr) -> str | None:
    try:
        return source.identify(index.path, scope, node)
    except Unresolved:
        return None


def _literal_strings(node: ast.expr) -> bool:
    return isinstance(node, (ast.List, ast.Tuple)) and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts)


# --- the stage on its own ----------------------------------------------------------------------------------------------

def facts_view(facts: Facts) -> dict:
    """What the contract recognised, as plain data: the functions with their roles and receivers, the classes with their resolved bases, C3 family, methods and EFFECTIVE
    members (authored, generated and implicit, each with its role and origin), and the fields and slots they have."""
    classes = []
    for key, cls in sorted(facts.classes.items()):
        try:
            family = [f"{path}::{qual}" for path, qual in facts.family(key)] if any(ref[0] == "class" for _, ref in cls.bases) else []
        except (ValueError, KeyError):
            family = []
        classes.append({"class": f"{key[0]}::{key[1]}", "bases": [[text, list(ref)] for text, ref in cls.bases], "family": family,
                        "methods": {name: fn.role for name, fn in cls.methods.items()}, "generated": sorted(cls.generated), "transforms": cls.transforms,
                        "members": {name: [m.role, m.origin] for name, m in sorted(cls.members.items())}, "fields": [name for name, _ in cls.fields], "slots": cls.slots})
    return {"contract": CONTRACT_ID, "diagnostics": [vars(d) for d in facts.diagnostics],
            "functions": [{"key": fn.key, "role": fn.role, "receiver": fn.receiver, "transforms": fn.transforms} for fn in facts.functions], "classes": classes}


def contract_view() -> dict:
    """The contract's own constants as plain data: what docs/gen2/SOURCE-CONTRACT.md must state (a test compares the two)."""
    return {"version": CONTRACT_VERSION, "id": CONTRACT_ID, "categories": {k: list(v) for k, v in CATEGORIES.items()},
            "transforms": [{"identity": t.identity, "applies_to": list(t.applies_to), "shape": t.shape, "effect": t.effect} for t in TRANSFORMS],
            "modelled_typing": list(MODELLED_TYPING), "mixable_external": list(MIXABLE_EXTERNAL), "hooks": list(HOOKS), "loader_calls": list(LOADER_CALLS),
            "forms": dict(sorted(source.FORMS.items())), "refused_by_design": list(source.REFUSED_BY_DESIGN), "binding_roles": list(source.BINDING_ROLES),
            "class_forms": dict(sorted(Contract.CLASS_FORMS.items())), "store_forms": dict(sorted(Contract.STORE_FORMS.items())),
            "loaders": [{"file": e.file, "function": e.function, "call": e.call, "discovery": e.discovery, "argument": e.argument, "package": e.package,
                         "skip_names": list(e.skip_names), "skip_prefix": e.skip_prefix, "condition": e.condition, "discovered": list(e.discovered),
                         "fingerprint": e.fingerprint} for e in LOADERS]}


def main(argv: list[str] | None = None) -> int:
    """`python tools/gen2_source_contract.py [--root R] [--json | --contract]`: the refusal stage alone. Exit 0 when the production source is inside the contract,
    1 when it is refused (diagnostics on stderr, or the facts and diagnostics as JSON on stdout), 2 when the repository cannot be read. `--contract` prints the
    contract's own constants as JSON and reads no repository."""
    parser = argparse.ArgumentParser(description="Gen-2 supported-source contract: refuse production source outside it")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="the repository (default: this one)")
    parser.add_argument("--json", action="store_true", help="print the recognised facts and the diagnostics as JSON")
    parser.add_argument("--contract", action="store_true", help="print the contract's constants as JSON (the version, categories, records and loader inventory)")
    args = parser.parse_args(argv)
    if args.contract:
        print(json.dumps(contract_view(), indent=1, sort_keys=True))
        return 0
    try:
        facts = load(Path(args.root))
    except source.ToolError as exc:
        print(f"gen2-source: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(facts_view(facts), indent=1, sort_keys=True))
    for diagnostic in facts.diagnostics:
        print(f"SOURCE REFUSED: {diagnostic.render()}", file=sys.stderr)
    print(f"gen2-source: {CONTRACT_ID}: {len(facts.diagnostics)} refusal(s) in {len(facts.paths['all'])} production files", file=sys.stderr if facts.diagnostics or args.json else sys.stdout)
    return 1 if facts.diagnostics else 0


if __name__ == "__main__":
    sys.exit(main())
