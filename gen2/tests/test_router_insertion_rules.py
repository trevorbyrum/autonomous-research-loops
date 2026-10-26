"""S4: literal Router refusals with SQL twins omitted only in disposable fixtures."""
import unittest
from unittest.mock import patch

from gen2.router.boundary import Refusal
from gen2.tests import store_fixtures as sf, test_canonical_content_tiers as content
from gen2.tests import test_table_availability as tables
from gen2.tests.ddl_fixtures import restore_triggers


class RouterInsertionRulesTest(unittest.TestCase):
    def isolate(self, case):
        restore_triggers(case, sf.DDL_TEXT, omit=(
            "verification_receipts_admitted_canonical", "verification_receipts_canonical_content_tier",
            "verification_receipts_extraction_content_tier", "verification_receipts_table_availability",
            "verification_receipts_own_extraction", "verification_receipts_validated_extraction"))

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
                self.isolate(case)
                doc = case.document()
                doc[section][key] = value
                self.refuse(case, doc, "canonical receipt must consume its admitted acquisition")
                self.assertEqual(case.send()["status"], "committed")

    def test_canonical_content_ceiling(self):
        self.content_ceiling(("canonical_bytes",))

    def test_extraction_content_ceiling(self):
        self.content_ceiling(("verifier_extraction", "validated_extraction"))

    def content_ceiling(self, methods):
        for method in methods:
            for record, tier, inflated in (({"identity": content.IDENTITY}, "bibliographic", "abstract"),
                    ({"identity": content.IDENTITY, "abstract": "Recorded abstract"}, "abstract", "full_text"),
                    (content.FULL, "full_text", "reproduced")):
                for verdict in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier"):
                    with self.subTest(method=method, tier=tier, verdict=verdict), tables.span_fixture(record) as case:
                        self.isolate(case)
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
                        self.isolate(case)
                        self.refuse(case, tables.document(case, method, tier, verdict, (tables.PAGE, tables.TABLE)),
                            "table citation requires recorded full-text availability")
                        self.assertEqual(case.send(tables.document(case, method, tier, verdict, (tables.PAGE,)))["status"], "committed")

    def test_table_controls_and_hold_exemption(self):
        for method in tables.METHODS:
            for record, verdict, holds in ((content.FULL, "supports", 0),
                    ({"identity": content.IDENTITY, "abstract": "Recorded abstract"}, "cannot_assess_at_required_tier", 1)):
                with self.subTest(method=method, verdict=verdict), tables.span_fixture(record) as case:
                    self.isolate(case)
                    # The SQL 34 reader must no longer supply the exemption.
                    with patch.object(case.store, "bound_extraction_receipt", side_effect=AssertionError("SQL 34 reader used")):
                        out = case.send(tables.document(case, method, "abstract", verdict))
                    self.assertEqual(out["status"], "committed", out)
                    self.assertEqual(case.rows("SELECT count(*) FROM holds"), [(holds,)])
