"""Gen-2 source facts: the one recognition boundary (tasks 2q-a-repair-3 and 2q-a-repair-4; docs/gen2/SOURCE-CONTRACT.md).

Gate D #4 found one cause behind the architecture ratchet's R1-R4 findings: three tools (the metrics resolver, the function inventory and the
locator checker) each rebuilt names, scopes and class ownership from the same source, so a form one of them mis-read became an apparent improvement
that the closed accounting then preserved. This module parses every production file ONCE, for both services, into one index:

  * definitions and scopes: every `def`, `async def`, `class`, lambda and comprehension, in the lexical scope that holds it, with its qualified name,
    its decorators and whether a compound statement guards it;
  * binding roles: every occurrence that binds a name in a scope, with its role (class, def, import, import from, star, assign, annotation, augmented
    assign, target, walrus, delete, parameter, global/nonlocal write) and whether it is conditional, and the expression whose value it binds;
  * store sites (an attribute or an item written or deleted) and call sites, each with the scope that holds it;
  * class bases, resolved by the one name resolver below (`Facts.expr`, which every consumer asks: bases, decorator, loader and call identities, store kinds, field markers, locator owners;
    task 2q-a-repair-5), and the C3 order over the project classes (`object` implicit and last, as Python has it);
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

SCOPE IS THE COMPILER'S (task 2q-a-repair-6; Astra's 2q-a-repair-5 review F1). Which scope a name lives in (local, declared or implicit global, nonlocal, free) is answered by the
standard library's `symtable`, the compiler's own scope analysis, and by nothing hand-written here (`locate`, the one rule every use and every write goes through). The index records
WHAT a binding refers to; the table decides WHERE the name lives. A file the compiler itself refuses (an invalid `nonlocal`) is refused with the compiler's message and has no facts.

THE PAIRING IS THE COMPILER'S ORDER, AND PROVED (task 2q-a-repair-6b; Astra's 2q-a-repair-6 review R6-1 and R6-2). Each scope of the tree gets the table the compiler built for it by
following the order in which the compiler enters scopes (`entered`: a comprehension's first iterable, a function's defaults, decorators and annotations and a class's decorators and
bases are read where the scope is written, before its block), never by a header that two scopes can share. Every pairing is then VALIDATED BOTH WAYS (`validate`): the names the tree
mentions in a scope, spelled as the compiler spells them (private names mangled, `mangle`), must be the table's identifiers, and the table may hold nothing else but the compiler's own
names and the free names of the scopes below it; a scope without a table, a table without a scope or any disagreement refuses the file. A name the table lacks is never a global: a
binding written for a name the table does not hold is refused, and only a name an unevaluated annotation mentions (`from __future__ import annotations`) takes the module's namespace.
The correspondence is validated for the reference interpreter, CPython 3.12.3, only (docs/gen2/SOURCE-CONTRACT.md).

Standard library only. Files outside the production inventory (tests, tools) can be indexed with the same code for the locator checker's
queries (`index_text`); their diagnostics are not the contract's concern.
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import symtable
from dataclasses import dataclass, field
from itertools import zip_longest
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


def mangle(private: str | None, name: str) -> str:
    """Python's private-name mangling (the language reference, "Private name mangling"; CPython `_Py_Mangle`): inside a class body `__name` (not ending in two underscores, no dot)
    is `_Class__name` with the class name's leading underscores stripped, and nothing is mangled when the class name is all underscores. `private` is the class the name is written in."""
    if private is None or not name.startswith("__") or name.endswith("__") or "." in name or not (stripped := private.lstrip("_")):
        return name
    return f"_{stripped}{name}"


class Scope:
    __slots__ = ("kind", "qual", "node", "parent", "bindings", "table", "private", "mentioned", "hidden", "below")

    def __init__(self, kind: str, qual: str, node: ast.AST, parent: "Scope | None") -> None:
        self.kind, self.qual, self.node, self.parent = kind, qual, node, parent   # module | class | function | lambda | comprehension
        self.bindings: dict[str, list[Binding]] = {}   # keyed by the name as WRITTEN: the compiler's mangled spelling (`mangle`) is the table's key, never this one
        self.table: symtable.SymbolTable | None = None   # the compiler's table for this scope (a list, set or dict comprehension CPython inlines has none)
        self.private: str | None = node.name if kind == "class" else parent.private if parent else None   # the class whose name mangles the names written here (a nested function has its class's)
        self.mentioned: set[str] = set()   # the names the tree writes in this scope, as the compiler spells them: `validate` compares them with the table
        self.hidden: set[str] = set()      # the names only an unevaluated annotation writes here (`from __future__ import annotations`): the compiler's table does not hold them
        self.below: set[str] = set()       # the names the scopes nested in this one write (`validate`: the free ones the compiler passes up into this table)

    def bind(self, name: str, binding: Binding) -> None:
        self.bindings.setdefault(name, []).append(binding)

    def symbol(self, spelled: str) -> symtable.Symbol | None:
        """The compiler's entry for a name, as the compiler spells it, in this scope's table, or None: the table holds no entry for a name this scope does not write."""
        try:
            return self.table.lookup(spelled) if self.table is not None else None
        except KeyError:
            return None

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

    def __init__(self, path: str, tree: ast.Module, text: str) -> None:
        """`text` is the source `tree` was parsed from: the compiler's symbol table is built from it."""
        self.path, self.tree = path, tree
        self.module = Scope("module", "", tree, None)
        self.functions: list[FunctionFact] = []
        self.classes: dict[str, ClassFact] = {}
        self.scopes: list[Scope] = [self.module]
        self.diagnostics: list[Diagnostic] = []
        self.star_imports: list[int] = []
        self.stores: list[Store] = []
        self.calls: list[CallSite] = []
        try:
            table = symtable.symtable(text, path, "exec")
        except SyntaxError as exc:   # the compiler refuses the file (an invalid `nonlocal`): no scope can be told from a table it will not build, so the file has no facts
            self.diagnostics.append(Diagnostic("SRC-INV-PARSE", path, exc.lineno or 0, f"the compiler refuses the file: {exc.msg}", "fix the source: Python itself will not run it"))
            return
        _Builder(self, table).run()


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


MISMATCH = "the index and the compiler's symbol table disagree about this scope: that is a defect of this tool, not of the source; report it rather than work around it"
FORM_REMEDY = ("write the form with a construct the contract records, or amend the contract (docs/gen2/SOURCE-CONTRACT.md, operator-reviewed) before using it: a form with no "
               "record binds or stores in a way the metrics cannot state")


def chain_text(node: ast.AST | None) -> str | None:
    """The dotted text of a pure name-and-attribute chain (`a`, `a.b.c`), or None for any other expression."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return ".".join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else None


TABLE_NAMES = {ast.Lambda: "lambda", ast.ListComp: "listcomp", ast.SetComp: "setcomp", ast.DictComp: "dictcomp", ast.GeneratorExp: "genexpr"}   # the names the compiler gives these scopes
INLINED = (ast.ListComp, ast.SetComp, ast.DictComp)   # CPython 3.12 inlines these into the table of the scope holding them (PEP 709); a generator expression keeps its own


def parameters_of(args: ast.arguments) -> list[ast.arg]:
    return [*args.posonlyargs, *args.args, *args.kwonlyargs, *(a for a in (args.vararg, args.kwarg) if a is not None)]


SCOPES = (*FUNCTIONS, ast.ClassDef, ast.Lambda, *INLINED, ast.GeneratorExp)
READ_ORDER = {ast.Try: ("body", "orelse", "handlers", "finalbody"), ast.TryStar: ("body", "orelse", "handlers", "finalbody")}   # the statements whose fields the compiler reads in another order than the tree lists them


def before(node: ast.AST, future: bool) -> list:
    """What the compiler reads where a scope is WRITTEN, before it enters the scope (CPython 3.12.3 `Python/symtable.c`, verified against `symtable` itself for every construct below): a
    comprehension's first iterable; a lambda's defaults; a function's defaults, keyword defaults, decorators, then annotations (positional, `*args`, `**kwargs`, keyword-only, the
    return: none at all under `from __future__ import annotations`); a class's decorators, bases and keywords."""
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *(k.value for k in node.keywords)]
    if not isinstance(node, (*FUNCTIONS, ast.Lambda)):
        return [node.generators[0].iter]
    args = node.args
    notes = [] if future or isinstance(node, ast.Lambda) else [a.annotation for a in (*args.posonlyargs, *args.args, args.vararg, args.kwarg, *args.kwonlyargs) if a] + [node.returns]
    return [*args.defaults, *args.kw_defaults, *getattr(node, "decorator_list", ()), *notes]


def within(node: ast.AST) -> list:
    """What the compiler reads inside the block of a scope, in its order: a comprehension reads its first target and conditions, then the other generators, then the VALUE of a
    dictionary comprehension before its key."""
    if isinstance(node, (ast.Module, *FUNCTIONS, ast.ClassDef)):
        return node.body
    if isinstance(node, ast.Lambda):
        return [node.body]
    first, *rest = node.generators
    return [first.target, *first.ifs, *(x for g in rest for x in (g.target, g.iter, *g.ifs)), *((node.value, node.key) if isinstance(node, ast.DictComp) else (node.elt,))]


def entered(nodes, future: bool):
    """The scopes the compiler enters, in the order it enters them, while it reads `nodes` in one block. A list, set or dict comprehension is inlined (PEP 709): what is written
    inside it is read in the block that holds it, and the comprehension itself has no table."""
    for node in nodes:
        if isinstance(node, SCOPES):
            yield from entered(before(node, future), future)
            yield node
            if isinstance(node, INLINED):
                yield from entered(within(node), future)
        elif isinstance(node, ast.AST):
            names = READ_ORDER.get(type(node), node._fields)
            yield from entered([child for name in names if not (future and name == "annotation") for value in [getattr(node, name, None)] for child in (value if isinstance(value, list) else [value])], future)


def internal(name: str) -> bool:
    """A name the compiler adds to a table itself: a comprehension's `.0`, `__class__` for a function that uses `super`."""
    return name.startswith(".") or name == "__class__"


def scope_kind(node: ast.AST) -> str:
    return "class" if isinstance(node, ast.ClassDef) else "lambda" if isinstance(node, ast.Lambda) else "function" if isinstance(node, FUNCTIONS) else "comprehension"


class _Builder:
    def __init__(self, index: FileIndex, table: symtable.SymbolTable) -> None:
        self.index, self.table = index, table
        self.nonlocals: list[tuple[Scope, str, Binding]] = []   # the `nonlocal` writes, placed once every scope has its bindings (the owner is the compiler's; the order is the source's)
        self.future = any(isinstance(s, ast.ImportFrom) and s.module == "__future__" and not s.level and any(a.name == "annotations" for a in s.names) for s in index.tree.body)
        self.hidden = 0   # above zero while an annotation the compiler does not read (`from __future__ import annotations`) is being walked
        self.tables: dict[int, symtable.SymbolTable | None] = {}   # the compiler's table for each scope node of the tree, None for the comprehensions it inlines
        self.unpaired: list[tuple[int, str, str]] = []   # (line, what, remedy) of each scope and table that could not be paired: reported after the walk, behind the form that explains them
        self.refused = False   # a form was refused: the tree is then not what the compiler read, and the pairing's refusals would only repeat that one

    def run(self) -> None:
        index = self.index
        self.pair(index.tree, self.table)
        index.module.table = self.table
        self.block(index.tree.body, index.module, False)
        for owner, name, binding in self.nonlocals:
            owner.bind(name, binding)
        for scope in index.scopes:
            self.structure(scope)
        if not self.refused:
            for line, construct, remedy in self.unpaired:
                self.diagnose("SRC-FORM-UNRECOGNISED", line, construct, remedy)
            self.validate()

    def pair(self, owner: ast.AST, table: symtable.SymbolTable) -> None:
        """Give every scope written in the block of `owner` the compiler's table for it, in the order the compiler entered them (`entered`): one table per scope, each of the kind, name and line the
        scope has. A scope with no table, a table with no scope and a pair that differs are refused; only a list, set or dict comprehension has no table (CPython inlines it)."""
        nodes = list(entered(within(owner), self.future))
        self.tables.update({id(n): None for n in nodes if isinstance(n, INLINED)})
        for node, child in zip_longest([n for n in nodes if not isinstance(n, INLINED)], table.get_children()):
            if node is None:
                self.unpaired.append((child.get_lineno(), f"the compiler's table for {child.get_name()} has no scope of the index to match", MISMATCH))
            elif child is None or (getattr(child.get_type(), "value", child.get_type()), child.get_name(), child.get_lineno()) != (
                    "class" if isinstance(node, ast.ClassDef) else "function", TABLE_NAMES.get(type(node)) or node.name, node.lineno):
                self.unpaired.append((node.lineno, f"the compiler's symbol table has no matching scope for {scope_kind(node)} {TABLE_NAMES.get(type(node)) or node.name} at this line", MISMATCH))
            else:
                self.tables[id(node)] = child
                self.pair(node, child)

    def attach(self, scope: Scope) -> None:
        """A scope of the walk takes the table `pair` gave its node: a scope it never reached (one inside an annotation the compiler does not read) has none, and is refused."""
        if id(scope.node) in self.tables:
            scope.table = self.tables[id(scope.node)]
        else:
            self.unpaired.append((scope.node.lineno, f"a {scope.kind} the compiler builds no table for (it is written where the compiler reads nothing)", FORM_REMEDY))

    def mention(self, scope: Scope, name: str) -> None:
        """The tree writes `name` in `scope`: the compiler holds it, spelled `mangle`d, in the scope's table, unless an annotation it does not read is all that writes it."""
        (scope.hidden if self.hidden else scope.mentioned).add(mangle(scope.private, name))

    def validate(self) -> None:
        """Every pairing is proved both ways. The names the tree writes in a scope (a comprehension the compiler inlines belongs to the scope that holds it) must all be in its table; and
        the table may hold only those, the compiler's own names (`.0`, `__class__`) and the free names of the scopes below that it passes up. Anything else means this scope is not the one the
        table was built for."""
        scopes = [s for s in self.index.scopes if s.table is not None or s.parent is None]
        def holder(scope: Scope) -> Scope:
            while scope.table is None and scope.parent is not None:
                scope = scope.parent
            return scope
        for scope in self.index.scopes:
            holder(scope).mentioned |= scope.mentioned
        for scope in reversed(scopes):
            if scope.parent is not None:
                holder(scope.parent).below |= scope.mentioned | scope.below
        for scope in scopes:
            table, written = scope.table, scope.mentioned
            held = {s.get_name() for s in table.get_symbols()}
            lacking = sorted(n for n in written - held if not internal(n))
            extra = sorted(n for n in held - written if not internal(n) and not (n in scope.below and table.lookup(n).is_free()))
            for names, what in ((lacking, "the tree writes {} but the compiler's table has no such name"), (extra, "the compiler's table holds {} that the tree does not write here")):
                if names:
                    self.diagnose("SRC-FORM-UNRECOGNISED", getattr(scope.node, "lineno", 1), f"in {scope.qual or 'the module'}: " + what.format(", ".join(names)), MISMATCH)

    # -- the dispatcher ----------------------------------------------------------------------------------------------

    def visit(self, node: ast.AST, scope: Scope, nested: bool, target: Target | None = None) -> None:
        """Every node goes through here, once: the form's handler records its effect, and a node class with no form is refused."""
        form = FORMS.get(type(node).__name__)
        if form is None:
            self.refused = True
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

    def annotations(self, nodes, scope: Scope, nested: bool) -> None:
        """Annotations: the compiler reads none under `from __future__ import annotations`, so the names in them are the tree's alone (`mention`) and they bind nothing."""
        self.hidden += self.future
        self.each(nodes, scope, nested)
        self.hidden -= self.future

    # -- scopes and definitions --

    def diagnose(self, category: str, line: int, construct: str, remediation: str) -> None:
        self.index.diagnostics.append(Diagnostic(category, self.index.path, line, construct, remediation))

    def bind(self, scope: Scope, name: str, role: str, line: int, conditional: bool, ref: tuple = (), source: ast.AST | None = None, direct: bool = False,
             annotated: ast.AST | None = None) -> None:
        """The one place a binding is recorded. WHERE the name lives is the compiler's answer (`locate`): a `global` or `nonlocal` declaration sends EVERY kind of binding (an import
        and a definition as much as an assignment) to the module or to the enclosing function that binds the name, and a comprehension's iteration variable stays in it."""
        if self.hidden:   # an annotation the compiler does not read binds nothing
            return
        if role != "star":
            self.mention(scope, name)
        if role == "walrus":   # the compiler records it in the scope that holds the comprehension too
            self.mention(holding(scope), name)
        try:
            owner = scope if role == "star" or (scope.kind == "comprehension" and role == "target") else locate(scope, name, bound=True)
        except Unresolved as exc:   # the table has no symbol for a name written here: it is never read as a global
            self.diagnose("SRC-FORM-UNRECOGNISED", line, exc.why, MISMATCH)
            return
        if owner is not scope and owner is not holding(scope):
            binding = Binding("global_write" if owner.kind == "module" else "nonlocal_write", line, conditional, (), source, direct, annotated, scope)
            if owner.kind == "module":
                owner.bind(mangle(scope.private, name), binding)   # a module's names are the compiler's: the one a class writes `global __g` for is `_C__g`, not the module's own `__g`
            else:
                self.nonlocals.append((owner, name, binding))
            return
        if role == "assign" and direct and chain_text(source) is not None:
            ref = ("alias", chain_text(source))   # a name bound to a name or an attribute chain forwards that identity
        owner.bind(name, Binding(role, line, conditional, ref, source, direct, annotated, scope))

    def new_scope(self, kind: str, qual: str, node: ast.AST, parent: Scope) -> Scope:
        inner = Scope(kind, qual, node, parent)
        self.index.scopes.append(inner)
        self.attach(inner)
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
        inner = self.new_scope("class", scope.named(node.name), node, scope)
        fact = ClassFact(self.index.path, inner.qual, node, inner, scope, nested)
        key, n = inner.qual, 2
        while key in self.index.classes:   # a duplicate is refused below; both stay in the index so nothing disappears
            key, n = f"{inner.qual}#{n}", n + 1
        self.index.classes[key] = fact
        self.each(getattr(node, "type_params", ()), scope, nested)
        self.each((*node.decorator_list, *node.bases, *(k.value for k in node.keywords)), scope, nested)
        self.block(node.body, inner, False)

    def parameters(self, args: ast.arguments, inner: Scope) -> list[ast.arg]:
        every = parameters_of(args)
        for arg in every:
            inner.bind(arg.arg, Binding("param", arg.lineno))
            self.mention(inner, arg.arg)
        return every

    def form_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: Scope, nested: bool, target) -> None:
        self.bind(scope, node.name, "def", node.lineno, nested)
        if nested and scope.kind == "class":
            self.diagnose("SRC-METHOD-CONDITIONAL", node.lineno, f"method {node.name} is declared inside a compound statement of class {scope.qual}",
                          "declare the method directly in the class body")
        inner = self.new_scope("function", scope.named(node.name), node, scope)
        fact = FunctionFact(self.index.path, inner.qual, node, inner, scope, nested)
        self.index.functions.append(fact)
        args = node.args
        every = self.parameters(args, inner)
        # everything in the header is evaluated where the function is DEFINED: decorators, defaults, every annotation, the return annotation
        self.each(getattr(node, "type_params", ()), scope, nested)
        self.each((*node.decorator_list, *args.defaults, *args.kw_defaults), scope, nested)
        self.annotations((*(a.annotation for a in every), node.returns), scope, nested)
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
        """`global` and `nonlocal` only say where a name lives, and the compiler's table answers that (`locate`): they record no binding. The compiler does hold the names, and a `global` one in the module's table too."""
        for name in node.names:
            self.mention(scope, name)
            if isinstance(node, ast.Global):
                self.mention(self.index.module, mangle(scope.private, name))   # already spelled: the module's own `private` is None, so it is not mangled again

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
        self.annotations([node.annotation], scope, nested)
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
        self.bind(scope, node.target.id, "walrus", node.lineno, nested, source=node.value, direct=True)   # inside a comprehension the compiler's table puts it where the comprehension is written

    # -- names, attributes, items, calls --

    def form_name(self, node: ast.Name, scope: Scope, nested: bool, target: Target | None) -> None:
        self.mention(scope, node.id)
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            if target is None:
                self.refused = True
                self.diagnose("SRC-FORM-UNRECOGNISED", node.lineno, f"the name {node.id} is written where no statement says how", FORM_REMEDY)
                return
            self.bind(scope, node.id, "delete" if isinstance(node.ctx, ast.Del) else target.role, node.lineno, nested, source=target.source, direct=target.direct,
                      annotated=target.annotated)

    def form_container(self, node, scope: Scope, nested: bool, target: Target | None) -> None:
        if target is None or not isinstance(node.ctx, (ast.Store, ast.Del)):
            self.each(ast.iter_child_nodes(node), scope, nested)
        elif (values := paired_values(node, target)) is not None:   # `a, b = x, y` binds a to x and b to y: each name is bound to a whole value of its own
            for element, value in zip(node.elts, values):
                self.visit(element, scope, nested, Target(target.role, value, target.annotated))
        else:
            self.each(ast.iter_child_nodes(node), scope, nested, replace_target(target))

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
        spellings: dict[str, tuple[str, list[Binding]]] = {}   # one name to the compiler, however it is written: `__h` and `_C__h` are the one name in class C
        for name, bindings in scope.bindings.items():
            spellings.setdefault(mangle(scope.private, name), (name, []))[1].extend(bindings)
        for name, bindings in spellings.values():
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


def paired_values(node: ast.AST, target: Target) -> list[ast.expr] | None:
    """The values a literal tuple or list assigned to a literal tuple or list of targets gives them one by one, or None (a starred element, a different count, a value that
    is no literal: the names are then elements of one value). Only an assignment pairs: a loop's or a `with`'s target takes elements of what it iterates."""
    source = target.source
    if target.role != "assign" or not isinstance(node, (ast.Tuple, ast.List)) or not isinstance(source, (ast.Tuple, ast.List)) or len(node.elts) != len(source.elts):
        return None
    return None if any(isinstance(e, ast.Starred) for e in (*node.elts, *source.elts)) else source.elts


def index_text(path: str, text: str) -> FileIndex:
    """The facts of any Python text (the locator checker indexes tests and tools this way); a SyntaxError of the parser propagates."""
    return FileIndex(path, ast.parse(text, filename=path), text)


# --- the whole production inventory --------------------------------------------------------------------------------

class Unresolved(Exception):
    """A name that cannot be followed to one certain definition (`category` is the contract's refusal category). `identity` marks a name whose competing bindings include one that carries an
    identity (an import, a definition, a class, an alias); `alias` marks an ordinary alias (`loader = import_module`) of such a name, or of itself. That is not "no recognised identity": the
    alias may have captured the one the contract refuses, so every consumer refuses it."""

    def __init__(self, category: str, why: str, alias: bool = False, identity: bool = False) -> None:
        super().__init__(why)
        self.category, self.why, self.alias, self.identity = category, why, alias, identity


def enclosing(scope: Scope):
    """The scopes around `scope`, nearest first, the module last."""
    while scope.parent is not None:
        scope = scope.parent
        yield scope


def module_of(scope: Scope) -> Scope:
    return scope if scope.parent is None else module_of(scope.parent)


def holding(scope: Scope) -> Scope:
    """The scope a comprehension is written in (PEP 572: its assignment expressions bind there); any other scope is its own."""
    while scope.kind == "comprehension" and scope.parent is not None:
        scope = scope.parent
    return scope


def locate(scope: Scope, name: str, bound: bool = False) -> Scope:
    """The scope whose namespace a name used or written in `scope` belongs to, as the COMPILER decides it (task 2q-a-repair-6): the standard library's `symtable` is the only authority for
    local, declared or implicit global, nonlocal and free, so no rule of this index decides a scope; the name is asked for as the compiler spells it (`mangle`, task 2q-a-repair-6b). A local
    name is the scope's own, a global one the module's, a free or nonlocal one the nearest enclosing function whose table has it local (a class body between is never one). What the table
    does not say, in four places only: a comprehension's own iteration variables stay inside it; a list, set or dict comprehension CPython inlines has no table, so its other names are those of
    the scope holding it (PEP 709); a name only an unevaluated annotation writes in the scope (`from __future__ import annotations`) is the module's, as `typing.get_type_hints` takes it
    from the module's globals; and a name the table does not hold, asked about by a consumer in a scope that never writes it, is looked up outward as any name a function does not bind.
    `bound` is a binding the tree writes in `scope`: the table must hold its name, and a name it lacks is Unresolved, never a global."""
    here = scope
    while here.table is None and here.parent is not None:
        if name in here.bindings:
            return here
        here = here.parent
    spelled = mangle(here.private, name)
    symbol = here.symbol(spelled)
    if symbol is None and spelled in here.hidden:
        return module_of(here)
    if symbol is None and bound:
        raise Unresolved("SRC-NAME-UNRESOLVED", f"the compiler's table for {here.qual or 'the module'} holds no symbol {spelled} for the binding of {name} written there")
    if symbol is not None:
        if symbol.is_global():
            return module_of(here)
        if not symbol.is_free():   # a declared `nonlocal` is free too
            return here
    binders = [outer for outer in enclosing(here) if outer.kind != "class" and (name in outer.bindings if outer.table is None else (found := outer.symbol(spelled)) is not None and found.is_local())]
    return binders[0] if binders else module_of(here)


def holder_of(scope: Scope, name: str) -> Scope | None:
    """The scope whose namespace holds the binding a use of `name` in `scope` means, or None when no scope of the file does (a builtin, or a name nothing binds): `locate`'s answer,
    which the resolver and its consumers share."""
    holder = locate(scope, name)
    return holder if name in holder.bindings else None


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
        if (diagnostic := Diagnostic(category, path, line, construct, remediation)) not in self.diagnostics:   # one refusal per site, however many consumers ask
            self.diagnostics.append(diagnostic)

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
            raise Unresolved("SRC-BINDING-COMPETING", f"{name} has competing or conditional bindings in {where} (lines {', '.join(str(b.line) for b in bindings)})",
                             identity=any(b.role in ("import", "from", "class", "def") or b.ref[:1] == ("alias",) for b in bindings))
        return next((b for b in bindings if not b.conditional), bindings[0])

    def bound(self, path: str, scope: Scope, name: str, seen: frozenset = frozenset(), assignments: bool = True) -> Ref:
        """A name used in `scope`: followed through the namespace the compiler's symbol table puts it in (`holder_of`), or a builtin."""
        if (candidate := holder_of(scope, name)) is not None:
            return self.follow(path, candidate, name, self.certain(name, candidate.bindings[name], candidate.qual or path), seen, assignments)
        if hasattr(builtins, name):
            return ("external", f"builtins.{name}")
        raise Unresolved("SRC-NAME-UNRESOLVED", f"{name} is neither defined nor imported in {path}")

    def follow(self, path: str, scope: Scope, name: str, binding: Binding, seen: frozenset, assignments: bool = True) -> Ref:
        if binding.role == "class":
            return ("class", path, scope.named(name))
        if binding.role == "def":
            return ("function", path, scope.named(name))
        if binding.role == "import":
            return self.module_ref(binding.ref[1])
        if binding.role == "from":
            return self.member(self.module_ref(binding.ref[1]), binding.ref[2], seen, assignments)
        if binding.ref[:1] == ("alias",) and assignments:   # a name bound once to a name or an attribute chain (`loader = import_module`, `a, b = x, y`) is what that chain is
            if (id(scope), name) in seen:
                raise Unresolved("SRC-BINDING-COMPETING", f"{name} is an alias of itself", alias=True)
            try:
                return self.expr(path, scope, binding.source, seen | {(id(scope), name)}, assignments)
            except Unresolved as exc:
                if exc.category != "SRC-BINDING-COMPETING" or exc.alias or not exc.identity:
                    raise
                raise Unresolved(exc.category, f"{name} is an alias of {ast.unparse(binding.source)}, which {exc.why}", alias=True) from None
        raise Unresolved("SRC-BASE-ALIAS", f"{name} is bound by {binding.role}, not by a class, a function or an import")

    def member(self, ref: Ref, attr: str, seen: frozenset = frozenset(), assignments: bool = True) -> Ref:
        """The attribute `attr` of a module, package or class; a re-export is followed through its one certain binding."""
        if ref[0] == "external":
            return ("external", f"{ref[1]}.{attr}")
        if ref[0] == "function":
            raise Unresolved("SRC-NAME-UNRESOLVED", f"{ref[2]} is a function, which has no attribute {attr} the contract recognises")
        if ref[0] == "class":
            fact = self.classes.get((ref[1], ref[2]))   # a class of a file outside the production inventory (a test, a tool) is not in the facts
            if fact is None or attr not in fact.scope.bindings:
                raise Unresolved("SRC-NAME-UNRESOLVED", f"class {ref[2]} defines no {attr}")
            return self.follow(ref[1], fact.scope, attr, self.certain(attr, fact.scope.bindings[attr], ref[2]), seen, assignments)
        dotted = ref[1]
        if ref[0] == "module":
            path = self.names[dotted]
            module = self.indexes[path].module
            if attr in module.bindings:
                if (path, attr) in seen:
                    raise Unresolved("SRC-BINDING-COMPETING", f"{dotted}.{attr} is imported through itself")
                return self.follow(path, module, attr, self.certain(attr, module.bindings[attr], dotted), seen | {(path, attr)}, assignments)
        sub = f"{dotted}.{attr}"
        if sub in self.names or sub in self.packages:
            return self.module_ref(sub)
        raise Unresolved("SRC-NAME-UNRESOLVED", f"{dotted} defines no {attr}")

    def expr(self, path: str, scope: Scope, node: ast.expr, seen: frozenset = frozenset(), assignments: bool = True) -> Ref:
        """THE binding-identity resolver (task 2q-a-repair-5). A name or an attribute chain used in `scope` is followed through explicit imports, aliases (a name bound once
        to another name or chain, however it is written: `x = y`, `x, = (y,)`), qualified module chains and re-exports across files, to the class, function, module or external
        identity it certainly has, or Unresolved with the refusal category. Every consumer asks this method: the bases of a class (and so the metrics' families), the identity
        of a decorator, a loader or any call (`identity`), the kind of what a store is written through, a field marker and the owner a locator may descend through. A base
        passes `assignments=False`: the contract refuses a base bound by an assignment (SRC-BASE-ALIAS) and every other consumer follows it."""
        if isinstance(node, ast.Name):
            return self.bound(path, scope, node.id, seen, assignments)
        if isinstance(node, ast.Attribute):
            return self.member(self.expr(path, scope, node.value, seen, assignments), node.attr, seen, assignments)
        raise Unresolved("SRC-BASE-SHAPE", f"{ast.unparse(node)} is not a name or an attribute chain")

    def identity(self, path: str, scope: Scope, node: ast.expr) -> str:
        """The dotted identity a name or attribute chain certainly has (`importlib.import_module`, `builtins.exec`, `gen2.gateway_client.client._serial`), from the one resolver:
        decorators, the contract's loader and `setattr` sites and the field markers are recognised by it, never by their spelling, so an alias or a re-export of a loader is the
        loader. A name that has no certain identity is Unresolved with the decorator categories (SRC-DECORATOR-UNKNOWN: nothing says what it is; SRC-DECORATOR-SHADOWED: it is
        rebound, conditional, competing or no import or definition)."""
        try:
            ref = self.expr(path, scope, node)
        except Unresolved as exc:
            raise Unresolved("SRC-DECORATOR-SHADOWED" if exc.category in ("SRC-BINDING-COMPETING", "SRC-BASE-ALIAS") else "SRC-DECORATOR-UNKNOWN", exc.why, exc.alias) from None
        return ref[1] if ref[0] in ("module", "package", "external") else f"{module_name(ref[1])}.{ref[2]}"

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
