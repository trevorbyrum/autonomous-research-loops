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
    for s in sdmx.series_xml(resp.text):
        dims = {k: v for k, v in s["key"].items() if k not in LABEL_ATTRS}
        skey = ".".join(dims.values())
        records.append(make_record(identity=f"series:bis:{flow}:{skey}", kind="series", source_id=SOURCE_ID,
                                   title=s["key"].get("TITLE_TS") or f"{flow} {skey}", links=["https://data.bis.org/topics"],
                                   attribution=ATTRIBUTION, extra={"dimensions": dims, "observations": s["observations"]},
                                   raw=s))
    return {"identity": identity, "records": records}
