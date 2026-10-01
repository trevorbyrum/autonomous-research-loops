"""Task 2b-repair-6 F3: a lane is exhausted only when its adapter says nothing remains.

Astra's 2b-repair-5 review: five converted matching venues, a local-index find at limit 2,
answered two records marked complete AND exhausted, its continuation the `exhausted`
sentinel — so the other three were never asked for, on all four doors, and the engine's
client stopped after one page. The router read "no continuation" as "nothing remains". Now an
adapter's answer says one of three things: a continuation (more may remain), `exhausted: True`
(its own evidence that nothing remains), or neither — records then are a lower bound
(`partial_pagination`), never complete, never cached, never exhausted (STATION-CONTRACT §2, RG-4).

  * ReportedEnd — the rule at the router, with a stub adapter.
  * AdapterEnds — each find adapter's own evidence of its end, from provider bodies stated here by
    hand: what continues, what positively ends, and what can only be a lower bound.
"""
from __future__ import annotations

import unittest

from research_gateway.adapters import (crossref, datacite, doaj, europepmc, govinfo, harvard_dataverse, huggingface, kaggle,
                                       openaire, openml, semanticscholar, socrata)
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.cache import Cache
from tests.test_lane_outcomes import rec, store_admits, stub

FIND = {"request_type": "find", "query": "q", "kind": "article"}
KEYS = ("coverage", "completeness", "count", "error_class", "next", "exhausted")


def entry_of(test: unittest.TestCase, out: dict, lane: str = "stub") -> dict:
    (entry,) = [e for e in out["lanes"] if e["source"] == lane]
    test.assertEqual(store_admits(entry), [], entry)
    return {k: entry.get(k) for k in KEYS}


class ReportedEnd(unittest.TestCase):
    def test_records_with_no_continuation_and_no_reported_end_are_a_lower_bound(self):
        cache = Cache()
        r, c, calls = stub(find=lambda cursor: {"records": [rec(1), rec(2)]})
        out = R.execute(r, FIND, c, cache=cache)
        self.assertEqual(entry_of(self, out), {"coverage": "searched_ok", "completeness": "partial", "count": 2,
                                               "error_class": "partial_pagination", "next": None, "exhausted": None})
        self.assertEqual(out["lanes"][0]["retrieved"], ["doi:10.1234/1", "doi:10.1234/2"], "the identities read are kept")
        self.assertNotIn("stub", out.get("next") or {}, "no sentinel: nothing says this lane returned everything")
        self.assertTrue(any("did not report the end" in f and "lower bound" in f for f in out["facts"]), out["facts"])
        again = R.execute(r, FIND, c, cache=cache)
        self.assertEqual((again.get("cache_hit"), len(calls)), (None, 2), "a lower bound is asked again, never replayed")

    def test_control_a_reported_end_is_exhausted(self):
        cache = Cache()
        r, c, calls = stub(find=lambda cursor: {"records": [rec(1), rec(2)], "exhausted": True})
        out = R.execute(r, FIND, c, cache=cache)
        self.assertEqual(entry_of(self, out), {"coverage": "searched_ok", "completeness": "complete", "count": 2,
                                               "error_class": None, "next": None, "exhausted": True})
        self.assertEqual(out["next"], {"stub": "exhausted"})
        again = R.execute(r, FIND, c, cache=cache)
        self.assertEqual((again.get("cache_hit"), len(calls)), (True, 1), "a whole answer is served again from the cache")

    def test_control_a_continuation_is_followed_not_exhausted(self):
        pages = {None: {"records": [rec(1), rec(2)], "next_cursor": "c2"}, "c2": {"records": [rec(3)], "exhausted": True}}
        r, c, calls = stub(find=lambda cursor: pages[cursor])
        first = R.execute(r, FIND, c)
        self.assertEqual(entry_of(self, first), {"coverage": "searched_ok", "completeness": "complete", "count": 2,
                                                 "error_class": None, "next": "c2", "exhausted": None})
        last = R.execute(r, {**FIND, "cursors": first["next"]}, c)
        self.assertEqual(entry_of(self, last), {"coverage": "searched_ok", "completeness": "complete", "count": 1,
                                                "error_class": None, "next": None, "exhausted": True})
        self.assertEqual(calls, [None, "c2"])

    def test_a_continuation_outranks_a_reported_end(self):
        r, c, _ = stub(find=lambda cursor: {"records": [rec(1)], "next_cursor": "c2", "exhausted": True})
        self.assertEqual({k: v for k, v in entry_of(self, R.execute(r, FIND, c)).items() if k in ("next", "exhausted")},
                         {"next": "c2", "exhausted": None}, "a wasted request costs less than skipped records")

    def test_an_empty_answer_is_exhausted_only_when_reported(self):
        r, c, _ = stub(find=lambda cursor: {"records": []})
        self.assertEqual(entry_of(self, R.execute(r, FIND, c)), {"coverage": "searched_empty", "completeness": "complete", "count": 0,
                                                                 "error_class": None, "next": None, "exhausted": None})
        r, c, _ = stub(find=lambda cursor: {"records": [], "exhausted": True})
        self.assertTrue(entry_of(self, R.execute(r, FIND, c))["exhausted"], "control: an empty last page that says so")


def ask(mod, method: str, prefix: str, body, status: int = 200, extra=(), **kwargs) -> tuple[dict, list]:
    """`mod.find` against one canned provider body; (its answer, the requests it sent)."""
    t = FakeTransport()
    for route in extra:
        t.add(*route)
    t.add(method, prefix, status=status, body=body)
    c = Client(broker=Broker({mod.SOURCE_ID: RatePolicy(per_second=1000)}), transport=t, secrets=lambda name, field=None: "k")
    out = mod.find(c, "q", **kwargs)
    return {k: out.get(k) for k in ("next_cursor", "next_page", "next_offset", "next_offset_mark", "exhausted")}, t.calls


def more(key, value):
    return {key: value, "exhausted": False}


def end(key):
    return {key: None, "exhausted": True}


def neither(key):
    return {key: None, "exhausted": False}


class AdapterEnds(unittest.TestCase):
    """Each find adapter, against bodies whose meaning is stated by hand: a page with more after it
    continues; a page the provider's own evidence shows is the last is exhausted; a page with no
    such evidence and no continuation is neither (the router makes it a lower bound)."""

    def check(self, cases):
        for name, (mod, method, prefix, body, kwargs, want, *status) in cases.items():
            with self.subTest(name):
                if mod is openaire:   # the process-wide token: minted here, never left for another test
                    openaire.reset_token()
                    self.addCleanup(openaire.reset_token)
                extra = [("POST", openaire.TOKEN_URL, 200, {"access_token": "tok", "expires_in": 3600})] if mod is openaire else ()
                got, _ = ask(mod, method, prefix, body, *status, extra=extra, **kwargs)
                self.assertEqual({k: v for k, v in got.items() if k in want}, want)

    def test_cursor_sources(self):
        items, cr, epmc = [{}, {}], "https://api.crossref.org/works", "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        oa, gi = "https://api.openaire.eu/graph/v1/researchProducts", "https://api.govinfo.gov/search"
        self.check({
            "crossref, more than one page": (crossref, "GET", cr, {"message": {"items": items, "total-results": 5, "next-cursor": "c2"}},
                                             {"limit": 2}, more("next_cursor", "c2")),
            "crossref, a first page holding every match": (crossref, "GET", cr, {"message": {"items": items, "total-results": 2,
                                                                                         "next-cursor": "c2"}}, {"limit": 2}, end("next_cursor")),
            "crossref, an empty cursor page": (crossref, "GET", cr, {"message": {"items": [], "total-results": 5, "next-cursor": "c3"}},
                                               {"limit": 2, "cursor": "c2"}, end("next_cursor")),
            "crossref, a later page with records": (crossref, "GET", cr, {"message": {"items": items, "total-results": 5, "next-cursor": "c3"}},
                                                    {"limit": 2, "cursor": "c2"}, more("next_cursor", "c3")),
            "crossref, a cursor page without its cursor": (crossref, "GET", cr, {"message": {"items": items, "total-results": 5}},
                                                           {"limit": 2, "cursor": "c2"}, neither("next_cursor")),
            "europepmc, more": (europepmc, "GET", epmc, {"hitCount": 5, "nextCursorMark": "c2", "resultList": {"result": items}},
                                {"limit": 2}, more("next_cursor", "c2")),
            "europepmc, the cursor stops advancing": (europepmc, "GET", epmc, {"hitCount": 5, "nextCursorMark": "c2", "resultList": {"result": []}},
                                                      {"limit": 2, "cursor": "c2"}, end("next_cursor")),
            "europepmc, no cursor": (europepmc, "GET", epmc, {"hitCount": 5, "resultList": {"result": items}}, {"limit": 2},
                                     neither("next_cursor")),
            "openaire, more": (openaire, "GET", oa, {"header": {"numFound": 5, "nextCursor": "c2"}, "results": items}, {"limit": 2},
                               more("next_cursor", "c2")),
            "openaire, a first page holding every match": (openaire, "GET", oa, {"header": {"numFound": 2, "nextCursor": "c2"}, "results": items},
                                                           {"limit": 2}, end("next_cursor")),
            "openaire, no cursor on a later page": (openaire, "GET", oa, {"header": {"numFound": 5}, "results": items},
                                                    {"limit": 2, "cursor": "c2"}, neither("next_cursor")),
            "govinfo, more": (govinfo, "POST", gi, {"count": 5, "offsetMark": "m2", "results": items}, {"limit": 2},
                              more("next_offset_mark", "m2")),
            "govinfo, a first page holding every match": (govinfo, "POST", gi, {"count": 2, "offsetMark": "m2", "results": items},
                                                          {"limit": 2}, end("next_offset_mark")),
            "govinfo, the mark stops advancing": (govinfo, "POST", gi, {"count": 5, "offsetMark": "m2", "results": []},
                                                  {"limit": 2, "offset_mark": "m2"}, end("next_offset_mark")),
            "govinfo, no mark on a later page": (govinfo, "POST", gi, {"count": 5, "results": items}, {"limit": 2, "offset_mark": "m2"},
                                                 neither("next_offset_mark")),
        })

    def test_crossref_asks_for_a_cursor_from_the_first_page(self):
        """Crossref sends next-cursor only to a request that carries one: without it page 1 had no
        continuation, and the router used to call every bounded Crossref answer exhausted."""
        _, calls = ask(crossref, "GET", "https://api.crossref.org/works",
                       {"message": {"items": [{}], "total-results": 5, "next-cursor": "c2"}}, limit=1)
        self.assertIn("cursor=%2A", calls[0][1])

    def test_page_and_offset_sources(self):
        items = [{}, {}]
        hundred = [{}] * 100
        dv, so = "https://dataverse.harvard.edu/api/search", "https://api.us.socrata.com/api/catalog/v1"
        s2, dc = "https://api.semanticscholar.org/graph/v1/paper/search", "https://api.datacite.org/dois"
        dj = "https://doaj.org/api/search/articles/"
        self.check({
            "doaj, more": (doaj, "GET", dj, {"total": 5, "results": items}, {"limit": 2}, more("next_page", 2)),
            "doaj, the pages reach the total": (doaj, "GET", dj, {"total": 5, "results": [{}]}, {"limit": 2, "page": 3}, end("next_page")),
            "doaj, its 1,000-record cap": (doaj, "GET", dj, {"total": 5000, "results": hundred}, {"limit": 100, "page": 10},
                                           neither("next_page")),
            "datacite, more": (datacite, "GET", dc, {"meta": {"total": 5}, "data": items}, {"limit": 2}, more("next_page", 2)),
            "datacite, the pages reach the total": (datacite, "GET", dc, {"meta": {"total": 5}, "data": [{}]}, {"limit": 2, "page": 3},
                                                    end("next_page")),
            "datacite, no total": (datacite, "GET", dc, {"data": items}, {"limit": 2}, neither("next_page")),
            "dataverse, more": (harvard_dataverse, "GET", dv, {"data": {"total_count": 5, "items": items}}, {"limit": 2},
                                more("next_page", 2)),
            "dataverse, the pages reach the total": (harvard_dataverse, "GET", dv, {"data": {"total_count": 5, "items": [{}]}},
                                                     {"limit": 2, "page": 3}, end("next_page")),
            "dataverse, no total": (harvard_dataverse, "GET", dv, {"data": {"items": items}}, {"limit": 2}, neither("next_page")),
            "socrata, more": (socrata, "GET", so, {"resultSetSize": 5, "results": items}, {"limit": 2}, more("next_offset", 2)),
            "socrata, the rows reach the size": (socrata, "GET", so, {"resultSetSize": 5, "results": [{}]}, {"limit": 2, "offset": 4},
                                                 end("next_offset")),
            "socrata, no size": (socrata, "GET", so, {"results": items}, {"limit": 2}, neither("next_offset")),
            "semanticscholar, more": (semanticscholar, "GET", s2, {"total": 5, "next": 2, "data": items}, {"limit": 2},
                                      more("next_offset", 2)),
            "semanticscholar, the rows reach the total": (semanticscholar, "GET", s2, {"total": 5, "data": [{}]}, {"limit": 2, "offset": 4},
                                                          end("next_offset")),
            "semanticscholar, its 1,000-result cap": (semanticscholar, "GET", s2, {"total": 5000, "data": items},
                                                      {"limit": 2, "offset": 998}, neither("next_offset")),
            "huggingface, a full page": (huggingface, "GET", "https://huggingface.co/api/datasets", items, {"limit": 2},
                                         more("next_offset", 2)),
            "huggingface, a short page": (huggingface, "GET", "https://huggingface.co/api/datasets", [{}], {"limit": 2}, end("next_offset")),
            "openml, a full page": (openml, "GET", "https://www.openml.org/api/v1/json/data/list/", {"data": {"dataset": items}},
                                    {"limit": 2}, more("next_offset", 2)),
            "openml, a short page": (openml, "GET", "https://www.openml.org/api/v1/json/data/list/", {"data": {"dataset": [{}]}},
                                     {"limit": 2}, end("next_offset")),
            "openml, its own no-results answer": (openml, "GET", "https://www.openml.org/api/v1/json/data/list/",
                                                  {"error": {"code": "372"}}, {"limit": 2}, end("next_offset"), 412),
        })

    KAGGLE = "https://www.kaggle.com/api/v1/datasets/list"

    def test_a_kaggle_page_cut_to_the_limit_neither_continues_nor_ends(self):
        """Kaggle answers pages of 20; the adapter keeps `limit` of them. Page 2 would skip the rows
        cut here, and a short page cut here is not the end: no honest continuation, no end."""
        self.check({"a full page cut": (kaggle, "GET", self.KAGGLE, [{}] * 20, {"limit": 5}, neither("next_page")),
                    "a short page cut": (kaggle, "GET", self.KAGGLE, [{}] * 8, {"limit": 5}, neither("next_page"))})

    def test_control_whole_kaggle_pages_continue_or_end(self):
        self.check({"a full page": (kaggle, "GET", self.KAGGLE, [{}] * 20, {"limit": 20}, more("next_page", 2)),
                    "a short page": (kaggle, "GET", self.KAGGLE, [{}] * 5, {"limit": 20}, end("next_page")),
                    "a short page within the limit": (kaggle, "GET", self.KAGGLE, [{}] * 5, {"limit": 5}, end("next_page"))})


if __name__ == "__main__":
    unittest.main()
