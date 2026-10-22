#!/usr/bin/env python3
"""Run one explicit CI workload. Scheduling and status aggregation belong to Jenkins.

The default is T0 only. Full acceptance requires every engine test and mutation
shard, trigger-order, and all three gateway modes; no subset implies acceptance.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from gen2_ci_evidence import junit, shard_spec, write_json
from gen2_workers import cpu_budget, mutation_workers

ROOT = Path(__file__).resolve().parent.parent
MODES = ("push", "engine-unit", "engine-trigger-order", "engine-mutation", "gateway-no-db", "gateway-db", "gateway-mutants")
PARTIAL_BANNER = "PARTIAL ACCEPTANCE — NOT FULL ACCEPTANCE"
DEFAULT_WORK = (("push", (1, 1)), ("engine-trigger-order", (1, 1)), ("engine-unit", (1, 8)))


def default_run(out: Path) -> int:
    """Execute and disclose the fixed, partial branch/PR workload."""
    destination = out / "default-1-of-1"
    destination.mkdir(parents=True, exist_ok=False)
    scope = {"schema": "gen2-ci-scope/v1", "acceptance": "partial", "full_acceptance": False,
             "banner": PARTIAL_BANNER, "mode": "default", "shard": [1, 1],
             "checkout_sha": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
             "source_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
             "ran": ["T0", "complete trigger-order", "units 1/8"],
             "omitted": ["unit partitions 2–8/8", "all mutation work", "all gateway modes"],
             "executions": [{"mode": mode, "shard": shard, "status": "not_run"}
                            for mode, shard in DEFAULT_WORK], "status": "running"}
    def publish():
        write_json(destination / "scope.json", scope)
        print(PARTIAL_BANNER, flush=True)
        print("Scope: " + "; ".join(scope["ran"]) + ". Omitted: " + "; ".join(scope["omitted"]), flush=True)
        print("GEN2_CI_SCOPE " + json.dumps(scope, sort_keys=True), flush=True)
        # cfg.junit is the deployed platform's supported consumer summary API.
        # Keep the disclosure visible in Jenkins' test names, even on failure.
        with_directory = os.environ.get("GEN2_CI_EVIDENCE")
        os.environ["GEN2_CI_EVIDENCE"] = str(destination.resolve())
        try:
            junit("acceptance-scope", [{"id": PARTIAL_BANNER + ": " + "; ".join(scope["ran"]) +
                  ". Omitted: " + "; ".join(scope["omitted"]),
                  "outcome": "pass" if scope["status"] == "pass" else "error"}], scope)
        finally:
            if with_directory is None:
                os.environ.pop("GEN2_CI_EVIDENCE", None)
            else:
                os.environ["GEN2_CI_EVIDENCE"] = with_directory
    publish()
    started = time.monotonic()
    try:
        for execution in scope["executions"]:
            execution["status"] = "running"
            write_json(destination / "scope.json", scope)
            index, total = execution["shard"]
            code = subprocess.call([sys.executable, str(Path(__file__).resolve()), "--mode", execution["mode"],
                                    "--shard", f"{index}/{total}", "--out", str(out.resolve())], cwd=ROOT)
            execution.update(status="pass" if code == 0 else "fail", exit_code=code)
            if code:
                return code
        scope["status"] = "pass"
        return 0
    finally:
        if scope["status"] != "pass":
            scope["status"] = "fail"
        scope["duration_s"] = time.monotonic() - started
        publish()


def command(mode: str, shard: tuple[int, int]) -> list[str]:
    index, total = shard
    if mode == "engine-unit":
        return ["make", "gen2-test", f"GEN2_TEST_ARGS=--shard {index}/{total}"]
    if mode == "engine-mutation":
        return ["make", "gen2-mutation", f"GEN2_MUTATION_ARGS=--shard {index}/{total}"]
    if shard != (1, 1):
        raise ValueError(f"{mode} does not support sharding")
    if mode.startswith("gateway-"):
        return ["make", "gen2-gateway", "GEN2_GATEWAY_MODE=" + mode.removeprefix("gateway-")]
    return ["make", "gen2-push" if mode == "push" else "gen2-trigger-order"]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def gateway_dependency() -> dict:
    probe = subprocess.run([os.environ.get("PYTHON_BOOTSTRAP", "python3"), "-c",
                            "import psycopg; print(psycopg.__version__)"], capture_output=True, text=True)
    return {"available": probe.returncode == 0, "version": probe.stdout.strip() or None,
            "error": probe.stderr.strip() or None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=(*MODES, "default"), default="push")
    parser.add_argument("--shard", type=shard_spec, default=(1, 1))
    parser.add_argument("--out", type=Path, default=ROOT / "build/ci-evidence")
    args = parser.parse_args(argv)
    if args.mode == "default":
        if args.shard != (1, 1):
            parser.error("default scope does not support sharding")
        return default_run(args.out)
    invocation = command(args.mode, args.shard)
    destination = args.out / f"{args.mode}-{args.shard[0]}-of-{args.shard[1]}"
    destination.mkdir(parents=True, exist_ok=False)
    budget = cpu_budget()
    identity = {
        "schema": "gen2-ci/v1", "mode": args.mode, "shard": args.shard,
        "checkout_sha": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
        "source_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "python": sys.version, "sqlite": sqlite3.sqlite_version,
        "budget": {"aggregate_cpus": budget, "engine_mutation_workers": mutation_workers(),
                   "gateway_workers": 1, "engine_gateway_concurrent": False},
        "capabilities": {"psycopg_in_engine_interpreter": importlib.util.find_spec("psycopg") is not None,
                         "gateway_psycopg": gateway_dependency()},
        "command": invocation, "status": "running", "exit_code": None,
    }
    # A git archive snapshot may use a separate, pinned git history for tests
    # which need it. Its bytes must be verified by the snapshot launcher.
    write_json(destination / "run.json", identity)
    print("gen2-ci: " + json.dumps(identity, sort_keys=True), flush=True)
    env = {**os.environ, "GEN2_CPU_BUDGET": str(budget), "GEN2_CI_EVIDENCE": str(destination.resolve()),
           "GEN2_TEST_LOG": str((destination / "engine-unit.log").resolve())}
    started = time.monotonic()
    try:
        with (destination / "command.log").open("w") as log:
            process = subprocess.Popen(invocation, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True)
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    print(line, end="", flush=True)
                code = process.wait()
            finally:
                process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait()
        identity.update(status="pass" if code == 0 else "fail", exit_code=code)
        return code
    finally:
        identity["duration_s"] = time.monotonic() - started
        write_json(destination / "run.json", identity)
        # v1.0 archives only platform files. Keep the structured measurements
        # in the retained console too until v1.1 publishes consumer artifacts.
        for path in sorted(destination.rglob("*.json")):
            if path.name != "run.json":
                print("GEN2_CI_EVIDENCE " + json.dumps({"path": str(path.relative_to(destination)),
                      "mode": args.mode, "shard": args.shard, "data": json.loads(path.read_text())}, sort_keys=True), flush=True)
        print("GEN2_CI_RESULT " + json.dumps(identity, sort_keys=True), flush=True)


if __name__ == "__main__":
    sys.exit(main())
