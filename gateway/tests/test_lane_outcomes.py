"""Task 2b, acceptance item 3 (lane level): what a lane entry says about what was observed.

Every lane entry carries coverage (STATION-CONTRACT.md §2), completeness (complete |
partial | unobserved) and, when degraded or partial, an error_class from the engine
store's vocabulary; `count` exists only for an observed result set and is a lower bound
when partial. A stub adapter isolates each outcome. Each negative has its paired
accepted-path control. `store_admits` restates, independently, the CHECK constraints the
engine store puts on search_observations (gen2/store/schema/03-evidence-and-decisions.sql)
so a lane entry the engine could not record faithfully fails here, at the gateway.
"""
from __future__ import annotations

import types
import unittest

from research_gateway import adapters
from research_gateway.adapters import socrata
from research_gateway.adapters.base import Client, FakeTransport, PayloadError, Response, SourceUnavailable, members
from research_gateway.core.schema import decode   # a parsed value, as this test states it
from research_gateway.core import schema as S
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.cache import Cache

OK_STATES = ("searched_ok", "searched_empty", "metadata_only")
ERROR_CLASSES = ("payload_invalid", "timeout", "rate_limited", "breaker_open", "budget_refused", "provider_outage",
                 "credentials_rejected", "credentials_not_configured", "secrets_backend_failing", "transport_failure",
                 "telemetry_missing", "partial_pagination")


def store_admits(entry: dict) -> list[str]:
    """Which of the store's search_observations CHECKs this lane entry would break (none = recordable)."""
    cov, comp, count, err = entry.get("coverage"), entry.get("completeness"), entry.get("count"), entry.get("error_class")
    broken = []
    if comp not in ("complete", "partial", "unobserved"):
        broken.append("completeness vocabulary")
    if err is not None and err not in ERROR_CLASSES:
        broken.append("error_class vocabulary")
    if cov in ("searched_ok",) and not (count is not None and count >= 1):
        broken.append("searched_ok needs a count >= 1")
    if cov == "searched_empty" and count != 0:
        broken.append("searched_empty is a count of 0")
    if cov not in OK_STATES and count is not None:
        broken.append("a degraded state carries no count")
    if cov in ("provider_unavailable", "auth_failed", "unknown") and err is None:
        broken.append("a degraded state names its error class")
    if (cov in OK_STATES) != (comp != "unobserved"):
        broken.append("observed states and only they have a result set")
    if cov == "searched_empty" and comp != "complete":
        broken.append("searched_empty is only ever complete")
    if comp == "partial" and err is None:
        broken.append("a partial set says why")
    if cov in ("searched_ok", "searched_empty") and comp != "partial" and err is not None:
        broken.append("a complete success carries no error class")
    return broken


def stub(find=None, resolve=None):
    calls = []

    def _find(client, query, *, limit=20, cursor=None):
        calls.append(cursor)
        return find(cursor)

    def _resolve(client, identity):
        calls.append(identity)
        return resolve(identity)

    mod = types.SimpleNamespace(SOURCE_ID="stub", CAPABILITIES=("find", "resolve"), SCHEMES=("stub",), find=_find, resolve=_resolve)
    row = {"id": "stub", "name": "Stub", "kind": "article", "enabled": True, "capabilities": ["find", "resolve"],
           "base_for": ["article"], "domains": [], "use_commercial": "allow"}
    router = R.Router([row], {"stub": mod})
    return router, Client(broker=Broker({"stub": RatePolicy(per_second=1000)}), transport=FakeTransport()), calls


def rec(i):
    return {"identity": f"doi:10.1234/{i}", "kind": "article", "source_id": "stub", "title": f"T{i}"}


def find(router, client, **payload):
    return R.execute(router, {"request_type": "find", "query": "q", "kind": "article", **payload}, client)


class LaneOutcomes(unittest.TestCase):
    def lane(self, out):
        self.assertEqual(len(out["lanes"]), 1, out["lanes"])
        entry = out["lanes"][0]
        self.assertEqual(store_admits(entry), [], entry)
        if entry.get("count") is not None:   # every counted record is named: a count is never a bare number (E-2)
            self.assertEqual(len(entry["retrieved"]), entry["count"], entry)
        else:
            self.assertNotIn("retrieved", entry)
        return entry

    def test_an_unreadable_answer_is_unavailable_with_no_count(self):
        def boom(cursor):
            raise PayloadError("stub: the answer has no results")
        r, c, _ = stub(find=boom)
        e = self.lane(find(r, c))
        self.assertEqual({k: e.get(k) for k in ("coverage", "completeness", "error_class", "count", "exhausted", "next")},
                         {"coverage": "provider_unavailable", "completeness": "unobserved", "error_class": "payload_invalid",
                          "count": None, "exhausted": None, "next": None})

    def test_control_a_readable_empty_answer_is_searched_empty(self):
        r, c, _ = stub(find=lambda cursor: {"records": [], "exhausted": True})
        e = self.lane(find(r, c))
        self.assertEqual((e["coverage"], e["completeness"], e["count"], e.get("error_class"), e.get("exhausted")),
                         ("searched_empty", "complete", 0, None, True))

    def test_dropped_records_make_a_partial_lower_bound(self):
        r, c, _ = stub(find=lambda cursor: {"records": [rec(1), rec(2), {"identity": None, "kind": "article"}], "next_cursor": "c2"})
        out = find(r, c)
        e = self.lane(out)
        self.assertEqual((e["coverage"], e["completeness"], e["count"], e["error_class"], e["next"]),
                         ("searched_ok", "partial", 2, "payload_invalid", "c2"))
        self.assertEqual(e["retrieved"], ["doi:10.1234/1", "doi:10.1234/2"], "the observed identities, in rank order")
        self.assertTrue(any("lower bound" in f for f in out["facts"]))
        self.assertEqual(len(out["records"]), 2, "what was observed is kept")

    def test_a_partial_lane_is_never_exhausted(self):
        """Not even when its adapter reports the end (2b-repair-6 F3: exhaustion is that report, on a whole answer)."""
        r, c, _ = stub(find=lambda cursor: {"records": [rec(1), "junk"], "exhausted": True})
        e = self.lane(find(r, c))
        self.assertEqual((e["completeness"], e.get("exhausted")), ("partial", None))
        r, c, _ = stub(find=lambda cursor: {"records": [rec(1)], "exhausted": True})
        self.assertTrue(self.lane(find(r, c))["exhausted"], "control: a complete last page is exhausted")

    def test_control_all_readable_records_are_complete(self):
        r, c, _ = stub(find=lambda cursor: {"records": [rec(1), rec(2), rec(3)], "exhausted": True})
        e = self.lane(find(r, c))
        self.assertEqual((e["coverage"], e["completeness"], e["count"], e.get("error_class")), ("searched_ok", "complete", 3, None))

    def test_withheld_stored_records_make_a_partial_lower_bound(self):
        """2b-repair-5 F2: stored matches the serving read withheld (rows not yet converted) are never a
        shorter complete answer: what was served is a partial lower bound, and if nothing was, nothing was
        observed — never searched_empty, never exhausted, never replayed from the search cache."""
        keys = ("coverage", "completeness", "count", "error_class", "exhausted")
        cache = Cache()
        r, c, _ = stub(find=lambda cursor: {"records": [rec(1)], "withheld": 2, "exhausted": True})
        out = R.execute(r, {"request_type": "find", "query": "q", "kind": "article"}, c, cache=cache)
        self.assertEqual(tuple(self.lane(out).get(k) for k in keys), ("searched_ok", "partial", 1, "payload_invalid", None))
        self.assertTrue(any("2 matching stored record(s) withheld" in f and "lower bound" in f for f in out["facts"]), out["facts"])
        self.assertIsNone(cache.get_search(cache.search_key("find", R._search_payload({"request_type": "find", "query": "q", "kind": "article"}))))
        r, c, _ = stub(find=lambda cursor: {"records": [], "withheld": 1, "exhausted": True})
        self.assertEqual(tuple(self.lane(find(r, c)).get(k) for k in keys), ("provider_unavailable", "unobserved", None, "payload_invalid", None))
        r, c, _ = stub(find=lambda cursor: {"records": [rec(1)], "withheld": 0, "exhausted": True})
        self.assertEqual(tuple(self.lane(find(r, c)).get(k) for k in keys), ("searched_ok", "complete", 1, None, True),
                         "control: nothing withheld is complete")

    def test_only_unreadable_records_observe_nothing(self):
        for records in ([{"identity": "x"}], ["junk", 7], {"not": "a list"}):
            with self.subTest(records=records):
                r, c, _ = stub(find=lambda cursor: {"records": records})
                e = self.lane(find(r, c))
                self.assertEqual((e["coverage"], e["completeness"], e.get("count"), e["error_class"]),
                                 ("provider_unavailable", "unobserved", None, "payload_invalid"))

    def test_a_fabricated_identity_is_a_dropped_record(self):
        """A4 at the router: a record whose identity was built from a missing value names nothing."""
        for fabricated in ("url:None", "openml:", "series:fred:null", "hf:undefined"):
            with self.subTest(fabricated):
                r, c, _ = stub(find=lambda cursor: {"records": [rec(1), {"identity": fabricated, "kind": "article"}]})
                e = self.lane(find(r, c))
                self.assertEqual((e["coverage"], e["completeness"], e.get("count"), e.get("retrieved"), e.get("error_class")),
                                 ("searched_ok", "partial", 1, ["doi:10.1234/1"], "payload_invalid"))

    def test_a_failed_continuation_page_keeps_its_cursor(self):
        def pages(cursor):
            if cursor == "c2":
                raise SourceUnavailable("stub", Response(503, {}, b"", "u"))
            return {"records": [rec(1)], "next_cursor": "c2"}
        r, c, _ = stub(find=pages)
        first = find(r, c)
        self.assertEqual((self.lane(first)["cursor"], first["next"]), (None, {"stub": "c2"}))
        failed = find(r, c, cursors={"stub": "c2"})
        e = self.lane(failed)
        self.assertEqual((e["cursor"], e["coverage"], e["error_class"], e.get("next"), e.get("exhausted")),
                         ("c2", "provider_unavailable", "provider_outage", None, None))
        self.assertNotIn("stub", failed.get("next") or {}, "no continuation is invented for a failed page")

    def test_each_refusal_names_its_error_class(self):
        cases = ((Response(401, {}, b"", "u"), "auth_failed", "credentials_rejected"),
                 (Response(403, {}, b"", "u"), "auth_failed", "credentials_rejected"),
                 (Response(429, {}, b"", "u"), "provider_unavailable", "rate_limited"),
                 (Response(500, {}, b"", "u"), "provider_unavailable", "provider_outage"),
                 (Response(404, {}, b"", "u"), "provider_unavailable", "provider_outage"),
                 (Response(None, {}, b"", "u", error="BreakerOpen: stub: breaker open until 9 (x)"), "provider_unavailable", "breaker_open"),
                 (Response(None, {}, b"", "u", error="BudgetExhausted: stub: daily request budget exhausted"), "provider_unavailable", "budget_refused"),
                 (Response(None, {}, b"", "u", error="NoPolicy: stub"), "provider_unavailable", "budget_refused"),
                 (Response(None, {}, b"", "u", error="URLError: <urlopen error timed out>"), "provider_unavailable", "timeout"),
                 (Response(None, {}, b"", "u", error="URLError: [Errno 111] Connection refused"), "provider_unavailable", "transport_failure"),
                 (Response(200, {}, b"", "u", error="HTML answer with a success status (unreadable)"), "provider_unavailable", "payload_invalid"))
        for resp, coverage, error_class in cases:
            with self.subTest(status=resp.status, error=resp.error):
                def refuse(cursor, resp=resp):
                    raise SourceUnavailable("stub", resp)
                r, c, _ = stub(find=refuse)
                e = self.lane(find(r, c))
                self.assertEqual((e["coverage"], e["error_class"], e["completeness"]), (coverage, error_class, "unobserved"))

    def test_a_fact_only_answer_is_degraded_not_empty(self):
        cases = (("no Stub key configured", "auth_failed", "credentials_not_configured"),
                 ("local index needs a database connection", "provider_unavailable", "provider_outage"))
        for fact, coverage, error_class in cases:
            with self.subTest(fact):
                r, c, _ = stub(find=lambda cursor, fact=fact: {"records": [], "capability_fact": fact})
                e = self.lane(find(r, c))
                self.assertEqual((e["coverage"], e["error_class"], e.get("count")), (coverage, error_class, None))

    def test_a_resolve_capability_fact_is_not_not_found(self):
        r, c, _ = stub(resolve=lambda identity: {"capability_fact": "no Stub key configured"})
        e = self.lane(R.execute(r, {"request_type": "resolve", "identity": "stub:1"}, c))
        self.assertEqual((e["coverage"], e["error_class"]), ("auth_failed", "credentials_not_configured"))
        r, c, _ = stub(resolve=lambda identity: None)
        e = self.lane(R.execute(r, {"request_type": "resolve", "identity": "stub:1"}, c))
        self.assertEqual((e["coverage"], e["count"]), ("searched_empty", 0), "control: not found is a successful empty answer")

    def test_an_exhausted_lane_reports_no_count(self):
        r, c, calls = stub(find=lambda cursor: {"records": [rec(1)]})
        e = self.lane(find(r, c, cursors={"stub": "exhausted"}))
        self.assertEqual((e["coverage"], e["completeness"], e.get("count")), ("exhausted", "unobserved", None))
        self.assertEqual(calls, [], "nothing is dispatched for it")


class DegradedAnswersAreNotReplayed(unittest.TestCase):
    """A degraded or partial answer is re-asked, never served again from the search cache
    as if it were the whole answer (a retry must be able to reach a recovered provider)."""

    def test_a_degraded_answer_is_asked_again(self):
        state = {"down": True}

        def flaky(cursor):
            if state["down"]:
                raise SourceUnavailable("stub", Response(503, {}, b"", "u"))
            return {"records": [rec(1)], "exhausted": True}
        r, c, calls = stub(find=flaky)
        cache = Cache(None)
        first = R.execute(r, {"request_type": "find", "query": "q", "kind": "article"}, c, cache)
        self.assertEqual(first["lanes"][0]["coverage"], "provider_unavailable")
        state["down"] = False
        again = R.execute(r, {"request_type": "find", "query": "q", "kind": "article"}, c, cache)
        self.assertFalse(again.get("cache_hit"))
        self.assertEqual((again["lanes"][0]["coverage"], len(calls)), ("searched_ok", 2))

    def test_control_a_complete_answer_is_served_from_cache(self):
        r, c, calls = stub(find=lambda cursor: {"records": [rec(1)], "exhausted": True})
        cache = Cache(None)
        R.execute(r, {"request_type": "find", "query": "q", "kind": "article"}, c, cache)
        again = R.execute(r, {"request_type": "find", "query": "q", "kind": "article"}, c, cache)
        self.assertEqual((again.get("cache_hit"), len(calls)), (True, 1))

    def test_a_partial_answer_is_asked_again(self):
        r, c, calls = stub(find=lambda cursor: {"records": [rec(1), "junk"]})
        cache = Cache(None)
        R.execute(r, {"request_type": "find", "query": "q", "kind": "article"}, c, cache)
        again = R.execute(r, {"request_type": "find", "query": "q", "kind": "article"}, c, cache)
        self.assertEqual((again.get("cache_hit"), len(calls)), (None, 2))


if __name__ == "__main__":
    unittest.main()


class RealAdapterMembers(unittest.TestCase):
    """Task 2b-repair A4: a provider's MEMBERS, decoded by the real adapters (Crossref, DOAJ)
    through the real router and seed, not a stub returning canonical records. An unreadable
    member is never a candidate (no `url:None`); a bad member beside readable ones leaves those
    as a partial lower bound — never exhausted, never replayed from the cache. Oracle: the
    identities the provider bodies below name, stated here by hand."""

    CROSSREF = ("https://api.crossref.org/works?", lambda items: {"message": {"items": items, "total-results": len(items)}})
    DOAJ = ("https://doaj.org/api/search/articles/", lambda items: {"results": items, "total": len(items)})
    VALID = {"crossref": ({"DOI": "10.1234/valid", "title": ["Good"]}, "doi:10.1234/valid"),
             "doaj": ({"id": "d1", "bibjson": {"title": "Open", "identifier": [{"type": "doi", "id": "10.5555/oa1"}]}}, "doi:10.5555/oa1")}

    def ask(self, lane: str, items: list, cache: Cache, times: int = 2):
        """The same find, `times` times, with the provider answering `items` each time; the lane's
        entries and whether each answer was served from the search cache."""
        from tests.test_routing import SEED_NO_INDEX, make
        router, client, transport = make(SEED_NO_INDEX)
        prefix, body = self.CROSSREF if lane == "crossref" else self.DOAJ
        answers = []
        for _ in range(times):
            transport.add("GET", prefix, body=body(items))
            out = R.execute(router, {"request_type": "find", "query": "q", "kind": "article", "lanes": [lane]}, client, cache)
            answers.append(({e["source"]: e for e in out["lanes"]}[lane], bool(out.get("cache_hit")), [r["identity"] for r in out["records"]]))
        return answers

    def test_an_unreadable_member_is_never_a_candidate(self):
        for lane, items in (("crossref", [{}]), ("crossref", [{"DOI": None, "URL": None, "title": ["no identifier"]}]),
                            ("crossref", ["not a work"]), ("crossref", [7]), ("doaj", [{}]), ("doaj", [7])):
            with self.subTest(lane=lane, items=items):
                for entry, cached, identities in self.ask(lane, items, Cache(None)):
                    self.assertEqual((entry["coverage"], entry["completeness"], entry.get("error_class")),
                                     ("provider_unavailable", "unobserved", "payload_invalid"))
                    self.assertNotIn("count", entry)
                    self.assertFalse(entry.get("exhausted"))
                    self.assertNotIn("next", entry)
                    self.assertFalse(cached, "a degraded answer is asked again, never replayed")
                    self.assertEqual(identities, [])

    def test_a_later_bad_member_keeps_the_earlier_as_a_partial_lower_bound(self):
        for lane in ("crossref", "doaj"):
            member, identity = self.VALID[lane]
            for bad in (7, {}, {**member, "author" if lane == "crossref" else "bibjson": 7}):
                with self.subTest(lane=lane, bad=bad):
                    for entry, cached, identities in self.ask(lane, [member, bad], Cache(None)):
                        self.assertEqual((entry["coverage"], entry["completeness"], entry.get("error_class"), entry.get("count"), entry.get("retrieved")),
                                         ("searched_ok", "partial", "payload_invalid", 1, [identity]))
                        self.assertFalse(entry.get("exhausted"), "a partial lane never claims it returned everything")
                        self.assertFalse(cached, "a partial answer is asked again, never replayed")
                        self.assertEqual(identities, [identity])
                        self.assertEqual(store_admits(entry), [])

    def test_each_member_is_decoded_alone(self):
        """The helper every find path decodes members with: a non-object member, a member whose
        decoding raises, and one whose record names nothing are each None beside a good one."""
        def build(m):
            if m["boom"] is not None:
                raise KeyError("DOI")
            return {"identity": m["id"], "kind": "article"}
        decoded = decode("stub", S.members(S.obj({"id": S.text(), "boom": S.whole()})), [{"id": "doi:10.1/a"}, 7, {"boom": 1}, {"id": "url:None"}, {"id": "doi:10.1/b"}])   # as the decoder hands it over
        try:
            got = members("stub", decoded, build)
        except KeyError as e:
            self.fail(f"one member's decoding failure escaped as {e!r}: it is that member's, not the answer's")
        self.assertEqual(got, [{"identity": "doi:10.1/a", "kind": "article"}, None, None, None, {"identity": "doi:10.1/b", "kind": "article"}])

    def socrata(self, items: list):
        """One finance/dataset find on the Socrata lane alone, the catalog answering `items`."""
        from tests.test_adapters_datasets import client as dataset_client
        from tests.test_routing import SEED_NO_INDEX
        socrata.reset_known_domains()
        self.addCleanup(socrata.reset_known_domains)
        c, t = dataset_client({})
        t.add("GET", "https://api.us.socrata.com/api/catalog/v1?", body={"results": items, "resultSetSize": 5})
        out = R.execute(R.Router(SEED_NO_INDEX, adapters.load_all()), {"request_type": "find", "query": "q", "kind": "dataset",
                        "domain": "finance", "lanes": ["socrata"], "accept_per_item": True}, c)
        (entry,) = [e for e in out["lanes"] if e["source"] == "socrata"]
        self.assertEqual(store_admits(entry), [], entry)
        return entry

    def test_a_socrata_member_that_is_not_an_object_keeps_the_readable_ones(self):
        """Astra (2b-repair-6 review): Socrata learnt portal domains from the raw members BEFORE each was
        decoded alone, so a non-object member beside a readable one lost the whole page — unobserved,
        the readable member gone (the same on d7cd61b). Now only a member read whole vouches a portal."""
        from tests.test_adapters_datasets import SOCRATA_CATALOG
        member = SOCRATA_CATALOG["results"][0]
        for bad in (7, "not a dataset", {"resource": {"id": "x"}, "metadata": "not an object"}):
            with self.subTest(bad=bad):
                entry = self.socrata([member, bad])
                self.assertEqual((entry["coverage"], entry["completeness"], entry.get("error_class"), entry.get("count"),
                                  entry.get("retrieved")),
                                 ("searched_ok", "partial", "payload_invalid", 1, ["socrata:data.cityofchicago.org:abcd-1234"]))
                self.assertEqual(socrata._KNOWN_DOMAINS, {"data.cityofchicago.org"}, "the readable member vouches its portal")

    def test_control_a_whole_socrata_page_is_complete(self):
        from tests.test_adapters_datasets import SOCRATA_CATALOG
        entry = self.socrata(SOCRATA_CATALOG["results"])
        self.assertEqual((entry["coverage"], entry["completeness"], entry.get("error_class"), entry.get("count")),
                         ("searched_ok", "complete", None, 1))
        self.assertEqual(socrata._KNOWN_DOMAINS, {"data.cityofchicago.org"})

    def test_control_readable_members_are_complete_and_cached(self):
        for lane in ("crossref", "doaj"):
            member, identity = self.VALID[lane]
            with self.subTest(lane=lane):
                (first, cached1, ids1), (second, cached2, ids2) = self.ask(lane, [member], Cache(None))
                self.assertEqual((first["coverage"], first["completeness"], first["count"], first["retrieved"]),
                                 ("searched_ok", "complete", 1, [identity]))
                self.assertTrue(first.get("exhausted"))
                self.assertEqual((cached1, cached2, ids1, ids2), (False, True, [identity], [identity]))
