"""OpenAlex *sources* snapshot → Tier 0 index (PLAN.md §8, D-2: never the API).

The operator fetches the snapshot the way OpenAlex documents it (an S3 sync of
`data/sources/`, no key needed) and points this loader at the directory; it
reads the gzipped JSON-lines part files and never opens a network connection.

    python3 -m research_gateway.harvest.openalex_snapshot /path/to/openalex-snapshot/data/sources [--limit N]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Iterator

from ..core import db
from ..core.canonical import make_record
from ..core.identity import normalize_issn
from . import index

SOURCE_ID = "openalex_snapshot"
REPOSITORY_TYPES = {"repository"}


def record_from(s: dict, issn_map: index.IssnMap | None = None) -> dict | None:
    if not isinstance(s, dict):
        return None
    oid = str(s.get("id") or "").rsplit("/", 1)[-1]
    if not oid:
        return None
    issns = [i for i in (normalize_issn(x) for x in list(s.get("issn") or []) + [s.get("issn_l")] if isinstance(x, str)) if i]
    issn_l = normalize_issn(s.get("issn_l")) or (issns[0] if issns else None)
    kind = "repository" if s.get("type") in REPOSITORY_TYPES else "venue"
    identity = f"issn:{issn_l}" if issn_l else f"{kind}:openalex:{oid.lower()}"
    if issn_l and issn_map is not None:
        identity = issn_map.identity_for(issns, identity)
    ids = {"openalex": oid}
    if issn_l:
        ids["issn"] = issn_l
    topics = [t.get("display_name") for t in s.get("topics") or [] if isinstance(t, dict) and t.get("display_name")]
    concepts = [c.get("display_name") for c in s.get("x_concepts") or [] if isinstance(c, dict) and c.get("display_name")]
    return make_record(identity=identity, kind=kind, source_id=SOURCE_ID, title=s.get("display_name"),
                       venue=s.get("host_organization_name"), identifiers=ids,
                       links=[u for u in (s.get("homepage_url"),) if u],
                       extra={"issns": issns, "type": s.get("type"), "works_count": s.get("works_count"),
                              "cited_by_count": s.get("cited_by_count"), "is_oa": s.get("is_oa"), "in_doaj": s.get("is_in_doaj"),
                              "is_core": s.get("is_core"), "country": s.get("country_code"), "subjects": (topics or concepts)[:25],
                              "aliases": s.get("alternate_titles") or []},
                       raw=s)


def read_snapshot(root: Path, *, limit: int | None = None, issn_map: index.IssnMap | None = None) -> Iterator[dict]:
    """Every source object in the snapshot directory (part files under updated_date=* folders)."""
    n = 0
    files = sorted(root.rglob("*.gz")) + sorted(p for p in root.rglob("*.jsonl") if p.is_file()) + sorted(root.rglob("*.json"))
    for path in files:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    rec = record_from(obj, issn_map)
                except (ValueError, TypeError, AttributeError):
                    continue
                if rec is None:
                    continue
                yield rec
                n += 1
                if limit and n >= limit:
                    return


def run(conn, root: Path, *, limit: int | None = None) -> int:
    return index.load(conn, lambda: read_snapshot(root, limit=limit, issn_map=index.IssnMap(conn)),
                      SOURCE_ID, license="CC0")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot_dir", type=Path)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    if not args.snapshot_dir.is_dir():
        print(f"not a directory: {args.snapshot_dir}", file=sys.stderr)
        return 2
    with db.connect() as conn:
        n = run(conn, args.snapshot_dir, limit=args.limit)
        with conn.cursor() as cur:  # proof of a COMPLETED refresh, written only on success (8f, finding 5)
            cur.execute("INSERT INTO gateway.meta (key, value, updated_at) VALUES (%s, %s, now()) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                        (f"harvest:{SOURCE_ID}", json.dumps({"loaded": n, "limit": args.limit,
                                                             "snapshot_dir": str(args.snapshot_dir)})))
        conn.commit()
        print(json.dumps({"loader": SOURCE_ID, "loaded": n, **index.counts(conn)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
