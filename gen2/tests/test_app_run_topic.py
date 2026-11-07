"""The command line (T17 CLI). Oracle: the driver's printed line and the exit code. Limits: the station is the driver tests' fake; the
real station, router and supervisor lifecycle are the other suites'.
"""
import tempfile
import unittest
from unittest import mock

from gen2.app import compose
from gen2.app.driver import Context
from gen2.app.workflow import Step
from gen2.core import canonical
from gen2.discovery import requests
from gen2.exec.common import Refused

from gen2.app import run_topic
from gen2.app.station import StationRefused
from gen2.supervisor.supervisor import RECORDED
from gen2.tests.test_app_driver import TOPIC, World

WAIT = "waiting for: the scoping report awaits approval; run: apply_operator_decision kind=scope_approval"


class RunTopicTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.station, self.said, self.calls = self.world.station(), [], []

    def run_main(self, argv, *, environ=None, opener=None):
        def default(root, **options):
            self.calls.append(options)
            return self.station
        return run_topic.main(argv, environ=environ or {}, opener=opener or default, say=self.said.append)

    def test_it_wires_the_station_and_prints_the_wait_and_closes_the_station(self):
        self.world.topic["status"] = "awaiting_scope_approval"
        self.assertEqual((self.run_main([self.tmp.name, TOPIC]), self.said, self.station.closed), (0, [WAIT], True))
        self.assertEqual(set(self.calls[0]["supervisor_options"]["recorders"]), set(RECORDED))
        self.assertIn("gateway_captures", self.calls[0]["router_options"])

    def test_exit_codes_distinguish_a_bad_call_a_station_that_will_not_start_and_a_stopped_walk(self):
        def refusing(root, **options):
            raise StationRefused("no bundle")
        self.assertEqual(self.run_main([self.tmp.name]), 2)
        self.assertEqual(self.run_main([self.tmp.name, TOPIC], opener=refusing), 2)
        self.world.topic["holds"] = [{"hold_id": "hold_x", "clears_when": "an operator acts"}]
        self.assertEqual(self.run_main([self.tmp.name, TOPIC]), 3)

    def test_the_gateway_comes_from_the_environment_as_a_url_and_a_token_file_only(self):
        self.world.topic["status"] = "awaiting_scope_approval"
        with mock.patch.object(run_topic, "Driver", wraps=run_topic.Driver) as driver:
            self.run_main([self.tmp.name, TOPIC], environ={"GEN2_GATEWAY_URL": "http://g.invalid", "GEN2_SECRET_GATEWAY_TOKEN_FILE": "/run/secrets/gw",
                                                         "GEN2_SECRET_GATEWAY_TOKEN": "s3cret", "PATH": "/bin"})
        self.assertEqual(driver.call_args.kwargs["discovery_env"], {"GEN2_GATEWAY_URL": "http://g.invalid", "GEN2_SECRET_GATEWAY_TOKEN_FILE": "/run/secrets/gw"})


def proposal(n=1, **over):
    return {"proposal_version": "search-proposal/1", "proposal_id": f"p{n}", "proposer": "primary", "lane": "semanticscholar", "request_type": "find",
            "query": "q", "page_cap": 1, "obligation_ids": [], "rationale": "r", **over}


class ProposalAssemblyTest(unittest.TestCase):
    """The CLI's own validator through the real discovery intake and the real discovery kit."""

    def committed(self, proposals):
        payload = canonical.canonical_bytes({"invocation_id": "inv_p", "topic_id": TOPIC, "search_proposals": proposals})
        return payload, {"invocation_id": "inv_p", "topic_id": TOPIC, "operation_kind": "final_outcome", "payload_digest": canonical.bytes_digest(payload)}

    def test_the_validator_accepts_valid_proposals_and_refuses_invalid_ones_by_refusal_not_by_schema_error(self):
        payload, receipt = self.committed([proposal(1), proposal(2)])
        self.assertEqual(len(requests.intake(payload, receipt, TOPIC, 10_000, run_topic.validate).proposals), 2)
        for case, bad in (("missing field", {k: v for k, v in proposal().items() if k != "query"}), ("wrong type", proposal(page_cap="many")),
                          ("extra key", proposal(extra=1))):
            with self.subTest(case), self.assertRaises(Refused):
                requests.intake(*self.committed([bad]), TOPIC, 10_000, run_topic.validate)

    def test_the_discovery_kit_assembles_valid_proposals_and_refuses_invalid_ones_before_anything_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            world = World(directory)
            station = world.station()
            kit = compose.Composition(TOPIC).bind(station).kits(lanes=["semanticscholar"], validate=run_topic.validate,
                                                               gateway={"commercial": False, "accept_per_item": False, "policy_version": 1})[("discovery", "search")]
            context = Context(Step("discovery", "search", 1, "c1"), "inv_d", TOPIC, {"context": "contract/1"}, [], None, lambda step: None,
                              "2026-11-08T09:00:00Z", Step("research_pass", "research", 1, "c1"), 0, lambda step: "inv_p")
            for proposals, expect in (([proposal(1)], True), ([proposal(1), {k: v for k, v in proposal(2).items() if k != "lane"}], False)):
                payload, receipt = self.committed(proposals)
                world.blobs[receipt["payload_digest"]] = payload
                world.records["operation_receipts"] = [receipt]
                with self.subTest(valid=expect):
                    if expect:
                        self.assertEqual(kit.view(context, {}, [])["committed"]["receipt"]["invocation_id"], "inv_p")
                    else:
                        with self.assertRaises(Refused):
                            kit.view(context, {}, [])
            self.assertEqual(station.supervisor.submitted, [])


class UncaughtTest(unittest.TestCase):
    def test_a_refusal_during_the_walk_is_a_stop_with_its_reason_and_the_station_still_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            world = World(directory)
            station, said = world.station(), []
            with mock.patch.object(run_topic.Driver, "run", side_effect=Refused("a view is malformed")):
                code = run_topic.main([directory, TOPIC], environ={}, opener=lambda root, **o: station, say=said.append)
            self.assertEqual((code, said, station.closed), (3, [f"stopped: an input was refused; {run_topic.DETAIL}"], True))

    def test_each_kind_of_failure_has_one_fixed_line_and_the_exception_text_is_never_printed(self):
        for error, expected in ((Refused("MARK refused"), "an input was refused"), (OSError("MARK io"), "a file operation failed"),
                                (ValueError("MARK value"), "a record was malformed"), (KeyError("MARK key"), "a record lacked a field")):
            with self.subTest(type(error).__name__), tempfile.TemporaryDirectory() as directory:
                said = []
                with mock.patch.object(run_topic.Driver, "run", side_effect=error):
                    code = run_topic.main([directory, TOPIC], environ={}, opener=lambda root, **o: World(directory).station(), say=said.append)
                self.assertEqual((code, said), (3, [f"stopped: {expected}; {run_topic.DETAIL}"]))

    def test_a_malformed_proposal_key_with_a_newline_never_reaches_any_output(self):
        """End to end: a valid proposal plus a key carrying a marker and a newline is refused at assembly; the stop line is fixed."""
        import contextlib
        import io
        evil = "CALLER_SENTINEL\nFORGED_LOG_LINE"
        payload = canonical.canonical_bytes({"invocation_id": "inv_p", "topic_id": TOPIC, "search_proposals": [proposal(1, **{evil: 1})]})
        receipt = {"invocation_id": "inv_p", "topic_id": TOPIC, "operation_kind": "final_outcome", "payload_digest": canonical.bytes_digest(payload)}
        with tempfile.TemporaryDirectory() as directory:
            world = World(directory)
            world.blobs[receipt["payload_digest"]] = payload
            world.records["operation_receipts"] = [receipt]
            station, said, out, err = world.station(), [], io.StringIO(), io.StringIO()
            context = Context(Step("discovery", "search", 1, "c1"), "inv_d", TOPIC, {"context": "contract/1"}, [], None, lambda step: None,
                              "2026-11-08T09:00:00Z", Step("research_pass", "research", 1, "c1"), 0, lambda step: "inv_p")

            def assemble(driver, *args, **kwargs):
                return driver.kits[("discovery", "search")].view(context, {}, [])
            with mock.patch.object(run_topic.Driver, "run", autospec=True, side_effect=assemble), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = run_topic.main([directory, TOPIC], environ={}, opener=lambda root, **o: station, say=said.append)
        self.assertEqual((code, said, station.closed, station.supervisor.submitted), (3, [f"stopped: an input was refused; {run_topic.DETAIL}"], True, []))
        for text in (*said, out.getvalue(), err.getvalue()):
            self.assertNotIn("CALLER_SENTINEL", text)
            self.assertNotIn("FORGED_LOG_LINE", text)
            self.assertNotIn("\n", text)
