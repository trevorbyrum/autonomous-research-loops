"""Router schema and strict JSON regressions, using only disposable stores."""
import json
import unittest

from gen2.tests.test_store_span_domain import BAD, DUPLICATES
from gen2.tests.test_table_availability import content, document, METHODS, PAGE
from gen2.tests.router_fixtures import empty_outcome


class SpanRouterTest(unittest.TestCase):
    def test_malformed_pairs(self):
        for method in METHODS:
            for predicate, cases in BAD.items():
                for spans in cases:
                    with self.subTest(method=method, predicate=predicate, spans=spans), content.fixture({"identity": content.IDENTITY}) as case:
                        doc = document(case, method, "bibliographic", spans=spans)
                        before = case.state()
                        out = case.send(doc)
                        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
                        self.assertIn("/cited_spans", out["detail"])
                        self.assertEqual(case.state(), before)
                        doc["cited_spans"] = [PAGE]
                        self.assertEqual(case.send(doc)["status"], "committed")
                        self.assertEqual(json.loads(case.value("SELECT receipt FROM verification_receipts")), doc)

    def test_duplicate_pairs_at_payload_boundary(self):
        for method in METHODS:
            for spans in DUPLICATES + (None,):
                with self.subTest(method=method, spans=spans), content.fixture({"identity": content.IDENTITY}) as case:
                    doc = document(case, method, "bibliographic", spans=(PAGE,))
                    # Stage actual duplicate bytes; a Python dict would lose the defect.
                    payload = {**empty_outcome("inv_verify0001", "interim_transition"), "verification_receipts": [doc]}
                    env = case.envelope(case.verifier, "op_verify001", payload)
                    if spans is None:
                        raw = json.dumps(payload).replace('"access_tier": "bibliographic"',
                            '"access_tier":"bibliographic","access_tier":"full_text"')
                    else:
                        doc["cited_spans"] = "__RAW_SPANS__"
                        raw = json.dumps(payload).replace('"__RAW_SPANS__"', spans)
                    encoded = raw.encode()
                    digest = case.spool.put(encoded, media_type="application/json")
                    env.update(payload_digest=digest, payload_size_bytes=len(encoded))
                    before = case.state()
                    out = case.router.commit_outcome(env)
                    self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
                    self.assertIn("duplicate object key", out["detail"])
                    self.assertEqual(case.state(), before)
                    self.assertEqual(case.send(document(case, method, "bibliographic", spans=(PAGE,)))["status"], "committed")
