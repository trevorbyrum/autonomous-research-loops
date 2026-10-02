"""Semantic Scholar: AI/ML and software domain lane; citations; open-access PDF pointers.

Results may not be persisted or redistributed (licence: CC BY-NC / ODC-BY mix);
the cache layer reads that from the registry. This adapter returns links to
full text, never the text.
"""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record
from ..core.identity import normalize_arxiv, normalize_doi
from .base import OMIT, Client, PayloadError, check, decode, members, offset_after, total

SOURCE_ID = "semanticscholar"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "enrich")
ENRICHES = ("citations", "references", "full_text")
SCHEMES = ("doi", "arxiv", "s2")
BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "externalIds,title,year,venue,authors,openAccessPdf,citationCount,referenceCount,publicationTypes"
SEARCH_CAP = 1000   # /paper/search: "the maximum sum of offset and limit" (docs/PROVIDER-PAGINATION.md)

# What an answer must be. A paper is named by its DOI, else its arXiv id, else its own id: all declared, so all decoded before one is chosen.
PAPER = S.obj({"paperId": S.text(), "externalIds": S.obj({"DOI": S.text(), "ArXiv": S.text(), "PubMed": S.text()}),
               "openAccessPdf": S.obj({"url": S.text(), "license": S.text()}), "title": S.text(), "year": S.year(), "venue": S.text(),
               "authors": S.own(S.obj({"name": S.text()})), "citationCount": S.any_(), "referenceCount": S.any_(), "publicationTypes": S.any_()},
              alts=(("externalIds.DOI", "externalIds.ArXiv", "paperId"),))
# `data` may be left out only when the answer counts nothing (`total` is 0); `next` is read by whether it is there ("Absent if no more data exists"), so
# one that is there and cannot be read is neither a continuation nor an end.
FIND = S.obj({"data": S.members(PAPER, empty_when=("total",)), "total": S.soft(S.whole()), "next": S.isolated(S.whole())})
RESOLVE = PAPER
CITATIONS, REFERENCES = (S.obj({"data": S.required(S.members(S.obj({key: PAPER})))}) for key in ("citingPaper", "citedPaper"))
SCHEMAS = {"find": FIND, "resolve": RESOLVE, "enrich:citations": CITATIONS, "enrich:references": REFERENCES}


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


def _record(p) -> dict:
    ext, access = p["externalIds"], p["openAccessPdf"]
    doi = normalize_doi(ext["DOI"])
    arx = normalize_arxiv(ext["ArXiv"])
    pmid, paper_id = ext["PubMed"], p["paperId"]
    ids = {k: v for k, v in (("doi", doi), ("arxiv", arx), ("pmid", pmid), ("s2", paper_id)) if v}
    pdf = access["url"]
    identity = f"doi:{doi}" if doi else (f"arxiv:{arx}" if arx else f"s2:{paper_id}")
    return make_record(
        identity=identity, kind="article", source_id=SOURCE_ID, title=p["title"],
        authors=[n for n in (a["name"] for a in p["authors"]) if n], year=p["year"],
        venue=p["venue"] or None, identifiers=ids, links=[pdf] if pdf else [],
        license=access["license"],
        attribution="Semantic Scholar",
        extra={"cited_by_count": p["citationCount"], "reference_count": p["referenceCount"],
               "publication_types": p["publicationTypes"], "redistributable": False},
        raw=p.raw,
    )


def _linked(key: str, row):
    """One citation or reference row: its linked paper as a citation record, or OMIT when that paper is unidentified."""
    paper = row[key]
    if not (paper["paperId"] or paper["externalIds"]["DOI"]):
        return OMIT
    return {**_record(paper), "kind": "citation"}


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0, year_from_: int | None = None) -> dict:
    params = {"query": query, "limit": min(limit, 100), "offset": offset, "fields": FIELDS,
              "year": f"{year_from_}-" if year_from_ else None}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/paper/search", params=params, headers=_headers(client), query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = decode(SOURCE_ID, FIND, resp.json)
    rows = j["data"]   # the search answer omits `data` when nothing matched; then it must say total 0
    # `next` is "Absent if no more data exists" — short of the 1,000-result cap, where the documentation
    # does not say what an absent `next` means; `total` is "approximate" and ends nothing
    end = j["next"] is None and offset + len(rows) < SEARCH_CAP
    return {"records": members(SOURCE_ID, rows, _record), "total": total(j["total"], offset + len(rows)), "next_offset": offset_after(j["next"], offset), "exhausted": end}


def _paper(client: Client, identity: str, pid: str):
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/paper/{pid}", params={"fields": FIELDS},
                      headers=_headers(client), identity=identity)
    if not check(SOURCE_ID, resp):
        return None
    paper = decode(SOURCE_ID, RESOLVE, resp.json)
    if not paper["paperId"]:
        raise PayloadError(f"{SOURCE_ID}: the paper answer carries no paperId")
    return paper


def resolve(client: Client, identity: str) -> dict | None:
    pid = _paper_id(identity)
    if not pid:
        return None
    paper = _paper(client, identity, pid)
    return _record(paper) if paper is not None else None


def enrich(client: Client, identity: str, what: str = "citations") -> dict:
    """citations | references (linked papers), or full_text (open-access PDF link only)."""
    pid = _paper_id(identity)
    if not pid:
        return {"identity": identity, "what": what, "items": []}
    if what == "full_text":
        paper = _paper(client, identity, pid)
        rec = _record(paper) if paper is not None else None
        items = []
        if rec and rec["links"]:
            items.append(make_record(identity=rec["identity"], kind="full_text", source_id=SOURCE_ID, title=rec["title"],
                                     links=rec["links"], license=rec["license"], attribution="Semantic Scholar",
                                     extra={"redistributable": False}, raw=paper["openAccessPdf"].raw))
        return {"identity": identity, "what": what, "items": items}
    if what not in ("citations", "references"):
        return {"identity": identity, "what": what, "items": []}
    key = "citingPaper" if what == "citations" else "citedPaper"
    resp = client.get(SOURCE_ID, "enrich", f"{BASE}/paper/{pid}/{what}",
                      params={"fields": "externalIds,title,year,venue", "limit": 100}, headers=_headers(client), identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "what": what, "items": []}
    return {"identity": identity, "what": what, "items": members(SOURCE_ID, decode(SOURCE_ID, SCHEMAS[f"enrich:{what}"], resp.json)["data"], lambda row: _linked(key, row))}
