"""Task 2b-repair-7: each find adapter's continuation and end, as its provider defines them.

docs/PROVIDER-PAGINATION.md records, for every find adapter, the provider evidence its rule rests
on (official documentation, or provider-owned source) with a quoted excerpt. The bodies below are
offline and follow the documented response shapes (field names and nesting from the provider's own
schema or examples; values synthetic). Each case isolates ONE decision and states its expected
answer from that evidence, by hand: a page that continues; the page the provider's evidence calls
the last — a normal, non-empty final page included; a page whose paging metadata is absent; and
the provider's cap. Where the evidence names no terminal signal, the adapter never says
`exhausted` and the router makes the page a lower bound (test_exhaustion.ReportedEnd).

What these cases cannot show: that a live provider still answers as documented (Phase 4's canary
qualifies that); they show the adapter acts on what the documentation says.
"""
from __future__ import annotations

import copy
import unittest

from research_gateway import adapters
from research_gateway.adapters import (crossref, datacite, doaj, europepmc, govinfo, harvard_dataverse, huggingface, kaggle, openaire,
                                       openml, qdr, semanticscholar, socrata)
from research_gateway.adapters.base import Client, FakeTransport, SourceUnavailable
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry.load import read_seed
from tests import test_adapters_articles as articles, test_adapters_datasets as datasets, test_adapters_platforms as platforms

NEXT_KEYS = ("next_cursor", "next_page", "next_offset", "next_offset_mark")


def ask(mod, method: str, prefix: str, body, status: int = 200, headers: dict | None = None, **kwargs) -> tuple[dict, list]:
    """`mod.find` against one canned provider answer: (its paging decision and record count, the requests it sent)."""
    t = FakeTransport()
    if mod is openaire:
        t.add("POST", openaire.TOKEN_URL, 200, {"access_token": "tok", "expires_in": 3600})
    t.add(method, prefix, status=status, body=body, headers=headers)
    c = Client(broker=Broker({mod.SOURCE_ID: RatePolicy(per_second=1000)}), transport=t, secrets=lambda name, field=None: "k")
    out = mod.find(c, "q", **kwargs)
    nxt = next((out[k] for k in NEXT_KEYS if out.get(k) is not None), None)
    return {"next": nxt, "exhausted": out.get("exhausted") is True, "records": len(out.get("records") or [])}, t.calls


def more(value, records: int) -> dict:
    return {"next": value, "exhausted": False, "records": records}


def last(records: int) -> dict:
    return {"next": None, "exhausted": True, "records": records}


def neither(records: int) -> dict:
    """No continuation and no end: the router reports such a page as a lower bound (partial_pagination)."""
    return {"next": None, "exhausted": False, "records": records}


class Cases(unittest.TestCase):
    def check(self, mod, method: str, prefix: str, cases: dict) -> None:
        for name, (body, kwargs, want, *status) in cases.items():
            with self.subTest(name):
                if mod is openaire:   # the process-wide token: minted here, never left for another test
                    openaire.reset_token()
                    self.addCleanup(openaire.reset_token)
                got, _ = ask(mod, method, prefix, body, *status, **kwargs)
                self.assertEqual(got, want)


class Crossref(Cases):
    """Crossref: "If the number of returned items is fewer than the number of expected rows then the end
    of the result set has been reached"; a full page continues by `next-cursor`."""
    URL = "https://api.crossref.org/works"

    @staticmethod
    def page(items: int, **message) -> dict:
        return {"status": "ok", "message-type": "work-list",
                "message": {"items-per-page": 2, "query": {"start-index": 0, "search-terms": "q"}, "total-results": 7,
                            "items": [articles.CROSSREF_WORK] * items, **message}}

    def test_continues(self):
        self.check(crossref, "GET", self.URL, {
            "a full page": (self.page(2, **{"next-cursor": "c2"}), {"limit": 2}, more("c2", 2)),
            "a full later page": (self.page(2, **{"next-cursor": "c3"}), {"limit": 2, "cursor": "c2"}, more("c3", 2)),
        })

    def test_ends(self):
        self.check(crossref, "GET", self.URL, {
            "a short final page, its next-cursor notwithstanding": (self.page(1, **{"next-cursor": "c4"}), {"limit": 2, "cursor": "c3"},
                                                                    last(1)),
            "an empty page": (self.page(0, **{"next-cursor": "c5"}), {"limit": 2, "cursor": "c4"}, last(0)),
        })

    def test_neither(self):
        self.check(crossref, "GET", self.URL, {
            "a full page without its next-cursor": (self.page(2), {"limit": 2, "cursor": "c2"}, neither(2)),
            # total-results is not documented as an exact count: a full first page holding it still continues
            "a full first page holding total-results continues": (self.page(2, **{"next-cursor": "c2", "total-results": 2}),
                                                                  {"limit": 2}, more("c2", 2)),
        })

    def test_the_first_page_asks_for_a_cursor(self):
        """Crossref sends next-cursor only to a request that carries one ("cursor=*" first)."""
        _, calls = ask(crossref, "GET", self.URL, self.page(1, **{"next-cursor": "c2"}), limit=1)
        self.assertIn("cursor=%2A", calls[0][1])
        self.assertIn("rows=1", calls[0][1])


class DataCiteDois(Cases):
    """DataCite: meta.total is the "Total results count"; page-number paging reaches only "the first
    10,000 records". The end is the page reaching the total; past the cap nothing continues or ends."""
    URL = "https://api.datacite.org/dois"

    @staticmethod
    def page(items: int, page: int, size: int, total=None) -> dict:
        meta = {"totalPages": -(-total // size), "page": page, "total": total} if total is not None else {}
        return {"data": [articles.DataCite.DOI] * items, "meta": meta,
                "links": {"self": f"{DataCiteDois.URL}?page[number]={page}"}}

    def test_continues(self):
        self.check(datacite, "GET", self.URL, {
            "a page short of the total": (self.page(2, 1, 2, 5), {"limit": 2}, more(2, 2)),
            "an empty page short of the total": (self.page(0, 2, 2, 5), {"limit": 2, "page": 2}, more(3, 0)),
            "the page before the last the cap lets page-number paging reach": (self.page(100, 99, 100, 50_000),
                                                                               {"limit": 100, "page": 99}, more(100, 100)),
        })

    def test_ends(self):
        self.check(datacite, "GET", self.URL, {
            "the final non-empty page reaches the total": (self.page(1, 3, 2, 5), {"limit": 2, "page": 3}, last(1)),
            "a full final page reaches the total": (self.page(2, 2, 2, 4), {"limit": 2, "page": 2}, last(2)),
            "an empty first page of a total of 0": (self.page(0, 1, 2, 0), {"limit": 2}, last(0)),
        })

    def test_neither(self):
        self.check(datacite, "GET", self.URL, {
            "no meta.total": (self.page(2, 1, 2), {"limit": 2}, neither(2)),
            "the last page the cap lets page-number paging reach": (self.page(100, 100, 100, 50_000), {"limit": 100, "page": 100},
                                                                    neither(100)),
        })


class DoajArticles(Cases):
    """DOAJ's own code: the last page is the one reaching `total`; a page may not START at or past record
    1,000. The next page exists only while it starts below the cap; the cap ends nothing."""
    URL = "https://doaj.org/api/search/articles/"

    @staticmethod
    def page(items: int, page: int, size: int, total=None) -> dict:
        body = {"timestamp": "2026-10-01T00:00:00Z", "page": page, "pageSize": size, "query": "q", "results": [articles.Doaj.ARTICLE] * items}
        return body if total is None else {**body, "total": total}

    def test_continues(self):
        self.check(doaj, "GET", self.URL, {
            "a page short of the total": (self.page(2, 1, 2, 5), {"limit": 2}, more(2, 2)),
            "a page whose successor starts below the cap": (self.page(100, 9, 100, 5000), {"limit": 100, "page": 9}, more(10, 100)),
        })

    def test_ends(self):
        self.check(doaj, "GET", self.URL, {
            "the final non-empty page reaches the total": (self.page(1, 3, 2, 5), {"limit": 2, "page": 3}, last(1)),
            "a search with no matches": (self.page(0, 1, 2, 0), {"limit": 2}, last(0)),
        })

    def test_neither(self):
        self.check(doaj, "GET", self.URL, {
            "no total": (self.page(2, 1, 2), {"limit": 2}, neither(2)),
            "a page whose successor would start at the cap": (self.page(100, 10, 100, 5000), {"limit": 100, "page": 10}, neither(100)),
        })

    def test_a_page_starting_past_the_cap_is_never_asked(self):
        t = FakeTransport()
        c = Client(broker=Broker({"doaj": RatePolicy(per_second=1000)}), transport=t)
        out = doaj.find(c, "q", limit=100, page=11)
        self.assertEqual((t.calls, out.get("exhausted"), out.get("next_page")), ([], None, None))
        self.assertIn("1000", out["capability_fact"])

    def test_control_a_page_starting_below_the_cap_is_asked(self):
        """Page 34 of 30 starts at record 990: DOAJ's rule (start below 1,000) admits it."""
        got, calls = ask(doaj, "GET", self.URL, self.page(30, 34, 30, 5000), limit=30, page=34)
        self.assertEqual((len(calls), got), (1, neither(30)))


class EuropePmcSearch(Cases):
    """Europe PMC documents the continuation only — "For every following page use the value of the returned
    nextCursorMark element" — and no last page: a moving cursor continues; nothing ever ends the lane."""
    URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

    @staticmethod
    def page(items: int, cursor=None, hits: int = 5) -> dict:
        body = {"version": "6.9", "hitCount": hits, "request": {"queryString": "q", "pageSize": 2},
                "resultList": {"result": [platforms.EuropePmc.RESULT] * items}}
        return body if cursor is None else {**body, "nextCursorMark": cursor}

    def test_continues(self):
        self.check(europepmc, "GET", self.URL, {
            "a moving cursor": (self.page(2, "c2"), {"limit": 2}, more("c2", 2)),
            "a moving cursor past an empty page": (self.page(0, "c3"), {"limit": 2, "cursor": "c2"}, more("c3", 0)),
            "hitCount reached, which is not documented as the end": (self.page(2, "c2", hits=2), {"limit": 2}, more("c2", 2)),
        })

    def test_neither(self):
        self.check(europepmc, "GET", self.URL, {
            "an unchanged cursor on a non-empty page": (self.page(1, "c2"), {"limit": 2, "cursor": "c2"}, neither(1)),
            "no nextCursorMark": (self.page(2), {"limit": 2}, neither(2)),
        })


class GovInfoSearch(Cases):
    """GovInfo documents only the continuation — "*" first, then "the value from the offsetMark key in the
    response" — and neither a last page nor what `count` counts: nothing ever ends the lane."""
    URL = "https://api.govinfo.gov/search"

    @staticmethod
    def page(items: int, mark=None, count: int = 15) -> dict:
        body = {"results": [datasets.GOVINFO_PKG] * items, "count": count}
        return body if mark is None else {**body, "offsetMark": mark}

    def test_continues(self):
        self.check(govinfo, "POST", self.URL, {
            "a moving mark": (self.page(2, "m2"), {"limit": 2}, more("m2", 2)),
            "a first page holding `count`, which is not documented as the end": (self.page(2, "m2", count=2), {"limit": 2},
                                                                                 more("m2", 2)),
        })

    def test_neither(self):
        self.check(govinfo, "POST", self.URL, {
            "an unchanged mark on a non-empty page": (self.page(1, "m2"), {"limit": 2, "offset_mark": "m2"}, neither(1)),
            "no offsetMark": (self.page(2), {"limit": 2, "offset_mark": "m2"}, neither(2)),
            "a search counting nothing": ({"count": 0}, {"limit": 2}, neither(0)),
        })


class DataverseSearch(Cases):
    """The Dataverse guide: "increase the ``start`` parameter on each iteration until you reach the
    ``total_count`` in the response" (its loop: `start = start + rows`, `condition = start < total`)."""

    @staticmethod
    def page(items: int, page: int, size: int, total=None) -> dict:
        data = {"q": "q", "start": (page - 1) * size, "spelling_alternatives": {}, "items": [datasets.DV_SEARCH["data"]["items"][0]] * items,
                "count_in_response": items}
        return {"status": "OK", "data": data if total is None else {**data, "total_count": total}}

    SOURCES = ((harvard_dataverse, "https://dataverse.harvard.edu/api/search"), (qdr, "https://data.qdr.syr.edu/api/search"))

    def check_both(self, cases: dict) -> None:
        for mod, url in self.SOURCES:   # QDR is a Dataverse: one implementation, both lanes
            with self.subTest(mod.SOURCE_ID):
                self.check(mod, "GET", url, cases)

    def test_continues(self):
        self.check_both({
            "start + rows short of total_count": (self.page(2, 1, 2, 5), {"limit": 2}, more(2, 2)),
            "an empty page short of total_count": (self.page(0, 2, 2, 5), {"limit": 2, "page": 2}, more(3, 0)),
        })

    def test_ends(self):
        self.check_both({
            "the final non-empty page reaches total_count": (self.page(1, 3, 2, 5), {"limit": 2, "page": 3}, last(1)),
            "a full final page reaches total_count": (self.page(2, 2, 2, 4), {"limit": 2, "page": 2}, last(2)),
            "nothing matched": (self.page(0, 1, 2, 0), {"limit": 2}, last(0)),
        })

    def test_neither(self):
        self.check_both({"no total_count": (self.page(2, 1, 2), {"limit": 2}, neither(2))})


class OpenAireProducts(Cases):
    """OpenAIRE: page "until the nextCursor returned matches the current cursor you've already specified,
    indicating that there are no more results"; numFound is "the total number of entities found"."""
    URL = "https://api.openaire.eu/graph/v1/researchProducts"

    @staticmethod
    def page(items: int, cursor=None, found: int = 5) -> dict:
        header = {"numFound": found, "maxScore": 1, "queryTime": 21, "pageSize": 2}
        return {"header": header if cursor is None else {**header, "nextCursor": cursor}, "results": [platforms.OPENAIRE_PUB] * items}

    def test_continues(self):
        self.check(openaire, "GET", self.URL, {
            "a new cursor": (self.page(2, "c2"), {"limit": 2}, more("c2", 2)),
            "a later page holding numFound rows, which is not the first page": (self.page(2, "c3", found=2), {"limit": 2, "cursor": "c2"},
                                                                                more("c3", 2)),
        })

    def test_ends(self):
        self.check(openaire, "GET", self.URL, {
            "the cursor handed back unchanged, on a non-empty page": (self.page(1, "c2"), {"limit": 2, "cursor": "c2"}, last(1)),
            "a first page holding numFound": (self.page(2, "c2", found=2), {"limit": 2}, last(2)),
            "nothing found": ({"header": {"numFound": 0, "pageSize": 2, "nextCursor": "c2"}}, {"limit": 2}, last(0)),
        })

    def test_neither(self):
        self.check(openaire, "GET", self.URL, {"no nextCursor on a later page": (self.page(2), {"limit": 2, "cursor": "c2"}, neither(2))})


class SemanticScholarSearch(Cases):
    """Semantic Scholar: `next` is "Absent if no more data exists"; the endpoint "Can only return up to
    1,000 relevance-ranked results"; `total` is "Approximate". Absent `next` short of the cap ends."""
    URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    @staticmethod
    def page(items: int, offset: int, nxt=None, total: int = 5) -> dict:
        body = {"total": total, "offset": offset, "data": [platforms.SemanticScholar.PAPER] * items}
        return body if nxt is None else {**body, "next": nxt}

    def test_continues(self):
        self.check(semanticscholar, "GET", self.URL, {"next present": (self.page(2, 0, 2), {"limit": 2}, more(2, 2))})

    def test_ends(self):
        self.check(semanticscholar, "GET", self.URL, {
            "next absent on the final non-empty page": (self.page(1, 4), {"limit": 2, "offset": 4}, last(1)),
            "next absent, whatever the approximate total says": (self.page(2, 0, total=5000), {"limit": 2}, last(2)),
            "nothing matched": (self.page(0, 0, total=0), {"limit": 2}, last(0)),
            "next absent just short of the cap": (self.page(2, 997, total=5000), {"limit": 2, "offset": 997}, last(2)),
        })

    def test_neither(self):
        self.check(semanticscholar, "GET", self.URL, {
            "next absent at the 1,000-result cap": (self.page(2, 998, total=5000), {"limit": 2, "offset": 998}, neither(2)),
        })


class KaggleDatasets(Cases):
    """Kaggle pages its datasets listing by number ("Page number" in its own specification) and answers a bare
    array: no page size, last page or total is documented. A non-empty page read whole continues at page + 1;
    a page cut to `limit` cannot continue (page + 1 would skip the rows cut); nothing ever ends the lane."""
    URL = "https://www.kaggle.com/api/v1/datasets/list"
    MEMBER = {"ref": "owner/data", "title": "A dataset", "ownerName": "owner", "lastUpdated": "2026-01-01T00:00:00Z"}

    def test_continues(self):
        self.check(kaggle, "GET", self.URL, {"twenty, all kept": ([self.MEMBER] * 20, {"limit": 20}, more(2, 20)),
                                             "five of a limit of twenty": ([self.MEMBER] * 5, {"limit": 20}, more(2, 5)),
                                             "five of a limit of five, on page 3": ([self.MEMBER] * 5, {"limit": 5, "page": 3}, more(4, 5))})

    def test_a_page_cut_to_the_limit_neither_continues_nor_ends(self):
        self.check(kaggle, "GET", self.URL, {"a page of twenty cut to five": ([self.MEMBER] * 20, {"limit": 5}, neither(5)),
                                             "a page of eight cut to five": ([self.MEMBER] * 8, {"limit": 5}, neither(5))})

    def test_an_empty_page_is_not_the_end(self):
        self.check(kaggle, "GET", self.URL, {"an empty page": ([], {"limit": 20, "page": 2}, neither(0))})


class OpenMLDatasets(Cases):
    """OpenML: its own client (openml-python) ends a listing on a batch shorter than the limit it asked, and on
    error 372 ("No results. There where no matches for the given constraints."), which the server answers with
    HTTP 412. A full page continues at the next offset."""
    URL = "https://www.openml.org/api/v1/json/data/list/"
    MEMBER = datasets.OPENML_LIST["data"]["dataset"][0]

    def test_continues(self):
        self.check(openml, "GET", self.URL, {"a full page": ({"data": {"dataset": [self.MEMBER] * 2}}, {"limit": 2}, more(2, 2)),
                                             "a full later page": ({"data": {"dataset": [self.MEMBER] * 2}}, {"limit": 2, "offset": 4},
                                                                   more(6, 2))})

    def test_ends(self):
        self.check(openml, "GET", self.URL, {
            "a short final page": ({"data": {"dataset": [self.MEMBER]}}, {"limit": 2, "offset": 4}, last(1)),
            "no match at this offset (372)": ({"error": {"code": "372", "message": "No results"}}, {"limit": 2, "offset": 6}, last(0), 412),
        })

    def test_another_precondition_failure_is_no_answer(self):
        """Only code 372 is "no results": any other 412 (370 "Illegal filter specified") is an unusable answer."""
        with self.assertRaises(SourceUnavailable):
            ask(openml, "GET", self.URL, {"error": {"code": "370", "message": "Illegal filter specified"}}, 412, limit=2)


class SocrataCatalog(Cases):
    """Socrata's discovery API: resultSetSize is "The total number of assets that could be returned from a
    query", and a search whose offset + limit exceeds 10000 is refused with a 400. The page reaching the size
    is the last; no next page is offered past the window, and the window ends nothing."""
    URL = "https://api.us.socrata.com/api/catalog/v1"

    def setUp(self):
        self.addCleanup(socrata.reset_known_domains)

    @staticmethod
    def page(items: int, size=None) -> dict:
        body = {"results": [datasets.SOCRATA_CATALOG["results"][0]] * items, "timings": {"serviceMillis": 9, "searchMillis": [4, 3]}}
        return body if size is None else {**body, "resultSetSize": size}

    def test_continues(self):
        self.check(socrata, "GET", self.URL, {
            "a page short of the size": (self.page(2, 5), {"limit": 2}, more(2, 2)),
            "the last page the window admits a successor to": (self.page(100, 50_000), {"limit": 100, "offset": 9800}, more(9900, 100)),
        })

    def test_ends(self):
        self.check(socrata, "GET", self.URL, {
            "the final non-empty page reaches the size": (self.page(1, 5), {"limit": 2, "offset": 4}, last(1)),
            "a full final page reaches the size": (self.page(2, 4), {"limit": 2, "offset": 2}, last(2)),
            "nothing matched": (self.page(0, 0), {"limit": 2}, last(0)),
        })

    def test_neither(self):
        self.check(socrata, "GET", self.URL, {
            "no resultSetSize": (self.page(2), {"limit": 2}, neither(2)),
            "an empty page short of the size": (self.page(0, 5), {"limit": 2, "offset": 2}, neither(0)),
            "a page whose successor the 10,000 window refuses": (self.page(100, 50_000), {"limit": 100, "offset": 9900}, neither(100)),
        })


def garbled(body: dict, *path_and_value) -> dict:
    """`body` with the value at the path replaced (a deep copy): the paging metadata present but not what it should be."""
    *path, value = path_and_value
    out = copy.deepcopy(body)
    cur = out
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value
    return out


class UnreadableMetadataNeverEnds(Cases):
    """2b-repair-8 R7-1, everywhere an adapter derives an end from the provider's own metadata: metadata that is THERE
    but cannot be read — a total that is not a number, a cursor that is a list — is neither a continuation nor an end.
    The adapters end a lane only from a positive reading (a number reaching a number, a cursor handed back unchanged, a
    short page, a header read whole) and a continuation is a cursor or a number read as one, so a reading that fails
    lands on `neither`, which the router makes a lower bound (partial_pagination). Hugging Face's header is
    tests/test_link_header.py; the oracle here is the `neither` of each provider's own table above."""

    COUNTS = ("5", ["5"], {"n": 5}, 2.5, True)   # present, and not a number
    TOKENS = (["c2"], {"n": 2}, 2.5, True)      # present, and not a string or an integer

    def test_a_count_that_cannot_be_read_ends_nothing(self):
        for value in self.COUNTS:
            with self.subTest(value=value):
                self.check(datacite, "GET", DataCiteDois.URL, {"a total that is not a number": (
                    garbled(DataCiteDois.page(2, 1, 2, 5), "meta", "total", value), {"limit": 2}, neither(2))})
                self.check(doaj, "GET", DoajArticles.URL, {"a total that is not a number": (
                    garbled(DoajArticles.page(2, 1, 2, 5), "total", value), {"limit": 2}, neither(2))})
                for mod, url in DataverseSearch.SOURCES:
                    self.check(mod, "GET", url, {"a total_count that is not a number": (
                        garbled(DataverseSearch.page(2, 1, 2, 5), "data", "total_count", value), {"limit": 2}, neither(2))})
                self.check(socrata, "GET", SocrataCatalog.URL, {"a resultSetSize that is not a number": (
                    garbled(SocrataCatalog.page(2, 5), "resultSetSize", value), {"limit": 2}, neither(2))})
                self.check(openaire, "GET", OpenAireProducts.URL, {"a numFound that is not a number, on a first page that would hold it": (
                    garbled(OpenAireProducts.page(2, "c3", found=2), "header", "numFound", value), {"limit": 2}, more("c3", 2))})

    def test_a_cursor_that_cannot_be_read_continues_nothing_and_ends_nothing(self):
        for value in self.TOKENS:
            with self.subTest(value=value):
                self.check(crossref, "GET", Crossref.URL, {"a next-cursor that is not a string": (
                    garbled(Crossref.page(2), "message", "next-cursor", value), {"limit": 2, "cursor": "c1"}, neither(2))})
                self.check(openaire, "GET", OpenAireProducts.URL, {"a nextCursor that is not a string": (
                    garbled(OpenAireProducts.page(2, "c3"), "header", "nextCursor", value), {"limit": 2, "cursor": "c2"}, neither(2))})
                self.check(europepmc, "GET", EuropePmcSearch.URL, {"a nextCursorMark that is not a string": (
                    garbled(EuropePmcSearch.page(2, "c2"), "nextCursorMark", value), {"limit": 2, "cursor": "c1"}, neither(2))})
                self.check(govinfo, "POST", GovInfoSearch.URL, {"an offsetMark that is not a string": (
                    garbled(GovInfoSearch.page(2, "m2"), "offsetMark", value), {"limit": 2, "offset_mark": "m1"}, neither(2))})

    def test_a_next_offset_that_cannot_be_read_is_not_a_continuation(self):
        for value in (["2"], {"n": 2}, True, 2.5):
            with self.subTest(value=value):
                self.check(semanticscholar, "GET", SemanticScholarSearch.URL, {"a `next` that is not a number": (
                    garbled(SemanticScholarSearch.page(2, 0, 2), "next", value), {"limit": 2}, neither(2))})

    def test_an_openml_error_that_cannot_be_read_is_an_outage_never_no_results(self):
        for name, body in (("an unparseable body", b'{"error": {"code": "37'), ("an error that is a string", {"error": "372"}),
                           ("a code that is a list", {"error": {"code": ["372"]}}), ("no error at all", {}), ("a list", [])):
            with self.subTest(name):
                with self.assertRaises(SourceUnavailable):
                    ask(openml, "GET", OpenMLDatasets.URL, body, 412, limit=2, offset=6)

    def test_control_the_readable_forms_still_end_and_continue(self):
        self.check(datacite, "GET", DataCiteDois.URL, {"a total read": (DataCiteDois.page(1, 3, 2, 5), {"limit": 2, "page": 3}, last(1)),
                                                      "a page short of it": (DataCiteDois.page(2, 1, 2, 5), {"limit": 2}, more(2, 2))})
        self.check(openml, "GET", OpenMLDatasets.URL, {"error 372": ({"error": {"code": "372", "message": "No results"}},
                                                                    {"limit": 2, "offset": 6}, last(0), 412)})
        self.check(semanticscholar, "GET", SemanticScholarSearch.URL, {"a next offset": (SemanticScholarSearch.page(2, 0, 2), {"limit": 2}, more(2, 2))})


class HuggingFaceDatasets(unittest.TestCase):
    """Hugging Face: the official client's pagination helper (huggingface_hub, utils/_pagination.py) follows
    the answer's `Link` header with rel="next" — "Next link already contains query params" — and stops when
    there is none; the official JavaScript client (@huggingface/hub, list-datasets) does the same. The
    adapter hands that URL back as the lane's continuation and asks it verbatim; a next link present is
    never the end, and no offset is ever invented."""
    LISTING = "https://huggingface.co/api/datasets"
    NEXT = "https://huggingface.co/api/datasets?search=q&limit=2&full=true&cursor=eyJfaWQiOiI2NTAwIn0"

    def page(self, items: int, link: str | None = None, cursor: str | None = None) -> tuple[dict, list]:
        t = FakeTransport()
        t.add("GET", self.LISTING, body=[datasets.HF_DATASET] * items, headers={"Link": link} if link else None)
        c = Client(broker=Broker({"huggingface": RatePolicy(per_second=1000)}), transport=t, secrets=lambda name, field=None: "hf_tok")
        out = huggingface.find(c, "q", limit=2, **({"cursor": cursor} if cursor else {}))
        return {"next": out.get("next_cursor"), "exhausted": out.get("exhausted") is True, "records": len(out["records"])}, t.calls

    def test_continues(self):
        for name, items in (("a full page", 2), ("a short page", 1), ("an empty page", 0)):
            with self.subTest(name):
                self.assertEqual(self.page(items, f'<{self.NEXT}>; rel="next"')[0], more(self.NEXT, items))
        with self.subTest("a relative next link beside another relation"):
            got, _ = self.page(2, f'<{self.LISTING}?search=q&cursor=p>; rel="prev", </api/datasets?search=q&cursor=n>; rel="next"')
            self.assertEqual(got, more(f"{self.LISTING}?search=q&cursor=n", 2))

    def test_ends(self):
        for name, items, link in (("a full page", 2, None), ("a short page", 1, None), ("an empty page", 0, None),
                                  ("a page linking only back", 2, f'<{self.NEXT}>; rel="prev"')):
            with self.subTest(name):
                self.assertEqual(self.page(items, link)[0], last(items))

    def test_the_next_page_is_asked_at_the_providers_own_url(self):
        first, asked = self.page(2, f'<{self.NEXT}>; rel="next"')
        self.assertNotIn("offset", asked[0][1], "the first page invents no offset")
        _, asked = self.page(1, cursor=first["next"])
        self.assertEqual([call[1] for call in asked], [self.NEXT], "verbatim: the provider's cursor URL, nothing rewritten")
        self.assertEqual(asked[0][2]["Authorization"], "Bearer hf_tok", "the adapter's own credentials, in its own header")

    LEAVING = ("https://evil.example/api/datasets?search=q&cursor=x", "http://huggingface.co/api/datasets?search=q&cursor=x",
               "https://huggingface.co:8443/api/datasets?search=q&cursor=x", "https://user:pw@huggingface.co/api/datasets?search=q&cursor=x",
               "https://huggingface.co/api/models?search=q&cursor=x", "https://huggingface.co/api/datasets?search=another&cursor=x",
               "https://huggingface.co/api/datasets?search=q&cursor=x#frag")

    def test_a_next_link_that_leaves_this_search_is_not_a_continuation(self):
        for link in self.LEAVING:
            with self.subTest(link):
                self.assertEqual(self.page(2, f'<{link}>; rel="next"')[0], neither(2), "nothing to follow, and a next link is not the end")

    def test_a_continuation_that_leaves_this_search_is_never_asked(self):
        for link in self.LEAVING:
            with self.subTest(link):
                t = FakeTransport()
                c = Client(broker=Broker({"huggingface": RatePolicy(per_second=1000)}), transport=t, secrets=lambda name, field=None: "hf_tok")
                try:
                    huggingface.find(c, "q", cursor=link)
                    raised = None
                except Exception as e:   # whatever a request sent to it would have raised, it must not be sent
                    raised = e
                self.assertEqual(t.calls, [], "refused before any request: no credentials leave for it")
                self.assertIsInstance(raised, ValueError, "a continuation this lane never gave")

    def test_the_lane_continues_until_the_hub_stops_linking(self):
        """Through the router: a short page WITH a next link continues (Astra's reproduction was called
        complete and exhausted); a full page WITHOUT one is the end, and its sentinel skips the lane."""
        t = FakeTransport()
        c = Client(broker=Broker({"huggingface": RatePolicy(per_second=1000)}), transport=t, secrets=lambda name, field=None: None)
        router = R.Router(read_seed(), adapters.load_all())
        find = {"request_type": "find", "query": "q", "kind": "dataset", "domain": "ai-ml", "lanes": ["huggingface"],
                "accept_per_item": True, "limit": 2}
        t.add("GET", self.LISTING + "?", body=[datasets.HF_DATASET], headers={"Link": f'<{self.NEXT}>; rel="next"'})
        first = R.execute(router, find, c)
        t.routes.clear()
        t.add("GET", self.NEXT, body=[datasets.HF_DATASET, dict(datasets.HF_DATASET, id="owner/other")])
        second = R.execute(router, {**find, "cursors": first["next"]}, c)
        lanes = [{k: out["lanes"][0].get(k) for k in ("coverage", "completeness", "count", "next", "exhausted")} for out in (first, second)]
        self.assertEqual(lanes, [{"coverage": "searched_ok", "completeness": "complete", "count": 1, "next": self.NEXT, "exhausted": None},
                                 {"coverage": "searched_ok", "completeness": "complete", "count": 2, "next": None, "exhausted": True}])
        self.assertEqual([call[1] for call in t.calls][1:], [self.NEXT])
        self.assertEqual(second["next"], {"huggingface": R.EXHAUSTED_CURSOR})


if __name__ == "__main__":
    unittest.main()
