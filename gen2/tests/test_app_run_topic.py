"""The command line (T17 CLI). Oracle: the driver's printed line and the exit code. Limits: the station is the driver tests' fake; the
real station, router and supervisor lifecycle are the other suites'.
"""
import tempfile
import unittest
from unittest import mock

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
