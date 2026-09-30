"""Recorded gateway answers for the engine's gateway client (task 2b).

The engine's client (gen2/gateway_client) is tested against what THIS gateway actually
answers, never against a hand-written imitation: each scenario below drives the real
service (the Gateway and its HTTP front door, FakeTransport providers, the loopback
Vault) with the exact requests the engine client sends, and the exchanges — request
method, path, correlation headers and body; response status, envelope headers and body —
are the fixture gen2/tests/test_gateway_client.py replays, checking the client sends the
same requests and maps these answers. Volatile values (retrieval times, grant tokens) are
normalized. This test fails when the gateway's answers drift from the committed files;
GATEWAY_RECORD_FIXTURES=1 rewrites them (then re-run both suites).

The durable request row is the one substituted part: these scenarios run without a
database, so Gateway._span is replaced by a counter returning row ids 101, 102, ... — the
gateway's own code still decides `captured` from it. One scenario keeps the real no-DB
answer (captured: false, with its capture_loss).

The committed file is a DRIFT check only (Astra's 2b review, tests 28-35: a snapshot the
implementation wrote cannot be its own acceptance oracle). Each scenario therefore also
asserts, by hand, the contract facts the engine relies on — every lane's coverage,
completeness, count, identities, error class and cursor; the caller's observation; the
effective request; the capability fact — stated here from STATION-CONTRACT.md, not read
back from the answer (task 2b-repair).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from research_gateway import app
from research_gateway.adapters.base import FakeTransport, Response
from research_gateway.api import http as api
from research_gateway.core import alerts, secrets
from research_gateway.registry.load import read_seed
from tests.fake_vault import FakeVault
from tests.test_adapters_articles import CROSSREF_WORK

# a mutation run's copy of gateway/ reads the committed fixtures from the repository it came from
FIXTURES = Path(os.environ.get("GATEWAY_SOURCE_REPOSITORY") or Path(__file__).resolve().parents[2]) / "gen2" / "tests" / "fixtures" / "gateway_answers"
RECORD = os.environ.get("GATEWAY_RECORD_FIXTURES") == "1"
TOKENS = {"engine": "tok-engine-secret"}
INV, ATT = "inv_fixture0001", 1
INV_B = "inv_fixture0002"   # a second invocation, of another topic (2b-repair-3 R2)
SEED = [dict(s, enabled=False) if s["id"] == "openalex_snapshot" else s for s in read_seed()]
T0 = 1790019900.0


class Transport(FakeTransport):
    """FakeTransport, plus answers chosen by a substring of the URL (a continuation page)."""

    def __init__(self):
        super().__init__()
        self.by_substring: list[tuple[str, Response]] = []

    def request(self, method, url, headers, body, timeout):
        for part, resp in self.by_substring:
            if part in url:
                self.calls.append((method.upper(), url, headers, body))
                return Response(resp.status, resp.headers, resp.body, url)
        return super().request(method, url, headers, body, timeout)


def providers() -> Transport:
    t = Transport()
    t.add("GET", "https://doi.org/ra/", body=[{"DOI": "10.1234/abc", "RA": "Crossref"}])
    t.add("GET", "https://api.crossref.org/works/10.1234/abc", body={"message": CROSSREF_WORK})
    t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
    t.add("GET", "https://api.stlouisfed.org/fred/series/observations?", body={"observations": [{"date": "2026-01-01", "value": "1.0"}]})
    t.add("GET", "https://api.stlouisfed.org/fred/series?", body={"seriess": [{"id": "GDP", "title": "GDP", "notes": "."}]})
    return t


def normalize(value):
    if isinstance(value, dict):
        return {k: ("2026-09-30T00:00:00+00:00" if k == "retrieved_at" and isinstance(v, str) else
                    "gwg1.fixture-grant" if k == "token" and isinstance(v, str) else
                    1790100000 if k == "expires_at" and isinstance(v, int) else normalize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize(v) for v in value]
    return value


class Recorder:
    def __init__(self, test, *, secrets_backend=None, extra_sources=(), durable=True):
        self.t = providers()
        self.gw = app.Gateway(app.Settings(tokens=TOKENS, grantors={"engine"}, workers=1, sync_timeout=10),
                              use_db=False, sources=SEED + list(extra_sources), transport=self.t,
                              secrets=secrets_backend or secrets.EnvBackend(), alerter=alerts.Alerter(None))
        if durable:
            # the durable call log is the one substitution: _observe finds a "database" and asks
            # _span for the request row, which a counter provides; requests still run inline
            # through the real executor, with no database connection behind their clients
            rows = iter(range(101, 10_000))
            gw = self.gw
            test.addCleanup(mock.patch.stopall)
            mock.patch.object(gw, "conn", object()).start()
            mock.patch.object(gw, "_span", lambda *a, **k: next(rows)).start()
            mock.patch.object(gw, "is_inline_only", lambda payload: True).start()
            mock.patch.object(gw, "_run_inline_locked", lambda payload, client_id, trace: app.execute(
                gw.router, payload, gw.make_client(None, client_id=client_id, **trace), gw.cache)).start()
        self.server = api.serve(self.gw, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        test.addCleanup(self.close)
        self.exchanges: list[dict] = []

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def send(self, method, path, body=None, *, token=TOKENS["engine"], correlated=True, invocation=INV):
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if correlated:
            headers.update({"X-Research-Invocation": invocation, "X-Research-Attempt": str(ATT)})
        data = json.dumps(body).encode() if body is not None else None
        if data:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                status, rh, raw = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            status, rh, raw = e.code, e.headers, e.read()
        doc = normalize(json.loads(raw))
        self.exchanges.append({"request": {"method": method, "path": path, "body": body,
                                           "authorization": "grant" if token.startswith("gwg1.") else "engine",
                                           "correlation": {"invocation_id": invocation, "attempt": ATT} if correlated else None},
                               "response": {"status": status, "content_type": rh.get("Content-Type"),
                                            "x_research_gateway": rh.get("X-Research-Gateway"), "body": doc}})
        return status, json.loads(raw)


def lanes_of(body: dict) -> list[tuple]:
    """(source, coverage, completeness, count, retrieved, error_class, cursor, next, exhausted) per lane."""
    return [(e["source"], e["coverage"], e["completeness"], e.get("count"), e.get("retrieved"), e.get("error_class"),
             e.get("cursor"), e.get("next"), e.get("exhausted")) for e in body["lanes"]]


def observed(body: dict) -> tuple:
    """(invocation, attempt, served, captured, call_ref, capture_loss) of the caller's observation."""
    o = body["observation"]
    return o["invocation_id"], o["attempt"], o["served"], o["captured"], o["call_ref"], o["capture_loss"]


FIND = {"query": "reranking", "kind": "article", "domain": "finance"}


class EngineFixtures(unittest.TestCase):
    maxDiff = None

    def check(self, name: str, rec: Recorder, note: str):
        doc = {"scenario": name, "note": note, "invocation_id": INV, "attempt": ATT, "exchanges": rec.exchanges}
        path = FIXTURES / f"{name}.json"
        if RECORD:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
        self.assertTrue(path.exists(), f"{path} is missing: GATEWAY_RECORD_FIXTURES=1 records it")
        self.assertEqual(json.loads(path.read_text()), json.loads(json.dumps(doc)),
                         f"the gateway's answer for {name} drifted from its fixture (re-record, then re-run gen2's client tests)")

    def test_find_complete(self):
        rec = Recorder(self)
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        status, body = rec.send("POST", "/v1/find", FIND)
        self.assertEqual(status, 200)
        self.assertEqual(lanes_of(body), [("crossref", "searched_ok", "complete", 1, ["doi:10.1234/abc"], None, None, None, True),
                                          ("doaj", "searched_empty", "complete", 0, [], None, None, None, True)])
        self.assertEqual(observed(body), (INV, ATT, "dispatched", True, 101, None))
        self.assertEqual({k: body["effective_request"][k] for k in ("request_type", "query", "kind", "domain", "limit", "cursors")},
                         {"request_type": "find", "query": "reranking", "kind": "article", "domain": "finance", "limit": 20, "cursors": {}})
        self.assertEqual([r["identity"] for r in body["records"]], ["doi:10.1234/abc"])
        self.check("find_complete", rec, "two lanes, both complete: crossref one record, doaj none")

    def test_find_served_from_cache(self):
        """The same find asked twice: the second is the cache's replay of the first dispatch,
        its lanes repeated, observed by this caller as `cache` with its own request row."""
        rec = Recorder(self)
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        first = rec.send("POST", "/v1/find", FIND)[1]
        status, again = rec.send("POST", "/v1/find", FIND)
        self.assertEqual((status, lanes_of(again)), (200, lanes_of(first)), "a replayed answer repeats the dispatch's lanes")
        self.assertEqual((again["cache_hit"], again["served_from"]), (True, "search_cache"))
        self.assertEqual(observed(again), (INV, ATT, "cache", True, 102, None))
        self.check("find_served_from_cache", rec, "one find twice: dispatched, then served from the search cache")

    def test_resolve_from_the_record_cache(self):
        """A resolve answered from the record cache: no lanes, the one record it holds, and says so."""
        rec = Recorder(self)
        status, first = rec.send("POST", "/v1/resolve", {"identity": "doi:10.1234/abc"})
        self.assertEqual(lanes_of(first), [("crossref", "searched_ok", "complete", 1, ["doi:10.1234/abc"], None, None, None, None)])
        status, again = rec.send("POST", "/v1/resolve", {"identity": "doi:10.1234/abc"})
        self.assertEqual((status, again["lanes"], again["cache_hit"], again["served_from"]), (200, [], True, "record_cache"))
        self.assertEqual([(r["identity"], r["source_id"]) for r in again["records"]], [("doi:10.1234/abc", "crossref")])
        self.assertEqual(observed(again), (INV, ATT, "cache", True, 102, None))
        self.check("resolve_from_the_record_cache", rec, "one resolve twice: dispatched to crossref, then from the record cache")

    def test_find_not_captured(self):
        rec = Recorder(self, durable=False)
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        status, body = rec.send("POST", "/v1/find", FIND)
        self.assertEqual(lanes_of(body), [("crossref", "searched_ok", "complete", 1, ["doi:10.1234/abc"], None, None, None, True),
                                          ("doaj", "searched_empty", "complete", 0, [], None, None, None, True)])
        self.assertEqual(observed(body), (INV, ATT, "dispatched", False, None, "no durable call log: this gateway runs without a database"),
                         "RG-4: the lost durable row is said, never implied captured (the engine then degrades the lanes)")
        self.check("find_not_captured", rec, "a gateway without a database: the durable request row is an explicit loss")

    def test_find_unreadable_lane(self):
        rec = Recorder(self)
        rec.t.add("GET", "https://api.crossref.org/works?", body=b'{"message": {"items": [{"DOI": "10.1234/ab')
        status, body = rec.send("POST", "/v1/find", FIND)
        self.assertEqual(lanes_of(body), [("crossref", "provider_unavailable", "unobserved", None, None, "payload_invalid", None, None, None),
                                          ("doaj", "searched_empty", "complete", 0, [], None, None, None, True)])
        self.assertNotIn("count", body["lanes"][0], "unreadable is no count, never zero")
        self.check("find_unreadable_lane", rec, "crossref answers truncated JSON: unavailable, payload_invalid, no count")

    def test_find_partial_records(self):
        """Through the REAL Crossref parser (2b-repair A4): a readable work, then a member that
        is not one — the readable one stands as a partial lower bound, not exhausted."""
        rec = Recorder(self)
        second = dict(CROSSREF_WORK, DOI="10.1234/def", title=["Reranking, continued"])
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK, 7, second, {}], "total-results": 4}})
        status, body = rec.send("POST", "/v1/find", {"query": "q", "kind": "article", "lanes": ["crossref"]})
        self.assertEqual(lanes_of(body), [("crossref", "searched_ok", "partial", 2, ["doi:10.1234/abc", "doi:10.1234/def"],
                                           "payload_invalid", None, None, None)])
        self.check("find_partial_records", rec, "two of four crossref members unreadable: searched_ok, partial, a lower bound of 2")

    def test_find_paged_then_failed(self):
        rec = Recorder(self)
        rec.t.by_substring.append(("cursor=c2", Response(503, {}, b"", "")))
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 3,
                                                                              "next-cursor": "c2"}})
        request = {"query": "reranking", "kind": "article", "domain": "finance"}
        first = rec.send("POST", "/v1/find", request)[1]
        status, second = rec.send("POST", "/v1/find", {**request, "cursors": {"crossref": "c2"}, "lanes": ["crossref"]})
        self.assertEqual(lanes_of(first)[0], ("crossref", "searched_ok", "complete", 1, ["doi:10.1234/abc"], None, None, "c2", None))
        self.assertEqual(lanes_of(second), [("crossref", "provider_unavailable", "unobserved", None, None, "provider_outage", "c2", None, None)],
                         "the failed page keeps the cursor it was asked with; no next, not exhausted")
        self.assertEqual((second["effective_request"]["cursors"], second["effective_request"]["lanes"]), ({"crossref": "c2"}, ["crossref"]))
        self.assertNotEqual(second["request_identity"], first["request_identity"], "each page is its own request")
        self.assertEqual((observed(first)[4], observed(second)[4]), (101, 102))
        self.check("find_paged_then_failed", rec, "page 1 reads one record and a cursor; page 2 fails with HTTP 503")

    def test_find_paged_complete(self):
        rec = Recorder(self)
        second = dict(CROSSREF_WORK, DOI="10.1234/def", title=["Reranking, continued"])
        rec.t.by_substring.append(("cursor=c2", Response(200, {}, json.dumps(
            {"message": {"items": [second], "total-results": 2}}).encode(), "")))
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 2,
                                                                              "next-cursor": "c2"}})
        request = {"query": "reranking", "kind": "article", "domain": "finance"}
        first = rec.send("POST", "/v1/find", request)[1]
        status, second = rec.send("POST", "/v1/find", {**request, "cursors": {"crossref": "c2"}, "lanes": ["crossref"]})
        self.assertEqual(lanes_of(first)[0], ("crossref", "searched_ok", "complete", 1, ["doi:10.1234/abc"], None, None, "c2", None))
        self.assertEqual(lanes_of(second), [("crossref", "searched_ok", "complete", 1, ["doi:10.1234/def"], None, "c2", None, True)])
        self.assertNotEqual(second["request_identity"], first["request_identity"], "each page is its own request")
        self.check("find_paged_complete", rec, "page 1 reads one record and a cursor; page 2 reads the last record")

    def test_data_secrets_failing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        token_file = os.path.join(tmp.name, "token")
        Path(token_file).write_text("s.fixture-token\n")
        vault = FakeVault(secrets={})
        self.addCleanup(vault.close)
        vault.mode = "status:403"
        chain = secrets.Chain(secrets.EnvBackend(), secrets.VaultBackend(addr=vault.url, token_file=token_file, environ={},
                                                                         wall=lambda: T0 + 120))
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("RESEARCH_GATEWAY_SECRET_")}, clear=True):
            rec = Recorder(self, secrets_backend=chain)
            status, body = rec.send("POST", "/v1/data", {"source": "fred", "params": {"series": "GDP"}})
        self.assertEqual(lanes_of(body), [("fred", "provider_unavailable", "unobserved", None, None, "secrets_backend_failing", None, None, None)])
        self.assertEqual(body["capability_facts"], [{"capability": "secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z",
                                                     "last_success_at": None, "detail": "403", "affected_lanes": ["fred"], "revision": 1}],
                         "the dated fact the engine records before the observation that names it (DEPLOYMENT-CONTRACT §3.4 fixture 5)")
        self.check("data_secrets_failing", rec, "vault answers 403: the lane is secrets_backend_failing with the dated fact")

    def test_data_secrets_outage_widens(self):
        """2b-repair-2 R2: ONE Vault outage answered three times, in order — FRED fails; GovInfo
        joins the same outage; Vault then fails another way. Every answer's fact keeps the
        episode's onset (the first failed read) and says what was true as it answered: the lanes
        failing so far and the latest failure's detail (STATION-CONTRACT; SecretsHealth)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        token_file = os.path.join(tmp.name, "token")
        Path(token_file).write_text("s.fixture-token\n")
        vault = FakeVault(secrets={})
        self.addCleanup(vault.close)
        vault.mode = "status:403"
        wall, clock = [T0 + 120], [0.0]
        chain = secrets.Chain(secrets.EnvBackend(), secrets.VaultBackend(addr=vault.url, token_file=token_file, environ={},
                                                                         wall=lambda: wall[0], clock=lambda: clock[0]))
        with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("RESEARCH_GATEWAY_SECRET_")}, clear=True):
            rec = Recorder(self, secrets_backend=chain)
            first = rec.send("POST", "/v1/data", {"source": "fred", "params": {"series": "GDP"}})[1]
            wall[0] += 60
            second = rec.send("POST", "/v1/find", {"query": "appropriations", "kind": "dataset", "lanes": ["govinfo"]})[1]
            wall[0] += 60
            clock[0] += secrets.VaultBackend.failure_ttl + 1   # FRED's failed read is no longer replayed: Vault is asked again
            vault.mode = "status:503"
            third = rec.send("POST", "/v1/data", {"source": "fred", "params": {"series": "UNRATE"}})[1]
        failing = ("provider_unavailable", "unobserved", None, None, "secrets_backend_failing", None, None, None)
        self.assertEqual([lanes_of(b) for b in (first, second, third)], [[("fred", *failing)], [("govinfo", *failing)], [("fred", *failing)]])
        episode = {"capability": "secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z", "last_success_at": None}
        self.assertEqual([b["capability_facts"] for b in (first, second, third)],
                         [[{**episode, "detail": "403", "affected_lanes": ["fred"], "revision": 1}],
                          [{**episode, "detail": "403", "affected_lanes": ["fred", "govinfo"], "revision": 2}],
                          [{**episode, "detail": "503", "affected_lanes": ["fred", "govinfo"], "revision": 3}]],
                         "one episode, its onset kept; its lanes and detail as of each answer, each change the next revision")
        self.check("data_secrets_outage_widens", rec, "one vault outage: FRED fails, GovInfo joins it, then vault answers 503 — "
                                                      "one onset, three snapshots")

    def outage(self):
        """A recorder over a loopback Vault answering 403, with its wall and cache clocks."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        token_file = os.path.join(tmp.name, "token")
        Path(token_file).write_text("s.fixture-token\n")
        vault = FakeVault(secrets={})
        self.addCleanup(vault.close)
        vault.mode = "status:403"
        wall, clock = [T0 + 120], [0.0]
        chain = secrets.Chain(secrets.EnvBackend(), secrets.VaultBackend(addr=vault.url, token_file=token_file, environ={},
                                                                         wall=lambda: wall[0], clock=lambda: clock[0]))
        env = mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if not k.startswith("RESEARCH_GATEWAY_SECRET_")}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        return Recorder(self, secrets_backend=chain), vault, wall, clock

    def test_data_secrets_outage_two_invocations(self):
        """2b-repair-3 R2 (Astra's reproduction 1): one Vault outage answered to two invocations
        — A's FRED read fails first; then B's GovInfo read widens the outage; then B asks GovInfo
        again after the failed read's cache ran out, and Vault answers the same. The first two
        are the outage's first two revisions; the fresh read changed nothing, so it is the same
        snapshot again (SecretsHealth: a revision is a change of the fact)."""
        rec, vault, wall, clock = self.outage()
        first = rec.send("POST", "/v1/data", {"source": "fred", "params": {"series": "GDP"}})[1]
        wall[0] += 60
        second = rec.send("POST", "/v1/find", {"query": "appropriations", "kind": "dataset", "lanes": ["govinfo"]}, invocation=INV_B)[1]
        wall[0] += 60
        clock[0] += secrets.VaultBackend.failure_ttl + 1   # GovInfo's failed read is no longer replayed: Vault is asked again
        third = rec.send("POST", "/v1/find", {"query": "budget", "kind": "dataset", "lanes": ["govinfo"]}, invocation=INV_B)[1]
        self.assertEqual([observed(b)[:2] for b in (first, second, third)], [(INV, ATT), (INV_B, ATT), (INV_B, ATT)])
        episode = {"capability": "secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z", "last_success_at": None, "detail": "403"}
        self.assertEqual([b["capability_facts"] for b in (first, second, third)],
                         [[{**episode, "affected_lanes": ["fred"], "revision": 1}],
                          [{**episode, "affected_lanes": ["fred", "govinfo"], "revision": 2}],
                          [{**episode, "affected_lanes": ["fred", "govinfo"], "revision": 2}]],
                         "the narrow snapshot, the wider one, and the wider one again: a fresh read that changed nothing")
        self.check("data_secrets_outage_two_invocations", rec, "one vault outage answered to two invocations: A's FRED read, then B's "
                                                               "GovInfo read widening it, then B's fresh GovInfo read changing nothing")

    def test_data_secrets_outage_recurs(self):
        """2b-repair-3 R2 (Astra's reproduction 2): ONE invocation, each answer before the next —
        FRED fails 403; GovInfo joins; a fresh FRED read fails 503; a fresh GovInfo read fails
        403 again. The fourth answer says what the second said, and is the outage's fourth
        revision: a later snapshot, never the second one replayed."""
        rec, vault, wall, clock = self.outage()
        answers = [rec.send("POST", "/v1/data", {"source": "fred", "params": {"series": "GDP"}})[1]]
        wall[0] += 60
        answers.append(rec.send("POST", "/v1/find", {"query": "appropriations", "kind": "dataset", "lanes": ["govinfo"]})[1])
        wall[0] += 60
        clock[0] += secrets.VaultBackend.failure_ttl + 1
        vault.mode = "status:503"
        answers.append(rec.send("POST", "/v1/data", {"source": "fred", "params": {"series": "UNRATE"}})[1])
        wall[0] += 60
        clock[0] += secrets.VaultBackend.failure_ttl + 1
        vault.mode = "status:403"
        answers.append(rec.send("POST", "/v1/find", {"query": "budget after 503", "kind": "dataset", "lanes": ["govinfo"]})[1])
        failing = ("provider_unavailable", "unobserved", None, None, "secrets_backend_failing", None, None, None)
        self.assertEqual([lanes_of(b) for b in answers], [[("fred", *failing)], [("govinfo", *failing)], [("fred", *failing)], [("govinfo", *failing)]])
        episode = {"capability": "secrets.vault", "state": "failing", "since": "2026-09-21T19:47:00Z", "last_success_at": None}
        self.assertEqual([b["capability_facts"] for b in answers],
                         [[{**episode, "detail": "403", "affected_lanes": ["fred"], "revision": 1}],
                          [{**episode, "detail": "403", "affected_lanes": ["fred", "govinfo"], "revision": 2}],
                          [{**episode, "detail": "503", "affected_lanes": ["fred", "govinfo"], "revision": 3}],
                          [{**episode, "detail": "403", "affected_lanes": ["fred", "govinfo"], "revision": 4}]],
                         "the fourth says what the second said, as the next revision")
        self.check("data_secrets_outage_recurs", rec, "one vault outage, one invocation: FRED 403, GovInfo joins, FRED 503, then "
                                                      "GovInfo 403 again — the second snapshot's contents as the fourth revision")

    def test_grant_and_policy_refusal(self):
        rec = Recorder(self)
        status, grant = rec.send("POST", "/v1/grants", {"topic_id": "topic-fixture", "commercial": True, "accept_per_item": False,
                                                        "invocation_id": INV, "ttl_seconds": 3600}, correlated=False)
        self.assertEqual((status, grant["client_id"], grant["invocation_id"], grant["policy"]),
                         (201, "engine@topic-fixture", INV, {"topic_id": "topic-fixture", "commercial": True, "accept_per_item": False}))
        status, refused = rec.send("POST", "/v1/resolve", {"identity": "doi:10.1234/abc", "commercial": False}, token=grant["token"])
        self.assertEqual((status, refused), (403, {"error": "policy-bound: commercial is set by the topic, not the caller"}))
        rec.exchanges[-1]["request"]["authorization"] = "grant"
        self.check("grant_and_policy_refusal", rec, "a grant is minted; a request under it asking to loosen its posture is refused")


if __name__ == "__main__":
    unittest.main()
