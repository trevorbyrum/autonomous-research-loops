"""DataCite: base dataset lane; the registry for Zenodo, figshare, institutional repository DOIs."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check, field, key, listed, members, need, nested, text, total

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
    a = nested(SOURCE_ID, d, "attributes")
    stated = a.get("doi")
    doi = normalize_doi(d.get("id") if stated is None or stated == "" else stated)   # the registry's own id is its DOI; an empty one is none
    rtype = text(SOURCE_ID, nested(SOURCE_ID, a, "types").get("resourceTypeGeneral"))
    rights = [text(SOURCE_ID, r.get("rightsIdentifier")) or text(SOURCE_ID, r.get("rights")) for r in listed(SOURCE_ID, a, "rightsList")]
    titles, url = listed(SOURCE_ID, a, "titles"), text(SOURCE_ID, a.get("url"))
    return make_record(
        identity=f"doi:{doi}" if doi else f"datacite:{key(SOURCE_ID, d.get('id'))}",
        kind=_KIND.get(rtype, "dataset"), source_id=SOURCE_ID,
        title=(titles[0] if titles else {}).get("title"),
        authors=[n for n in (text(SOURCE_ID, c.get("name")) for c in listed(SOURCE_ID, a, "creators")) if n],
        year=a.get("publicationYear"), venue=a.get("publisher"),
        identifiers={"doi": doi} if doi else {},
        links=[url] if url else [], license=next((r for r in rights if r), None),
        extra={"resource_type": rtype, "client_id": nested(SOURCE_ID, d, "relationships", "client", "data").get("id")},
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
    count = total(field(j, "meta", "total"), (page - 1) * size + len(data))
    # meta.total is the "Total results count": the page reaching it is the last. Page-number paging reaches only
    # the first 10,000 records; past them nothing continues and nothing ends (docs/PROVIDER-PAGINATION.md)
    reached = count is not None and page * size >= count
    nxt = page + 1 if count is not None and not reached and (page + 1) * size <= MAX_PAGED_RECORDS else None
    return {"records": members(SOURCE_ID, data, _record), "total": count, "next_page": nxt, "exhausted": reached}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/dois/{doi}", identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    return _record(need(SOURCE_ID, resp.json, "data", kind=dict))
