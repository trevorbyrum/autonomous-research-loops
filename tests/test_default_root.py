import unittest
from pathlib import Path
from unittest import mock

from research_loops.__main__ import _default_root


class DefaultRootTests(unittest.TestCase):
    def test_source_tree_present_returns_source_tree_root(self):
        # The real, unmocked case: this repo's own pyproject.toml sits next to
        # research_loops/, so this must resolve to the actual repo root
        # regardless of the test runner's cwd.
        result = _default_root()
        self.assertTrue((result / "pyproject.toml").is_file())
        self.assertTrue((result / "research_loops" / "chassis").is_dir())

    def test_no_source_tree_falls_back_to_cwd(self):
        # Simulates a real (non-editable) wheel install: chassis/ ships as
        # package data either way, so its presence can't distinguish the two
        # -- only pyproject.toml (a source-only file) can. Regression test for
        # a real bug: an earlier version of this check looked for a top-level
        # chassis/ sibling, which broke once chassis moved inside
        # research_loops/ and started shipping in every install mode.
        with mock.patch("pathlib.Path.is_file", return_value=False):
            with mock.patch("pathlib.Path.cwd", return_value=Path("/some/arbitrary/project")):
                self.assertEqual(_default_root(), Path("/some/arbitrary/project"))


if __name__ == "__main__":
    unittest.main()
