"""Phase 3 live smoke (PLAN.md §13): one minimal call per adapter capability.

Prints what each source actually answered — status, latency, rate-limit
headers, failure class — so the operator can turn "(verify)" rows in the seed
into verified evidence. Nothing here writes to the registry; the seed stays the
source of truth and is edited by hand from this report.

    python3 -m research_gateway.smoke                # plan only (no network)
    python3 -m research_gateway.smoke --live         # run it
    python3 -m research_gateway.smoke --live --only fred,bea --report out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Callable

from . import adapters
from .adapters.base import AdapterError, Client, SourceUnavailable
from .core.broker import Broker, policies_from_rows
from .core.secrets import from_config
from .registry.load import read_seed

DOI = "doi:10.1038/nature12373"        # a Crossref-registered article with open-access locations
DATASET_DOI = "doi:10.7910/DVN/OY6CBK"  # the World Management Survey on Harvard Dataverse (DataCite DOI)

# (source id, capability, callable(module, client)) — each makes the smallest sensible request.
PLAN: list[tuple[str, str, Callable]] = [
    ("crossref", "resolve", lambda m, c: m.resolve(c, DOI)),
    ("doaj", "find", lambda m, c: m.find(c, "management", limit=1)),
    ("datacite", "resolve", lambda m, c: m.resolve(c, DATASET_DOI)),
    ("unpaywall", "enrich", lambda m, c: m.enrich(c, DOI, "oa_location")),
    ("opencitations", "enrich", lambda m, c: m.enrich(c, "doi:10.1162/qss_a_00023", "references")),
    ("openaire", "find", lambda m, c: m.find(c, "management practices", limit=1)),
    ("semanticscholar", "resolve", lambda m, c: m.resolve(c, DOI)),
    ("core", "resolve", lambda m, c: m.resolve(c, DOI)),
    ("europepmc", "resolve", lambda m, c: m.resolve(c, DOI)),
    ("doi_org", "resolve", lambda m, c: m.resolve(c, DOI)),
    ("govinfo", "find", lambda m, c: m.find(c, "artificial intelligence", limit=1)),
    ("harvard_dataverse", "resolve", lambda m, c: m.resolve(c, DATASET_DOI)),
    ("wms", "fetch", lambda m, c: m.fetch(c)),
    ("qdr", "find", lambda m, c: m.find(c, "interview", limit=1)),
    ("socrata", "find", lambda m, c: m.find(c, "business licenses", limit=1)),
    ("kaggle", "find", lambda m, c: m.find(c, "housing prices", limit=1)),
    ("huggingface", "resolve", lambda m, c: m.resolve(c, "stanfordnlp/imdb")),
    ("openml", "resolve", lambda m, c: m.resolve(c, "openml:61")),
    ("fred", "data", lambda m, c: m.data(c, {"series": "GDP", "limit": 1, "include_meta": False})),
    ("bea", "data", lambda m, c: m.data(c, {"method": "GETDATASETLIST"})),
    ("census", "data", lambda m, c: m.data(c, {"dataset": "2022/acs/acs1", "get": ["NAME"], "for": "state:37"})),
    ("bls", "data", lambda m, c: m.data(c, {"series": "CUUR0000SA0", "start_year": 2025, "end_year": 2025})),
    ("bis", "data", lambda m, c: m.data(c, {"dataflow": "WS_EER", "key": "M.N.B.US", "start": "2026-01"})),
    ("ecb", "data", lambda m, c: m.data(c, {"dataflow": "EXR", "key": "D.USD.EUR.SP00.A", "start": "2026-08-01"})),
]
LOCAL_ONLY = {"openalex_snapshot": "local index, no network", "globe": "static files; nothing to probe without a file URL"}


def build_client(seed: list[dict], transport=None, secrets=None) -> Client:
    """A client whose broker carries every seeded policy — the smoke *is* the verification step."""
    rows = [{"source_id": s["id"], **s.get("rate", {})} for s in seed if s["kind"] != "manual"]
    email = os.environ.get("RESEARCH_GATEWAY_CONTACT_EMAIL", "gateway@example.org")
    kw = {"transport": transport} if transport is not None else {}
    backend = secrets if secrets is not None else from_config(os.environ.get("RESEARCH_GATEWAY_SECRETS", "env"))
    return Client(broker=Broker(policies_from_rows(rows)), secrets=backend.get, contact_email=email,
                  user_agent=f"research-gateway/0.1 (mailto:{email})", **kw)


def run(client: Client, only: set[str] | None = None) -> list[dict]:
    mods = adapters.load_all()
    out = []
    for sid, cap, call in PLAN:
        if only and sid not in only:
            continue
        before = len(client.log)
        t0 = time.monotonic()
        row = {"source": sid, "capability": cap, "outcome": "ok", "detail": None}
        try:
            result = call(mods[sid], client)
            if isinstance(result, dict):
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
        out.append(row)
    for sid, why in LOCAL_ONLY.items():
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--live", action="store_true", help="actually call the sources (one request each)")
    ap.add_argument("--only", default="", help="comma-separated source ids")
    ap.add_argument("--report", default="", help="write the JSON report here")
    args = ap.parse_args(argv)
    only = {s for s in args.only.split(",") if s} or None
    if not args.live:
        for sid, cap, _ in PLAN:
            if not only or sid in only:
                print(f"{sid:18} {cap}")
        print("(add --live to run)")
        return 0
    rows = run(build_client(read_seed()), only)
    print(render(rows))
    if args.report:
        with open(args.report, "w") as f:
            json.dump(rows, f, indent=1)
        print(f"report: {args.report}")
    bad = [r for r in rows if r["outcome"] in ("crash", "adapter-error")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
