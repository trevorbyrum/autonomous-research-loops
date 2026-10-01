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
  single   a lookup's one record (resolve, a data record): the answer is unreadable: `provider_unavailable`, `payload_invalid`, `unobserved`, no count, no record
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
from dataclasses import dataclass

TEXT_WRONG = (False, 0, 0.0, [], {}, 7, 1.5, True, ["x"], {"a": 1})


def get(body, path):
    for key in path:
        body = body[key]
    return body


def put(record, path, value):
    holder = record
    for key in path[:-1]:
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
    scope: str                      # member | single | whole
    p: tuple                        # the preferred field, a path inside the record
    p_valid: object
    a: tuple                        # the alternate
    a_valid: object
    doc: str                        # what makes both fields the provider's own, for the same meaning
    named: bool = False             # named by the 2b-repair-11 brief
    supported: bool = True          # the gateway reads A at all (see the module docstring); False: listed, not asserted
    wrong: tuple = TEXT_WRONG       # values of the wrong kind for A (and for P)
    note: str = ""

    def record(self, body):
        rec = get(body, self.container)
        return rec[0] if self.scope != "single" else rec

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
CANDIDATES: tuple = ()

PAIRS = tuple(p for p in (*NAMED, *CANDIDATES) if p.supported)
