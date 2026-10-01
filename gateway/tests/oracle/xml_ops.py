"""BIS and ECB catalogue execution cases: SDMX-ML structure messages, with the answer each must produce (task 2b-repair-10a, R9-5).

R9-5: the harness's coverage credited `bis.catalog` although nothing ever executed it, so a BIS mutant that fabricated catalogue entries
survived. These cases are real operations: each is run through the router (tests/test_oracle.py) and counts for coverage only if the instrumented
client served a request for it (tests/oracle/coverage.py).

Written from the SDMX 2.1 information model and its XML (SDMX-ML 2.1 Structure message), the SDMX REST key syntax, and PLAN.md D-32/D-32a (the
catalogue of BIS and ECB: "SDMX dataflow listings then the flow's DIMENSION IDS IN KEY ORDER via its datastructure; per-dimension codelists
deferred"). The BIS API documentation (https://stats.bis.org/api-doc/v2/, SOURCES.md) is not captured in the evidence folder, so no URL path is
assumed: each provider's host serves one structure message for every path, which holds the dataflows AND their data structures, the way a
structure query with `references=descendants` answers. What is asserted is what the message says:

  * a dataflow listing names the message's dataflows, by id, in document order;
  * a dataflow's browse names the dimensions of ITS data structure, in key order, and not the time dimension (SDMX REST: a key is the values of the
    dimensions other than TIME_PERIOD, in dimension order);
  * an answer that is not a structure message (an HTML challenge page, text, an empty body) or a data structure with no dimensions is never a
    successful empty catalogue (PLAN.md D-32a: "never as a successful empty catalogue; REFUSES to invent an empty key template").

Dimension browsing (the codes of one dimension) is deferred by D-32 ("per-dimension codelists deferred, documented"); `DEFERRED` lists it, with the
reason, so the coverage registry shows it as listed and not as covered.
"""
from __future__ import annotations

from xml.sax.saxutils import escape

NS = ('xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message" '
      'xmlns:structure="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure" '
      'xmlns:common="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common"')

# (flow id, name, data structure id, key dimensions in key order, the time dimension)
BIS_FLOWS = (
    ("WS_CBPOL", "Policy rates", "BIS_CBPOL", ("FREQ", "REF_AREA"), "TIME_PERIOD"),
    ("WS_EER", "Effective exchange rates", "BIS_EER", ("FREQ", "EER_TYPE", "EER_BASKET", "REF_AREA"), "TIME_PERIOD"),
    ("WS_XRU", "US dollar exchange rates", "BIS_XRU", ("FREQ", "REF_AREA", "CURRENCY"), "TIME_PERIOD"),
)
ECB_FLOWS = (
    ("EXR", "Exchange Rates", "ECB_EXR1", ("FREQ", "CURRENCY", "CURRENCY_DENOM", "EXR_TYPE", "EXR_SUFFIX"), "TIME_PERIOD"),
    ("ICP", "Indices of Consumer Prices", "ECB_ICP1", ("FREQ", "REF_AREA", "ADJUSTMENT", "ICP_ITEM", "STS_INSTITUTION", "ICP_SUFFIX"), "TIME_PERIOD"),
    ("BSI", "Balance Sheet Items", "ECB_BSI1", ("FREQ", "REF_AREA", "ADJUSTMENT", "BS_REP_SECTOR", "BS_ITEM", "MATURITY_ORIG"), "TIME_PERIOD"),
)


def _ref(id_, agency, package, cls, version="1.0", **extra) -> str:
    attrs = "".join(f' {k}="{v}"' for k, v in extra.items())
    return f'<Ref id="{id_}" version="{version}" agencyID="{agency}" package="{package}" class="{cls}"{attrs}/>'


def _dimension(agency: str, dsd: str, i: int, dim: str, time: bool = False) -> str:
    tag = "TimeDimension" if time else "Dimension"
    rep = ("<structure:LocalRepresentation><structure:TextFormat textType=\"ObservationalTimePeriod\"/></structure:LocalRepresentation>" if time else
           f"<structure:LocalRepresentation><structure:Enumeration>{_ref('CL_' + dim, agency, 'codelist', 'Codelist')}</structure:Enumeration></structure:LocalRepresentation>")
    return (f'<structure:{tag} id="{dim}" position="{i}" urn="urn:sdmx:org.sdmx.infomodel.datastructure.{tag}={agency}:{dsd}(1.0).{dim}">'
            f"<structure:ConceptIdentity>{_ref(dim, agency, 'conceptscheme', 'Concept', maintainableParentID='CS_' + agency, maintainableParentVersion='1.0')}"
            f"</structure:ConceptIdentity>{rep}</structure:{tag}>")


def structure_message(agency: str, flows, dimensions: bool = True, structures: bool = True) -> str:
    """An SDMX-ML 2.1 Structure message: the dataflows and, with `structures`, the data structure of each (what `references=datastructure` adds)."""
    parts = [f'<?xml version="1.0" encoding="UTF-8"?>\n<message:Structure {NS}>',
             f'<message:Header><message:ID>IDREF1</message:ID><message:Test>false</message:Test><message:Prepared>2026-10-01T00:00:00</message:Prepared>'
             f'<message:Sender id="{agency}"/></message:Header><message:Structures>']
    parts.append("<structure:Dataflows>")
    for flow, name, dsd, _dims, _time in flows:
        parts.append(f'<structure:Dataflow id="{flow}" urn="urn:sdmx:org.sdmx.infomodel.datastructure.Dataflow={agency}:{flow}(1.0)" agencyID="{agency}" '
                     f'version="1.0" isFinal="true"><common:Name xml:lang="en">{escape(name)}</common:Name>'
                     f"<structure:Structure>{_ref(dsd, agency, 'datastructure', 'DataStructure')}</structure:Structure></structure:Dataflow>")
    parts.append("</structure:Dataflows>")
    if not structures:
        parts.append("</message:Structures></message:Structure>")
        return "".join(parts)
    parts.append("<structure:DataStructures>")
    for _flow, name, dsd, dims, time in flows:
        body = ""
        if dimensions:
            body = ('<structure:DimensionList id="DimensionDescriptor" urn="urn:sdmx:org.sdmx.infomodel.datastructure.DimensionDescriptor='
                    f'{agency}:{dsd}(1.0).DimensionDescriptor">' + "".join(_dimension(agency, dsd, i, d) for i, d in enumerate(dims, 1))
                    + _dimension(agency, dsd, len(dims) + 1, time, True) + "</structure:DimensionList>")
        parts.append(f'<structure:DataStructure id="{dsd}" urn="urn:sdmx:org.sdmx.infomodel.datastructure.DataStructure={agency}:{dsd}(1.0)" agencyID="{agency}" '
                     f'version="1.0" isFinal="true"><common:Name xml:lang="en">{escape(name)}</common:Name>'
                     f"<structure:DataStructureComponents>{body}"
                     '<structure:MeasureList id="MeasureDescriptor"><structure:PrimaryMeasure id="OBS_VALUE" urn="urn:sdmx:org.sdmx.infomodel.datastructure.'
                     f'PrimaryMeasure={agency}:{dsd}(1.0).OBS_VALUE"><structure:ConceptIdentity>{_ref("OBS_VALUE", agency, "conceptscheme", "Concept", maintainableParentID="CS_" + agency, maintainableParentVersion="1.0")}'
                     "</structure:ConceptIdentity></structure:PrimaryMeasure></structure:MeasureList></structure:DataStructureComponents></structure:DataStructure>")
    parts.append("</structure:DataStructures></message:Structures></message:Structure>")
    return "".join(parts)


HTML_CHALLENGE = ('<!DOCTYPE html><html><head><title>Just a moment...</title></head><body><h1>Checking your browser before accessing the site.</h1>'
                  "</body></html>")

HOSTS = {"bis": "https://stats.bis.org/", "ecb": "https://data-api.ecb.europa.eu/"}

# --- BIS data: one SDMX-ML 2.1 StructureSpecificData message with two series (the harness corrupts BIS data only as text; this runs it once as a
# valid answer so that `bis.data` is executed)
BIS_DATA_NS = ('xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message" '
               'xmlns:ss="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/structurespecific" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')


def bis_data_message(series: tuple) -> str:
    rows = "".join(f'<Series FREQ="M" REF_AREA="{area}" TITLE="Policy rate {area}"><Obs TIME_PERIOD="2026-08" OBS_VALUE="{v}"/>'
                   f'<Obs TIME_PERIOD="2026-09" OBS_VALUE="{v + 1}"/></Series>' for area, v in series)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<message:StructureSpecificData {BIS_DATA_NS}><message:Header><message:ID>1</message:ID>'
            f'<message:Test>false</message:Test><message:Prepared>2026-10-01T00:00:00</message:Prepared><message:Sender id="BIS"/></message:Header>'
            f'<message:DataSet ss:structureRef="BIS_CBPOL" xsi:type="ss:DataSetType">{rows}</message:DataSet></message:StructureSpecificData>')


def build(ops) -> dict:
    """`ops` is tests.invariant_ops (for Op and Route). Returns {name: {"op": Op, "entries": ids, "browse": dimension ids}}. None of these join the JSON harness's
    tuples. A listing answer holds the dataflows only (`references=none`); a browse of one flow holds that flow and its data structure
    (`references=datastructure`); the multi-structure case holds three flows and their three structures, as a wildcard query answers."""
    Op, Route, request = ops.Op, ops.Route, ops.request

    def op(name, sid, req, text):
        return Op(name, sid, req, (Route("GET", HOSTS[sid], text),), ())

    cases = {}
    for sid, flows, agency in (("bis", BIS_FLOWS, "BIS"), ("ecb", ECB_FLOWS, "ECB")):
        listing, browse, several = f"{sid}.catalog (the dataflows)", f"{sid}.catalog (a dataflow's dimensions)", f"{sid}.catalog (a dataflow's dimensions, among several structures)"
        first = flows[0]
        cases[listing] = {"op": op(listing, sid, request("catalog", source=sid), structure_message(agency, flows, structures=False)),
                          "entries": tuple(f[0] for f in flows), "browse": None}
        cases[browse] = {"op": op(browse, sid, request("catalog", source=sid, within=first[0]), structure_message(agency, flows[:1])), "entries": None, "browse": first[3]}
        cases[several] = {"op": op(several, sid, request("catalog", source=sid, within=first[0]), structure_message(agency, flows)), "entries": None, "browse": first[3]}
        # an answer that is no structure message, or names no dimension, is never a successful empty catalogue
        for what, body, req in (("an HTML challenge page", HTML_CHALLENGE, request("catalog", source=sid)),
                                ("not XML at all", "this is not xml", request("catalog", source=sid)),
                                ("an empty body", "", request("catalog", source=sid)),
                                ("a dataflow whose data structure has no dimensions", structure_message(agency, flows[:1], dimensions=False),
                                 request("catalog", source=sid, within=first[0]))):
            name = f"{sid}.catalog ({what})"
            cases[name] = {"op": op(name, sid, req, body), "entries": None, "browse": None}
    cases["bis.data (two series)"] = {"op": op("bis.data (two series)", "bis", request("data", source="bis", params={"dataflow": "WS_CBPOL", "key": "M.US+XM"}),
                                               bis_data_message((("US", 4), ("XM", 2)))), "entries": None, "browse": None}
    return cases


# what the catalogue operations this package does not run are, and why (the coverage registry lists them; none is silently credited)
DEFERRED = {
    ("bis", "catalog", "dimension codes"): "PLAN.md D-32: the codes of one dimension (its codelist) are deferred; a browse stops at the dimension ids",
    ("ecb", "catalog", "dimension codes"): "PLAN.md D-32: the codes of one dimension (its codelist) are deferred; a browse stops at the dimension ids",
}
