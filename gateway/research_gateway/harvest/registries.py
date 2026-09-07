"""Registry loaders for the Tier 0 index (PLAN.md §8): Crossref journals, DOAJ journals,
DataCite repositories — each through the metered client under its own source's policy.

    python3 -m research_gateway.harvest.registries crossref [--limit N]
    python3 -m research_gateway.harvest.registries doaj
    python3 -m research_gateway.harvest.registries datacite
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from typing import Iterator

from ..adapters.base import Client, check
from ..core import db
from ..core.canonical import make_record
from ..core.identity import normalize_issn
from . import index

CROSSREF_JOURNALS = "https://api.crossref.org/journals"
DOAJ_CSV = "https://doaj.org/csv"
DATACITE_REPOSITORIES = "https://api.datacite.org/repositories"


def venue_identity(issns: list[str | None], fallback: str) -> tuple[str, list[str]]:
    clean = [i for i in (normalize_issn(x) for x in issns if x) if i]
    return (f"issn:{clean[0]}" if clean else fallback), clean


# ---------------------------------------------------------------- Crossref journals
def crossref_journals(client: Client, *, limit: int | None = None, rows: int = 1000) -> Iterator[dict]:
    cursor, seen = "*", 0
    while cursor:
        resp = client.get("crossref", "find", CROSSREF_JOURNALS,
                          params={"rows": rows, "cursor": cursor, "mailto": client.contact_email}, query="journals harvest")
        if not check("crossref", resp):
            return
        msg = (resp.json or {}).get("message") or {}
        items = msg.get("items") or []
        for j in items:
            issns = [x.get("value") for x in j.get("issn-type") or []] or j.get("ISSN") or []
            identity, clean = venue_identity(issns, f"venue:crossref:{(j.get('title') or '').lower()[:80]}")
            if not clean and not j.get("title"):
                continue
            counts = j.get("counts") or {}
            yield make_record(identity=identity, kind="venue", source_id="crossref", title=j.get("title"), venue=j.get("publisher"),
                              identifiers={"issn": clean[0]} if clean else {}, links=[],
                              extra={"issns": clean, "subjects": [s.get("name") for s in j.get("subjects") or [] if s.get("name")],
                                     "works_count": counts.get("total-dois"), "current_dois": counts.get("current-dois")},
                              raw=j)
            seen += 1
            if limit and seen >= limit:
                return
        cursor = msg.get("next-cursor") if items and len(items) >= rows else None


# ---------------------------------------------------------------- DOAJ journals (CSV)
def doaj_journals(client: Client, *, limit: int | None = None) -> Iterator[dict]:
    resp = client.get("doaj", "find", DOAJ_CSV, headers={"Accept": "text/csv"}, query="journals csv")
    if not check("doaj", resp):
        return
    reader = csv.DictReader(io.StringIO(resp.text))
    for n, row in enumerate(reader, 1):
        title = row.get("Journal title")
        identity, clean = venue_identity([row.get("Journal ISSN (print version)"), row.get("Journal EISSN (online version)")],
                                         f"venue:doaj:{(title or '').lower()[:80]}")
        if not clean and not title:
            continue
        subjects = [s.strip() for s in (row.get("Subjects") or "").split("|") if s.strip()]
        yield make_record(identity=identity, kind="venue", source_id="doaj", title=title, venue=row.get("Publisher"),
                          identifiers={"issn": clean[0]} if clean else {}, links=[u for u in (row.get("Journal URL"),) if u],
                          license=row.get("Journal license"),
                          extra={"issns": clean, "subjects": subjects, "country": row.get("Country of publisher"),
                                 "in_doaj": True, "apc": row.get("APC"), "language": row.get("Languages in which the journal accepts manuscripts")},
                          raw=row)
        if limit and n >= limit:
            return


# ---------------------------------------------------------------- DataCite repositories
def datacite_repositories(client: Client, *, limit: int | None = None, size: int = 1000) -> Iterator[dict]:
    page, seen = 1, 0
    while True:
        resp = client.get("datacite", "find", DATACITE_REPOSITORIES, params={"page[size]": size, "page[number]": page},
                          query="repositories harvest")
        if not check("datacite", resp):
            return
        j = resp.json or {}
        data = j.get("data") or []
        for d in data:
            a = d.get("attributes") or {}
            symbol = (a.get("symbol") or d.get("id") or "").lower()
            if not symbol:
                continue
            yield make_record(identity=f"repository:datacite:{symbol}", kind="repository", source_id="datacite", title=a.get("name"),
                              identifiers={"datacite_client": symbol, **({"re3data": a["re3data"]} if a.get("re3data") else {})},
                              links=[u for u in (a.get("url"),) if u],
                              extra={"description": (a.get("description") or "")[:1000], "client_type": a.get("clientType"),
                                     "subjects": [s.get("name") if isinstance(s, dict) else str(s) for s in a.get("subjects") or []],
                                     "active": a.get("isActive"), "language": a.get("language")},
                              raw=d)
            seen += 1
            if limit and seen >= limit:
                return
        total_pages = (j.get("meta") or {}).get("totalPages") or 0
        if not data or page >= total_pages:
            return
        page += 1


LOADERS = {"crossref": (crossref_journals, "Metadata: no rights asserted (facts)"),
           "doaj": (doaj_journals, "CC0"),
           "datacite": (datacite_repositories, "CC0")}


def run(conn, client: Client, name: str, *, limit: int | None = None) -> int:
    fn, license = LOADERS[name]
    return index.load(conn, fn(client, limit=limit), name, license=license)


def main(argv: list[str] | None = None) -> int:
    from ..app import Gateway, load_settings  # the app owns client construction (I-6)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("loader", choices=sorted(LOADERS))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    gw = Gateway(load_settings(), use_db=False)
    with db.connect() as conn:
        n = run(conn, gw.make_client(conn), args.loader, limit=args.limit)
        print(json.dumps({"loader": args.loader, "loaded": n, **index.counts(conn)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
