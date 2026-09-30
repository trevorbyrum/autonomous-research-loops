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
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import types
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

FIXTURES = Path(__file__).resolve().parents[2] / "gen2" / "tests" / "fixtures" / "gateway_answers"
RECORD = os.environ.get("GATEWAY_RECORD_FIXTURES") == "1"
TOKENS = {"engine": "tok-engine-secret"}
INV, ATT = "inv_fixture0001", 1
SEED = [dict(s, enabled=False) if s["id"] == "openalex_snapshot" else s for s in read_seed()]
STUB_ROW = {"id": "stub", "name": "Stub", "kind": "article", "enabled": True, "capabilities": ["find"], "base_for": ["article"],
            "domains": [], "use_commercial": "allow", "license": "CC0 (fixture)", "freshness_lag": "none",
            "rate": {"per_second": 100, "verified": True}}
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

    def send(self, method, path, body=None, *, token=TOKENS["engine"], correlated=True):
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        if correlated:
            headers.update({"X-Research-Invocation": INV, "X-Research-Attempt": str(ATT)})
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
                                           "correlation": {"invocation_id": INV, "attempt": ATT} if correlated else None},
                               "response": {"status": status, "content_type": rh.get("Content-Type"),
                                            "x_research_gateway": rh.get("X-Research-Gateway"), "body": doc}})
        return status, json.loads(raw)


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
        rec.send("POST", "/v1/find", {"query": "reranking", "kind": "article", "domain": "finance"})
        self.check("find_complete", rec, "two lanes, both complete: crossref one record, doaj none")

    def test_find_not_captured(self):
        rec = Recorder(self, durable=False)
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        rec.send("POST", "/v1/find", {"query": "reranking", "kind": "article", "domain": "finance"})
        self.check("find_not_captured", rec, "a gateway without a database: the durable request row is an explicit loss")

    def test_find_unreadable_lane(self):
        rec = Recorder(self)
        rec.t.add("GET", "https://api.crossref.org/works?", body=b'{"message": {"items": [{"DOI": "10.1234/ab')
        rec.send("POST", "/v1/find", {"query": "reranking", "kind": "article", "domain": "finance"})
        self.check("find_unreadable_lane", rec, "crossref answers truncated JSON: unavailable, payload_invalid, no count")

    def test_find_partial_records(self):
        rec = Recorder(self, extra_sources=[STUB_ROW])
        good = [{"identity": f"doi:10.1234/p{i}", "kind": "article", "source_id": "stub", "title": f"P{i}"} for i in (1, 2)]
        rec.gw.router.adapters["stub"] = types.SimpleNamespace(
            SOURCE_ID="stub", CAPABILITIES=("find",), find=lambda client, query, *, limit=20: {"records": good + [{"identity": None}]})
        rec.send("POST", "/v1/find", {"query": "q", "kind": "article", "lanes": ["stub"]})
        self.check("find_partial_records", rec, "one of three records unreadable: searched_ok, partial, a lower bound of 2")

    def test_find_paged_then_failed(self):
        rec = Recorder(self)
        rec.t.by_substring.append(("cursor=c2", Response(503, {}, b"", "")))
        rec.t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 3,
                                                                              "next-cursor": "c2"}})
        request = {"query": "reranking", "kind": "article", "domain": "finance"}
        rec.send("POST", "/v1/find", request)
        rec.send("POST", "/v1/find", {**request, "cursors": {"crossref": "c2"}, "lanes": ["crossref"]})
        self.check("find_paged_then_failed", rec, "page 1 reads one record and a cursor; page 2 fails with HTTP 503")

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
            rec.send("POST", "/v1/data", {"source": "fred", "params": {"series": "GDP"}})
        self.check("data_secrets_failing", rec, "vault answers 403: the lane is secrets_backend_failing with the dated fact")

    def test_grant_and_policy_refusal(self):
        rec = Recorder(self)
        status, grant = rec.send("POST", "/v1/grants", {"topic_id": "topic-fixture", "commercial": True, "accept_per_item": False,
                                                        "invocation_id": INV, "ttl_seconds": 3600}, correlated=False)
        rec.send("POST", "/v1/resolve", {"identity": "doi:10.1234/abc", "commercial": False}, token=grant["token"])
        rec.exchanges[-1]["request"]["authorization"] = "grant"
        self.check("grant_and_policy_refusal", rec, "a grant is minted; a request under it asking to loosen its posture is refused")


if __name__ == "__main__":
    unittest.main()
