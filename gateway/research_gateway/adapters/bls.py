"""BLS: Consumer Expenditure, CPI and other series (v2 API; optional registration key)."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "bls"
CAPABILITIES = ("data",)
BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
ATTRIBUTION = "U.S. Bureau of Labor Statistics"


def data(client: Client, params: dict) -> dict:
    """params: series (id or list of ids), start_year, end_year, catalog (bool)."""
    ids = (params or {}).get("series")
    if not ids:
        raise AdapterError("bls.data needs 'series'")
    ids = [ids] if isinstance(ids, str) else list(ids)
    body = {"seriesid": ids[:50]}
    for k, bk in (("start_year", "startyear"), ("end_year", "endyear")):
        if params.get(k):
            body[bk] = str(params[k])
    if params.get("catalog"):
        body["catalog"] = True
    key = client.secret("bls")
    if key:
        body["registrationkey"] = key
    identity = f"series:bls:{','.join(ids[:3])}{'…' if len(ids) > 3 else ''}"
    resp = client.post(SOURCE_ID, "data", BASE, body=body, identity=identity)
    if not check(SOURCE_ID, resp):
        return {"identity": identity, "records": []}
    j = resp.json or {}
    if j.get("status") != "REQUEST_SUCCEEDED":
        return {"identity": identity, "records": [], "capability_fact": f"BLS: {j.get('status')} {'; '.join(j.get('message') or [])}"[:300]}
    records = []
    for s in (j.get("Results") or {}).get("series") or []:
        obs = [(f"{d.get('year')}-{d.get('period')}", d.get("value")) for d in reversed(s.get("data") or [])]
        cat = s.get("catalog") or {}
        records.append(make_record(identity=f"series:bls:{s.get('seriesID')}", kind="series", source_id=SOURCE_ID,
                                   title=cat.get("series_title") or s.get("seriesID"),
                                   links=[f"https://data.bls.gov/timeseries/{s.get('seriesID')}"], attribution=ATTRIBUTION,
                                   extra={"observations": obs, "survey": cat.get("survey_name"), "seasonality": cat.get("seasonality")},
                                   raw=s))
    return {"identity": identity, "records": records, "messages": j.get("message") or []}
