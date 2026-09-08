"""BEA: U.S. national, regional and international economic accounts."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "bea"
SMOKE = {'capability': 'data', 'params': {'method': 'GETDATASETLIST'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data", "catalog",)
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


def catalog(client: Client, *, query: str | None = None, within: str | None = None,
            cursor=None, limit: int = 20) -> dict:
    """Identifier discovery (D-32) through BEA's own metadata methods: no `within` lists
    datasets; within=<dataset> lists its parameters; within=<dataset>/<parameter> lists
    that parameter's values with a PARTIAL research_data template to complete. BEA's
    HTTP-200 error envelopes are capability facts (D-32a finding 7), and value rows are
    read PER PARAMETER — a Year listing returns per-table year RANGES, never a table
    name masquerading as a year (finding 4)."""
    key = client.secret("bea")
    if not key:
        return {"entries": [], "capability_fact": "no BEA key configured"}
    base_q = {"UserID": key, "ResultFormat": "JSON"}
    dataset, _, parameter = (within or "").partition("/")
    offset = int(cursor or 0)

    def call(method, **extra):
        resp = client.get(SOURCE_ID, "catalog", BASE, params={**base_q, "method": method, **extra}, query=query)
        if not check(SOURCE_ID, resp, allow_404=False):
            return None, None
        j = resp.json or {}
        err = _error(j)
        if err:
            return None, f"BEA: {err}"
        return (j.get("BEAAPI") or {}).get("Results") or {}, None

    def rows_of(results, *keys):
        for k in keys:
            v = results.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                return [v]
        return []

    if not dataset:
        results, err = call("GETDATASETLIST")
        if results is None:
            return {"entries": [], **({"capability_fact": err} if err else {})}
        entries = [{"id": d.get("DatasetName"), "label": d.get("DatasetDescription"), "kind": "dataset",
                    "children": True, "within": d.get("DatasetName")}
                   for d in rows_of(results, "Dataset") if d.get("DatasetName")]
    elif not parameter:
        results, err = call("GetParameterList", DataSetName=dataset)
        if results is None:
            return {"entries": [], **({"capability_fact": err} if err else {})}
        entries = [{"id": p.get("ParameterName"), "label": p.get("ParameterDescription"), "kind": "parameter",
                    "children": True, "within": f"{dataset}/{p.get('ParameterName')}"}
                   for p in rows_of(results, "Parameter") if p.get("ParameterName")]
    else:
        results, err = call("GetParameterValues", DataSetName=dataset, ParameterName=parameter)
        if results is None:
            return {"entries": [], **({"capability_fact": err} if err else {})}
        entries = []
        for v in rows_of(results, "ParamValue"):
            range_keys = [k for k in v if k.startswith(("First", "Last"))]
            exact = next((v[k] for k in (parameter, parameter.capitalize(), parameter.upper(), "Key") if v.get(k)), None)
            if exact is not None and not range_keys:
                entries.append({"id": exact, "label": v.get("Desc") or v.get("Description") or exact, "kind": "value",
                                "data_request": {"tool": "research_data", "partial": True,
                                                 "arguments": {"source": SOURCE_ID,
                                                               "params": {"dataset": dataset, parameter.lower(): exact}},
                                                 "missing": "the dataset's other required parameters (browse them the same way)"}})
            elif range_keys and v.get("TableName"):
                spans = ", ".join(f"{k}={v[k]}" for k in sorted(range_keys) if v.get(k))
                entries.append({"id": v["TableName"], "label": f"{v['TableName']}: {spans}", "kind": "range",
                                "data_request": {"tool": "research_data", "partial": True,
                                                 "arguments": {"source": SOURCE_ID,
                                                               "params": {"dataset": dataset, "table": v["TableName"]}},
                                                 "missing": f"a {parameter.lower()} within the listed span (plus frequency)"}})
    if query:
        q = query.lower()
        entries = [e for e in entries if q in str(e.get("id", "")).lower() or q in str(e.get("label", "")).lower()]
    page = entries[offset:offset + limit]
    return {"entries": page, "next": str(offset + limit) if len(entries) > offset + limit else None}

