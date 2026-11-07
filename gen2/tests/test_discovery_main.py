"""The discovery child's `python -m` entry, in fresh processes. Oracle: the files the process leaves in the scratch directory and its exit status.
The offline command is the production `child.main` with the canned gateway injected (tests/discovery_entry.py); the production command has
no transport, which is the pre-T19 fence: it must refuse, name the closed entrance, write nothing and not even read the token file."""
import json
import tempfile
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.tests import children
from gen2.tests.test_discovery_child import Fixture, proposal


class MainTest(Fixture, unittest.TestCase):
    def run_module(self, module, env, extra=None):
        return children.python(["-m", module, str(self.root)], cwd=self.root, env={**env, **(extra or {})}, capture_output=True, text=True)

    def files(self):
        return sorted(p.name for p in self.root.iterdir() if p.is_file() and p.name != "gateway-token")   # what the process wrote (the token file is the fixture's)

    def test_the_offline_command_produces_a_real_result_in_a_fresh_process(self):
        env = self.stage([proposal(1, obligation_ids=[]), proposal(2, lane="semanticscholar", obligation_ids=[])])
        done = self.run_module("gen2.tests.discovery_entry", env)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        result = canonical.parse_json_strict((self.root / "discovery-result.json").read_bytes())
        observed = [(o["observation"]["lane"], o["observation"]["coverage_state"], o["observation"]["result_count"], o["observation"]["request"]["proposal_ref"])
                    for s in result["searches"] for o in s["out"]["observations"]]
        self.assertEqual(observed, [("crossref", "searched_ok", 1, "inv_proposer01:p1"), ("semanticscholar", "searched_ok", 1, "inv_proposer01:p2")])
        outcome = canonical.parse_json_strict((self.root / "outcome.json").read_bytes())
        self.assertEqual((outcome["claims"], outcome["scoping_reports"], outcome["verification_receipts"]), ([], [], []))
        self.assertEqual(self.files(), ["discovery-result.json", "outcome.json"])

    def test_malformed_input_is_refused_and_writes_nothing(self):
        good = self.stage([proposal(1, obligation_ids=[])])
        raw = json.loads((self.root / "inputs" / "input.json").read_bytes())
        cases = {"an input that does not match its pinned digest": {**good, "GEN2_INPUT_DIGEST": "sha256:" + "0" * 64},
                 "no digest at all": {k: v for k, v in good.items() if k != "GEN2_INPUT_DIGEST"},
                 "no gateway address": {k: v for k, v in good.items() if k != "GEN2_GATEWAY_URL"},
                 "a token file that is not there": {**good, "GEN2_SECRET_GATEWAY_TOKEN_FILE": str(self.root / "absent")}}
        for name, env in cases.items():
            with self.subTest(name):
                done = self.run_module("gen2.tests.discovery_entry", env)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertIn("gen2.discovery.child:", done.stderr)
                self.assertNotIn("Traceback", done.stderr)
                self.assertEqual(self.files(), [])
        for name, edit in (("an input that is another purpose's", lambda d: d.update(purpose="other")), ("an input with no view", lambda d: d.pop("view"))):
            with self.subTest(name):
                changed = {**raw}
                edit(changed)
                data = canonical.canonical_bytes(changed)
                (self.root / "inputs" / "input.json").write_bytes(data)
                done = self.run_module("gen2.tests.discovery_entry", {**good, "GEN2_INPUT_DIGEST": canonical.bytes_digest(data)})
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(self.files(), [])

    def test_the_production_command_without_a_transport_refuses_before_touching_anything(self):
        env = self.stage([proposal(1, obligation_ids=[])])
        for name, variables in (("with credentials in the environment", env), ("with a token file that does not exist", {**env, "GEN2_SECRET_GATEWAY_TOKEN_FILE": str(self.root / "absent")})):
            with self.subTest(name):
                done = self.run_module("gen2.discovery.child", variables)
                self.assertEqual(done.returncode, 2)
                self.assertIn("the live gateway entrance is closed", done.stderr)
                self.assertEqual(self.files(), [])
        done = children.python(["-m", "gen2.discovery.child"], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual((done.returncode, "usage" in done.stderr), (2, True))

    def test_a_diagnostic_never_carries_text_from_the_input(self):
        """Caller-controlled names (a filter key, an unknown property, a path) with a marker and a newline in them never reach stdout or stderr: exit 2 prints one fixed line."""
        marker = "CALLER_SENTINEL_148\nFORGED: gen2.discovery.child: ok"
        cases = {"a schema-valid proposal with an unsupported filter name": proposal(1, filters={marker: "x"}, obligation_ids=[]),
                 "a proposal the schema refuses, by an unknown property named with the marker": {**proposal(1, obligation_ids=[]), marker: 1},
                 "a proposal with a wrong-type filter value under a marked name": proposal(1, filters={"limit": marker}, obligation_ids=[])}
        for name, bad in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                env = self.stage([proposal(2, obligation_ids=[]), bad])
                done = self.run_module("gen2.tests.discovery_entry", env)
                self.assertEqual(done.returncode, 2)
                self.assertEqual(done.stdout, "")
                self.assertNotIn("CALLER_SENTINEL", done.stdout + done.stderr)
                self.assertNotIn("FORGED", done.stdout + done.stderr)
                self.assertEqual(done.stderr.count("\n"), 1, "one line")
                self.assertTrue(done.stderr.startswith("gen2.discovery.child: stopped: "), done.stderr)
                self.assertEqual(self.files(), [])
        # the paths the input names are not echoed either
        self.tearDown()
        self.setUp()
        done = self.run_module("gen2.tests.discovery_entry", {**self.stage([proposal(1, obligation_ids=[])]), "GEN2_SECRET_GATEWAY_TOKEN_FILE": str(self.root / "PATH_SENTINEL_148")})
        self.assertEqual((done.returncode, "PATH_SENTINEL_148" in done.stderr + done.stdout), (2, False))
