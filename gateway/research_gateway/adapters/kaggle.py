"""Kaggle datasets (HTTP basic auth: username + API token). Personal research use only."""
from __future__ import annotations

import base64

from ..core.canonical import make_record, year_from
from .base import AdapterError, Client, check, quote

SOURCE_ID = "kaggle"
SMOKE = {'capability': 'find', 'query': 'housing prices', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "fetch")
BASE = "https://www.kaggle.com/api/v1"


def _headers(client: Client) -> dict | None:
    user, key = client.secret("kaggle", "username"), client.secret("kaggle", "key")
    if not user or not key:
        return None
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{key}".encode()).decode()}


def _ref(target: str) -> str:
    ref = target.split(":", 1)[-1] if target.startswith("kaggle:") else target
    if ref.count("/") != 1:
        raise AdapterError("kaggle target must be 'kaggle:<owner>/<dataset>'")
    return ref


def _record(d: dict) -> dict:
    ref = d.get("ref")
    return make_record(identity=f"kaggle:{ref}", kind="dataset", source_id=SOURCE_ID, title=d.get("title"),
                       authors=[d.get("ownerName")] if d.get("ownerName") else [], year=year_from(d.get("lastUpdated")),
                       venue="Kaggle", identifiers={"dataset_ref": ref}, links=[d.get("url") or f"https://www.kaggle.com/datasets/{ref}"],
                       license=d.get("licenseName"),
                       extra={"subtitle": d.get("subtitle"), "total_bytes": d.get("totalBytes"), "last_updated": d.get("lastUpdated"),
                              "download_count": d.get("downloadCount"), "usability": d.get("usabilityRating")},
                       raw=d)


def find(client: Client, query: str, *, limit: int = 20, page: int = 1) -> dict:
    hdrs = _headers(client)
    if not hdrs:
        return {"records": [], "total": None, "next_page": None, "capability_fact": "no Kaggle username/key configured"}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/datasets/list", params={"search": query, "page": page}, headers=hdrs, query=query)
    if not check(SOURCE_ID, resp):
        return {"records": [], "total": None, "next_page": None}
    items = resp.json if isinstance(resp.json, list) else []
    return {"records": [_record(d) for d in items[:limit]], "total": None, "next_page": page + 1 if len(items) >= 20 else None}


def fetch(client: Client, target: str, *, file_name: str | None = None, download: bool = False) -> dict:
    """List a dataset's files; with download=True return one file's bytes (or the zip when file_name is None)."""
    ref = _ref(target)
    identity = f"kaggle:{ref}"
    hdrs = _headers(client)
    if not hdrs:
        return {"identity": identity, "records": [], "capability_fact": "no Kaggle username/key configured"}
    if download:
        url = f"{BASE}/datasets/download/{ref}" + (f"/{quote(file_name, safe='')}" if file_name else "")
        resp = client.get(SOURCE_ID, "fetch", url, headers={**hdrs, "Accept": "*/*"}, identity=identity)
        if not check(SOURCE_ID, resp, allow_html=True):  # raw file download: an HTML document can be legitimate content here
            return {"identity": identity, "records": []}
        return {"identity": identity, "records": [], "content": resp.body, "content_type": resp.headers.get("content-type")}
    resp = client.get(SOURCE_ID, "fetch", f"{BASE}/datasets/list/{ref}", headers=hdrs, identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    files = (resp.json or {}).get("datasetFiles") or []
    records = [make_record(identity=f"{identity}#{f.get('name')}", kind="file", source_id=SOURCE_ID, title=f.get("name"),
                           links=[f"{BASE}/datasets/download/{ref}/{quote(f.get('name') or '', safe='')}"],
                           extra={"size": f.get("totalBytes") or f.get("size"), "created": f.get("creationDate")},
                           raw=f) for f in files]
    return {"identity": identity, "records": records}


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed file (D-31a)."""
    name = record.get("title")
    return {"target": target, "params": {"file_name": name}} if name else None
