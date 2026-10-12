"""Recorded table access through disposable Router stores; no providers execute."""
import json
import unittest

from gen2.tests import test_canonical_content_tiers as content
from gen2.tests.test_canonical_receipt_admission import ReceiptCase
from gen2.tests.test_extraction_acquisitions import extraction_document
from gen2.tests.test_store_table_availability import TABLE, PAGE
from gen2.tests.test_reaccess_admission import RAW, STAMP
from gen2.tests.router_fixtures import TOPIC, empty_outcome

METHODS = ("canonical_bytes", "verifier_extraction", "validated_extraction")


def document(case, method, tier, verdict="supports", spans=(TABLE,)):
    doc = extraction_document(case, method)
    if method != "canonical_bytes":
        doc["extraction"]["produced_by_invocation_id"] = case.verifier["invocation_id"]
    doc.update(access_tier=tier, verdict=verdict, cited_spans=list(spans))
    doc["requested_for"]["required_access_tier"] = tier
    return doc


class TableRouterTest(unittest.TestCase):
    def refuse(self, case, doc):
        before = case.state()
        out = case.send(doc)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("table citation requires recorded full-text availability", out["detail"])
        self.assertEqual(case.state(), before)
        control = {**doc, "cited_spans": [PAGE]}
        self.assertEqual(case.send(control)["status"], "committed")

    def test_insufficient_and_mixed(self):
        for method in METHODS:
            for record, tier in (({"identity": content.IDENTITY}, "bibliographic"),
                    ({"identity": content.IDENTITY, "abstract": "Recorded abstract"}, "abstract")):
                for verdict in ("supports", "partially_supports", "does_not_support"):
                    for spans in ((TABLE,), (PAGE, TABLE)):
                        with self.subTest(method=method, tier=tier, verdict=verdict, spans=spans), content.fixture(record) as case:
                            self.refuse(case, document(case, method, tier, verdict, spans))

    def test_controls_readback_replay(self):
        for method in METHODS:
            with self.subTest(method=method), content.fixture(content.FULL) as case:
                doc = document(case, method, "full_text", spans=(PAGE, TABLE))
                out = case.send(doc)
                self.assertEqual(out["status"], "committed", out)
                self.assertEqual(json.loads(case.value("SELECT receipt FROM verification_receipts")), doc)
                self.assertEqual(case.rows("SELECT response_bytes FROM source_acquisitions"), [(case.raw,)])
                before = case.state(exclude=())
                self.assertEqual(case.router.commit_outcome(case.env), {"status": "replayed", "receipt": out["receipt"]})
                self.assertEqual(case.state(exclude=()), before)

    def test_cannot_assess_keeps_hold(self):
        for method in METHODS:
            for record, tier in (({"identity": content.IDENTITY}, "bibliographic"),
                    ({"identity": content.IDENTITY, "abstract": "Recorded abstract"}, "abstract")):
                with self.subTest(method=method, tier=tier), content.fixture(record) as case:
                    doc = document(case, method, tier, "cannot_assess_at_required_tier")
                    doc["requested_for"]["required_access_tier"] = "full_text"
                    doc["checks"].update(numeric_units="unavailable", denominators="unavailable", negation="not_checked", qualifications="unavailable")
                    out = case.send(doc)
                    self.assertEqual(out["status"], "committed", out)
                    self.assertEqual(json.loads(case.value("SELECT receipt FROM verification_receipts")), doc)
                    self.assertEqual(case.rows("SELECT hold_class, recoverability, required_authority, clears_when FROM holds"),
                        [("judgment", "needs_remediation", "primary", "independent verification with the required content")])

    def test_evidence_shapes(self):
        scenarios = (({"identity": content.IDENTITY, "kind": "full_text", "links": ["https://fixture.invalid/table"],
                "has_full_text": True, "raw": {"text": "Table 1"}}, "searched_ok", "bibliographic"),
            ({**content.FULL, "text": "\u200b\ufeff"}, "searched_ok", "bibliographic"),
            ({**content.FULL, "abstract": "Recorded abstract"}, "metadata_only", "abstract"),
            ({"identity": content.IDENTITY, "kind": "series", "rows": [{"DataValue": "2"}], "row_count": 1,
                "method": "GetData", "query": {"TableName": "T10101"}}, "searched_ok", "bibliographic"))
        for method in METHODS:
            for record, coverage, tier in scenarios:
                with self.subTest(method=method, record=record), content.fixture(record, coverage,
                        [{**content.FULL, "identity": "doi:10.1/other"}]) as case:
                    self.refuse(case, document(case, method, tier))

    def test_borrowed_acquisition_or_work(self):
        for method in METHODS:
            for selector in ("version", "work"):
                with self.subTest(method=method, selector=selector):
                    response = json.loads(RAW)
                    response["records"] = [{"identity": content.IDENTITY}, {**content.FULL, "identity": "doi:10.1/other"}]
                    response["lanes"][0]["retrieved"].append("doi:10.1/other")
                    case = ReceiptCase()
                    case.RESPONSE = json.dumps(response).encode()
                    case.setUp()
                    try:
                        case.x("INSERT INTO retrieval_events VALUES ('rev_other0001', 'obs_capture001', ?, 'doi:10.1/other', 2, ?)", TOPIC, STAMP)
                        if selector == "work":
                            work = case.register(case.producer, [("doi", "10.1/other", ["rev_other0001"])])["works"][0]["work_id"]
                        else:
                            work = case.work
                            case.x("INSERT INTO record_work_links VALUES ('rev_other0001', ?, 'dedup-1', ?)", work, STAMP)
                        version = "v2" if selector == "version" else "v1"
                        payload = {**empty_outcome(case.ACQUIRER, "interim_transition"), "source_artifacts": [
                            {"work_id": work, "source_version": version, "artifact_ref": case.source}]}
                        self.assertEqual(case.router.commit_outcome(case.envelope(case.producer, "op_other0001", payload,
                            refs=[case.source]))["status"], "committed")
                        case.admit()
                        self.assertEqual(case.router.admit_reaccess(case.request(work_id=work, source_version=version,
                            event_id="rev_other0001"))["status"], "admitted")
                        self.assertEqual(sorted(case.rows("SELECT recorded_tier_rank FROM source_acquisition_content_tiers")), [(1,), (3,)])
                        self.refuse(case, document(case, method, "bibliographic"))
                    finally:
                        case.tearDown()

    def test_rollback_and_conflict(self):
        for method in METHODS:
            with self.subTest(method=method), content.fixture(content.FULL) as case:
                doc = document(case, method, "full_text")
                before = case.state(exclude=())
                case.faults["in_transaction:end"] = RuntimeError("after table receipt")
                with self.assertRaisesRegex(RuntimeError, "after table receipt"):
                    case.send(doc)
                self.assertEqual(case.state(exclude=()), before)
                case.faults.clear()
                self.assertEqual(case.send(doc)["status"], "committed")
                before = case.state()
                out = case.send({**doc, "cited_spans": [PAGE]})
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "operation_id_conflict"), out)
                self.assertEqual(case.state(), before)

    def test_tier_diagnostic(self):
        for method in METHODS:
            with self.subTest(method=method), content.fixture({"identity": content.IDENTITY}) as case:
                before = case.state()
                out = case.send(document(case, method, "full_text"))
                self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
                self.assertIn("tier exceeds recorded content", out["detail"])
                self.assertEqual(case.state(), before)
