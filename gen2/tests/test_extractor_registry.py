"""Registry declarations never grant support; all databases are disposable."""
import json
from unittest.mock import patch

from gen2.tests import operator_fixtures as op
from gen2.tests.test_extraction_records import RecordCase


def approval(version=1, **changes):
    return {"registry_version": version, "operator_id": "fixture-operator", "reason": "approve fixture tools",
        "tools": [{"extractor_identity": "tool-a", "family": "family-a"},
            {"extractor_identity": "tool-b", "family": "family-b"}], **changes}


class RegistryTest(RecordCase):
    def test_control(self):
        self.assertEqual(self.send(source_extractions=[self.extraction()])["status"], "committed")
        self.assertEqual(self.rows("SELECT extractor_identity, extractor_registry_version FROM source_extractions"), [("tool-a", 1)])
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), [])

    def test_membership(self):
        reads = []
        original = self.spool.read
        def read(digest, **key):
            if digest == self.output["content_hash"]:
                reads.append(digest)
            return original(digest, **key)
        for changes in ({"extractor_identity": name} for name in ("unknown", "alias-a", "Tool-a", " tool-a", "tool-a ", "tool-a\x00alias")):
            with self.subTest(changes=changes):
                with patch.object(self.spool, "read", read):
                    out = self.send(op="op_badtool001", source_extractions=[self.extraction(**changes)])
                self.assertEqual((out["status"], out["reason"]), ("rejected", "payload_invalid"))
                self.assertEqual(reads, [], "unknown tools refuse before output authentication")
        self.assertEqual(self.rows("SELECT * FROM source_extractions"), [])

    def test_revision(self):
        out = self.send(source_extractions=[self.extraction(extractor_registry_version=2)])
        self.assertEqual((out["status"], out["reason"]), ("rejected", "payload_invalid"))

    def test_registration(self):
        doc = approval(2, tools=[{"extractor_identity": "tool-a", "family": "reclassified"}])
        self.assertEqual(self.router.register_extractor_registry(doc)["status"], "registered")
        before = self.state(exclude=())
        self.assertEqual(self.router.register_extractor_registry(doc)["status"], "replayed")
        self.assertEqual(self.router.register_extractor_registry({**doc, "reason": "changed"})["status"], "rejected")
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.rows("SELECT family FROM extractor_tools WHERE extractor_identity = 'tool-a' ORDER BY registry_version"),
            [("family-a",), ("reclassified",)])

    def test_duplicates(self):
        out = self.router.register_extractor_registry(approval(2, tools=[approval()["tools"][0]] * 2))
        self.assertEqual((out["status"], out["reason"]), ("rejected", "request_invalid"))

    def test_order(self):
        self.assertEqual(self.router.register_extractor_registry(approval(3))["status"], "registered")
        self.assertEqual(self.router.register_extractor_registry(approval(2))["status"], "rejected")

    def test_rollback(self):
        before = self.state(exclude=())
        original = self.router._store.insert
        def insert(table, row):
            if table == "extractor_tools":
                raise RuntimeError("registry fault")
            return original(table, row)
        with patch.object(self.router._store, "insert", insert), self.assertRaisesRegex(RuntimeError, "registry fault"):
            self.router.register_extractor_registry(approval(2))
        self.assertEqual(self.state(exclude=()), before)


class RegistryOperatorTest(op.OperatorTestCase):
    def test_authority(self):
        doc = approval()
        del doc["operator_id"]
        self.assertEqual(self.command("register_extractor_registry", doc, token=op.EXPORTER_TOKEN)[0], 403)
        self.assertEqual(self.command("register_extractor_registry", {**doc, "operator_id": "forged"})[0], 400)
        self.assertEqual(self.rows("SELECT * FROM extractor_registry_revisions"), [])

    def test_control(self):
        doc = approval()
        del doc["operator_id"]
        code, reply = self.command("register_extractor_registry", doc)
        self.assertEqual((code, reply["status"]), (200, "registered"))
        self.assertEqual(self.rows("SELECT operator_id FROM extractor_registry_revisions"), [("alice",)])
