"""Task 2b-repair-9 R8-2: a container a provider sends is validated for its kind before its size or its truth is looked at.

Astra's finding (2b-repair-8): `if not series: return NO_SERIES` (ECB) and `need(..., "siblings") if d.get("siblings") else NO_MEMBERS` (HF)
read every false value as "nothing there", so a `series` of `false`, `0`, `""`, `[]` or a `siblings` of `{}` — a container that is there and is
the wrong kind — became an empty, complete answer. The cause is one pattern, a truthiness test on provider data, and it is in every adapter
that reads an optional container; the invariant harness (tests/test_invariants.py) finds it in any position of any answer. These are the named
cases, stated by hand: each holder, through the real adapter and router, with the wrong kinds Astra listed and the empty ones that are valid.

Oracle: a holder that is missing or null lists nothing (a valid empty answer: searched_empty, count 0, complete); a list or object that is the
right kind and empty also lists nothing; any other kind is an unreadable holder — one loss, the rest of the answer stands as a partial lower
bound, and an answer with nothing else readable is unobserved with no count.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone

from research_gateway import adapters
from research_gateway.adapters import bea, census, harvard_dataverse as dv, huggingface, socrata
from research_gateway.adapters.base import Client, FakeTransport, PayloadError, identified, is_unreadable, offset_after, total
from research_gateway.core.schema import decode   # parsed values, as these tests state them (an adapter decodes the client's response, adapters.base.decode)
from research_gateway.core import canonical, identity as ident, router as R, sdmx
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.core.payload import plain
from research_gateway.core.schema import counts_nothing
from research_gateway.harvest import registries
from research_gateway.registry.load import read_seed
from tests.test_member_decoding import dataverse, sdmx_sets, siblings

GOOD_SERIES = {"series": {"0:0": {"observations": {"0": [1.25]}}}}   # one readable series of an ECB data set, as the other member tests state it

WRONG = (False, 0, "", {}, "x", 5, [1])   # for a list holder: the kinds that are not one, the falsy ones first
VALID_EMPTY = (None, [])                    # for a list holder: left out (below: missing), or the empty list


def lane(sid: str, request: dict, url: str, body, method: str = "GET") -> tuple[dict, dict]:
    t = FakeTransport()
    t.add(method, url, body=body)
    c = Client(broker=Broker({sid: RatePolicy(per_second=1000)}), transport=t, secrets=lambda n, f=None: "k")
    out = R.execute(R.Router(read_seed(), adapters.load_all()), request, c)
    return out, next(e for e in out["lanes"] if e["source"] == sid)


def shape(e: dict) -> tuple:
    return e["coverage"], e["completeness"], e.get("count"), e.get("error_class")


UNOBSERVED = ("provider_unavailable", "unobserved", None, "payload_invalid")
EMPTY = ("searched_empty", "complete", 0, None)


class HoldersOfMembers(unittest.TestCase):
    """Each optional holder of members: ECB's series, HF's siblings, Crossref's reference list, Dataverse's files, GovInfo's formats."""

    def ecb(self, datasets):
        return lane("ecb", {"request_type": "data", "source": "ecb", "params": {"dataflow": "EXR", "key": "D.USD"}},
                    "https://data-api.ecb.europa.eu/service/data/EXR/", sdmx_sets(datasets))

    def test_ecb_a_series_that_is_there_and_not_an_object_is_one_unreadable_data_set(self):
        for wrong in (False, 0, "", [], [1], "x", 5):
            with self.subTest(series=wrong):
                out, e = self.ecb([GOOD_SERIES, {"series": wrong}])   # Astra: was retained, complete, no drop fact
                self.assertEqual((shape(e), e["retrieved"]), (("searched_ok", "partial", 1, "payload_invalid"), ["series:ecb:EXR:D.USD"]))
                self.assertTrue(any("malformed record(s) dropped" in f for f in out["facts"]))
                out, e = self.ecb([{"series": wrong}])   # Astra: searched_empty, complete, count 0
                self.assertEqual(shape(e), UNOBSERVED)

    def test_ecb_control_a_series_that_is_left_out_or_is_an_empty_object_lists_nothing(self):
        for nothing in ({}, None):
            with self.subTest(series=nothing):
                out, e = self.ecb([GOOD_SERIES, {"series": nothing}])
                self.assertEqual((shape(e), e["retrieved"]), (("searched_ok", "complete", 1, None), ["series:ecb:EXR:D.USD"]))
                self.assertEqual(shape(self.ecb([{"series": nothing}])[1])[:2], ("searched_empty", "complete"))
        self.assertEqual(shape(self.ecb([GOOD_SERIES, {}])[1])[:2], ("searched_ok", "complete"), "a data set with no series at all")
        self.assertEqual(shape(self.ecb([])[1])[:2], ("searched_empty", "complete"), "no data sets: nothing was listed")

    def hf(self, listed_files):
        body = siblings([])
        if listed_files is not ...:
            body["siblings"] = listed_files
        else:
            del body["siblings"]
        return lane("huggingface", {"request_type": "fetch", "target": "hf:review/dataset"}, "https://huggingface.co/api/datasets/review/dataset", body)

    def test_hf_siblings_that_are_there_and_not_a_list_are_unreadable_not_empty(self):
        for wrong in WRONG:
            with self.subTest(siblings=wrong):
                self.assertEqual(shape(self.hf(wrong)[1]), UNOBSERVED)   # Astra: {} was searched_empty, complete, count 0

    def test_hf_control_siblings_that_are_left_out_or_empty_list_no_files(self):
        for nothing in (..., None, []):
            with self.subTest(siblings=nothing):
                self.assertEqual(shape(self.hf(nothing)[1]), EMPTY)

    def test_hf_file_count_is_unknown_when_the_siblings_cannot_be_read_and_never_zero(self):
        for wrong, want in ((False, None), ({}, None), ("x", None), ([], 0), (None, 0), ([{"rfilename": "a"}, 7], 2)):
            with self.subTest(siblings=wrong):
                record = huggingface._record(decode("huggingface", huggingface.DATASET, {**siblings([]), "siblings": wrong}))
                self.assertEqual(record["file_count"], want)

    def crossref_references(self, reference):
        body = {"message": {"DOI": "10.1000/a1", "reference": reference}}
        if reference is ...:
            del body["message"]["reference"]
        return lane("crossref", {"request_type": "enrich", "identity": "doi:10.1000/a1", "what": "references"}, "https://api.crossref.org/works/10.1000/a1", body)

    def test_a_reference_list_that_is_there_and_not_a_list_is_unreadable(self):
        for wrong in WRONG:
            with self.subTest(reference=wrong):
                self.assertEqual(shape(self.crossref_references(wrong)[1]), UNOBSERVED)
        for nothing in (..., None, []):
            with self.subTest(reference=nothing):
                self.assertEqual(shape(self.crossref_references(nothing)[1]), EMPTY)

    def dataverse_files(self, version):
        return lane("harvard_dataverse", {"request_type": "fetch", "target": "doi:10.7910/DVN/OY6CBK"},
                    "https://dataverse.harvard.edu/api/datasets/:persistentId/", {"data": {**dataverse([])["data"], "latestVersion": version}})

    def test_dataverse_files_and_version_that_are_there_and_not_what_they_are_unreadable(self):
        version = dataverse([])["data"]["latestVersion"]
        for wrong in WRONG:
            with self.subTest(files=wrong):
                self.assertEqual(shape(self.dataverse_files({**version, "files": wrong})[1]), UNOBSERVED)
        for wrong in (False, 0, "", [], [1], "x", 5):   # the version itself: an object, or left out
            with self.subTest(version=wrong):
                self.assertEqual(shape(self.dataverse_files(wrong)[1]), UNOBSERVED)   # `latestVersion or {}` read these as a dataset with no files
        for nothing in (None, {}, {**version, "files": None}, {**version, "files": []}):
            with self.subTest(nothing=nothing):
                self.assertEqual(shape(self.dataverse_files(nothing)[1]), EMPTY)

    def govinfo_formats(self, download):
        t = FakeTransport()
        t.add("GET", "https://api.govinfo.gov/packages/CRPT-1/summary", body={"packageId": "CRPT-1", "title": "T", "download": download})
        c = Client(broker=Broker({"govinfo": RatePolicy(per_second=1000)}), transport=t, secrets=lambda n, f=None: "k")
        out = R.execute(R.Router(read_seed(), adapters.load_all()), {"request_type": "fetch", "target": "govinfo:CRPT-1"}, c)
        return next(e for e in out["lanes"] if e["source"] == "govinfo")

    def test_govinfo_download_that_is_there_and_not_an_object_lists_no_formats_no_more_than_it_lists_one(self):
        for wrong in (False, 0, "", [], [1], "x", 5):
            with self.subTest(download=wrong):
                self.assertEqual(shape(self.govinfo_formats(wrong)), UNOBSERVED)
        self.assertEqual(shape(self.govinfo_formats(None)), EMPTY)
        self.assertEqual(shape(self.govinfo_formats({})), EMPTY)


class ListsLeftOutWhenNothingMatched(unittest.TestCase):
    """GovInfo's `results`, OpenAIRE's `results` and Semantic Scholar's `data` may be left out of an answer only when the provider's own count
    says nothing matched. Two fields of one answer, so one corruption of each: a count that is not the whole number zero says nothing, and a list
    that is not there is then not an empty one (the harness's pair pass finds this for every such lane; these are the cases by hand)."""
    WRONG_COUNTS = (False, 0.0, "0", None, ..., 5, [], {})

    LANES = (
        ("govinfo", {"request_type": "find", "kind": "dataset", "query": "q", "limit": 3, "domain": "finance"}, "https://api.govinfo.gov/search", "POST",
         lambda count: {"offsetMark": "x", **({} if count is ... else {"count": count})}),
        ("semanticscholar", {"request_type": "find", "kind": "article", "query": "q", "limit": 3, "domain": "ai-ml"},
         "https://api.semanticscholar.org/graph/v1/paper/search", "GET", lambda count: {} if count is ... else {"total": count}),
    )

    def test_a_list_that_is_left_out_is_empty_only_when_the_count_is_the_whole_number_zero(self):
        for sid, request, url, method, body in self.LANES:
            with self.subTest(sid, count=0):
                self.assertEqual(shape(lane(sid, request, url, body(0), method)[1])[:2], ("searched_empty", "complete"))
            for count in self.WRONG_COUNTS:
                with self.subTest(sid, count=count):
                    self.assertEqual(shape(lane(sid, request, url, body(count), method)[1]), UNOBSERVED)

    def test_openaire_the_same_through_the_adapter(self):
        from research_gateway.adapters import openaire
        for count, ok in [(0, True), *((c, False) for c in self.WRONG_COUNTS)]:
            with self.subTest(count=count):
                openaire.reset_token()
                self.addCleanup(openaire.reset_token)
                t = FakeTransport()
                t.add("POST", openaire.TOKEN_URL, body={"access_token": "tok", "expires_in": 3600})
                t.add("GET", "https://api.openaire.eu/graph/v1/researchProducts", body={"header": {"nextCursor": "c1", **({} if count is ... else {"numFound": count})}})
                c = Client(broker=Broker({"openaire": RatePolicy(per_second=1000)}), transport=t, secrets=lambda n, f=None: "k")
                if ok:
                    self.assertEqual(openaire.find(c, "q")["records"], [])
                else:
                    with self.assertRaises(PayloadError):
                        openaire.find(c, "q")


class Readers(unittest.TestCase):
    """The readers of provider metadata in adapters.base: what each accepts is stated here, and every other kind is no count and no continuation. (How a field of
    each kind is DECODED — missing, null and malformed — is stated in tests/test_schema.py.)"""

    def test_an_offset_is_a_whole_number_past_where_the_page_started_and_a_total_a_whole_number_no_smaller_than_what_was_read(self):
        self.assertEqual([offset_after(v, 0) for v in (1, 3, 10 ** 9)], [1, 3, 10 ** 9])
        for wrong in (None, 0, -1, True, False, 1.5, "3", [], {}, [1]):
            self.assertIsNone(offset_after(wrong, 0), repr(wrong))
        self.assertIsNone(offset_after(100, 100), "an offset that does not advance")
        self.assertEqual([total(v, 3) for v in (3, 9, 10 ** 12)], [3, 9, 10 ** 12])
        for wrong in (None, 2, 0, -1, True, False, 3.0, "9", [], {}, [1], {"a": 1}):
            self.assertIsNone(total(wrong, 3), repr(wrong))
        self.assertEqual(total(0, 0), 0, "zero is a count when nothing was read")

    def test_only_the_whole_number_zero_says_nothing_matched(self):
        self.assertTrue(counts_nothing(0))
        for other in (False, 0.0, "0", None, [], {}, 1, -1):
            self.assertFalse(counts_nothing(other), repr(other))

    def test_a_listing_of_rows_none_of_which_names_anything_is_not_an_empty_catalogue(self):
        self.assertEqual(identified("s", [{"x": 1}], [{"id": 1}]), [{"id": 1}])
        self.assertEqual(identified("s", [], []), [], "an empty listing is empty")
        with self.assertRaises(PayloadError):
            identified("s", [{"x": 1}], [])


class Records(unittest.TestCase):
    """make_record is where adapters put provider values into canonical fields: a value of the wrong kind there is an unreadable member."""

    def make(self, **fields):
        return canonical.make_record(identity="doi:10.1/x", kind="article", source_id="s", **fields)

    def test_a_field_of_the_wrong_kind_is_unreadable_whatever_its_truth(self):
        for name, wrongs in (("title", (5, False, 0, [], {}, ["x"])), ("venue", (5, [], {})), ("license", (False, ["a"])), ("attribution", (0,)),
                             ("authors", (5, "x", False, {}, ["a", 5], [{}])), ("links", ("x", 5, [5])), ("year", (False, True, [], {}, "x", 1.5, "20x1")),
                             ("identifiers", ("x", [], {"a": 5}, {5: "a"}))):
            for wrong in wrongs:
                with self.subTest(field=name, value=wrong), self.assertRaises(PayloadError):
                    self.make(**{name: wrong})

    def test_control_the_fields_that_are_right_are_kept_and_nothing_is_nothing(self):
        r = self.make(title="T", venue=None, license="CC0", authors=["A", None], links=["u", None], year="2021", identifiers={"doi": "10.1/x", "x": None})
        self.assertEqual((r["title"], r["venue"], r["license"], r["authors"], r["links"], r["year"], r["identifiers"]),
                         ("T", None, "CC0", ["A"], ["u"], 2021, {"doi": "10.1/x"}))
        self.assertEqual(self.make(year=2021.0)["year"], 2021)
        self.assertEqual((self.make()["authors"], self.make()["identifiers"], self.make(title="")["title"]), ([], {}, ""))

    def test_the_normalisers_take_an_identifier_that_is_not_text_for_unreadable_not_for_none(self):
        for normalise in (ident.normalize_doi, ident.normalize_issn, ident.normalize_arxiv):
            self.assertIsNone(normalise(None))
            self.assertIsNone(normalise(""))
            for wrong in (False, 0, 5, [], {}, ["10.1/x"]):
                with self.assertRaises(PayloadError, msg=f"{normalise.__name__}({wrong!r})"):
                    normalise(wrong)
        self.assertEqual(ident.normalize_doi("https://doi.org/10.1234/X"), "10.1234/x")

    def test_a_date_is_text_that_names_a_year_or_nothing(self):
        self.assertEqual((canonical.year_from("2021-03-04"), canonical.year_from(None), canonical.year_from(""), canonical.year_from("n/a")), (2021, None, None, None))
        for wrong in (2021, False, 0, [], {}, ["2021"]):
            with self.assertRaises(PayloadError, msg=repr(wrong)):
                canonical.year_from(wrong)

    def test_one_member_whose_title_is_a_number_is_dropped_and_counted_not_raised(self):
        """Found by the invariant harness: the member decoded (title=5), reached the merge, and `.lower()` raised out of the router."""
        body = {"message": {"items": [{"DOI": "10.1000/A1", "title": [5]}, {"DOI": "10.1000/A2", "title": ["Two"]}], "total-results": 2}}
        try:
            out, e = lane("crossref", {"request_type": "find", "kind": "article", "query": "q", "limit": 5}, "https://api.crossref.org/works", body)
        except Exception as error:
            self.fail(f"one member's title raised out of the router: {error!r}")
        self.assertEqual((shape(e), e.get("retrieved")), (("searched_ok", "partial", 1, "payload_invalid"), ["doi:10.1000/a2"]))


class DatasetFiles(unittest.TestCase):
    """The files of a dataset need its identity and its licence and nothing else of it: a field no file takes cannot cost them (R8)."""

    def test_a_garbled_author_or_tags_or_title_does_not_cost_the_files_of_a_hugging_face_repository(self):
        for field_, value in (("author", 5), ("author", ["a"]), ("lastModified", 5), ("description", [1]), ("downloads", {"a": 1}), ("tags", ["x", 5])):
            with self.subTest(field=field_):
                out, e = lane("huggingface", {"request_type": "fetch", "target": "hf:review/dataset"}, "https://huggingface.co/api/datasets/review/dataset",
                              {**siblings([{"rfilename": "a.csv"}, {"rfilename": "b.csv"}]), field_: value})
                self.assertEqual((shape(e), e.get("retrieved")), (("searched_ok", "complete", 2, None), ["hf:review/dataset#a.csv", "hf:review/dataset#b.csv"]))

    def test_a_garbled_title_or_author_does_not_cost_the_files_of_a_dataverse_dataset(self):
        for version_field, value in (("metadataBlocks", True), ("releaseTime", 5), ("versionNumber", [1])):
            with self.subTest(field=version_field):
                body = dataverse([{"label": "a.csv", "restricted": False, "dataFile": {"id": 1, "filename": "a.csv"}}])
                body["data"]["latestVersion"][version_field] = value
                out, e = lane("harvard_dataverse", {"request_type": "fetch", "target": "doi:10.7910/DVN/OY6CBK"},
                              "https://dataverse.harvard.edu/api/datasets/:persistentId/", body)
                self.assertEqual((shape(e), e.get("retrieved")), (("searched_ok", "complete", 1, None), ["doi:10.7910/dvn/oy6cbk#1"]))

    def test_a_licence_that_cannot_be_read_costs_every_file_because_every_file_carries_it(self):
        out, e = lane("huggingface", {"request_type": "fetch", "target": "hf:review/dataset"}, "https://huggingface.co/api/datasets/review/dataset",
                      {**siblings([{"rfilename": "a.csv"}]), "cardData": {"license": {"a": 1}}})
        self.assertEqual(shape(e), UNOBSERVED)

    def test_a_govinfo_package_lists_its_formats_whatever_its_authors_and_dates_say(self):
        t = FakeTransport()
        t.add("GET", "https://api.govinfo.gov/packages/CRPT-1/summary", body={"packageId": "CRPT-1", "title": "T", "governmentAuthor1": 5, "dateIssued": [1],
                                                                              "download": {"pdfLink": "u1", "txtLink": "u2", "otherLink": "u3", "pdfFile": "x"}})
        c = Client(broker=Broker({"govinfo": RatePolicy(per_second=1000)}), transport=t, secrets=lambda n, f=None: "k")
        out = R.execute(R.Router(read_seed(), adapters.load_all()), {"request_type": "fetch", "target": "govinfo:CRPT-1"}, c)
        self.assertEqual([r["identity"] for r in out["records"]], ["govinfo:CRPT-1#pdf", "govinfo:CRPT-1#txt"])


class DatasetRecords(unittest.TestCase):
    """harvard_dataverse.dataset_record and search_record: no route of the router reaches the first (a DOI goes to its registration agency's
    resolver, never to Dataverse; qdr's resolve is the same code), so what they do with a container of the wrong kind is stated here directly."""

    @staticmethod
    def dataset(**version) -> dict:
        body = dataverse([{"label": "a.csv", "restricted": False, "dataFile": {"id": 1, "filename": "a.csv"}}])["data"]
        body["latestVersion"]["metadataBlocks"]["citation"]["fields"].append(
            {"typeName": "author", "value": [{"authorName": {"value": "Bloom, Nicholas"}}, {"authorName": {"value": "Van Reenen, John"}}]})
        body["latestVersion"].update(version)
        return body

    def record(self, body):
        """The dataset record the resolve operation makes of `body` (the dataset object of Dataverse's answer): decoded against the operation's schema first."""
        return dv.dataset_record(dv.BASE, "harvard_dataverse", decode("harvard_dataverse", dv.SCHEMAS["resolve"], {"data": body})["data"])

    def test_a_dataset_is_read_whole(self):
        r = self.record(self.dataset())
        self.assertEqual((r["identity"], r["title"], r["authors"], r["license"], r["file_count"]),
                         ("doi:10.7910/dvn/oy6cbk", "WMS", ["Bloom, Nicholas", "Van Reenen, John"], "CC0 1.0", 1))

    def test_a_container_that_is_there_and_the_wrong_kind_is_unreadable_not_empty(self):
        for version in (False, 0, "", [], "x"):
            with self.subTest(latestVersion=version), self.assertRaises(PayloadError):
                body = self.dataset()
                body["latestVersion"] = version
                self.record(body)
        for what, wrong in (("metadataBlocks", True), ("metadataBlocks", []), ("metadataBlocks", {"citation": 5}),
                            ("metadataBlocks", {"citation": {"fields": {}}}), ("metadataBlocks", {"citation": {"fields": False}})):
            with self.subTest(what=what, wrong=wrong), self.assertRaises(PayloadError):
                self.record(self.dataset(**{what: wrong}))
        for wrong in ({}, "x", 5, [5], [{"authorName": 5}], [{"authorName": {"value": 5}}], [7]):
            with self.subTest(author=wrong), self.assertRaises(PayloadError):
                d = self.dataset()
                d["latestVersion"]["metadataBlocks"]["citation"]["fields"][-1]["value"] = wrong
                self.record(d)

    def test_nothing_where_a_container_may_be_left_out_is_nothing(self):
        for version in (None, {}):
            body = self.dataset()
            body["latestVersion"] = version
            r = self.record(body)
            self.assertEqual((r["title"], r["authors"], r["file_count"]), (None, [], 0))

    def test_the_file_count_is_unknown_when_the_files_cannot_be_read_and_never_zero(self):
        for files, want in ((False, None), ({}, None), ("x", None), ([], 0), (None, 0), ([7, {"label": "a"}], 2)):
            with self.subTest(files=files):
                self.assertEqual(self.record(self.dataset(files=files))["file_count"], want)

    def test_a_search_hit_whose_lists_are_not_lists_is_unreadable(self):
        hit = {"name": "N", "global_id": "doi:10.7910/DVN/X1", "authors": ["B"], "subjects": ["S"], "published_at": "2021-05-01T00:00:00Z", "fileCount": 2}
        def search_record(item):
            return dv.search_record(dv.BASE, "harvard_dataverse", decode("harvard_dataverse", dv.HIT, item))
        self.assertEqual(search_record(hit)["identity"], "doi:10.7910/dvn/x1")
        for name, wrong in (("authors", 5), ("authors", {}), ("authors", "B"), ("subjects", False), ("subjects", ""), ("global_id", 5), ("description", [1])):
            with self.subTest(name=name, wrong=wrong), self.assertRaises(PayloadError):
                search_record({**hit, name: wrong})


class StatisticalAnswers(unittest.TestCase):
    """BEA's and Census's tables are one record's rows, read whole; a listing that is not a list, or a table that is not rows, is unreadable."""

    def bea(self, results, method="GETDATASETLIST"):
        t = FakeTransport()
        t.add("GET", "https://apps.bea.gov/api/data/", body={"BEAAPI": {"Results": results}})
        c = Client(broker=Broker({"bea": RatePolicy(per_second=1000)}), transport=t, secrets=lambda n, f=None: "k")
        return bea.data(c, {"method": method})

    def test_bea_a_listing_that_is_there_and_is_not_a_list_is_not_zero_rows(self):
        for wrong in (False, 0, "", {}, "x", 5):
            with self.subTest(dataset=wrong), self.assertRaises(PayloadError):
                self.bea({"Dataset": wrong})
        self.assertEqual(self.bea({"Dataset": [{"DatasetName": "NIPA"}]})["records"][0]["row_count"], 1)
        self.assertEqual(self.bea({"Dataset": {"DatasetName": "NIPA"}})["records"][0]["row_count"], 1, "BEA's habit for a list of one: the one row, bare")
        self.assertEqual(self.bea({"Dataset": []})["records"][0]["row_count"], 0)
        self.assertEqual(self.bea({})["records"][0]["row_count"], 0, "BEA names no listing here: an empty one")

    def test_bea_a_catalogue_whose_listing_is_missing_or_names_nothing_is_not_an_empty_catalogue(self):
        t = FakeTransport()
        c = Client(broker=Broker({"bea": RatePolicy(per_second=1000)}), transport=t, secrets=lambda n, f=None: "k")
        for results in ({}, {"Dataset": {}}, {"Dataset": False}, {"Dataset": [{"x": 1}]}, {"Dataset": {"x": 1}}):
            t.routes.clear()
            t.add("GET", "https://apps.bea.gov/api/data/", body={"BEAAPI": {"Results": results}})
            with self.subTest(results=results), self.assertRaises(PayloadError):
                bea.catalog(c)
        t.routes.clear()
        t.add("GET", "https://apps.bea.gov/api/data/", body={"BEAAPI": {"Results": {"Dataset": []}}})
        self.assertEqual(bea.catalog(c)["entries"], [], "a listing that is there and lists nothing")

    def test_census_a_row_that_is_not_a_list_makes_the_table_unreadable_not_shorter(self):
        t = FakeTransport()
        c = Client(broker=Broker({"census": RatePolicy(per_second=1000)}), transport=t, secrets=lambda n, f=None: "k")
        for table in ([["NAME", "v"], ["a", "1"], 5], [["NAME", "v"], {}], [["NAME", "v"], ""], [["NAME", False], ["a", "1"]], [["NAME", "v"], {"a": 1}]):
            t.routes.clear()
            t.add("GET", "https://api.census.gov/data/2022/acs/acs1", body=table)
            with self.subTest(table=table), self.assertRaises(PayloadError):
                census.data(c, {"dataset": "2022/acs/acs1", "get": "NAME,v"})
        t.routes.clear()
        t.add("GET", "https://api.census.gov/data/2022/acs/acs1", body=[["NAME", "v"], ["a", "1"], []])
        self.assertEqual(census.data(c, {"dataset": "2022/acs/acs1", "get": "NAME,v"})["records"][0]["row_count"], 2)


class Structures(unittest.TestCase):
    """SDMX: the message's structure, data sets and observations are what they are, or the message is unreadable."""

    @staticmethod
    def message(value):
        return sdmx.message("ecb", value)

    def test_a_structure_that_is_there_and_is_not_an_object_is_unreadable_not_none(self):
        for wrong in (False, 0, "", [], "x", 5):
            with self.subTest(structure=wrong), self.assertRaises(PayloadError):
                self.message({"structure": wrong, "dataSets": []})
        for nothing in ({}, {"structure": None}, {"structures": None}, {"structures": []}, {"data": None}):
            self.assertIsNone(sdmx.structure(self.message(nothing)))
        self.assertEqual(plain(sdmx.structure(self.message({"structures": [{"a": 1}]})).raw), {"a": 1})
        self.assertEqual(plain(sdmx.structure(self.message({"data": {"structures": [{"a": 2}]}})).raw), {"a": 2})
        for wrong in ({"structures": {"a": 1}}, {"structures": 5}, {"structures": [5]}, {"data": 5}, {"data": []}, {"data": ""}):
            with self.subTest(message=wrong), self.assertRaises(PayloadError):
                self.message(wrong)

    def test_data_sets_inside_a_data_wrapper_that_is_not_one_are_unreadable(self):
        for wrong in (False, 0, "", [], 5):
            with self.subTest(data=wrong), self.assertRaises(PayloadError):
                self.message({"data": wrong})
        self.assertEqual(len(sdmx.datasets(self.message({"data": None}))), 0)

    def test_dimensions_and_observations_that_are_there_and_the_wrong_kind_are_unreadable(self):
        good = {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}], "observation": [{"id": "T", "values": [{"id": "2026"}]}]}}
        for dims in (False, 0, "", [], 5):
            with self.subTest(dimensions=dims), self.assertRaises(PayloadError):
                self.message({"structure": {"dimensions": dims}, "dataSets": []})
        for part in ("series", "observation"):
            for wrong in (False, 0, "", {}, 5):
                with self.subTest(part=part, value=wrong), self.assertRaises(PayloadError):
                    self.message({"structure": {"dimensions": {**good["dimensions"], part: wrong}}})

        def series(observations):
            msg = self.message({"structure": good, "dataSets": [{"series": {"0": {"observations": observations}}}]})
            members_ = sdmx.series_members(msg)
            assert len(members_) == 1
            return members_.at(0), sdmx.series_reader(msg)
        member, read = series({"0": [1.5]})
        self.assertEqual(plain(read(member)["observations"]), [("2026", 1.5)])
        for wrong in (False, 0, "", [], 5):
            with self.subTest(observations=wrong):
                member, read = series(wrong)
                self.assertTrue(is_unreadable(member), "a series whose observations are not an object is one unreadable series")
        member, read = series(None)
        self.assertEqual(read(member)["observations"], [], "a series that has none")


class Loaders(unittest.TestCase):
    """The registry loaders end only on what the provider's end rule says, as the lanes do: a continuation they cannot read is a failed load."""

    def load(self, loader, url, pages, **kwargs):
        t = FakeTransport()
        for prefix, body in pages:
            t.add("GET", prefix, body=body)
        c = Client(broker=Broker({"crossref": RatePolicy(per_second=1000), "datacite": RatePolicy(per_second=1000)}), transport=t, sleep=lambda s: None)
        return [r["identity"] for r in loader(c, **kwargs)]

    JOURNAL = lambda self, i: {"title": f"J{i}", "ISSN": [f"1234-567{i}"]}   # noqa: E731

    def test_crossref_journals_a_full_page_whose_next_cursor_cannot_be_read_fails_the_load(self):
        rows = 2
        first = f"{registries.CROSSREF_JOURNALS}?rows=2&cursor=%2A"
        for cursor in (None, "", "  ", -1, False, 1.5, [], {}, ["a"]):
            message = {"items": [self.JOURNAL(1), self.JOURNAL(2)]}
            if cursor is not None:
                message["next-cursor"] = cursor
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                self.load(registries.crossref_journals, "", [(first, {"message": message})], rows=rows)

    def test_crossref_journals_control_a_cursor_that_is_read_continues_and_a_short_page_ends(self):
        first, second = f"{registries.CROSSREF_JOURNALS}?rows=2&cursor=%2A", f"{registries.CROSSREF_JOURNALS}?rows=2&cursor=c2"
        got = self.load(registries.crossref_journals, "", [(first, {"message": {"items": [self.JOURNAL(1), self.JOURNAL(2)], "next-cursor": "c2"}}),
                                                         (second, {"message": {"items": [self.JOURNAL(3)]}})], rows=2)
        self.assertEqual(got, ["issn:1234-5671", "issn:1234-5672", "issn:1234-5673"])
        self.assertEqual(self.load(registries.crossref_journals, "", [(first, {"message": {"items": []}})], rows=2), [])

    def test_datacite_repositories_a_total_of_pages_that_cannot_be_read_fails_the_load(self):
        first = f"{registries.DATACITE_REPOSITORIES}?page%5Bsize%5D=2&page%5Bnumber%5D=1"
        data = [{"id": "r.one", "attributes": {"name": "one"}}, {"id": "r.two", "attributes": {"name": "two"}}]
        for meta in ({}, {"totalPages": None}, {"totalPages": "2"}, {"totalPages": 0}, {"totalPages": False}, {"totalPages": 1.5}, {"totalPages": -1}, 5, False, [1]):
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                self.load(registries.datacite_repositories, "", [(first, {"data": data, "meta": meta})], size=2)

    def test_datacite_repositories_control_pages_are_read_to_the_last(self):
        first = f"{registries.DATACITE_REPOSITORIES}?page%5Bsize%5D=2&page%5Bnumber%5D=1"
        second = f"{registries.DATACITE_REPOSITORIES}?page%5Bsize%5D=2&page%5Bnumber%5D=2"
        got = self.load(registries.datacite_repositories, "", [
            (first, {"data": [{"id": "r.one", "attributes": {}}, {"id": "r.two", "attributes": {}}], "meta": {"totalPages": 2}}),
            (second, {"data": [{"id": "r.three", "attributes": {}}], "meta": {"totalPages": 2}})], size=2)
        self.assertEqual(got, ["repository:datacite:r.one", "repository:datacite:r.two", "repository:datacite:r.three"])


class SocrataTimestamps(unittest.TestCase):
    """A view's `rowsUpdatedAt` is epoch seconds: the leading digits of 1694726470 are not the year 1694 (found by the invariant harness)."""

    def test_the_year_of_a_view_is_the_year_of_its_timestamp(self):
        for seconds, year in ((1694726470, 2023), (0, 1970), (1767225600, 2026)):
            self.assertEqual(socrata._epoch_year(seconds), year, seconds)
            self.assertEqual(datetime.fromtimestamp(seconds, timezone.utc).year, year, "the oracle: the standard library's reading of the same seconds")
        self.assertIsNone(socrata._epoch_year(None))
        for wrong in ("2023", "", False, True, [], {}, 1.5):   # not a whole number of seconds: the view does not decode
            with self.assertRaises(PayloadError, msg=repr(wrong)):
                decode("socrata", socrata.VIEW, {"id": "abcd-1231", "rowsUpdatedAt": wrong})
        with self.assertRaises(PayloadError):   # a whole number that is no moment in time
            socrata._epoch_year(10 ** 30)


if __name__ == "__main__":
    unittest.main()
