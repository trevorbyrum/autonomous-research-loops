"""V7 §§4–5: pure protocol and file refusals; no daemon, listeners or Q PASS."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.gen2.live import build, fixture, qualify, runner


class Fixtures(unittest.TestCase):
    def test_dedicated_builder_and_original_counter(self):
        view = {"Driver": "docker", "Nodes": [{"Endpoint": build.SOCKET}]}
        build.builder_gate("gen2-2e1-build", view, {})
        for driver in ("docker-container", "remote"):
            with self.subTest(driver=driver), self.assertRaises(ValueError):
                build.builder_gate("gen2-2e1-build", view | {"Driver": driver}, {})
        rows = [dict(event=event, nonce="a" * 32, origin={}, count=i, forwarded=0) for i, event in enumerate(("ready", "delivery"))]
        self.assertEqual(qualify.counts("\n".join(map(json.dumps, rows)), "a" * 32, {}), 1)
        with self.assertRaisesRegex(ValueError, "observer_originals"):
            qualify.counts("\n".join(map(json.dumps, rows)), "b" * 32, {})

    def test_workflow_input_names(self):
        with patch.object(runner, "read_file", side_effect=[b"Judge the input", b'{"topic":"fixture"}']) as read:
            self.assertIn('{"topic":"fixture"}', runner.work_prompt(7))
            self.assertEqual([call.args[1] for call in read.call_args_list], ["prompt.md", "input.json"])

    def test_two_sends_and_rejected_branch(self):
        request = dict(model="gpt-5.4", stream=True, tools=[{"name": n} for n in ("exec_command", "write_stdin", "apply_patch")])
        status, _, data = fixture.response("accepted", 1, request)
        event = json.loads(data.decode().split("data: ")[1].split("\n")[0])
        self.assertEqual((status, event["item"]["name"], event["item"]["call_id"]), (200, "exec_command", "call_2e1"))
        request["input"] = [dict(type="function_call_output", call_id="call_2e1", output="2e1-tool-ok")]
        self.assertIn(b"2e1 complete", fixture.response("accepted", 2, request)[2])
        self.assertEqual(fixture.response("rejected", 1, request)[0], 401)
        for case, ordinal, change in (("accepted", 3, {}), ("rejected", 2, {}), ("accepted", 1, {"tools": []}),
                                      ("accepted", 2, {"input": []}), ("accepted", 1, {"model": "other"})):
            with self.subTest(case=case, ordinal=ordinal, change=change), self.assertRaises(ValueError):
                fixture.response(case, ordinal, request | change)

    def test_seed_read_refuses_link_and_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "auth.json")
            path.write_bytes(b"dummy")
            path.chmod(0o400)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.assertEqual(runner.read_file(fd, "auth.json", 5), b"dummy")
                with self.assertRaises(ValueError):
                    runner.read_file(fd, "auth.json", 4)
                os.link(path, Path(directory, "link"))
                with self.assertRaises(ValueError):
                    runner.read_file(fd, "auth.json", 5)
            finally:
                os.close(fd)
