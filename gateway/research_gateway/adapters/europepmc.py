"""Europe PMC: biomedical-domain article lane (per-item licences)."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check, decode, first_member, identity_from, members, total

SOURCE_ID = "europepmc"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi", "pmid")
BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

# What an answer must be. The identity is the DOI, else the PMID, else the id: all declared, so all decoded before one is chosen. The "Y"/"N" flags are
# text (a flag that is a list, a number or `false` is unreadable, not an N), and a year that is text and no number names none.
RECORD = S.obj({"doi": S.text(), "pmid": S.text(), "pmcid": S.text(), "id": S.text(), "source": S.text(), "title": S.text(), "authorString": S.text(),
                "pubYear": S.oneof(S.year(), S.text()), "journalTitle": S.text(), "license": S.text(),
                "hasTextMinedTerms": S.text(), "inEPMC": S.text(), "isOpenAccess": S.text()},
               alts=(("doi", "pmid", "id"),))
RESULTS = S.required(S.obj({"result": S.required(S.members(RECORD))}))
FIND = S.obj({"resultList": RESULTS, "hitCount": S.soft(S.whole()), "nextCursorMark": S.soft(S.token())})
RESOLVE = S.obj({"resultList": RESULTS})
SCHEMAS = {"find": FIND, "resolve": RESOLVE}


def _record(r) -> dict:
    doi = normalize_doi(r["doi"])
    mined, in_epmc = r["hasTextMinedTerms"] == "Y", r["inEPMC"] == "Y"
    pmid, pmcid, published = r["pmid"], r["pmcid"], r["pubYear"]
    ids = {k: v for k, v in (("doi", doi), ("pmid", pmid), ("pmcid", pmcid)) if v}
    own, source = r["id"], r["source"]
    identity = identity_from(SOURCE_ID, ("doi", doi), ("pmid", pmid), ("europepmc", own))
    links = [f"https://europepmc.org/abstract/{source}/{own}"] if own and source else []
    return make_record(
        identity=identity, kind="article", source_id=SOURCE_ID, title=r["title"],
        authors=[a.strip() for a in (r["authorString"] or "").rstrip(".").split(",") if a.strip()],
        year=None if isinstance(published, str) else published, venue=r["journalTitle"],   # text that is no year names none
        identifiers=ids, links=links, license=r["license"],  # per-article CC variant when the source states one
        extra={"open_access": r["isOpenAccess"] == "Y", "has_full_text": mined or in_epmc,
               "redistributable": False},
        raw=r.raw,
    )


def find(client: Client, query: str, *, limit: int = 20, cursor: str | None = None) -> dict:
    params = {"query": query, "format": "json", "pageSize": min(limit, 100), "cursorMark": cursor or "*", "resultType": "lite"}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/search", params=params, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = decode(SOURCE_ID, FIND, resp)
    results = j["resultList"]["result"]
    # Europe PMC documents only the continuation — "For every following page use the value of the returned
    # nextCursorMark element" — and no last page: a cursor that moves continues, nothing here ends the lane, and
    # a cursor handed back unchanged would only repeat this page (docs/PROVIDER-PAGINATION.md)
    mark = j["nextCursorMark"]
    nxt = mark if mark not in (None, cursor or "*") else None
    return {"records": members(SOURCE_ID, results, _record), "total": total(j["hitCount"], len(results)), "next_cursor": nxt,
            "exhausted": False}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    q = f"DOI:{doi}" if doi else (f"EXT_ID:{identity.split(':', 1)[1]}" if identity.startswith("pmid:") else None)
    if not q:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/search", params={"query": q, "format": "json", "pageSize": 1, "resultType": "lite"},
                      identity=identity)
    if not check(SOURCE_ID, resp):
        return None
    return first_member(SOURCE_ID, decode(SOURCE_ID, RESOLVE, resp)["resultList"]["result"], _record)
