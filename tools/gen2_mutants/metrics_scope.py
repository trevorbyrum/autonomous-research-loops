"""Mutants of task 2q-a-repair-6 (Astra's 2q-a-repair-5 review F1: scope is the compiler's, and an alias the resolver cannot follow is refused) and of task 2q-a-repair-6b (her
2q-a-repair-6 review R6-1 and R6-2: the pairing follows the compiler's order and is checked both ways, and a private name is the compiler's mangled one). Each guard is removed or weakened alone.

  2Q6-idx-*   the index (tools/gen2_source_index.py): `locate`, the one rule every use and every write goes through, over the compiler's symbol tables (`symtable`); the pairing of
              each scope with its table; a file the compiler refuses; an ordinary alias whose target the resolver cannot say;
  2Q6-con-*   the contract (tools/gen2_source_contract.py): the consumers that must refuse that alias;
  2Q6B-idx-*  the order the pairing follows (`entered` and what a scope's header reads first), its validation in each direction, the mangling, and a binding the table has no symbol for.

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
PAIRING, MN = "test_source_binding.PairingTest.", "test_source_binding.MangleTest."
ORDER = (PAIRING + "test_a_generator_in_the_first_iterable_of_another_is_entered_first_and_the_walrus_belongs_to_the_outer_one",
         PAIRING + "test_every_scope_the_compiler_enters_in_its_order_gets_its_own_table_and_none_is_refused")
MANGLING = (BINDING, MN + "test_the_language_rule", MN + "test_a_private_name_is_looked_up_as_the_compiler_holds_it_in_every_scope_of_the_class")


def m(mid: str, description: str, killers: tuple[str, ...], target: str, old: str, new: str) -> Mutation:
    return Mutation(f"2Q6-{mid}", "2q-a-repair-6", description, killers, target=target, old=old, new=new)


def b(mid: str, description: str, killers: tuple[str, ...], target: str, old: str, new: str) -> Mutation:
    return Mutation(f"2Q6B-{mid}", "2q-a-repair-6b", description, killers, target=target, old=old, new=new)


GLOBAL_LINE = "        if symbol.is_global():\n            return module_of(here)"
NEAREST = '(found := outer.symbol(spelled)) is not None and found.is_local())]'

MUTATIONS: list[Mutation] = [
    # --- locate: local, global, free, as the compiler's table says ----------------------------------------------------------------------------
    m("idx-scope-ignores-global", "a name the compiler declared global is read as the scope's own (the hand rule Astra's global-read probes defeat)", (BINDING, GLOBAL_READ), IDX,
      GLOBAL_LINE, "        if symbol.is_global() and not symbol.is_declared_global():\n            return module_of(here)"),
    m("idx-free-name-is-local", "a free name is read as the scope's own", (BINDING, FREE_BINDER, NONLOCAL), IDX, "        if not symbol.is_free():   # a declared `nonlocal` is free too", "        if True:"),
    m("idx-free-binder-is-the-nearest-scope", "a free name belongs to the nearest enclosing function that merely mentions it", (BINDING, FREE_BINDER, NL + "test_the_write_skips_a_function_that_does_not_bind_the_name"), IDX,
      NEAREST, "(found := outer.symbol(name)) is not None)]"),
    m("idx-free-binder-is-the-outermost", "a free name belongs to the outermost enclosing function that binds it", (FREE_BINDER, NL + "test_the_write_stops_at_the_nearest_function_that_binds_the_name", SCOPES), IDX,
      "    return binders[0] if binders else module_of(here)", "    return binders[-1] if binders else module_of(here)"),
    m("idx-free-search-enters-a-class", "a class body that binds the name is the enclosing binder of a free name", (FREE_BINDER, NL + "test_a_class_body_between_is_not_an_enclosing_scope"), IDX,
      '[outer for outer in enclosing(here) if outer.kind != "class" and (', "[outer for outer in enclosing(here) if ("),
    m("idx-absent-name-is-local", "a name only an unevaluated annotation writes in the scope is the scope's own", (SB + "test_a_name_only_an_unevaluated_annotation_mentions_is_the_modules",), IDX,
      "    if symbol is None and spelled in here.hidden:\n        return module_of(here)", "    if symbol is None and spelled in here.hidden:\n        return here"),
    m("idx-comprehension-variable-escapes", "a comprehension's iteration variable is read in the scope that holds the comprehension", (COMPREHENSION, SCOPES), IDX,
      "        if name in here.bindings:\n            return here\n        here = here.parent", "        here = here.parent"),
    m("idx-comprehension-target-binds-outside", "a comprehension's iteration variable is bound where the compiler's table puts a name of the scope that holds it", (SCOPES,), IDX,
      '            owner = scope if role == "star" or (scope.kind == "comprehension" and role == "target") else locate(scope, name, bound=True)', "            owner = locate(scope, name, bound=True)"),
    # --- each scope is paired with the compiler's table for it, or the file is refused ---------------------------------------------------------
    m("idx-table-mismatch-accepted", "a scope with no matching table of the compiler is accepted", (UNMATCHED,), IDX,
      '                self.unpaired.append((node.lineno, f"the compiler\'s symbol table has no matching scope for {scope_kind(node)} {TABLE_NAMES.get(type(node)) or node.name} at this line", MISMATCH))', "                pass"),
    m("idx-leftover-table-accepted", "a table of the compiler that no scope of the index matches is accepted", (UNMATCHED,), IDX,
      '                self.unpaired.append((child.get_lineno(), f"the compiler\'s table for {child.get_name()} has no scope of the index to match", MISMATCH))', "                pass"),
    # --- the pairing follows the compiler's order (R6-1) and is checked both ways ------------------------------------------------------------------
    b("idx-pairing-unvalidated", "every scope is given the table the order says, and nothing checks that the names the tree writes in it are the table's", (PAIRING + "test_a_pairing_the_tree_and_the_table_disagree_about_is_refused_both_ways",), IDX,
      "            self.validate()", "            pass"),
    b("idx-validation-ignores-the-trees-names", "a name the tree writes in a scope that its table lacks is accepted", (PAIRING + "test_a_pairing_the_tree_and_the_table_disagree_about_is_refused_both_ways",), IDX,
      "            lacking = sorted(n for n in written - held if not internal(n))", "            lacking = []"),
    b("idx-validation-ignores-the-tables-names", "a name the table holds that the tree does not write in the scope is accepted", (PAIRING + "test_a_pairing_the_tree_and_the_table_disagree_about_is_refused_both_ways",), IDX,
      "            extra = sorted(n for n in held - written if not internal(n) and not (n in scope.below and table.lookup(n).is_free()))", "            extra = []"),
    b("idx-first-iterable-is-read-inside", "a comprehension's first iterable is entered after the comprehension (the walker's order, not the compiler's: Astra's R6-1)", ORDER, IDX,
      "            yield from entered(before(node, future), future)\n            yield node", "            yield node\n            yield from entered(before(node, future), future)"),
    b("idx-dict-comprehension-key-first", "a dictionary comprehension reads its key before its value", ORDER[1:], IDX,
      "((node.value, node.key) if isinstance(node, ast.DictComp) else (node.elt,))", "((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,))"),
    b("idx-try-fields-in-tree-order", "a try statement is read body, handlers, else, finally", ORDER[1:], IDX,
      'READ_ORDER = {ast.Try: ("body", "orelse", "handlers", "finalbody"), ast.TryStar: ("body", "orelse", "handlers", "finalbody")}', 'READ_ORDER = {}'),
    b("idx-decorators-after-annotations", "a function's annotations are read before its decorators", ORDER[1:], IDX,
      '    return [*args.defaults, *args.kw_defaults, *getattr(node, "decorator_list", ()), *notes]', '    return [*args.defaults, *args.kw_defaults, *notes, *getattr(node, "decorator_list", ())]'),
    b("idx-annotations-in-tree-order", "a function's keyword-only annotations are read before `*args` and `**kwargs`", ORDER[1:], IDX,
      "(*args.posonlyargs, *args.args, args.vararg, args.kwarg, *args.kwonlyargs)", "(*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)"),
    b("idx-annotation-names-are-demanded", "a name only an unevaluated annotation writes is one the table must hold", (SB + "test_a_name_only_an_unevaluated_annotation_writes_is_no_name_the_table_must_hold_and_a_lambda_in_one_is_refused",), IDX,
      "        (scope.hidden if self.hidden else scope.mentioned).add(mangle(scope.private, name))", "        scope.mentioned.add(mangle(scope.private, name))"),
    # --- a private name is the compiler's mangled one (R6-2), and a name the table lacks is never a global ---------------------------------------
    b("idx-mangling-skipped", "a private name is looked up and compared as written, not as the compiler mangles it", MANGLING, IDX,
      '    return f"_{stripped}{name}"', "    return name"),
    b("idx-private-spellings-kept-apart", "`__h` and `_C__h` are two names in class C", (BINDING,), IDX,
      "            spellings.setdefault(mangle(scope.private, name), (name, []))[1].extend(bindings)", "            spellings.setdefault(name, (name, []))[1].extend(bindings)"),
    b("idx-global-write-keeps-the-written-name", "a `global __g` written in a class is a binding of the module's own `__g`", (MN + "test_a_global_a_class_declares_is_the_modules_name_as_the_compiler_mangles_it",), IDX,
      "                owner.bind(mangle(scope.private, name), binding)", "                owner.bind(name, binding)"),
    b("idx-missing-symbol-is-global", "a binding written for a name the table does not hold is the module's", (MN + "test_a_binding_the_table_has_no_symbol_for_is_refused_and_is_never_the_modules",), IDX,
      "    if symbol is None and bound:", "    if False:"),
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
