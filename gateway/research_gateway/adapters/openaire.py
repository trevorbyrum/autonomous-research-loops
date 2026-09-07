"""OpenAIRE Graph: DOI-metadata fallback and identifier-less repository records.

Registered-service auth: client id/secret exchanged for an hourly bearer token.
The exchange is an outbound call and is metered under this source.
"""
from __future__ import annotations

import base64
import time

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from .base import Client, check

SOURCE_ID = "openaire"
CAPABILITIES = ("find", "resolve")
BASE = "https://api.openaire.eu/graph/v1"
TOKEN_URL = "https://aai.openaire.eu/oidc/token"
_TOKEN: dict[str, object] = {}   # {"value": str, "exp": float}; one per process
_KIND = {"publication": "article", "dataset": "dataset", "software": "software", "other": "document"}


def _headers(client: Client) -> dict:
    """Bearer header when credentials exist; empty (keyless, 60/h) otherwise."""
    if _TOKEN.get("value") and float(_TOKEN.get("exp", 0)) > time.time() + 60:
        return {"Authorization": f"Bearer {_TOKEN['value']}"}
    cid, sec = client.secret("openaire", "client_id"), client.secret("openaire", "client_secret")
    if not (cid and sec):
        return {}
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    resp = client.post(SOURCE_ID, "resolve", TOKEN_URL, body=b"grant_type=client_credentials",
                       headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
                       query="token exchange")
    j = resp.json if resp.ok else None
    if not j or not j.get("access_token"):
        return {}
    _TOKEN["value"], _TOKEN["exp"] = j["access_token"], time.time() + float(j.get("expires_in", 3600))
    return {"Authorization": f"Bearer {_TOKEN['value']}"}


def reset_token() -> None:
    _TOKEN.clear()


def _record(r: dict) -> dict:
    pids = list(r.get("pids") or [])
    links, licenses = [], []
    for inst in r.get("instances") or []:
        pids += list(inst.get("alternateIdentifiers") or []) + list(inst.get("pids") or [])
        links += [u for u in (inst.get("urls") or []) if u]
        if inst.get("license"):
            licenses.append(inst["license"])
    doi = next((normalize_doi(p.get("value")) for p in pids if (p.get("scheme") or "").lower() == "doi" and normalize_doi(p.get("value"))), None)
    others = {(p.get("scheme") or "").lower(): p.get("value") for p in pids if p.get("scheme") and (p.get("scheme") or "").lower() != "doi"}
    ids = {"doi": doi} if doi else {}
    ids.update({k: v for k, v in others.items() if k in ("handle", "arxiv", "pmid", "urn")})
    typ = r.get("type") or ""
    return make_record(
        identity=f"doi:{doi}" if doi else f"openaire:{r.get('id')}",
        kind=_KIND.get(typ, "document"), source_id=SOURCE_ID, title=r.get("mainTitle"),
        authors=[a.get("fullName") for a in (r.get("authors") or []) if a.get("fullName")],
        year=year_from(r.get("publicationDate")), venue=(r.get("container") or {}).get("name") or r.get("publisher"),
        identifiers=ids, links=links, license=licenses[0] if licenses else None,
        extra={"openaire_id": r.get("id"), "access_right": (r.get("bestAccessRight") or {}).get("label"),
               "has_doi": bool(doi)},
        raw={k: r.get(k) for k in ("id", "mainTitle", "type", "publicationDate", "pids", "instances", "originalIds", "authors")},
    )


def find(client: Client, query: str, *, limit: int = 20, kind: str | None = None, cursor: str | None = None,
         year_from_: int | None = None) -> dict:
    params = {"search": query, "pageSize": min(limit, 100), "cursor": cursor or "*",
              "type": {"article": "publication", "dataset": "dataset", "software": "software"}.get(kind) if kind else None,
              "fromPublicationDate": f"{year_from_}-01-01" if year_from_ else None}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/researchProducts", params=params, headers=_headers(client), query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": 0, "next_cursor": None}
    j = resp.json or {}
    return {"records": [_record(r) for r in j.get("results") or []],
            "total": (j.get("header") or {}).get("numFound"), "next_cursor": (j.get("header") or {}).get("nextCursor")}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/researchProducts", params={"pid": doi, "pageSize": 1},
                      headers=_headers(client), identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    results = (resp.json or {}).get("results") or []
    return _record(results[0]) if results else None
