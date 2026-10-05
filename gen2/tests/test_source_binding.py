"""Binding identity (task 2q-a-repair-5, slice 1 of the F1 repair; Astra's 2q-a-repair-4 review F1): one resolver says which class, function, module or external object a name is, and
every consumer asks it (docs/gen2/SOURCE-CONTRACT.md, "Binding identity").

The oracle is the interpreter, not the tool: each probe of gen2/tests/source_binding_fixtures.py has a control Python runs in the fixture tree and a verdict written by hand. The unit
tests pin the two places the resolver's input is built: a `nonlocal` write is recorded in the function that binds the name, and an unpacking pairs each name with its own value.

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

    def test_a_name_no_enclosing_function_binds_is_refused_and_another_nonlocal_write_does_not_bind_it(self) -> None:
        text = lines("def outer():", "    def middle():", "        def inner():", "            nonlocal A", "            A = 1", "        nonlocal A", "        A = 2", "    middle()")
        said = in_the_tools(f"index = si.index_text('gen2/x.py', {text!r})\nprint(json.dumps([[d.category, d.line, d.construct] for d in index.diagnostics]))")
        self.assertEqual(sorted(line for _category, line, _construct in said), [5, 7])
        self.assertEqual({category for category, _line, _construct in said}, {"SRC-FORM-UNRECOGNISED"})
        self.assertTrue(all("names no binding of an enclosing function" in construct for _category, _line, construct in said))


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

    def test_a_loop_target_takes_the_elements_of_what_it_iterates_and_not_the_values_beside_it(self) -> None:
        self.assertEqual(unpacked("for a, b in [x, y]:\n    pass\n"), {"a": ["target", "[x, y]", False, []], "b": ["target", "[x, y]", False, []]})


if __name__ == "__main__":
    unittest.main()
