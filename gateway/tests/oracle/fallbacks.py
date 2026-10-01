"""Alternatives beside a valid preferred value (R10-1). Task 2b-repair-11a.

R10-1 (Astra, gen2-2b-repair-10-astra-review-20261001.md): `text(a) or text(b)` validates `a` only when `a` is non-empty, so a present, malformed `b` beside a valid
`a` is never read. The metamorphic harness cannot see that: it corrupts the positions of its VALID answers, and a malformed field the gateway ignores leaves the
record exactly as the valid answer had it, which its invariants accept. The oracle states the rule from the contracts instead:

  STATION-CONTRACT.md §2 (task 2b-repair-9, R8-2): "The same rule reads every container and every typed field of a record ... one member whose title is a number is
  dropped and counted"; a lookup's one record that cannot be read is an unreadable answer; "a catalogue's entries ... one that cannot be read makes its whole
  catalogue answer unreadable". A field a provider documents for the same meaning as another, and that the gateway reads, is a typed field like any other: when it is
  PRESENT and of the wrong kind the member is unreadable, whatever its sibling says, in whichever order the two are read.

For each pair (the preferred field P and its alternate A, both documented by the provider) the oracle holds the answer with BOTH populated and valid (the control),
with A alone and malformed (the alternate IS read: the isolation Astra used), and with A malformed beside a valid P (the case R10-1 is about); and the mirror image,
P malformed beside a valid A. Expected outcome by `scope`:

  member   a list member: dropped and counted: the lane is `partial` (`payload_invalid`), `count` one fewer, `retrieved` the others in order, no record for it
  lookup   the first result of a lookup that reads only the first result of a list: the answer is unreadable: `provider_unavailable`, `payload_invalid`,
           `unobserved`, no count, no record ("one that cannot be read is an unreadable answer, never not found": STATION-CONTRACT.md §2)
  single   a lookup's one record (resolve, a data record): the same
  whole    a catalogue: the same, and no entries

Which pairs: the three the 2b-repair-11 brief names (DataCite `rightsIdentifier`/`rights`, BEA `Desc`/`Description`, OpenML `licence`/`license`) are asserted unconditionally.
The others are fields a provider's own documentation shows as carrying the same meaning, listed in `CANDIDATES` with the document; `supported` records whether the
gateway reads the alternate AT ALL, found once, before the pairs were written, by the isolation above (A alone malformed, P removed: is the member dropped?). That one
probe is a qualification of this oracle's independence (it ran the gateway to choose WHICH documented fields are supported; it supplied no expected value), and
evidence/2b-repair-11a/fallback-probe.* has its outcome for every candidate, supported or not. A candidate the gateway does not read is not asserted: a field it does not
support cannot be required to be validated. A pair listed as supported that stops being read fails its isolation case, so support cannot shrink unnoticed.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace

TEXT_WRONG = (False, 0, 0.0, [], {}, 7, 1.5, True, ["x"], {"a": 1})


def get(body, path):
    for key in path:
        body = body[key]
    return body


def put(record, path, value):
    """Set `path` inside `record`, creating the objects that are missing on the way (a documented optional object the fixture leaves out)."""
    holder = record
    for key in path[:-1]:
        if isinstance(holder, dict) and key not in holder:
            holder[key] = {}
        holder = holder[key]
    holder[path[-1]] = value


def drop(body, path):
    holder = body
    for key in path[:-1]:
        holder = holder[key]
    del holder[path[-1]]


@dataclass(frozen=True)
class Pair:
    name: str
    op: str                         # the harness operation (tests/invariant_ops.py) whose valid answer is the body
    container: tuple                # path to the list of members (scope member) or to the one record (scope single) or to the entries (scope whole)
    scope: str                      # member | lookup | single | whole
    p: tuple                        # the preferred field, a path inside the record
    p_valid: object
    a: tuple                        # the alternate
    a_valid: object
    doc: str                        # what makes both fields the provider's own, for the same meaning
    named: bool = False             # named by the 2b-repair-11 brief
    supported: bool | None = True   # the gateway reads A at all (see the module docstring); False: listed, not asserted; None: not probed yet
    wrong: tuple = TEXT_WRONG       # values of the wrong kind for A
    p_wrong: tuple | None = None    # values of the wrong kind for P, when P's type is not A's
    note: str = ""

    @property
    def wrong_for_p(self) -> tuple:
        return self.p_wrong if self.p_wrong is not None else self.wrong

    def record(self, body):
        rec = get(body, self.container)
        return rec if self.scope == "single" else rec[0]

    def both_valid(self, body):
        body = copy.deepcopy(body)
        rec = self.record(body)
        put(rec, self.p, copy.deepcopy(self.p_valid))
        put(rec, self.a, copy.deepcopy(self.a_valid))
        return body

    def with_(self, body, *, p=..., a=...):
        """Both valid, then P and/or A replaced (`...` leaves it; the module-level ABSENT removes it)."""
        body = self.both_valid(body)
        rec = self.record(body)
        for path, value in ((self.p, p), (self.a, a)):
            if value is ...:
                continue
            if value is ABSENT:
                drop(rec, path)
            else:
                put(rec, path, copy.deepcopy(value))
        return body


class _Absent:
    def __repr__(self):
        return "<absent>"


ABSENT = _Absent()

DATACITE_RIGHTS_DOC = ("DataCite OpenAPI `DoiPropertiesMetadata.rightsList[]` (evidence/2b-repair-7/docs/datacite-openapi.yaml): `rights` and `rightsIdentifier` are both "
                       "string properties of one rights statement (DataCite Metadata Schema 4, Rights: the statement and its SPDX identifier)")
BEA_DESC_DOC = ("BEA API user guide (evidence/2b-repair-11a/docs/bea-api-user-guide.pdf, p.10-12): a GetParameterValues entry has `Key` and `Desc` ('usually a description of "
                "the value'). `Description` is NOT in the guide: the 2b-repair-11 brief and Astra's R10-1 name it as read beside `Desc`, so this pair rests on the review, "
                "not on BEA's documentation")
OPENML_DOC = ("OpenML `Api_data.php` (evidence/2b-repair-7/docs, the data/{id} example): `licence`. The US spelling `license` is not in that document; the 2b-repair-11 brief "
              "and Astra's R10-1 name the listing as reading both, so this pair rests on the review, not on OpenML's documentation")

NAMED = (
    Pair("datacite.find: rightsIdentifier / rights", "datacite.find (a full page)", ("data",), "member",
         ("attributes", "rightsList", 0, "rightsIdentifier"), "cc0-1.0", ("attributes", "rightsList", 0, "rights"), "CC0 1.0 Universal", DATACITE_RIGHTS_DOC, named=True),
    Pair("datacite.resolve: rightsIdentifier / rights", "datacite.resolve", ("data",), "single",
         ("attributes", "rightsList", 0, "rightsIdentifier"), "cc0-1.0", ("attributes", "rightsList", 0, "rights"), "CC0 1.0 Universal", DATACITE_RIGHTS_DOC, named=True),
    Pair("bea.catalog values: Desc / Description", "bea.catalog (a parameter's values)", ("BEAAPI", "Results", "ParamValue"), "whole",
         ("Desc",), "d A", ("Description",), "d A", BEA_DESC_DOC, named=True),
    Pair("openml.find: licence / license", "openml.find (a full page)", ("data", "dataset"), "member",
         ("licence",), "Public", ("license",), "CC0-1.0", OPENML_DOC, named=True),
)

# Candidates beyond the named three: the fields a provider's documentation shows for one meaning. `supported` is filled in by the probe (module docstring).
LIST_WRONG = (False, True, 0, 7, 1.5, "x", {}, {"a": 1}, [1], [[]])
INT_WRONG = (False, True, "x", "7", 1.5, [], {}, [1])
DATE_WRONG = (False, 0, "x", [], ["x"], {"date-parts": "x"}, {"date-parts": ["x"]}, {"date-parts": [["x"]]})
CROSSREF = ("Crossref REST API swagger, `Work` (evidence/2b-repair-7/docs/crossref-swagger-docs.json): ")
DATACITE = ("DataCite OpenAPI `DoiPropertiesMetadata` (evidence/2b-repair-7/docs/datacite-openapi.yaml): ")
OPENAIRE = ("OpenAIRE Graph API V1 spec `GraphResult`, `Author`, `Instance`, `ResultPid` (evidence/2b-repair-7/docs/openaire-graph-v1-spec.json): ")
S2DOC = ("Semantic Scholar Graph API swagger `BasePaper` (evidence/2b-repair-7/docs/semanticscholar-graph-swagger.json): ")
OPENML_PHP = ("OpenML `Api_data.php` data/{id} example (evidence/2b-repair-7/docs/openml-server-api-data-php.php, lines 745-780): ")
DOAJ_SW = ("DOAJ API swagger `bibjson` of a journal (evidence/2b-repair-7/docs/doaj-swagger.json): ")


def _crossref(scope: str):
    op, container = ("crossref.find (a full page)", ("message", "items")) if scope == "member" else ("crossref.resolve", ("message",))
    kw = dict(op=op, container=container, scope=scope)
    date = lambda y: {"date-parts": [[2021, y]]}  # noqa: E731
    out = [
        Pair(f"crossref.{scope}: container-title / short-container-title", p=("container-title",), p_valid=["J"], a=("short-container-title",), a_valid=["J."],
             doc=CROSSREF + "`container-title` and `short-container-title` are both arrays of strings naming the container", wrong=LIST_WRONG, **kw),
        Pair(f"crossref.{scope}: issued / published-print", p=("issued",), p_valid=date(3), a=("published-print",), a_valid=date(3),
             doc=CROSSREF + "`issued` and `published-print` are both `DateParts`", wrong=DATE_WRONG, **kw),
        Pair(f"crossref.{scope}: issued / published-online", p=("issued",), p_valid=date(3), a=("published-online",), a_valid=date(2),
             doc=CROSSREF + "`issued` and `published-online` are both `DateParts`", wrong=DATE_WRONG, **kw),
        Pair(f"crossref.{scope}: issued / published", p=("issued",), p_valid=date(3), a=("published",), a_valid=date(3),
             doc=CROSSREF + "`issued` and `published` are both `DateParts`", wrong=DATE_WRONG, **kw),
        Pair(f"crossref.{scope}: URL / resource.primary.URL", p=("URL",), p_valid="https://doi.org/10.1000/a1", a=("resource", "primary", "URL"),
             a_valid="https://example.org/a1", doc=CROSSREF + "`URL` and `Resources.primary.URL` are both strings naming where the work is", **kw),
        Pair(f"crossref.{scope}: ISSN / issn-type", p=("ISSN",), p_valid=["1234-5679"], a=("issn-type",), a_valid=[{"type": "print", "value": "1234-5679"}],
             doc=CROSSREF + "`ISSN` (array of strings) and `issn-type` (array of `WorkISSNType`: type and value) both give the work's ISSNs", wrong=LIST_WRONG, **kw),
        Pair(f"crossref.{scope}: reference-count / references-count", p=("reference-count",), p_valid=0, a=("references-count",), a_valid=0,
             doc=CROSSREF + "`reference-count` and `references-count` are both integers", wrong=INT_WRONG, **kw),
    ]
    return out


def _datacite(scope: str):
    op, container = ("datacite.find (a full page)", ("data",)) if scope == "member" else ("datacite.resolve", ("data",))
    kw = dict(op=op, container=container, scope=scope)
    return [
        Pair(f"datacite.{scope}: rightsIdentifier / rightsUri", p=("attributes", "rightsList", 0, "rightsIdentifier"), p_valid="cc0-1.0",
             a=("attributes", "rightsList", 0, "rightsUri"), a_valid="https://creativecommons.org/publicdomain/zero/1.0/", doc=DATACITE_RIGHTS_DOC.replace("`rights` and", "`rightsUri` and"), **kw),
        Pair(f"datacite.{scope}: publicationYear / dates", p=("attributes", "publicationYear"), p_valid=2021, a=("attributes", "dates"),
             a_valid=[{"date": "2021-05-01", "dateType": "Issued"}], doc=DATACITE + "`publicationYear` (integer) and `dates[]` (date and dateType: 'Issued') both give when it was issued",
             wrong=LIST_WRONG, p_wrong=INT_WRONG, **kw),
        Pair(f"datacite.{scope}: creator name / givenName", p=("attributes", "creators", 0, "name"), p_valid="A", a=("attributes", "creators", 0, "givenName"), a_valid="A",
             doc=DATACITE + "a creator has `name` (the full name) and `givenName`, `familyName` (its parts), all strings", **kw),
        Pair(f"datacite.{scope}: creator name / familyName", p=("attributes", "creators", 0, "name"), p_valid="A", a=("attributes", "creators", 0, "familyName"), a_valid="B",
             doc=DATACITE + "a creator has `name` and `familyName`, both strings", **kw),
    ]


def _openaire(scope: str):
    op, container = ("openaire.find (a full page)", ("results",)) if scope == "member" else ("openaire.resolve", ("results",))
    scope = "member" if scope == "member" else "lookup"
    kw = dict(op=op, container=container, scope=scope)
    return [
        Pair(f"openaire.{scope}: publicationDate / instances.publicationDate", p=("publicationDate",), p_valid="2024-05-01", a=("instances", 0, "publicationDate"),
             a_valid="2024-05-01", doc=OPENAIRE + "`GraphResult.publicationDate` and `Instance.publicationDate` are both strings", **kw),
        Pair(f"openaire.{scope}: author fullName / name", p=("authors", 0, "fullName"), p_valid="A", a=("authors", 0, "name"), a_valid="A",
             doc=OPENAIRE + "`Author.fullName` and `Author.name` are both strings", **kw),
        Pair(f"openaire.{scope}: author fullName / surname", p=("authors", 0, "fullName"), p_valid="A", a=("authors", 0, "surname"), a_valid="Z",
             doc=OPENAIRE + "`Author.fullName` and `Author.surname` are both strings", **kw),
        Pair(f"openaire.{scope}: instances.alternateIdentifiers / pids", p=("instances", 0, "alternateIdentifiers"),
             p_valid=[{"scheme": "doi", "value": "10.46298/abc1"}], a=("pids",), a_valid=[{"scheme": "doi", "value": "10.46298/abc1"}],
             doc=OPENAIRE + "`Instance.alternateIdentifiers` and `GraphResult.pids` are both arrays of `ResultPid` (scheme, value)", wrong=LIST_WRONG, **kw),
    ]


def _s2(scope: str):
    op, container = ("semanticscholar.find (a next offset)", ("data",)) if scope == "member" else ("semanticscholar.resolve", ())
    kw = dict(op=op, container=container, scope=scope)
    return [
        Pair(f"semanticscholar.{scope}: year / publicationDate", p=("year",), p_valid=2021, a=("publicationDate",), a_valid="2021-03-01",
             doc=S2DOC + "`year` (integer) and `publicationDate` (YYYY-MM-DD) both give when the paper was published", p_wrong=INT_WRONG, **kw),
        Pair(f"semanticscholar.{scope}: venue / publicationVenue.name", p=("venue",), p_valid="V", a=("publicationVenue", "name"), a_valid="V",
             doc=S2DOC + "`venue` (string) and `publicationVenue` (object with `name`) both name the venue", **kw),
        Pair(f"semanticscholar.{scope}: venue / journal.name", p=("venue",), p_valid="V", a=("journal", "name"), a_valid="V",
             doc=S2DOC + "`venue` (string) and `journal` (object with `name`) both name the venue", **kw),
    ]


_RAW = (
    *_crossref("member"), *_crossref("single"),
    *_datacite("member"), *_datacite("single"),
    *_openaire("member"), *_openaire("lookup"),
    *_s2("member"), *_s2("single"),
    Pair("openml.resolve: licence / license", "openml.resolve", ("data_set_description",), "single", ("licence",), "Public", ("license",), "CC0-1.0", OPENML_DOC),
    Pair("openml.fetch: licence / license", "openml.fetch (a dataset's file links)", ("data_set_description",), "single", ("licence",), "Public", ("license",), "CC0-1.0", OPENML_DOC),
    Pair("openml.resolve: version / version_label", "openml.resolve", ("data_set_description",), "single", ("version",), "1", ("version_label",), "1",
         OPENML_PHP + "`version` and `version_label` are both strings of one dataset version"),
    Pair("doaj.resolve (journal): pissn / eissn", "doaj.resolve (a journal by its ISSN)", ("results",), "lookup", ("bibjson", "pissn"), "1234-5679", ("bibjson", "eissn"), "2345-6787",
         DOAJ_SW + "`pissn` and `eissn` are both strings, the journal's two ISSNs"),
)

# The probe of 2026-10-01 (evidence/2b-repair-11a/fallback-probe.txt): of these 40 documented candidates, the alternates the gateway READS (A alone and malformed is
# rejected for every wrong value) are the two below; the other 38 are ignored when malformed even with the preferred field absent, so the gateway does not support them
# and nothing is asserted about them. The OpenAIRE pair already passes its beside-case; it is asserted so that it keeps passing.
READ_BY_PROBE = frozenset({"openaire.member: instances.alternateIdentifiers / pids", "openaire.lookup: instances.alternateIdentifiers / pids"})
CANDIDATES = tuple(replace(p, supported=p.name in READ_BY_PROBE) for p in _RAW)

PAIRS = tuple(p for p in (*NAMED, *CANDIDATES) if p.named or p.supported)
