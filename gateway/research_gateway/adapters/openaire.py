"""OpenAIRE Graph: DOI-metadata fallback and identifier-less repository records.

Registered-service auth: client id/secret exchanged for an hourly bearer token.
The exchange is an outbound call and is metered under this source.
"""
from __future__ import annotations

import base64
import threading
import time

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.identity import normalize_doi
from .base import Client, check, decode, first_member, identity_from, members, total

SOURCE_ID = "openaire"
SMOKE = {'capability': 'find', 'query': 'management practices', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve")
SCHEMES = ("doi",)
AGENCIES = ("*",)   # primary for DOIs from any other registration agency (mEDRA, KISTI, ...) and unknown ones
BASE = "https://api.openaire.eu/graph/v1"
TOKEN_URL = "https://aai.openaire.eu/oidc/token"
_TOKEN: dict[str, object] = {}   # {"value": str, "exp": float}; one per process
_TOKEN_LOCK = threading.Lock()   # single-flight mint under parallel lanes: a concurrent
                                               # refresh must never hand out a token the requesting
                                               # client did not register for redaction (9·2b)
_KIND = {"publication": "article", "dataset": "dataset", "software": "software", "other": "document"}

# What an answer must be. A product is named by the DOI among its identifiers (the product's `pids`, and each instance's `alternateIdentifiers` and `pids`; all
# are decoded), else by its own id. A list may be left out only when the header's `numFound` is the whole number 0; a header that cannot be read costs the members
# beside it only what it alone establishes — an end, a continuation. Graph API V1: `GraphResult.pids` and `Instance.pids` are arrays of `ResultPid`, `Instance.alternateIdentifiers`
# an array of `AlternateIdentifier`; each has a string `scheme` and `value`.
PID = S.obj({"scheme": S.text(), "value": S.text()})
PRODUCT = S.obj({"id": S.maybe_key(), "mainTitle": S.text(), "type": S.text(), "publicationDate": S.text(), "publisher": S.text(),
                 "pids": S.own(PID), "authors": S.own(S.obj({"fullName": S.text()})),
                 "instances": S.own(S.obj({"alternateIdentifiers": S.own(PID), "pids": S.own(PID), "urls": S.own(S.text()), "license": S.text()})),
                 "container": S.obj({"name": S.text()}), "bestAccessRight": S.obj({"label": S.any_()})},
                alts=(("pids", "instances", "id"),))
RESULTS = S.members(PRODUCT, empty_when=("header", "numFound"))
FIND = S.obj({"results": RESULTS, "header.numFound": S.deep(("header", "numFound"), S.whole()), "header.nextCursor": S.deep(("header", "nextCursor"), S.token())})
RESOLVE = S.obj({"results": RESULTS})
TOKEN = S.obj({"access_token": S.any_(), "expires_in": S.any_()})
SCHEMAS = {"find": FIND, "resolve": RESOLVE, "token": TOKEN}


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
    j = decode(SOURCE_ID, TOKEN, resp.json)   # an unreadable 200 is an unreadable answer, not "no credentials"
    if not j["access_token"]:
        return {}
    try:
        ttl = float(j["expires_in"] or 3600)
    except (TypeError, ValueError):
        ttl = 3600.0
    _TOKEN["value"], _TOKEN["exp"] = str(j["access_token"]), time.time() + ttl
    client.secret_values.add(_TOKEN["value"])   # an exchanged bearer token is a secret too (D-24)
    return {"Authorization": f"Bearer {_TOKEN['value']}"}


def reset_token() -> None:
    _TOKEN.clear()


def _record(r) -> dict:
    pids = list(r["pids"])
    links, licenses = [], []
    for inst in r["instances"]:
        pids += inst["alternateIdentifiers"] + inst["pids"]
        links += [u for u in inst["urls"] if u]
        if inst["license"]:
            licenses.append(inst["license"])
    schemes = [(p["scheme"] or "").lower() for p in pids]
    dois = [normalize_doi(p["value"]) for p, scheme in zip(pids, schemes) if scheme == "doi"]   # every DOI it lists is read; the first that is one is its DOI
    doi = next((d for d in dois if d), None)
    others = {scheme: p["value"] for p, scheme in zip(pids, schemes) if scheme and scheme != "doi"}
    ids = {"doi": doi} if doi else {}
    ids.update({k: v for k, v in others.items() if k in ("handle", "arxiv", "pmid", "urn")})
    typ, publisher, own = r["type"] or "", r["publisher"], r["id"]
    return make_record(
        identity=identity_from(SOURCE_ID, ("doi", doi), ("openaire", own)),
        kind=_KIND.get(typ, "document"), source_id=SOURCE_ID, title=r["mainTitle"],
        authors=[n for n in (a["fullName"] for a in r["authors"]) if n],
        year=year_from(r["publicationDate"]), venue=r["container"]["name"] or publisher,
        identifiers=ids, links=links, license=licenses[0] if licenses else None,
        attribution="OpenAIRE",   # the CC-BY verdict is conditional on attribution (seed evidence)
        extra={"openaire_id": r["id"], "publisher": publisher, "access_right": r["bestAccessRight"]["label"],
               "has_doi": bool(doi)},
        raw=r.raw,
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
    j = decode(SOURCE_ID, FIND, resp.json)
    rows = j["results"]
    # OpenAIRE's end: "the nextCursor returned matches the current cursor you've already specified"; and
    # numFound is "the total number of entities found", so a first page holding that many holds them all.
    # A missing nextCursor is undocumented: it neither continues nor ends (docs/PROVIDER-PAGINATION.md)
    sent, found, mark = cursor or "*", total(j["header.numFound"], len(rows)), j["header.nextCursor"]
    end = mark == sent or (sent == "*" and found is not None and len(rows) >= found)
    return {"records": members(SOURCE_ID, rows, _record), "total": found,
            "next_cursor": None if end else mark, "exhausted": end}


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
    return first_member(SOURCE_ID, decode(SOURCE_ID, RESOLVE, resp.json)["results"], _record)
