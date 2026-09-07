"""Crossref: base article lane; DOI resolution; reference lists for citation fallback."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import Client, check

SOURCE_ID = "crossref"
CAPABILITIES = ("find", "resolve", "enrich")
ENRICHES = ("references",)
SCHEMES = ("doi",)
BASE = "https://api.crossref.org"


def _record(client: Client, w: dict) -> dict:
    doi = normalize_doi(w.get("DOI"))
    authors = [" ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name", "")
               for a in w.get("author", [])]
    issued = (w.get("issued") or {}).get("date-parts") or [[None]]
    year = issued[0][0] if issued and issued[0] and issued[0][0] else year_from((w.get("created") or {}).get("date-time"))
    licenses = [l.get("URL") for l in w.get("license", []) if l.get("URL")]
    issns = [normalize_issn(i) for i in w.get("ISSN", []) if normalize_issn(i)]
    ids = {"doi": doi} if doi else {}
    if issns:
        ids["issn"] = issns[0]
    return make_record(
        identity=f"doi:{doi}" if doi else f"url:{w.get('URL')}",
        kind="article", source_id=SOURCE_ID,
        title=(w.get("title") or [None])[0], authors=[a for a in authors if a], year=year,
        venue=(w.get("container-title") or [None])[0], identifiers=ids,
        links=[u for u in (w.get("URL"),) if u], license=licenses[0] if licenses else None,
        attribution=None,
        extra={"type": w.get("type"), "cited_by_count": w.get("is-referenced-by-count"),
               "reference_count": w.get("reference-count"), "publisher": w.get("publisher")},
        raw={k: w.get(k) for k in ("DOI", "type", "title", "author", "issued", "container-title", "ISSN", "URL",
                                   "license", "publisher", "is-referenced-by-count", "reference-count", "subject")},
    )


def find(client: Client, query: str, *, limit: int = 20, year_from_: int | None = None,
         year_to: int | None = None, cursor: str | None = None) -> dict:
    filters = []
    if year_from_:
        filters.append(f"from-pub-date:{year_from_}")
    if year_to:
        filters.append(f"until-pub-date:{year_to}")
    params = {"query.bibliographic": query, "rows": min(limit, 100), "mailto": client.contact_email,
              "filter": ",".join(filters) or None, "cursor": cursor}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/works", params=params, query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": 0, "next_cursor": None}
    msg = (resp.json or {}).get("message") or {}
    return {"records": [_record(client, w) for w in msg.get("items", [])],
            "total": msg.get("total-results"), "next_cursor": msg.get("next-cursor")}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/works/{doi}", params={"mailto": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    return _record(client, (resp.json or {}).get("message") or {})


def enrich(client: Client, identity: str, what: str = "references") -> dict:
    """references: DOIs this work cites (from its deposited reference list)."""
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi or what != "references":
        return {"identity": identity, "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{BASE}/works/{doi}", params={"mailto": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    refs = ((resp.json or {}).get("message") or {}).get("reference") or []
    items = [{"identity": f"doi:{normalize_doi(r['DOI'])}", "unstructured": r.get("unstructured")}
             for r in refs if r.get("DOI") and normalize_doi(r.get("DOI"))]
    return {"identity": f"doi:{doi}", "what": what, "items": items}
