"""Mutants of task 2q-t1 (the 2q tooling slice: DEBT-018, DEBT-017 and DEBT-016). Each guard is removed or weakened alone, and each refusal has an over-restriction beside it.

  2QT1-ban-*         the `builtins` module is a banned name (Astra's 2q-a-repair-7 R7-1): the name, `__builtins__`, and each as an attribute of anything;
  2QT1-exception-*   each excepted statement's whole enclosing function is pinned (R7-2): the pin, its signature and decorators, and the receiver the excepted write needs;
  2QT1-decorator-*   two recorded transformations on one function are refused (DEBT-016 item 2);
  2QT1-idx-*         the parenthesised annotated name `(x): int` declares nothing (DEBT-017 item 1).

Every killer fails by ASSERTION: a refusal fixture or interpreter-backed probe the mutant lets through, or a positive fixture it refuses (the real production functions in the pinned fixtures, the
two-function `re` control, the decorated methods the contract records). The mutants that change what the function form reads change the recorded fingerprints with them (`also`), so the real tree is
accepted and only the property under test changes.
"""
from __future__ import annotations

from .base import Mutation
from .metrics_2q7 import ATTRIBUTES, BANNED, banned

CON, IDX = "tools/gen2_source_contract.py", "tools/gen2_source_index.py"
BM, EX = "test_source_mechanisms.BannedMechanismTest.test_refuses_", "test_source_mechanisms.ExceptionTest."
BUILTINS = "test_source_mechanisms.BuiltinsModuleTest."
PINNED = EX + "test_the_function_an_exception_is_in_is_pinned_whole_a_changed_receiver_a_static_or_class_method_and_any_edit_are_refused"
NO_METHOD = EX + "test_an_excepted_write_in_a_function_that_is_no_method_of_a_class_is_refused"
CHANGED = EX + "test_a_changed_statement_is_refused_and_so_is_a_second_copy_and_another_reference_in_the_same_function"
DECORATED = "test_source_contract.AcceptanceTest.test_accepts_decorators_and_descriptors"
UNKNOWN = "test_source_contract.RefusalTest.test_refuses_src_decorator_unknown"
COMPOSITION = "test_source_mechanisms.CompositionTest.test_a_property_over_a_classmethod_is_a_property_whose_getter_is_not_callable_and_the_stack_is_refused_in_both_services"
PARENTHESISED = "test_source_closure.ClosureAcceptanceTest.test_a_parenthesised_annotated_name_binds_nothing_and_python_agrees"
BINDS_DATA = "test_source_closure.ClosureAcceptanceTest.test_accepts_class_bodies_that_bind_data"

# the recorded fingerprints (tools/gen2_source_contract.py EXCEPTIONS and LOADERS) of the variants of `function_form` that ignore the signature or the decorators
LOAD_ALL, HOLD, SEALED, PASSIVE = ("0c3248cd031cc6d8417aed3f9e2e1b109712cb7095a9151ba0dd96d4d7922041", "9c337856399195bdbed662c27f5ec0655259c020be086726f832993ce206a70a",
                                   "aeb7cdbb25ebb07ad825cb3231a53b6b8b74ce69fac1b7ea98855875883ba906", "0ac2a3258a5a1117be0c43598427255f4297f6c6b846b77fe07f97a8da6d7443")
LOADER = "d92736324e8162a92f838d37cfc5f55df496ae08374f1b1627857558522ff842"
FORM = 'for name in node._fields}, "body"'


def t(mid: str, description: str, killers: tuple[str, ...], old: str, new: str, *, target: str = CON, also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2QT1-{mid}", "2q-t1", description, killers, target=target, old=old, new=new, also=also)


def ban_without(mid: str, description: str, killers: tuple[str, ...], names: str = "", attributes: str = "") -> Mutation:
    """`BANNED` without `names`, or `BANNED_ATTRIBUTES` without `attributes` (the builtins entries are the last two of each)."""
    old, new = (f"BANNED = {BANNED}", banned(names)[1]) if names else (f"BANNED_ATTRIBUTES = {ATTRIBUTES}", "")
    if attributes:
        new = old
        for name in attributes.split(","):
            new = new.replace(f', "{name}"', "", 1)
    return t(mid, description, killers, old, new)


MUTATIONS: list[Mutation] = [
    # --- the `builtins` module is a banned name (R7-1) -------------------------------------------------------------------------------------------------------------
    ban_without("ban-builtins-unreferenced", "a reference to the builtins module (an import, a name) is accepted", (BM + "builtins_module", BUILTINS + "test_astras_r7_1_sources_change_a_class_in_the_interpreter_and_are_refused_in_both_services"),
                names="builtins"),
    ban_without("ban-dunder-builtins-unreferenced", "a reference to `__builtins__` is accepted", (BM + "code_execution",), names="__builtins__"),
    ban_without("ban-builtins-attribute-unreferenced", "the builtins module reached as an attribute of anything (`helpers.builtins`) is accepted",
                (BM + "builtins_module", BUILTINS + "test_astras_r7_1_sources_change_a_class_in_the_interpreter_and_are_refused_in_both_services"), attributes="builtins"),
    ban_without("ban-dunder-builtins-attribute-unreferenced", "`__builtins__` reached as an attribute of anything is accepted", (BM + "builtins_module",), attributes="__builtins__"),
    t("ban-banned-names-are-banned-as-attributes", "every banned name is banned as an attribute too, so `re.compile` and `b.compile` are references to the built-in `compile`",
      (BUILTINS + "test_a_builtins_alias_in_one_function_refuses_that_reference_and_not_another_functions_alias_of_re",),
      "        return [node.attr] if node.attr in BANNED_ATTRIBUTES else []", "        return [node.attr] if node.attr in (*BANNED_ATTRIBUTES, *BANNED) else []"),
    # --- each excepted statement's whole enclosing function is pinned (R7-2) ------------------------------------------------------------------------------------------
    t("exception-function-unpinned", "an excepted statement is excepted in any function that holds it, whatever the rest of the function says", (PINNED, CHANGED),
      "                elif site.function and pins[qual] != {site.fingerprint}:", "                elif False:"),
    t("exception-function-pin-ignores-the-signature", "the pin of an excepted function does not read its signature (a changed receiver parameter is accepted); the recorded fingerprints are those of this variant",
      (PINNED,), FORM, 'for name in node._fields if name != "args"}, "body"',
      also=((LOAD_ALL, "d9dd448e0119b66e9f9370b7a5cd84f17e5bc9cbecbe8691f22017f7cadc4b2b"), (HOLD, "5bf50a10511091c620541065e104db5dd09b28b77051157f3663f4349135c8a4"),
            (SEALED, "6d69c84931d6a8deecaae12774247a270e4ab8569ae3d9a9f9f2f6fdbe803c77"), (PASSIVE, "6d69c84931d6a8deecaae12774247a270e4ab8569ae3d9a9f9f2f6fdbe803c77"),
            (LOADER, "610d87d12f0e9b48438d5040d97db3fcfbde939c545c957c48f1100d2201ee5b"))),
    t("exception-function-pin-ignores-the-decorators", "the pin of an excepted function does not read its decorators (a staticmethod or classmethod is accepted); the recorded fingerprint is that of this variant",
      (PINNED,), FORM, 'for name in node._fields if name != "decorator_list"}, "body"', also=((HOLD, "e83e3460a12c58d4da567ca1ef015fc693e1017d6cd710c9573e6a3628ee65e3"),)),
    t("exception-write-needs-no-receiver", "an excepted write in a function that is no method of a class is accepted",
      (NO_METHOD,), "        if not context:\n            self.refuse(", "        if not context:\n            (lambda *a: None)("),
    # --- two recorded transformations on one function (DEBT-016 item 2) -----------------------------------------------------------------------------------------------
    t("decorator-composition-accepted", "two recorded transformations on one function are accepted, the last one's role winning", (UNKNOWN, COMPOSITION),
      "        if len(fn.transforms) > 1:", "        if False:"),
    t("decorator-any-transformation-is-a-composition", "a function with one recorded transformation is refused as a composition", (DECORATED,),
      "        if len(fn.transforms) > 1:", "        if len(fn.transforms) > 0:", also=(("fn.node.decorator_list[1].lineno", "fn.node.decorator_list[0].lineno"),)),
    # --- `(x): int` declares nothing (DEBT-017 item 1) ------------------------------------------------------------------------------------------------------------------
    t("idx-parenthesised-annotation-is-a-binding", "`(x): int` binds x, which the compiler's table does not hold: the pairing refuses it", (PARENTHESISED, BINDS_DATA),
      "        if node.value is None and not (isinstance(node.target, ast.Name) and node.simple):", "        if node.value is None and not isinstance(node.target, ast.Name):", target=IDX),
    t("idx-annotation-alone-binds-nothing", "a simple annotation with no value (`x: int` in a class body) declares nothing either", (BINDS_DATA, "test_source_closure.ClosureAcceptanceTest.test_accepts_implicit_and_generated_members"),
      "        if node.value is None and not (isinstance(node.target, ast.Name) and node.simple):", "        if node.value is None:", target=IDX),
]
