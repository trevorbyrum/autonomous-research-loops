import contextlib
import io
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from research_loops.__main__ import main
from research_loops.mcp_server import EngineTools
from research_loops.queue import QueueError


class OperatorTransportTests(unittest.TestCase):
    def test_cli_socket_route_never_probes_or_opens_protected_state(self):
        with patch.dict(os.environ, {"RESEARCH_LOOP_CONTROLLER_SOCKET": "/test/controller.sock"}), \
             patch("research_loops.__main__.ControlStore", side_effect=AssertionError("private state probed")), \
             patch("research_loops.__main__.QueueStore", side_effect=AssertionError("private queue opened")), \
             patch("research_loops.__main__.controller_call", return_value={"active_count": 2}) as call, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--root", "/unreadable", "stations", "--show"]), 0)
            call.assert_called_once_with("/test/controller.sock", "stations.show", {})

    def test_mcp_socket_operations_share_controller_handlers_without_local_store(self):
        with patch.dict(os.environ, {"RESEARCH_LOOP_CONTROLLER_SOCKET": "/test/controller.sock"}), \
             patch("research_loops.mcp_server.ControlStore", side_effect=AssertionError("private state probed")), \
             patch("research_loops.mcp_server.QueueStore", side_effect=AssertionError("private queue opened")), \
             patch("research_loops.mcp_server.controller_call", return_value={"ok": True}) as call:
            engine = EngineTools(Path("/unreadable"))
            for method, route in ((engine.submit_intake, "intake.submit_brief"),
                                  (engine.decide_intake, "intake.approve"),
                                  (engine.decide_checkpoint, "checkpoint.decide"),
                                  (engine.reset_checkpoint_allowance, "checkpoint.reset_allowance")):
                self.assertEqual(method({"request_id": "test"}), {"ok": True})
                call.assert_called_with("/test/controller.sock", route, {"request_id": "test"})
            with self.assertRaises(QueueError):
                engine.draft_topic("topic", "title", "brief")
            with self.assertRaises(QueueError):
                engine.approve_and_queue("topic", "topic")
