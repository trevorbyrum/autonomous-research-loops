"""The receipt basis guard through raw INSERTs, including reversed DDL."""
import unittest
from pathlib import Path
from gen2.tests.test_own_extraction_receipts import OwnCases


class OwnReceiptDDLTest(OwnCases, unittest.TestCase):
    RAW = True

    def test_reference_type(self):
        self.clone('source_extractions', dict(extraction_id='123'))
        self.doc['extraction']['extraction_id'] = 123
        self.refuse()

    def test_domain_preserved(self):
        original = (Path(__file__).resolve().parents[1] / 'store/schema/21-receipt-span-domain.sql').read_text()
        original = original[original.index('CREATE TRIGGER'):].strip().rstrip(';')
        expected = original.replace('verification_receipts_span_domain', 'verification_receipts_span_domain_v4')
        expected = expected.replace("[\"method\",\"extractor\",\"produced_by_invocation_id\",\"validation_ref\"]', '[]'", "[\"method\",\"extractor\",\"produced_by_invocation_id\",\"validation_ref\"]', '[\"extraction_id\"]'")
        expected = expected.replace('"verdict","verified_at"]\', \'[]\', 0, 0)',
            '"verdict","verified_at"]\', CASE json_extract(NEW.receipt, \'$.receipt_version\') WHEN \'verification-receipt/2\' THEN \'["detailed_checks"]\' ELSE \'[]\' END, 0, 0)')
        installed = self.case.value("SELECT sql FROM sqlite_schema WHERE name = 'verification_receipts_span_domain_v4'")
        # SQL 38 adds only the magnitude guard and its explicit diagnostic.
        # The separate cap matrices/mutants establish that new predicate.
        head, cap = installed.split('\n            -- Exact magnitude:', 1)
        tail = cap.split("\n        OR CASE WHEN json_type(s.value, '$.locator')", 1)[1]
        preserved = head + ")\n        OR CASE WHEN json_type(s.value, '$.locator')" + tail
        preserved = preserved.replace('; offsets maximum 9007199254740991', '')
        self.assertEqual(preserved, expected)
