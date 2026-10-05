"""Gen-2 source facts: the one recognition boundary (task 2q-a-repair-3; docs/gen2/SOURCE-CONTRACT.md).

Gate D #4 found one cause behind the architecture ratchet's R1-R4 findings: three tools (the metrics resolver, the function inventory and the
locator checker) each rebuilt names, scopes and class ownership from the same source, so a form one of them mis-read became an apparent improvement
that the closed accounting then preserved. This module parses every production file ONCE, for both services, into one index:

  * definitions and scopes: every `def`, `async def` and `class`, in the lexical scope that holds it, with its qualified name, its decorators and
    whether a compound statement guards it;
  * binding roles: every occurrence that binds a name in a scope, with its role (class, def, import, import from, star, assign, augmented assign,
    target, walrus, delete, parameter, global/nonlocal write) and whether it is conditional;
  * class bases, resolved by the one name resolver below, and the C3 order over the project classes;
  * method ownership: the methods a class declares directly, and each method's receiver;
  * diagnostics: every construct the structural rows of the source contract refuse (a duplicate definition, a conditional class or method, a
    rebound definition, a star import, an unresolvable base ...), each naming file, line, construct and remediation.

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


@dataclass
class Binding:
    """One occurrence that binds a name in a scope. `ref` is ("module", dotted) or ("from", module, name) for the import roles."""
    role: str      # class def import from star assign annotation augassign target walrus delete param global_write nonlocal_write
    line: int
    conditional: bool = False
    ref: tuple = ()


class Scope:
    __slots__ = ("kind", "qual", "node", "parent", "bindings", "declared")

    def __init__(self, kind: str, qual: str, node: ast.AST, parent: "Scope | None") -> None:
        self.kind, self.qual, self.node, self.parent = kind, qual, node, parent   # module | class | function
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

    @property
    def key(self) -> tuple[str, str]:
        return (self.path, self.qual)


class FileIndex:
    """One file's facts: scopes with their bindings, definitions, classes and the structural diagnostics found while reading it."""

    def __init__(self, path: str, tree: ast.Module) -> None:
        self.path, self.tree = path, tree
        self.module = Scope("module", "", tree, None)
        self.functions: list[FunctionFact] = []
        self.classes: dict[str, ClassFact] = {}
        self.scopes: list[Scope] = [self.module]
        self.diagnostics: list[Diagnostic] = []
        self.star_imports: list[int] = []
        _Builder(self).run()


def statement_blocks(node: ast.AST):
    """The statement lists a compound statement holds, in source order (an `except` handler's and a `case`'s body included)."""
    for name, value in ast.iter_fields(node):
        if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
            yield value
        elif name == "handlers":
            for handler in value:
                yield handler.body
        elif name == "cases":
            for case in value:
                yield case.body


class _Builder:
    def __init__(self, index: FileIndex) -> None:
        self.index = index

    def run(self) -> None:
        index = self.index
        self.body(index.tree.body, index.module, False)
        for scope in index.scopes:
            self.structure(scope)

    # -- scopes and definitions --

    def diagnose(self, category: str, line: int, construct: str, remediation: str) -> None:
        self.index.diagnostics.append(Diagnostic(category, self.index.path, line, construct, remediation))

    def bind(self, scope: Scope, name: str, role: str, line: int, conditional: bool, ref: tuple = ()) -> None:
        if name in scope.declared and role in ("assign", "augassign", "target", "walrus", "delete", "def", "class"):
            kind = scope.declared[name]
            target = self.index.module if kind == "global" else next((s for s in self._enclosing(scope) if s.kind == "function"), scope)
            role, scope = f"{kind}_write", target
        scope.bind(name, Binding(role, line, conditional, ref))

    @staticmethod
    def _enclosing(scope: Scope):
        scope = scope.parent
        while scope is not None:
            yield scope
            scope = scope.parent

    def body(self, statements: list[ast.stmt], scope: Scope, nested: bool) -> None:
        for node in statements:
            if isinstance(node, ast.ClassDef):
                self.class_def(node, scope, nested)
            elif isinstance(node, FUNCTIONS):
                self.function_def(node, scope, nested)
            else:
                self.other(node, scope, nested)

    def class_def(self, node: ast.ClassDef, scope: Scope, nested: bool) -> None:
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
        for expression in (*node.decorator_list, *node.bases, *(k.value for k in node.keywords)):
            self.writes(expression, scope, nested, "target")
        self.body(node.body, inner, False)

    def function_def(self, node: ast.FunctionDef | ast.AsyncFunctionDef, scope: Scope, nested: bool) -> None:
        self.bind(scope, node.name, "def", node.lineno, nested)
        if nested and scope.kind == "class":
            self.diagnose("SRC-METHOD-CONDITIONAL", node.lineno, f"method {node.name} is declared inside a compound statement of class {scope.qual}",
                          "declare the method directly in the class body")
        inner = Scope("function", scope.named(node.name), node, scope)
        fact = FunctionFact(self.index.path, inner.qual, node, inner, scope, nested)
        self.index.functions.append(fact)
        self.index.scopes.append(inner)
        args = node.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
            if arg is not None:
                inner.bind(arg.arg, Binding("param", arg.lineno))
        for expression in (*node.decorator_list, *args.defaults, *(d for d in args.kw_defaults if d is not None)):
            self.writes(expression, scope, nested, "target")
        self.body(node.body, inner, False)

    # -- every other statement: imports, writes, compound blocks --

    def other(self, node: ast.stmt, scope: Scope, nested: bool) -> None:
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.partition(".")[0]
                self.bind(scope, name, "import", node.lineno, nested, ("module", alias.name if alias.asname else alias.name.partition(".")[0]))
        elif isinstance(node, ast.ImportFrom):
            base = absolute_module(self.index.path, node.level, node.module)
            for alias in node.names:
                if alias.name == "*":
                    self.index.star_imports.append(node.lineno)
                    self.bind(scope, "*", "star", node.lineno, nested, ("star", base))
                else:
                    self.bind(scope, alias.asname or alias.name, "from", node.lineno, nested, ("from", base, alias.name))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            scope.declared.update({name: "global" if isinstance(node, ast.Global) else "nonlocal" for name in node.names})
        role = "augassign" if isinstance(node, ast.AugAssign) else "assign" if isinstance(node, (ast.Assign, ast.AnnAssign)) else "target"
        self.writes(node, scope, nested, role)
        for block in statement_blocks(node):
            self.body(block, scope, True)

    def writes(self, node: ast.AST, scope: Scope, nested: bool, role: str) -> None:
        """Bind the names a statement (or an expression) writes in its own scope: store and delete targets, `except ... as`, match captures, walrus
        targets (also inside a comprehension, which binds them in the scope that holds it). Nested statements, lambdas and comprehension targets
        have their own scopes and are not entered here."""
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(scope, node.id, "delete" if isinstance(node.ctx, ast.Del) else role, node.lineno, nested)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and node.name:
            self.bind(scope, node.name, "target", getattr(node, "lineno", 0), True)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            self.bind(scope, node.rest, "target", 0, True)
        elif isinstance(node, ast.NamedExpr):
            self.writes(node.value, scope, nested, "walrus")
            self.bind(scope, node.target.id, "walrus", node.lineno, nested)
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.stmt, ast.Lambda)) or (isinstance(node, ast.comprehension) and child is node.target):
                continue
            self.writes(child, scope, nested, "annotation" if isinstance(node, ast.AnnAssign) and child is node.target and node.value is None else role)

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
        """C3 linearization of a class over its project bases: project classes are (file, qualified name); an external base is an opaque entry."""
        if key in self._mro:
            return self._mro[key]
        if key in building:
            raise ValueError("inheritance cycle")
        sequences, direct = [], []
        for text, ref in self.classes[key].bases:
            node = (ref[1], ref[2]) if ref[0] == "class" else ("base", text)
            direct.append(node)
            sequences.append(self.mro(node, building + (key,)) if ref[0] == "class" else [node])
        self._mro[key] = [key] + c3_merge(sequences + [direct])
        return self._mro[key]

    def family(self, key: tuple[str, str]) -> list[tuple[str, str]]:
        """The project classes in a class's method-resolution order (itself first)."""
        return [member for member in self.mro(key) if member[0] != "base"]


def identify(path: str, scope: Scope, node: ast.expr) -> str:
    """The dotted identity a name or attribute chain certainly has in `scope`, from the file's own bindings alone: an import binds `module` or `module.name`, a
    definition `<module of this file>.<qualified name>`, an unbound builtin `builtins.<name>`. A name with competing, conditional or non-import bindings (an
    assignment, a parameter, a loop target ...) has no certain identity: Unresolved, SRC-DECORATOR-SHADOWED. Decorators and the contract's loader sites are
    recognised by this identity, never by their spelling."""
    if isinstance(node, ast.Attribute):
        return f"{identify(path, scope, node.value)}.{node.attr}"
    if not isinstance(node, ast.Name):
        raise Unresolved("SRC-DECORATOR-UNKNOWN", f"{ast.unparse(node)} is not a name or an attribute chain")
    for candidate in lexical_chain(scope):
        if node.id in candidate.bindings:
            bindings = candidate.bindings[node.id]
            if len({(b.role, b.ref) for b in bindings}) > 1 or all(b.conditional for b in bindings) or bindings[0].role not in ("import", "from", "def", "class"):
                raise Unresolved("SRC-DECORATOR-SHADOWED", f"{node.id} is not bound once, unconditionally, by an import or a definition (it is {', '.join(sorted({b.role for b in bindings}))}, "
                                 f"line {bindings[0].line})")
            binding = bindings[0]
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
