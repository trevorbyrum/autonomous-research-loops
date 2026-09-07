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

    def test_capability_facts_are_never_searched_empty(self):
        self.assertEqual(R._fact_coverage("no BEA key configured"), "auth_failed")
        self.assertEqual(R._fact_coverage("no Census key configured; the keyless 500/day tier is not enabled"), "auth_failed")
        self.assertEqual(R._fact_coverage("BEA: something went wrong"), "provider_unavailable")

    def test_exhausted_lanes_are_marked_and_never_restarted(self):
        r, c, t = make()
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [CROSSREF_WORK], "total-results": 1}})
        t.add("GET", "https://doaj.org/api/search/articles/", body={"results": [], "total": 0})
        out = R.execute(r, {"request_type": "find", "query": "exhaustion", "kind": "article"}, c)
        self.assertEqual(out["next"].get("crossref"), R.EXHAUSTED_CURSOR,
                         "a lane that answered without a continuation says so explicitly")
        calls_before = len(t.calls)
        again = R.execute(r, {"request_type": "find", "query": "exhaustion", "kind": "article",
                              "cursors": dict(out["next"])}, c)
        entry = next(ln for ln in again["lanes"] if ln["source"] == "crossref")
        self.assertEqual(entry["coverage"], "exhausted")
        self.assertFalse(any("crossref" in u for _, u, _, _ in t.calls[calls_before:]),
                         "handing the next map back never re-dispatches the exhausted lane")

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
        stored = R.redact_for_storage(result, {"crossref": {"license": "CC0 1.0"}})
        members = stored["records"][0]["provenance"]
        self.assertEqual(members[0], {"source_id": "crossref", "identity": "doi:10.1/p", "license": "cc-by-4.0",
                                      "retrieved_at": "2026-09-07T00:00:00+00:00", "metadata_license": "CC0 1.0"})
        self.assertEqual(members[1], {"source_id": "doaj", "identity": "doi:10.1/p"})
        self.assertNotIn("raw", json.dumps(stored), "no member ever smuggles raw into gateway.jobs")
        self.assertEqual(stored["records"][0]["retrieved_at"], "2026-09-07T00:00:00+00:00")

    def test_summary_values_must_be_scalar_strings(self):
        """Pass-1 finding 8: a nested object in a whitelisted field name (a DOAJ licence
        dict carrying raw) must never ride the summary into gateway.jobs."""
        result = {"request_type": "find", "records": [{
            "identity": "doi:10.1/n", "kind": "article", "sources": ["doaj"],
            "provenance": [{"source_id": "doaj", "identity": "doi:10.1/n",
                            "license": {"type": "CC BY", "raw": {"rows": [[1]], "text": "full text"}},
                            "attribution": ["not", "a", "string"]}]}], "facts": [], "lanes": []}
        stored = R.redact_for_storage(result)
        self.assertEqual(stored["records"][0]["provenance"], [{"source_id": "doaj", "identity": "doi:10.1/n"}])
        flat = json.dumps(stored)
        for forbidden in ("raw", "rows", "full text"):
            self.assertNotIn(forbidden, flat)


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
        default = {"topic_id": "topic-x", "commercial": True, "accept_per_item": False}
        return {"id": job_id, "status": "done", "payload": getattr(self, "job_payload", default)}


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

    def test_job_polling_is_policy_bound_too(self):
        """Findings 1 (both rounds): a bound topic never reads another topic's job, and
        even its OWN older jobs must match the policy in force now."""
        client = StubClient()
        client.job_payload = {"topic_id": "someone-else", "query": "q"}
        with self.assertRaises(mcp_stdio.PolicyError):
            mcp_stdio.call_tool(client, "research_job", {"job_id": 7}, policy=BOUND)
        client.job_payload = {"topic_id": "topic-x", "query": "q", "commercial": False}
        with self.assertRaises(mcp_stdio.PolicyError, msg="a since-tightened commercial posture "
                               "never reads personal-mode results"):
            mcp_stdio.call_tool(client, "research_job", {"job_id": 7}, policy=BOUND)
        client.job_payload = {"topic_id": "topic-x", "query": "q", "commercial": True, "accept_per_item": False}
        out = mcp_stdio.call_tool(client, "research_job", {"job_id": 7}, policy=BOUND)
        self.assertEqual(out["id"], 7)
        out = mcp_stdio.call_tool(StubClient(), "research_job", {"job_id": 7}, policy={})
        self.assertEqual(out["id"], 7, "unbound sessions poll exactly as before")

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
        self.assertEqual((out["id"], out["status"]), (41, "done"))


class ActivityFile(unittest.TestCase):
    def test_degraded_lanes_and_gateway_failures_are_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "research-activity.jsonl")
            client = StubClient()  # default result has one provider_unavailable lane
            mcp_stdio.call_tool(client, "research_find", {"query": "q"}, activity=path)
            down = StubClient(boom=ConnectionError("gateway is gone"))
            with self.assertRaises(ConnectionError):
                mcp_stdio.call_tool(down, "research_find", {"query": "q"}, activity=path)
            fact = StubClient(result={"capability_fact": "gateway_unavailable", "error": "connection refused"})
            mcp_stdio.call_tool(fact, "research_find", {"query": "q2"}, activity=path)
            lines = [json.loads(l) for l in Path(path).read_text().splitlines()]
        self.assertEqual([(l["source"], l["coverage"]) for l in lines],
                         [("crossref", "provider_unavailable"), ("gateway", "searched_ok"),
                          ("gateway", "provider_unavailable"), ("gateway", "provider_unavailable")],
                         "thrown errors AND capability-fact answers both land; a gateway that "
                         "answered logs its own ok so its blocker can clear (findings 3, 6)")

    def test_transitions_are_ordered_and_recovery_is_never_deduplicated(self):
        """Pass-1 finding 6: fail -> ok for the SAME request must be visible as the
        key's last state; repeats of an unchanged state write nothing."""
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "activity.jsonl")
            ok = {"request_type": "find", "records": [], "facts": [],
                  "lanes": [{"source": "crossref", "coverage": "searched_ok"}]}
            bad = {"request_type": "find", "records": [], "facts": [],
                   "lanes": [{"source": "crossref", "coverage": "provider_unavailable"}]}
            for result in (ok, ok, bad, ok):
                mcp_stdio.call_tool(StubClient(result=result), "research_find", {"query": "q"}, activity=path)
            mcp_stdio.call_tool(StubClient(result=ok), "research_find", {"query": "other"}, activity=path)
            lines = [json.loads(l) for l in Path(path).read_text().splitlines()]
        crossref = [(l["coverage"], l["query_or_identity"]) for l in lines if l["source"] == "crossref"]
        self.assertEqual(crossref,
                         [("searched_ok", "q"), ("provider_unavailable", "q"), ("searched_ok", "q"),
                          ("searched_ok", "other")],
                         "one line per transition, per exact request, in order")
        self.assertEqual([l["query_or_identity"] for l in lines if l["source"] == "gateway"], ["q", "other"],
                         "each answered request also logs the gateway ok, once per request")
        out = mcp_stdio.call_tool(StubClient(), "research_find", {"query": "q"},
                                  activity="/nonexistent-dir/activity.jsonl")
        self.assertIn("lanes", out, "an unwritable activity file never breaks the answer")


class DownloadHandoff(unittest.TestCase):
    def _client(self):
        return StubClient(result={"request_type": "fetch", "records": [], "facts": [], "lanes": [],
                                  "content": b"\xd0\xcf\x11payload", "content_type": "application/vnd.ms-excel"})

    def test_fetch_lists_only_and_points_at_download(self):
        with self.assertRaises(ValueError):
            mcp_stdio.call_tool(self._client(), "research_fetch",
                                {"target": "doi:x", "params": {"download": True}})

    def test_bytes_land_in_the_iteration_download_dir(self):
        with tempfile.TemporaryDirectory() as d:
            out = mcp_stdio.call_tool(self._client(), "research_download",
                                      {"target": "https://globeproject.com/data/x.xls"}, download_dir=d)
            self.assertIsNone(out["content"])
            self.assertEqual(out["content_bytes"], 10)
            saved = Path(out["saved_to"])
            self.assertEqual(saved.parent, Path(d))
            self.assertEqual(saved.read_bytes(), b"\xd0\xcf\x11payload")
            self.assertIn("x.xls", saved.name)

    def test_same_second_downloads_never_overwrite_and_carry_identity(self):
        """Pass-1 finding 11: two files from one dataset in one second are two files."""
        with tempfile.TemporaryDirectory() as d:
            first = mcp_stdio.call_tool(self._client(), "research_download",
                                        {"target": "doi:10.7910/DVN/X", "params": {"file_id": 1}},
                                        download_dir=d)
            second = mcp_stdio.call_tool(self._client(), "research_download",
                                         {"target": "doi:10.7910/DVN/X", "params": {"file_id": 1}},
                                         download_dir=d)
            self.assertNotEqual(first["saved_to"], second["saved_to"])
            self.assertEqual(len(list(Path(d).iterdir())), 2)
            self.assertIn("_1", Path(first["saved_to"]).name, "the file identity is in the name")

    def test_without_a_download_dir_bytes_are_only_counted(self):
        client = StubClient(result={"request_type": "fetch", "records": [], "facts": [], "lanes": [],
                                    "content": b"abc"})
        out = mcp_stdio.call_tool(client, "research_download", {"target": "url:x"}, download_dir=None)
        self.assertEqual((out["content"], out["content_bytes"]), (None, 3))
        self.assertNotIn("saved_to", out)




class ReverifyRoundPins(unittest.TestCase):
    """The seven re-verification reopenings, pinned (report findings 1/3/4/6/7/9/19)."""

    def test_html_with_a_success_status_is_unavailable_not_empty(self):
        from research_gateway.adapters.base import Response, SourceUnavailable, check
        for body in (b"<!DOCTYPE html><html>bot wall</html>",
                     b"\xef\xbb\xbf<html>BOM first</html>",
                     b"<!-- served by cdn --><html>challenge</html>"):
            with self.assertRaises(SourceUnavailable, msg=body):
                check("crossref", Response(200, {"content-type": "text/html"}, body, "u"))
        with self.assertRaises(SourceUnavailable, msg="sniff without a declared type"):
            check("crossref", Response(200, {}, b"  <!doctype html><html/>", "u"))
        html = Response(200, {"content-type": "text/html"}, b"<html>doc</html>", "u")
        self.assertTrue(check("globe", html, allow_html=True), "raw file paths may fetch HTML documents")
        self.assertTrue(check("crossref", Response(200, {}, b'{"ok": 1}', "u")))
        self.assertTrue(check("bis", Response(200, {"content-type": "application/xml"},
                                              b"<!-- sdmx --><?xml version='1.0'?><doc/>", "u")),
                        "a comment-prefixed XML answer with a declared type stays usable")

    def test_empty_lanes_are_exhausted_too_but_failed_lanes_never_are(self):
        r, c, t = make()
        t.add("GET", "https://api.crossref.org/works?", body={"message": {"items": [], "total-results": 0}})
        t.add("GET", "https://doaj.org/api/search/articles/", status=503)
        out = R.execute(r, {"request_type": "find", "query": "nothing here", "kind": "article"}, c)
        self.assertEqual(out["next"].get("crossref"), R.EXHAUSTED_CURSOR,
                         "an EMPTY answer is also final: continuation must not re-dispatch it")
        self.assertNotIn("doaj", out.get("next") or {},
                         "a FAILED lane is never exhausted — that would clear its blocker "
                         "without any successful research (closing-round finding 9)")

    def test_empty_fulltext_enrichment_is_metadata_only(self):
        r, c, t = make()
        t.add("GET", "https://api.unpaywall.org/v2/", body={"doi": "10.1/x", "oa_locations": [], "best_oa_location": None})
        out = R.execute(r, {"request_type": "enrich", "identity": "doi:10.1/x", "what": "oa_location"}, c)
        lanes = {ln["source"]: ln.get("coverage") for ln in out["lanes"]}
        self.assertIn("metadata_only", lanes.values(),
                      "the record exists; an empty full-text answer is not an empty search")

    def test_data_requests_key_by_series_not_source(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "activity.jsonl")
            down = {"request_type": "data", "records": [], "facts": [],
                    "lanes": [{"source": "fred", "coverage": "provider_unavailable"}]}
            ok = {"request_type": "data", "records": [], "facts": [],
                  "lanes": [{"source": "fred", "coverage": "searched_ok"}]}
            mcp_stdio.call_tool(StubClient(result=down), "research_data",
                                {"source": "fred", "params": {"series": "GDP"}}, activity=path)
            mcp_stdio.call_tool(StubClient(result=ok), "research_data",
                                {"source": "fred", "params": {"series": "UNRATE"}}, activity=path)
            lines = [json.loads(l) for l in Path(path).read_text().splitlines() if json.loads(l)["source"] == "fred"]
        self.assertEqual(len({l["query_or_identity"] for l in lines}), 2,
                         "a GDP failure and an UNRATE success are different requests (finding 4)")

    def test_polled_job_lanes_key_by_the_original_request(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "activity.jsonl")
            client = StubClient()
            job = {"id": 9, "status": "done", "request_type": "find",
                   "payload": {"topic_id": "topic-x", "query": "stored q"},
                   "result": {"lanes": [{"source": "crossref", "coverage": "provider_unavailable"}]}}
            client.job = lambda job_id: job
            mcp_stdio.call_tool(client, "research_job", {"job_id": 9}, activity=path)
            lines = [json.loads(l) for l in Path(path).read_text().splitlines()]
        self.assertIn(("crossref", "provider_unavailable", "find", "stored q"),
                      [(l["source"], l["coverage"], l["request_type"], l["query_or_identity"]) for l in lines],
                      "a polled failure and a direct retry of the same search share one blocker "
                      "key (closing-round finding 6)")

    def test_polling_outages_are_recorded_never_mistaken_for_policy_violations(self):
        """Closing-round finding 3: a gateway-trouble poll answer has no payload — it is
        an outage observation for the guard, not a policy question."""
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "activity.jsonl")
            client = StubClient()
            client.job = lambda job_id: {"capability_fact": "gateway_unavailable", "error": "connection refused"}
            out = mcp_stdio.call_tool(client, "research_job", {"job_id": 5}, policy=BOUND, activity=path)
            self.assertEqual(out["capability_fact"], "gateway_unavailable")
            lines = [json.loads(l) for l in Path(path).read_text().splitlines()]
        self.assertEqual([(l["source"], l["coverage"], l["query_or_identity"]) for l in lines],
                         [("gateway", "provider_unavailable", "job:5")],
                         "recorded under the stable job key, so a later successful poll clears it")


if __name__ == "__main__":
    unittest.main()
