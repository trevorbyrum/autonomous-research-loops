"""Minimal SDMX readers: SDMX-JSON (ECB; 1.0 `structure` and 2.0 `structures`) and
SDMX-ML 2.1 structure-specific XML (BIS, which serves no JSON)."""
from __future__ import annotations

import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def series_xml(text: str) -> list[dict]:
    """StructureSpecificData → same shape as series(): dimension attributes on each
    <Series>, observations from its <Obs TIME_PERIOD OBS_VALUE> children."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for el in root.iter():
        if _local(el.tag) != "Series":
            continue
        observations = []
        for obs in el:
            if _local(obs.tag) != "Obs":
                continue
            raw = obs.get("OBS_VALUE")
            try:
                value = float(raw) if raw not in (None, "") else None
            except ValueError:
                value = raw
            observations.append((obs.get("TIME_PERIOD"), value))
        out.append({"key": dict(el.attrib), "observations": observations})
    return out


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
