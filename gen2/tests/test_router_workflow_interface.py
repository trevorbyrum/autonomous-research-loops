"""C-10/C-12/F3: trusted workflow interfaces; row/hash oracles, no real executors."""
import base64
import copy
import json
from unittest.mock import patch

from gen2.router import boundary
from gen2.store.capture import input_hash
from gen2.tests import router_fixtures as rf
from gen2.tests.test_dossier_record import FixtureEvaluator
from gen2.tests import test_router_registries as bundle_tests

FAMILIES = """claim_source_links obligation_assessments source_acquisitions source_artifacts
retrieval_events search_observations record_work_links works facets obligations contract_revisions
claims verification_receipts detailed_check_records completion_records registry_dispositions intake_briefs scoping_reports dossiers
operation_receipts quote_checks""".split()
PROPOSAL = {"proposal_version": "search-proposal/1", "proposal_id": "search-1", "proposer": "primary",
    "lane": "crossref", "request_type": "find", "query": "omissions", "page_cap": 1,
    "obligation_ids": ["O-1"], "rationale": "Test the open obligation"}


class InterfaceTests(FixtureEvaluator, rf.ContractWorld):
    refused = rf.ContractWorld.refused_command
    capture = rf.Workflow.capture
    refused_commit = rf.Workflow.refused_commit

    def dossier_request(self, iid="inv_interface01"):
        grant = self.started(iid, "checkpoint")
        return {**{k: grant[k] for k in ("capability_id", "invocation_id")}, "topic_id": rf.TOPIC}

    def test_dossier_replay_is_original_after_later_revision_and_expiry(self):
        """C-10: persisted revision/hash and whole-store equality; fixture evaluator, no sufficiency proof."""
        req = self.dossier_request()
        first = self.router.record_dossier(req)
        self.assertEqual((first["status"], first["dossier_revision"]), ("recorded", 1))
        self.assertEqual(first["content_hash"], self.value("SELECT content_hash FROM dossiers WHERE dossier_revision=1"))
        self.assertEqual(self.finish(self.claim(req["invocation_id"], "checkpoint"), "op_interface01")["status"], "committed")
        second = self.router.record_dossier(self.dossier_request("inv_interface02"))
        self.assertEqual(second["dossier_revision"], 2)
        read = self.router.topic_records({"topic_id": rf.TOPIC, "families": ["dossiers"], "dossier_revision": 1})
        self.assertEqual(read["records"]["dossiers"][0]["content_hash"], first["content_hash"])
        self.clock.set("2027-01-01T00:00:00Z")
        before = self.state()
        with patch.object(self.router, "_evaluate", side_effect=AssertionError("replay evaluated")):
            self.assertEqual(self.router.record_dossier(req), {**first, "status": "replayed"})
        self.assertEqual(self.state(), before)

    def test_dossier_authority_and_atomic_failure(self):
        """Checkpoint identity, current lease and running state fence new rows; all-table equality, no runner."""
        req = self.dossier_request()
        other = self.started("inv_research01")
        for bad, reason in (({**req, "topic_id": rf.OTHER}, "cross_topic"),
                            ({**req, "capability_id": "cap_missing000"}, "capability_invalid"),
                            ({**req, "invocation_id": other["invocation_id"]}, "capability_invocation_mismatch"),
                            ({**{k: other[k] for k in ("capability_id", "invocation_id")}, "topic_id": rf.TOPIC}, "kind_not_permitted"),
                            ({**req, "history": "legacy_unknown"}, "request_invalid")):
            self.refused("record_dossier", bad, reason)
        with patch.object(self.router, "_store", rf.Refusing(self.store, 0)):
            self.refused("record_dossier", req, "payload_invalid")
        self.clock.set("2027-01-01T00:00:00Z")
        self.refused("record_dossier", req, "lease_not_current")
        self.clock.set(rf.STAMP)
        self.router.request_cancel({"invocation_id": req["invocation_id"], "requested_by": "operator", "reason": "stop"})
        self.refused("record_dossier", req, "cancel_requested")

    def test_dossier_race_replays_the_same_invocation(self):
        """C-10 freshness retry finds the winner instead of a second revision; local nested writer, no threads."""
        req = self.dossier_request()
        evaluate = self.router._evaluate
        def race(inputs, spool, as_of):
            with patch.object(self.router, "_evaluate", side_effect=evaluate):
                self.assertEqual(self.router.record_dossier(req)["status"], "recorded")
            return evaluate(inputs, spool, as_of)
        with patch.object(self.router, "_evaluate", side_effect=race):
            out = self.router.record_dossier(req)
        self.assertEqual((out["status"], out["dossier_revision"]), ("replayed", 1))
        self.assertEqual(self.value("SELECT count(*) FROM dossiers"), 1)

    def test_topic_snapshot_scope_body_and_hash_stability(self):
        """F3: explicit families, SQL-scoped work lineage and exact persisted body; no input builder claim."""
        req = self.dossier_request()
        self.router.record_dossier(req)
        grant = self.started("inv_research01")
        events = rf.Workflow.observe(self, grant, "obs_interface01", ("record-1",))
        work = rf.Workflow.register(self, grant, [("doi", "10.1/visible", events)])["works"][0]["work_id"]
        before, digest = self.state(), input_hash(self.store.capture_topic(rf.TOPIC), "native")
        select_rows = self.store.select
        def checked_select(*args, **kwargs):
            self.assertTrue(self.db.in_transaction)
            return select_rows(*args, **kwargs)
        with patch.object(self.store, "select", side_effect=checked_select) as select:
            out = self.router.topic_records({"topic_id": rf.TOPIC, "families": FAMILIES, "dossier_revision": 1})
        self.assertEqual(out["status"], "ok", out)
        self.assertEqual(set(out["records"]), set(FAMILIES))
        self.assertEqual([r["work_id"] for r in out["records"]["works"]], [work])
        self.assertEqual([r["event_id"] for r in out["records"]["record_work_links"]], events)
        self.assertEqual(out["records"]["dossiers"][0]["document"], json.loads(self.value("SELECT document FROM dossiers WHERE dossier_revision=1")))
        self.assertEqual(out["records"]["intake_briefs"][0]["document"], json.loads(self.value("SELECT document FROM intake_briefs LIMIT 1")))
        self.assertTrue(out["records"]["facets"] and out["records"]["obligations"])
        self.assertTrue(all(call.args[1] for call in select.call_args_list))
        self.assertEqual(input_hash(self.store.capture_topic(rf.TOPIC), "native"), digest)
        self.assertEqual(self.state(), before)
        out["records"]["dossiers"][0]["document"].clear()
        self.assertTrue(json.loads(self.value("SELECT document FROM dossiers WHERE dossier_revision=1")))

    def test_topic_read_refusals(self):
        """Fixed selectors refuse unknown family/topic/revision; whole-store equality, no arbitrary query API."""
        base = {"topic_id": rf.TOPIC, "families": ["claims"]}
        for req, reason in (({**base, "families": ["audit_events"]}, "request_invalid"),
                            ({**base, "families": ["claims", "claims"]}, "request_invalid"),
                            ({**base, "where": {}}, "request_invalid"),
                            ({**base, "topic_id": "fleet-a:missing"}, "unknown_topic"),
                            ({**base, "families": ["dossiers"]}, "request_invalid"),
                            ({**base, "families": ["dossiers"], "dossier_revision": 99}, "unknown_dossier")):
            self.refused("topic_records", req, reason)

    def test_validated_only_proposals_commit_and_replay(self):
        """P6/F3: literal final receipt and payload survive topic-scoped reads/replay; no discovery sends."""
        grant = self.started("inv_proposals01")
        payload = {**rf.empty_outcome(grant["invocation_id"]), "search_proposals": [PROPOSAL]}
        env = self.envelope(grant, "op_proposals01", payload)
        self.ready(grant, env["payload_digest"])
        env["expected_state_revision"] = self.state_revision(rf.TOPIC)
        self.assertEqual(self.router.commit_outcome(env)["status"], "committed")
        self.assertEqual(self.value("SELECT payload_digest FROM operation_receipts WHERE operation_id=?", env["operation_id"]), env["payload_digest"])
        self.assertEqual([(r["operation_kind"], r["invocation_id"]) for r in self.router.topic_records({"topic_id": rf.TOPIC, "families": ["operation_receipts"]})["records"]["operation_receipts"]],
                         [("final_outcome", grant["invocation_id"])])
        self.assertEqual(self.router.topic_records({"topic_id": rf.OTHER, "families": ["operation_receipts"]})["records"]["operation_receipts"], [])
        self.assertEqual(json.loads(self.spool.read(env["payload_digest"], topic_id=rf.TOPIC))["search_proposals"], [PROPOSAL])
        before = self.state()
        self.assertEqual(self.router.commit_outcome(env)["status"], "replayed")
        self.assertEqual(self.state(), before)

    def test_proposal_kind_context_and_shape(self):
        """C-12: literal permission table and malformed-proposal refusals; structural checks, no scientific judgment."""
        for context in ("pre-contract/1", "contract/1"):
            for kind in ("research_pass", "checkpoint", "verification", "discovery", "delegate"):
                if kind in ("research_pass", "checkpoint"):
                    boundary.check_sections({"search_proposals": [PROPOSAL]}, kind, context, None)
                else:
                    with self.assertRaises(boundary.Refusal):
                        boundary.check_sections({"search_proposals": [PROPOSAL]}, kind, context, None)
        verifier = self.started("inv_verifier01", "verification")
        self.refused_commit(verifier, "op_proposals02", "kind_not_permitted", "search_proposals", search_proposals=[PROPOSAL])
        grant = self.started("inv_research01")
        for proposals in ([{**PROPOSAL, "page_cap": 0}], [PROPOSAL] * 33):
            self.refused_commit(grant, "op_proposals03", "payload_invalid", "search_proposals", search_proposals=proposals)


class ExecutorTests(rf.RouterTestCase):
    activate = bundle_tests.ConfigBundleTest.activate
    refused = bundle_tests.ConfigBundleTest.refused

    def test_executor_pin_shape_limits_and_duplicate_keys(self):
        """G-10: helper-shaped pins plus explicit bounds; schema/bundle readbacks, no prompt mounting or launcher."""
        pin = {"kind": "research_pass", "purpose": "scope", "prompt": {"version": 1, "content_hash": rf.h("a")}}
        entry = {**pin, "deadline_s": 120, "lease_s": 180, "max_input_bytes": 4096, "max_output_bytes": 8192}
        doc = {**rf.BUNDLE, "version": 2, "policy": {"executors": [entry]}}
        for field, bad in (("deadline_s", 0), ("lease_s", None), ("max_input_bytes", True),
                           ("max_output_bytes", 0), ("max_passes", 0), ("prompt", {"version": 1, "content_hash": "tag"})):
            wrong = copy.deepcopy(doc)
            wrong["policy"]["executors"][0][field] = bad
            self.refused(wrong, "bundle_invalid", field)
        self.refused({**doc, "policy": {"executors": [entry, entry]}}, "bundle_invalid", "appears twice")
        self.refused({**doc, "policy": {"executors": [pin]}}, "bundle_invalid", "required")
        out = self.activate(doc)
        self.assertEqual(out["status"], "activated", out)
        self.assertEqual(self.router.config_bundle(out["bundle_hash"])["policy"]["executors"], [entry])
        self.assertNotIn("executors", self.router.config_bundle(rf.CONFIG)["policy"])
        changed = copy.deepcopy(doc)
        changed["version"] = 3
        changed["policy"]["executors"][0]["prompt"]["content_hash"] = rf.h("b")
        self.assertEqual(self.activate(changed)["status"], "activated")


class ScopingTests(rf.Workflow):
    def test_scoping_view_reads_topic_bodies_without_changing_dossier_hashes(self):
        """T14/F3: two topics' persisted report/brief bodies and capture hashes; no executor-input assembly."""
        reports = {}
        for topic in (rf.TOPIC, rf.OTHER):
            self.to_scoping(topic)
            reports[topic] = self.scoped(topic)
        before = self.state()
        for topic, report in reports.items():
            raw = self.store.capture_topic(topic)
            out = self.router.topic_records({"topic_id": topic, "families": ["scoping_reports", "intake_briefs"]})
            self.assertEqual(out["status"], "ok", out)
            self.assertEqual([(r["topic_id"], r["document"]) for r in out["records"]["scoping_reports"]], [(topic, report)])
            brief = json.loads(self.value("SELECT document FROM intake_briefs WHERE topic_id=?", topic))
            self.assertEqual([(r["topic_id"], r["document"]) for r in out["records"]["intake_briefs"]], [(topic, brief)])
            self.assertNotIn("scoping_reports", {t.name for t in raw.tables})
            self.assertEqual(input_hash(self.store.capture_topic(topic), "native"), input_hash(raw, "native"))
        self.assertEqual(self.state(), before)

    def test_proposal_only_pass_keeps_scoping_and_has_no_ordinal(self):
        """P6/P10: pre-contract final commit retains proposals; SQL state/ordinal oracle, no discovery job."""
        self.to_scoping()
        grant = self.started("inv_scopeprop01")
        out = self.finish(grant, "op_scopeprop01", {**rf.empty_outcome(grant["invocation_id"]), "search_proposals": [PROPOSAL]})
        self.assertEqual(out["status"], "committed", out)
        self.assertEqual(self.rows("SELECT status FROM queue_entries WHERE topic_id=?", rf.TOPIC), [("scoping",)])
        self.assertEqual(self.value("SELECT count(*) FROM research_ordinals"), 0)


class AcquisitionReadTests(rf.AcquisitionCase):
    def test_binary_retained_exchanges_are_lossless_json_cells(self):
        """F3/ControlBackend: admitted bytes survive the JSON read contract; real Router, fixture exchange only."""
        self.assertEqual(self.router.admit_reaccess(self.request())["status"], "admitted")
        before = self.state()
        out = self.router.topic_records({"topic_id": rf.TOPIC, "families": ["source_acquisitions"]})
        row = json.loads(json.dumps(out))["records"]["source_acquisitions"][0]
        for column, expected in (("request_bytes", rf.REQUEST), ("response_bytes", self.raw)):
            self.assertEqual(row[column]["encoding"], "base64")
            self.assertEqual(base64.b64decode(row[column]["data"], validate=True), expected)
        self.assertEqual(self.state(), before)
