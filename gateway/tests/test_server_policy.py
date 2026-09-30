"""Task 2b, acceptance item 4: authenticated server-side station/topic policy on every door.

Gen-1 enforced a topic's policy only in the station's stdio client; an agent holding the
gateway token could call the HTTP API directly with its own posture (design review §9).
Here a station agent holds only a GRANT the grantor (the engine) minted for one invocation
of one topic, and every door binds it: /v1 sync and async, the MCP endpoint (tool calls,
batch entries, downloads, job polls) and GET /v1/jobs. Each bypass below is attempted the
way an agent would — straight at the server over HTTP, not through the stdio client — and
each has its paired accepted path. DB cases (job polling across topics and postures) need
RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1.
"""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

from research_gateway import app
from research_gateway.adapters.base import FakeTransport
from research_gateway.api import http as api
from research_gateway.core import db
from research_gateway.core.principals import GRANT_PREFIX, Grants, Principal, _b64, _unb64
from research_gateway.registry.load import read_seed
from tests.test_adapters_articles import CROSSREF_WORK

TOKENS = {"engine": "tok-engine-secret", "operator": "tok-operator-secret"}
HAVE_DB = db.configured() and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1"
SEED = [dict(s, enabled=False) if s["id"] == "openalex_snapshot" else s for s in read_seed()]


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


def serve(use_db=False):
    gw = app.Gateway(app.Settings(tokens=TOKENS, grantors={"engine"}, workers=1, sync_timeout=20), use_db=use_db,
                     sources=SEED, transport=transport(), secrets=NoSecrets())
    gw.start()
    server = api.serve(gw, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return gw, server, f"http://127.0.0.1:{server.server_port}"


def call(url, path, body=None, token=None, headers=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {}),
                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def mcp(url, token, name, arguments, headers=None):
    status, body = call(url, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": name, "arguments": arguments}}, token, headers)
    assert status == 200, body
    result = body["result"]
    text = result["content"][0]["text"]
    return result["isError"], (json.loads(text) if not text.startswith("error:") else text)


GRANT = {"topic_id": "topic-alpha", "commercial": True, "accept_per_item": False, "domain": "finance",
         "invocation_id": "inv_alpha0001"}


class Grants_(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw, cls.server, cls.url = serve()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.gw.stop()

    def grant(self, **over):
        status, body = call(self.url, "/v1/grants", {**GRANT, **over}, TOKENS["engine"])
        self.assertEqual(status, 201, body)
        return body["token"]

    def test_only_a_grantor_mints_and_a_grant_never_does(self):
        self.assertEqual(call(self.url, "/v1/grants", GRANT, TOKENS["operator"])[0], 403, "a configured client that is not a grantor")
        self.assertEqual(call(self.url, "/v1/grants", GRANT, self.grant())[0], 403, "a grant cannot mint a wider one")
        self.assertEqual(call(self.url, "/v1/grants", GRANT)[0], 401)
        status, body = call(self.url, "/v1/grants", GRANT, TOKENS["engine"])
        self.assertEqual((status, body["client_id"], body["policy"], body["invocation_id"]),
                         (201, "engine@topic-alpha", {"topic_id": "topic-alpha", "commercial": True, "accept_per_item": False,
                                                      "domain": "finance"}, "inv_alpha0001"))

    def test_a_grant_request_states_its_posture(self):
        for bad in ({k: v for k, v in GRANT.items() if k != "commercial"}, {**GRANT, "commercial": "no"},
                    {**GRANT, "topic_id": "bad topic"}, {**GRANT, "invocation_id": ""}, {**GRANT, "ttl_seconds": 10},
                    {**GRANT, "scope": "all"}):
            with self.subTest(bad):
                self.assertEqual(call(self.url, "/v1/grants", bad, TOKENS["engine"])[0], 400)

    def test_the_v1_door_binds_the_topic_policy(self):
        token = self.grant()
        for field, value in (("commercial", False), ("topic_id", "topic-beta"), ("accept_per_item", True)):
            with self.subTest(field):
                status, body = call(self.url, "/v1/find", {"query": "q", "kind": "article", field: value}, token)
                self.assertEqual((status, body.get("error")), (403, f"policy-bound: {field} is set by the topic, not the caller"))
        status, body = call(self.url, "/v1/find", {"query": "q", "kind": "article"}, token)
        self.assertEqual(status, 200, body)
        eff = body["effective_request"]
        self.assertEqual((eff["commercial"], eff["accept_per_item"], eff["domain"]), (True, False, "finance"),
                         "control: the grant's posture is injected when the caller says nothing")
        status, body = call(self.url, "/v1/find", {"query": "q", "kind": "article", "domain": "biomed"}, token)
        self.assertEqual((status, body["effective_request"]["domain"]), (200, "biomed"), "domain stays advisory")

    def test_the_grant_carries_its_invocation(self):
        token = self.grant()
        status, body = call(self.url, "/v1/find", {"query": "q"}, token,
                            {"X-Research-Invocation": "inv_other0001", "X-Research-Attempt": "1"})
        self.assertEqual(status, 403, "a grant-bearer cannot act as another invocation")
        status, body = call(self.url, "/v1/find", {"query": "q"}, token, {"X-Research-Invocation": "inv_alpha0001", "X-Research-Attempt": "4"})
        self.assertEqual((body["observation"]["invocation_id"], body["observation"]["attempt"]), ("inv_alpha0001", 4))
        status, body = call(self.url, "/v1/find", {"query": "q"}, token)
        self.assertEqual((body["observation"]["invocation_id"], body["observation"]["attempt"]), ("inv_alpha0001", 1),
                         "control: with no headers the grant's invocation, first attempt")

    def test_the_mcp_door_binds_it_too(self):
        token = self.grant()
        is_error, text = mcp(self.url, token, "research_find", {"query": "q", "commercial": False})
        self.assertTrue(is_error)
        self.assertIn("policy-bound: commercial", text)
        is_error, text = mcp(self.url, token, "research_download", {"target": "hf:a/b", "params": {"path": "x"}, "topic_id": "topic-beta"})
        self.assertTrue(is_error)
        self.assertIn("policy-bound: topic_id", text)
        is_error, out = mcp(self.url, token, "research_batch", {"calls": [
            {"tool": "research_resolve", "arguments": {"identity": "doi:10.1234/abc", "commercial": False}},
            {"tool": "research_resolve", "arguments": {"identity": "doi:10.1234/abc"}}]})
        self.assertIn("policy-bound: commercial", out["results"][0]["error"])
        self.assertEqual(out["results"][1]["result"]["effective_request"]["commercial"], True,
                         "control: the batch's clean entry runs under the grant's posture")
        is_error, out = mcp(self.url, token, "research_find", {"query": "q"})
        self.assertFalse(is_error)
        self.assertEqual((out["effective_request"]["commercial"], out["observation"]["invocation_id"]), (True, "inv_alpha0001"))

    def test_a_forged_altered_expired_or_foreign_grant_is_refused(self):
        token = self.grant()
        body, sig = token[len(GRANT_PREFIX):].split(".")
        claims = json.loads(_unb64(body))
        altered = GRANT_PREFIX + _b64(json.dumps({**claims, "c": False}, sort_keys=True, separators=(",", ":")).encode()) + "." + sig
        foreign = Grants().mint(Principal("engine", grantor=True), GRANT)["token"]   # another gateway process's key
        expired = Grants(key=self.gw.grants._key, clock=lambda: time.time() - 7200).mint(
            Principal("engine", grantor=True), {**GRANT, "ttl_seconds": 3600})["token"]
        for label, bad in (("altered claims", altered), ("another key", foreign), ("expired", expired),
                           ("garbage", GRANT_PREFIX + "x.y"), ("no signature", GRANT_PREFIX + body)):
            with self.subTest(label):
                self.assertEqual(call(self.url, "/v1/find", {"query": "q"}, bad)[0], 401)
        self.assertEqual(call(self.url, "/v1/find", {"query": "q"}, token)[0], 200, "control: the real grant")

    def test_control_an_unbound_client_is_unchanged(self):
        status, body = call(self.url, "/v1/find", {"query": "q", "kind": "article", "commercial": False}, TOKENS["operator"])
        self.assertEqual((status, body["effective_request"]["commercial"]), (200, False))


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class JobsAreTheirTopicsAlone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gw, cls.server, cls.url = serve(use_db=True)
        cls.tag = f"policy-{uuid.uuid4().hex[:8]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.gw.stop()
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.calls WHERE job_id IN (SELECT id FROM gateway.jobs WHERE payload::text LIKE %s)", (f"%{cls.tag}%",))
            cur.execute("DELETE FROM gateway.calls WHERE query LIKE %s", (f"%{cls.tag}%",))
            cur.execute("DELETE FROM gateway.jobs WHERE payload::text LIKE %s", (f"%{cls.tag}%",))
            conn.commit()

    def grant(self, **over):
        return call(self.url, "/v1/grants", {**GRANT, **over}, TOKENS["engine"])[1]["token"]

    def queued_job(self) -> int:
        alpha = self.grant()
        status, body = call(self.url, "/v1/find?async=1", {"query": f"q {self.tag} {uuid.uuid4().hex[:6]}", "kind": "article"}, alpha)
        self.assertEqual(status, 202, body)
        self.assertEqual(body["observation"]["invocation_id"], "inv_alpha0001")
        job = self.gw.wait(body["job_id"], 20)
        self.assertEqual((job["payload"]["topic_id"], job["payload"]["commercial"], job["invocation_id"]),
                         ("topic-alpha", True, "inv_alpha0001"), "the queued job is bound as the grant says")
        return body["job_id"]

    def test_the_async_door_binds_the_policy(self):
        status, _ = call(self.url, "/v1/resolve?async=1", {"identity": "doi:10.1234/abc", "commercial": False}, self.grant())
        self.assertEqual(status, 403)

    def test_control_its_own_topic_reads_its_job(self):
        job_id = self.queued_job()
        self.assertEqual(call(self.url, f"/v1/jobs/{job_id}", token=self.grant())[0], 200)
        is_error, job = mcp(self.url, self.grant(), "research_job", {"job_id": job_id})
        self.assertEqual(job["id"], job_id)

    def test_polling_never_crosses_topics_or_postures(self):
        job_id = self.queued_job()
        beta = self.grant(topic_id="topic-beta", invocation_id="inv_beta00001")
        self.assertEqual(call(self.url, f"/v1/jobs/{job_id}", token=beta)[0], 404, "another topic's grant never sees it")
        is_error, text = mcp(self.url, beta, "research_job", {"job_id": job_id})
        self.assertEqual(text.get("capability_fact") if isinstance(text, dict) else text, "gateway_error_404")
        loosened = self.grant(commercial=False, invocation_id="inv_alpha0002")
        self.assertEqual(call(self.url, f"/v1/jobs/{job_id}", token=loosened)[0], 404,
                         "the same topic under another posture does not read results obtained under this one")
        self.assertEqual(call(self.url, f"/v1/jobs/{job_id}", token=TOKENS["engine"])[0], 404,
                         "the grantor's own unbound session is a different client")

if __name__ == "__main__":
    unittest.main()
