"""Registry loaders for the Tier 0 index (PLAN.md §8): Crossref journals, DOAJ journals,
DataCite repositories — each through the metered client under its own source's policy.

    python3 -m research_gateway.harvest.registries crossref [--limit N]
    python3 -m research_gateway.harvest.registries doaj
    python3 -m research_gateway.harvest.registries datacite
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
from typing import Iterator

from ..adapters.base import Client, check
from ..core import db
from ..core.canonical import make_record
from ..core.identity import normalize_issn, normalize_title
from . import index

CROSSREF_JOURNALS = "https://api.crossref.org/journals"
DOAJ_CSV = "https://doaj.org/csv"
DATACITE_REPOSITORIES = "https://api.datacite.org/repositories"


def venue_identity(issns: list[str | None], registry: str, title: str | None, publisher: str | None,
                   issn_map: index.IssnMap | None = None) -> tuple[str | None, list[str]]:
    """One identity per journal: the identity already holding any of its ISSNs (print, electronic or
    ISSN-L — registries disagree about which one comes first), else `issn:<first>`; a journal with no
    ISSN is keyed by registry, full normalised title and publisher, so two different journals whose
    names merely share a prefix stay apart. None when there is nothing to key on."""
    clean = [i for i in (normalize_issn(x) for x in issns if x) if i]
    if clean:
        preferred = f"issn:{clean[0]}"
        return (issn_map.identity_for(clean, preferred) if issn_map is not None else preferred), clean
    if not (title or "").strip():
        return None, []
    key = hashlib.sha1(f"{normalize_title(title)}|{normalize_title(publisher)}".encode()).hexdigest()[:16]
    return f"venue:{registry}:{key}", []


def _safe(fn, item, facts: list[str]):
    """Build one record or explain why it was skipped; a malformed registry row never stops a load."""
    try:
        return fn(item)
    except (TypeError, ValueError, KeyError, AttributeError) as e:
        facts.append(f"{type(e).__name__}: {e}"[:120])
        return None


# ---------------------------------------------------------------- Crossref journals
def crossref_journals(client: Client, *, limit: int | None = None, rows: int = 1000, issn_map: index.IssnMap | None = None,
                      skipped: list[str] | None = None) -> Iterator[dict]:
    cursor, seen, skipped = "*", 0, skipped if skipped is not None else []

    def build(j: dict) -> dict | None:
        issns = [x.get("value") for x in j.get("issn-type") or []] or j.get("ISSN") or []
        identity, clean = venue_identity(issns, "crossref", j.get("title"), j.get("publisher"), issn_map)
        if identity is None:
            return None
        counts = j.get("counts") or {}
        return make_record(identity=identity, kind="venue", source_id="crossref", title=j.get("title"), venue=j.get("publisher"),
                           identifiers={"issn": clean[0]} if clean else {}, links=[],
                           extra={"issns": clean, "subjects": [s.get("name") for s in j.get("subjects") or [] if s.get("name")],
                                  "works_count": counts.get("total-dois"), "current_dois": counts.get("current-dois")},
                           raw=j)

    while cursor:
        resp = client.get("crossref", "find", CROSSREF_JOURNALS,
                          params={"rows": rows, "cursor": cursor, "mailto": client.contact_email}, query="journals harvest")
        check("crossref", resp, allow_404=False)   # a failed page fails the load (D-23)
        j = resp.json
        msg = j.get("message") if isinstance(j, dict) else None
        if not isinstance(msg, dict) or not isinstance(msg.get("items"), list):
            raise ValueError(f"Crossref journals answered 200 but not with an items list "
                             f"(content-type {resp.headers.get('content-type')!r}) — load failed, not empty (D-24/D-25)")
        items = msg["items"]
        for j in items:
            rec = _safe(build, j, skipped) if isinstance(j, dict) else None
            if rec is None:
                continue
            yield rec
            seen += 1
            if limit and seen >= limit:
                return
        cursor = msg.get("next-cursor") if items and len(items) >= rows else None


# ---------------------------------------------------------------- DOAJ journals (CSV)
def doaj_journals(client: Client, *, limit: int | None = None, issn_map: index.IssnMap | None = None) -> Iterator[dict]:
    resp = client.get("doaj", "find", DOAJ_CSV, headers={"Accept": "text/csv"}, query="journals csv")
    check("doaj", resp, allow_404=False)   # a missing catalogue is a failed load, never a zero-row success (D-23)
    reader = csv.DictReader(io.StringIO(resp.text))
    if not reader.fieldnames or "Journal title" not in reader.fieldnames:
        raise ValueError(f"DOAJ CSV shape changed: columns {list(reader.fieldnames or [])[:5]!r} lack 'Journal title'")
    for n, row in enumerate(reader, 1):
        title = row.get("Journal title")
        identity, clean = venue_identity([row.get("Journal ISSN (print version)"), row.get("Journal EISSN (online version)")],
                                         "doaj", title, row.get("Publisher"), issn_map)
        if identity is None:
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
        check("datacite", resp, allow_404=False)   # a failed page fails the load (D-23)
        j = resp.json
        if not isinstance(j, dict) or not isinstance(j.get("data"), list):
            raise ValueError(f"DataCite repositories answered 200 but not with a data list "
                             f"(content-type {resp.headers.get('content-type')!r}) — load failed, not empty (D-24/D-25)")
        data = j["data"]

        def build(d: dict) -> dict | None:
            a = d.get("attributes") or {}
            symbol = str(a.get("symbol") or d.get("id") or "").lower()
            if not symbol:
                return None
            return make_record(identity=f"repository:datacite:{symbol}", kind="repository", source_id="datacite", title=a.get("name"),
                               identifiers={"datacite_client": symbol, **({"re3data": a["re3data"]} if a.get("re3data") else {})},
                               links=[u for u in (a.get("url"),) if u],
                               extra={"description": (a.get("description") or "")[:1000], "client_type": a.get("clientType"),
                                      "subjects": [s.get("name") if isinstance(s, dict) else str(s) for s in a.get("subjects") or []],
                                      "active": a.get("isActive"), "language": a.get("language")},
                               raw=d)

        for d in data:
            rec = _safe(build, d, []) if isinstance(d, dict) else None
            if rec is None:
                continue
            yield rec
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

    def stream():  # built only once the loader lock is held (D-23)
        kw = {"issn_map": index.IssnMap(conn)} if name in ("crossref", "doaj") else {}
        return fn(client, limit=limit, **kw)

    return index.load(conn, stream, name, license=license)


def main(argv: list[str] | None = None) -> int:
    from ..app import Gateway, load_settings  # the app owns client construction (I-6)
    from ..smoke import service_is_running
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("loader", choices=sorted(LOADERS))
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    if service_is_running() and os.environ.get("RESEARCH_GATEWAY_ALLOW_CONCURRENT") != "1":
        print("refusing: a gateway service is running and owns these sources' limits (I-1). "
              "Stop it, or set RESEARCH_GATEWAY_ALLOW_CONCURRENT=1 knowingly.", file=sys.stderr)
        return 2
    from ..app import open_breakers, todays_usage
    gw = Gateway(load_settings(), use_db=False)
    from ..core.broker import Broker, load_policies
    with db.connect() as conn:
        client = gw.make_client(conn, client_id="harvest")
        deployed = load_policies(conn)   # deployed policies over the seed's when a database exists (D-26)
        if deployed:
            client.broker = Broker(deployed)
        client.broker.seed_usage(todays_usage(conn))       # the loader shares the day's budgets (I-1, D-25)
        client.broker.seed_breakers(open_breakers(conn))
        n = run(conn, client, args.loader, limit=args.limit)
        print(json.dumps({"loader": args.loader, "loaded": n, **index.counts(conn)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
