"""Socrata (SODA): federated government open-data portals. Licence is per dataset."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..core.canonical import make_record, year_from
from ..core.licenses import allow_listed
from .base import AdapterError, Client, Obj, PayloadError, check, key, listed, members, need, nested, plain, preferred, text, total

SOURCE_ID = "socrata"
SMOKE = {'capability': 'find', 'query': 'business licenses', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
DISCOVERY = "https://api.us.socrata.com/api/catalog/v1"
SEARCH_WINDOW = 10_000   # Socrata refuses a search whose offset + limit exceeds 10,000 (docs/PROVIDER-PAGINATION.md)


def _headers(client: Client) -> dict:
    tok = client.secret("socrata")
    return {"X-App-Token": tok} if tok else {}


_KNOWN_DOMAINS: set[str] = set()   # portals the discovery catalog has vouched for, per process


def _split(target: str) -> tuple[str, str]:
    """'socrata:{domain}:{id}' → (domain, id)."""
    parts = target.split(":")
    if len(parts) != 3 or parts[0] != "socrata" or not parts[1] or not parts[2]:
        raise AdapterError("socrata target must be 'socrata:<domain>:<dataset_id>'")
    return parts[1].lower(), parts[2]


_HOSTNAME = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def _vouched(client: Client, domain: str) -> None:
    """R-6: only portals the Socrata discovery catalog itself lists may be called. The hostname
    must be syntactically valid, and the catalog must return a result whose portal is EXACTLY the
    requested one (a nonzero count for a lookalike is not a voucher). Remembered per process."""
    if not _HOSTNAME.match(domain):
        raise AdapterError(f"{domain!r} is not a valid portal hostname")
    if domain in _KNOWN_DOMAINS:
        return
    resp = client.get(SOURCE_ID, "resolve", DISCOVERY, params={"domains": domain, "limit": 1, "only": "datasets"},
                      headers=_headers(client), identity=f"socrata:{domain}")
    vouched = {((r.get("metadata") or {}).get("domain") or "").lower() for r in plain(need(SOURCE_ID, resp.json, "results"))
               if isinstance(r, dict)} if check(SOURCE_ID, resp) else set()
    if domain not in vouched:
        raise AdapterError(f"{domain} is not a Socrata portal known to the discovery catalog (R-6)")
    _KNOWN_DOMAINS.add(domain)


def reset_known_domains() -> None:
    _KNOWN_DOMAINS.clear()


def _catalog_record(r: dict) -> dict:
    res, meta = nested(SOURCE_ID, r, "resource"), nested(SOURCE_ID, r, "metadata")
    domain, did = key(SOURCE_ID, meta.get("domain")), key(SOURCE_ID, res.get("id"))
    return make_record(identity=f"socrata:{domain}:{did}", kind="dataset", source_id=SOURCE_ID, title=res.get("name"),
                       year=year_from(res.get("updatedAt")), venue=domain, identifiers={"dataset_id": did},
                       links=[preferred(text(SOURCE_ID, r.get("permalink")), text(SOURCE_ID, r.get("link")), f"https://{domain}/d/{did}")], license=meta.get("license"),
                       extra={"description": (text(SOURCE_ID, res.get("description")) or "")[:1000], "type": res.get("type"), "updated_at": res.get("updatedAt"),
                              "attribution": res.get("attribution")},
                       raw=r)


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0, portal: str | None = None) -> dict:
    """`portal` restricts to one Socrata-hosted portal hostname. (Deliberately NOT named `domain`:
    the router forwards the request's TOPIC domain to a parameter of that name — D-23.)"""
    size = min(limit, 100)
    params = {"q": query, "only": "datasets", "limit": size, "offset": offset, "domains": portal}
    resp = client.get(SOURCE_ID, "find", DISCOVERY, params=params, headers=_headers(client), query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = resp.json
    results = need(SOURCE_ID, j, "results")
    count = total(j.get("resultSetSize"), offset + len(results))
    records = members(SOURCE_ID, results, _catalog_record)
    # the catalog vouches for a portal only through a member read whole: learning domains from the raw
    # members, before each is decoded alone, let one non-object member lose the whole page (A4)
    _KNOWN_DOMAINS.update(r["venue"].lower() for r in records if r and isinstance(r.get("venue"), str) and r["venue"])
    # resultSetSize is "The total number of assets that could be returned from a query": the page reaching it
    # is the last, and a missing size ends nothing. A next page past the 10,000 window would be refused, so
    # none is offered there — the window ends nothing either
    following = offset + len(results)
    reached = count is not None and following >= count
    nxt = following if results and count is not None and not reached and following + size <= SEARCH_WINDOW else None
    return {"records": records, "total": count, "next_offset": nxt, "exhausted": reached}


def _epoch_year(value) -> int | None:
    """The year of a view's timestamp, which Socrata states as epoch seconds (the leading digits of 1694726470 are not a year); none when
    the view states none, and anything but a whole number of seconds is unreadable."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadError(f"{SOURCE_ID}: {type(value).__name__} where a timestamp belongs")
    try:
        return datetime.fromtimestamp(value, timezone.utc).year
    except (OverflowError, OSError, ValueError):
        raise PayloadError(f"{SOURCE_ID}: {value} is no timestamp") from None


def resolve(client: Client, identity: str) -> dict | None:
    domain, did = _split(identity)
    _vouched(client, domain)
    resp = client.get(SOURCE_ID, "resolve", f"https://{domain}/api/views/{did}.json", headers=_headers(client), identity=identity)
    if not check(SOURCE_ID, resp):
        return None
    v = need(SOURCE_ID, resp.json, kind=dict)
    if not v.get("id"):
        raise PayloadError(f"{SOURCE_ID}: the view answer carries no id")
    lic = v.get("license")
    return make_record(identity=identity, kind="dataset", source_id=SOURCE_ID, title=v.get("name"), year=_epoch_year(v.get("rowsUpdatedAt")),
                       venue=domain, identifiers={"dataset_id": did}, links=[f"https://{domain}/d/{did}"],
                       license=lic.get("name") if isinstance(lic, Obj) else lic,
                       extra={"description": (text(SOURCE_ID, v.get("description")) or "")[:1000],
                              "columns": [text(SOURCE_ID, c.get("fieldName")) for c in listed(SOURCE_ID, v, "columns")],
                              "attribution": v.get("attribution"), "license_link": lic.get("termsLink") if isinstance(lic, Obj) else None},
                       raw=v)


def fetch(client: Client, target: str, *, limit: int = 1000, offset: int = 0, where: str | None = None) -> dict:
    """Rows of a dataset through the SODA resource endpoint (JSON); nothing is persisted.
    The dataset's own licence is looked up first (it vouches the portal too) and travels with
    the rows, so per-item commercial gating can act on them (R-8, D-23)."""
    domain, did = _split(target)
    meta = resolve(client, target)   # vouches the portal and carries the dataset licence
    if meta is None:
        return {"identity": target, "records": [], "capability_fact": "dataset not found"}
    if client.commercial and not allow_listed(meta.get("license")):
        return {"identity": target, "records": [],
                "capability_fact": f"rows refused before fetching: dataset licence {meta.get('license') or 'unknown'} is not usable commercially (R-8)"}
    params = {"$limit": min(limit, 50000), "$offset": offset, "$where": where}
    resp = client.get(SOURCE_ID, "fetch", f"https://{domain}/resource/{did}.json", params=params, headers=_headers(client), identity=target)
    if not check(SOURCE_ID, resp):
        return {"identity": target, "records": []}
    rows = need(SOURCE_ID, resp.json)
    rec = make_record(identity=f"{target}#rows", kind="file", source_id=SOURCE_ID, title=f"{did} rows {offset}-{offset + len(rows)}",
                      links=[f"https://{domain}/resource/{did}.json"], license=meta.get("license"),
                      extra={"rows": rows, "row_count": len(rows), "offset": offset}, raw=None)
    return {"identity": target, "records": [rec], "license": meta.get("license"),
            "next_offset": offset + len(rows) if len(rows) == min(limit, 50000) else None}
