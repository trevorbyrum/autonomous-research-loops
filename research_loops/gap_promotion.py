"""Recoverable lease-scoped publication of existing automatic gap promotions."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any

from .access import authenticate_capability, current_lease
from .contract_publication import _atomic_write
from .control_store import ControlStore

_TARGETS = ("TOPIC.md", "SEMANTIC-STATE.json", "DECISIONS-LOG.md")


def _prepare(topic_dir: Path, payload: dict) -> dict:
    script = Path(__file__).with_name("chassis") / "gap-policy.py"
    spec = importlib.util.spec_from_file_location("managed_gap_chassis", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory() as temporary:
        staged = Path(temporary)
        for name in (*_TARGETS, "AUTHORITY.md"):
            source = topic_dir / name
            if source.is_symlink():
                raise ValueError(f"refusing symlink managed gap target: {name}")
            if source.exists():
                (staged / name).write_bytes(source.read_bytes())
        try:
            module.promote(staged, obligation_id=payload["obligation_id"], text=payload["text"],
                           source_ref=payload["source_ref"], auto=True)
        except SystemExit as exc:
            raise ValueError(str(exc)) from exc
        semantic = module.semantic_state._load(staged)
        errors = module.semantic_state.structural_errors(staged, semantic)
        if errors:
            raise ValueError("invalid promoted inventory: " + "; ".join(errors))
        return {"files": {name: (staged / name).read_text() for name in _TARGETS},
                "completion_lock": module.semantic_state.inventory_lock(semantic)}


def _commit_promotion(control: ControlStore, state: dict, intent: dict, identity: str) -> dict:
    payload = intent["payload"]
    item = next(i for i in state["queue"]["items"] if i["id"] == payload["topic_id"])
    lock = intent["prepared"]["completion_lock"]
    item["completion_lock"] = lock
    topic = control.ensure_topic_work(state, payload["topic_id"], inventory_version=lock)
    topic["inventory_version"] = lock
    topic["review_state"] = intent["previous_review_state"]
    used = state["work"].setdefault("auto_gap_promotions", {}).setdefault(payload["topic_id"], [])
    used.append({"obligation_id": payload["obligation_id"], "lease_id": intent["lease_id"], "identity": identity})
    result = {"topic_id": payload["topic_id"], "obligation_id": payload["obligation_id"],
              "completion_lock": lock, "remaining": max(0, intent["limit"] - len(used))}
    intent.update(state="committed", result=result)
    return result


def promote(control: ControlStore, *, peer_uid: int, token: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != {"topic_id", "obligation_id", "text", "source_ref"} or any(not isinstance(value, str) or not value.strip() for value in payload.values()):
        raise ValueError("gap.promote requires exact non-empty topic_id, obligation_id, text, source_ref")
    capability = authenticate_capability(control, token=token or "", peer_uid=peer_uid, topic_id=payload["topic_id"])
    if capability["execution_kind"] != "research":
        raise ValueError("gap promotion requires an active ordinary research lease")
    identity = hashlib.sha256(json.dumps([payload["topic_id"], payload["obligation_id"]]).encode()).hexdigest()
    actor = f"research-uid:{peer_uid}"
    with control.transaction(actor=actor, affected_ids=[payload["topic_id"]]) as state:
        if current_lease(state, topic_id=payload["topic_id"], lease_id=capability["lease_id"]) is None:
            raise ValueError("gap promotion lease is no longer current")
        intents = state["work"].setdefault("auto_gap_intents", {})
        prior = intents.get(identity)
        if prior:
            if prior["payload"] != payload:
                raise ValueError("gap obligation id already used with different content")
            if prior["state"] == "committed":
                return dict(prior["result"])
        else:
            if any(i["payload"]["topic_id"] == payload["topic_id"] and i["state"] != "committed" for i in intents.values()):
                raise ValueError("retry the pending gap promotion before another inventory change")
            item = next(i for i in state["queue"]["items"] if i["id"] == payload["topic_id"])
            limit = item.get("gap_auto_limit")
            if item.get("gap_policy") != "auto" or not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
                raise ValueError("operator policy denies auto gap promotion")
            used = state["work"].get("auto_gap_promotions", {}).get(payload["topic_id"], [])
            if len(used) >= limit:
                raise ValueError("operator auto gap budget is exhausted")
            topic = control.ensure_topic_work(state, payload["topic_id"])
            prepared = _prepare(Path(item["cwd"]), payload)
            intents[identity] = {"payload": dict(payload), "state": "prepared", "prepared": prepared,
                                 "topic_dir": item["cwd"], "limit": limit, "lease_id": capability["lease_id"],
                                 "previous_review_state": topic.get("review_state", "eligible")}
            topic["review_state"] = "needs_attention"
    # The full validated bundle is committed before any approved target changes.
    # Serialize publication with all other controller state writes; replay uses
    # exactly this bundle even after only some file replacements completed.
    with control.transaction(actor=actor, affected_ids=[payload["topic_id"]]) as state:
        intent = state["work"]["auto_gap_intents"][identity]
        if intent["state"] == "committed":
            return dict(intent["result"])
        for name, content in intent["prepared"]["files"].items():
            _atomic_write(Path(intent["topic_dir"]) / name, content)
        return _commit_promotion(control, state, intent, identity)
