"""Black-box tests for tools/gen2_affected.py (the per-PR affected-test selector).

Trace: Trevor's ruling 2026-11-20, "affected tests per PR". Each test builds a
throwaway git repository with a base commit and a head commit, runs the tool as
a subprocess and compares its output with a hand-written expectation.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools" / "gen2_affected.py"
T = "gen2/tests/"
BASE_FILES = {
    "gen2/store/c.py": "X = 1\n", "gen2/store/b.py": "from gen2.store import c\n",
    "gen2/store/a.py": "import gen2.store.b\n", "gen2/store/lonely.py": "Y = 1\n",
    T + "helper.py": "from gen2.store import a\n", T + "test_a.py": "from gen2.store import a\n",
    T + "test_b.py": "import gen2.tests.helper\n", T + "test_c.py": "import gen2.tests.helper\n",
    T + "test_d.py": "from gen2.store import lonely\n", T + "test_e.py": "run('child.py')\n", T + "child.py": "from gen2.store import lonely\n",
    "docs/gen2/NOTES.md": "x\n",
}


def select(head_files: dict[str, str | None]) -> str:
    """Commit BASE_FILES, then head_files (None deletes); return the tool's output."""
    with tempfile.TemporaryDirectory() as root:
        def run(*cmd: str) -> str:
            return subprocess.run(cmd, cwd=root, check=True, capture_output=True, text=True).stdout
        run("git", "init", "-q", "-b", "main")
        run("git", "config", "user.email", "t@example.com")
        run("git", "config", "user.name", "t")
        for files in (BASE_FILES, head_files):
            for name, text in files.items():
                path = Path(root, name)
                if text is None:
                    path.unlink()
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            run("git", "add", "-A")
            run("git", "commit", "-q", "-m", "c")
            run("git", "tag", "-f", "base" if files is BASE_FILES else "head")
        return run(sys.executable, str(TOOL), "base", "head").strip()


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


if __name__ == "__main__":
    unittest.main()
