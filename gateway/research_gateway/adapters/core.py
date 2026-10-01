"""CORE: repository full text (personal-research lane; small daily budget)."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check, first_member, identity_from, listed, maybe_key, need, plain, quote, text

SOURCE_ID = "core"
SMOKE = {'capability': 'resolve', 'identity': 'doi:10.1038/nature12373'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("resolve", "enrich")
ENRICHES = ("full_text",)
SCHEMES = ("doi",)
BASE = "https://api.core.ac.uk/v3"


def _headers(client: Client) -> dict:
    key = client.secret("core")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _record(w: dict, *, with_text: bool = False) -> dict:
    doi = normalize_doi(w.get("doi"))
    links = [u for u in (text(SOURCE_ID, w.get("downloadUrl")), *(text(SOURCE_ID, u) for u in listed(SOURCE_ID, w, "sourceFulltextUrls"))) if u]
    full_text, publisher, own = text(SOURCE_ID, w.get("fullText")), text(SOURCE_ID, w.get("publisher")), maybe_key(SOURCE_ID, w.get("id"))
    identity = identity_from(SOURCE_ID, ("doi", doi), ("core", own))
    rec = make_record(
        identity=identity,
        kind="full_text" if with_text else "article", source_id=SOURCE_ID, title=w.get("title"),
        authors=[n for n in (text(SOURCE_ID, a.get("name")) for a in listed(SOURCE_ID, w, "authors")) if n], year=w.get("yearPublished"),
        venue=publisher or None, identifiers={"doi": doi} if doi else {"core": own},
        links=links, license=None, attribution="CORE",
        extra={"core_id": w.get("id"), "publisher": publisher, "redistributable": False, "has_full_text": bool(full_text)},
        raw={k: v for k, v in plain(w).items() if k != "fullText"},  # the payload minus the text itself (I-7)
    )
    if with_text and full_text:
        rec["text"] = full_text  # returned to the caller, never stored (I-7)
    return rec


def _lookup(client: Client, doi: str, request_type: str, *, want_text: bool) -> dict | None:
    resp = client.get(SOURCE_ID, request_type, f"{BASE}/search/works",
                      params={"q": f'doi:"{doi}"', "limit": 1, "exclude": None if want_text else "fullText"},
                      headers=_headers(client), identity=f"doi:{doi}")
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    return first_member(SOURCE_ID, need(SOURCE_ID, resp.json, "results"), lambda w: _record(w, with_text=want_text))


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
