"""Mutants of task 2q-a-repair-4 (Astra's 2q-a-repair-3 review F1-F4): the closure of the supported-source contract (positive recognition), the effective-member model, the
external precedence through ancestors, the loader's fingerprint, and the completion witness and the verdict that lets incomplete execution dominate. Each guard is removed or
weakened alone.

  2QC-idx-*     the walker (tools/gen2_source_index.py): the one dispatcher over syntax nodes, the positions of a header, the scopes, the aliases, the order;
  2QC-con-*     the contract (tools/gen2_source_contract.py): the dispatchers of class-body bindings and of stores, what an expression denotes, `__all__`, the effective members,
                the order of external classes, the loader's fingerprint;
  2QC-met-*     the metrics commands (tools/gen2_metrics.py): attribution by effective member, the partial and not-certified report;
  2QC-run-*     the completion witness (gen2/tests/tool_repo_fixtures.py);
  2QC-harness-* the harness's verdict (tools/gen2_mutations.py, loaded by test_mutation_verdict from a path the harness points at the mutated copy).

Every killer fails by ASSERTION on a source refusal fixture the mutant lets through (or refuses wrongly), on a recorded member the mutant changes, on a verdict the mutant
reverses; none relies on a crash (a tool that dies is an error, and an error is no kill: task 2q-a-repair-4, F4).
"""
from __future__ import annotations

from .base import Mutation

IDX, CON, MET, FIX, HAR = ("tools/gen2_source_index.py", "tools/gen2_source_contract.py", "tools/gen2_metrics.py", "gen2/tests/tool_repo_fixtures.py", "tools/gen2_mutations.py")
CLR, CLA = "test_source_closure.ClosureRefusalTest.test_refuses_", "test_source_closure.ClosureAcceptanceTest.test_accepts_"
WU, PR, EM, LB, TB = (f"test_source_closure.{c}." for c in ("WalkerUnitTest", "ProbeTest", "EffectiveMemberTest", "LoaderBoundaryTest", "TableTest"))
EC, WT, MV = "test_source_contract.EveryCommandTest.", "test_tool_completion.WitnessTest.", "test_mutation_verdict.MixedSubtestTest."
WALRUS, GLOBAL, HOOKS, ALIAS = (CLR + f for f in ("walrus_in_every_header_and_expression_position", "global_redirect_of_every_kind_of_binding", "hooks_bound_by_any_statement",
                                                    "method_aliases_by_any_statement"))
FORMS, BODY = CLR + "unrecognised_forms", CLR + "class_body_bindings_of_every_kind"
MODS, CLASSES = CLR + "stores_on_modules_and_packages", CLR + "stores_on_classes_through_names"
ALL, EXTERNAL, ALIASES, DATACLASS = (CLR + f for f in ("all_not_only_mutated_but_passed_on", "external_classes_through_ancestors", "aliases_carry_the_identity", "dataclass_forms_the_record_does_not_allow"))
DATA, BODIES, MEMBERS, AFTER, SCOPES = (CLA + f for f in ("ordinary_data_stores", "class_bodies_that_bind_data", "implicit_and_generated_members",
                                                          "external_classes_after_every_project_class", "aliases_and_scopes"))


def c(mid: str, description: str, killers: tuple[str, ...], target: str, old: str, new: str, also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2QC-{mid}", "2q-a-repair-4", description, killers, target=target, old=old, new=new, also=also)


HEADER = "        self.each((*node.decorator_list, *args.defaults, *args.kw_defaults), scope, nested)"   # the decorators and defaults; the annotations are walked on the next line (task 2q-a-repair-6b)
NOTES = "        self.annotations((*(a.annotation for a in every), node.returns), scope, nested)"
CLASS_HEADER = "        self.each((*node.decorator_list, *node.bases, *(k.value for k in node.keywords)), scope, nested)"
FINGERPRINT = "d92736324e8162a92f838d37cfc5f55df496ae08374f1b1627857558522ff842"   # the recorded fingerprint of the real loader (tools/gen2_source_contract.py LOADERS)
# `function_form` is the one form the loader's fingerprint and an excepted function's (EXCEPTIONS, task 2q-t1) both read: under the variant that keeps docstrings the two excepted functions that have one
# (`load_all`, `Job.hold`) have the recorded fingerprints below, so the mutant changes what a docstring edit is and nothing about the real tree
EXCEPTION_FINGERPRINTS_WITH_DOCSTRINGS = (("0c3248cd031cc6d8417aed3f9e2e1b109712cb7095a9151ba0dd96d4d7922041", "8c9c903c0cf95f90bc32d058e2e0bcc544fa3310a1855ab4eb8eeee60b5e93eb"),
                                          ("9c337856399195bdbed662c27f5ec0655259c020be086726f832993ce206a70a", "28d08c246131368d2bf98e2ae99b0426f9b49edec1211562f2cfabe4ea72ba7b"))
STORE_FORMS = '    STORE_FORMS = {"receiver": "store_receiver", "data": "store_data", "class": "store_namespace", "namespace": "store_namespace"}'

MUTATIONS: list[Mutation] = [
    # --- the walker: one dispatcher, every position of a header visited, scopes, aliases, the order ------------------------------------------------
    c("idx-unrecognised-node-read-as-harmless", "a syntax node class with no entry in the table is walked as an ordinary one", (WU + "test_a_node_class_the_table_has_no_entry_for_is_refused_and_not_read_as_harmless",
                                                                                                                              WU + "test_a_node_class_inside_an_expression_is_refused_as_well", FORMS), IDX,
      "        form = FORMS.get(type(node).__name__)\n        if form is None:", '        form = FORMS.get(type(node).__name__, "generic")\n        if form is None:'),
    c("idx-header-annotations-not-visited", "the annotations of a function's parameters are not walked", (WALRUS,), IDX, NOTES,
      "        self.annotations((node.returns,), scope, nested)"),
    c("idx-header-return-annotation-not-visited", "the return annotation of a function is not walked", (WALRUS,), IDX, NOTES,
      "        self.annotations((*(a.annotation for a in every),), scope, nested)"),
    c("idx-header-defaults-not-visited", "the defaults of a function are not walked", (WALRUS,), IDX, HEADER,
      "        self.each(node.decorator_list, scope, nested)"),
    c("idx-header-decorators-not-visited", "the decorators of a function are not walked", (WALRUS,), IDX, HEADER,
      "        self.each((*args.defaults, *args.kw_defaults), scope, nested)"),
    c("idx-class-header-keywords-not-visited", "the keyword values of a class are not walked", (WALRUS,), IDX, CLASS_HEADER, "        self.each((*node.decorator_list, *node.bases), scope, nested)"),
    c("idx-class-header-bases-not-visited", "the bases of a class are not walked", (WALRUS,), IDX, CLASS_HEADER, "        self.each((*node.decorator_list, *(k.value for k in node.keywords)), scope, nested)"),
    c("idx-class-header-decorators-not-visited", "the decorators of a class are not walked", (WALRUS,), IDX, CLASS_HEADER, "        self.each((*node.bases, *(k.value for k in node.keywords)), scope, nested)"),
    c("idx-lambda-defaults-not-visited", "the defaults of a lambda are not walked", (WALRUS,), IDX, "        self.each((*node.args.defaults, *node.args.kw_defaults), scope, nested)", "        self.each((), scope, nested)"),
    c("idx-walrus-in-a-comprehension-binds-inside-it", "an assignment expression in a comprehension binds in the comprehension's own scope", (WALRUS, GLOBAL), IDX,
      '            owner = scope if role == "star" or (scope.kind == "comprehension" and role == "target") else locate(scope, name, bound=True)', '            owner = scope if role == "star" or scope.kind == "comprehension" else locate(scope, name, bound=True)'),
    c("idx-comprehension-conditions-not-visited", "the conditions of a comprehension are not walked", (WALRUS,), IDX, "            self.each(generator.ifs, inner, nested)", "            pass"),
    c("idx-comprehension-element-not-visited", "the element of a comprehension is not walked", (WALRUS,), IDX,
      "        self.each((node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,), inner, nested)", "        pass"),
    c("idx-annotation-of-an-assignment-not-visited", "the annotation of an annotated assignment is not walked", (WALRUS,), IDX, "        self.annotations([node.annotation], scope, nested)\n", "        pass\n"),
    c("idx-value-of-an-annotated-assignment-not-visited", "the value of an annotated assignment is not walked", (WALRUS,), IDX, "        self.each([node.value], scope, nested)\n", "        pass\n"),
    c("idx-compound-header-not-visited", "the header expressions of an if, while, try or match are not walked", (WALRUS,), IDX,
      "            elif isinstance(value, ast.AST):\n                self.visit(value, scope, nested)\n", "            elif False:\n                self.visit(value, scope, nested)\n"),
    c("idx-loop-iterable-not-visited", "the iterable of a loop is not walked", (WALRUS,), IDX, "        self.visit(node.iter, scope, nested)\n        self.block(node.body, scope, True)", "        self.block(node.body, scope, True)"),
    c("idx-call-arguments-not-visited", "the arguments of a call are not walked", (WALRUS,), IDX,
      "        self.index.calls.append(CallSite(node, scope))\n        self.form_generic(node, scope, nested, target)", "        self.index.calls.append(CallSite(node, scope))"),
    c("idx-global-redirect-skips-imports", "a `global` declaration does not redirect an import", (GLOBAL,), IDX,
      "        if owner is not scope and owner is not holding(scope):\n", '        if owner is not scope and owner is not holding(scope) and role not in ("import", "from", "star"):\n'),
    c("idx-global-redirect-skips-definitions", "a `global` declaration does not redirect a definition", (GLOBAL,), IDX,
      "        if owner is not scope and owner is not holding(scope):\n", '        if owner is not scope and owner is not holding(scope) and role not in ("def", "class"):\n'),
    c("idx-global-redirect-skips-targets", "a `global` declaration does not redirect a loop, with or except target", (GLOBAL,), IDX,
      "        if owner is not scope and owner is not holding(scope):\n", '        if owner is not scope and owner is not holding(scope) and role != "target":\n'),
    c("idx-alias-identity-not-recorded", "a name bound to another name carries no alias reference", (CLR + "aliases_carry_the_identity", SCOPES), IDX,
      '        if role == "assign" and direct and chain_text(source) is not None:', "        if False:"),
    c("idx-alias-identity-not-followed", "an alias does not take the identity of what it aliases", (ALIASES, SCOPES, "test_source_binding.BindingTest.test_each_probe"), IDX,
      '        if binding.ref[:1] == ("alias",) and assignments:', "        if False:"),
    c("idx-object-not-implicit", "`object` is not the implicit last base of a class", (PR + "test_each_probe", EXTERNAL), IDX, "if direct else [OBJECT])", "if direct else [])"),
    c("idx-external-base-has-no-object", "an external base's order does not end with `object`", (EXTERNAL,), IDX, "else [node] if node == OBJECT else [node, OBJECT])", "else [node])"),
    c("idx-attribute-stores-not-recorded", "an attribute written or deleted is not a store site", (MODS, CLASSES), IDX,
      "    def form_attribute(self, node: ast.Attribute, scope: Scope, nested: bool, target) -> None:\n        if isinstance(node.ctx, (ast.Store, ast.Del)):",
      "    def form_attribute(self, node: ast.Attribute, scope: Scope, nested: bool, target) -> None:\n        if False:"),
    c("idx-subscript-stores-not-recorded", "an item written or deleted is not a store site", (MODS, CLASSES), IDX,
      "    def form_subscript(self, node: ast.Subscript, scope: Scope, nested: bool, target) -> None:\n        if isinstance(node.ctx, (ast.Store, ast.Del)):",
      "    def form_subscript(self, node: ast.Subscript, scope: Scope, nested: bool, target) -> None:\n        if False:"),
    c("idx-calls-not-recorded", "a call is not a call site", (CLR + "aliases_carry_the_identity",), IDX, "        self.index.calls.append(CallSite(node, scope))\n", "        pass\n"),
    c("idx-annotation-only-attribute-is-a-store", "`a.b: int`, which stores nothing, is a store", (DATA,), IDX,
      "        if node.value is None and not (isinstance(node.target, ast.Name) and node.simple):", "        if False:"),
    # --- the contract's dispatchers: a kind with no recorded effect is refused --------------------------------------------------------------
    c("con-store-of-an-unrecognised-kind-accepted", "a store whose base the classification cannot say is accepted as a store on data", (FORMS,), CON,
      "        form = self.STORE_FORMS.get(kind)\n", '        form = self.STORE_FORMS.get(kind, "store_data")\n'),
    c("con-class-binding-of-an-unrecognised-role-accepted", "a kind of binding in a class body that has no record is accepted as data",
      (WU + "test_a_kind_of_binding_in_a_class_body_the_contract_has_no_record_of_is_refused",), CON,
      "                form = self.CLASS_FORMS.get(binding.role)\n", '                form = self.CLASS_FORMS.get(binding.role, "member_data")\n'),
    c("con-binding-role-unrecognised-accepted", "a binding role the contract does not list is accepted", (WU + "test_a_binding_role_the_contract_has_no_record_of_is_refused",), CON,
      "                if binding.role not in source.BINDING_ROLES:", "                if False:"),
    c("con-store-through-a-module-accepted", "an attribute written on a module, a function or an external object is accepted", (MODS,), CON,
      STORE_FORMS, STORE_FORMS.replace('"namespace": "store_namespace"}', '"namespace": "store_data"}')),
    c("con-imported-class-is-a-namespace", "a name imported from a module is a namespace even when it is a class", (MODS,), CON,
      '                return "class" if self.facts.bound(index.path, holder, name)[0] == "class" else "namespace"', '                return "namespace"'),
    c("con-alias-of-a-class-is-data", "a name bound to a class denotes data", (CLASSES, MODS), CON,
      '            return self.kind_of(index, binding.origin or holder, binding.source, context, seen)', '            return "data"'),
    c("con-walrus-base-is-data", "a write through an assignment expression is a write through data, whatever it binds", (CLASSES,), CON,
      "        if isinstance(node, ast.NamedExpr):   # `(k := A).f = 1` writes through what `A` is\n            return self.kind_of(index, scope, node.value, context, seen)\n        return \"unknown\"", "        if isinstance(node, ast.NamedExpr):\n            return \"data\"\n        return \"unknown\""),
    c("con-write-through-data-to-a-family-name-accepted", "an attribute named like a method of a family, written through data, is accepted", (CLR + "writes_through_data_to_a_family_methods_name",), CON,
      "        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and node.attr in self.family_names:", "        if False:"),
    c("con-family-names-include-single-classes", "the method names of a class that has no family count as a family's", (DATA,), CON, "            if size > 1:", "            if True:"),
    c("con-deleting-a-family-name-is-an-override", "deleting an attribute named like a method of a family is an override", (DATA,), CON,
      "        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store) and node.attr in self.family_names:", "        if isinstance(node, ast.Attribute) and node.attr in self.family_names:"),
    # --- exports ---------------------------------------------------------------------------------------------------------------------------
    c("con-all-passed-on-accepted", "`__all__` passed on as a value is accepted", (ALL,), CON, "            elif not self.reads_only(index, node, up):", "            elif False:"),
    c("con-all-of-another-module-not-seen", "`__all__` read or written as an attribute of another module is not looked at", (ALL,), CON,
      '            named = (isinstance(node, ast.Name) and node.id == "__all__") or (isinstance(node, ast.Attribute) and node.attr == "__all__")', '            named = isinstance(node, ast.Name) and node.id == "__all__"'),
    # --- class bodies --------------------------------------------------------------------------------------------------------------------------
    c("con-hook-bound-by-a-statement-accepted", "a hook name bound by an assignment, a loop target or an import is accepted", (HOOKS,), CON,
      "        if name in HOOKS:\n            self.refuse(\"SRC-CLASS-HOOK\", index.path, binding.line, f\"class {cls.qual} binds", "        if False:\n            self.refuse(\"SRC-CLASS-HOOK\", index.path, binding.line, f\"class {cls.qual} binds"),
    c("con-method-aliased-by-a-statement-accepted", "a method aliased by anything but a plain assignment is accepted", (ALIAS,), CON,
      "        aliased = sorted({n.id for n in ast.walk(binding.source) if isinstance(n, ast.Name) and n.id in defs}) if binding.source is not None else []",
      '        aliased = sorted({n.id for n in ast.walk(binding.source) if isinstance(n, ast.Name) and n.id in defs}) if binding.source is not None and binding.role == "assign" and binding.direct else []'),
    c("con-superseded-always", "every class attribute counts as replaced by a transformation", (BODY,), CON,
      '        superseded = cls.members.get(name) is not None and cls.members[name].origin == "generated"', "        superseded = True"),
    c("con-slot-hiding-a-method-accepted", "a slot named like a method of the family is accepted", (BODY,), CON, "        for name in cls.slots:\n            if name in names:", "        for name in cls.slots:\n            if False:"),
    c("con-field-hiding-a-method-accepted", "a dataclass field named like a method of the family is accepted", (BODY,), CON, "        for name, line in cls.fields:\n            if name in names:",
      "        for name, line in cls.fields:\n            if False:"),
    c("con-fields-not-collected", "a dataclass has no fields", (BODY,), CON,
      "                if binding.annotated is not None and not self.not_a_field(cls, binding.annotated):\n                    cls.fields.append((name, binding.line))", "                pass"),
    c("con-classvar-is-a-field", "an annotation of ClassVar, InitVar or KW_ONLY makes an instance field", (MEMBERS,), CON,
      "            return self.facts.identity(cls.path, cls.parent, node) in FIELD_MARKERS", "            return False"),
    c("con-slots-written-twice-accepted", "a __slots__ written twice is accepted", (FORMS,), CON, "        if len(bindings) != 1 or bindings[0].role != \"assign\"", "        if bindings[0].role != \"assign\""),
    c("con-annotation-alone-binds", "an annotation without a value is a member of the class", (BODIES,), CON,
      '            elif any(b.role != "annotation" for b in bindings):', "            elif bindings:"),
    c("con-slots-not-members", "the names a __slots__ lists are not members", (MEMBERS,), CON,
      '        members.update({name: Member("slot", "authored", "a __slots__ entry") for name in cls.slots if name not in members})', "        pass"),
    # --- the effective members ---------------------------------------------------------------------------------------------------------------------------
    c("con-eq-without-hash-keeps-the-inherited-hash", "a class that defines __eq__ and not __hash__ keeps its ancestor's __hash__", (MEMBERS, PR + "test_each_probe", EM + "test_the_hash_member_of_every_class_is_what_the_interpreter_builds",
                                                                                                                                 EM + "test_the_masked_call_is_attributed_to_nobody_in_both_services"), CON,
      '        if "__eq__" in authored and "__hash__" not in authored:', "        if False:"),
    c("con-eq-replaces-an-explicit-hash", "a class that defines __eq__ has its own __hash__ replaced by None", (MEMBERS, EM + "test_the_hash_member_of_every_class_is_what_the_interpreter_builds"), CON,
      '        if "__eq__" in authored and "__hash__" not in authored:', '        if "__eq__" in authored:'),
    c("con-dataclass-hash-swapped", "a non-frozen dataclass generates a hash and a frozen one has None", (MEMBERS, EM + "test_the_hash_member_of_every_class_is_what_the_interpreter_builds"), CON,
      '            members["__hash__"] = Member("method", "generated", "frozen=True and eq=True: a generated __hash__") if frozen else \\', '            members["__hash__"] = Member("method", "generated", "frozen=True and eq=True: a generated __hash__") if not frozen else \\'),
    c("con-dataclass-explicit-hash-overwritten", "a dataclass's own __hash__ is replaced by the generated one", (MEMBERS, EM + "test_the_hash_member_of_every_class_is_what_the_interpreter_builds"), CON,
      '        explicit = bool(authored_hash) and not (none_hash and "__eq__" in authored)', "        explicit = False"),
    c("con-dataclass-none-hash-beside-eq-is-explicit", "a `__hash__ = None` beside __eq__ stays in a frozen dataclass", (MEMBERS, EM + "test_the_hash_member_of_every_class_is_what_the_interpreter_builds"), CON,
      '        explicit = bool(authored_hash) and not (none_hash and "__eq__" in authored)', "        explicit = bool(authored_hash)"),
    c("con-frozen-dataclass-generates-no-setattr", "a frozen dataclass generates no __setattr__ or __delattr__", (MEMBERS,), CON,
      '        for name in ("__init__", "__repr__", "__eq__", *(("__setattr__", "__delattr__") if frozen else ())):', '        for name in ("__init__", "__repr__", "__eq__"):'),
    c("con-data-members-attributed-as-methods", "a name an implicit or data member holds is attributed to an ancestor's method", (EM + "test_a_masking_member_is_data_for_every_name_and_not_only_hash",), MET,
      '                        if owner and role in ("method", "static", "class") and owner != member[0]:', "                        if owner and owner != member[0]:"),
    c("con-implicit-members-not-consulted", "the implicit members of a class are not consulted by the attribution", (PR + "test_each_probe", EM + "test_the_masked_call_is_attributed_to_nobody_in_both_services"), MET,
      "                for name, effective in facts.classes[member].members.items():", "                for name, effective in {n: m for n, m in facts.classes[member].members.items() if m.origin != 'implicit'}.items():"),
    c("con-dataclass-unsafe-hash-allowed", "a dataclass with unsafe_hash=True is a recorded form", (DATACLASS,), CON,
      'all(k.arg == "frozen" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)',
      'all(k.arg in ("frozen", "unsafe_hash") and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)'),
    # --- the external classes in the order -------------------------------------------------------------------------------------------------------------
    c("con-external-ancestor-before-a-project-class-accepted", "an external class that comes before a project class through an ancestor is accepted", (EXTERNAL, PR + "test_each_probe"), CON,
      "                external = external or entry[1]", "                external = None"),
    c("con-external-after-every-project-class-refused", "an external class after every project class is refused", (AFTER, EM + "test_an_external_class_after_every_project_class_cannot_hide_a_project_name"), CON,
      '            elif entry[0] != "base" and external:', '            elif entry[0] != "base" and not external:'),
    # --- the loader's fingerprint ----------------------------------------------------------------------------------------------------------------------------
    c("con-loader-fingerprint-unchecked", "a changed loader implementation is accepted when its filter is the reviewed one", (LB + "test_the_continue_turned_pass_loads_names_the_inventory_does_not_list_and_is_refused",
                                                                                                                              LB + "test_each_listed_change_to_the_reviewed_loader_is_refused"), CON,
      "            if found is not None and found != entry.fingerprint:", "            if False:"),
    c("con-fingerprint-includes-docstrings", "a docstring edit changes the loader's fingerprint (the recorded fingerprint is that of this variant, so the real loader is accepted)",
      (LB + "test_changes_that_are_not_the_implementation_are_not_refused",), CON, '"body": without_docstring(node.body)}))', '"body": node.body}))',
      also=((FINGERPRINT, "e9983d212c5022d2f6a0742b7d81943ea23c1106fe6f4d685dd8e3192e9e8a42"), *EXCEPTION_FINGERPRINTS_WITH_DOCSTRINGS)),
    c("con-fingerprint-ignores-the-modules-statements", "the statements around the loader are not part of its fingerprint (the recorded fingerprint is that of this variant)",
      (LB + "test_each_listed_change_to_the_reviewed_loader_is_refused",), CON,
      "        elif not isinstance(statement, (*source.FUNCTIONS, ast.ClassDef)):\n            parts.append(normalised(statement))", "        elif False:\n            parts.append(normalised(statement))",
      also=((FINGERPRINT, "2efc3f5025cbfdd0120a97c628cc5d377375cadb9737f9c86ebd1c2b0a047566"),)),
    c("con-fingerprint-includes-other-definitions", "another function in the loader's module changes its fingerprint", (LB + "test_changes_that_are_not_the_implementation_are_not_refused",), CON,
      "        elif not isinstance(statement, (*source.FUNCTIONS, ast.ClassDef)):\n            parts.append(normalised(statement))", "        else:\n            parts.append(normalised(statement))"),
    c("con-fingerprint-includes-the-module-docstring", "the module docstring is part of the loader's fingerprint (the recorded fingerprint is that of this variant)",
      (LB + "test_changes_that_are_not_the_implementation_are_not_refused",), CON, "    for statement in without_docstring(tree.body):", "    for statement in tree.body:",
      also=((FINGERPRINT, "03d39537f1600b4db30947c67ae0dca7c14e71358c8b15b16554a69f803004f5"),)),
    # --- the commands: a partial report says so ---------------------------------------------------------------------------------------------------------------
    c("met-report-writes-no-marker", "a report of refused source leaves no NOT-CERTIFIED marker", (EC + "test_report_shows_the_input_as_incomplete_and_non_passing_and_still_writes_what_it_could_read",), MET,
      "        mark_not_certified(Path(args.out), measurement.facts.diagnostics)\n        print_refusal(measurement.facts.diagnostics, partial=True)\n        print(f\"gen2-metrics: PARTIAL report",
      "        print_refusal(measurement.facts.diagnostics, partial=True)\n        print(f\"gen2-metrics: PARTIAL report"),
    c("met-report-says-nothing-was-measured", "a report of refused source says nothing was measured, though it writes tables", (EC + "test_report_shows_the_input_as_incomplete_and_non_passing_and_still_writes_what_it_could_read",
                                                                                                                                EC + "test_hotspots_refuses_too_and_its_tables_are_marked_partial_and_not_certified"), MET,
      '    outcome = ("the tables written are PARTIAL, the input is incomplete and non-passing, and nothing in them is certified" if partial', '    outcome = ("the tables written are PARTIAL, the input is incomplete and non-passing, and nothing in them is certified" if False'),
    c("met-command-says-partial-when-it-measured-nothing", "check says its tables are partial, though it writes none", (EC + "test_check_refuses",), MET,
      '               else "nothing was measured, recorded or certified")', '               else "the tables written are PARTIAL, the input is incomplete and non-passing, and nothing in them is certified")'),
    c("met-hotspots-writes-no-marker", "the history report of refused source leaves no NOT-CERTIFIED marker", (EC + "test_hotspots_refuses_too_and_its_tables_are_marked_partial_and_not_certified",), MET,
      "        mark_not_certified(Path(args.out), measurement.facts.diagnostics)\n        print_refusal(measurement.facts.diagnostics, partial=True)\n        return EXIT_FAIL\n    return EXIT_OK\n\n\ndef main(",
      "        print_refusal(measurement.facts.diagnostics, partial=True)\n        return EXIT_FAIL\n    return EXIT_OK\n\n\ndef main("),
    c("met-report-certifies-refused-source", "a report of refused source is marked certified", (EC + "test_report_shows_the_input_as_incomplete_and_non_passing_and_still_writes_what_it_could_read",), MET,
      '"certified": not facts.diagnostics,', '"certified": True,'),
    # --- the completion witness ---------------------------------------------------------------------------------------------------------------------------------
    c("run-no-record-is-complete", "a child that left no completion record is a completed run", (WT + "test_a_child_that_leaves_through_os_exit_zero_wrote_no_record_and_did_not_complete",
                                                                                                   WT + "test_an_exit_one_child_whose_crash_report_is_suppressed_did_not_complete"), FIX,
      "    if completion is None:\n        return \"it left no completion record: it did not return or exit normally (an os._exit, or a crash whose report was suppressed)\"",
      "    if completion is None:\n        return None"),
    c("run-record-status-unchecked", "a completion record that disagrees with the exit status is accepted", (WT + "test_a_record_that_disagrees_with_the_exit_status_is_not_a_completed_run",), FIX,
      "    if completion.get(\"status\") != done.returncode:", "    if False:"),
    c("run-launcher-records-the-status-wrongly", "the launcher records status 0 whatever the tool exited with", (WT + "test_an_exit_one_child_that_is_a_refusal_wrote_its_record_and_completed",), FIX,
      '    json.dump({"status": status}, handle)', '    json.dump({"status": 0}, handle)'),
    c("run-launcher-records-before-the-tool-runs", "the launcher writes its record before the tool has run", (WT + "test_a_child_that_leaves_through_os_exit_zero_wrote_no_record_and_did_not_complete",), FIX,
      'status = 0\ntry:\n    runpy.run_path(tool, run_name="__main__")', 'status = 0\nwith open(record, "w", encoding="utf-8") as handle:\n    json.dump({"status": 0}, handle)\ntry:\n    runpy.run_path(tool, run_name="__main__")'),
    # --- the harness's verdict ------------------------------------------------------------------------------------------------------------------------------------
    c("harness-an-error-beside-a-failure-is-a-kill", "a killer that errored in one subtest and failed in another is KILLED", (MV + "test_an_assertion_failure_and_a_child_that_did_not_complete_in_one_killer_is_invalid",
                                                                                                                              MV + "test_a_child_that_vanished_without_a_record_is_the_same_incomplete_execution",
                                                                                                                              MV + "test_an_error_in_the_killers_own_process_is_incomplete_execution_too"), HAR,
      "    if res.errored:   # only killers and controls ran", "    if res.errored and (missing or not m.killers):   # only killers and controls ran"),
    c("harness-the-complete-child-result-is-dropped", "the collector keeps only the last line of an error", (MV + "test_the_invalid_verdict_keeps_the_complete_child_result",), HAR,
      "            self.errored_detail.setdefault(test.id(), []).append(text)\n", "            pass\n"),
    c("harness-the-invalid-verdict-shows-no-detail", "the INVALID verdict does not print the complete errors", (MV + "test_the_invalid_verdict_keeps_the_complete_child_result",), HAR,
      '                f"even when the same test also failed an assertion){shown}")', '                f"even when the same test also failed an assertion)")'),
]
