"""Actual staged JSON bytes exercise strict parsing, schema and Store writes."""
import json
import unittest

from gen2.tests import test_store_exact_spans as raw
from gen2.tests.test_table_availability import content, document, METHODS, PAGE
from gen2.tests.router_fixtures import empty_outcome


class ExactSpanRouterTest(unittest.TestCase):
    def stage(self, case, method, numeral=None, transform=lambda d: d):
        doc = document(case, method, "bibliographic", spans=(PAGE,))
        payload = {**empty_outcome("inv_verify0001", "interim_transition"), "verification_receipts": [doc]}
        env = case.envelope(case.verifier, "op_verify001", payload)
        if numeral is not None: doc["cited_spans"] = "__RAW_SPANS__"
        text = json.dumps(payload)
        if numeral is not None: text = text.replace('"__RAW_SPANS__"', numeral)
        encoded = transform(text).encode()
        digest = case.spool.put(encoded, media_type="application/json")
        env.update(payload_digest=digest, payload_size_bytes=len(encoded))
        return case.router.commit_outcome(env)

    def test_pairs_at_payload_boundary(self):
        cases = [(raw.numeric(k, n), lambda d: d, "not exactly representable")
            for k in ("start", "end") for n in ("1.00000000000000001", "-1e-999")]
        cases += [(None, lambda d, k=k: d.replace('"' + k + '":', '"' + k + '\\u0000suffix":'), "no value is allowed")
            for k in ("start", "end", "locator", "kind", "value", "extraction", "method", "checks", "status")]
        page = json.dumps([PAGE])
        cases += [(None, lambda d: d.replace('"cited_spans": ' + page,
            '"cited_spans\\u0000suffix":' + page + ',"cited_spans":[{"start":0,"end":5,"locator":{"kind":"table","value":"T"}}]'), "no value is allowed")]
        for method in METHODS:
            for numeral, transform, detail in cases:
                with self.subTest(method=method, numeral=numeral), content.fixture({"identity": content.IDENTITY}) as case:
                    before = case.state()
                    out = self.stage(case, method, numeral, transform)
                    self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
                    self.assertIn(detail, out["detail"])
                    self.assertEqual(case.state(), before)
                    self.assertEqual(self.stage(case, method, raw.numeric("start", "5.0"))["status"], "committed")
                    retained = case.value("SELECT cited_spans FROM verification_receipts")
                    self.assertEqual(retained, '[{"end":9,"locator":{"kind":"page","value":"2"},"start":5}]')

    def test_canonical_exponent_control(self):
        for method in METHODS:
            with self.subTest(method=method), content.fixture({"identity": content.IDENTITY}) as case:
                self.assertEqual(self.stage(case, method, raw.numeric("start", "1e30"))["status"], "committed")
                self.assertIn('"start":1e+30', case.value("SELECT cited_spans FROM verification_receipts"))
