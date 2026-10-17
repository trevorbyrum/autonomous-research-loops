"""Literal trusted content through Router; no provider or reproduction execution."""
import json
import unittest
from contextlib import contextmanager
from functools import partial

from gen2.tests.test_canonical_receipt_admission import ReceiptCase, AttributedReceiptCase
from gen2.tests.test_reaccess_admission import RAW

IDENTITY = "doi:10.1/fixture"
FULL = {"identity": IDENTITY, "kind": "full_text", "text": "Complete fixture text"}


@contextmanager
def fixture(record, coverage="searched_ok", others=(), *, detailed=False):
    case = AttributedReceiptCase() if detailed else ReceiptCase()
    response = json.loads(RAW)
    response["records"] = [record, *others]
    response["lanes"][0]["coverage"] = coverage
    case.RESPONSE = json.dumps(response).encode()
    case.COVERAGE = coverage
    case.setUp()
    try:
        case.admit()
        yield case
    finally:
        case.tearDown()


# Other importers remain explicitly pending; this slice opts in its consumers.
attributed_fixture = partial(fixture, detailed=True)


def document(case, tier, verdict="supports"):
    doc = case.document()
    doc["access_tier"] = tier
    doc["requested_for"]["required_access_tier"] = tier
    doc["verdict"] = verdict
    return doc


class ContentRouterTest(unittest.TestCase):
    def test_controls(self):
        for record, tier in (({"identity": IDENTITY, "kind": "article", "title": "Fixture"}, "bibliographic"),
                ({"identity": IDENTITY, "kind": "article", "abstract": "Fixture abstract"}, "abstract"), (FULL, "full_text")):
            with self.subTest(tier=tier), attributed_fixture(record) as case:
                doc = document(case, tier)
                out = case.send(doc)
                self.assertEqual(out["status"], "committed", out)
                self.assertEqual(json.loads(case.value("SELECT receipt FROM verification_receipts")), doc)
                self.assertEqual(case.rows("SELECT access_tier FROM verification_receipts"), [(tier,)])
                self.assertEqual(case.rows("SELECT response_bytes FROM source_acquisitions"), [(case.raw,)])
                before = case.state(exclude=())
                self.assertEqual(case.router.commit_outcome(case.env), {"status": "replayed", "receipt": out["receipt"]})
                self.assertEqual(case.state(exclude=()), before)

    def refuse(self, case, tier, control, verdict="supports"):
        before = case.state()
        out = case.send(document(case, tier, verdict))
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assertIn("tier exceeds recorded content", out["detail"])
        self.assertEqual(case.state(), before)
        self.assertEqual(case.send(document(case, control))["status"], "committed")

    def test_inflation_all_verdicts(self):
        for verdict in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier"):
            with self.subTest(verdict=verdict), attributed_fixture({"identity": IDENTITY, "abstract": "Fixture abstract"}) as case:
                self.refuse(case, "full_text", "abstract", verdict)

    def test_link_only(self):
        with attributed_fixture({"identity": IDENTITY, "kind": "full_text", "links": ["https://fixture.invalid/paper.pdf"],
                "has_full_text": True, "raw": {"text": "Untrusted metadata"}}) as case:
            self.refuse(case, "full_text", "bibliographic")

    def test_abstract_only_route(self):
        with attributed_fixture({**FULL, "abstract": "Fixture abstract"}, "metadata_only") as case:
            self.refuse(case, "full_text", "abstract")

    def test_unrelated_record(self):
        with attributed_fixture({"identity": IDENTITY}, others=[{**FULL, "identity": "doi:10.1/other"}, "opaque metadata"]) as case:
            self.refuse(case, "full_text", "bibliographic")

    def test_full_text_is_not_reproduction(self):
        with attributed_fixture({**FULL, "access_tier": "reproduced", "reproduced": True}) as case:
            self.refuse(case, "reproduced", "full_text")

    def test_missing_content_hold(self):
        with attributed_fixture({"identity": IDENTITY, "abstract": "Fixture abstract"}) as case:
            doc = document(case, "abstract", "cannot_assess_at_required_tier")
            doc["requested_for"]["required_access_tier"] = "full_text"
            self.assertEqual(case.send(doc)["status"], "committed")
            self.assertEqual(case.rows("SELECT hold_class, recoverability, required_authority, clears_when FROM holds"),
                [("judgment", "needs_remediation", "primary", "independent verification with the required content")])

    def test_rollback_and_conflict(self):
        with attributed_fixture(FULL) as case:
            before = case.state(exclude=())
            case.faults["in_transaction:end"] = RuntimeError("after content receipt")
            with self.assertRaisesRegex(RuntimeError, "after content receipt"):
                case.send(document(case, "full_text"))
            self.assertEqual(case.state(exclude=()), before)
            case.faults.clear()
            self.assertEqual(case.send(document(case, "full_text"))["status"], "committed")
            before = case.state()
            out = case.send(document(case, "reproduced"))
            self.assertEqual((out["status"], out.get("reason")), ("rejected", "operation_id_conflict"))
            self.assertEqual(case.state(), before)

    def test_unicode_blank(self):
        # Literal Unicode separators/ignorables, selected independently of SQL.
        for value in ("\v", "\f\u00a0", "\u0085", "\u1680", "\u2007", "\u2028", "\u2029",
                "\u202f", "\u205f", "\u3000", "\u200b", "\ufeff", "\U000e0100"):
            for field, tier in (("abstract", "abstract"), ("text", "full_text")):
                with self.subTest(value=repr(value), field=field), attributed_fixture({"identity": IDENTITY, "kind": "full_text", field: value}) as case:
                    self.refuse(case, tier, "bibliographic")

    def test_unicode_text_controls(self):
        for value in ("\f\u00a0Results\u2028", "\u200bFindings\ufeff", "\u200d文\U000e0100", "."):
            for field, tier in (("abstract", "abstract"), ("text", "full_text")):
                with self.subTest(value=value, field=field), attributed_fixture({"identity": IDENTITY, "kind": "full_text", field: value}) as case:
                    self.assertEqual(case.send(document(case, tier))["status"], "committed")
