"""Explicit permission bootstrap for a drained, migrated managed workspace.

Default invocation is read-only. This command never starts/stops services or
selects models, intervals, active capacity, iteration baselines, or decisions.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .access import (AccessError, initialize_access, load_access,
                     validate_control_protection, validate_topic_protection)
from .control_store import ControlStore

PROTECTED_CONTRACT = frozenset({"TOPIC.md", "AUTHORITY.md", "SEMANTIC-STATE.json"})


def protect_topic(topic_dir: Path, *, agent_uid: int, agent_gid: int, draft: bool = False) -> None:
    """Provision evidence access without giving the agent inventory ownership.

    Caller must have drained this topic and validated its publication. Existing
    text is untouched. Symlinks fail before any ownership mutation.
    """
    paths = [topic_dir, *topic_dir.rglob("*")]
    if any(path.is_symlink() for path in paths):
        raise AccessError("permission bootstrap requires explicit review of topic symlinks")
    protected_contract = frozenset("DRAFT-" + name for name in PROTECTED_CONTRACT) if draft else PROTECTED_CONTRACT
    for name in protected_contract:
        if not (topic_dir / name).is_file():
            raise AccessError(f"approved topic is missing {name}")
    # The parent stays controller-owned, with the sticky bit protecting inventory
    # names against rename/unlink. Evidence descendants belong to the agent UID.
    os.chown(topic_dir, os.geteuid(), agent_gid)
    os.chmod(topic_dir, 0o1770)
    for path in paths[1:]:
        protected = path.parent == topic_dir and (path.name in protected_contract or path.name.startswith(".checkpoint-") or path.name.startswith(".intake-"))
        if protected:
            os.chown(path, os.geteuid(), agent_gid)
            os.chmod(path, 0o640 if path.is_file() else 0o750)
        else:
            os.chown(path, agent_uid, agent_gid)
            os.chmod(path, 0o700 if path.is_dir() else 0o600)
    validate_topic_protection(topic_dir, agent_uid=agent_uid, draft=draft)


def audit(root: Path) -> dict:
    control = ControlStore(root)
    access = load_access(root)
    validate_control_protection(root, agent_uid=access["agent_uid"], agent_gid=access["agent_gid"])
    state = control.snapshot()
    checked = []
    for item in state["queue"]["items"]:
        if item.get("lane", "research") == "research":
            validate_topic_protection(Path(item["cwd"]), agent_uid=access["agent_uid"])
            checked.append(item["id"])
    return {"verified": True, "topics": checked, "active_count": state["configuration"]["active_count"],
            "agent_uid": access["agent_uid"], "socket_path": access["socket_path"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--access-file", type=Path, help="exact access bootstrap JSON; required with --apply")
    parser.add_argument("--apply", action="store_true", help="apply reviewed permissions to a drained workspace")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        if not args.apply:
            print(json.dumps(audit(root), indent=2, sort_keys=True))
            return 0
        if args.access_file is None:
            raise AccessError("--apply requires --access-file")
        access = json.loads(args.access_file.read_text())
        expected = {"schema_version", "agent_uid", "agent_gid", "operator_uids", "socket_path"}
        if not isinstance(access, dict) or set(access) != expected or type(access["schema_version"]) is not int or access["schema_version"] != 1:
            raise AccessError("access bootstrap must match the exact version 1 access schema")
        state = ControlStore(root).snapshot()
        if any(a.get("current") for a in state["work"].get("assignments", {}).values()) or any(i.get("status") == "running" for i in state["queue"]["items"]):
            raise AccessError("drain all executions before changing deployment identities")
        if state["configuration"]["active_count"] != 0:
            raise AccessError("permission bootstrap requires active_count 0")
        existing = root / "state" / "access.json"
        if existing.exists():
            if load_access(root) != access:
                raise AccessError("existing access identity differs; explicit identity migration is required")
        else:
            initialize_access(root, **{k: v for k, v in access.items() if k != "schema_version"})
        for item in state["queue"]["items"]:
            if item.get("lane", "research") == "research":
                protect_topic(Path(item["cwd"]), agent_uid=access["agent_uid"], agent_gid=access["agent_gid"])
        print(json.dumps(audit(root), indent=2, sort_keys=True))
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(2, f"deployment: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
