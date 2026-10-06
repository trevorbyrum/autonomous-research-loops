"""Mutants of task 2q-a-repair-7 (SOURCE-CONTRACT version 2, soundy by declaration: the ban on the dynamic mechanisms, the exact-statement exceptions, private names and quoted class-body
annotations). Each guard is removed or weakened alone.

  2Q7-ban-*        which names are banned and where a reference is read (tools/gen2_source_contract.py `BANNED`, `banned_references`, and the reference-not-value rule);
  2Q7-exception-*  the exact-statement exceptions: by file, by enclosing function, by the statement itself, once, and the write an excepted statement makes;
  2Q7-quoted-*     a quoted annotation in a class body;
  2Q7-private-*    a private (name-mangled) identifier in each position it can be written;
  2Q7-line-*       the walk's order.

Every killer fails by ASSERTION: a refusal fixture the mutant lets through (gen2/tests/source_mechanism_fixtures.py: one family per mechanism, in both services) or a positive fixture it
refuses (the plain-data-processing control, the ordinary dunders, the quoted annotations that are no field marker); none relies on a crash.
"""
from __future__ import annotations

from .base import Mutation

CON = "tools/gen2_source_contract.py"
BM, PN, QA, EX = ("test_source_mechanisms.BannedMechanismTest.test_refuses_", "test_source_mechanisms.PrivateNameTest.", "test_source_mechanisms.QuotedAnnotationTest.", "test_source_mechanisms.ExceptionTest.")
PRIVATE = PN + "test_refuses_private_names_in_every_position"
ACCEPTED_NAMES = PN + "test_the_accepted_names_are_accepted_in_both_services"
QUOTED = QA + "test_refuses_quoted_annotations_in_a_class_body"
QUOTED_OK = QA + "test_the_accepted_quoted_annotations_are_accepted_in_both_services"
OTHER_FUNCTION = EX + "test_the_same_statements_in_another_function_are_refused"
CHANGED = EX + "test_a_changed_statement_is_refused_and_so_is_a_second_copy_in_the_same_function"

BANNED = '("setattr", "delattr", "vars", "globals", "locals", "exec", "eval", "compile", "__import__", "importlib", "import_module", "__dict__", "__setattr__", "__delattr__", "__getattribute__")'
ATTRIBUTES = '("__dict__", "__setattr__", "__delattr__", "__getattribute__", "import_module", "__import__", "modules")'


def banned(without: str) -> tuple[str, str]:
    """The `BANNED = (...)` line without these entries."""
    old = f"BANNED = {BANNED}"
    new = old
    for name in without.split(","):
        new = new.replace(f'"{name}", ', "", 1) if f'"{name}", ' in new else new.replace(f', "{name}"', "", 1)
    return old, new


def b(mid: str, description: str, killers: tuple[str, ...], old: str, new: str, also: tuple[tuple[str, str], ...] = ()) -> Mutation:
    return Mutation(f"2Q7-{mid}", "2q-a-repair-7", description, killers, target=CON, old=old, new=new, also=also)


def ban_without(mid: str, description: str, killers: tuple[str, ...], names: str, attributes: str = "") -> Mutation:
    old, new = banned(names)
    also = ()
    if attributes:
        old_attrs = f"BANNED_ATTRIBUTES = {ATTRIBUTES}"
        new_attrs = old_attrs
        for name in attributes.split(","):
            new_attrs = new_attrs.replace(f'"{name}", ', "", 1) if f'"{name}", ' in new_attrs else new_attrs.replace(f', "{name}"', "", 1)
        also = ((old_attrs, new_attrs),)
    return b(mid, description, killers, old, new, also)


MUTATIONS: list[Mutation] = [
    # --- the names the ban lists --------------------------------------------------------------------------------------------------------------
    ban_without("ban-setattr-delattr-unreferenced", "a reference to setattr or delattr is accepted", (BM + "setattr_and_delattr",), "setattr,delattr"),
    ban_without("ban-vars-globals-locals-unreferenced", "a reference to vars, globals or locals is accepted", (BM + "vars_globals_locals",), "vars,globals,locals"),
    ban_without("ban-exec-eval-compile-unreferenced", "a reference to exec, eval or compile is accepted", (BM + "code_execution",), "exec,eval,compile"),
    ban_without("ban-importlib-unreferenced", "a reference to importlib is accepted", (BM + "dynamic_import",), "importlib"),
    ban_without("ban-import-module-unreferenced", "a reference to import_module is accepted", (BM + "dynamic_import",), "import_module", "import_module"),
    ban_without("ban-dunder-import-unreferenced", "a reference to __import__ is accepted", (BM + "dynamic_import",), "__import__", "__import__"),
    ban_without("ban-dunder-dict-unreferenced", "an access of __dict__ is accepted", (BM + "dunder_dict",), "__dict__", "__dict__"),
    ban_without("ban-attribute-protocol-unreferenced", "a reference to __setattr__, __delattr__ or __getattribute__ is accepted", (BM + "attribute_protocol",), "__setattr__,__delattr__,__getattribute__",
                "__setattr__,__delattr__,__getattribute__"),
    b("ban-sys-modules-attribute-unreferenced", "an attribute `modules` (sys.modules) is accepted", (BM + "sys_modules",), f"BANNED_ATTRIBUTES = {ATTRIBUTES}", f"BANNED_ATTRIBUTES = {ATTRIBUTES.replace(', \"modules\"', '')}"),
    b("ban-from-sys-import-modules-unreferenced", "`from sys import modules` is accepted", (BM + "sys_modules",),
      ' or (node.module == "sys" and a.name == "modules")', ""),
    b("ban-builtins-attributes-unreferenced", "a built-in reached as an attribute of the imported builtins module is accepted", (BM + "setattr_and_delattr", BM + "code_execution"),
      'BUILTIN_ATTRIBUTES = ("setattr", "delattr", "vars", "globals", "locals", "exec", "eval", "compile")', "BUILTIN_ATTRIBUTES = ()"),
    b("ban-builtins-module-not-collected", "an imported builtins module (or an alias of it) is not known as one", (BM + "setattr_and_delattr", BM + "code_execution"),
      '        builtin_modules = {"__builtins__"} | {a.asname or a.name for n in ast.walk(index.tree) if isinstance(n, ast.Import) for a in n.names if a.name == "builtins"}', "        builtin_modules = set()"),
    b("ban-type-starred-or-keyword-call-accepted", "type with a starred argument, a keyword or two arguments is accepted: only the three-argument call is refused", (BM + "three_argument_type",),
      "        one_plain_argument = len(node.args) == 1 and not node.keywords and not isinstance(node.args[0], ast.Starred)", "        one_plain_argument = len(node.args) != 3"),
    # --- where a reference is read: imports, and the REFERENCE rather than the call ------------------------------------------------------------
    b("ban-imports-unreferenced", "`import importlib` is not a reference", (BM + "dynamic_import",),
      '    if isinstance(node, ast.Import):\n        return [a.name for a in node.names if a.asname in BANNED or any(part in BANNED for part in a.name.split("."))]\n',
      "    if isinstance(node, ast.Import):\n        return []\n"),
    b("ban-from-imports-unreferenced", "`from importlib import x` and `from sys import modules` are not references", (BM + "dynamic_import", BM + "sys_modules"),
      '        found = [node.module] if node.module and not node.level and any(part in BANNED for part in node.module.split(".")) else []\n        return found + [a.name for a in node.names if a.name in BANNED or a.asname in BANNED or (node.module == "sys" and a.name == "modules")]',
      "        return []"),
    b("ban-reads-only-a-bare-call-statement", "a banned name is refused only in a bare expression statement: an alias, a value passed, stored or assigned is missed (a ban on the call, not the reference)",
      (BM + "vars_globals_locals", BM + "dynamic_import", BM + "code_execution", BM + "dunder_dict"),
      "            for name in banned_references(node, builtin_modules):", "            for name in (banned_references(node, builtin_modules) if isinstance(stmt, ast.Expr) else []):"),
    # --- the exact-statement exceptions -------------------------------------------------------------------------------------------------------
    b("exception-ignores-the-function", "an excepted statement is excepted in any function of its file", (OTHER_FUNCTION,),
      "e.function == qual and e.statement == text and used.setdefault", "e.statement == text and used.setdefault"),
    b("exception-ignores-the-statement", "any statement of an excepted function is excepted", (CHANGED,),
      "e.function == qual and e.statement == text and used.setdefault", "e.function == qual and used.setdefault"),
    b("exception-ignores-the-file", "an excepted statement is excepted in any file", (EX + "test_the_same_statements_in_another_file_are_refused",),
      "        excepted, used = [e for e in EXCEPTIONS if e.file == path], {}", "        excepted, used = list(EXCEPTIONS), {}"),
    b("exception-matches-a-second-copy", "an excepted statement is excepted again where it is copied in the same function", (CHANGED,),
      " and used.setdefault(e, id(stmt)) == id(stmt)), None)", "), None)"),
    b("exception-write-unchecked", "the instance attribute an excepted statement sets is not checked against the family's methods", (EX + "test_the_excepted_write_is_checked_like_any_write_through_the_receiver",),
      "                elif site.writes:", "                elif False:"),
    b("exception-loader-file-matches-any-statement", "every statement of the loader's file is excepted in its function", (EX + "test_another_reference_inside_the_loader_function_is_refused_as_a_banned_mechanism_whatever_the_fingerprint_says",),
      "e.function == qual and e.statement == text and used.setdefault", "e.function == qual and (e.statement == text or e.file == LOADER_FILE) and used.setdefault"),
    # --- a quoted annotation in a class body -------------------------------------------------------------------------------------------------
    b("quoted-annotation-accepted", "a quoted annotation in a class body is accepted", (QUOTED,),
      "            if in_class and isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Constant) and isinstance(node.annotation.value, str):",
      "            if False and in_class and isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Constant) and isinstance(node.annotation.value, str):"),
    b("quoted-annotation-refused-outside-a-class-body", "a quoted annotation is refused wherever it stands, not only in a class body", (QUOTED_OK,),
      "            if in_class and isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Constant) and isinstance(node.annotation.value, str):",
      "            if isinstance(node, ast.AnnAssign) and isinstance(node.annotation, ast.Constant) and isinstance(node.annotation.value, str):"),
    b("quoted-annotation-class-body-includes-methods", "the body of a method of a class is a class body", (QUOTED_OK,),
      "        in_class = isinstance(node, ast.ClassDef) or (in_class and not isinstance(node, (*source.FUNCTIONS, ast.Lambda)))", "        in_class = isinstance(node, ast.ClassDef) or in_class"),
    b("quoted-annotation-class-body-excludes-compound-statements", "a quoted annotation under an `if` in a class body is not in the class body", (QUOTED,),
      "        in_class = isinstance(node, ast.ClassDef) or (in_class and not isinstance(node, (*source.FUNCTIONS, ast.Lambda)))", "        in_class = isinstance(node, ast.ClassDef)"),
    # --- a private (name-mangled) identifier ---------------------------------------------------------------------------------------------------
    b("private-names-accepted", "no identifier is private", (PRIVATE,),
      '    return bool(name) and name.startswith("__") and not name.endswith("__")', "    return False"),
    b("private-dunders-are-private", "a name that ends in two underscores is private as well", (ACCEPTED_NAMES,),
      '    return bool(name) and name.startswith("__") and not name.endswith("__")', '    return bool(name) and name.startswith("__")'),
    b("private-name-unchecked", "a private name read or written as a name is accepted", (PRIVATE,),
      "    if isinstance(node, ast.Name):\n        names = [node.id]\n    elif isinstance(node, ast.Attribute):", "    if isinstance(node, ast.Name):\n        names = []\n    elif isinstance(node, ast.Attribute):"),
    b("private-attribute-unchecked", "a private attribute is accepted", (PRIVATE,), "        names = [node.attr]\n", "        names = []\n"),
    b("private-definition-unchecked", "a private function or class name is accepted", (PRIVATE,), "        names = [node.name]\n    elif isinstance(node, ast.arg):", "        names = []\n    elif isinstance(node, ast.arg):"),
    b("private-parameter-unchecked", "a private parameter is accepted", (PRIVATE,), "        names = [node.arg]\n    elif isinstance(node, ast.alias):", "        names = []\n    elif isinstance(node, ast.alias):"),
    b("private-import-alias-unchecked", "a private import alias or imported name is accepted", (PRIVATE,), '        names = [*node.name.split("."), node.asname]', "        names = []"),
    b("private-global-unchecked", "a private name declared global or nonlocal is accepted", (PRIVATE,), "        names = node.names\n", "        names = []\n"),
    b("private-capture-unchecked", "a private name bound by `except ... as` or a match capture is accepted", (PRIVATE,),
      "    elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):\n        names = [node.name]", "    elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):\n        names = []"),
    b("private-mapping-rest-unchecked", "a private name captured by a mapping pattern is accepted", (PRIVATE,), "        names = [node.rest]\n", "        names = []\n"),
    b("private-class-pattern-keyword-unchecked", "a private attribute name in a class pattern is accepted", (PRIVATE,), "        names = node.kwd_attrs\n", "        names = []\n"),
    b("private-keyword-unchecked", "a private keyword of a call or a class is accepted", (PRIVATE,), "    elif isinstance(node, ast.keyword):\n        names = [node.arg]", "    elif isinstance(node, ast.keyword):\n        names = []"),
    b("private-module-path-unchecked", "a private module path in a from-import is accepted", (PRIVATE,), '        names = (node.module or "").split(".")', "        names = []"),
    b("private-slot-unchecked", "a private entry of __slots__ is accepted", (PRIVATE,), "            if is_private(e.value):   # the compiler mangles a slot's name like any other private name", "            if False:"),
    # --- the walk visits the nodes in source order ---------------------------------------------------------------------------------------------
    b("line-walk-reversed", "the walk visits the nodes in reverse order, so the first copy of an excepted statement is the one refused", (CHANGED,),
      "        todo.extend(reversed([(child, qual, stmt, in_class) for child in ast.iter_child_nodes(node)]))", "        todo.extend([(child, qual, stmt, in_class) for child in ast.iter_child_nodes(node)])"),
]
