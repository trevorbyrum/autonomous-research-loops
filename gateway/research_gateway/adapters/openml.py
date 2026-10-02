"""OpenML: machine-learning benchmark datasets (no key). Licence is per dataset."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record, year_from
from ..core.licenses import allow_listed
from .base import AdapterError, Client, check, decode, is_unreadable, members, quote

SOURCE_ID = "openml"
SMOKE = {'capability': 'resolve', 'identity': 'openml:61'}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("find", "resolve", "fetch")
BASE = "https://www.openml.org/api/v1/json"
HOSTS = ("https://www.openml.org/", "https://api.openml.org/", "https://data.openml.org/")

# What an answer must be. A listing's licence is OpenML's own spelling (`licence`) or the other (`license`): both declared, so both decoded before one is chosen.
# A dataset's file links are a file of their own each: `url` is built only if the dataset has a file id, and `parquet_url` only if the format is not Sparse_ARFF, so a link
# that is null, missing or empty is a file the dataset does not have; one that is there and is not text is one unreadable file (`isolated`: dropped and counted, never
# replaced by the other link when it is the one a download asked for).
LISTED = S.obj({"did": S.key(), "name": S.text(), "licence": S.text(), "license": S.text(), "version": S.any_(), "status": S.any_(), "format": S.any_(),
                "quality": S.own(S.obj({"name": S.text(), "value": S.any_()}))}, alts=(("licence", "license"),))
DESCRIBED = S.obj({"id": S.key(), "name": S.text(), "creator": S.oneof(S.text(), S.own(S.text())), "upload_date": S.text(), "url": S.text(), "parquet_url": S.text(),
                   "licence": S.text(), "version": S.any_(), "format": S.any_(), "description": S.text(), "default_target_attribute": S.any_(), "file_id": S.any_()})
LINKED = S.obj({"licence": S.text(), "url": S.isolated(S.text()), "parquet_url": S.isolated(S.text())})
FIND = S.obj({"data": S.required(S.obj({"dataset": S.required(S.members(LISTED))}))})
RESOLVE = S.obj({"data_set_description": S.required(DESCRIBED)})
FETCH = S.obj({"data_set_description": S.required(LINKED)})
ERROR = S.obj({"error.code": S.deep(("error", "code"), S.any_())})
SCHEMAS = {"find": FIND, "resolve": RESOLVE, "fetch": FETCH}


def _did(target: str) -> str:
    did = target.split(":", 1)[-1] if target.startswith("openml:") else target
    if not did.isdigit():
        raise AdapterError("openml target must be 'openml:<dataset_id>'")
    return did


def _list_record(d) -> dict:
    did = str(d["did"])
    quality = {n: q["value"] for q in d["quality"] if (n := q["name"])}
    return make_record(identity=f"openml:{did}", kind="dataset", source_id=SOURCE_ID, title=d["name"], venue="OpenML",
                       identifiers={"dataset_id": did}, links=[f"https://www.openml.org/d/{did}"],
                       license=d["licence"] or d["license"],   # captured whenever the listing carries it (D-25); OpenML's own spelling first
                       extra={"version": d["version"], "status": d["status"], "format": d["format"],
                              "instances": quality.get("NumberOfInstances"), "features": quality.get("NumberOfFeatures")},
                       raw=d.raw)


def _desc_record(d) -> dict:
    did = str(d["id"])
    creator = d["creator"]
    return make_record(identity=f"openml:{did}", kind="dataset", source_id=SOURCE_ID, title=d["name"],
                       authors=[creator] if isinstance(creator, str) else (creator or []),
                       year=year_from(d["upload_date"]), venue="OpenML", identifiers={"dataset_id": did},
                       links=[f"https://www.openml.org/d/{did}"] + [u for u in (d["url"], d["parquet_url"]) if u],
                       license=d["licence"],
                       extra={"version": d["version"], "format": d["format"], "description": (d["description"] or "")[:1000],
                              "default_target": d["default_target_attribute"], "file_id": d["file_id"], "url": d["url"],
                              "parquet_url": d["parquet_url"]},
                       raw=d.raw)


def find(client: Client, query: str, *, limit: int = 20, offset: int = 0) -> dict:
    """OpenML's public API filters by exact data_name only; free-text search is not documented."""
    url = f"{BASE}/data/list/data_name/{quote(query, safe='')}/limit/{min(limit, 100)}/offset/{offset}/status/active"
    resp = client.get(SOURCE_ID, "find", url, query=query)
    body = resp.json_or_none()   # an error answer that cannot be read is no "no results": it is an outage, below
    code = decode(SOURCE_ID, ERROR, body)["error.code"] if isinstance(body, dict) else None
    if resp.status == 412 and code is not None and str(code) == "372":
        # OpenML's list API answers "no results" — no match at this offset — as HTTP 412 with error code 372;
        # its own client ends a listing there: a successful empty page, not an outage (any other 412 still is one)
        return {"records": [], "total": 0, "next_offset": None, "exhausted": True}
    check(SOURCE_ID, resp, allow_404=False)   # a search endpoint's 404 is not "no results"
    items = decode(SOURCE_ID, FIND, resp.json)["data"]["dataset"]
    # openml-python, OpenML's own client, ends a listing on a batch shorter than the limit it asked
    # (docs/PROVIDER-PAGINATION.md); a full page continues at the next offset
    return {"records": members(SOURCE_ID, items, _list_record), "total": None,
            "next_offset": offset + len(items) if len(items) >= min(limit, 100) else None,
            "exhausted": len(items) < min(limit, 100)}


def _description(client: Client, did: str, schema):
    """The dataset's description as `schema` decodes it, None when OpenML has no such dataset."""
    resp = client.get(SOURCE_ID, "resolve", f"{BASE}/data/{did}", identity=f"openml:{did}")
    if not check(SOURCE_ID, resp):
        return None
    return decode(SOURCE_ID, schema, resp.json)["data_set_description"]


def resolve(client: Client, identity: str) -> dict | None:
    d = _description(client, _did(identity), RESOLVE)
    return _desc_record(d) if d is not None else None


def fetch(client: Client, target: str, *, download: bool = False, prefer: str = "parquet") -> dict:
    """The dataset's data file link(s); with download=True the preferred file's bytes (never persisted). Each link the description carries
    is a file of its own: one it leaves out (missing, null, empty) lists no file, and one that is there and is not text is one unreadable
    file — dropped and counted, and never replaced by the other link when it is the one a download asked for."""
    did = _did(target)
    identity = f"openml:{did}"
    d = _description(client, did, FETCH)
    if d is None:
        return {"identity": identity, "records": []}
    license_ = d["licence"]
    files = []
    for name in ("parquet_url", "url") if prefer == "parquet" else ("url", "parquet_url"):
        u = d[name]
        if is_unreadable(u):
            files.append(None)
        elif u:   # null, missing or empty: a file the dataset does not have
            files.append(make_record(identity=f"{identity}#{u.rsplit('/', 1)[-1]}", kind="file", source_id=SOURCE_ID, title=u.rsplit("/", 1)[-1],
                                     license=license_, links=[u], raw=None))
    if not download:
        return {"identity": identity, "records": files}
    if client.commercial and not allow_listed(license_):
        return {"identity": identity, "records": files,
                "capability_fact": f"download refused before fetching: licence {license_ or 'unknown'} is not usable commercially (R-8)"}
    if not files or files[0] is None or not files[0]["links"][0].startswith(HOSTS):
        why = "a data file link of the dataset cannot be read" if files and files[0] is None else "no OpenML-hosted data file to download"
        return {"identity": identity, "records": files, "capability_fact": why}
    resp = client.get(SOURCE_ID, "fetch", files[0]["links"][0], headers={"Accept": "*/*"}, identity=files[0]["identity"])
    if not check(SOURCE_ID, resp, allow_html=True):  # raw file download: an HTML document can be legitimate content here
        return {"identity": identity, "records": files}
    return {"identity": identity, "records": files, "content": resp.body,
            "content_type": resp.headers.get("content-type"), "license": license_}


def download_request(record: dict, target: str) -> dict | None:
    """The COMPLETE research_download call for one listed file (D-31a): openml downloads
    select by format preference, and the target stays the bare numeric dataset id."""
    title = str(record.get("title") or "")
    prefer = "parquet" if title.endswith((".pq", ".parquet")) else "arff"
    return {"target": f"openml:{_did(target)}", "params": {"prefer": prefer}}
