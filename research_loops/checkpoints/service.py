"""Durable checkpoint state transitions over the controller work ledger."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


class CheckpointError(RuntimeError):
    """An actionable checkpoint control-plane error."""

    def __init__(self, code: str, message: str, field: str | None = None):
        self.code, self.field = code, field
        super().__init__(message)

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "path": self.field or "$", "explanation": str(self),
                "next_operation": "refresh controller status and correct the indicated field before retrying"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# Serializes decision publication for stores without a filesystem root (test
# doubles); real stores use the state/publication.lock flock, which also
# covers multiple processes.
import threading
_PUBLICATION_PROCESS_LOCK = threading.Lock()


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CheckpointError("VALIDATION_ERROR", f"{field} must be a non-empty string", field)
    return value


def _require_int(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise CheckpointError("VALIDATION_ERROR", f"{field} must be an integer", field)
    return value


def _work(state: dict[str, Any]) -> dict[str, Any]:
    work = state.setdefault("work", {})
    if not isinstance(work, dict):
        raise CheckpointError("VALIDATION_ERROR", "work ledger is not an object")
    for name in ("topics", "runs", "triggers", "episodes", "proposals", "decisions", "assignments"):
        value = work.setdefault(name, {})
        if not isinstance(value, dict):
            raise CheckpointError("VALIDATION_ERROR", f"work.{name} is not an object")
    return work


def _topic(work: dict[str, Any], topic_id: str, inventory_version: str | None = None) -> dict[str, Any]:
    from ..control_store import default_topic_record
    topics = work["topics"]
    topic = topics.get(topic_id)
    if topic is None:
        topic = default_topic_record(topic_id, inventory_version or "unknown")
        topics[topic_id] = topic
    if inventory_version is not None:
        topic["inventory_version"] = inventory_version
    return topic


def _checkpoint_policy(state: Mapping[str, Any]) -> Mapping[str, Any]:
    config = state.get("configuration")
    if not isinstance(config, Mapping):
        return {}
    checkpoints = config.get("checkpoints")
    return checkpoints if isinstance(checkpoints, Mapping) else {}


def _enabled(policy: Mapping[str, Any]) -> bool:
    return policy.get("enabled", True) is True


def _trigger_id(topic_id: str, kind: str, ordinal: int, inventory_version: str) -> str:
    raw = f"{topic_id}\0{kind}\0{ordinal}\0{inventory_version}".encode()
    return f"trigger-{hashlib.sha256(raw).hexdigest()[:24]}"


def _new_episode(work: dict[str, Any], topic: dict[str, Any], trigger_ids: list[str]) -> dict[str, Any]:
    episode_id = f"checkpoint-{uuid.uuid4()}"
    episode = {
        "episode_id": episode_id,
        "topic_id": topic["topic_id"],
        "triggered_after_research_iteration": topic["research_iterations_completed"],
        "trigger_ids": trigger_ids,
        "inventory_version": topic["inventory_version"],
        "state": "due",
        "resolved_agent_pair": None,
        "configuration_revision": None,
        "prompt_protocol_version": "checkpoint-protocol-v1",
        "attempt_history": [],
        "remaining_budgets": {"delegate_launches": 4, "final_proposals": min(2, int(topic.get("proposal_allowance_remaining", 2))), "repair_exchanges": 1, "infra_refunds_remaining": 2},
        "prior_review_reference": None,
        "result_reference": None,
    }
    work["episodes"][episode_id] = episode
    topic["active_episode_id"] = episode_id
    # This exact scheduler gate reserves the topic for a separate checkpoint
    # lease before another ordinary ordinal can claim it.
    topic["review_state"] = "checkpoint_due"
    return episode


def _coalesce_episode(work: dict[str, Any], topic: dict[str, Any], trigger_ids: list[str]) -> dict[str, Any]:
    active_id = topic.get("active_episode_id")
    episode = work["episodes"].get(active_id) if isinstance(active_id, str) else None
    if isinstance(episode, dict) and episode.get("state") in {"due", "checkpoint_running", "retry_wait", "awaiting_operator", "publishing_decision", "needs_attention"}:
        for trigger_id in trigger_ids:
            if trigger_id not in episode["trigger_ids"]:
                episode["trigger_ids"].append(trigger_id)
        return episode
    return _new_episode(work, topic, trigger_ids)


def accept_research_completion(
    control: Any, *, topic_id: str, run_id: str, station_id: int, inventory_version: str,
    accepted: bool, deepening_entry: bool = False, lease_generation: int | None = None,
) -> dict[str, Any]:
    """Account for one accepted *ordinary* research completion exactly once.

    The caller must have already applied ordinary scientific completion validation.
    Failed/interrupted work deliberately has no accounting effect.
    """
    _require_string(topic_id, "topic_id"); _require_string(run_id, "run_id")
    _require_string(inventory_version, "inventory_version")
    _require_int(station_id, "station_id")
    if not isinstance(accepted, bool):
        raise CheckpointError("VALIDATION_ERROR", "accepted must be boolean", "accepted")
    with control.transaction(actor="runner", operation_id=f"research-completion:{run_id}") as state:
        work = _work(state)
        prior = work["runs"].get(run_id)
        if prior is not None:
            if prior.get("topic_id") != topic_id:
                raise CheckpointError("DUPLICATE_REQUEST_CONFLICT", "run_id belongs to another topic", "run_id")
            if "accounting_result" in prior:
                return copy.deepcopy(prior["accounting_result"])
            if prior.get("state") not in (None, "started"):
                # Finished-without-accounting is an inconsistent record, not
                # an in-progress run — never recount it (Astra qualification
                # on the missing-accounting_result branch).
                raise CheckpointError("REVISION_CONFLICT", "run record already finished without accounting; refusing to recount", "run_id")
            # A claim-time "started" record (written in the lease-minting
            # transaction) is this same run in progress, not a replay.
        elif int(work.get("pruned_runs", {}).get(topic_id, 0)):
            # Once compaction has pruned ANY of this topic's runs, an unknown
            # run_id could be a pruned historical run replaying (Astra F10):
            # counting requires the run's own current lease as authority.
            from ..access import current_lease
            if current_lease(state, topic_id=topic_id, lease_id=run_id) is None:
                raise CheckpointError("REVISION_CONFLICT",
                                      "run_id has no record and no current lease; a pruned historical run cannot be recounted", "run_id")
        topic = _topic(work, topic_id, inventory_version)
        run = dict(prior) if prior is not None else {}
        run.update({"run_id": run_id, "topic_id": topic_id, "station_id": station_id,
                    "lease_generation": lease_generation if lease_generation is not None else run.get("lease_generation"),
                    "accepted": accepted, "state": "finished", "ended_at": _now(),
                    "ordinal": None, "completion_accounted": False})
        if not accepted:
            result = {"topic_id": topic_id, "run_id": run_id, "accepted": False,
                      "research_iterations_completed": topic["research_iterations_completed"],
                      "next_research_ordinal": topic["next_research_ordinal"], "episode_id": topic.get("active_episode_id")}
            run["accounting_result"] = result; work["runs"][run_id] = run
            return copy.deepcopy(result)
        ordinal = int(topic["research_iterations_completed"]) + 1
        topic["research_iterations_completed"] = ordinal
        topic["next_research_ordinal"] = ordinal + 1
        topic["last_accepted_run_id"] = run_id
        topic["row_revision"] = int(topic.get("row_revision", 0)) + 1
        run.update({"ordinal": ordinal, "completion_accounted": True})
        policy = _checkpoint_policy(state)
        # Each trigger carries its kind from creation; the stable hashed ID is
        # replay-safe and stays opaque (the review-flagged no-op reconstruction
        # ternary is gone).
        triggers: list[tuple[str, str]] = []
        if _enabled(policy):
            every = policy.get("every_research_iterations", 25)
            if isinstance(every, int) and not isinstance(every, bool) and every > 0 and ordinal % every == 0:
                triggers.append((_trigger_id(topic_id, "cadence", ordinal, inventory_version), "cadence"))
            entries = topic.setdefault("deepening_entries", {})
            first_deepening = deepening_entry and inventory_version not in entries
            if first_deepening and policy.get("on_deepening_entry", True) is True:
                triggers.append((_trigger_id(topic_id, "deepening_entry", ordinal, inventory_version), "deepening_entry"))
            if deepening_entry:
                entries.setdefault(inventory_version, {"entered_after_ordinal": ordinal, "triggered": False})
        trigger_ids = [trigger_id for trigger_id, _ in triggers]
        for trigger_id, kind in triggers:
            work["triggers"].setdefault(trigger_id, {"trigger_id": trigger_id, "topic_id": topic_id, "kind": kind,
                "research_ordinal": ordinal, "inventory_version": inventory_version, "episode_id": None, "handled": False})
        if trigger_ids:
            episode = _coalesce_episode(work, topic, trigger_ids)
            for trigger_id in trigger_ids:
                work["triggers"][trigger_id]["episode_id"] = episode["episode_id"]
            entry = topic.get("deepening_entries", {}).get(inventory_version)
            if isinstance(entry, dict) and any(kind == "deepening_entry" for _, kind in triggers): entry["triggered"] = True
        result = {"topic_id": topic_id, "run_id": run_id, "accepted": True, "ordinal": ordinal,
                  "research_iterations_completed": ordinal, "next_research_ordinal": ordinal + 1,
                  "episode_id": topic.get("active_episode_id"), "review_state": topic["review_state"]}
        run["accounting_result"] = result; work["runs"][run_id] = run
        return copy.deepcopy(result)


def resolve_checkpoint_agents(state: Mapping[str, Any]) -> dict[str, str]:
    config = state.get("configuration")
    if not isinstance(config, Mapping): raise CheckpointError("VALIDATION_ERROR", "configuration is missing")
    policy = _checkpoint_policy(state)
    source = policy.get("agent_source", "station_1")
    if source == "explicit":
        return {"primary_profile": _require_string(policy.get("primary_profile"), "checkpoints.primary_profile"),
                "secondary_profile": _require_string(policy.get("secondary_profile"), "checkpoints.secondary_profile")}
    if source != "station_1": raise CheckpointError("VALIDATION_ERROR", "checkpoints.agent_source must be station_1 or explicit")
    stations = config.get("stations")
    if not isinstance(stations, list): raise CheckpointError("VALIDATION_ERROR", "configuration.stations is missing")
    station_one = next((x for x in stations if isinstance(x, Mapping) and x.get("id") == 1), None)
    if station_one is None: raise CheckpointError("VALIDATION_ERROR", "station 1 configuration is missing")
    return {"primary_profile": _require_string(station_one.get("primary_profile"), "stations[1].primary_profile"),
            "secondary_profile": _require_string(station_one.get("secondary_profile"), "stations[1].secondary_profile")}


def _material_context_digest(state: Mapping[str, Any], topic_id: str) -> str:
    item = next((x for x in state.get("queue", {}).get("items", []) if isinstance(x, Mapping) and x.get("id") == topic_id), {})
    root = Path(str(item.get("cwd", ""))); parts: list[bytes] = []
    for name in ("TOPIC.md", "AUTHORITY.md", "SEMANTIC-STATE.json", "SOURCE-LEDGER.json", "SOURCE-LEDGER.md", "SYNTHESIS.md"):
        path = root / name
        if path.is_file() and not path.is_symlink(): parts.extend((name.encode(), b"\0", path.read_bytes(), b"\0"))
    work = state.get("work", {}); topic = work.get("topics", {}).get(topic_id, {})
    decisions = [v for v in work.get("decisions", {}).values() if isinstance(v, Mapping) and (v.get("topic_id") == topic_id or v.get("result", {}).get("topic_id") == topic_id)]
    parts.append(json.dumps({"inventory_version": topic.get("inventory_version"), "decisions": decisions, "allowance": topic.get("proposal_allowance_remaining", 2), "resets": topic.get("proposal_allowance_resets", [])}, sort_keys=True, default=str).encode())
    return hashlib.sha256(b"".join(parts)).hexdigest()


def start_checkpoint(control: Any, *, episode_id: str, station_id: int, run_id: str) -> dict[str, Any]:
    """Claim a due episode and snapshot its shared pair exactly once."""
    with control.transaction(actor="runner", operation_id=f"checkpoint-start:{run_id}") as state:
        work = _work(state); episode = work["episodes"].get(episode_id)
        if not isinstance(episode, dict): raise CheckpointError("VALIDATION_ERROR", "unknown episode_id", "episode_id")
        if episode.get("state") == "checkpoint_running" and episode.get("run_id") == run_id: return copy.deepcopy(episode)
        if episode.get("state") not in {"due", "retry_wait"}: raise CheckpointError("AWAITING_OPERATOR", f"episode is {episode.get('state')}", "episode_id")
        # Episodes created before the refund budget existed get the documented
        # cap on their next start instead of silently having none.
        episode.setdefault("remaining_budgets", {}).setdefault("infra_refunds_remaining", 2)
        resolver = getattr(control, "resolve_checkpoint_pair", None)
        if episode.get("resolved_agent_pair") is None:
            if not callable(resolver):
                raise CheckpointError("VALIDATION_ERROR", "controller does not expose resolved checkpoint profiles")
            # Under executing_station, the pair is the CLAIMING station's own
            # (operator ruling 2026-09-10: models are managed per station,
            # and reviews are served by whichever station picks them up).
            try:
                episode["resolved_agent_pair"] = resolver(state, station_id=station_id)
            except TypeError:
                episode["resolved_agent_pair"] = resolver(state)
        episode["configuration_revision"] = state.get("revision")
        digest = _material_context_digest(state, episode["topic_id"])
        episode["material_context_digest"] = digest
        prior = next((x for x in work["episodes"].values() if isinstance(x, dict) and x.get("topic_id") == episode["topic_id"] and x.get("state") in {"complete_without_proposals", "complete_with_decisions"} and x.get("material_context_digest") == digest), None)
        episode["prior_review_reference"] = prior.get("episode_id") if prior else None
        episode["state"] = "checkpoint_running"; episode["run_id"] = run_id; episode["station_id"] = station_id
        episode["attempt_history"].append({"run_id": run_id, "station_id": station_id, "started_at": _now()})
        episode["delegate_invocation_ids"] = {
            role: f"{episode_id}-{role}-{len(episode['attempt_history'])}"
            for role in ("preparation", "counter", "repair_response", "repair_assessment")}
        # A supervisor retry continues the same bounded review. Successful
        # role calls already consumed their slot; expose their replayable IDs
        # rather than directing the primary toward a forbidden second call.
        for invocation_id, record in episode.get("invocations", {}).items():
            if record.get("status") == "finished" and record.get("exit_code") == 0:
                episode["delegate_invocation_ids"][record["role"]] = invocation_id
        return copy.deepcopy(episode)


def reserve_delegate_launch(control: Any, *, episode_id: str, lease_id: str,
                            invocation_id: str, role: str,
                            capability_digest: str | None = None) -> dict[str, Any]:
    """Atomically reserve one bounded checkpoint delegate invocation.

    The controller calls this after authenticating the lease capability.  An
    adapter cannot mint a role, reset a budget, or spend a slot twice.
    """
    _require_string(episode_id, "episode_id"); _require_string(lease_id, "lease_id")
    _require_string(invocation_id, "invocation_id")
    # This identifier is later used as part of a controller-owned report name.
    # Keep it a bounded filename component even though reports are not written
    # into a worker-writable directory.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", invocation_id):
        raise CheckpointError("VALIDATION_ERROR", "invocation_id must be a slug of at most 128 characters", "invocation_id")
    roles = {"preparation": "secondary", "counter": "primary", "repair_response": "secondary", "repair_assessment": "primary"}
    if role not in roles: raise CheckpointError("VALIDATION_ERROR", "invalid checkpoint delegate role", "role")
    with control.transaction(actor="checkpoint-broker", operation_id=f"checkpoint-delegate:{invocation_id}") as state:
        work = _work(state); episode = work["episodes"].get(episode_id)
        if not isinstance(episode, dict) or episode.get("state") != "checkpoint_running":
            raise CheckpointError("AWAITING_OPERATOR", "episode is not running", "episode_id")
        if episode.get("run_id") != lease_id: raise CheckpointError("REVISION_CONFLICT", "lease does not own this episode", "lease_id")
        if capability_digest is not None:
            # Close the auth-to-spend window: the controller authenticated a
            # snapshot; re-validate the same capability and lease currency in
            # the transaction that actually spends the slot.
            from ..access import current_lease
            capability = state.get("work", {}).get("capabilities", {}).get(capability_digest)
            if (not isinstance(capability, Mapping) or capability.get("revoked")
                    or capability.get("lease_id") != lease_id):
                raise CheckpointError("REVISION_CONFLICT", "execution capability was revoked before this delegate launch")
            lease = current_lease(state, topic_id=str(episode.get("topic_id")), lease_id=lease_id)
            if lease is None or lease.get("lease_generation") != capability.get("lease_generation"):
                raise CheckpointError("REVISION_CONFLICT", "checkpoint lease was released before this delegate launch")
        invocations = episode.setdefault("invocations", {})
        prior = invocations.get(invocation_id)
        if isinstance(prior, dict):
            if prior.get("role") != role: raise CheckpointError("DUPLICATE_REQUEST_CONFLICT", "invocation_id has another role", "invocation_id")
            replay = copy.deepcopy(prior)
            replay["_new_reservation"] = False
            return replay
        if any(isinstance(record, Mapping) and record.get("status") == "reserved" for record in invocations.values()):
            raise CheckpointError("REVISION_CONFLICT", "another checkpoint delegate invocation is still running")
        budgets = episode.setdefault("remaining_budgets", {})
        if int(budgets.get("delegate_launches", 0)) <= 0: raise CheckpointError("BUDGET_EXHAUSTED", "checkpoint delegate launch budget is exhausted")
        successful = lambda named: any(isinstance(record, Mapping) and record.get("role") == named and record.get("status") == "finished" and record.get("exit_code") == 0 for record in invocations.values())
        if role in {"preparation", "counter", "repair_response", "repair_assessment"} and successful(role):
            raise CheckpointError("REVISION_CONFLICT", f"successful {role} invocation already exists")
        if role == "repair_response":
            if successful("repair_assessment"):
                raise CheckpointError("REVISION_CONFLICT", "a completed repair assessment already exists")
            if not successful("counter") or int(budgets.get("delegate_launches", 0)) < 2 or int(budgets.get("repair_exchanges", 0)) <= 0:
                raise CheckpointError("BUDGET_EXHAUSTED", "repair response requires successful counter, one exchange, and two launch slots")
            budgets["repair_exchanges"] -= 1; episode["repair_phase"] = "response_reserved"
        elif role == "repair_assessment":
            if episode.get("repair_phase") != "response_finished" or int(budgets.get("delegate_launches", 0)) < 1:
                raise CheckpointError("REVISION_CONFLICT", "repair assessment requires the successful reserved repair response")
            episode["repair_phase"] = "assessment_reserved"
        pair = episode.get("resolved_agent_pair")
        if not isinstance(pair, Mapping): raise CheckpointError("VALIDATION_ERROR", "episode has no resolved agent pair")
        seat = roles[role]
        profile = pair.get(f"{seat}_profile") or pair.get(seat)
        if not isinstance(profile, (str, Mapping)): raise CheckpointError("VALIDATION_ERROR", f"episode lacks resolved {seat} profile")
        budgets["delegate_launches"] -= 1
        record = {"invocation_id": invocation_id, "role": role, "seat": seat, "profile": copy.deepcopy(profile), "lease_id": lease_id, "reserved_at": _now(), "status": "reserved"}
        invocations[invocation_id] = record
        created = copy.deepcopy(record)
        created["_new_reservation"] = True
        return created


# Exit codes that mean the INFRASTRUCTURE failed (timeout/spawn error/empty
# response), not that the model produced an invalid result. These may refund
# a launch slot under the episode's bounded infra-refund allowance; exit 78
# (a well-formed run returning garbage) deliberately stays spent.
_INFRA_EXIT_CODES = frozenset({70, 124})


def record_delegate_result(control: Any, *, episode_id: str, invocation_id: str,
                           exit_code: int, output_reference: str | None = None,
                           delegate_result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Durably close a previously reserved invocation.

    Semantically failed slots stay spent; infrastructure failures refund the
    launch slot up to the episode's infra_refunds_remaining cap (operator
    decision 2026-09-09: flaky providers must not force a retry cycle, but the
    anti-abuse launch bound stays hard)."""
    with control.transaction(actor="checkpoint-broker", operation_id=f"checkpoint-delegate-result:{invocation_id}") as state:
        episode = _work(state)["episodes"].get(episode_id)
        if not isinstance(episode, dict) or not isinstance(episode.get("invocations", {}).get(invocation_id), dict):
            raise CheckpointError("VALIDATION_ERROR", "unknown checkpoint invocation")
        record = episode["invocations"][invocation_id]
        if record.get("status") != "reserved": return copy.deepcopy(record)
        record.update({"status": "finished", "exit_code": _require_int(exit_code, "exit_code"), "output_reference": output_reference, "finished_at": _now()})
        if delegate_result is not None:
            record["delegate_result"] = copy.deepcopy(dict(delegate_result))
        if record.get("role") == "repair_response": episode["repair_phase"] = "response_finished" if exit_code == 0 else "response_failed"
        elif record.get("role") == "repair_assessment": episode["repair_phase"] = "assessment_finished" if exit_code == 0 else "assessment_failed"
        if exit_code in _INFRA_EXIT_CODES:
            budgets = episode.setdefault("remaining_budgets", {})
            refunds = int(budgets.get("infra_refunds_remaining", 0))
            if refunds > 0:
                budgets["infra_refunds_remaining"] = refunds - 1
                budgets["delegate_launches"] = int(budgets.get("delegate_launches", 0)) + 1
                record["infra_refund"] = True
                # An infrastructure failure never obtained the exchange it
                # reserved (Astra F7): restore the repair state machine so
                # the SAME uncompleted exchange/assessment can retry — this
                # authorizes a retry, never a second successful exchange.
                if record.get("role") == "repair_response":
                    budgets["repair_exchanges"] = int(budgets.get("repair_exchanges", 0)) + 1
                    episode["repair_phase"] = None
                elif record.get("role") == "repair_assessment":
                    episode["repair_phase"] = "response_finished"
        return copy.deepcopy(record)


def _delegate_ledger_append(topic_root: Path, identity: Mapping[str, Any], record: dict[str, Any]) -> None:
    """Best-effort 9·0 delegation-coverage line in the topic's delegate ledger.

    Written after the provider call returns (the durable pre-launch evidence
    is the reserved invocation record in the controller store); a launch line
    with no usage line reads as an unobserved outcome, which is accurate here
    — checkpoint delegate calls have no usage capture. Never fails the call.

    SECURITY (Astra F1, 2026-09-10): this append runs under the SUPERVISOR
    identity inside an agent-owned logs directory. Every path component is
    opened O_NOFOLLOW via directory descriptors and ownership is transferred
    on the opened inode (fchown), so an agent-planted symlink — for the file,
    its parent, or a swap between create and chown — can never redirect a
    supervisor write or ownership change to a protected file.
    """
    import stat as stat_module

    root_fd = logs_fd = file_fd = None
    try:
        root_fd = os.open(topic_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            logs_fd = os.open("logs", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        except FileNotFoundError:
            return
        try:
            # O_NONBLOCK (Astra R2-2): opening an agent-planted FIFO for
            # writing with no reader would otherwise block the controller
            # BEFORE the regular-file check can run; nonblocking, it fails
            # with ENXIO immediately, and for the regular file we expect it
            # is a write-path no-op.
            file_fd = os.open("delegate-usage.jsonl",
                              os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
                              dir_fd=logs_fd)
            created = False
        except FileNotFoundError:
            file_fd = os.open("delegate-usage.jsonl",
                              os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                              0o644, dir_fd=logs_fd)
            created = True
        info = os.fstat(file_fd)
        if not stat_module.S_ISREG(info.st_mode):
            return
        os.write(file_fd, (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8"))
        if created and isinstance(identity.get("user"), int) and isinstance(identity.get("group"), int):
            # On the INODE we hold open — the agent's own delegate wrapper
            # must be able to keep appending, and a pathname chown could be
            # redirected by a post-create swap.
            os.fchown(file_fd, identity["user"], identity["group"])
    except OSError:
        pass
    finally:
        for fd in (file_fd, logs_fd, root_fd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


def execute_delegate(control: Any, *, episode_id: str, lease_id: str, invocation_id: str, role: str, prompt: str,
                     capability_digest: str | None = None) -> dict[str, Any]:
    """Reserve then run one resolved delegate under the lease OS identity."""
    _require_string(prompt, "prompt")
    if len(prompt.encode("utf-8")) > 64 * 1024:
        raise CheckpointError("VALIDATION_ERROR", "checkpoint delegate prompt exceeds 64 KiB", "prompt")
    launch = reserve_delegate_launch(control, episode_id=episode_id, lease_id=lease_id, invocation_id=invocation_id, role=role,
                                     capability_digest=capability_digest)
    new_reservation = launch.pop("_new_reservation", False)
    if launch.get("status") == "finished":
        # The idempotency key identifies one bounded provider call.  Replaying
        # a controller request must return its evidence, never launch again.
        stored = launch.get("delegate_result")
        return {"invocation": launch, "result": copy.deepcopy(stored) if isinstance(stored, dict) else None,
                "stderr": "" if launch.get("exit_code") == 0 else "delegate invocation already finished"}
    # Another request with this id may have reserved the bounded slot while
    # this caller was waiting.  It must never result in a second subprocess.
    if not new_reservation or launch.get("status") != "reserved" or launch.get("reserved_at") is None:
        raise CheckpointError("REVISION_CONFLICT", "checkpoint delegate invocation is already running")
    profile = launch["profile"]
    if not isinstance(profile, Mapping): raise CheckpointError("VALIDATION_ERROR", "resolved profile record is unavailable")
    executable, argv = profile.get("executable"), profile.get("argv")
    if not isinstance(executable, str) or not isinstance(argv, list) or any(not isinstance(arg, str) for arg in argv):
        raise CheckpointError("VALIDATION_ERROR", "resolved profile has invalid executable arguments")
    state = control.snapshot(); episode = _work(state)["episodes"].get(episode_id)
    if not isinstance(episode, Mapping): raise CheckpointError("VALIDATION_ERROR", "unknown episode_id")
    item = next((entry for entry in state["queue"].get("items", []) if entry.get("id") == episode.get("topic_id")), None)
    if not isinstance(item, Mapping): raise CheckpointError("VALIDATION_ERROR", "episode topic is not queued")
    identity: dict[str, Any] = {}
    try:
        from ..access import prepare_agent_launch
        additions, identity = prepare_agent_launch(control.root, str(episode["topic_id"]), lease_id)
        env = os.environ.copy(); env.update(additions)
        env.update({"RESEARCH_LOOP_CHECKPOINT_EPISODE": episode_id, "RESEARCH_LOOP_CHECKPOINT_INVOCATION": invocation_id, "RESEARCH_LOOP_CHECKPOINT_ROLE": role, "RESEARCH_LOOP_PROFILE": str(profile.get("id") or "")})
        task = {"schema_version": 1, "episode_id": episode_id, "invocation_id": invocation_id,
                "role": role, "profile": profile, "prompt": prompt,
                "protocol_path": str((Path(__file__).parent / "prompts" / "protocol.md").resolve()),
                "instructions": "Perform only this bounded delegate role, not the primary checkpoint. Return only a JSON object with exactly the fields shown in required_result. Replace findings and limitations with arrays of strings containing your substantive review. Do not issue a checkpoint-result object or launch other delegates.",
                "required_result": {"schema_version": 1, "invocation_id": invocation_id, "role": role,
                                    "status": "complete", "findings": [], "limitations": []}}
        prompt_text = json.dumps(task, sort_keys=True)
        from .runner import launch_registered_profile
        try:
            exit_code, output = launch_registered_profile(profile, prompt_text, cwd=str(item["cwd"]),
                                                          env=env, identity=identity, timeout_seconds=900)
        except ValueError as exc:
            raise CheckpointError("VALIDATION_ERROR", str(exc)) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        # Keep the provider's own stderr when a timeout captured one — "auth
        # error from the provider" and "binary missing" must stay
        # distinguishable in the recorded report.
        stderr_tail = ""
        if isinstance(exc, subprocess.TimeoutExpired) and exc.stderr:
            raw = exc.stderr if isinstance(exc.stderr, str) else exc.stderr.decode(errors="replace")
            stderr_tail = raw[-1000:]
        output = str(exc) + (f"\nprovider stderr tail:\n{stderr_tail}" if stderr_tail else "")
        exit_code = 124
    if exit_code == 0 and not output.strip():
        # An empty response on a zero exit is a capability failure, never a
        # valid (or even parseable) result — classify as infrastructure.
        output, exit_code = "delegate produced no output", 70
    topic_root = Path(str(item["cwd"])).resolve()
    _delegate_ledger_append(topic_root, identity, {
        "ts": _now(), "event": "launch",
        "model": str(profile.get("model") or "unknown"), "role": role,
        "checkpoint_episode": episode_id,
    })
    report_dir = topic_root / ".checkpoint-reports"
    try:
        report_dir.mkdir(mode=0o750, exist_ok=True)
        if report_dir.is_symlink() or not report_dir.is_dir():
            raise CheckpointError("VALIDATION_ERROR", "checkpoint report directory is unsafe")
        if isinstance(identity.get("group"), int):
            os.chown(report_dir, os.geteuid(), identity["group"])
        os.chmod(report_dir, 0o750)
    except OSError as exc:
        raise CheckpointError("VALIDATION_ERROR", f"cannot prepare protected checkpoint report directory: {exc}") from exc
    report_name = f"checkpoint-{episode_id}-{invocation_id}.json"
    output_path = report_dir / report_name
    if len(output.encode("utf-8")) > 256 * 1024:
        output, exit_code = output[:256 * 1024], 78
    delegate_result: dict[str, Any] | None = None
    if exit_code == 0:
        try:
            candidate = json.loads(output)
            if (not isinstance(candidate, dict) or set(candidate) != {"schema_version", "invocation_id", "role", "status", "findings", "limitations"}
                    or type(candidate.get("schema_version")) is not int or candidate.get("schema_version") != 1
                    or candidate.get("invocation_id") != invocation_id or candidate.get("role") != role
                    or candidate.get("status") != "complete"
                    or not isinstance(candidate.get("findings"), list) or not isinstance(candidate.get("limitations"), list)
                    or any(not isinstance(value, str) for field in ("findings", "limitations") for value in candidate[field])):
                raise ValueError("invalid structured delegate result")
            delegate_result = candidate
        except (ValueError, json.JSONDecodeError):
            exit_code = 78
    # The agent has no write permission to this directory.  A controller-owned
    # temporary file plus atomic replace prevents a planted symlink from being
    # treated as counter evidence.
    try:
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=report_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(output)
            handle.flush()
            os.fsync(handle.fileno())
        if isinstance(identity.get("group"), int):
            os.chown(temporary, os.geteuid(), identity["group"])
        os.chmod(temporary, 0o640)
        os.replace(temporary, output_path)
    except OSError as exc:
        raise CheckpointError("VALIDATION_ERROR", f"cannot write protected checkpoint report: {exc}") from exc
    result = record_delegate_result(control, episode_id=episode_id, invocation_id=invocation_id, exit_code=exit_code,
                                    output_reference=str(output_path.relative_to(topic_root)), delegate_result=delegate_result)
    return {"invocation": result, "result": delegate_result, "stderr": "" if exit_code == 0 else output}


def finish_checkpoint(control: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    """Persist a validated structured result; zero proposals auto-resumes."""
    from .runner import validate_checkpoint_result
    parsed = validate_checkpoint_result(result)
    with control.transaction(actor="runner", operation_id=f"checkpoint-finish:{parsed['run_id']}") as state:
        work = _work(state); episode = work["episodes"].get(parsed["episode_id"])
        if not isinstance(episode, dict): raise CheckpointError("VALIDATION_ERROR", "unknown episode_id", "episode_id")
        if episode.get("result_reference") == parsed["run_id"]: return {"episode_id": episode["episode_id"], "state": episode["state"], "replayed": True}
        if episode.get("state") != "checkpoint_running" or episode.get("run_id") != parsed["run_id"]: raise CheckpointError("REVISION_CONFLICT", "checkpoint result does not match active run", "run_id")
        if parsed["inventory_version"] != episode.get("inventory_version") or set(parsed["trigger_ids"]) != set(episode["trigger_ids"]):
            raise CheckpointError("REVISION_CONFLICT", "checkpoint result context is stale")
        episode.setdefault("results", {})[parsed["run_id"]] = copy.deepcopy(parsed)
        topic = _topic(work, episode["topic_id"])
        if not parsed["complete"]:
            episode["state"] = "needs_attention"; episode["failure_reason"] = parsed["limitations"]
            topic["review_state"] = "needs_attention"
            return {"episode_id": episode["episode_id"], "state": "needs_attention", "hold_reason": parsed["limitations"]}
        reuse_of = parsed.get("reuse_of")
        if reuse_of is not None and reuse_of != episode.get("prior_review_reference"):
            raise CheckpointError("REVISION_CONFLICT", "reuse reference is not the supervisor-validated prior review")
        if reuse_of is not None and _material_context_digest(state, episode["topic_id"]) != episode.get("material_context_digest"):
            raise CheckpointError("REVISION_CONFLICT", "material context changed during this checkpoint; prior review cannot be reused")
        counter_records = [record for record in episode.get("invocations", {}).values()
                           if isinstance(record, Mapping) and record.get("role") == "counter"
                           and record.get("status") == "finished" and record.get("exit_code") == 0
                           and isinstance(record.get("output_reference"), str)
                           and isinstance(record.get("delegate_result"), Mapping)
                           and record["delegate_result"].get("status") == "complete"]
        if not counter_records and reuse_of is None:
            # A model's final JSON cannot certify that the required fresh
            # counter happened. Keep the episode recoverable and due.
            episode["state"] = "retry_wait"; episode["failure_reason"] = "missing successful recorded counter invocation"
            topic["review_state"] = "checkpoint_due"
            return {"episode_id": episode["episode_id"], "state": "retry_wait", "hold_reason": episode["failure_reason"]}
        if any(proposal["proposal_id"] in work["proposals"] for proposal in parsed["proposals"]):
            raise CheckpointError("DUPLICATE_REQUEST_CONFLICT", "proposal IDs must be new; prior proposal history cannot be replaced")
        episode["result_reference"] = parsed["run_id"]
        for trigger_id in episode["trigger_ids"]: work["triggers"][trigger_id]["handled"] = True
        proposals = parsed["proposals"]
        allowance = int(topic.get("proposal_allowance_remaining", 2))
        if len(proposals) > allowance:
            raise CheckpointError("BUDGET_EXHAUSTED", "topic proposal allowance requires explicit operator reset")
        if not proposals:
            episode["state"] = "complete_without_proposals"; topic["active_episode_id"] = None; topic["review_state"] = "eligible"
        else:
            topic["proposal_allowance_remaining"] = allowance - len(proposals)
            episode.setdefault("remaining_budgets", {})["final_proposals"] = topic["proposal_allowance_remaining"]
            episode["state"] = "awaiting_operator"; topic["review_state"] = "awaiting_operator"
            for proposal in proposals:
                proposal = dict(proposal); proposal.update({"episode_id": episode["episode_id"], "topic_id": topic["topic_id"], "inventory_version": episode["inventory_version"], "status": "pending"})
                work["proposals"][proposal["proposal_id"]] = proposal
        return {"episode_id": episode["episode_id"], "state": episode["state"], "proposal_ids": [p["proposal_id"] for p in proposals], "next_research_ordinal": topic["next_research_ordinal"]}


def apply_decision(control: Any, payload: Mapping[str, Any], *, actor: str = "operator", publisher: Callable[[Mapping[str, Any], Mapping[str, Any] | None], None] | None = None) -> dict[str, Any]:
    """Apply an idempotent operator decision bundle for one checkpoint episode."""
    if not isinstance(payload, Mapping): raise CheckpointError("VALIDATION_ERROR", "decision payload must be an object")
    if set(payload) != {"schema_version", "request_id", "expected_revision", "topic_id", "episode_id", "decisions"}:
        raise CheckpointError("VALIDATION_ERROR", "decision payload has missing or unknown fields")
    if _require_int(payload["schema_version"], "schema_version") != 1: raise CheckpointError("VALIDATION_ERROR", "schema_version must be 1", "schema_version")
    request_id = _require_string(payload["request_id"], "request_id"); expected = _require_int(payload["expected_revision"], "expected_revision")
    topic_id = _require_string(payload["topic_id"], "topic_id"); episode_id = _require_string(payload["episode_id"], "episode_id")
    decisions = payload["decisions"]
    if not isinstance(decisions, list) or not decisions: raise CheckpointError("VALIDATION_ERROR", "decisions must be a non-empty array", "decisions")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    # A durable intent owns publication across controller/process failures. A
    # second decision cannot race an unfinished publication for this episode.
    snapshot = control.snapshot()
    prior = snapshot["work"].get("decisions", {}).get(request_id)
    intent = snapshot["work"].get("decision_publications", {}).get(request_id)
    if prior is not None:
        if prior.get("payload") != canonical:
            raise CheckpointError("DUPLICATE_REQUEST_CONFLICT", "request_id was used with different content", "request_id")
        if publisher is not None and intent and intent.get("publications"):
            # Cleanup on a replay obeys the same serialization as publication
            # itself (Astra R2-1): identity-checked finalize under the
            # publication lock, so a stale replay can never race — or
            # remove — a newer publication's journal.
            _with_publication_lock(
                control, lambda: publisher.finalize(_publications_for_cleanup(intent)))
        return copy.deepcopy(prior["result"])
    if intent is not None:
        if intent.get("payload") != canonical:
            raise CheckpointError("DUPLICATE_REQUEST_CONFLICT", "request_id was used with different content", "request_id")
        return _complete_decision_publication(control, request_id, actor, publisher)
    with control.transaction(actor=actor, operation_id=f"checkpoint-decision-intent:{request_id}") as state:
        work = _work(state); existing = work["decisions"].get(request_id)
        if isinstance(existing, dict):
            if existing.get("payload") != canonical: raise CheckpointError("DUPLICATE_REQUEST_CONFLICT", "request_id was used with different content", "request_id")
            return copy.deepcopy(existing["result"])
        if state.get("revision") != expected: raise CheckpointError("REVISION_CONFLICT", "expected_revision is stale", "expected_revision")
        episode = work["episodes"].get(episode_id)
        if not isinstance(episode, dict) or episode.get("topic_id") != topic_id or episode.get("state") != "awaiting_operator": raise CheckpointError("AWAITING_OPERATOR", "topic is not awaiting a decision for this episode")
        seen: set[str] = set(); selected: list[tuple[dict[str, Any], Mapping[str, Any]]] = []
        for index, decision in enumerate(decisions):
            if not isinstance(decision, Mapping): raise CheckpointError("VALIDATION_ERROR", f"decisions[{index}] must be an object")
            allowed = {"proposal_id", "proposal_version", "action", "reason", "edits"}
            if set(decision) - allowed or not {"proposal_id", "proposal_version", "action", "reason"} <= set(decision): raise CheckpointError("VALIDATION_ERROR", f"decisions[{index}] has invalid fields")
            proposal_id = _require_string(decision["proposal_id"], f"decisions[{index}].proposal_id")
            if proposal_id in seen: raise CheckpointError("VALIDATION_ERROR", "proposal appears twice", f"decisions[{index}].proposal_id")
            seen.add(proposal_id); proposal = work["proposals"].get(proposal_id)
            if not isinstance(proposal, dict) or proposal.get("episode_id") != episode_id or proposal.get("status") != "pending": raise CheckpointError("REVISION_CONFLICT", "proposal is no longer pending", f"decisions[{index}].proposal_id")
            if _require_int(decision["proposal_version"], f"decisions[{index}].proposal_version") != proposal.get("proposal_version"): raise CheckpointError("REVISION_CONFLICT", "proposal_version is stale", f"decisions[{index}].proposal_version")
            action = decision["action"]
            if action not in {"approve", "approve_with_edits", "reject"}: raise CheckpointError("VALIDATION_ERROR", "invalid decision action", f"decisions[{index}].action")
            _require_string(decision["reason"], f"decisions[{index}].reason")
            if action == "approve_with_edits" and not isinstance(decision.get("edits"), Mapping): raise CheckpointError("VALIDATION_ERROR", "approve_with_edits requires edits object", f"decisions[{index}].edits")
            if action != "approve_with_edits" and "edits" in decision: raise CheckpointError("VALIDATION_ERROR", "edits only allowed for approve_with_edits", f"decisions[{index}].edits")
            selected.append((proposal, decision))
        # Validate every approval's publishable shape before changing state or
        # invoking any publisher. Publication itself is still recoverable via
        # its durable journal.
        for proposal, decision in selected:
            if decision["action"] != "reject" and publisher is None:
                # Approval has a durable scope-publication consequence.  Never
                # turn an unavailable publisher into a silently resolved hold.
                raise CheckpointError("PUBLICATION_PENDING", "approved proposal needs the controller contract publisher")
        approved = [(proposal, decision) for proposal, decision in selected if decision["action"] != "reject"]
        if approved and not all(callable(getattr(publisher, name, None)) for name in ("prepare_bundle", "publish_prepared", "finalize")):
            raise CheckpointError("PUBLICATION_PENDING", "approval requires a recoverable bundle publisher")
        # Preparation validates every change before the first approved file
        # changes. Only the durable journal is created at this stage.
        prepared = publisher.prepare_bundle([(p, d.get("edits")) for p, d in approved]) if approved else None
        episode["state"] = "publishing_decision"
        _topic(work, topic_id)["review_state"] = "publishing_decision"
        work.setdefault("decision_publications", {})[request_id] = {
            "payload": canonical, "topic_id": topic_id, "episode_id": episode_id,
            "selected": copy.deepcopy(selected), "prepared": prepared,
            "state": "pending", "actor": actor, "created_at": _now(),
        }
    return _complete_decision_publication(control, request_id, actor, publisher)


def _complete_decision_publication(control: Any, request_id: str, actor: str, publisher: Any) -> dict[str, Any]:
    # Publication runs OUTSIDE any store transaction (2026-09-09 review:
    # holding BEGIN IMMEDIATE across contract-file fsyncs stalled every other
    # controller operation — claims, finalize, operator queries) but INSIDE a
    # dedicated publication lock (Astra F2, 2026-09-10): without it, a
    # delayed duplicate caller could re-apply an already-committed prepared
    # bundle over evidence written AFTER the winner released the topic, and
    # pathname cleanup could remove a later publication's journal. Under the
    # lock, the snapshot below always sees the winner's committed decision
    # and returns without touching the filesystem.
    return _with_publication_lock(
        control, lambda: _complete_decision_publication_locked(control, request_id, actor, publisher))


def _publications_for_cleanup(intent: Mapping[str, Any]) -> list:
    """Saved publication results enriched for identity-checked cleanup.

    Publication results committed BEFORE the identity-checked finalizer
    existed lack `publication_identity` even though the intent's own prepared
    bundle — the trusted origin of the journal — records it (Astra R3-1:
    without this, a valid pre-upgrade committed publication could never clean
    its own journal and would block the topic's next publication). The
    conservative standalone rule is untouched: with no ownership proof from
    the intent either, cleanup still refuses to guess.
    """
    publications = intent.get("publications") or []
    prepared = intent.get("prepared")
    identity = (prepared.get("identity") or prepared.get("key")) if isinstance(prepared, Mapping) else None
    enriched = []
    for record in publications:
        if isinstance(record, Mapping) and not record.get("publication_identity") and identity:
            record = {**record, "publication_identity": str(identity)}
        enriched.append(record)
    return enriched


def _with_publication_lock(control: Any, operation: Callable[[], Any]) -> Any:
    """Run `operation` holding the store's publication lock.

    Real stores flock `state/publication.lock` (covers every process);
    in-memory doubles have no filesystem root, so a process-wide lock
    serializes every caller they can have.
    """
    import fcntl

    root = getattr(control, "root", None)
    if root is None:
        with _PUBLICATION_PROCESS_LOCK:
            return operation()
    lock_path = Path(root) / "state" / "publication.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as publication_lock:
        fcntl.flock(publication_lock.fileno(), fcntl.LOCK_EX)
        return operation()


def _complete_decision_publication_locked(control: Any, request_id: str, actor: str, publisher: Any) -> dict[str, Any]:
    snapshot = control.snapshot()
    intent = snapshot["work"].get("decision_publications", {}).get(request_id)
    if not isinstance(intent, dict):
        raise CheckpointError("VALIDATION_ERROR", "unknown decision publication intent")
    existing = snapshot["work"].get("decisions", {}).get(request_id)
    if existing is not None:
        publications = _publications_for_cleanup(intent)
        if publications:
            publisher.finalize(publications)
        return copy.deepcopy(existing["result"])
    prepared = intent.get("prepared")
    if prepared is not None and publisher is None:
        raise CheckpointError("PUBLICATION_PENDING", "recovery requires the contract publisher")
    publications = publisher.publish_prepared(prepared) if prepared is not None else []
    for published in publications:
        if not isinstance(published, Mapping) or not isinstance(published.get("completion_lock"), str):
            raise CheckpointError("PUBLICATION_PENDING", "publisher did not return a completion lock")
    with control.transaction(actor=actor, operation_id=f"checkpoint-decision:{request_id}") as state:
        work = _work(state)
        intent = work["decision_publications"][request_id]
        existing = work["decisions"].get(request_id)
        if existing is not None:
            result = copy.deepcopy(existing["result"])
        else:
            result = _commit_decision(state, intent, request_id, publications)
            intent["state"] = "published"
            intent["publications"] = copy.deepcopy(publications)
    # Only committed decisions may remove the recovery journal. If cleanup
    # fails, replay sees the committed result and retries this harmless step.
    if publications:
        publisher.finalize(publications)
    return result


def _commit_decision(state: dict[str, Any], intent: dict[str, Any], request_id: str, publications: list) -> dict[str, Any]:
        work = _work(state)
        topic_id, episode_id = intent["topic_id"], intent["episode_id"]
        topic, episode = _topic(work, topic_id), work["episodes"][episode_id]
        selected = [(work["proposals"][proposal["proposal_id"]], decision) for proposal, decision in intent["selected"]]
        for proposal, decision in selected:
            proposal["status"] = "resolved"; proposal["decision"] = dict(decision); proposal["resolved_at"] = _now()
        pending = [p["proposal_id"] for p in work["proposals"].values() if isinstance(p, dict) and p.get("episode_id") == episode_id and p.get("status") == "pending"]
        # Contract lock and ledger inventory advance together with the decision;
        # queue lookup is authoritative for managed runnable work.
        if publications:
            lock = publications[-1]["completion_lock"]
            topic["inventory_version"] = lock
            for item in state.get("queue", {}).get("items", []):
                if item.get("id") == topic_id: item["completion_lock"] = lock
        if not pending:
            episode["state"] = "complete_with_decisions"; topic["active_episode_id"] = None; topic["review_state"] = "eligible"
        else:
            episode["state"] = "awaiting_operator"; topic["review_state"] = "awaiting_operator"
        result = {"topic_id": topic_id, "episode_id": episode_id, "resolved": not pending, "remaining_proposal_ids": pending,
                  "next_research_ordinal": topic["next_research_ordinal"], "hold_reason": None if not pending else "awaiting_operator",
                  "revision": state.get("revision", 0) + 1}
        work["decisions"][request_id] = {"request_id": request_id, "payload": intent["payload"], "result": copy.deepcopy(result), "actor": intent["actor"], "created_at": _now()}
        return result
