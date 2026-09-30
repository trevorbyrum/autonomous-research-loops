"""Task 2b, acceptance items 1 and 2: invocation/attempt identity and complete request identity.

Item 1 — the caller's invocation and attempt travel through both front doors (/v1 and the
MCP endpoint, batch entries included), onto queued jobs (the CREATOR's, immutable), onto
every lane call row, and back in each caller's own `observation`; a coalesced or
cache-served caller gets its own observation and its own durable row, while the shared
content keeps the dispatcher's identity. Item 2 — the request identity covers the complete
effective request (defaults, kind, filters, cursor/page), every call row carries it, and
each answer acknowledges whether the caller's request row was durably written, or says
why not. Each negative has its paired accepted-path control. DB cases need
RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database: they write rows).
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid
from unittest import mock

from research_gateway import app
from research_gateway.adapters.base import FakeTransport
from research_gateway.api import http as api
from research_gateway.clients import mcp_stdio
from research_gateway.clients.http_client import GatewayClient
from research_gateway.core import calllog, db
from research_gateway.core.request_identity import effective_request, request_identity
from research_gateway.registry.load import read_seed
from tests.test_adapters_articles import CROSSREF_WORK

TOKENS = {"engine": "tok-engine-secret"}
HAVE_DB = db.configured() and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1"
SEED = [dict(s, enabled=False) if s["id"] == "openalex_snapshot" else s for s in read_seed()]   # no DB-only lane


class NoSecrets:
    def get(self, name, field=None):
        return None


def transport():
    t = FakeTransport()
    t.add("GET", "https://doi.org/ra/", body=[{"DOI": "10.1234/abc", "RA": "Crossref"}])
    t.add("GET", "https://api.crossref.org/works/10.1234/abc", body={"message": CROSSREF_WORK})
    t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
    t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
    return t


def gateway(use_db=False, t=None):
    return app.Gateway(app.Settings(tokens=TOKENS, workers=1, sync_timeout=20), use_db=use_db, sources=SEED,
                       transport=t or transport(), secrets=NoSecrets())


def post(url, path, body, headers=None):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {TOKENS['engine']}",
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


INV = {"X-Research-Invocation": "inv_research01", "X-Research-Attempt": "2"}


class RequestIdentity(unittest.TestCase):
    def rid(self, **payload):
        return request_identity({"request_type": "find", "query": "q", **payload})

    def test_the_design_reviews_probe_kind_and_cursor_no_longer_collide(self):
        # DR §9: "two searches differing in kind and cursor produced the same _subject_of key
        # when neither included source"
        a = {"query": "q", "kind": "article", "cursors": {"crossref": "c1"}}
        b = {"query": "q", "kind": "dataset", "cursors": {"crossref": "c2"}}
        self.assertNotEqual(mcp_stdio._subject_of(a, "find"), mcp_stdio._subject_of(b, "find"))
        self.assertNotEqual(request_identity({**a, "request_type": "find"}), request_identity({**b, "request_type": "find"}))
        for field, x, y in (("kind", "article", "dataset"), ("cursors", {"crossref": "c1"}, {"crossref": "c2"}),
                            ("limit", 5, 50), ("year_from", 2001, 2002), ("published_after", "2026-01-01", "2026-02-01"),
                            ("domain", "finance", "biomed"), ("commercial", False, True), ("accept_per_item", False, True),
                            ("lanes", ["crossref"], ["doaj"])):
            with self.subTest(field):
                self.assertNotEqual(self.rid(**{field: x}), self.rid(**{field: y}))
                self.assertNotEqual(mcp_stdio._subject_of({"query": "q", field: x}, "find"),
                                    mcp_stdio._subject_of({"query": "q", field: y}, "find"))

    def test_control_spellings_of_one_request_share_its_identity(self):
        self.assertEqual(self.rid(), self.rid(limit=20), "the executor's default page size")
        self.assertEqual(self.rid(), self.rid(domain="not-a-domain"), "an unknown domain resolves to other")
        self.assertEqual(self.rid(lanes=["doaj", "crossref"]), self.rid(lanes=["crossref", "doaj"]))
        self.assertEqual(self.rid(), self.rid(priority="harvest", timeout=5, topic_id="t-1"),
                         "scheduling and the topic binding are not what is asked")
        self.assertEqual(mcp_stdio._subject_of({"query": "q"}, "find"), "q", "a bare request keeps its readable key")

    def test_other_request_types_cover_their_parameters(self):
        pairs = ((("enrich", {"identity": "doi:10.1/x", "what": "citations"}), ("enrich", {"identity": "doi:10.1/x", "what": "references"})),
                 (("data", {"source": "fred", "params": {"series": "GDP"}}), ("data", {"source": "fred", "params": {"series": "UNRATE"}})),
                 (("catalog", {"source": "ecb", "within": "EXR"}), ("catalog", {"source": "ecb", "within": "ICP"})),
                 (("catalog", {"source": "fred", "query": "gdp", "cursor": "20"}), ("catalog", {"source": "fred", "query": "gdp"})),
                 (("fetch", {"target": "hf:a/b", "params": {"path": "x"}}), ("fetch", {"target": "hf:a/b", "params": {"path": "y"}})),
                 (("resolve", {"identity": "doi:10.1/x"}), ("resolve", {"identity": "doi:10.1/y"})))
        for (rt1, p1), (rt2, p2) in pairs:
            with self.subTest(p1=p1, p2=p2):
                self.assertNotEqual(request_identity({**p1, "request_type": rt1}), request_identity({**p2, "request_type": rt2}))

    def test_every_answer_names_its_effective_request_and_identity(self):
        gw = gateway()
        out = gw.handle({"request_type": "find", "query": "q", "kind": "article", "limit": 20}, "engine")
        self.assertEqual(out["effective_request"], effective_request({"request_type": "find", "query": "q", "kind": "article"}))
        self.assertEqual(out["request_identity"], request_identity({"request_type": "find", "query": "q", "kind": "article"}))
        self.assertEqual(out["observation"]["request_identity"], out["request_identity"])


class BothDoorsCarryTheInvocation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw = gateway()
        cls.server = api.serve(cls.gw, "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.gw.stop()

    def test_the_v1_door_echoes_the_callers_invocation_and_attempt(self):
        status, body = post(self.url, "/v1/find", {"query": "q", "kind": "article"}, INV)
        self.assertEqual(status, 200, body)
        obs = body["observation"]
        self.assertEqual((obs["invocation_id"], obs["attempt"], obs["served"]), ("inv_research01", 2, "dispatched"))
        self.assertEqual((obs["captured"], obs["capture_loss"]), (False, "no durable call log: this gateway runs without a database"),
                         "without a database the loss of the durable row is explicit, never an implied capture")

    def test_malformed_or_half_given_correlation_is_refused(self):
        for headers in ({"X-Research-Invocation": "inv_x"}, {"X-Research-Attempt": "1"},
                        {"X-Research-Invocation": "inv x", "X-Research-Attempt": "1"},
                        {"X-Research-Invocation": "inv_x", "X-Research-Attempt": "0"},
                        {"X-Research-Invocation": "inv_x", "X-Research-Attempt": "one"}):
            with self.subTest(headers):
                for path in ("/v1/find", "/mcp"):
                    status, body = post(self.url, path, {"query": "q"} if path == "/v1/find"
                                        else {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, headers)
                    self.assertEqual(status, 400, (path, body))

    def test_control_no_correlation_is_an_unattributed_request(self):
        status, body = post(self.url, "/v1/find", {"query": "q"})
        self.assertEqual((status, body["observation"]["invocation_id"], body["observation"]["attempt"]), (200, None, None))

    def test_the_mcp_door_carries_it_into_every_tool_call_and_batch_entry(self):
        call = {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                "params": {"name": "research_find", "arguments": {"query": "q", "kind": "article"}}}
        status, body = post(self.url, "/mcp", call, INV)
        result = json.loads(body["result"]["content"][0]["text"])
        self.assertEqual((result["observation"]["invocation_id"], result["observation"]["attempt"]), ("inv_research01", 2))
        seen = []
        real = self.gw.handle

        def spy(payload, client_id, **kw):
            seen.append(dict(kw.get("trace") or {}))
            return real(payload, client_id, **kw)
        batch = {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "research_batch", "arguments": {"calls": [
            {"tool": "research_resolve", "arguments": {"identity": "doi:10.1234/abc"}},
            {"tool": "research_resolve", "arguments": {"identity": "doi:10.1234/abc"}}]}}}
        with mock.patch.object(self.gw, "handle", spy):
            post(self.url, "/mcp", batch, INV)
        self.assertEqual([(t.get("invocation_id"), t.get("attempt"), t.get("batch_entry")) for t in seen],
                         [("inv_research01", 2, 0), ("inv_research01", 2, 1)])


class StdioClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        mcp_stdio._LOST.update(lines=0, why=None)
        mcp_stdio._ATTEMPTS.clear()

    def lines(self, path):
        with open(path) as fh:
            return [json.loads(x) for x in fh.read().splitlines() if x.strip()]

    def test_a_failed_activity_write_is_acknowledged_and_announced_later(self):
        missing_dir = os.path.join(self.tmp.name, "gone", "activity.jsonl")
        answer = {"lanes": [{"source": "crossref", "coverage": "searched_ok"}], "records": []}
        ack = mcp_stdio.record_activity(missing_dir, "research_find", {"query": "q"}, answer)
        self.assertEqual(ack["captured"], False)
        self.assertIn("activity file not written", ack["loss"])
        path = os.path.join(self.tmp.name, "activity.jsonl")
        self.assertEqual(mcp_stdio.record_activity(path, "research_find", {"query": "q"}, answer), {"captured": True})
        first = self.lines(path)[0]
        self.assertEqual((first["coverage"], first["request_type"]), ("unknown", "telemetry"))
        self.assertIn("telemetry_missing: 2 earlier observation line(s)", first["detail"])
        mcp_stdio.record_activity(path, "research_find", {"query": "q"}, answer)
        self.assertEqual(sum(1 for ln in self.lines(path) if ln["request_type"] == "telemetry"), 1, "announced once")

    def test_the_tool_result_carries_the_loss(self):
        class Stub:
            def request(self, rt, payload):
                return {"lanes": [], "records": []}
        out = mcp_stdio.call_tool(Stub(), "research_find", {"query": "q"}, activity=os.path.join(self.tmp.name, "no", "x.jsonl"))
        self.assertFalse(out["activity_capture"]["captured"])
        out = mcp_stdio.call_tool(Stub(), "research_find", {"query": "q"}, activity=os.path.join(self.tmp.name, "x.jsonl"))
        self.assertNotIn("activity_capture", out, "control: a written observation adds nothing")

    def test_the_gateway_line_is_the_transport_and_a_pending_answer_clears_nothing(self):
        path = os.path.join(self.tmp.name, "activity.jsonl")
        mcp_stdio.record_activity(path, "research_find", {"query": "q"}, {"status": "queued", "job_id": 5})
        self.assertFalse(os.path.exists(path) and self.lines(path), "nothing observed yet, nothing cleared")
        mcp_stdio.record_activity(path, "research_find", {"query": "q"}, {"lanes": [{"source": "crossref", "coverage": "provider_unavailable"}]})
        gateway_line = next(ln for ln in self.lines(path) if ln["source"] == "gateway")
        self.assertEqual((gateway_line["scope"], gateway_line["coverage"]), ("gateway", "searched_ok"))
        self.assertEqual({ln["request_identity"] for ln in self.lines(path)},
                         {request_identity({"request_type": "find", "query": "q"})})

    def test_attempts_number_repeats_of_one_request(self):
        seen = []

        class Client(GatewayClient):
            def _call(self, method, path, body=None):
                seen.append(self.attempt)
                return {"lanes": [], "records": []}
        client = Client("http://gateway.invalid", "t", invocation_id="inv_research01")
        for args in ({"query": "q"}, {"query": "q"}, {"query": "other"}, {"query": "q", "limit": 20}):
            mcp_stdio.call_tool(client, "research_find", args)
        self.assertEqual(seen, [1, 2, 1, 3], "a repeat of the same effective request is the next attempt")


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class DurableCorrelation(unittest.TestCase):
    def setUp(self):
        self.tag = f"corr-{uuid.uuid4().hex[:8]}"
        self.gw = gateway(use_db=True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.gw.stop()
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.calls WHERE query LIKE %s OR job_id IN (SELECT id FROM gateway.jobs WHERE payload::text LIKE %s)",
                        (f"%{self.tag}%", f"%{self.tag}%"))
            cur.execute("DELETE FROM gateway.jobs WHERE payload::text LIKE %s", (f"%{self.tag}%",))
            conn.commit()

    def rows(self, sql, *args):
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, args)
            return cur.fetchall()

    def test_a_queued_job_and_its_lane_calls_carry_the_creators_invocation(self):
        self.gw.start()
        payload = {"request_type": "find", "query": f"q {self.tag}", "kind": "article"}
        out = self.gw.handle(payload, "engine", trace={"invocation_id": "inv_creator01", "attempt": 1})
        self.assertEqual((out["status"], out["observation"]["served"], out["observation"]["captured"]), ("done", "dispatched", True))
        rid = request_identity(payload)
        (job,) = self.rows("SELECT invocation_id, attempt, request_identity FROM gateway.jobs WHERE id = %s", out["job_id"])
        self.assertEqual(job, ("inv_creator01", 1, rid))
        lanes = self.rows("SELECT source_id, invocation_id, attempt, request_identity FROM gateway.calls WHERE job_id = %s", out["job_id"])
        self.assertTrue(lanes and all(r[1:] == ("inv_creator01", 1, rid) for r in lanes), lanes)
        (span,) = self.rows("SELECT source_id, invocation_id, attempt, request_identity FROM gateway.calls WHERE id = %s",
                            out["observation"]["call_ref"])
        self.assertEqual(span, ("request", "inv_creator01", 1, rid), "the acknowledged row is the caller's own")

    def test_a_coalesced_caller_keeps_its_own_invocation(self):
        payload = {"request_type": "find", "query": f"shared {self.tag}", "kind": "article"}
        answers = {}

        def ask(name, inv):
            answers[name] = self.gw.handle(dict(payload), "engine", timeout=20, trace={"invocation_id": inv, "attempt": 1})
        first = threading.Thread(target=ask, args=("first", "inv_first001"))
        first.start()
        deadline = time.monotonic() + 10
        while not self.rows("SELECT 1 FROM gateway.jobs WHERE payload::text LIKE %s", f"%{self.tag}%") and time.monotonic() < deadline:
            time.sleep(0.05)
        second = threading.Thread(target=ask, args=("second", "inv_second01"))
        second.start()
        deadline = time.monotonic() + 10   # the waiter's coalesce row exists: it has joined the in-flight job
        while not self.rows("SELECT 1 FROM gateway.calls WHERE source_id = 'coalesce' AND query LIKE %s", f"%{self.tag}%") \
                and time.monotonic() < deadline:
            time.sleep(0.05)
        self.gw.start()   # only now does a worker run the job both callers wait on
        first.join(30)
        second.join(30)
        a, b = answers["first"]["observation"], answers["second"]["observation"]
        self.assertEqual((a["invocation_id"], a["served"]), ("inv_first001", "dispatched"))
        self.assertEqual((b["invocation_id"], b["served"], b["dispatched_by"]),
                         ("inv_second01", "coalesced", {"invocation_id": "inv_first001", "attempt": 1}))
        self.assertEqual(answers["first"]["job_id"], answers["second"]["job_id"])
        (job,) = self.rows("SELECT invocation_id FROM gateway.jobs WHERE id = %s", answers["first"]["job_id"])
        self.assertEqual(job, ("inv_first001",), "the job is the creator's; the waiter never rewrote it")
        waiter = self.rows("SELECT source_id, invocation_id FROM gateway.calls WHERE job_id = %s AND source_id = 'coalesce'",
                           answers["second"]["job_id"])
        self.assertEqual(waiter, [("coalesce", "inv_second01")])
        self.assertTrue(b["captured"])

    def test_a_cache_served_caller_is_observed_as_itself(self):
        self.gw.start()
        # finance plans only the routed lanes, so the first answer is complete (a degraded one is never cached)
        payload = {"request_type": "find", "query": f"cached {self.tag}", "kind": "article", "domain": "finance"}
        first = self.gw.handle(dict(payload), "engine", trace={"invocation_id": "inv_first001", "attempt": 1})
        second = self.gw.handle(dict(payload), "engine", trace={"invocation_id": "inv_second01", "attempt": 3})
        self.assertEqual((first["observation"]["served"], second["observation"]["served"]), ("dispatched", "cache"))
        self.assertEqual((second["observation"]["invocation_id"], second["observation"]["attempt"]), ("inv_second01", 3))
        hit = self.rows("SELECT invocation_id, attempt, cache_hit FROM gateway.calls WHERE job_id = %s AND source_id = 'cache'",
                        second["job_id"])
        self.assertEqual(hit, [("inv_second01", 3, True)], "the warm-cache read is the second caller's own row")
        cached = [answer for _, answer in self.gw.cache._searches.values()]
        self.assertTrue(cached)
        self.assertFalse(any("observation" in answer for answer in cached), "cached content carries no caller's observation")

    def test_correlation_is_immutable_once_written(self):
        self.gw.start()
        payload = {"request_type": "find", "query": f"imm {self.tag}", "kind": "article"}
        out = self.gw.handle(payload, "engine", trace={"invocation_id": "inv_creator01", "attempt": 1})
        import psycopg
        for sql in ("UPDATE gateway.jobs SET invocation_id = 'inv_other001' WHERE id = %s",
                    "UPDATE gateway.jobs SET attempt = 2 WHERE id = %s",
                    "UPDATE gateway.jobs SET request_identity = 'sha256:x' WHERE id = %s",
                    "UPDATE gateway.calls SET invocation_id = 'inv_other001' WHERE job_id = %s",
                    "UPDATE gateway.calls SET attempt = 9 WHERE job_id = %s"):
            with self.subTest(sql):
                with db.connect() as conn, conn.cursor() as cur:
                    with self.assertRaises(psycopg.errors.RaiseException):
                        cur.execute(sql, (out["job_id"],))
        with db.connect() as conn, conn.cursor() as cur:   # control: the rows' other fields still move
            cur.execute("UPDATE gateway.jobs SET error_class = 'probe' WHERE id = %s", (out["job_id"],))
            cur.execute("UPDATE gateway.calls SET latency_ms = latency_ms WHERE job_id = %s", (out["job_id"],))
            conn.commit()

    def test_a_lost_request_row_is_reported_not_implied(self):
        self.gw.start()
        real = calllog.record

        def failing(conn, rec):
            if rec.source_id == "request":
                raise calllog.AuditError("call log write failed: probe")
            return real(conn, rec)
        payload = {"request_type": "find", "query": f"lost {self.tag}", "kind": "article"}
        with mock.patch.object(calllog, "record", failing):
            out = self.gw.handle(payload, "engine", trace={"invocation_id": "inv_lost0001", "attempt": 1})
        self.assertEqual((out["status"], out["observation"]["captured"], out["observation"]["call_ref"]), ("done", False, None))
        self.assertIn("request row not written: AuditError", out["observation"]["capture_loss"])
        self.assertTrue(out["records"], "the research result itself is still delivered")


if __name__ == "__main__":
    unittest.main()
