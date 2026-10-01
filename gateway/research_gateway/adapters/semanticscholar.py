"""Semantic Scholar: AI/ML and software domain lane; citations; open-access PDF pointers.

Results may not be persisted or redistributed (licence: CC BY-NC / ODC-BY mix);
the cache layer reads that from the registry. This adapter returns links to
full text, never the text.
"""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_arxiv, normalize_doi
from .base import NO_MEMBERS, OMIT, Client, PayloadError, check, counts_nothing, listed, members, need, nested, offset_after, plain, text, total

SOURCE_ID = "semanticscholar"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "enrich")
ENRICHES = ("citations", "references", "full_text")
SCHEMES = ("doi", "arxiv", "s2")
BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "externalIds,title,year,venue,authors,openAccessPdf,citationCount,referenceCount,publicationTypes"
SEARCH_CAP = 1000   # /paper/search: "the maximum sum of offset and limit" (docs/PROVIDER-PAGINATION.md)


def _headers(client: Client) -> dict:
    key = client.secret("semantic_scholar")
    return {"x-api-key": key} if key else {}


def _paper_id(identity: str) -> str | None:
    scheme, _, value = identity.partition(":") if ":" in identity else ("", "", identity)
    scheme = scheme.lower()
    doi = normalize_doi(value if scheme == "doi" else identity)
    if doi:
        return f"DOI:{doi}"
    arx = normalize_arxiv(value if scheme == "arxiv" else identity)
    if arx:
        return f"ARXIV:{arx}"
    if scheme == "s2":
        return value
    return None


def _record(p: dict) -> dict:
    ext, access = nested(SOURCE_ID, p, "externalIds"), nested(SOURCE_ID, p, "openAccessPdf")
    doi = normalize_doi(ext.get("DOI"))
    arx = normalize_arxiv(ext.get("ArXiv"))
    pmid, paper_id = text(SOURCE_ID, ext.get("PubMed")), text(SOURCE_ID, p.get("paperId"))
    ids = {k: v for k, v in (("doi", doi), ("arxiv", arx), ("pmid", pmid), ("s2", paper_id)) if v}
    pdf = text(SOURCE_ID, access.get("url"))
    identity = f"doi:{doi}" if doi else (f"arxiv:{arx}" if arx else f"s2:{paper_id}")
    return make_record(
        identity=identity, kind="article", source_id=SOURCE_ID, title=p.get("title"),
        authors=[n for n in (text(SOURCE_ID, a.get("name")) for a in listed(SOURCE_ID, p, "authors")) if n], year=p.get("year"),
        venue=text(SOURCE_ID, p.get("venue")) or None, identifiers=ids, links=[pdf] if pdf else [],
        license=access.get("license"),
        attribution="Semantic Scholar",
        extra={"cited_by_count": p.get("citationCount"), "reference_count": p.get("referenceCount"),
               "publication_types": plain(p.get("publicationTypes")), "redistributable": False},
        raw=p,
    )


def _linked(key: str, row: dict):
    """One citation or reference row: its linked paper as a citation record, or OMIT when that paper is unidentified."""
    paper = nested(SOURCE_ID, row, key)
    if not (text(SOURCE_ID, paper.get("paperId")) or text(SOURCE_ID, nested(SOURCE_ID, paper, "externalIds").get("DOI"))):
        return OMIT
    return {**_record(paper), "kind": "citation"}


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0, year_from_: int | None = None) -> dict:
    params = {"query": query, "limit": min(limit, 100), "offset": offset, "fields": FIELDS,
              "year": f"{year_from_}-" if year_from_ else None}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/paper/search", params=params, headers=_headers(client), query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = need(SOURCE_ID, resp.json, kind=dict)
    # the search answer omits `data` when nothing matched; then it must say total 0
    rows = need(SOURCE_ID, j, "data") if "data" in j or not counts_nothing(j.get("total")) else NO_MEMBERS
    # `next` is "Absent if no more data exists" — short of the 1,000-result cap, where the documentation
    # does not say what an absent `next` means; `total` is "approximate" and ends nothing
    end = j.get("next") is None and offset + len(rows) < SEARCH_CAP
    return {"records": members(SOURCE_ID, rows, _record), "total": total(j.get("total"), offset + len(rows)), "next_offset": offset_after(j.get("next"), offset), "exhausted": end}


def resolve(client: Client, identity: str) -> dict | None:
    pid = _paper_id(identity)
    if not pid:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/paper/{pid}", params={"fields": FIELDS},
                      headers=_headers(client), identity=identity)
    if not check(SOURCE_ID, resp):
        return None
    paper = need(SOURCE_ID, resp.json, kind=dict)
    if not paper.get("paperId"):
        raise PayloadError(f"{SOURCE_ID}: the paper answer carries no paperId")
    return _record(paper)


def enrich(client: Client, identity: str, what: str = "citations") -> dict:
    """citations | references (linked papers), or full_text (open-access PDF link only)."""
    pid = _paper_id(identity)
    if not pid:
        return {"identity": identity, "what": what, "items": []}
    if what == "full_text":
        rec = resolve(client, identity)
        items = []
        if rec and rec["links"]:
            items.append(make_record(identity=rec["identity"], kind="full_text", source_id=SOURCE_ID, title=rec["title"],
                                     links=rec["links"], license=rec["license"], attribution="Semantic Scholar",
                                     extra={"redistributable": False}, raw=rec["raw"].get("openAccessPdf")))
        return {"identity": identity, "what": what, "items": items}
    if what not in ("citations", "references"):
        return {"identity": identity, "what": what, "items": []}
    key = "citingPaper" if what == "citations" else "citedPaper"
    resp = client.get(SOURCE_ID, "enrich", f"{BASE}/paper/{pid}/{what}",
                      params={"fields": "externalIds,title,year,venue", "limit": 100}, headers=_headers(client), identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "what": what, "items": []}
    return {"identity": identity, "what": what, "items": members(SOURCE_ID, need(SOURCE_ID, resp.json, "data"), lambda row: _linked(key, row))}
