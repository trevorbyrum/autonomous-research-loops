"""Mutants of task 2q-a-repair-5 (Astra's 2q-a-repair-4 review F1, slice 1: binding identity): the nonlocal write's owner, the pairing of an unpacking, and the consumers that
must ask the one resolver. Each guard is removed or weakened alone.

  2QB-idx-*  the index (tools/gen2_source_index.py): what an unpacking binds, an alias that is its own identity (which function a `nonlocal` write belongs to was a family of this file
             until task 2q-a-repair-6 made it the compiler's answer: the 2Q6-idx-free-* mutants);
  2QB-con-*  the contract (tools/gen2_source_contract.py): a consumer that reads a spelling where the resolver gives an identity, a base that follows an assignment.

Every killer fails by ASSERTION on a refusal the mutant lets through or a recorded fact it changes (the interpreter-controlled probes of gen2/tests/source_binding_fixtures.py
among them); none relies on a crash. A mutant whose removal of a guard would crash the tool (the resolver's refusal of a class outside the inventory: AttributeError) has no
mutant: a crash is an error, and an error is no kill.
"""
from __future__ import annotations

from .base import Mutation
from .metrics_closure import ALIASES, CLR, CLA, CON, IDX, SCOPES

NONLOCAL, BINDING = CLR + "nonlocal_and_global_inside_closures", "test_source_binding.BindingTest.test_each_probe"
NL, UP = "test_source_binding.NonlocalOwnerTest.", "test_source_binding.UnpackingTest."
OWNER = "test_locators.QualifiedScopeTest.test_an_owner_is_judged_by_the_identity_of_its_decorator_and_not_by_its_spelling"
BASE_ALIAS = "test_source_contract.RefusalTest.test_refuses_src_base_alias"


def b(mid: str, description: str, killers: tuple[str, ...], target: str, old: str, new: str) -> Mutation:
    return Mutation(f"2QB-{mid}", "2q-a-repair-5", description, killers, target=target, old=old, new=new)


MUTATIONS: list[Mutation] = [
    # --- a `nonlocal` write belongs to the enclosing function the compiler says binds the name: the mutants of that rule are the 2Q6-idx-free-* ones (tools/gen2_mutants/metrics_scope.py) -----
    # --- an unpacking pairs each name with its own value --------------------------------------------------------------------------------------
    b("idx-unpacking-binds-no-value", "no name of an unpacking is bound to its value", (BINDING, ALIASES, UP + "test_each_name_takes_the_value_at_its_position_and_a_chain_is_an_alias"),
      IDX, "    return None if any(isinstance(e, ast.Starred) for e in (*node.elts, *source.elts)) else source.elts", "    return None"),
    b("idx-unpacking-binds-every-name-to-the-first-value", "every name of an unpacking is bound to the first value", (BINDING, UP + "test_each_name_takes_the_value_at_its_position_and_a_chain_is_an_alias"),
      IDX, "zip(node.elts, values)", "zip(node.elts, values[:1] * len(node.elts))"),
    b("idx-unpacking-pairs-a-loop-target", "a loop's target is paired with the values beside it", (UP + "test_a_loop_target_takes_the_elements_of_what_it_iterates_and_not_the_values_beside_it",),
      IDX, 'if target.role != "assign" or not isinstance(node, (ast.Tuple, ast.List))', "if not isinstance(node, (ast.Tuple, ast.List))"),
    b("idx-unpacking-pairs-a-starred-value", "a literal with a starred element is paired by position", (UP + "test_nothing_is_paired_for_a_starred_element_a_different_count_or_a_value_that_is_no_literal",),
      IDX, "    return None if any(isinstance(e, ast.Starred) for e in (*node.elts, *source.elts)) else source.elts", "    return source.elts"),
    b("idx-unpacking-pairs-a-different-count", "a literal of another length is paired as far as it goes", (UP + "test_nothing_is_paired_for_a_starred_element_a_different_count_or_a_value_that_is_no_literal",),
      IDX, " or len(node.elts) != len(source.elts):", ":"),
    # --- an alias that is its own identity has none ------------------------------------------------------------------------------------------
    b("idx-alias-cycle-is-external", "an alias of itself is read as an external name instead of being refused", (ALIASES,), IDX,
      '                raise Unresolved("SRC-BINDING-COMPETING", f"{name} is an alias of itself", alias=True)', '                return ("external", name)'),
    # --- every consumer asks the one resolver --------------------------------------------------------------------------------------------------
    b("con-decorator-identity-is-its-spelling", "a decorator is recognised by how it is written, not by the identity the resolver gives it", (SCOPES, OWNER, CLA + "implicit_and_generated_members"), CON,
      "    identity = facts.identity(path, scope, target)", "    identity = ast.unparse(target)"),
    b("con-call-identity-is-its-spelling", "a loader, setattr or sys.modules is recognised by how it is written, not by the identity the resolver gives it", (ALIASES, BINDING), CON,
      "            return self.facts.identity(index.path, scope, node)\n        except Unresolved as exc:", "            return source.chain_text(node)\n        except Unresolved as exc:"),
    b("con-base-follows-an-assignment", "a base bound by an assignment is followed to what it aliases and accepted", (BASE_ALIAS,), CON,
      '                ref = self.facts.expr(path, cls.parent, node, assignments=False)\n            if ref[0] in ("module", "package"):', '                ref = self.facts.expr(path, cls.parent, node)\n            if ref[0] in ("module", "package"):'),
]
