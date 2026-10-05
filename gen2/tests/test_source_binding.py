"""Binding identity (task 2q-a-repair-5, slice 1 of the F1 repair; Astra's 2q-a-repair-4 review F1): one resolver says which class, function, module or external object a name is, and
every consumer asks it (docs/gen2/SOURCE-CONTRACT.md, "Binding identity").

The oracle is the interpreter, not the tool: each probe of gen2/tests/source_binding_fixtures.py has a control Python runs in the fixture tree and a verdict written by hand. The unit
tests pin the places the resolver's input is built: which scope a name lives in is the compiler's answer (task 2q-a-repair-6: `symtable`, no rule of the index), a `nonlocal` write is
recorded in the function the compiler says binds the name, an unpacking pairs each name with its own value, and an alias the resolver cannot follow is reported as uncertain.

What this does not show: that a store through a module a CALL returns, a container holds or a parameter receives is refused. That is slice 2 (call-time owner effects); the
positive fixtures that accept such stores prove only that ordinary data processing is not over-refused (gen2/tests/source_closure_fixtures.py, "ordinary_data_stores").
"""
from __future__ import annotations

import unittest

from gen2.tests.source_binding_fixtures import PROBES
from gen2.tests.test_source_closure import ProbeCase, in_the_tools


class BindingTest(ProbeCase):
    def test_each_probe(self) -> None:
        self.check_each_probe(PROBES)


def lines(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def roles(*cases: tuple[str, str]) -> list[dict[str, list[str]]]:
    """For each (source, scope): the roles every name has in that scope (a function or a class by its qualified name, the module by "")."""
    return in_the_tools(f"cases = {list(cases)!r}\nout = []\nfor text, scope in cases:\n    index = si.index_text('gen2/x.py', text)\n"
                        "    found = next(s for s in index.scopes if s.qual == scope and s.kind in ('module', 'function', 'class'))\n"
                        "    out.append({name: [b.role for b in held] for name, held in found.bindings.items()})\nprint(json.dumps(out))")


class NonlocalOwnerTest(unittest.TestCase):
    """The scope a `nonlocal` write is recorded in: Python's rule, decided over the whole body of each function."""

    def test_the_write_skips_a_function_that_does_not_bind_the_name(self) -> None:
        text = lines("def factory():", "    A = 1", "    def middle():", "        def replace():", "            nonlocal A", "            A = 2", "        replace()", "    middle()")
        owner, passed_through = roles((text, "factory"), (text, "factory.middle"))
        self.assertEqual(owner["A"], ["assign", "nonlocal_write"])
        self.assertNotIn("A", passed_through)

    def test_the_write_stops_at_the_nearest_function_that_binds_the_name(self) -> None:
        text = lines("def factory():", "    A = 1", "    def middle():", "        A = 3", "        def replace():", "            nonlocal A", "            A = 2", "        replace()", "    middle()")
        outer, nearest = roles((text, "factory"), (text, "factory.middle"))
        self.assertEqual((outer["A"], nearest["A"]), (["assign"], ["assign", "nonlocal_write"]))

    def test_a_binding_after_the_nested_function_and_a_parameter_still_own_the_write(self) -> None:
        after = lines("def factory():", "    def replace():", "        nonlocal A", "        A = 2", "    A = 1", "    replace()")
        parameter = lines("def factory(A):", "    def replace():", "        nonlocal A", "        A = 2", "    replace()")
        later, param = roles((after, "factory"), (parameter, "factory"))
        self.assertEqual((later["A"], param["A"]), (["assign", "nonlocal_write"], ["param", "nonlocal_write"]))

    def test_a_class_body_between_is_not_an_enclosing_scope(self) -> None:
        text = lines("def factory():", "    A = 1", "    class Holder:", "        A = 2", "        def replace(self):", "            nonlocal A", "            A = 3")
        outer, holder = roles((text, "factory"), (text, "factory.Holder"))
        self.assertEqual((outer["A"], holder["A"]), (["assign", "nonlocal_write"], ["assign"]))

    def test_a_declaration_the_compiler_refuses_refuses_the_file_with_the_compilers_message_and_line(self) -> None:
        text = lines("def outer():", "    def middle():", "        def inner():", "            nonlocal A", "            A = 1", "        inner()", "    middle()")
        said = in_the_tools(f"index = si.index_text('gen2/x.py', {text!r})\nprint(json.dumps([[d.category, d.line, d.construct] for d in index.diagnostics]))")
        self.assertEqual([(category, line) for category, line, _construct in said], [("SRC-INV-PARSE", 4)])
        self.assertIn("no binding for nonlocal 'A' found", said[0][2])

    def test_a_file_the_compiler_refuses_has_no_facts(self) -> None:
        text = lines("def outer():", "    def inner():", "        nonlocal A", "    inner()")
        said = in_the_tools(f"index = si.index_text('gen2/x.py', {text!r})\nprint(json.dumps([len(index.functions), len(index.classes), len(index.scopes), len(index.module.bindings)]))")
        self.assertEqual(said, [0, 0, 1, 0])


def holders(text: str, *uses: tuple[str, str, str]) -> list:
    """For each (kind, qualified name, name): the (kind, qualified name) of the scope that holds what the name means in that scope, or None (a builtin, or a name nothing binds)."""
    return in_the_tools(f"index = si.index_text('gen2/x.py', {text!r})\nout = []\nfor kind, qual, name in {list(uses)!r}:\n    scope = next(s for s in index.scopes if (s.kind, s.qual) == (kind, qual))\n"
                        "    held = si.holder_of(scope, name)\n    out.append(held and [held.kind, held.qual])\nprint(json.dumps(out))")


FACTS = "text = {text!r}\nindex = si.index_text('gen2/x.py', text)\nfacts = si.Facts(pathlib.Path('.'), {{'all': ['gen2/x.py'], 'engine': ['gen2/x.py'], 'gateway': []}}, {{'gen2/x.py': text}}, {{'gen2/x.py': index}})\n"


def identities(text: str, *names: str) -> list:
    """For each name used at the module level: ["found", its dotted identity], or ["unresolved", the category, whether it is an alias the resolver cannot follow]."""
    return in_the_tools(FACTS.format(text=text) + f"out = []\nfor name in {list(names)!r}:\n    try:\n        out.append(['found', facts.identity('gen2/x.py', index.module, ast.parse(name, mode='eval').body)])\n"
                        "    except si.Unresolved as exc:\n        out.append(['unresolved', exc.category, exc.alias])\nprint(json.dumps(out))")


class ScopeTest(unittest.TestCase):
    """Which scope a name lives in is the compiler's answer (`symtable`, through `locate`), never a rule of the index. The oracle is the language: each source is one whose scopes Python
    defines (the interpreter-backed controls are the probes of source_binding_fixtures.py)."""

    def test_a_global_declaration_sends_a_read_to_the_module_and_without_one_a_local_shadow_is_the_functions(self) -> None:
        text = lines("x = 1", "def f():", "    x = 2", "    def g():", "        global x", "        return x", "    def h():", "        return x", "    return g, h")
        self.assertEqual(holders(text, ("function", "f.g", "x"), ("function", "f.h", "x"), ("function", "f", "x")), [["module", ""], ["function", "f"], ["function", "f"]])

    def test_a_free_name_goes_to_the_nearest_function_that_binds_it_through_one_that_does_not_and_never_to_a_class(self) -> None:
        text = lines("def outer():", "    A = 1", "    def middle():", "        A = 2", "        class K:", "            A = 3", "            def r(self):", "                return A", "        return K", "    def passes():",
                     "        def inner():", "            return A", "        return inner", "    return middle, passes")
        self.assertEqual(holders(text, ("function", "outer.middle.K.r", "A"), ("function", "outer.passes.inner", "A"), ("class", "outer.middle.K", "A")),
                         [["function", "outer.middle"], ["function", "outer"], ["class", "outer.middle.K"]])

    def test_a_comprehension_keeps_its_iteration_variable_and_a_walrus_target_is_the_scope_that_writes_it(self) -> None:
        iteration = lines("x = 1", "rows = [x for x in range(2)]")
        walrus = lines("def f():", "    return [(y := 3) for _ in range(2)]")
        self.assertEqual(holders(iteration, ("comprehension", "", "x")), [["comprehension", ""]])
        self.assertEqual(holders(walrus, ("comprehension", "f", "y")), [["function", "f"]])
        self.assertEqual(roles((walrus, "f"))[0]["y"], ["walrus"])

    def test_a_name_only_an_unevaluated_annotation_mentions_is_the_modules(self) -> None:
        text = lines("from __future__ import annotations", "import typing", "def make():", "    class D:", "        v: typing.ClassVar[int] = 0", "    return D")
        self.assertEqual(holders(text, ("function", "make", "typing")), [["module", ""]])

    def test_a_scope_the_compilers_table_does_not_match_is_refused_and_so_is_a_table_no_scope_matches(self) -> None:
        said = in_the_tools("rows = [si.FileIndex('gen2/a.py', ast.parse('f = lambda a: a'), 'f = lambda b: b'), si.FileIndex('gen2/a.py', ast.parse('x = 1'), 'def f(): pass')]\n"
                            "print(json.dumps([[d.construct for d in index.diagnostics] for index in rows]))")
        scope_without_table, table_without_scope = said
        self.assertTrue(any("no matching scope for lambda" in construct for construct in scope_without_table), msg=scope_without_table)
        self.assertTrue(table_without_scope and all("has no scope of the index to match" in construct for construct in table_without_scope), msg=table_without_scope)

    def test_scopes_that_share_a_line_are_told_apart_by_their_parameters_and_iteration_variables(self) -> None:
        """Two lambdas the compiler lists in the other order, and a generator expression inside the first iterable of another (the compiler's table for the inner one comes first)."""
        said = in_the_tools("swapped = si.FileIndex('gen2/a.py', ast.parse('f = (lambda a: a, lambda b: b)'), 'f = (lambda b: b, lambda a: a)')\n"
                            "nested = si.index_text('gen2/a.py', 'ok = all(p for p in [*(g for g in xs)])')\n"
                            "print(json.dumps([[sorted(s.table.get_parameters()) for s in swapped.scopes if s.kind == 'lambda'], [d.construct for d in swapped.diagnostics],\n"
                            "                  [sorted(n for n in s.table.get_identifiers() if n in 'pg') for s in nested.scopes if s.kind == 'comprehension'], [d.construct for d in nested.diagnostics]]))")
        self.assertEqual(said, [[["a"], ["b"]], [], [["p"], ["g"]], []])


class ResolverTest(unittest.TestCase):
    """What the one resolver says of an alias: followed through a chain, unresolved and marked where it cannot be followed, and unmarked where what it cannot follow is data."""

    def test_an_alias_chain_that_ends_in_an_import_is_that_import(self) -> None:
        self.assertEqual(identities("import os.path as p\nq = p\nr = q\n", "r"), [["found", "os.path"]])

    def test_an_alias_of_itself_is_an_unresolved_alias(self) -> None:
        self.assertEqual(identities("a = b\nb = a\n", "a"), [["unresolved", "SRC-DECORATOR-SHADOWED", True]])

    def test_an_alias_of_a_name_whose_bindings_compete_is_an_unresolved_alias_and_the_name_itself_is_not_one(self) -> None:
        text = lines("from importlib import import_module", "loader = import_module", "import_module = len")
        self.assertEqual(identities(text, "loader", "import_module"), [["unresolved", "SRC-DECORATOR-SHADOWED", True], ["unresolved", "SRC-DECORATOR-SHADOWED", False]])

    def test_an_alias_of_a_name_whose_competing_bindings_carry_no_identity_is_no_unresolved_alias(self) -> None:
        self.assertEqual(identities(lines("cb = 1", "for cb in (2, 3):", "    pass", "fn = cb"), "fn"), [["unresolved", "SRC-DECORATOR-SHADOWED", False]])

    def test_a_decorator_written_as_its_qualified_identity_has_that_identity(self) -> None:
        text = lines("import contextlib", "", "@contextlib.contextmanager", "def f():", "    yield")
        said = in_the_tools(FACTS.format(text=text) + "fn = index.functions[0]\nprint(json.dumps(c.decorator_transform(facts, 'gen2/x.py', fn.parent, fn.node.decorator_list[0], 'function').identity))")
        self.assertEqual(said, "contextlib.contextmanager")


def unpacked(text: str) -> dict[str, list]:
    """For each name the module binds: [role, the value it is bound to as text (or None), whether it is the whole target, the alias reference]."""
    return in_the_tools(f"index = si.index_text('gen2/x.py', {text!r})\nprint(json.dumps({{n: [b[0].role, b[0].source and ast.unparse(b[0].source), b[0].direct, list(b[0].ref)] "
                        "for n, b in index.module.bindings.items()}))")


class UnpackingTest(unittest.TestCase):
    """What an assignment's target is bound to: the pairing of a literal unpacking, and nothing else."""

    def test_each_name_takes_the_value_at_its_position_and_a_chain_is_an_alias(self) -> None:
        self.assertEqual(unpacked("a, (b, c) = x, (y.z, 3)\n"), {"a": ["assign", "x", True, ["alias", "x"]], "b": ["assign", "y.z", True, ["alias", "y.z"]], "c": ["assign", "3", True, []]})
        self.assertEqual(unpacked("a, b = (x, y), z\n"), {"a": ["assign", "(x, y)", True, []], "b": ["assign", "z", True, ["alias", "z"]]})

    def test_a_list_pairs_as_a_tuple_does_and_a_swap_pairs_each_name_with_the_other(self) -> None:
        self.assertEqual(unpacked("[a, b] = (x, y)\nc, d = d, c\n"), {"a": ["assign", "x", True, ["alias", "x"]], "b": ["assign", "y", True, ["alias", "y"]],
                                                                       "c": ["assign", "d", True, ["alias", "d"]], "d": ["assign", "c", True, ["alias", "c"]]})

    def test_nothing_is_paired_for_a_starred_element_a_different_count_or_a_value_that_is_no_literal(self) -> None:
        for text in ("a, *b = x, y, z\n", "a, b = x, y, z\n", "a, b = pair\n", "a, b = *x, y\n"):
            with self.subTest(text=text):
                names = unpacked(text)
                self.assertTrue(names and all(fact[2] is False and fact[3] == [] for name, fact in names.items() if name in "ab"), msg=text)

    def test_a_starred_element_on_either_side_pairs_nothing_even_when_the_counts_are_equal(self) -> None:
        for text in ("a, *b = x, y\n", "a, b = *x, y\n"):
            with self.subTest(text=text):
                self.assertTrue(all(fact[2] is False and fact[3] == [] for name, fact in unpacked(text).items() if name in "ab"), msg=text)

    def test_a_loop_target_takes_the_elements_of_what_it_iterates_and_not_the_values_beside_it(self) -> None:
        self.assertEqual(unpacked("for a, b in [x, y]:\n    pass\n"), {"a": ["target", "[x, y]", False, []], "b": ["target", "[x, y]", False, []]})


if __name__ == "__main__":
    unittest.main()
