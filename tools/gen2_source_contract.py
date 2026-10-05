"""The supported-source contract, version 1 (task 2q-a-repair-3; docs/gen2/SOURCE-CONTRACT.md, ratified by the operator on 2026-10-05).

The architecture metrics are exact over a DECLARED subset of Python (Gate D #4, option B), not over arbitrary Python. This module is the one place the subset
is stated as code: the refusal categories, the records of the transformations and external terminals the subset allows (resolved identity, allowed argument
shape, effect on the metrics), and the one inventoried dynamic loader. `load(root)` indexes the production inventory of BOTH services once
(tools/gen2_source_index.py) and runs the contract over it; every diagnostic names file, line, construct and remediation. A refusal happens BEFORE any
measurement and nothing waives it: no numeric exemption, identity transition or ledger entry exists for it, and no command writes a baseline or a ledger
over refused source. Discovering another valid Python form outside this subset is a new refusal test, not an extension of the analyser.

The contract does not interpret arbitrary Python. It constrains what decides measured identities, bindings and attribution: lexical definitions, class
declarations and bases, imports and exports, decorators, the receiver of a method's self-calls, reflective writes to class and module namespaces, and dynamic
loading. Ordinary control flow, data processing, `getattr` on data, `type(x)` and data-field initialisation are not restricted.

Standard library only.
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import gen2_source_index as source
from gen2_source_index import ClassFact, Diagnostic, Facts, FileIndex, FunctionFact, Unresolved

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
    "SRC-LOADER-INVENTORY": ("non-graph mechanisms", "an inventoried loader that changed, or whose discovered files differ from the inventory"),
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
    generated: tuple[str, ...] = ()
    generated_frozen: tuple[str, ...] = ()


TRANSFORMS = (
    Transform("dataclasses.dataclass", ("class",), "`@dataclass`, `@dataclass()` or `@dataclass(frozen=True)`; no other argument, so never `slots=True`",
              "returns the decorated class object; generates `__init__`, `__repr__` and `__eq__` (and with `frozen=True` `__setattr__`, `__delattr__`, `__hash__`) as methods of "
              "that class unless its body defines them", _dataclass_arguments, generated=("__init__", "__repr__", "__eq__"),
              generated_frozen=("__setattr__", "__delattr__", "__hash__")),
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


LOADERS = (
    Loader("gateway/research_gateway/adapters/__init__.py", "load_all", "importlib.import_module", "pkgutil.iter_modules", "f'{__name__}.{info.name}'", "research_gateway.adapters",
           ("base",), "_", "info.name in _SKIP or info.name.startswith('_')",
           ("bea", "bis", "bls", "census", "core", "crossref", "datacite", "doaj", "doi_org", "ecb", "europepmc", "fred", "globe", "govinfo", "harvard_dataverse", "huggingface",
            "kaggle", "openaire", "openalex_snapshot", "opencitations", "openml", "qdr", "semanticscholar", "socrata", "unpaywall", "wms")),
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


class Contract:
    """The rows of the contract over one set of facts. One method per row; each only adds diagnostics and fills the facts the metrics read."""

    def __init__(self, facts: Facts) -> None:
        self.facts = facts
        self.component: dict[tuple[str, str], int] = {}
        self.family_methods: dict[int, set[str]] = collections.defaultdict(set)
        self.owner_of = {id(cls.scope): cls for cls in facts.classes.values()}   # the class whose body a scope is

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
                self.class_body(index, cls)
            self.walk(index)

    # -- class declarations: bases, keywords, decorators, hooks -------------------------------------------------------------

    def declaration(self, index: FileIndex, cls: ClassFact) -> None:
        path, node = index.path, cls.node
        for keyword in node.keywords:
            self.refuse("SRC-CLASS-HOOK", path, node.lineno, f"class {cls.qual} has the keyword {keyword.arg or '**'}=", "declare the class without a metaclass or class keywords")
        for item in node.body:
            if isinstance(item, source.FUNCTIONS) and item.name in HOOKS:
                self.refuse("SRC-CLASS-HOOK", path, item.lineno, f"class {cls.qual} defines {item.name}", f"do not define {item.name}: it changes how classes or attributes resolve")
        for base in node.bases:
            self.base(index, cls, base)
        for decorator in node.decorator_list:
            try:
                record = decorator_transform(path, cls.parent, decorator, "class")
            except Unresolved as exc:
                self.refuse(exc.category, path, decorator.lineno, f"class {cls.qual} is decorated {ast.unparse(decorator)}: {exc.why}", REMEDY[exc.category])
                continue
            cls.transforms.append(record.identity)
            frozen = isinstance(decorator, ast.Call) and bool(decorator.keywords)
            cls.generated.update(record.generated + (record.generated_frozen if frozen else ()))
        defined = {item.name for item in node.body if isinstance(item, source.FUNCTIONS)}
        cls.generated -= defined

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
        try:
            self.facts.mro(cls.key)
        except (ValueError, KeyError) as exc:
            self.refuse("SRC-BASE-HIERARCHY", index.path, cls.node.lineno, f"class {cls.qual} has an unusable hierarchy ({exc})", "make the bases consistent and acyclic")

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

    # -- families: the data a method name must not be overridden by ---------------------------------------------------------

    def families(self) -> None:
        parent: dict[tuple[str, str], tuple[str, str]] = {key: key for key in self.facts.classes}

        def find(key):
            while parent[key] != key:
                parent[key] = parent[parent[key]]
                key = parent[key]
            return key

        for key, cls in self.facts.classes.items():
            for _, ref in cls.bases:
                if ref[0] == "class" and (ref[1], ref[2]) in parent:
                    parent[find(key)] = find((ref[1], ref[2]))
        numbers: dict[tuple[str, str], int] = {}
        for key, cls in self.facts.classes.items():
            self.component[key] = numbers.setdefault(find(key), len(numbers))
            self.family_methods[self.component[key]] |= set(cls.methods) | cls.generated

    def class_body(self, index: FileIndex, cls: ClassFact) -> None:
        names = self.family_methods[self.component[cls.key]]
        defs = {n for n, bs in cls.scope.bindings.items() if any(b.role == "def" for b in bs)}
        for node in self.assignments(cls):
            aliased = sorted({n.id for n in ast.walk(node.value) if isinstance(n, ast.Name) and n.id in defs})
            if aliased:
                self.refuse("SRC-METHOD-ALIAS", index.path, node.lineno, f"{ast.unparse(node)} in class {cls.qual} aliases the method {aliased[0]}",
                            "call the method by its own name: an alias is a second name the self-call attribution would not see")
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                for leaf in ast.walk(target):
                    if isinstance(leaf, ast.Name) and leaf.id in names and leaf.id not in defs:
                        self.override(index.path, node.lineno, f"the class attribute {leaf.id} of {cls.qual}", leaf.id)

    @staticmethod
    def assignments(cls: ClassFact):
        """The assignments with a value in a class body, in its compound statements too, not in its methods or nested classes."""
        stack = list(cls.node.body)
        while stack:
            node = stack.pop()
            if isinstance(node, (source.FUNCTIONS, ast.ClassDef)):
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and getattr(node, "value", None) is not None:
                yield node
            stack.extend(ast.iter_child_nodes(node))

    def override(self, path: str, line: int, what: str, name: str) -> None:
        self.refuse("SRC-ATTR-OVERRIDE", path, line, f"{what} overrides a method named {name} of its class family",
                    "give the data its own name: a data attribute that hides a method would send calls to it, not to the method the analysis attributes")

    # -- exports ----------------------------------------------------------------------------------------------------------------

    def exports(self, index: FileIndex) -> None:
        allowed = None
        for statement in index.tree.body:
            if (isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "__all__"):
                allowed = statement
        parents = {child: node for node in ast.walk(index.tree) for child in ast.iter_child_nodes(node)}
        count = 0
        for node in ast.walk(index.tree):
            if not (isinstance(node, ast.Name) and node.id == "__all__"):
                continue
            up = parents.get(node)
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                count += 1
                literal = isinstance(up, ast.Assign) and up is allowed and _literal_strings(up.value)
                if not literal or count > 1:
                    self.refuse("SRC-ALL-DYNAMIC", index.path, node.lineno, f"`{ast.unparse(up)[:60]}` binds __all__ other than as one module-level literal list or tuple of strings",
                                "write __all__ once, at module level, as a literal list or tuple of strings (or have none)")
            elif (isinstance(up, ast.Attribute) and up.attr in MUTATORS) or (isinstance(up, ast.Subscript) and isinstance(up.ctx, (ast.Store, ast.Del))):
                self.refuse("SRC-ALL-DYNAMIC", index.path, node.lineno, f"`{ast.unparse(up)[:60]}` mutates __all__", "write __all__ once as a literal; do not extend or edit it")

    # -- one pass over each file's expressions: reflection and loading -----------------------------------------------------

    def walk(self, index: FileIndex) -> None:
        """Calls and writes with a scope context: reflective writes to class, module and method namespaces, three-argument `type`, and the writes of a method's
        receiver. Names resolve in the nearest enclosing def or class; a name that cannot be resolved is data, not a class."""
        scopes = {id(s.node): s for s in index.scopes}
        methods = {id(fn.node): fn for fn in index.functions}
        stack: list[tuple[ast.AST, source.Scope, tuple]] = [(statement, index.module, ()) for statement in index.tree.body]
        while stack:
            node, scope, context = stack.pop()
            if isinstance(node, (source.FUNCTIONS, ast.ClassDef)):
                outer = [*node.decorator_list, *(node.bases if isinstance(node, ast.ClassDef) else [*node.args.defaults, *[d for d in node.args.kw_defaults if d]])]
                stack.extend((child, scope, ()) for child in outer)
                stack.extend((child, scopes[id(node)], self.method_context(node, methods.get(id(node)), context)) for child in node.body)
                continue
            if isinstance(node, ast.Call):
                self.call(index, scope, node, context)
            elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.write(index, scope, node, context)
            stack.extend((child, scope, context) for child in ast.iter_child_nodes(node))

    def method_context(self, node: ast.AST, fn: FunctionFact | None, context: tuple) -> tuple:
        """What the code inside a def or class knows of its receiver: (the class, the receiver's name, the method's role) inside a method, nothing in a class body,
        and the enclosing method's own inside a closure."""
        if fn is not None and fn.parent.kind == "class" and fn.receiver and not fn.conditional:
            return (self.owner_of[id(fn.parent)], fn.receiver, fn.role)
        return () if isinstance(node, ast.ClassDef) else context

    def names_a_class(self, index: FileIndex, scope: source.Scope, node: ast.expr, context: tuple) -> bool:
        if isinstance(node, ast.Name) and context and context[2] == "class" and node.id == context[1]:
            return True
        if isinstance(node, ast.Call) and len(node.args) == 1 and isinstance(node.func, ast.Name) and node.func.id == "type":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "__class__":
            return True
        try:
            return self.facts.expr(index.path, scope, node)[0] == "class"
        except (Unresolved, KeyError):
            return False

    def write(self, index: FileIndex, scope: source.Scope, node: ast.AST, context: tuple) -> None:
        text = ast.unparse(node)
        reason = None
        if isinstance(node, ast.Attribute):
            if node.attr in STRUCTURAL:
                reason = f"writes {node.attr}"
            elif self.names_a_class(index, scope, node.value, context):
                reason = f"writes the attribute {node.attr} of a class"
            elif context and isinstance(node.value, ast.Name) and node.value.id == context[1] and node.attr in self.family_methods[self.component[context[0].key]]:
                self.override(index.path, node.lineno, f"`{text}` in {context[0].qual}", node.attr)
                return
        else:
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "__dict__" and self.names_a_class(index, scope, value.value, context):
                reason = "writes the namespace of a class"
            elif isinstance(value, ast.Call) and _identity(index, scope, value.func) in ("builtins.globals", "builtins.vars", "builtins.locals"):
                reason = "writes a namespace through globals(), locals() or vars()"
            elif _identity(index, scope, value) == "sys.modules":
                reason = "writes sys.modules"
        if reason:
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` {reason}", "declare the class or module member in source: a namespace changed at run time is not in the facts")

    def call(self, index: FileIndex, scope: source.Scope, node: ast.Call, context: tuple) -> None:
        identity = _identity(index, scope, node.func)
        if identity == "builtins.type" and len(node.args) == 3 or identity in ("types.new_class", "builtins.__build_class__"):
            self.refuse("SRC-CLASS-DYNAMIC", index.path, node.lineno, f"`{ast.unparse(node)[:80]}` makes a class by a call", "write a class statement")
        elif identity in SET_CALLS:
            self.set_call(index, scope, node, context)
        elif identity in LOADER_CALLS:
            self.loader(index, scope, node, identity)
        elif isinstance(node.func, ast.Attribute) and node.func.attr in MUTATORS:
            holder, text = node.func.value, ast.unparse(node)[:80]
            if isinstance(holder, ast.Attribute) and holder.attr == "__dict__" and self.names_a_class(index, scope, holder.value, context):
                self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` changes the namespace of a class", "declare the member in the class body")
            elif isinstance(holder, ast.Call) and _identity(index, scope, holder.func) in ("builtins.globals", "builtins.vars", "builtins.locals"):
                self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` changes a namespace through globals(), locals() or vars()", "bind the name in source")

    def set_call(self, index: FileIndex, scope: source.Scope, node: ast.Call, context: tuple) -> None:
        """`setattr`, `delattr` and their `object.__setattr__` spellings: not on a class, never under a computed name, and a literal name not a family method."""
        text = ast.unparse(node)[:80]
        first = node.args[0] if node.args else None
        literal = len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str)
        if first is not None and self.names_a_class(index, scope, first, context):
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` writes an attribute of a class", "declare the member in the class body")
        elif not literal:
            self.refuse("SRC-REFLECTIVE", index.path, node.lineno, f"`{text}` writes an attribute under a computed name", "write the attribute with a literal name")
        elif context and node.args[1].value in self.family_methods[self.component[context[0].key]]:
            self.override(index.path, node.lineno, f"`{text}` in {context[0].qual}", node.args[1].value)

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
    """What the contract recognised, as plain data: the functions with their roles and receivers, the classes with their resolved bases, C3 family and methods."""
    classes = []
    for key, cls in sorted(facts.classes.items()):
        try:
            family = [f"{path}::{qual}" for path, qual in facts.family(key)] if any(ref[0] == "class" for _, ref in cls.bases) else []
        except (ValueError, KeyError):
            family = []
        classes.append({"class": f"{key[0]}::{key[1]}", "bases": [[text, list(ref)] for text, ref in cls.bases], "family": family,
                        "methods": {name: fn.role for name, fn in cls.methods.items()}, "generated": sorted(cls.generated), "transforms": cls.transforms})
    return {"contract": CONTRACT_ID, "diagnostics": [vars(d) for d in facts.diagnostics],
            "functions": [{"key": fn.key, "role": fn.role, "receiver": fn.receiver, "transforms": fn.transforms} for fn in facts.functions], "classes": classes}


def contract_view() -> dict:
    """The contract's own constants as plain data: what docs/gen2/SOURCE-CONTRACT.md must state (a test compares the two)."""
    return {"version": CONTRACT_VERSION, "id": CONTRACT_ID, "categories": {k: list(v) for k, v in CATEGORIES.items()},
            "transforms": [{"identity": t.identity, "applies_to": list(t.applies_to), "shape": t.shape, "effect": t.effect} for t in TRANSFORMS],
            "modelled_typing": list(MODELLED_TYPING), "mixable_external": list(MIXABLE_EXTERNAL), "hooks": list(HOOKS), "loader_calls": list(LOADER_CALLS),
            "loaders": [{"file": e.file, "function": e.function, "call": e.call, "discovery": e.discovery, "argument": e.argument, "package": e.package,
                         "skip_names": list(e.skip_names), "skip_prefix": e.skip_prefix, "condition": e.condition, "discovered": list(e.discovered)} for e in LOADERS]}


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
