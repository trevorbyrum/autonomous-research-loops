"""BIS Data Portal: cross-border banking and monetary statistics (SDMX 2.1 REST; XML only)."""
from __future__ import annotations

from ..core import sdmx
from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "bis"
SMOKE = {'capability': 'data', 'params': {'dataflow': 'WS_EER', 'key': 'M.N.B.US', 'start': '2026-01'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data",)
BASE = "https://stats.bis.org/api/v2/data/dataflow/BIS"
ATTRIBUTION = "Bank for International Settlements"
LABEL_ATTRS = ("TITLE_TS", "TITLE")  # series attributes that label rather than key the series


# the agent-facing data contract (research_sources; validated before dispatch, D-31)
DATA_PARAMS = {
    "required": {"dataflow": "BIS dataflow id, e.g. WS_EER"},
    "optional": {"key": "SDMX series key, dot-separated dimensions, e.g. M.N.B.US (default: all)",
                 "start": "startPeriod", "end": "endPeriod"},
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
