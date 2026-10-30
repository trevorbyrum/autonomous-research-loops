"""python fake_executor.py <script.json>: a deterministic, scriptable stand-in
for the executor of any invocation kind (task 1c; design review §10 Phase 1:
"exercise research, discovery, delegate, verifier and checkpoint envelopes
through the same lifecycle using fake executors").

No model, no gateway, no network: standard library only, run by path in the
job's scratch directory (its working directory), following its script's
steps in order. What it can do is what an agent can do to a supervisor:
succeed, crash at any step, hang, return empty output, declare a wrong
digest, claim success without output, plant a symlink where its output
should be, and leave descendants running.

Steps (each an object with "op"):
  write            {"name", "text" | "hex"}    write a file of the scratch directory
  symlink          {"name", "target"}          make name a symlink to target
  link             {"name", "target"}          make name a hard link to target
  claim_success    {}                          write status.json {"status": "completed"} (a self-report)
  declare_digest   {"digest"}                  write declared-digest (the agent's own claim about its output)
  spawn_descendant {"marker"}                  start a child that stays in the session and sleeps; write its pid to marker
  wait_for         {"name", "seconds"}         wait until name exists in the scratch directory (a gate the test opens)
  sleep            {"seconds"}
  hang             {}                          sleep until killed
  exit             {"code"}                    exit now with this code
  kill_self        {"signal"}                  end by this signal
Running out of steps exits 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def publish(path: Path, text: str) -> None:
    """Write a file others poll for, whole: its name appears only by rename,
    after the content is written, so a reader that sees the name never reads
    it empty (task 1c-repair C2: a test read descendant.pid the moment it
    existed and, under load, found it empty)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def descendant(marker: str) -> int:
    publish(Path(marker), str(os.getpid()))
    while True:
        time.sleep(3600)


def run(script: dict) -> int:
    here = Path.cwd()
    for step in script["steps"]:
        op = step["op"]
        if op == "write":
            data = bytes.fromhex(step["hex"]) if "hex" in step else step["text"].encode("utf-8")
            (here / step["name"]).write_bytes(data)
        elif op == "symlink":
            os.symlink(step["target"], here / step["name"])
        elif op == "link":
            os.link(step["target"], here / step["name"])
        elif op == "claim_success":
            (here / "status.json").write_text(json.dumps({"status": "completed"}))
        elif op == "declare_digest":
            (here / "declared-digest").write_text(step["digest"])
        elif op == "spawn_descendant":
            subprocess.Popen([sys.executable, __file__, "--descendant", str(here / step["marker"])], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
            deadline = time.monotonic() + 10
            while not (here / step["marker"]).exists() and time.monotonic() < deadline:
                time.sleep(0.005)
        elif op == "wait_for":
            deadline = time.monotonic() + step["seconds"]
            while not (here / step["name"]).exists():
                if time.monotonic() >= deadline:
                    return 3
                time.sleep(0.005)
        elif op == "sleep":
            time.sleep(step["seconds"])
        elif op == "hang":
            while True:
                time.sleep(3600)
        elif op == "exit":
            return step["code"]
        elif op == "kill_self":
            os.kill(os.getpid(), step["signal"])
            time.sleep(10)
        else:
            raise ValueError(f"unknown step {op!r}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--descendant":
        sys.exit(descendant(sys.argv[2]))
    sys.exit(run(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))))
