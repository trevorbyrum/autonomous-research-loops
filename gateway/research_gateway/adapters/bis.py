"""BIS Data Portal: cross-border banking and monetary statistics (SDMX 2.1 REST; XML only)."""
from __future__ import annotations

from ..core import sdmx
from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "bis"
SMOKE = {'capability': 'data', 'params': {'dataflow': 'WS_EER', 'key': 'M.N.B.US', 'start': '2026-01'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data", "catalog",)
STRUCTURE_BASE = "https://stats.bis.org/api/v2/structure"
AGENCY = "BIS"
BASE = "https://stats.bis.org/api/v2/data/dataflow/BIS"
ATTRIBUTION = "Bank for International Settlements"
LABEL_ATTRS = ("TITLE_TS", "TITLE")  # series attributes that label rather than key the series


# the agent-facing data contract (research_sources; validated before dispatch, D-31)
DATA_PARAMS = {
    "required": {"dataflow": {"doc": "BIS dataflow id, e.g. WS_EER", "type": "string"}},
    "optional": {"key": {"doc": "SDMX series key, dot-separated dimensions, e.g. M.N.B.US (default: all)", "type": "string"},
                 "start": {"doc": "startPeriod, e.g. 2020 or 2020-01", "type": "period"},
                 "end": {"doc": "endPeriod", "type": "period"}},
    "open": False,
    "example": {"dataflow": "WS_EER", "key": "M.N.B.US"},
    "notes": "dimension order is the dataflow's own; 'all' returns every series in the flow",
}

def data(client: Client, params: dict) -> dict:
    """params: dataflow (e.g. WS_EER), key (SDMX series key such as M.N.B.US; default 'all'), start, end."""
    flow = (params or {}).get("dataflow")
    if not flow:
        raise AdapterError("bis.data needs 'dataflow'")
    key = params.get("key") or "all"
    identity = f"series:bis:{flow}:{key}"
    resp = client.get(SOURCE_ID, "data", f"{BASE}/{flow}/1.0/{key}",
                      params={"startPeriod": params.get("start"), "endPeriod": params.get("end")},
                      headers={"Accept": "application/xml"}, identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    records = []
    ctx = sdmx.context_xml(resp.text)
    for s in sdmx.series_xml(resp.text):
        dims = {k: v for k, v in s["key"].items() if k not in LABEL_ATTRS}
        skey = ".".join(dims.values())
        records.append(make_record(identity=f"series:bis:{flow}:{skey}", kind="series", source_id=SOURCE_ID,
                                   title=s["key"].get("TITLE_TS") or f"{flow} {skey}", links=["https://data.bis.org/topics"],
                                   attribution=ATTRIBUTION, extra={"dimensions": dims, "observations": s["observations"]},
                                   raw={"series": s, "context": ctx}))
    return {"identity": identity, "records": records}


def catalog(client: Client, *, query: str | None = None, within: str | None = None,
            cursor=None, limit: int = 20) -> dict:
    """Identifier discovery (D-32): no `within` lists dataflows; within=<flow> returns its
    dimension ids IN KEY ORDER — what an agent needs to build the dotted SDMX key. Codes
    per dimension are a documented residual (codelist browsing is not yet exposed)."""
    if not within:
        resp = client.get(SOURCE_ID, "catalog", STRUCTURE_BASE + "/dataflow/" + AGENCY,
                          headers={"Accept": "application/xml"}, query=query)
        if not check(SOURCE_ID, resp, allow_html=True):
            return {"entries": []}
        q = (query or "").lower()
        flows = [f for f in sdmx.dataflows_xml(resp.text)
                 if not q or q in str(f["id"]).lower() or q in str(f["label"]).lower()]
        return {"entries": [{"id": f["id"], "label": f["label"], "kind": "dataflow",
                             "children": True, "within": f["id"]} for f in flows[:limit]],
                "next": None}
    resp = client.get(SOURCE_ID, "catalog", STRUCTURE_BASE + "/dataflow/" + AGENCY + "/" + within,
                      headers={"Accept": "application/xml"}, identity=f"series:{SOURCE_ID}:{within}")
    if not check(SOURCE_ID, resp, allow_html=True):
        return {"entries": []}
    flows = sdmx.dataflows_xml(resp.text)
    ref = flows[0]["structure_ref"] if flows and flows[0].get("structure_ref") else within
    ds = client.get(SOURCE_ID, "catalog", STRUCTURE_BASE + "/datastructure/" + AGENCY + "/" + ref,
                    headers={"Accept": "application/xml"}, identity=f"series:{SOURCE_ID}:{within}")
    dims = sdmx.dimensions_xml(ds.text) if ds.ok else []
    entry = {"id": within, "label": (flows[0]["label"] if flows else within), "kind": "dataflow",
             "dimensions_in_key_order": dims,
             "data_request": {"tool": "research_data", "partial": True,
                              "arguments": {"source": SOURCE_ID,
                                            "params": {"dataflow": within, "key": ".".join("?" * len(dims)) or "all"}},
                              "missing": "one code per dimension, dot-separated in the order above"}}
    return {"entries": [entry], "next": None,
            "notes": "codelists per dimension are not yet exposed; the source's own data portal documents them"}
