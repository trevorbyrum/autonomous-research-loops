"""Socrata (SODA): federated government open-data portals. Licence is per dataset."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from .base import AdapterError, Client, check

SOURCE_ID = "socrata"
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


def _vouched(client: Client, domain: str) -> None:
    """R-6: only portals the Socrata discovery catalog knows may be called; the check is a metered
    catalog query, remembered for the process. Raises AdapterError for anything else."""
    if domain in _KNOWN_DOMAINS:
        return
    resp = client.get(SOURCE_ID, "resolve", DISCOVERY, params={"domains": domain, "limit": 1, "only": "datasets"},
                      headers=_headers(client), identity=f"socrata:{domain}")
    if not check(SOURCE_ID, resp) or not ((resp.json or {}).get("resultSetSize") or 0):
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


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0, domain: str | None = None) -> dict:
    params = {"q": query, "only": "datasets", "limit": min(limit, 100), "offset": offset, "domains": domain}
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
    """Rows of a dataset through the SODA resource endpoint (JSON); nothing is persisted."""
    domain, did = _split(target)
    _vouched(client, domain)
    params = {"$limit": min(limit, 50000), "$offset": offset, "$where": where}
    resp = client.get(SOURCE_ID, "fetch", f"https://{domain}/resource/{did}.json", params=params, headers=_headers(client), identity=target)
    if not check(SOURCE_ID, resp):
        return {"identity": target, "records": []}
    rows = resp.json if isinstance(resp.json, list) else []
    rec = make_record(identity=f"{target}#rows", kind="file", source_id=SOURCE_ID, title=f"{did} rows {offset}-{offset + len(rows)}",
                      links=[f"https://{domain}/resource/{did}.json"], extra={"rows": rows, "row_count": len(rows), "offset": offset},
                      raw=None)
    return {"identity": target, "records": [rec], "next_offset": offset + len(rows) if len(rows) == min(limit, 50000) else None}
