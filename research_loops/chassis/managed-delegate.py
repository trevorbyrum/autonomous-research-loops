#!/usr/bin/env python3
"""Invoke a configured managed station role through its packaged adapter."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in {"primary", "secondary"}:
        raise SystemExit("usage: managed-delegate.py primary|secondary <topic-dir> <task>")
    role, topic_dir, task = argv[1:]
    raw = os.environ.get(f"RESEARCH_LOOP_MANAGED_{role.upper()}_PROFILE")
    try:
        profile = json.loads(raw or "")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"managed {role} profile is invalid: {exc}")
    if not isinstance(profile, dict) or set(profile) != {"id", "adapter", "model", "executable", "argv"}:
        raise SystemExit(f"managed {role} profile is missing required fields")
    adapter = profile["adapter"]
    chassis = Path(__file__).resolve().parent
    runner = chassis.parent / "runners" / f"{adapter}.sh"
    if not runner.is_file():
        raise SystemExit(f"managed {role} adapter is not packaged: {adapter}")
    key = adapter.upper().replace("-", "_")
    env = os.environ.copy()
    env[f"RESEARCH_LOOP_{key}_MODEL"] = profile["model"]
    env[f"RESEARCH_LOOP_{key}_BIN"] = profile["executable"]
    env[f"RESEARCH_LOOP_{key}_ARGV_JSON"] = json.dumps(profile["argv"])
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as prompt:
        prompt.write(task)
        prompt_path = prompt.name
    try:
        return subprocess.run([str(runner), str(Path(topic_dir).resolve()), prompt_path], env=env).returncode
    finally:
        Path(prompt_path).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
