"""OpenAIRE Graph: DOI-metadata fallback and identifier-less repository records.

Registered-service auth: client id/secret exchanged for an hourly bearer token.
The exchange is an outbound call and is metered under this source.
"""
from __future__ import annotations

import base64
import time

from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from .base import NO_MEMBERS, Client, check, first_member, members, need, plain, scalar

SOURCE_ID = "openaire"
SMOKE = {'capability': 'find', 'query': 'management practices', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi",)
AGENCIES = ("*",)   # primary for DOIs from any other registration agency (mEDRA, KISTI, ...) and unknown ones
BASE = "https://api.openaire.eu/graph/v1"
TOKEN_URL = "https://aai.openaire.eu/oidc/token"
_TOKEN: dict[str, object] = {}   # {"value": str, "exp": float}; one per process
_TOKEN_LOCK = __import__("threading").Lock()   # single-flight mint under parallel lanes: a concurrent
                                               # refresh must never hand out a token the requesting
                                               # client did not register for redaction (9·2b)
_KIND = {"publication": "article", "dataset": "dataset", "software": "software", "other": "document"}


def _headers(client: Client) -> dict:
    """Bearer header when credentials exist; empty (keyless, 60/h) otherwise. Minting is
    single-flight: the lock covers check-and-mint, and EVERY caller registers the token it
    is about to send for redaction — including one minted by a sibling lane (9·2b)."""
    with _TOKEN_LOCK:
        return _headers_locked(client)


def _headers_locked(client: Client) -> dict:
    if _TOKEN.get("value") and float(_TOKEN.get("exp", 0)) > time.time() + 60:
        client.secret_values.add(_TOKEN["value"])   # a fresh Client reusing the process token learns it too (D-24)
        return {"Authorization": f"Bearer {_TOKEN['value']}"}
    cid, sec = client.secret("openaire", "client_id"), client.secret("openaire", "client_secret")
    if not (cid and sec):
        return {}
    basic = base64.b64encode(f"{cid}:{sec}".encode()).decode()
    resp = client.post(SOURCE_ID, "resolve", TOKEN_URL, body=b"grant_type=client_credentials",
                       headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
                       query="token exchange")
    if not resp.ok:
        return {}   # a refused exchange: the lane reports the missing credentials
    j = need(SOURCE_ID, resp.json, kind=dict)   # an unreadable 200 is an unreadable answer, not "no credentials"
    if not j.get("access_token"):
        return {}
    try:
        ttl = float(j.get("expires_in") or 3600)
    except (TypeError, ValueError):
        ttl = 3600.0
    _TOKEN["value"], _TOKEN["exp"] = str(j["access_token"]), time.time() + ttl
    client.secret_values.add(_TOKEN["value"])   # an exchanged bearer token is a secret too (D-24)
    return {"Authorization": f"Bearer {_TOKEN['value']}"}


def reset_token() -> None:
    _TOKEN.clear()


def _record(r: dict) -> dict:
    pids = list(plain(r.get("pids")) or [])
    links, licenses = [], []
    for inst in plain(r.get("instances")) or []:
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
        authors=[a.get("fullName") for a in (plain(r.get("authors")) or []) if a.get("fullName")],
        year=year_from(r.get("publicationDate")), venue=(r.get("container") or {}).get("name") or r.get("publisher"),
        identifiers=ids, links=links, license=licenses[0] if licenses else None,
        attribution="OpenAIRE",   # the CC-BY verdict is conditional on attribution (seed evidence)
        extra={"openaire_id": r.get("id"), "access_right": (r.get("bestAccessRight") or {}).get("label"),
               "has_doi": bool(doi)},
        raw=r,
    )


def find(client: Client, query: str, *, limit: int = 20, kind: str | None = None, cursor: str | None = None,
         year_from_: int | None = None) -> dict:
    hdrs = _headers(client)
    if not hdrs:
        # the enabled rate policy is the REGISTERED tier (7,200/h); keyless would be 60/h, so
        # running without credentials under this policy would overrun the real limit (D-23)
        return {"records": [], "total": 0, "next_cursor": None,
                "capability_fact": "no OpenAIRE client credentials (or token exchange failed); the keyless tier is 60/h and is not enabled"}
    params = {"search": query, "pageSize": min(limit, 100), "cursor": cursor or "*",
              "type": {"article": "publication", "dataset": "dataset", "software": "software"}.get(kind) if kind else None,
              "fromPublicationDate": f"{year_from_}-01-01" if year_from_ else None}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/researchProducts", params=params, headers=hdrs, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = need(SOURCE_ID, resp.json, kind=dict)
    header = need(SOURCE_ID, j, "header", kind=dict)
    # an answer may leave `results` out only when its header says nothing matched
    rows = need(SOURCE_ID, j, "results") if j.get("results") is not None or header.get("numFound") != 0 else NO_MEMBERS
    # OpenAIRE's end: "the nextCursor returned matches the current cursor you've already specified"; and
    # numFound is "the total number of entities found", so a first page holding that many holds them all.
    # A missing nextCursor is undocumented: it neither continues nor ends (docs/PROVIDER-PAGINATION.md)
    sent, found = cursor or "*", scalar(header.get("numFound"))
    end = header.get("nextCursor") == sent or (sent == "*" and type(found) is int and len(rows) >= found)
    return {"records": members(SOURCE_ID, rows, _record), "total": found,
            "next_cursor": None if end else scalar(header.get("nextCursor")), "exhausted": end}


def resolve(client: Client, identity: str) -> dict | None:
    doi = normalize_doi(identity.split(":", 1)[-1] if identity.startswith("doi:") else identity)
    if not doi:
        return None
    hdrs = _headers(client)
    if not hdrs:   # same as find: the enabled policy assumes the registered tier (D-23) — an auth fact, not "not found"
        return {"capability_fact": "no OpenAIRE client credentials (or token exchange failed); the keyless tier is 60/h and is not enabled"}
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/researchProducts", params={"pid": doi, "pageSize": 1},
                      headers=hdrs, identity=f"doi:{doi}")
    if not check(SOURCE_ID, resp):
        return None
    j = need(SOURCE_ID, resp.json, kind=dict)
    rows = need(SOURCE_ID, j, "results") if j.get("results") is not None or (j.get("header") or {}).get("numFound") != 0 else NO_MEMBERS
    return first_member(SOURCE_ID, rows, _record)
