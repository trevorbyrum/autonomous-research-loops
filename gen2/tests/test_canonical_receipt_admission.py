"""Canonical receipts consume literal trusted exchanges, inside Router commits."""
import json

from gen2.tests.router_fixtures import TOPIC, empty_outcome
from gen2.tests.test_reaccess_admission import AcquisitionCase, STAMP


class ReceiptCase(AcquisitionCase):
    def setUp(self):
        super().setUp()
        text = self.artifact(b"Fixture claim")
        payload = {**empty_outcome("inv_capture001", "interim_transition"),
            "claims": [{"claim_id": "clm_fixture001", "revision": 1, "text_ref": text,
                "load_bearing": False, "required_access_tier": None}]}
        self.assertEqual(self.router.commit_outcome(self.envelope(self.producer, "op_claim001", payload, refs=[text]))["status"], "committed")

    def document(self):
        return {"receipt_version": "verification-receipt/1", "verification_receipt_id": "ver_fixture001", "topic_id": TOPIC,
            "claim": {"claim_id": "clm_fixture001", "claim_revision": 1}, "source": {"work_id": self.work, "source_version": "v1"},
            "cited_spans": [{"start": 0, "end": 5, "locator": {"kind": "section", "value": "Abstract"}}],
            "obtained_content_hash": self.source["content_hash"], "access_tier": "abstract",
            "requested_for": {"use": "sampled", "required_access_tier": "abstract"},
            "acquisition": {"route": "gateway:crossref", "retrieved_at": STAMP, "gateway_call_ref": "gw-call:101", "cache_reuse": True},
            "extraction": {"method": "canonical_bytes", "extractor": "canonical/1", "produced_by_invocation_id": self.ACQUIRER, "validation_ref": None},
            "producer_invocation_id": "inv_capture001", "verifier_invocation_id": "inv_verify0001", "verifier_capability_id": self.verifier["capability_id"],
            "quote_check_id": None, "checks": {"exact_quote": {"status": "not_applicable", "normalization_version": "none/1", "source_artifact_hash": self.source["content_hash"]},
                "numeric_units": "not_applicable", "denominators": "not_applicable", "negation": "checked_ok", "qualifications": "checked_ok"},
            "adjudication": None, "verdict": "supports", "verified_at": STAMP}

    def send(self, doc=None, op="op_verify001"):
        payload = {**empty_outcome("inv_verify0001", "interim_transition"), "verification_receipts": [doc or self.document()]}
        self.env = self.envelope(self.verifier, op, payload)
        return self.router.commit_outcome(self.env)

    def rejected(self, doc=None):
        before = self.state()
        out = self.send(doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("must consume its admitted acquisition", out["detail"])
        self.assertEqual(self.state(), before)

    def admit(self):
        self.assertEqual(self.router.admit_reaccess(self.request())["status"], "admitted")
        from gen2.tests.extraction_receipt_fixtures import seed
        seed(self)


class ReceiptTest(ReceiptCase):
    def test_control(self):
        self.admit()
        out = self.send()
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(json.loads(self.value("SELECT receipt FROM verification_receipts")), self.document())
        self.assertEqual(self.rows("SELECT source_version, access_tier, extraction_method, extraction_invocation_id, verifier_invocation_id FROM verification_receipts"),
            [("v1", "abstract", "canonical_bytes", self.ACQUIRER, "inv_verify0001")])
        self.assertEqual(self.rows("SELECT response_bytes FROM source_acquisitions"), [(self.raw,)])
        self.assertEqual(self.rows("SELECT * FROM holds"), [])
        before = self.state(exclude=())
        self.assertEqual(self.router.commit_outcome(self.env), {"status": "replayed", "receipt": out["receipt"]})
        self.assertEqual(self.state(exclude=()), before)

    def test_missing_admission(self):
        # Artifact, source, call reference and valid canonical bytes already exist.
        self.rejected()
        self.admit()
        self.assertEqual(self.send()["status"], "committed")

    def test_lineage(self):
        self.admit()
        for section, key, value in (("source", "source_version", "v2"), ("acquisition", "route", "gateway:core"),
                ("acquisition", "gateway_call_ref", "gw-call:102"), ("acquisition", "retrieved_at", "2026-09-28T10:00:00Z"),
                ("extraction", "produced_by_invocation_id", "inv_verify0001")):
            with self.subTest(key=key):
                doc = self.document()
                doc[section][key] = value
                self.rejected(doc)
        self.assertEqual(self.send()["status"], "committed")

    def test_conflicting_replay(self):
        self.admit()
        self.assertEqual(self.send()["status"], "committed")
        before = self.state()
        doc = self.document()
        doc["acquisition"]["route"] = "gateway:core"
        out = self.send(doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "operation_id_conflict"), out)
        self.assertEqual(self.state(), before)

    def test_rollback(self):
        self.admit()
        before = self.state(exclude=())
        self.faults["in_transaction:end"] = RuntimeError("fixture after canonical receipt")
        with self.assertRaisesRegex(RuntimeError, "after canonical receipt"):
            self.send()
        self.assertEqual(self.state(exclude=()), before)
        self.faults.clear()
        self.assertEqual(self.send()["status"], "committed")


class OtherAcquirerReceiptTest(ReceiptCase):
    ACQUIRER = "inv_other0001"
    EVENT_ID = "rev_other0001"
    test_control = ReceiptTest.test_control
