"""Separate adapter entry point for structured checkpoint executions."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping


class CheckpointResultError(ValueError):
    pass


_PROPOSAL_FIELDS = {"proposal_id", "proposal_version", "kind", "anchors", "evidence_target", "nearest_reference", "consequence", "counterargument", "dependencies", "content"}


def validate_checkpoint_result(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping): raise CheckpointResultError("checkpoint result must be an object")
    required = {"episode_id", "run_id", "inventory_version", "trigger_ids", "complete", "findings", "limitations", "protocol_evidence_refs", "proposals"}
    if set(value) - (required | {"reuse_of"}) or not required <= set(value): raise CheckpointResultError("checkpoint result has missing or unknown fields")
    if "reuse_of" in value and (not isinstance(value["reuse_of"], str) or not value["reuse_of"]): raise CheckpointResultError("reuse_of must be a non-empty episode id")
    for field in ("episode_id", "run_id", "inventory_version"):
        if not isinstance(value[field], str) or not value[field]: raise CheckpointResultError(f"{field} must be a non-empty string")
    if not isinstance(value["complete"], bool): raise CheckpointResultError("complete must be boolean")
    for field in ("trigger_ids", "findings", "limitations", "protocol_evidence_refs", "proposals"):
        if not isinstance(value[field], list): raise CheckpointResultError(f"{field} must be an array")
    for field in ("findings", "limitations", "protocol_evidence_refs"):
        if any(not isinstance(item, str) or not item.strip() for item in value[field]):
            raise CheckpointResultError(f"{field} must contain non-empty strings")
    if not value["complete"] and not value["limitations"]: raise CheckpointResultError("incomplete result requires limitations")
    if not value["complete"] and value["proposals"]: raise CheckpointResultError("incomplete result cannot issue proposals")
    if "reuse_of" in value and (not value["complete"] or value["proposals"]): raise CheckpointResultError("reuse requires a complete zero-proposal result")
    if len(value["proposals"]) > 2: raise CheckpointResultError("at most two final proposals are allowed")
    if not value["trigger_ids"] or any(not isinstance(item, str) or not item for item in value["trigger_ids"]) or len(set(value["trigger_ids"])) != len(value["trigger_ids"]):
        raise CheckpointResultError("trigger_ids must be a non-empty unique string array")
    proposal_ids: set[str] = set()
    for i, proposal in enumerate(value["proposals"]):
        if not isinstance(proposal, Mapping) or set(proposal) != _PROPOSAL_FIELDS: raise CheckpointResultError(f"proposals[{i}] has missing or unknown fields")
        if proposal.get("kind") not in {"addition", "amendment", "scope_request"}: raise CheckpointResultError(f"proposals[{i}].kind is invalid")
        if not isinstance(proposal.get("proposal_id"), str) or not proposal["proposal_id"]: raise CheckpointResultError(f"proposals[{i}].proposal_id is required")
        if proposal["proposal_id"] in proposal_ids: raise CheckpointResultError(f"proposals[{i}].proposal_id is duplicated")
        proposal_ids.add(proposal["proposal_id"])
        if not isinstance(proposal.get("proposal_version"), int) or isinstance(proposal["proposal_version"], bool) or proposal["proposal_version"] < 1: raise CheckpointResultError(f"proposals[{i}].proposal_version is invalid")
        if not isinstance(proposal["anchors"], list) or not proposal["anchors"] or any(not isinstance(anchor, Mapping) or set(anchor) != {"locator", "observation", "inference"} or not all(isinstance(anchor.get(field), str) and anchor[field].strip() for field in ("locator", "observation", "inference")) for anchor in proposal["anchors"]):
            raise CheckpointResultError(f"proposals[{i}].anchors requires non-empty locator records")
        if not isinstance(proposal["evidence_target"], Mapping) or set(proposal["evidence_target"]) != {"route", "support", "complication", "null", "unresolved"} or any(not isinstance(proposal["evidence_target"].get(field), str) or not proposal["evidence_target"][field].strip() for field in proposal["evidence_target"]):
            raise CheckpointResultError(f"proposals[{i}].evidence_target requires route")
        if not isinstance(proposal["nearest_reference"], Mapping) or set(proposal["nearest_reference"]) != {"reference", "non_duplication"} or any(not isinstance(proposal["nearest_reference"].get(field), str) or not proposal["nearest_reference"][field].strip() for field in proposal["nearest_reference"]):
            raise CheckpointResultError(f"proposals[{i}].nearest_reference requires a reference or documented absence")
        if not isinstance(proposal["consequence"], str) or not proposal["consequence"].strip() or not isinstance(proposal["counterargument"], str) or not proposal["counterargument"].strip():
            raise CheckpointResultError(f"proposals[{i}] requires non-empty consequence and counterargument")
        if not isinstance(proposal["dependencies"], list) or any(not isinstance(item, str) or not item.strip() for item in proposal["dependencies"]): raise CheckpointResultError(f"proposals[{i}].dependencies must be a string array")
        content = proposal["content"]
        if not isinstance(content, Mapping): raise CheckpointResultError(f"proposals[{i}].content must be an object")
        if proposal["kind"] == "addition" and (set(content) != {"text", "source_ref"} or not isinstance(content.get("text"), str) or not content["text"].strip() or not isinstance(content.get("source_ref"), str) or not content["source_ref"].strip()):
            raise CheckpointResultError(f"proposals[{i}].content requires exact addition text and source_ref")
        if proposal["kind"] == "amendment" and (set(content) != {"target_id", "current_text", "proposed_text", "framing_defect", "implications"} or any(not isinstance(content.get(field), str) or not content[field].strip() for field in content)):
            raise CheckpointResultError(f"proposals[{i}].content lacks amendment fields")
        if proposal["kind"] == "scope_request" and (set(content) != {"requested_mission", "rationale"} or not isinstance(content.get("requested_mission"), str) or not content["requested_mission"].strip() or not isinstance(content.get("rationale"), str) or not content["rationale"].strip()):
            raise CheckpointResultError(f"proposals[{i}].content requires requested_mission and rationale")
    return dict(value)


class CheckpointRunner:
    """Runs only the configured checkpoint adapter; never the ordinary prompt."""
    def __init__(self, adapter: Callable[[Mapping[str, Any]], Mapping[str, Any]]): self.adapter = adapter

    def run(self, episode_context: Mapping[str, Any]) -> dict[str, Any]:
        result = validate_checkpoint_result(self.adapter(dict(episode_context)))
        if result["episode_id"] != episode_context.get("episode_id") or result["run_id"] != episode_context.get("run_id"):
            raise CheckpointResultError("adapter result identity does not match episode context")
        return result


class SubprocessCheckpointAdapter:
    """Production adapter boundary for a configured checkpoint executable.

    The executable receives one JSON context on stdin and must emit exactly one
    JSON result on stdout.  It is deliberately distinct from a topic's ordinary
    command and gets the installed package protocol path in its context.
    """
    def __init__(self, command: list[str], *, timeout_seconds: int = 900):
        if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
            raise CheckpointResultError("checkpoint adapter command must be a non-empty string array")
        self.command, self.timeout_seconds = list(command), timeout_seconds

    def __call__(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        protocol = Path(__file__).with_name("prompts") / "protocol.md"
        if not protocol.is_file():
            raise CheckpointResultError("installed checkpoint protocol is unavailable")
        payload = {key: value for key, value in context.items() if not key.startswith("_")}
        payload["protocol_path"] = str(protocol)
        try:
            env = None
            additions = context.get("_launch_env")
            if isinstance(additions, Mapping):
                import os
                env = os.environ.copy(); env.update({str(key): str(value) for key, value in additions.items()})
            identity = context.get("_popen_identity")
            if not isinstance(identity, Mapping): identity = {}
            process = subprocess.run(self.command, input=json.dumps(payload), text=True,
                                     capture_output=True, timeout=self.timeout_seconds, check=False,
                                     cwd=context.get("_cwd"), env=env, **identity)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CheckpointResultError(f"checkpoint adapter failed to launch: {exc}") from exc
        if process.returncode != 0:
            raise CheckpointResultError(f"checkpoint adapter exited {process.returncode}: {process.stderr[-1000:]}")
        try:
            return json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise CheckpointResultError("checkpoint adapter did not emit a JSON result") from exc


def launch_registered_profile(profile: Mapping[str, Any], prompt: str, *, cwd: Any, env: Any,
                              identity: Mapping[str, Any] | None, timeout_seconds: int) -> tuple[int, str]:
    """Run one registered provider profile to completion: (exit_code, text).

    The single launch implementation for every consumer of a registered
    profile (the checkpoint adapter below and the controller's delegate
    broker) — the 2026-09-09 review found two divergent copies. OSError and
    TimeoutExpired propagate: callers classify infrastructure failures
    differently. ValueError means an unsupported adapter name.
    """
    import os
    adapter, executable, model = profile["adapter"], profile["executable"], profile["model"]
    argv = list(profile.get("argv") or [])
    identity = dict(identity or {})
    if adapter == "codex":
        with tempfile.NamedTemporaryFile(prefix="checkpoint-provider-", delete=False) as output:
            output_path = output.name
        if isinstance(identity.get("user"), int) and isinstance(identity.get("group"), int):
            os.chown(output_path, identity["user"], identity["group"])
            os.chmod(output_path, 0o600)
        try:
            process = subprocess.run([executable, "exec", "-m", model, "-o", output_path, *argv, prompt],
                                     text=True, capture_output=True, timeout=timeout_seconds,
                                     check=False, cwd=cwd, env=env, **identity)
            text = Path(output_path).read_text(encoding="utf-8") if process.returncode == 0 else process.stderr
        finally:
            Path(output_path).unlink(missing_ok=True)
    elif adapter == "claude":
        process = subprocess.run([executable, "-p", prompt, "--model", model, "--output-format", "json", *argv],
                                 text=True, capture_output=True, timeout=timeout_seconds,
                                 check=False, cwd=cwd, env=env, **identity)
        if process.returncode != 0:
            text = process.stderr
        elif not process.stdout.strip():
            text = ""  # a truly empty response — callers classify infrastructure
        else:
            # NONEMPTY malformed output is a semantic failure and must keep
            # its diagnostic (Astra F8): mapping it to an empty response
            # would misclassify it as refundable infrastructure and destroy
            # the evidence needed to tell garbage from absence.
            try:
                envelope = json.loads(process.stdout)
            except json.JSONDecodeError:
                return 78, "claude response is not a JSON envelope: " + process.stdout[-1000:]
            result = envelope.get("result") if isinstance(envelope, dict) else None
            if not isinstance(result, str) or not result.strip():
                return 78, "claude envelope lacks result text: " + process.stdout[-1000:]
            text = result
    elif adapter == "hermes":
        process = subprocess.run([executable, "-p", str(profile.get("id") or "default"), "-z", prompt, *argv],
                                 text=True, capture_output=True, timeout=timeout_seconds,
                                 check=False, cwd=cwd, env=env, **identity)
        text = process.stdout if process.returncode == 0 else process.stderr
    else:
        raise ValueError(f"registered profile adapter has no packaged provider launcher: {adapter}")
    return process.returncode, text if isinstance(text, str) else ""


class RegisteredCheckpointAdapter:
    """Provider-aware checkpoint launcher for a resolved registered profile."""
    def __init__(self, profile: Mapping[str, Any], *, timeout_seconds: int = 900):
        required = {"id", "adapter", "model", "executable", "argv"}
        if not isinstance(profile, Mapping) or not required <= set(profile): raise CheckpointResultError("resolved checkpoint profile is incomplete")
        if profile["adapter"] not in {"codex", "claude", "hermes"}: raise CheckpointResultError("checkpoint profile adapter has no packaged provider launcher")
        if not isinstance(profile["argv"], list) or any(not isinstance(arg, str) for arg in profile["argv"]): raise CheckpointResultError("checkpoint profile argv must be a string array")
        self.profile, self.timeout_seconds = dict(profile), timeout_seconds

    def __call__(self, context: Mapping[str, Any]) -> Mapping[str, Any]:
        task = {key: value for key, value in context.items() if not key.startswith("_")}
        supplied_prompt = context.get("_prompt_text")
        if isinstance(supplied_prompt, str):
            prompt = supplied_prompt + "\n\nSTRUCTURED CONTEXT:\n" + json.dumps(task, sort_keys=True) + "\nReturn only the required structured JSON object."
        else:
            protocol = Path(__file__).with_name("prompts") / "protocol.md"
            prompt = protocol.read_text(encoding="utf-8") + "\n\nSTRUCTURED CONTEXT:\n" + json.dumps(task, sort_keys=True) + "\nReturn only the checkpoint-result JSON object."
        env = None
        if isinstance(context.get("_launch_env"), Mapping):
            import os
            env = os.environ.copy(); env.update({str(k): str(v) for k, v in context["_launch_env"].items()})
        identity = context.get("_popen_identity") if isinstance(context.get("_popen_identity"), Mapping) else {}
        try:
            code, text = launch_registered_profile(self.profile, prompt, cwd=context.get("_cwd"),
                                                   env=env, identity=identity,
                                                   timeout_seconds=self.timeout_seconds)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise CheckpointResultError(f"checkpoint provider launch failed: {exc}") from exc
        if code != 0: raise CheckpointResultError(f"checkpoint provider exited {code}: {text[-1000:]}")
        try: return json.loads(text)
        except (TypeError, json.JSONDecodeError) as exc: raise CheckpointResultError("checkpoint provider did not return checkpoint-result JSON") from exc
