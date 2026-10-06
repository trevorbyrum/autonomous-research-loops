"""Fixtures for the forms SOURCE-CONTRACT version 2 excludes (docs/gen2/SOURCE-CONTRACT.md, "Dynamic mechanisms", "Private names", "Quoted class-body annotations"; task 2q-a-repair-7).

The same shape of oracle as gen2/tests/source_contract_fixtures.py: literal source text, the category and the line the contract must report, never the tool's output; `{pkg}` is the package
name; every fixture runs in both services. They are organised by MECHANISM, because the contract is: a banned name is refused wherever it is referenced (called, aliased, passed, stored,
imported, reached as an attribute), and the families below are those spellings. One test per family, so that a mutant of the guard that reads one spelling runs that family's fixtures.

  * `BAN`: every spelling of every banned mechanism, refused (`SRC-DYNAMIC-MECHANISM`, and `SRC-CLASS-DYNAMIC` for a class made by `type`);
  * `PRIVATE`: a private (name-mangled) identifier in every position it can be written, refused (`SRC-PRIVATE-NAME`), and the names that are not private, accepted;
  * `QUOTED`: a quoted class-body annotation, refused (`SRC-QUOTED-ANNOTATION`), and the quoted annotations that are no dataclass field markers, accepted;
  * `ACCEPTED`: what the ban must leave alone (plain data processing; a definition of a banned name is no reference).
"""
from __future__ import annotations

from gen2.tests.source_contract_fixtures import Fixture, accept, refuse
from gen2.tests.source_probe_fixtures import Probe
from gen2.tests.tool_repo_fixtures import py

A = py("class A:", "    def f(self):", "        return 'project'")   # lines 1-3
MECH, DYNAMIC, PRIVATE_NAME, QUOTED_ANNOTATION = "SRC-DYNAMIC-MECHANISM", "SRC-CLASS-DYNAMIC", "SRC-PRIVATE-NAME", "SRC-QUOTED-ANNOTATION"


def ban(name: str, lines: tuple[str, ...], line: int, token: str, *, category: str = MECH, files: dict[str, str] | None = None, file: str = "a.py") -> Fixture:
    """A fixture one file (`a.py`, or `files`) of which the contract must refuse at `line` of `file`, the construct naming `token`."""
    return refuse(name, category, files if files is not None else {"a.py": py(*lines)}, (file, line), token)


BAN: dict[str, list[Fixture]] = {
    "setattr_and_delattr": [
        ban("setattr on a class by its name", ("class A:", "    pass", "", "setattr(A, 'x', 1)"), 4, "`setattr`"),
        ban("setattr on an imported module", ("import os", "setattr(os, 'sep', '|')"), 2, "`setattr`"),
        ban("setattr with a computed name", ("def put(obj, name):", "    setattr(obj, name, 1)"), 2, "`setattr`"),
        ban("setattr through a parameter with a literal name", ("def put(obj):", "    setattr(obj, 'value', 1)"), 2, "`setattr`"),
        ban("setattr through a name nothing binds", ("def put():", "    setattr(nowhere, 'x', 1)"), 2, "`setattr`"),
        ban("delattr on an imported module", ("import os", "delattr(os, 'sep')"), 2, "`delattr`"),
        ban("delattr through a parameter", ("def drop(obj):", "    delattr(obj, 'value')"), 2, "`delattr`"),
        ban("builtins.setattr through an imported builtins", ("import builtins", "", "def put(obj):", "    builtins.setattr(obj, 'x', 1)"), 4, "`builtins`"),
        ban("builtins.delattr through an alias of the builtins module", ("import builtins as b", "", "def drop(obj):", "    b.delattr(obj, 'x')"), 1, "`builtins`"),
        ban("setattr imported from builtins", ("from builtins import setattr as put",), 1, "`setattr`"),
    ],
    "vars_globals_locals": [
        ban("vars of a module written", ("import os", "vars(os)['sep'] = '|'"), 2, "`vars`"),
        ban("vars of a class updated", ("class A:", "    pass", "", "vars(A).update({'f': 1})"), 4, "`vars`"),
        ban("vars of the receiver written", ("class A:", "    def f(self):", "        vars(self)['g'] = 1"), 3, "`vars`"),
        ban("vars read", ("def names(obj):", "    return sorted(vars(obj))"), 2, "`vars`"),
        ban("globals written", ("globals()['x'] = 1",), 1, "`globals`"),
        ban("globals updated", ("globals().update({'x': 1})",), 1, "`globals`"),
        ban("globals updated through a local name", ("def change():", "    g = globals()", "    g.update({'x': 1})"), 2, "`globals`"),
        ban("an attribute of an item of globals written", (*A.splitlines(), "", "globals()['A'].f = 1"), 5, "`globals`"),
        ban("locals read", ("def snapshot():", "    return dict(locals())"), 2, "`locals`"),
        ban("globals aliased", ("g = globals",), 1, "`globals`"),
        ban("vars passed as a value", ("def apply(fn, obj):", "    return fn(obj)", "", "apply(vars, 1)"), 4, "`vars`"),
        ban("vars stored in a container", ("TABLE = {'vars': vars}",), 1, "`vars`"),
    ],
    "dunder_dict": [
        ban("a module dictionary written", ("import os", "os.__dict__['sep'] = '|'"), 2, "`__dict__`"),
        ban("a module dictionary updated", ("import os", "os.__dict__.update({'sep': '|'})"), 2, "`__dict__`"),
        ban("a class dictionary written", (*A.splitlines(), "", "A.__dict__['f'] = 1"), 5, "`__dict__`"),
        ban("the receiver's own dictionary written", ("class A:", "    def f(self):", "        self.__dict__['g'] = 1"), 3, "`__dict__`"),
        ban("the receiver's own dictionary updated", ("class A:", "    def f(self):", "        self.__dict__.update({'g': 1})"), 3, "`__dict__`"),
        ban("the dictionary of the type of the receiver", ("class A:", "    def f(self):", "        type(self).__dict__.update({'g': 1})"), 3, "`__dict__`"),
        ban("a dictionary's mutator aliased (Astra's dict-method-alias)", ("import os", "edit = os.__dict__.update", "edit(sep='|')"), 2, "`__dict__`"),
        ban("a dictionary's dunder mutator (Astra's dict-dunder-mutator)", ("import os", "os.__dict__.__setitem__('sep', '|')"), 2, "`__dict__`"),
        ban("the dictionary of a local object read", ("def look(obj):", "    return obj.__dict__"), 2, "`__dict__`"),
        ban("the dictionary of a thread-local, outside the excepted statement", ("import threading", "", "_HELD = threading.local()", "", "def keys():", "    return _HELD.__dict__.setdefault('keys', set())"), 6, "`__dict__`"),
        ban("__dict__ as a bare name", ("def look(__dict__):", "    return __dict__",), 2, "`__dict__`"),
    ],
    "dynamic_import": [
        ban("import importlib", ("import importlib",), 1, "`importlib`"),
        ban("importlib.import_module called", ("import importlib", "", "def load(name):", "    return importlib.import_module(name)"), 4, "`import_module`"),
        ban("import_module imported by name", ("from importlib import import_module", "", "def load(name):", "    return import_module(name)"), 1, "`import_module`"),
        ban("import_module imported under another name", ("from importlib import import_module as fetch", "", "def load(name):", "    return fetch(name)"), 1, "`importlib`"),
        ban("a submodule of importlib", ("import importlib.util",), 1, "`importlib.util`"),
        ban("importlib imported under another name", ("import importlib as il", "", "def load(name):", "    return il.import_module(name)"), 4, "`import_module`"),
        ban("__import__ called", ("def load(name):", "    return __import__(name)"), 2, "`__import__`"),
        ban("__import__ aliased", ("fetch = __import__",), 1, "`__import__`"),
        ban("__import__ through an imported builtins", ("import builtins", "", "def load(name):", "    return builtins.__import__(name)"), 4, "`__import__`"),
        ban("a loader assigned to a name (Astra's loader alias)", ("from importlib import import_module", "loader = import_module", "value = loader('math')"), 1, "`import_module`"),
        ban("a loader passed as a default argument (Astra's loader-default)", ("from importlib import import_module", "def load(loader=import_module):", "    return loader('math')"), 2, "`import_module`"),
        ban("a loader bound by an assignment expression (Astra's loader-walrus)", ("from importlib import import_module", "(loader := import_module)('math')"), 2, "`import_module`"),
        ban("a loader reached through getattr on the module (Astra's loader-getattr)", ("import importlib", "value = getattr(importlib, 'import_module')('math')"), 2, "`importlib`"),
        ban("a loader re-exported by another module", (), 1, "`import_module`", files={"a.py": py("from importlib import import_module as load"), "b.py": py("from {pkg}.a import load", "value = load('math')")}),
        ban("a loader unpacked from a tuple", ("from importlib import import_module", "size, loader = (len, import_module)", "value = loader('math')"), 1, "`import_module`"),
        ban("importlib reached through an alias of the module", ("import importlib", "m = importlib", "value = m.import_module('math')"), 1, "`importlib`"),
        ban("importlib.reload", ("import importlib", "", "def again(module):", "    return importlib.reload(module)"), 1, "`importlib`"),
    ],
    "code_execution": [
        ban("exec", ("def run(text):", "    exec(text)"), 2, "`exec`"),
        ban("eval", ("def run(text):", "    return eval(text)"), 2, "`eval`"),
        ban("compile", ("def run(text):", "    return compile(text, 'x', 'exec')"), 2, "`compile`"),
        ban("exec aliased", ("run = exec", "run('x = 1')"), 1, "`exec`"),
        ban("eval passed as a value", ("def apply(fn, text):", "    return fn(text)", "", "apply(eval, '1')"), 4, "`eval`"),
        ban("exec through an imported builtins", ("import builtins", "", "def run(text):", "    builtins.exec(text)"), 4, "`builtins`"),
        ban("eval through an alias of the builtins module", ("import builtins as b", "", "def run(text):", "    return b.eval(text)"), 1, "`builtins`"),
        ban("exec through __builtins__", ("def run(text):", "    __builtins__.exec(text)"), 2, "`__builtins__`"),
        ban("compile imported from builtins", ("from builtins import compile",), 1, "`compile`"),
        ban("a name bound to compile by a loop target", ("for fn in (compile, len):", "    pass"), 1, "`compile`"),
    ],
    "attribute_protocol": [
        ban("object.__setattr__ outside the excepted statements", ("class A:", "    __slots__ = ('_value',)", "", "    def __init__(self, value):", "        object.__setattr__(self, '_value', value)"), 5, "`__setattr__`"),
        ban("object.__setattr__ on a module", ("import os", "object.__setattr__(os, 'sep', '|')"), 2, "`__setattr__`"),
        ban("object.__delattr__", ("import os", "object.__delattr__(os, 'sep')"), 2, "`__delattr__`"),
        ban("__setattr__ called on the receiver (Astra's dunder-setattr)", ("class A:", "    def f(self):", "        return 1", "", "class B(A):", "    def __init__(self):", "        self.__setattr__('f', lambda: 'injected')"), 7, "`__setattr__`"),
        ban("__setattr__ assigned on a class", ("class A:", "    pass", "", "A.__setattr__ = object.__setattr__"), 4, "`__setattr__`"),
        ban("type.__setattr__", ("class A:", "    pass", "", "type.__setattr__(A, 'f', 1)"), 4, "`__setattr__`"),
        ban("super().__setattr__", ("class A:", "    def __init__(self):", "        super().__setattr__('x', 1)"), 3, "`__setattr__`"),
        ban("__getattribute__ called", ("class A:", "    def f(self):", "        return object.__getattribute__(self, 'g')"), 3, "`__getattribute__`"),
        ban("__setattr__ passed as a value", ("def apply(fn, obj):", "    return fn(obj, 'x', 1)", "", "apply(object.__setattr__, 1)"), 4, "`__setattr__`"),
        ban("the getattr fallback that installs an instance override (Astra's getattr-installs-hook)",
            ("class A:", "    def f(self):", "        return 'project'", "", "class B(A):", "    def __getattr__(self, name):", "        self.__dict__.__setitem__('f', lambda: 'fallback')", "        return None"), 7, "`__dict__`"),
    ],
    "sys_modules": [
        ban("sys.modules written", ("import sys", "", "sys.modules['x'] = sys"), 3, "`modules`"),
        ban("sys.modules updated", ("import sys", "sys.modules.update({})"), 2, "`modules`"),
        ban("sys.modules popped", ("import sys", "sys.modules.pop('x', None)"), 2, "`modules`"),
        ban("an item deleted from sys.modules", ("import sys", "del sys.modules['x']"), 2, "`modules`"),
        ban("sys.modules read", ("import sys", "", "def loaded(name):", "    return name in sys.modules"), 4, "`modules`"),
        ban("sys.modules imported by name", ("from sys import modules",), 1, "`modules`"),
        ban("sys.modules through an alias of sys", ("import sys as system", "", "def drop(name):", "    system.modules.pop(name)"), 4, "`modules`"),
        ban("sys.modules through a name bound to sys", ("import sys", "s = sys", "s.modules.clear()"), 3, "`modules`"),
        ban("sys.modules through a call that returns sys", ("import sys", "", "def system():", "    return sys", "", "system().modules.clear()"), 6, "`modules`"),
    ],
    "builtins_module": [   # the module itself is the banned name (R7-1): no alias of it is followed, so every spelling of a reference to it is refused where it stands
        ban("import builtins", ("import builtins",), 1, "`builtins`"),
        ban("builtins imported under another name", ("import builtins as bi",), 1, "`builtins`"),
        ban("the module aliased by an assignment (Astra's assignment-builtins-setattr)", ("import builtins", "bi = builtins", "", "def put(obj):", "    bi.setattr(obj, 'x', 1)"), 2, "`builtins`"),
        ban("the module aliased by an assignment, which writes a namespace through vars (Astra's assignment-builtins-vars)",
            ("import builtins", "import os", "bi = builtins", "bi.vars(os)['sep'] = '|'"), 3, "`builtins`"),
        ban("a function from the module imported by name", ("from builtins import open",), 1, "`builtins`"),
        ban("the module imported by name from another module", ("from os import builtins",), 1, "`builtins`"),
        ban("the name bound to nothing", ("def run():", "    return builtins"), 2, "`builtins`"),
        ban("the module as an attribute of something else", ("import os", "", "def put(obj):", "    os.builtins.setattr(obj, 'x', 1)"), 4, "`builtins`"),
        ban("__builtins__ as an attribute", ("import os", "", "def table():", "    return os.__builtins__"), 4, "`__builtins__`"),
        ban("the module re-exported by another file (Astra's reexport-builtins-setattr)", files={"helpers.py": "import builtins as bi\n", "b.py": "from {pkg}.helpers import bi\nbi.setattr(object, 'x', 1)\n"},
            file="helpers.py", lines=(), line=1, token="`builtins`"),
        ban("the module reached through the re-exporting file (Astra's qualified-reexport-builtins-setattr)",
            files={"helpers.py": "import builtins\n", "b.py": "from {pkg} import helpers\nhelpers.builtins.setattr(object, 'x', 1)\n"}, file="b.py", lines=(), line=2, token="`builtins`"),
    ],
    "three_argument_type": [
        ban("a class made by three-argument type", ("A = type('A', (), {})",), 1, "makes a class by a call", category=DYNAMIC),
        ban("a class made by type with a starred argument (Astra's type-star)", ("value = type(*('Dynamic', (), {}))",), 1, "makes a class by a call", category=DYNAMIC),
        ban("a class made by type with a keyword", ("A = type('A', (), dict=1)",), 1, "makes a class by a call", category=DYNAMIC),
        ban("type with two arguments", ("A = type('A', ())",), 1, "makes a class by a call", category=DYNAMIC),
        ban("a class made by an aliased type", ("make = type", "A = make('A', (), {})"), 2, "makes a class by a call", category=DYNAMIC),
        ban("a class made by type imported from builtins under another name", ("from builtins import type as make", "A = make('A', (), {})"), 2, "makes a class by a call", category=DYNAMIC),
        ban("a class made by types.new_class", ("import types", "", "A = types.new_class('A')"), 3, "makes a class by a call", category=DYNAMIC),
    ],
}

# every spelling above, in a function and at module level, is refused wherever it stands; these say it is the REFERENCE that is refused, not a call of it
EVERYWHERE = [
    ("in a function default", ("def f(x=setattr):", "    pass"), 1, "`setattr`"),
    ("in a lambda", ("f = lambda o: setattr(o, 'x', 1)",), 1, "`setattr`"),
    ("in a class body", ("class A:", "    put = setattr"), 2, "`setattr`"),
    ("in a method", ("class A:", "    def f(self, o):", "        return setattr(o, 'x', 1)"), 3, "`setattr`"),
    ("in a decorator", ("@setattr", "def f():", "    pass"), 1, "`setattr`"),
    ("in a comprehension", ("rows = [setattr(r, 'x', 1) for r in []]",), 1, "`setattr`"),
    ("in a conditional expression", ("def f(c):", "    return setattr if c else len"), 2, "`setattr`"),
    ("in an f-string", ("def f(o):", "    return f'{vars(o)}'"), 2, "`vars`"),
    ("in an annotation", ("def f(x: vars):", "    pass"), 1, "`vars`"),
    ("in a nested function", ("def f():", "    def g(o):", "        return globals()", "    return g"), 3, "`globals`"),
    ("in an except clause", ("try:", "    pass", "except eval:", "    pass"), 3, "`eval`"),
    ("in an assert", ("assert exec",), 1, "`exec`"),
]


def everywhere() -> list[Fixture]:
    return [ban(f"a banned name {where}", lines, line, token) for where, lines, line, token in EVERYWHERE]


BAN["the_ban_is_on_the_reference_wherever_it_stands"] = everywhere()

# a private (name-mangled) identifier: any `__name` with no trailing `__`, in every position it can be written
PRIVATE: dict[str, list[Fixture]] = {
    "private_names_in_every_position": [
        ban("a private method", ("class A:", "    def __helper(self):", "        return 1"), 2, "`__helper` is a private", category=PRIVATE_NAME),
        ban("a private method called on the receiver", ("class A:", "    def run(self):", "        return self.__helper()"), 3, "`__helper`", category=PRIVATE_NAME),
        ban("a private attribute read", ("class A:", "    def run(self):", "        return self.__value"), 3, "`__value`", category=PRIVATE_NAME),
        ban("a private attribute written", ("class A:", "    def __init__(self):", "        self.__value = 1"), 3, "`__value`", category=PRIVATE_NAME),
        ban("a private class attribute", ("class A:", "    __count = 0"), 2, "`__count`", category=PRIVATE_NAME),
        ban("a private class", ("class __Hidden:", "    pass"), 1, "`__Hidden`", category=PRIVATE_NAME),
        ban("a private nested class", ("class A:", "    class __Inner:", "        pass"), 2, "`__Inner`", category=PRIVATE_NAME),
        ban("a private module-level name", ("__registry = {}",), 1, "`__registry`", category=PRIVATE_NAME),
        ban("a private function", ("def __helper():", "    return 1"), 1, "`__helper`", category=PRIVATE_NAME),
        ban("a private parameter", ("def f(__x):", "    return 1"), 1, "`__x`", category=PRIVATE_NAME),
        ban("a private keyword-only parameter", ("def f(*, __k=1):", "    return 1"), 1, "`__k`", category=PRIVATE_NAME),
        ban("a private lambda parameter", ("f = lambda __x: 1",), 1, "`__x`", category=PRIVATE_NAME),
        ban("a private *args name", ("def f(*__rest):", "    return 1"), 1, "`__rest`", category=PRIVATE_NAME),
        ban("a private import alias", ("def f():", "    from os import path as __p", "    return __p"), 2, "`__p`", category=PRIVATE_NAME),
        ban("a private import by name", ("from os import __file__ as x, path as y", "from os import __weird"), 2, "`__weird`", category=PRIVATE_NAME),
        ban("a private module imported as a name", ("import __hidden",), 1, "`__hidden`", category=PRIVATE_NAME),
        ban("a private module path in a from-import", ("from pkg.__secret import value",), 1, "`__secret`", category=PRIVATE_NAME),
        ban("a private name declared global", ("def f():", "    global __g", "    __g = 1"), 2, "`__g`", category=PRIVATE_NAME),
        ban("a private name declared nonlocal", ("def f():", "    __n = 0", "    def g():", "        nonlocal __n", "        __n += 1", "    return g"), 2, "`__n`", category=PRIVATE_NAME),
        ban("a private name bound by except", ("try:", "    pass", "except Exception as __e:", "    pass"), 3, "`__e`", category=PRIVATE_NAME),
        ban("a private name bound by a match capture", ("match 1:", "    case __c:", "        pass"), 2, "`__c`", category=PRIVATE_NAME),
        ban("a private name captured by a star pattern", ("match [1]:", "    case [*__rest]:", "        pass"), 2, "`__rest`", category=PRIVATE_NAME),
        ban("a private key captured by a mapping pattern", ("match {}:", "    case {**__rest}:", "        pass"), 2, "`__rest`", category=PRIVATE_NAME),
        ban("a private name as a loop target", ("for __i in range(2):", "    pass"), 1, "`__i`", category=PRIVATE_NAME),
        ban("a private name in a comprehension", ("rows = [__x for __x in range(2)]",), 1, "`__x`", category=PRIVATE_NAME),
        ban("a private name bound by an assignment expression", ("(__w := 1)",), 1, "`__w`", category=PRIVATE_NAME),
        ban("a private name only annotated", ("__a: int",), 1, "`__a`", category=PRIVATE_NAME),
        ban("a private dataclass field", ("from dataclasses import dataclass", "", "@dataclass", "class A:", "    __x: int = 0"), 5, "`__x`", category=PRIVATE_NAME),
        ban("a private keyword argument of a call", ("def f(**kw):", "    return kw", "", "f(__x=1)"), 4, "`__x`", category=PRIVATE_NAME),
        ban("a private keyword of a class", ("class A(dict, __total=False):", "    pass"), 1, "`__total`", category=PRIVATE_NAME),
        ban("a private attribute name in a class pattern", ("match 1:", "    case int(__real=1):", "        pass"), 2, "`__real`", category=PRIVATE_NAME),
        ban("a private entry of __slots__", ("class A:", "    __slots__ = ('__a',)"), 2, "`__a`", category=PRIVATE_NAME),
        ban("a private name with a trailing single underscore", ("class A:", "    __x_ = 1"), 2, "`__x_`", category=PRIVATE_NAME),
        ban("a private name with three leading underscores", ("class A:", "    ___x = 1"), 2, "`___x`", category=PRIVATE_NAME),
        ban("a private name written in a nested class's method", ("class A:", "    class B:", "        def f(self):", "            return self.__x"), 4, "`__x`", category=PRIVATE_NAME),
        ban("Astra's R6B-1: two private methods of one name in a subclass and its base", ("class A:", "    def __helper(self):", "        return 'A'", "    def run(self):", "        return self.__helper()"), 2, "`__helper`",
            category=PRIVATE_NAME, files={"a.py": py("class A:", "    def __helper(self):", "        return 'A'", "    def run(self):", "        return self.__helper()"),
                                          "b.py": py("from {pkg}.a import A", "", "class B(A):", "    def __helper(self):", "        return 'B'")}),
        ban("Astra's R6B-2: a private import and its mangled spelling assigned", ("class Factory:", "    def build(self):", "        from {pkg}.a import A as __A", "        _Factory__A = object", "        class B(__A):",
                                                                                     "            def run(self):", "                return self.f()", "        return B"), 3, "`__A`", category=PRIVATE_NAME,
            files={"a.py": A, "b.py": py("class Factory:", "    def build(self):", "        from {pkg}.a import A as __A", "        _Factory__A = object", "        class B(__A):", "            def run(self):", "                return self.f()",
                                         "        return B")}, file="b.py"),
    ],
}

PRIVATE_ACCEPTED: list[Fixture] = [
    accept("ordinary dunders, single-underscore names and double underscores that are not private are accepted",
           {"a.py": py("class A:", "    __slots__ = ('_x', 'y__z')", "", "    def __init__(self):", "        self._x = 1", "        self.y__z = 2", "", "    def __eq__(self, other):", "        return self.__class__ is other.__class__", "",
                       "    def __hash__(self):", "        return hash((self._x, self.__module__, __name__))", "", "    def _helper(self, __=None, ___=None):", "        return self.__doc__", "", "_cache = {}", "x__y = 1")},
           classes=["a.py::A"]),
    accept("a mangled-looking name that is spelled out is an ordinary name",
           {"a.py": py("class A:", "    def _A__helper(self):", "        return 'A'", "", "    def run(self):", "        return self._A__helper()")}, methods={"a.py::A": {"_A__helper": "method", "run": "method"}}),
]

# a quoted annotation of a statement in a class body (the dataclass decorator reads a string annotation by its text)
QUOTED: dict[str, list[Fixture]] = {
    "quoted_annotations_in_a_class_body": [
        ban("a quoted ClassVar in a dataclass (Astra's string-field-marker)", ("from dataclasses import dataclass", "", "@dataclass", "class B:", "    f: 'ClassVar[object]'"), 5, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted ClassVar whose name is shadowed (Astra's string-field-marker-shadow)", ("from dataclasses import dataclass", "", "ClassVar = list", "", "@dataclass", "class B:", "    f: 'ClassVar[object]'"), 7, "quoted",
            category=QUOTED_ANNOTATION),
        ban("a quoted InitVar", ("from dataclasses import dataclass", "", "@dataclass", "class B:", "    f: 'InitVar[int]'"), 5, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted annotation in a plain class", ("class B:", "    f: 'int' = 0"), 2, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted annotation without a value", ("class B:", "    f: 'int'"), 2, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted annotation under a condition in the class body", ("class B:", "    if True:", "        f: 'int' = 0"), 3, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted annotation in a nested class", ("class A:", "    class B:", "        f: 'int' = 0"), 3, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted annotation in a class made inside a function", ("def make():", "    class B:", "        f: 'int' = 0", "    return B"), 3, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted annotation in a class body under a future import", ("from __future__ import annotations", "", "class B:", "    f: 'int' = 0"), 4, "quoted", category=QUOTED_ANNOTATION),
        ban("a quoted KW_ONLY marker", ("from dataclasses import dataclass", "", "@dataclass", "class B:", "    _: 'KW_ONLY'"), 5, "quoted", category=QUOTED_ANNOTATION),
    ],
}

QUOTED_ACCEPTED: list[Fixture] = [
    accept("an unquoted marker, quoted method annotations, a local annotation and a name inside a subscript are accepted",
           {"a.py": py("from __future__ import annotations", "", "from dataclasses import dataclass", "from typing import ClassVar, Optional", "", "@dataclass", "class B:", "    seen: ClassVar[int] = 0",
                       "    f: Optional['B'] = None", "", "    def g(self, other: 'B') -> 'B':", "        local: 'int' = 1", "        return other", "", "def free() -> 'B':", "    x: 'int' = 1", "    return B()")},
           classes=["a.py::B"], fields={"a.py::B": ["f"]}),
]

# the control the interpreter runs for the quoted-annotation family: what `dataclasses` does with each spelling (printed as the sorted names of the fields)
FIELD_CONTROL = (
    "from dataclasses import dataclass, fields\nfrom typing import ClassVar, Optional\n\n"
    "@dataclass\nclass Whole:\n    kept: int = 0\n    hidden: 'ClassVar[int]' = 0\n\n"
    "@dataclass\nclass Nested:\n    kept: int = 0\n    named: Optional['ClassVar[int]'] = None\n\n"
    "print(sorted(f.name for f in fields(Whole)), sorted(f.name for f in fields(Nested)))"
)
FIELD_SAYS = "['kept'] ['kept', 'named']"


# --- Astra's 40 closure probes (private/evidence/astra-2q-a-repair-4/closure-probes.json: 20 sources, each run in both services) -----------------------------------------------
# Her exact sources, each with the interpreter's control and the verdict the contract gives now. Sixteen are refused (the mechanism is banned, the quoted marker refused, an alias the
# resolver follows refused, the compiler-invalid scope refused). FOUR are the escaped-value forms - a module or a class that reaches the write through a call, a container or a parameter - and
# SOURCE-CONTRACT version 2 declares them outside its claim ("What the contract does not claim"): they stay accepted, and the interpreter control shows what each does.
PROBE_BASE = 'class A:\n    def f(self): return "project"\n'
PROBE_CHILD = "class B(a.A):\n    def run(self): return self.f()\n"
RUN_MODULE = 'from {pkg}.b import B; print("has_f", hasattr(B, "f")); print(B().run())'
RUN_B = "from {pkg}.b import B; print(B().run())"
RUN_FIELD = 'from {pkg}.b import B; print(B(f=lambda: "injected").run())'
RUN_VALUE = "from {pkg}.b import value; print(value.__name__)"
NOT_THERE = "has_f False\nAttributeError: 'B' object has no attribute 'f'"   # what Python prints when the module's class was replaced by `object`
FIELD_B = 'from {pkg}.a import A\nfrom dataclasses import dataclass\n'


def module_probe(name: str, change: str, **kw) -> Probe:
    return Probe(name, "closure-probes.json", {"a.py": PROBE_BASE, "b.py": "import {pkg}.a as a\n" + change + PROBE_CHILD}, RUN_MODULE, NOT_THERE, **kw)


CLOSURE_PROBES = [
    # --- the sixteen refused ---------------------------------------------------------------------------------------------------------------------------------------------------
    module_probe("unpacked-module", "other, = (a,)\nother.A = object\n", refused=(("SRC-REFLECTIVE", "b.py", 3),)),
    module_probe("dict-method-alias", "edit = a.__dict__.update\nedit(A=object)\n", refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 2),)),
    module_probe("dict-dunder-mutator", 'a.__dict__.__setitem__("A", object)\n', refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 2),)),
    Probe("receiver-dict-alias", "closure-probes.json", {"a.py": PROBE_BASE, "b.py": 'from {pkg}.a import A\nclass B(A):\n    def __init__(self):\n        edit = self.__dict__.update\n'
                                                                                '        edit(f=lambda: "injected")\n    def run(self): return self.f()\n'}, RUN_B, "injected", refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 4),)),
    Probe("receiver-dict-dunder", "closure-probes.json", {"a.py": PROBE_BASE, "b.py": 'from {pkg}.a import A\nclass B(A):\n    def __init__(self):\n        self.__dict__.__setitem__("f", lambda: "injected")\n'
                                                                                 '    def run(self): return self.f()\n'}, RUN_B, "injected", refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 4),)),
    Probe("string-field-marker", "closure-probes.json", {"a.py": PROBE_BASE, "b.py": FIELD_B + '@dataclass\nclass B(A):\n    f: "ClassVar[object]"\n    def run(self): return self.f()\n'}, RUN_FIELD, "injected",
          refused=(("SRC-QUOTED-ANNOTATION", "b.py", 5),)),
    Probe("string-field-marker-shadow", "closure-probes.json", {"a.py": PROBE_BASE, "b.py": FIELD_B + 'ClassVar = list\n@dataclass\nclass B(A):\n    f: "ClassVar[object]"\n    def run(self): return self.f()\n'},
          RUN_FIELD, "injected", refused=(("SRC-QUOTED-ANNOTATION", "b.py", 6),)),
    Probe("dunder-setattr", "closure-probes.json", {"a.py": PROBE_BASE, "b.py": 'from {pkg}.a import A\nclass B(A):\n    def __init__(self): self.__setattr__("f", lambda: "injected")\n    def run(self): return self.f()\n'},
          RUN_B, "injected", refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 3),)),
    Probe("getattr-installs-hook", "closure-probes.json", {"a.py": PROBE_BASE, "b.py": 'from {pkg}.a import A\nclass B(A):\n    def __getattr__(self, name):\n        self.__dict__.__setitem__("f", lambda: "fallback")\n'
                                                                                      '        return None\n    def run(self):\n        self.missing\n        return self.f()\n'},
          RUN_B, "fallback", refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 4),)),
    Probe("nonlocal-skips-nearest-function", "closure-probes.json",
          {"a.py": PROBE_BASE, "b.py": "def factory():\n    from {pkg}.a import A\n    def middle():\n        def replace():\n            nonlocal A\n            A = object\n        replace()\n    middle()\n"
                                       "    class B(A):\n        def run(self): return self.f()\n    return B\nB = factory()\n"},
          "from {pkg}.b import B; print(B.__bases__)", "(<class 'object'>,)", refused=(("SRC-BINDING-COMPETING", "b.py", 9),)),
    Probe("loader-unpack", "closure-probes.json", {"a.py": "", "b.py": 'from importlib import import_module\nloader, = (import_module,)\nvalue = loader("math")\n'}, RUN_VALUE, "math",
          refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 1), ("SRC-DYNAMIC-MECHANISM", "b.py", 2), ("SRC-LOADER-UNINVENTORIED", "b.py", 3))),
    Probe("loader-reexport", "closure-probes.json", {"a.py": "from importlib import import_module as load\n", "b.py": 'from {pkg}.a import load\nvalue=load("math")\n'}, RUN_VALUE, "math",
          refused=(("SRC-DYNAMIC-MECHANISM", "a.py", 1), ("SRC-LOADER-UNINVENTORIED", "b.py", 2))),
    Probe("loader-default", "closure-probes.json", {"a.py": "", "b.py": 'from importlib import import_module\ndef load(loader=import_module): return loader("math")\nvalue=load()\n'}, RUN_VALUE, "math",
          refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 1), ("SRC-DYNAMIC-MECHANISM", "b.py", 2)), notes="no loader call is recognised here at all: the BAN on the reference is what refuses it"),
    Probe("loader-walrus", "closure-probes.json", {"a.py": "", "b.py": 'from importlib import import_module\n(loader := import_module)("math")\nvalue=loader("math")\n'}, RUN_VALUE, "math",
          refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 1), ("SRC-DYNAMIC-MECHANISM", "b.py", 2))),
    Probe("loader-getattr", "closure-probes.json", {"a.py": "", "b.py": 'import importlib\nvalue=getattr(importlib,"import_module")("math")\n'}, RUN_VALUE, "math",
          refused=(("SRC-DYNAMIC-MECHANISM", "b.py", 1), ("SRC-DYNAMIC-MECHANISM", "b.py", 2))),
    Probe("type-star", "closure-probes.json", {"a.py": "", "b.py": 'value=type(*("Dynamic", (), {}))\n'}, RUN_VALUE, "Dynamic", refused=(("SRC-CLASS-DYNAMIC", "b.py", 1),)),
]

# --- the four escaped-value probes: declared outside the claim ---------------------------------------------------------------------------------------------------------------------
ESCAPED_PROBES = [
    module_probe("returned-module", "def namespace(): return a\nnamespace().A = object\n"),
    module_probe("subscript-module", "box = [a]\nbox[0].A = object\n"),
    module_probe("parameter-module", "def replace(ns): ns.A = object\nreplace(a)\n"),
    module_probe("returned-class-delete", "def owner(): return a.A\ndel owner().f\n"),
]

# --- Astra's R7-1 sources (2q-a-repair-7 review, private/evidence/astra-2q-a-repair-7/probes.json): the `builtins` module aliased or re-exported ------------------------------------------------
# Each is a class or a module changed at run time by an ordinary alias of the module (the interpreter says so), accepted by 2q-a-repair-7 and refused now, in both services.
R7_A = {"a.py": "class A:\n    def f(self): return 'A'\n"}
R7_B = "from {pkg}.a import A\nclass B(A):\n    def run(self): return self.f()\n"
R7_ERROR = "TypeError: 'int' object is not callable"
BUILTINS_PROBES = [
    Probe("assignment-builtins-setattr", "probes.json", R7_A | {"b.py": R7_B + "import builtins\nbi = builtins\nbi.setattr(A, 'f', 7)\n"}, RUN_B, R7_ERROR,
          refused=((MECH, "b.py", 4), (MECH, "b.py", 5))),
    Probe("assignment-builtins-delattr", "probes.json", R7_A | {"b.py": R7_B + "import builtins\nbi = builtins\nbi.delattr(A, 'f')\n"}, RUN_B, "AttributeError: 'B' object has no attribute 'f'",
          refused=((MECH, "b.py", 4), (MECH, "b.py", 5))),
    Probe("reexport-builtins-setattr", "probes.json", R7_A | {"helpers.py": "import builtins as bi\n", "b.py": R7_B + "from {pkg}.helpers import bi\nbi.setattr(A, 'f', 7)\n"}, RUN_B, R7_ERROR,
          refused=((MECH, "helpers.py", 1),), notes="the file that re-exports the module is the one refused: the module is named there"),
    Probe("qualified-reexport-builtins-setattr", "probes.json", R7_A | {"helpers.py": "import builtins\n", "b.py": R7_B + "from {pkg} import helpers\nhelpers.builtins.setattr(A, 'f', 7)\n"}, RUN_B, R7_ERROR,
          refused=((MECH, "b.py", 5), (MECH, "helpers.py", 1))),
    Probe("assignment-builtins-vars", "probes.json", R7_A | {"b.py": R7_B + "import builtins\nfrom {pkg} import a\nbi = builtins\nbi.vars(a)['A'] = object\n"},
          "from {pkg}.b import B; from {pkg} import a; print(a.A is object)", "True", refused=((MECH, "b.py", 4), (MECH, "b.py", 6))),
]
# `re` is not `builtins`: an ordinary `compile` of the regular-expression module stays accepted, and so does a function that imports it where another function imports the built-ins under the same alias
REGEX = "def regex():\n    import re as b\n    return b.compile('x').pattern\n"
REGEX_CONTROL = ("from {pkg}.a import regex; print(regex())", "x")
BUILTINS_SHADOW = "def helper():\n    import builtins as b\n    return b.len([])\n\n" + REGEX   # `b` is the built-ins in `helper` and the regular-expression module in `regex`

# --- the composition of recorded transformations (2q-a-repair-4 review F2, DEBT-016 item 2): `property` over `classmethod` is a property whose getter is not callable ---------------------------------
COMPOSITION = [Probe("property-over-classmethod", "2q-a-repair-4 review, F2 (effective-member probes)",
                     R7_A | {"b.py": "from {pkg}.a import A\nclass B(A):\n    @property\n    @classmethod\n    def f(cls): return 'B'\n    def run(self): return self.f()\n"}, RUN_B,
                     "TypeError: 'classmethod' object is not callable", refused=(("SRC-DECORATOR-UNKNOWN", "b.py", 4),))]
