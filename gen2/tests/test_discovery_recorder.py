"""gen2/discovery recorder and exchanges. Oracles: the router's acquisition check (`reaccess.check_reaccess`) applied to the
staged bytes, hashlib/canonical digests recomputed from what the real spool holds, and the router's reply vocabulary. The
router is a recording double here (its own replay rules are tested in test_router_*); what this proves is the order, the
replay and the refusals of the recorder. Limits: the staged response is a canonical reconstruction of the client's parsed
exchange, not raw transport octets, and these tests say so rather than check octets."""
import json
import tempfile
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.core.control import ControlUnavailable
from gen2.discovery import child, exchanges, recorder
from gen2.exec.common import Refused
from gen2.router import reaccess
from gen2.supervisor.spool import Spool
from gen2.tests.test_discovery_child import ABSTRACT, INV, TOPIC, Fixture, proposal

ORDER = {"invocation_id": INV, "topic_id": TOPIC}
GRANT = {"capability_id": "cap_aaaaaaaa", "invocation_id": INV}


class Control:
    """A router double: records every call in order, acknowledges it as recorded, then as replayed."""
    def __init__(self, log, refuse=None, lose=None):
        self.log, self.refuse, self.lose, self.seen = log, refuse, lose, set()

    def _call(self, method, request):
        self.log.append((method, request))
        if self.lose == len(self.log):
            self.lose = None
            raise ControlUnavailable("reply lost")
        if method == self.refuse:
            return {"status": "refused", "reason": "request_invalid"}
        key = (method, json.dumps(request, sort_keys=True))
        status = "replayed" if key in self.seen else "recorded"
        self.seen.add(key)
        return {"status": status}

    def record_gateway_facts(self, request):
        return self._call("record_gateway_facts", request)

    def record_observation(self, request):
        return self._call("record_observation", request)

    def register_works(self, request):
        return self._call("register_works", request)


class RecorderTest(Fixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.spool_dir = tempfile.TemporaryDirectory()
        self.spool = Spool(self.spool_dir.name)
        self.log = []

    def tearDown(self):
        self.spool_dir.cleanup()
        super().tearDown()

    def staged_events(self):
        original = self.spool.stage
        def stage(topic, data, media):
            self.log.append(("stage", media))
            return original(topic, data, media)
        return stage

    def produce(self, proposals=None):
        self.run_child(self.stage(proposals or [proposal(1), proposal(2, lane="doaj")]))

    def record(self, control=None):
        recorder.recorder(self.staged_events())(control or Control(self.log), ORDER, GRANT, self.root)

    def test_router_acks_come_first_then_the_retained_exchanges_then_the_works(self):
        self.produce()
        self.record()
        methods = [entry[0] for entry in self.log]
        self.assertEqual(methods, ["record_observation", "record_observation", "stage", "stage", "stage", "stage", "register_works"])
        observation = self.log[0][1]
        self.assertEqual((observation["capability_id"], observation["invocation_id"]), ("cap_aaaaaaaa", INV))
        (works,) = [r["works"] for m, r in self.log if m == "register_works"]
        self.assertEqual(works, [{"identity_scheme": "doi", "identity_value": "10.1/a",
                                  "event_ids": sorted({e["event_id"] for m, r in self.log if m == "record_observation" for e in r["retrieval_events"]})}])

    def test_a_replay_repeats_every_request_and_adds_nothing(self):
        self.produce()
        control = Control(self.log)
        self.record(control)
        index = (self.root / "exchanges.json").read_bytes()
        first = list(self.log)
        self.log.clear()
        self.record(control)
        self.assertEqual([(m, r) for m, r in self.log if m != "stage"], [(m, r) for m, r in first if m != "stage"])
        self.assertEqual((self.root / "exchanges.json").read_bytes(), index)

    def test_a_lost_reply_is_retried_whole_with_the_same_requests(self):
        self.produce()
        control = Control(self.log, lose=2)
        with self.assertRaises(ControlUnavailable):
            self.record(control)
        before = list(self.log)
        self.record(control)
        self.assertEqual(self.log[len(before):][:len(before)], before, "the retry sends the same requests, in order")

    def test_without_the_routers_ack_nothing_goes_on(self):
        self.produce()
        with self.assertRaises(Refused):
            self.record(Control(self.log, refuse="record_observation"))
        self.assertEqual([m for m, _ in self.log], ["record_observation"])
        self.assertFalse((self.root / "exchanges.json").exists())
        sent = self.log[0][1]["observation"]
        self.assertEqual((sent["coverage_state"], sent["completeness"]), ("searched_ok", "complete"), "the historical coverage is what the gateway said")

    def test_a_result_for_another_invocation_is_refused(self):
        self.produce()
        with self.assertRaises(Refused):
            recorder.recorder(self.spool.stage)(Control(self.log), {**ORDER, "invocation_id": "inv_other0001"}, GRANT, self.root)
        self.assertEqual(self.log, [])

    def test_the_staged_response_passes_the_routers_acquisition_check_and_says_what_it_is(self):
        self.produce([proposal(1)])
        self.record()
        index = ExchangeIndex(self)
        out = canonical.parse_json_strict((self.root / "discovery-result.json").read_bytes())["searches"][0]["out"]
        observation, events = out["observations"][0]["observation"], out["observations"][0]["retrieval_events"]
        found = index.read(topic_id=TOPIC, invocation_id=INV, attempt=1, gateway_call_ref=observation["gateway_call_ref"])
        digest = canonical.bytes_digest(found.response_bytes)
        row = {**observation, "topic_id": TOPIC, "invocation_id": INV}
        acquired = reaccess.check_reaccess(
            source={"topic_id": TOPIC, "work_id": "wrk_aaaaaaaa", "source_version": digest, "content_hash": digest},
            artifact={"content_hash": digest, "size_bytes": len(found.response_bytes), "media_type": "application/json"},
            observation=row, event={**events[0], "topic_id": TOPIC, "observation_id": observation["observation_id"]},
            link={"event_id": events[0]["event_id"], "work_id": "wrk_aaaaaaaa"}, raw=found.response_bytes)
        self.assertEqual((acquired.gateway_call_ref, acquired.provider_record_id), (observation["gateway_call_ref"], "doi:10.1/a"))
        self.assertEqual(found.request_bytes, canonical.canonical_bytes(observation["request"]))
        document = canonical.parse_json_strict(found.response_bytes)
        self.assertIn("not the raw transport octets", document["retained_form"])
        self.assertEqual([r.get("abstract") for r in document["records"]], [ABSTRACT], "the full parsed record, abstract included")
        with self.assertRaises(reaccess.ReaccessRefused):
            reaccess.check_reaccess(source={"topic_id": TOPIC, "work_id": "wrk_aaaaaaaa", "source_version": digest, "content_hash": digest},
                                    artifact={"content_hash": digest, "size_bytes": 1, "media_type": "application/json"},
                                    observation=row, event={**events[0], "topic_id": TOPIC, "observation_id": observation["observation_id"]},
                                    link={"event_id": events[0]["event_id"], "work_id": "wrk_aaaaaaaa"}, raw=found.response_bytes)

    def test_the_index_reads_back_only_verified_bytes(self):
        self.produce([proposal(1)])
        self.record()
        index = ExchangeIndex(self)
        call = json.loads((self.root / "exchanges.json").read_text())["exchanges"][0]
        ref, data = index.response(call["gateway_call_ref"])
        self.assertEqual(canonical.bytes_digest(data), ref["content_hash"])
        self.assertIsNone(index.response("gw-call:999999"))
        for name, kwargs in (("invocation", {"invocation_id": "inv_other0001", "attempt": 1}), ("attempt", {"invocation_id": INV, "attempt": 2}),
                             ("topic", {"invocation_id": INV, "attempt": 1, "topic_id": "fleet:other"})):
            with self.subTest(name):
                self.assertIsNone(index.read(**{"topic_id": TOPIC, "gateway_call_ref": call["gateway_call_ref"], **kwargs}))
        # bytes in the spool that are not the reference's are never returned
        tampered = ExchangeIndex(self)
        tampered._spool = type("Bad", (), {"read": staticmethod(lambda h, topic_id: b"other bytes")})()
        self.assertIsNone(tampered.response(call["gateway_call_ref"]))
        self.assertIsNone(tampered.read(topic_id=TOPIC, invocation_id=INV, attempt=1, gateway_call_ref=call["gateway_call_ref"]))


try:
    from gen2.exec import views
    from gen2.tests import test_exec_research as research_fixtures
except ImportError:   # T14 PR3 (#119) is not in this tree yet; the witness runs once it is
    views = research_fixtures = None


@unittest.skipIf(views is None, "gen2.exec.views (T14 PR3) is not merged yet")
class ResearchViewWitness(Fixture, unittest.TestCase):
    """An adapter-shaped page whose record carries an abstract: recorded, staged, indexed, and seen by the research view."""
    def setUp(self):
        super().setUp()
        self.spool_dir = tempfile.TemporaryDirectory()
        self.spool = Spool(self.spool_dir.name)

    def tearDown(self):
        self.spool_dir.cleanup()
        super().tearDown()

    def test_the_view_shows_the_abstract_the_recorder_staged(self):
        self.run_child(self.stage([proposal(1)]))
        log = []
        recorder.recorder(self.spool.stage)(Control(log), ORDER, GRANT, self.root)
        observation = next(r["observation"] for m, r in log if m == "record_observation")
        events = next(r["retrieval_events"] for m, r in log if m == "record_observation")
        records = research_fixtures.records(
            retrieval_events=[{**e, "observation_id": observation["observation_id"], "captured_at": "2026-11-05T11:00:00Z"} for e in events],
            record_work_links=[{"event_id": events[0]["event_id"], "work_id": "wrk_aaaaaaaa"}], search_observations=[{**observation, "invocation_id": INV}],
            works=[{"work_id": "wrk_aaaaaaaa", "identity_scheme": "doi", "identity_value": "10.1/a"}])
        view = views.research_view(research_fixtures.ADMISSION, records, ExchangeIndex(self), lambda ref: None, "2026-11-05T12:00:00Z", 1, [])
        ref = ExchangeIndex(self).response(observation["gateway_call_ref"])[0]
        self.assertEqual(view["works"], [{"work_id": "wrk_aaaaaaaa", "identity": "doi:10.1/a", "abstract": ABSTRACT, "artifact_ref": ref, "lane": "crossref", "provider_record_id": "doi:10.1/a"}])


def ExchangeIndex(case):
    return exchanges.ExchangeIndex(case.spool, TOPIC, lambda: [case.root])


class PureTest(unittest.TestCase):
    def test_a_call_the_gateway_did_not_capture_has_no_exchange(self):
        page = {"page": 1, "sent": {"request_type": "find", "lanes": ["crossref"]}, "effective_request": None, "call_ref": None}
        result = {"invocation_id": INV, "attempt": 1, "searches": [{"proposal_id": "p1", "out": {"pages": [page], "observations": []}}]}
        self.assertEqual(exchanges.build(result), {})

    def test_work_identity_table(self):
        for record_id, expected in (("doi:10.1/a", ("doi", "10.1/a")), ("arxiv:2101.00001", ("arxiv", "2101.00001")),
                                    ("s2:abc", ("gateway_record", "s2:abc")), ("doi:", ("gateway_record", "doi:")), ("plain", ("gateway_record", "plain"))):
            with self.subTest(record_id):
                self.assertEqual(recorder.work_identity(record_id), expected)
