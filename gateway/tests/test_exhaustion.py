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
  * LocalIndexPages (DB) — the local index pages by offset over one total order, reading one row
    past the page to know positively whether anything remains; withheld matches. Task 2b-repair-7
    F3-R1: the index changes between pages (a delete, an insert, a reordering, and cached pages
    before the change) — the continuation names the population it was counted in, so a page of a
    changed one reads nothing and ends nothing.
  * AssembledPaging (DB) — the running gateway: strictly more converted matches than `limit`, on
    HTTP /v1/find, HTTP MCP, a queued job and the stdio MCP bridge, each continued to the end; the
    all-fit controls; withheld matches; a changed index on every door; the engine's GatewayClient
    paging in its own process.
DB cases need RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
import uuid
from pathlib import Path

from research_gateway import adapters, app
from research_gateway.adapters import (crossref, datacite, doaj, europepmc, govinfo, harvard_dataverse, huggingface, kaggle,
                                       openaire, openalex_snapshot, openml, semanticscholar, socrata)
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.api import http as api
from research_gateway.core import db
from research_gateway.core import identity as ident
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.cache import Cache
from research_gateway.core.canonical import make_record
from research_gateway.harvest import index
from research_gateway.registry.load import read_seed
from tests.test_lane_outcomes import rec, store_admits, stub
from tests.test_record_gate import INVOCATION, answer

HAVE_DB = db.configured() and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1"
GATEWAY_DIR = Path(__file__).resolve().parents[1]
REPOSITORY = Path(os.environ.get("GATEWAY_SOURCE_REPOSITORY") or GATEWAY_DIR.parent)
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


def venue(cur, identity: str, title: str, current: bool = True) -> None:
    """A stored, indexed venue; `current` False is a row an earlier writer left (the view withholds it)."""
    cur.execute("INSERT INTO gateway.records (identity, kind, canonical, restriction_inputs) VALUES (%s, 'venue', %s, %s)",
                (identity, json.dumps({"identity": identity, "kind": "venue", "title": title}), current))
    cur.execute("INSERT INTO gateway.index_docs (identity, kind, domain, year, tsv) VALUES (%s, 'venue', NULL, NULL, "
                "to_tsvector('english', %s))", (identity, title))


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class LocalIndexPages(unittest.TestCase):
    """Five converted venues match; the router and the real local-index adapter, no HTTP."""

    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]
        self.word = f"pagecheck{self.tag}"
        self.venues = sorted(f"issn:page-{self.tag}-{n}" for n in range(5))
        self.conn = db.connect()
        self.addCleanup(self.cleanup)
        with self.conn.cursor() as cur:
            for n, identity in enumerate(self.venues):
                venue(cur, identity, f"{self.word} venue {n}")
        self.conn.commit()
        self.router = R.Router(read_seed(), adapters.load_all())

    def cleanup(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.index_docs WHERE identity LIKE %s", (f"%{self.tag}%",))
            cur.execute("DELETE FROM gateway.records WHERE identity LIKE %s", (f"%{self.tag}%",))
        self.conn.commit()
        self.conn.close()

    def find(self, limit: int, cursors: dict | None = None, cache: Cache | None = None) -> dict:
        client = Client(broker=Broker({"openalex_snapshot": RatePolicy(per_second=1000)}), transport=FakeTransport(), conn=self.conn)
        return R.execute(self.router, {"request_type": "find", "query": self.word, "kind": "venue", "limit": limit,
                                       **({"cursors": cursors} if cursors else {})}, client, cache=cache)

    def pages(self, limit: int) -> list[dict]:
        out, cursors = [], None
        while len(out) < 10:
            answered = self.find(limit, cursors)
            (lane,) = answered["lanes"]
            out.append(lane)
            if lane.get("next") is None:
                return out
            cursors = answered["next"]
        self.fail("the pages never ended")

    def test_more_matches_than_the_limit_page_to_the_end(self):
        pages = self.pages(2)
        self.assertEqual([{k: p.get(k) for k in KEYS if k != "next"} for p in pages],
                         [{"coverage": "searched_ok", "completeness": "complete", "count": 2, "error_class": None, "exhausted": None},
                          {"coverage": "searched_ok", "completeness": "complete", "count": 2, "error_class": None, "exhausted": None},
                          {"coverage": "searched_ok", "completeness": "complete", "count": 1, "error_class": None, "exhausted": True}],
                         "two, two, then the one left: the first page is never the end")
        self.assertTrue(all(continues(p) for p in pages[:2]) and pages[2].get("next") is None, pages)
        read = [i for p in pages for i in p["retrieved"]]
        self.assertEqual(read, self.find(10)["lanes"][0]["retrieved"], "the pages are the one ordering, cut in pages")
        self.assertEqual(sorted(read), self.venues, "every match once")

    def test_control_everything_fitting_on_the_final_page_is_exhausted(self):
        for limit in (5, 10):
            with self.subTest(limit=limit):
                self.assertEqual({k: self.find(limit)["lanes"][0].get(k) for k in KEYS},
                                 {"coverage": "searched_ok", "completeness": "complete", "count": 5, "error_class": None,
                                  "next": None, "exhausted": True})

    def test_withheld_matches_leave_every_page_partial_and_the_last_unexhausted(self):
        with self.conn.cursor() as cur:
            venue(cur, f"issn:page-{self.tag}-old", f"{self.word} venue an earlier writer left", current=False)
        self.conn.commit()
        pages = self.pages(2)
        self.assertEqual([(p["completeness"], p["count"], p["error_class"], continues(p), p.get("exhausted")) for p in pages],
                         [("partial", 2, "payload_invalid", True, None), ("partial", 2, "payload_invalid", True, None),
                          ("partial", 1, "payload_invalid", False, None)],
                         "each page a lower bound that still continues; the last is not the end while a match is withheld")
        self.assertEqual(sorted(i for p in pages for i in p["retrieved"]), self.venues, "the withheld row is never served")

    def test_a_negative_offset_is_no_page(self):
        lane = self.find(2, {"openalex_snapshot": -2})["lanes"][0]
        self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count")), ("provider_unavailable", "unobserved", None))

    # ---- 2b-repair-7 F3-R1: the index changes between pages ----------------------------------------------------
    def first_page(self, cache: Cache | None = None) -> tuple[dict, list[str]]:
        """Page one at limit 2, and the order a fresh all-fit query puts the five matches in."""
        order = self.find(10)["lanes"][0]["retrieved"]
        first = self.find(2, cache=cache)
        self.assertEqual(first["lanes"][0]["retrieved"], order[:2])
        self.assertTrue(continues(first["lanes"][0]))
        return first, order

    def unindex(self, identity: str) -> None:
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.index_docs WHERE identity = %s", (identity,))
        self.conn.commit()

    def outranking(self, identity: str) -> None:
        """Index `identity` with the term three times: it then ranks ahead of every other match."""
        with self.conn.cursor() as cur:
            cur.execute("UPDATE gateway.index_docs SET tsv = to_tsvector('english', %s) WHERE identity = %s",
                        (f"{self.word} {self.word} {self.word} venue", identity))
        self.conn.commit()

    def changed(self, out: dict) -> None:
        """A continuation page asked of a changed index: nothing read, nothing ended, and said why."""
        (lane,) = out["lanes"]
        self.assertEqual({k: lane.get(k) for k in KEYS},
                         {"coverage": "provider_unavailable", "completeness": "unobserved", "count": None,
                          "error_class": "partial_pagination", "next": None, "exhausted": None}, out["facts"])
        self.assertEqual(store_admits(lane), [], lane)
        self.assertNotIn("openalex_snapshot", out.get("next") or {}, "no sentinel: nothing says this lane returned everything")
        self.assertTrue(any("changed since this search's first page" in f for f in out["facts"]), out["facts"])

    def test_a_match_removed_after_page_one_never_hides_the_one_after_it(self):
        """Astra's reproduction (2b-repair-6 review, F3-R1): page one reads the first two of five
        matches; the first is then removed from the index. Counted again, offset 2 starts one match
        later, so the third match of the order page one cut — still a converted match — would never
        be returned, and the last page would say the lane had returned everything."""
        first, order = self.first_page()
        self.unindex(order[0])
        self.assertIn(order[2], self.find(10)["lanes"][0]["retrieved"], "the match an offset would pass over still matches")
        self.changed(self.find(2, first["next"]))
        again = self.pages(2)   # the search asked again from its first page: every remaining match, once
        self.assertEqual(sorted(i for p in again for i in p["retrieved"]), sorted(order[1:]))
        self.assertTrue(again[-1]["exhausted"])

    def test_a_match_inserted_ahead_of_the_offset_is_never_passed_over(self):
        first, order = self.first_page()
        newcomer = f"issn:page-{self.tag}-new"
        with self.conn.cursor() as cur:
            venue(cur, newcomer, f"{self.word} {self.word} {self.word} venue")
        self.conn.commit()
        self.assertEqual(self.find(10)["lanes"][0]["retrieved"][0], newcomer, "it ranks ahead of page one's matches")
        self.changed(self.find(2, first["next"]))

    def test_a_match_reordered_ahead_of_the_offset_is_never_passed_over(self):
        """The same five matches, in another order: the last now ranks first, so offset 2 would repeat
        page one's second match and never reach the moved one — membership alone does not bind an offset."""
        first, order = self.first_page()
        self.outranking(order[-1])
        now = self.find(10)["lanes"][0]["retrieved"]
        self.assertEqual((sorted(now), now[0]), (sorted(order), order[-1]))
        self.changed(self.find(2, first["next"]))

    def test_cached_pages_never_splice_two_populations(self):
        """Pages one and two are answered and cached; the index then changes. Asked again, both are
        replayed from the cache as the earlier dispatch's answers, with the earlier continuations —
        and page three, which only the changed index can answer, is asked with the population page
        one counted in, so it reads nothing and ends nothing."""
        cache = Cache()
        first, order = self.first_page(cache)
        replayed = self.find(2, cache=cache)
        self.assertEqual((replayed.get("cache_hit"), replayed["next"]), (True, first["next"]))
        second = self.find(2, first["next"], cache=cache)   # control: unchanged, a fresh page after a cached one continues
        self.assertEqual((second.get("cache_hit"), second["lanes"][0]["retrieved"]), (None, order[2:4]))
        self.assertTrue(continues(second["lanes"][0]))
        self.unindex(order[0])
        for cursors, page in ((None, first), (first["next"], second)):
            again = self.find(2, cursors, cache=cache)
            self.assertEqual((again.get("cache_hit"), again["lanes"][0]["retrieved"], again["next"]),
                             (True, page["lanes"][0]["retrieved"], page["next"]))
        self.changed(self.find(2, second["next"], cache=cache))
        self.assertIsNone(self.find(2, second["next"], cache=cache).get("cache_hit"), "an unread page is never cached")


def continues(lane: dict) -> bool:
    """The lane handed back a continuation of its own — never the exhausted sentinel."""
    return isinstance(lane.get("next"), str) and lane["next"] != R.EXHAUSTED_CURSOR


ENGINE = """
import json, sys
from gen2.gateway_client.client import GatewayClient
out = GatewayClient(sys.argv[1], "t").search(json.loads(sys.argv[2]), invocation_id="inv_exhaustion01", attempt=1,
                                            policy_version="exhaustion/1", pages=int(sys.argv[3]))
print(json.dumps([[o["observation"][k] for k in ("lane", "coverage_state", "completeness", "result_count", "error_class")]
                  + [o["observation"]["request"]["page"], [e["provider_record_id"] for e in o["retrieval_events"]]]
                  for o in out["observations"]]))
"""


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class AssembledPaging(unittest.TestCase):
    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]
        self.gw = app.Gateway(app.Settings(tokens={"engine": "t"}, workers=1), use_db=True, transport=FakeTransport())
        self.gw.start()
        self.server = api.serve(self.gw, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(self.cleanup)
        self.word = f"doorpage{self.tag}"
        self.venues = self.five(self.word)

    def five(self, word: str) -> list[str]:
        """Five converted venues matching `word`, written through the harvest's own writer."""
        venues = sorted(ident.canonical(f"issn:{word}-{self.tag}-{n}") for n in range(5))
        with db.connect() as conn:
            with conn.cursor() as cur:
                for n, identity in enumerate(venues):
                    index.upsert(cur, make_record(identity=identity, kind="venue", source_id="doaj", title=f"{word} venue {n}",
                                                  license="CC BY", raw={}), "doaj")
            conn.commit()
        return venues

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.gw.stop()
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.index_docs WHERE identity ILIKE %s", (f"%{self.tag}%",))
            cur.execute("DELETE FROM gateway.records WHERE identity ILIKE %s", (f"%{self.tag}%",))
            conn.commit()

    def post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.url + path, json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer t", **INVOCATION})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def door(self, name: str, limit: int, cursors: dict | None, word: str | None = None) -> dict:
        """One find page through the named door."""
        args = {"query": word or self.word, "kind": "venue", "limit": limit, **({"cursors": cursors} if cursors else {})}
        call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "research_find", "arguments": args}}
        if name == "http":
            return answer(self.post("/v1/find", args))
        if name == "mcp":
            return answer(self.post("/mcp", call))
        if name == "queued":
            job = self.post("/v1/find?async=1", args)["job_id"]
            for _ in range(300):
                req = urllib.request.Request(f"{self.url}/v1/jobs/{job}", headers={"Authorization": "Bearer t", **INVOCATION})
                with urllib.request.urlopen(req, timeout=30) as r:
                    found = answer(json.load(r))
                if found is not None:
                    return found
                time.sleep(0.05)
            self.fail(f"job {job} never answered")
        done = subprocess.run([sys.executable, "-m", "research_gateway.clients.mcp_stdio"], input=json.dumps(call) + "\n",
                              capture_output=True, text=True, timeout=60, cwd=GATEWAY_DIR,
                              env={**os.environ, "RESEARCH_GATEWAY_URL": self.url, "RESEARCH_GATEWAY_TOKEN": "t",
                                   "RESEARCH_INVOCATION_ID": "inv_exhaustion02"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return answer(done.stdout)

    def pages(self, name: str, limit: int) -> list[tuple[dict, list]]:
        """A find through `door` continued to its end, each page handing back the `next` map it was given."""
        out, cursors = [], None
        while len(out) < 10:
            answered = self.door(name, limit, cursors)
            self.assertIsNotNone(answered, name)
            (lane,) = [lane for lane in answered["lanes"] if lane["source"] == "openalex_snapshot"]
            out.append((lane, answered))
            if lane.get("next") is None:
                return out
            cursors = answered["next"]
        self.fail(f"{name}: the pages never ended")

    def test_more_converted_matches_than_the_limit_continue_on_every_door(self):
        for name, limit in (("http", 2), ("mcp", 3), ("queued", 4), ("stdio", 1)):   # a distinct request per door
            with self.subTest(name):
                pages = self.pages(name, limit)
                sizes = [limit] * (5 // limit) + ([5 % limit] if 5 % limit else [])
                self.assertEqual([(lane["coverage"], lane["completeness"], lane["count"], continues(lane), lane.get("exhausted"))
                                  for lane, _ in pages],
                                 [("searched_ok", "complete", n, i < len(sizes) - 1, None if i < len(sizes) - 1 else True)
                                  for i, n in enumerate(sizes)],
                                 "each page but the last continues; only the last, holding what was left, is exhausted")
                self.assertEqual(pages[0][1]["next"], {"openalex_snapshot": pages[0][0]["next"]}, "the first page's continuation, never the sentinel")
                self.assertEqual(pages[-1][1]["next"], {"openalex_snapshot": "exhausted"})
                read = [i for lane, _ in pages for i in lane["retrieved"]]
                self.assertEqual(sorted(read), self.venues, "every converted match, each once")

    def test_control_everything_fitting_is_exhausted_and_its_sentinel_skips_the_lane(self):
        (lane, out), = self.pages("http", 5)
        self.assertEqual((lane["coverage"], lane["completeness"], lane["count"], lane.get("exhausted")), ("searched_ok", "complete", 5, True))
        self.assertEqual(sorted(lane["retrieved"]), self.venues)
        after = answer(self.post("/v1/find", {"query": self.word, "kind": "venue", "limit": 5, "cursors": out["next"]}))
        (lane,) = after["lanes"]
        self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count")), ("exhausted", "unobserved", None))

    def test_withheld_matches_continue_as_lower_bounds_and_never_end(self):
        identity = ident.canonical(f"issn:door-{self.tag}-old")
        with db.connect() as conn:   # after startup: a gateway never opens over an unconverted row
            with conn.cursor() as cur:
                venue(cur, identity, f"{self.word} venue an earlier writer left", current=False)
            conn.commit()
        pages = self.pages("http", 2)
        self.assertEqual([(lane["completeness"], lane["count"], lane.get("error_class"), continues(lane), lane.get("exhausted"))
                          for lane, _ in pages],
                         [("partial", 2, "payload_invalid", True, None), ("partial", 2, "payload_invalid", True, None),
                          ("partial", 1, "payload_invalid", False, None)])
        self.assertNotIn("openalex_snapshot", pages[-1][1].get("next") or {}, "no sentinel while a match is withheld")
        self.assertEqual(sorted(i for lane, _ in pages for i in lane["retrieved"]), self.venues)
        self.assertTrue(all("1 matching stored record(s) withheld" in " ".join(out["facts"]) for _, out in pages))

    def test_a_changed_index_ends_no_doors_search(self):
        """F3-R1 on every door: page one, then its first match removed from the index; the page its
        continuation asks for reads nothing and ends nothing — no records, no count, no sentinel."""
        for name, limit in (("http", 2), ("mcp", 3), ("queued", 4), ("stdio", 1)):
            with self.subTest(name):
                word = f"doorchange{name}{self.tag}"
                self.five(word)
                first = self.door(name, limit, None, word)
                (lane,) = [lane for lane in first["lanes"] if lane["source"] == "openalex_snapshot"]
                self.assertTrue(continues(lane), lane)
                with db.connect() as conn, conn.cursor() as cur:
                    cur.execute("DELETE FROM gateway.index_docs WHERE identity = %s", (lane["retrieved"][0],))
                    conn.commit()
                after = self.door(name, limit, first["next"], word)
                (lane,) = [lane for lane in after["lanes"] if lane["source"] == "openalex_snapshot"]
                self.assertEqual((lane["coverage"], lane["completeness"], lane.get("count"), lane.get("error_class"),
                                  lane.get("next"), lane.get("exhausted")),
                                 ("provider_unavailable", "unobserved", None, "partial_pagination", None, None), after["facts"])
                self.assertNotIn("openalex_snapshot", after.get("next") or {})

    def test_the_engine_client_pages_to_the_end(self):
        """The real engine GatewayClient, in its own process with the engine's interpreter, against this
        gateway: limit 2 and up to 5 pages asks three times and records each page whole; asked for
        two pages, it records two, the second still continuing — never one page called complete."""
        engine = REPOSITORY / ".venv-gen2" / "bin" / "python"
        self.assertTrue(engine.exists(), f"{engine}: the engine's interpreter (make gen2-venv)")
        request = {"request_type": "find", "query": self.word, "kind": "venue", "limit": 2, "lanes": ["openalex_snapshot"]}
        for pages, want in ((5, [(1, 2), (2, 2), (3, 1)]), (2, [(1, 2), (2, 2)])):
            with self.subTest(pages=pages):
                done = subprocess.run([str(engine), "-B", "-c", ENGINE, self.url, json.dumps(request), str(pages)],
                                      cwd=REPOSITORY, capture_output=True, text=True, timeout=120)
                self.assertEqual(done.returncode, 0, done.stderr)
                observed = json.loads(done.stdout)
                self.assertEqual([(o[5], o[3]) for o in observed], want)
                self.assertEqual({tuple(o[:3]) + (o[4],) for o in observed}, {("openalex_snapshot", "searched_ok", "complete", None)})
                read = [i for o in observed for i in o[6]]
                self.assertEqual(len(read), len(set(read)))
                self.assertTrue(set(read) <= set(self.venues))
                if pages == 5:
                    self.assertEqual(sorted(read), self.venues, "all five, across three pages")


if __name__ == "__main__":
    unittest.main()
