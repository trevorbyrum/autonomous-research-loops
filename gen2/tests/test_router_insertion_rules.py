"""S4: literal Router acquisition, ceiling and table-availability refusals."""
import json
import unittest
from unittest.mock import patch

from gen2.router.boundary import Refusal
from gen2.tests import router_fixtures as content
from gen2.tests import router_fixtures as tables
from gen2.tests.router_fixtures import RAW


class RouterInsertionRulesTest(unittest.TestCase):

    def refuse(self, case, doc, detail):
        before, refused = case.state(), []
        original = case.router._evidence_writer._write_evidence

        def write(*args):
            try:
                return original(*args)
            except Refusal as exc:
                refused.append((exc.reason, exc.detail))
                raise

        with patch.object(case.router._evidence_writer, "_write_evidence", side_effect=write):
            out = case.send(doc)
        self.assertEqual((out["status"], out.get("reason"), out.get("detail")), ("rejected", "payload_invalid", detail))
        self.assertEqual(refused, [("payload_invalid", detail)])  # A SQLite/Store error cannot satisfy this.
        case.assert_audited_state(before, 1)

    def test_canonical_acquisition_binding(self):
        for section, key, value in (("extraction", "produced_by_invocation_id", "inv_verify0001"),
                ("acquisition", "route", "gateway:core"), ("acquisition", "gateway_call_ref", "gw-call:102"),
                ("acquisition", "retrieved_at", "2026-09-28T10:00:00Z")):
            with self.subTest(key=key), content.attributed_fixture(content.FULL) as case:
                doc = case.document()
                doc[section][key] = value
                self.refuse(case, doc, "canonical receipt must consume its admitted acquisition")
                self.assertEqual(case.send()["status"], "committed")

    def test_canonical_content_ceiling(self):
        self.content_ceiling(("canonical_bytes",))

    def test_acquisition_time_does_not_pool_content(self):
        for method in tables.METHODS:
            for stamp in ("2026-09-26T10:00:00Z", "2026-09-28T10:00:00Z"):
                with self.subTest(method=method, distractor_time=stamp):
                    response = json.loads(RAW)
                    response['records'] = [dict(identity=content.IDENTITY, abstract='Recorded abstract'),
                        {**content.FULL, 'identity': 'doi:10.1/other'}]
                    response['lanes'][0]['retrieved'].append('doi:10.1/other')
                    case = content.AttributedReceiptCase()
                    case.RESPONSE = json.dumps(response).encode()
                    case.setUp()
                    try:
                        # Both acquisitions authenticate the same retained exchange;
                        # two recorded provider identities resolve to the same work.
                        case.x("INSERT INTO retrieval_events VALUES ('rev_other0001', 'obs_capture001', ?, 'doi:10.1/other', 2, ?)",
                            tables.TOPIC, stamp)
                        case.x("INSERT INTO record_work_links VALUES ('rev_other0001', ?, 'dedup-1', ?)", case.work, stamp)
                        case.admit()
                        tables.seed_spans(case)
                        self.assertEqual(case.router.admit_reaccess(case.request(event_id='rev_other0001'))['status'], 'admitted')
                        self.assertEqual(sorted((case.router._detailed_checks._content_rank(a),) for a in case.store.select('source_acquisitions')), [(2,), (3,)])
                        label = 'canonical' if method == 'canonical_bytes' else 'extraction'
                        self.refuse(case, tables.document(case, method, 'full_text', spans=(tables.PAGE,)),
                            label + ' receipt tier exceeds recorded content')
                        self.refuse(case, tables.document(case, method, 'abstract'),
                            'table citation requires recorded full-text availability')
                        self.assertEqual(case.send(tables.document(case, method, 'abstract', spans=(tables.PAGE,)))['status'], 'committed')
                    finally:
                        case.tearDown()

    def test_extraction_content_ceiling(self):
        self.content_ceiling(("verifier_extraction", "validated_extraction"))

    def content_ceiling(self, methods):
        for method in methods:
            for record, tier, inflated in (({"identity": content.IDENTITY}, "bibliographic", "abstract"),
                    ({"identity": content.IDENTITY, "abstract": "Recorded abstract"}, "abstract", "full_text"),
                    (content.FULL, "full_text", "reproduced")):
                for verdict in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier"):
                    with self.subTest(method=method, tier=tier, verdict=verdict), tables.span_fixture(record) as case:
                        label = "canonical" if method == "canonical_bytes" else "extraction"
                        self.refuse(case, tables.document(case, method, inflated, verdict, (tables.PAGE,)),
                            label + " receipt tier exceeds recorded content")
                        self.assertEqual(case.send(tables.document(case, method, tier, verdict, (tables.PAGE,)))["status"], "committed")

    def test_table_availability(self):
        for method in tables.METHODS:
            for record, tier in (({"identity": content.IDENTITY}, "bibliographic"),
                    ({"identity": content.IDENTITY, "abstract": "Recorded abstract"}, "abstract")):
                for verdict in ("supports", "partially_supports", "does_not_support"):
                    with self.subTest(method=method, tier=tier, verdict=verdict), tables.span_fixture(record) as case:
                        self.refuse(case, tables.document(case, method, tier, verdict, (tables.PAGE, tables.TABLE)),
                            "table citation requires recorded full-text availability")
                        self.assertEqual(case.send(tables.document(case, method, tier, verdict, (tables.PAGE,)))["status"], "committed")

    def test_table_controls_and_hold_exemption(self):
        for method in tables.METHODS:
            for record, verdict, holds in ((content.FULL, "supports", 0),
                    ({"identity": content.IDENTITY, "abstract": "Recorded abstract"}, "cannot_assess_at_required_tier", 1)):
                with self.subTest(method=method, verdict=verdict), tables.span_fixture(record) as case:
                    out = case.send(tables.document(case, method, "abstract", verdict))
                    self.assertEqual(out["status"], "committed", out)
                    self.assertEqual(case.rows("SELECT count(*) FROM holds"), [(holds,)])
