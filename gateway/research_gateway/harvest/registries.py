"""Registry loaders for the Tier 0 index (PLAN.md §8): Crossref journals, DOAJ journals,
DataCite repositories — each through the metered client under its own source's policy.

    python3 -m research_gateway.harvest.registries crossref [--limit N]
    python3 -m research_gateway.harvest.registries doaj
    python3 -m research_gateway.harvest.registries datacite
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Iterator

from ..adapters.base import Client, MemberList, PayloadError, Rec, check, decode, members, total
from ..core import db
from ..core import schema as S
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
    clean = [i for i in (normalize_issn(x) for x in issns if x is not None) if i]
    if clean:
        preferred = f"issn:{clean[0]}"
        return (issn_map.identity_for(clean, preferred) if issn_map is not None else preferred), clean
    if not (title or "").strip():
        return None, []
    key = hashlib.sha1(f"{normalize_title(title)}|{normalize_title(publisher)}".encode()).hexdigest()[:16]
    return f"venue:{registry}:{key}", []


# ---------------------------------------------------------------- Crossref journals
# What a page must be. A journal's ISSNs are its typed list (`issn-type`), else its plain one (`ISSN`): both are declared, so both are decoded,
# nested members included, before one is chosen (R11-1) — a malformed plain list is a malformed journal even beside a typed one that reads.
JOURNAL = S.obj({"title": S.text(), "publisher": S.text(), "issn-type": S.own(S.obj({"value": S.text()})), "ISSN": S.own(S.text()),
                 "subjects": S.own(S.obj({"name": S.text()})), "counts": S.obj({"total-dois": S.any_(), "current-dois": S.any_()})},
                alts=(("issn-type", "ISSN"),))
JOURNALS_PAGE = S.obj({"message": S.required(S.obj({"items": S.required(S.members(JOURNAL)), "next-cursor": S.soft(S.token())}))})


def crossref_journals(client: Client, *, limit: int | None = None, rows: int = 1000, issn_map: index.IssnMap | None = None,
                      skipped: list[str] | None = None) -> Iterator[dict]:
    cursor, seen, skipped = "*", 0, skipped if skipped is not None else []

    def build(j) -> dict | None:
        typed = [x["value"] for x in j["issn-type"]]
        issns = typed or j["ISSN"]
        title, publisher = j["title"], j["publisher"]
        identity, clean = venue_identity(issns, "crossref", title, publisher, issn_map)
        if identity is None:
            return None
        counts = j["counts"]
        return make_record(identity=identity, kind="venue", source_id="crossref", title=title, venue=publisher,
                           identifiers={"issn": clean[0]} if clean else {}, links=[],
                           extra={"issns": clean, "subjects": [n for n in (s["name"] for s in j["subjects"]) if n],
                                  "works_count": counts["total-dois"], "current_dois": counts["current-dois"]},
                           raw=j.raw)

    while cursor is not None:
        resp = client.get("crossref", "find", CROSSREF_JOURNALS,
                          params={"rows": rows, "cursor": cursor, "mailto": client.contact_email}, query="journals harvest")
        check("crossref", resp, allow_404=False)   # a failed page fails the load (D-23)
        try:
            msg = decode("crossref", JOURNALS_PAGE, resp)["message"]
        except PayloadError as e:
            raise PayloadError(f"Crossref journals answered 200 but not with an items list (content-type {resp.headers.get('content-type')!r}) — "
                               f"load failed, not empty (D-24/D-25): {e}") from None
        items = msg["items"]
        for rec in _built("crossref", items, build, skipped):   # each member alone; None is one that was skipped
            if rec is None:
                continue
            yield rec
            seen += 1
            if limit and seen >= limit:
                return
        if len(items) < rows:   # Crossref: "fewer than the number of expected rows" is the end of the result set
            cursor = None
        else:
            cursor = msg["next-cursor"]
            if cursor is None:   # a full page whose continuation cannot be read is not the end of the registry (the lane's own rule)
                raise ValueError("Crossref journals answered a full page without a next-cursor that can be read — load failed, not complete (D-23)")


def _built(source_id: str, items: MemberList, build, skipped: list[str]) -> list:
    """Each decoded member through `build`; a malformed registry row never stops a load. A row that was an object and could not be decoded, or whose
    record cannot be built, is reported in `skipped`; one that was not an object is skipped without a word (it is not a row of the registry at all)."""
    def reported(member):
        try:
            return build(member)
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            skipped.append(f"{type(e).__name__}: {e}"[:120])
            return None
    for member in items.unreadable():
        if member.was_object:
            skipped.append(f"PayloadError: {member.reason}"[:120])
    return members(source_id, items, reported)


# ---------------------------------------------------------------- DOAJ journals (CSV)
# What a row of DOAJ's CSV dump must be: the columns the index takes, each text (a cell the row is too short to hold is nothing). The dump is parsed by the csv module; each
# row is decoded against this before the loader reads it.
DOAJ_ROW = S.obj({"Journal title": S.text(), "Journal ISSN (print version)": S.text(), "Journal EISSN (online version)": S.text(), "Publisher": S.text(),
                  "Subjects": S.text(), "Journal URL": S.text(), "Journal license": S.text(), "Country of publisher": S.text(), "APC": S.text(),
                  "Languages in which the journal accepts manuscripts": S.text()})


DOAJ_COLUMNS = ("Journal title",)   # the file must have this column: one that does not is not the dump the loader supports


def doaj_journals(client: Client, *, limit: int | None = None, issn_map: index.IssnMap | None = None) -> Iterator[dict]:
    resp = client.get("doaj", "find", DOAJ_CSV, headers={"Accept": "text/csv"}, query="journals csv")
    check("doaj", resp, allow_404=False)   # a missing catalogue is a failed load, never a zero-row success (D-23)
    rows = S.decode_csv("doaj", DOAJ_ROW, resp, columns=DOAJ_COLUMNS)   # the dump is opened and parsed by the decoder; each row is decoded against the row schema, alone

    def build(row) -> dict | None:
        title = row["Journal title"]
        identity, clean = venue_identity([row["Journal ISSN (print version)"], row["Journal EISSN (online version)"]],
                                         "doaj", title, row["Publisher"], issn_map)
        if identity is None:
            return None
        subjects = [s.strip() for s in (row["Subjects"] or "").split("|") if s.strip()]
        return make_record(identity=identity, kind="venue", source_id="doaj", title=title, venue=row["Publisher"],
                           identifiers={"issn": clean[0]} if clean else {}, links=[u for u in (row["Journal URL"],) if u],
                           license=row["Journal license"],
                           extra={"issns": clean, "subjects": subjects, "country": row["Country of publisher"],
                                  "in_doaj": True, "apc": row["APC"], "language": row["Languages in which the journal accepts manuscripts"]},
                           raw=row.raw)
    for n, rec in enumerate(_built("doaj", rows, build, []), 1):   # a row that could not be read, or names no journal, is skipped (position kept: `limit` counts rows)
        if rec is None:
            continue
        yield rec
        if limit and n >= limit:
            return


# ---------------------------------------------------------------- DataCite repositories
REPOSITORY = S.obj({"id": S.text(), "attributes": S.obj({"symbol": S.text(), "re3data": S.text(), "url": S.text(), "name": S.text(), "description": S.text(),
                                                         "clientType": S.any_(), "isActive": S.any_(), "language": S.any_(),
                                                         "subjects": S.own(S.oneof(S.obj({"name": S.any_()}), S.text()))})},
                   alts=(("attributes.symbol", "id"),))
REPOSITORIES_PAGE = S.obj({"data": S.required(S.members(REPOSITORY)), "meta.totalPages": S.deep(("meta", "totalPages"), S.whole())})


def datacite_repositories(client: Client, *, limit: int | None = None, size: int = 1000) -> Iterator[dict]:
    page, seen = 1, 0
    while True:
        resp = client.get("datacite", "find", DATACITE_REPOSITORIES, params={"page[size]": size, "page[number]": page},
                          query="repositories harvest")
        check("datacite", resp, allow_404=False)   # a failed page fails the load (D-23)
        try:
            j = decode("datacite", REPOSITORIES_PAGE, resp)
        except PayloadError as e:
            raise PayloadError(f"DataCite repositories answered 200 but not with a data list (content-type {resp.headers.get('content-type')!r}) — "
                               f"load failed, not empty (D-24/D-25): {e}") from None
        data = j["data"]

        def build(d) -> dict | None:
            a = d["attributes"]
            symbol = (a["symbol"] or d["id"] or "").lower()
            if not symbol:
                return None
            re3data, url = a["re3data"], a["url"]
            return make_record(identity=f"repository:datacite:{symbol}", kind="repository", source_id="datacite", title=a["name"],
                               identifiers={"datacite_client": symbol, **({"re3data": re3data} if re3data else {})},
                               links=[url] if url else [],
                               extra={"description": (a["description"] or "")[:1000], "client_type": a["clientType"],
                                      "subjects": [s["name"] if isinstance(s, Rec) else s for s in a["subjects"]],
                                      "active": a["isActive"], "language": a["language"]},
                               raw=d.raw)

        for rec in _built("datacite", data, build, []):
            if rec is None:
                continue
            yield rec
            seen += 1
            if limit and seen >= limit:
                return
        pages = total(j["meta.totalPages"], page)   # the last page reaches the number of pages, and no page is past it
        if pages is None:
            raise ValueError("DataCite repositories answered a page whose meta.totalPages cannot be read — load failed, not complete (D-23)")
        if not data or page >= pages:
            return
        page += 1


SCHEMAS = {"crossref journals": JOURNALS_PAGE, "doaj journals (csv)": DOAJ_ROW, "datacite repositories": REPOSITORIES_PAGE}

# each loader and the METADATA licence of the registry it reads (never a record's content licence, A3)
LOADERS = {"crossref": (crossref_journals, "Metadata: no rights asserted (facts)"),
           "doaj": (doaj_journals, "CC0"),
           "datacite": (datacite_repositories, "CC0")}


def run(conn, client: Client, name: str, *, limit: int | None = None) -> int:
    fn, metadata_license = LOADERS[name]

    def stream():  # built only once the loader lock is held (D-23)
        kw = {"issn_map": index.IssnMap(conn)} if name in ("crossref", "doaj") else {}
        return fn(client, limit=limit, **kw)

    return index.load(conn, stream, name, metadata_license=metadata_license)


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
        # deployed policies are authoritative whenever a database exists — even an EMPTY set (D-27)
        client.broker = Broker(load_policies(conn))
        client.broker.seed_usage(todays_usage(conn))       # the loader shares the day's budgets (I-1, D-25)
        client.broker.seed_breakers(open_breakers(conn))
        n = run(conn, client, args.loader, limit=args.limit)
        with conn.cursor() as cur:  # proof of a COMPLETED refresh, written only on success (8f)
            cur.execute("INSERT INTO gateway.meta (key, value, updated_at) VALUES (%s, %s, now()) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                        (f"harvest:{args.loader}", json.dumps({"loaded": n, "limit": args.limit})))
        conn.commit()
        print(json.dumps({"loader": args.loader, "loaded": n, **index.counts(conn)}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
