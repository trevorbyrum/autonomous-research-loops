"""The adapter operations the invariant harness (tests/test_invariants.py) corrupts, one `Op` each.

An `Op` is a provider-shaped answer an adapter operation reads, plus what a reader of the provider's documentation
knows about it, written here by hand and never derived from the adapter:

  * `routes`: the requests the operation makes and the answer to each; the one that is corrupted is marked.
  * `levels` / `single`: where the answer's members stand (the lists or keyed objects each of which holds independent
    candidates, outermost first; or the one record a lookup reads), and `ids`, the identity each member names.
  * `end`: the alternative sets of fields the provider's end rule reads (docs/PROVIDER-PAGINATION.md); `cursor`: the
    fields a continuation is made from. A field is `(path, kind)`: kinds are in `test_invariants.readable`.
  * `shared`: fields every member needs to be read at all (a dataset's own identity, a message's structure).

What an Op deliberately does not say: how the adapter reads any of it. The harness runs the real adapter and the real
router against corrupted copies of `routes[corrupt].body` and compares the answer with these statements only.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

# ------------------------------------------------------------------ the vocabulary


@dataclass(frozen=True)
class Level:
    """A container whose elements are the next level's holders, or (the last level) the members themselves."""
    path: tuple                         # keys from the parent element (or the answer) to the container
    kind: type = list                   # list, or dict for a keyed container (SDMX series, keyed by position)
    optional_from: int | None = None    # index into `path` from which a missing or null key is a permitted empty
    take: int | None = None             # a lookup reads only the first `take` elements


@dataclass(frozen=True)
class Route:
    method: str
    url: str
    body: object
    headers: dict | None = None
    corrupt: bool = False               # the answer the harness corrupts (exactly one per Op)


@dataclass(frozen=True)
class Op:
    name: str
    sid: str
    request: dict
    routes: tuple
    ids: tuple
    levels: tuple = ()
    single: tuple | None = None         # the one record of a lookup: its path in the answer
    explicit: tuple = ()                # members that are fields, not elements of a container: a link the answer carries, or not (leaf "url")
    shared: tuple = ()
    end: tuple = ()                     # alternatives; each a tuple of (path, kind) all of which the end rule reads
    cursor: tuple = ()                  # fields a continuation is made from
    find: bool = False
    exhausted: bool = False             # what the valid answer must say
    continues: bool = False
    zero_counts: tuple = ()             # (record field, path of the holder it counts relative to the member, whether the holder may be left out)
    unknowable: tuple = ()              # record fields that are honestly None (unknown) when what they count cannot be read, and never zero
    agency: str | None = None           # a DOI lookup is routed by the registration agency doi.org names
    whole: bool = False                 # an answer read whole: one member that cannot be read makes it unreadable
    bare_row: bool = False              # a list of one may come as the one object (BEA's habit): a non-empty object holds one member
    empty_when: tuple = ()              # (holder path, count path): the provider may leave the holder out only when its count is the whole number zero
    leaf: str = "object"                # what a member is: an object, a list, any value (a keyed entry whose key is all that is read), or a "url" (text; empty is none)
    typed: bool = True                  # a lane's failure on a garbled answer must be a PayloadError
    seed: dict | None = None            # what the registry row says differently, so the router plans this lane (OpenAIRE is no discovery lane)


def corrupt_route(op: Op) -> Route:
    return next(r for r in op.routes if r.corrupt)


# ------------------------------------------------------------------ Crossref
def crossref_work(i: int) -> dict:
    return {"DOI": f"10.1000/A{i}", "URL": f"https://doi.org/10.1000/a{i}", "type": "journal-article", "title": [f"T{i}"],
            "author": [{"given": "A", "family": "B"}], "issued": {"date-parts": [[2021, 3]]}, "container-title": ["J"],
            "ISSN": ["1234-5679"], "license": [{"URL": "https://example.org/license"}], "publisher": "P",
            "is-referenced-by-count": 1, "reference-count": 0}


def crossref_page(n: int, cursor: str | None) -> dict:
    message = {"total-results": 9, "items": [crossref_work(i) for i in range(1, n + 1)]}
    if cursor:
        message["next-cursor"] = cursor
    return {"status": "ok", "message-type": "work-list", "message": message}


CROSSREF_IDS = tuple(f"doi:10.1000/a{i}" for i in (1, 2, 3))
FIND = {"request_type": "find", "kind": "article", "query": "q", "limit": 3}
CROSSREF_URL = "https://api.crossref.org/works"

CROSSREF_FIND_MORE = Op(
    "crossref.find (a full page)", "crossref", FIND, (Route("GET", CROSSREF_URL, crossref_page(3, "AoE/cursor-1"), corrupt=True),),
    CROSSREF_IDS, levels=(Level(("message", "items")),), end=((( ("message", "items"), "list"),),),
    cursor=((("message", "next-cursor"), "token"),), find=True, continues=True)
CROSSREF_FIND_END = replace(
    CROSSREF_FIND_MORE, name="crossref.find (a short page)", routes=(Route("GET", CROSSREF_URL, crossref_page(2, None), corrupt=True),),
    ids=CROSSREF_IDS[:2], continues=False, exhausted=True)

# ------------------------------------------------------------------ DataCite
DATACITE_URL = "https://api.datacite.org/dois"


def datacite_item(i: int) -> dict:
    return {"id": f"10.1000/d{i}", "attributes": {"doi": f"10.1000/d{i}", "titles": [{"title": f"T{i}"}], "creators": [{"name": "A"}],
                                                   "publicationYear": 2021, "publisher": "P", "types": {"resourceTypeGeneral": "Dataset"},
                                                   "rightsList": [{"rightsIdentifier": "cc0-1.0"}], "url": f"https://example.org/d{i}"},
            "relationships": {"client": {"data": {"id": "c"}}}}


def datacite_page(n: int, total: int) -> dict:
    return {"data": [datacite_item(i) for i in range(1, n + 1)], "meta": {"total": total, "totalPages": 3}}


DATASET_FIND = {"request_type": "find", "kind": "dataset", "query": "q", "limit": 3}
DATACITE_IDS = tuple(f"doi:10.1000/d{i}" for i in (1, 2, 3))
DATACITE_FIND_MORE = Op(
    "datacite.find (a full page)", "datacite", DATASET_FIND, (Route("GET", DATACITE_URL, datacite_page(3, 9), corrupt=True),), DATACITE_IDS,
    levels=(Level(("data",)),), end=(((("meta", "total"), "total"),),), cursor=((("meta", "total"), "total"),), find=True, continues=True)
DATACITE_FIND_END = replace(
    DATACITE_FIND_MORE, name="datacite.find (the page that reaches the total)", routes=(Route("GET", DATACITE_URL, datacite_page(3, 3), corrupt=True),),
    continues=False, exhausted=True)

# ------------------------------------------------------------------ DOAJ
DOAJ_URL = "https://doaj.org/api/search/articles/"


def doaj_article(i: int) -> dict:
    return {"id": f"j{i}", "bibjson": {"title": f"T{i}", "year": "2021", "identifier": [{"type": "doi", "id": f"10.1000/j{i}"}],
                                       "author": [{"name": "A"}], "journal": {"title": "J", "issns": ["1234-5679"], "license": [{"type": "CC BY"}]},
                                       "link": [{"url": f"https://example.org/j{i}"}]}}


DOAJ_IDS = tuple(f"doi:10.1000/j{i}" for i in (1, 2, 3))
DOAJ_FIND_MORE = Op(
    "doaj.find (a full page)", "doaj", FIND, (Route("GET", DOAJ_URL, {"total": 9, "results": [doaj_article(i) for i in (1, 2, 3)]}, corrupt=True),),
    DOAJ_IDS, levels=(Level(("results",)),), end=(((("total",), "total"),),), cursor=((("total",), "total"),), find=True, continues=True)
DOAJ_FIND_END = replace(
    DOAJ_FIND_MORE, name="doaj.find (the page that reaches the total)",
    routes=(Route("GET", DOAJ_URL, {"total": 3, "results": [doaj_article(i) for i in (1, 2, 3)]}, corrupt=True),), continues=False, exhausted=True)

# ------------------------------------------------------------------ Europe PMC
EPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def epmc_record(i: int) -> dict:
    return {"id": str(i), "source": "MED", "pmid": str(i), "doi": f"10.1000/e{i}", "title": f"T{i}", "authorString": "A B.", "pubYear": "2021",
            "journalTitle": "J"}


EPMC_IDS = tuple(f"doi:10.1000/e{i}" for i in (1, 2, 3))
EPMC_FIND = Op(
    "europepmc.find", "europepmc", {"request_type": "find", "kind": "article", "query": "q", "limit": 3, "domain": "biomed"},
    (Route("GET", EPMC_URL, {"hitCount": 9, "nextCursorMark": "AoE=", "resultList": {"result": [epmc_record(i) for i in (1, 2, 3)]}}, corrupt=True),),
    EPMC_IDS, levels=(Level(("resultList", "result")),), cursor=((("nextCursorMark",), "token"),), find=True, continues=True)

# ------------------------------------------------------------------ GovInfo
GOVINFO_URL = "https://api.govinfo.gov/search"


def govinfo_package(i: int) -> dict:
    return {"packageId": f"CRPT-{i}", "title": f"T{i}", "collectionCode": "CRPT", "dateIssued": "2023-02-01", "governmentAuthor1": "House",
            "download": {"pdfLink": f"https://api.govinfo.gov/packages/CRPT-{i}/pdf"}}


GOVINFO_IDS = tuple(f"govinfo:CRPT-{i}" for i in (1, 2, 3))
GOVINFO_FIND = Op(
    "govinfo.find", "govinfo", {"request_type": "find", "kind": "dataset", "query": "q", "limit": 3, "domain": "finance"},
    (Route("POST", GOVINFO_URL, {"count": 9, "offsetMark": "AoE-1", "results": [govinfo_package(i) for i in (1, 2, 3)]}, corrupt=True),),
    GOVINFO_IDS, levels=(Level(("results",)),), cursor=((("offsetMark",), "token"),), find=True, continues=True, empty_when=((("results",), ("count",)),))

# ------------------------------------------------------------------ Harvard Dataverse (and QDR, which is the same client)
DV_SEARCH_URL = "https://dataverse.harvard.edu/api/search"


def dataverse_hit(i: int) -> dict:
    return {"name": f"N{i}", "global_id": f"doi:10.7910/DVN/X{i}", "url": f"https://doi.org/10.7910/DVN/X{i}", "authors": ["B"],
            "published_at": "2021-05-01T00:00:00Z", "fileCount": 2, "subjects": ["S"]}


def dataverse_search(total: int) -> dict:
    return {"status": "OK", "data": {"total_count": total, "items": [dataverse_hit(i) for i in (1, 2, 3)]}}


DV_IDS = tuple(f"doi:10.7910/dvn/x{i}" for i in (1, 2, 3))
DV_FIND_MORE = Op(
    "harvard_dataverse.find (a full page)", "harvard_dataverse", {"request_type": "find", "kind": "dataset", "query": "q", "limit": 3, "domain": "social"},
    (Route("GET", DV_SEARCH_URL, dataverse_search(9), corrupt=True),), DV_IDS, levels=(Level(("data", "items")),),
    end=(((("data", "total_count"), "total"),),), cursor=((("data", "total_count"), "total"),), find=True, continues=True)
DV_FIND_END = replace(DV_FIND_MORE, name="harvard_dataverse.find (the page that reaches the total)",
                      routes=(Route("GET", DV_SEARCH_URL, dataverse_search(3), corrupt=True),), continues=False, exhausted=True)

# ------------------------------------------------------------------ Hugging Face
HF_LIST = "https://huggingface.co/api/datasets"
HF_ASKED = "https://huggingface.co/api/datasets?search=q&limit=3&full=true"
HF_NEXT = HF_ASKED + "&cursor=eyJfaWQiOiI2NTAwIn0"


def hf_dataset(i: int, files: int = 2) -> dict:
    return {"id": f"o/d{i}", "author": "o", "lastModified": "2026-02-01T00:00:00Z", "tags": ["license:cc-by-4.0"], "cardData": {"license": "cc-by-4.0"},
            "siblings": [{"rfilename": f"f{i}-{k}.csv"} for k in range(files)], "gated": False}


HF_IDS = tuple(f"hf:o/d{i}" for i in (1, 2, 3))
HF_FIND_MORE = Op(
    "huggingface.find (a Link to the next page)", "huggingface", {"request_type": "find", "kind": "dataset", "query": "q", "limit": 3, "domain": "ai-ml"},
    (Route("GET", HF_LIST, [hf_dataset(i) for i in (1, 2, 3)], {"Link": f'<{HF_NEXT}>; rel="next"'}, corrupt=True),), HF_IDS,
    levels=(Level(()),), end=((),), find=True, continues=True, zero_counts=(("file_count", ("siblings",), True),), unknowable=("file_count",))
HF_FIND_END = replace(HF_FIND_MORE, name="huggingface.find (no Link header)",
                      routes=(Route("GET", HF_LIST, [hf_dataset(i) for i in (1, 2, 3)], None, corrupt=True),), continues=False, exhausted=True)

# ------------------------------------------------------------------ Kaggle
KAGGLE_LIST = "https://www.kaggle.com/api/v1/datasets/list"
KAGGLE_FIND = Op(
    "kaggle.find", "kaggle", {"request_type": "find", "kind": "dataset", "query": "q", "limit": 3, "domain": "ai-ml"},
    (Route("GET", KAGGLE_LIST, [{"ref": f"o/d{i}", "title": f"T{i}", "ownerName": "o", "lastUpdated": "2026-01-01", "totalBytes": 10}
                                for i in (1, 2, 3)], corrupt=True),), tuple(f"kaggle:o/d{i}" for i in (1, 2, 3)), levels=(Level(()),),
    cursor=(((), "list"),), find=True, continues=True)

# ------------------------------------------------------------------ OpenAIRE
OPENAIRE_URL = "https://api.openaire.eu/graph/v1/researchProducts"


def openaire_product(i: int) -> dict:
    return {"id": f"oa::{i}", "mainTitle": f"T{i}", "type": "publication", "publicationDate": "2024-05-01", "pids": None,
            "authors": [{"fullName": "A"}], "instances": [{"alternateIdentifiers": [{"scheme": "doi", "value": f"10.46298/abc{i}"}], "license": "CC BY",
                                                             "urls": [f"https://doi.org/10.46298/abc{i}"]}]}


def openaire_page(found: int) -> dict:
    return {"header": {"numFound": found, "nextCursor": "c1", "pageSize": 3}, "results": [openaire_product(i) for i in (1, 2, 3)]}


OPENAIRE_IDS = tuple(f"doi:10.46298/abc{i}" for i in (1, 2, 3))
OPENAIRE_FIND_MORE = Op(
    "openaire.find (a full page)", "openaire", FIND, (Route("GET", OPENAIRE_URL, openaire_page(9), corrupt=True),), OPENAIRE_IDS,
    levels=(Level(("results",)),), seed={"base_for": ["article"]}, empty_when=((("results",), ("header", "numFound")),),
    end=(((("header", "nextCursor"), "same"),), ((("header", "numFound"), "total"), (("results",), "list"))),
    cursor=((("header", "nextCursor"), "token"),), find=True, continues=True)
OPENAIRE_FIND_END = replace(OPENAIRE_FIND_MORE, name="openaire.find (the first page holds every match)",
                            routes=(Route("GET", OPENAIRE_URL, openaire_page(3), corrupt=True),), continues=False, exhausted=True)

# ------------------------------------------------------------------ OpenML
OPENML_URL = "https://www.openml.org/api/v1/json/data/list/"


def openml_listing(n: int) -> dict:
    return {"data": {"dataset": [{"did": 60 + i, "name": f"iris{i}", "version": 1, "status": "active", "format": "ARFF", "file_id": 60 + i,
                                  "quality": [{"name": "NumberOfInstances", "value": "150"}]} for i in range(1, n + 1)]}}


OPENML_IDS = tuple(f"openml:{60 + i}" for i in (1, 2, 3))
OPENML_FIND_MORE = Op(
    "openml.find (a full page)", "openml", {"request_type": "find", "kind": "dataset", "query": "iris", "limit": 3, "domain": "ai-ml"},
    (Route("GET", OPENML_URL, openml_listing(3), corrupt=True),), OPENML_IDS, levels=(Level(("data", "dataset")),),
    end=(((("data", "dataset"), "list"),),), cursor=((("data", "dataset"), "list"),), find=True, continues=True)
OPENML_FIND_END = replace(OPENML_FIND_MORE, name="openml.find (a short page)", routes=(Route("GET", OPENML_URL, openml_listing(2), corrupt=True),),
                          ids=OPENML_IDS[:2], continues=False, exhausted=True)

# ------------------------------------------------------------------ Semantic Scholar
S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"


def s2_paper(i: int) -> dict:
    return {"paperId": f"p{i}", "externalIds": {"DOI": f"10.1000/s{i}"}, "title": f"T{i}", "year": 2021, "venue": "V", "authors": [{"name": "A"}]}


def s2_page(more: bool) -> dict:
    body = {"total": 9, "offset": 0, "data": [s2_paper(i) for i in (1, 2, 3)]}
    if more:
        body["next"] = 3
    return body


S2_IDS = tuple(f"doi:10.1000/s{i}" for i in (1, 2, 3))
S2_FIND_MORE = Op(
    "semanticscholar.find (a next offset)", "semanticscholar", {"request_type": "find", "kind": "article", "query": "q", "limit": 3, "domain": "ai-ml"},
    (Route("GET", S2_SEARCH, s2_page(True), corrupt=True),), S2_IDS, levels=(Level(("data",)),), end=(((("next",), "absent"),),), empty_when=((("data",), ("total",)),),
    cursor=((("next",), "offset"),), find=True, continues=True)
S2_FIND_END = replace(S2_FIND_MORE, name="semanticscholar.find (no next offset)", routes=(Route("GET", S2_SEARCH, s2_page(False), corrupt=True),),
                      continues=False, exhausted=True)

# ------------------------------------------------------------------ Socrata
SOCRATA_URL = "https://api.us.socrata.com/api/catalog/v1"


def socrata_hit(i: int) -> dict:
    return {"resource": {"id": f"abcd-123{i}", "name": f"N{i}", "type": "dataset", "updatedAt": "2026-01-05T00:00:00Z"},
            "metadata": {"domain": "data.example.gov", "license": "Public Domain"}, "permalink": f"https://data.example.gov/d/abcd-123{i}"}


SOCRATA_IDS = tuple(f"socrata:data.example.gov:abcd-123{i}" for i in (1, 2, 3))
SOCRATA_FIND_MORE = Op(
    "socrata.find (a full page)", "socrata", {"request_type": "find", "kind": "dataset", "query": "q", "limit": 3, "domain": "finance"},
    (Route("GET", SOCRATA_URL, {"resultSetSize": 9, "results": [socrata_hit(i) for i in (1, 2, 3)]}, corrupt=True),), SOCRATA_IDS,
    levels=(Level(("results",)),), end=(((("resultSetSize",), "total"),),), cursor=((("resultSetSize",), "total"),), find=True, continues=True)
SOCRATA_FIND_END = replace(SOCRATA_FIND_MORE, name="socrata.find (the page that reaches the size)",
                           routes=(Route("GET", SOCRATA_URL, {"resultSetSize": 3, "results": [socrata_hit(i) for i in (1, 2, 3)]}, corrupt=True),),
                           continues=False, exhausted=True)

# ================================================================== lookups: resolve
def request(kind: str, **fields) -> dict:
    return {"request_type": kind, **fields}


CROSSREF_RESOLVE = Op(
    "crossref.resolve", "crossref", request("resolve", identity="doi:10.1000/a1"),
    (Route("GET", "https://api.crossref.org/works/10.1000/a1", {"status": "ok", "message": crossref_work(1)}, corrupt=True),), ("doi:10.1000/a1",),
    single=("message",))
DATACITE_RESOLVE = Op(
    "datacite.resolve", "datacite", request("resolve", identity="doi:10.9101/d1"),
    (Route("GET", "https://api.datacite.org/dois/10.9101/d1", {"data": {**datacite_item(1), "id": "10.9101/d1",
                                                                         "attributes": {**datacite_item(1)["attributes"], "doi": "10.9101/d1"}}}, corrupt=True),),
    ("doi:10.9101/d1",), single=("data",), agency="DataCite")
OPENAIRE_RESOLVE = Op(
    "openaire.resolve", "openaire", request("resolve", identity="doi:10.46298/abc1"),
    (Route("GET", OPENAIRE_URL, {"header": {"numFound": 2}, "results": [openaire_product(1), openaire_product(2)]}, corrupt=True),),
    ("doi:10.46298/abc1",), levels=(Level(("results",), take=1),))


def doaj_journal(i: int) -> dict:
    return {"id": f"jj{i}", "bibjson": {"title": f"J{i}", "publisher": {"name": "P"},
                                        "license": [{"type": "CC BY"}], "subject": [{"term": "S"}]}}


DOAJ_RESOLVE = Op(
    "doaj.resolve (a journal by its ISSN)", "doaj", request("resolve", identity="issn:1234-5679"),
    (Route("GET", "https://doaj.org/api/search/journals/", {"results": [doaj_journal(1), doaj_journal(2)]}, corrupt=True),), ("issn:1234-5679",),
    levels=(Level(("results",), take=1),))
EPMC_RESOLVE = Op(
    "europepmc.resolve", "europepmc", request("resolve", identity="pmid:1"),
    (Route("GET", EPMC_URL, {"resultList": {"result": [epmc_record(1), epmc_record(2)]}}, corrupt=True),), ("doi:10.1000/e1",),
    levels=(Level(("resultList", "result"), take=1),))
HF_RESOLVE = Op(
    "huggingface.resolve", "huggingface", request("resolve", identity="hf:o/d1"),
    (Route("GET", "https://huggingface.co/api/datasets/o/d1", hf_dataset(1), corrupt=True),), ("hf:o/d1",), single=(), shared=(("id",),),
    zero_counts=(("file_count", ("siblings",), True),), unknowable=("file_count",))
OPENML_DESC = {"data_set_description": {"id": "61", "name": "iris", "version": "1", "format": "ARFF", "licence": "Public", "upload_date": "2014-04-06",
                                        "url": "https://api.openml.org/data/v1/download/61/iris.arff",
                                        "parquet_url": "https://data.openml.org/datasets/0000/0061/dataset_61.pq", "creator": "R.A. Fisher"}}
OPENML_RESOLVE = Op("openml.resolve", "openml", request("resolve", identity="openml:61"),
                    (Route("GET", "https://www.openml.org/api/v1/json/data/61", OPENML_DESC, corrupt=True),), ("openml:61",), single=("data_set_description",))
S2_RESOLVE = Op("semanticscholar.resolve", "semanticscholar", request("resolve", identity="s2:p1"),
                (Route("GET", "https://api.semanticscholar.org/graph/v1/paper/p1", s2_paper(1), corrupt=True),), ("doi:10.1000/s1",), single=())
SOCRATA_VOUCH = Route("GET", SOCRATA_URL, {"results": [{"metadata": {"domain": "data.example.gov"}}]})
SOCRATA_VIEW = {"id": "abcd-1231", "name": "N", "rowsUpdatedAt": 1700000000, "description": "d", "columns": [{"fieldName": "a"}, {"fieldName": "b"}],
                "license": {"name": "Public Domain"}, "attribution": "x"}
SOCRATA_RESOLVE = Op("socrata.resolve", "socrata", request("resolve", identity="socrata:data.example.gov:abcd-1231"),
                     (SOCRATA_VOUCH, Route("GET", "https://data.example.gov/api/views/abcd-1231.json", SOCRATA_VIEW, corrupt=True)),
                     ("socrata:data.example.gov:abcd-1231",), single=(), shared=(("id",),))

RESOLVE_OPS = (CROSSREF_RESOLVE, DATACITE_RESOLVE, OPENAIRE_RESOLVE, DOAJ_RESOLVE, EPMC_RESOLVE, HF_RESOLVE, OPENML_RESOLVE, S2_RESOLVE, SOCRATA_RESOLVE)

# ================================================================== enrichments
ENRICH = request("enrich", identity="doi:10.1000/a1", what="references")
CROSSREF_REFERENCES = Op(
    "crossref.enrich references", "crossref", ENRICH,
    (Route("GET", "https://api.crossref.org/works/10.1000/a1", {"message": {"DOI": "10.1000/a1", "reference": [{"DOI": f"10.2000/R{i}", "article-title": f"R{i}", "year": "2020"}
                                                                                                          for i in (1, 2, 3)]}}, corrupt=True),),
    tuple(f"doi:10.2000/r{i}" for i in (1, 2, 3)), levels=(Level(("message", "reference"), optional_from=1),))


def s2_link(key: str, i: int) -> dict:
    return {key: {"paperId": f"c{i}", "externalIds": {"DOI": f"10.9000/c{i}"}, "title": f"T{i}", "year": 2022, "venue": "V"}}


S2_CITATIONS = Op("semanticscholar.enrich citations", "semanticscholar", request("enrich", identity="doi:10.1000/a1", what="citations"),
                  (Route("GET", "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1000/a1/citations",
                         {"data": [s2_link("citingPaper", i) for i in (1, 2, 3)]}, corrupt=True),),
                  tuple(f"doi:10.9000/c{i}" for i in (1, 2, 3)), levels=(Level(("data",)),))
S2_REFERENCES = Op("semanticscholar.enrich references", "semanticscholar", ENRICH,
                   (Route("GET", "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1000/a1/references",
                          {"data": [s2_link("citedPaper", i) for i in (1, 2, 3)]}, corrupt=True),),
                   tuple(f"doi:10.9000/c{i}" for i in (1, 2, 3)), levels=(Level(("data",)),))


def oc_row(i: int, key: str) -> dict:
    return {"oci": f"1-{i}", "citing": f"doi:10.9000/c{i} omid:br/{i}" if key == "citing" else "doi:10.1000/a1",
            "cited": f"doi:10.8000/r{i}" if key == "cited" else "doi:10.1000/a1", "creation": "2022-01", "timespan": "P1Y"}


OC_CITATIONS = Op("opencitations.enrich citations", "opencitations", request("enrich", identity="doi:10.1000/a1", what="citations"),
                  (Route("GET", "https://api.opencitations.net/index/v2/citations/doi:10.1000/a1", [oc_row(i, "citing") for i in (1, 2, 3)], corrupt=True),),
                  tuple(f"doi:10.9000/c{i}" for i in (1, 2, 3)), levels=(Level(()),))
OC_REFERENCES = Op("opencitations.enrich references", "opencitations", ENRICH,
                   (Route("GET", "https://api.opencitations.net/index/v2/references/doi:10.1000/a1", [oc_row(i, "cited") for i in (1, 2, 3)], corrupt=True),),
                   tuple(f"doi:10.8000/r{i}" for i in (1, 2, 3)), levels=(Level(()),))
OC_METADATA = Op("opencitations.enrich metadata", "opencitations", request("enrich", identity="doi:10.1000/a1", what="metadata"),
                 (Route("GET", "https://api.opencitations.net/meta/v1/metadata/doi:10.1000/a1",
                        [{"title": f"T{i}", "author": "A", "pub_date": "2020", "venue": "V"} for i in (1, 2)], corrupt=True),),
                 ("doi:10.1000/a1",), levels=(Level((), take=1),))


def unpaywall_location(i: int) -> dict:
    return {"url_for_pdf": f"https://example.org/{i}.pdf", "url": f"https://example.org/{i}", "host_type": "publisher", "license": "cc-by",
            "version": "publishedVersion"}


UNPAYWALL = Op("unpaywall.enrich oa_location", "unpaywall", request("enrich", identity="doi:10.1000/a1", what="oa_location"),
               (Route("GET", "https://api.unpaywall.org/v2/10.1000/a1", {"doi": "10.1000/a1", "is_oa": True, "oa_status": "gold", "title": "T", "year": 2021,
                                                                         "journal_name": "J", "best_oa_location": unpaywall_location(1),
                                                                         "oa_locations": [unpaywall_location(i) for i in (1, 2, 3)]}, corrupt=True),),
               ("doi:10.1000/a1",) * 3, levels=(Level(("oa_locations",)),), shared=(("title",), ("year",), ("journal_name",)))
def core_work(i: int) -> dict:
    return {"id": i, "doi": "10.1000/a1", "title": "T", "downloadUrl": "https://example.org/a1.pdf", "authors": [{"name": "A"}], "yearPublished": 2021,
            "publisher": "P", "fullText": "text"}



CORE_FULL_TEXT = Op("core.enrich full_text", "core", request("enrich", identity="doi:10.1000/a1", what="full_text"),
                    (Route("GET", "https://api.core.ac.uk/v3/search/works", {"results": [core_work(1), core_work(2)]}, corrupt=True),),
                    ("doi:10.1000/a1",), levels=(Level(("results",), take=1),))

ENRICH_OPS = (CROSSREF_REFERENCES, S2_CITATIONS, S2_REFERENCES, OC_CITATIONS, OC_REFERENCES, OC_METADATA, UNPAYWALL, CORE_FULL_TEXT)

# ================================================================== statistical data: series and tables
BLS_SERIES = [{"seriesID": f"S{i}", "catalog": {"series_title": f"T{i}", "survey_name": "s"}, "data": [{"year": "2026", "period": "M07", "value": "1"}]}
              for i in (1, 2, 3)]
BLS_DATA = Op("bls.data", "bls", request("data", source="bls", params={"series": ["S1", "S2", "S3"]}),
              (Route("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/",
                     {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": BLS_SERIES}}, corrupt=True),),
              tuple(f"series:bls:S{i}" for i in (1, 2, 3)), levels=(Level(("Results", "series")),), shared=(("status",),))

SDMX_STRUCTURE = {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}, {"id": "CURRENCY", "values": [{"id": "USD"}, {"id": "GBP"}, {"id": "CHF"}]}],
                                 "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-09-01"}]}]}}
ECB_BODY = {"structure": SDMX_STRUCTURE,
            "dataSets": [{"series": {"0:0": {"observations": {"0": [1.08]}}, "0:1": {"observations": {"0": [0.85]}}}},
                         {"series": {"0:2": {"observations": {"0": [0.96]}}}}]}
ECB_DATA = Op("ecb.data", "ecb", request("data", source="ecb", params={"dataflow": "EXR", "key": "D.USD"}),
              (Route("GET", "https://data-api.ecb.europa.eu/service/data/EXR/", ECB_BODY, corrupt=True),),
              tuple(f"series:ecb:EXR:D.{c}" for c in ("USD", "GBP", "CHF")),
              levels=(Level(("dataSets",), optional_from=0), Level(("series",), dict, optional_from=0)), shared=(("structure",),), leaf="object")

ECB_BODY_ONE = {"structure": SDMX_STRUCTURE, "dataSets": [{"series": {"0:0": {"observations": {"0": [1.08]}}, "0:1": {"observations": {"0": [0.85]}},
                                                                  "0:2": {"observations": {"0": [0.96]}}}}]}
ECB_DATA_ONE = replace(ECB_DATA, name="ecb.data (one data set)", routes=(Route("GET", "https://data-api.ecb.europa.eu/service/data/EXR/", ECB_BODY_ONE, corrupt=True),))

FRED_OBSERVATIONS = Route("GET", "https://api.stlouisfed.org/fred/series/observations?",
                          {"observations": [{"date": "2026-01-01", "value": "1"}, {"date": "2026-04-01", "value": "2"}]})
FRED_SERIES = Route("GET", "https://api.stlouisfed.org/fred/series?", {"seriess": [{"id": "GDP", "title": "GDP", "units": "B", "frequency": "Q", "notes": "n"}]})
FRED_REQUEST = request("data", source="fred", params={"series": "GDP"})
FRED_OBS = Op("fred.data (the observations)", "fred", FRED_REQUEST, (replace(FRED_OBSERVATIONS, corrupt=True), FRED_SERIES), ("series:fred:GDP",), single=(),
              zero_counts=(("observations", ("observations",), False),))
FRED_META = Op("fred.data (the series metadata)", "fred", FRED_REQUEST, (FRED_OBSERVATIONS, replace(FRED_SERIES, corrupt=True)), ("series:fred:GDP",), single=())

BEA_DATA = {"BEAAPI": {"Results": {"Data": [{"TableName": "T10101", "LineDescription": f"L{i}", "TimePeriod": "2025", "DataValue": "3.1"} for i in (1, 2)],
                                   "Notes": [{"NoteText": "Percent change"}]}}}
BEA_GETDATA = Op("bea.data (GetData)", "bea", request("data", source="bea", params={"dataset": "NIPA", "table": "T10101", "frequency": "A", "year": "2025"}),
                 (Route("GET", "https://apps.bea.gov/api/data/", BEA_DATA, corrupt=True),), ("table:bea:NIPA:T10101",), single=(),
                 zero_counts=(("row_count", ("BEAAPI", "Results", "Data"), False),))
BEA_LIST = Op("bea.data (GETDATASETLIST)", "bea", request("data", source="bea", params={"method": "GETDATASETLIST"}),
              (Route("GET", "https://apps.bea.gov/api/data/", {"BEAAPI": {"Results": {"Dataset": [{"DatasetName": "NIPA", "DatasetDescription": "d"},
                                                                                                 {"DatasetName": "Regional", "DatasetDescription": "d"}]}}},
                     corrupt=True),), ("table:bea:GETDATASETLIST",), single=(),
              zero_counts=(("row_count", ("BEAAPI", "Results", "Dataset"), True),))
CENSUS_DATA = Op("census.data", "census", request("data", source="census", params={"dataset": "2022/acs/acs1", "get": "NAME,B01001_001E", "for": "state:*"}),
                 (Route("GET", "https://api.census.gov/data/2022/acs/acs1", [["NAME", "B01001_001E", "state"], ["Alabama", "1", "01"], ["Alaska", "2", "02"]],
                        corrupt=True),), ("table:census:2022/acs/acs1:NAME,B01001_001E",), single=(), leaf="list", zero_counts=(("row_count", (), False),))

DATA_OPS = (BLS_DATA, ECB_DATA, ECB_DATA_ONE, FRED_OBS, FRED_META, BEA_GETDATA, BEA_LIST, CENSUS_DATA)

# ================================================================== fetch: a dataset's files
def dataverse_file(i: int) -> dict:
    return {"label": f"f{i}.csv", "restricted": False, "dataFile": {"id": 900 + i, "filename": f"f{i}.csv", "contentType": "text/csv", "filesize": 12}}


DV_DATASET = {"data": {"id": 42, "authority": "10.7910", "identifier": "DVN/X1", "persistentUrl": "https://doi.org/10.7910/DVN/X1", "publisher": "Harvard Dataverse",
                       "latestVersion": {"versionNumber": 1, "versionMinorNumber": 0, "releaseTime": "2021-05-01", "license": {"name": "CC0 1.0"},
                                         "metadataBlocks": {"citation": {"fields": [{"typeName": "title", "value": "T"}]}},
                                         "files": [dataverse_file(i) for i in (1, 2, 3)]}}}
DV_FETCH = Op("harvard_dataverse.fetch (a dataset's files)", "harvard_dataverse", request("fetch", target="doi:10.7910/DVN/X1"),
              (Route("GET", "https://dataverse.harvard.edu/api/datasets/:persistentId/", DV_DATASET, corrupt=True),),
              tuple(f"doi:10.7910/dvn/x1#{900 + i}" for i in (1, 2, 3)), levels=(Level(("data", "latestVersion", "files"), optional_from=1),),
              shared=(("data", "authority"), ("data", "identifier"), ("data", "id"), ("data", "latestVersion", "license"),
                      ("data", "latestVersion", "termsOfUse")))
HF_FETCH = Op("huggingface.fetch (a dataset's files)", "huggingface", request("fetch", target="hf:o/d1"),
              (Route("GET", "https://huggingface.co/api/datasets/o/d1", hf_dataset(1, files=3), corrupt=True),), tuple(f"hf:o/d1#f1-{k}.csv" for k in range(3)),
              levels=(Level(("siblings",), optional_from=0),), shared=(("id",), ("cardData",), ("tags",)))
KAGGLE_FETCH = Op("kaggle.fetch (a dataset's files)", "kaggle", request("fetch", target="kaggle:o/d1"),
                  (Route("GET", "https://www.kaggle.com/api/v1/datasets/list/o/d1", {"datasetFiles": [{"name": f"f{i}.csv", "totalBytes": 10} for i in (1, 2, 3)]},
                         corrupt=True),), tuple(f"kaggle:o/d1#f{i}.csv" for i in (1, 2, 3)), levels=(Level(("datasetFiles",)),))
GOVINFO_SUMMARY = {"packageId": "CRPT-1", "title": "T", "collectionCode": "CRPT", "dateIssued": "2023-02-01",
                   "download": {"pdfLink": "https://api.govinfo.gov/packages/CRPT-1/pdf", "txtLink": "https://api.govinfo.gov/packages/CRPT-1/txt"}}
GOVINFO_FETCH = Op("govinfo.fetch (a package's formats)", "govinfo", request("fetch", target="govinfo:CRPT-1"),
                   (Route("GET", "https://api.govinfo.gov/packages/CRPT-1/summary", GOVINFO_SUMMARY, corrupt=True),),
                   ("govinfo:CRPT-1#pdf", "govinfo:CRPT-1#txt"), levels=(Level(("download",), dict, optional_from=0),), shared=(("packageId",), ("title",)), leaf="any")
SOCRATA_ROWS = Op("socrata.fetch (the rows)", "socrata", request("fetch", target="socrata:data.example.gov:abcd-1231"),
                  (SOCRATA_VOUCH, Route("GET", "https://data.example.gov/api/views/abcd-1231.json", SOCRATA_VIEW),
                   Route("GET", "https://data.example.gov/resource/abcd-1231.json", [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}], corrupt=True)),
                  ("socrata:data.example.gov:abcd-1231#rows",), single=(), leaf="list", zero_counts=(("row_count", (), False),))

GOVINFO_RESOLVE = Op("govinfo.resolve", "govinfo", request("resolve", identity="govinfo:CRPT-1"),
                     (Route("GET", "https://api.govinfo.gov/packages/CRPT-1/summary", GOVINFO_SUMMARY, corrupt=True),), ("govinfo:CRPT-1",), single=(),
                     shared=(("packageId",),))
OPENML_FETCH = Op("openml.fetch (a dataset's file links)", "openml", request("fetch", target="openml:61"),
                  (Route("GET", "https://www.openml.org/api/v1/json/data/61", OPENML_DESC, corrupt=True),),
                  ("openml:61#dataset_61.pq", "openml:61#iris.arff"),
                  explicit=(("data_set_description", "parquet_url"), ("data_set_description", "url")), leaf="url",
                  shared=(("data_set_description", "licence"), ("data_set_description", "id")))

FETCH_OPS = (DV_FETCH, HF_FETCH, KAGGLE_FETCH, GOVINFO_FETCH, SOCRATA_ROWS, OPENML_FETCH)
RESOLVE_OPS = (*RESOLVE_OPS, GOVINFO_RESOLVE)

# ================================================================== catalogues: entries answered whole
BEA_CATALOG = Op("bea.catalog (the datasets)", "bea", request("catalog", source="bea"),
                 (Route("GET", "https://apps.bea.gov/api/data/", {"BEAAPI": {"Results": {"Dataset": [{"DatasetName": n, "DatasetDescription": "d"} for n in ("NIPA", "Regional", "ITA")]}}},
                        corrupt=True),), ("NIPA", "Regional", "ITA"), levels=(Level(("BEAAPI", "Results", "Dataset")),), whole=True, bare_row=True)
BLS_CATALOG = Op("bls.catalog (the surveys)", "bls", request("catalog", source="bls"),
                 (Route("GET", "https://api.bls.gov/publicAPI/v2/surveys", {"status": "REQUEST_SUCCEEDED", "Results": {"survey": [
                     {"survey_abbreviation": n, "survey_name": f"S {n}"} for n in ("CU", "LA", "CE")]}}, corrupt=True),), ("CU", "LA", "CE"),
                 levels=(Level(("Results", "survey")),), whole=True)
CENSUS_CATALOG = Op("census.catalog (the datasets)", "census", request("catalog", source="census"),
                    (Route("GET", "https://api.census.gov/data.json", {"dataset": [{"c_dataset": ["acs", f"acs{i}"], "c_vintage": 2022, "title": f"ACS {i}"}
                                                                                  for i in (1, 3, 5)]}, corrupt=True),),
                    tuple(f"2022/acs/acs{i}" for i in (1, 3, 5)), levels=(Level(("dataset",)),), whole=True)
FRED_CATALOG = Op("fred.catalog (a search)", "fred", request("catalog", source="fred", query="gdp"),
                  (Route("GET", "https://api.stlouisfed.org/fred/series/search?", {"seriess": [{"id": n, "title": f"T {n}", "units": "B", "frequency": "Q",
                                                                                              "observation_start": "1947", "observation_end": "2026"}
                                                                                             for n in ("GDP", "GDPC1", "GDPPOT")]}, corrupt=True),),
                  ("GDP", "GDPC1", "GDPPOT"), levels=(Level(("seriess",)),), whole=True)

BEA_PARAMETERS = Op("bea.catalog (a dataset's parameters)", "bea", request("catalog", source="bea", within="NIPA"),
                    (Route("GET", "https://apps.bea.gov/api/data/", {"BEAAPI": {"Results": {"Parameter": [
                        {"ParameterName": n, "ParameterDescription": "d"} for n in ("Frequency", "Year", "TableName")]}}}, corrupt=True),),
                    ("Frequency", "Year", "TableName"), levels=(Level(("BEAAPI", "Results", "Parameter")),), whole=True, bare_row=True)
BEA_VALUES = Op("bea.catalog (a parameter's values)", "bea", request("catalog", source="bea", within="NIPA/Frequency"),
                (Route("GET", "https://apps.bea.gov/api/data/", {"BEAAPI": {"Results": {"ParamValue": [
                    {"Key": n, "Desc": f"d {n}"} for n in ("A", "Q", "M")]}}}, corrupt=True),),
                ("A", "Q", "M"), levels=(Level(("BEAAPI", "Results", "ParamValue")),), whole=True, bare_row=True)
BLS_POPULAR = Op("bls.catalog (a survey's popular series)", "bls", request("catalog", source="bls", within="CU"),
                 (Route("GET", "https://api.bls.gov/publicAPI/v2/timeseries/popular", {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
                     {"seriesID": n} for n in ("CUUR0000SA0", "CUUR0000SA0L1E", "CUSR0000SA0")]}}, corrupt=True),),
                 ("CUUR0000SA0", "CUUR0000SA0L1E", "CUSR0000SA0"), levels=(Level(("Results", "series")),), whole=True)
CENSUS_VARIABLES = Op("census.catalog (a dataset's variables)", "census", request("catalog", source="census", within="2022/acs/acs1"),
                      (Route("GET", "https://api.census.gov/data/2022/acs/acs1/variables.json", {"variables": {
                          n: {"label": f"L {n}", "predicateOnly": False} for n in ("B01001_001E", "B01001_002E", "B01001_003E")}}, corrupt=True),),
                      ("B01001_001E", "B01001_002E", "B01001_003E"), levels=(Level(("variables",), dict),), whole=True)
FRED_SERIES_ENTRY = Op("fred.catalog (one series)", "fred", request("catalog", source="fred", within="GDP"),
                       (Route("GET", "https://api.stlouisfed.org/fred/series?", {"seriess": [
                           {"id": n, "title": f"T {n}", "units": "B", "frequency": "Q", "observation_start": "1947", "observation_end": "2026"}
                           for n in ("GDP", "GDPC1", "GDPPOT")]}, corrupt=True),),
                       ("GDP", "GDPC1", "GDPPOT"), levels=(Level(("seriess",)),), whole=True)

CATALOG_OPS = (BEA_CATALOG, BEA_PARAMETERS, BEA_VALUES, BLS_CATALOG, BLS_POPULAR, CENSUS_CATALOG, CENSUS_VARIABLES, FRED_CATALOG, FRED_SERIES_ENTRY)

FIND_OPS = (CROSSREF_FIND_MORE, CROSSREF_FIND_END, DATACITE_FIND_MORE, DATACITE_FIND_END, DOAJ_FIND_MORE, DOAJ_FIND_END, EPMC_FIND, GOVINFO_FIND,
            DV_FIND_MORE, DV_FIND_END, HF_FIND_MORE, HF_FIND_END, KAGGLE_FIND, OPENAIRE_FIND_MORE, OPENAIRE_FIND_END, OPENML_FIND_MORE, OPENML_FIND_END,
            S2_FIND_MORE, S2_FIND_END, SOCRATA_FIND_MORE, SOCRATA_FIND_END)

# ================================================================== populated optional-field variants (task 2b-repair-10a)
# Each operation again, with every optional field its provider documents populated (tests/oracle/variants.py), so that the corruption pass reaches those
# fields too. They are appended LAST, after every minimal operation: the harness draws its generated cases (MixedMembers) from one seeded stream in the
# order of `ALL`, so appending anywhere else would shift the draws of the minimal operations. The XML catalogue and data cases
# (tests/oracle/xml_ops.py) are not here: this pass corrupts JSON.
import sys as _sys  # noqa: E402

from tests.oracle import variants as _variants  # noqa: E402

_POPULATED = _variants.build(_sys.modules[__name__])
POPULATED_OPS = tuple(op for group in ("find", "resolve", "enrich", "data", "fetch", "catalog") for op in _POPULATED[group])
CATALOG_OPS = (*CATALOG_OPS, *POPULATED_OPS)
