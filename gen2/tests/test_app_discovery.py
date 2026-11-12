"""A2: the app entry selects the real transport in a supervised child; the non-live default stays fenced.

Oracles: a real loopback gateway's requests, fresh child exit/files, and durable orders/lifecycle records. No provider or Docker.
The lookup witness stalls getaddrinfo inside the real app entry; the ordinary supervisor's deadline terminates its process group.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gen2.app import discovery, walk, workflow
from gen2.core import canonical
from gen2.discovery import child, recorder
from gen2.gateway_client.client import GatewayClient, http_transport
from gen2.tests import children, router_fixtures as rf
from gen2.tests.gateway_wire import CAPTURED, EMPTY_LANE, Recorder, gateway_script, reply
from gen2.tests.loopback import ThreadsJoined
from gen2.tests.supervisor_fixtures import AFTER_DEADLINE, MAIN, SupervisedTestCase
from gen2.tests.test_app_driver import World, scope
from gen2.tests.test_discovery_child import Fixture, committed, proposal


class LiveEntry(Fixture, ThreadsJoined):
    def setUp(self):
        ThreadsJoined.setUp(self)
        Fixture.setUp(self)

    def tearDown(self):
        Fixture.tearDown(self)

    def result(self):
        return json.loads((self.root / child.RESULT).read_text())

    def test_import_and_parent_composition_construct_no_client_and_entry_injects_the_exact_transport(self):
        with mock.patch.object(child, "GatewayClient", side_effect=AssertionError("client outside job")), \
             mock.patch("socket.getaddrinfo", side_effect=AssertionError("lookup during import")), mock.patch.object(child, "main", return_value=0) as main:
            importlib.reload(discovery)
            self.assertEqual(discovery.main([str(self.root)]), 0)
            main.assert_called_once_with([str(self.root)], validate=walk.validate, transport=http_transport)

    def test_production_module_runs_with_scrubbed_environment_and_real_serial_http_requests(self):
        gateway = Recorder(self, gateway_script())
        env = {**self.stage([proposal(1), proposal(2)]), child.URL: gateway.server.url}
        done = children.python(["-m", "gen2.app.discovery", str(self.root)], env=env, cwd=self.root, capture_output=True, text=True, timeout=20)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(gateway.request_lines, ["POST /v1/grants HTTP/1.1", "POST /v1/find HTTP/1.1", "POST /v1/find HTTP/1.1"])
        self.assertEqual([s["proposal_id"] for s in self.result()["searches"]], ["p1", "p2"])
        self.assertTrue((self.root / child.OUTCOME).exists())

    def test_one_client_per_job_and_no_io_for_the_fenced_entry_or_malformed_proposals(self):
        gateway = Recorder(self, gateway_script())
        for bad in (proposal(2, page_cap=0), proposal(2, filters={"what": "invalid for find"})):
            self.tmp.cleanup()
            Fixture.setUp(self)
            env = {**self.stage([proposal(1), bad]), child.URL: gateway.server.url}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(child, "GatewayClient", wraps=GatewayClient) as constructor:
                self.assertEqual(discovery.main([str(self.root)]), 2)
                constructor.assert_not_called()
                self.assertEqual(child.main([str(self.root)]), 2)
                constructor.assert_not_called()
            self.assertEqual(gateway.count, 0)
            self.assertFalse((self.root / child.RESULT).exists())
        # Valid jobs each build one client, and each uses it for both proposals serially.
        self.tmp.cleanup()
        Fixture.setUp(self)
        env = {**self.stage([proposal(1), proposal(2)]), child.URL: gateway.server.url}
        built = []
        def construct(*args, **kw):
            client = GatewayClient(*args, **kw)
            built.append(client)
            return client
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(child, "GatewayClient", side_effect=construct):
            self.assertEqual(discovery.main([str(self.root)]), 0)
            self.assertEqual(discovery.main([str(self.root)]), 0)
        self.assertEqual(len(built), 2)
        self.assertIsNot(built[0], built[1])
        self.assertEqual(gateway.count, 6)

    def test_degraded_or_capture_failed_retrieval_never_becomes_empty_success(self):
        for captured, lanes in ((True, [{**EMPTY_LANE, "coverage": "provider_unavailable", "completeness": "unobserved", "count": None, "exhausted": False}]),
                                (False, [EMPTY_LANE])):
            with self.subTest(captured=captured):
                self.tmp.cleanup()
                Fixture.setUp(self)
                def answer(server, conn, head, body, index):
                    payload = {"token": "gwg1.synthetic"} if head.startswith(b"POST /v1/grants") else {
                        "observation": {**CAPTURED, "captured": captured}, "lanes": lanes, "records": []}
                    server.send(conn, [(0, reply(json.dumps(payload).encode(), "201 Created" if "token" in payload else "200 OK"))])
                gateway = Recorder(self, answer)
                env = {**self.stage([proposal(1)]), child.URL: gateway.server.url}
                with mock.patch.dict(os.environ, env, clear=True):
                    self.assertEqual(discovery.main([str(self.root)]), 0)
                observation = self.result()["searches"][0]["out"]["observations"][0]["observation"]
                self.assertIn(observation["coverage_state"], ("provider_unavailable", "unknown"))
                self.assertIsNone(observation["result_count"])


class Selection(unittest.TestCase):
    def test_selection_is_per_new_order_and_later_ticks_preserve_the_issued_entry_without_model_authority(self):
        for first_live in (True, False):
            with self.subTest(first_live=first_live), tempfile.TemporaryDirectory() as root:
                world = World(root)
                station = world.station()
                kits = world.driver(station).kits
                factory = walk.driver_factory(station, SimpleNamespace(kits=lambda *a, **kw: kits), {"GEN2_PROMPTS": str(Path(root) / "prompts")})
                with mock.patch.object(child, "GatewayClient", side_effect=AssertionError("client in engine")):
                    driver = factory("fleet:topic")
                    driver.tick()
                    iid = driver.invocation_id(scope(1))
                    station.supervisor.script[iid] = "committed"
                    world.blobs[f"sha256:{iid}"] = canonical.canonical_bytes({"search_proposals": [{"proposal_id": "p1"}]})
                    driver.tick()
                    step = workflow.Step("discovery", "search", 1, "p2")
                    self.assertEqual(factory("fleet:topic", live=first_live).tick(), workflow.Issue(step))
                    order = station.supervisor.submitted[-1]
                    expected = "gen2.app.discovery" if first_live else "gen2.discovery.child"
                    self.assertEqual(order.command[1:3], ("-m", expected))
                    self.assertEqual(station.supervisor.lives, [False, False])  # discovery is not a model dispatch
                    self.assertEqual(factory("fleet:topic", live=not first_live).tick(), workflow.Advance(step))
                    self.assertEqual(len(station.supervisor.submitted), 2)
                    self.assertEqual(station.supervisor.job(order.invocation_id).read("order.json")["env"], dict(order.env))
                    self.assertEqual(order.command[2], expected)


class LookupDeadline(SupervisedTestCase):
    def test_stalled_lookup_in_the_live_entry_is_terminated_by_the_supervised_job_deadline(self):
        fixture = Fixture()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        env = fixture.stage([proposal(1)])
        document = json.loads((fixture.root / "inputs" / "input.json").read_text())
        document.update(invocation_id=MAIN, topic_id=rf.TOPIC)
        document["view"].update(committed([proposal(1)], topic=rf.TOPIC))
        data = canonical.canonical_bytes(document)
        (fixture.root / "inputs" / "input.json").write_bytes(data)
        env.update(GEN2_INPUT_DIGEST=canonical.bytes_digest(data), GEN2_GATEWAY_URL="http://gateway.invalid", GEN2_PURPOSE="discovery/search")
        # Patch only the external resolver in this test child; execute the real production module and transport selection.
        code = """import runpy, socket, sys, time
from pathlib import Path
def lookup(*args):
    Path('lookup-entered').touch()
    while True: time.sleep(1)
socket.getaddrinfo = lookup
runpy.run_module('gen2.app.discovery', run_name='__main__')
"""
        from dataclasses import replace
        order = replace(self.order("discovery"), command=(sys.executable, "-c", code, str(fixture.root)), env=children.env(env))
        supervisor = self.make_supervisor(recorders={"discovery/search": recorder.recorder(self.spool.stage)})
        self.assertEqual(supervisor.submit(order), "running")
        self.wait_for_file("scratch/lookup-entered")
        self.clock.set(AFTER_DEADLINE)
        self.assertEqual(supervisor.run(MAIN), "failed")
        ended = self.ended()
        self.assertEqual(ended["failure_class"], "timeout")
        self.assertEqual(self.journal()["collected"]["observation"]["descendants"]["handling"], "terminated")
        self.assertEqual(supervisor.job(MAIN).lookup()["members"], [])
        self.assertFalse((fixture.root / child.RESULT).exists())
