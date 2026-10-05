"""Fixtures for the supported-source contract (docs/gen2/SOURCE-CONTRACT.md; task 2q-a-repair-3).

One REFUSAL per way a category can fire and one POSITIVE per supported form of each row of the contract's table, as literal source text (the oracle is the
text and the contract, never the tool's output). Each fixture is a package of files relative to a service's package root, written under `gen2/` for the
engine and `gateway/research_gateway/` for the gateway; `{pkg}` stands for the package name (`gen2` or `research_gateway`), so that the same fixture runs
in both services. A fixture limited to one service says so (`only`).

A refusal fixture names the category it must produce and the line it must be reported at. Several are the exact unsupported forms Gate D #4 reproduced
(`probes.py`: the duplicate-function crossover, a conditional Router method, a method alias, an explicit/star import order, a dynamic `__all__`, a replacing class
decorator) and the unused or isolated declarations, with no collaboration pair to disappear, that Astra required to be refused by form alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from gen2.tests.tool_repo_fixtures import py

BASE = py("class Base:", "    def f(self):", "        return 1")


@dataclass(frozen=True)
class Fixture:
    name: str
    files: dict[str, str]
    category: str | None = None        # the refusal category; None for a positive fixture
    where: tuple[str, int] | None = None   # (file relative to the package root, line) the diagnostic must name
    construct: str = ""                # a substring the diagnostic's construct must contain
    only: str | None = None            # "engine" or "gateway": the fixture means nothing in the other service
    expect: dict = field(default_factory=dict)   # for a positive fixture: facts the recognised view must hold (see the test)


def refuse(name: str, category: str, files: dict[str, str], where: tuple[str, int], construct: str = "", only: str | None = None) -> Fixture:
    return Fixture(name, files, category, where, construct, only)


def accept(name: str, files: dict[str, str], only: str | None = None, **expect) -> Fixture:
    return Fixture(name, files, None, None, "", only, expect)


REFUSALS = [
    # --- row 1: the source inventory -------------------------------------------------------------------------------------
    refuse("a file that does not parse", "SRC-INV-PARSE", {"a.py": "def (:\n"}, ("a.py", 1), "does not parse"),
    refuse("a module and a package of one name", "SRC-INV-MODULE", {"a.py": "x = 1\n", "a/__init__.py": "y = 2\n"}, ("a/__init__.py", 0), "both module"),
    refuse("a path that is not a module path", "SRC-INV-MODULE", {"my-file.py": "x = 1\n"}, ("my-file.py", 0), "not a module path"),
    # --- row 2: function identity ----------------------------------------------------------------------------------------
    refuse("the duplicate-function crossover Gate D #4 reproduced (R1)", "SRC-DEF-DUPLICATE",
           {"a.py": py("def f(a):", "    pass", "", "def f(a):", "    return a")}, ("a.py", 4), "f is defined more than once"),
    refuse("two functions of one name in mutually exclusive branches", "SRC-DEF-DUPLICATE",
           {"a.py": py("import sys", "", "if sys.version_info >= (3, 12):", "    def f():", "        return 1", "else:", "    def f():", "        return 2")},
           ("a.py", 7), "f is defined more than once"),
    refuse("overload-style repetition of a method", "SRC-DEF-DUPLICATE",
           {"a.py": py("class A:", "    def f(self):", "        return 1", "", "    def f(self, x):", "        return x")}, ("a.py", 5), "f is defined more than once in A"),
    refuse("a class defined twice", "SRC-DEF-DUPLICATE", {"a.py": py("class A:", "    pass", "", "class A:", "    pass")}, ("a.py", 4), "A is defined more than once"),
    refuse("a nested function defined twice", "SRC-DEF-DUPLICATE",
           {"a.py": py("def outer():", "    def inner():", "        return 1", "    def inner():", "        return 2", "    return inner")}, ("a.py", 4), "inner is defined more than once"),
    refuse("a function rebound by assignment", "SRC-DEF-REBOUND", {"a.py": py("def f():", "    return 1", "", "f = None")}, ("a.py", 4), "bound again as assign"),
    refuse("a function rebound by an import", "SRC-DEF-REBOUND", {"a.py": py("import os", "", "def os():", "    return 1")}, ("a.py", 1), "bound again as import"),
    refuse("a class rebound by a loop target", "SRC-DEF-REBOUND", {"a.py": py("class A:", "    pass", "", "for A in range(3):", "    pass")}, ("a.py", 4), "bound again as target"),
    refuse("a function deleted", "SRC-DEF-REBOUND", {"a.py": py("def f():", "    return 1", "", "del f")}, ("a.py", 4), "bound again as delete"),
    refuse("a module function rebound through `global`", "SRC-DEF-REBOUND",
           {"a.py": py("def f():", "    return 1", "", "def g():", "    global f", "    f = None")}, ("a.py", 6), "bound again as global_write"),
    refuse("a function whose name a nested definition rebinds as a parameter", "SRC-DEF-REBOUND",
           {"a.py": py("def outer(helper):", "    def helper():", "        return 1", "    return helper")}, ("a.py", 1), "bound again as param"),
    # --- row 3: class and method declarations ----------------------------------------------------------------------------
    refuse("a conditional class", "SRC-CLASS-CONDITIONAL", {"a.py": py("import sys", "", "if sys.platform == 'linux':", "    class A:", "        pass")}, ("a.py", 4), "class A"),
    refuse("a class declared in a try block", "SRC-CLASS-CONDITIONAL", {"a.py": py("try:", "    class A:", "        pass", "except Exception:", "    pass")}, ("a.py", 2), "class A"),
    refuse("a class declared in a loop in a function", "SRC-CLASS-CONDITIONAL", {"a.py": py("def f():", "    for _ in range(2):", "        class A:", "            pass")}, ("a.py", 3), "class A"),
    refuse("the real Router's method moved under `if True:` (R2)", "SRC-METHOD-CONDITIONAL",
           {"a.py": py("class A:", "    if True:", "        def _now(self):", "            return 1", "    def g(self):", "        return self._now()")}, ("a.py", 3), "method _now"),
    refuse("a method declared under try in its class", "SRC-METHOD-CONDITIONAL", {"a.py": py("class A:", "    try:", "        def f(self):", "            return 1", "    except Exception:", "        pass")},
           ("a.py", 3), "method f"),
    refuse("a class made by three-argument type", "SRC-CLASS-DYNAMIC", {"a.py": py("A = type('A', (), {})")}, ("a.py", 1), "makes a class by a call"),
    refuse("a class made by types.new_class", "SRC-CLASS-DYNAMIC", {"a.py": py("import types", "", "A = types.new_class('A')")}, ("a.py", 3), "makes a class by a call"),
    refuse("a method alias", "SRC-METHOD-ALIAS",
           {"a.py": py("class A:", "    def helper(self):", "        return 1", "    f = helper", "    def g(self):", "        return 2")}, ("a.py", 4), "aliases the method helper"),
    refuse("a method wrapped by an assignment", "SRC-METHOD-ALIAS",
           {"a.py": py("class A:", "    def getter(self):", "        return 1", "    value = property(getter)")}, ("a.py", 4), "aliases the method getter"),
    refuse("a subclass's class attribute that hides a method", "SRC-ATTR-OVERRIDE",
           {"a.py": py("class A:", "    def f(self):", "        return 1", "", "class B(A):", "    f = None")}, ("a.py", 6), "overrides a method named f"),
    refuse("an instance write that hides a method", "SRC-ATTR-OVERRIDE",
           {"a.py": py("class A:", "    def f(self):", "        return 1", "", "    def __init__(self):", "        self.f = lambda: 2")}, ("a.py", 6), "overrides a method named f"),
    refuse("a setattr with the name of a method", "SRC-ATTR-OVERRIDE",
           {"a.py": py("class A:", "    def f(self):", "        return 1", "", "    def g(self):", "        setattr(self, 'f', None)")}, ("a.py", 6), "overrides a method named f"),
    # --- row 4: imports and exports --------------------------------------------------------------------------------------
    refuse("a star import", "SRC-STAR-IMPORT", {"base.py": BASE, "a.py": py("from {pkg}.base import *")}, ("a.py", 1), "a star import"),
    refuse("an explicit import beside a competing star import (Gate D #4)", "SRC-STAR-IMPORT",
           {"a.py": py("class Base:", "    pass"), "b.py": py("class Base:", "    pass"),
            "c.py": py("from {pkg}.a import Base", "from {pkg}.b import *", "", "class C(Base):", "    pass")}, ("c.py", 2), "a star import"),
    refuse("an __all__ mutated after its literal (Gate D #4)", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = []", "__all__.append('Base')")}, ("a.py", 2), "mutates __all__"),
    refuse("an __all__ extended with +=", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['A']", "__all__ += ['B']")}, ("a.py", 2), "__all__"),
    refuse("an __all__ built from a name", "SRC-ALL-DYNAMIC", {"a.py": py("NAMES = ['A']", "__all__ = NAMES")}, ("a.py", 2), "__all__"),
    refuse("an __all__ chosen by a condition", "SRC-ALL-DYNAMIC", {"a.py": py("import sys", "", "if sys.platform == 'linux':", "    __all__ = ['A']")}, ("a.py", 4), "__all__"),
    refuse("an __all__ written twice", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['A']", "__all__ = ['B']")}, ("a.py", 2), "__all__"),
    refuse("an __all__ written inside a function", "SRC-ALL-DYNAMIC", {"a.py": py("def f():", "    global __all__", "    __all__ = ['A']")}, ("a.py", 3), "__all__"),
    refuse("competing imports of a base under try", "SRC-BINDING-COMPETING",
           {"a.py": BASE, "b.py": BASE,
            "c.py": py("try:", "    from {pkg}.a import Base", "except ImportError:", "    from {pkg}.b import Base", "", "class C(Base):", "    pass")}, ("c.py", 6), "competing or conditional"),
    refuse("a base imported conditionally", "SRC-BINDING-COMPETING",
           {"a.py": BASE, "c.py": py("import sys", "", "if sys.platform == 'linux':", "    from {pkg}.a import Base", "", "class C(Base):", "    pass")}, ("c.py", 6), "competing or conditional"),
    refuse("a base re-exported by two competing imports", "SRC-BINDING-COMPETING",
           {"a.py": BASE, "b.py": BASE, "pkg/__init__.py": py("from {pkg}.a import Base", "from {pkg}.b import Base"),
            "c.py": py("from {pkg}.pkg import Base", "", "class C(Base):", "    pass")}, ("c.py", 3), "competing or conditional"),
    refuse("a base a measured module does not define", "SRC-NAME-UNRESOLVED",
           {"a.py": "x = 1\n", "c.py": py("from {pkg}.a import Base", "", "class C(Base):", "    pass")}, ("c.py", 3), "defines no Base"),
    refuse("a first-party module outside the inventory", "SRC-NAME-UNRESOLVED",
           {"c.py": py("from {pkg}.gone import Base", "", "class C(Base):", "    pass")}, ("c.py", 3), "not in the production inventory"),
    refuse("a base that is not defined or imported", "SRC-NAME-UNRESOLVED", {"c.py": py("class C(Nowhere):", "    pass")}, ("c.py", 1), "neither defined nor imported"),
    # --- row 5: inheritance ----------------------------------------------------------------------------------------------
    refuse("a base made by a call", "SRC-BASE-SHAPE", {"c.py": py("def make():", "    return object", "", "class C(make()):", "    pass")}, ("c.py", 4), "not a name or an attribute chain"),
    refuse("a base read from a loaded module", "SRC-BASE-SHAPE", {"c.py": py("import sys", "", "class C(getattr(sys, 'Base')):", "    pass")}, ("c.py", 3), "not a name or an attribute chain"),
    refuse("a base bound by an assignment alias", "SRC-BASE-ALIAS", {"a.py": BASE, "c.py": py("from {pkg}.a import Base", "", "Alias = Base", "", "class C(Alias):", "    pass")}, ("c.py", 5), "bound by assign"),
    refuse("a base that names a function", "SRC-BASE-ALIAS", {"c.py": py("def make():", "    return object", "", "class C(make):", "    pass")}, ("c.py", 4), "names a function"),
    refuse("a base that names a module", "SRC-BASE-ALIAS", {"a.py": BASE, "c.py": py("from {pkg} import a", "", "class C(a):", "    pass")}, ("c.py", 3), "names a module"),
    refuse("a project base subscripted", "SRC-BASE-SUBSCRIPT", {"a.py": BASE, "c.py": py("from {pkg}.a import Base", "", "class C(Base[int]):", "    pass")}, ("c.py", 3), "subscripted"),
    refuse("an external base subscripted that is not a modelled typing form", "SRC-BASE-SUBSCRIPT", {"c.py": py("class C(list[int]):", "    pass")}, ("c.py", 1), "subscripted"),
    refuse("a project base mixed with Exception", "SRC-BASE-MIXED", {"a.py": BASE, "c.py": py("from {pkg}.a import Base", "", "class C(Base, Exception):", "    pass")}, ("c.py", 3), "mixes project bases"),
    refuse("a project base mixed with a standard-library base", "SRC-BASE-MIXED",
           {"a.py": BASE, "c.py": py("import threading", "from {pkg}.a import Base", "", "class C(Base, threading.Thread):", "    pass")}, ("c.py", 4), "mixes project bases"),
    refuse("an inconsistent hierarchy", "SRC-BASE-HIERARCHY",
           {"a.py": py("class A:", "    pass"), "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"),
            "x.py": py("from {pkg}.a import A", "from {pkg}.b import B", "", "class X(A, B):", "    pass")}, ("x.py", 4), "no consistent method resolution order"),
    refuse("a metaclass keyword", "SRC-CLASS-HOOK", {"c.py": py("import abc", "", "class C(metaclass=abc.ABCMeta):", "    pass")}, ("c.py", 3), "keyword metaclass"),
    refuse("a class keyword that is not a metaclass", "SRC-CLASS-HOOK", {"c.py": py("class C(dict, total=False):", "    pass")}, ("c.py", 1), "keyword total"),
    refuse("__init_subclass__", "SRC-CLASS-HOOK", {"c.py": py("class C:", "    def __init_subclass__(cls):", "        pass")}, ("c.py", 2), "__init_subclass__"),
    refuse("__getattribute__", "SRC-CLASS-HOOK", {"c.py": py("class C:", "    def __getattribute__(self, name):", "        return 1")}, ("c.py", 2), "__getattribute__"),
    refuse("__mro_entries__", "SRC-CLASS-HOOK", {"c.py": py("class C:", "    def __mro_entries__(self, bases):", "        return ()")}, ("c.py", 2), "__mro_entries__"),
    # --- row 6: decorators and descriptors -------------------------------------------------------------------------------
    refuse("a class decorator that returns another object (Gate D #4)", "SRC-DECORATOR-UNKNOWN",
           {"a.py": py("def decorate(cls):", "    return object", "", "@decorate", "class Base:", "    def f(self):", "        return 1")}, ("a.py", 4), "decorate"),
    refuse("an unknown method decorator", "SRC-DECORATOR-UNKNOWN",
           {"a.py": py("import functools", "", "class A:", "    @functools.cache", "    def f(self):", "        return 1")}, ("a.py", 4), "functools.cache"),
    refuse("a project decorator that is not recorded", "SRC-DECORATOR-UNKNOWN",
           {"a.py": py("def once(fn):", "    return fn", "", "class A:", "    @once", "    def f(self):", "        return 1")}, ("a.py", 5), "once"),
    refuse("the property name rebound before use", "SRC-DECORATOR-SHADOWED",
           {"a.py": py("property = lambda fn: fn", "", "class A:", "    @property", "    def f(self):", "        return 1")}, ("a.py", 4), "property"),
    refuse("a decorator name defined locally is the project's own function, not the builtin", "SRC-DECORATOR-UNKNOWN",
           {"a.py": py("def staticmethod(fn):", "    return fn", "", "class A:", "    @staticmethod", "    def f():", "        return 1")}, ("a.py", 5), "staticmethod"),
    refuse("a decorator name a parameter shadows", "SRC-DECORATOR-SHADOWED",
           {"a.py": py("def make(property):", "    class A:", "        @property", "        def f(self):", "            return 1", "    return A")}, ("a.py", 3), "property"),
    refuse("a decorator imported under try", "SRC-DECORATOR-SHADOWED",
           {"a.py": py("try:", "    from dataclasses import dataclass", "except ImportError:", "    dataclass = None", "", "@dataclass", "class A:", "    x: int = 0")}, ("a.py", 6), "dataclass"),
    refuse("a slotted dataclass", "SRC-DECORATOR-ARGS", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(slots=True)", "class A:", "    x: int = 0")}, ("a.py", 3), "slots=True"),
    refuse("a dataclass with a non-frozen flag", "SRC-DECORATOR-ARGS", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(order=True)", "class A:", "    x: int = 0")}, ("a.py", 3), "order=True"),
    refuse("functools.wraps without its one name", "SRC-DECORATOR-ARGS",
           {"a.py": py("import functools", "", "def deco(fn):", "    @functools.wraps()", "    def run():", "        return fn()", "    return run")}, ("a.py", 4), "functools.wraps"),
    refuse("a property with an argument", "SRC-DECORATOR-ARGS", {"a.py": py("class A:", "    @property()", "    def f(self):", "        return 1")}, ("a.py", 2), "builtins.property"),
    refuse("the engine's _serial with a computed operation", "SRC-DECORATOR-ARGS",
           {"gateway_client/client.py": py("def _serial(operation, within=False):", "    def decorate(method):", "        return method", "    return decorate", "",
                                           "NAME = 'x'", "", "class C:", "    @_serial(NAME)", "    def f(self):", "        return 1")}, ("gateway_client/client.py", 9), "_serial", "engine"),
    refuse("a _serial of another file is not the recorded _serial", "SRC-DECORATOR-UNKNOWN",
           {"other.py": py("def _serial(operation, within=False):", "    def decorate(method):", "        return method", "    return decorate", "",
                           "class C:", "    @_serial('x')", "    def f(self):", "        return 1")}, ("other.py", 7), "_serial"),
    # --- row 7: receiver calls and attributes ----------------------------------------------------------------------------
    refuse("a receiver assigned in its method", "SRC-RECEIVER-REBOUND", {"a.py": py("class A:", "    def f(self):", "        self = A()", "        return self.g()", "    def g(self):", "        return 1")},
           ("a.py", 3), "receiver self"),
    refuse("a receiver shadowed by a closure parameter", "SRC-RECEIVER-REBOUND",
           {"a.py": py("class A:", "    def f(self):", "        def inner(self):", "            return self.g()", "        return inner", "    def g(self):", "        return 1")}, ("a.py", 3), "receiver self"),
    refuse("a receiver shadowed by a lambda parameter", "SRC-RECEIVER-REBOUND", {"a.py": py("class A:", "    def f(self):", "        return lambda self: self.g()", "    def g(self):", "        return 1")}, ("a.py", 3), "receiver self"),
    refuse("a receiver used as a comprehension target", "SRC-RECEIVER-REBOUND", {"a.py": py("class A:", "    def f(self, xs):", "        return [self.g() for self in xs]", "    def g(self):", "        return 1")},
           ("a.py", 3), "receiver self"),
    refuse("a receiver bound by a with target", "SRC-RECEIVER-REBOUND", {"a.py": py("class A:", "    def f(self, cm):", "        with cm as self:", "            return self.g()", "    def g(self):", "        return 1")},
           ("a.py", 3), "receiver self"),
    refuse("a receiver bound by except", "SRC-RECEIVER-REBOUND", {"a.py": py("class A:", "    def f(self):", "        try:", "            return 1", "        except Exception as self:", "            return 2")},
           ("a.py", 5), "receiver self"),
    refuse("a receiver named by global", "SRC-RECEIVER-REBOUND", {"a.py": py("class A:", "    def f(self):", "        global self", "        return 1")}, ("a.py", 3), "receiver self"),
    refuse("a classmethod receiver rebound", "SRC-RECEIVER-REBOUND", {"a.py": py("class A:", "    @classmethod", "    def make(cls):", "        cls = object", "        return cls")}, ("a.py", 4), "receiver cls"),
    refuse("a class attribute written through the class", "SRC-REFLECTIVE", {"a.py": py("class A:", "    pass", "", "A.f = 1")}, ("a.py", 4), "writes the attribute f of a class"),
    refuse("a class attribute written through type(self)", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self):", "        type(self).counter = 1")}, ("a.py", 3), "writes the attribute counter"),
    refuse("a class attribute written through cls", "SRC-REFLECTIVE", {"a.py": py("class A:", "    @classmethod", "    def make(cls):", "        cls.registry = {}")}, ("a.py", 4), "writes the attribute registry"),
    refuse("a class attribute written through self.__class__", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self):", "        self.__class__.counter = 1")}, ("a.py", 3), "writes the attribute counter"),
    refuse("__class__ assigned", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self, other):", "        self.__class__ = other")}, ("a.py", 3), "writes __class__"),
    refuse("__bases__ assigned", "SRC-REFLECTIVE", {"a.py": py("class A:", "    pass", "", "class B:", "    pass", "", "B.__bases__ = (A,)")}, ("a.py", 7), "writes __bases__"),
    refuse("a class namespace written through __dict__", "SRC-REFLECTIVE", {"a.py": py("class A:", "    pass", "", "A.__dict__['f'] = 1")}, ("a.py", 4), "namespace of a class"),
    refuse("setattr on a class (the shape of _no_reading)", "SRC-REFLECTIVE",
           {"a.py": py("def decorate(cls):", "    for name in ('__len__',):", "        setattr(cls, name, None)", "    return cls")}, ("a.py", 3), "computed name"),
    refuse("setattr with a computed name", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self, name):", "        setattr(self, name, 1)")}, ("a.py", 3), "computed name"),
    refuse("setattr on a class by its name", "SRC-REFLECTIVE", {"a.py": py("class A:", "    pass", "", "setattr(A, 'x', 1)")}, ("a.py", 4), "writes an attribute of a class"),
    refuse("a module namespace written through globals()", "SRC-REFLECTIVE", {"a.py": py("globals()['x'] = 1")}, ("a.py", 1), "globals()"),
    refuse("a module namespace changed by globals().update", "SRC-REFLECTIVE", {"a.py": py("globals().update({'x': 1})")}, ("a.py", 1), "globals()"),
    refuse("sys.modules written", "SRC-REFLECTIVE", {"a.py": py("import sys", "", "sys.modules['x'] = sys")}, ("a.py", 3), "sys.modules"),
    # --- row 8: non-graph mechanisms -------------------------------------------------------------------------------------
    refuse("importlib.import_module with no inventory entry", "SRC-LOADER-UNINVENTORIED", {"a.py": py("import importlib", "", "def load(name):", "    return importlib.import_module(name)")},
           ("a.py", 4), "importlib.import_module"),
    refuse("a loader imported under another name", "SRC-LOADER-UNINVENTORIED", {"a.py": py("from importlib import import_module as fetch", "", "def load(name):", "    return fetch(name)")},
           ("a.py", 4), "importlib.import_module"),
    refuse("__import__", "SRC-LOADER-UNINVENTORIED", {"a.py": py("def load(name):", "    return __import__(name)")}, ("a.py", 2), "builtins.__import__"),
    refuse("exec", "SRC-LOADER-UNINVENTORIED", {"a.py": py("def run(text):", "    exec(text)")}, ("a.py", 2), "builtins.exec"),
    refuse("eval", "SRC-LOADER-UNINVENTORIED", {"a.py": py("def run(text):", "    return eval(text)")}, ("a.py", 2), "builtins.eval"),
    refuse("compile", "SRC-LOADER-UNINVENTORIED", {"a.py": py("def run(text):", "    return compile(text, 'x', 'exec')")}, ("a.py", 2), "builtins.compile"),
    refuse("runpy.run_path", "SRC-LOADER-UNINVENTORIED", {"a.py": py("import runpy", "", "def run(path):", "    return runpy.run_path(path)")}, ("a.py", 4), "runpy.run_path"),
    refuse("pkgutil discovery outside the inventory", "SRC-LOADER-UNINVENTORIED", {"a.py": py("import pkgutil", "", "def names(path):", "    return list(pkgutil.iter_modules(path))")},
           ("a.py", 4), "pkgutil.iter_modules"),
    refuse("the inventoried loader's code in the engine", "SRC-LOADER-UNINVENTORIED",
           {"adapters/__init__.py": py("import importlib", "import pkgutil", "", "_SKIP = {'base'}", "", "def load_all():", "    out = {}",
                                       "    for info in pkgutil.iter_modules(__path__):", "        out[info.name] = importlib.import_module(f'{__name__}.{info.name}')", "    return out")},
           ("adapters/__init__.py", 8), "pkgutil.iter_modules", "engine"),
]

# the loader inventory's own refusals are built from the real file (a copy that passes, then one edit), so they live in the test module

POSITIVES = [
    # --- row 1 ---------------------------------------------------------------------------------------------------------
    accept("one function in a module", {"a.py": py("def f():", "    return 1")}, functions=["a.py::f"]),
    # --- row 2: function identity --------------------------------------------------------------------------------------
    accept("one short name in different scopes is valid", {"a.py": py("def f():", "    def g():", "        return 1", "    return g", "", "def g():", "    return 2", "",
                                                                      "class A:", "    def f(self):", "        return 3", "", "class B:", "    def f(self):", "        return 4")},
           functions=["a.py::f", "a.py::f.g", "a.py::g", "a.py::A.f", "a.py::B.f"]),
    accept("a unique local helper inside control flow is a lexical definition", {"a.py": py("def run(items):", "    for item in items:", "        if item:", "            def build(x):", "                return x",
                                                                                               "            return build(item)", "    return None")},
           functions=["a.py::run", "a.py::run.build"]),
    accept("async definitions are definitions", {"a.py": py("async def f():", "    return 1", "", "class A:", "    async def g(self):", "        return 2")}, functions=["a.py::f", "a.py::A.g"]),
    accept("a name defined once and read elsewhere", {"a.py": py("def f():", "    return 1", "", "x = f()", "y = f")}, functions=["a.py::f"]),
    accept("an annotation alone is not a rebinding", {"a.py": py("def f():", "    return 1", "", "f: int")}, functions=["a.py::f"]),
    accept("a lambda's own bindings are not the enclosing scope's", {"a.py": py("def f():", "    return 1", "", "g = lambda: (f := 2)")}, functions=["a.py::f"]),
    # --- row 3: class and method declarations -------------------------------------------------------------------------
    accept("nested and local classes keep their lexical scope", {"a.py": py("class Outer:", "    class Inner:", "        def f(self):", "            return 1", "", "def make():", "    class Local:",
                                                                           "        def g(self):", "            return 2", "    return Local")},
           classes=["a.py::Outer", "a.py::Outer.Inner", "a.py::make.Local"], functions=["a.py::Outer.Inner.f", "a.py::make", "a.py::make.Local.g"]),
    accept("methods are declared directly in their class", {"a.py": py("class A:", "    def f(self):", "        return 1", "    def g(self):", "        return self.f()")}, methods={"a.py::A": {"f": "method", "g": "method"}}),
    accept("data fields and injected callables are not methods", {"a.py": py("class A:", "    def _now(self):", "        return self._clock()", "", "    def __init__(self, clock):",
                                                                              "        self._clock = clock", "        self.name = 'x'")}, methods={"a.py::A": {"_now": "method", "__init__": "method"}}),
    # --- row 4: imports and exports -----------------------------------------------------------------------------------
    accept("explicit absolute, relative, aliased and qualified imports and a unique re-export",
           {"base.py": BASE, "pkg/__init__.py": py("from {pkg}.base import Base"), "a.py": py("from {pkg}.pkg import Base as B", "", "class A(B):", "    def g(self):", "        return self.f()"),
            "b.py": py("import {pkg}.base", "", "class B({pkg}.base.Base):", "    pass"), "c.py": py("from . import base", "", "class C(base.Base):", "    pass"),
            "d.py": py("from .base import Base", "", "class D(Base):", "    pass")},
           bases={"a.py::A": "base.py::Base", "b.py::B": "base.py::Base", "c.py::C": "base.py::Base", "d.py::D": "base.py::Base"}),
    accept("one literal __all__ is allowed", {"a.py": py("__all__ = ['f', 'g']", "", "def f():", "    return 1", "", "def g():", "    return 2")}, functions=["a.py::f", "a.py::g"]),
    accept("an __all__ as a tuple, and none at all", {"a.py": py("__all__ = ('f',)", "", "def f():", "    return 1"), "b.py": py("def g():", "    return 2")}, functions=["a.py::f", "b.py::g"]),
    accept("an __all__ that is only read is not a mutation", {"a.py": py("__all__ = ['f']", "", "def f():", "    return 1", "", "NAMES = sorted(__all__)", "COUNT = len(__all__)", "FIRST = __all__[0]")}, functions=["a.py::f"]),
    accept("local and conditional imports are not an uncertain base", {"a.py": BASE, "b.py": py("import sys", "", "if sys.platform == 'linux':", "    import os", "", "def f():", "    from {pkg}.a import Base",
                                                                                                "    return Base")}, functions=["a.py::Base.f", "b.py::f"]),
    # --- row 5: inheritance --------------------------------------------------------------------------------------------
    accept("C3 over a diamond with a same-file intermediate", {"a.py": py("class A:", "    def f(self):", "        return 'A'"), "b.py": py("from {pkg}.a import A", "", "class B(A):", "    def run(self):", "        return self.f()"),
                                                              "c.py": py("from {pkg}.a import A", "", "class C(A):", "    def f(self):", "        return 'C'"),
                                                              "d.py": py("from {pkg}.b import B", "from {pkg}.c import C", "", "class Mid(B, C):", "    pass", "", "class D(Mid):", "    pass")},
           family={"d.py::D": ["d.py::D", "d.py::Mid", "b.py::B", "c.py::C", "a.py::A"]}),
    accept("external-only leaves are outside project collaboration", {"a.py": py("import threading", "from typing import NamedTuple, Protocol", "", "class E(Exception):", "    pass", "", "class P(Protocol):",
                                                                               "    def f(self) -> int: ...", "", "class N(NamedTuple):", "    x: int", "", "class T(threading.Thread):", "    pass", "", "class O(object):", "    pass")},
           classes=["a.py::E", "a.py::P", "a.py::N", "a.py::T", "a.py::O"]),
    accept("a project base mixed with object, Generic or Protocol, subscripted only on them", {"a.py": BASE, "b.py": py("from typing import Generic, Protocol, TypeVar", "from {pkg}.a import Base", "", "T = TypeVar('T')", "",
                                                                                                                           "class G(Base, Generic[T]):", "    pass", "", "class P(Base, Protocol[T]):", "    pass", "", "class O(Base, object):", "    pass")},
           family={"b.py::G": ["b.py::G", "a.py::Base"]}),
    # --- row 6: decorators and descriptors -----------------------------------------------------------------------------
    accept("dataclass in its bare, called and frozen forms generates the methods the record names",
           {"a.py": py("from dataclasses import dataclass", "import dataclasses", "", "@dataclass", "class A:", "    x: int = 0", "", "@dataclass()", "class B:", "    x: int = 0", "",
                       "@dataclasses.dataclass(frozen=True)", "class C:", "    x: int = 0", "", "@dataclass", "class D:", "    x: int = 0", "", "    def __repr__(self):", "        return 'D'")},
           generated={"a.py::A": ["__eq__", "__init__", "__repr__"], "a.py::C": ["__delattr__", "__eq__", "__hash__", "__init__", "__repr__", "__setattr__"], "a.py::D": ["__eq__", "__init__"]}),
    accept("property, staticmethod and classmethod give their roles", {"a.py": py("class A:", "    @property", "    def p(self):", "        return 1", "", "    @staticmethod", "    def s():", "        return 2", "",
                                                                                   "    @classmethod", "    def c(cls):", "        return 3", "", "    def m(self):", "        return 4")},
           methods={"a.py::A": {"p": "property", "s": "static", "c": "class", "m": "method"}}),
    accept("contextmanager in both spellings, and wraps", {"a.py": py("import contextlib", "import functools", "from contextlib import contextmanager", "", "@contextlib.contextmanager", "def one():", "    yield 1", "",
                                                                      "@contextmanager", "def two():", "    yield 2", "", "def deco(fn):", "    @functools.wraps(fn)", "    def run(*a):", "        return fn(*a)", "    return run")},
           transforms={"a.py::one": ["contextlib.contextmanager"], "a.py::two": ["contextlib.contextmanager"], "a.py::deco.run": ["functools.wraps"]}),
    accept("the engine's _serial wrapper leaves the method a method", {"gateway_client/client.py": py("import functools", "", "def _serial(operation, within=False):", "    def decorate(method):", "        @functools.wraps(method)",
                                                                                                        "        def run(self, *args, **kwargs):", "            return method(self, *args, **kwargs)", "        return run", "    return decorate", "",
                                                                                                        "class C:", "    @_serial('resolve')", "    def a(self):", "        return 1", "", "    @_serial('exchange', within=True)",
                                                                                                        "    def b(self):", "        return 2")},
           only="engine", methods={"gateway_client/client.py::C": {"a": "method", "b": "method"}}, transforms={"gateway_client/client.py::C.a": ["gen2.gateway_client.client._serial"]}),
    # --- row 7: receiver calls and attributes -------------------------------------------------------------------------
    accept("direct calls on the receiver, closures that capture it, and data that is not a method", {"a.py": py("class A:", "    def f(self):", "        return 1", "", "    def g(self):", "        def inner():", "            return self.f()",
                                                                                                                 "        return inner() + (lambda: self.f())()", "", "    def h(self, obj):", "        return getattr(obj, 'x', None), type(obj)")},
           methods={"a.py::A": {"f": "method", "g": "method", "h": "method"}}),
    accept("a staticmethod's first parameter is an ordinary name it may rebind", {"a.py": py("class A:", "    @staticmethod", "    def s(x):", "        x = x + 1", "        return x")},
           methods={"a.py::A": {"s": "static"}}),
    accept("instance-data initialisation through object.__setattr__ and a literal setattr", {"a.py": py("class A:", "    __slots__ = ('_value', 'other')", "", "    def __init__(self, value):", "        object.__setattr__(self, '_value', value)",
                                                                                                       "        setattr(self, 'other', 1)")}, classes=["a.py::A"]),
    accept("a data object's __dict__ is data, not a class namespace", {"a.py": py("import threading", "", "_HELD = threading.local()", "", "def keys():", "    return _HELD.__dict__.setdefault('keys', set())")}, functions=["a.py::keys"]),
    # --- row 8: non-graph mechanisms ----------------------------------------------------------------------------------
    accept("super(), indirect calls and attribute-method calls stay outside the metrics", {"a.py": BASE, "b.py": py("from {pkg}.a import Base", "", "class C(Base):", "    def f(self):", "        return super().f()", "",
                                                                                                                  "    def g(self, handler):", "        return handler(), self.handler.run(), getattr(self, 'f')()")},
           family={"b.py::C": ["b.py::C", "a.py::Base"]}),
]


# which row of the contract's table each positive fixture shows (the tests run one per row, so a mutant of one guard runs a few fixtures, not all)
ROW_OF = {
    "one function in a module": "source inventory",
    "one short name in different scopes is valid": "function identity",
    "a unique local helper inside control flow is a lexical definition": "function identity",
    "async definitions are definitions": "function identity",
    "a name defined once and read elsewhere": "function identity",
    "an annotation alone is not a rebinding": "function identity",
    "a lambda's own bindings are not the enclosing scope's": "function identity",
    "nested and local classes keep their lexical scope": "class and method declarations",
    "methods are declared directly in their class": "class and method declarations",
    "data fields and injected callables are not methods": "class and method declarations",
    "explicit absolute, relative, aliased and qualified imports and a unique re-export": "imports and exports",
    "one literal __all__ is allowed": "imports and exports",
    "an __all__ as a tuple, and none at all": "imports and exports",
    "an __all__ that is only read is not a mutation": "imports and exports",
    "local and conditional imports are not an uncertain base": "imports and exports",
    "C3 over a diamond with a same-file intermediate": "inheritance",
    "external-only leaves are outside project collaboration": "inheritance",
    "a project base mixed with object, Generic or Protocol, subscripted only on them": "inheritance",
    "dataclass in its bare, called and frozen forms generates the methods the record names": "decorators and descriptors",
    "property, staticmethod and classmethod give their roles": "decorators and descriptors",
    "contextmanager in both spellings, and wraps": "decorators and descriptors",
    "the engine's _serial wrapper leaves the method a method": "decorators and descriptors",
    "direct calls on the receiver, closures that capture it, and data that is not a method": "receiver calls and attributes",
    "a staticmethod's first parameter is an ordinary name it may rebind": "receiver calls and attributes",
    "instance-data initialisation through object.__setattr__ and a literal setattr": "receiver calls and attributes",
    "a data object's __dict__ is data, not a class namespace": "receiver calls and attributes",
    "super(), indirect calls and attribute-method calls stay outside the metrics": "non-graph mechanisms",
}
ROWS = sorted(set(ROW_OF.values()))
