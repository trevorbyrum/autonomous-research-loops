"""DOAJ: open-access journal articles (always added to article discovery)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import Client, check, quote

SOURCE_ID = "doaj"
SMOKE = {'capability': 'find', 'query': 'management', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi", "issn")
BASE = "https://doaj.org/api"
MAX_RECORDS_PER_QUERY = 1000  # DOAJ refuses results beyond record 1,000


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
    if page * page_size > MAX_RECORDS_PER_QUERY:
        return {"records": [], "total": None, "next_page": None,
                "capability_fact": f"DOAJ caps a query at {MAX_RECORDS_PER_QUERY} records"}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/search/articles/{quote(query)}",
                      params={"page": page, "pageSize": page_size, "sort": "created_date:desc"}, query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": 0, "next_page": None}
    j = resp.json or {}
    results = j.get("results") or []
    nxt = page + 1 if results and (page + 1) * page_size <= MAX_RECORDS_PER_QUERY and page * page_size < (j.get("total") or 0) else None
    return {"records": [_record(a) for a in results], "total": j.get("total"), "next_page": nxt}


def resolve(client: Client, identity: str) -> dict | None:
    """A DOI resolves to its article; an ISSN resolves to its journal (both declared in SCHEMES)."""
    value = identity.split(":", 1)[-1] if ":" in identity else identity
    issn = normalize_issn(value) if identity.lower().startswith("issn:") or normalize_issn(value) else None
    if issn and not normalize_doi(value):
        resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search/journals/" + quote(f'issn:"{issn}"'),
                          params={"pageSize": 1}, identity=f"issn:{issn}")
        if not check(SOURCE_ID, resp):
            return None
        results = (resp.json or {}).get("results") or []
        if not results:
            return None
        b = results[0].get("bibjson") or {}
        return make_record(identity=f"issn:{issn}", kind="venue", source_id=SOURCE_ID, title=b.get("title"),
                           venue=b.get("publisher", {}).get("name") if isinstance(b.get("publisher"), dict) else b.get("publisher"),
                           identifiers={"issn": issn}, links=[r.get("url") for r in b.get("ref", {}).values()] if isinstance(b.get("ref"), dict) else [],
                           license=((b.get("license") or [{}])[0]).get("type"),
                           extra={"in_doaj": True, "subjects": [s.get("term") for s in b.get("subject") or [] if s.get("term")]},
                           raw=results[0])
    doi = normalize_doi(value)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search/articles/" + quote(f'doi:"{doi}"'),
                      params={"pageSize": 1}, identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    results = (resp.json or {}).get("results") or []
    return _record(results[0]) if results else None
