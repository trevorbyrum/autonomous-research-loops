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

DIAGNOSTIC (2026-09-11): a distinct failure mode was observed that neither of
the above catches — the wrapper's OWN process vanishes mid-call (no exit
code, no output, nothing in this file's control ever runs again) with a
recurring, topic-clustered pattern. The leading theory is a primary
backgrounding this command (`... managed-delegate.py & ; sleep N; poll`)
instead of blocking on it as instructed, and the surrounding sandboxed
command-execution session reaping the orphaned child once the visible
command returns. This cannot be proven from inside a process that gets
killed before it can log anything about its own death — so instead, each
invocation leaves a durable INFLIGHT MARKER FILE for the duration of the
call and removes it only on a normal return from subprocess.run(). The
NEXT invocation for the same topic checks for a marker whose process is no
longer alive and, if found, records a `vanished` ledger line — external,
after-the-fact proof that a prior call died mid-flight, distinguishing that
from "never launched" or "ran and genuinely returned empty." This is pure
observability: it changes no timeout, no retry, no scheduling, and nothing
about how a delegate call itself runs.
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


def _inflight_dir(topic_dir: Path) -> Path:
    return topic_dir / "logs"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not signalable by us — still alive
    return True


def _report_vanished_markers(topic_dir: Path) -> None:
    """Best-effort: log any prior invocation's marker whose process is dead.

    Read-only with respect to control flow — this never raises, never blocks,
    and never affects the launch that follows it. It only ever reports on
    THIS wrapper's own leftover marker files, written by a prior invocation
    of this same script.
    """
    directory = _inflight_dir(topic_dir)
    try:
        markers = sorted(directory.glob(".delegate-inflight-*.json"))
    except OSError:
        return
    for marker in markers:
        try:
            record = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(record["pid"])
        except (OSError, ValueError, KeyError, TypeError):
            marker.unlink(missing_ok=True)
            continue
        if _pid_alive(pid):
            continue  # still legitimately running (or PID reused too fast); leave it
        launched_at = record.get("launched_at")
        detected_at = _now()
        elapsed = None
        try:
            if launched_at:
                delta = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(
                    launched_at.replace("Z", "+00:00"))
                elapsed = round(delta.total_seconds(), 1)
        except ValueError:
            pass
        _ledger_append(topic_dir, {
            "ts": detected_at, "event": "vanished", "pid": pid,
            "role": record.get("role"), "model": record.get("model"),
            "launched_at": launched_at, "detected_at": detected_at,
            "elapsed_seconds": elapsed,
        })
        marker.unlink(missing_ok=True)


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
    _report_vanished_markers(topic_path)  # diagnostic: prior invocation's fate, if it never returned
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
    launch_ts = _now()
    _ledger_append(topic_path, {"ts": launch_ts, "event": "launch",
                                "model": profile["model"], "role": role})
    marker_path = _inflight_dir(topic_path) / f".delegate-inflight-{os.getpid()}.json"
    try:
        marker_path.write_text(json.dumps({"pid": os.getpid(), "role": role,
                                           "model": profile["model"], "launched_at": launch_ts}),
                               encoding="utf-8")
    except OSError:
        pass  # diagnostic-only: an unwritable marker never blocks the delegate call
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
        # A normal return from subprocess.run() reaches here regardless of
        # the adapter's own exit code — only a process that never gets this
        # far (this wrapper itself killed from outside, e.g. by a sandbox
        # session tearing down an orphaned backgrounded child) leaves the
        # marker behind for the next invocation to find.
        marker_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
