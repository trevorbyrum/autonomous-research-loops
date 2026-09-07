"""Phase 3 live smoke (PLAN.md §13): one minimal call per adapter capability.

Each adapter declares its own probe in a `SMOKE` attribute (I-2): adding a source
never edits this file. Prints what each source actually answered — status,
latency, rate-limit headers, failure class — so the operator can turn "(verify)"
rows in the seed into verified evidence. Nothing here writes to the registry.

The smoke refuses to run while a gateway service owns the same limits, unless
RESEARCH_GATEWAY_ALLOW_CONCURRENT=1 (I-1, D-23). With a database configured its
calls are logged like everyone else's, under client id `smoke`.

    python3 -m research_gateway.smoke                # plan only (no network)
    python3 -m research_gateway.smoke --live         # run it
    python3 -m research_gateway.smoke --live --only fred,bea --report out.json --strict
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import adapters
from .adapters.base import AdapterError, Client, SourceUnavailable
from .core import db
from .core.broker import Broker, policies_from_rows
from .core.secrets import from_config
from .registry.load import read_seed


def probes() -> tuple[dict[str, dict], dict[str, str]]:
    """(source id -> SMOKE spec) for network probes, (source id -> reason) for local-only ones."""
    plan, local = {}, {}
    for sid, mod in adapters.load_all().items():
        spec = getattr(mod, "SMOKE", None)
        if spec is None:
            raise RuntimeError(f"adapter {sid} declares no SMOKE probe (I-2)")
        if "local" in spec:
            local[sid] = spec["local"]
        else:
            plan[sid] = spec
    return plan, local


def probe_call(mod, spec: dict):
    cap = spec["capability"]
    if cap == "find":
        return lambda c: mod.find(c, spec["query"], limit=spec.get("limit", 1))
    if cap == "resolve":
        return lambda c: mod.resolve(c, spec["identity"])
    if cap == "enrich":
        return lambda c: mod.enrich(c, spec["identity"], spec["what"])
    if cap == "data":
        return lambda c: mod.data(c, dict(spec["params"]))
    if cap == "fetch":
        return (lambda c: mod.fetch(c)) if spec.get("target") is None else (lambda c: mod.fetch(c, spec["target"]))
    raise RuntimeError(f"unknown smoke capability {cap!r}")


def build_client(seed: list[dict], transport=None, secrets=None, conn=None) -> Client:
    """A client whose broker carries every seeded policy — the smoke *is* the verification step."""
    rows = [{"source_id": s["id"], **s.get("rate", {})} for s in seed if s["kind"] != "manual"]
    email = os.environ.get("RESEARCH_GATEWAY_CONTACT_EMAIL", "gateway@example.org")
    kw = {"transport": transport} if transport is not None else {}
    backend = secrets if secrets is not None else from_config(os.environ.get("RESEARCH_GATEWAY_SECRETS", "env"))
    return Client(broker=Broker(policies_from_rows(rows)), secrets=backend.get, contact_email=email,
                  user_agent=f"research-gateway/0.1 (mailto:{email})", conn=conn, client_id="smoke", **kw)


def run(client: Client, only: set[str] | None = None) -> list[dict]:
    plan, local = probes()
    mods = adapters.load_all()
    out = []
    for sid, spec in plan.items():
        if only and sid not in only:
            continue
        before = len(client.log)
        t0 = time.monotonic()
        row = {"source": sid, "capability": spec["capability"], "outcome": "ok", "detail": None}
        try:
            result = probe_call(mods[sid], spec)(client)
            if isinstance(result, dict) and "records" not in result and "items" not in result:
                row["detail"] = "1 record: " + str(result.get("identity") or result.get("agency"))
            elif isinstance(result, dict):
                row["detail"] = result.get("capability_fact") or f"records={len(result.get('records') or result.get('items') or [])}"
            elif result is None:
                row["detail"] = "not found"
        except SourceUnavailable as e:
            row["outcome"], row["detail"] = "unavailable", str(e)
        except AdapterError as e:
            row["outcome"], row["detail"] = "adapter-error", str(e)
        except Exception as e:  # a crash is a finding, not a reason to stop the smoke
            row["outcome"], row["detail"] = "crash", f"{type(e).__name__}: {e}"
        row["seconds"] = round(time.monotonic() - t0, 2)
        row["calls"] = [{"status": r.status, "class": r.failure_class, "latency_ms": r.latency_ms, "ratelimit": r.ratelimit}
                        for r in client.log[before:]]
        if row["outcome"] == "ok" and not row["calls"]:
            row["outcome"] = "unverified"   # a refusal without a network call verified nothing (D-24)
        out.append(row)
    for sid, why in local.items():
        if not only or sid in only:
            out.append({"source": sid, "capability": "-", "outcome": "skipped", "detail": why, "seconds": 0, "calls": []})
    return out


def render(rows: list[dict]) -> str:
    lines = [f"{'source':18} {'cap':8} {'outcome':13} {'status':7} {'ms':>6}  detail / rate-limit headers"]
    for r in rows:
        status = ",".join(str(c["status"]) for c in r["calls"]) or "-"
        ms = ",".join(str(c["latency_ms"]) for c in r["calls"]) or "-"
        headers = {k: v for c in r["calls"] for k, v in (c["ratelimit"] or {}).items()}
        lines.append(f"{r['source']:18} {r['capability']:8} {r['outcome']:13} {status:7} {ms:>6}  {r['detail'] or ''}"
                     + (f"  {json.dumps(headers)}" if headers else ""))
    return "\n".join(lines)


def service_is_running() -> bool:
    """True unless the gateway URL is positively ABSENT (connection refused / no route). Any
    answer — healthy, unhealthy, 401, 503 — and any timeout means something may own the limits,
    and the guard fails safe (I-1, D-24)."""
    from .clients.http_client import from_env
    client = from_env()
    client.timeout = 3.0
    health = client.health()
    fact = str(health.get("capability_fact") or "")
    if not fact:
        return True                      # it answered: it is running
    if fact != "gateway_unavailable":
        return True                      # it answered with an error status: still running
    return "timed out" in str(health.get("error") or "").lower()   # a hang is not proof of absence


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="actually call the sources (one request each)")
    ap.add_argument("--only", default="", help="comma-separated source ids")
    ap.add_argument("--report", default="", help="write the JSON report here")
    ap.add_argument("--strict", action="store_true", help="unavailable sources fail the run too")
    args = ap.parse_args(argv)
    only = {s for s in args.only.split(",") if s} or None
    plan, _ = probes()
    if not args.live:
        for sid, spec in plan.items():
            if not only or sid in only:
                print(f"{sid:18} {spec['capability']}")
        print("(add --live to run)")
        return 0
    if service_is_running() and os.environ.get("RESEARCH_GATEWAY_ALLOW_CONCURRENT") != "1":
        print("refusing: a gateway service is running and owns these sources' limits (I-1). "
              "Stop it, or set RESEARCH_GATEWAY_ALLOW_CONCURRENT=1 knowingly.", file=sys.stderr)
        return 2
    conn = db.connect() if db.configured() else None
    try:
        rows = run(build_client(read_seed(), conn=conn), only)
    finally:
        if conn is not None:
            conn.close()
    print(render(rows))
    if args.report:
        with open(args.report, "w") as f:
            json.dump(rows, f, indent=1)
        print(f"report: {args.report}")
    bad = [r for r in rows if r["outcome"] in ("crash", "adapter-error")]
    unverified = [r for r in rows if r["outcome"] in ("unavailable", "unverified")]
    if unverified:
        print(f"note: {len(unverified)} source(s) unavailable or unverified — their limits were NOT verified by this run: "
              + ", ".join(r["source"] for r in unverified), file=sys.stderr)
    return 1 if bad or (args.strict and unverified) else 0


if __name__ == "__main__":
    sys.exit(main())
