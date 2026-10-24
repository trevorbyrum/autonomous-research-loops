"""Literal acquired content caps pending declarations of both methods."""
import json
import unittest

from gen2.tests import test_canonical_content_tiers as content
from gen2.tests.test_canonical_receipt_admission import AttributedReceiptCase
from gen2.tests.test_extraction_acquisitions import extraction_document, send
from gen2.tests.test_pending_extraction_support import METHODS
from gen2.tests.test_reaccess_admission import RAW, STAMP
from gen2.tests.router_fixtures import TOPIC, empty_outcome


def document(case, method, tier, verdict="supports"):
    doc = extraction_document(case, method)
    doc.update(access_tier=tier, verdict=verdict)
    doc["requested_for"]["required_access_tier"] = tier
    return doc


class ExtractionContentRouterTest(unittest.TestCase):
    def refuse(self, case, method, tier, control, verdict="supports"):
        before = case.state()
        out = send(case, document(case, method, tier, verdict))
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("extraction receipt tier exceeds recorded content", out["detail"])
        case.assert_audited_state(before, 1)
        self.assertEqual(send(case, document(case, method, control))["status"], "committed")

    def test_controls(self):
        for method in METHODS:
            for record, tier in (({"identity": content.IDENTITY, "title": "Fixture"}, "bibliographic"),
                    ({"identity": content.IDENTITY, "abstract": "Fixture abstract"}, "abstract"), (content.FULL, "full_text")):
                with self.subTest(method=method, tier=tier), content.attributed_fixture(record) as case:
                    doc = document(case, method, tier)
                    out = send(case, doc)
                    self.assertEqual(out["status"], "committed", out)
                    self.assertEqual(json.loads(case.value("SELECT receipt FROM verification_receipts")), doc)
                    self.assertEqual(case.rows("SELECT access_tier, extraction_method FROM verification_receipts"), [(tier, method)])
                    self.assertEqual(case.rows("SELECT response_bytes FROM source_acquisitions"), [(case.raw,)])
                    before = case.state(exclude=())
                    self.assertEqual(case.router.commit_outcome(case.env), {"status": "replayed", "receipt": out["receipt"]})
                    self.assertEqual(case.state(exclude=()), before)

    def test_inflation(self):
        for method in METHODS:
            for record, tier, control in (({"identity": content.IDENTITY}, "abstract", "bibliographic"),
                    ({"identity": content.IDENTITY, "abstract": "Fixture abstract"}, "full_text", "abstract"),
                    ({**content.FULL, "reproduced": True, "access_tier": "reproduced"}, "reproduced", "full_text")):
                for verdict in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier"):
                    with self.subTest(method=method, tier=tier, verdict=verdict), content.attributed_fixture(record) as case:
                        self.refuse(case, method, tier, control, verdict)

    def test_record_and_route(self):
        scenarios = (({"identity": content.IDENTITY, "kind": "full_text", "links": ["https://fixture.invalid/paper"],
                "has_full_text": True, "raw": {"text": "Metadata"}}, "searched_ok", (), "bibliographic"),
            ({**content.FULL, "abstract": "Fixture abstract"}, "metadata_only", (), "abstract"),
            ({"identity": content.IDENTITY}, "searched_ok", ({**content.FULL, "identity": "doi:10.1/other"},), "bibliographic"))
        for method in METHODS:
            for record, coverage, others, control in scenarios:
                with self.subTest(method=method, record=record, coverage=coverage), content.attributed_fixture(record, coverage, others) as case:
                    self.refuse(case, method, "full_text", control)

    def test_unicode(self):
        for method in METHODS:
            for field, tier in (("abstract", "abstract"), ("text", "full_text")):
                for value in ("\v\f\u00a0\u2029", "\u200b\u200d\ufeff\U000e0100", "", " \t\r\n"):
                    with self.subTest(method=method, field=field, value=repr(value)), content.attributed_fixture({"identity": content.IDENTITY, "kind": "full_text", field: value}) as case:
                        self.refuse(case, method, tier, "bibliographic")
                for value in ("\u200b.\U000e0100", "\f\u00a0文\u2029"):
                    with self.subTest(method=method, field=field, value=value), content.attributed_fixture({"identity": content.IDENTITY, "kind": "full_text", field: value}) as case:
                        self.assertEqual(send(case, document(case, method, tier))["status"], "committed")

    def test_other_work_same_response(self):
        for method in METHODS:
            with self.subTest(method=method):
                response = json.loads(RAW)
                response["records"] = [{"identity": content.IDENTITY}, {**content.FULL, "identity": "doi:10.1/other"}]
                response["lanes"][0]["retrieved"].append("doi:10.1/other")
                case = AttributedReceiptCase()
                case.RESPONSE = json.dumps(response).encode()
                case.setUp()
                try:
                    # Register the second retrieval under the original observation.
                    # Router observations are immutable; a second capture is unnecessary
                    # for this fixture's raw event-to-work binding.
                    case.x("INSERT INTO retrieval_events VALUES ('rev_other0001', 'obs_capture001', ?, 'doi:10.1/other', 2, ?)", TOPIC, STAMP)
                    other = case.register(case.producer, [("doi", "10.1/other", ["rev_other0001"])])["works"][0]["work_id"]
                    payload = {**empty_outcome(case.ACQUIRER, "interim_transition"), "source_artifacts": [
                        {"work_id": other, "source_version": "v1", "artifact_ref": case.source}]}
                    self.assertEqual(case.router.commit_outcome(case.envelope(case.producer, "op_other0001", payload, refs=[case.source]))["status"], "committed")
                    case.admit()
                    self.assertEqual(case.router.admit_reaccess(case.request(work_id=other, event_id="rev_other0001"))["status"], "admitted")
                    self.refuse(case, method, "full_text", "bibliographic")
                finally:
                    case.tearDown()

    def test_rollback_and_conflict(self):
        for method in METHODS:
            with self.subTest(method=method), content.attributed_fixture(content.FULL) as case:
                before = case.state(exclude=())
                case.faults["in_transaction:end"] = RuntimeError("after extraction ceiling")
                with self.assertRaisesRegex(RuntimeError, "after extraction ceiling"):
                    send(case, document(case, method, "full_text"))
                self.assertEqual(case.state(exclude=()), before)
                case.faults.clear()
                self.assertEqual(send(case, document(case, method, "full_text"))["status"], "committed")
                before = case.state()
                out = send(case, document(case, method, "bibliographic"))
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "operation_id_conflict"), out)
                case.assert_audited_state(before, 1)
