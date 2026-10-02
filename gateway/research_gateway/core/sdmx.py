"""SDMX schemas and readers: SDMX-JSON (ECB; 1.0 `structure` and 2.0 `structures`) and SDMX-ML 2.1 (BIS, which serves no JSON).

Every message is decoded against a schema declared here (core/schema.py) before anything reads it; the functions below read the DECODED message only.

What the schemas settle, and the 2b-repair-12 rounds that settled it:

  * SDMX-JSON states a message's structure in up to four places: `structure`, `structures`, and the same two under the 2.0 wrapper `data`. All four are declared, so
    all four are decoded — the first element of a `structures` list included, which is the one a lookup reads — before one is chosen. A `false`, a `0`, a `[]` or a
    string in any of them is an unreadable message, not a message with another structure to fall back on (R11-1). Data sets are members, each decoded alone.
  * A Dataflow's structure reference is a `Ref` with an optional `URN`, or a `URN` alone (SDMX 2.1, DataflowType and DataStructureReferenceType). Its shape is checked
    over EVERYTHING the flow states, before any of it is filtered or chosen (2b-repair-13a, R12-2): every `Ref` and every `URN` counts — an empty one, or one that
    names no id, is a reference that is malformed, not one that is not there — so more than one of either is a flow that does not say which structure it has, and
    a `Ref` states `package` and `class` only with the values the schema fixes (`datastructure`, `DataStructure`), or it is no data structure reference. A URN that
    names a different object than the Ref beside it is the same contradiction (R11-2). A lone `Ref` that names no id, and a URN alone, are legitimate representations
    this reader does not follow: the flow names no structure it can use, and no series template is invented for it. Nothing is ever the first of several.
  * A Dataflow is selected by its id and agency from a listing that is decoded as names only: a flow no one asked for is not asked for its references.
"""
from __future__ import annotations

import re

from . import schema as S
from .payload import MemberList, PayloadError, is_unreadable

ATTRIBUTES = S.table(S.text())   # `"@*"`: every attribute of an element, as text

# ---------------------------------------------------------------- SDMX-JSON data messages
DIM_VALUE = S.obj({"id": S.text(), "name": S.text()})
DIMENSION = S.obj({"id": S.text(), "name": S.text(), "values": S.members(DIM_VALUE)})
# the structural context kept with each record (`context`): each field is `maybe` metadata — None when the message leaves it out or sends null, else carried as sent and stored, never read —
# so whether it is there is the schema's own fact, and `context` needs no way to look inside one
STRUCTURE = S.obj({"dimensions": S.maybe(S.obj({"series": S.own(DIMENSION), "observation": S.own(S.obj({"values": S.own(DIM_VALUE)}))})),
                   "attributes": S.maybe(S.any_()), "annotations": S.maybe(S.any_()), "name": S.maybe(S.any_()), "names": S.maybe(S.any_())})
# an observation is an array whose first element is its value (`[value, status, ...]`), or the value itself: the shape is declared, what is in it is metadata
DATASET = S.obj({"series": S.entries(S.obj({"observations": S.table(S.oneof(S.own(S.any_()), S.any_()))}))})
_PLACE = {"structure": S.maybe(STRUCTURE), "structures": S.lookup(STRUCTURE), "dataSets": S.maybe(S.members(DATASET))}
JSON_MESSAGE = S.obj({**_PLACE, "data": S.obj(_PLACE)}, alts=(("structure", "structures", "data.structure", "data.structures"),))

# ---------------------------------------------------------------- SDMX-ML data messages (BIS)
OBSERVATION = S.obj({"@*": ATTRIBUTES, "@TIME_PERIOD": S.text(), "@OBS_VALUE": S.text()})
SERIES_XML = S.obj({"@*": ATTRIBUTES, "Obs": S.own(OBSERVATION)})
HEADER_CHILD = S.obj({"%": S.text(), "#": S.text(), "@*": ATTRIBUTES})
XML_MESSAGE = S.obj({"@*": ATTRIBUTES, "**Header": S.own(S.obj({"*": S.own(HEADER_CHILD)})), "**Structure": S.own(S.obj({"@*": ATTRIBUTES})),
                     "**Series": S.members(SERIES_XML)})

# ---------------------------------------------------------------- SDMX-ML structure messages
FLOW_NAMES = S.obj({"**Dataflow": S.own(S.obj({"@id": S.text(), "@agencyID": S.text(), "@version": S.text(), "Name": S.own(S.obj({"#": S.text()}))}))})
_URN = re.compile(r"^urn:sdmx:org\.sdmx\.infomodel\.datastructure\.DataStructure=([^:()]+):([^:()]+)\(([^()]+)\)$")


# DataStructureRefType (SDMXCommonReferences.xsd): `class` and `package` are optional and FIXED to these values
_REF_FIXED = {"class": "DataStructure", "package": "datastructure"}


def _reference(rec) -> dict:
    """The one structure reference a Dataflow states ({} when it states none this reader follows), after checking everything it states: how many `Structure` children,
    `Ref`s and `URN`s there are — counted before any is set aside, a `Ref` that names nothing included — the fixed attributes of the `Ref`, and that a `Ref` and a `URN`
    beside each other name the same structure."""
    structures = rec["Structure"]
    if len(structures) > 1:
        raise PayloadError(f"a dataflow with {len(structures)} structure references: nothing says which one is meant")
    refs = [r["@*"] for st in structures for r in st["Ref"]]
    urns = [(u["#"] or "").strip() for st in structures for u in st["URN"]]
    if len(refs) > 1:
        raise PayloadError(f"a dataflow with {len(refs)} structure references: nothing says which one is meant")
    if len(urns) > 1:
        raise PayloadError(f"a dataflow with {len(urns)} structure URNs: nothing says which one is meant")
    for ref in refs:
        for name, fixed in _REF_FIXED.items():
            if name in ref and ref[name] != fixed:
                raise PayloadError(f"a dataflow whose structure Ref states {name}={ref[name]!r}, which a data structure reference fixes to {fixed!r}: it is no such reference")
    if refs and not (refs[0].get("id") or "").strip():
        if urns:
            raise PayloadError("a dataflow whose structure Ref names no id beside a URN: they cannot be shown to name the same structure")
        return {}   # a lone Ref that names nothing: no structure this reader can follow
    if refs and urns:
        named = _URN.match(urns[0])
        if not named:
            raise PayloadError(f"a dataflow whose structure URN {urns[0]!r} cannot be read beside its Ref: they cannot be shown to name the same structure")
        agency, ident, version = named.groups()
        ref = refs[0]
        if (ref["id"] != ident or ref.get("agencyID") not in (None, agency) or ref.get("version") not in (None, version)):
            raise PayloadError(f"a dataflow whose structure Ref {ref['id']!r} and URN {urns[0]!r} name different structures")
    return dict(refs[0]) if refs else {}


FLOW_BINDING = S.obj({"@id": S.text(), "@agencyID": S.text(), "@version": S.text(), "Name": S.own(S.obj({"#": S.text()})),
                      "Structure": S.own(S.obj({"Ref": S.own(S.obj({"@*": ATTRIBUTES})), "URN": S.own(S.obj({"#": S.text()}))}))},
                     rule=_reference)
DATA_STRUCTURES = S.obj({"**DataStructure": S.own(S.obj({"@id": S.text(), "@agencyID": S.text(), "@version": S.text(),
                                                         "**Dimension": S.own(S.obj({"@id": S.text(), "@position": S.text()}))}))})
SCHEMAS = {"json": JSON_MESSAGE, "xml": XML_MESSAGE, "flows": FLOW_NAMES, "flow": FLOW_BINDING, "structures": DATA_STRUCTURES}


# ---------------------------------------------------------------- SDMX-JSON readers
def message(source_id: str, value):
    """The decoded SDMX-JSON message (its structure, in whichever place it is stated, and its data sets)."""
    return S.decode(source_id, JSON_MESSAGE, value)


def structure(msg):
    """The message's structure (its dimension and attribute definitions): the first place that states one, in the order `structure`, `structures`, then the same under
    `data` — None when the message names none. All four were decoded before this chose."""
    return next((s for s in (msg["structure"], msg["structures"], msg["data"]["structure"], msg["data"]["structures"]) if s is not None), None)


def datasets(msg) -> MemberList:
    """The message's data sets, as the decoder left them (one that cannot be read is Unreadable): the top-level `dataSets`, else the wrapper's; none when it names none."""
    found = msg["dataSets"] if msg["dataSets"] is not None else msg["data"]["dataSets"]
    return found or MemberList([])


def has_content(msg) -> bool:
    """Whether the message has any data set, or a structure that says anything (an empty `{}` structure says nothing)."""
    st = structure(msg)
    return bool(datasets(msg)) or bool(st is not None and not st.empty)


def context(msg) -> dict:
    """The SDMX-JSON structural context (dimension and attribute definitions) without the data — kept with each record's raw so nothing needed to reread the
    observations is lost (I-8, D-25)."""
    st = structure(msg)
    out = {}
    for k in ("dimensions", "attributes", "annotations", "name", "names"):
        value = st[k] if st is not None else None   # stored, never read: metadata that is kept as the provider sent it (still sealed: the router makes it plain), or not at all when it sent none
        if value is not None:
            out[k] = value
    return out


def series_members(msg) -> MemberList:
    """Every series of every data set as one member (a Rec of its `key`, its position, and its `value`), so the caller decodes each alone (adapters.base.members)
    and a series that cannot be read is that series' loss only. A data set that cannot be read is ONE unreadable member in place of its series, and the series of
    the other data sets stand."""
    return datasets(msg).expand(lambda ds: ds["series"])


def series_reader(msg):
    """The function that reads one `series_members` member into {key: {dim: value}, observations: [(period, value)], observations_raw}; the message's structure
    is read once, here, whole — every series needs it."""
    st = structure(msg)
    dims = st["dimensions"] if st is not None else None
    series_dims = dims["series"] if dims is not None else []
    obs_dims = dims["observation"] if dims is not None else []
    periods = [v["id"] or v["name"] for v in (obs_dims[0]["values"] if obs_dims else [])]

    def read(member) -> dict:
        key, s = member["key"], member["value"]
        idx = [int(i) for i in key.split(":")] if key else []
        dim_values = {}
        for pos, d in zip(idx, series_dims):
            vals = d["values"]
            if pos < len(vals):
                value = vals.at(pos)
                if is_unreadable(value):
                    raise PayloadError(f"the series {key!r} points at a dimension value that cannot be read: {value.reason}")
                dim_values[d["id"] or d["name"]] = value["id"] or value["name"]
        observed = s["observations"]   # the observations of ONE series: read whole, a malformed one makes it unreadable
        observations = []
        for oi, arr in sorted(((int(k), v) for k, v in observed.items()), key=lambda kv: kv[0]):
            period = periods[oi] if oi < len(periods) else str(oi)
            value = arr[0] if isinstance(arr, list) and arr else arr
            observations.append((period, value))
        return {"key": dim_values, "observations": observations,
                "observations_raw": observed}   # full per-observation arrays survive (I-8)
    return read


# ---------------------------------------------------------------- SDMX-ML readers
def data_xml(source_id: str, answer):
    """The decoded SDMX-ML data message (StructureSpecificData or GenericData); `answer` is the client's response (opened by the decoder) or its text."""
    return S.decode(source_id, XML_MESSAGE, S.parse_xml(answer, "StructureSpecificData", "GenericData"))


def series_xml(msg) -> MemberList:
    """StructureSpecificData → the series as members, each {key: {dimension attribute: value}, observations, observations_raw}:
    dimension attributes on each <Series>, observations from its <Obs TIME_PERIOD OBS_VALUE> children."""
    def convert(el) -> MemberList:
        observations, observations_raw = [], []
        for obs in el["Obs"]:
            raw = obs["@OBS_VALUE"]
            try:
                value = float(raw) if raw not in (None, "") else None
            except ValueError:
                value = raw
            observations.append((obs["@TIME_PERIOD"], value))
            observations_raw.append(dict(obs["@*"]))   # status/confidentiality flags survive into raw (I-8)
        return MemberList([{"key": dict(el["@*"]), "observations": observations, "observations_raw": observations_raw}])
    return msg["**Series"].expand(convert)


def context_xml(msg) -> dict:
    """The SDMX-ML message context: header fields and the structure reference (I-8, D-25)."""
    out: dict = {"root_attributes": dict(msg["@*"])}
    for header in msg["**Header"]:
        out["header"] = {c["%"]: (c["#"] or "").strip() or dict(c["@*"]) for c in header["*"]}   # the last Header element wins
    for st in msg["**Structure"]:
        out["structure"] = dict(st["@*"])
    return out


def flows(source_id: str, answer) -> list[dict]:
    """SDMX structure XML → one entry per Dataflow element, in document order: {id, agency, version, label}. Namespace-agnostic like the rest of this module. `label` is
    the flow's own `Name` child (its id when it has none). Nothing is taken from another element of the message."""
    decoded = S.decode(source_id, FLOW_NAMES, S.parse_xml(answer, "Structure"))
    return [{"id": f["@id"], "agency": f["@agencyID"], "version": f["@version"], "label": next((n["#"] for n in f["Name"] if n["#"]), None) or f["@id"], "element": f.raw}
            for f in decoded["**Dataflow"]]


def dataflow_named(source_id: str, listed: list[dict], wanted: str, agency: str) -> dict | None:
    """The one Dataflow `wanted` that `agency` maintains, from `flows`' entries: None when the message defines none (a flow that states another agency is that
    agency's, not this one). Its label and its structure reference are what the answer is about, and nothing of another flow: {id, agency, version, label, structure},
    `structure` being the reference its own `Structure` child makes ({} when it states none this reader follows). Every definition of the flow is decoded with its
    references before they are compared, so a contradiction in any of them is unreadable (R11-2). A message that defines it more than once, differently — another
    version, another agency's definition, another name or another structure — does not say which is meant: PayloadError, never the first of them. The same
    definition twice is one."""
    found = []
    for f in listed:
        if f["id"] == wanted and f["agency"] in (None, agency):
            bound = S.decode(source_id, FLOW_BINDING, f["element"])
            found.append({"id": f["id"], "agency": f["agency"], "version": f["version"], "label": f["label"], "structure": _reference(bound)})
    distinct = {(f["agency"], f["version"], f["label"], tuple(sorted(f["structure"].items()))) for f in found}
    if len(distinct) > 1:
        raise PayloadError(f"an SDMX answer that defines the dataflow {wanted!r} {len(distinct)} times, differently: nothing says which one is meant")
    return found[0] if found else None


def _dimension_ids(structure_: dict) -> list[str]:
    """One data structure's dimension ids IN KEY ORDER (position attribute when present, document order otherwise), each once; the time dimension is none of them."""
    dims = []
    for el in structure_["**Dimension"]:
        if el["@id"] and all(el["@id"] != d for _, d in dims):
            try:
                position = int(el["@position"] if el["@position"] is not None else len(dims))
            except ValueError:
                position = len(dims)
            dims.append((position, el["@id"]))
    return [d for _, d in sorted(dims)]


def dimensions_xml(source_id: str, answer, structure_: dict) -> list[str]:
    """The dimension ids of ONE data structure IN KEY ORDER: the one `structure_` names (its `id`, and its `agencyID` and `version` when the reference states them). A message may
    hold many (a wildcard query, a `references=descendants` answer): their dimensions are theirs, never this one's. [] when the message holds none of that structure. A
    reference that more than one structure of the message answers to, with different dimensions, does not say which is meant: PayloadError."""
    decoded = S.decode(source_id, DATA_STRUCTURES, S.parse_xml(answer, "Structure"))
    found = [el for el in decoded["**DataStructure"]
             if all(el["@" + k] == structure_[k] for k in ("id", "agencyID", "version") if structure_.get(k) is not None)]
    answers = {tuple(_dimension_ids(el)) for el in found}
    if len(answers) > 1:
        raise PayloadError(f"an SDMX answer in which the data structure {structure_.get('id')!r} names {len(found)} structures with different dimensions: nothing says which one is meant")
    return list(next(iter(answers))) if answers else []
