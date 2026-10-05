"""Mutants of task 2q-a-repair-6 (Astra's 2q-a-repair-5 review F1: scope is the compiler's, and an alias the resolver cannot follow is refused). Each guard is removed or weakened alone.

  2Q6-idx-*  the index (tools/gen2_source_index.py): `locate`, the one rule every use and every write goes through, over the compiler's symbol tables (`symtable`); the pairing of
             each scope with its table; a file the compiler refuses; an ordinary alias whose target the resolver cannot say;
  2Q6-con-*  the contract (tools/gen2_source_contract.py): the consumers that must refuse that alias.

Every killer fails by ASSERTION: a refusal the mutant lets through, a recorded fact or a resolved scope it changes (the interpreter-controlled probes of
gen2/tests/source_binding_fixtures.py among them); none relies on a crash.
"""
from __future__ import annotations

from .base import Mutation
from .metrics_binding import BINDING, NONLOCAL, NL
from .metrics_closure import ALIASES, CON, IDX, SCOPES

SB, RV = "test_source_binding.ScopeTest.", "test_source_binding.ResolverTest."
UNMATCHED = SB + "test_a_scope_the_compilers_table_does_not_match_is_refused_and_so_is_a_table_no_scope_matches"
GLOBAL_READ, FREE_BINDER, COMPREHENSION = (SB + t for t in ("test_a_global_declaration_sends_a_read_to_the_module_and_without_one_a_local_shadow_is_the_functions",
                                                          "test_a_free_name_goes_to_the_nearest_function_that_binds_it_through_one_that_does_not_and_never_to_a_class",
                                                          "test_a_comprehension_keeps_its_iteration_variable_and_a_walrus_target_is_the_scope_that_writes_it"))
COMPILER = (NONLOCAL, NL + "test_a_declaration_the_compiler_refuses_refuses_the_file_with_the_compilers_message_and_line")


def m(mid: str, description: str, killers: tuple[str, ...], target: str, old: str, new: str) -> Mutation:
    return Mutation(f"2Q6-{mid}", "2q-a-repair-6", description, killers, target=target, old=old, new=new)


GLOBAL_LINE = "    if symbol is None or symbol.is_global():\n        return module_of(here)"
NEAREST = '(found := outer.symbol(name)) is not None and found.is_local())]'

MUTATIONS: list[Mutation] = [
    # --- locate: local, global, free, as the compiler's table says ----------------------------------------------------------------------------
    m("idx-scope-ignores-global", "a name the compiler declared global is read as the scope's own (the hand rule Astra's global-read probes defeat)", (BINDING, GLOBAL_READ), IDX,
      GLOBAL_LINE, "    if symbol is None or (symbol.is_global() and not symbol.is_declared_global()):\n        return module_of(here)"),
    m("idx-free-name-is-local", "a free name is read as the scope's own", (BINDING, FREE_BINDER, NONLOCAL), IDX, "    if not symbol.is_free():   # a declared `nonlocal` is free too", "    if True:"),
    m("idx-free-binder-is-the-nearest-scope", "a free name belongs to the nearest enclosing function that merely mentions it", (BINDING, FREE_BINDER, NL + "test_the_write_skips_a_function_that_does_not_bind_the_name"), IDX,
      NEAREST, "(found := outer.symbol(name)) is not None)]"),
    m("idx-free-binder-is-the-outermost", "a free name belongs to the outermost enclosing function that binds it", (FREE_BINDER, NL + "test_the_write_stops_at_the_nearest_function_that_binds_the_name", SCOPES), IDX,
      "    return binders[0] if binders else module_of(here)", "    return binders[-1] if binders else module_of(here)"),
    m("idx-free-search-enters-a-class", "a class body that binds the name is the enclosing binder of a free name", (FREE_BINDER, NL + "test_a_class_body_between_is_not_an_enclosing_scope"), IDX,
      '[outer for outer in enclosing(here) if outer.kind != "class" and (', "[outer for outer in enclosing(here) if ("),
    m("idx-absent-name-is-local", "a name the table does not hold (only an unevaluated annotation mentions it) is the scope's own", (SB + "test_a_name_only_an_unevaluated_annotation_mentions_is_the_modules",), IDX,
      GLOBAL_LINE, "    if symbol is None:\n        return here\n    if symbol.is_global():\n        return module_of(here)"),
    m("idx-comprehension-variable-escapes", "a comprehension's iteration variable is read in the scope that holds the comprehension", (COMPREHENSION, SCOPES), IDX,
      "        if name in here.bindings:\n            return here\n        here = here.parent", "        here = here.parent"),
    m("idx-comprehension-target-binds-outside", "a comprehension's iteration variable is bound where the compiler's table puts a name of the scope that holds it", (SCOPES,), IDX,
      '        owner = scope if scope.kind == "comprehension" and role == "target" else locate(scope, name)', "        owner = locate(scope, name)"),
    # --- each scope is paired with the compiler's table for it, or the file is refused ---------------------------------------------------------
    m("idx-table-mismatch-accepted", "a scope with no matching table of the compiler is accepted", (UNMATCHED,), IDX,
      '            self.diagnose("SRC-FORM-UNRECOGNISED", node.lineno, f"the compiler\'s symbol table has no matching scope for {scope.kind} {name} at this line", MISMATCH)', "            pass"),
    m("idx-leftover-table-accepted", "a table of the compiler that no scope of the index matches is accepted", (UNMATCHED,), IDX,
      '                    self.diagnose("SRC-FORM-UNRECOGNISED", table.get_lineno(), f"the compiler\'s table for {table.get_name()} has no scope of the index to match", MISMATCH)', "                    pass"),
    m("idx-header-names-unchecked", "scopes that share a line are paired in the compiler's order without checking their parameters or iteration variables",
      (SB + "test_scopes_that_share_a_line_are_told_apart_by_their_parameters_and_iteration_variables", UNMATCHED), IDX,
      "        table = next((t for t in found if names <= {s.get_name() for s in t.get_symbols() if s.is_parameter() or s.is_assigned()}), None)", "        table = next(iter(found), None)"),
    # --- a file the compiler refuses has no facts and is refused with the compiler's message ----------------------------------------------------
    m("idx-compiler-refusal-unreported", "a file the compiler's symbol table refuses (an invalid `nonlocal`) is swallowed, with no facts and no refusal", COMPILER, IDX,
      '            self.diagnostics.append(Diagnostic("SRC-INV-PARSE", path, exc.lineno or 0, f"the compiler refuses the file: {exc.msg}", "fix the source: Python itself will not run it"))', "            pass"),
    # --- an alias the resolver cannot follow is refused, not accepted -------------------------------------------------------------------------
    m("con-unresolved-alias-accepted", "a call through an alias of a rebound name is read as no recognised site", (BINDING,), CON, '        if exc.alias:\n            self.refuse("SRC-BINDING-COMPETING"', '        if False:\n            self.refuse("SRC-BINDING-COMPETING"'),
    m("con-field-marker-uncertainty-ignored", "a dataclass field marker that is an alias of a rebound name is read as a field", (ALIASES,), CON, "            self.uncertain(cls.path, node, exc)\n            return False", "            return False"),
    m("idx-alias-uncertainty-unmarked", "an alias of a name whose bindings compete is reported as an ordinary unresolved name", (BINDING, RV + "test_an_alias_of_a_name_whose_bindings_compete_is_an_unresolved_alias_and_the_name_itself_is_not_one"), IDX,
      '{exc.why}", alias=True) from None', '{exc.why}", alias=False) from None'),
    m("idx-competing-bindings-carry-no-identity", "a name whose competing bindings include an import is read as carrying none", (BINDING, RV + "test_an_alias_of_a_name_whose_bindings_compete_is_an_unresolved_alias_and_the_name_itself_is_not_one"), IDX,
      '                             identity=any(b.role in ("import", "from", "class", "def") or b.ref[:1] == ("alias",) for b in bindings))', "                             identity=False)"),
    m("idx-alias-of-data-is-unresolved", "an alias of a name whose competing bindings are all data is an unresolved alias too", (RV + "test_an_alias_of_a_name_whose_competing_bindings_carry_no_identity_is_no_unresolved_alias", SCOPES), IDX,
      '                if exc.category != "SRC-BINDING-COMPETING" or exc.alias or not exc.identity:', '                if exc.category != "SRC-BINDING-COMPETING" or exc.alias:'),
]
