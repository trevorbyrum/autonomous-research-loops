"""Authenticated local controller for managed operator and research operations.

Unix peer credentials establish the caller's OS identity. Research calls also
require a capability tied to the current topic lease; an ``actor`` payload never
grants authority. The service itself is the protected database/file writer.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
import stat
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .access import AccessError, authenticate_capability, current_lease, load_access
from .control_store import ControlStore
from .controller_client import MAX_MESSAGE_BYTES

STATE_ACTIONS = frozenset({"select", "get", "summary", "check", "validate", "lock", "signature",
                           "source-count", "transition", "pending", "deliverable", "contradiction"})


class Controller:
    def __init__(self, root: str | Path, *, routes: dict[str, Callable] | None = None):
        self.root = Path(root).resolve()
        self.control = ControlStore(self.root)
        self.access = load_access(self.root)
        self._routes = routes

    def operator_routes(self, peer_uid: int) -> dict[str, Callable]:
        if self._routes is not None:
            return self._routes
        from .intake import operator_dispatch
        routes = operator_dispatch(self.control, self.root / "topics", actor=f"operator-uid:{peer_uid}")
        routes["control.snapshot"] = lambda params: self.control.snapshot() if not params else _reject("snapshot takes no parameters")
        routes["checkpoint.reset_allowance"] = lambda params: self.reset_allowance(params, peer_uid)
        return routes

    def reset_allowance(self, params: dict, peer_uid: int) -> dict:
        from .input_schema import strict_object, integer, nonempty_string
        strict_object(params, path="$", required={"schema_version", "request_id", "expected_revision", "topic_id", "reason"})
        if integer(params["schema_version"], "$.schema_version") != 1:
            raise AccessError("unsupported schema_version")
        for name in ("request_id", "topic_id", "reason"):
            nonempty_string(params[name], "$." + name)
        integer(params["expected_revision"], "$.expected_revision", minimum=0)
        with self.control.transaction(actor=f"operator-uid:{peer_uid}", operation_id=params["request_id"], affected_ids=[params["topic_id"]]) as state:
            requests = state["work"].setdefault("proposal_reset_requests", {})
            prior = requests.get(params["request_id"])
            if prior:
                if prior["payload"] != params:
                    raise AccessError("request_id was already used with different reset content")
                return prior["result"]
            if state["revision"] != params["expected_revision"]:
                raise AccessError("stale expected_revision; refresh stations status before resetting allowance")
            topic = state["work"]["topics"].get(params["topic_id"])
            if topic is None:
                raise AccessError("unknown managed topic")
            topic["proposal_allowance_remaining"] = 2
            topic.setdefault("proposal_allowance_resets", []).append({"request_id": params["request_id"], "reason": params["reason"], "operator_uid": peer_uid})
            result = {"topic_id": params["topic_id"], "proposal_allowance_remaining": 2}
            requests[params["request_id"]] = {"payload": dict(params), "result": result}
            return result

    def dispatch(self, request: Any, *, peer_uid: int, peer_pid: int) -> Any:
        if not isinstance(request, dict) or set(request) - {"method", "params", "token"}:
            raise AccessError("request must contain method, params and optional execution token only")
        method, params = request.get("method"), request.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            raise AccessError("method must be a string and params must be an object")
        if peer_uid in self.access["operator_uids"]:
            handler = self.operator_routes(peer_uid).get(method)
            if handler is None:
                raise AccessError(f"unknown operator operation: {method}")
            return handler(params)
        if peer_uid != self.access["agent_uid"]:
            raise AccessError("caller UID is not authorized for this controller")
        if method == "gap.promote":
            from .gap_promotion import promote
            return promote(self.control, peer_uid=peer_uid, token=request.get("token"), payload=params)
        if method == "checkpoint.delegate":
            episode_id = params.get("episode_id")
            if not isinstance(episode_id, str):
                raise AccessError("checkpoint.delegate requires an episode_id")
            episode = self.control.snapshot()["work"].get("episodes", {}).get(episode_id)
            if not isinstance(episode, dict):
                raise AccessError("unknown checkpoint episode")
            capability = authenticate_capability(self.control, token=request.get("token"),
                peer_uid=peer_uid, topic_id=episode["topic_id"])
            if capability["execution_kind"] != "checkpoint" or capability["lease_id"] != params.get("lease_id"):
                raise AccessError("delegate request must use its own active checkpoint lease")
            from .checkpoints.delegate import dispatch
            return dispatch(self.control, params)
        if method != "state.cli":
            raise AccessError("execution callers cannot invoke operator operations")
        if set(params) != {"topic_id", "action", "arguments"}:
            raise AccessError("state.cli requires exactly topic_id, action and arguments")
        topic_id, action, arguments = params["topic_id"], params["action"], params["arguments"]
        if (not isinstance(topic_id, str) or not topic_id or action not in STATE_ACTIONS
                or not isinstance(arguments, list) or any(not isinstance(x, str) or "\0" in x for x in arguments)):
            raise AccessError("invalid or unauthorized state operation")
        capability = authenticate_capability(self.control, token=request.get("token"),
                                             peer_uid=peer_uid, topic_id=topic_id)
        if capability["execution_kind"] == "intake_discovery":
            raise AccessError("discovery returns a structured result; it cannot mutate approved research state")
        # Hold the controller transaction across the existing state operation.
        # Handoff cannot revoke a lease between authorization and the file write.
        with self.control.transaction(actor=f"research-uid:{peer_uid}", affected_ids=[topic_id]) as state:
            lease = current_lease(state, topic_id=topic_id, lease_id=capability["lease_id"])
            if lease is None or lease["lease_generation"] != capability["lease_generation"]:
                raise AccessError("execution lease changed before state mutation")
            if any(intent["payload"]["topic_id"] == topic_id and intent["state"] != "committed"
                   for intent in state["work"].get("auto_gap_intents", {}).values()):
                raise AccessError("retry the pending gap promotion before further semantic state operations")
            item = next((i for i in state["queue"]["items"] if i["id"] == topic_id), None)
            if item is None:
                raise AccessError("unknown managed topic")
            topic_dir = Path(item["cwd"]).resolve()
            # Internal-citation policy is operator-owned. A caller cannot grant
            # itself this access by changing a CLI flag.
            if "--allow-internal-citations" in arguments and not item.get("internal_citations"):
                raise AccessError("internal citations are not enabled for this topic")
            for index, argument in enumerate(arguments):
                if argument == "--topics-root" or argument.startswith("--topics-root="):
                    value = argument.partition("=")[2] if "=" in argument else (
                        arguments[index + 1] if index + 1 < len(arguments) else "")
                    if not value or Path(value).resolve() != (self.root / "topics").resolve():
                        raise AccessError("topics-root must be the managed portfolio")
            env = os.environ.copy()
            for key in ("RESEARCH_LOOP_CONTROLLER_SOCKET", "RESEARCH_LOOP_EXECUTION_CAPABILITY",
                        "RESEARCH_LOOP_MANAGED_TOPIC_ID", "RESEARCH_LOOP_MANAGED_TOPIC_DIR"):
                env.pop(key, None)
            command = [sys.executable, str(Path(__file__).parent / "chassis" / "semantic-state.py"),
                       action, str(topic_dir), *arguments]
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)
            # A file operation's audit is explicit even though the controller's
            # main queue/work counters intentionally do not change.
            history = state["work"].setdefault("state_operations", {})
            import uuid
            history[str(uuid.uuid4())] = {"topic_id": topic_id, "lease_id": lease["lease_id"],
                "action": action, "caller_uid": peer_uid, "caller_pid": peer_pid,
                "exit_code": result.returncode}
            return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def _reject(message: str) -> Any:
    raise AccessError(message)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.request.settimeout(65)
        try:
            raw = self.rfile.readline(MAX_MESSAGE_BYTES + 1)
            if not raw.endswith(b"\n") or len(raw) > MAX_MESSAGE_BYTES:
                raise AccessError("invalid or oversized request")
            peer_pid, peer_uid, _peer_gid = struct.unpack("3i", self.request.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
            result = self.server.controller.dispatch(json.loads(raw), peer_uid=peer_uid, peer_pid=peer_pid)
            response = {"ok": True, "result": result}
        except Exception as exc:
            if hasattr(exc, "as_dict"):
                error = exc.as_dict()
                error.setdefault("message", str(exc))
            else:
                error = {"code": "ACCESS_DENIED" if isinstance(exc, AccessError) else "OPERATION_FAILED", "message": str(exc)}
            response = {"ok": False, "error": error}
        encoded = json.dumps(response, ensure_ascii=False).encode() + b"\n"
        if len(encoded) > MAX_MESSAGE_BYTES:
            encoded = b'{"ok":false,"error":{"code":"RESULT_TOO_LARGE","message":"request a bounded state view"}}\n'
        try:
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            pass


class ControllerServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, controller: Controller):
        self.controller = controller
        self.socket_path = Path(controller.access["socket_path"])
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        parent = self.socket_path.parent.stat()
        if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o022:
            raise AccessError("controller socket directory must be supervisor-owned and not group/world writable")
        # Refuse to replace an existing socket: that could disconnect a live
        # controller. Explicit recovery removes a verified stale socket.
        super().__init__(str(self.socket_path), _Handler)
        os.chmod(self.socket_path, 0o666)

    def server_close(self) -> None:
        super().server_close()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        controller = Controller(args.root)
        with ControllerServer(controller) as server:
            server.serve_forever()
    except (OSError, AccessError) as exc:
        parser.exit(2, f"controller: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
