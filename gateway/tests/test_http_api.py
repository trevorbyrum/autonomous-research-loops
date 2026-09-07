"""Phase 5 acceptance: HTTP front door, bearer auth, inline and queued modes, the MCP endpoint,
the stdio client, and the CLI payload mapping. Servers bind to an ephemeral localhost port."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from research_gateway import app
from research_gateway.adapters.base import FakeTransport
from research_gateway.api import http as api
from research_gateway.clients import cli, http_client, mcp_stdio
from research_gateway.core import db
from research_gateway.mcp import homelab_adapter
from research_gateway.registry.load import read_seed
from tests.test_adapters_articles import CROSSREF_WORK

TOKENS = {"loops": "tok-loops-secret", "mcp": "tok-mcp-secret"}


class NoSecrets:
    def get(self, name, field=None):
        return None


def transport():
    t = FakeTransport()
    t.add("GET", "https://doi.org/ra/", body=[{"DOI": "10.1234/abc", "RA": "Crossref"}])
    t.add("GET", "https://api.crossref.org/works/10.1234/abc", body={"message": CROSSREF_WORK})
    t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
    t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
    t.add("GET", "https://globeproject.com/data/x.xls", body=b"\xd0\xcf\x11", headers={"Content-Type": "application/vnd.ms-excel"})
    return t


def start(use_db=False, sources=None):
    gw = app.Gateway(app.Settings(tokens=TOKENS, workers=1, sync_timeout=20), use_db=use_db, sources=sources,
                     transport=transport(), secrets=NoSecrets())
    gw.start()
    server = api.serve(gw, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return gw, server, f"http://127.0.0.1:{server.server_port}"


def stop(gw, server):
    server.shutdown()
    server.server_close()
    gw.stop()


def http(url, method="GET", body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, ctype, status = r.read(), r.headers.get("Content-Type"), r.status
    except urllib.error.HTTPError as e:
        raw, ctype, status = e.read(), e.headers.get("Content-Type"), e.code
    return status, (json.loads(raw) if "json" in (ctype or "") and raw else raw), ctype


class InlineGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw, cls.server, cls.url = start(use_db=False)

    @classmethod
    def tearDownClass(cls):
        stop(cls.gw, cls.server)

    def test_health_is_open_and_green(self):
        status, body, _ = http(f"{self.url}/v1/health")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"ok": True, "version": app.VERSION, "mode": "inline"}, "no internals without a token")
        status, body, _ = http(f"{self.url}/v1/status", token=TOKENS["loops"])
        self.assertEqual(body["health"]["workers"], {"alive": 0, "expected": 0})

    def test_bad_token_is_refused(self):
        for token in (None, "wrong", TOKENS["loops"] + "x"):
            status, body, _ = http(f"{self.url}/v1/find", "POST", {"query": "q"}, token)
            self.assertEqual(status, 401, token)
            self.assertIn("token", body["error"])
        status, _, _ = http(f"{self.url}/v1/status", token="wrong")
        self.assertEqual(status, 401)

    def test_find_resolve_and_status(self):
        status, body, _ = http(f"{self.url}/v1/find", "POST", {"query": "reranking", "kind": "article", "domain": "finance"}, TOKENS["loops"])
        self.assertEqual(status, 200)
        self.assertEqual(body["records"][0]["identity"], "doi:10.1234/abc")
        self.assertEqual(body["domain_resolved"], "finance")
        status, body, _ = http(f"{self.url}/v1/resolve", "POST", {"identity": "doi:10.1234/abc"}, TOKENS["loops"])
        self.assertEqual(body["records"][0]["source_id"], "crossref")
        status, body, _ = http(f"{self.url}/v1/status", token=TOKENS["mcp"])
        self.assertEqual(status, 200)
        self.assertIn("crossref", body["broker"])
        self.assertTrue(body["health"]["ok"])

    def test_fetch_download_streams_bytes(self):
        seed = [dict(s, enabled=True, rate={**s["rate"], "verified": True}) if s["id"] == "globe" else s for s in read_seed()]
        gw, server, url = start(use_db=False, sources=seed)
        try:
            status, body, ctype = http(f"{url}/v1/fetch", "POST", {"target": "https://globeproject.com/data/x.xls", "params": {"download": True}}, TOKENS["loops"])
            self.assertEqual(status, 200)
            self.assertEqual(body, b"\xd0\xcf\x11")
            self.assertEqual(ctype, "application/vnd.ms-excel")
        finally:
            stop(gw, server)

    def test_bad_requests(self):
        status, body, _ = http(f"{self.url}/v1/delete", "POST", {}, TOKENS["loops"])
        self.assertEqual(status, 404)
        status, body, _ = http(f"{self.url}/v1/jobs/1", token=TOKENS["loops"])
        self.assertEqual(status, 404, "inline mode has no queue")
        req = urllib.request.Request(f"{self.url}/v1/find", data=b"not json", method="POST",
                                     headers={"Authorization": f"Bearer {TOKENS['loops']}", "Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(cm.exception.code, 400)
        for bad in ({"query": "q", "params": [1]}, {"query": "q", "commercial": "yes"}, {"query": "q", "limit": "5"},
                    {"query": "q", "limit": 0}, {"query": "q", "limit": -3}, {"query": "q", "unknown": 1}, {"query": 5}):
            status, body, _ = http(f"{self.url}/v1/find", "POST", bad, TOKENS["loops"])
            self.assertEqual(status, 400, bad)
            self.assertIn("error", body)
        status, _, _ = http(f"{self.url}/v1/jobs/1/2", token=TOKENS["loops"])
        self.assertEqual(status, 404, "only /v1/jobs/<digits>")
        status, _, _ = http(f"{self.url}/v1/jobs/abc", token=TOKENS["loops"])
        self.assertEqual(status, 404)

    def test_malformed_content_length_is_a_400(self):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.putrequest("POST", "/v1/find")
        conn.putheader("Authorization", f"Bearer {TOKENS['loops']}")
        conn.putheader("Content-Length", "abc")
        conn.endheaders()
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_client_never_relays_non_json_error_bodies(self):
        client = http_client.GatewayClient(self.url, TOKENS["loops"])
        out = client._call("GET", "/definitely/not/a/route")
        self.assertEqual(out["capability_fact"], "gateway_error_404")
        self.assertEqual(out.get("error"), "no such route", "JSON error bodies are relayed")
        out = client._call("GET", "/v1/jobs/1/2")
        self.assertNotIn("<", json.dumps(out), "an HTML/binary error body is never relayed")

    def test_mcp_endpoint_lists_and_calls_tools(self):
        status, body, _ = http(f"{self.url}/mcp", "POST", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, TOKENS["mcp"])
        self.assertEqual(status, 200)
        self.assertEqual([t["name"] for t in body["result"]["tools"]],
                         ["research_find", "research_resolve", "research_enrich", "research_fetch", "research_data", "research_status"])
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "research_resolve", "arguments": {"identity": "doi:10.1234/abc"}}}
        status, body, _ = http(f"{self.url}/mcp", "POST", call, TOKENS["mcp"])
        result = json.loads(body["result"]["content"][0]["text"])
        self.assertEqual(result["records"][0]["identity"], "doi:10.1234/abc")
        self.assertFalse(body["result"]["isError"])
        status, body, _ = http(f"{self.url}/mcp", "POST", {"jsonrpc": "2.0", "id": 3, "method": "resources/list"}, TOKENS["mcp"])
        self.assertEqual(body["error"]["code"], -32601)
        status, _, _ = http(f"{self.url}/mcp", "POST", {"jsonrpc": "2.0", "method": "notifications/initialized"}, TOKENS["mcp"])
        self.assertEqual(status, 202)
        status, _, _ = http(f"{self.url}/mcp", "POST", {"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
        self.assertEqual(status, 401)

    def test_stdio_client_against_the_server_and_when_it_is_gone(self):
        client = http_client.GatewayClient(self.url, TOKENS["loops"])
        out = mcp_stdio.handle({"method": "tools/call", "params": {"name": "research_find", "arguments": {"query": "reranking", "kind": "article"}}},
                               lambda n, a: mcp_stdio.call_tool(client, n, a))
        self.assertFalse(out["isError"])
        self.assertIn("doi:10.1234/abc", out["content"][0]["text"])
        dead = http_client.GatewayClient("http://127.0.0.1:9", TOKENS["loops"], timeout=2)
        out = mcp_stdio.handle({"method": "tools/call", "params": {"name": "research_find", "arguments": {"query": "q"}}},
                               lambda n, a: mcp_stdio.call_tool(dead, n, a))
        self.assertTrue(out["isError"])
        self.assertIn("gateway_unavailable", out["content"][0]["text"])
        self.assertEqual(mcp_stdio.handle({"method": "initialize", "params": {}}, None)["serverInfo"]["name"], "research-gateway")
        with self.assertRaises(LookupError):
            mcp_stdio.handle({"method": "prompts/list"}, None)


class Wiring(unittest.TestCase):
    def test_tokens_and_settings(self):
        self.assertEqual(app.parse_tokens("a=1, b=2,,bad"), {"a": "1", "b": "2"})
        s = app.load_settings(path=app.LOCAL_CONFIG.with_name("does-not-exist.toml"),
                              environ={"RESEARCH_GATEWAY_TOKENS": "loops=x", "RESEARCH_GATEWAY_LISTEN": "0.0.0.0:9000"})
        self.assertEqual((s.host, s.port, s.tokens), ("0.0.0.0", 9000, {"loops": "x"}))

    def test_peer_entry_has_no_secret(self):
        text = homelab_adapter.peer_entry("http://gateway.local:8765")
        entry = json.loads(text)["research"]
        self.assertEqual(entry["url"], "http://gateway.local:8765/mcp")
        self.assertEqual(entry["transport"], "http")
        self.assertEqual(entry["auth"], {"type": "bearer", "token": "${RESEARCH_GATEWAY_TOKEN}"})

    def test_cli_payloads(self):
        args = cli.build_parser().parse_args(["find", "management practices", "--kind", "article", "--domain", "management", "--commercial"])
        self.assertEqual(cli.payload_from(args), {"query": "management practices", "kind": "article", "limit": 20, "domain": "management", "commercial": True})
        args = cli.build_parser().parse_args(["data", "fred", "--params", '{"series": "GDP"}'])
        self.assertEqual(cli.payload_from(args), {"source": "fred", "params": {"series": "GDP"}})
        args = cli.build_parser().parse_args(["fetch", "doi:10.7910/DVN/OY6CBK", "--params", '{"download": true, "file_id": 9}', "--out", "x"])
        self.assertEqual(cli.payload_from(args)["params"], {"download": True, "file_id": 9})

    def test_inline_only_rule(self):
        self.assertTrue(app.Gateway.is_inline_only({"request_type": "enrich", "what": "full_text"}))
        self.assertTrue(app.Gateway.is_inline_only({"request_type": "fetch", "params": {"download": True}}))
        self.assertFalse(app.Gateway.is_inline_only({"request_type": "fetch", "params": {}}))


@unittest.skipUnless(db.configured(), "RESEARCH_GATEWAY_DSN not set")
class QueuedGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw, cls.server, cls.url = start(use_db=True, sources=read_seed())

    @classmethod
    def tearDownClass(cls):
        stop(cls.gw, cls.server)
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.calls WHERE job_id IN (SELECT id FROM gateway.jobs WHERE client_id IN ('loops', 'mcp') AND payload::text LIKE '%%test-http-api%%')")
            cur.execute("DELETE FROM gateway.jobs WHERE client_id IN ('loops', 'mcp') AND payload::text LIKE '%%test-http-api%%'")
            conn.commit()

    def test_sync_request_is_queued_worked_and_logged_with_job_id(self):
        status, body, _ = http(f"{self.url}/v1/find", "POST", {"query": "reranking test-http-api", "kind": "article", "domain": "finance"}, TOKENS["loops"])
        self.assertEqual(status, 200, body)
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["records"][0]["identity"], "doi:10.1234/abc")
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT source_id, domain_resolved, client_id FROM gateway.calls WHERE job_id = %s ORDER BY id", (body["job_id"],))
            rows = cur.fetchall()
        self.assertEqual({r[0] for r in rows}, {"openalex_snapshot", "crossref", "doaj"})
        self.assertTrue(all(r[1] == "finance" and r[2] == "loops" for r in rows), "every call carries the client id (I-6)")
        status, job, _ = http(f"{self.url}/v1/jobs/{body['job_id']}", token=TOKENS["loops"])
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["client_id"], "loops")
        status, _, _ = http(f"{self.url}/v1/jobs/{body['job_id']}", token=TOKENS["mcp"])
        self.assertEqual(status, 404, "another client cannot read this client's job")

    def test_inline_download_is_logged_with_the_client_id(self):
        seed = [dict(s, enabled=True, rate={**s["rate"], "verified": True}) if s["id"] == "globe" else s for s in read_seed()]
        gw, server, url = start(use_db=True, sources=seed)
        try:
            status, body, _ = http(f"{url}/v1/fetch", "POST", {"target": "https://globeproject.com/data/x.xls", "params": {"download": True}, "topic_id": "test-http-api"}, TOKENS["mcp"])
            self.assertEqual(status, 200)
            with db.connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT client_id, job_id FROM gateway.calls WHERE source_id = 'globe' ORDER BY id DESC LIMIT 1")
                row = cur.fetchone()
                cur.execute("DELETE FROM gateway.calls WHERE source_id = 'globe' AND client_id = 'mcp'")
                conn.commit()
            self.assertEqual(row, ("mcp", None), "inline requests are durably logged, attributed, and have no job")
        finally:
            stop(gw, server)

    def test_async_returns_job_id_then_result(self):
        status, body, _ = http(f"{self.url}/v1/resolve?async=1", "POST", {"identity": "doi:10.1234/abc", "topic_id": "test-http-api"}, TOKENS["mcp"])
        self.assertEqual(status, 202)
        job = self.gw.wait(body["job_id"], 20)
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["result"]["records"][0]["source_id"], "crossref")
        self.assertTrue(self.gw.health()["ok"])


if __name__ == "__main__":
    unittest.main()
