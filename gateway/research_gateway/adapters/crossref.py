"""Crossref: base article lane; DOI resolution; reference lists for citation fallback."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import OMIT, Client, PayloadError, check, members, need

SOURCE_ID = "crossref"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "enrich")
ENRICHES = ("references",)
SCHEMES = ("doi",)
AGENCIES = ("Crossref",)   # DOI registration agencies this source is the primary resolver for (R-1)
BASE = "https://api.crossref.org"


def _record(client: Client, w: dict) -> dict:
    doi = normalize_doi(w.get("DOI"))
    if not doi and not (isinstance(w.get("URL"), str) and w["URL"].strip()):
        raise PayloadError(f"{SOURCE_ID}: a work with neither a DOI nor a URL names nothing (A4)")
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
        raw=w,
    )


def _reference(r: dict):
    """One deposited reference as a citation record, or OMIT when it deposited no DOI (most do not)."""
    doi = normalize_doi(r.get("DOI"))
    if not doi:
        return OMIT
    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, title=r.get("article-title"),
                       year=year_from(r.get("year")), venue=r.get("journal-title"), identifiers={"doi": doi},
                       extra={"unstructured": r.get("unstructured")}, raw=r)


def find(client: Client, query: str, *, limit: int = 20, year_from_: int | None = None,
         year_to: int | None = None, cursor: str | None = None) -> dict:
    filters = []
    if year_from_:
        filters.append(f"from-pub-date:{year_from_}")
    if year_to:
        filters.append(f"until-pub-date:{year_to}")
    rows = min(limit, 100)
    params = {"query.bibliographic": query, "rows": rows, "mailto": client.contact_email,
              "filter": ",".join(filters) or None, "cursor": cursor or "*"}   # Crossref sends next-cursor only when asked with one
    resp = client.get(SOURCE_ID, "find", f"{BASE}/works", params=params, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    msg = need(SOURCE_ID, resp.json, "message", kind=dict)
    items, total = need(SOURCE_ID, msg, "items"), msg.get("total-results")
    # Crossref: "If the number of returned items is fewer than the number of expected rows then the end of
    # the result set has been reached"; a full page continues by its next-cursor (docs/PROVIDER-PAGINATION.md)
    end = len(items) < rows
    return {"records": members(SOURCE_ID, items, lambda w: _record(client, w)),
            "total": total, "next_cursor": None if end else msg.get("next-cursor"), "exhausted": end}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/works/{doi}", params={"mailto": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    msg = need(SOURCE_ID, resp.json, "message", kind=dict)
    if not normalize_doi(msg.get("DOI")):
        # an HTTP 200 that is not a Crossref work envelope is not a record (D-23) — and not
        # "no such DOI" either: it is an unreadable answer (task 2b, H-5)
        raise PayloadError(f"{SOURCE_ID}: the answer's message carries no DOI")
    return _record(client, msg)


def enrich(client: Client, identity: str, what: str = "references") -> dict:
    """references: DOIs this work cites (from its deposited reference list)."""
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi or what != "references":
        return {"identity": identity, "what": what, "items": []}
    resp = client.get(SOURCE_ID, "enrich", f"{BASE}/works/{doi}", params={"mailto": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"doi:{doi}", "what": what, "items": []}
    msg = need(SOURCE_ID, resp.json, "message", kind=dict)
    refs = need(SOURCE_ID, msg, "reference") if msg.get("reference") else []   # a work that deposited no references has none
    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, refs, _reference)}
