"""Minimal SDMX readers: SDMX-JSON (ECB; 1.0 `structure` and 2.0 `structures`) and
SDMX-ML 2.1 structure-specific XML (BIS, which serves no JSON)."""
from __future__ import annotations

import xml.etree.ElementTree as ET

from .payload import Members, Obj, PayloadError, plain

NO_SERIES = Members(())


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _root(text: str, *roots: str) -> ET.Element:
    """The parsed message, whose root must be one of `roots`: unparseable XML, or a document
    that is not an SDMX message of that kind, is an unreadable answer — never an empty one."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise PayloadError(f"unparseable SDMX-ML ({e})") from None
    if _local(root.tag) not in roots:
        raise PayloadError(f"an SDMX answer rooted at {_local(root.tag)!r}, not {' or '.join(roots)}")
    return root


def series_xml(text: str) -> Members:
    """StructureSpecificData → the series as members, each {key: {dimension attribute: value}, observations, observations_raw}:
    dimension attributes on each <Series>, observations from its <Obs TIME_PERIOD OBS_VALUE> children."""
    root = _root(text, "StructureSpecificData", "GenericData")
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
    return Members(out)


def _kind(value) -> str:
    return {"Obj": "an object", "Members": "a list"}.get(type(value).__name__, type(value).__name__)


def structure(j: Obj):
    """The message's structure (its dimension and attribute definitions): an Obj, or {} when the message names none (nothing there, or
    null). A `structures` list is read for its first, as a lookup reads its first result. A structure that is there and is anything
    else — `false`, `0`, `""`, `[]` included — is an unreadable message: it is not "no structure", and every series needs it."""
    found = j.get("structure")
    if found is not None:
        if not isinstance(found, Obj):
            raise PayloadError(f"an SDMX answer whose structure is {_kind(found)}, not an object")
        return found
    many = j.get("structures")
    if many is not None:
        if not isinstance(many, Members):
            raise PayloadError(f"an SDMX answer whose structures is {_kind(many)}, not a list")
        if many:
            return many.first(lambda s: s, "sdmx")
    wrapped = j.get("data")  # 2.0 wraps everything under data
    if wrapped is not None:
        if not isinstance(wrapped, Obj):
            raise PayloadError(f"an SDMX answer whose data is {_kind(wrapped)}, not an object")
        return structure(wrapped)
    return {}


def datasets(j: Obj) -> Members:
    """The message's data sets: none when it names none (missing or null); a `dataSets` that is there and is anything but a list is an
    unreadable message, never an empty one."""
    holder = j
    if "dataSets" not in j:
        wrapped = j.get("data")
        if wrapped is not None and not isinstance(wrapped, Obj):
            raise PayloadError(f"an SDMX answer whose data is {_kind(wrapped)}, not an object")
        holder = wrapped if wrapped is not None else {}
    found = holder.get("dataSets")
    if isinstance(found, Members):
        return found
    if found is not None:
        raise PayloadError(f"an SDMX answer whose dataSets is {_kind(found)}, not a list")
    return NO_SERIES


def context(j: Obj) -> dict:
    """The SDMX-JSON structural context (dimension and attribute definitions) without the data —
    kept with each record's raw so nothing needed to reread the observations is lost (I-8, D-25)."""
    st = structure(j)
    return {k: st.get(k) for k in ("dimensions", "attributes", "annotations", "name", "names") if st.get(k) is not None}


def context_xml(text: str) -> dict:
    """The SDMX-ML message context: header fields and the structure reference (I-8, D-25)."""
    root = _root(text, "StructureSpecificData", "GenericData")
    out: dict = {"root_attributes": dict(root.attrib)}
    for el in root.iter():
        name = _local(el.tag)
        if name == "Header":
            out["header"] = {_local(c.tag): (c.text or "").strip() or dict(c.attrib) for c in el}
        elif name == "Structure":
            out["structure"] = dict(el.attrib)
    return out


def _series_of(dataset: Obj) -> Members:
    """The series a data set holds: none when it names none (missing or null); `series` that is there is an object before its size or its
    truth is looked at — a `false`, `0`, `""` or `[]` in its place is an unreadable data set (one loss), not one with no series."""
    series = dataset.get("series")
    if series is None:
        return NO_SERIES
    if not isinstance(series, Obj):
        raise PayloadError(f"an SDMX data set whose series is {_kind(series)}, not an object")
    return series.entries()


def series_members(j: Obj) -> Members:
    """Every series of every data set as one member, `{"key": <its position>, "value": <as sent>}`, so the caller decodes
    each alone (adapters.base.members) and a series that cannot be read is that series' loss only. A data set that
    cannot be read — not an object, or `series` of the wrong kind — is ONE unreadable member in place of its series, and
    the series of the other data sets stand (Members.expand): it is dropped and counted, not the whole message lost."""
    return datasets(j).expand(_series_of)


def _held(holder, key: str, kind: type):
    """What `holder[key]` holds, as plain data: an empty `kind` when it is missing or null, and exactly a `kind` when it is there — one
    that is not (a `false`, a `0`, an `{}` for a list) is an unreadable structure, not an empty one."""
    value = plain(holder.get(key))
    if value is None:
        return kind()
    if not isinstance(value, kind):
        raise PayloadError(f"an SDMX structure whose {key} is {type(value).__name__}, not {kind.__name__}")
    return value


def series_reader(j: Obj):
    """The function that reads one `series_members` member into {key: {dim: value}, observations: [(period,
    value)], observations_raw}; the message's structure is read once, here, whole — every series needs it."""
    st = structure(j)
    dims = _held(st, "dimensions", dict)
    series_dims = _held(dims, "series", list)
    obs_dims = _held(dims, "observation", list)
    periods = [v.get("id") or v.get("name") for v in (_held(obs_dims[0], "values", list) if obs_dims else [])]

    def read(member: Obj) -> dict:
        key, s = member["key"], member["value"]
        idx = [int(i) for i in key.split(":")] if key else []
        dim_values = {}
        for pos, d in zip(idx, series_dims):
            vals = _held(d, "values", list)
            if pos < len(vals):
                dim_values[d.get("id") or d.get("name")] = vals[pos].get("id") or vals[pos].get("name")
        observed = _held(s, "observations", dict)   # the observations of ONE series: read whole, a malformed one makes it unreadable
        observations = []
        for oi, arr in sorted(((int(k), v) for k, v in observed.items()), key=lambda kv: kv[0]):
            period = periods[oi] if oi < len(periods) else str(oi)
            value = arr[0] if isinstance(arr, list) and arr else arr
            observations.append((period, value))
        return {"key": dim_values, "observations": observations,
                "observations_raw": observed}   # full per-observation arrays survive (I-8)
    return read


def dataflows_xml(text: str) -> list[dict]:
    """SDMX structure XML → [{id, label, structure_ref}] for every Dataflow element.
    Namespace-agnostic like the rest of this module; the structure ref is the DSD id
    the flow's key browsing needs (D-32)."""
    flows = []
    root = _root(text, "Structure")
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
    dims = []
    root = _root(text, "Structure")
    for el in root.iter():
        if _local(el.tag) == "Dimension" and el.attrib.get("id"):
            try:
                position = int(el.attrib.get("position", len(dims)))
            except ValueError:
                position = len(dims)
            dims.append((position, el.attrib["id"]))
    return [d for _, d in sorted(dims)]
