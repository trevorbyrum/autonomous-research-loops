"""Astra's binding-identity probes of the 2q-a-repair-4 review (F1), kept as permanent regressions (task 2q-a-repair-5, slice 1 of the F1 repair).

Each probe is a package of literal files (`{pkg}` is the package name), her exact sources from `private/evidence/astra-2q-a-repair-4/closure-probes.py` (`closure-probes.json`:
`loader-unpack`, `loader-reexport`, `unpacked-module`, `nonlocal-skips-nearest-function`), with two oracles that do not read the tool's output: a CONTROL the interpreter runs in the
fixture tree and the text Python prints for it, and the VERDICT the contract must give (a refusal at a category and a line, written by hand, or none and the measured cross-file
sites). The `Probe` record is the one of tests/source_probe_fixtures.py and the runner is `BindingTest` (tests/test_source_binding.py).

What this slice settles is BINDING IDENTITY: which class, function, module or external object a name is, through explicit imports, aliases (also tuple-unpacked), re-exports across
files and `nonlocal` writes; since task 2q-a-repair-6 also which scope a name lives in (the compiler's symbol table: the probes of `scope-probes.json` below), the compiler-invalid `nonlocal` forms, and an
alias the resolver cannot follow; since task 2q-a-repair-6b also the pairing of scopes with the compiler's tables (a generator over a generator) and Python's private-name mangling, her
2q-a-repair-6 review R6-1 and R6-2 (`pairing-probes.json`, `private-name-probes.json`). It does not settle what a call or a container hands out at run time (a function that returns a module, a module in a list, a module passed to a
parameter, a namespace dictionary's mutator): those are call-time owner effects, slice 2 of the F1 repair, and nothing here claims them. Of her 20 closure-probe cases only the four above are
binding identity; the other 16 (and her walrus, default-parameter, `getattr` and `type(*args)` loader and class cases among them) are still accepted by the source stage.
"""
from __future__ import annotations

from gen2.tests.source_probe_fixtures import BASE, CONTROL_IMPORT, RESIDUE, Probe
from gen2.tests.tool_repo_fixtures import py

RUN_LOADED = "from {pkg}.b import value; print(value.__name__)"
OBJECT_BASE = f"False\n{RESIDUE}"   # what Python prints when B's base was replaced by `object`: B has no `f`
IMPORT_LOADER = "from importlib import import_module"
A_OF_A, A_OF_C = py("class A:", "    def f(self): return 'A'"), py("class A:", "    def f(self): return 'C'")   # Astra's two classes of one name, told apart by what `f` returns
RUN_BASE = "from {pkg}.b import B; print(B().run())"
RUN_C = "from {pkg}.a import C; print(C().run())"
NO_BINDING = "SyntaxError: no binding for nonlocal 'A' found"   # what Python prints for the two invalid `nonlocal` forms below

PROBES = [
    Probe("loader-unpack", "closure-probes.json", {"a.py": "", "b.py": py(IMPORT_LOADER, "loader, = (import_module,)", 'value = loader("math")')}, RUN_LOADED, "math",
          refused=(("SRC-LOADER-UNINVENTORIED", "b.py", 3),), notes="a loader unpacked out of a tuple is the loader"),
    Probe("loader-reexport", "closure-probes.json", {"a.py": py("from importlib import import_module as load"), "b.py": py("from {pkg}.a import load", 'value = load("math")')}, RUN_LOADED, "math",
          refused=(("SRC-LOADER-UNINVENTORIED", "b.py", 2),), notes="an explicit re-export of a loader, in the import form the contract supports, is the loader"),
    Probe("unpacked-module", "closure-probes.json", {"a.py": BASE, "b.py": py("import {pkg}.a as a", "other, = (a,)", "other.A = object", "class B(a.A):", "    def run(self): return self.f()")},
          CONTROL_IMPORT, OBJECT_BASE, refused=(("SRC-REFLECTIVE", "b.py", 3),), notes="a module unpacked into another name is that module: replacing a class through it is refused"),
    Probe("nonlocal-skips-nearest-function", "closure-probes.json",
          {"a.py": BASE, "b.py": py("def factory():", "    from {pkg}.a import A", "    def middle():", "        def replace():", "            nonlocal A", "            A = object", "        replace()",
                                    "    middle()", "    class B(A):", "        def run(self): return self.f()", "    return B", "B = factory()")},
          CONTROL_IMPORT, OBJECT_BASE, refused=(("SRC-BINDING-COMPETING", "b.py", 9),), notes="the nonlocal write rebinds factory's A, two functions up: the base has two bindings and is refused"),
    # --- task 2q-a-repair-6: scope is the compiler's (`symtable`), Astra's 2q-a-repair-5 probes (private/evidence/astra-2q-a-repair-5/scope-probes.json) ---------------------------------
    Probe("global-read-owner", "scope-probes.json", {"a.py": A_OF_A, "c.py": A_OF_C, "b.py": py("from {pkg}.a import A", "def factory():", "    from {pkg}.c import A", "    def build():",
                                                                                          "        global A", "        class B(A):", "            def run(self): return self.f()", "        return B", "    return build()",
                                                                                          "B = factory()")},
          RUN_BASE, "A", sites=1, pairs=(("b.py", "a.py"),), notes="`global A` in build makes the base the MODULE's A (a.py), not the A factory imported: the cross-file pair is b.py -> a.py"),
    Probe("global-read-loader", "scope-probes.json", {"a.py": "", "b.py": py(IMPORT_LOADER + " as load", "def factory():", "    load = len", "    def run():", "        global load", '        return load("math")',
                                                                              "    return run()", "value = factory()")},
          RUN_LOADED, "math", refused=(("SRC-LOADER-UNINVENTORIED", "b.py", 6),), notes="`global load` reads the module's loader, not factory's `len`"),
    Probe("nonlocal-no-binding-no-write", "scope-probes.json", {"a.py": "", "b.py": py("def outer():", "    def inner():", "        nonlocal A", "        return A", "    return inner")},
          "from {pkg}.b import outer", NO_BINDING, refused=(("SRC-INV-PARSE", "b.py", 3),), notes="a `nonlocal` with no enclosing binding is a SyntaxError in Python, written or not"),
    Probe("nonlocal-global-barrier", "scope-probes.json",
          {"a.py": BASE, "b.py": py("def outer():", "    from {pkg}.a import A", "    def middle():", "        global A", "        def inner():", "            nonlocal A", "            A = object", "        return inner",
                                    "    return middle")}, "from {pkg}.b import outer", NO_BINDING, refused=(("SRC-INV-PARSE", "b.py", 6),),
          notes="`middle` declares A global, so the import in outer is no binder for inner's nonlocal: Python refuses the module"),
    Probe("loader-source-rebound", "scope-probes.json", {"a.py": "", "b.py": py(IMPORT_LOADER, "loader = import_module", "import_module = len", 'value = loader("math")')}, RUN_LOADED, "math",
          refused=(("SRC-BINDING-COMPETING", "b.py", 4),), notes="`loader` keeps the imported function: an alias of a name whose bindings compete is neither accepted nor guessed, the call through it is refused"),
    Probe("a local import shadows the module's name (a control: accepted)", "a control of the scope repair",
          {"a.py": A_OF_A, "c.py": A_OF_C, "b.py": py("from {pkg}.a import A", "def factory():", "    from {pkg}.c import A", "    class B(A):", "        def run(self): return self.f()", "    return B", "B = factory()")},
          RUN_BASE, "C", sites=1, pairs=(("b.py", "c.py"),), notes="no declaration: the nearest binding is factory's own import, so the base is c.py's A"),
    # --- task 2q-a-repair-6b: the pairing follows the compiler's order (R6-1) and a private name is the compiler's mangled one (R6-2), Astra's 2q-a-repair-6 probes ------------------------------
    Probe("generators over a generator rebind the base (pairing)", "pairing-probes.json",
          {"a.py": A_OF_A, "b.py": py("def factory():", "    from {pkg}.a import A", "    tuple((A := object) for q in (q for q in (1,)))", "    class B(A):", "        def run(self): return self.f()", "    return B", "B = factory()")},
          CONTROL_IMPORT, OBJECT_BASE, refused=(("SRC-BINDING-COMPETING", "b.py", 4),),
          notes="two generator tables share a type, a name, a line and the names `.0` and `q`; the compiler enters the INNER one first (the first iterable is read outside the outer generator), so the walrus is the outer's and rebinds factory's A"),
    Probe("the same generators without the rebinding (a control: accepted)", "pairing-probes.json",
          {"a.py": A_OF_A, "b.py": py("def factory():", "    from {pkg}.a import A", "    tuple(q for q in (q for q in (1,)))", "    class B(A):", "        def run(self): return self.f()", "    return B", "B = factory()")},
          RUN_BASE, "A", sites=1, pairs=(("b.py", "a.py"),), notes="no assignment: the base is the project class and the call is a cross-file site"),
    Probe("two private methods of one name", "private-name-probes.json",
          {"a.py": py("class C:", "    def __helper(self): return 1", "    def __helper(self): return 2", "    def run(self): return self.__helper()")}, RUN_C, "2",
          refused=(("SRC-DEF-DUPLICATE", "a.py", 3),), notes="the compiler holds both as `_C__helper`: the second replaces the first"),
    Probe("a private method written twice in its two spellings", "private-name-probes.json",
          {"a.py": py("class C:", "    def __helper(self): return 1", "    def _C__helper(self): return 2", "    def run(self): return self.__helper()")}, RUN_C, "2",
          refused=(("SRC-DEF-DUPLICATE", "a.py", 3),), notes="`__helper` and `_C__helper` are one name in class C"),
    Probe("a private method rebound by an assignment", "private-name-probes.json",
          {"a.py": py("class C:", "    def __helper(self): return 1", "    __helper = None", "    def run(self): return self.__helper")}, RUN_C, "None",
          refused=(("SRC-DEF-REBOUND", "a.py", 3),)),
    Probe("a private method, defined once (a control: accepted)", "private-name-probes.json",
          {"a.py": py("class C:", "    def __helper(self): return 1", "    def run(self): return self.__helper()")}, RUN_C, "1", sites=0),
    Probe("a private local import is the base of a nested class (a control: accepted)", "private-name-probes.json",
          {"a.py": A_OF_A, "b.py": py("class Factory:", "    def build(self):", "        from {pkg}.a import A as __A", "        class B(__A):", "            def run(self): return self.f()", "        return B")},
          "from {pkg}.b import Factory; print(Factory().build()().run())", "A", sites=1, pairs=(("b.py", "a.py"),),
          notes="`__A` is `_Factory__A` in build's table: the base is the project class a.py's A"),
    # --- controls, accepted or refused the same at both pins: the refusals above are not blanket ones, and a name is bound where Python binds it -------------------------
    Probe("the second name of an unpacking is the second value", "a control of the alias repair",
          {"a.py": "", "b.py": py(IMPORT_LOADER, "size, loader = (len, import_module)", 'value = loader("math")')}, RUN_LOADED, "math", refused=(("SRC-LOADER-UNINVENTORIED", "b.py", 3),),
          notes="the pairing is by position: `loader` is the loader and not the first value"),
    Probe("the first name of an unpacking is the first value (a control: accepted)", "a control of the alias repair",
          {"a.py": "", "b.py": py(IMPORT_LOADER, "size, loader = (len, import_module)", 'value = size("math")')}, "from {pkg}.b import value; print(value)", "4",
          notes="`size` is `len`, not the loader that follows it in the tuple"),
    Probe("a nonlocal write belongs to the nearest function that has the name (a control: accepted)", "a control of the nonlocal repair",
          {"a.py": BASE, "b.py": py("def factory():", "    from {pkg}.a import A", "    def middle():", "        A = 1", "        def replace():", "            nonlocal A", "            A = 2", "        replace()",
                                    "        return A", "    middle()", "    class B(A):", "        def run(self): return self.f()", "    return B", "B = factory()")},
          "from {pkg}.b import B; print(B().run())", "project", sites=1,
          notes="`middle` binds its own A, so replace's nonlocal is middle's and factory's import is untouched: the base is the project class and the call is a cross-file site"),
]
