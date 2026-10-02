"""Crossref: base article lane; DOI resolution; reference lists for citation fallback."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi, normalize_issn
from .base import OMIT, Client, PayloadError, check, decode, members, total

SOURCE_ID = "crossref"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "enrich")
ENRICHES = ("references",)
SCHEMES = ("doi",)
AGENCIES = ("Crossref",)   # DOI registration agencies this source is the primary resolver for (R-1)
BASE = "https://api.crossref.org"

# What an answer must be. An author's name is `given`+`family`, else `name`: all three are declared, so all are decoded before one is chosen.
AUTHOR = S.obj({"given": S.text(), "family": S.text(), "name": S.text()}, alts=(("given", "family", "name"),))
WORK = S.obj({"DOI": S.text(), "URL": S.text(), "type": S.any_(), "title": S.own(S.text()), "author": S.own(AUTHOR), "container-title": S.own(S.text()),
              "issued": S.obj({"date-parts": S.own(S.own(S.year()))}), "created": S.obj({"date-time": S.text()}),   # the issue date, else the creation date
              "license": S.own(S.obj({"URL": S.text()})), "ISSN": S.own(S.text()), "publisher": S.text(),
              "is-referenced-by-count": S.any_(), "reference-count": S.any_()},
             alts=(("issued", "created"),))
REFERENCE = S.obj({"DOI": S.text(), "article-title": S.text(), "year": S.text(), "journal-title": S.text(), "unstructured": S.any_()})
FIND = S.obj({"message": S.required(S.obj({"items": S.required(S.members(WORK)), "total-results": S.soft(S.whole()), "next-cursor": S.soft(S.token())}))})
RESOLVE = S.obj({"message": S.required(WORK)})
ENRICH = S.obj({"message": S.required(S.obj({"reference": S.members(REFERENCE)}))})
SCHEMAS = {"find": FIND, "resolve": RESOLVE, "enrich:references": ENRICH}


def _author(a) -> str:
    """One author's name: the given and family names together, else the `name` of an organisation."""
    return " ".join(p for p in (a["given"], a["family"]) if p) or a["name"] or ""


def _record(client: Client, w) -> dict:
    doi, url = normalize_doi(w["DOI"]), w["URL"]
    if not doi and not (url and url.strip()):
        raise PayloadError(f"{SOURCE_ID}: a work with neither a DOI nor a URL names nothing (A4)")
    authors = [_author(a) for a in w["author"]]
    dated = w["issued"]["date-parts"]
    created = year_from(w["created"]["date-time"])
    parts = dated[0] if dated else []
    year = parts[0] if parts and parts[0] is not None else created
    licenses = [u for u in (l["URL"] for l in w["license"]) if u]
    issns = [normalize_issn(i) for i in w["ISSN"] if normalize_issn(i)]
    ids = {"doi": doi} if doi else {}
    if issns:
        ids["issn"] = issns[0]
    return make_record(
        identity=f"doi:{doi}" if doi else f"url:{url}",
        kind="article", source_id=SOURCE_ID,
        title=(w["title"] or [None])[0], authors=[a for a in authors if a], year=year,
        venue=(w["container-title"] or [None])[0], identifiers=ids,
        links=[url] if url else [], license=licenses[0] if licenses else None,
        attribution=None,
        extra={"type": w["type"], "cited_by_count": w["is-referenced-by-count"],
               "reference_count": w["reference-count"], "publisher": w["publisher"]},
        raw=w.raw,
    )


def _reference(r):
    """One deposited reference as a citation record, or OMIT when it deposited no DOI (most do not)."""
    doi = normalize_doi(r["DOI"])
    if not doi:
        return OMIT
    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, title=r["article-title"],
                       year=year_from(r["year"]), venue=r["journal-title"], identifiers={"doi": doi},
                       extra={"unstructured": r["unstructured"]}, raw=r.raw)


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
    msg = decode(SOURCE_ID, FIND, resp.json)["message"]
    items = msg["items"]
    # Crossref: "If the number of returned items is fewer than the number of expected rows then the end of
    # the result set has been reached"; a full page continues by its next-cursor (docs/PROVIDER-PAGINATION.md)
    end = len(items) < rows
    return {"records": members(SOURCE_ID, items, lambda w: _record(client, w)),
            "total": total(msg["total-results"], len(items)), "next_cursor": None if end else msg["next-cursor"], "exhausted": end}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/works/{doi}", params={"mailto": client.contact_email},
                      identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    msg = decode(SOURCE_ID, RESOLVE, resp.json)["message"]
    if not normalize_doi(msg["DOI"]):
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
    refs = decode(SOURCE_ID, ENRICH, resp.json)["message"]["reference"]   # a work that deposited no references has none; one whose `reference` is not a list is unreadable
    return {"identity": f"doi:{doi}", "what": what, "items": members(SOURCE_ID, refs, _reference)}
