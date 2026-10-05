"""Gen-2 source facts: the one recognition boundary (tasks 2q-a-repair-3 and 2q-a-repair-4; docs/gen2/SOURCE-CONTRACT.md).

Gate D #4 found one cause behind the architecture ratchet's R1-R4 findings: three tools (the metrics resolver, the function inventory and the
locator checker) each rebuilt names, scopes and class ownership from the same source, so a form one of them mis-read became an apparent improvement
that the closed accounting then preserved. This module parses every production file ONCE, for both services, into one index:

  * definitions and scopes: every `def`, `async def`, `class`, lambda and comprehension, in the lexical scope that holds it, with its qualified name,
    its decorators and whether a compound statement guards it;
  * binding roles: every occurrence that binds a name in a scope, with its role (class, def, import, import from, star, assign, annotation, augmented
    assign, target, walrus, delete, parameter, global/nonlocal write) and whether it is conditional, and the expression whose value it binds;
  * store sites (an attribute or an item written or deleted) and call sites, each with the scope that holds it;
  * class bases, resolved by the one name resolver below, and the C3 order over the project classes (`object` implicit and last, as Python has it);
  * method ownership: the methods a class declares directly, and each method's receiver;
  * diagnostics: every construct the structural rows of the source contract refuse (a duplicate definition, a conditional class or method, a
    rebound definition, a star import, an unresolvable base, a syntax form the walker has no record of ...), each naming file, line, construct and
    remediation.

POSITIVE RECOGNITION (task 2q-a-repair-4; Astra's 2q-a-repair-3 review F2). Three rounds of fixes for individual spellings showed the cause: the guard
refused the forms it knew to be bad and trusted every other. The walker below turns that around. It is ONE dispatcher: every node of the syntax tree is
visited exactly once, through the table `FORMS`, which names the handler of every node class that can occur in the supported subset - the handler that records
what the node does to a namespace (a binding, a store, a call, a new scope) or that it does nothing. A node class with no entry in `FORMS` is REFUSED
(SRC-FORM-UNRECOGNISED), not read as harmless; so is a name stored where no statement recorded how. There is no traversal that lists the positions it
knows of (statements, defaults, decorators, loop targets ...): a position the walker does not enumerate is still visited, because the walk is by node, and a
node it does not recognise stops the build. tools/gen2_source_contract.py runs the contract's rows over these facts the same way: a kind of binding or store
with no recognised effect is refused there too.

It does not decide policy about decorators, receivers, reflection or dynamic loading: tools/gen2_source_contract.py holds the contract's records
and rows and runs them over this index. Everything that measures or looks a name up (tools/gen2_metrics.py, tools/check_gen2_locators.py) reads
these facts, so a form the index cannot state is refused before anything is measured, never read differently by a second consumer.

Standard library only. Files outside the production inventory (tests, tools) can be indexed with the same code for the locator checker's
queries (`index_text`); their diagnostics are not the contract's concern.
"""
from __future__ import annotations

import ast
import builtins
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

SERVICES = ("engine", "gateway")
SERVICE_PREFIX = {"engine": "gen2/", "gateway": "gateway/research_gateway/"}
ENGINE_TESTS = "gen2/tests/"
FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
DEFINING = ("class", "def")       # roles that make a name an identity: one per scope, never rebound
DECLARING = ("class", "def", "assign", "annotation")   # roles under which a `path::name` locator finds a name declared in a file
CERTAIN = ("class", "def", "assign")                   # roles under which a module/class-attribute locator finds a name defined in a namespace


class ToolError(Exception):
    """The tool could not run (exit 2): not a repository, an unreadable file, an unreadable baseline."""


# --- the inventory -------------------------------------------------------------------------------------------------

def git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True, timeout=120).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"git {' '.join(args)} failed in {root}: {getattr(exc, 'stderr', '') or exc}") from exc


def is_production(path: str) -> str | None:
    """The service a path belongs to as production Python (gen2/ without its tests, gateway/research_gateway/), or None."""
    if path.startswith(SERVICE_PREFIX["engine"]) and not path.startswith(ENGINE_TESTS):
        return "engine"
    return "gateway" if path.startswith(SERVICE_PREFIX["gateway"]) else None


def production_files(root: Path) -> dict[str, list[str]]:
    """Tracked production `.py` files per service (and "all", the two together), in `git ls-files` order. A tracked file missing from the working tree is
    listed here and skipped by the contract's `load`, so that the ledger then asks for the retirement of its identities."""
    tracked = [p for p in git(root, "ls-files").splitlines() if p.endswith(".py")]
    engine = [p for p in tracked if is_production(p) == "engine"]
    gateway = [p for p in tracked if is_production(p) == "gateway"]
    return {"engine": engine, "gateway": gateway, "all": [p for p in tracked if p in set(engine) | set(gateway)]}


def untracked_candidates(root: Path) -> list[str]:
    """Production-looking `.py` files present but neither tracked nor ignored: a local check that omitted them would claim a completeness it lacks."""
    others = git(root, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted(p for p in others if p.endswith(".py") and is_production(p))


def module_name(path: str) -> str:
    return path.removeprefix("gateway/").removesuffix(".py").replace("/", ".").removesuffix(".__init__")


def absolute_module(path: str, level: int, module: str | None) -> str:
    """The dotted module an `import`/`from` names, a relative one resolved against the importing file's package."""
    base = module or ""
    if not level:
        return base
    name = module_name(path)
    package = name if path.endswith("__init__.py") else name.rpartition(".")[0]
    parts = package.split(".")
    return ".".join(parts[:len(parts) - level + 1] + ([base] if base else []))


# --- facts ---------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Diagnostic:
    category: str     # SRC-... (docs/gen2/SOURCE-CONTRACT.md, "Refusal categories")
    file: str
    line: int
    construct: str
    remediation: str

    def render(self) -> str:
        return f"{self.file}:{self.line}: {self.category}: {self.construct}. {self.remediation}"


# The roles a binding can have: the complete list, one per kind of binding site (docs/gen2/SOURCE-CONTRACT.md, "Closure"). tools/gen2_source_contract.py recognises each
# of them in each kind of namespace; a role not listed there is refused, so a new kind of binding cannot be added here and trusted.
BINDING_ROLES = ("class", "def", "import", "from", "star", "assign", "annotation", "augassign", "target", "walrus", "delete", "param", "global_write", "nonlocal_write")


@dataclass
class Binding:
    """One occurrence that binds a name in a scope. `ref` is ("module", dotted) or ("from", module, name) for the import roles, ("alias", text) for a name bound
    directly to a name or an attribute chain. `source` is the expression whose value the name is bound to, where there is one (an assignment's value, a loop's
    iterable, a walrus's value); `direct` says the bare name is the whole target, not one element of an unpacking."""
    role: str      # one of BINDING_ROLES
    line: int
    conditional: bool = False
    ref: tuple = ()
    source: ast.AST | None = None
    direct: bool = False
    annotated: ast.AST | None = None   # the annotation of the annotated assignment that bound it (a dataclass field is one)
    origin: "Scope | None" = None      # the scope the binding statement ran in (a `global` or `nonlocal` write is recorded in another scope, but `source` is evaluated here)


class Scope:
    __slots__ = ("kind", "qual", "node", "parent", "bindings", "declared")

    def __init__(self, kind: str, qual: str, node: ast.AST, parent: "Scope | None") -> None:
        self.kind, self.qual, self.node, self.parent = kind, qual, node, parent   # module | class | function | lambda | comprehension
        self.bindings: dict[str, list[Binding]] = {}
        self.declared: dict[str, str] = {}   # names a `global` or `nonlocal` statement sends elsewhere

    def bind(self, name: str, binding: Binding) -> None:
        self.bindings.setdefault(name, []).append(binding)

    def named(self, name: str) -> str:
        return f"{self.qual}.{name}" if self.qual else name


@dataclass
class FunctionFact:
    path: str
    qual: str
    node: ast.FunctionDef | ast.AsyncFunctionDef
    scope: Scope                # the function's own scope
    parent: Scope               # the scope that holds the definition
    conditional: bool
    transforms: list[str] = field(default_factory=list)   # resolved decorator identities, innermost last (the contract fills these)
    role: str = "function"      # function | method | static | class | property (a function directly in a class body: the contract decides)
    receiver: str | None = None

    @property
    def name(self) -> str:
        return self.node.name

    @property
    def key(self) -> str:
        return f"{self.path}::{self.qual}"


@dataclass(frozen=True)
class Member:
    """One member a class has once Python has built it (the contract fills these). `role` is a function's role (method, static, class, property) for a member that is
    a `def`, `data` for a name bound to anything else, `slot` for a `__slots__` entry. `origin` says where it comes from: authored in the body, generated by a recorded
    transformation, or IMPLICIT (Python's own rule: `__eq__` without `__hash__` sets `__hash__` to None)."""
    role: str
    origin: str
    note: str = ""


@dataclass
class ClassFact:
    path: str
    qual: str
    node: ast.ClassDef
    scope: Scope
    parent: Scope
    conditional: bool
    bases: list[tuple[str, tuple]] = field(default_factory=list)   # (source text, ("class", path, qual) | ("external", dotted identity))
    transforms: list[str] = field(default_factory=list)
    methods: dict[str, FunctionFact] = field(default_factory=dict)
    generated: set[str] = field(default_factory=set)        # method names a modelled class decorator adds (a dataclass's __init__ ...)
    members: dict[str, Member] = field(default_factory=dict)   # the EFFECTIVE members: authored, generated and implicit ones; the first class in the C3 order that has the name decides it
    fields: list[tuple[str, int]] = field(default_factory=list)   # a dataclass's fields (name, line): each is an instance attribute its generated `__init__` writes
    slots: list[str] = field(default_factory=list)          # the names a literal `__slots__` lists
    dataclass_kind: str = ""                                # "plain" or "frozen" for a recorded `dataclasses.dataclass`, else ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.path, self.qual)


@dataclass(frozen=True)
class Store:
    """An attribute or an item written or deleted (`a.b = v`, `a[k] += v`, `del a.b`, a loop or `with` target `a.b`) and the scope that holds the statement."""
    node: ast.Attribute | ast.Subscript
    scope: Scope
    conditional: bool


@dataclass(frozen=True)
class CallSite:
    node: ast.Call
    scope: Scope


class FileIndex:
    """One file's facts: scopes with their bindings, definitions, classes, store and call sites, and the structural diagnostics found while reading it."""

    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path, self.tree = path, tree
        self.module = Scope("module", "", tree, None)
        self.functions: list[FunctionFact] = []
        self.classes: dict[str, ClassFact] = {}
        self.scopes: list[Scope] = [self.module]
        self.diagnostics: list[Diagnostic] = []
        self.star_imports: list[int] = []
        self.stores: list[Store] = []
        self.calls: list[CallSite] = []
        _Builder(self).run()


# --- the dispatcher's table ------------------------------------------------------------------------------------------------
# Every syntax node class that may occur in the supported subset, and the handler (a `form_<name>` method of _Builder) that records what it does. A class not named
# here is REFUSED (SRC-FORM-UNRECOGNISED): the walker has no record of what it binds, stores or changes. A node class of a later Python is therefore refused until it is
# listed, deliberately. `REFUSED_BY_DESIGN` are the node classes the contract does not record: the `type` statement and type parameters bind names in an annotation
# scope this index does not model. gen2/tests/test_source_contract.py compares this table with the node classes of the interpreter running the tests.

FORMS: dict[str, str] = {}


def _forms(handler: str, *names: str) -> None:
    FORMS.update(dict.fromkeys(names, handler))


_forms("leaf", "Constant", "Pass", "Break", "Continue", "Load", "Store", "Del", "And", "Or", "Add", "Sub", "Mult", "MatMult", "Div", "Mod", "Pow", "LShift", "RShift",
       "BitOr", "BitXor", "BitAnd", "FloorDiv", "Invert", "Not", "UAdd", "USub", "Eq", "NotEq", "Lt", "LtE", "Gt", "GtE", "Is", "IsNot", "In", "NotIn", "TypeIgnore",
       "MatchSingleton")
_forms("generic", "Module", "Expression", "Interactive", "FunctionType", "Return", "Raise", "Assert", "Expr", "BoolOp", "BinOp", "UnaryOp", "IfExp", "Dict", "Set", "Await",
       "Yield", "YieldFrom", "Compare", "FormattedValue", "JoinedStr", "Slice", "comprehension", "arguments", "arg", "keyword", "alias", "MatchValue", "MatchSequence", "MatchClass",
       "MatchOr", "ExtSlice", "Index", "Suite")
_forms("function", "FunctionDef", "AsyncFunctionDef")
_forms("class", "ClassDef")
_forms("lambda", "Lambda")
_forms("comprehension_scope", "ListComp", "SetComp", "DictComp", "GeneratorExp")
_forms("assign", "Assign")
_forms("augassign", "AugAssign")
_forms("annassign", "AnnAssign")
_forms("delete", "Delete")
_forms("loop", "For", "AsyncFor")
_forms("compound", "While", "If", "Try", "TryStar", "Match", "With", "AsyncWith")
_forms("withitem", "withitem")
_forms("except_handler", "ExceptHandler")
_forms("match_case", "match_case")
_forms("capture", "MatchAs", "MatchStar", "MatchMapping")
_forms("import", "Import")
_forms("import_from", "ImportFrom")
_forms("declaration", "Global", "Nonlocal")
_forms("walrus", "NamedExpr")
_forms("name", "Name")
_forms("container", "Tuple", "List", "Starred")
_forms("attribute", "Attribute")
_forms("subscript", "Subscript")
_forms("call", "Call")
REFUSED_BY_DESIGN = ("TypeAlias", "TypeVar", "ParamSpec", "TypeVarTuple")   # a name bound in an annotation scope: not modelled, so not accepted
PURE_NODES = tuple(name for name, form in FORMS.items() if form == "leaf")    # nodes with no children that matter


@dataclass(frozen=True)
class Target:
    """How the names a statement writes are bound: the role, the expression whose value they take, the annotation of the annotated assignment that wrote them (if
    one did), and whether the bare name is the whole target (it is not an element of an unpacking)."""
    role: str
    source: ast.AST | None = None
    annotated: ast.AST | None = None
    direct: bool = True


FORM_REMEDY = ("write the form with a construct the contract records, or amend the contract (docs/gen2/SOURCE-CONTRACT.md, operator-reviewed) before using it: a form with no "
               "record binds or stores in a way the metrics cannot state")


def chain_text(node: ast.AST | None) -> str | None:
    """The dotted text of a pure name-and-attribute chain (`a`, `a.b.c`), or None for any other expression."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else None


class _Builder:
    def __init__(self, index: FileIndex) -> None:
        self.index = index

    def run(self) -> None:
        index = self.index
        self.block(index.tree.body, index.module, False)
        for scope in index.scopes:
            self.structure(scope)

    # -- the dispatcher ----------------------------------------------------------------------------------------------

    def visit(self, node: ast.AST, scope: Scope, nested: bool, target: Target | None = None) -> None:
        """Every node goes through here, once: the form's handler records its effect, and a node class with no form is refused."""
        form = FORMS.get(type(node).__name__)
        if form is None:
            self.diagnose("SRC-FORM-UNRECOGNISED", getattr(node, "lineno", 0), f"the syntax {type(node).__name__} has no recorded effect on a namespace", FORM_REMEDY)
            return
        getattr(self, f"form_{form}")(node, scope, nested, target)

    def block(self, statements: list[ast.stmt], scope: Scope, nested: bool) -> None:
        for statement in statements:
            self.visit(statement, scope, nested)

    def each(self, nodes, scope: Scope, nested: bool, target: Target | None = None) -> None:
        for node in nodes:
            if node is not None:
                self.visit(node, scope, nested, target)

    # -- scopes and definitions --

    def diagnose(self, category: str, line: int, construct: str, remediation: str) -> None:
        self.index.diagnostics.append(Diagnostic(category, self.index.path, line, construct, remediation))

    def bind(self, scope: Scope, name: str, role: str, line: int, conditional: bool, ref: tuple = (), source: ast.AST | None = None, direct: bool = False,
             annotated: ast.AST | None = None) -> None:
        """The one place a binding is recorded. A `global` or `nonlocal` declaration sends EVERY kind of binding (an import and a definition as much as an assignment)
        to the scope it names."""
        origin = scope
        if name in scope.declared:
            kind = scope.declared[name]
            target = self.index.module if kind == "global" else next((s for s in self._enclosing(scope) if s.kind == "function"), scope)
            role, scope, ref = f"{kind}_write", target, ()
        elif role == "assign" and direct and chain_text(source) is not None:
            ref = ("alias", chain_text(source))   # a name bound to a name or an attribute chain forwards that identity
        scope.bind(name, Binding(role, line, conditional, ref, source, direct, annotated, origin))

    @staticmethod
    def _enclosing(scope: Scope):
        scope = scope.parent
        while scope is not None:
            yield scope
            scope = scope.parent

    def new_scope(self, kind: str, qual: str, node: ast.AST, parent: Scope) -> Scope:
        inner = Scope(kind, qual, node, parent)
        self.index.scopes.append(inner)
        return inner

    def form_leaf(self, node, scope, nested, target) -> None:
        return None

    def form_generic(self, node, scope, nested, target) -> None:
        for child in ast.iter_child_nodes(node):
            if type(child).__name__ not in PURE_NODES:
                self.visit(child, scope, nested)

    def form_class(self, node: ast.ClassDef, scope: Scope, nested: bool, target) -> None:
        self.bind(scope, node.name, "class", node.lineno, nested)
        if nested:
            self.diagnose("SRC-CLASS-CONDITIONAL", node.lineno, f"class {node.name} is declared inside a compound statement",
                          "declare the class directly in its module, class or function body")
        inner = Scope("class", scope.named(node.name), node, scope)
        fact = ClassFact(self.index.path, inner.qual, node, inner, scope, nested)
        key, n = inner.qual, 2
        while key in self.index.classes:   # a duplicate is refused below; both stay in the index so nothing disappears
            key, n = f"{inner.qual}#{n}", n + 1
        self.index.classes[key] = fact
        self.index.scopes.append(inner)
        self.each(getattr(node, "type_params", ()), scope, nested)
        self.each((*node.decorator_list, *node.bases, *(k.value for k in node.keywords)), scope, nested)
        self.block(node.body, inner, False)

    def parameters(self, args: ast.arguments, inner: Scope) -> list[ast.arg]:
        every = [*args.posonlyargs, *args.args, *args.kwonlyargs, *(a for a in (args.vararg, args.kwarg) if a is not None)]
        for arg in every:
            inner.bind(arg.arg, Binding("param", arg.lineno))
        return every

    def form_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: Scope, nested: bool, target) -> None:
        self.bind(scope, node.name, "def", node.lineno, nested)
        if nested and scope.kind == "class":
            self.diagnose("SRC-METHOD-CONDITIONAL", node.lineno, f"method {node.name} is declared inside a compound statement of class {scope.qual}",
                          "declare the method directly in the class body")
        inner = Scope("function", scope.named(node.name), node, scope)
        fact = FunctionFact(self.index.path, inner.qual, node, inner, scope, nested)
        self.index.functions.append(fact)
        self.index.scopes.append(inner)
        args = node.args
        every = self.parameters(args, inner)
        # everything in the header is evaluated where the function is DEFINED: decorators, defaults, every annotation, the return annotation
        self.each(getattr(node, "type_params", ()), scope, nested)
        self.each((*node.decorator_list, *args.defaults, *args.kw_defaults, *(a.annotation for a in every), node.returns), scope, nested)
        self.block(node.body, inner, False)

    def form_lambda(self, node: ast.Lambda, scope: Scope, nested: bool, target) -> None:
        self.each((*node.args.defaults, *node.args.kw_defaults), scope, nested)
        inner = self.new_scope("lambda", scope.qual, node, scope)
        self.parameters(node.args, inner)
        self.visit(node.body, inner, nested)

    def form_comprehension_scope(self, node, scope: Scope, nested: bool, target) -> None:
        """A comprehension has a scope of its own for its targets; only its first iterable is evaluated outside it, and a walrus inside it binds in the scope that holds it."""
        inner = self.new_scope("comprehension", scope.qual, node, scope)
        for position, generator in enumerate(node.generators):
            self.visit(generator.iter, scope if position == 0 else inner, nested)
            self.visit(generator.target, inner, nested, Target("target", generator.iter))
            self.each(generator.ifs, inner, nested)
        self.each((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,), inner, nested)

    # -- statements: imports, writes, compound blocks --

    def form_import(self, node: ast.Import, scope: Scope, nested: bool, target) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.partition(".")[0]
            self.bind(scope, name, "import", node.lineno, nested, ("module", alias.name if alias.asname else alias.name.partition(".")[0]))

    def form_import_from(self, node: ast.ImportFrom, scope: Scope, nested: bool, target) -> None:
        base = absolute_module(self.index.path, node.level, node.module)
        for alias in node.names:
            if alias.name == "*":
                self.index.star_imports.append(node.lineno)
                self.bind(scope, "*", "star", node.lineno, nested, ("star", base))
            else:
                self.bind(scope, alias.asname or alias.name, "from", node.lineno, nested, ("from", base, alias.name))

    def form_declaration(self, node: ast.Global | ast.Nonlocal, scope: Scope, nested: bool, target) -> None:
        scope.declared.update({name: "global" if isinstance(node, ast.Global) else "nonlocal" for name in node.names})

    def form_assign(self, node: ast.Assign, scope: Scope, nested: bool, target) -> None:
        self.each(node.targets, scope, nested, Target("assign", node.value))
        self.visit(node.value, scope, nested)

    def form_augassign(self, node: ast.AugAssign, scope: Scope, nested: bool, target) -> None:
        self.visit(node.target, scope, nested, Target("augassign", node.value))
        self.visit(node.value, scope, nested)

    def form_annassign(self, node: ast.AnnAssign, scope: Scope, nested: bool, target) -> None:
        if node.value is None and not isinstance(node.target, ast.Name):
            self.each(ast.iter_child_nodes(node.target), scope, nested)   # `a.b: int` declares and stores nothing
        else:
            self.visit(node.target, scope, nested, Target("assign" if node.value is not None else "annotation", node.value, annotated=node.annotation))
        self.visit(node.annotation, scope, nested)
        self.each([node.value], scope, nested)

    def form_delete(self, node: ast.Delete, scope: Scope, nested: bool, target) -> None:
        self.each(node.targets, scope, nested, Target("delete"))

    def form_loop(self, node: ast.For | ast.AsyncFor, scope: Scope, nested: bool, target) -> None:
        self.visit(node.target, scope, nested, Target("target", node.iter))
        self.visit(node.iter, scope, nested)
        self.block(node.body, scope, True)
        self.block(node.orelse, scope, True)

    def form_compound(self, node: ast.stmt, scope: Scope, nested: bool, target) -> None:
        """If, While, Try, With and Match: the header's expressions belong to the statement, its blocks are conditional."""
        for name, value in ast.iter_fields(node):
            if name in ("body", "orelse", "finalbody") and isinstance(value, list):
                self.block(value, scope, True)
            elif name in ("handlers", "cases", "items"):
                self.each(value, scope, True if name != "items" else nested)
            elif isinstance(value, ast.AST):
                self.visit(value, scope, nested)

    def form_withitem(self, node: ast.withitem, scope: Scope, nested: bool, target) -> None:
        self.visit(node.context_expr, scope, nested)
        if node.optional_vars is not None:
            self.visit(node.optional_vars, scope, nested, Target("target", node.context_expr))

    def form_except_handler(self, node: ast.ExceptHandler, scope: Scope, nested: bool, target) -> None:
        self.each([node.type], scope, nested)
        if node.name:
            self.bind(scope, node.name, "target", node.lineno, True)
        self.block(node.body, scope, True)

    def form_match_case(self, node: ast.match_case, scope: Scope, nested: bool, target) -> None:
        self.visit(node.pattern, scope, nested)
        self.each([node.guard], scope, nested)
        self.block(node.body, scope, True)

    def form_capture(self, node, scope: Scope, nested: bool, target) -> None:
        """A match pattern that captures a name: `case x`, `case [*rest]`, `case {**rest}`."""
        name = node.rest if isinstance(node, ast.MatchMapping) else node.name
        if name:
            self.bind(scope, name, "target", getattr(node, "lineno", 0), True)
        self.form_generic(node, scope, nested, target)

    def form_walrus(self, node: ast.NamedExpr, scope: Scope, nested: bool, target) -> None:
        self.visit(node.value, scope, nested)
        holder = scope
        while holder.kind == "comprehension" and holder.parent is not None:
            holder = holder.parent   # the target of an assignment expression in a comprehension is bound in the scope that holds the comprehension
        self.bind(holder, node.target.id, "walrus", node.lineno, nested, source=node.value, direct=True)

    # -- names, attributes, items, calls --

    def form_name(self, node: ast.Name, scope: Scope, nested: bool, target: Target | None) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            if target is None:
                self.diagnose("SRC-FORM-UNRECOGNISED", node.lineno, f"the name {node.id} is written where no statement says how", FORM_REMEDY)
                return
            self.bind(scope, node.id, "delete" if isinstance(node.ctx, ast.Del) else target.role, node.lineno, nested, source=target.source, direct=target.direct,
                      annotated=target.annotated)

    def form_container(self, node, scope: Scope, nested: bool, target: Target | None) -> None:
        inner = replace_target(target) if target is not None and isinstance(node.ctx, (ast.Store, ast.Del)) else None
        self.each(ast.iter_child_nodes(node), scope, nested, inner)

    def form_attribute(self, node: ast.Attribute, scope: Scope, nested: bool, target) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.index.stores.append(Store(node, scope, nested))
        self.visit(node.value, scope, nested)

    def form_subscript(self, node: ast.Subscript, scope: Scope, nested: bool, target) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.index.stores.append(Store(node, scope, nested))
        self.visit(node.value, scope, nested)
        self.visit(node.slice, scope, nested)

    def form_call(self, node: ast.Call, scope: Scope, nested: bool, target) -> None:
        self.index.calls.append(CallSite(node, scope))
        self.form_generic(node, scope, nested, target)

    # -- one definition, one binding ---------------------------------------------------------------------------------------

    def structure(self, scope: Scope) -> None:
        for name, bindings in scope.bindings.items():
            defs = [b for b in bindings if b.role in DEFINING]
            others = [b for b in bindings if b.role not in DEFINING and b.role != "annotation"]
            if len(defs) > 1:
                self.diagnose("SRC-DEF-DUPLICATE", defs[1].line, f"{name} is defined more than once in {scope.qual or 'the module'} (first at line {defs[0].line})",
                              "give each definition in a scope its own name; a branch, an overload or a redefinition is not a second identity")
            if defs and others:
                self.diagnose("SRC-DEF-REBOUND", others[0].line, f"{name} is defined in {scope.qual or 'the module'} (line {defs[0].line}) and bound again as {others[0].role}",
                              "bind the defined name once: rename the other binding, or the definition")
        if scope.kind == "module":
            for line in self.index.star_imports:
                self.diagnose("SRC-STAR-IMPORT", line, "a star import", "import the names explicitly: a star import's bindings depend on the imported module's exports and the order of the imports")


def replace_target(target: Target) -> Target:
    """The same target for an element of an unpacking."""
    return Target(target.role, target.source, target.annotated, False)


def index_text(path: str, text: str) -> FileIndex:
    """The facts of any Python text (the locator checker indexes tests and tools this way); a SyntaxError propagates."""
    return FileIndex(path, ast.parse(text, filename=path))


# --- the whole production inventory --------------------------------------------------------------------------------

class Unresolved(Exception):
    """A name that cannot be followed to one certain definition (`category` is the contract's refusal category)."""

    def __init__(self, category: str, why: str) -> None:
        super().__init__(why)
        self.category, self.why = category, why


def lexical_chain(scope: Scope) -> list[Scope]:
    """The namespaces a name used in `scope` is looked up in: the scope itself, then each enclosing function and the module (a class body is not
    enclosing for the code inside it)."""
    chain, outer = [scope], scope.parent
    while outer is not None:
        if outer.kind != "class":
            chain.append(outer)
        outer = outer.parent
    return chain


Ref = tuple   # ("class", path, qual) | ("function", path, qual) | ("module", dotted) | ("package", dotted) | ("external", dotted identity)
OBJECT = ("base", "builtins.object")   # the entry every class's order ends with


def c3_merge(sequences: list[list]) -> list:
    """Python's C3 merge of the linearizations of the bases and the list of the bases themselves; ValueError when none is consistent."""
    sequences = [list(seq) for seq in sequences if seq]
    order: list = []
    while sequences:
        head = next((seq[0] for seq in sequences if not any(seq[0] in other[1:] for other in sequences)), None)
        if head is None:
            raise ValueError("no consistent method resolution order")
        order.append(head)
        for seq in sequences:
            if seq[0] == head:
                del seq[0]
        sequences = [seq for seq in sequences if seq]
    return order


class Facts:
    """Every production file indexed once, for both services, with one name resolver (the contract's `load` builds and validates it)."""

    def __init__(self, root: Path, paths: dict[str, list[str]], texts: dict[str, str], indexes: dict[str, FileIndex]) -> None:
        self.root, self.paths, self.texts, self.indexes = root, paths, texts, indexes
        self.names = {module_name(p): p for p in paths["all"] if p in indexes}
        self.packages = {".".join(m.split(".")[:i]) for m in self.names for i in range(1, len(m.split(".")))} - set(self.names)
        self.tops = {m.partition(".")[0] for m in self.names}
        self.diagnostics: list[Diagnostic] = [d for index in indexes.values() for d in index.diagnostics]
        self.classes: dict[tuple[str, str], ClassFact] = {}
        for index in indexes.values():
            for fact in index.classes.values():
                self.classes.setdefault(fact.key, fact)
        self.functions: list[FunctionFact] = [fn for p in paths["all"] if p in indexes for fn in indexes[p].functions]
        self._mro: dict[tuple[str, str], list] = {}

    def service_of(self, path: str) -> str | None:
        return is_production(path)

    def diagnose(self, category: str, path: str, line: int, construct: str, remediation: str) -> None:
        self.diagnostics.append(Diagnostic(category, path, line, construct, remediation))

    # -- the name resolver: one certain definition, or a refusal ---------------------------------------------------------

    def module_ref(self, dotted: str) -> Ref:
        if dotted in self.names:
            return ("module", dotted)
        if dotted in self.packages:
            return ("package", dotted)
        if dotted.partition(".")[0] in self.tops:
            raise Unresolved("SRC-NAME-UNRESOLVED", f"{dotted} is a first-party module that is not in the production inventory")
        return ("external", dotted)

    @staticmethod
    def certain(name: str, bindings: list[Binding], where: str) -> Binding:
        """The one binding a name has in a namespace, or the reason it has no single certain one."""
        if not bindings:
            raise Unresolved("SRC-NAME-UNRESOLVED", f"{name} is not bound in {where}")
        distinct = {(b.role, b.ref) for b in bindings}
        if len(distinct) > 1 or all(b.conditional for b in bindings):
            raise Unresolved("SRC-BINDING-COMPETING", f"{name} has competing or conditional bindings in {where} (lines {', '.join(str(b.line) for b in bindings)})")
        return next((b for b in bindings if not b.conditional), bindings[0])

    def bound(self, path: str, scope: Scope, name: str, seen: frozenset = frozenset()) -> Ref:
        """A name used in `scope`: its own namespace first, then each enclosing function's and the module's (a class body is not enclosing)."""
        for candidate in lexical_chain(scope):
            if name in candidate.bindings:
                return self.follow(path, candidate, name, self.certain(name, candidate.bindings[name], candidate.qual or path), seen)
        if hasattr(builtins, name):
            return ("external", f"builtins.{name}")
        raise Unresolved("SRC-NAME-UNRESOLVED", f"{name} is neither defined nor imported in {path}")

    def follow(self, path: str, scope: Scope, name: str, binding: Binding, seen: frozenset) -> Ref:
        if binding.role == "class":
            return ("class", path, scope.named(name))
        if binding.role == "def":
            return ("function", path, scope.named(name))
        if binding.role == "import":
            return self.module_ref(binding.ref[1])
        if binding.role == "from":
            return self.member(self.module_ref(binding.ref[1]), binding.ref[2], seen)
        raise Unresolved("SRC-BASE-ALIAS", f"{name} is bound by {binding.role}, not by a class, a function or an import")

    def member(self, ref: Ref, attr: str, seen: frozenset = frozenset()) -> Ref:
        """The attribute `attr` of a module, package or class; a re-export is followed through its one certain binding."""
        if ref[0] == "external":
            return ("external", f"{ref[1]}.{attr}")
        if ref[0] == "function":
            raise Unresolved("SRC-NAME-UNRESOLVED", f"{ref[2]} is a function, which has no attribute {attr} the contract recognises")
        if ref[0] == "class":
            scope = self.classes[(ref[1], ref[2])].scope
            if attr not in scope.bindings:
                raise Unresolved("SRC-NAME-UNRESOLVED", f"class {ref[2]} defines no {attr}")
            return self.follow(ref[1], scope, attr, self.certain(attr, scope.bindings[attr], ref[2]), seen)
        dotted = ref[1]
        if ref[0] == "module":
            path = self.names[dotted]
            module = self.indexes[path].module
            if attr in module.bindings:
                if (path, attr) in seen:
                    raise Unresolved("SRC-BINDING-COMPETING", f"{dotted}.{attr} is imported through itself")
                return self.follow(path, module, attr, self.certain(attr, module.bindings[attr], dotted), seen | {(path, attr)})
        sub = f"{dotted}.{attr}"
        if sub in self.names or sub in self.packages:
            return self.module_ref(sub)
        raise Unresolved("SRC-NAME-UNRESOLVED", f"{dotted} defines no {attr}")

    def expr(self, path: str, scope: Scope, node: ast.expr) -> Ref:
        if isinstance(node, ast.Name):
            return self.bound(path, scope, node.id)
        if isinstance(node, ast.Attribute):
            return self.member(self.expr(path, scope, node.value), node.attr)
        raise Unresolved("SRC-BASE-SHAPE", f"{ast.unparse(node)} is not a name or an attribute chain")

    # -- class bases and the C3 order ------------------------------------------------------------------------------------

    def mro(self, key: tuple[str, str], building: tuple = ()) -> list:
        """C3 linearization of a class over its bases: project classes are (file, qualified name); an external base is an opaque entry, ("base", resolved identity), that
        stands for the class and ALL its ancestors; `object` is the implicit last base of every class, as in Python, so `class C(object, A)` is inconsistent here as it is there."""
        if key in self._mro:
            return self._mro[key]
        if key in building:
            raise ValueError("inheritance cycle")
        sequences, direct = [], []
        for _text, ref in self.classes[key].bases:
            node = (ref[1], ref[2]) if ref[0] == "class" else ("base", ref[1])
            direct.append(node)
            sequences.append(self.mro(node, building + (key,)) if ref[0] == "class" else [node] if node == OBJECT else [node, OBJECT])
        self._mro[key] = [key] + (c3_merge(sequences + [direct]) if direct else [OBJECT])
        return self._mro[key]

    def family(self, key: tuple[str, str]) -> list[tuple[str, str]]:
        """The project classes in a class's method-resolution order (itself first)."""
        return [member for member in self.mro(key) if member[0] != "base"]


def identify(path: str, scope: Scope, node: ast.expr, seen: frozenset = frozenset()) -> str:
    """The dotted identity a name or attribute chain certainly has in `scope`, from the file's own bindings alone: an import binds `module` or `module.name`, a
    definition `<module of this file>.<qualified name>`, an unbound builtin `builtins.<name>`, and a name bound ONCE, directly, to another name or attribute chain
    (`loader = import_module`) has the identity of that chain. A name with competing, conditional or other bindings (an assignment of a call, a parameter, a loop target
    ...) has no certain identity: Unresolved, SRC-DECORATOR-SHADOWED. Decorators and the contract's loader sites are recognised by this identity, never by their
    spelling, so an alias of a loader is the loader."""
    if isinstance(node, ast.Attribute):
        return f"{identify(path, scope, node.value, seen)}.{node.attr}"
    if not isinstance(node, ast.Name):
        raise Unresolved("SRC-DECORATOR-UNKNOWN", f"{ast.unparse(node)} is not a name or an attribute chain")
    for candidate in lexical_chain(scope):
        if node.id in candidate.bindings:
            bindings = candidate.bindings[node.id]
            alias = bindings[0].role == "assign" and bindings[0].ref[:1] == ("alias",) and (id(candidate), node.id) not in seen
            if len({(b.role, b.ref) for b in bindings}) > 1 or all(b.conditional for b in bindings) or (bindings[0].role not in ("import", "from", "def", "class") and not alias):
                raise Unresolved("SRC-DECORATOR-SHADOWED", f"{node.id} is not bound once, unconditionally, by an import or a definition (it is {', '.join(sorted({b.role for b in bindings}))}, "
                                 f"line {bindings[0].line})")
            binding = bindings[0]
            if alias:
                return identify(path, candidate, binding.source, seen | {(id(candidate), node.id)})
            if binding.role == "import":
                return binding.ref[1]
            if binding.role == "from":
                return f"{binding.ref[1]}.{binding.ref[2]}"
            return f"{module_name(path)}.{candidate.named(node.id)}"
    if hasattr(builtins, node.id):
        return f"builtins.{node.id}"
    raise Unresolved("SRC-DECORATOR-UNKNOWN", f"{node.id} is neither defined nor imported in {path}")


# --- queries the locator checker asks, over the same facts -----------------------------------------------------------

def declares(index: FileIndex, name: str) -> bool:
    """Declaration-in-file query: the file defines, assigns or declares the plain `name` ANYWHERE (in a class, a function, a branch), scopes and conditions aside.
    `path::name` locators ask this; a dotted name (`Class.method`) is the other query, `module_attribute`."""
    return any(found == name and any(b.role in DECLARING for b in bindings) for scope in index.scopes for found, bindings in scope.bindings.items())


def module_attribute(index: FileIndex, chain: list[str], owner_ok=lambda cls: True) -> str | None:
    """Module/class-attribute query: why `chain` (a name, then class attributes) is not an attribute the module certainly has, or None when it is. Each
    step must be bound once, unconditionally, by a def, class or assignment in the namespace it is looked up in (an import is not a definition there);
    each owner on the way must be a class `owner_ok` accepts (the contract: decorators and keywords it models), so a replaced or unsupported owner satisfies
    nothing. A module with a star import can have any name replaced and is refused."""
    if index.star_imports:
        return "the module has a star import: its exports are not certain, cite the defining module"
    scope = index.module
    for position, name in enumerate(chain):
        bindings = scope.bindings.get(name, [])
        if len(bindings) != 1 or bindings[0].conditional or bindings[0].role not in CERTAIN:
            return f"{name} is not bound exactly once, unconditionally, by a definition in {scope.qual or 'the module'}"
        if position == len(chain) - 1:
            return None
        owner = next((c for c in index.classes.values() if c.qual == scope.named(name)), None)
        if owner is None:   # a class declaration of that qualified name is the one certain binding that is a class
            return f"{name} is not a class, so it has no attribute {chain[position + 1]}"
        if not owner_ok(owner):
            return f"class {name} is not a supported owner (a decorator or metaclass the contract does not model)"
        scope = owner.scope
    return None
