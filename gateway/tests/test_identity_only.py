"""Task 2b-repair-13a, Gate D #2: the gateway's authoritative deduplication is by IDENTITY, through the real route.

Gate D's probe sent two Crossref works with distinct DOIs and the same title, year and first author through the real adapter and router: the lane recorded TWO retrieved identities and the answer
listed ONE record, with the first DOI as its canonical identity and identifier. A retrieval helper had decided that two works are one — the gen-2 methodology and INVARIANTS E-3 reserve that for the
evidence layer's governed assessment ("deduplication removes identity duplicates only"). Here the same inputs, and the controls, through the same route. The unit contract of `core/dedup.py`
is tests/test_cache_dedup.py's.
"""
from __future__ import annotations

import unittest

from research_gateway.adapters import crossref
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry.load import read_seed


def work(doi, title, year=2021, author="Lovelace"):
    return {"DOI": doi, "title": [title], "author": [{"given": "Ada", "family": author}], "issued": {"date-parts": [[year]]}}


def routed(items):
    t = FakeTransport()
    t.add("GET", crossref.BASE + "/works", 200, {"message": {"items": items, "total-results": len(items)}})
    c = Client(broker=Broker({"crossref": RatePolicy(per_second=100000)}), transport=t, sleep=lambda _: None)
    router = R.Router([s for s in read_seed() if s["id"] == "crossref"], {"crossref": crossref})
    return R.execute(router, {"request_type": "find", "kind": "article", "query": "synthetic", "lanes": ["crossref"], "limit": 20}, c)


class IdentityOnly(unittest.TestCase):
    def test_two_distinct_dois_with_the_same_title_year_and_author_are_two_candidates(self):
        answer = routed([work("10.1000/a", "Annual survey"), work("10.1000/b", "Annual survey")])
        self.assertEqual([r["identity"] for r in answer["records"]], ["doi:10.1000/a", "doi:10.1000/b"])
        self.assertEqual([r["identifiers"] for r in answer["records"]], [{"doi": "10.1000/a"}, {"doi": "10.1000/b"}], "neither candidate carries the other's DOI")
        self.assertEqual([[m["identity"] for m in r["provenance"]] for r in answer["records"]], [["doi:10.1000/a"], ["doi:10.1000/b"]])
        (lane,) = answer["lanes"]
        self.assertEqual((lane["retrieved"], lane["count"]), (["doi:10.1000/a", "doi:10.1000/b"], 2), "the raw retrieval inventory is what it was")

    def test_the_look_alike_is_recorded_as_a_suggestion_for_a_later_assessment_with_both_provenances(self):
        answer = routed([work("10.1000/a", "Annual survey"), work("10.1000/b", "Annual survey")])
        self.assertEqual(len(answer.get("linkage_suggestions", [])), 1)
        (suggestion,) = answer["linkage_suggestions"]
        self.assertEqual((suggestion["type"], suggestion["identities"], suggestion["disposition"]), ("possible_same_work", ["doi:10.1000/a", "doi:10.1000/b"], "unassessed"))
        self.assertEqual(suggestion["differing_identifiers"], {"doi": ["10.1000/a", "10.1000/b"]})
        self.assertEqual([(p["identity"], p["sources"]) for p in suggestion["provenance"]], [("doi:10.1000/a", ["crossref"]), ("doi:10.1000/b", ["crossref"])])
        self.assertTrue(all(p["retrieved_at"] for p in suggestion["provenance"]), "each side says when it was retrieved")

    def test_controls_a_different_year_is_two_candidates_and_no_suggestion_and_the_same_doi_is_one(self):
        different_year = routed([work("10.1000/a", "Annual survey"), work("10.1000/b", "Annual survey", 2022)])
        self.assertEqual(([r["identity"] for r in different_year["records"]], "linkage_suggestions" in different_year), (["doi:10.1000/a", "doi:10.1000/b"], False))
        same = routed([work("10.1000/a", "Annual survey"), work("10.1000/A", "Annual survey")])
        self.assertEqual([r["identity"] for r in same["records"]], ["doi:10.1000/a"], "an identity stated twice is one candidate")
        self.assertEqual(len(same["records"][0]["provenance"]), 2, "and keeps both retrievals' provenance")
        self.assertEqual(same["lanes"][0]["retrieved"], ["doi:10.1000/a", "doi:10.1000/a"], "the inventory counts both retrievals")
        self.assertNotIn("linkage_suggestions", same)

    def test_an_answer_with_nothing_alike_carries_no_suggestions_key(self):
        """The engine's recorded answers (gen2/tests/fixtures/gateway_answers) have no such key: it appears only when there is something to say."""
        answer = routed([work("10.1000/a", "Annual survey"), work("10.1000/c", "Something else entirely", author="Hopper")])
        self.assertEqual(len(answer["records"]), 2)
        self.assertNotIn("linkage_suggestions", answer)


if __name__ == "__main__":
    unittest.main()
