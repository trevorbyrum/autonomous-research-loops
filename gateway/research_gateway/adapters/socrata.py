"""Socrata (SODA): federated government open-data portals. Licence is per dataset."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.licenses import allow_listed
from .base import AdapterError, Client, PayloadError, Rec, check, decode, members, total

SOURCE_ID = "socrata"
SMOKE = {'capability': 'find', 'query': 'business licenses', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
DISCOVERY = "https://api.us.socrata.com/api/catalog/v1"
SEARCH_WINDOW = 10_000   # Socrata refuses a search whose offset + limit exceeds 10,000 (docs/PROVIDER-PAGINATION.md)

# What an answer must be. A catalogue hit links to its dataset by its `permalink`, else its `link`: both declared, so both decoded before one is chosen. A portal is
# vouched for only by a catalogue member that names it, so a member that cannot be read vouches for nothing (fail closed, R-6). A view's licence is an object that
# names it or the name itself; its timestamp is epoch seconds.
HIT = S.obj({"resource": S.obj({"id": S.key(), "name": S.text(), "updatedAt": S.text(), "description": S.text(), "type": S.any_(), "attribution": S.any_()}),
             "metadata": S.obj({"domain": S.key(), "license": S.text()}), "permalink": S.text(), "link": S.text()}, alts=(("permalink", "link"),))
SEARCH = S.obj({"results": S.required(S.members(HIT)), "resultSetSize": S.soft(S.whole())})
VOUCH = S.obj({"results": S.required(S.members(S.obj({"metadata": S.obj({"domain": S.text()})})))})
VIEW = S.obj({"id": S.any_(), "name": S.text(), "rowsUpdatedAt": S.whole(), "description": S.text(), "columns": S.own(S.obj({"fieldName": S.text()})),
              "license": S.oneof(S.obj({"name": S.text(), "termsLink": S.any_()}), S.text()), "attribution": S.any_()})
ROWS = S.own(S.any_())
SCHEMAS = {"find": SEARCH, "vouch": VOUCH, "resolve": VIEW, "fetch": ROWS}


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
    vouched = {d for d in decode(SOURCE_ID, VOUCH, resp.json)["results"].each(lambda r: (r["metadata"]["domain"] or "").lower())
               if d is not None} if check(SOURCE_ID, resp) else set()
    if domain not in vouched:
        raise AdapterError(f"{domain} is not a Socrata portal known to the discovery catalog (R-6)")
    _KNOWN_DOMAINS.add(domain)


def reset_known_domains() -> None:
    _KNOWN_DOMAINS.clear()


def _catalog_record(r) -> dict:
    res, meta = r["resource"], r["metadata"]
    domain, did = meta["domain"], str(res["id"])
    return make_record(identity=f"socrata:{domain}:{did}", kind="dataset", source_id=SOURCE_ID, title=res["name"],
                       year=year_from(res["updatedAt"]), venue=str(domain), identifiers={"dataset_id": did},
                       links=[r["permalink"] or r["link"] or f"https://{domain}/d/{did}"], license=meta["license"],
                       extra={"description": (res["description"] or "")[:1000], "type": res["type"], "updated_at": res["updatedAt"],
                              "attribution": res["attribution"]},
                       raw=r.raw)


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0, portal: str | None = None) -> dict:
    """`portal` restricts to one Socrata-hosted portal hostname. (Deliberately NOT named `domain`:
    the router forwards the request's TOPIC domain to a parameter of that name — D-23.)"""
    size = min(limit, 100)
    params = {"q": query, "only": "datasets", "limit": size, "offset": offset, "domains": portal}
    resp = client.get(SOURCE_ID, "find", DISCOVERY, params=params, headers=_headers(client), query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    j = decode(SOURCE_ID, SEARCH, resp.json)
    results = j["results"]
    count = total(j["resultSetSize"], offset + len(results))
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
    the view states none (the schema made it a whole number or nothing)."""
    if value is None:
        return None
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
    v = decode(SOURCE_ID, VIEW, resp.json)
    if not v["id"]:
        raise PayloadError(f"{SOURCE_ID}: the view answer carries no id")
    lic = v["license"]
    return make_record(identity=identity, kind="dataset", source_id=SOURCE_ID, title=v["name"], year=_epoch_year(v["rowsUpdatedAt"]),
                       venue=domain, identifiers={"dataset_id": did}, links=[f"https://{domain}/d/{did}"],
                       license=lic["name"] if isinstance(lic, Rec) else lic,
                       extra={"description": (v["description"] or "")[:1000],
                              "columns": [c["fieldName"] for c in v["columns"]],
                              "attribution": v["attribution"], "license_link": lic["termsLink"] if isinstance(lic, Rec) else None},
                       raw=v.raw)


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
    rows = decode(SOURCE_ID, ROWS, resp.json)
    rec = make_record(identity=f"{target}#rows", kind="file", source_id=SOURCE_ID, title=f"{did} rows {offset}-{offset + len(rows)}",
                      links=[f"https://{domain}/resource/{did}.json"], license=meta.get("license"),
                      extra={"rows": rows, "row_count": len(rows), "offset": offset}, raw=None)
    return {"identity": target, "records": [rec], "license": meta.get("license"),
            "next_offset": offset + len(rows) if len(rows) == min(limit, 50000) else None}
