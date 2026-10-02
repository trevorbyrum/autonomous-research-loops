"""BEA: U.S. national, regional and international economic accounts."""
from __future__ import annotations

from ..core import schema as S
from ..core.canonical import make_record
from .base import AdapterError, Client, PayloadError, check, decode, identified

SOURCE_ID = "bea"
SMOKE = {'capability': 'data', 'params': {'method': 'GETDATASETLIST'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data", "catalog",)
BASE = "https://apps.bea.gov/api/data/"
ATTRIBUTION = "U.S. Bureau of Economic Analysis"

# What an answer must be. BEA states an error inside an HTTP-200 answer, beside the results or in the envelope: both places are declared, so both are decoded before
# one is chosen, and an answer that states an error needs nothing else (it has no results). Any other answer must have its results, and the rows the operation reads.
# A list of rows is a list, or the one row as a bare object (BEA's habit for a list of one); `{}` is no row. A table is ONE record, kept whole: a row that is not an
# object makes the answer unreadable, not shorter. The listing keys are alternatives: the first the answer carries is the listing, and every one it carries is decoded.
ERROR = S.obj({"APIErrorDescription": S.text()})
NOTES = S.own(S.obj({"NoteText": S.text()}))
TABLE_ROW = S.obj({"TableName": S.text(), "LineDescription": S.text()})
LISTING_KEYS = ("Dataset", "ParamValue", "Parameter")


def _error(api) -> str | None:
    """The error BEA reports inside a 200 answer, if it reports one: the one beside the results, else the envelope's."""
    results = api["Results"]
    beside = results["Error"] if results is not None else None
    return (beside if beside is not None and not beside.empty else api["Error"])["APIErrorDescription"]


def _stated(*needs: str):
    """The rule of an answer: it states an error, or it has its results and, in them, `needs`."""
    def rule(root) -> None:
        api = root["BEAAPI"]
        if _error(api):
            return
        results = api["Results"]
        if results is None:
            raise PayloadError("the answer has no BEAAPI.Results")
        missing = [n for n in needs if results[n] is None]
        if missing:
            raise PayloadError(f"the answer has no {', '.join(missing)}: a listing of nothing is not a catalogue")
    return rule


def _answer(results: dict, rule) -> S.Spec:
    return S.obj({"BEAAPI": S.obj({"Results": S.maybe(S.obj({**results, "Error": ERROR})), "Error": ERROR})}, rule=rule)


def _rows(row: S.Spec) -> S.Spec:
    return S.maybe(S.own(row, bare=True))


def values_schema(parameter: str) -> S.Spec:
    """A parameter's values: each row carries the value under the parameter's own spelling (or `Key`), with a description; or, for a parameter that is a span (Year),
    the table and the first/last of it. Every spelling the row carries is decoded before the first is chosen."""
    spellings = {name: S.maybe_key(only_empty=True) for name in (parameter, parameter.capitalize(), parameter.upper(), "Key")}
    return _answer({"ParamValue": _rows(S.obj({"Desc": S.text(), "Description": S.text(), "TableName": S.text(), **spellings, "span": S.matching(("First", "Last"), S.maybe_key())}))},
                   _stated("ParamValue"))


def _table_name(v) -> str | None:
    name = v["TableName"]
    if name is not None and not isinstance(name, str):
        raise PayloadError(f"{SOURCE_ID}: a table name that is {type(name).__name__}, not text")
    return name or None


DATA_GET = _answer({"Data": S.maybe(S.own(TABLE_ROW)), "Notes": NOTES}, _stated("Data"))
DATA_LIST = _answer({**{k: _rows(TABLE_ROW) for k in LISTING_KEYS}, "Notes": NOTES}, _stated())   # a listing is not required here: BEA may name none
# A catalogue's names are what a caller selects by and what its next request carries (`within`, a request's DataSetName/ParameterName): a name is text, a number, or nothing (a
# row with none is skipped), and a `true`, a list or an object is a name that cannot be read: the catalogue is unreadable, never one with that for an identifier. A description and a
# span's first/last are shown as labels, so they are kinds too (2b-repair-13a, R12-1).
CATALOG_DATASETS = _answer({"Dataset": _rows(S.obj({"DatasetName": S.maybe_key(), "DatasetDescription": S.text()}))}, _stated("Dataset"))
CATALOG_PARAMETERS = _answer({"Parameter": _rows(S.obj({"ParameterName": S.maybe_key(), "ParameterDescription": S.text()}))}, _stated("Parameter"))
SCHEMAS = {"data:getdata": DATA_GET, "data:list": DATA_LIST, "catalog:datasets": CATALOG_DATASETS, "catalog:parameters": CATALOG_PARAMETERS,
           "catalog:values": values_schema("Frequency")}


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
    j = decode(SOURCE_ID, DATA_GET if method.lower() == "getdata" else DATA_LIST, resp)
    err = _error(j["BEAAPI"])
    if err:
        return {"identity": identity, "records": [], "capability_fact": f"BEA: {err}"}
    results = j["BEAAPI"]["Results"]   # the rows of ONE table record, kept whole
    # GetData answers carry Data; a GetData answer without it is unreadable, never an empty table
    parsed = results["Data"] if method.lower() == "getdata" else next((results[k] for k in LISTING_KEYS if results[k] is not None), [])
    rows = [r.raw for r in parsed]
    notes = [t for t in (n["NoteText"] for n in results["Notes"]) if t]
    rec = make_record(identity=identity, kind="series", source_id=SOURCE_ID,
                      title=(parsed[0]["TableName"] or parsed[0]["LineDescription"]) if parsed else method,
                      links=["https://apps.bea.gov/iTable/"], attribution=ATTRIBUTION,
                      extra={"rows": rows, "row_count": len(rows), "notes": notes, "method": method,
                             "query": {k: v for k, v in query.items() if k != "UserID"}}, raw=j.raw)
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

    def call(method, schema, **extra):
        resp = client.get(SOURCE_ID, "catalog", BASE, params={**base_q, "method": method, **extra}, query=query)
        if not check(SOURCE_ID, resp, allow_404=False):
            return None, None
        j = decode(SOURCE_ID, schema, resp)
        err = _error(j["BEAAPI"])
        if err:
            return None, f"BEA: {err}"
        return j["BEAAPI"]["Results"], None   # a catalogue: its entries are read whole

    if not dataset:
        results, err = call("GETDATASETLIST", CATALOG_DATASETS)
        if results is None:
            return {"entries": [], **({"capability_fact": err} if err else {})}
        rows = results["Dataset"]
        entries = identified(SOURCE_ID, rows, [{"id": d["DatasetName"], "label": d["DatasetDescription"], "kind": "dataset",
                                                "children": True, "within": d["DatasetName"]}
                                               for d in rows if d["DatasetName"]])
    elif not parameter:
        results, err = call("GetParameterList", CATALOG_PARAMETERS, DataSetName=dataset)
        if results is None:
            return {"entries": [], **({"capability_fact": err} if err else {})}
        rows = results["Parameter"]
        entries = identified(SOURCE_ID, rows, [{"id": p["ParameterName"], "label": p["ParameterDescription"], "kind": "parameter",
                                                "children": True, "within": f"{dataset}/{p['ParameterName']}"}
                                               for p in rows if p["ParameterName"]])
    else:
        results, err = call("GetParameterValues", values_schema(parameter), DataSetName=dataset, ParameterName=parameter)
        if results is None:
            return {"entries": [], **({"capability_fact": err} if err else {})}
        entries, rows = [], results["ParamValue"]
        for v in rows:
            range_keys = v["span"]
            spellings = [str(v[k]) for k in (parameter, parameter.capitalize(), parameter.upper(), "Key") if v[k] not in (None, "")]   # every spelling the row carries was read
            exact = spellings[0] if spellings else None
            if exact is not None and not range_keys:
                entries.append({"id": exact, "label": v["Desc"] or v["Description"] or exact, "kind": "value",
                                "data_request": {"tool": "research_data", "partial": True,
                                                 "arguments": {"source": SOURCE_ID,
                                                               "params": {"dataset": dataset, parameter.lower(): exact}},
                                                 "missing": "the dataset's other required parameters (browse them the same way)"}})
            elif range_keys and _table_name(v):
                table = _table_name(v)
                spans = ", ".join(f"{k}={range_keys[k]}" for k in sorted(range_keys) if range_keys[k])
                entries.append({"id": table, "label": f"{table}: {spans}", "kind": "range",
                                "data_request": {"tool": "research_data", "partial": True,
                                                 "arguments": {"source": SOURCE_ID,
                                                               "params": {"dataset": dataset, "table": table}},
                                                 "missing": f"a {parameter.lower()} within the listed span (plus frequency)"}})
    identified(SOURCE_ID, rows, entries)
    if query:
        q = query.lower()
        entries = [e for e in entries if q in str(e.get("id", "")).lower() or q in str(e.get("label", "")).lower()]
    page = entries[offset:offset + limit]
    return {"entries": page, "next": str(offset + limit) if len(entries) > offset + limit else None}

