"""BLS: Consumer Expenditure, CPI and other series (v2 API; optional registration key)."""
from __future__ import annotations

from ..core.canonical import make_record
from .base import AdapterError, Client, check

SOURCE_ID = "bls"
SMOKE = {'capability': 'data', 'params': {'series': 'CUUR0000SA0', 'start_year': 2025, 'end_year': 2025}}   # the live smoke's one minimal call (I-2: declared here, not in smoke.py)
CAPABILITIES = ("data", "catalog",)
BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
ATTRIBUTION = "U.S. Bureau of Labor Statistics"


# the agent-facing data contract (research_sources; validated before dispatch, D-31)
DATA_PARAMS = {
    "required": {"series": {"doc": "one BLS series id or a list of up to 50, e.g. LNS14000000",
                            "type": "string_or_list", "max_items": 50}},
    "optional": {"start_year": {"doc": "first year", "type": "year"},
                 "end_year": {"doc": "last year", "type": "year"},
                 "catalog": {"doc": "true to include series catalog metadata", "type": "boolean"}},
    "open": False,
    "example": {"series": "LNS14000000", "start_year": 2020, "end_year": 2025},
    "notes": "at most 50 series ids per call; larger lists are rejected, never silently truncated",
}

def data(client: Client, params: dict) -> dict:
    """params: series (id or list of ids), start_year, end_year, catalog (bool)."""
    ids = (params or {}).get("series")
    if not ids:
        raise AdapterError("bls.data needs 'series'")
    ids = [ids] if isinstance(ids, str) else list(ids)
    if len(ids) > 50:
        raise AdapterError(f"bls.data accepts at most 50 series ids per call, got {len(ids)} — split the list")
    body = {"seriesid": ids}
    for k, bk in (("start_year", "startyear"), ("end_year", "endyear")):
        if params.get(k):
            body[bk] = str(params[k])
    if params.get("catalog"):
        body["catalog"] = True
    key = client.secret("bls")
    identity = f"series:bls:{','.join(ids[:3])}{'…' if len(ids) > 3 else ''}"
    if not key:
        # unregistered BLS is 25 queries/day; the enabled 500/day policy assumes a key (D-23)
        return {"identity": identity, "records": [],
                "capability_fact": "no BLS registration key configured; the unregistered 25/day tier is not enabled"}
    body["registrationkey"] = key
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


def catalog(client: Client, *, query: str | None = None, within: str | None = None,
            cursor=None, limit: int = 20) -> dict:
    """Identifier discovery (D-32), deliberately SCOPED: BLS publishes no full-text series
    search API, so this lists surveys and each survey's popular series — anything beyond
    that still needs the BLS data finder by hand (documented residual)."""
    if not within:
        resp = client.get(SOURCE_ID, "catalog", "https://api.bls.gov/publicAPI/v2/surveys", query=query)
        if not check(SOURCE_ID, resp, allow_404=False):
            return {"entries": []}
        q = (query or "").lower()
        entries = [{"id": s.get("survey_abbreviation"), "label": s.get("survey_name"), "kind": "survey",
                    "children": True, "within": s.get("survey_abbreviation")}
                   for s in (((resp.json or {}).get("Results") or {}).get("survey") or [])
                   if s.get("survey_abbreviation")
                   and (not q or q in str(s.get("survey_name", "")).lower()
                        or q in str(s.get("survey_abbreviation", "")).lower())]
        offset = int(cursor or 0)
        page = entries[offset:offset + limit]
        return {"entries": page, "next": str(offset + limit) if len(entries) > offset + limit else None,
                "notes": "BLS has no series search API: browse a survey's popular series, or find ids at data.bls.gov"}
    resp = client.get(SOURCE_ID, "catalog", f"https://api.bls.gov/publicAPI/v2/timeseries/popular?survey={within}",
                      identity=f"series:bls:{within}")
    if not check(SOURCE_ID, resp, allow_404=False):
        return {"entries": []}
    series = (((resp.json or {}).get("Results") or {}).get("series") or [])
    entries = [{"id": s.get("seriesID"), "label": s.get("seriesID"), "kind": "series",
                "data_request": {"tool": "research_data",
                                 "arguments": {"source": SOURCE_ID, "params": {"series": s.get("seriesID")}}}}
               for s in series if s.get("seriesID")]
    offset = int(cursor or 0)
    page = entries[offset:offset + limit]
    return {"entries": page, "next": str(offset + limit) if len(entries) > offset + limit else None,
            "notes": f"the survey's POPULAR series only; other {within} series ids come from data.bls.gov"}
