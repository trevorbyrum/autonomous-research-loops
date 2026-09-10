"""Authenticated local controller for managed operator and research operations.

Unix peer credentials establish the caller's OS identity. Research calls also
require a capability tied to the current topic lease; an ``actor`` payload never
grants authority. The service itself is the protected database/file writer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import uuid
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
        routes["checkpoint.retry"] = lambda params: self.retry_checkpoint(params, peer_uid)
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

    def retry_checkpoint(self, params: dict, peer_uid: int) -> dict:
        """Return one failed checkpoint episode to the scheduler's retry state.

        Recovery deliberately preserves every research, delegate, and proposal
        record.  It is an operator disposition, never a new checkpoint run or
        a way to refill a spent budget.
        """
        from .input_schema import strict_object, integer, nonempty_string

        required = {"schema_version", "request_id", "expected_revision", "topic_id", "episode_id", "reason"}
        strict_object(params, path="$", required=required)
        if integer(params["schema_version"], "$.schema_version") != 1:
            raise AccessError("unsupported schema_version")
        for name in ("request_id", "topic_id", "episode_id", "reason"):
            nonempty_string(params[name], "$." + name)
        integer(params["expected_revision"], "$.expected_revision", minimum=0)
        payload = dict(params)
        with self.control.transaction(actor=f"operator-uid:{peer_uid}", operation_id=f"checkpoint-retry:{params['request_id']}", affected_ids=[params["topic_id"], params["episode_id"]]) as state:
            work = state["work"]
            requests = work.setdefault("checkpoint_recovery_requests", {})
            prior = requests.get(params["request_id"])
            if prior:
                if prior.get("payload") != payload:
                    raise AccessError("request_id was already used with different checkpoint recovery content")
                return prior["result"]
            if state["revision"] != params["expected_revision"]:
                raise AccessError("stale expected_revision; refresh checkpoint status before retrying")
            topic = work.get("topics", {}).get(params["topic_id"])
            episode = work.get("episodes", {}).get(params["episode_id"])
            if not isinstance(topic, dict) or not isinstance(episode, dict):
                raise AccessError("unknown managed topic or checkpoint episode")
            if episode.get("topic_id") != params["topic_id"] or topic.get("active_episode_id") != params["episode_id"]:
                raise AccessError("checkpoint episode does not belong to the topic's active review")
            if episode.get("state") not in {"needs_attention", "retry_wait"}:
                raise AccessError("checkpoint retry requires an episode in needs_attention or retry_wait")
            pending = [proposal_id for proposal_id, proposal in work.get("proposals", {}).items()
                       if isinstance(proposal, dict) and proposal.get("episode_id") == params["episode_id"]
                       and proposal.get("status") == "pending"]
            if pending:
                raise AccessError("checkpoint retry cannot replace unresolved proposals")
            currents = [record.get("current") for record in work.get("assignments", {}).values()
                        if isinstance(record, dict)]
            intake_current = work.get("intake_assignment", {}).get("current") if isinstance(work.get("intake_assignment"), dict) else None
            if any(isinstance(current, dict) and current.get("topic_id") == params["topic_id"] for current in [*currents, intake_current]):
                raise AccessError("checkpoint retry requires no current execution lease for the topic")
            if any(isinstance(record, dict) and record.get("status") == "reserved"
                   for record in episode.get("invocations", {}).values()):
                raise AccessError("checkpoint retry requires all delegate invocations to finish")
            old_failure = episode.pop("failure_reason", None)
            episode.setdefault("recovery_audit", []).append({
                "request_id": params["request_id"], "reason": params["reason"],
                "operator_uid": peer_uid, "previous_state": episode.get("state"),
                "previous_failure_reason": old_failure,
            })
            episode["state"] = "retry_wait"
            topic["review_state"] = "checkpoint_due"
            result = {"topic_id": params["topic_id"], "episode_id": params["episode_id"],
                      "state": "retry_wait", "review_state": "checkpoint_due",
                      "revision": state["revision"] + 1}
            requests[params["request_id"]] = {"payload": payload, "result": result}
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
            # The digest lets the reservation transaction re-validate this
            # capability at spend time — authentication above reads a
            # snapshot, and a lease can be released/revoked in between.
            digest = hashlib.sha256(str(request.get("token")).encode()).hexdigest()
            return dispatch(self.control, params, capability_digest=digest)
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
            # A minimal environment, not the controller's own: this bridge
            # runs with the supervisor's identity, and semantic-state.py needs
            # nothing beyond an interpreter path (2026-09-09 review —
            # confused-deputy hardening; a dedicated execution identity for
            # the bridge is a recorded follow-up in docs/managed-stations.md).
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "LANG": os.environ.get("LANG", "C.UTF-8")}
            command = [sys.executable, str(Path(__file__).parent / "chassis" / "semantic-state.py"),
                       action, str(topic_dir), *arguments]
            result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=60)
            # A file operation's audit is explicit even though the controller's
            # main queue/work counters intentionally do not change.
            history = state["work"].setdefault("state_operations", {})
            from .control_store import utc_now
            history[str(uuid.uuid4())] = {"at": utc_now(), "topic_id": topic_id,
                "lease_id": lease["lease_id"],
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
            elif isinstance(exc, AccessError):
                error = {"code": "ACCESS_DENIED", "message": str(exc)}
            else:
                # Unstructured internals go to the journal, not the peer: an
                # authenticated caller is not entitled to raw tracebacks or
                # filesystem paths from arbitrary exceptions.
                import traceback
                print(f"controller: unhandled {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                      file=sys.stderr, flush=True)
                error = {"code": "OPERATION_FAILED",
                         "message": f"{type(exc).__name__}: see the controller journal"}
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
        # Peer-credential auth is the real gate, but do not throw away
        # defense-in-depth: only the supervisor's group (which deployment
        # gives to the agent account and to operators) may even connect.
        try:
            os.chown(self.socket_path, os.geteuid(), controller.access["agent_gid"])
            os.chmod(self.socket_path, 0o660)
        except PermissionError:
            # A non-root supervisor cannot give the socket to the agent
            # group, and 0660 under its own group would lock the agent
            # account out entirely — peer-credential auth remains the sole
            # gate there (the pre-hardening behavior). Root deployments get
            # the group-scoped socket above.
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
