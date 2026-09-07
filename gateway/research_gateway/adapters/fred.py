"""FRED: macro and financial time series (attribution required; some series restricted)."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "fred"
SMOKE = {'capability': 'data', 'params': {'series': 'GDP', 'limit': 1}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data", "catalog",)
BASE = "https://api.stlouisfed.org/fred"
ATTRIBUTION = "Source: FRED, Federal Reserve Bank of St. Louis"
# markers FRED's free-text notes use for third-party terms; a match fails the commercial gate (D-25)
_RESTRICTION_MARKERS = ("restrict", "non-commercial", "noncommercial", "written permission", "prohibited",
                        "may not be", "copyrighted", "proprietary", "licens")


def _restricted(notes: str | None) -> bool:
    low = (notes or "").lower()
    return any(m in low for m in _RESTRICTION_MARKERS)


# the agent-facing data contract (research_sources; validated before dispatch, D-31)
DATA_PARAMS = {
    "required": {"series": {"doc": "FRED series id, e.g. GDP, UNRATE, CPIAUCSL", "type": "string"}},
    "optional": {"start": {"doc": "observation start, ISO date YYYY-MM-DD", "type": "date"},
                 "end": {"doc": "observation end, ISO date YYYY-MM-DD", "type": "date"},
                 "limit": {"doc": "max observations returned", "type": "integer"}},
    "open": False,
    "example": {"series": "GDP", "start": "2020-01-01"},
    "notes": "series metadata is always fetched; series FRED flags as third-party-restricted are withheld under commercial topics",
}

def data(client: Client, params: dict) -> dict:
    """params: series (required), start, end, limit. Series metadata is ALWAYS fetched: its notes
    are where FRED flags third-party restrictions, and skipping that check is not an option (D-23)."""
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
    m = client.get(SOURCE_ID, "data", f"{BASE}/series", params={**common, "series_id": series_id},
                   identity=f"series:fred:{series_id}")
    seriess = ((m.json or {}).get("seriess") or []) if m.ok else []
    s = seriess[0] if seriess and isinstance(seriess[0], dict) else {}
    if not s.get("id") and not s.get("title"):
        # an empty or shapeless metadata object is no metadata: the restriction check could not
        # run, so there is no answer (fail closed, D-24/D-25)
        return {"identity": f"series:fred:{series_id}", "records": [],
                "capability_fact": "series metadata unavailable; observations withheld because the third-party-restriction check could not run"}
    series_payload = m.json
    meta = {k: s.get(k) for k in ("title", "units", "frequency", "seasonal_adjustment", "last_updated", "notes")}
    rec = make_record(identity=f"series:fred:{series_id}", kind="series", source_id=SOURCE_ID, title=meta.get("title"),
                      links=[f"https://fred.stlouisfed.org/series/{series_id}"], attribution=ATTRIBUTION,
                      extra={"units": meta.get("units"), "frequency": meta.get("frequency"), "observations": obs,
                             "third_party_restricted": _restricted(meta.get("notes"))},
                      raw={"observations": resp.json, "series": series_payload})
    return {"identity": rec["identity"], "records": [rec]}


def catalog(client: Client, *, query: str | None = None, within: str | None = None,
            cursor=None, limit: int = 20) -> dict:
    """Identifier discovery (D-32): search FRED series by text, or inspect one series id.
    Every fully-selected entry carries the COMPLETE research_data call."""
    key = client.secret("fred")
    if not key:
        return {"entries": [], "capability_fact": "no FRED key configured"}
    common = {"api_key": key, "file_type": "json"}
    if within:
        resp = client.get(SOURCE_ID, "catalog", f"{BASE}/series", params={**common, "series_id": within},
                          identity=f"series:fred:{within}")
        if not check(SOURCE_ID, resp):
            return {"entries": []}
        seriess = (resp.json or {}).get("seriess") or []
    else:
        if not query:
            return {"entries": [], "capability_fact": "fred catalog needs a query (or within=<series id>)"}
        offset = int(cursor or 0)
        resp = client.get(SOURCE_ID, "catalog", f"{BASE}/series/search",
                          params={**common, "search_text": query, "limit": limit, "offset": offset},
                          query=query)
        if not check(SOURCE_ID, resp):
            return {"entries": []}
        seriess = (resp.json or {}).get("seriess") or []
    entries = [{"id": s.get("id"), "label": s.get("title"), "kind": "series",
                "units": s.get("units"), "frequency": s.get("frequency"),
                "observation_range": f"{s.get('observation_start')}..{s.get('observation_end')}",
                "data_request": {"tool": "research_data",
                                 "arguments": {"source": SOURCE_ID, "params": {"series": s.get("id")}}}}
               for s in seriess if s.get("id")]
    nxt = str(int(cursor or 0) + limit) if (not within and len(entries) == limit) else None
    return {"entries": entries, "next": nxt}
