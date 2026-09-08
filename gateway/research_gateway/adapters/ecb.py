"""ECB Data Portal: euro-area statistics (SDMX)."""
from __future__ import annotations

from ..core import sdmx
from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "ecb"
SMOKE = {'capability': 'data', 'params': {'dataflow': 'EXR', 'key': 'D.USD.EUR.SP00.A', 'start': '2026-08-01'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data", "catalog",)
STRUCTURE_BASE = "https://data-api.ecb.europa.eu/service"
STRUCTURE_PARAMS = {}   # BIS answers SDMX-JSON unless the XML format is named (D-32a finding 3)
AGENCY = "ECB"
BASE = "https://data-api.ecb.europa.eu/service/data"
ATTRIBUTION = "European Central Bank"


# the agent-facing data contract (research_sources; validated before dispatch, D-31)
DATA_PARAMS = {
    "required": {"dataflow": {"doc": "ECB dataflow id, e.g. EXR", "type": "string"},
                 "key": {"doc": "SDMX series key, e.g. D.USD.EUR.SP00.A", "type": "string"}},
    "optional": {"start": {"doc": "startPeriod, e.g. 2024-01-01", "type": "period"},
                 "end": {"doc": "endPeriod", "type": "period"}},
    "open": False,
    "example": {"dataflow": "EXR", "key": "D.USD.EUR.SP00.A", "start": "2024-01-01"},
    "notes": "dimension order is the dataflow's own (ECB EXR: FREQ.CURRENCY.CURRENCY_DENOM.EXR_TYPE.EXR_SUFFIX)",
}

def data(client: Client, params: dict) -> dict:
    """params: dataflow (e.g. EXR), key (e.g. D.USD.EUR.SP00.A), start, end."""
    flow, key = (params or {}).get("dataflow"), (params or {}).get("key")
    if not flow or not key:
        raise AdapterError("ecb.data needs 'dataflow' and 'key'")
    identity = f"series:ecb:{flow}:{key}"
    resp = client.get(SOURCE_ID, "data", f"{BASE}/{flow}/{key}",
                      params={"format": "jsondata", "startPeriod": params.get("start"), "endPeriod": params.get("end")},
                      identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    records = []
    ctx = sdmx.context(resp.json or {})
    for s in sdmx.series(resp.json or {}):
        skey = ".".join(str(v) for v in s["key"].values()) or key
        records.append(make_record(identity=f"series:ecb:{flow}:{skey}", kind="series", source_id=SOURCE_ID, title=f"{flow} {skey}",
                                   links=[f"https://data.ecb.europa.eu/data/datasets/{flow}"], attribution=ATTRIBUTION,
                                   extra={"dimensions": s["key"], "observations": s["observations"]},
                                   raw={"series": s, "context": ctx}))
    return {"identity": identity, "records": records}

def catalog(client: Client, *, query: str | None = None, within: str | None = None,
            cursor=None, limit: int = 20) -> dict:
    """Identifier discovery (D-32): no `within` lists dataflows; within=<flow> returns its
    dimension ids IN KEY ORDER — what an agent needs to build the dotted SDMX key. Codes
    per dimension are a documented residual (codelist browsing is not yet exposed).
    Every dependent answer is checked: an unparseable structure, an error envelope or a
    failed datastructure lookup is a capability fact, never a successful empty catalogue
    (D-32a finding 7)."""
    offset = int(cursor or 0)
    if not within:
        resp = client.get(SOURCE_ID, "catalog", STRUCTURE_BASE + "/dataflow/" + AGENCY,
                          params=STRUCTURE_PARAMS or None, headers={"Accept": "application/xml"}, query=query)
        if not check(SOURCE_ID, resp, allow_404=False):
            return {"entries": []}
        flows = sdmx.dataflows_xml(resp.text)
        if not flows:
            return {"entries": [], "capability_fact": "unparseable dataflow answer (not the expected SDMX XML)"}
        q = (query or "").lower()
        flows = [f for f in flows if not q or q in str(f["id"]).lower() or q in str(f["label"]).lower()]
        page = flows[offset:offset + limit]
        return {"entries": [{"id": f["id"], "label": f["label"], "kind": "dataflow",
                             "children": True, "within": f["id"]} for f in page],
                "next": str(offset + limit) if len(flows) > offset + limit else None}
    resp = client.get(SOURCE_ID, "catalog", STRUCTURE_BASE + "/dataflow/" + AGENCY + "/" + within,
                      params=STRUCTURE_PARAMS or None, headers={"Accept": "application/xml"},
                      identity=f"series:{SOURCE_ID}:{within}")
    if not check(SOURCE_ID, resp, allow_404=False):
        return {"entries": []}
    flows = sdmx.dataflows_xml(resp.text)
    if not flows:
        return {"entries": [], "capability_fact": f"dataflow {within!r}: unparseable structure answer"}
    ref = flows[0]["structure_ref"] or within
    ds = client.get(SOURCE_ID, "catalog", STRUCTURE_BASE + "/datastructure/" + AGENCY + "/" + ref,
                    params=STRUCTURE_PARAMS or None, headers={"Accept": "application/xml"},
                    identity=f"series:{SOURCE_ID}:{within}")
    if not check(SOURCE_ID, ds, allow_404=False):
        return {"entries": []}
    dims = sdmx.dimensions_xml(ds.text)
    if not dims:
        return {"entries": [], "capability_fact": f"datastructure {ref!r}: no dimensions parsed — refusing to "
                                                  "invent an empty series template"}
    entry = {"id": within, "label": flows[0]["label"], "kind": "dataflow",
             "dimensions_in_key_order": dims,
             "data_request": {"tool": "research_data", "partial": True,
                              "arguments": {"source": SOURCE_ID,
                                            "params": {"dataflow": within, "key": ".".join("?" * len(dims))}},
                              "missing": "one code per dimension, dot-separated in the order above"}}
    return {"entries": [entry], "next": None,
            "notes": "codelists per dimension are not yet exposed; the source's own data portal documents them"}
