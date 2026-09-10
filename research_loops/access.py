"""Managed execution identities and lease-scoped control capabilities.

The access file is deployment bootstrap, never a second station configuration.
Only a trusted supervisor can read the database or mint a child capability. The
child gets a capability for its current lease and runs under a different OS uid.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import pwd
from pathlib import Path
from typing import Any

from .control_store import ControlStore, ControlStoreError
from .control_store import ControlScheduler


class AccessError(ControlStoreError):
    pass


def load_access(root: str | Path) -> dict[str, Any]:
    path = Path(root) / "state" / "access.json"
    try:
        metadata = path.stat()
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise AccessError("access.json must be owned by the supervisor and have mode 0600")
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise AccessError(f"managed execution requires protected access.json: {exc}") from exc
    required = {"schema_version", "operator_uids", "agent_uid", "agent_gid", "socket_path"}
    if not isinstance(data, dict) or set(data) != required or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise AccessError("access.json requires schema_version=1, operator_uids, agent_uid, agent_gid, socket_path")
    if not isinstance(data["operator_uids"], list) or not data["operator_uids"]:
        raise AccessError("operator_uids must be a nonempty list of numeric user IDs")
    for value in [*data["operator_uids"], data["agent_uid"], data["agent_gid"]]:
        if type(value) is not int or value < 0:
            raise AccessError("execution identities must be non-negative integer IDs")
    if data["agent_uid"] == 0 or data["agent_uid"] == os.geteuid() or data["agent_uid"] in data["operator_uids"]:
        raise AccessError("research agent UID must differ from root, supervisor and every operator UID")
    if not isinstance(data["socket_path"], str) or not Path(data["socket_path"]).is_absolute():
        raise AccessError("socket_path must be an absolute path")
    return data


def initialize_access(root: str | Path, *, agent_uid: int, agent_gid: int,
                      operator_uids: list[int], socket_path: str) -> dict[str, Any]:
    """Explicit deployment operation. Never invoked by a read or ordinary run."""
    root = Path(root)
    path = root / "state" / "access.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "operator_uids": operator_uids,
               "agent_uid": agent_uid, "agent_gid": agent_gid, "socket_path": socket_path}
    # Validate in memory before publishing: identity requirements don't depend on disk.
    if (type(agent_uid) is not int or type(agent_gid) is not int or agent_uid <= 0 or agent_gid < 0
            or agent_uid == os.geteuid() or not isinstance(operator_uids, list)
            or not operator_uids or any(type(x) is not int or x < 0 for x in operator_uids)
            or agent_uid in operator_uids or not isinstance(socket_path, str)
            or not Path(socket_path).is_absolute()):
        raise AccessError("invalid or overlapping deployment identities/socket path")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path.parent, 0o700)
    return load_access(root)


def current_lease(state: dict[str, Any], *, topic_id: str, lease_id: str) -> dict[str, Any] | None:
    assignments = [*state["work"].get("assignments", {}).values(), state["work"].get("intake_assignment", {})]
    for assignment in assignments:
        lease = assignment.get("current") if isinstance(assignment, dict) else None
        if isinstance(lease, dict) and lease.get("topic_id") == topic_id and lease.get("lease_id") == lease_id:
            return lease
    return None


def issue_capability(control: ControlStore, *, topic_id: str, lease_id: str,
                     agent_uid: int) -> str:
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    with control.transaction(actor="supervisor", affected_ids=[topic_id]) as state:
        lease = current_lease(state, topic_id=topic_id, lease_id=lease_id)
        if lease is None:
            raise AccessError("cannot issue capability without the topic's current execution lease")
        state["work"].setdefault("capabilities", {})[digest] = {
            "topic_id": topic_id, "lease_id": lease_id, "agent_uid": agent_uid,
            "lease_generation": lease["lease_generation"],
            "execution_kind": lease["execution_kind"], "revoked": False,
        }
    return token


def authenticate_capability(control: ControlStore, *, token: str, peer_uid: int,
                            topic_id: str) -> dict[str, Any]:
    if not isinstance(token, str) or not token:
        raise AccessError("execution capability is required")
    digest = hashlib.sha256(token.encode()).hexdigest()
    state = control.snapshot()
    record = state["work"].get("capabilities", {}).get(digest)
    if (not isinstance(record, dict) or record.get("revoked") or record.get("agent_uid") != peer_uid
            or record.get("topic_id") != topic_id):
        raise AccessError("capability does not authorize this caller/topic")
    lease = current_lease(state, topic_id=topic_id, lease_id=record["lease_id"])
    if lease is None or lease.get("lease_generation") != record["lease_generation"]:
        raise AccessError("execution capability belongs to a released or superseded lease")
    return record


def revoke_lease_capabilities(control: ControlStore, lease_id: str) -> None:
    with control.transaction(actor="supervisor") as state:
        for record in state["work"].get("capabilities", {}).values():
            if record.get("lease_id") == lease_id:
                record["revoked"] = True


def validate_topic_protection(topic_dir: Path, *, agent_uid: int, draft: bool = False) -> None:
    """Sticky controller-owned directory permits evidence files, protects inventory.

    A writable directory without the sticky bit would let a worker rename even a
    read-only contract. Individual file chmod alone is not a write boundary.
    """
    parent = topic_dir.stat()
    if parent.st_uid == agent_uid:
        raise AccessError("managed topic directory must be controller-owned")
    if parent.st_mode & 0o022 and not parent.st_mode & stat.S_ISVTX:
        raise AccessError("writable managed topic directory requires sticky-bit protection")
    for ancestor in topic_dir.parents:
        metadata = ancestor.stat()
        if metadata.st_uid == agent_uid or (metadata.st_mode & 0o002 and not metadata.st_mode & stat.S_ISVTX):
            raise AccessError(f"execution identity can replace the managed topic directory through {ancestor}")
    names = ("DRAFT-TOPIC.md", "DRAFT-AUTHORITY.md", "DRAFT-SEMANTIC-STATE.json") if draft else ("TOPIC.md", "AUTHORITY.md", "SEMANTIC-STATE.json")
    for name in names:
        path = topic_dir / name
        if path.is_symlink():
            raise AccessError(f"managed {name} may not be a symlink")
        metadata = path.stat()
        if metadata.st_uid == agent_uid or metadata.st_mode & 0o022:
            raise AccessError(f"managed {name} must be controller-owned and not group/world writable")


def validate_control_protection(root: Path, *, agent_uid: int, agent_gid: int) -> None:
    """Check replacement as well as file-write permissions before granting a lease."""
    state_dir = root / "state"
    if state_dir.is_symlink() or stat.S_IMODE(state_dir.stat().st_mode) & 0o077:
        # POSIX ACL grants surface here as unexpected group bits (a directory
        # shows e.g. 0750 with a "+" flag). Operators read through the
        # controller socket instead — never widen this directory.
        raise AccessError(
            "managed state directory must be a real supervisor-owned directory with mode 0700 "
            f"(found {stat.S_IMODE(state_dir.stat().st_mode):04o}; an ACL grant also causes this — "
            "fix with: setfacl -b state/ && chmod 0700 state/)")
    paths = [root, state_dir, Path(__file__).resolve()]
    for path in paths:
        if path.is_symlink():
            raise AccessError(f"protected deployment path may not be a symlink: {path}")
        for ancestor in [path, *path.parents]:
            metadata = ancestor.stat()
            if metadata.st_uid == agent_uid:
                raise AccessError(f"execution identity owns protected deployment path: {ancestor}")
            writable = bool(metadata.st_mode & 0o002 or
                            (metadata.st_gid == agent_gid and metadata.st_mode & 0o020))
            if writable and not (ancestor.is_dir() and metadata.st_mode & stat.S_ISVTX):
                raise AccessError(f"execution identity can replace protected deployment content: {ancestor}")


def prepare_agent_launch(root: str | Path, topic_id: str, run_id: str) -> tuple[dict[str, str], dict[str, Any]]:
    """Return child-only env and subprocess identity kwargs for an existing lease.

    `run_id` is the scheduler lease ID. The trusted supervisor needs OS permission
    to set uid/gid. Failure is fatal; never fall back to its own identity.
    """
    root = Path(root)
    access = load_access(root)
    validate_control_protection(root, agent_uid=access["agent_uid"], agent_gid=access["agent_gid"])
    control = ControlStore(root)
    snapshot = control.snapshot()
    item = next((i for i in snapshot["queue"]["items"] if i["id"] == topic_id), None)
    if item is None:
        raise AccessError("unknown managed topic")
    lease = current_lease(snapshot, topic_id=topic_id, lease_id=run_id)
    if lease is None:
        raise AccessError("launch lease is no longer current")
    if lease["execution_kind"] == "intake_discovery":
        with control.transaction(actor="intake-launch") as state:
            current = current_lease(state, topic_id=topic_id, lease_id=run_id)
            if not current or state["queue"].get("paused") or state["queue"].get("stopping"):
                raise AccessError("intake launch is paused or its lease has been released")
            current["launch_confirmed"] = True
    else:
        try:
            ControlScheduler(control).confirm_launch(lease["station_id"], run_id)
        except ControlStoreError as exc:
            raise AccessError(f"launch rejected by current station assignment: {exc}") from exc
    topic_dir = Path(item["cwd"])
    validate_topic_protection(topic_dir, agent_uid=access["agent_uid"], draft=lease["execution_kind"] == "intake_discovery")
    token = issue_capability(control, topic_id=topic_id, lease_id=run_id, agent_uid=access["agent_uid"])
    account = pwd.getpwuid(access["agent_uid"])
    return {
        "HOME": account.pw_dir,
        "USER": account.pw_name,
        "LOGNAME": account.pw_name,
        "RESEARCH_LOOP_CONTROLLER_SOCKET": access["socket_path"],
        "RESEARCH_LOOP_EXECUTION_CAPABILITY": token,
        "RESEARCH_LOOP_MANAGED_TOPIC_ID": topic_id,
        "RESEARCH_LOOP_MANAGED_TOPIC_DIR": str(topic_dir.resolve()),
    }, {"user": access["agent_uid"], "group": access["agent_gid"], "extra_groups": []}
