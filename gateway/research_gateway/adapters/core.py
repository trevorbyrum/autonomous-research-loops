"""CORE: repository full text (personal-research lane; small daily budget)."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check, decode, first_member, identity_from

SOURCE_ID = "core"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("resolve", "enrich")
ENRICHES = ("full_text",)
SCHEMES = ("doi",)
BASE = "https://api.core.ac.uk/v3"

# What an answer must be. A work is named by its DOI, else its own id: both are declared, so both are decoded before the record picks one.
WORK = S.obj({"doi": S.text(), "id": S.maybe_key(), "title": S.text(), "downloadUrl": S.text(), "sourceFulltextUrls": S.own(S.text()),
              "authors": S.own(S.obj({"name": S.text()})), "yearPublished": S.year(), "publisher": S.text(), "fullText": S.text()},
             alts=(("doi", "id"),))
SEARCH = S.obj({"results": S.required(S.members(WORK))})
SCHEMAS = {"resolve": SEARCH, "enrich:full_text": SEARCH}


def _headers(client: Client) -> dict:
    key = client.secret("core")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _record(w, *, with_text: bool = False) -> dict:
    doi = normalize_doi(w["doi"])
    links = [u for u in (w["downloadUrl"], *w["sourceFulltextUrls"]) if u]
    full_text, publisher, own = w["fullText"], w["publisher"], w["id"]
    identity = identity_from(SOURCE_ID, ("doi", doi), ("core", own))
    rec = make_record(
        identity=identity,
        kind="full_text" if with_text else "article", source_id=SOURCE_ID, title=w["title"],
        authors=[n for n in (a["name"] for a in w["authors"]) if n], year=w["yearPublished"],
        venue=publisher or None, identifiers={"doi": doi} if doi else {"core": str(own)},
        links=links, license=None, attribution="CORE",
        extra={"core_id": w["id"], "publisher": publisher, "redistributable": False, "has_full_text": bool(full_text)},
        raw={k: v for k, v in w.raw.items() if k != "fullText"},  # the payload minus the text itself (I-7)
    )
    if with_text and full_text:
        rec["text"] = full_text  # returned to the caller, never stored (I-7)
    return rec


def _lookup(client: Client, doi: str, request_type: str, *, want_text: bool) -> dict | None:
    resp = client.get(SOURCE_ID, request_type, f"{BASE}/search/works",
                      params={"q": f'doi:"{doi}"', "limit": 1, "exclude": None if want_text else "fullText"},
                      headers=_headers(client), identity=f"doi:{doi}")
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    return first_member(SOURCE_ID, decode(SOURCE_ID, SEARCH, resp.json)["results"], lambda w: _record(w, with_text=want_text))


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    return _lookup(client, doi, "resolve", want_text=False)


def enrich(client: Client, identity: str, what: str = "full_text") -> dict:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi or what != "full_text":
        return {"identity": identity, "what": what, "items": []}
    rec = _lookup(client, doi, "enrich", want_text=True)
    return {"identity": f"doi:{doi}", "what": what, "items": [rec] if rec else []}
