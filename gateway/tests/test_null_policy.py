"""Task 2b-repair-13a (Astra R12-3): Semantic Scholar's explicit null is not a complete empty answer.

Before repair-12, a find answer `{"data": null, "total": 0}` was unreadable with no count. Repair-12 moved the accepted special case — `data` may be OMITTED when the answer counts nothing — into the generic decoder, whose
"missing or null" rule made a PRESENT null identical to an omitted field, and the four such pairs (two operations, each with its populated variant) became `searched_empty`, `complete`, count 0 (two of them still offering a next
offset, two claiming the end): a false claim of a readable empty result, from an answer that says only that `data` is null.

The Semantic Scholar Graph API's own specification does not allow it. `PaperRelevanceSearchBatch.data` is `type: array` (https://api.semanticscholar.org/graph/v1/swagger.json — captured in
private/evidence/astra-2b-repair-12/docs/s2-swagger.json, sha256 00d7302b…); the document declares no nullable value anywhere (it has neither `nullable` nor `x-nullable`), `total` is "Approximate number of matching
search results", and `next` is "Absent if no more data exists". The accepted reading of an omitted `data` beside `total: 0` is "a search that matched nothing"; a `null` is not an omission and is not an array. So
this operation's schema says `never_null` (adapters/semanticscholar.py) and the decoder keeps the distinction: left out is the empty value (when the answer counts nothing), null is unreadable. Another provider's null policy
is not this one's: nothing here is read from BEA's, GovInfo's or OpenAIRE's.
"""
from __future__ import annotations

import copy
import unittest

from tests import invariant_ops as O
from tests import test_invariants as H

S2_FINDS = {name: op for name, op in H.ALL.items() if name.startswith("semanticscholar.find")}


class SemanticScholarNull(unittest.TestCase):
    def lane(self, op, data, total=0):
        body = copy.deepcopy(O.corrupt_route(op).body)
        body["total"] = total
        if data is H.MISSING:
            body.pop("data")
        else:
            body["data"] = data
        return H.run(op, body)[1]

    def test_the_four_cases_data_null_with_total_zero_are_unreadable_with_no_count(self):
        self.assertEqual(len(S2_FINDS), 4, sorted(S2_FINDS))
        for name, op in S2_FINDS.items():
            lane = self.lane(op, None)
            with self.subTest(op=name):
                self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), "count" in lane, "next" in lane, lane.get("exhausted")),
                                 ("provider_unavailable", "unobserved", "payload_invalid", False, False, None), lane)

    def test_controls_an_omitted_data_and_an_empty_array_beside_total_zero_are_the_accepted_empty_answer(self):
        for name, op in S2_FINDS.items():
            for data in (H.MISSING, []):
                lane = self.lane(op, data)
                with self.subTest(op=name, data="omitted" if data is H.MISSING else "[]"):
                    self.assertEqual((lane["coverage"], lane["completeness"], lane["count"]), ("searched_empty", "complete", 0))

    def test_a_null_with_any_other_total_and_the_other_wrong_kinds_are_unreadable_as_before(self):
        for name, op in S2_FINDS.items():
            for data, total in ((None, 3), (None, 0), (False, 0), ({}, 0), ("x", 0), (H.MISSING, 3)):
                lane = self.lane(op, data, total)
                with self.subTest(op=name, data=repr(data), total=total):
                    self.assertEqual((lane["completeness"], lane.get("error_class"), "count" in lane), ("unobserved", "payload_invalid", False))

    def test_the_declaration_is_this_operations_alone(self):
        """No other schema is `never_null`: the rule is not borrowed for a provider whose contract does not say it (a field left out or null stays the same thing there)."""
        from research_gateway import adapters
        from research_gateway.core import schema as S
        found = []

        def visit(spec, where):
            if spec.never_null:
                found.append(where)
            children = spec.of.values() if isinstance(spec.of, dict) else (spec.of,) if isinstance(spec.of, S.Spec) else tuple(spec.of) if isinstance(spec.of, tuple) else ()
            for i, child in enumerate(children):
                if isinstance(child, S.Spec):
                    visit(child, where + (i,))
        for sid, module in adapters.load_all().items():
            for key, spec in {**getattr(module, "SCHEMAS", {})}.items():
                visit(spec, (sid, key))
        self.assertEqual([w[:2] for w in found], [("semanticscholar", "find")])


if __name__ == "__main__":
    unittest.main()
