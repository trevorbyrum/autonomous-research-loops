"""Phase 8 acceptance for docs/STATION-CONTRACT.md: coverage states on every lane,
whitelisted provenance summaries in stored results, per-record retrieval stamps,
topic-policy enforcement in the stdio dispatcher, the research-activity file, and the
station-side download handoff."""
import json
import tempfile
import unittest
from pathlib import Path

from research_gateway import adapters
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.clients import mcp_stdio
from research_gateway.core import dedup
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.canonical import make_record
from research_gateway.registry.load import read_seed
from tests.test_adapters_articles import CROSSREF_WORK

SEED = read_seed()
ADAPTERS = adapters.load_all()


def make():
    t = FakeTransport()
    b = Broker({s["id"]: RatePolicy(per_second=100) for s in SEED})
    return R.Router(SEED, ADAPTERS), Client(broker=b, transport=t), t


class CoverageStates(unittest.TestCase):
    def test_every_lane_reports_its_coverage_state(self):
        r, c, t = make()
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
        t.add("GET", "https://api.semanticscholar.org/graph/v1/paper/search", status=401, body={"error": "bad key"})
        out = R.execute(r, {"request_type": "find", "query": "coverage states", "kind": "article"}, c)
        cov = {ln["source"]: ln.get("coverage") for ln in out["lanes"]}
        self.assertEqual(cov.get("crossref"), "searched_ok")
        self.assertEqual(cov.get("doaj"), "searched_empty",
                         "searched-and-found-nothing is never conflated with unavailable")
        self.assertEqual(cov.get("semanticscholar"), "auth_failed")
        self.assertTrue(all(ln.get("coverage") for ln in out["lanes"]), out["lanes"])

    def test_outage_and_commercial_skip_states(self):
        r, c, t = make()
        t.add("GET", "https://api.crossref.org/works?", status=503)
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
        out = R.execute(r, {"request_type": "find", "query": "outages", "kind": "article", "commercial": True}, c)
        cov = {ln["source"]: ln.get("coverage") for ln in out["lanes"]}
        self.assertEqual(cov.get("crossref"), "provider_unavailable")
        skipped = [ln for ln in out["lanes"] if ln.get("role") == "skipped"]
        self.assertTrue(skipped, "commercially dropped lanes appear with coverage not_searched")
        self.assertTrue(all(ln["coverage"] == "not_searched" for ln in skipped))

    def test_data_answers_echo_the_request_for_reproducible_citations(self):
        r, c, _ = make()
        out = R.execute(r, {"request_type": "data", "source": "fred", "params": {"series": "GDP"}}, c)
        self.assertEqual(out["request"], {"source": "fred", "params": {"series": "GDP"}})


class RetrievalStamps(unittest.TestCase):
    def test_every_record_carries_retrieved_at(self):
        rec = make_record(identity="doi:10.1/x", kind="article", source_id="crossref", title="T")
        self.assertRegex(rec["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")

    def test_dedup_members_keep_their_own_retrieval_times(self):
        a = make_record(identity="doi:10.1/m", kind="article", source_id="crossref", title="M", raw={"a": 1})
        b = {**make_record(identity="doi:10.1/m", kind="article", source_id="doaj", title="M", raw={"b": 2}),
             "retrieved_at": "2026-01-01T00:00:00+00:00"}
        merged = dedup.cluster([a, b])[0]
        times = {m["source_id"]: m.get("retrieved_at") for m in merged["provenance"]}
        self.assertEqual(times["crossref"], a["retrieved_at"])
        self.assertEqual(times["doaj"], "2026-01-01T00:00:00+00:00",
                         "merged sources retrieved on different dates keep their own stamps")


class StoredProvenanceSummary(unittest.TestCase):
    def test_stored_results_keep_citation_ingredients_and_never_raw(self):
        result = {"request_type": "find", "records": [{
            "identity": "doi:10.1/p", "kind": "article", "title": "P", "sources": ["crossref", "doaj"],
            "retrieved_at": "2026-09-07T00:00:00+00:00",
            "provenance": [
                {"source_id": "crossref", "identity": "doi:10.1/p", "license": "cc-by-4.0",
                 "retrieved_at": "2026-09-07T00:00:00+00:00", "raw": {"secret": "payload"}},
                {"source_id": "doaj", "identity": "doi:10.1/p", "license": None, "raw": {"x": 1}, "rows": [[1]]},
            ]}], "facts": [], "lanes": []}
        stored = R.redact_for_storage(result)
        members = stored["records"][0]["provenance"]
        self.assertEqual(members[0], {"source_id": "crossref", "identity": "doi:10.1/p", "license": "cc-by-4.0",
                                      "retrieved_at": "2026-09-07T00:00:00+00:00"})
        self.assertEqual(members[1], {"source_id": "doaj", "identity": "doi:10.1/p"})
        self.assertNotIn("raw", json.dumps(stored), "no member ever smuggles raw into gateway.jobs")
        self.assertEqual(stored["records"][0]["retrieved_at"], "2026-09-07T00:00:00+00:00")


class StubClient:
    """GatewayClient stand-in: records what the dispatcher actually sends over HTTP."""

    def __init__(self, result=None, boom=None):
        self.seen = []
        self.result = result or {"request_type": "find", "records": [], "facts": [],
                                 "lanes": [{"source": "crossref", "coverage": "provider_unavailable"}]}
        self.boom = boom

    def request(self, rt, payload):
        if self.boom:
            raise self.boom
        self.seen.append((rt, dict(payload)))
        return dict(self.result)

    def status(self):
        return {"health": {"ok": True}}

    def job(self, job_id):
        self.seen.append(("job", job_id))
        return {"id": job_id, "status": "done"}


BOUND = {"topic_id": "topic-x", "commercial": True, "accept_per_item": False, "domain": "finance"}


class PolicyBinding(unittest.TestCase):
    def test_env_parsing(self):
        env = {"RESEARCH_TOPIC_ID": "topic-x", "RESEARCH_TOPIC_COMMERCIAL": "1",
               "RESEARCH_TOPIC_ACCEPT_PER_ITEM": "false", "RESEARCH_TOPIC_DOMAIN": "finance"}
        self.assertEqual(mcp_stdio.policy_from_env(env), BOUND)
        self.assertEqual(mcp_stdio.policy_from_env({}), {}, "no environment, no binding")

    def test_bound_fields_are_injected_and_domain_stays_advisory(self):
        client = StubClient()
        mcp_stdio.call_tool(client, "research_find", {"query": "q"}, policy=BOUND)
        rt, payload = client.seen[0]
        self.assertEqual((payload["topic_id"], payload["commercial"], payload["accept_per_item"]),
                         ("topic-x", True, False))
        self.assertEqual(payload["domain"], "finance")
        mcp_stdio.call_tool(client, "research_find", {"query": "q", "domain": "ai-ml"}, policy=BOUND)
        self.assertEqual(client.seen[1][1]["domain"], "ai-ml", "domain is a routing hint the agent may override")

    def test_conflicting_argument_is_rejected_not_overridden(self):
        client = StubClient()
        for field, value in (("commercial", False), ("accept_per_item", True), ("topic_id", "other")):
            with self.assertRaises(mcp_stdio.PolicyError, msg=field):
                mcp_stdio.call_tool(client, "research_find", {"query": "q", field: value}, policy=BOUND)
        self.assertEqual(client.seen, [], "nothing reaches the gateway on a policy conflict")
        out = mcp_stdio.handle({"method": "tools/call", "params": {"name": "research_find",
                                                                   "arguments": {"query": "q", "commercial": False}}},
                               lambda n, a: mcp_stdio.call_tool(client, n, a, policy=BOUND))
        self.assertTrue(out["isError"])
        self.assertIn("policy-bound", out["content"][0]["text"])

    def test_unbound_session_passes_arguments_through_unchanged(self):
        client = StubClient()
        mcp_stdio.call_tool(client, "research_find", {"query": "q", "commercial": False}, policy={})
        self.assertEqual(client.seen[0][1], {"query": "q", "commercial": False})


class BatchAndJob(unittest.TestCase):
    def test_batch_runs_each_entry_and_keeps_failures_in_place(self):
        client = StubClient(result={"request_type": "resolve", "records": [], "facts": [], "lanes": []})
        out = mcp_stdio.call_tool(client, "research_batch", {"calls": [
            {"tool": "research_resolve", "arguments": {"identity": "doi:10.1/a"}},
            {"tool": "research_find", "arguments": {"query": "not allowed"}},
            {"tool": "research_enrich", "arguments": {"identity": "doi:10.1/a", "what": "citations"}},
        ]}, policy=BOUND)
        self.assertEqual([("result" in r, "error" in r) for r in out["results"]],
                         [(True, False), (False, True), (True, False)])
        self.assertTrue(all(p["topic_id"] == "topic-x" for _, p in client.seen), "policy binds batch members too")

    def test_batch_bounds(self):
        client = StubClient()
        with self.assertRaises(ValueError):
            mcp_stdio.call_tool(client, "research_batch", {"calls": []})
        with self.assertRaises(ValueError):
            mcp_stdio.call_tool(client, "research_batch",
                                {"calls": [{"tool": "research_resolve", "arguments": {}}] * 21})

    def test_job_lookup(self):
        client = StubClient()
        out = mcp_stdio.call_tool(client, "research_job", {"job_id": 41})
        self.assertEqual(out, {"id": 41, "status": "done"})


class ActivityFile(unittest.TestCase):
    def test_degraded_lanes_and_gateway_failures_are_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "research-activity.jsonl")
            client = StubClient()  # default result has one provider_unavailable lane
            mcp_stdio.call_tool(client, "research_find", {"query": "q"}, activity=path)
            down = StubClient(boom=ConnectionError("gateway is gone"))
            with self.assertRaises(ConnectionError):
                mcp_stdio.call_tool(down, "research_find", {"query": "q"}, activity=path)
            lines = [json.loads(l) for l in Path(path).read_text().splitlines()]
        self.assertEqual([(l["source"], l["coverage"]) for l in lines],
                         [("crossref", "provider_unavailable"), ("gateway", "provider_unavailable")])
        self.assertTrue(all(l["at"] and l["request_type"] == "find" for l in lines))

    def test_successes_are_logged_once_per_pair_so_blockers_can_clear(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "activity.jsonl")
            client = StubClient(result={"request_type": "find", "records": [], "facts": [],
                                        "lanes": [{"source": "crossref", "coverage": "searched_ok"},
                                                  {"source": "doaj", "coverage": "searched_empty"}]})
            mcp_stdio.call_tool(client, "research_find", {"query": "q"}, activity=path)
            mcp_stdio.call_tool(client, "research_find", {"query": "q2"}, activity=path)
            lines = [json.loads(l) for l in Path(path).read_text().splitlines()]
        self.assertEqual([(l["source"], l["coverage"]) for l in lines],
                         [("crossref", "searched_ok"), ("doaj", "searched_empty")],
                         "each successful (source, coverage) pair is written once per process, not per call")
        out = mcp_stdio.call_tool(StubClient(), "research_find", {"query": "q"},
                                  activity="/nonexistent-dir/activity.jsonl")
        self.assertIn("lanes", out, "an unwritable activity file never breaks the answer")


class DownloadHandoff(unittest.TestCase):
    def test_bytes_land_in_the_topic_downloads_dir(self):
        client = StubClient(result={"request_type": "fetch", "records": [], "facts": [], "lanes": [],
                                    "content": b"\xd0\xcf\x11payload", "content_type": "application/vnd.ms-excel"})
        with tempfile.TemporaryDirectory() as d:
            out = mcp_stdio.call_tool(client, "research_fetch",
                                      {"target": "https://globeproject.com/data/x.xls"}, topic_dir=d)
            self.assertIsNone(out["content"])
            self.assertEqual(out["content_bytes"], 10)
            saved = Path(out["saved_to"])
            self.assertEqual(saved.parent, Path(d) / "downloads")
            self.assertEqual(saved.read_bytes(), b"\xd0\xcf\x11payload")
            self.assertIn("x.xls", saved.name)

    def test_without_a_topic_dir_bytes_are_only_counted(self):
        client = StubClient(result={"request_type": "fetch", "records": [], "facts": [], "lanes": [],
                                    "content": b"abc"})
        out = mcp_stdio.call_tool(client, "research_fetch", {"target": "url:x"}, topic_dir=None)
        self.assertEqual((out["content"], out["content_bytes"]), (None, 3))
        self.assertNotIn("saved_to", out)


if __name__ == "__main__":
    unittest.main()
