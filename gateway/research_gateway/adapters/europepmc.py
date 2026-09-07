"""Europe PMC: biomedical-domain article lane (per-item licences)."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check

SOURCE_ID = "europepmc"
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi", "pmid")
BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"


def _record(r: dict) -> dict:
    doi = normalize_doi(r.get("doi"))
    ids = {k: v for k, v in (("doi", doi), ("pmid", r.get("pmid")), ("pmcid", r.get("pmcid"))) if v}
    identity = f"doi:{doi}" if doi else (f"pmid:{r.get('pmid')}" if r.get("pmid") else f"europepmc:{r.get('id')}")
    links = [f"https://europepmc.org/abstract/{r.get('source')}/{r.get('id')}"] if r.get("id") and r.get("source") else []
    return make_record(
        identity=identity, kind="article", source_id=SOURCE_ID, title=r.get("title"),
        authors=[a.strip() for a in (r.get("authorString") or "").rstrip(".").split(",") if a.strip()],
        year=int(r["pubYear"]) if str(r.get("pubYear", "")).isdigit() else None, venue=r.get("journalTitle"),
        identifiers=ids, links=links, license=None,
        extra={"open_access": (r.get("isOpenAccess") == "Y"), "has_full_text": (r.get("hasTextMinedTerms") == "Y") or (r.get("inEPMC") == "Y"),
               "redistributable": False},
        raw={k: r.get(k) for k in ("id", "source", "doi", "pmid", "pmcid", "title", "authorString", "pubYear", "journalTitle", "isOpenAccess")},
    )


def find(client: Client, query: str, *, limit: int = 20, cursor: str | None = None) -> dict:
    params = {"query": query, "format": "json", "pageSize": min(limit, 100), "cursorMark": cursor or "*", "resultType": "lite"}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/search", params=params, query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": 0, "next_cursor": None}
    j = resp.json or {}
    results = (j.get("resultList") or {}).get("result") or []
    nxt = j.get("nextCursorMark") if results and j.get("nextCursorMark") != (cursor or "*") else None
    return {"records": [_record(r) for r in results], "total": j.get("hitCount"), "next_cursor": nxt}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    q = f"DOI:{doi}" if doi else (f"EXT_ID:{identity.split(':', 1)[1]}" if identity.startswith("pmid:") else None)
    if not q:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search", params={"query": q, "format": "json", "pageSize": 1, "resultType": "lite"},
                      identity=identity)
    if not check(SOURCE_ID, resp):
        return None
    results = ((resp.json or {}).get("resultList") or {}).get("result") or []
    return _record(results[0]) if results else None
