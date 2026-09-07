"""ECB Data Portal: euro-area statistics (SDMX)."""
from __future__ import annotations

from ..core import sdmx
from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "ecb"
SMOKE = {'capability': 'data', 'params': {'dataflow': 'EXR', 'key': 'D.USD.EUR.SP00.A', 'start': '2026-08-01'}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data",)
BASE = "https://data-api.ecb.europa.eu/service/data"
ATTRIBUTION = "European Central Bank"


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
    for s in sdmx.series(resp.json or {}):
        skey = ".".join(str(v) for v in s["key"].values()) or key
        records.append(make_record(identity=f"series:ecb:{flow}:{skey}", kind="series", source_id=SOURCE_ID, title=f"{flow} {skey}",
                                   links=[f"https://data.ecb.europa.eu/data/datasets/{flow}"], attribution=ATTRIBUTION,
                                   extra={"dimensions": s["key"], "observations": s["observations"]},
                                   raw=s))
    return {"identity": identity, "records": records}
