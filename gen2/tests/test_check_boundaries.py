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

CHECKER = Path(__file__).resolve().parents[2] / "tools" / "check_boundaries.py"

DOC_HEADINGS = ["Router", "Station supervisor", "Verifier"]

BASE_MODULES: dict[str, dict] = {
    "core": {"path": "gen2/core", "boundaries": [], "may_import": [], "stdlib_capabilities": []},
    "store": {"path": "gen2/store", "boundaries": ["Router"], "may_import": ["core"], "stdlib_capabilities": ["sqlite3"]},
    "router": {"path": "gen2/router", "boundaries": ["Router"], "may_import": ["core", "store"], "stdlib_capabilities": []},
    "supervisor": {"path": "gen2/supervisor", "boundaries": ["Station supervisor"], "may_import": ["core"], "stdlib_capabilities": ["subprocess", "os.exec*"]},
    "tests": {"path": "gen2/tests", "boundaries": [], "may_import": ["*"], "stdlib_capabilities": ["*"]},
}
RESTRICTED = ["sqlite3", "subprocess", "os.system", "os.exec*", "urllib.request", "importlib.import_module"]


def render_config(modules: dict[str, dict], unmapped: dict[str, str] | None = None) -> str:
    lines = [
        "schema_version = 1",
        'package_root = "gen2"',
        'boundaries_doc = "docs/gen2/BOUNDARIES.md"',
        'forbidden_imports = ["research_loops", "research_gateway"]',
        'forbidden_calls = ["eval", "exec", "compile", "__import__"]',
        f"restricted_stdlib = {json.dumps(RESTRICTED)}",
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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")

    def run_checker(self) -> subprocess.CompletedProcess:
        self.write("gen2/boundaries.toml", render_config(self.modules, self.unmapped))
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
        self.write("gen2/core/types.py", "x = eval('1')\ny = __import__('gen2.supervisor')\nimport builtins\nbuiltins.exec('pass')\n")
        result = self.run_checker()
        self.assertViolation(result, "gen2/core/types.py:1: core calls forbidden builtin eval()")
        self.assertIn("gen2/core/types.py:2: core calls forbidden builtin __import__()", result.stderr)
        self.assertIn("gen2/core/types.py:4: core calls forbidden builtin exec()", result.stderr)

    def test_star_import_rejected(self) -> None:
        self.write("gen2/router/commit.py", "from gen2.store import *\n")
        self.assertViolation(self.run_checker(), "star import from 'gen2.store' hides its dependencies")

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

    def test_missing_config_file(self) -> None:
        self.write("docs/gen2/BOUNDARIES.md", "## Router\n")
        result = subprocess.run([sys.executable, str(CHECKER), "--root", str(self.root)], capture_output=True, text=True, timeout=60)
        self.assertViolation(result, "gen2/boundaries.toml: not found", code=2)


if __name__ == "__main__":
    unittest.main()
