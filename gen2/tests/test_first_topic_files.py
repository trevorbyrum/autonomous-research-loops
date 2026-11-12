"""A3: generated inputs are proposed data, not authority. Schema/hash oracles plus a fresh hosted fixture through CLI routes.

Scientific content comes from the draft; canned judgments prove only wiring. The test substitutes an authorized fixture sentinel,
never treats the shipped placeholder as a real inventory, and checks the actual persisted principals and mandatory completion gates.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen2.core import canonical
from gen2.router.boundary import work_id
from gen2.router.schemas import SchemaSet
from gen2.tests import children, first_topic_files as files, offline_run

TRIPWIRE = """import os, sys
def _deny(event, args):
    if event == "sqlite3.connect" or (event == "open" and isinstance(args[0], (str, bytes, os.PathLike))
                                      and os.path.realpath(os.fsdecode(args[0])).startswith({deny!r})):
        raise RuntimeError("operator process touched the private store: " + event)
sys.addaudithook(_deny)
"""
ROOT = children.path("examples/gen2/first-topic")


def inputs():
    return {p.stem: json.loads(p.read_text()) for p in ROOT.glob("*.json")}


class FirstTopic(unittest.TestCase):
    def test_generated_documents_are_reproducible_schema_valid_and_hash_true_with_a_visible_placeholder(self):
        data = inputs()
        self.assertEqual(data, files.generate(data["brief"]["document"]["created_at"]))
        schemas = SchemaSet()
        for name, schema in (("bundle", "config-bundle"), ("brief", "intake-brief"), ("contract-r1", "contract-v2"), ("contract-r2", "contract-v2")):
            doc = data[name].get("document", data[name])
            self.assertEqual(schemas.errors(doc, schema + ".schema.json"), [], name)
            if "content_hash" in doc:
                self.assertEqual(canonical.content_hash(doc), doc["content_hash"])
        ref = data["contract-r1"]["document"]["stopping_profiles"][0]["rules"][0]["params"]["sentinel_set"]
        raw = (ROOT / "sentinel.json").read_bytes()
        self.assertEqual(ref, {"content_hash": canonical.bytes_digest(raw), "size_bytes": len(raw), "media_type": "application/json"})
        self.assertEqual(data["sentinel"]["PLACEHOLDER"], "OPERATOR_STOPPING_RULE_RULING_PENDING")
        self.assertTrue(data["sentinel"]["not_for_staging"])
        self.assertTrue(all("operator_id" not in d and d["decided_at"] is None for d in data["decisions"].values()))
        self.assertEqual(data["ratings"], files.ratings(data["contract-r2"]["document"]))
        text = json.dumps(data, ensure_ascii=False)
        self.assertNotIn("fleet-a:t1", text)
        self.assertNotIn("2026-09-27", text)
        self.assertNotIn("opd_brieft101", text)

    def test_the_runbook_commands_run_as_documented_against_the_authenticated_listener(self):
        """The runbook's shell blocks run verbatim (cwd = repo, `python` = this interpreter, listener URL/token in the environment), a non-live
        fixture execution of the documented sequence with one explicit substitution: `--live` is dropped, because this fixture has no qualified
        live dispatch authority (LiveProfileRefused: profile_absent). Test-boundary work is only fixture setup and the sentinel staging a dedicated
        stack would do. A runtime tripwire (audit hook, PEP 578) in every operator subprocess refuses any open under the station directory and any
        sqlite3.connect, so no private store read can supply a decision; this is a focused regression oracle, not a sandbox. Decisions are also
        checked in the records, and the subprocess environment names neither the fixture root nor any GEN2_STORE*."""
        book = children.path("docs/gen2/FIRST-TOPIC.md").read_text()
        prepare, helper, to_scope, contracts, research = re.findall(r"```sh\n(.*?)\n```", book, re.S)
        for block, command in ((prepare, "activate_config_bundle"), (to_scope, "scope_approval"), (contracts, "draft_contract"), (research, "completion_approval")):
            self.assertIn(command, block)
        with mock.patch.object(offline_run, "TOPIC", files.TOPIC):
            run = offline_run.Offline()
            self.addCleanup(run.close)
            root = Path(run.tmp.name)
            (root / "shim").mkdir()
            apart = tempfile.TemporaryDirectory()   # the operator's TMPDIR lies outside the fixture root
            self.addCleanup(apart.cleanup)
            tmpdir, trip = Path(apart.name) / "operator-tmp", Path(apart.name) / "tripwire"
            tmpdir.mkdir()
            trip.mkdir()
            (trip / "sitecustomize.py").write_text(TRIPWIRE.format(deny=os.path.realpath(root / "station")))
            shim = root / "shim" / "python"
            shim.write_text(f'#!/bin/sh\nexec {sys.executable} "$@"\n')
            shim.chmod(0o755)
            base = {**children.env(), **run.environ, "PATH": f"{root / 'shim'}:{os.environ['PATH']}", "TMPDIR": str(tmpdir)}
            base["PYTHONPATH"] += os.pathsep + str(trip)
            self.assertFalse([k for k in base if k.startswith("GEN2_STORE")] or [v for v in base.values() if str(root) in v and v != base["PATH"]])

            def sh(block, **extra):
                return subprocess.run(["sh", "-e", "-c", block], cwd=children.path("."), env={**base, **extra}, capture_output=True, text=True, timeout=600)

            def local(block):   # the one boundary edit: the fixture has no qualified live dispatch authority, so `--live` (a permission flag) is dropped
                self.assertIn("run_topic", block)
                return block.replace(" --live", "")

            def ok(block, **extra):
                done = sh(block, **extra)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                return done
            ok(prepare, GEN2_OPERATOR_NAME="alice", GEN2_BRIEF_REVIEW_DEADLINE="2099-01-01T00:00:00Z")
            (working,) = tmpdir.iterdir()
            env = {"GEN2_FIRST_TOPIC_DIR": str(working), "GEN2_SENTINEL_REFERENCE": str(working / "sentinel-ref.json"),
                   "GEN2_FIRST_TOPIC_ID": files.TOPIC}   # the operator's shell keeps what the earlier blocks exported
            ok(helper, **env)
            ok(local(to_scope), **env)   # the walk stops at the scope wait; the approval is the runbook's own command
            refused = sh(contracts, **env)   # the shipped placeholder is refused by the runbook before anything is drafted
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("AssertionError", refused.stderr)
            (working / "sentinel.json").write_bytes(canonical.canonical_bytes([work_id("doi", "10.1/offline-a")]))
            (working / "sentinel-ref.json").write_text(json.dumps(run.sentinel))   # authorized fixture staging at the station opener
            ok(contracts, **env)
            ok(local(research), **env)
            decisions = run.records("operator_decisions")
            self.assertEqual({d["operator_id"] for d in decisions}, {"alice"})
            self.assertEqual({d["decision_id"] for d in decisions}, set(files.DECISIONS.values()))
            (scope,) = [d for d in decisions if d["kind"] == "scope_approval"]
            self.assertIn(scope["subject_hash"], {r["content_hash"] for r in run.records("scoping_reports")})
            (completion,) = [d for d in decisions if d["kind"] == "completion_approval"]
            dossier = next(d for d in run.records("dossiers") if d["dossier_revision"] == completion["subject_revision"])
            self.assertEqual(completion["subject_hash"], dossier["content_hash"])
            for contract in run.records("contract_revisions"):
                self.assertEqual(canonical.content_hash(contract["document"]), contract["content_hash"])
                self.assertEqual(contract["document"]["stopping_profiles"][0]["rules"][0]["params"]["sentinel_set"], run.sentinel)
            review = run.topic()["review"]
            self.assertEqual({g["gate"]: g["state"] for g in review["dossier"]["gates"]}, {
                "load_bearing_verification_tiers": "satisfied", "challenge_pass_completed": "satisfied", "coverage_integrity": "satisfied"})
            self.assertEqual(review["reviews"][0]["outcome"], "sufficient")
            self.assertEqual(run.records("queue_entries")[0]["status"], "completed_with_qualified_conclusions")
