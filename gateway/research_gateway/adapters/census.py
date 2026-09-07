"""U.S. Census Bureau Data API: tables of variables by geography."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "census"
SMOKE = {'capability': 'data', 'params': {'dataset': '2022/acs/acs1', 'get': ['NAME'], 'for': 'state:37'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data",)
BASE = "https://api.census.gov/data"
ATTRIBUTION = "U.S. Census Bureau"


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
    j = resp.json
    if not isinstance(j, list) or not j:
        return {"identity": identity, "records": [], "capability_fact": f"Census returned no table ({resp.text[:120]!r})"}
    header, rows = j[0], [dict(zip(j[0], r)) for r in j[1:]]
    rec = make_record(identity=identity, kind="series", source_id=SOURCE_ID, title=f"{dataset}: {query['get']}",
                      links=[f"https://api.census.gov/data/{dataset.strip('/')}.html"], attribution=ATTRIBUTION,
                      extra={"columns": header, "rows": rows, "row_count": len(rows), "dataset": dataset,
                             "query": {k: v for k, v in query.items() if k != "key"}}, raw=j)
    return {"identity": identity, "records": [rec]}
