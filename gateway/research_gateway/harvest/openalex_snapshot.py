"""OpenAlex *sources* snapshot → Tier 0 index (PLAN.md §8, D-2: never the API).

The operator fetches the snapshot the way OpenAlex documents it (an S3 sync of
`data/sources/`, no key needed) and points this loader at the directory; it
reads the gzipped JSON-lines part files and never opens a network connection.

    python3 -m research_gateway.harvest.openalex_snapshot /path/to/openalex-snapshot/data/sources [--limit N]

WHAT A FAILURE COSTS (task 2b-repair-14; Astra R13C-4; the accepted scope of 2b-repair-8). The unit of a snapshot is its LINE: JSON Lines frames each source object on a line of its own,
so a line that cannot be read does not touch the lines beside it. A line that is not JSON in the gateway's strict reading (core/wire.py: not UTF-8, a name twice, `NaN`, a number past a
double, nesting past the limit, text after the object), one that is JSON but not a source object, and one that holds an object no record can be made of is REFUSED — never skipped
silently: it is counted and named in the `LineReport` the caller passes (its file and line, and why), and the readable lines around it are loaded. A FILE that cannot be read, decompressed
or framed (a truncated or corrupt gzip member, a file that is not gzip, an unreadable path) fails the load, naming the file: nothing says which of its lines were lost. This loader is not a
lane of the live gateway: it loads a local subset into the index, and a load that refused lines is a load of the rest, reported; it claims nothing about the snapshot's completeness.
An uncompressed `.jsonl` file cut mid-line has a refused last line like any other; one cut at a line boundary is a shorter file (nothing in JSON Lines marks the end).
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import zlib
from pathlib import Path
from typing import Iterator

from ..core import db, wire
from ..core.canonical import make_record
from ..core.payload import PayloadError
from ..core.identity import normalize_issn
from . import index

SOURCE_ID = "openalex_snapshot"
REPOSITORY_TYPES = {"repository"}


class LineReport:
    """The lines a load refused: how many, and which (file, line number and why), the first `keep` of them in full — a snapshot of garbage must not fill memory with its own account."""

    def __init__(self, keep: int = 1000):
        self.keep, self.count, self.lines = keep, 0, []

    def refuse(self, path: Path, number: int, why: str) -> None:
        self.count += 1
        if len(self.lines) < self.keep:
            self.lines.append(f"{path.name} line {number}: {why}"[:300])

    def as_dict(self) -> dict:
        return {"refused": self.count, "refused_lines": self.lines, "refused_lines_listed": len(self.lines)}


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


def read_snapshot(root: Path, *, report: LineReport, limit: int | None = None, issn_map: index.IssnMap | None = None) -> Iterator[dict]:
    """Every source object in the snapshot directory (part files under updated_date=* folders). A line that cannot be read, or made a record of, is refused into `report` (see the module
    docstring) and the lines beside it are read; a file that cannot be read, decompressed or framed is a PayloadError."""
    n = 0
    files = sorted(root.rglob("*.gz")) + sorted(p for p in root.rglob("*.jsonl") if p.is_file()) + sorted(root.rglob("*.json"))
    for path in files:
        opener = gzip.open if path.suffix == ".gz" else open
        try:
            with opener(path, "rb") as f:   # bytes: each line is decoded (UTF-8, strictly) by the opener on its own, so an invalid byte spoils its line and no other
                for number, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = wire.open_json(line)
                    except wire.Malformed as e:
                        report.refuse(path, number, str(e))
                        continue
                    if not isinstance(obj, dict):
                        report.refuse(path, number, f"JSON that is not a source object ({type(obj).__name__})")
                        continue
                    try:
                        rec = record_from(obj, issn_map)
                    except (ValueError, TypeError, AttributeError) as e:
                        report.refuse(path, number, f"a source object no record can be made of ({type(e).__name__}: {str(e)[:100]})")
                        continue
                    if rec is None:
                        report.refuse(path, number, "a source object with no id")
                        continue
                    yield rec
                    n += 1
                    if limit and n >= limit:
                        return
        except (OSError, EOFError, zlib.error) as e:   # gzip.BadGzipFile is an OSError; a gzip member cut short is an EOFError; a corrupt one a zlib.error
            raise PayloadError(f"{path.name}: the file cannot be read, decompressed or framed ({type(e).__name__}: {e})") from None


def run(conn, root: Path, *, report: LineReport, limit: int | None = None) -> int:
    return index.load(conn, lambda: read_snapshot(root, report=report, limit=limit, issn_map=index.IssnMap(conn)),
                      SOURCE_ID, metadata_license="CC0")   # the snapshot's own licence, not its works' (A3)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot_dir", type=Path)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    if not args.snapshot_dir.is_dir():
        print(f"not a directory: {args.snapshot_dir}", file=sys.stderr)
        return 2
    report = LineReport()
    with db.connect() as conn:
        n = run(conn, args.snapshot_dir, report=report, limit=args.limit)
        with conn.cursor() as cur:  # proof of a COMPLETED refresh, written only on success (8f, finding 5); it says how many lines were refused
            cur.execute("INSERT INTO gateway.meta (key, value, updated_at) VALUES (%s, %s, now()) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                        (f"harvest:{SOURCE_ID}", json.dumps({"loaded": n, "limit": args.limit, "refused_lines": report.count,
                                                             "snapshot_dir": str(args.snapshot_dir)})))
        conn.commit()
        print(json.dumps({"loader": SOURCE_ID, "loaded": n, **report.as_dict(), **index.counts(conn)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
