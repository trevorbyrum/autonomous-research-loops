"""FRED: macro and financial time series (attribution required; some series restricted)."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "fred"
CAPABILITIES = ("data",)
BASE = "https://api.stlouisfed.org/fred"
ATTRIBUTION = "Source: FRED, Federal Reserve Bank of St. Louis"


def data(client: Client, params: dict) -> dict:
    """params: series (required), start, end, limit, include_meta."""
    series_id = (params or {}).get("series")
    if not series_id:
        raise AdapterError("fred.data needs 'series'")
    key = client.secret("fred")
    if not key:
        return {"identity": f"series:fred:{series_id}", "records": [], "capability_fact": "no FRED key configured"}
    common = {"api_key": key, "file_type": "json"}
    resp = client.get(SOURCE_ID, "data", f"{BASE}/series/observations",
                      params={**common, "series_id": series_id, "observation_start": params.get("start"),
                              "observation_end": params.get("end"), "limit": params.get("limit"), "sort_order": "asc"},
                      identity=f"series:fred:{series_id}")
    if not check(SOURCE_ID, resp):
        return {"identity": f"series:fred:{series_id}", "records": []}
    obs = [(o.get("date"), o.get("value")) for o in (resp.json or {}).get("observations", [])]
    meta, series_payload = {}, None
    if params.get("include_meta", True):
        m = client.get(SOURCE_ID, "data", f"{BASE}/series", params={**common, "series_id": series_id},
                       identity=f"series:fred:{series_id}")
        if m.ok:
            series_payload = m.json
            s = ((m.json or {}).get("seriess") or [{}])[0]
            meta = {k: s.get(k) for k in ("title", "units", "frequency", "seasonal_adjustment", "last_updated", "notes")}
    rec = make_record(identity=f"series:fred:{series_id}", kind="series", source_id=SOURCE_ID, title=meta.get("title"),
                      links=[f"https://fred.stlouisfed.org/series/{series_id}"], attribution=ATTRIBUTION,
                      extra={"units": meta.get("units"), "frequency": meta.get("frequency"), "observations": obs,
                             "third_party_restricted": "restrict" in (meta.get("notes") or "").lower()},
                      raw={"observations": resp.json, "series": series_payload})
    return {"identity": rec["identity"], "records": [rec]}
