"""Literal fixture lineage oracles; no Router admission or live gateway calls.

Each negative changes one relationship and asserts its specific refusal.
Changed response fixtures get independently rehashed so digest validation
cannot mask a missing capture/record guard (2d-4 part 1 C1).
"""
import copy
import hashlib
import json
import unittest
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

from gen2.router import reaccess

RAW = b'{"request_type":"resolve","observation":{"captured":true,"call_ref":101,"invocation_id":"inv_producer01","attempt":1},"lanes":[{"source":"crossref","coverage":"searched_ok","completeness":"complete","retrieved":["doi:10.1/test"]}],"records":[{"identity":"doi:10.1/test","kind":"article","source_id":"crossref","title":"A fixture","abstract":"An abstract"}]}'
REQUEST = {"lane": "crossref", "page": 1, "request": {"request_type": "resolve", "identity": "doi:10.1/test"}}
REQUEST_BYTES = b'{"lane":"crossref","page":1,"request":{"identity":"doi:10.1/test","request_type":"resolve"}}'


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class ReaccessTest(unittest.TestCase):
    def setUp(self):
        self.args = {"raw": RAW,
            "source": {"topic_id": "fleet-a:t1", "work_id": "wrk_test0001", "source_version": "v1", "content_hash": digest(RAW)},
            "artifact": {"content_hash": digest(RAW), "size_bytes": len(RAW), "media_type": "application/json"},
            "observation": {"observation_id": "obs_test0001", "topic_id": "fleet-a:t1", "invocation_id": "inv_producer01", "attempt": 1,
                "gateway_call_ref": "gw-call:101", "coverage_state": "searched_ok", "completeness": "complete",
                "lane": "crossref", "request": copy.deepcopy(REQUEST), "request_identity": digest(REQUEST_BYTES)},
            "event": {"event_id": "rev_test0001", "observation_id": "obs_test0001", "topic_id": "fleet-a:t1",
                "provider_record_id": "doi:10.1/test", "captured_at": "2026-10-11T00:00:00Z"},
            "link": {"event_id": "rev_test0001", "work_id": "wrk_test0001"}}

    def response(self, change):
        doc = json.loads(self.args["raw"])
        change(doc)
        raw = json.dumps(doc, separators=(",", ":")).encode()
        self.bytes(raw)

    def bytes(self, raw):
        self.args["raw"] = raw
        self.args["source"]["content_hash"] = digest(raw)
        self.args["artifact"].update(content_hash=digest(raw), size_bytes=len(raw))

    def refused(self, reason):
        before = copy.deepcopy(self.args)
        with self.assertRaises(Exception) as caught:
            reaccess.check_reaccess(**self.args)
        self.assertIsInstance(caught.exception, reaccess.ReaccessRefused)
        self.assertEqual(str(caught.exception), reason)
        self.assertEqual(self.args, before)

    def test_producer_bytes_control(self):
        before = copy.deepcopy(self.args)
        acquired = reaccess.check_reaccess(**self.args)
        self.assertEqual(asdict(acquired), {"topic_id": "fleet-a:t1", "work_id": "wrk_test0001", "source_version": "v1",
            "content_hash": digest(RAW), "observation_id": "obs_test0001", "event_id": "rev_test0001", "gateway_call_ref": "gw-call:101",
            "acquired_by_invocation_id": "inv_producer01", "attempt": 1, "lane": "crossref", "request_type": "resolve",
            "provider_record_id": "doi:10.1/test", "retrieved_at": "2026-10-11T00:00:00Z"})
        self.assertEqual(self.args, before)
        with self.assertRaises(FrozenInstanceError):
            acquired.lane = "abstract"

    def test_other_acquirer_control(self):
        self.args["observation"]["invocation_id"] = "inv_other0001"
        self.response(lambda d: d["observation"].update(invocation_id="inv_other0001"))
        self.assertEqual(reaccess.check_reaccess(**self.args).acquired_by_invocation_id, "inv_other0001")

    def test_partial_control(self):
        self.args["observation"]["completeness"] = "partial"
        self.response(lambda d: d["lanes"][0].update(completeness="partial"))
        self.assertEqual(reaccess.check_reaccess(**self.args).provider_record_id, "doi:10.1/test")

    def test_recorded_gateway_fixture(self):
        path = Path(__file__).parent / "fixtures/gateway_answers/find_complete.json"
        response = json.loads(path.read_text())["exchanges"][0]["response"]["body"]
        self.bytes(json.dumps(response, separators=(",", ":")).encode())
        request = {"lane": "crossref", "page": 1, "request": {"request_type": "find", "query": "reranking"}}
        self.args["observation"].update(invocation_id="inv_fixture0001", request=request,
            request_identity=digest(b'{"lane":"crossref","page":1,"request":{"query":"reranking","request_type":"find"}}'))
        self.args["event"]["provider_record_id"] = "doi:10.1234/abc"
        acquired = reaccess.check_reaccess(**self.args)
        self.assertEqual((acquired.acquired_by_invocation_id, acquired.gateway_call_ref, acquired.lane,
            acquired.request_type, acquired.provider_record_id), ("inv_fixture0001", "gw-call:101", "crossref", "find", "doi:10.1234/abc"))

    def test_topic(self):
        for row in ("source", "observation", "event"):
            with self.subTest(row=row):
                self.args[row]["topic_id"] = "fleet-a:t2"
                self.refused("acquisition topic")
                self.args[row]["topic_id"] = "fleet-a:t1"

    def test_work(self):
        self.args["link"]["work_id"] = "wrk_other0001"
        self.refused("acquisition work")

    def test_work_link(self):
        self.args["link"]["event_id"] = "rev_other001"
        self.refused("acquisition work link")

    def test_observation(self):
        self.args["event"]["observation_id"] = "obs_other001"
        self.refused("acquisition observation")

    def test_source_identity(self):
        self.args["source"]["content_hash"] = "sha256:" + "0" * 64
        self.refused("source artifact identity")

    def test_bytes_digest(self):
        self.args["raw"] = RAW.replace(b"A fixture", b"A forgery")
        self.refused("acquisition bytes digest")

    def test_bytes_size(self):
        self.args["artifact"]["size_bytes"] += 1
        self.refused("acquisition bytes size")

    def test_media(self):
        self.args["artifact"]["media_type"] = "text/plain"
        self.refused("canonical gateway media type")

    def test_unobserved(self):
        self.args["observation"]["coverage_state"] = "unknown"
        self.response(lambda d: d["lanes"][0].update(coverage="unknown"))
        self.refused("observed acquisition")

    def test_completeness(self):
        self.args["observation"]["completeness"] = "unobserved"
        self.response(lambda d: d["lanes"][0].update(completeness="unobserved"))
        self.refused("observed acquisition")

    def test_request_identity(self):
        self.args["observation"]["request_identity"] = "sha256:" + "0" * 64
        self.refused("attempted request identity")

    def test_request_lane(self):
        self.args["observation"]["lane"] = "core"
        self.response(lambda d: d["lanes"][0].update(source="core"))
        self.refused("recorded request lane")

    def test_request_type(self):
        self.args["observation"]["request"]["request"]["request_type"] = "abstract-only"
        self.args["observation"]["request_identity"] = digest(REQUEST_BYTES.replace(b"resolve", b"abstract-only"))
        self.response(lambda d: d.update(request_type="abstract-only"))
        self.refused("recorded request type")

    def test_summary(self):
        self.bytes(b'{"summary":"producer-selected summary"}')
        self.refused("gateway capture missing")

    def test_json(self):
        self.bytes(RAW[:-1] + b',"extra":1,"extra":1}')
        self.refused("canonical gateway JSON")

    def test_envelope(self):
        self.bytes(b'[]')
        self.refused("canonical gateway envelope")

    def test_capture(self):
        self.response(lambda d: d["observation"].update(captured=False))
        self.refused("gateway capture unacknowledged")

    def test_call_type(self):
        self.args["observation"]["gateway_call_ref"] = "gw-call:True"
        self.response(lambda d: d["observation"].update(call_ref=True))
        self.refused("gateway capture call type")

    def test_call_binding(self):
        self.response(lambda d: d["observation"].update(call_ref=102))
        self.refused("gateway capture call binding")

    def test_invocation(self):
        self.response(lambda d: d["observation"].update(invocation_id="inv_other0001"))
        self.refused("gateway capture invocation")

    def test_attempt(self):
        for attempt in (2, True):
            with self.subTest(attempt=attempt):
                self.response(lambda d: d["observation"].update(attempt=attempt))
                self.refused("gateway capture attempt")

    def test_route(self):
        self.response(lambda d: d.update(request_type="enrich"))
        self.refused("gateway request route")

    def test_response_lists(self):
        self.response(lambda d: d.update(records={}))
        self.refused("gateway response lists")

    def test_lane(self):
        self.response(lambda d: d["lanes"][0].update(source="core"))
        self.refused("gateway acquisition lane")

    def test_duplicate_lane(self):
        self.response(lambda d: d["lanes"].append(d["lanes"][0].copy()))
        self.refused("gateway acquisition lane")

    def test_availability(self):
        self.response(lambda d: d["lanes"][0].update(coverage="searched_empty"))
        self.refused("gateway lane availability")

    def test_lane_completeness(self):
        self.response(lambda d: d["lanes"][0].update(completeness="partial"))
        self.refused("gateway lane availability")

    def test_identity(self):
        self.response(lambda d: d["lanes"][0].update(retrieved=["doi:10.1/other"]))
        self.refused("gateway retrieved identity")

    def test_canonical_record(self):
        self.response(lambda d: d["records"][0].update(identity="doi:10.1/other"))
        self.refused("gateway canonical record missing")
