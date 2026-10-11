"""2d-3b2 first part: literal source identities, Router commits and raw SQL.

No quote admission or support authority is implemented by this slice.
"""
import json
from pathlib import Path

from gen2.core.canonical import bytes_digest
from gen2.router.schemas import SchemaSet
from gen2.tests.router_fixtures import TOPIC, OTHER, empty_outcome, h
from gen2.tests.test_router_workflow import Workflow

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema/source-artifact.schema.json"


class AdmissionTest(Workflow):
    def setUp(self):
        super().setUp()
        self.to_queued()
        self.grant = self.started("inv_capture001")
        events = self.observe(self.grant, "obs_source0001", ("rec-source",))
        self.work = self.register(self.grant, [("doi", "10.1/source", events)])["works"][0]["work_id"]
        self.ref = self.artifact(b"Original source bytes.")

    def record(self, **changes):
        return {"work_id": self.work, "source_version": "edition-1", "artifact_ref": self.ref, **changes}

    def send(self, records, grant=None, refs=None):
        grant = grant or self.grant
        payload = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "source_artifacts": records}
        self.env = self.envelope(grant, self.ids("op_"), payload, refs=[self.ref] if refs is None else refs)
        return self.router.commit_outcome(self.env)

    def reject(self, record, reason, **kwargs):
        before = self.state()
        out = self.send([record], **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assertEqual(self.state(), before)

    def test_control(self):
        out = self.send([self.record()])
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT topic_id, work_id, source_version, content_hash, invocation_id, recorded_by_operation_id FROM source_artifacts"),
                         [(TOPIC, self.work, "edition-1", bytes_digest(b"Original source bytes."), "inv_capture001", self.env["operation_id"])])
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", out["receipt"]["effects"]["audit_event_id"]))
        self.assertEqual(audit["source_artifacts"], [[self.work, "edition-1", bytes_digest(b"Original source bytes.")]])
        self.assertEqual(self.value("SELECT created_at FROM source_artifacts"), self.value("SELECT committed_at FROM operation_receipts WHERE operation_id = ?", self.env["operation_id"]))
        self.assertFalse(any(locked for _, locked in self.spool.reads))
        before = self.state(exclude=())
        replay = self.router.commit_outcome(self.env)
        self.assertEqual((replay["status"], replay["receipt"]), ("replayed", out["receipt"]))
        self.assertEqual(self.state(exclude=()), before)

    def test_noop_control(self):
        self.assertEqual(self.send([])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM source_artifacts"), [])

    def test_primary_authority(self):
        verifier = self.started("inv_verify0001", "verification")
        self.reject(self.record(), "kind_not_permitted", grant=verifier)

    def test_precontract_authority(self):
        self.to_scoping(OTHER)
        scope = self.started("inv_scope00001", tid=OTHER)
        self.reject(self.record(), "kind_not_permitted", grant=scope)

    def test_unretrieved_work(self):
        self.reject(self.record(work_id="wrk_absent0001"), "cross_topic")

    def test_artifact_binding(self):
        self.reject(self.record(artifact_ref={**self.ref, "content_hash": h("f")}), "payload_missing", refs=[])
        self.reject(self.record(artifact_ref={**self.ref, "media_type": "text/html"}), "payload_invalid")

    def test_forged_bytes(self):
        self.spool.blobs[self.ref["content_hash"]] = b"Forged source bytes!!!"
        self.reject(self.record(), "payload_digest_mismatch")

    def test_other_topics_bytes(self):
        self.to_queued(OTHER)
        other = self.started("inv_other00001", tid=OTHER)
        foreign = self.artifact(b"Only recorded for another topic.")
        self.assertEqual(self.send([], grant=other, refs=[foreign])["status"], "committed")
        self.reject(self.record(artifact_ref=foreign), "payload_missing", refs=[])

    def test_version_conflict_and_equal_reference(self):
        self.assertEqual(self.send([self.record()])["status"], "committed")
        original = self.rows("SELECT * FROM source_artifacts")
        changed = self.artifact(b"Revised source bytes.")
        self.reject(self.record(artifact_ref=changed), "payload_invalid", refs=[changed])
        checkpoint = self.started("inv_checkpoint1", "checkpoint")
        self.assertEqual(self.send([self.record()], grant=checkpoint, refs=[])["status"], "committed")
        self.assertEqual(self.rows("SELECT * FROM source_artifacts"), original)
        self.assertEqual(self.send([self.record(source_version="edition-2", artifact_ref=changed)], refs=[changed])["status"], "committed")
        self.assertEqual(self.rows("SELECT source_version, content_hash FROM source_artifacts ORDER BY source_version"),
                         [("edition-1", bytes_digest(b"Original source bytes.")), ("edition-2", bytes_digest(b"Revised source bytes."))])

    def test_batch_conflict_rolls_back(self):
        changed = self.artifact(b"Different bytes for the same version.")
        before = self.state()
        out = self.send([self.record(), self.record(artifact_ref=changed)], refs=[self.ref, changed])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertEqual(self.state(), before)

    def test_schema_attribution(self):
        schemas = self.schema()
        self.assertEqual(schemas.errors(self.record(), "source-artifact.schema.json"), [])
        for name in ("invocation_id", "recorded_by_operation_id", "created_at", "topic_id", "exact_match"):
            self.assertTrue(schemas.errors(self.record(**{name: "forged"}), "source-artifact.schema.json"), name)
            self.reject(self.record(**{name: "forged"}), "payload_invalid")

    def test_schema_required_identity(self):
        schemas = self.schema()
        for name in ("work_id", "source_version", "artifact_ref"):
            record = self.record()
            del record[name]
            self.assertTrue(schemas.errors(record, "source-artifact.schema.json"), name)

    def schema(self):
        return SchemaSet(Path(__file__).resolve().parents[1] / "schema", {"source-artifact.schema.json": json.loads(SCHEMA_PATH.read_text())})

    def test_schema_control(self):
        self.assertEqual(self.schema().errors(self.record(), "source-artifact.schema.json"), [])
