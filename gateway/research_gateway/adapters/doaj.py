"""DOAJ: open-access journal articles (always added to article discovery)."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import Client, check, quote

SOURCE_ID = "doaj"
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
        raw={"id": a.get("id"), "bibjson": {k: b.get(k) for k in ("title", "year", "journal", "identifier", "author", "link", "subject")}},
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
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search/articles/" + quote(f'doi:"{doi}"'),
                      params={"pageSize": 1}, identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    results = (resp.json or {}).get("results") or []
    return _record(results[0]) if results else None
