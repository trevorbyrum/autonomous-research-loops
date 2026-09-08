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
        observations, observations_raw = [], []
        for obs in el:
            if _local(obs.tag) != "Obs":
                continue
            raw = obs.get("OBS_VALUE")
            try:
                value = float(raw) if raw not in (None, "") else None
            except ValueError:
                value = raw
            observations.append((obs.get("TIME_PERIOD"), value))
            observations_raw.append(dict(obs.attrib))   # status/confidentiality flags survive into raw (I-8)
        out.append({"key": dict(el.attrib), "observations": observations, "observations_raw": observations_raw})
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


def context(j: dict) -> dict:
    """The SDMX-JSON structural context (dimension and attribute definitions) without the data —
    kept with each record's raw so nothing needed to reread the observations is lost (I-8, D-25)."""
    st = _structure(j)
    return {k: st.get(k) for k in ("dimensions", "attributes", "annotations", "name", "names") if st.get(k) is not None}


def context_xml(text: str) -> dict:
    """The SDMX-ML message context: header fields and the structure reference (I-8, D-25)."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    out: dict = {"root_attributes": dict(root.attrib)}
    for el in root.iter():
        name = _local(el.tag)
        if name == "Header":
            out["header"] = {_local(c.tag): (c.text or "").strip() or dict(c.attrib) for c in el}
        elif name == "Structure":
            out["structure"] = dict(el.attrib)
    return out


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
            out.append({"key": dim_values, "observations": observations,
                        "observations_raw": s.get("observations")})   # full per-observation arrays survive (I-8)
    return out


def dataflows_xml(text: str) -> list[dict]:
    """SDMX structure XML → [{id, label, structure_ref}] for every Dataflow element.
    Namespace-agnostic like the rest of this module; the structure ref is the DSD id
    the flow's key browsing needs (D-32)."""
    import xml.etree.ElementTree as ET
    flows = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return flows
    for el in root.iter():
        if _local(el.tag) != "Dataflow":
            continue
        label = next((c.text for c in el.iter() if _local(c.tag) == "Name" and c.text), None)
        ref = next((c.attrib.get("id") for c in el.iter() if _local(c.tag) == "Ref" and c.attrib.get("id")), None)
        flows.append({"id": el.attrib.get("id"), "label": label or el.attrib.get("id"), "structure_ref": ref})
    return flows


def dimensions_xml(text: str) -> list[str]:
    """SDMX datastructure XML → dimension ids IN KEY ORDER (position attribute when
    present, document order otherwise) — the order an agent needs to build a series key."""
    import xml.etree.ElementTree as ET
    dims = []
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return dims
    for el in root.iter():
        if _local(el.tag) == "Dimension" and el.attrib.get("id"):
            try:
                position = int(el.attrib.get("position", len(dims)))
            except ValueError:
                position = len(dims)
            dims.append((position, el.attrib["id"]))
    return [d for _, d in sorted(dims)]
