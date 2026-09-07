"""Validate the source seed and mirror it into Postgres.

    python -m research_gateway.registry.load --dry-run          # validate only
    python -m research_gateway.registry.load --check-adapters   # adapters <-> seed (I-2)
    python -m research_gateway.registry.load --schema --load    # apply schema, upsert seed

Connection: RESEARCH_GATEWAY_DSN (a libpq URI). Nothing private is read from
the tree; deployments set the variable.
"""
from __future__ import annotations

import argparse
import os
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = HERE / "seed" / "sources.toml"
SCHEMA = HERE / "schema.sql"
ADAPTERS = HERE.parent / "adapters"

KINDS = {"article", "dataset", "citation", "resolver", "statistical", "manual"}
CAPABILITIES = {"find", "resolve", "enrich", "fetch", "data", "catalog"}
AUTH = {"none", "email", "key", "optional_token", "client_credentials", "username_key", "account"}
VERDICTS = {"allow", "per-item", "deny", "unknown"}
DOMAINS = {"finance", "market", "social", "management", "ai-ml", "software", "biomed"}
RATE_FIELDS = {"per_second", "per_minute", "per_hour", "per_day", "cost_cap_per_day", "burst", "verified", "evidence"}
REQUIRED = ("id", "name", "kind", "homepage", "capabilities", "auth", "use_commercial", "use_evidence", "rate")


def read_seed(path: Path = SEED) -> list[dict]:
    with open(path, "rb") as f:
        return tomllib.load(f)["source"]


def validate(sources: list[dict]) -> list[str]:
    """Return a list of problems; empty means the seed is sound."""
    problems: list[str] = []
    seen: set[str] = set()
    for s in sources:
        sid = s.get("id", "<missing id>")
        for key in REQUIRED:
            if key not in s:
                problems.append(f"{sid}: missing {key}")
        if sid in seen:
            problems.append(f"{sid}: duplicate id")
        seen.add(sid)
        if s.get("kind") not in KINDS:
            problems.append(f"{sid}: kind {s.get('kind')!r} not in {sorted(KINDS)}")
        caps = set(s.get("capabilities", []))
        if not caps <= CAPABILITIES:
            problems.append(f"{sid}: capabilities {sorted(caps - CAPABILITIES)} unknown")
        if s.get("kind") == "manual" and caps:
            problems.append(f"{sid}: manual sources cannot declare capabilities")
        if s.get("kind") != "manual" and not caps:
            problems.append(f"{sid}: no capabilities")
        if s.get("auth") not in AUTH:
            problems.append(f"{sid}: auth {s.get('auth')!r} not in {sorted(AUTH)}")
        if s.get("auth") in {"key", "client_credentials", "username_key"} and not s.get("secret_ref"):
            problems.append(f"{sid}: auth {s['auth']} requires secret_ref")
        if s.get("use_commercial") not in VERDICTS:
            problems.append(f"{sid}: use_commercial {s.get('use_commercial')!r} not in {sorted(VERDICTS)}")
        bad_domains = set(s.get("domains", [])) - DOMAINS
        if bad_domains:
            problems.append(f"{sid}: unknown domains {sorted(bad_domains)}")
        rate = s.get("rate", {})
        extra = set(rate) - RATE_FIELDS
        if extra:
            problems.append(f"{sid}: unknown rate fields {sorted(extra)}")
        if "verified" not in rate or "evidence" not in rate:
            problems.append(f"{sid}: rate needs verified and evidence")
        if "verified" in rate and not isinstance(rate["verified"], bool):
            problems.append(f"{sid}: rate.verified must be true or false")
        for k in ("per_second", "per_minute", "per_hour", "per_day", "cost_cap_per_day"):
            v = rate.get(k)
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0):
                problems.append(f"{sid}: rate.{k} must be a positive number")
        burst = rate.get("burst")
        if burst is not None and (isinstance(burst, bool) or not isinstance(burst, int) or burst <= 0):
            problems.append(f"{sid}: rate.burst must be a positive integer")
        if s.get("enabled") and not rate.get("verified"):
            problems.append(f"{sid}: enabled but rate not verified (PLAN §3)")
        if s.get("kind") not in {"manual", "article"} or sid != "openalex_snapshot":
            limits = {k for k in ("per_second", "per_minute", "per_hour", "per_day") if rate.get(k)}
            if s.get("kind") != "manual" and sid != "openalex_snapshot" and not limits:
                problems.append(f"{sid}: no rate limit set (I-3: unscheduled without one)")
        if "key_instructions" not in s:
            problems.append(f"{sid}: key_instructions required for the docs (I-9)")
    return problems


def check_adapters(sources: list[dict]) -> tuple[list[str], list[str]]:
    """(orphan adapters without a seed row, seeded sources without an adapter)."""
    ids = {s["id"] for s in sources if s["kind"] != "manual"}
    present: set[str] = set()
    if ADAPTERS.is_dir():
        present = {p.stem for p in ADAPTERS.glob("*.py") if p.stem not in {"__init__", "base"}}
    return sorted(present - ids), sorted(ids - present)


def _sql_array(values: list[str]) -> str:
    return "{" + ",".join('"' + v.replace('"', '\\"') + '"' for v in values) + "}"


def load(sources: list[dict], dsn: str, apply_schema: bool, *, seed_operational: bool = False) -> None:
    """Upsert the seed. A catalogue update and a deployment decision are different acts (8f):
    on an EXISTING row the deployed `enabled` flag is preserved — the operator's on/off
    switch survives every reload — unless `seed_operational` deliberately reasserts the
    seed's values (fresh deploys, or an operator reset). New rows always take the seed's."""
    import psycopg  # the one allowed driver (I-12); imported here so --dry-run needs no DB

    enabled_update = "enabled=EXCLUDED.enabled" if seed_operational else "enabled=gateway.sources.enabled"
    # rate caps and their verified state are deployment overrides too (pass-1 finding 12):
    # an ordinary catalogue reload refreshes only the evidence link; --seed-operational
    # reasserts the seed's numbers deliberately
    rate_update = ("per_second=EXCLUDED.per_second, per_minute=EXCLUDED.per_minute, per_hour=EXCLUDED.per_hour, "
                   "per_day=EXCLUDED.per_day, cost_cap_per_day=EXCLUDED.cost_cap_per_day, burst=EXCLUDED.burst, "
                   "verified=EXCLUDED.verified, evidence=EXCLUDED.evidence") if seed_operational else "evidence=EXCLUDED.evidence"
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        if apply_schema:
            cur.execute(SCHEMA.read_text())
        for s in sources:
            cur.execute(
                f"""
                INSERT INTO gateway.sources (id, name, kind, homepage, docs_url, capabilities, identifiers,
                    base_for, domains, auth, secret_ref, key_instructions, license, use_commercial,
                    use_evidence, freshness_lag, substitution_group, enabled, notes, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (id) DO UPDATE SET
                    name=EXCLUDED.name, kind=EXCLUDED.kind, homepage=EXCLUDED.homepage,
                    docs_url=EXCLUDED.docs_url, capabilities=EXCLUDED.capabilities,
                    identifiers=EXCLUDED.identifiers, base_for=EXCLUDED.base_for, domains=EXCLUDED.domains,
                    auth=EXCLUDED.auth, secret_ref=EXCLUDED.secret_ref, key_instructions=EXCLUDED.key_instructions,
                    license=EXCLUDED.license, use_commercial=EXCLUDED.use_commercial,
                    use_evidence=EXCLUDED.use_evidence, freshness_lag=EXCLUDED.freshness_lag,
                    substitution_group=EXCLUDED.substitution_group, {enabled_update},
                    notes=EXCLUDED.notes, updated_at=now()
                """,
                (s["id"], s["name"], s["kind"], s.get("homepage"), s.get("docs_url"),
                 _sql_array(s.get("capabilities", [])), _sql_array(s.get("identifiers", [])),
                 _sql_array(s.get("base_for", [])), _sql_array(s.get("domains", [])),
                 s["auth"], s.get("secret_ref") or None, s.get("key_instructions"), s.get("license"),
                 s["use_commercial"], s.get("use_evidence"), s.get("freshness_lag"),
                 s.get("substitution_group") or None, bool(s.get("enabled", False)), s.get("notes")),
            )
            r = s["rate"]
            cur.execute(
                f"""
                INSERT INTO gateway.rate_policies (source_id, per_second, per_minute, per_hour, per_day,
                    cost_cap_per_day, burst, verified, evidence)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_id) DO UPDATE SET
                    {rate_update}
                """,
                (s["id"], r.get("per_second"), r.get("per_minute"), r.get("per_hour"), r.get("per_day"),
                 r.get("cost_cap_per_day"), r.get("burst"), bool(r.get("verified", False)), r.get("evidence")),
            )
        conn.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="validate the seed and print a summary")
    ap.add_argument("--check-adapters", action="store_true", help="adapters directory <-> seed consistency")
    ap.add_argument("--schema", action="store_true", help="apply schema.sql before loading")
    ap.add_argument("--load", action="store_true", help="upsert the seed into gateway.sources / rate_policies")
    ap.add_argument("--dsn", default=os.environ.get("RESEARCH_GATEWAY_DSN"), help="libpq URI (default: $RESEARCH_GATEWAY_DSN)")
    ap.add_argument("--seed-operational", action="store_true",
                    help="also reassert the seed's enabled flags on EXISTING rows (a deployment "
                         "reset); by default a reload updates the catalogue and preserves the "
                         "deployed on/off switches (8f)")
    args = ap.parse_args(argv)

    sources = read_seed()
    problems = validate(sources)
    if problems:
        print("seed INVALID:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 2

    if args.dry_run or not (args.check_adapters or args.load or args.schema):
        kinds: dict[str, int] = {}
        for s in sources:
            kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
        enabled = sum(1 for s in sources if s.get("enabled"))
        verified = sum(1 for s in sources if s["rate"].get("verified"))
        print(f"seed OK: {len(sources)} sources; enabled {enabled}; rate-verified {verified}; by kind {kinds}")

    rc = 0
    if args.check_adapters:
        orphans, missing = check_adapters(sources)
        print(f"adapters: {len(missing)} seeded sources without an adapter; {len(orphans)} orphan adapters")
        if missing:
            print("  missing:", ", ".join(missing))
        if orphans:
            print("  ORPHANS (I-2 violation):", ", ".join(orphans), file=sys.stderr)
            rc = 3

    if args.load or args.schema:
        if not args.dsn:
            print("RESEARCH_GATEWAY_DSN is not set", file=sys.stderr)
            return 4
        load(sources, args.dsn, apply_schema=args.schema, seed_operational=args.seed_operational)
        print(f"loaded {len(sources)} sources into gateway.sources (schema {'applied' if args.schema else 'unchanged'}; "
              f"enabled flags {'reasserted from seed' if args.seed_operational else 'preserved on existing rows'})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
