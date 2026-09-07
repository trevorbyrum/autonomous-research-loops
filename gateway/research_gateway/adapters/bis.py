"""BIS Data Portal: cross-border banking and monetary statistics (SDMX)."""
from __future__ import annotations

from ..core import sdmx
from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "bis"
CAPABILITIES = ("data",)
BASE = "https://stats.bis.org/api/v2/data/dataflow/BIS"
ATTRIBUTION = "Bank for International Settlements"


def data(client: Client, params: dict) -> dict:
    """params: dataflow (e.g. WS_CBS_PUB), key (SDMX series key, default 'all'), start, end."""
    flow = (params or {}).get("dataflow")
    if not flow:
        raise AdapterError("bis.data needs 'dataflow'")
    key = params.get("key") or "all"
    identity = f"series:bis:{flow}:{key}"
    resp = client.get(SOURCE_ID, "data", f"{BASE}/{flow}/1.0/{key}",
                      params={"format": "json", "startPeriod": params.get("start"), "endPeriod": params.get("end")},
                      identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    records = []
    for s in sdmx.series(resp.json or {}):
        skey = ".".join(str(v) for v in s["key"].values())
        records.append(make_record(identity=f"series:bis:{flow}:{skey}", kind="series", source_id=SOURCE_ID, title=f"{flow} {skey}",
                                   links=[f"https://data.bis.org/topics"], attribution=ATTRIBUTION,
                                   extra={"dimensions": s["key"], "observations": s["observations"]},
                                   raw={"dataflow": flow, "count": len(s["observations"])}))
    return {"identity": identity, "records": records}
