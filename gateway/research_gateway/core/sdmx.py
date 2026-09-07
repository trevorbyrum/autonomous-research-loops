"""Minimal SDMX-JSON reader for BIS and ECB series (1.0 `structure` and 2.0 `structures`)."""
from __future__ import annotations


def _structure(j: dict) -> dict:
    if isinstance(j.get("structure"), dict):
        return j["structure"]
    if isinstance(j.get("structures"), list) and j["structures"]:
        return j["structures"][0]
    if isinstance(j.get("data"), dict):  # 2.0 wraps everything under data
        return _structure(j["data"])
    return {}


def _datasets(j: dict) -> list:
    if isinstance(j.get("dataSets"), list):
        return j["dataSets"]
    if isinstance(j.get("data"), dict):
        return j["data"].get("dataSets") or []
    return []


def series(j: dict) -> list[dict]:
    """Flatten SDMX-JSON into [{key: {dim: value}, observations: [(period, value)]}]."""
    st = _structure(j)
    dims = st.get("dimensions") or {}
    series_dims = dims.get("series") or []
    obs_dims = dims.get("observation") or []
    periods = [v.get("id") or v.get("name") for v in (obs_dims[0].get("values") if obs_dims else [])]
    out = []
    for ds in _datasets(j):
        for key, s in (ds.get("series") or {}).items():
            idx = [int(i) for i in key.split(":")] if key else []
            dim_values = {}
            for pos, d in zip(idx, series_dims):
                vals = d.get("values") or []
                if pos < len(vals):
                    dim_values[d.get("id") or d.get("name")] = vals[pos].get("id") or vals[pos].get("name")
            observations = []
            for oi, arr in sorted(((int(k), v) for k, v in (s.get("observations") or {}).items()), key=lambda kv: kv[0]):
                period = periods[oi] if oi < len(periods) else str(oi)
                value = arr[0] if isinstance(arr, list) and arr else arr
                observations.append((period, value))
            out.append({"key": dim_values, "observations": observations})
    return out
