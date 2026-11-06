"""gen2/exec views, scope builder, artifact binding and the scope prompt. Oracles: scoping-report, source-artifact,
outcome-document and judgment-scope schemas (SchemaSet); hashlib for byte digests; the router's own scoping
checks, restated as assertions (brief pin, content hash, gap map within facets, coverage equal to observations).
Limits: rows are hand-built to topic_records' ticket-plan shape; the live router route is T12-A's."""
import copy
import hashlib
import importlib.util
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from gen2.core import canonical
from gen2.exec import artifacts, common, scope, views
from gen2.router.schemas import SchemaSet
from gen2.router.service import Router
from gen2.tests import children

TOPIC = "fleet:topic"
HASH = "sha256:" + "a" * 64
PIN = {"brief_id": "brief1", "version": 2, "content_hash": HASH}
ADMISSION = {"context": "pre-contract/1", "brief": PIN, "brief_confirmation_decision_id": "dec_aaaaaaaa"}
SCHEMAS = SchemaSet()


def observation(n, lane="semanticscholar", state="searched_ok"):
    return {"observation_id": f"obs_{n:08d}", "lane": lane, "coverage_state": state, "completeness": "complete",
            "result_count": 3, "error_class": None, "request": {"request": {"request_type": "find", "query": "q"}},
            "gateway_call_ref": f"call-{n}", "topic_id": TOPIC}


def records(**over):
    base = {"intake_briefs": [{**PIN, "document": {"objective_in_operator_words": "x"}}],
            "search_observations": [observation(1), observation(2, "crossref", "provider_unavailable")],
            "scoping_reports": []}
    return {**base, **over}


JUDGMENT = json.loads((Path(children.path("gen2/schema/examples/judgment-scope/valid-example.json"))).read_text())["instance"]


def work(recs=None, truncation=None, **over):
    view = views.scope_view(ADMISSION, recs or records(), ["semanticscholar"], "2026-11-05T12:00:00Z", truncation if truncation is not None else [])
    return {"invocation_id": "inv_aaaaaaaa", "topic_id": TOPIC, "view": view, **over}


class ViewsTest(unittest.TestCase):
    def test_reader_refusals(self):
        class Reader:
            def __init__(self, answer):
                self.answer = answer

            def topic_records(self, request):
                return self.answer
        ok = {"status": "ok", "topic_id": TOPIC, "records": {"a": [1], "b": []}}
        self.assertEqual(views.read_records(Reader(ok), TOPIC, ["a", "b"]), ok["records"])
        for case, answer in (("refused", {"status": "refused", "reason": "family_not_allowed"}),
                             ("other topic", {**ok, "topic_id": "fleet:other"}), ("family dropped", {**ok, "records": {"a": []}})):
            with self.subTest(case), self.assertRaises(common.Refused):
                views.read_records(Reader(answer), TOPIC, ["a", "b"])

    def test_truncation_is_recorded_and_keeps_the_latest(self):
        notes: list = []
        self.assertEqual(views.bounded("f", list(range(5)), notes, cap=2), [3, 4])
        self.assertEqual(notes, [{"family": "f", "kept": 2, "total": 5}])
        self.assertEqual(views.bounded("f", [1], notes, cap=2), [1])
        self.assertEqual(len(notes), 1)

    def test_scope_view_reads_the_pinned_brief_and_recorded_searches(self):
        view = work(records(scoping_reports=[{"report_id": "scope", "version": 3}, {"report_id": "scope", "version": 1}]))["view"]
        self.assertEqual(view["brief"], {**PIN, "document": {"objective_in_operator_words": "x"}})
        self.assertEqual(view["latest_report"], {"report_id": "scope", "version": 3})
        self.assertEqual([o["coverage_state"] for o in view["observations"]], ["searched_ok", "provider_unavailable"])
        self.assertNotIn("gateway_call_ref", view["observations"][0])

    def test_scope_view_refuses_without_exactly_the_pinned_brief_or_a_scoping_admission(self):
        other = {**PIN, "version": 1, "document": {}}
        for case, recs, admission in (("no brief", records(intake_briefs=[other]), ADMISSION),
                                      ("two briefs", records(intake_briefs=[records()["intake_briefs"][0]] * 2), ADMISSION),
                                      ("contract admission", records(), {"context": "contract/1"})):
            with self.subTest(case), self.assertRaises(common.Refused):
                views.scope_view(admission, recs, [], "2026-11-05T12:00:00Z", [])


class ScopeBuilderTest(unittest.TestCase):
    def test_report_passes_the_schema_and_the_routers_scoping_checks(self):
        w = work()
        report = scope.scoping_report(w, JUDGMENT)
        self.assertEqual(SCHEMAS.errors(report, "scoping-report.schema.json"), [])
        self.assertEqual(report["content_hash"], canonical.content_hash(report))
        self.assertEqual(report["brief"], PIN)
        self.assertLessEqual({g["facet_id"] for g in report["gap_map"]}, {f["facet_id"] for f in report["candidate_facets"]})
        self.assertEqual(report["coverage"], [{"lane": "crossref", "coverage_state": "provider_unavailable", "observation_ids": ["obs_00000002"]},
                                              {"lane": "semanticscholar", "coverage_state": "searched_ok", "observation_ids": ["obs_00000001"]}])
        self.assertEqual((report["report_id"], report["version"], report["parent_version"]), ("scope", 1, None))
        self.assertEqual(report["gap_map"][0]["note"], JUDGMENT["gap_skeleton"])

    def test_versions_chain_from_the_standing_report(self):
        report = scope.scoping_report(work(records(scoping_reports=[{"report_id": "scope-a", "version": 4}])), JUDGMENT)
        self.assertEqual((report["report_id"], report["version"], report["parent_version"]), ("scope-a", 5, 4))

    def test_mechanism_status_follows_recorded_coverage(self):
        for states, expected in ((["searched_empty"], "ran"), (["provider_unavailable", "not_searched"], "unavailable"),
                                 (["not_searched", "unknown"], "not_run"), ([], "not_run")):
            with self.subTest(states=states):
                recs = records(search_observations=[observation(n, state=s) for n, s in enumerate(states, 1)])
                report = scope.scoping_report(work(recs), JUDGMENT)
                self.assertEqual(report["discovery_mechanisms"][0], {"mechanism": "database_search", "status": expected})

    def test_a_replay_builds_identical_bytes(self):
        build = lambda: common.outcome_bytes(scope.build_scope(work(), {**copy.deepcopy(JUDGMENT), "search_proposals": []}))
        self.assertEqual(build(), build())

    def handoff(self, outcome):
        """The router's own decision for a scoping topic committing this outcome (service.py `_decide_effects`); it reads nothing of `self` on this path."""
        payload = {**outcome, "next_queue_state": None}
        lease = {"lease_id": "l1", "generation": 1}
        inv = {"kind": "research_pass", "admission_context": "pre-contract/1", "topic_id": TOPIC}
        return Router._decide_effects(SimpleNamespace(), True, inv, {"status": "scoping"}, payload, lease)[1]

    def test_pending_searches_commit_alone_and_the_topic_stays_scoping(self):
        forged = {**JUDGMENT["search_proposals"][0], "proposer": "forged"}
        outcome = scope.build_scope(work(), {**JUDGMENT, "search_proposals": [forged]})
        self.assertEqual(outcome["scoping_reports"], [])
        self.assertEqual([p["proposer"] for p in outcome["search_proposals"]], ["research_pass.scope"])
        self.assertEqual(SCHEMAS.errors(outcome["search_proposals"][0], "search-proposal.schema.json"), [])
        self.assertIsNone(self.handoff(outcome))

    def test_no_pending_searches_commit_one_report_and_hand_off_to_the_operator(self):
        outcome = scope.build_scope(work(), {**JUDGMENT, "search_proposals": []})
        self.assertEqual((len(outcome["scoping_reports"]), "search_proposals" in outcome), (1, False))
        self.assertEqual(SCHEMAS.errors(outcome, "outcome-document.schema.json"), [])
        self.assertEqual(self.handoff(outcome), {"from": "scoping", "to": "awaiting_scope_approval"})

    def test_a_proposal_only_pass_needs_no_report_fields(self):
        outcome = scope.build_scope(work(), {**JUDGMENT, "traditions": [], "candidate_facets": []})
        self.assertEqual((outcome["scoping_reports"], len(outcome["search_proposals"])), ([], 1))

    def test_a_report_without_traditions_or_facets_is_refused(self):
        for key in ("traditions", "candidate_facets"):
            with self.subTest(key), self.assertRaises(common.Refused):
                scope.build_scope(work(), {**JUDGMENT, "search_proposals": [], key: []})


class Exchanges:
    def __init__(self, staged):
        self.staged = staged

    def response(self, ref):
        return self.staged.get(ref)


def staged(data=b"response bytes", lie=False):
    digest = canonical.bytes_digest(b"other" if lie else data)
    return ({"content_hash": digest, "size_bytes": len(data), "media_type": "application/json"}, data)


def lineage(**over):
    base = {"retrieval_events": [{"event_id": "e1", "observation_id": "obs_00000001", "captured_at": "2026-11-05T11:00:00Z"},
                                 {"event_id": "e2", "observation_id": "obs_00000002", "captured_at": "2026-11-05T11:05:00Z"}],
            "record_work_links": [{"event_id": "e1", "work_id": "wrk_aaaaaaaa"}, {"event_id": "e2", "work_id": "wrk_aaaaaaaa"}],
            "search_observations": [observation(1), observation(2)]}
    return {**base, **over}


class ArtifactsTest(unittest.TestCase):
    def test_text_ref_is_the_staged_bytes_own(self):
        text = "claim é"
        data = text.encode()
        good = lambda b, media: {"content_hash": canonical.bytes_digest(b), "size_bytes": len(b), "media_type": media}
        self.assertEqual(artifacts.text_ref(good, text)["content_hash"], "sha256:" + hashlib.sha256(data).hexdigest())
        for case, stage in (("wrong hash", lambda b, m: {**good(b, m), "content_hash": HASH}),
                            ("wrong size", lambda b, m: {**good(b, m), "size_bytes": 1})):
            with self.subTest(case), self.assertRaises(common.Refused):
                artifacts.text_ref(stage, text)

    def test_record_binds_the_earliest_staged_retained_response(self):
        ref, data = staged(b"second")
        first = staged(b"first")
        found = artifacts.source_artifacts(["wrk_aaaaaaaa"], lineage(), Exchanges({"call-1": first, "call-2": (ref, data)}))
        self.assertEqual(found, [{"work_id": "wrk_aaaaaaaa", "source_version": first[0]["content_hash"], "artifact_ref": first[0]}])
        self.assertEqual(SCHEMAS.errors(found[0], "source-artifact.schema.json"), [])
        later = artifacts.source_artifacts(["wrk_aaaaaaaa"], lineage(), Exchanges({"call-2": (ref, data)}))
        self.assertEqual(later[0]["artifact_ref"], ref)

    def test_nothing_is_invented_for_a_source_without_lineage_or_bytes(self):
        good = {"call-1": staged()}
        for case, work_id, recs, exchanges in (
                ("never retrieved", "wrk_bbbbbbbb", lineage(), good),
                ("link outside the topic's events", "wrk_aaaaaaaa", lineage(retrieval_events=[]), good),
                ("no staged exchange", "wrk_aaaaaaaa", lineage(), {}),
                ("bytes differ from the reference", "wrk_aaaaaaaa", lineage(), {"call-1": staged(lie=True)})):
            with self.subTest(case), self.assertRaises(common.Refused):
                artifacts.source_artifacts([work_id], recs, Exchanges(exchanges))


class PromptTest(unittest.TestCase):
    path = Path(children.path("gen2/prompts/research_pass.scope.md"))

    def test_the_mounted_file_is_pinnable_under_its_name(self):
        spec = importlib.util.spec_from_file_location("pins", children.path("tools/gen2_prompt_pins.py"))
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        pinned = {(p["kind"], p["purpose"]): p["prompt"]["content_hash"] for p in tool.pins(self.path.parent, 1)}
        self.assertEqual(pinned[("research_pass", "scope")], "sha256:" + hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_its_example_is_a_valid_judgment(self):
        block = re.search(r"```json\n(.*?)\n```", self.path.read_text(), re.S).group(1)
        self.assertEqual(SCHEMAS.errors(json.loads(block), "judgment-scope.schema.json"), [])
