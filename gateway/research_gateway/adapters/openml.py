"""OpenML: machine-learning benchmark datasets (no key). Licence is per dataset."""
from __future__ import annotations

from ..core.canonical import make_record, year_from
from .base import AdapterError, Client, check, quote

SOURCE_ID = "openml"
CAPABILITIES = ("find", "resolve", "fetch")
BASE = "https://www.openml.org/api/v1/json"
HOSTS = ("https://www.openml.org/", "https://api.openml.org/", "https://data.openml.org/")


def _did(target: str) -> str:
    did = target.split(":", 1)[-1] if target.startswith("openml:") else target
    if not did.isdigit():
        raise AdapterError("openml target must be 'openml:<dataset_id>'")
    return did


def _list_record(d: dict) -> dict:
    did = str(d.get("did"))
    quality = {q.get("name"): q.get("value") for q in d.get("quality") or [] if q.get("name")}
    return make_record(identity=f"openml:{did}", kind="dataset", source_id=SOURCE_ID, title=d.get("name"), venue="OpenML",
                       identifiers={"dataset_id": did}, links=[f"https://www.openml.org/d/{did}"],
                       extra={"version": d.get("version"), "status": d.get("status"), "format": d.get("format"),
                              "instances": quality.get("NumberOfInstances"), "features": quality.get("NumberOfFeatures")},
                       raw=d)


def _desc_record(d: dict) -> dict:
    did = str(d.get("id"))
    return make_record(identity=f"openml:{did}", kind="dataset", source_id=SOURCE_ID, title=d.get("name"),
                       authors=[d.get("creator")] if isinstance(d.get("creator"), str) else list(d.get("creator") or []),
                       year=year_from(d.get("upload_date")), venue="OpenML", identifiers={"dataset_id": did},
                       links=[f"https://www.openml.org/d/{did}"] + [u for u in (d.get("url"), d.get("parquet_url")) if u],
                       license=d.get("licence"),
                       extra={"version": d.get("version"), "format": d.get("format"), "description": (d.get("description") or "")[:1000],
                              "default_target": d.get("default_target_attribute"), "file_id": d.get("file_id"), "url": d.get("url"),
                              "parquet_url": d.get("parquet_url")},
                       raw=d)


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0) -> dict:
    """OpenML's public API filters by exact data_name only; free-text search is not documented."""
    url = f"{BASE}/data/list/data_name/{quote(query, safe='')}/limit/{min(limit, 100)}/offset/{offset}/status/active"
    resp = client.get(SOURCE_ID, "find", url, query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": None, "next_offset": None}
    items = ((resp.json or {}).get("data") or {}).get("dataset") or []
    return {"records": [_list_record(d) for d in items], "total": None,
            "next_offset": offset + len(items) if len(items) >= min(limit, 100) else None}


def resolve(client: Client, identity: str) -> dict | None:
    did = _did(identity)
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/data/{did}", identity=f"openml:{did}")
    if not check(SOURCE_ID, resp):
        return None
    d = (resp.json or {}).get("data_set_description")
    return _desc_record(d) if d else None


def fetch(client: Client, target: str, *, download: bool = False, prefer: str = "parquet") -> dict:
    """The dataset's data file link(s); with download=True the preferred file's bytes (never persisted)."""
    rec = resolve(client, target)
    identity = f"openml:{_did(target)}"
    if rec is None:
        return {"identity": identity, "records": []}
    urls = [u for u in ((rec["parquet_url"], rec["url"]) if prefer == "parquet" else (rec["url"], rec["parquet_url"])) if u]
    files = [make_record(identity=f"{identity}#{u.rsplit('/', 1)[-1]}", kind="file", source_id=SOURCE_ID, title=u.rsplit("/", 1)[-1],
                         license=rec["license"], links=[u], raw=None) for u in urls]
    if not download:
        return {"identity": identity, "records": files}
    if not urls or not urls[0].startswith(HOSTS):
        return {"identity": identity, "records": files, "capability_fact": "no OpenML-hosted data file to download"}
    resp = client.get(SOURCE_ID, "fetch", urls[0], headers={"Accept": "*/*"}, identity=files[0]["identity"])
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": files}
    return {"identity": identity, "records": files, "content": resp.body, "content_type": resp.headers.get("content-type")}
