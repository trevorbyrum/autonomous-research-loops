"""2e1 v7 §4-§5 dual witness, offline: the T6 fixture handler on loopback, hand-authored access rows.

Oracle: `classify` over the fixture's own record plus the log row and runner events
a real run would leave (the real-runner witness is T10/Q11 on the host). Limits: no
daemon, no pinned runner, no real provider; a fixture record never attests a genuine route.
"""
import http.client
import importlib.util
import io
import json
import threading
import time
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from gen2.supervisor import rejection
from gen2.tests import router_fixtures as rf

# The T6 responder is lane C's file under deploy/, which tests may not import; read it by path, unchanged.
_spec = importlib.util.spec_from_file_location("t6_fixture", Path(__file__).parents[2] / "deploy/gen2/live/fixture.py")
fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixture)

RID = "a" * 32
ROW = {"v": 3, "id": RID, "src": "172.31.254.3", "port": "40000", "conn": "1", "ordinal": "1", "listener": "model",
       "server_port": "8080", "method": "POST", "route": "model", "upstream": "172.31.252.3:8081", "status": "401",
       "upstream_status": "401", "complete": "OK", "at": "1.0"}
FAILED = [{"type": t} for t in ("thread.started", "turn.started", "error", "turn.failed")]
TOOLS = [{"name": n} for n in ("exec_command", "write_stdin", "apply_patch")]


def lines(rows):
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


def exchange(case, bodies):
    """Send each body to a fresh loopback fixture server; return statuses, payloads and the fixture record bytes."""
    server = HTTPServer(("127.0.0.1", 0), fixture.Handler)
    server.case, server.record, server.raw, server.requests = case, io.StringIO(), io.StringIO(), []
    server.count, server.deadline, server.timeout = 0, time.monotonic() + 30, 5
    results = []
    with server:
        for index, body in enumerate(bodies, 1):
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            headers = {"Authorization": "Bearer 2e1-fixture-" + case, "X-Request-ID": RID[:-1] + str(index), "Content-Type": "application/json"}
            connection.request("POST", "/v1/responses", json.dumps(body), headers)
            reply = connection.getresponse()
            results.append((reply.status, reply.read()))
            connection.close()
            thread.join()
    return results, server.record.getvalue().encode()


class DualWitness(unittest.TestCase):
    def classify(self, rows=None, events=FAILED, record=None, code=1, **change):
        rows = [ROW | change] if rows is None else rows
        return rejection.classify(lines(rows), lines(events), record, code, model="gpt-5.4")["disposition"]

    def test_rejected_key_is_one_request_literal_rejection(self):
        results, record = exchange("rejected", [{"model": "gpt-5.4", "stream": True}])
        self.assertEqual([status for status, _ in results], [401])
        self.assertEqual(self.classify(record=record, id=RID[:-1] + "1"), "credentials_rejected")

    def test_accepted_key_drives_tool_and_two_request_completion(self):
        request = {"model": "gpt-5.4", "stream": True, "tools": TOOLS}
        results, record = exchange("accepted", [request, request | {"input": [dict(
            type="function_call_output", call_id="call_2e1", output="2e1-tool-ok")]}])
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertIn(b'"name": "exec_command"', results[0][1])
        self.assertIn(b"2e1 complete", results[1][1])
        self.assertEqual(len(json.loads(record)["requests"]), 2)
        events = [{"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}]
        usage = rejection.usage_record({}, lines(events), elapsed=1.5, gateway_refs=[], raw_refs=[], observed_model="gpt-5.4", configured_model="gpt-5.4")
        self.assertEqual(usage["usage"]["input_tokens"], {"state": "reported", "value": 10})
        self.assertEqual(self.classify(rows=[ROW, ROW | {"id": RID[:-1] + "2", "ordinal": "2"}], events=events, record=record, code=0), "unknown")

    def test_refusal_controls_never_become_a_credential_fact(self):
        _, record = exchange("rejected", [{"model": "gpt-5.4", "stream": True}])
        genuine = json.dumps({"v": 1, "requests": [{"id": RID[:-1] + "1", "route": "/v1/responses", "model": "gpt-5.4", "credential": "accepted"}]}).encode()
        text401 = FAILED[:2] + [{"type": "error", "message": "401"}] + FAILED[3:]
        for name, kwargs, expected in (
                ("timeout", dict(upstream_status="504", status="504"), "transport_failed"),
                ("429", dict(upstream_status="429", status="429"), "transport_failed"),
                ("malformed", dict(rows=[]) | dict(record=record), "unknown"),
                ("model text 401", dict(status="200", upstream_status="200", events=text401), "unknown"),
                ("bogus success", dict(status="200", upstream_status="200", events=[{"type": "turn.completed"}], code=0), "unknown"),
                ("missing log", dict(rows=[]), "unknown"),
                ("extra request", dict(rows=[ROW, ROW | {"id": "b" * 32}]), "unknown"),
                ("fixture as genuine", dict(record=genuine), "unknown")):
            with self.subTest(name):
                kwargs = {"record": record, "id": RID[:-1] + "1"} | kwargs
                if name == "malformed":
                    got = rejection.classify(lines([ROW])[:-5], lines(FAILED), record, 1, model="gpt-5.4")["disposition"]
                else:
                    got = self.classify(**kwargs)
                self.assertEqual(got, expected)


class PersistenceAck(rf.Workflow):
    """Gateway capture ACK and Router persistence ACK are distinct (H-6, DEP 4.1): existing Router API, tests only."""
    def test_missing_persistence_ack_changes_nothing_and_replays_once(self):
        self.to_queued()
        grant = self.started("inv_research01")
        before = self.state()
        with patch.object(self.router, "_store", rf.Refusing(self.store, 1)), self.assertRaises(AssertionError):
            self.observe(grant, "obs_ack00001", ("rec_1",))
        self.assertEqual(self.state(), before)
        self.assertEqual(self.observe(grant, "obs_ack00001", ("rec_1",)), ["rev_ack0000101"])
        after = self.state()
        with self.assertRaises(AssertionError):  # an identical resend is not a second recording
            self.observe(grant, "obs_ack00001", ("rec_1",))
        self.assertEqual(self.state(), after)
        self.assertEqual(len(self.store.select("search_observations")), 1)
