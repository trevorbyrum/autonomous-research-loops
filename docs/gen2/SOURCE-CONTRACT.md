# Gen-2 supported-source contract

**Version 1** (`source-contract/1`). Ratified by the operator on 2026-10-05 and implemented in task 2q-a-repair-3 (tools `tools/gen2_source_index.py` and `tools/gen2_source_contract.py`); its enforcement was completed under positive recognition in task 2q-a-repair-4 (see "Closure": the same rows and the same refusals, enforced structurally; not a change of scope). Charter: "Architecture metrics" and "Root-cause fixes, not patches"; the design record is Gate D #4 (`private/reviews/gen2-gate-d-4-astra-review.md`, §3), which proposed this contract and its finite acceptance checklist.

## What this is, and the rulings behind it

The architecture metrics (`tools/gen2_metrics.py`) are **exact over a declared, guarded supported-source subset** of Python, not over arbitrary Python (Gate D #4 option B). A source form outside the subset is **refused with an actionable diagnostic before anything is measured, recorded or certified** (a `report` or `hotspots` run is the one exception that writes anything: it writes PARTIAL tables for what could be read, marks the input incomplete, non-passing and not certified, and writes `NOT-CERTIFIED.txt` beside them; it never certifies). The refusal stage runs first in every command that reads the production source — the metrics `check`, `report`, `admit`, `rebaseline` and its bootstrap, the history `hotspots` report, and the locator check — however the command is run. It is **unwaivable**: no exemption, no numeric budget, no identity transition and no ledger entry excuses it. The cure for a refusal is to change the source (or, through an amendment below, the contract), never to classify it.

The operator's rulings of 2026-10-05, each given as "I agree" to the three recommendations of Gate D #4:

1. **Option B is adopted.** The metrics are computed exactly over this guarded subset. An unwaivable source-refusal stage precedes measurement. The repair-2 brief's permission to pass analysis by classifying an unresolved binding in the ledger (`classify` entries, the `unresolved_base` metric) is **withdrawn**; the claims and tests that relied on it are amended (see "Amended" below).
2. **The minimal production change is authorized before 2q-a acceptance.** `_no_reading` (`gateway/research_gateway/core/payload.py`) and its two uses, `Sealed` and `Passive`, are replaced by explicit, statically represented methods that share one refusal implementation; behaviour is unchanged.
3. **Sequencing.** That production change belongs to the same repair and the 2q-a family review history; it is not a separate 2q-b slice.

"Exact" means exact relative to the metric definitions in `tools/gen2_metrics.py`. The import graph counts explicit import syntax (including local and `TYPE_CHECKING` imports); it is not the runtime dependency graph. Complexity measures authored function bodies with the published AST proxies; it is not a semantic-equivalence judgment. Collaboration measures direct `self` calls between the classes of one inheritance family, attributed by C3 order; it is not a call graph. Low metric values do not establish scientific validity or software correctness.

## Closure: positive recognition

The guard does not refuse a list of known-bad spellings and trust the rest (task 2q-a-repair-3 did, and each review found another spelling). It is **closed**: every construct that can
**bind or rebind a name** in a module or class namespace, or **change an attribute or member** of a measured module or class, has to be one of a finite, enumerated set of recognised
forms whose effect the index records, and **anything else is refused (`SRC-FORM-UNRECOGNISED`)**, in whichever structural position it appears: statements, expressions inside function
headers and annotations, defaults, decorators, class bodies, comprehensions, loop targets, `global` and `nonlocal` redirection, imports, walrus expressions, and attribute or subscript
stores on imported modules or classes. This is part of version 1's enforcement and not a scope change: the recognised set is exactly the supported rows below, and a new form gets in
only by a contract amendment, never by the tool's default. The enforcement is structural, one dispatcher over each kind of site, in which a kind with no entry is a refusal:

| Dispatcher | What it recognises | An unrecognised kind is |
|---|---|---|
| The walker's table of syntax forms (`FORMS` in `tools/gen2_source_index.py`) | Every syntax node class that can occur in the supported subset, each with the handler that records what it does to a namespace: a binding, a store, a call, a new scope (a class, function, lambda or comprehension) or nothing. The walk is by node, so no position is skipped. The `type` statement and type parameters are not recorded. | a node class with no entry, and a name written where no statement says how |
| The binding kinds of a class body (`Contract.CLASS_FORMS`) | `def`, `class`, assignment, augmented assignment, loop and `with` target, walrus, `del`, import, and an annotation alone; each is checked by name against the hook names, the names of the class family's methods and the methods the body itself defines | any other kind of binding |
| The binding roles of every scope (`BINDING_ROLES`) | the fourteen roles the index records | a role the contract does not list |
| The store bases (`Contract.STORE_FORMS`) | a write through the method's own receiver (an instance attribute: it must not be a method of the class family), through data (a parameter, a local or module-level value, an element of a container, the result of a call that is no recognised producer), provided the attribute written is not the name of a method of a class family of more than one class (the object may be an instance of it: `SRC-ATTR-OVERRIDE`) | a write through a class, a module, a package, a function, an external object, a namespace's dictionary (`globals()`, `vars(x)`, `A.__dict__`, `sys.modules`) or the receiver's own `__dict__`, and a write through something nothing in the source says what it is |
| The call forms | class-making calls, `setattr`/`delattr`/`object.__setattr__`/`type.__setattr__`, the loader calls and the mutators of a namespace's dictionary | (none: other calls are calls) |

A name bound once, directly, to another name or attribute chain (`loader = import_module`, `me = self`) has the identity or the kind of that chain, so an alias is the thing it aliases.

## The supported subset

One table, one row per area. The refusal categories are listed in the next section; every category has a refusal fixture and every row a positive fixture, in both services (`gen2/tests/test_source_contract.py`).

| Area | Supported | Guard refuses (categories) |
|---|---|---|
| Source inventory | All tracked production Python in both services (`gen2/` except `gen2/tests/`, and `gateway/research_gateway/`), including newly staged files. A tracked file missing from the working tree is skipped, and the ledger then requires its identities to be retired. | A file that does not parse (`SRC-INV-PARSE`); two files with one module name, or a path that is not a module path (`SRC-INV-MODULE`); a production candidate that is neither tracked nor ignored, so a local check could not claim completeness (`SRC-INV-UNTRACKED`: `git add` the file; CI evaluates a clean committed tree). |
| Function identity | One named `def` or `async def` per lexical scope, including nested functions. Local helpers inside control-flow blocks are measured as lexical definitions. The same short name in different scopes is valid. Identity is `file::qualified.name`, qualified by the scopes that hold it. | Two definitions of a name in one scope, in any branches, including mutually exclusive ones and overload-style repetition (`SRC-DEF-DUPLICATE`); a defined name bound again in its scope by an assignment, import, loop or `with` target, `except ... as`, `del`, walrus, or a `global`/`nonlocal` write (`SRC-DEF-REBOUND`). No positional `#2` identity is issued. |
| Class and method declarations | Unconditional `class` statements directly in a module, class or function body; methods declared directly in their class body; nested and local classes keep their lexical scope. | A class declared inside a compound statement (`SRC-CLASS-CONDITIONAL`); a method declared inside a compound statement of its class, including `if True:` (`SRC-METHOD-CONDITIONAL`); a class made by a call: three-argument `type(...)`, `types.new_class` (`SRC-CLASS-DYNAMIC`); a class-body binding, by any statement, whose value names a method of the body (`SRC-METHOD-ALIAS`); a data attribute, class or instance, that overrides a method of its class family, bound by any statement (an assignment, a loop or `with` target, an import, a walrus), a dataclass field or a `__slots__` entry (`SRC-ATTR-OVERRIDE`); a `__slots__` that is not one literal of names (`SRC-FORM-UNRECOGNISED`). |
| Imports and exports | Explicit absolute and relative imports, aliases, qualified module chains and uniquely bound explicit re-exports. Local and conditional imports still count as syntax edges of the import graph but never provide an uncertain base or owner binding. One module-level literal list or tuple of strings as `__all__`, or none; `__all__` may be read by index, comparison, iteration, copy, `len`, `sorted`, `list`, `tuple`, `set` or `frozenset`. | A star import, in either service (`SRC-STAR-IMPORT`); an `__all__` that is dynamic, repeated, conditional, annotated, mutated, or passed on as a value (an alias, a call argument) (`SRC-ALL-DYNAMIC`); a name used as a base with competing or conditional bindings (`SRC-BINDING-COMPETING`); a first-party name that cannot be followed to one definition (`SRC-NAME-UNRESOLVED`). Binding order is never guessed. |
| Inheritance | A statically resolved project hierarchy with C3 order, including same-file intermediates and diamonds. `object` is known. External-only leaves (a base outside the production inventory: the standard library or a third-party package) are outside project collaboration. `object` is the implicit last base of every class, as in Python. A project base may be mixed only with `object`, `typing.Generic` and `typing.Protocol`, no external class may come before a project class in the resolution order, through any ancestor, and a subscript is erased only on the modelled typing forms. | A base that is not a name or an attribute chain (`SRC-BASE-SHAPE`); a base bound by an assignment, or naming a function or a module (`SRC-BASE-ALIAS`); a subscripted base that is not a modelled typing form (`SRC-BASE-SUBSCRIPT`); a project base mixed with any other external base, or a hierarchy in which an external class, an ancestor of one of the bases, comes before a project class (`SRC-BASE-MIXED`); an inconsistent or cyclic hierarchy, or a base defined in the other service (`SRC-BASE-HIERARCHY`); a class keyword such as `metaclass=`, or a hook that changes classes or attribute lookup, defined or bound by any form (`SRC-CLASS-HOOK`). |
| Decorators and descriptors | The finite list of resolved transformations below, each with its stated effect. Authored wrapper bodies are measured as written. | A decorator with no record (`SRC-DECORATOR-UNKNOWN`); a decorator name whose identity cannot be established because it is rebound, conditional or competing (`SRC-DECORATOR-SHADOWED`); a known decorator with an argument shape its record does not allow, such as `@dataclass(slots=True)` (`SRC-DECORATOR-ARGS`). |
| Receiver calls and attributes | Direct calls on the method's own receiver (the first parameter of a method that is not a `staticmethod`), including calls in closures that capture it. Ordinary data fields and injected callables are distinguished from declared methods, and a member that is not a method (a property, a slot, data, the `__hash__` Python sets to `None`) is never a project method: a call of it calls its value. `getattr` on data, `type(x)` and data-field initialisation are not restricted. | A method that binds its receiver's name again, in any nested scope (`SRC-RECEIVER-REBOUND`); a data write that overrides a family method (`SRC-ATTR-OVERRIDE`); reflective mutation of a class, module or method namespace: an attribute or item written, deleted or augmented on a class, a module, a package, a function or an external object (`a.A = object` through an imported module as much as `A.f = 1`), `setattr`/`delattr` on one or with a computed name, `__class__`/`__bases__`/`__dict__`/`__mro__` written, `globals()`, `vars()`, `sys.modules` or a `__dict__` written or changed (`SRC-REFLECTIVE`); a write through something nothing in the source says what it is (`SRC-FORM-UNRECOGNISED`). |
| Deliberate non-graph mechanisms | The documented exclusions stay outside the direct-call and import metrics: `super()`, indirect and injected calls, reflection on data. The one adapter-discovery loader is a separately inventoried dynamic-import site with a fixed package, filter and discovered-file inventory, and a pinned reviewed implementation (a fingerprint). | A dynamic import or code-loading call with no inventory entry (`SRC-LOADER-UNINVENTORIED`); an inventoried loader whose implementation is not the reviewed one (its fingerprint changed), or whose filter now finds files the inventory does not list (`SRC-LOADER-INVENTORY`). The inventory is a reviewed boundary, not an invented set of import edges. |

## Refusal categories

The closed list. A diagnostic's category is always one of these (`tools/gen2_source_contract.py` `CATEGORIES`; a test compares this table with the tool). A diagnostic names the file, the line, the construct and the remediation.

| Category | Row | Refused |
|---|---|---|
| `SRC-INV-PARSE` | source inventory | a production file that does not parse |
| `SRC-INV-MODULE` | source inventory | two files with one module name, or a path that is not a module path |
| `SRC-INV-UNTRACKED` | source inventory | a production candidate that is neither tracked nor ignored |
| `SRC-DEF-DUPLICATE` | function identity | two definitions of one name in one lexical scope, in any branches |
| `SRC-DEF-REBOUND` | function identity | a defined name bound again in its scope |
| `SRC-CLASS-CONDITIONAL` | class and method declarations | a class declared inside a compound statement |
| `SRC-METHOD-CONDITIONAL` | class and method declarations | a method declared inside a compound statement of its class |
| `SRC-CLASS-DYNAMIC` | class and method declarations | a class made by a call, not a class statement |
| `SRC-METHOD-ALIAS` | class and method declarations | a class-body assignment that aliases a method |
| `SRC-STAR-IMPORT` | imports and exports | a star import, in either service |
| `SRC-ALL-DYNAMIC` | imports and exports | an `__all__` that is not one module-level literal list or tuple of strings |
| `SRC-BINDING-COMPETING` | imports and exports | a name with competing or conditional bindings used where one is needed |
| `SRC-NAME-UNRESOLVED` | imports and exports | a first-party name that cannot be followed to one definition |
| `SRC-BASE-SHAPE` | inheritance | a base that is not a name or an attribute chain |
| `SRC-BASE-ALIAS` | inheritance | a base bound by an assignment, a function or a module |
| `SRC-BASE-SUBSCRIPT` | inheritance | a subscripted base that is not a modelled typing form |
| `SRC-BASE-MIXED` | inheritance | a project base mixed with an external base the contract does not model |
| `SRC-BASE-HIERARCHY` | inheritance | an inconsistent or cyclic hierarchy, or a base in the other service |
| `SRC-CLASS-HOOK` | inheritance | a class keyword (a metaclass) or a hook that changes classes or attribute lookup |
| `SRC-DECORATOR-UNKNOWN` | decorators and descriptors | a decorator with no record in the contract |
| `SRC-DECORATOR-SHADOWED` | decorators and descriptors | a decorator name whose identity cannot be established |
| `SRC-DECORATOR-ARGS` | decorators and descriptors | a known decorator with an argument shape the record does not allow |
| `SRC-RECEIVER-REBOUND` | receiver calls and attributes | a method's receiver name bound again inside the method |
| `SRC-ATTR-OVERRIDE` | receiver calls and attributes | a data write that overrides a method of the class family |
| `SRC-REFLECTIVE` | receiver calls and attributes | reflective mutation of a class, module or method namespace |
| `SRC-LOADER-UNINVENTORIED` | non-graph mechanisms | a dynamic import or code-loading call with no inventory entry |
| `SRC-LOADER-INVENTORY` | non-graph mechanisms | an inventoried loader whose implementation changed, or whose discovered files differ from the inventory |
| `SRC-FORM-UNRECOGNISED` | closure of every row | a syntax form, binding or store with no recognised effect |

Hook names refused in a class body (`SRC-CLASS-HOOK`), whether a `def` or any other binding (an assignment, a loop or `with` target, an import, a walrus) defines them: `__init_subclass__`, `__mro_entries__`, `__getattribute__`.

## Transformation records

For each transformation the contract allows, its **resolved identity** (never the spelling: the decorator name is resolved through the file's own bindings, so shadowing cannot pass), the **allowed argument shape** and the **effect relevant to these metrics**. A first-party transformation's identity change, or a new transformation, is a contract amendment, not an analyser extension.

| Identity | Applies to | Allowed argument shape | Effect on the metrics |
|---|---|---|---|
| `dataclasses.dataclass` | class | `@dataclass`, `@dataclass()` or `@dataclass(frozen=True)`; no other argument, so never `slots=True`, `eq=False`, `unsafe_hash=True` or `order=True` | returns the decorated class object; generates `__init__`, `__repr__` and `__eq__` as methods of that class unless its body defines them; sets `__hash__` by the dataclasses documentation (eq is true): to `None` unless the body defines `__hash__` for `@dataclass` and `@dataclass()`, to a generated method unless the body defines `__hash__` for `frozen=True`, which also generates `__setattr__` and `__delattr__`; each annotated field (not a `ClassVar`, `InitVar` or `KW_ONLY`) is an instance attribute the generated `__init__` writes, so a field named like a method of the class family is refused as SRC-ATTR-OVERRIDE |
| `builtins.property` | method | no argument | the name becomes a data attribute: `self.name()` calls its value, never a project method of that name |
| `builtins.staticmethod` | method | no argument | the method keeps its name and has no receiver |
| `builtins.classmethod` | method | no argument | the method keeps its name; its receiver is the class, so its calls are not instance self-calls |
| `contextlib.contextmanager` | function, method | no argument | the name stays bound to a callable that returns a context manager; the authored body is the generator and is measured as written |
| `functools.wraps` | function | exactly one positional name, no keyword | copies metadata onto the wrapper it decorates; the wrapper's body is measured as written |
| `gen2.gateway_client.client._serial` | method | one positional string literal, and optionally `within=True` or `within=False` | the method name stays bound to a callable wrapper (`run`, measured as written) that calls the decorated function; the decorated body is the method's |

## External terminals

A base that resolves outside the production inventory is an **external terminal**: its identity is recorded as the resolved dotted name (`builtins.Exception`, `typing.Protocol`, `threading.Thread`, `urllib.request.HTTPHandler`). A class whose bases are all external is a leaf outside project collaboration: it adds no project method and takes none. Two lists of identities are modelled:

| List | Identities | Meaning |
|---|---|---|
| modelled typing forms | `typing.Generic`, `typing.Protocol` | a subscript on them is erased; they add no project method |
| mixable with a project base | `builtins.object`, `typing.Generic`, `typing.Protocol` | the only external bases a project base may share a class with |

Any other external base mixed with a project base is refused (`SRC-BASE-MIXED`): its methods could precede or follow the project's in an order the analysis does not model. The same holds through ANCESTORS, not only the immediate bases: for `A(UserDict)`, a project class `B` with a method `keys`, and `C(A, B)`, the resolution order is `C, A, UserDict, ..., B`, so `self.keys()` finds `UserDict`'s name before the project's. A class whose resolution order (C3, with `object` implicit and last) places an external class other than the modelled ones before a project class is refused, because an external class's absence of the name cannot be established. An external class after every project class cannot hide a project name, and a class whose bases are all external is a leaf outside project collaboration. An unknown external behaviour never silently resolves a project method.

## Effective members

Primary documentation: the Python data model on `object.__hash__` ("A class that overrides `__eq__()` and does not define `__hash__()` will have its `__hash__()` implicitly set to `None`") and the `dataclasses` documentation ("If eq and frozen are both true, by default `@dataclass` will generate a `__hash__()` method for you. If eq is true and frozen is false, `__hash__()` will be set to `None`"; "Neither will it add or change an existing explicitly defined `__hash__()` method"; with `frozen=True` a `__setattr__` or `__delattr__` the body defines is a `TypeError`, so such a class is never built). `gen2/tests/test_source_closure.py` proves the recorded members against the interpreter, for a plain class and the three recorded dataclass forms over six bodies each, in both services.

Ownership and attribution use a class's **effective members**: what Python has built once the body has run and the recorded transformations are applied, not only the methods the body writes
(`tools/gen2_source_contract.py` `effective`). A name is attributed to the first class in the C3 order that HAS it as an effective member; a member that is not a callable `def` (a property, a
slot, data, an implicit `None`) is data, so a call of it calls its value and nothing after it in the order is reached.

| Effective member | Where it comes from | Effect |
|---|---|---|
| a `def` | the body | its role (method, `staticmethod`, `classmethod`, property) |
| any other name bound in the body | the body | data (an annotation alone binds nothing) |
| `__hash__ = None` | **implicit**: a body that defines `__eq__` and not `__hash__` (the Python data model on `__hash__`) | data: a call of `self.__hash__()` is not attributed to an ancestor's `__hash__` |
| the names a literal `__slots__` lists | the body | slots (data); a slot named like a method of the family is refused |
| `__init__`, `__repr__`, `__eq__` | a recorded `@dataclass`, unless the body defines them | generated methods |
| `__hash__` | a recorded `@dataclass` (the `dataclasses` documentation's table, for the recorded forms only): `None` when frozen is false, a generated method when `frozen=True`, in both cases unless the body defines an explicit `__hash__` | data, or a generated method |
| `__setattr__`, `__delattr__` | a recorded `@dataclass(frozen=True)` | generated methods |
| each annotated field (not `ClassVar`, `InitVar`, `KW_ONLY`) | a recorded `@dataclass`: its generated `__init__` writes it on every instance | an instance attribute; a field named like a method of the class family is refused (`SRC-ATTR-OVERRIDE`) |

## Dynamic loader inventory

The only dynamic import in production is the adapter-discovery loader. It is **inventoried, not modelled**: the metric's import graph is explicitly syntax-level, `adapters.load_all()` creates runtime dependencies the graph does not count, and turning that graph into a complete runtime graph is a separate metric amendment. A new loader site cannot pass unnoticed merely because `ast.Import` does not see it.

| Field | Value |
|---|---|
| Site | `gateway/research_gateway/adapters/__init__.py`, function `load_all` |
| Call | `importlib.import_module` |
| Discovery | `pkgutil.iter_modules` over the package's own `__path__` |
| Argument | `f'{__name__}.{info.name}'` |
| Package | `research_gateway.adapters` |
| Skip names | `base` (the module constant `_SKIP`) |
| Skip prefix | `_` |
| Filter | `info.name in _SKIP or info.name.startswith('_')` |
| Fingerprint | `d92736324e8162a92f838d37cfc5f55df496ae08374f1b1627857558522ff842` |
| Discovered files | `bea`, `bis`, `bls`, `census`, `core`, `crossref`, `datacite`, `doaj`, `doi_org`, `ecb`, `europepmc`, `fred`, `globe`, `govinfo`, `harvard_dataverse`, `huggingface`, `kaggle`, `openaire`, `openalex_snapshot`, `opencitations`, `openml`, `qdr`, `semanticscholar`, `socrata`, `unpaywall`, `wms` |

The **fingerprint** pins the reviewed implementation, not only the text the filter is written in: it is the SHA-256 of the normalised syntax (positions, comments and docstrings ignored) of the function `load_all` and of every statement of its module that is not another definition (its imports, `_SKIP`, and any rebinding of a name it reads, such as `__path__`), and any change to either is a refusal until the contract is amended, so turning a `continue` into a `pass` under the same condition is caught. The guard also recomputes the files the filter finds in the package from the tracked inventory and compares them with this list; a new, removed or renamed adapter is a refusal until this table and `LOADERS` in `tools/gen2_source_contract.py` are amended together. Loader calls refused without an entry: `importlib.import_module`, `__import__`, `importlib.reload`, `importlib.util.spec_from_file_location`, `importlib.util.module_from_spec`, `importlib.machinery.SourceFileLoader`, `runpy.run_module`, `runpy.run_path`, `exec`, `eval`, `compile`, `pkgutil.iter_modules`, `pkgutil.walk_packages`. A loader may never bind a class base or a locator owner: a base computed from a loaded module is a `SRC-BASE-SHAPE` refusal.

## Explicit non-graph exclusions

Unchanged from the metric definitions, and not claims of the contract: `super()` calls, `self.<attribute>.method()` calls, indirect and injected calls, reflection on data, and attribute reads are outside the import and direct-call metrics. The contract constrains only the parts of Python that decide identities, bindings and attribution.

## What the contract does not establish

- That the code is correct, or that a refactor that lowers a metric is an architectural improvement: a recognition change that moves a measurement is reported as a **measurement change**.
- That a locator's cited name is the right definition or that the prose around it is true (only that the name exists where it says, through facts the contract guarded).
- That an author's stated reason in the ledger is true (reviewed metadata under trust model B; Git records commitment, review establishes adequacy).
- That a call never hands out a class or a module. The recognised producers are `type(x)`, `globals()`, `locals()`, `vars(x)`, `getattr(x, ...)` on a class or namespace, and the methods of a namespace's dictionary; any other call returns a new object, which is data. A project function that returns a class, and a write through its result, is indirection, which the contract excludes with the other non-graph mechanisms.
- That an external class's absence of a name can be established: every external class other than the modelled ones is assumed able to supply any name, so none may come before a project class in the resolution order.

## Amendments to repair-2

The 2q-a-repair-2 brief let an unresolved binding be classified in the ledger and still pass, with a `classify` action and an `unresolved_base` metric. **Withdrawn (ruling 1).** The `classify` action no longer exists (an entry with it is an invalid action naming this withdrawal); `unresolved_base` is not a metric an exemption may name; a binding the contract cannot make certain is a refusal. The tests that asserted classification (`test_a_ledger_classifies_it_and_a_stale_one_fails`, `test_bases_outside_the_measured_files_are_classified_without_an_exemption`, `test_classifications_do_not_replace_missing_pair_accounting` and the unresolved-base cases of `UnresolvedBaseTest`) were replaced by refusal tests in `gen2/tests/test_source_contract.py` and `gen2/tests/test_metrics_collaboration.py`. The identity and numeric obligations of repair-2 (present, mapped or retired; admission of new budgets; both complexity scores) are unchanged.

## Amendment path

The contract changes only by an explicit amendment: the operator rules on the concrete form; `docs/gen2/SOURCE-CONTRACT.md` and `tools/gen2_source_contract.py` change together and the version number rises; a refusal test and a positive test accompany every new row. Finding another valid Python form outside the subset is a new refusal fixture, not an automatic extension of the analyser: a concrete counterexample **inside** the subset still blocks, and a form outside it must be refused.
