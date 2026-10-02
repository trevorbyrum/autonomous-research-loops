"""U.S. Census Bureau Data API: tables of variables by geography."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record
from .base import AdapterError, Client, PayloadError, check, decode, identified

SOURCE_ID = "census"
SMOKE = {'capability': 'data', 'params': {'dataset': '2022/acs/acs1', 'get': ['NAME'], 'for': 'state:37'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data", "catalog",)
BASE = "https://api.census.gov/data"
ATTRIBUTION = "U.S. Census Bureau"


def _is_a_table(rows: list) -> None:
    if not rows:
        raise PayloadError("the answer is not a table (no header row)")
    if not all(isinstance(h, str) for h in rows[0]):
        raise PayloadError("a column name of the table is not what it should be: the table is unreadable, not shorter")


# What an answer must be. A table is ONE record: a header row of column names and rows that are lists, read whole — a malformed row makes it unreadable, not shorter.
# The dataset directory and a dataset's variables are catalogues answered whole, too: an entry that is not what it should be makes the catalogue unreadable, not
# shorter. A dataset with no vintage (timeseries/bds and 87 friends) is real: its path is its id (D-32a finding 6).
TABLE = S.own(S.own(S.any_()), rule=_is_a_table)
DATASETS = S.obj({"dataset": S.required(S.own(S.obj({"c_dataset": S.own(S.text()), "c_vintage": S.maybe_key(only_empty=True), "title": S.text()})))})
VARIABLES = S.obj({"variables": S.required(S.table(S.obj({"label": S.text(), "predicateOnly": S.flag()})))})
SCHEMAS = {"data": TABLE, "catalog:datasets": DATASETS, "catalog:variables": VARIABLES}


# the agent-facing data contract (research_sources; validated before dispatch, D-31).
# open=True: Census predicates (e.g. NAICS2017=72) pass through by design.
DATA_PARAMS = {
    "required": {"dataset": {"doc": "dataset path with vintage, e.g. 2022/acs/acs1", "type": "string"},
                 "get": {"doc": "variable list or comma string, e.g. NAME,B01001_001E", "type": "string_or_list"}},
    "optional": {"for": {"doc": "geography, e.g. state:* or county:037", "type": "string"},
                 "in": {"doc": "containing geography, e.g. state:06", "type": "string"}},
    "open": True,
    "example": {"dataset": "2022/acs/acs1", "get": "NAME,B01001_001E", "for": "state:*"},
    "notes": "additional keys are passed through as Census predicates",
}

def data(client: Client, params: dict) -> dict:
    """params: dataset (e.g. '2022/acs/acs1'), get (list or comma string), for (geography), in (optional), plus predicates."""
    p = dict(params or {})
    dataset, get = p.pop("dataset", None), p.pop("get", None)
    if not dataset or not get:
        raise AdapterError("census.data needs 'dataset' and 'get'")
    key = client.secret("census")
    if not key:
        # keyless Census is 500/day per IP; the enabled policy is the keyed no-cap tier (D-23)
        return {"identity": f"table:census:{dataset}", "records": [],
                "capability_fact": "no Census key configured; the keyless 500/day tier is not enabled"}
    query = {"get": ",".join(get) if isinstance(get, (list, tuple)) else get, "key": key}
    for k in ("for", "in"):
        if p.get(k):
            query[k] = p.pop(k)
    query.update({k: v for k, v in p.items() if v is not None})
    identity = f"table:census:{dataset}:{query['get']}"
    resp = client.get(SOURCE_ID, "data", f"{BASE}/{dataset.strip('/')}", params=query, identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    if resp.status == 204:   # the Census API's answer to a query no data matches: successful and empty
        return {"identity": identity, "records": []}
    j = decode(SOURCE_ID, TABLE, resp.json)   # the rows of ONE table record: read whole, a malformed row makes it unreadable
    header, rows = j[0], [dict(zip(j[0], r)) for r in j[1:]]
    rec = make_record(identity=identity, kind="series", source_id=SOURCE_ID, title=f"{dataset}: {query['get']}",
                      links=[f"https://api.census.gov/data/{dataset.strip('/')}.html"], attribution=ATTRIBUTION,
                      extra={"columns": header, "rows": rows, "row_count": len(rows), "dataset": dataset,
                             "query": {k: v for k, v in query.items() if k != "key"}}, raw=j)
    return {"identity": identity, "records": [rec]}


def catalog(client: Client, *, query: str | None = None, within: str | None = None,
            cursor=None, limit: int = 20) -> dict:
    """Identifier discovery (D-32): no `within` searches the dataset directory
    (api.census.gov/data.json, filtered by query); within=<dataset> lists its variables
    (filtered by query) with a PARTIAL research_data template — pick a geography to
    complete it."""
    offset = int(cursor or 0)
    if not within:
        resp = client.get(SOURCE_ID, "catalog", "https://api.census.gov/data.json", query=query)
        if not check(SOURCE_ID, resp, allow_404=False):
            return {"entries": []}
        q = (query or "").lower()
        entries, rows, named = [], decode(SOURCE_ID, DATASETS, resp.json)["dataset"], []
        for d in rows:
            path = "/".join(part or "" for part in d["c_dataset"])
            vintage = d["c_vintage"]
            # unvintaged datasets (timeseries/bds and 87 friends) are real: their path IS
            # the dataset id (D-32a finding 6)
            ds = (f"{vintage}/{path}" if vintage else path) if path else None
            title = d["title"] or ""
            if ds:
                named.append(ds)
            if not ds or (q and q not in title.lower() and q not in ds.lower()):
                continue
            entries.append({"id": ds, "label": title, "kind": "dataset", "children": True, "within": ds})
        identified(SOURCE_ID, rows, named)
        page = entries[offset:offset + limit]
        return {"entries": page, "next": str(offset + limit) if len(entries) > offset + limit else None}
    resp = client.get(SOURCE_ID, "catalog", f"https://api.census.gov/data/{within.strip('/')}/variables.json",
                      identity=f"table:census:{within}", query=query)
    if not check(SOURCE_ID, resp, allow_404=False):
        return {"entries": []}
    q = (query or "").lower()
    entries = []
    for name, meta in decode(SOURCE_ID, VARIABLES, resp.json)["variables"].items():
        label = meta["label"] or ""   # a label that is not text makes the catalogue unreadable, not a variable without one
        if q and q not in name.lower() and q not in label.lower():
            continue
        if meta["predicateOnly"]:
            # a predicate is a FILTER, never a selectable column: putting it in `get`
            # produces an HTTP 400 (D-32a finding 5)
            entries.append({"id": name, "label": label, "kind": "predicate",
                            "usage": f'filter with "{name}": <value> (or the for/in geography keys) — never in `get`'})
            continue
        entries.append({"id": name, "label": label, "kind": "variable",
                        "data_request": {"tool": "research_data", "partial": True,
                                         "arguments": {"source": SOURCE_ID,
                                                       "params": {"dataset": within, "get": f"NAME,{name}"}},
                                         "missing": "a geography, e.g. \"for\": \"state:*\""}})
    page = sorted(entries, key=lambda e: e["id"])[offset:offset + limit]
    return {"entries": page, "next": str(offset + limit) if len(entries) > offset + limit else None}
