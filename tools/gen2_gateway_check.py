#!/usr/bin/env python3
"""The gateway's checks for task 2b, in one command (make gen2-gateway).

  1. the gateway's own suite (gateway/tests), without a database;
  2. with a THROWAWAY PostgreSQL: a cluster initialized in a temporary directory,
     listening only on a Unix socket there (no TCP port), the schema and seed loaded,
     the suite run again with RESEARCH_GATEWAY_DSN pointing at it — the cases that
     exercise the queue, the call log, the immutability triggers and DB-backed source
     loading — then the cluster is stopped and removed;
  3. tools/gen2_gateway_mutations.py (every task-2b gateway mutant, the database ones on
     the same throwaway cluster).

It never reads RESEARCH_GATEWAY_DSN from its own environment: no existing database —
certainly not a running gateway's — is ever touched. Without PostgreSQL server binaries
(initdb, pg_ctl; on PATH or under /usr/lib/postgresql/*/bin) the database steps cannot
run and the check FAILS, naming what did not run. Needs the gateway's interpreter
dependency (psycopg) in the running Python. Exit status 0 only if every step passed.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATEWAY = ROOT / "gateway"


def pg_bin(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for candidate in sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{name}"), reverse=True):
        return candidate
    return None


def step(label: str, argv: list[str], env: dict, cwd: Path) -> bool:
    print(f"gen2-gateway: {label}", flush=True)
    code = subprocess.run(argv, cwd=cwd, env=env).returncode
    print(f"gen2-gateway: {label}: {'passed' if code == 0 else f'FAILED (exit {code})'}", flush=True)
    return code == 0


def main() -> int:
    base = {k: v for k, v in os.environ.items() if not k.startswith("RESEARCH_GATEWAY_")}
    suite = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."]
    ok = step("gateway suite without a database", suite, base, GATEWAY)
    initdb, pg_ctl = pg_bin("initdb"), pg_bin("pg_ctl")
    if not (initdb and pg_ctl):
        print("gen2-gateway: FAILED: no PostgreSQL server binaries (initdb, pg_ctl): the database cases and "
              "mutants did not run", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="gen2-gateway-pg-") as tmp:
        data, sock = Path(tmp) / "data", Path(tmp)
        subprocess.run([initdb, "-D", str(data), "-U", "gateway", "--auth=trust"], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([pg_ctl, "-D", str(data), "-o", f"-k {sock} -c listen_addresses=''", "-l", str(Path(tmp) / "log"),
                        "-w", "start"], check=True, stdout=subprocess.DEVNULL)
        try:
            subprocess.run([str(Path(pg_ctl).with_name("createdb")), "-h", str(sock), "-U", "gateway", "gateway_check"], check=True)
            env = {**base, "RESEARCH_GATEWAY_DSN": f"postgresql://gateway@/gateway_check?host={sock}", "RESEARCH_GATEWAY_TEST_OK": "1"}
            ok &= step("schema and seed", [sys.executable, "-m", "research_gateway.registry.load", "--schema", "--load",
                                           "--seed-operational"], env, GATEWAY)
            ok &= step("gateway suite on a throwaway database", suite, env, GATEWAY)
            ok &= step("gateway mutants", [sys.executable, str(ROOT / "tools" / "gen2_gateway_mutations.py")], env, ROOT)
        finally:
            subprocess.run([pg_ctl, "-D", str(data), "-m", "fast", "-w", "stop"], stdout=subprocess.DEVNULL)
    print(f"gen2-gateway: {'all checks passed' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
