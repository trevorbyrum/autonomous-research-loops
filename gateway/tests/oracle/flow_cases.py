"""BIS and ECB: which flow a browse answers (R10-2), and a flow listing that names no flow (R10-3). Task 2b-repair-11a.

Astra's review of 2b-repair-10 (gen2-2b-repair-10-astra-review-20261001.md, R10-2 and R10-3) found that the oracle's multi-structure browse always asked for the
FIRST flow of the message, so a reader that takes `flows[0]` and a reader that follows the request could not be told apart; and that a listing whose every
`Dataflow` has no `id` still passed, because the only unreadable listings the oracle held were HTML, text, an empty body and a structure without dimensions.

Both sets of cases are written from the SDMX 2.1 information model (a Dataflow is identified by `id`, `agencyID` and `version`; it points at its DataStructure
by a reference naming the structure's own id, agency and version; a key is the values of that structure's dimensions other than the time dimension, in order:
SDMX 2.1 REST, "key") and from PLAN.md D-32 / D-32a, STATION-CONTRACT.md §2 (an unreadable answer is `provider_unavailable`, `payload_invalid`, `unobserved`, with no
count, never an empty one; a catalogue's entries are answered whole). Nothing about how the gateway selects a flow was read. What the answer must say:

  success      the entry for the REQUESTED flow carries that flow's own name, the dimensions of the structure ITS reference names (in key order, no time
               dimension, none repeated, none from another structure), and a `research_data` request template for THAT flow whose `key` has one component per
               dimension. Asked in every position of the message (first, middle, last), under rotated flow orders and with the structures listed in either order.
  fail closed  a requested flow that is not in the message, is named twice by two different definitions (ambiguous), or whose structure is not in the message
               yields NO entry and NO template: the lane is `unobserved` or `provider_unavailable`, never `complete` or `searched_ok`.
  unnamed      a listing in which every `Dataflow` has no `id` (or an empty one) is unreadable whole: `provider_unavailable`, `payload_invalid`, `unobserved`, no count,
               no entry; the same listing with its ids is read (the control).

What the answer does NOT have to call things is left open: the template is found by its documented parameters (`dataflow` and `key`, the names the harness's own
`ecb.data` request uses), the dimension list as any list of strings in the entry, the name as text anywhere in it.
"""
from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from .xml_ops import BIS_FLOWS, ECB_FLOWS, HOSTS, NS, _ref

SOURCES = (("bis", BIS_FLOWS, "BIS"), ("ecb", ECB_FLOWS, "ECB"))


@dataclass(frozen=True)
class FlowSpec:
    id: str | None                      # None: no `id` attribute at all
    name: str
    dsd: str
    dsd_version: str = "1.0"
    dsd_agency: str | None = None       # None: the message's agency
    version: str = "1.0"


@dataclass(frozen=True)
class DsdSpec:
    id: str
    dims: tuple
    time: str = "TIME_PERIOD"
    version: str = "1.0"
    agency: str | None = None


def _dimension(agency: str, dsd: DsdSpec, i: int, dim: str, time: bool = False) -> str:
    tag = "TimeDimension" if time else "Dimension"
    rep = ('<structure:LocalRepresentation><structure:TextFormat textType="ObservationalTimePeriod"/></structure:LocalRepresentation>' if time else
           f"<structure:LocalRepresentation><structure:Enumeration>{_ref('CL_' + dim, agency, 'codelist', 'Codelist')}</structure:Enumeration></structure:LocalRepresentation>")
    return (f'<structure:{tag} id="{dim}" position="{i}"><structure:ConceptIdentity>'
            f"{_ref(dim, agency, 'conceptscheme', 'Concept', maintainableParentID='CS_' + agency, maintainableParentVersion='1.0')}"
            f"</structure:ConceptIdentity>{rep}</structure:{tag}>")


def message(agency: str, flows: list, dsds: list) -> str:
    """A Structure message holding exactly these dataflows and these data structures, in this order."""
    parts = [f'<?xml version="1.0" encoding="UTF-8"?>\n<message:Structure {NS}><message:Header><message:ID>IDREF1</message:ID><message:Test>false</message:Test>'
             f'<message:Prepared>2026-10-01T00:00:00</message:Prepared><message:Sender id="{agency}"/></message:Header><message:Structures><structure:Dataflows>']
    for f in flows:
        ident = "" if f.id is None else f' id="{f.id}"'
        parts.append(f'<structure:Dataflow{ident} agencyID="{agency}" version="{f.version}" isFinal="true"><common:Name xml:lang="en">{escape(f.name)}</common:Name>'
                     f"<structure:Structure>{_ref(f.dsd, f.dsd_agency or agency, 'datastructure', 'DataStructure', version=f.dsd_version)}</structure:Structure></structure:Dataflow>")
    parts.append("</structure:Dataflows><structure:DataStructures>")
    for d in dsds:
        ag = d.agency or agency
        dims = "".join(_dimension(ag, d, i, x) for i, x in enumerate(d.dims, 1)) + _dimension(ag, d, len(d.dims) + 1, d.time, True)
        parts.append(f'<structure:DataStructure id="{d.id}" agencyID="{ag}" version="{d.version}" isFinal="true"><common:Name xml:lang="en">{escape(d.id)}</common:Name>'
                     f'<structure:DataStructureComponents><structure:DimensionList id="DimensionDescriptor">{dims}</structure:DimensionList>'
                     "</structure:DataStructureComponents></structure:DataStructure>")
    parts.append("</structure:DataStructures></message:Structures></message:Structure>")
    return "".join(parts)


@dataclass(frozen=True)
class Case:
    name: str
    sid: str
    kind: str                           # bind | absent | ambiguous | missing-structure | versions | unnamed | unnamed-empty | control
    op: object
    requested: str | None               # the flow id asked for (a browse); None for a listing
    dims: tuple = ()                    # the dimensions the requested flow's own structure names
    flow_name: str = ""                 # the requested flow's own name
    others: tuple = ()                  # ((id, name, dims), ...) of the flows that are not the one asked for
    entries: tuple = ()                 # a listing: the flow ids it names
    why: str = ""
    fails_closed: bool = False


def _specs(flows):
    return [FlowSpec(fid, name, dsd) for fid, name, dsd, _d, _t in flows], [DsdSpec(dsd, dims, time) for _f, _n, dsd, dims, time in flows]


def build(ops) -> dict:
    """`ops` is tests.invariant_ops (for Op, Route, request). Returns {name: Case}."""
    Op, Route, request = ops.Op, ops.Route, ops.request
    cases = {}

    def add(case_kwargs, text, req):
        name = case_kwargs["name"]
        op = Op(name, case_kwargs["sid"], req, (Route("GET", HOSTS[case_kwargs["sid"]], text),), ())
        cases[name] = Case(op=op, **case_kwargs)

    for sid, flows, agency in SOURCES:
        by_id = {f[0]: f for f in flows}

        def other(excluding):
            return tuple((f[0], f[1], f[3]) for f in flows if f[0] != excluding)

        # --- success: the flow asked for, wherever it stands; flow orders rotated; structures listed in the flows' order or reversed
        for order in ("structures in flow order", "structures reversed"):
            for rot in range(3):
                rotated = list(flows[rot:] + flows[:rot])
                for asked in flows:
                    fs, ds = _specs(rotated)
                    if order == "structures reversed":
                        ds = list(reversed(ds))
                    position = [f[0] for f in rotated].index(asked[0])
                    where = ("first", "middle", "last")[position]
                    add(dict(name=f"{sid}.catalog (browse {asked[0]}: {where} of {[f[0] for f in rotated]}, {order})", sid=sid, kind="bind", requested=asked[0],
                             dims=asked[3], flow_name=asked[1], others=other(asked[0]), why=f"requested flow is {where}"),
                        message(agency, fs, ds), request("catalog", source=sid, within=asked[0]))

        # --- two data structures with one id: the flow's reference names the version (and agency) it wants
        first = flows[0]
        wanted = ("VERSION_ONLY_TWO", "DECOY_DIM")
        fs = [FlowSpec(first[0], first[1], first[2], dsd_version="2.0")] + [FlowSpec(f[0], f[1], f[2]) for f in flows[1:]]
        ds = [DsdSpec(first[2], wanted, version="1.0"), DsdSpec(first[2], first[3], version="2.0")] + [DsdSpec(f[2], f[3]) for f in flows[1:]]
        add(dict(name=f"{sid}.catalog (browse {first[0]}: its structure has two versions, the flow names 2.0)", sid=sid, kind="versions", requested=first[0], dims=first[3],
                 flow_name=first[1], others=(("(version 1.0 of the same structure)", "", wanted),), why="structure id, agency AND version identify the structure"),
            message(agency, fs, ds), request("catalog", source=sid, within=first[0]))
        fs = [FlowSpec(first[0], first[1], first[2], dsd_agency=agency)] + [FlowSpec(f[0], f[1], f[2]) for f in flows[1:]]
        ds = [DsdSpec(first[2], ("OTHER_AGENCY_DIM",), agency="OTHER"), DsdSpec(first[2], first[3])] + [DsdSpec(f[2], f[3]) for f in flows[1:]]
        add(dict(name=f"{sid}.catalog (browse {first[0]}: two structures share its id, one agency is the flow's)", sid=sid, kind="versions", requested=first[0], dims=first[3],
                 flow_name=first[1], others=(("(the structure of agency OTHER)", "", ("OTHER_AGENCY_DIM",)),), why="structure agency identifies the structure"),
            message(agency, fs, ds), request("catalog", source=sid, within=first[0]))

        # --- fail closed: no flow, no template
        fs, ds = _specs(flows)
        add(dict(name=f"{sid}.catalog (browse MISSING_FLOW: no such flow in a message of three)", sid=sid, kind="absent", requested="MISSING_FLOW", others=other(None),
                 fails_closed=True, why="a flow the message does not hold"),
            message(agency, fs, ds), request("catalog", source=sid, within="MISSING_FLOW"))
        fs1, ds1 = _specs(flows[:1])
        add(dict(name=f"{sid}.catalog (browse MISSING_FLOW: no such flow in a message of one)", sid=sid, kind="absent", requested="MISSING_FLOW", others=other(None),
                 fails_closed=True, why="a flow the message does not hold, beside a single other flow that is not it"),
            message(agency, fs1, ds1), request("catalog", source=sid, within="MISSING_FLOW"))
        asked = flows[1]
        fs, ds = _specs(flows)
        ds = [d for d in ds if d.id != asked[2]]
        add(dict(name=f"{sid}.catalog (browse {asked[0]}: the structure it names is not in the message)", sid=sid, kind="missing-structure", requested=asked[0],
                 others=other(asked[0]), fails_closed=True, why="the flow is there; the structure its reference names is not"),
            message(agency, fs, ds), request("catalog", source=sid, within=asked[0]))
        fs, ds = _specs(flows)
        twice = FlowSpec(asked[0], asked[1] + " (second definition)", flows[2][2])
        fs = [fs[0], fs[1], twice, fs[2]]
        add(dict(name=f"{sid}.catalog (browse {asked[0]}: two definitions of it name two structures)", sid=sid, kind="ambiguous", requested=asked[0], others=other(asked[0]),
                 fails_closed=True, why="one id, one agency, one version, two different definitions: nothing says which is meant"),
            message(agency, fs, ds), request("catalog", source=sid, within=asked[0]))

        # --- R10-3: a listing whose flows name no id
        fs, ds = _specs(flows)
        add(dict(name=f"{sid}.catalog (a listing whose every dataflow has no id)", sid=sid, kind="unnamed", requested=None, fails_closed=True,
                 why="no flow is named: unreadable whole, never an entry called None"),
            message(agency, [FlowSpec(None, f.name, f.dsd) for f in fs], ds), request("catalog", source=sid))
        add(dict(name=f"{sid}.catalog (a listing whose every dataflow has an empty id)", sid=sid, kind="unnamed-empty", requested=None, fails_closed=True,
                 why="an empty id names nothing"),
            message(agency, [FlowSpec("", f.name, f.dsd) for f in fs], ds), request("catalog", source=sid))
        add(dict(name=f"{sid}.catalog (the same listing with its ids: the control)", sid=sid, kind="control", requested=None, entries=tuple(f[0] for f in flows),
                 why="a readable listing beside the unreadable ones"),
            message(agency, fs, ds), request("catalog", source=sid))
    return cases


# ------------------------------------------------------------------ the reference reader: what the SDMX information model says a message answers (checks the cases, never the gateway)
def reference_browse(text: str, agency: str, requested: str) -> tuple:
    """("ok", dims, name) | ("absent" | "ambiguous" | "missing-structure", None, None): the requested Dataflow is found by id; two definitions with one id, agency and
    version are ambiguous; its Structure reference names a DataStructure by id, agency and version, which must be in the message; the key dimensions are that
    structure's Dimension elements in position order, the TimeDimension excluded."""
    import xml.etree.ElementTree as ET
    ns = {"s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure", "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"}
    root = ET.fromstring(text)
    flows = [f for f in root.iter("{%s}Dataflow" % ns["s"]) if f.get("id") == requested]
    if not flows:
        return "absent", None, None
    keys = {(f.get("id"), f.get("agencyID"), f.get("version")) for f in flows}
    defs = {ET.tostring(f) for f in flows}
    if len(flows) > 1 and (len(keys) == 1 and len(defs) > 1):
        return "ambiguous", None, None
    flow = flows[0]
    ref = flow.find("s:Structure/Ref", ns)
    if ref is None:
        ref = flow.find("s:Structure/{*}Ref", ns)
    wanted = (ref.get("id"), ref.get("agencyID"), ref.get("version"))
    found = [d for d in root.iter("{%s}DataStructure" % ns["s"]) if (d.get("id"), d.get("agencyID"), d.get("version")) == wanted]
    if len(found) != 1:
        return ("missing-structure" if not found else "ambiguous"), None, None
    dims = sorted(found[0].iter("{%s}Dimension" % ns["s"]), key=lambda d: int(d.get("position")))
    name = flow.find("c:Name", ns).text
    return "ok", tuple(d.get("id") for d in dims), name


# the failure modes a catalogue operation is tested for, by case kind (an executed case is not a tested failure mode: coverage.py records both)
FAILURE_MODES = {
    "absent": "the requested flow is not in the message",
    "ambiguous": "the requested flow is defined twice, differently",
    "missing-structure": "the structure the requested flow names is not in the message",
    "unnamed": "no dataflow of the listing has an id",
    "unnamed-empty": "every dataflow of the listing has an empty id",
}
