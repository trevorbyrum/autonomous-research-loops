"""BEA: U.S. national, regional and international economic accounts."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "bea"
SMOKE = {'capability': 'data', 'params': {'method': 'GETDATASETLIST'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data",)
BASE = "https://apps.bea.gov/api/data/"
ATTRIBUTION = "U.S. Bureau of Economic Analysis"


def _error(j: dict) -> str | None:
    api = j.get("BEAAPI") or {}
    err = (api.get("Results") or {}).get("Error") or api.get("Error")
    return err.get("APIErrorDescription") if isinstance(err, dict) else None


# the agent-facing data contract (research_sources; validated before dispatch, D-31).
# open=True: BEA methods take dataset-specific keys that pass through by design.
DATA_PARAMS = {
    "required": {},
    "optional": {"method": {"doc": "GetData (default) | GetParameterList | GetParameterValues | GETDATASETLIST", "type": "string"},
                 "dataset": {"doc": "BEA DataSetName, e.g. NIPA", "type": "string"},
                 "table": {"doc": "TableName, e.g. T10101", "type": "string"},
                 "frequency": {"doc": "A|Q|M", "type": "string"},
                 "year": {"doc": "year, list of years, or 'X' for all", "type": "string_or_int"},
                 "parameter": {"doc": "ParameterName for metadata methods", "type": "string"},
                 "geo": {"doc": "GeoFips", "type": "string_or_int"},
                 "line": {"doc": "LineCode", "type": "string_or_int"}},
    "open": True,
    "example": {"dataset": "NIPA", "table": "T10101", "frequency": "Q", "year": "2024"},
    "notes": "start with method=GETDATASETLIST then GetParameterList to discover a dataset's own keys; unknown keys pass through to BEA",
}

def data(client: Client, params: dict) -> dict:
    """params: method (GetData|GetParameterList|GetParameterValues|GETDATASETLIST), dataset, table, frequency, year, plus any BEA-specific keys."""
    p = dict(params or {})
    method = p.pop("method", "GetData")
    key = client.secret("bea")
    if not key:
        return {"identity": f"table:bea:{p.get('dataset')}:{p.get('table')}", "records": [], "capability_fact": "no BEA key configured"}
    query = {"UserID": key, "method": method, "ResultFormat": "JSON"}
    mapping = {"dataset": "DataSetName", "table": "TableName", "frequency": "Frequency", "year": "Year",
               "parameter": "ParameterName", "geo": "GeoFips", "line": "LineCode"}
    for k, v in p.items():
        if v is not None:
            query[mapping.get(k, k)] = v
    identity = f"table:bea:{p.get('dataset', method)}:{p.get('table', '')}".rstrip(":")
    resp = client.get(SOURCE_ID, "data", BASE, params=query, identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    j = resp.json or {}
    err = _error(j)
    if err:
        return {"identity": identity, "records": [], "capability_fact": f"BEA: {err}"}
    results = (j.get("BEAAPI") or {}).get("Results") or {}
    rows = results.get("Data") if isinstance(results.get("Data"), list) else (
        results.get("Dataset") or results.get("ParamValue") or results.get("Parameter") or [])
    notes = [n.get("NoteText") for n in results.get("Notes", []) if isinstance(n, dict) and n.get("NoteText")]
    rec = make_record(identity=identity, kind="series", source_id=SOURCE_ID,
                      title=(rows[0].get("TableName") or rows[0].get("LineDescription")) if rows and isinstance(rows[0], dict) else method,
                      links=["https://apps.bea.gov/iTable/"], attribution=ATTRIBUTION,
                      extra={"rows": rows, "row_count": len(rows), "notes": notes, "method": method,
                             "query": {k: v for k, v in query.items() if k != "UserID"}}, raw=j)
    return {"identity": identity, "records": [rec]}
