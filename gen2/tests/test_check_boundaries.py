"""Black-box tests for tools/check_boundaries.py.

Trace: task 0a deliverable 4 ("fails loudly on violation"); BUILD-STATE says
the boundary-graph check itself gets a Gate C review.

Each test builds a throwaway repository (its own boundaries.toml,
BOUNDARIES.md and gen2/ tree, written literally here rather than derived from
the real config), runs the checker as a subprocess, and asserts the exit code
plus the specific violation it must report. The oracle is the hand-written
expectation in each test, not the checker's own output.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "tools" / "check_boundaries.py"  # module globals: tools/gen2_mutations.py points these at mutated copies
REAL_BOUNDARIES = REPO / "gen2" / "boundaries.toml"

DOC_HEADINGS = ["Router", "Station supervisor", "Verifier"]

BASE_MODULES: dict[str, dict] = {
    "core": {"path": "gen2/core", "boundaries": [], "may_import": [], "stdlib_capabilities": []},
    "store": {"path": "gen2/store", "boundaries": ["Router"], "may_import": ["core"], "stdlib_capabilities": ["sqlite3"]},
    "router": {"path": "gen2/router", "boundaries": ["Router"], "may_import": ["core", "store"], "stdlib_capabilities": []},
    "supervisor": {"path": "gen2/supervisor", "boundaries": ["Station supervisor"], "may_import": ["core"], "stdlib_capabilities": ["subprocess", "os.exec*"]},
    "tests": {"path": "gen2/tests", "boundaries": [], "may_import": ["*"], "stdlib_capabilities": ["*"]},
}
RESTRICTED = ["sqlite3", "subprocess", "os.system", "os.exec*", "urllib.request", "importlib.import_module"]
FORBIDDEN_SQL = [r"\bOR\s+REPLACE\b", r"\bREPLACE\s+INTO\b"]


STORE_RULE = [  # rule 9 (task 1b), as the real config states it
    'store_write_primitives = ["gen2.store.api.Store", "gen2.store.api.open_store", "gen2.store.api.adopt_in_memory", "gen2.store.db.connect"]',
    'store_writers = ["router"]',
    'store_writer_exempt_modules = ["tests"]',
]


def render_config(modules: dict[str, dict], unmapped: dict[str, str] | None = None, store_rule: list[str] | None = None) -> str:
    lines = [
        "schema_version = 1",
        'package_root = "gen2"',
        'boundaries_doc = "docs/gen2/BOUNDARIES.md"',
        'forbidden_imports = ["research_loops", "research_gateway"]',
        'forbidden_calls = ["eval", "exec", "compile", "__import__"]',
        f"restricted_stdlib = {json.dumps(RESTRICTED)}",
        f"forbidden_sql = {json.dumps(FORBIDDEN_SQL)}",
        'forbidden_sql_exempt_modules = ["tests"]',
        *(store_rule or []),
    ]
    for name, spec in modules.items():
        lines.append(f"[modules.{name}]")
        lines.append(f"path = {json.dumps(spec['path'])}")
        lines.append('purpose = "fixture module"')
        for key in ("boundaries", "may_import", "stdlib_capabilities"):
            lines.append(f"{key} = {json.dumps(spec[key])}")
        lines.append("third_party = []")
    lines.append("[unmapped_components]")
    for heading, reason in (unmapped if unmapped is not None else {"Verifier": "invocation kind"}).items():
        lines.append(f"{json.dumps(heading)} = {json.dumps(reason)}")
    return "\n".join(lines) + "\n"


class BoundaryCheckerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.modules = json.loads(json.dumps(BASE_MODULES))
        self.headings = list(DOC_HEADINGS)
        self.unmapped: dict[str, str] | None = None
        self.store_rule: list[str] | None = None

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")

    def run_checker(self) -> subprocess.CompletedProcess:
        self.write("gen2/boundaries.toml", render_config(self.modules, self.unmapped, self.store_rule))
        self.write("docs/gen2/BOUNDARIES.md", "# Contract\n\n" + "".join(f"## {h}\n- text\n\n" for h in self.headings))
        return subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)], capture_output=True, text=True, timeout=60)

    def assertViolation(self, result: subprocess.CompletedProcess, fragment: str, code: int = 1) -> None:
        self.assertEqual(result.returncode, code, msg=f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertIn(fragment, result.stderr)
        self.assertIn("FAILED", result.stderr)

    # -- clean tree -------------------------------------------------------
    def test_clean_tree_passes(self) -> None:
        self.write("gen2/core/types.py", "from __future__ import annotations\nimport dataclasses\nimport os\nX = os.path.join('a', 'b')\n")
        self.write("gen2/store/db.py", "import sqlite3\nfrom gen2.core import types\n")
        self.write("gen2/router/commit.py", "from gen2.store import db\nfrom ..core import types\nfrom . import helpers\n")
        self.write("gen2/router/helpers.py", "")
        self.write("gen2/supervisor/run.py", "import os\nimport subprocess\ndef go():\n    os.execv('/bin/true', ['true'])\n")
        self.write("gen2/tests/test_x.py", "import sqlite3\nimport gen2.router.commit\nimport gen2.supervisor.run\n")
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("gen2 boundary check OK: 6 Python file(s) in 5 module(s)", result.stdout)

    def test_empty_package_passes_with_config_validated(self) -> None:
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("no code yet", result.stdout)

    # -- gen2 dependency rules --------------------------------------------
    def test_undeclared_dependency_absolute(self) -> None:
        self.write("gen2/router/commit.py", "from gen2.supervisor import run\n")
        self.assertViolation(self.run_checker(), "gen2/router/commit.py:1: router imports supervisor")

    def test_undeclared_dependency_via_namespace_root_form(self) -> None:
        self.write("gen2/router/commit.py", "from gen2 import supervisor\n")
        self.assertViolation(self.run_checker(), "router imports supervisor")

    def test_undeclared_dependency_via_relative_import(self) -> None:
        self.write("gen2/router/commit.py", "from ..supervisor import run\n")
        self.assertViolation(self.run_checker(), "router imports supervisor (gen2.supervisor.run)")

    def test_relative_import_escaping_package_root(self) -> None:
        self.write("gen2/router/commit.py", "from ... import anything\n")
        self.assertViolation(self.run_checker(), "relative import escapes the package root")

    def test_reverse_direction_is_not_implied(self) -> None:
        # router may import store; store may not import router.
        self.write("gen2/store/db.py", "import gen2.router.commit\n")
        self.assertViolation(self.run_checker(), "store imports router")

    def test_imports_hidden_in_functions_and_type_checking_blocks_count(self) -> None:
        self.write(
            "gen2/router/commit.py",
            """\
            from typing import TYPE_CHECKING
            if TYPE_CHECKING:
                from gen2 import supervisor
            def late():
                import gen2.supervisor.run
            """,
        )
        result = self.run_checker()
        self.assertViolation(result, "gen2/router/commit.py:3: router imports supervisor")
        self.assertIn("gen2/router/commit.py:5: router imports supervisor", result.stderr)

    def test_file_outside_every_declared_module(self) -> None:
        self.write("gen2/misc/thing.py", "")
        self.assertViolation(self.run_checker(), "gen2/misc/thing.py: not inside any declared module")

    def test_import_of_undeclared_gen2_package(self) -> None:
        self.write("gen2/core/types.py", "import gen2.misc\n")
        self.assertViolation(self.run_checker(), "imports 'gen2.misc', which is not inside any declared module")

    # -- gen-1 is off limits everywhere ------------------------------------
    def test_gen1_engine_import_forbidden_even_for_tests(self) -> None:
        self.write("gen2/tests/test_x.py", "import research_loops.queue\n")
        self.assertViolation(self.run_checker(), "tests imports forbidden 'research_loops.queue'")

    def test_gateway_internals_import_forbidden(self) -> None:
        self.write("gen2/core/types.py", "from research_gateway.app import thing\n")
        self.assertViolation(self.run_checker(), "core imports forbidden 'research_gateway.app.thing'")

    # -- capability-bearing stdlib and third-party --------------------------
    def test_restricted_stdlib_not_granted(self) -> None:
        self.write("gen2/router/commit.py", "import sqlite3\n")
        self.assertViolation(self.run_checker(), "router uses restricted stdlib 'sqlite3'")

    def test_restricted_entry_covers_members_and_submodules(self) -> None:
        self.write("gen2/router/commit.py", "from subprocess import run\nimport sqlite3.dbapi2\n")
        result = self.run_checker()
        self.assertViolation(result, "gen2/router/commit.py:1: router uses restricted stdlib 'subprocess' (via subprocess.run)")
        self.assertIn("gen2/router/commit.py:2: router uses restricted stdlib 'sqlite3' (via sqlite3.dbapi2)", result.stderr)

    def test_restricted_attribute_on_unrestricted_import(self) -> None:
        self.write("gen2/core/types.py", "import os\nos.system('true')\n")
        self.assertViolation(self.run_checker(), "gen2/core/types.py:2: core uses restricted stdlib 'os.system'")

    def test_restricted_prefix_entry(self) -> None:
        self.write("gen2/core/types.py", "from os import execvp\n")
        self.assertViolation(self.run_checker(), "core uses restricted stdlib 'os.exec*' (via os.execvp)")

    def test_restricted_submodule_via_attribute_chain(self) -> None:
        self.write("gen2/core/types.py", "import urllib\nurllib.request.urlopen('http://x.invalid')\n")
        self.assertViolation(self.run_checker(), "core uses restricted stdlib 'urllib.request'")

    def test_third_party_import_undeclared(self) -> None:
        self.write("gen2/core/types.py", "import requests\n")
        self.assertViolation(self.run_checker(), "core imports third-party package 'requests'")

    # -- dynamic code ------------------------------------------------------
    def test_dynamic_import_via_importlib(self) -> None:
        self.write("gen2/core/types.py", "import importlib\nm = importlib.import_module('gen2.supervisor')\n")
        self.assertViolation(self.run_checker(), "core uses restricted stdlib 'importlib.import_module'")

    def test_forbidden_builtin_calls(self) -> None:
        """B20 rewrite (A8), extended for RA7: every ordinary static spelling
        that reaches a forbidden builtin is reported at its line — not only
        literal calls, and not only in bodies: parameter annotations (the
        review's `def f(x: eval('1')): pass`, and keyword-only, *args/**kwargs
        and positional-only variants), return annotations, async signatures and
        type-parameter bounds are evaluated code too."""
        self.write("gen2/core/types.py", """\
            x = eval('1')
            y = __import__('gen2.supervisor')
            import builtins
            builtins.exec('pass')
            import builtins as b
            b.exec('pass')
            from builtins import eval as evaluate
            evaluate('1')
            e = compile
            __builtins__['exec']('pass')
            def late():
                import builtins as bb
                return bb.eval('2')
            ops = list(map(exec, []))
            def f(x: eval('1')): pass
            def ret() -> exec('pass'): pass
            def kwonly(*, k: compile('1', 'f', 'eval') = 1): pass
            def star(*a: __import__('os'), **kw: eval('2')): pass
            def pos(p: exec('x'), /): pass
            async def coro(x: eval('3')): pass
            def generic[T: eval('4')](): pass
            class Generic[T: exec('5')]: pass
            """)
        result = self.run_checker()
        self.assertViolation(result, "gen2/core/types.py:1: core reaches forbidden builtin eval()")
        for line, name in ((2, "__import__()"), (4, "exec()"), (6, "exec()"), (7, "eval()"), (9, "compile()"), (10, "__builtins__"), (13, "eval()"), (14, "exec()"),
                           (15, "eval()"), (16, "exec()"), (17, "compile()"), (18, "__import__()"), (18, "eval()"), (19, "exec()"), (20, "eval()"),
                           (21, "eval()"), (22, "exec()")):
            with self.subTest(line=line):
                self.assertIn(f"gen2/core/types.py:{line}: core reaches forbidden builtin {name}", result.stderr)

    def test_shadowed_names_are_not_builtins(self) -> None:
        """Scope-aware negative controls: a local binding named like a builtin is
        not the builtin (re.compile, a parameter, a local function)."""
        self.write("gen2/core/types.py", """\
            from re import compile
            PATTERN = compile('x')
            def run(eval):
                return eval(1)
            def local():
                def exec(code):
                    return code
                return exec('x')
            class K:
                def compile(self):
                    return self.compile
            """)
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_alias_reuse_in_another_scope_does_not_hide_a_capability(self) -> None:
        """The review's A8 probe: `import json as x` in one function must not hide
        `import os as x` (module level) used in another. Aliases resolve in the
        scope that binds them; global declarations are honoured."""
        self.write("gen2/core/types.py", """\
            import os as x
            def f():
                import json as x
                return x.dumps({})
            def g():
                return x.system('true')
            def h():
                global y
                import os as y
            def i():
                return y.system('true')
            def j():
                import json as x
                return x.system
            """)
        result = self.run_checker()
        self.assertViolation(result, "gen2/core/types.py:6: core uses restricted stdlib 'os.system'")
        self.assertIn("gen2/core/types.py:11: core uses restricted stdlib 'os.system'", result.stderr)
        self.assertNotIn("types.py:14:", result.stderr)  # there x is json: json.system is no capability
        self.assertNotIn("types.py:4:", result.stderr)

    REVIEW_RA7 = {  # Astra re-review RA7, verbatim: each returned no violation in accounting under the real graph
        "annotation.py": "def f(x: eval('1')): pass\n",
        "annotation_os.py": "import os\ndef f(x: os.system('true')): pass\n",
        "nonlocal_rebind.py": "def f():\n    import json as x\n    def g():\n        nonlocal x\n        import os as x\n    g()\n    x.system('true')\n",
        "posix_direct.py": "import posix\nposix.system('true')\n",
    }

    def real_graph(self) -> None:
        self.write("gen2/boundaries.toml", REAL_BOUNDARIES.read_text(encoding="utf-8"))
        self.write("docs/gen2/BOUNDARIES.md", (REPO / "docs" / "gen2" / "BOUNDARIES.md").read_text(encoding="utf-8"))

    def test_review_ra7_reproductions_under_the_real_graph(self) -> None:
        """RA7: the review's four sources, verbatim, in `accounting` under the
        REAL gen2/boundaries.toml, each reported at its line — beside positive
        shadowing controls that must stay silent: a parameter named eval with
        a string annotation, an os annotation that is no capability, posixpath
        and os.getcwd, a nonlocal import rebinding an os alias to json (x.dumps
        is no capability), and a nonlocal non-import binding shadowing a
        module-level os alias."""
        self.real_graph()
        for name, source in self.REVIEW_RA7.items():
            self.write(f"gen2/accounting/{name}", source)
        self.write("gen2/accounting/controls.py", """\
            import os
            import os as x
            import posixpath
            def typed(n: int = 1, *, eval: str = 's') -> 'eval':
                return eval
            def path(p: os.PathLike) -> str:
                return posixpath.join(os.getcwd(), 'a')
            def outer():
                import os as y
                def inner():
                    nonlocal y
                    import json as y
                inner()
                return y.dumps({})
            def shadowed():
                x = None
                def inner():
                    nonlocal x
                    x = object()
                inner()
                return x.system
            """)
        result = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, msg=result.stderr)
        for where, what in (("annotation.py:1", "reaches forbidden builtin eval()"), ("annotation_os.py:2", "uses restricted stdlib 'os.system'"),
                            ("nonlocal_rebind.py:7", "uses restricted stdlib 'os.system'"), ("posix_direct.py:1", "uses restricted stdlib 'posix'")):
            with self.subTest(source=where):
                self.assertIn(f"gen2/accounting/{where}: accounting {what}", result.stderr)
        self.assertNotIn("controls.py", result.stderr)
        self.assertIn("gen2 boundary check FAILED: 4 violation(s)", result.stderr)

    def test_scope_resolution_witnesses(self) -> None:
        """The three scope-resolution cases Astra's independent mutants showed
        untested (re-review, 'additional Python mutants'): a class body is not
        visible to its methods (module os, class-local json, method x.system:
        os.system); `global` resolves at module scope from a nested function
        even when the enclosing function rebinds the name to json; and — the
        positive control — a walrus inside a comprehension binds in the
        enclosing function, shadowing a module os alias (no violation)."""
        self.write("gen2/core/types.py", """\
            import os as x
            class K:
                import json as x
                def m(self):
                    return x.system('true')
            def f():
                import json as x
                def g():
                    global x
                    return x.system('true')
                return g
            def h(items):
                [(x := item) for item in items]
                return x.system
            """)
        result = self.run_checker()
        self.assertViolation(result, "gen2/core/types.py:5: core uses restricted stdlib 'os.system'")
        self.assertIn("gen2/core/types.py:10: core uses restricted stdlib 'os.system'", result.stderr)
        self.assertNotIn("types.py:14:", result.stderr)
        self.assertIn("gen2 boundary check FAILED: 2 violation(s)", result.stderr)

    def test_real_graph_restricts_low_level_and_alternate_surfaces(self) -> None:
        """A8 against the REAL gen2/boundaries.toml and BOUNDARIES.md (not a
        fixture config): the private modules behind the public surfaces (RA7:
        posix/nt, the modules behind os, included) and the alternate
        network/loader surfaces are restricted for a module that is granted
        none of them."""
        self.write("gen2/boundaries.toml", REAL_BOUNDARIES.read_text(encoding="utf-8"))
        self.write("docs/gen2/BOUNDARIES.md", (REPO / "docs" / "gen2" / "BOUNDARIES.md").read_text(encoding="utf-8"))
        surfaces = ("_sqlite3", "_posixsubprocess", "imaplib", "poplib", "_socket", "_ssl", "_multiprocessing", "_ctypes", "_pickle",
                    "_imp", "zipimport", "pkgutil", "dbm", "webbrowser", "wsgiref", "_signal", "_asyncio", "posix", "nt")
        self.write("gen2/accounting/sums.py", "".join(f"import {name}\n" for name in surfaces) + "import importlib\nimportlib.__import__('os')\n")
        result = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, msg=result.stderr)
        for line, name in enumerate(surfaces, start=1):
            with self.subTest(surface=name):
                self.assertIn(f"gen2/accounting/sums.py:{line}: accounting uses restricted stdlib '{name}'", result.stderr)
        self.assertIn(f"gen2/accounting/sums.py:{len(surfaces) + 2}: accounting uses restricted stdlib 'importlib.__import__'", result.stderr)

    def test_importer_cannot_reach_a_store_under_the_real_graph(self) -> None:
        """Task 0b: the dry-run importer writes no gen-2 store and reads no
        SQLite. Under the REAL gen2/boundaries.toml a gen2/importer file that
        imports the store module, the router, or sqlite3 (also its private
        module) is reported at each line; core is allowed."""
        self.real_graph()
        self.write("gen2/importer/probe.py", "from gen2.store import api\nimport gen2.router\nimport sqlite3\nimport _sqlite3\nfrom gen2.core import canonical\n")
        result = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, msg=result.stderr)
        for fragment in ("gen2/importer/probe.py:1: importer imports store", "gen2/importer/probe.py:2: importer imports router",
                         "gen2/importer/probe.py:3: importer uses restricted stdlib 'sqlite3'", "gen2/importer/probe.py:4: importer uses restricted stdlib '_sqlite3'"):
            with self.subTest(violation=fragment):
                self.assertIn(fragment, result.stderr)
        self.assertNotIn("probe.py:5:", result.stderr)

    def test_star_import_rejected(self) -> None:
        self.write("gen2/router/commit.py", "from gen2.store import *\n")
        self.assertViolation(self.run_checker(), "star import from 'gen2.store' hides its dependencies")

    # -- REPLACE in store write paths (INVARIANTS C-11) ---------------------
    def test_replace_sql_in_a_store_write_path_fails(self) -> None:
        self.write("gen2/store/db.py", 'import sqlite3\nQ = "insert or replace into operation_receipts values (?)"\nR = f"REPLACE INTO {Q}"\n')
        result = self.run_checker()
        self.assertViolation(result, "gen2/store/db.py:2: store has SQL matching forbidden pattern")
        self.assertIn("gen2/store/db.py:3: store has SQL matching forbidden pattern", result.stderr)

    def test_replace_sql_allowed_in_exempt_module_and_docstrings(self) -> None:
        self.write("gen2/tests/test_x.py", 'Q = "INSERT OR REPLACE INTO t VALUES (1)"\n')
        self.write("gen2/store/db.py", '"""Never uses INSERT OR REPLACE."""\ndef f():\n    """Nor REPLACE INTO."""\n    return "INSERT INTO t VALUES (1)"\n')
        result = self.run_checker()
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    # -- files the checker cannot analyse fail rather than pass ------------
    def test_unparseable_file_fails_loudly(self) -> None:
        self.write("gen2/core/bad.py", "def (:\n")
        self.assertViolation(self.run_checker(), "gen2/core/bad.py: cannot be parsed")

    def test_shell_code_under_package_fails(self) -> None:
        self.write("gen2/core/run.sh", "sqlite3 state.db 'delete from leases'\n")
        self.assertViolation(self.run_checker(), "gen2/core/run.sh: non-Python code")

    # -- configuration and BOUNDARIES.md drift (exit 2) ---------------------
    def test_config_names_undeclared_dependency(self) -> None:
        self.modules["router"]["may_import"] = ["core", "ghost"]
        self.assertViolation(self.run_checker(), "may_import names undeclared module 'ghost'", code=2)

    def test_config_cycle_rejected(self) -> None:
        self.modules["core"]["may_import"] = ["router"]
        self.assertViolation(self.run_checker(), "cycle: core -> router -> core", code=2)

    def test_config_grant_outside_restricted_list(self) -> None:
        self.modules["supervisor"]["stdlib_capabilities"] = ["json"]
        self.assertViolation(self.run_checker(), "stdlib capability 'json' is not in restricted_stdlib", code=2)

    def test_config_overlapping_module_paths(self) -> None:
        self.modules["policy"] = {"path": "gen2/router/policy", "boundaries": [], "may_import": [], "stdlib_capabilities": []}
        self.assertViolation(self.run_checker(), "module paths overlap", code=2)

    def test_drift_config_names_heading_missing_from_doc(self) -> None:
        self.modules["router"]["boundaries"] = ["Routr"]
        result = self.run_checker()
        self.assertViolation(result, "boundaries entry 'Routr' is not a `## ` heading", code=2)

    def test_drift_doc_component_not_accounted_for(self) -> None:
        self.headings.append("Gateway")
        self.assertViolation(self.run_checker(), "component 'Gateway' is neither mapped to a module nor listed", code=2)

    def test_drift_unmapped_entry_missing_from_doc(self) -> None:
        self.unmapped = {"Verifier": "invocation kind", "Oracle": "not real"}
        self.assertViolation(self.run_checker(), "unmapped_components entry 'Oracle' is not a `## ` heading", code=2)

    # -- rule 9: the store's write capability (task 1b) ---------------------
    STORE_PROBE = """\
        from gen2.store.api import open_store
        from gen2.store import api
        api.Store.insert(None, 'queue_entries', {})
        import gen2.store.db as d
        d.connect('store.sqlite3')
        from gen2.store.api import StoreWriteError
        x = api.adopt_in_memory
        from gen2.store.api import Store as S
        """

    def test_only_the_store_writers_reach_store_write_primitives(self) -> None:
        """A module granted `store` in may_import (so rule 2 is silent) still
        cannot reach a write primitive: by import (1, 8) or attribute chain
        (3, 5, 7). Importing the module (2, 4) or a name that merely starts
        like a primitive (6) is not reaching one. The router, the store module
        itself and the exempt tests are silent."""
        self.store_rule = list(STORE_RULE)
        self.modules["importer"] = {"path": "gen2/importer", "boundaries": [], "may_import": ["core", "store"], "stdlib_capabilities": []}
        self.write("gen2/importer/load.py", self.STORE_PROBE)
        self.write("gen2/router/commit.py", self.STORE_PROBE)
        self.write("gen2/store/api.py", "from gen2.store import db\nclass Store:\n    def insert(self): pass\ndef open_store(p):\n    db.connect(p)\n    return Store()\n")
        self.write("gen2/tests/test_store.py", self.STORE_PROBE)
        result = self.run_checker()
        self.assertEqual(result.returncode, 1, result.stderr)
        for line, primitive in ((1, "open_store"), (3, "Store"), (5, "connect"), (7, "adopt_in_memory"), (8, "Store")):
            with self.subTest(line=line):
                self.assertIn(f"gen2/importer/load.py:{line}: importer reaches store write primitive gen2.store.", result.stderr)
                self.assertRegex(result.stderr, f"load.py:{line}: .*primitive gen2\\.store\\.(api|db)\\.{primitive} ")
        for line in (2, 4, 6):
            self.assertNotIn(f"load.py:{line}:", result.stderr)
        self.assertNotIn("importer imports store", result.stderr)
        for silent in ("gen2/router/", "gen2/store/", "gen2/tests/"):
            self.assertNotIn(silent, result.stderr)
        self.assertEqual(result.stderr.count("BOUNDARY VIOLATION"), 5)

    def test_without_the_rule_the_same_tree_passes(self) -> None:
        """The control: rule 9 is what reports it (the import grant allows it)."""
        self.modules["importer"] = {"path": "gen2/importer", "boundaries": [], "may_import": ["core", "store"], "stdlib_capabilities": []}
        self.write("gen2/importer/load.py", self.STORE_PROBE)
        self.assertEqual(self.run_checker().returncode, 0)

    def test_store_rule_configuration_is_checked(self) -> None:
        for rule, fragment in ((['store_write_primitives = ["gen2.store.api.Store"]', 'store_writers = ["routr"]'], "store_writers names undeclared module 'routr'"),
                               (['store_write_primitives = ["gen2.nowhere.Store"]', 'store_writers = ["router"]'], "is not inside a declared module"),
                               (['store_write_primitives = ["gen2.store.api.Store"]'], "without store_writers")):
            with self.subTest(fragment):
                self.store_rule = rule
                self.assertViolation(self.run_checker(), fragment, code=2)

    def test_store_writes_are_the_routers_under_the_real_graph(self) -> None:
        """Under the REAL gen2/boundaries.toml: the router may reach the write
        primitives; the composition root may not — reported by rule 2 (it may
        not import store) and, independently, by rule 9."""
        self.real_graph()
        self.write("gen2/router/writes.py", "from gen2.store.api import open_store, adopt_in_memory\nfrom gen2.store import db\ndb.connect('p')\n")
        self.write("gen2/app/main.py", "from gen2.store.api import open_store\n")
        result = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("gen2/app/main.py:1: app imports store", result.stderr)
        self.assertIn("gen2/app/main.py:1: app reaches store write primitive gen2.store.api.open_store", result.stderr)
        self.assertIn("only router writes the store", result.stderr)
        self.assertNotIn("gen2/router/", result.stderr)

    def test_missing_config_file(self) -> None:
        self.write("docs/gen2/BOUNDARIES.md", "## Router\n")
        result = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)], capture_output=True, text=True, timeout=60)
        self.assertViolation(result, "gen2/boundaries.toml: not found", code=2)


if __name__ == "__main__":
    unittest.main()
