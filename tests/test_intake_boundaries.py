import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from research_loops.control_store import ControlStore, default_configuration, default_work
from research_loops.input_schema import InterfaceError
from research_loops.intake import IntakeService, _research_item
from research_loops import topic_authoring


def configured():
    value = default_configuration()
    for station in value["stations"]:
        station["primary_profile"] = "terra"
        station["secondary_profile"] = "luna"
    return value


class IntakeBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        work = default_work()
        work["agent_profiles"] = {name: {"adapter": "test", "model": name, "executable": "true", "argv": []} for name in ("terra", "luna")}
        self.control = ControlStore.initialize(self.root, configuration=configured(), work=work)
        self.service = IntakeService(self.control, self.root / "topics", actor="authenticated-operator")

    def tearDown(self): self.tmp.cleanup()

    def brief(self):
        return {"schema_version": 1, "request_id": "brief-1", "topic_id": "intake-topic", "title": "Intake topic", "operator_brief": "Research the boundary.", "mode": "focused"}

    @staticmethod
    def criteria(): return [{"id": str(i), "status": "pass", "explanation": "checked"} for i in range(1, 7)]

    def test_submit_registers_exactly_one_discovery_task_and_replays(self):
        first = self.service.submit_brief(self.brief())
        replay = self.service.submit_brief(self.brief())
        self.assertEqual(first, replay)
        state = self.control.snapshot()
        self.assertEqual([item["id"] for item in state["queue"]["items"]], ["discovery.intake-topic"])
        self.assertEqual(state["work"]["intake_drafts"]["intake-topic"]["status"], "discovery_queued")

    def test_approved_research_record_has_the_ordinary_runner_contract(self):
        item = _research_item("approved", self.root / "topics" / "approved", "a" * 64)
        required = {"id", "cwd", "command", "status", "desired_state", "attempts", "restart_generation", "max_attempts", "last_pid", "completion_lock", "lane"}
        self.assertTrue(required <= set(item))
        self.assertEqual(item["lane"], "research")
        self.assertEqual(item["command"][0], str(Path(__file__).resolve().parents[1] / "research_loops" / "chassis" / "run-topic.sh"))

    def test_unknown_brief_field_is_exact_validation_error(self):
        payload = self.brief() | {"actor": "operator"}
        with self.assertRaises(InterfaceError) as raised: self.service.submit_brief(payload)
        self.assertEqual(raised.exception.code, "VALIDATION_ERROR")
        self.assertEqual(raised.exception.path, "$.actor")

    def test_discovery_stale_revision_never_changes_history(self):
        self.service.submit_brief(self.brief())
        payload = {"schema_version": 1, "request_id": "result-1", "expected_revision": 0, "topic_id": "intake-topic", "draft_revision": 1, "draft_hash": "0" * 64, "pass_kind": "criteria", "restated_intent": "Research the boundary.", "criteria": self.criteria(), "traceability": [], "questions": []}
        with self.assertRaises(InterfaceError) as raised: self.service.record_discovery_result(payload)
        self.assertEqual(raised.exception.code, "REVISION_CONFLICT")
        self.assertEqual(self.control.snapshot()["work"]["intake_drafts"]["intake-topic"]["discovery_history"], [])

    def test_approval_registers_once_and_replay_does_not_append(self):
        created = self.service.submit_brief(self.brief())
        found = self.service.record_discovery_result({"schema_version": 1, "request_id": "result-1", "expected_revision": 2, "topic_id": "intake-topic", "draft_revision": 1, "draft_hash": created["draft_hash"], "pass_kind": "criteria", "restated_intent": "Research the boundary.", "criteria": self.criteria(), "traceability": [], "questions": []})
        payload = {"schema_version": 1, "request_id": "approve-1", "expected_revision": 3, "topic_id": "intake-topic", "draft_revision": 1, "result_id": found["result_id"], "action": "approve", "rationale": "approved"}
        first = self.service.approve(payload)
        replay = self.service.approve(payload)
        self.assertEqual(first, replay)
        self.assertEqual([i["id"] for i in self.control.snapshot()["queue"]["items"]], ["discovery.intake-topic", "intake-topic"])

    def test_topic_publication_recovers_after_a_rename_failure(self):
        topic_authoring.new_topic("recover", title="Recover", brief_text="Research boundary.", dest=self.root / "topics", mode="focused")
        topic = self.root / "topics" / "recover"
        qa = topic / "QA-RECORD.md"
        qa.write_text(qa.read_text().replace("## Operator confirmation", "## Operator confirmation\n\nConfirmed."))
        (topic / "SCOPE-PROPOSAL.md").write_text("criteria pass")
        original = Path.rename
        calls = {"count": 0}
        def fail_once(path, target):
            calls["count"] += 1
            if calls["count"] == 2: raise OSError("injected rename failure")
            return original(path, target)
        with patch.object(Path, "rename", fail_once):
            with self.assertRaises(OSError): topic_authoring.approve_topic("recover", dest=self.root / "topics")
        self.assertTrue((topic / ".intake-publication.json").is_file())
        recovered = topic_authoring.approve_topic("recover", dest=self.root / "topics")
        self.assertEqual(recovered["publication_state"], "recovered")
        self.assertTrue((topic / "TOPIC.md").is_file())

    def test_approval_staging_failure_changes_no_approved_files(self):
        created = self.service.submit_brief(self.brief())
        found = self.service.record_discovery_result({"schema_version":1,"request_id":"r","expected_revision":2,"topic_id":"intake-topic","draft_revision":1,"draft_hash":created["draft_hash"],"pass_kind":"criteria","restated_intent":"x","criteria":self.criteria(),"traceability":[],"questions":[]})
        topic = self.root / "topics" / "intake-topic"; qa = topic / "QA-RECORD.md"
        qa.write_text(qa.read_text().replace("## Operator confirmation", "## Operator confirmation\n\nConfirmed.")); (topic / "SCOPE-PROPOSAL.md").write_text("pass")
        payload = {"schema_version":1,"request_id":"a","expected_revision":3,"topic_id":"intake-topic","draft_revision":1,"result_id":found["result_id"],"action":"approve","rationale":"ok"}
        with patch("research_loops.intake.topic_authoring.approve_topic", side_effect=OSError("staging failed")):
            with self.assertRaises(OSError): self.service.approve(payload)
        self.assertFalse((topic / "TOPIC.md").exists())
        result = self.service.approve(payload)
        self.assertTrue(result["registered"])
        with self.assertRaises(InterfaceError): self.service.approve(payload | {"rationale":"changed"})

    def test_approval_recovers_published_files_before_queue_registration(self):
        created = self.service.submit_brief(self.brief())
        found = self.service.record_discovery_result({"schema_version": 1, "request_id": "r", "expected_revision": 2,
            "topic_id": "intake-topic", "draft_revision": 1, "draft_hash": created["draft_hash"], "pass_kind": "criteria",
            "restated_intent": "Research boundary", "criteria": self.criteria(), "traceability": [], "questions": []})
        decision = {"schema_version": 1, "request_id": "a", "expected_revision": 3, "topic_id": "intake-topic",
            "draft_revision": 1, "result_id": found["result_id"], "action": "approve", "rationale": "Approved exact reviewed scope"}
        with patch("research_loops.intake._research_item", side_effect=OSError("registration interrupted")):
            with self.assertRaises(OSError): self.service.approve(decision)
        self.assertTrue((self.root / "topics" / "intake-topic" / "TOPIC.md").exists())
        self.assertFalse(any(i["id"] == "intake-topic" for i in self.control.snapshot()["queue"]["items"]))
        with self.assertRaises(InterfaceError):
            self.service.approve(decision | {"rationale": "different payload"})
        result = self.service.approve(decision)
        self.assertEqual(self.service.approve(decision), result)
        self.assertEqual(sum(i["id"] == "intake-topic" for i in self.control.snapshot()["queue"]["items"]), 1)
