"""2d-3b3 first part: computed literal results through Router commits.

Fixtures use a disposable store and spool; no NLI/provider executes. Notification,
adjudication and disposition consumers belong to the next part of the split.
"""
import json
from pathlib import Path

from gen2.core.canonical import bytes_digest
from gen2.router.schemas import SchemaSet
from gen2.tests.router_fixtures import OTHER, TOPIC, empty_outcome
from gen2.tests.test_router_workflow import Workflow

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema/quote-check.schema.json"


class QuotesCase(Workflow):
    def setUp(self):
        super().setUp()
        self.to_queued()
        self.capture_grant = self.started("inv_capture001")
        events = self.observe(self.capture_grant, "obs_quote00001", ("quote-record",))
        self.work = self.register(self.capture_grant, [("doi", "10.1/quote", events)])["works"][0]["work_id"]
        self.source = self.artifact(b"<effect observed>")
        self.text = self.artifact(b"effect observed")
        payload = {**empty_outcome("inv_capture001", "interim_transition"),
            "source_artifacts": [{"work_id": self.work, "source_version": "v1", "artifact_ref": self.source}],
            "claims": [{"claim_id": "clm_quote00001", "revision": 1, "text_ref": self.text, "load_bearing": False, "required_access_tier": None}]}
        out = self.router.commit_outcome(self.envelope(self.capture_grant, "op_capture001", payload, refs=[self.source, self.text]))
        self.assertEqual(out["status"], "committed", out)
        self.grant = self.started("inv_verify0001", "verification")

    def record(self, **changes):
        return {"check_id": "qck_quote00001", "claim_id": "clm_quote00001", "claim_revision": 1,
            "work_id": self.work, "source_version": "v1", "artifact_ref": self.source,
            "quoted_text": "effect observed", "span_start": 1, "span_end": 16, **changes}

    def send(self, records, grant=None, refs=(), **sections):
        grant = grant or self.grant
        payload = {**empty_outcome(grant["invocation_id"], "interim_transition", grant["topic_id"]), "quote_checks": records, **sections}
        self.env = self.envelope(grant, self.ids("op_"), payload, refs=refs)
        return self.router.commit_outcome(self.env)

    def accepted(self, record=None, **kwargs):
        out = self.send([record or self.record()], **kwargs)
        self.assertEqual(out["status"], "committed", out)
        return out

    def rejected(self, record, reason, detail=None, **kwargs):
        before = self.state()
        out = self.send([record], **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        if detail is not None:
            self.assertIn(detail, out.get("detail", ""))
        self.assertEqual(self.state(), before)

    def result(self):
        raw = self.value("SELECT match_result FROM quote_checks WHERE check_id = 'qck_quote00001'")
        self.assertIsNotNone(raw)
        return json.loads(raw)

    def receipt_document(self, status="matched", verdict="supports"):
        path = Path(__file__).resolve().parents[1] / "schema/examples/verification-receipt/valid-load-bearing-full-text.json"
        doc = json.loads(path.read_text())["instance"]
        doc.update(verification_receipt_id="ver_quote00001", topic_id=TOPIC,
            claim={"claim_id": "clm_quote00001", "claim_revision": 1}, source={"work_id": self.work, "source_version": "v1"},
            cited_spans=[{"start": 1, "end": 16, "locator": {"kind": "section", "value": "Results"}}],
            obtained_content_hash=self.source["content_hash"], requested_for={"use": "sampled", "required_access_tier": "full_text"},
            producer_invocation_id="inv_capture001", verifier_invocation_id="inv_verify0001", verifier_capability_id=self.grant["capability_id"],
            quote_check_id="qck_quote00001", verdict=verdict, verified_at="2026-09-27T10:00:00Z")
        doc["extraction"].update(produced_by_invocation_id="inv_verify0001")
        doc["checks"]["exact_quote"].update(status=status, source_artifact_hash=self.source["content_hash"], normalization_version="quote-nfc-safe/2+ucd15.0.0")
        del doc["checks"]["tier0"]
        return doc


class AdmissionTest(QuotesCase):
    def test_exact_control(self):
        out = self.accepted()
        digest = bytes_digest(b"<effect observed>")
        self.assertEqual(self.result(), {"quoted_bytes_hex": "656666656374206f62736572766564", "source_span_bytes_hex": "656666656374206f62736572766564",
            "expected_artifact_hash": digest, "artifact_hash": digest, "span_start": 1, "span_end": 16,
            "status": "match", "reason": None, "normalized_quote": "effect observed", "normalized_source": "effect observed", "diagnostic": None,
            "normalization": ["quote-nfc-safe", "2+ucd15.0.0"], "protection": "quote-protection/5",
            "token_versions": ["decimal-expression/2", "english-negation/3", "si9-2022+clinical/2"]})
        self.assertEqual(self.rows("SELECT topic_id, work_id, source_version, verifier_invocation_id, recorded_by_operation_id, exact_match, quote_quarantined, nli_signal FROM quote_checks"),
            [(TOPIC, self.work, "v1", "inv_verify0001", self.env["operation_id"], "matched", 0, "not_run")])
        self.assertEqual(self.value("SELECT checked_at FROM quote_checks"), out["receipt"]["committed_at"])
        self.assertFalse(any(locked for _, locked in self.spool.reads))
        audit = json.loads(self.value("SELECT detail FROM audit_events WHERE audit_event_id = ?", out["receipt"]["effects"]["audit_event_id"]))
        self.assertEqual(audit["quote_checks"], ["qck_quote00001"])

    def test_noop_control(self):
        self.assertEqual(self.send([])["status"], "committed")
        self.assertEqual(self.rows("SELECT check_id FROM quote_checks"), [])

    def test_normalized(self):
        self.accepted(self.record(quoted_text="effect\tobserved"))
        result = self.result()
        self.assertEqual((result["status"], result["normalized_quote"], result["normalized_source"], result["quoted_bytes_hex"]),
            ("match_normalized", "effect observed", "effect observed", "656666656374096f62736572766564"))
        self.assertEqual(self.rows("SELECT exact_match, quote_quarantined FROM quote_checks"), [("matched", 0)])

    def test_near(self):
        source = self.bind_source("a" * 99 + "c")
        self.accepted(self.record(artifact_ref=source, source_version="v2", quoted_text="a" * 99 + "b", span_start=0, span_end=100))
        result = self.result()
        self.assertEqual((result["status"], result["reason"], result["normalized_quote"], result["normalized_source"]),
            ("mismatch", "near_match", "a" * 99 + "b", "a" * 99 + "c"))
        self.assertEqual(result["diagnostic"], {"similarity": 0.99,
            "differing_spans": [{"quote_start": 99, "quote_end": 100, "source_start": 99, "source_end": 100}],
            "measure": ["difflib.SequenceMatcher.ratio/min-bidirectional/autojunk=False", "3.12.3"]})
        self.assertEqual(self.rows("SELECT exact_match, quote_quarantined FROM quote_checks"), [("mismatch", 1)])
        self.assertEqual(self.rows("SELECT * FROM source_lifecycle"), [])

    def bind_source(self, text):
        source = self.artifact(text.encode())
        out = self.send([], grant=self.capture_grant, refs=[source],
            source_artifacts=[{"work_id": self.work, "source_version": "v2", "artifact_ref": source}])
        self.assertEqual(out["status"], "committed", out)
        return source

    def test_protected_and_label_ignored(self):
        source = self.bind_source("dose 5 mg")
        self.accepted(self.record(source_version="v2", artifact_ref=source, quoted_text="dose 6 mg", span_start=0, span_end=9, exact_match="matched"))
        self.assertEqual((self.result()["status"], self.result()["reason"], self.result()["diagnostic"]), ("mismatch", "protected_number", None))
        self.assertEqual(self.rows("SELECT exact_match, quote_quarantined FROM quote_checks"), [("mismatch", 1)])

    def test_matching_label_ignored(self):
        self.accepted(self.record(exact_match="mismatch"))
        self.assertEqual((self.result()["status"], self.value("SELECT quote_quarantined FROM quote_checks")), ("match", 0))

    def test_wrong_version(self):
        self.rejected(self.record(source_version="missing-version"), "payload_invalid", detail="needs a recorded work/source version")

    def test_wrong_hash(self):
        foreign = self.artifact(b"<forged content!>")
        self.accepted(self.record(artifact_ref=foreign), refs=[foreign])
        self.assertEqual((self.result()["status"], self.result()["reason"], self.result()["expected_artifact_hash"], self.result()["artifact_hash"]),
            ("mismatch", "artifact_version", self.source["content_hash"], foreign["content_hash"]))
        self.assertEqual(self.value("SELECT source_artifact_hash FROM quote_checks"), self.source["content_hash"])

    def test_forged_bytes(self):
        self.spool.blobs[self.source["content_hash"]] = b"<forged content!>"
        self.rejected(self.record(), "payload_digest_mismatch")

    def test_artifact_reference(self):
        self.rejected(self.record(artifact_ref={**self.source, "size_bytes": 99}), "payload_invalid")

    def test_claim_binding(self):
        self.rejected(self.record(claim_revision=2), "payload_invalid", detail="needs a recorded claim revision")
        self.to_queued(OTHER)
        other = self.started("inv_verify0002", "verification", tid=OTHER)
        self.rejected(self.record(), "payload_invalid", detail="needs a recorded claim revision", grant=other)

    def test_authority(self):
        self.rejected(self.record(), "kind_not_permitted", grant=self.capture_grant)

    def test_replay_and_conflict(self):
        out = self.accepted()
        before = self.state(exclude=())
        replay = self.router.commit_outcome(self.env)
        self.assertEqual((replay["status"], replay["receipt"]), ("replayed", out["receipt"]))
        self.assertEqual(self.state(exclude=()), before)
        self.rejected(self.record(quoted_text="changed"), "payload_invalid")

    def test_support_control(self):
        self.accepted(verification_receipts=[self.receipt_document()])
        self.assertEqual(self.rows("SELECT verdict FROM verification_receipts"), [("supports",)])

    def test_partial_support_blocked(self):
        self.rejected(self.record(quoted_text="wrong"), "payload_invalid",
            detail="governed quarantined quote cannot supply support",
            verification_receipts=[self.receipt_document("mismatch", "partially_supports")])

    def test_schema_control(self):
        self.assertEqual(self.schema().errors(self.record(), "quote-check.schema.json"), [])

    def test_schema_attribution(self):
        for key in ("producer_invocation_id", "verifier_invocation_id", "recorded_by_operation_id", "quote_quarantined", "match_result", "nli_signal"):
            self.assertTrue(self.schema().errors(self.record(**{key: "forged"}), "quote-check.schema.json"), key)

    def schema(self):
        return SchemaSet(Path(__file__).resolve().parents[1] / "schema", {"quote-check.schema.json": json.loads(SCHEMA_PATH.read_text())})
