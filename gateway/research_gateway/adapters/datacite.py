"""DataCite: base dataset lane; the registry for Zenodo, figshare, institutional repository DOIs."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check

SOURCE_ID = "datacite"
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi",)
BASE = "https://api.datacite.org"

_KIND = {"Dataset": "dataset", "Software": "software", "Text": "document", "JournalArticle": "article",
         "Preprint": "article", "Report": "document", "Book": "document", "Collection": "dataset"}


def _record(d: dict) -> dict:
    a = d.get("attributes") or {}
    doi = normalize_doi(a.get("doi") or d.get("id"))
    rtype = (a.get("types") or {}).get("resourceTypeGeneral")
    rights = a.get("rightsList") or []
    lic = next((r.get("rightsIdentifier") or r.get("rights") for r in rights if r.get("rightsIdentifier") or r.get("rights")), None)
    return make_record(
        identity=f"doi:{doi}" if doi else f"datacite:{d.get('id')}",
        kind=_KIND.get(rtype, "dataset"), source_id=SOURCE_ID,
        title=((a.get("titles") or [{}])[0]).get("title"),
        authors=[c.get("name") for c in a.get("creators", []) if c.get("name")],
        year=a.get("publicationYear"), venue=a.get("publisher"),
        identifiers={"doi": doi} if doi else {},
        links=[u for u in (a.get("url"),) if u], license=lic,
        extra={"resource_type": rtype, "client_id": (d.get("relationships") or {}).get("client", {}).get("data", {}).get("id")},
        raw={"id": d.get("id"), "attributes": {k: a.get(k) for k in ("doi", "titles", "creators", "publicationYear", "publisher",
                                                                         "types", "url", "rightsList", "subjects")}},
    )


def find(client: Client, query: str, *, limit: int = 20, page: int = 1, resource_type: str | None = None) -> dict:
    params = {"query": query, "page[size]": min(limit, 100), "page[number]": page}
    if resource_type:
        params["resource-type-id"] = resource_type
    resp = client.get(SOURCE_ID, "find", f"{BASE}/dois", params=params, query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": 0, "next_page": None}
    j = resp.json or {}
    data = j.get("data") or []
    total = (j.get("meta") or {}).get("total")
    nxt = page + 1 if data and total and page * min(limit, 100) < total else None
    return {"records": [_record(d) for d in data], "total": total, "next_page": nxt}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/dois/{doi}", identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    d = (resp.json or {}).get("data")
    return _record(d) if d else None
