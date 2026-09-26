"""Counterfactual checks for schema fixtures: a negative fixture must be
refused by the rule it was written for, not by some other rule that happens
to report the same (keyword, path).

Trace: Astra 0c review C1. The mixed-disposition negative still passed after
its rule was removed, because a second, unrelated rule failed at the same
instance path; Astra showed it by running the repository's own schema check
on a temporary copy of the whole schema tree with the rule deleted. These
tests make that counterfactual a standing check. Each run copies gen2/schema
and docs/gen2/BOUNDARIES.md into a temporary root, runs
`tools/check_gen2_schemas.py --root <tmp> --part schemas` as a subprocess,
and each test asserts that the fixtures it names still behave exactly as
declared.

Unmutated, these tests restate what `make gen2-schemas` already checks. Their
purpose is the mutation inventory (tools/gen2_mutations.py, the `0CR-`
entries): the harness points one of the *_SCHEMA globals below at a copy of
that schema with one rule removed, and the test named for the rule's negative
must then fail, because that negative now validates. A kill proves the
negative depends on the rule. It does not prove the rule is the right one,
and these tests read no runtime behaviour.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "tools" / "check_gen2_schemas.py"
SCHEMAS = REPO / "gen2" / "schema"
# The checker imports gen2.core.instants; a temp root holds only the schemas.
ENV = {**os.environ, "PYTHONPATH": str(REPO)}

# Module globals: tools/gen2_mutations.py points one at a mutated copy.
EXPORT_BUNDLE_SCHEMA = SCHEMAS / "export-bundle.schema.json"
OVERRIDES = {
    "EXPORT_BUNDLE_SCHEMA": "export-bundle.schema.json",
}
FAILURE = re.compile(r"^SCHEMA CHECK FAILURE: (\S+?): (.*)$")


class FixtureCounterfactualTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(SCHEMAS, root / "gen2" / "schema")
            (root / "docs" / "gen2").mkdir(parents=True)
            shutil.copyfile(REPO / "docs" / "gen2" / "BOUNDARIES.md", root / "docs" / "gen2" / "BOUNDARIES.md")
            for name, filename in OVERRIDES.items():
                shutil.copyfile(globals()[name], root / "gen2" / "schema" / filename)
            result = subprocess.run([sys.executable, str(CHECKER), "--root", str(root), "--part", "schemas"],
                                    capture_output=True, text=True, timeout=120, env=ENV)
        cls.failures: dict[str, list[str]] = {}
        for line in result.stderr.splitlines():
            match = FAILURE.match(line)
            if match:
                cls.failures.setdefault(match.group(1), []).append(match.group(2))
        broken = {path: why for path, why in cls.failures.items() if "/examples/" not in path}
        if broken or (result.returncode != 0 and not cls.failures):
            # A mutant that breaks a schema file itself is not a rule removal:
            # erroring here makes the harness report it INVALID, never KILLED.
            raise RuntimeError(f"the schema tree does not load: {broken or result.stderr[-2000:]}")

    def assertBehaveAsDeclared(self, schema: str, *fixtures: str) -> None:
        for fixture in fixtures:
            path = f"gen2/schema/examples/{schema}/{fixture}"
            self.assertNotIn(path, self.failures, msg=f"{path}: {self.failures.get(path)}")

    # --- export-bundle: a mixed disposition names its adjudication holds (A3, C1)
    def test_a_mixed_disposition_without_its_hold_list_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-bundle", "valid-completed-topic.json",
                                    "invalid-mixed-disposition-without-an-adjudication-item.json")

    def test_a_mixed_disposition_with_an_empty_hold_list_is_refused(self) -> None:
        self.assertBehaveAsDeclared("export-bundle", "valid-completed-topic.json",
                                    "invalid-mixed-disposition-with-an-empty-adjudication-list.json")


if __name__ == "__main__":
    unittest.main()
