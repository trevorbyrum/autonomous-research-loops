"""Socrata (SODA): federated government open-data portals. Licence is per dataset."""
from __future__ import annotations

import re

from ..core.canonical import make_record, year_from
from .base import AdapterError, Client, check

SOURCE_ID = "socrata"
SMOKE = {'capability': 'find', 'query': 'business licenses', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
DISCOVERY = "https://api.us.socrata.com/api/catalog/v1"


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
    listed = {((r.get("metadata") or {}).get("domain") or "").lower() for r in ((resp.json or {}).get("results") or [])
              if isinstance(r, dict)} if check(SOURCE_ID, resp) else set()
    if domain not in listed:
        raise AdapterError(f"{domain} is not a Socrata portal known to the discovery catalog (R-6)")
    _KNOWN_DOMAINS.add(domain)


def reset_known_domains() -> None:
    _KNOWN_DOMAINS.clear()


def _catalog_record(r: dict) -> dict:
    res, meta = r.get("resource") or {}, r.get("metadata") or {}
    domain, did = meta.get("domain"), res.get("id")
    return make_record(identity=f"socrata:{domain}:{did}", kind="dataset", source_id=SOURCE_ID, title=res.get("name"),
                       year=year_from(res.get("updatedAt")), venue=domain, identifiers={"dataset_id": did},
                       links=[r.get("permalink") or r.get("link") or f"https://{domain}/d/{did}"], license=meta.get("license"),
                       extra={"description": (res.get("description") or "")[:1000], "type": res.get("type"), "updated_at": res.get("updatedAt"),
                              "attribution": res.get("attribution")},
                       raw=r)


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0, portal: str | None = None) -> dict:
    """`portal` restricts to one Socrata-hosted portal hostname. (Deliberately NOT named `domain`:
    the router forwards the request's TOPIC domain to a parameter of that name — D-23.)"""
    params = {"q": query, "only": "datasets", "limit": min(limit, 100), "offset": offset, "domains": portal}
    resp = client.get(SOURCE_ID, "find", DISCOVERY, params=params, headers=_headers(client), query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": 0, "next_offset": None}
    j = resp.json or {}
    results, total = j.get("results") or [], j.get("resultSetSize") or 0
    _KNOWN_DOMAINS.update((r.get("metadata") or {}).get("domain", "").lower() for r in results if (r.get("metadata") or {}).get("domain"))
    return {"records": [_catalog_record(r) for r in results], "total": total,
            "next_offset": offset + len(results) if results and offset + len(results) < total else None}


def resolve(client: Client, identity: str) -> dict | None:
    domain, did = _split(identity)
    _vouched(client, domain)
    resp = client.get(SOURCE_ID, "resolve", f"https://{domain}/api/views/{did}.json", headers=_headers(client), identity=identity)
    if not check(SOURCE_ID, resp):
        return None
    v = resp.json or {}
    lic = v.get("license") or {}
    return make_record(identity=identity, kind="dataset", source_id=SOURCE_ID, title=v.get("name"), year=year_from(v.get("rowsUpdatedAt")),
                       venue=domain, identifiers={"dataset_id": did}, links=[f"https://{domain}/d/{did}"],
                       license=lic.get("name") if isinstance(lic, dict) else lic,
                       extra={"description": (v.get("description") or "")[:1000], "columns": [c.get("fieldName") for c in v.get("columns") or []],
                              "attribution": v.get("attribution"), "license_link": lic.get("termsLink") if isinstance(lic, dict) else None},
                       raw=v)


def fetch(client: Client, target: str, *, limit: int = 1000, offset: int = 0, where: str | None = None) -> dict:
    """Rows of a dataset through the SODA resource endpoint (JSON); nothing is persisted.
    The dataset's own licence is looked up first (it vouches the portal too) and travels with
    the rows, so per-item commercial gating can act on them (R-8, D-23)."""
    domain, did = _split(target)
    meta = resolve(client, target)   # vouches the portal and carries the dataset licence
    if meta is None:
        return {"identity": target, "records": [], "capability_fact": "dataset not found"}
    params = {"$limit": min(limit, 50000), "$offset": offset, "$where": where}
    resp = client.get(SOURCE_ID, "fetch", f"https://{domain}/resource/{did}.json", params=params, headers=_headers(client), identity=target)
    if not check(SOURCE_ID, resp):
        return {"identity": target, "records": []}
    rows = resp.json if isinstance(resp.json, list) else []
    rec = make_record(identity=f"{target}#rows", kind="file", source_id=SOURCE_ID, title=f"{did} rows {offset}-{offset + len(rows)}",
                      links=[f"https://{domain}/resource/{did}.json"], license=meta.get("license"),
                      extra={"rows": rows, "row_count": len(rows), "offset": offset}, raw=None)
    return {"identity": target, "records": [rec], "license": meta.get("license"),
            "next_offset": offset + len(rows) if len(rows) == min(limit, 50000) else None}
