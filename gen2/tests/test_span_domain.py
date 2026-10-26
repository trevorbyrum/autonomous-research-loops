"""Router schema and strict JSON regressions, using only disposable stores."""
import json
import unittest

from gen2.tests.test_table_availability import content, document, METHODS, PAGE, span_fixture
from gen2.tests.detailed_receipt_fixtures import attach_checks
from gen2.tests.router_fixtures import empty_outcome


def span(**changes):
    return {**PAGE, **changes}


def locator(**changes):
    return span(locator={**PAGE["locator"], **changes})


BAD = {
    "array_max": [[PAGE] * 51],
    "span_object": [["page"], [0], [None], [True], [[]]],
    "span_members": [[span(extra=0)]],
    "start_type": [[span(start=v)] for v in (None, True, "0", [], {})]
        + [[{k: v for k, v in span(other=0).items() if k != "start"}]],
    "start_integer": [[span(start=0.5)]],
    "start_min": [[span(start=-1)]],
    "end_type": [[span(end=v)] for v in (None, True, "1", [], {})]
        + [[{k: v for k, v in span(other=0).items() if k != "end"}]],
    "end_integer": [[span(end=1.5)]],
    "end_min": [[span(end=0)]],
    "locator_object": [[span(locator=v)] for v in (None, True, "page", 1, [])]
        + [[{k: v for k, v in span(other=0).items() if k != "locator"}]],
    "locator_members": [[locator(extra=0)]],
    "kind": [[locator(kind=v)] for v in (None, True, 1, [], {}, "TABLE", "Page", "unknown")]
        + [[span(locator={"other": "page", "value": "2"})], [PAGE, locator(kind="TABLE")]],
    "value_type": [[locator(value=v)] for v in (None, True, 1, [], {})]
        + [[span(locator={"kind": "page", "other": "2"})]],
    "value_min": [[locator(value="")]],
    "value_max": [[locator(value="x" * 501)], [locator(value="\0" * 501)], [locator(value="字" * 501)]],
}
DUPLICATES = (
    '[{"start":5,"end":9,"locator":{"kind":"page","kind":"table","value":"2"}}]',
    '[{"start":5,"end":9,"locator":{"kind":"page","value":"2"},"locator":{"kind":"table","value":"T"}}]',
    '[{"start":5,"start":0,"end":9,"locator":{"kind":"page","value":"2"}}]',
    '[{"start":5,"end":9,"end":10,"locator":{"kind":"page","value":"2"}}]',
    '[{"start":5,"end":9,"locator":{"kind":"page","value":"2","value":"T"}}]',
    r'[{"start":5,"end":9,"locator":{"kind":"page","ki\u006ed":"table","value":"2"}}]',
)


class SpanRouterTest(unittest.TestCase):
    def test_malformed_pairs(self):
        for method in METHODS:
            for predicate, cases in BAD.items():
                for spans in cases:
                    with self.subTest(method=method, predicate=predicate, spans=spans), span_fixture({"identity": content.IDENTITY}, bindings=((PAGE,),)) as case:
                        doc = document(case, method, "bibliographic", spans=spans, detailed=False)
                        before = case.state()
                        out = case.send(doc)
                        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
                        self.assertIn("/cited_spans", out["detail"])
                        case.assert_audited_state(before, 1)
                        doc["cited_spans"] = [PAGE]
                        attach_checks(case, doc)
                        self.assertEqual(case.send(doc)["status"], "committed")
                        self.assertEqual(json.loads(case.value("SELECT receipt FROM verification_receipts")), doc)

    def test_duplicate_pairs_at_payload_boundary(self):
        for method in METHODS:
            for spans in DUPLICATES + (None,):
                with self.subTest(method=method, spans=spans), span_fixture({"identity": content.IDENTITY}, bindings=((PAGE,),)) as case:
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
                    case.assert_audited_state(before, 1)
                    self.assertEqual(case.send(document(case, method, "bibliographic", spans=(PAGE,)))["status"], "committed")
