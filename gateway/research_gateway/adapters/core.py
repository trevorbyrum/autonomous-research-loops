"""CORE: repository full text (personal-research lane; small daily budget)."""
from __future__ import annotations

from ..core.canonical import make_record
from ..core.identity import normalize_doi
from .base import Client, check, quote

SOURCE_ID = "core"
CAPABILITIES = ("resolve", "enrich")
ENRICHES = ("full_text",)
SCHEMES = ("doi",)
BASE = "https://api.core.ac.uk/v3"


def _headers(client: Client) -> dict:
    key = client.secret("core")
    return {"Authorization": f"Bearer {key}"} if key else {}


def _record(w: dict, *, with_text: bool = False) -> dict:
    doi = normalize_doi(w.get("doi"))
    links = [u for u in (w.get("downloadUrl"), *(w.get("sourceFulltextUrls") or [])) if u]
    rec = make_record(
        identity=f"doi:{doi}" if doi else f"core:{w.get('id')}",
        kind="full_text" if with_text else "article", source_id=SOURCE_ID, title=w.get("title"),
        authors=[a.get("name") for a in (w.get("authors") or []) if a.get("name")], year=w.get("yearPublished"),
        venue=(w.get("publisher") or None), identifiers={"doi": doi} if doi else {"core": str(w.get("id"))},
        links=links, license=None, attribution="CORE",
        extra={"core_id": w.get("id"), "redistributable": False, "has_full_text": bool(w.get("fullText"))},
        raw={k: v for k, v in w.items() if k != "fullText"},  # the payload minus the text itself (I-7)
    )
    if with_text and w.get("fullText"):
        rec["text"] = w["fullText"]  # returned to the caller, never stored (I-7)
    return rec


def _lookup(client: Client, doi: str, request_type: str, *, want_text: bool) -> dict | None:
    resp = client.get(SOURCE_ID, request_type, f"{BASE}/search/works",
                      params={"q": f'doi:"{doi}"', "limit": 1, "exclude": None if want_text else "fullText"},
                      headers=_headers(client), identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    results = (resp.json or {}).get("results") or []
    return results[0] if results else None


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    w = _lookup(client, doi, "resolve", want_text=False)
    return _record(w) if w else None


def enrich(client: Client, identity: str, what: str = "full_text") -> dict:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi or what != "full_text":
        return {"identity": identity, "what": what, "items": []}
    w = _lookup(client, doi, "enrich", want_text=True)
    return {"identity": f"doi:{doi}", "what": what, "items": [_record(w, with_text=True)] if w else []}
