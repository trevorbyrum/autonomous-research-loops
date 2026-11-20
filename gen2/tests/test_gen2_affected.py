"""Black-box tests for tools/gen2_affected.py (the per-PR affected-test selector).

Trace: Trevor's ruling 2026-11-20, "affected tests per PR". Each test builds a
throwaway git repository with a base commit and a head commit, runs the tool as
a subprocess and compares its output with a hand-written expectation.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "gen2_affected.py"
T = "gen2/tests/"
BASE_FILES = {
    "gen2/store/c.py": "X = 1\n", "gen2/store/b.py": "from gen2.store import c\n",
    "gen2/store/a.py": "import gen2.store.b\n", "gen2/store/lonely.py": "Y = 1\n",
    T + "helper.py": "from gen2.store import a\n", T + "test_a.py": "from gen2.store import a\n",
    T + "test_b.py": "import gen2.tests.helper\n", T + "test_c.py": "import gen2.tests.helper\n",
    T + "test_d.py": "from gen2.store import lonely\n", T + "test_e.py": "run('child.py')\n", T + "child.py": "from gen2.store import lonely\n",
    "docs/gen2/NOTES.md": "x\n", "docs/gen2/FIXTURE.md": "x\n", T + "test_f.py": "open('FIXTURE.md')\n",
    "gen2/pk/b.py": "X = 1\n", "gen2/pk/a.py": "from .b import X\n", "gen2/pk/sub/c.py": "from ..d import Y\n",
    "gen2/pk/d.py": "Y = 1\n", T + "test_r.py": "from gen2.pk import a\n", T + "test_s.py": "import gen2.pk.sub.c\n",
    "gen2/pk/job.py": "Z = 1\n", "gen2/pk/orders.py": "cmd = (py, '-m', 'gen2.pk.job')\n", T + "test_o.py": "import gen2.pk.orders\n",
}


def build(root: str, head_files: dict[str, str | None], base_files: dict[str, str] = BASE_FILES) -> None:
    """Commit base_files, then head_files (None deletes), tagging `base` and `head`."""
    def run(*cmd: str) -> str:
        return subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True).stdout
    run("git", "init", "-q", "-b", "main")
    run("git", "config", "user.email", "t@example.com")
    run("git", "config", "user.name", "t")
    for files in (base_files, head_files):
        for name, text in files.items():
            path = Path(root, name)
            if text is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        run("git", "add", "-A")
        run("git", "commit", "-q", "-m", "c")
        run("git", "tag", "-f", "base" if files is base_files else "head")


def select(head_files: dict[str, str | None], base_files: dict[str, str] = BASE_FILES) -> str:
    with tempfile.TemporaryDirectory() as root:
        build(root, head_files, base_files)
        return subprocess.run([sys.executable, str(TOOL), "base", "head"], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


class AffectedSelectorTest(unittest.TestCase):
    def test_deleted_function_still_selects_its_importers(self):
        # The #201 case: the module (and function) is gone at head; base's graph names the importers.
        self.assertEqual(select({"gen2/store/lonely.py": None}), "test_d\ntest_e")

    def test_transitive_import_reaches_the_test(self):
        # test_a -> a -> b -> c: a change to c selects test_a (and test_b/test_c through helper -> a).
        self.assertEqual(select({"gen2/store/c.py": "X = 2\n"}), "test_a\ntest_b\ntest_c")

    def test_shared_helper_is_full(self):
        self.assertTrue(select({T + "helper.py": "# changed\n"}).startswith("FULL: gen2/tests/helper.py is a shared"))

    def test_docs_only_selects_none(self):
        self.assertEqual(select({"docs/gen2/NOTES.md": "y\n"}), "NONE: docs-only change")

    def test_unmapped_file_is_full(self):
        self.assertTrue(select({"gen2/prompts/p.txt": "x\n"}).startswith("FULL: gen2/prompts/p.txt"))
        self.assertTrue(select({"tools/x.py": "x = 1\n"}).startswith("FULL: tools/x.py"))

    def test_changed_test_selects_itself(self):
        self.assertEqual(select({T + "test_e.py": "# edited\n"}), "test_e")

    def test_unimported_production_selects_none(self):
        self.assertEqual(select({"gen2/store/new.py": "Z = 1\n"}), "NONE: no test module imports the changed code")

    def test_subprocess_child_mentioned_by_a_test_is_an_edge(self):
        self.assertEqual(select({"gen2/store/lonely.py": "Y = 2\n"}), "test_d\ntest_e")

    def test_relative_imports_are_edges(self):
        self.assertEqual(select({"gen2/pk/b.py": "X = 2\n"}), "test_r")  # from .b import X
        self.assertEqual(select({"gen2/pk/d.py": "Y = 2\n"}), "test_s")  # from ..d import Y

    def test_launch_target_by_string_or_unresolvable_target(self):
        self.assertEqual(select({"gen2/pk/job.py": "Z = 2\n"}), "test_o")  # -m gen2.pk.job
        dynamic = {**BASE_FILES, "gen2/pk/dyn.py": "import importlib\nimportlib.import_module(name)\n", T + "test_dyn.py": "import gen2.pk.dyn\n"}
        self.assertIn("test_dyn", select({"gen2/store/lonely.py": "Y = 2\n"}, dynamic).split("\n"))  # a target no string names

    def test_only_inert_documentation_is_exempt(self):
        self.assertTrue(select({"tools/x.md": "x\n"}).startswith("FULL: tools/x.md"))
        self.assertTrue(select({"gen2/core/x.md": "x\n"}).startswith("FULL: gen2/core/x.md"))
        self.assertTrue(select({"docs/gen2/phase-status.json": "{}\n"}).startswith("FULL: docs/gen2/phase-status.json"))
        self.assertTrue(select({"docs/gen2/FIXTURE.md": "y\n"}).startswith("FULL: docs/gen2/FIXTURE.md is a quoted name"))  # a test reads it

    def test_a_multi_module_selection_reaches_the_runner_in_one_invocation(self):
        files = {name: (ROOT / name).read_text() for name in ("Makefile", "tools/gen2_affected.py")}
        files["tools/gen2_test.py"] = "import sys\nopen('argv.txt', 'a').write(repr(sys.argv[1:]) + '\\n')\n"
        files |= {f"gen2/requirements{name}.txt": "\n" for name in ("", "-dev", "-build")}
        with tempfile.TemporaryDirectory() as root:
            build(root, {"gen2/store/c.py": "X = 2\n"}, BASE_FILES | files)
            Path(root, ".v").mkdir()
            Path(root, ".v/.gen2-installed").touch()
            subprocess.run(["make", "gen2-affected", "BASE=base", "HEAD=head", "GEN2_VENV=.v", f"PYTHON={sys.executable}"],
                           cwd=root, check=True, capture_output=True)
            self.assertEqual(Path(root, "argv.txt").read_text(), "['--modules', 'test_a', 'test_b', 'test_c']\n")


class RunnerModulesTest(unittest.TestCase):
    def run_runner(self, modules, *flags):
        with tempfile.TemporaryDirectory() as root:
            for rel in ("tools", "gen2/tests"):
                Path(root, rel).mkdir(parents=True)
            for name in ("gen2_test.py", "gen2_ci_evidence.py", "gen2_coverage.py", "gen2_mutation_runner.py", "gen2_workers.py"):
                shutil.copy(ROOT / "tools" / name, Path(root, "tools", name))
            for name, body in {"ok": "def test_ok(self): pass", "bad": "def test_bad(self): self.fail('ran')",
                               "boom": "def test_x(self): pass\nimport no_such_module_anywhere"}.items():
                Path(root, f"gen2/tests/test_{name}.py").write_text(f"import unittest\nclass T(unittest.TestCase):\n    {body}\n")
            env = {**os.environ, "GEN2_TEST_LOG": str(Path(root, "log"))}
            return subprocess.run([sys.executable, "tools/gen2_test.py", *flags, "--modules", *modules], cwd=root, env=env, capture_output=True, text=True)

    def test_a_selected_module_that_fails_to_import_fails_the_run(self):
        for flags in ((), ("--workers", "2")):
            self.assertNotEqual(self.run_runner(["test_ok", "test_boom"], *flags).returncode, 0, flags)
            self.assertNotEqual(self.run_runner(["test_ok", "test_missing"], *flags).returncode, 0, flags)

    def test_the_module_filter_holds_with_workers(self):
        done = self.run_runner(["test_ok"], "--workers", "2")  # test_bad would fail the run if the filter were dropped
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
