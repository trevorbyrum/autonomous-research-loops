"""Hand-written expected canonical records for the valid answer of every harness operation (task 2b-repair-10a, R9-4).

Why: the harness took `run(op, valid)[0]` as the baseline a corrupted answer is compared with, so a mutant that erased every title from the
valid answer too passed. These expectations are written from the fixture data (tests/invariant_ops.py, read as data) and the documents below,
not from what the gateway answers. They were committed (e4b7eac) before the first comparison with the gateway, and several were changed or removed after it (GovInfo `kind`, an
inherited OpenML licence expectation, the venue field names of the loaders: evidence/2b-repair-10a/corrections-after-observation.md; the qualifications are in
evidence/2b-repair-11a/independence-statement.md). A field is left out, with the reason in `UNDOCUMENTED`, wherever no document decides it.

A field is asserted only when all three hold:
  1. the canonical field's NAME is documented: it is shown by the record sample the engine's contract fixtures ship
     (gen2/tests/fixtures/gateway_answers/find_complete.json: one Crossref work, raw and canonical side by side), or named by
     STATION-CONTRACT.md / LICENSING.md / PLAN.md (`file_count`, `row_count`, `license`, `attribution`, kinds `venue`, `repository`);
  2. the provider's own field of that meaning is unambiguous in the fixture (its schema names it: DataCite `titles[].title`, DOAJ
     `bibjson.journal.title`, OpenAIRE `mainTitle`, ...). A date that is a modification or upload date is not a publication year;
  3. the REPRESENTATION is shown by the sample: `title` text, `authors` a list of display names (`given family`, or `name`), `year` a whole
     number, `venue` and `publisher` text, `license` the licence the source REPORTED (LICENSING.md: "the CONTENT licence that source reported
     for the work itself"), `identifiers` a map with the DOI lowercased (and an ISSN hyphenated), counts whole numbers.

Source tags (each expectation carries one; tests/test_oracle.py writes them out beside the failing ones):
  pair      the Crossref raw-to-canonical pair of find_complete.json (title[0] -> title, "given family" -> authors, issued date-parts[0][0] ->
            year, container-title[0] -> venue, license[0].URL -> license, is-referenced-by-count -> cited_by_count, reference-count ->
            reference_count, URL -> links, DOI lowercased -> identity `doi:` and identifiers.doi)
  schema    the provider's own field of the same meaning as the canonical field (provider documentation: the evidence copies in
            private/evidence/2b-repair-7/docs, or the provider's published schema)
  contract  STATION-CONTRACT.md, LICENSING.md, PLAN.md or INVARIANTS.md say so
  rule      an identity rule: a work with a DOI is identified by it, lowercased (`doi:<doi>`); a file member is `<parent>#<its file id or name>`
  harness   the identity SCHEME (`series:fred:GDP`, `table:bea:NIPA:T10101`, `kaggle:o/d1`) is documented nowhere but the harness's own
            operation table, which says it was written by hand from the providers' documentation; used for the scheme only, never for a value
"""
from __future__ import annotations

from dataclasses import dataclass


class CI(str):
    """A licence identifier the source reported: the same identifier in another case is the same licence; another identifier is not."""


@dataclass(frozen=True)
class Has:
    """A map or list that holds at least these entries."""
    items: object


class Somewhere(str):
    """The value appears in some field of the record: the NAME of the field is undocumented (registry-loader venues), the value is not."""


@dataclass(frozen=True)
class F:
    value: object
    src: str


@dataclass(frozen=True)
class Rec:
    identity: str
    fields: dict                      # canonical field -> F(expected value, source tag)

    def __post_init__(self):
        assert all(isinstance(v, F) for v in self.fields.values()), self.identity


def rec(identity: str, **fields) -> Rec:
    """`rec("doi:..", title=("T", "schema"))`: the pairs are (value, source tag)."""
    return Rec(identity, {k: F(*v) for k, v in fields.items()})


DOI = "rule"


# ------------------------------------------------------------------ articles
def crossref(i: int) -> Rec:
    d = f"10.1000/a{i}"
    return rec(f"doi:{d}", title=(f"T{i}", "pair"), authors=(["A B"], "pair"), year=(2021, "pair"), venue=("J", "pair"), publisher=("P", "pair"),
               license=("https://example.org/license", "pair"), type=("journal-article", "pair"), links=([f"https://doi.org/{d}"], "pair"),
               identifiers=(Has({"doi": d, "issn": "1234-5679"}), "pair"), cited_by_count=(1, "pair"), reference_count=(0, "pair"))


def crossref_find(i: int) -> Rec:
    r = crossref(i)
    return Rec(r.identity, {**r.fields, "kind": F("article", "pair")})


def datacite(i: int, doi: str | None = None, kind: bool = True) -> Rec:
    d = doi or f"10.1000/d{i}"
    f = dict(title=(f"T{i}", "schema"), authors=(["A"], "schema"), year=(2021, "schema"), publisher=("P", "schema"),
             license=(CI("cc0-1.0"), "contract"), identifiers=(Has({"doi": d}), "pair"))
    if kind:
        f["kind"] = ("dataset", "contract")
    return rec(f"doi:{d}", **f)


def doaj_article(i: int) -> Rec:
    return rec(f"doi:10.1000/j{i}", kind=("article", "contract"), title=(f"T{i}", "schema"), authors=(["A"], "schema"), year=(2021, "schema"),
               venue=("J", "schema"), license=(CI("CC BY"), "contract"), identifiers=(Has({"doi": f"10.1000/j{i}", "issn": "1234-5679"}), "schema"))


def epmc(i: int, kind: bool = True) -> Rec:
    f = dict(title=(f"T{i}", "schema"), year=(2021, "schema"), venue=("J", "schema"), identifiers=(Has({"doi": f"10.1000/e{i}"}), "pair"))
    if kind:
        f["kind"] = ("article", "contract")
    return rec(f"doi:10.1000/e{i}", **f)


def s2(i: int, kind: bool = True) -> Rec:
    f = dict(title=(f"T{i}", "schema"), authors=(["A"], "schema"), year=(2021, "schema"), venue=("V", "schema"), identifiers=(Has({"doi": f"10.1000/s{i}"}), "pair"))
    if kind:
        f["kind"] = ("article", "contract")
    return rec(f"doi:10.1000/s{i}", **f)


def openaire(i: int, kind: bool = True) -> Rec:
    f = dict(title=(f"T{i}", "schema"), authors=(["A"], "schema"), year=(2024, "schema"), license=(CI("CC BY"), "contract"),
             identifiers=(Has({"doi": f"10.46298/abc{i}"}), "pair"))
    if kind:
        f["kind"] = ("article", "contract")
    return rec(f"doi:10.46298/abc{i}", **f)


# ------------------------------------------------------------------ datasets
def govinfo_find(i: int) -> Rec:
    # no `kind`: PLAN.md §3 calls GovInfo's packages DOCUMENTS ("D(documents)") while routing treats the lane as a dataset lane, so the documents disagree
    # with themselves about the kind of a GovInfo record (corrected after the first comparison: see UNDOCUMENTED and the evidence log)
    return rec(f"govinfo:CRPT-{i}", title=(f"T{i}", "schema"), year=(2023, "schema"))


def dataverse_find(i: int) -> Rec:
    return rec(f"doi:10.7910/dvn/x{i}", kind=("dataset", "contract"), title=(f"N{i}", "schema"), authors=(["B"], "schema"), year=(2021, "schema"),
               identifiers=(Has({"doi": f"10.7910/dvn/x{i}"}), "pair"))


def hf(i: int, kind: bool = True) -> Rec:
    f = dict(license=(CI("cc-by-4.0"), "contract"), file_count=(2, "contract"))
    if kind:
        f["kind"] = ("dataset", "contract")
    return rec(f"hf:o/d{i}", **f)


def kaggle_find(i: int) -> Rec:
    return rec(f"kaggle:o/d{i}", kind=("dataset", "contract"), title=(f"T{i}", "schema"))


def openml_find(i: int) -> Rec:
    return rec(f"openml:{60 + i}", kind=("dataset", "contract"), title=(f"iris{i}", "schema"))


def socrata_find(i: int) -> Rec:
    return rec(f"socrata:data.example.gov:abcd-123{i}", kind=("dataset", "contract"), title=(f"N{i}", "schema"), license=(CI("Public Domain"), "contract"))


# ------------------------------------------------------------------ the expectations, by operation name (the names of tests/invariant_ops.py)
EXPECTED: dict = {
    "crossref.find (a full page)": tuple(crossref_find(i) for i in (1, 2, 3)),
    "crossref.find (a short page)": tuple(crossref_find(i) for i in (1, 2)),
    "datacite.find (a full page)": tuple(datacite(i) for i in (1, 2, 3)),
    "datacite.find (the page that reaches the total)": tuple(datacite(i) for i in (1, 2, 3)),
    "doaj.find (a full page)": tuple(doaj_article(i) for i in (1, 2, 3)),
    "doaj.find (the page that reaches the total)": tuple(doaj_article(i) for i in (1, 2, 3)),
    "europepmc.find": tuple(epmc(i) for i in (1, 2, 3)),
    "govinfo.find": tuple(govinfo_find(i) for i in (1, 2, 3)),
    "harvard_dataverse.find (a full page)": tuple(dataverse_find(i) for i in (1, 2, 3)),
    "harvard_dataverse.find (the page that reaches the total)": tuple(dataverse_find(i) for i in (1, 2, 3)),
    "huggingface.find (a Link to the next page)": tuple(hf(i) for i in (1, 2, 3)),
    "huggingface.find (no Link header)": tuple(hf(i) for i in (1, 2, 3)),
    "kaggle.find": tuple(kaggle_find(i) for i in (1, 2, 3)),
    "openaire.find (a full page)": tuple(openaire(i) for i in (1, 2, 3)),
    "openaire.find (the first page holds every match)": tuple(openaire(i) for i in (1, 2, 3)),
    "openml.find (a full page)": tuple(openml_find(i) for i in (1, 2, 3)),
    "openml.find (a short page)": tuple(openml_find(i) for i in (1, 2)),
    "semanticscholar.find (a next offset)": tuple(s2(i) for i in (1, 2, 3)),
    "semanticscholar.find (no next offset)": tuple(s2(i) for i in (1, 2, 3)),
    "socrata.find (a full page)": tuple(socrata_find(i) for i in (1, 2, 3)),
    "socrata.find (the page that reaches the size)": tuple(socrata_find(i) for i in (1, 2, 3)),

    # --- resolve: the kind of a looked-up record is not documented, so it is left out
    "crossref.resolve": (crossref(1),),
    "datacite.resolve": (datacite(1, doi="10.9101/d1", kind=False),),
    "openaire.resolve": (openaire(1, kind=False),),                          # the first of the two results, never the second
    "doaj.resolve (a journal by its ISSN)": (rec("issn:1234-5679", kind=("venue", "contract"), title=("J1", "schema"), publisher=("P", "schema"),
                                                  license=(CI("CC BY"), "contract")),),
    "europepmc.resolve": (epmc(1, kind=False),),
    "huggingface.resolve": (hf(1, kind=False),),
    "openml.resolve": (rec("openml:61", title=("iris", "schema"), license=(CI("Public"), "contract"), authors=(["R.A. Fisher"], "schema")),),
    "semanticscholar.resolve": (s2(1, kind=False),),
    "socrata.resolve": (rec("socrata:data.example.gov:abcd-1231", title=("N", "schema"), license=(CI("Public Domain"), "contract")),),
    "govinfo.resolve": (rec("govinfo:CRPT-1", title=("T", "schema"), year=(2023, "schema")),),

    # --- enrich: the records a lane returns are the cited or citing works, a work's open-access locations, or its full-text copy
    "crossref.enrich references": tuple(rec(f"doi:10.2000/r{i}", title=(f"R{i}", "schema"), year=(2020, "schema")) for i in (1, 2, 3)),
    "semanticscholar.enrich citations": tuple(rec(f"doi:10.9000/c{i}", title=(f"T{i}", "schema"), year=(2022, "schema"), venue=("V", "schema")) for i in (1, 2, 3)),
    "semanticscholar.enrich references": tuple(rec(f"doi:10.9000/c{i}", title=(f"T{i}", "schema"), year=(2022, "schema"), venue=("V", "schema")) for i in (1, 2, 3)),
    "opencitations.enrich citations": tuple(rec(f"doi:10.9000/c{i}") for i in (1, 2, 3)),
    "opencitations.enrich references": tuple(rec(f"doi:10.8000/r{i}") for i in (1, 2, 3)),
    "opencitations.enrich metadata": (rec("doi:10.1000/a1", title=("T1", "schema"), year=(2020, "schema"), venue=("V", "schema")),),
    "unpaywall.enrich oa_location": (rec("doi:10.1000/a1", title=("T", "schema"), year=(2021, "schema"), venue=("J", "schema")),) * 3,
    "core.enrich full_text": (rec("doi:10.1000/a1", title=("T", "schema"), authors=(["A"], "schema"), year=(2021, "schema"), publisher=("P", "schema")),),

    # --- data: series and tables. Only the identity scheme (harness) and what the fixture's own field plainly names
    "bls.data": tuple(rec(f"series:bls:S{i}", title=(f"T{i}", "schema")) for i in (1, 2, 3)),
    "ecb.data": tuple(rec(f"series:ecb:EXR:D.{c}") for c in ("USD", "GBP", "CHF")),
    "ecb.data (one data set)": tuple(rec(f"series:ecb:EXR:D.{c}") for c in ("USD", "GBP", "CHF")),
    "fred.data (the observations)": (rec("series:fred:GDP", title=("GDP", "schema")),),
    "fred.data (the series metadata)": (rec("series:fred:GDP", title=("GDP", "schema")),),
    "bea.data (GetData)": (rec("table:bea:NIPA:T10101", row_count=(2, "contract")),),
    "bea.data (GETDATASETLIST)": (rec("table:bea:GETDATASETLIST", row_count=(2, "contract")),),
    "census.data": (rec("table:census:2022/acs/acs1:NAME,B01001_001E"),),

    # --- fetch: a dataset's files. A member is `<dataset>#<file>`; the file's own id or name is in the fixture
    "harvard_dataverse.fetch (a dataset's files)": tuple(rec(f"doi:10.7910/dvn/x1#{900 + i}") for i in (1, 2, 3)),
    "huggingface.fetch (a dataset's files)": tuple(rec(f"hf:o/d1#f1-{k}.csv") for k in range(3)),
    "kaggle.fetch (a dataset's files)": tuple(rec(f"kaggle:o/d1#f{i}.csv") for i in (1, 2, 3)),
    "govinfo.fetch (a package's formats)": (rec("govinfo:CRPT-1#pdf"), rec("govinfo:CRPT-1#txt")),
    "socrata.fetch (the rows)": (rec("socrata:data.example.gov:abcd-1231#rows", row_count=(2, "contract")),),
    "openml.fetch (a dataset's file links)": (rec("openml:61#dataset_61.pq"), rec("openml:61#iris.arff")),
}

# catalogue entries are named by the provider's own identifiers, in the provider's order (PLAN.md D-32); nothing else is asserted about them
CATALOG_ENTRIES: dict = {
    "bea.catalog (the datasets)": ("NIPA", "Regional", "ITA"),
    "bea.catalog (a dataset's parameters)": ("Frequency", "Year", "TableName"),
    "bea.catalog (a parameter's values)": ("A", "Q", "M"),
    "bls.catalog (the surveys)": ("CU", "LA", "CE"),
    "bls.catalog (a survey's popular series)": ("CUUR0000SA0", "CUUR0000SA0L1E", "CUSR0000SA0"),
    "census.catalog (the datasets)": ("2022/acs/acs1", "2022/acs/acs3", "2022/acs/acs5"),
    "census.catalog (a dataset's variables)": ("B01001_001E", "B01001_002E", "B01001_003E"),
    "fred.catalog (a search)": ("GDP", "GDPC1", "GDPPOT"),
    "fred.catalog (one series)": ("GDP", "GDPC1", "GDPPOT"),
}

# Left out, and why. Reported with the failing cases so nobody mistakes a gap for a pass.
UNDOCUMENTED: dict = {
    "*": "`links`: which provider field becomes a record's link is documented only for Crossref (URL). `type`: only Crossref's is shown. `kind` of a "
         "looked-up (resolve, enrich, data, fetch) record: no document says. `attribution`, `permissions`, `freshness_lag`, `metadata_license`: "
         "per-source registry facts (LICENSING.md), not per-fixture values.",
    "huggingface.*": "`title`, `authors`, `year`: a Hub dataset has no title, its `author` is its owner, and `lastModified` is a modification date.",
    "kaggle.*": "`authors` (`ownerName` is an owner), `year` (`lastUpdated` is a modification date).",
    "socrata.*": "`year` (`updatedAt` is a modification date), `links` (`permalink`).",
    "openml.*": "`year` (`upload_date` is an upload date), `format`, `version`.",
    "europepmc.*": "`authors`: `authorString` is one string holding a list in Europe PMC's own convention; how it is split is not documented.",
    "govinfo.*": "`authors`: `governmentAuthor1` names an issuing body, not a person. `kind` of a package from `find kind=dataset`: PLAN.md §3 calls the packages "
                 "documents, the seed and routing treat the lane as a dataset lane; the documents do not decide it.",
    "openml.resolve (license only)": "`license`: OpenML documents the British spelling `licence` only (Api_data.php); what the US spelling means is not documented, so this "
                                     "variant asserts nothing about it (it exists so that the harness corrupts it).",
    "census.data": "`row_count`: whether a table's header row is a row is not documented.",
    "fred.*": "`observations`: whether the record's field is the list or its length is not documented.",
    "ecb.*": "`title`: an SDMX series has no title in the fixture; its identity is its dataflow and key.",
    "catalog entries": "everything but the provider's identifier: what an entry's name and description are called is not documented.",
}
