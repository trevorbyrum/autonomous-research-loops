import copy, json, tempfile, unittest
from contextlib import contextmanager
from pathlib import Path

from research_loops import topic_authoring
from research_loops.contract_publication import checkpoint_publisher
from research_loops.checkpoints.service import apply_decision, CheckpointError
from research_loops.control_store import ControlStore, default_configuration
from unittest.mock import patch


class PublicationRecoveryTests(unittest.TestCase):
    def managed_review(self, root, *, second_invalid=False):
        directory = self.approved_topic(root)
        configuration = default_configuration()
        for station in configuration["stations"]:
            station.update(primary_profile="test", secondary_profile="test")
        control = ControlStore.initialize(root, configuration=configuration,
            agent_profiles={"test": {"adapter": "codex", "model": "test", "executable": "/bin/true", "argv": []}},
            queue={"revision": 0, "items": [{"id": "topic", "cwd": str(directory), "status": "queued", "completion_lock": "old"}]})
        with control.transaction() as state:
            topic = control.ensure_topic_work(state, "topic", inventory_version="old")
            topic.update(research_iterations_completed=25, next_research_ordinal=26,
                active_episode_id="episode", review_state="awaiting_operator")
            state["work"]["episodes"]["episode"] = {"episode_id": "episode", "topic_id": "topic", "state": "awaiting_operator"}
            for identity in ("one", "two"):
                proposal = self.proposal(identity, text=f"New exact question {identity}")
                proposal.update(episode_id="episode", status="pending")
                if identity == "two" and second_invalid: proposal["content"]["text"] = ""
                state["work"]["proposals"][identity] = proposal
        payload = {"schema_version": 1, "request_id": "decision", "expected_revision": control.snapshot()["revision"],
            "topic_id": "topic", "episode_id": "episode", "decisions": [
                {"proposal_id": identity, "proposal_version": 1, "action": "approve", "reason": "exact change approved"}
                for identity in ("one", "two")]}
        return control, directory, payload

    def test_invalid_second_decision_rolls_back_database_and_all_contract_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); control, directory, payload = self.managed_review(root, second_invalid=True)
            before = control.snapshot()
            files = [(directory / name).read_bytes() for name in ("TOPIC.md", "SEMANTIC-STATE.json")]
            with self.assertRaises(RuntimeError):
                apply_decision(control, payload, publisher=checkpoint_publisher(root))
            self.assertEqual(control.snapshot(), before)
            self.assertEqual(files, [(directory / name).read_bytes() for name in ("TOPIC.md", "SEMANTIC-STATE.json")])

    def test_crash_after_files_before_decision_commit_recovers_same_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); control, directory, payload = self.managed_review(root)
            publisher = checkpoint_publisher(root)
            with patch("research_loops.checkpoints.service._commit_decision", side_effect=OSError("injected precommit crash")):
                with self.assertRaises(OSError): apply_decision(control, payload, publisher=publisher)
            snapshot = control.snapshot()
            self.assertEqual(snapshot["work"]["topics"]["topic"]["review_state"], "publishing_decision")
            self.assertEqual(snapshot["queue"]["items"][0]["completion_lock"], "old")
            self.assertTrue((directory / ".checkpoint-contract-publication.json").exists())
            with self.assertRaises(CheckpointError):
                apply_decision(control, payload | {"topic_id": "different"}, publisher=publisher)
            result = apply_decision(control, payload, publisher=publisher)
            self.assertEqual(result["next_research_ordinal"], 26)
            self.assertEqual(apply_decision(control, payload, publisher=publisher), result)
            obligations = json.loads((directory / "SEMANTIC-STATE.json").read_text())["obligations"]
            for identity in ("one", "two"):
                self.assertEqual(sum(o["text"] == f"New exact question {identity}" for o in obligations), 1)
            self.assertFalse((directory / ".checkpoint-contract-publication.json").exists())
            self.assertEqual(control.snapshot()["queue"]["items"][0]["completion_lock"],
                control.snapshot()["work"]["topics"]["topic"]["inventory_version"])

    def test_cleanup_failure_replays_committed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); control, directory, payload = self.managed_review(root)
            publisher = checkpoint_publisher(root)
            with patch.object(publisher, "finalize", side_effect=OSError("postcommit cleanup")):
                with self.assertRaises(OSError): apply_decision(control, payload, publisher=publisher)
            self.assertEqual(control.snapshot()["work"]["topics"]["topic"]["review_state"], "eligible")
            result = apply_decision(control, payload, publisher=publisher)
            self.assertTrue(result["resolved"])
            self.assertFalse((directory / ".checkpoint-contract-publication.json").exists())

    def test_partial_decision_retains_review_hold_then_resumes_same_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); control, directory, payload = self.managed_review(root)
            first = payload | {"decisions": [payload["decisions"][0]]}
            result = apply_decision(control, first, publisher=checkpoint_publisher(root))
            self.assertEqual(result["remaining_proposal_ids"], ["two"])
            self.assertEqual(control.snapshot()["work"]["topics"]["topic"]["review_state"], "awaiting_operator")
            second = payload | {"request_id": "decision-2", "expected_revision": control.snapshot()["revision"], "decisions": [payload["decisions"][1]]}
            self.assertTrue(apply_decision(control, second, publisher=checkpoint_publisher(root))["resolved"])
            self.assertEqual([i["id"] for i in control.snapshot()["queue"]["items"]], ["topic"])

    def approved_topic(self, root):
        topics = root / "topics"; topic_authoring.new_topic("topic", title="Topic", brief_text="Original question.", dest=topics, mode="focused")
        d = topics / "topic"; q = d / "QA-RECORD.md"; q.write_text(q.read_text().replace("## Operator confirmation", "## Operator confirmation\n\nConfirmed.")); (d / "SCOPE-PROPOSAL.md").write_text("pass")
        topic_authoring.approve_topic("topic", dest=topics); return d

    def proposal(self, ident, text="New exact question"):
        return {"topic_id":"topic","proposal_id":ident,"proposal_version":1,"kind":"addition","content":{"text":text,"source_ref":"SRC"}}

    def test_invalid_second_bundle_leaves_original_contract_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); d=self.approved_topic(root); before=(d/"TOPIC.md").read_bytes(), (d/"SEMANTIC-STATE.json").read_bytes()
            bad=self.proposal("bad"); bad["content"]={"text":""}
            with self.assertRaises(Exception): checkpoint_publisher(root).publish_bundle([(self.proposal("one"),None),(bad,None)])
            self.assertEqual(before, ((d/"TOPIC.md").read_bytes(), (d/"SEMANTIC-STATE.json").read_bytes()))

    def test_journal_recovery_never_duplicates_addition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); d=self.approved_topic(root); publisher=checkpoint_publisher(root)
            result=publisher.publish_bundle([(self.proposal("one"),None)])
            self.assertTrue((d/".checkpoint-contract-publication.json").exists())
            # Re-running the same durable publication result leaves one exact obligation.
            publisher.publish_bundle([(self.proposal("one"),None)])
            state=json.loads((d/"SEMANTIC-STATE.json").read_text())
            self.assertEqual(sum(o["text"] == "New exact question" for o in state["obligations"]), 1)
            for record in result:
                Path(record["publication_journal"]).unlink(missing_ok=True)
            self.assertFalse((d/".checkpoint-contract-publication.json").exists())

    def test_symlinked_journal_is_rejected_without_touching_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); d=self.approved_topic(root); outside=root/"outside"; outside.write_text("safe")
            (d/".checkpoint-contract-publication.json").symlink_to(outside)
            with self.assertRaises(Exception): checkpoint_publisher(root).prepare_bundle([(self.proposal("one"),None)])
            self.assertEqual(outside.read_text(), "safe")
