"""DOAJ: open-access journal articles (always added to article discovery)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import Client, Obj, check, first_member, key, listed, members, need, nested, optional, plain, quote, text, total

SOURCE_ID = "doaj"
SMOKE = {'capability': 'find', 'query': 'management', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi", "issn")
BASE = "https://doaj.org/api"
MAX_RECORDS_PER_QUERY = 1000  # DOAJ refuses a page that starts at or past record 1,000 (docs/PROVIDER-PAGINATION.md)


def _record(a: dict) -> dict:
    b = nested(SOURCE_ID, a, "bibjson")
    doi = next((normalize_doi(i.get("id")) for i in listed(SOURCE_ID, b, "identifier") if (text(SOURCE_ID, i.get("type")) or "").lower() == "doi"), None)
    journal = nested(SOURCE_ID, b, "journal")
    issns = [normalize_issn(i) for i in listed(SOURCE_ID, journal, "issns") if normalize_issn(i)]
    ids = {"doi": doi} if doi else {}
    if issns:
        ids["issn"] = issns[0]
    links = [u for u in (text(SOURCE_ID, l.get("url")) for l in listed(SOURCE_ID, b, "link")) if u]
    licenses = listed(SOURCE_ID, journal, "license")
    return make_record(
        identity=f"doi:{doi}" if doi else f"doaj:{key(SOURCE_ID, a.get('id'))}",
        kind="article", source_id=SOURCE_ID, title=b.get("title"),
        authors=[n for n in (text(SOURCE_ID, x.get("name")) for x in listed(SOURCE_ID, b, "author")) if n],
        year=year_from(b.get("year")), venue=journal.get("title"), identifiers=ids, links=links,
        license=licenses[0].get("type") if licenses else None,
        extra={"open_access": True, "doaj_id": a.get("id")},
        raw=a,
    )


def find(client: Client, query: str, *, limit: int = 20, page: int = 1) -> dict:
    page_size = min(limit, 100)
    if (page - 1) * page_size >= MAX_RECORDS_PER_QUERY:
        return {"records": [], "total": None, "next_page": None,
                "capability_fact": f"DOAJ caps a query at {MAX_RECORDS_PER_QUERY} records"}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/search/articles/{quote(query)}",
                      params={"page": page, "pageSize": page_size, "sort": "created_date:desc"}, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = resp.json
    results = need(SOURCE_ID, j, "results")
    count = total(j.get("total"), (page - 1) * page_size + len(results))
    # DOAJ's own code: the last page is the one reaching `total` (page_count = ((total - 1) // page_size) + 1),
    # and the next page exists only while it starts below record 1,000 — the cap ends nothing
    reached = count is not None and page * page_size >= count
    nxt = page + 1 if count is not None and not reached and page * page_size < MAX_RECORDS_PER_QUERY else None
    return {"records": members(SOURCE_ID, results, _record), "total": count, "next_page": nxt, "exhausted": reached}


def _journal(issn: str, a: dict) -> dict:
    b = nested(SOURCE_ID, a, "bibjson")
    publisher, licenses = b.get("publisher"), listed(SOURCE_ID, b, "license")
    return make_record(identity=f"issn:{issn}", kind="venue", source_id=SOURCE_ID, title=b.get("title"),
                       venue=publisher.get("name") if isinstance(publisher, Obj) else publisher,
                       identifiers={"issn": issn},
                       links=[u for u in (v if isinstance(v, str) else text(SOURCE_ID, v.get("url")) for v in plain(optional(SOURCE_ID, b, "ref", dict)).values()) if u],
                       license=(licenses[0] if licenses else {}).get("type"),
                       extra={"in_doaj": True, "subjects": [t for t in (text(SOURCE_ID, s.get("term")) for s in listed(SOURCE_ID, b, "subject")) if t]},
                       raw=a)


def resolve(client: Client, identity: str) -> dict | None:
    """A DOI resolves to its article; an ISSN resolves to its journal (both declared in SCHEMES)."""
    value = identity.split(":", 1)[-1] if ":" in identity else identity
    issn = normalize_issn(value) if identity.lower().startswith("issn:") or normalize_issn(value) else None
    if issn and not normalize_doi(value):
        resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search/journals/" + quote(f'issn:"{issn}"'),
                          params={"pageSize": 1}, identity=f"issn:{issn}")
        if not check(SOURCE_ID, resp):
            return None
        return first_member(SOURCE_ID, need(SOURCE_ID, resp.json, "results"), lambda a: _journal(issn, a))
    doi = normalize_doi(value)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search/articles/" + quote(f'doi:"{doi}"'),
                      params={"pageSize": 1}, identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    return first_member(SOURCE_ID, need(SOURCE_ID, resp.json, "results"), _record)
