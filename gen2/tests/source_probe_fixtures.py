"""Astra's probes of the 2q-a-repair-3 review, kept as permanent regressions (task 2q-a-repair-4, checklist item 6).

Each probe is a package of literal files, written under `gen2/` for the engine and `gateway/research_gateway/` for the gateway (`{pkg}` is the package name), her exact sources from
`private/evidence/astra-2q-a-repair-3/independent-2_b30ra6/` (`inside-probes.json`, `new-probes.json`, `supplemental-probes.json`, `boundary-probes.json`), with two oracles that do not
read the tool's output:

  * a CONTROL: a line of Python run by the interpreter itself in a child whose only importable package is the fixture (tool_repo_fixtures.fixture_python), and the text Python is
    known to print for it. It shows what Python actually does with the source, so the verdict on the source is checked against the language, not against the tool's idea of it;
  * the VERDICT the contract must give: a refusal at a category and a line, or (for the sources that are inside the contract) none, and the number of cross-file self-call sites
    the metrics must measure.

Every probe fails at dbe5dd4 (2q-a-repair-3) and passes now, in both services where she ran both, apart from the controls that are accepted at both pins and are there to show that
the refusals are not blanket ones.
"""
from __future__ import annotations

from dataclasses import dataclass

from gen2.tests.tool_repo_fixtures import py

BASE = py("class A:", "    def f(self):", "        return 'project'")   # Astra's BASE, lines 1-3
RESIDUE = "(<class 'object'>,)"                                         # what Python prints for the bases of a class built over a replaced base
CONTROL_IMPORT = "from {pkg}.b import B; print(hasattr(B, 'f')); print(B.__bases__)"


@dataclass(frozen=True)
class Probe:
    name: str                                              # her probe's name
    astra: str                                             # the file of hers that holds it
    files: dict[str, str]
    control: str                                           # Python run in the fixture tree
    says: str                                              # what it prints (standard output, then the last line of standard error if it failed), exactly
    refused: tuple[tuple[str, str, int], ...] = ()         # (category, file, line) each of which the contract must report; empty: the source is inside the contract
    sites: int | None = None                               # for a source inside the contract: the cross-file self-call sites the metrics must measure
    pairs: tuple[tuple[str, str], ...] | None = None       # and the (calling file, defining file) of each: which class a base is, as the metrics attribute it
    only: str | None = None
    notes: str = ""


def hash_files(name: str, subclass: str) -> dict[str, str]:
    """Astra's F1 sources: `A.__hash__` returns 42, and `B(A)` calls `self.__hash__()`; `subclass` is B's class statement and body."""
    return {"a.py": py("class A:", "    def __hash__(self):", "        return 42"), "b.py": py("from {pkg}.a import A", *subclass.splitlines(), "    def run(self):", "        return self.__hash__()")}


RUN_HASH = "from {pkg}.b import B\ntry:\n    print('selected hash:', B.__hash__ is None, B().run())\nexcept TypeError as exc:\n    print('selected hash:', B.__hash__ is None, 'TypeError:', exc)"

PROBES = [
    # ---- inside-probes.json: F1, entirely inside the contract ----------------------------------------------------------------
    Probe("ordinary-hash-suppression, before", "inside-probes.json", hash_files("ordinary", "class B(A):"), RUN_HASH, "selected hash: False 42", sites=1),
    Probe("ordinary-hash-suppression, after", "inside-probes.json", hash_files("ordinary", "class B(A):\n    def __eq__(self, other):\n        return False"), RUN_HASH,
          "selected hash: True TypeError: 'NoneType' object is not callable", sites=0,
          notes="__eq__ without __hash__ makes B.__hash__ None: the call raises, and attributing it to a.py would be a collaboration that cannot happen"),
    Probe("dataclass-hash-suppression, before", "inside-probes.json", hash_files("dataclass", "class B(A):"), RUN_HASH, "selected hash: False 42", sites=1),
    Probe("dataclass-hash-suppression, after", "inside-probes.json", hash_files("dataclass", "from dataclasses import dataclass\n@dataclass\nclass B(A):"), RUN_HASH,
          "selected hash: True TypeError: 'NoneType' object is not callable", sites=0),
    Probe("frozen dataclass: __hash__ is generated, in the class itself", "inside-probes.json (the third approved form)",
          hash_files("frozen", "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass B(A):"),
          "from {pkg}.b import B\nprint('selected hash:', B.__hash__ is None, B.__hash__.__qualname__)", "selected hash: False B.__hash__", sites=0,
          notes="the generated method belongs to B (b.py), so the call is no cross-file call"),
    # ---- new-probes.json: F2 ----------------------------------------------------------------------------------------------
    Probe("dataclass-field", "new-probes.json", {"a.py": BASE, "b.py": py("from {pkg}.a import A", "from dataclasses import dataclass", "@dataclass", "class B(A):", "    f: object", "    def run(self):", "        return self.f()")},
          "from {pkg}.b import B; print(B(f=lambda: 'injected').run())", "injected", refused=(("SRC-ATTR-OVERRIDE", "b.py", 5),)),
    Probe("transitive-external", "new-probes.json", {"a.py": py("from collections import UserDict", "class A(UserDict): pass"), "b.py": py("class B:", "    def keys(self): return 'project'"),
                                                      "c.py": py("from {pkg}.a import A", "from {pkg}.b import B", "class C(A, B):", "    def run(self): return list(self.keys())")},
          "from {pkg}.c import C; print(C({'runtime': 1}).run()); print(C.keys.__module__, C.keys.__qualname__)", "['runtime']\ncollections.abc Mapping.keys", refused=(("SRC-BASE-MIXED", "c.py", 3),)),
    Probe("module-overwrite", "new-probes.json", {"a.py": BASE, "b.py": py("import {pkg}.a as a", "a.A = object", "class B(a.A):", "    def run(self): return self.f()")},
          CONTROL_IMPORT, f"False\n{RESIDUE}", refused=(("SRC-REFLECTIVE", "b.py", 2),)),
    Probe("annotation-rebind", "new-probes.json", {"a.py": BASE + py("def marker(x: (A := object)): pass"), "b.py": py("from {pkg}.a import A", "class B(A):", "    def run(self): return self.f()")},
          CONTROL_IMPORT, f"False\n{RESIDUE}", refused=(("SRC-DEF-REBOUND", "a.py", 4),)),
    Probe("global-import-rebind", "new-probes.json", {"a.py": BASE + py("def replace():", "    global A", "    from builtins import object as A", "replace()"),
                                                      "b.py": py("from {pkg}.a import A", "class B(A):", "    def run(self): return self.f()")},
          CONTROL_IMPORT, f"False\n{RESIDUE}", refused=(("SRC-DEF-REBOUND", "a.py", 6),)),
    Probe("loader-alias", "new-probes.json", {"a.py": py("from importlib import import_module", "loader = import_module", 'value = loader("math")')}, "from {pkg}.a import value; print(value.__name__)", "math",
          refused=(("SRC-LOADER-UNINVENTORIED", "a.py", 3),)),
    Probe("all-alias", "new-probes.json", {"a.py": BASE + py("__all__ = []", "exports = __all__", 'exports.append("A")')}, "from {pkg}.a import __all__; print(__all__)", "['A']", refused=(("SRC-ALL-DYNAMIC", "a.py", 5),)),
    Probe("class-hook-alias", "new-probes.json", {"a.py": py("def getattribute(self, name):", '    if name == "f": return lambda: "injected"', "    return object.__getattribute__(self,name)", "class A:",
                                                              "    __getattribute__ = getattribute", '    def f(self): return "project"'),
                                                  "b.py": py("from {pkg}.a import A", "class B(A):", "    def run(self): return self.f()")},
          "from {pkg}.b import B; print(B().run())", "injected", refused=(("SRC-CLASS-HOOK", "a.py", 5),)),
    Probe("class-loop-target", "new-probes.json", {"a.py": BASE, "b.py": py("from {pkg}.a import A", "class B(A):", "    for f in [lambda: 'injected']:", "        pass", "    def run(self): return self.f()")},
          "from {pkg}.b import B; print(B.f())", "injected", refused=(("SRC-ATTR-OVERRIDE", "b.py", 3),)),
    Probe("builtin-object-order", "new-probes.json", {"a.py": BASE, "b.py": py("from {pkg}.a import A", "class B(object, A): pass")},
          "try:\n    from {pkg}.b import B\nexcept TypeError as exc:\n    print('TypeError:', str(exc).replace(chr(10), ' '))", "TypeError: Cannot create a consistent method resolution order (MRO) for bases object, A",
          refused=(("SRC-BASE-HIERARCHY", "b.py", 2),), notes="Python cannot even import it: the order the index computed was consistent only because it left `object` out"),
    Probe("captured-global-self (a control: accepted)", "new-probes.json", {"a.py": BASE, "b.py": py("from {pkg}.a import A", "class B(A):", "    def run(this):", "        def closure(): return this.f()", "        return closure()")},
          "from {pkg}.b import B; print(B().run())", "project", sites=1, notes="the refusals above are not blanket ones: a capturing closure over the receiver is inside the contract and attributed"),
]

# the locator consequence of the module overwrite (supplemental-probes.json, stale_qualified_locator): a qualified owner whose namespace has been replaced satisfies nothing
LOCATOR_FILES = PROBES[8].files   # module-overwrite
LOCATOR_DOC = "`{pkg}.a.A.f`\n"
LOCATOR_CONTROL = "import {pkg}.b; from {pkg}.a import A; print(hasattr(A, 'f'))"
LOCATOR_SAYS = "False"

# boundary-probes.json, loader: the real adapter loader with `continue` changed to `pass` under the unchanged skip condition (the stubs are inert)
LOADER_NAMES = ("bea", "bis", "bls", "census", "core", "crossref", "datacite", "doaj", "doi_org", "ecb", "europepmc", "fred", "globe", "govinfo", "harvard_dataverse", "huggingface",
                "kaggle", "openaire", "openalex_snapshot", "opencitations", "openml", "qdr", "semanticscholar", "socrata", "unpaywall", "wms")
LOADER_CONTROL = "from research_gateway.adapters import load_all; print(sorted(load_all()))"
