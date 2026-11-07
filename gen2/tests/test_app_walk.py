"""The hosted walk (T19 step 1). Oracles: the HTTP replies of a real engine (real station, real owner thread, real authentication) and
the stub driver's scripted ticks; for the slow-operation witness, wall-clock times of concurrent requests. Limits: the real-driver case
stops at the first operator wait (no live agent, no jobs); the walk's later steps are the driver suites'.
"""
import json
import threading
import time
import unittest

from gen2.app import compose, walk, workflow
from gen2.app.engine import Engine
from gen2.app.station import open_station
from gen2.exec.common import Refused
from gen2.tests import operator_fixtures as of
from gen2.tests.router_fixtures import TOPIC

SECRET = "SENTINEL\nLINE"


class Stub:
    """A driver whose tick is scripted: an action, an exception, or a delay."""
    def __init__(self, result, delay=0.0):
        self.result, self.delay = result, delay

    def tick(self):
        time.sleep(self.delay)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class WalkerTest(unittest.TestCase):
    def walker(self, result, delay=0.0):
        return walk.Walker(lambda topic: Stub(result, delay))

    def test_a_closed_body_is_required_and_anything_else_is_refused_without_reflecting_it(self):
        for body in ({}, {"topic_id": TOPIC, "live": True}, {"topic_id": 7}, {"topic_id": "no colon"}, {"topic_id": TOPIC + "\n"}, {"topic": TOPIC}, ["x"], None):
            with self.subTest(body=body):
                self.assertEqual(self.walker(workflow.Done()).walk(body), {"status": "refused", "reason": "request_invalid"})

    def test_each_action_has_one_fixed_reply(self):
        step = workflow.Step("research_pass", "scope", 1, "p2")
        for action, expected in ((workflow.Issue(step), {"status": "ok", "action": "issue"}), (workflow.Advance(step), {"status": "ok", "action": "advance"}),
                                 (workflow.Done(), {"status": "ok", "action": "done"}),
                                 (workflow.Wait("a long reason " + SECRET, "open_review"), {"status": "ok", "action": "wait", "command": "open_review"}),
                                 (workflow.Stop("open hold hold_x: " + SECRET, "hold_open"), {"status": "ok", "action": "stop", "code": "hold_open"})):
            with self.subTest(type(action).__name__):
                self.assertEqual(self.walker(action).walk({"topic_id": TOPIC}), expected)

    def test_a_failing_tick_is_a_fixed_code_and_never_the_exception_text(self):
        for error, code in ((Refused(SECRET), "refused"), (OSError(SECRET), "io"), (ValueError(SECRET), "malformed"), (KeyError(SECRET), "malformed")):
            with self.subTest(type(error).__name__):
                self.assertEqual(self.walker(error).walk({"topic_id": TOPIC}), {"status": "stopped", "code": code})


class HostedWalk(of.OperatorTestCase):
    """Over real HTTP to the engine."""

    def engine_with(self, make_driver):
        self.engine.close()
        self.engine = None
        self.engine = Engine(lambda: open_station(self.root, station_id="station-1", host_id="host-1", clock=self.clock, router_options={"new_id": self.ids}),
                             of.credentials(), log=self.logs.append, walker=lambda station: walk.Walker(make_driver))

    def test_without_a_walker_the_command_is_refused(self):
        self.assertEqual(self.command("walk", {"topic_id": TOPIC}), (200, {"status": "refused", "reason": "walk_unavailable", "detail": "operation refused"}))

    def test_only_an_authenticated_operator_may_walk_and_the_body_names_no_authority(self):
        self.engine_with(lambda topic: Stub(workflow.Done()))
        self.assertEqual(self.command("walk", {"topic_id": TOPIC}), (200, {"status": "ok", "action": "done"}))
        self.assertEqual(self.command("walk", {"topic_id": TOPIC}, token=of.EXPORTER_TOKEN)[0], 403)
        self.assertEqual(self.command("walk", {"topic_id": TOPIC}, token=None)[0], 401)
        code, reply = self.command("walk", {"topic_id": TOPIC, "capability_id": "cap_" + "a" * 32})
        self.assertEqual((code, reply["reason"]), (400, "authority_in_request"))

    def test_the_mcp_transport_applies_the_same_rule(self):
        self.engine_with(lambda topic: Stub(workflow.Done()))
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "walk", "arguments": {"topic_id": TOPIC}}}
        code, reply, _ = self.http("POST", "/mcp", message)
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(reply["result"]["content"][0]["text"]), {"status": "ok", "action": "done"})
        code, reply, _ = self.http("POST", "/mcp", message, token=of.EXPORTER_TOKEN)
        self.assertNotIn("done", json.dumps(reply))          # the exporter role cannot walk by either transport

    def test_the_real_driver_walks_one_tick_on_the_owner_thread_and_stops_at_the_operators_move(self):
        composition = compose.Composition()
        self.engine.close()
        self.engine = None
        self.engine = Engine(lambda: composition.bind(open_station(
            self.root, station_id="station-1", host_id="host-1", clock=self.clock,
            router_options={"new_id": self.ids, "gateway_captures": composition.captures}, supervisor_options={"recorders": composition.recorders()})).station,
            of.credentials(), log=self.logs.append, walker=lambda station: walk.Walker(walk.driver_factory(station, composition, {})))
        self.assertEqual(self.command("walk", {"topic_id": TOPIC}),
                         (200, {"status": "ok", "action": "wait", "command": "apply_operator_decision kind=brief_confirmation"}))
        self.assertEqual(self.command("walk", {"topic_id": "fleet-a:nothing"})[1]["status"], "stopped")        # an unknown topic: a fixed code, no traceback

    def test_a_slow_tick_holds_the_owner_thread_so_health_and_the_next_walk_queue_behind_it_and_are_never_run_together(self):
        """The measured bound: a tick of T seconds delays a health read by up to T and serializes walks. Nothing is shortened to hide it."""
        order, tick = [], 0.6

        class Slow(Stub):
            def tick(inner):
                order.append(("start", time.monotonic()))
                time.sleep(tick)
                order.append(("end", time.monotonic()))
                return workflow.Done()
        self.engine_with(lambda topic: Slow(None))
        replies, health = [], []
        first = threading.Thread(target=lambda: replies.append(self.command("walk", {"topic_id": TOPIC})))
        second = threading.Thread(target=lambda: replies.append(self.command("walk", {"topic_id": TOPIC})))
        first.start()
        time.sleep(0.1)
        second.start()
        began = time.monotonic()
        code, _, _ = self.http("GET", "/v1/health", token=None)
        health.append(time.monotonic() - began)
        first.join()
        second.join()
        self.assertEqual((code, [r[1]["action"] for r in replies]), (200, ["done", "done"]))
        self.assertGreater(health[0], tick * 0.5)                         # health waited behind the running tick (the owner thread is one)
        self.assertLess(health[0], 2 * tick + 2.0)                        # and not behind unbounded work
        kinds = [k for k, _ in order]
        self.assertEqual(kinds, ["start", "end", "start", "end"])         # the two walks never overlapped
