"""Real Unix-peer and lease boundary tests, plus protected inventory operations."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from research_loops.access import (
    AccessError, authenticate_capability, initialize_access, issue_capability,
    prepare_agent_launch, validate_topic_protection,
)
from research_loops.control_store import ControlScheduler, ControlStore, default_configuration, default_work
from research_loops.controller import Controller, ControllerServer
from research_loops.controller_client import ControllerClientError, call

REPO = Path(__file__).resolve().parents[1]


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.root.chmod(0o755)
        self.topic = self.root / "topics" / "example"
        shutil.copytree(REPO / "examples" / "static-site-generator-choice", self.topic)
        self.topic.chmod(0o1777)
        for name in ("TOPIC.md", "AUTHORITY.md", "SEMANTIC-STATE.json"):
            (self.topic / name).chmod(0o644)
        self.agent_uid = 65534 if os.geteuid() != 65534 else 65533
        self.socket = self.root / "run" / "control.sock"
        self.socket.parent.mkdir(mode=0o755)
        config = default_configuration()
        config["active_count"] = 1
        for s in config["stations"]:
            s.update(primary_profile="test", secondary_profile="test")
        work = default_work()
        work["agent_profiles"] = {"test": {"adapter": "generic", "model": "test", "executable": "/bin/true", "argv": []}}
        queue = {"revision": 0, "paused": False, "stopping": False, "items": [
            {"id": "example", "cwd": str(self.topic), "status": "queued", "desired_state": "running", "lane": "research"}]}
        self.control = ControlStore.initialize(self.root, configuration=config, queue=queue, work=work)
        initialize_access(self.root, agent_uid=self.agent_uid, agent_gid=self.agent_uid,
                          operator_uids=[os.geteuid()], socket_path=str(self.socket))
        self.lease = ControlScheduler(self.control).claim(1)
        self.token = issue_capability(self.control, topic_id="example", lease_id=self.lease["lease_id"], agent_uid=self.agent_uid)
        self.controller = Controller(self.root, routes={"operator.probe": lambda params: {"value": "ok"}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_token_is_bound_to_os_uid_topic_and_live_lease(self):
        authenticate_capability(self.control, token=self.token, peer_uid=self.agent_uid, topic_id="example")
        for uid, topic in ((self.agent_uid + 1, "example"), (self.agent_uid, "other")):
            with self.assertRaises(AccessError):
                authenticate_capability(self.control, token=self.token, peer_uid=uid, topic_id=topic)
        ControlScheduler(self.control).finalize(1, self.lease["lease_id"])
        with self.assertRaises(AccessError):
            authenticate_capability(self.control, token=self.token, peer_uid=self.agent_uid, topic_id="example")

    def test_operator_allowance_reset_is_idempotent_and_preserves_count_and_order(self):
        self.controller._routes = None
        with self.control.transaction(actor="fixture") as state:
            topic = state["work"]["topics"]["example"]
            topic.update(proposal_allowance_remaining=0, research_iterations_completed=25, next_research_ordinal=26)
        before = self.control.snapshot()
        payload = {"schema_version": 1, "request_id": "reset-1", "expected_revision": before["revision"],
                   "topic_id": "example", "reason": "Operator authorized another proposal allowance"}
        request = {"method": "checkpoint.reset_allowance", "params": payload}
        with self.assertRaises(AccessError):
            self.controller.dispatch(request, peer_uid=self.agent_uid, peer_pid=1)
        result = self.controller.dispatch(request, peer_uid=os.geteuid(), peer_pid=1)
        after = self.control.snapshot()
        self.assertEqual(self.controller.dispatch(request, peer_uid=os.geteuid(), peer_pid=1), result)
        self.assertEqual(self.control.snapshot(), after)
        self.assertEqual(before["queue"], after["queue"])
        topic = after["work"]["topics"]["example"]
        self.assertEqual((topic["research_iterations_completed"], topic["next_research_ordinal"], topic["proposal_allowance_remaining"]), (25, 26, 2))
        with self.assertRaises(AccessError):
            self.controller.dispatch({"method": request["method"], "params": payload | {"reason": "changed"}}, peer_uid=os.geteuid(), peer_pid=1)

    def test_actor_payload_and_operator_method_cannot_escalate_research(self):
        for request in (
            {"method": "operator.probe", "params": {}, "token": self.token},
            {"method": "state.cli", "params": {}, "token": self.token, "actor": "operator"},
        ):
            with self.assertRaises(AccessError):
                self.controller.dispatch(request, peer_uid=self.agent_uid, peer_pid=1)

    def test_existing_state_cli_validation_is_preserved(self):
        result = self.controller.dispatch({"method": "state.cli", "params": {
            "topic_id": "example", "action": "select", "arguments": []}, "token": self.token},
            peer_uid=self.agent_uid, peer_pid=1)
        self.assertEqual(result["exit_code"], 0, result["stderr"])
        self.assertIsInstance(json.loads(result["stdout"]), dict)
        with self.assertRaises(AccessError):
            self.controller.dispatch({"method": "state.cli", "params": {
                "topic_id": "example", "action": "rehash", "arguments": []}, "token": self.token},
                peer_uid=self.agent_uid, peer_pid=1)

    def test_read_only_contract_requires_directory_rename_protection(self):
        validate_topic_protection(self.topic, agent_uid=self.agent_uid)
        self.topic.chmod(0o777)
        with self.assertRaises(AccessError):
            validate_topic_protection(self.topic, agent_uid=self.agent_uid)

    def test_assessment_write_preserves_inventory_and_exact_policy_options(self):
        before = json.loads((self.topic / "SEMANTIC-STATE.json").read_text())
        (self.topic / "evidence.txt").write_text("Existing research evidence")
        def invoke(action, arguments):
            return self.controller.dispatch({"method": "state.cli", "params": {
                "topic_id": "example", "action": action, "arguments": arguments}, "token": self.token},
                peer_uid=self.agent_uid, peer_pid=1)
        result = invoke("pending", ["--add", "evidence.txt"])
        self.assertEqual(result["exit_code"], 0, result["stderr"])
        after = json.loads((self.topic / "SEMANTIC-STATE.json").read_text())
        self.assertEqual(before["obligations"], after["obligations"])
        self.assertIn("evidence.txt", after["pending_evidence_refs"])
        with self.assertRaises(AccessError):
            invoke("validate", ["--topics-root=/tmp"])
        self.assertNotEqual(invoke("validate", ["--allow-internal"])["exit_code"], 0)

    def test_launch_cannot_fall_back_to_supervisor_identity(self):
        env, kwargs = prepare_agent_launch(self.root, "example", self.lease["lease_id"])
        self.assertEqual(kwargs, {"user": self.agent_uid, "group": self.agent_uid, "extra_groups": []})
        self.assertEqual(env["RESEARCH_LOOP_MANAGED_TOPIC_ID"], "example")
        (self.root / "state" / "access.json").chmod(0o644)
        with self.assertRaises(AccessError):
            prepare_agent_launch(self.root, "example", self.lease["lease_id"])

    def test_unix_socket_uses_real_peer_credentials(self):
        with ControllerServer(self.controller) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertEqual(call(str(self.socket), "operator.probe", {}), {"value": "ok"})
                with self.assertRaises(ControllerClientError):
                    call(str(self.socket), "not-an-operation", {})
            finally:
                server.shutdown()
                thread.join()

    def test_distinct_os_user_cannot_write_state_or_replace_contract_but_can_use_state_cli(self):
        if not shutil.which("sudo") or subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode:
            self.skipTest("requires local permission to execute a disposable child under a different UID")
        with ControllerServer(self.controller) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                # Scope secrets travel over stdin, never shell interpolation.
                child = r'''
import json,pathlib,socket,sys
p=json.load(sys.stdin)
denied=[]
for path in (p['database'],p['access'],p['contract']):
 try: pathlib.Path(path).write_text('tamper')
 except PermissionError: denied.append(path)
try: pathlib.Path(p['contract']).unlink()
except PermissionError: denied.append('unlink')
sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.connect(p['socket'])
sock.sendall((json.dumps({'method':'operator.probe','params':{},'token':p['token']})+'\n').encode())
op=json.loads(sock.makefile().readline());sock.close()
sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.connect(p['socket'])
sock.sendall((json.dumps({'method':'state.cli','params':{'topic_id':'example','action':'select','arguments':[]},'token':p['token']})+'\n').encode())
result=json.loads(sock.makefile().readline());sock.close()
print(json.dumps({'denied':len(denied),'operator_denied':not op['ok'],'state_ok':result['ok'] and result['result']['exit_code']==0}))
'''
                payload = {"database": str(self.control.path), "access": str(self.root / "state" / "access.json"),
                           "contract": str(self.topic / "TOPIC.md"), "socket": str(self.socket), "token": self.token}
                result = subprocess.run(["sudo", "-n", "-u", f"#{self.agent_uid}", "/usr/bin/python3", "-c", child],
                                        input=json.dumps(payload), text=True, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"denied": 4, "operator_denied": True, "state_ok": True})
            finally:
                server.shutdown()
                thread.join()


if __name__ == "__main__":
    unittest.main()
