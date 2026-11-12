"""A3: generated inputs are proposed data, not authority. Schema/hash oracles plus a fresh hosted fixture through CLI routes.

Scientific content comes from the draft; canned judgments prove only wiring. The test substitutes an authorized fixture sentinel,
never treats the shipped placeholder as a real inventory, and checks the actual persisted principals and mandatory completion gates.
"""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from gen2.core import canonical
from gen2.router.boundary import work_id
from gen2.router.schemas import SchemaSet
from gen2.tests import children, first_topic_files as files, offline_run

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

    def test_proposed_files_load_through_authenticated_routes_and_keep_all_completion_gates(self):
        book = children.path("docs/gen2/FIRST-TOPIC.md").read_text()
        prepare, bind_contracts = re.findall(r"python - <<'PY'\n(.*?)\nPY", book, re.S)
        helper = re.search(r"cat > .*?/decision.py\" <<'PY'\n(.*?)\nPY", book, re.S)[1]
        with mock.patch.object(offline_run, "TOPIC", files.TOPIC):
            run = offline_run.Offline()
            self.addCleanup(run.close)
            root = children.path("examples/gen2/first-topic")
            working = Path(run.tmp.name) / "operator-inputs"
            working.mkdir()
            for path in root.glob("*.json"):
                (working / path.name).write_bytes(path.read_bytes())
            def read(name):
                return json.loads((working / (name + ".json")).read_text())
            def status(name):
                _, shown = run.cli(["status", "--topic", files.TOPIC])
                path = working / (name + ".json")
                path.write_text(json.dumps(shown))
                return str(path)
            _, station = run.cli(["status"])
            (working / "station-status.json").write_text(json.dumps(station))
            env = {"GEN2_FIRST_TOPIC_DIR": str(working), "GEN2_OPERATOR_NAME": "alice", "GEN2_BRIEF_REVIEW_DEADLINE": "2099-01-01T00:00:00Z",
                   "GEN2_SENTINEL_REFERENCE": str(working / "sentinel-ref.json")}
            def execute(code, *args):
                return children.python(["-c", code, *args], env={**children.env(), **env}, capture_output=True, text=True, timeout=30)
            prepared = execute(prepare)
            self.assertEqual(prepared.returncode, 0, prepared.stderr)
            run.command("activate_config_bundle", read("bundle"))
            def intake():
                run.command("create_topic", read("topic"))
                run.command("open_brief", read("brief"))
            def decide(kind, shown=None):
                out = execute(helper, kind, *([shown] if shown else []))
                self.assertEqual(out.returncode, 0, out.stderr)
                return run.command("apply_operator_decision", json.loads(out.stdout))
            def contract():
                refused = execute(bind_contracts)  # the runbook refuses its shipped placeholder
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn("AssertionError", refused.stderr)
                (working / "sentinel.json").write_bytes(canonical.canonical_bytes([work_id("doi", "10.1/offline-a")]))
                (working / "sentinel-ref.json").write_text(json.dumps(run.sentinel))  # authorized fixture setup from the station opener
                bound = execute(bind_contracts)
                self.assertEqual(bound.returncode, 0, bound.stderr)
                run.command("draft_contract", read("contract-r1"))
                decide("rating_approval")
                run.command("draft_contract", read("contract-r2"))
                decide("contract_approval")
            def complete():
                decide("completion_approval", status("completion-status"))
            run.intake, run.approve_contract, run.approve_completion = intake, contract, complete
            run.confirm_brief = lambda: decide("brief_confirmation")
            run.approve_scope = lambda: decide("scope_approval", status("scope-status"))
            run.open_review = lambda: run.command("open_review", {"episode_id": "rev_ft_review01", "topic_id": files.TOPIC, "kind": "fixed_cadence"})
            with mock.patch.object(run, "records", side_effect=AssertionError("private operator read")):
                self.assertEqual(run.walk(), "done")
            decisions = run.records("operator_decisions")
            self.assertEqual({d["operator_id"] for d in decisions}, {"alice"})
            self.assertEqual({d["decision_id"] for d in decisions}, set(files.DECISIONS.values()))
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
