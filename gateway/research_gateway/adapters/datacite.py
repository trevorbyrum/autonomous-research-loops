"""DataCite: base dataset lane; the registry for Zenodo, figshare, institutional repository DOIs."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check, decode, identity_from, members, total

SOURCE_ID = "datacite"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.7910/DVN/OY6CBK'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi",)
AGENCIES = ("DataCite",)
BASE = "https://api.datacite.org"
MAX_PAGED_RECORDS = 10_000   # page-number paging: "Only the first 10,000 records ... can be retrieved"

_KIND = {"Dataset": "dataset", "Software": "software", "Text": "document", "JournalArticle": "article",
         "Preprint": "article", "Report": "document", "Book": "document", "Collection": "dataset"}

# What an answer must be. A right is stated by its `rightsIdentifier`, else its `rights`; a DOI by the record's `attributes.doi`, else the registry's own `id`
# (its DOI): in both, every alternative is declared, so every alternative is decoded before the record picks one.
RIGHT = S.obj({"rightsIdentifier": S.text(), "rights": S.text()}, alts=(("rightsIdentifier", "rights"),))
DOI_RECORD = S.obj({"id": S.text(),
                    "attributes": S.obj({"doi": S.text(), "types": S.obj({"resourceTypeGeneral": S.text()}), "rightsList": S.own(RIGHT),
                                         "titles": S.own(S.obj({"title": S.text()})), "url": S.text(), "publisher": S.text(),
                                         "creators": S.own(S.obj({"name": S.text()})), "publicationYear": S.year()}),
                    "relationships": S.obj({"client": S.obj({"data": S.obj({"id": S.any_()})})})},
                   alts=(("attributes.doi", "id"),))
FIND = S.obj({"data": S.required(S.members(DOI_RECORD)), "meta.total": S.deep(("meta", "total"), S.whole())})
RESOLVE = S.obj({"data": S.required(DOI_RECORD)})
SCHEMAS = {"find": FIND, "resolve": RESOLVE}


def _record(d) -> dict:
    a = d["attributes"]
    stated, own = normalize_doi(a["doi"]), normalize_doi(d["id"])   # the registry's own id is its DOI: both are read as identifiers before either is chosen
    doi = own if a["doi"] in (None, "") else stated   # an empty one is none
    rtype = a["types"]["resourceTypeGeneral"]
    rights = [r["rightsIdentifier"] or r["rights"] for r in a["rightsList"]]
    titles, url, publisher = a["titles"], a["url"], a["publisher"]
    own_id = d["id"] if d["id"] and d["id"].strip() else None
    return make_record(
        identity=identity_from(SOURCE_ID, ("doi", doi), ("datacite", own_id)),
        kind=_KIND.get(rtype, "dataset"), source_id=SOURCE_ID,
        title=titles[0]["title"] if titles else None,
        authors=[n for n in (c["name"] for c in a["creators"]) if n],
        year=a["publicationYear"], venue=publisher,
        identifiers={"doi": doi} if doi else {},
        links=[url] if url else [], license=next((r for r in rights if r), None),
        extra={"publisher": publisher, "resource_type": rtype, "client_id": d["relationships"]["client"]["data"]["id"]},
        raw=d.raw,
    )


def find(client: Client, query: str, *, limit: int = 20, page: int = 1, resource_type: str | None = None) -> dict:
    size = min(limit, 100)
    params = {"query": query, "page[size]": size, "page[number]": page}
    if resource_type:
        params["resource-type-id"] = resource_type
    resp = client.get(SOURCE_ID, "find", f"{BASE}/dois", params=params, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = decode(SOURCE_ID, FIND, resp.json)
    data = j["data"]
    count = total(j["meta.total"], (page - 1) * size + len(data))
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
    return _record(decode(SOURCE_ID, RESOLVE, resp.json)["data"])
