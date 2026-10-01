"""DataCite: base dataset lane; the registry for Zenodo, figshare, institutional repository DOIs."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check, members, need, plain, scalar

SOURCE_ID = "datacite"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.7910/DVN/OY6CBK'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi",)
AGENCIES = ("DataCite",)
BASE = "https://api.datacite.org"
MAX_PAGED_RECORDS = 10_000   # page-number paging: "Only the first 10,000 records ... can be retrieved"

_KIND = {"Dataset": "dataset", "Software": "software", "Text": "document", "JournalArticle": "article",
         "Preprint": "article", "Report": "document", "Book": "document", "Collection": "dataset"}


def _record(d: dict) -> dict:
    a = d.get("attributes") or {}
    doi = normalize_doi(a.get("doi") or d.get("id"))
    rtype = (a.get("types") or {}).get("resourceTypeGeneral")
    rights = plain(a.get("rightsList")) or []
    lic = next((r.get("rightsIdentifier") or r.get("rights") for r in rights if r.get("rightsIdentifier") or r.get("rights")), None)
    return make_record(
        identity=f"doi:{doi}" if doi else f"datacite:{d.get('id')}",
        kind=_KIND.get(rtype, "dataset"), source_id=SOURCE_ID,
        title=((plain(a.get("titles")) or [{}])[0]).get("title"),
        authors=[c.get("name") for c in plain(a.get("creators", [])) if c.get("name")],
        year=a.get("publicationYear"), venue=a.get("publisher"),
        identifiers={"doi": doi} if doi else {},
        links=[u for u in (a.get("url"),) if u], license=lic,
        extra={"resource_type": rtype, "client_id": (d.get("relationships") or {}).get("client", {}).get("data", {}).get("id")},
        raw=d,
    )


def find(client: Client, query: str, *, limit: int = 20, page: int = 1, resource_type: str | None = None) -> dict:
    size = min(limit, 100)
    params = {"query": query, "page[size]": size, "page[number]": page}
    if resource_type:
        params["resource-type-id"] = resource_type
    resp = client.get(SOURCE_ID, "find", f"{BASE}/dois", params=params, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = resp.json
    data = need(SOURCE_ID, j, "data")
    total = scalar((j.get("meta") or {}).get("total"))
    # meta.total is the "Total results count": the page reaching it is the last. Page-number paging reaches only
    # the first 10,000 records; past them nothing continues and nothing ends (docs/PROVIDER-PAGINATION.md)
    reached = type(total) is int and page * size >= total
    nxt = page + 1 if type(total) is int and not reached and (page + 1) * size <= MAX_PAGED_RECORDS else None
    return {"records": members(SOURCE_ID, data, _record), "total": total, "next_page": nxt, "exhausted": reached}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/dois/{doi}", identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    return _record(need(SOURCE_ID, resp.json, "data", kind=dict))
