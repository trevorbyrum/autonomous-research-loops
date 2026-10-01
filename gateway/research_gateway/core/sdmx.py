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


def _wrapper(j: Obj):
    """The `data` object SDMX-JSON 2.0 wraps its data sets and structures in: None when the message has none; one that is there and is not an object is an unreadable message."""
    wrapped = j.get("data")
    if wrapped is not None and not isinstance(wrapped, Obj):
        raise PayloadError(f"an SDMX answer whose data is {_kind(wrapped)}, not an object")
    return wrapped


def structure(j: Obj):
    """The message's structure (its dimension and attribute definitions): an Obj, or {} when the message names none (nothing there, or
    null). A `structures` list is read for its first, as a lookup reads its first result. A structure that is there and is anything
    else — `false`, `0`, `""`, `[]` included — is an unreadable message: it is not "no structure", and every series needs it. Every place a message
    may state it (`structure`, `structures`, and what 2.0 wraps under `data`) is read for its kind before one is chosen (R10-1)."""
    found, many, wrapped = j.get("structure"), j.get("structures"), _wrapper(j)
    if found is not None and not isinstance(found, Obj):
        raise PayloadError(f"an SDMX answer whose structure is {_kind(found)}, not an object")
    if many is not None and not isinstance(many, Members):
        raise PayloadError(f"an SDMX answer whose structures is {_kind(many)}, not a list")
    if found is not None:
        return found
    if many:
        return many.first(lambda s: s, "sdmx")
    return structure(wrapped) if wrapped is not None else {}   # 2.0 wraps everything under data


def datasets(j: Obj) -> Members:
    """The message's data sets: none when it names none (missing or null); a `dataSets` that is there and is anything but a list is an
    unreadable message, never an empty one."""
    wrapped = _wrapper(j)   # read whether or not the data sets are at the top
    holder = j if "dataSets" in j else (wrapped if wrapped is not None else {})
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


def _named(entry) -> str | None:
    """What an SDMX-JSON entry (a dimension, one of its values) is called: its `id`, else its `name`. Both are text when they are there, and are read as
    such before either is chosen: an `id` that is `false` or `[]` is not a missing one with a `name` to fall back to."""
    ident, name = entry.get("id"), entry.get("name")
    if any(v is not None and not isinstance(v, str) for v in (ident, name)):
        raise PayloadError("an SDMX entry whose id or name is not text")
    return ident or name


def series_reader(j: Obj):
    """The function that reads one `series_members` member into {key: {dim: value}, observations: [(period,
    value)], observations_raw}; the message's structure is read once, here, whole — every series needs it."""
    st = structure(j)
    dims = _held(st, "dimensions", dict)
    series_dims = _held(dims, "series", list)
    obs_dims = _held(dims, "observation", list)
    periods = [_named(v) for v in (_held(obs_dims[0], "values", list) if obs_dims else [])]

    def read(member: Obj) -> dict:
        key, s = member["key"], member["value"]
        idx = [int(i) for i in key.split(":")] if key else []
        dim_values = {}
        for pos, d in zip(idx, series_dims):
            vals = _held(d, "values", list)
            if pos < len(vals):
                dim_values[_named(d)] = _named(vals[pos])
        observed = _held(s, "observations", dict)   # the observations of ONE series: read whole, a malformed one makes it unreadable
        observations = []
        for oi, arr in sorted(((int(k), v) for k, v in observed.items()), key=lambda kv: kv[0]):
            period = periods[oi] if oi < len(periods) else str(oi)
            value = arr[0] if isinstance(arr, list) and arr else arr
            observations.append((period, value))
        return {"key": dim_values, "observations": observations,
                "observations_raw": observed}   # full per-observation arrays survive (I-8)
    return read


def _children(el: ET.Element, name: str) -> list[ET.Element]:
    return [c for c in el if _local(c.tag) == name]


def dataflows_xml(text: str) -> list[dict]:
    """SDMX structure XML → one entry per Dataflow element, in document order: {id, agency, version, label, structure}. Namespace-agnostic like the rest of this
    module. `label` is the flow's own `Name` child (its id when it has none) and `structure` the reference its own `Structure` child makes to its data structure — `id`,
    `agencyID` and `version` as that reference states them, and {} when the flow names none (D-32). Nothing is taken from another element of the message."""
    flows = []
    for el in _root(text, "Structure").iter():
        if _local(el.tag) != "Dataflow":
            continue
        ref = next((dict(r.attrib) for s in _children(el, "Structure") for r in _children(s, "Ref") if r.attrib.get("id")), {})
        label = next((c.text for c in _children(el, "Name") if c.text), None)
        flows.append({"id": el.attrib.get("id"), "agency": el.attrib.get("agencyID"), "version": el.attrib.get("version"),
                      "label": label or el.attrib.get("id"), "structure": ref})
    return flows


def dataflow_named(flows: list[dict], wanted: str, agency: str) -> dict | None:
    """The one Dataflow `wanted` that `agency` maintains, from `dataflows_xml`'s entries: None when the message defines none (a flow that states another agency is
    that agency's, not this one). Its label and its structure reference are what the answer is about, and nothing of another flow. A message that defines it more than once,
    differently — another version, another agency's definition, another name or another structure — does not say which is meant: PayloadError, never the first of them.
    The same definition twice is one."""
    found = [f for f in flows if f["id"] == wanted and f["agency"] in (None, agency)]
    distinct = {(f["agency"], f["version"], f["label"], tuple(sorted(f["structure"].items()))) for f in found}
    if len(distinct) > 1:
        raise PayloadError(f"an SDMX answer that defines the dataflow {wanted!r} {len(distinct)} times, differently: nothing says which one is meant")
    return found[0] if found else None


def _dimension_ids(structure: ET.Element) -> list[str]:
    """One data structure's dimension ids IN KEY ORDER (position attribute when present, document order otherwise), each once; the time dimension is none of them."""
    dims = []
    for el in structure.iter():
        if _local(el.tag) == "Dimension" and el.attrib.get("id") and all(el.attrib["id"] != d for _, d in dims):
            try:
                position = int(el.attrib.get("position", len(dims)))
            except ValueError:
                position = len(dims)
            dims.append((position, el.attrib["id"]))
    return [d for _, d in sorted(dims)]


def dimensions_xml(text: str, structure: dict) -> list[str]:
    """The dimension ids of ONE data structure IN KEY ORDER: the one `structure` names (its `id`, and its `agencyID` and `version` when the reference states them). A message may
    hold many (a wildcard query, a `references=descendants` answer): their dimensions are theirs, never this one's. [] when the message holds none of that structure. A
    reference that more than one structure of the message answers to, with different dimensions, does not say which is meant: PayloadError."""
    root = _root(text, "Structure")
    found = [el for el in root.iter() if _local(el.tag) == "DataStructure"
             and all(el.attrib.get(k) == structure[k] for k in ("id", "agencyID", "version") if structure.get(k) is not None)]
    answers = {tuple(_dimension_ids(el)) for el in found}
    if len(answers) > 1:
        raise PayloadError(f"an SDMX answer in which the data structure {structure.get('id')!r} names {len(found)} structures with different dimensions: nothing says which one is meant")
    return list(next(iter(answers))) if answers else []
