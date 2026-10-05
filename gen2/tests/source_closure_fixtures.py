"""Fixtures for the CLOSURE of the supported-source contract (docs/gen2/SOURCE-CONTRACT.md, "Closure"; task 2q-a-repair-4, Astra's 2q-a-repair-3 review F1 and F2).

The guard is not a list of known-bad spellings: every construct that binds a name in a module or class namespace, or changes an attribute or member of a measured module or
class, is a recognised form with a recorded effect, and anything else is refused. These fixtures are the same SHAPE of oracle as gen2/tests/source_contract_fixtures.py - literal
source text, the category and the line the contract must report, never the tool's output - but organised by the STRUCTURAL POSITION or KIND of site, because the failure they guard
against is a position (a function header, a class body, a loop target, a `global` redirect) or a kind of write (an attribute of a module, a dictionary of a namespace) that a list of
spellings did not name. Each family is one test, so that a mutant of one guard runs the fixtures of that guard and no others (tests/test_source_closure.py).

`{pkg}` is the package name (`gen2` or `research_gateway`); every fixture runs in both services. A refusal names the category and the line; a positive fixture names the effective
members the index must record, where the form is one whose effect is a member.
"""
from __future__ import annotations

from gen2.tests.source_contract_fixtures import Fixture, accept, refuse
from gen2.tests.tool_repo_fixtures import py

A = py("class A:", "    def f(self):", "        return 'project'")            # a class with one method, lines 1-3
AM = {"a.py": A}                                                                  # as a module
MODULE_A = {"a.py": py("class A:", "    def f(self):", "        return 1", "", "count = 0", "x = 1")}   # a module with a class, a counter and a value

# the same statement written in each structural position that can hold a walrus, rebinding the module's class A
WALRUS = {
    "a parameter annotation": ("def marker(x: (A := object)):", "    pass"),
    "a return annotation": ("def marker() -> (A := object):", "    pass"),
    "a default": ("def marker(x=(A := object)):", "    pass"),
    "a keyword-only default": ("def marker(*, x=(A := object)):", "    pass"),
    "a decorator": ("@(A := (lambda f: f))", "def marker():", "    pass"),
    "a class decorator": ("@(A := (lambda c: c))", "class Other:", "    pass"),
    "a class base": ("class Other((A := object)):", "    pass"),
    "a class keyword value": ("class Other(object, flag=(A := object)):", "    pass"),
    "a lambda default": ("marker = lambda x=(A := object): x",),
    "a comprehension element": ("items = [(A := object) for _ in range(2)]",),
    "a comprehension condition": ("items = [i for i in range(2) if (A := object)]",),
    "an annotated assignment's annotation": ("marker: (A := object) = 1",),
    "an annotated assignment's value": ("marker: int = (A := object)",),
    "a loop iterable": ("for _ in [(A := object)]:", "    pass"),
    "an if test": ("if (A := object):", "    pass"),
    "a while test": ("while (A := object):", "    break"),
    "a call argument": ("print((A := object))",),
    "a call keyword": ("print(sep=(A := object))",),
    "a subscript index": ("item = [1][(A := 0)]",),
    "a dictionary value": ("table = {'k': (A := object)}",),
    "a formatted string": ("text = f'{(A := object)}'",),
    "an except type": ("try:", "    pass", "except (A := ValueError):", "    pass"),
    "a raise": ("try:", "    raise (A := ValueError())", "except ValueError:", "    pass"),
    "an assert message": ("assert True, (A := 'message')",),
    "a match subject": ("match (A := 1):", "    case _:", "        pass"),
    "a plain statement": ("(A := object)",),
    "a conditional expression": ("choice = 1 if (A := object) else 2",),
    "an assert": ("assert (A := object)",),
    "a with item": ("with (A := open('x')):", "    pass"),
}


def walrus_fixtures() -> list[Fixture]:
    out = []
    for position, lines in WALRUS.items():
        where = 1 + next(i for i, line in enumerate(lines) if "A :=" in line)   # the line of the walrus, in the lines after the class's three
        out.append(refuse(f"a walrus in {position} rebinds the module's class", "SRC-DEF-REBOUND", {"a.py": A + py(*lines)}, ("a.py", 3 + where), "bound again as walrus"))
    return out


# every kind of binding statement, run from a function that declared the module's class A `global`
GLOBAL = {
    "an import": ("    import os as A",),
    "an import from": ("    from os import path as A",),
    "a definition": ("    def A():", "        pass"),
    "a class": ("    class A:", "        pass"),
    "an assignment": ("    A = 1",),
    "an augmented assignment": ("    A += 1",),
    "a loop target": ("    for A in range(2):", "        pass"),
    "a with target": ("    with open('x') as A:", "        pass"),
    "an except target": ("    try:", "        pass", "    except Exception as A:", "        pass"),
    "a walrus": ("    (A := 1)",),
    "a walrus in a comprehension": ("    [(A := i) for i in range(2)]",),
    "a deletion": ("    del A",),
    "a match capture": ("    match 1:", "        case A:", "            pass"),
}


GLOBAL_LINE = {"an except target": 9, "a match capture": 8}   # the line of the binding in the function: the statement's own, which is not the first line of the block for these two


def global_fixtures() -> list[Fixture]:
    out = []
    for kind, lines in GLOBAL.items():
        out.append(refuse(f"a global redirect of {kind} rebinds the module's class", "SRC-DEF-REBOUND",
                          {"a.py": A + py("", "def replace():", "    global A", *lines)}, ("a.py", GLOBAL_LINE.get(kind, 7)), "bound again as global_write"))
    return out


CLOSURE_REFUSALS: dict[str, list[Fixture]] = {
    "walrus_in_every_header_and_expression_position": walrus_fixtures(),
    "global_redirect_of_every_kind_of_binding": global_fixtures(),
    "nonlocal_and_global_inside_closures": [
        refuse("a closure's global import rebinds the module's class", "SRC-DEF-REBOUND",
               {"a.py": A + py("", "def outer():", "    def inner():", "        global A", "        import os as A", "    return inner")}, ("a.py", 8), "bound again as global_write"),
        # a `nonlocal` write belongs to the nearest enclosing function that binds the name, not to the nearest function: `middle` binds nothing, so `outer`'s definition is rebound
        refuse("a nonlocal assignment through a function that does not bind the name rebinds the outer function's definition", "SRC-DEF-REBOUND",
               {"a.py": py("def outer():", "    def helper():", "        return 1", "    def middle():", "        def replace():", "            nonlocal helper", "            helper = None", "        replace()",
                           "    middle()")}, ("a.py", 7), "bound again as nonlocal_write"),
        refuse("a nonlocal import through two functions that do not bind the name rebinds the outer function's class", "SRC-DEF-REBOUND",
               {"a.py": py("def outer():", "    class Helper:", "        pass", "    def middle():", "        def inner():", "            def replace():", "                nonlocal Helper", "                import os as Helper",
                           "            replace()", "        inner()", "    middle()")}, ("a.py", 8), "bound again as nonlocal_write"),
        refuse("a nonlocal deletion rebinds the outer function's definition", "SRC-DEF-REBOUND",
               {"a.py": py("def outer():", "    def helper():", "        return 1", "    def replace():", "        nonlocal helper", "        del helper", "    replace()")}, ("a.py", 6), "bound again as nonlocal_write"),
        # the compiler refuses each of these (symtable raises), so the source stage refuses the file with the compiler's message and its line (task 2q-a-repair-6; Astra's 2q-a-repair-5 review)
        refuse("a nonlocal name that no enclosing function binds", "SRC-INV-PARSE",
               {"a.py": py("def outer():", "    def inner():", "        nonlocal missing", "        missing = 1", "    inner()")}, ("a.py", 3), "no binding for nonlocal 'missing' found"),
        refuse("a nonlocal declaration with no enclosing binding and no write", "SRC-INV-PARSE",
               {"a.py": py("def outer():", "    def inner():", "        nonlocal A", "        return A", "    return inner")}, ("a.py", 3), "no binding for nonlocal 'A' found"),
        refuse("a nonlocal write whose apparent binder lies beyond an intervening function's `global`", "SRC-INV-PARSE",
               {"a.py": py("def outer():", "    A = 1", "    def middle():", "        global A", "        def inner():", "            nonlocal A", "            A = 2", "        return inner", "    return middle")},
               ("a.py", 6), "no binding for nonlocal 'A' found"),
        refuse("an annotated name declared global", "SRC-INV-PARSE", {"a.py": py("A = 1", "", "def replace():", "    global A", "    A: int = 1")}, ("a.py", 5), "annotated name 'A' can't be global"),
        refuse("a star import in a class body", "SRC-INV-PARSE", {"a.py": py("class A:", "    from os import *")}, ("a.py", 2), "import * only allowed at module level"),
    ],
    "unrecognised_forms": [
        refuse("a type alias statement", "SRC-FORM-UNRECOGNISED", {"a.py": py("type Alias = int")}, ("a.py", 1), "TypeAlias"),
        refuse("a type alias in a class body", "SRC-FORM-UNRECOGNISED", {"a.py": py("class C:", "    type Alias = int")}, ("a.py", 2), "TypeAlias"),
        refuse("a type parameter of a function", "SRC-FORM-UNRECOGNISED", {"a.py": py("def f[T](x: T) -> T:", "    return x")}, ("a.py", 1), "TypeVar"),
        refuse("a type parameter of a class", "SRC-FORM-UNRECOGNISED", {"a.py": py("class C[T]:", "    pass")}, ("a.py", 1), "TypeVar"),
        refuse("a type parameter pack of a function", "SRC-FORM-UNRECOGNISED", {"a.py": py("def f[*Ts](*args: *Ts):", "    pass")}, ("a.py", 1), "TypeVarTuple"),
        refuse("a store through a name nothing binds", "SRC-FORM-UNRECOGNISED", {"a.py": py("def f():", "    nowhere.x = 1")}, ("a.py", 2), "nowhere.x"),
        refuse("an item written through a name nothing binds", "SRC-FORM-UNRECOGNISED", {"a.py": py("def f():", "    nowhere[0] = 1")}, ("a.py", 2), "nowhere[0]"),
        refuse("setattr through a name nothing binds", "SRC-FORM-UNRECOGNISED", {"a.py": py("def f():", "    setattr(nowhere, 'x', 1)")}, ("a.py", 2), "nowhere"),
        refuse("a __slots__ that is a name, not a literal", "SRC-FORM-UNRECOGNISED", {"a.py": py("NAMES = ('a',)", "", "class C:", "    __slots__ = NAMES")}, ("a.py", 4), "__slots__"),
        refuse("a __slots__ written twice", "SRC-FORM-UNRECOGNISED", {"a.py": py("class C:", "    __slots__ = ('a',)", "    __slots__ = ('b',)")}, ("a.py", 2), "__slots__"),
        refuse("a __slots__ that is a dictionary", "SRC-FORM-UNRECOGNISED", {"a.py": py("class C:", "    __slots__ = {'a': 'documented'}")}, ("a.py", 2), "__slots__"),
    ],
    "class_body_bindings_of_every_kind": [
        refuse("a loop target in a class body hides an inherited method (Astra's class-loop target)", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    for f in [lambda: 'injected']:", "        pass")}, ("b.py", 4), "overrides a method named f"),
        refuse("a with target in a class body hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    with open('x') as f:", "        pass")}, ("b.py", 4), "overrides a method named f"),
        refuse("an import in a class body hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    from os import path as f")}, ("b.py", 4), "overrides a method named f"),
        refuse("a walrus in a class body hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    (f := 1)")}, ("b.py", 4), "overrides a method named f"),
        refuse("an augmented assignment in a class body hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    f = 0", "    f += 1")}, ("b.py", 4), "overrides a method named f"),
        refuse("a nested class in a class body hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    class f:", "        pass")}, ("b.py", 4), "overrides a method named f"),
        refuse("a match capture in a class body hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    match 1:", "        case f:", "            pass")}, ("b.py", 5), "overrides a method named f"),
        refuse("a slot hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    __slots__ = ('f',)")}, ("b.py", 3), "overrides a method named f"),
        refuse("a slot written as a bare string hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    __slots__ = 'f'")}, ("b.py", 3), "overrides a method named f"),
        refuse("a dataclass field hides an inherited method (Astra's dataclass field)", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from dataclasses import dataclass", "from {pkg}.a import A", "", "@dataclass", "class B(A):", "    f: object")}, ("b.py", 6), "overrides a method named f"),
        refuse("a dataclass field with a default hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from dataclasses import dataclass", "from {pkg}.a import A", "", "@dataclass", "class B(A):", "    f: int = 0")}, ("b.py", 6), "overrides a method named f"),
        refuse("a frozen dataclass field hides an inherited method", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from dataclasses import dataclass", "from {pkg}.a import A", "", "@dataclass(frozen=True)", "class B(A):", "    f: object")}, ("b.py", 6), "overrides a method named f"),
        refuse("a dataclass field hides a method of a SIBLING in the family", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from dataclasses import dataclass", "from {pkg}.a import A", "", "@dataclass", "class B(A):", "    pass", "", "@dataclass", "class C(A):", "    f: int"),
                }, ("b.py", 10), "overrides a method named f"),
        refuse("a field of an inherited dataclass hides a method of its subclass", "SRC-ATTR-OVERRIDE",
               {"a.py": py("from dataclasses import dataclass", "", "@dataclass", "class A:", "    size: int"),
                "b.py": py("from {pkg}.a import A", "", "class B(A):", "    def size(self):", "        return 1")}, ("a.py", 5), "overrides a method named size"),
        refuse("a dataclass field named like a method of its own class", "SRC-ATTR-OVERRIDE",
               {"a.py": py("from dataclasses import dataclass", "", "@dataclass", "class A:", "    size: int", "", "    def size(self):", "        return 1")}, ("a.py", 5), "overrides a method named size"),
    ],
    "writes_through_data_to_a_family_methods_name": [
        refuse("an attribute written on a parameter, named like a method of a family", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"), "c.py": py("def hack(obj):", "    obj.f = lambda: 'injected'")}, ("c.py", 2), "may hold an instance of the family"),
        refuse("an attribute written on a local, named like a method of a family", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"), "c.py": py("def hack(make):", "    obj = make()", "    obj.f = 1")}, ("c.py", 3), "may hold an instance of the family"),
        refuse("an attribute written by an augmented assignment through an element", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"), "c.py": py("def hack(objs):", "    objs[0].f += 1")}, ("c.py", 2), "may hold an instance of the family"),
        refuse("a literal setattr through a parameter, named like a method of a family", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"), "c.py": py("def hack(obj):", "    setattr(obj, 'f', 1)")}, ("c.py", 2), "overrides a method named f"),
        refuse("an attribute written through a loop target over data, named like a method of a family", "SRC-ATTR-OVERRIDE",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"), "c.py": py("def hack(rows):", "    for row in rows:", "        row.f = 1")}, ("c.py", 3), "may hold an instance of the family"),
    ],
    "hooks_bound_by_any_statement": [
        refuse("__getattribute__ assigned from a function (Astra's class hook alias)", "SRC-CLASS-HOOK",
               {"a.py": py("def getattribute(self, name):", "    return object.__getattribute__(self, name)", "", "class A:", "    __getattribute__ = getattribute")}, ("a.py", 5), "binds __getattribute__"),
        refuse("__getattribute__ bound by a loop target", "SRC-CLASS-HOOK",
               {"a.py": py("class A:", "    for __getattribute__ in [object.__getattribute__]:", "        pass")}, ("a.py", 2), "binds __getattribute__"),
        refuse("__getattribute__ bound by a with target", "SRC-CLASS-HOOK", {"a.py": py("class A:", "    with open('x') as __getattribute__:", "        pass")}, ("a.py", 2), "binds __getattribute__"),
        refuse("__getattribute__ imported", "SRC-CLASS-HOOK", {"a.py": py("class A:", "    from os import path as __getattribute__")}, ("a.py", 2), "binds __getattribute__"),
        refuse("__getattribute__ bound by a walrus", "SRC-CLASS-HOOK", {"a.py": py("class A:", "    (__getattribute__ := object.__getattribute__)")}, ("a.py", 2), "binds __getattribute__"),
        refuse("__init_subclass__ assigned", "SRC-CLASS-HOOK", {"a.py": py("class A:", "    __init_subclass__ = classmethod(lambda cls: None)")}, ("a.py", 2), "binds __init_subclass__"),
        refuse("__mro_entries__ assigned", "SRC-CLASS-HOOK", {"a.py": py("class A:", "    __mro_entries__ = lambda self, bases: ()")}, ("a.py", 2), "binds __mro_entries__"),
        refuse("__getattribute__ annotated with a value", "SRC-CLASS-HOOK", {"a.py": py("class A:", "    __getattribute__: object = object.__getattribute__")}, ("a.py", 2), "binds __getattribute__"),
    ],
    "method_aliases_by_any_statement": [
        refuse("a method aliased by a loop target", "SRC-METHOD-ALIAS",
               {"a.py": py("class A:", "    def helper(self):", "        return 1", "    for g in (helper,):", "        pass")}, ("a.py", 4), "aliases the method helper"),
        refuse("a method aliased by a walrus", "SRC-METHOD-ALIAS",
               {"a.py": py("class A:", "    def helper(self):", "        return 1", "    (g := helper)")}, ("a.py", 4), "aliases the method helper"),
        refuse("a method aliased by an unpacking", "SRC-METHOD-ALIAS",
               {"a.py": py("class A:", "    def helper(self):", "        return 1", "    g, h = helper, 2")}, ("a.py", 4), "aliases the method helper"),
        refuse("a method aliased inside a container", "SRC-METHOD-ALIAS",
               {"a.py": py("class A:", "    def helper(self):", "        return 1", "    table = {'k': helper}")}, ("a.py", 4), "aliases the method helper"),
        refuse("a method aliased by an annotated assignment", "SRC-METHOD-ALIAS",
               {"a.py": py("class A:", "    def helper(self):", "        return 1", "    g: object = helper")}, ("a.py", 4), "aliases the method helper"),
        refuse("a method aliased under a conditional in the body", "SRC-METHOD-ALIAS",
               {"a.py": py("class A:", "    def helper(self):", "        return 1", "    if True:", "        g = helper")}, ("a.py", 5), "aliases the method helper"),
    ],
    "stores_on_modules_and_packages": [
        refuse("an attribute written on an imported module (Astra's module overwrite)", "SRC-REFLECTIVE",
               {"a.py": A, "b.py": py("import {pkg}.a as a", "a.A = object")}, ("b.py", 2), "writes the attribute A of a module"),
        refuse("an attribute written on a module imported by name", "SRC-REFLECTIVE",
               {"a.py": A, "b.py": py("from {pkg} import a", "a.A = object")}, ("b.py", 2), "writes the attribute A of a module"),
        refuse("an attribute written on a package", "SRC-REFLECTIVE",
               {"pkg/__init__.py": "x = 1\n", "b.py": py("import {pkg}.pkg as p", "", "p.x = 2")}, ("b.py", 3), "writes the attribute x of a module"),
        refuse("an attribute deleted from a module", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "del a.A")}, ("b.py", 2), "writes the attribute A of a module"),
        refuse("a module attribute augmented", "SRC-REFLECTIVE", {"a.py": MODULE_A["a.py"], "b.py": py("import {pkg}.a as a", "a.count += 1")}, ("b.py", 2), "writes the attribute count of a module"),
        refuse("a module attribute written by a loop target", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "for a.A in range(2):", "    pass")}, ("b.py", 2), "writes the attribute A of a module"),
        refuse("a module attribute written by a with target", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "with open('x') as a.A:", "    pass")}, ("b.py", 2), "writes the attribute A of a module"),
        refuse("a module attribute written by an unpacking", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "a.A, other = 1, 2")}, ("b.py", 2), "writes the attribute A of a module"),
        refuse("a module attribute written by a comprehension target", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "items = [0 for a.A in range(2)]")}, ("b.py", 2), "writes the attribute A of a module"),
        refuse("a module attribute written inside a function", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "", "def replace():", "    a.A = object")}, ("b.py", 4), "writes the attribute A of a module"),
        refuse("a module attribute written through an alias", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "", "m = a", "m.A = object")}, ("b.py", 4), "writes the attribute A of a module"),
        refuse("a class attribute written through a module", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "a.A.f = object")}, ("b.py", 2), "writes the attribute f of a class"),
        refuse("a class attribute written through an imported class", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("from {pkg}.a import A", "A.f = object")}, ("b.py", 2), "writes the attribute f of a class"),
        refuse("an attribute written on an external module", "SRC-REFLECTIVE", {"a.py": py("import os", "os.sep = '|'")}, ("a.py", 2), "writes the attribute sep of a module"),
        refuse("an attribute written on an external object imported by name", "SRC-REFLECTIVE", {"a.py": py("from os import path", "path.sep = '|'")}, ("a.py", 2), "writes the attribute sep of a module"),
        refuse("an item of an external module's member written", "SRC-REFLECTIVE", {"a.py": py("import os", "os.environ['X'] = 'y'")}, ("a.py", 2), "of a module, a function or an external object"),
        refuse("a function's attribute written", "SRC-REFLECTIVE", {"a.py": py("def f():", "    pass", "", "f.cache = {}")}, ("a.py", 4), "writes the attribute cache of a module, a function"),
        refuse("setattr on an imported module", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "setattr(a, 'A', object)")}, ("b.py", 2), "writes an attribute of a module"),
        refuse("setattr on an external module", "SRC-REFLECTIVE", {"a.py": py("import os", "setattr(os, 'sep', '|')")}, ("a.py", 2), "writes an attribute of a module"),
        refuse("object.__setattr__ on an imported module", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "object.__setattr__(a, 'A', object)")}, ("b.py", 2), "writes an attribute of a module"),
        refuse("delattr on an imported module", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "delattr(a, 'A')")}, ("b.py", 2), "writes an attribute of a module"),
    ],
    "stores_on_classes_through_names": [
        refuse("a class attribute written through an alias of the class", "SRC-REFLECTIVE", {"a.py": A + py("", "k = A", "k.f = 1")}, ("a.py", 6), "writes the attribute f of a class"),
        refuse("a class attribute written through a local alias of the class", "SRC-REFLECTIVE", {"a.py": A + py("", "def change():", "    k = A", "    k.f = 1")}, ("a.py", 7), "writes the attribute f of a class"),
        refuse("a class attribute written through a conditional alias", "SRC-REFLECTIVE", {"a.py": A + py("", "def change(flag):", "    k = A if flag else object", "    k.f = 1")}, ("a.py", 7), "writes the attribute f of a class"),
        refuse("a class attribute written through a loop target over classes", "SRC-REFLECTIVE", {"a.py": A + py("", "def change():", "    for k in (A, object):", "        k.f = 1")}, ("a.py", 7), "writes the attribute f of a class"),
        refuse("a class attribute written through a loop target over a name bound to classes", "SRC-REFLECTIVE",
               {"a.py": A + py("", "KLASSES = [A, object]", "", "def change():", "    for k in KLASSES:", "        k.f = 1")}, ("a.py", 9), "writes the attribute f of a class"),
        refuse("a class attribute written through getattr of a class", "SRC-REFLECTIVE", {"a.py": A + py("", "getattr(A, 'self_type').x = 1")}, ("a.py", 5), "writes the attribute x of a class"),
        refuse("a class attribute written through type of an instance", "SRC-REFLECTIVE", {"a.py": A + py("", "def change(a):", "    type(a).f = 1")}, ("a.py", 6), "writes the attribute f of a class"),
        refuse("a class attribute written through __class__ of data", "SRC-REFLECTIVE", {"a.py": A + py("", "def change(a):", "    a.__class__.f = 1")}, ("a.py", 6), "writes the attribute f of a class"),
        refuse("an item written on a class", "SRC-REFLECTIVE", {"a.py": A + py("", "A['k'] = 1")}, ("a.py", 5), "writes the attribute an item of a class"),
        refuse("a class attribute written through a walrus alias", "SRC-REFLECTIVE", {"a.py": A + py("", "def change():", "    (k := A).f = 1")}, ("a.py", 6), "writes the attribute f of a class"),
    ],
    "namespace_dictionaries_and_sys_modules": [
        refuse("a module dictionary written", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "a.__dict__['A'] = object")}, ("b.py", 2), "namespace of a class"),
        refuse("vars of a module written", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "vars(a)['A'] = object")}, ("b.py", 2), "vars()"),
        refuse("a class dictionary updated through vars", "SRC-REFLECTIVE", {"a.py": A + py("", "vars(A).update({'f': 1})")}, ("a.py", 5), "namespace through globals(), locals() or vars()"),
        refuse("a module dictionary updated", "SRC-REFLECTIVE", {"a.py": A, "b.py": py("import {pkg}.a as a", "a.__dict__.update({'A': object})")}, ("b.py", 2), "namespace of a class"),
        refuse("sys.modules updated by a method", "SRC-REFLECTIVE", {"a.py": py("import sys", "sys.modules.update({})")}, ("a.py", 2), "changes sys.modules"),
        refuse("sys.modules popped", "SRC-REFLECTIVE", {"a.py": py("import sys", "sys.modules.pop('x', None)")}, ("a.py", 2), "changes sys.modules"),
        refuse("an item deleted from sys.modules", "SRC-REFLECTIVE", {"a.py": py("import sys", "del sys.modules['x']")}, ("a.py", 2), "writes sys.modules"),
        refuse("an attribute of a module taken from sys.modules written", "SRC-REFLECTIVE", {"a.py": py("import sys", "sys.modules['x'].attr = 1")}, ("a.py", 2), "of a module, a function"),
        refuse("an attribute of a module taken from sys.modules.get written", "SRC-REFLECTIVE", {"a.py": py("import sys", "sys.modules.get('x').attr = 1")}, ("a.py", 2), "of a module, a function"),
        refuse("an attribute of an item of globals written", "SRC-REFLECTIVE", {"a.py": A + py("", "globals()['A'].f = 1")}, ("a.py", 5), "of a module, a function"),
        refuse("globals updated through a local name", "SRC-REFLECTIVE", {"a.py": py("def change():", "    g = globals()", "    g['x'] = 1")}, ("a.py", 3), "globals()"),
        refuse("a namespace dictionary through a local name updated by a method", "SRC-REFLECTIVE", {"a.py": py("def change():", "    g = globals()", "    g.update({'x': 1})")}, ("a.py", 3), "changes"),
        refuse("the receiver's own dictionary written", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self):", "        self.__dict__['g'] = 1")}, ("a.py", 3), "receiver's own namespace"),
        refuse("the receiver's own dictionary updated", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self):", "        self.__dict__.update({'g': 1})")}, ("a.py", 3), "receiver's own namespace"),
        refuse("the receiver's vars written", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self):", "        vars(self)['g'] = 1")}, ("a.py", 3), "receiver's own namespace"),
        refuse("a class dictionary updated through type of the receiver", "SRC-REFLECTIVE", {"a.py": py("class A:", "    def f(self):", "        type(self).__dict__.update({'g': 1})")}, ("a.py", 3), "namespace of a class"),
    ],
    "all_not_only_mutated_but_passed_on": [
        refuse("__all__ aliased and the alias mutated (Astra's aliased __all__)", "SRC-ALL-DYNAMIC", {"a.py": A + py("__all__ = []", "exports = __all__", "exports.append('A')")}, ("a.py", 5), "passes __all__ on"),
        refuse("__all__ passed to a function", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['x']", "", "def grow(names):", "    names.append('y')", "", "grow(__all__)")}, ("a.py", 6), "passes __all__ on"),
        refuse("__all__ returned from a function", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['x']", "", "def names():", "    return __all__")}, ("a.py", 4), "passes __all__ on"),
        refuse("__all__ held in a container", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['x']", "", "HOLDERS = [__all__]")}, ("a.py", 3), "passes __all__ on"),
        refuse("__all__ extended through another module", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['x']"), "b.py": py("import {pkg}.a as a", "a.__all__.append('y')")}, ("b.py", 2), "mutates __all__"),
        refuse("__all__ of another module replaced", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['x']"), "b.py": py("import {pkg}.a as a", "a.__all__ = []")}, ("b.py", 2), "binds __all__"),
        refuse("__all__ of another module edited by item", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['x']"), "b.py": py("import {pkg}.a as a", "a.__all__[0] = 'y'")}, ("b.py", 2), "mutates __all__"),
        refuse("__all__ imported and passed on", "SRC-ALL-DYNAMIC", {"a.py": py("__all__ = ['x']"), "b.py": py("from {pkg}.a import __all__", "mine = __all__")}, ("b.py", 2), "passes __all__ on"),
    ],
    "external_classes_through_ancestors": [
        refuse("an external ancestor before a project class (Astra's UserDict case)", "SRC-BASE-MIXED",
               {"a.py": py("from collections import UserDict", "", "class A(UserDict):", "    pass"), "b.py": py("class B:", "    def keys(self):", "        return 'project'"),
                "c.py": py("from {pkg}.a import A", "from {pkg}.b import B", "", "class C(A, B):", "    pass")}, ("c.py", 4), "comes before the project class"),
        refuse("an external ancestor two levels up, before a project class", "SRC-BASE-MIXED",
               {"a.py": py("class A(Exception):", "    pass"), "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"), "d.py": py("class D:", "    def args(self):", "        return 1"),
                "c.py": py("from {pkg}.b import B", "from {pkg}.d import D", "", "class C(B, D):", "    pass")}, ("c.py", 4), "comes before the project class"),
        refuse("an external ancestor reached through a same-file intermediate", "SRC-BASE-MIXED",
               {"a.py": py("import threading", "", "class A(threading.Thread):", "    pass", "", "class Mid(A):", "    pass"), "d.py": py("class D:", "    def run(self):", "        return 1"),
                "c.py": py("from {pkg}.a import Mid", "from {pkg}.d import D", "", "class C(Mid, D):", "    pass")}, ("c.py", 4), "comes before the project class"),
        refuse("object listed before a project base", "SRC-BASE-HIERARCHY", {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(object, A):", "    pass")}, ("b.py", 3), "no consistent method resolution order"),
        refuse("object listed before a project base whose own base is external", "SRC-BASE-HIERARCHY",
               {"a.py": py("class A(Exception):", "    pass"), "b.py": py("from {pkg}.a import A", "", "class B(object, A):", "    pass")}, ("b.py", 3), "no consistent method resolution order"),
        refuse("a base listed twice", "SRC-BASE-HIERARCHY", {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A, A):", "    pass")}, ("b.py", 3), "no consistent method resolution order"),
    ],
    "aliases_carry_the_identity": [
        refuse("a dataclass field marker that is an alias of a name whose bindings compete", "SRC-BINDING-COMPETING",
               {"a.py": py("import typing", "from dataclasses import dataclass", "", "marker = typing.ClassVar", "typing = None", "", "@dataclass", "class A:", "    n: marker[int] = 0")}, ("a.py", 9),
               "its identity matters"),
        refuse("a loader assigned to a name (Astra's loader alias)", "SRC-LOADER-UNINVENTORIED",
               {"a.py": py("from importlib import import_module", "loader = import_module", "value = loader('math')")}, ("a.py", 3), "importlib.import_module"),
        refuse("a loader reached through an aliased module", "SRC-LOADER-UNINVENTORIED",
               {"a.py": py("import importlib", "m = importlib", "value = m.import_module('math')")}, ("a.py", 3), "importlib.import_module"),
        refuse("a loader aliased twice", "SRC-LOADER-UNINVENTORIED",
               {"a.py": py("from importlib import import_module", "first = import_module", "second = first", "value = second('math')")}, ("a.py", 4), "importlib.import_module"),
        refuse("a loader aliased inside a function", "SRC-LOADER-UNINVENTORIED",
               {"a.py": py("import importlib", "", "def load():", "    fn = importlib.import_module", "    return fn('math')")}, ("a.py", 5), "importlib.import_module"),
        refuse("a loader unpacked from a tuple, at the position it has", "SRC-LOADER-UNINVENTORIED",
               {"a.py": py("from importlib import import_module", "size, loader = (len, import_module)", "value = loader('math')")}, ("a.py", 3), "importlib.import_module"),
        refuse("a loader re-exported by another module", "SRC-LOADER-UNINVENTORIED",
               {"a.py": py("from importlib import import_module as load"), "b.py": py("from {pkg}.a import load", "value = load('math')")}, ("b.py", 2), "importlib.import_module"),
        refuse("a loader re-exported through an alias assignment and a qualified module chain", "SRC-LOADER-UNINVENTORIED",
               {"a.py": py("from importlib import import_module", "load = import_module"), "b.py": py("import {pkg}.a as a", "value = a.load('math')")}, ("b.py", 2), "importlib.import_module"),
        refuse("exec aliased", "SRC-LOADER-UNINVENTORIED", {"a.py": py("run = exec", "run('x = 1')")}, ("a.py", 2), "builtins.exec"),
        refuse("a decorator that is an alias of itself through a swap has no identity", "SRC-DECORATOR-SHADOWED",
               {"a.py": py("first, second = second, first", "", "class A:", "    @first", "    def f(self):", "        return 1")}, ("a.py", 4), "an alias of itself"),
        refuse("a class made by an aliased three-argument type", "SRC-CLASS-DYNAMIC", {"a.py": py("make = type", "A = make('A', (), {})")}, ("a.py", 2), "makes a class by a call"),
        refuse("setattr aliased and aimed at a class", "SRC-REFLECTIVE", {"a.py": A + py("", "put = setattr", "put(A, 'f', 1)")}, ("a.py", 6), "writes an attribute of a class"),
        refuse("a decorator that is an alias of an unrecorded one", "SRC-DECORATOR-UNKNOWN",
               {"a.py": py("import functools", "", "cached = functools.cache", "", "class A:", "    @cached", "    def f(self):", "        return 1")}, ("a.py", 6), "functools.cache"),
    ],
    "dataclass_forms_the_record_does_not_allow": [
        refuse("a dataclass with unsafe_hash", "SRC-DECORATOR-ARGS", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(unsafe_hash=True)", "class A:", "    x: int = 0")}, ("a.py", 3), "unsafe_hash=True"),
        refuse("a dataclass with eq false", "SRC-DECORATOR-ARGS", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(eq=False)", "class A:", "    x: int = 0")}, ("a.py", 3), "eq=False"),
        refuse("a dataclass with frozen false said out loud", "SRC-DECORATOR-ARGS", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(frozen=False)", "class A:", "    x: int = 0")}, ("a.py", 3), "frozen=False"),
        refuse("a dataclass without an init", "SRC-DECORATOR-ARGS", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(init=False)", "class A:", "    x: int = 0")}, ("a.py", 3), "init=False"),
        refuse("a dataclass with frozen and unsafe_hash together", "SRC-DECORATOR-ARGS",
               {"a.py": py("from dataclasses import dataclass", "", "@dataclass(frozen=True, unsafe_hash=True)", "class A:", "    x: int = 0")}, ("a.py", 3), "unsafe_hash=True"),
    ],
}


def ordinary_data_stores() -> list[Fixture]:
    """Ordinary data processing that must not be over-refused: attributes and items written on parameters, locals, call results and the elements of containers.

    NOTE 2026-10-05 (task 2q-a-repair-5): these fixtures are NOT closure evidence, and the family is no longer named for one. Astra's 2q-a-repair-4 review (F1, Gate C) showed that a
    parameter, a call result or the element of a container can hold a module or a class (`def replace(ns): ns.A = object` called with a module), and a store through it changes the
    owner of a later direct call. Which of those values may be such an owner is decided by CALL-TIME OWNER EFFECTS, slice 2 of the F1 repair, which slice 1 (binding identity) does not do:
    until then they say only that the stores below are accepted, not that accepting them is sound. Slice 2 replaces the expectations it cannot keep with owner-escape cases that
    the interpreter controls (gen2/tests/source_binding_fixtures.py shows the shape)."""
    return [
        accept("a name no family has as a method may be written on data, and so may a name only a single class has",
               {"a.py": py("class Solo:", "    def only(self):", "        return 1"), "b.py": py("def change(obj):", "    obj.only = 2", "    obj.other = 3", "    delattr(obj, 'only')", "    del obj.only")}, functions=["a.py::Solo.only", "b.py::change"]),
        accept("deleting an attribute named like a method of a family hides nothing",
               {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A):", "    pass"), "c.py": py("def drop(obj):", "    delattr(obj, 'f')", "    del obj.f")}, functions=["a.py::A.f", "c.py::drop"]),
        accept("an attribute written through an assignment expression that binds data", {"a.py": py("def change(make):", "    (obj := make()).value = 1", "    return obj")}, functions=["a.py::change"]),
        accept("an attribute written on a parameter", {"a.py": py("def change(obj):", "    obj.value = 1", "    obj.value += 1", "    del obj.value")}, functions=["a.py::change"]),
        accept("an item written on a parameter, a local and a module-level container",
               {"a.py": py("REGISTRY = {}", "", "def put(key, value, rows):", "    REGISTRY[key] = value", "    rows[0] = value", "    local = {}", "    local[key] = value", "    del local[key]", "    return local")},
               functions=["a.py::put"]),
        accept("an attribute written on the result of a call and on an element of a container",
               {"a.py": py("def change(rows, make):", "    make().value = 1", "    rows[0].value = 2", "    rows[0][1] = 3", "    rows.get('k').value = 4", "    rows.setdefault('k', {})['x'] = 5")}, functions=["a.py::change"]),
        accept("an attribute written on an object a local name holds", {"a.py": py("import threading", "", "_STATE = threading.local()", "", "def change():", "    state = threading.local()", "    state.x = 1",
                                                                                   "    _STATE.y = 2", "    with open('x') as handle:", "        handle.mode = 'r'")}, functions=["a.py::change"]),
        accept("an attribute written through the receiver and through a chain from it",
               {"a.py": py("class A:", "    def __init__(self):", "        self.items = {}", "        self.items['k'] = 1", "        self.inner = object()", "        self.inner.value = 2", "        self.rows = [0]",
                           "        self.rows[0] = 3", "        me = self", "        me.other = 4")}, methods={"a.py::A": {"__init__": "method"}}),
        accept("a write through a loop target over data and a conditional of data", {"a.py": py("def change(rows, flag, other):", "    for row in rows:", "        row.seen = True", "    target = rows if flag else other",
                                                                                                 "    target.count = 1")}, functions=["a.py::change"]),
        accept("an attribute written on a class instance the function makes", {"a.py": py("class A:", "    pass", "", "def make():", "    a = A()", "    a.value = 1", "    return a")}, functions=["a.py::make"]),
        accept("setattr on data with a literal name", {"a.py": py("def change(obj):", "    setattr(obj, 'value', 1)", "    delattr(obj, 'value')")}, functions=["a.py::change"]),
        accept("a dictionary of data, vars of data and the __dict__ of a local object", {"a.py": py("def change(obj, rows):", "    obj.__dict__['k'] = 1", "    vars(obj)['k'] = 2", "    rows.__dict__.update({'k': 3})")},
               functions=["a.py::change"]),
        accept("an annotation of an attribute declares and stores nothing", {"a.py": py("def change(obj):", "    obj.value: int", "    return obj")}, functions=["a.py::change"]),
        accept("an annotation of an attribute of a module stores nothing in it", {"a.py": py("import os", "", "os.extra: int")}),
    ]


CLOSURE_ACCEPTS: dict[str, list[Fixture]] = {
    "ordinary_data_stores": ordinary_data_stores(),   # not closure evidence: see the note on ordinary_data_stores
    "class_bodies_that_bind_data": [
        accept("a class body binds data by any recorded statement without colliding with a method",
               {"a.py": py("class A:", "    one = 1", "    two: int = 2", "    three: int", "    for four in range(2):", "        pass", "    with open('x') as five:", "        pass", "    from os import path as six",
                           "    (seven := 7)", "    eight = nine = 8", "    ten, eleven = 10, 11", "    class Inner:", "        pass", "", "    def run(self):", "        return self.one")},
               members={"a.py::A": {"one": ["data", "authored"], "two": ["data", "authored"], "four": ["data", "authored"], "five": ["data", "authored"], "six": ["data", "authored"],
                                    "seven": ["data", "authored"], "eight": ["data", "authored"], "nine": ["data", "authored"], "ten": ["data", "authored"], "eleven": ["data", "authored"],
                                    "Inner": ["data", "authored"], "run": ["method", "authored"]}}),
        accept("an annotation alone binds nothing in the class", {"a.py": py("class A:", "    x: int", "    def f(self):", "        return 1")}, members={"a.py::A": {"f": ["method", "authored"], "x": None}}),
    ],
    "implicit_and_generated_members": [
        accept("__eq__ without __hash__ sets __hash__ to None",
               {"a.py": py("class A:", "    def __eq__(self, other):", "        return True")}, members={"a.py::A": {"__eq__": ["method", "authored"], "__hash__": ["data", "implicit"]}}),
        accept("__eq__ with __hash__ keeps the method", {"a.py": py("class A:", "    def __eq__(self, other):", "        return True", "", "    def __hash__(self):", "        return 1")},
               members={"a.py::A": {"__eq__": ["method", "authored"], "__hash__": ["method", "authored"]}}),
        accept("__hash__ written as None is data", {"a.py": py("class A:", "    __hash__ = None")}, members={"a.py::A": {"__hash__": ["data", "authored"]}}),
        accept("a bare dataclass has __hash__ None", {"a.py": py("from dataclasses import dataclass", "", "@dataclass", "class A:", "    x: int = 0")},
               members={"a.py::A": {"__hash__": ["data", "generated"], "__eq__": ["method", "generated"], "__init__": ["method", "generated"], "__repr__": ["method", "generated"]}}),
        accept("a called dataclass has __hash__ None", {"a.py": py("from dataclasses import dataclass", "", "@dataclass()", "class A:", "    x: int = 0")}, members={"a.py::A": {"__hash__": ["data", "generated"]}}),
        accept("a frozen dataclass has a generated __hash__", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(frozen=True)", "class A:", "    x: int = 0")},
               members={"a.py::A": {"__hash__": ["method", "generated"], "__setattr__": ["method", "generated"], "__delattr__": ["method", "generated"]}}),
        accept("a dataclass whose body defines __hash__ keeps it", {"a.py": py("from dataclasses import dataclass", "", "@dataclass", "class A:", "    x: int = 0", "", "    def __hash__(self):", "        return 1")},
               members={"a.py::A": {"__hash__": ["method", "authored"]}}),
        accept("a frozen dataclass whose body defines __hash__ keeps it", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(frozen=True)", "class A:", "    x: int = 0", "", "    def __hash__(self):", "        return 1")},
               members={"a.py::A": {"__hash__": ["method", "authored"]}}),
        accept("a dataclass whose body defines __eq__ has __hash__ None", {"a.py": py("from dataclasses import dataclass", "", "@dataclass", "class A:", "    x: int = 0", "", "    def __eq__(self, other):", "        return True")},
               members={"a.py::A": {"__hash__": ["data", "generated"], "__eq__": ["method", "authored"]}}),
        accept("a frozen dataclass whose body defines __eq__ generates __hash__", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(frozen=True)", "class A:", "    x: int = 0", "", "    def __eq__(self, other):", "        return True")},
               members={"a.py::A": {"__hash__": ["method", "generated"], "__eq__": ["method", "authored"]}}),
        accept("a frozen dataclass whose body sets __hash__ to None next to __eq__ generates __hash__", {"a.py": py("from dataclasses import dataclass", "", "@dataclass(frozen=True)", "class A:", "    x: int = 0", "", "    __hash__ = None", "",
                                                                                                                       "    def __eq__(self, other):", "        return True")},
               members={"a.py::A": {"__hash__": ["method", "generated"]}}),
        accept("a literal __slots__ lists its names as slots", {"a.py": py("class A:", "    __slots__ = ('a', 'b')", "", "class B:", "    __slots__ = ['c']", "", "class C:", "    __slots__ = 'd'", "", "class D:", "    __slots__ = ()")},
               members={"a.py::A": {"a": ["slot", "authored"], "b": ["slot", "authored"]}, "a.py::B": {"c": ["slot", "authored"]}, "a.py::C": {"d": ["slot", "authored"]}}),
        accept("ClassVar, InitVar and KW_ONLY are no instance fields, so a subclass may have a method of that name",
               {"a.py": py("from dataclasses import dataclass, InitVar, KW_ONLY", "from typing import ClassVar", "", "@dataclass", "class A:", "    seed: InitVar[int]", "    shared: ClassVar[int]", "    _: KW_ONLY",
                           "    kept: int = 0", "    named: int = 0", "", "class B(A):", "    def shared(self):", "        return 1", "", "    def seed(self):", "        return 2")},
               fields={"a.py::A": ["kept", "named"]}),
    ],
    "external_classes_after_every_project_class": [
        accept("an external ancestor after every project class cannot hide a project name",
               {"a.py": py("from collections import UserDict", "", "class A(UserDict):", "    pass"), "b.py": py("class B:", "    def keys(self):", "        return 'project'"),
                "c.py": py("from {pkg}.a import A", "from {pkg}.b import B", "", "class C(B, A):", "    def run(self):", "        return self.keys()")},
               family={"c.py::C": ["c.py::C", "b.py::B", "a.py::A"]}),
        accept("a class that is external all the way up is a leaf", {"a.py": py("class A(Exception):", "    pass", "", "class B(A):", "    pass")}, classes=["a.py::A", "a.py::B"]),
        accept("object last in the bases is the order Python has", {"a.py": A, "b.py": py("from {pkg}.a import A", "", "class B(A, object):", "    pass")}, family={"b.py::B": ["b.py::B", "a.py::A"]}),
    ],
    "aliases_and_scopes": [
        accept("a name bound to a recorded decorator is that decorator", {"a.py": py("d = property", "", "class A:", "    @d", "    def p(self):", "        return 1")}, methods={"a.py::A": {"p": "property"}}),
        accept("a walrus in a function body binds there", {"a.py": py("def f(items):", "    if (n := len(items)) > 1:", "        return n", "    return [(m := i) for i in items]")}, functions=["a.py::f"]),
        accept("a walrus in a class body annotation binds in the class, not in the module", {"a.py": A + py("", "class Other:", "    marker: (A := object)")}, classes=["a.py::A", "a.py::Other"]),
        accept("a lambda and a comprehension keep their own bindings", {"a.py": py("class A:", "    pass", "", "key = lambda A: A", "rows = [A for A in range(2)]", "pairs = {A: A for A in range(2)}")}, classes=["a.py::A"]),
        accept("a comprehension's iteration variable shadows an imported loader", {"a.py": py("from importlib import import_module as load", "", "def apply(handlers):", "    keep = load", "    return [load('x') for load in handlers]")},
               functions=["a.py::apply"]),
        accept("a call through an alias of data whose bindings compete is no unresolved alias", {"a.py": py("def run(handler):", "    chosen = handler", "    handler = 5", "    return chosen()")}, functions=["a.py::run"]),
        accept("a global declared for a name the module only reads is no rebinding of a definition", {"a.py": py("COUNT = 0", "", "def bump():", "    global COUNT", "    COUNT += 1")}, functions=["a.py::bump"]),
        accept("a nonlocal write belongs to the nearest function that binds the name, so the outer function's definition is not rebound",
               {"a.py": py("def outer():", "    def helper():", "        return 1", "    def middle():", "        helper = 2", "        def replace():", "            nonlocal helper", "            helper = 3", "        replace()",
                           "    middle()")}, functions=["a.py::outer", "a.py::outer.helper", "a.py::outer.middle", "a.py::outer.middle.replace"]),
        accept("a global that is a data name and a nonlocal in a closure", {"a.py": py("TOTAL = 0", "", "def outer():", "    seen = 0", "    def inner():", "        global TOTAL", "        nonlocal seen", "        TOTAL += 1", "        seen += 1",
                                                                                         "    return inner")}, functions=["a.py::outer", "a.py::outer.inner"]),
    ],
}
