"""Regression (PLAN.md §13 Phase 7): replay the 2026-09 per-source presence expectations.

The discovery phase recorded, for a sample of works, which sources held each one.
This probe re-asks a subset of those sources through the gateway's own metered
client and reports the per-source presence rate now against then. A source
that drifts by more than the tolerance (default 5 points) fails the run.

    python3 -m tests.regression.overlap_probe --expectations <path outside the public tree> --live --sample 100

The expectations file is a JSON list of {"doi": ..., "origin": ..., "found": {"crossref": true, ...}};
it comes from the private discovery tables and is not in the public tree.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

PROBES = {  # found-key -> (source id, how to ask)
    "crossref": ("crossref", "resolve"), "doaj": ("doaj", "resolve"), "openaire": ("openaire", "resolve"),
    "datacite": ("datacite", "resolve"), "unpaywall": ("unpaywall", "oa_location"), "semanticscholar": ("semanticscholar", "resolve"),
    "core": ("core", "resolve"), "europepmc": ("europepmc", "resolve"),
}


def present(adapters: dict, client, key: str, doi: str) -> bool | None:
    """Ask one source whether it has the DOI; None when the probe cannot run (refused, error)."""
    source_id, how = PROBES[key]
    mod = adapters.get(source_id)
    if mod is None:
        return None
    try:
        if how == "resolve":
            return mod.resolve(client, f"doi:{doi}") is not None
        # Unpaywall "has" a DOI when it answers with a record at all (is_oa true or false),
        # which is what the 2026-09 discovery probe recorded — not whether an OA copy exists
        return mod.enrich(client, f"doi:{doi}", "oa_location").get("is_oa") is not None
    except Exception:
        return None


MIN_AGREEMENT = 0.9   # paired: the same DOIs must answer the same way, not merely the same share of them


def compare(expected: list[dict], observed: dict[tuple[str, str], bool | None], tolerance: float,
            min_agreement: float = MIN_AGREEMENT) -> dict:
    """Per source, over the DOIs actually probed: presence rate then vs now (within `tolerance`)
    AND paired agreement (≥ `min_agreement`). At n=40 the rate tolerance alone is two works, so
    the paired gate is the one that matters; use --sample 100 or more for a real verdict."""
    out = {}
    for key in PROBES:
        then, now = [], []
        for row in expected:
            exp = (row.get("found") or {}).get(key)
            obs = observed.get((row["doi"], key))
            if exp is None or obs is None:
                continue
            then.append(bool(exp))
            now.append(bool(obs))
        if not then:
            continue
        rate_then, rate_now = sum(then) / len(then), sum(now) / len(now)
        agreement = sum(1 for a, b in zip(then, now) if a == b) / len(then)
        out[key] = {"n": len(then), "then": round(rate_then, 3), "now": round(rate_now, 3), "agreement": round(agreement, 3),
                    "ok": abs(rate_now - rate_then) <= tolerance and agreement >= min_agreement}
    return out


def render(result: dict) -> str:
    lines = [f"{'source':16} {'n':>4} {'then':>6} {'now':>6} {'agree':>6}  ok"]
    for k, v in result.items():
        lines.append(f"{k:16} {v['n']:>4} {v['then']:>6.0%} {v['now']:>6.0%} {v['agreement']:>6.0%}  {'yes' if v['ok'] else 'NO'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expectations", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--tolerance", type=float, default=0.05)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--sources", default="", help="comma-separated found-keys to probe (default: all)")
    ap.add_argument("--min-n", type=int, default=10, help="fewest comparable observations a source needs to count as verified")
    args = ap.parse_args(argv)
    keys = [k for k in PROBES if not args.sources or k in args.sources.split(",")]
    expected = json.loads(args.expectations.read_text())
    rng = random.Random(args.seed)
    rows = rng.sample(expected, min(args.sample, len(expected)))
    if not args.live:
        print(f"{len(rows)} of {len(expected)} works would be probed against {sorted(keys)}; add --live to run")
        return 0
    import os

    from research_gateway import adapters
    from research_gateway.app import Gateway, load_settings
    from research_gateway.core import db
    from research_gateway.smoke import service_is_running
    if service_is_running() and os.environ.get("RESEARCH_GATEWAY_ALLOW_CONCURRENT") != "1":
        print("refusing: a gateway service is running and owns these sources' limits (I-1). "
              "Stop it, or set RESEARCH_GATEWAY_ALLOW_CONCURRENT=1 knowingly.", file=sys.stderr)
        return 2
    gw = Gateway(load_settings(), use_db=False)
    mods = adapters.load_all()
    observed = {}
    with db.connect() as conn:
        client = gw.make_client(conn, client_id="regression")
        for row in rows:
            for key in keys:
                if (row.get("found") or {}).get(key) is None:
                    continue
                observed[(row["doi"], key)] = present(mods, client, key, row["doi"])
    result = compare(rows, observed, args.tolerance)
    print(render(result))
    if args.report:
        args.report.write_text(json.dumps({"sample": len(rows), "result": result}, indent=1))
    # coverage gate: a source that produced nothing comparable was NOT verified — that is a
    # failure of the run, never a silent pass (D-23)
    uncompared = [k for k in keys if k not in result or result[k]["n"] < args.min_n]
    if uncompared:
        print(f"FAIL: fewer than {args.min_n} comparable observations for {', '.join(uncompared)} — "
              "sources unavailable or expectations too thin; nothing was verified for them (D-24)", file=sys.stderr)
        return 1
    return 0 if all(v["ok"] for v in result.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
