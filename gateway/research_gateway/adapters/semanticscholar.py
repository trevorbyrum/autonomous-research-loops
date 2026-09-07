"""Semantic Scholar: AI/ML and software domain lane; citations; open-access PDF pointers.

Results may not be persisted or redistributed (licence: CC BY-NC / ODC-BY mix);
the cache layer reads that from the registry. This adapter returns links to
full text, never the text.
"""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_arxiv, normalize_doi
from .base import Client, check

SOURCE_ID = "semanticscholar"
CAPABILITIES = ("find", "resolve", "enrich")
BASE = "https://api.semanticscholar.org/graph/v1"
FIELDS = "externalIds,title,year,venue,authors,openAccessPdf,citationCount,referenceCount,publicationTypes"


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
    ext = p.get("externalIds") or {}
    doi = normalize_doi(ext.get("DOI"))
    arx = normalize_arxiv(ext.get("ArXiv"))
    ids = {k: v for k, v in (("doi", doi), ("arxiv", arx), ("pmid", ext.get("PubMed")), ("s2", p.get("paperId"))) if v}
    pdf = (p.get("openAccessPdf") or {}).get("url")
    identity = f"doi:{doi}" if doi else (f"arxiv:{arx}" if arx else f"s2:{p.get('paperId')}")
    return make_record(
        identity=identity, kind="article", source_id=SOURCE_ID, title=p.get("title"),
        authors=[a.get("name") for a in (p.get("authors") or []) if a.get("name")], year=p.get("year"),
        venue=p.get("venue") or None, identifiers=ids, links=[u for u in (pdf,) if u],
        license=(p.get("openAccessPdf") or {}).get("license"),
        attribution="Semantic Scholar",
        extra={"cited_by_count": p.get("citationCount"), "reference_count": p.get("referenceCount"),
               "publication_types": p.get("publicationTypes"), "redistributable": False},
        raw={k: p.get(k) for k in ("paperId", "externalIds", "title", "year", "venue", "openAccessPdf", "citationCount")},
    )


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0, year_from_: int | None = None) -> dict:
    params = {"query": query, "limit": min(limit, 100), "offset": offset, "fields": FIELDS,
              "year": f"{year_from_}-" if year_from_ else None}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/paper/search", params=params, headers=_headers(client), query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": 0, "next_offset": None}
    j = resp.json or {}
    return {"records": [_record(p) for p in j.get("data") or []], "total": j.get("total"), "next_offset": j.get("next")}


def resolve(client: Client, identity: str) -> dict | None:
    pid = _paper_id(identity)
    if not pid:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/paper/{pid}", params={"fields": FIELDS},
                      headers=_headers(client), identity=identity)
    if not check(SOURCE_ID, resp):
        return None
    return _record(resp.json or {})


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
    items = []
    for row in (resp.json or {}).get("data") or []:
        p = row.get(key) or {}
        if p.get("paperId") or (p.get("externalIds") or {}).get("DOI"):
            r = _record(p)
            r["kind"] = "citation"
            items.append(r)
    return {"identity": identity, "what": what, "items": items}
