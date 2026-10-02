"""Kaggle datasets (HTTP basic auth: username + API token). Personal research use only."""
from __future__ import annotations

import base64

from ..core import schema as S
from ..core.canonical import make_record, year_from
from .base import AdapterError, Client, check, decode, members, quote

SOURCE_ID = "kaggle"
SMOKE = {'capability': 'find', 'query': 'housing prices', 'limit': 1}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "fetch")
BASE = "https://www.kaggle.com/api/v1"

# What an answer must be: a listing is a list of datasets; a dataset's files are `datasetFiles`. A file's size is `totalBytes`, else `size`, each a whole number
# (the captured SDK types totalBytes as int): both spellings are declared, so both are decoded before one is chosen.
DATASET = S.obj({"ref": S.key(), "ownerName": S.text(), "title": S.text(), "lastUpdated": S.text(), "url": S.text(), "licenseName": S.text(), "subtitle": S.any_(),
                 "totalBytes": S.any_(), "downloadCount": S.any_(), "usabilityRating": S.any_()})
FILE = S.obj({"name": S.text(), "totalBytes": S.whole(), "size": S.whole(), "creationDate": S.any_()}, alts=(("totalBytes", "size"),))
SCHEMAS = {"find": S.members(DATASET), "fetch": S.obj({"datasetFiles": S.required(S.members(FILE))})}


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


def _record(d) -> dict:
    ref, owner = str(d["ref"]), d["ownerName"]
    return make_record(identity=f"kaggle:{ref}", kind="dataset", source_id=SOURCE_ID, title=d["title"],
                       authors=[owner] if owner else [], year=year_from(d["lastUpdated"]),
                       venue="Kaggle", identifiers={"dataset_ref": ref}, links=[d["url"] or f"https://www.kaggle.com/datasets/{ref}"],
                       license=d["licenseName"],
                       extra={"subtitle": d["subtitle"], "total_bytes": d["totalBytes"], "last_updated": d["lastUpdated"],
                              "download_count": d["downloadCount"], "usability": d["usabilityRating"]},
                       raw=d.raw)


def _file(identity: str, ref: str, f) -> dict:
    name = f["name"]
    total_bytes, size = f["totalBytes"], f["size"]
    return make_record(identity=f"{identity}#{name}", kind="file", source_id=SOURCE_ID, title=name,
                       links=[f"{BASE}/datasets/download/{ref}/{quote(name or '', safe='')}"],
                       extra={"size": total_bytes if total_bytes is not None else size, "created": f["creationDate"]}, raw=f.raw)


def find(client: Client, query: str, *, limit: int = 20, page: int = 1) -> dict:
    hdrs = _headers(client)
    if not hdrs:
        return {"records": [], "total": None, "next_page": None, "capability_fact": "no Kaggle username/key configured"}
    resp = client.get(SOURCE_ID, "find", f"{BASE}/datasets/list", params={"search": query, "page": page}, headers=hdrs, query=query)
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    items = decode(SOURCE_ID, SCHEMAS["find"], resp)
    # Kaggle's own clients page this listing by number and document neither its page size, a last page nor a
    # total (docs/PROVIDER-PAGINATION.md): a non-empty page read whole continues at page + 1, and nothing here
    # ever ends the lane. A page cut to `limit` cannot continue: page + 1 would skip the rows cut here
    cut = len(items) > limit
    return {"records": members(SOURCE_ID, items.take(limit), _record), "total": None,
            "next_page": page + 1 if items and not cut else None, "exhausted": False}


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
        return {"identity": identity, "records": [], "content": resp.download(), "content_type": resp.headers.get("content-type")}
    resp = client.get(SOURCE_ID, "fetch", f"{BASE}/datasets/list/{ref}", headers=hdrs, identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    records = members(SOURCE_ID, decode(SOURCE_ID, SCHEMAS["fetch"], resp)["datasetFiles"], lambda f: _file(identity, ref, f))
    return {"identity": identity, "records": records}


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed file (D-31a)."""
    name = record.get("title")
    return {"target": target, "params": {"file_name": name}} if name else None
