#!/usr/bin/env python3
"""Invoke a configured managed station role through its packaged adapter.

Besides launching the adapter, this shim is the managed replacement for the
legacy delegate wrapper's OBSERVABILITY contract (9·0 delegation coverage):
every allowed invocation appends a `launch` line to the topic's
logs/delegate-usage.jsonl before running, and a usage line (token detail) after
a run whose adapter captured usage. A launch with no later usage line is an
unobserved outcome — the throughput report distinguishes "no delegation" from
"delegation whose usage was never recorded" only because of these lines.

Failure surfacing (the delegate-silent-failure class, fixed 2026-09-09 in the
legacy wrapper and restored here): a nonzero exit surfaces the adapter's
stderr tail, and a zero exit with NO output at all becomes exit 70 — an empty
response must never read as a successful empty search.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ledger_append(topic_dir: Path, record: dict) -> None:
    """Best-effort observability append; never fails the delegate call."""
    path = topic_dir / "logs" / "delegate-usage.jsonl"
    try:
        if not path.parent.is_dir():
            return
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    except OSError:
        pass


def _usage_record(usage_path: Path, model: str) -> dict | None:
    """Translate the adapter's usage capture into a ledger usage line.

    The line shape matches the legacy wrapper (throughput_report reads it):
    token detail plus total_tokens, and deliberately NO "event" key.
    """
    try:
        captured = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(captured, dict):
        return None
    total = captured.get("total_tokens")
    if not isinstance(total, (int, float)):
        return None
    record = {"ts": _now(), "model": model, "provider": captured.get("provider") or "unknown",
              "total_tokens": int(total)}
    models = captured.get("models")
    detail = models.get(model) if isinstance(models, dict) else None
    if isinstance(detail, dict):
        for key, value in detail.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                # Keep fractional values (e.g. a cost field) exact; only
                # integral counts collapse to int.
                record[key] = int(value) if float(value).is_integer() else float(value)
    return record


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in {"primary", "secondary"}:
        raise SystemExit("usage: managed-delegate.py primary|secondary <topic-dir> <task>")
    role, topic_dir, task = argv[1:]
    raw = os.environ.get(f"RESEARCH_LOOP_MANAGED_{role.upper()}_PROFILE")
    if not raw:
        raise SystemExit(f"managed {role} profile is not configured in this environment")
    try:
        profile = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"managed {role} profile is invalid: {exc}")
    if not isinstance(profile, dict) or set(profile) != {"id", "adapter", "model", "executable", "argv"}:
        raise SystemExit(f"managed {role} profile is missing required fields")
    adapter = profile["adapter"]
    chassis = Path(__file__).resolve().parent
    runner = chassis.parent / "runners" / f"{adapter}.sh"
    if not runner.is_file():
        raise SystemExit(f"managed {role} adapter is not packaged: {adapter}")
    topic_path = Path(topic_dir).resolve()
    key = adapter.upper().replace("-", "_")
    env = os.environ.copy()
    env[f"RESEARCH_LOOP_{key}_MODEL"] = profile["model"]
    env[f"RESEARCH_LOOP_{key}_BIN"] = profile["executable"]
    env[f"RESEARCH_LOOP_{key}_ARGV_JSON"] = json.dumps(profile["argv"])
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as prompt:
        prompt.write(task)
        prompt_path = prompt.name
    usage_fd, usage_path = tempfile.mkstemp(prefix=".delegate-usage-")
    os.close(usage_fd)
    env["RESEARCH_LOOP_USAGE_FILE"] = usage_path
    _ledger_append(topic_path, {"ts": _now(), "event": "launch",
                                "model": profile["model"], "role": role})
    try:
        completed = subprocess.run(
            [str(runner), str(topic_path), prompt_path],
            env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        rc = completed.returncode
        # Re-emit the adapter's captured stdout/stderr for the caller. Capture
        # buffers until completion: content is preserved, but streaming/
        # interleaving timing is not, and a killed shim loses buffered
        # partial output (documented limit of the observability rewrite).
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        usage = _usage_record(Path(usage_path), profile["model"])
        if usage is not None:
            _ledger_append(topic_path, usage)
        if rc != 0 or not completed.stdout.strip():
            tail = "\n".join(completed.stderr.splitlines()[-5:])
            print(f"delegate ({profile['model']}) failed rc={rc}; adapter stderr tail:\n{tail}",
                  file=sys.stderr)
            if rc == 0:
                # Empty output on a zero exit is a capability failure, never a
                # successful empty search (delegate-silent-failure class).
                rc = 70
        return rc
    finally:
        Path(prompt_path).unlink(missing_ok=True)
        Path(usage_path).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
