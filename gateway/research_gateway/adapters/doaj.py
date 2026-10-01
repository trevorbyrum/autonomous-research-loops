"""DOAJ: open-access journal articles (always added to article discovery)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import Client, check, first_member, members, need, quote

SOURCE_ID = "doaj"
SMOKE = {'capability': 'find', 'query': 'management', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi", "issn")
BASE = "https://doaj.org/api"
MAX_RECORDS_PER_QUERY = 1000  # DOAJ refuses a page that starts at or past record 1,000 (docs/PROVIDER-PAGINATION.md)


def _record(a: dict) -> dict:
    b = a.get("bibjson") or {}
    doi = next((normalize_doi(i.get("id")) for i in b.get("identifier", []) if (i.get("type") or "").lower() == "doi"), None)
    journal = b.get("journal") or {}
    issns = [normalize_issn(i) for i in journal.get("issns", []) if normalize_issn(i)]
    ids = {"doi": doi} if doi else {}
    if issns:
        ids["issn"] = issns[0]
    links = [l.get("url") for l in b.get("link", []) if l.get("url")]
    return make_record(
        identity=f"doi:{doi}" if doi else f"doaj:{a.get('id')}",
        kind="article", source_id=SOURCE_ID, title=b.get("title"),
        authors=[x.get("name") for x in b.get("author", []) if x.get("name")],
        year=year_from(b.get("year")), venue=journal.get("title"), identifiers=ids, links=links,
        license=(journal.get("license") or [{}])[0].get("type") if journal.get("license") else None,
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
    total = j.get("total")
    # DOAJ's own code: the last page is the one reaching `total` (page_count = ((total - 1) // page_size) + 1),
    # and the next page exists only while it starts below record 1,000 — the cap ends nothing
    reached = type(total) is int and page * page_size >= total
    nxt = page + 1 if type(total) is int and not reached and page * page_size < MAX_RECORDS_PER_QUERY else None
    return {"records": members(SOURCE_ID, results, _record), "total": total, "next_page": nxt, "exhausted": reached}


def _journal(issn: str, a: dict) -> dict:
    b = a.get("bibjson") or {}
    return make_record(identity=f"issn:{issn}", kind="venue", source_id=SOURCE_ID, title=b.get("title"),
                       venue=b.get("publisher", {}).get("name") if isinstance(b.get("publisher"), dict) else b.get("publisher"),
                       identifiers={"issn": issn}, links=[r.get("url") for r in b.get("ref", {}).values()] if isinstance(b.get("ref"), dict) else [],
                       license=((b.get("license") or [{}])[0]).get("type"),
                       extra={"in_doaj": True, "subjects": [s.get("term") for s in b.get("subject") or [] if s.get("term")]},
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
