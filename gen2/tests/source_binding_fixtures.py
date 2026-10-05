"""Astra's binding-identity probes of the 2q-a-repair-4 review (F1), kept as permanent regressions (task 2q-a-repair-5, slice 1 of the F1 repair).

Each probe is a package of literal files (`{pkg}` is the package name), her exact sources from `private/evidence/astra-2q-a-repair-4/closure-probes.py` (`closure-probes.json`:
`loader-unpack`, `loader-reexport`, `unpacked-module`, `nonlocal-skips-nearest-function`), with two oracles that do not read the tool's output: a CONTROL the interpreter runs in the
fixture tree and the text Python prints for it, and the VERDICT the contract must give (a refusal at a category and a line, written by hand, or none and the measured cross-file
sites). The `Probe` record is the one of tests/source_probe_fixtures.py and the runner is `BindingTest` (tests/test_source_binding.py).

What this slice settles is BINDING IDENTITY: which class, function, module or external object a name is, through explicit imports, aliases (also tuple-unpacked), re-exports across
files and `nonlocal` writes. It does not settle what a call or a container hands out at run time (a function that returns a module, a module in a list, a module passed to a
parameter, a namespace dictionary's mutator): those are call-time owner effects, slice 2 of the F1 repair, and nothing here claims them. Of her 20 closure-probe cases only the four above are
binding identity; the other 16 (and her walrus, default-parameter, `getattr` and `type(*args)` loader and class cases among them) are still accepted by the source stage.
"""
from __future__ import annotations

from gen2.tests.source_probe_fixtures import BASE, CONTROL_IMPORT, RESIDUE, Probe
from gen2.tests.tool_repo_fixtures import py

RUN_LOADED = "from {pkg}.b import value; print(value.__name__)"
OBJECT_BASE = f"False\n{RESIDUE}"   # what Python prints when B's base was replaced by `object`: B has no `f`
IMPORT_LOADER = "from importlib import import_module"

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
