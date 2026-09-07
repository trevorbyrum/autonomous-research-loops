"""Phase 2 acceptance for the job queue and call log — runs against the real
schema when RESEARCH_GATEWAY_DSN is set, otherwise skipped, because these
tests exercise Postgres semantics (SKIP LOCKED, partial unique indexes) that
no in-memory substitute reproduces."""
import threading
import unittest
import uuid

from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core import calllog, db, queue
from research_gateway.core.broker import Broker, RatePolicy

HAVE_DB = db.configured()


def plain_client(conn, job):
    """A metered client with no policies: any outbound call would be refused and logged."""
    return Client(broker=Broker({}), transport=FakeTransport(), conn=conn, job_id=job["id"])


@unittest.skipUnless(HAVE_DB, "RESEARCH_GATEWAY_DSN not set")
class QueueTests(unittest.TestCase):
    def setUp(self):
        self.client = f"test-{uuid.uuid4()}"
        self.conn = db.connect()

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.calls WHERE job_id IN (SELECT id FROM gateway.jobs WHERE client_id = %s)", (self.client,))
            cur.execute("DELETE FROM gateway.jobs WHERE client_id = %s", (self.client,))
        self.conn.commit()
        self.conn.close()

    def test_enqueue_claim_finish(self):
        jid, created = queue.enqueue(self.conn, "find", {"q": "reranking", "n": 1}, client_id=self.client)
        self.assertTrue(created)
        job = queue.claim(self.conn)
        # another test's job could be claimed first; claim until ours appears (bounded)
        seen = []
        while job and job["id"] != jid and len(seen) < 50:
            seen.append(job["id"]); queue.fail(self.conn, job["id"], "refused", {"reason": "not mine"}); job = queue.claim(self.conn)
        self.assertIsNotNone(job)
        self.assertEqual(job["id"], jid)
        self.assertEqual(job["payload"], {"q": "reranking", "n": 1})
        queue.finish(self.conn, jid, {"ok": True})
        self.assertEqual(queue.get(self.conn, jid)["status"], "done")

    def test_inflight_dedup(self):
        j1, c1 = queue.enqueue(self.conn, "resolve", {"doi": "10.1/x"}, client_id=self.client)
        j2, c2 = queue.enqueue(self.conn, "resolve", {"doi": "10.1/x"}, client_id=self.client)
        self.assertTrue(c1)
        self.assertFalse(c2)
        self.assertEqual(j1, j2)
        queue.fail(self.conn, j1, "refused")
        j3, c3 = queue.enqueue(self.conn, "resolve", {"doi": "10.1/x"}, client_id=self.client)
        self.assertTrue(c3, "once the first job is terminal a new one may be queued")

    def test_priority_order(self):
        low, _ = queue.enqueue(self.conn, "fetch", {"u": self.client + "low"}, client_id=self.client, priority=queue.PRIORITY_HARVEST)
        high, _ = queue.enqueue(self.conn, "fetch", {"u": self.client + "high"}, client_id=self.client, priority=queue.PRIORITY_INTERACTIVE)
        order = []
        for _ in range(60):
            job = queue.claim(self.conn)
            if job is None:
                break
            if job["client_id"] == self.client:
                order.append(job["id"])
            queue.finish(self.conn, job["id"], {})
            if len(order) == 2:
                break
        self.assertEqual(order, [high, low])

    def test_skip_locked_two_connections_never_share_a_job(self):
        ids = {queue.enqueue(self.conn, "enrich", {"k": f"{self.client}-{i}"}, client_id=self.client)[0] for i in range(6)}
        claimed: list[int] = []
        lock = threading.Lock()

        def worker():
            with db.connect() as c:
                while True:
                    job = queue.claim(c)
                    if job is None:
                        return
                    if job["client_id"] == self.client:
                        with lock:
                            claimed.append(job["id"])
                    queue.finish(c, job["id"], {})

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(claimed), sorted(ids))
        self.assertEqual(len(claimed), len(set(claimed)), "a job was claimed twice")

    def test_run_once_dispatches_and_records_failures(self):
        jid, _ = queue.enqueue(self.conn, "data", {"series": "GDP", "c": self.client}, client_id=self.client)
        handled = []
        handlers = {"data": lambda client, job: handled.append(job["id"]) or {"rows": 1}}
        for _ in range(60):
            if not queue.run_once(self.conn, handlers, plain_client):
                break
            if jid in handled:
                break
        self.assertIn(jid, handled)
        self.assertEqual(queue.get(self.conn, jid)["result"], {"rows": 1})

        jid2, _ = queue.enqueue(self.conn, "find", {"q": self.client + "boom"}, client_id=self.client)

        def boom(client, job):
            raise ValueError("adapter exploded")

        for _ in range(60):
            if not queue.run_once(self.conn, {"find": boom}, plain_client):
                break
            if queue.get(self.conn, jid2)["status"] != "queued":
                break
        got = queue.get(self.conn, jid2)
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["error_class"], "outage")
        self.assertIn("adapter exploded", got["result"]["error"])

    def test_dispatched_call_gets_exactly_one_calls_row_with_job_id(self):
        """Phase 2 check: every dispatched call has a gateway.calls row (I-6)."""
        jid, _ = queue.enqueue(self.conn, "resolve", {"doi": self.client + "-logged"}, client_id=self.client)
        transport = FakeTransport()
        transport.add("GET", "https://api.crossref.org/works/", body={"message": {"DOI": "10.1000/x"}})
        broker = Broker({"crossref": RatePolicy(per_second=100)})

        def make_client(conn, job):
            return Client(broker=broker, transport=transport, conn=conn, job_id=job["id"])

        def handler(client, job):
            client.get("crossref", "resolve", "https://api.crossref.org/works/10.1000/x", identity="doi:10.1000/x")
            return {"ok": True}

        for _ in range(60):
            if not queue.run_once(self.conn, {"resolve": handler}, make_client):
                break
            if queue.get(self.conn, jid)["status"] != "queued":
                break
        self.assertEqual(queue.get(self.conn, jid)["status"], "done")
        with self.conn.cursor() as cur:
            cur.execute("SELECT count(*), min(source_id), min(status) FROM gateway.calls WHERE job_id = %s", (jid,))
            self.assertEqual(cur.fetchone(), (1, "crossref", 200))

    def test_unknown_request_type_rejected(self):
        with self.assertRaises(ValueError):
            queue.enqueue(self.conn, "delete_everything", {}, client_id=self.client)

    def test_worker_thread_processes_and_stops(self):
        jid, _ = queue.enqueue(self.conn, "resolve", {"doi": self.client}, client_id=self.client)
        stop = threading.Event()
        w = queue.Worker(db.connect, {"resolve": lambda client, job: {"doi": job["payload"]["doi"]}}, stop, plain_client, poll_seconds=0.05)
        w.start()
        for _ in range(100):
            if queue.get(self.conn, jid)["status"] == "done":
                break
            threading.Event().wait(0.05)
        stop.set()
        w.join(timeout=5)
        self.assertIsNone(w.error)
        self.assertEqual(queue.get(self.conn, jid)["status"], "done")


@unittest.skipUnless(HAVE_DB, "RESEARCH_GATEWAY_DSN not set")
class CallLogTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect()
        self.ids = []

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.calls WHERE id = ANY(%s)", (self.ids,))
        self.conn.commit()
        self.conn.close()

    def test_record_and_read_back(self):
        rec = calllog.CallRecord(source_id="crossref", request_type="resolve", status=200, latency_ms=42,
                                 identity="doi:10.1/x", ratelimit={"x-ratelimit-limit": "50"}, result_count=1)
        rid = calllog.record(self.conn, rec)
        self.ids.append(rid)
        with self.conn.cursor() as cur:
            cur.execute("SELECT source_id, status, failure_class, ratelimit->>'x-ratelimit-limit', cache_hit FROM gateway.calls WHERE id = %s", (rid,))
            self.assertEqual(cur.fetchone(), ("crossref", 200, "ok", "50", False))


class JobIdentity(unittest.TestCase):
    def test_commercial_flag_is_part_of_the_job_identity(self):
        p = {"identity": "doi:10.1000/x"}
        self.assertEqual(queue.payload_hash("resolve", p), queue.payload_hash("resolve", dict(p), commercial=False))
        self.assertNotEqual(queue.payload_hash("resolve", p), queue.payload_hash("resolve", p, commercial=True),
                            "a personal and a commercial twin must never collapse onto one job (R-8)")


class Classification(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(calllog.classify(200), "ok")
        self.assertEqual(calllog.classify(429), "quota")
        self.assertEqual(calllog.classify(404), "notfound")
        self.assertEqual(calllog.classify(503), "outage")
        self.assertEqual(calllog.classify(None, network_error=True), "outage")
        self.assertEqual(calllog.classify(401), "auth")
        self.assertEqual(calllog.classify(403, body="<html>Cloudflare challenge</html>"), "botwall")
        self.assertEqual(calllog.classify(302), "refused")

    def test_ratelimit_headers_filtered(self):
        h = {"Content-Type": "json", "X-RateLimit-Limit": "50", "Retry-After": "30", "x-ratelimit-remaining": "49"}
        self.assertEqual(calllog.ratelimit_headers(h), {"x-ratelimit-limit": "50", "retry-after": "30", "x-ratelimit-remaining": "49"})


if __name__ == "__main__":
    unittest.main()
