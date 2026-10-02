"""Task 2b-repair-7b / 2b-repair-8: every provider member is decoded alone.

One member that is not an object (or whose decoding raises) must cost that member only: the readable ones
beside it stand as a partial lower bound. OpenCitations' enrich lost the whole answer to one (2b-repair-7b), an
audit found nine more such paths, Socrata's page and 2b-repair-7's reproductions were the same defect one adapter at a
time (2b-repair A4), and Hugging Face's file siblings and ECB's data sets were still the same after all of that
(Astra, 2b-repair-7 review). A source scan for loops that call a record builder missed each new spelling, so it is
gone: a provider's list reaches an adapter as a `Members` that can only be decoded member by member
(core/payload.py), and tests/test_member_isolation.py holds that property directly. This file holds the behaviour:

  * EveryMemberAlone: for every path that turns a provider's list into records, through the real adapters, one member
    that is not an object beside readable ones costs that member only, the readable ones stand, and a member that is
    readable but names nothing to report (a reference with no DOI) is omitted, not counted as lost. The paths include
    the lists inside a member whose members become records: Hugging Face's `siblings` and ECB's `dataSets`.
  * ThroughTheRouter and RoutedMixedAnswers: what the lane entry says about each such answer through the real router
    (Astra's Hugging Face and ECB reproductions among them), each with a readable control.
  * FirstResult: a lookup asks for ONE result and reads the first, through the same decoder (OpenCitations'
    metadata lookup read `rows[0]` itself until 2b-repair-8).

Oracle: the identities the bodies below name, stated here by hand. What the lists that are NOT members do — a table's
rows, a catalogue's entries — is not decided here: tests/inventory.py lists them, with why (held by tests/test_inventory.py).
"""
from __future__ import annotations

import unittest

from research_gateway import adapters
from research_gateway.adapters import (bis, bls, core, crossref, doaj, ecb, europepmc, harvard_dataverse as dv, huggingface, kaggle, openaire,
                                       opencitations, semanticscholar, unpaywall)
from research_gateway.adapters.base import AdapterError, Client, FakeTransport, PayloadError
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.registry.load import read_seed
from research_gateway.core.payload import plain
from tests.test_routing import SEED_NO_INDEX

SIDS = ("crossref", "semanticscholar", "unpaywall", "opencitations", "kaggle", "harvard_dataverse", "bls", "ecb", "bis", "core", "doaj",
        "europepmc", "openaire", "huggingface")
KEYS = {("kaggle", "username"): "u", ("kaggle", "key"): "k", ("bls", None): "REG", ("core", None): "c",
        ("openaire", "client_id"): "i", ("openaire", "client_secret"): "s"}


def client():
    t = FakeTransport()
    return Client(broker=Broker({s: RatePolicy(per_second=1000) for s in SIDS}), transport=t,
                  secrets=lambda n, f=None: KEYS.get((n, f))), t


OC = {"oci": "1-2", "citing": "doi:10.9000/citer omid:br/1", "cited": "doi:10.1234/abc", "creation": "2022-01", "timespan": "P1Y"}
DV_FILE = {"label": "wms.csv", "restricted": False, "dataFile": {"id": 900, "filename": "wms.csv", "contentType": "text/csv", "filesize": 12}}


def dataverse(files):
    return {"data": {"id": 42, "authority": "10.7910", "identifier": "DVN/OY6CBK", "persistentUrl": "https://doi.org/10.7910/DVN/OY6CBK",
                     "publisher": "Harvard Dataverse",
                     "latestVersion": {"versionNumber": 1, "versionMinorNumber": 0, "license": {"name": "CC0 1.0"},
                                       "metadataBlocks": {"citation": {"fields": [{"typeName": "title", "value": "WMS"}]}}, "files": files}}}


def sdmx(series: list) -> dict:
    """An SDMX-JSON message whose series are keyed by position: the readable one at 0:0, each other at its own."""
    return {"structure": {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}, {"id": "CURRENCY", "values": [{"id": "USD"}, {"id": "GBP"}]}],
                                         "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-09-01"}]}]}},
            "dataSets": [{"series": {("0:0" if isinstance(m, dict) else f"0:{i + 1}"): m for i, m in enumerate(series)}}]}


SDMX_STRUCTURE = {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}, {"id": "CURRENCY", "values": [{"id": "USD"}, {"id": "GBP"}]}],
                                 "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-09-01"}]}]}}


def sdmx_sets(datasets: list) -> dict:
    """An SDMX-JSON message whose DATA SETS are the members, each holding series: ECB's other list of members."""
    return {"structure": SDMX_STRUCTURE, "dataSets": datasets}


def siblings(files: list) -> dict:
    """A Hugging Face dataset envelope (valid id and licence) whose `siblings`, its files, are the members."""
    return {"id": "review/dataset", "cardData": {"license": "cc0-1.0"}, "siblings": files}


# label, call, url prefix, body for a list of members, a readable member, the identity it names, the answer's list
PATHS = [
    ("opencitations citations", lambda c: opencitations.enrich(c, "doi:10.1234/abc", "citations"),
     "https://api.opencitations.net/index/v2/citations/", lambda ms: ms, OC, "doi:10.9000/citer", "items"),
    ("opencitations references", lambda c: opencitations.enrich(c, "doi:10.1234/abc", "references"),
     "https://api.opencitations.net/index/v2/references/", lambda ms: ms,
     {**OC, "citing": "doi:10.1234/abc", "cited": "doi:10.8000/cited"}, "doi:10.8000/cited", "items"),
    ("crossref references", lambda c: crossref.enrich(c, "doi:10.1234/x", "references"), "https://api.crossref.org/works/10.1234/x",
     lambda ms: {"message": {"DOI": "10.1234/x", "reference": ms}}, {"DOI": "10.5555/r1"}, "doi:10.5555/r1", "items"),
    ("semanticscholar citations", lambda c: semanticscholar.enrich(c, "doi:10.1234/abc", "citations"),
     "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234/abc/citations", lambda ms: {"data": ms},
     {"citingPaper": {"paperId": "c1", "externalIds": {"DOI": "10.9000/cit"}, "title": "Citer"}}, "doi:10.9000/cit", "items"),
    ("semanticscholar references", lambda c: semanticscholar.enrich(c, "doi:10.1234/abc", "references"),
     "https://api.semanticscholar.org/graph/v1/paper/DOI:10.1234/abc/references", lambda ms: {"data": ms},
     {"citedPaper": {"paperId": "r1", "externalIds": {"DOI": "10.8000/ref"}, "title": "Cited"}}, "doi:10.8000/ref", "items"),
    ("unpaywall locations", lambda c: unpaywall.enrich(c, "doi:10.1234/abc"), "https://api.unpaywall.org/v2/10.1234/abc",
     lambda ms: {"doi": "10.1234/abc", "is_oa": True, "oa_status": "gold", "title": "T", "oa_locations": ms},
     {"url": "https://pub.example/a", "host_type": "publisher"}, "doi:10.1234/abc", "items"),
    ("kaggle file listing", lambda c: kaggle.fetch(c, "kaggle:owner/ds"), "https://www.kaggle.com/api/v1/datasets/list/owner/ds",
     lambda ms: {"datasetFiles": ms}, {"name": "train.csv", "totalBytes": 10}, "kaggle:owner/ds#train.csv", "records"),
    ("dataverse file listing", lambda c: dv.fetch(c, "doi:10.7910/DVN/OY6CBK"), "https://dataverse.harvard.edu/api/datasets/:persistentId/",
     dataverse, DV_FILE, "doi:10.7910/dvn/oy6cbk#900", "records"),
    ("bls series", lambda c: bls.data(c, {"series": "CUUR0000SA0"}), "https://api.bls.gov/publicAPI/v2/timeseries/data/",
     lambda ms: {"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": ms}},
     {"seriesID": "CUUR0000SA0", "catalog": {"series_title": "CPI-U"}, "data": [{"year": "2026", "period": "M07", "value": "320.1"}]},
     "series:bls:CUUR0000SA0", "records"),
    ("ecb series", lambda c: ecb.data(c, {"dataflow": "EXR", "key": "D.USD"}), "https://data-api.ecb.europa.eu/service/data/EXR/",
     sdmx, {"observations": {"0": [1.08]}}, "series:ecb:EXR:D.USD", "records"),
    # the lists inside a member whose members become records (2b-repair-8): each was read before the decoder ran
    ("ecb data sets", lambda c: ecb.data(c, {"dataflow": "EXR", "key": "D.USD"}), "https://data-api.ecb.europa.eu/service/data/EXR/",
     sdmx_sets, {"series": {"0:0": {"observations": {"0": [1.08]}}}}, "series:ecb:EXR:D.USD", "records"),
    ("hugging face files", lambda c: huggingface.fetch(c, "hf:review/dataset"), "https://huggingface.co/api/datasets/review/dataset",
     siblings, {"rfilename": "train.csv"}, "hf:review/dataset#train.csv", "records"),
]


def split(out: dict, key: str) -> tuple[list[str], int]:
    """(the identities an answer kept, how many members it reported dropped: the Nones the router counts)."""
    listed = out[key]
    return [r["identity"] for r in listed if r], sum(1 for r in listed if not r)


class EveryMemberAlone(unittest.TestCase):
    def ask(self, call, prefix, body):
        c, t = client()
        t.add("POST" if "bls.gov" in prefix else "GET", prefix, body=body)
        try:
            return call(c)
        except Exception as e:
            self.fail(f"one member's failure escaped as {e!r}: it is that member's, not the answer's")

    def test_control_a_readable_member_alone_is_kept_whole(self):
        for label, call, prefix, body, ok, identity, key in PATHS:
            with self.subTest(path=label):
                self.assertEqual(split(self.ask(call, prefix, body([ok])), key), ([identity], 0))

    def test_a_member_that_is_not_an_object_costs_that_member_only(self):
        """The reported defect (OpenCitations), and every other path an audit found: one member that is not an
        object, before or after a readable one or among several non-objects, no longer loses the answer."""
        for label, call, prefix, body, ok, identity, key in PATHS:
            for members, lost in (([ok, 7], 1), ([7, ok], 1), (["not a member", ok, None, [1]], 3)):
                with self.subTest(path=label, members=members):
                    self.assertEqual(split(self.ask(call, prefix, body(members)), key), ([identity], lost))

    def test_members_that_are_all_unreadable_are_all_dropped(self):
        for label, call, prefix, body, ok, identity, key in PATHS:
            with self.subTest(path=label):
                self.assertEqual(split(self.ask(call, prefix, body([7])), key), ([], 1), "dropped, so the router reports it unobserved")

    def test_a_member_that_fails_to_decode_is_that_members_loss_too(self):
        """Not only a non-object: an object whose own decoding raises (a DOI that is a number, a linked paper that is
        not an object) is the same, in the paths that read such fields themselves."""
        bad = {"crossref references": {"DOI": 7}, "semanticscholar citations": {"citingPaper": 7},
               "opencitations citations": {**OC, "citing": 7}, "hugging face files": {"rfilename": 7},
               "ecb data sets": {"series": [1]}}
        for label, call, prefix, body, ok, identity, key in PATHS:
            if label in bad:
                with self.subTest(path=label):
                    self.assertEqual(split(self.ask(call, prefix, body([ok, bad[label]])), key), ([identity], 1))

    def test_control_a_member_naming_nothing_is_omitted_not_dropped(self):
        """A reference with no DOI, a citation row with none, an unidentified linked paper, a location that links
        nowhere: readable, and nothing to report. The answer is whole, not a lower bound (the same as before)."""
        nothing = {"opencitations citations": {**OC, "citing": "omid:br/1 pmid:123"},
                   "opencitations references": {**OC, "cited": "omid:br/2"},
                   "crossref references": {"unstructured": "Smith 2020, a book without a DOI"},
                   "semanticscholar citations": {"citingPaper": {"title": "unidentified"}},
                   "semanticscholar references": {"citedPaper": None},
                   "unpaywall locations": {"host_type": "repository"}}
        for label, call, prefix, body, ok, identity, key in PATHS:
            if label in nothing:
                with self.subTest(path=label):
                    self.assertEqual(split(self.ask(call, prefix, body([nothing[label], ok])), key), ([identity], 0))

    def test_bis_series_are_decoded_through_the_one_decoder_too(self):
        """BIS reads SDMX-ML: its series come out of an XML parse already decoded, so none can be a non-object;
        the lane still builds its records through the decoder, and two series stand as two records."""
        c, t = client()
        t.add("GET", "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_EER/1.0/", body=(
            '<message:StructureSpecificData xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message">'
            '<message:DataSet><Series FREQ="M" REF_AREA="US"><Obs TIME_PERIOD="2026-01" OBS_VALUE="1.5"/></Series>'
            '<Series FREQ="M" REF_AREA="GB"><Obs TIME_PERIOD="2026-01" OBS_VALUE="2.5"/></Series></message:DataSet>'
            '</message:StructureSpecificData>'))
        self.assertEqual(split(bis.data(c, {"dataflow": "WS_EER", "key": "M.US"}), "records"),
                         (["series:bis:WS_EER:M.US", "series:bis:WS_EER:M.GB"], 0))


class ThroughTheRouter(unittest.TestCase):
    """OpenCitations enrich through the real router and seed: what the lane entry says about each answer."""

    def lane(self, members):
        c, t = client()
        router = R.Router(SEED_NO_INDEX, adapters.load_all())
        t.add("GET", "https://api.opencitations.net/index/v2/citations/doi:10.1000/x", body=members)
        out = R.execute(router, {"request_type": "enrich", "identity": "doi:10.1000/x", "what": "citations"}, c)
        return out, {e["source"]: e for e in out["lanes"]}["opencitations"]

    def test_one_unreadable_row_beside_a_readable_one_is_a_partial_lower_bound(self):
        out, e = self.lane([OC, 7])
        self.assertEqual((e["coverage"], e["completeness"], e.get("error_class"), e.get("count"), e.get("retrieved")),
                         ("searched_ok", "partial", "payload_invalid", 1, ["doi:10.9000/citer"]))
        self.assertEqual([r["identity"] for r in out["records"]], ["doi:10.9000/citer"], "what was readable is kept")
        self.assertTrue(any("malformed record(s) dropped" in f for f in out["facts"]))

    def test_every_row_unreadable_is_unobserved_never_zero(self):
        _, e = self.lane([7])
        self.assertEqual((e["coverage"], e["completeness"], e["error_class"]), ("provider_unavailable", "unobserved", "payload_invalid"))
        self.assertNotIn("count", e)

    def test_control_readable_rows_are_complete(self):
        _, e = self.lane([OC])
        self.assertEqual((e["coverage"], e["completeness"], e["count"], e.get("error_class")), ("searched_ok", "complete", 1, None))


class RoutedMixedAnswers(unittest.TestCase):
    """Astra's two R7-2 reproductions through the real adapters and router, each with a readable control: the dataset's
    own identity and licence (HF) and the message's own structure (ECB) were intact, and one malformed member of a list
    inside the answer lost every readable record beside it — no records, unavailable, no lower-bound count."""

    def lane(self, sid, body, request, url):
        c, t = client()
        t.add("GET", url, body=body)
        out = R.execute(R.Router(read_seed(), adapters.load_all()), request, c)
        return out, {e["source"]: e for e in out["lanes"]}[sid]

    def hf(self, files):
        return self.lane("huggingface", siblings(files), {"request_type": "fetch", "target": "hf:review/dataset"},
                         "https://huggingface.co/api/datasets/review/dataset")

    def ecb(self, datasets):
        return self.lane("ecb", sdmx_sets(datasets), {"request_type": "data", "source": "ecb", "params": {"dataflow": "EXR", "key": "D.USD"}},
                         "https://data-api.ecb.europa.eu/service/data/EXR/")

    GOOD_FILE, GOOD_SET = {"rfilename": "train.csv"}, {"series": {"0:0": {"observations": {"0": [1.25]}}}}
    HF_ID, ECB_ID = "hf:review/dataset#train.csv", "series:ecb:EXR:D.USD"

    def shape(self, e):
        return (e["coverage"], e["completeness"], e.get("count"), e.get("error_class"), e.get("retrieved"))

    def test_a_readable_file_survives_a_malformed_sibling(self):
        for files in ([self.GOOD_FILE, 7], [7, self.GOOD_FILE], [{}, self.GOOD_FILE, "x", {"rfilename": 5}]):
            with self.subTest(files=files):
                out, e = self.hf(files)
                self.assertEqual(self.shape(e), ("searched_ok", "partial", 1, "payload_invalid", [self.HF_ID]))
                self.assertEqual([r["identity"] for r in out["records"]], [self.HF_ID], "what was readable is kept")
                self.assertTrue(any("malformed record(s) dropped" in f for f in out["facts"]))

    def test_a_readable_series_survives_a_malformed_data_set(self):
        for datasets in ([self.GOOD_SET, 7], [7, self.GOOD_SET], [self.GOOD_SET, {"series": 5}], [{"series": [self.GOOD_SET]}, self.GOOD_SET]):
            with self.subTest(datasets=datasets):
                out, e = self.ecb(datasets)
                self.assertEqual(self.shape(e), ("searched_ok", "partial", 1, "payload_invalid", [self.ECB_ID]))
                self.assertEqual([r["identity"] for r in out["records"]], [self.ECB_ID])

    def test_nothing_readable_is_unobserved_never_zero(self):
        for out, e in (self.hf([7]), self.hf([{}, "x"]), self.ecb([7]), self.ecb([7, {"series": 5}])):
            self.assertEqual((e["coverage"], e["completeness"], e["error_class"]), ("provider_unavailable", "unobserved", "payload_invalid"))
            self.assertNotIn("count", e)

    def test_control_readable_lists_are_complete(self):
        for out, identity in ((self.hf([self.GOOD_FILE, {"rfilename": "test.csv"}])[0], self.HF_ID), (self.ecb([self.GOOD_SET])[0], self.ECB_ID)):
            (e,) = [e for e in out["lanes"] if e["source"] in ("huggingface", "ecb")]
            self.assertEqual((e["coverage"], e["completeness"], e.get("error_class")), ("searched_ok", "complete", None))
            self.assertIn(identity, [r["identity"] for r in out["records"]])

    def test_a_dataset_is_read_whole_beside_unreadable_files_in_every_lane_that_returns_it(self):
        """The dataset record no longer carries its files, so a file that cannot be read cannot take the dataset
        with it: resolve and find both return it, with the count of files the Hub listed."""
        dataset = {"id": "review/dataset", "cardData": {"license": "cc0-1.0"}, "siblings": [7, {"rfilename": "a"}, None]}
        try:
            c, t = client()
            t.add("GET", "https://huggingface.co/api/datasets/review/dataset", body=dataset)
            resolved = huggingface.resolve(c, "hf:review/dataset")
            c, t = client()
            t.add("GET", "https://huggingface.co/api/datasets?", body=[dataset])
            found = huggingface.find(c, "review", limit=2)
        except Exception as e:
            self.fail(f"one unreadable file lost the dataset ({e!r}): it is that file's, not the dataset's")
        for record in (resolved, found["records"][0]):
            self.assertEqual((record["identity"], record["license"], record["file_count"]), ("hf:review/dataset", "cc0-1.0", 3))
            self.assertNotIn("files", record)
        self.assertEqual(len(found["records"]), 1, "the dataset is not dropped")

    def test_opencitations_metadata_is_the_first_result_or_an_unreadable_answer(self):
        def lane(body):
            c, t = client()
            t.add("GET", "https://api.opencitations.net/meta/v1/metadata/doi:10.1000/x", body=body)
            out = R.execute(R.Router(SEED_NO_INDEX, adapters.load_all()),
                            {"request_type": "enrich", "identity": "doi:10.1000/x", "what": "metadata"}, c)
            return out, {e["source"]: e for e in out["lanes"]}["opencitations"]
        out, e = lane([{"title": "T", "author": "A", "pub_date": "2020", "venue": "V"}, 7])
        self.assertEqual((e["coverage"], e["completeness"], e["count"]), ("searched_ok", "complete", 1), "only the first result is read")
        out, e = lane([7, {"title": "T"}])
        self.assertEqual((e["coverage"], e["completeness"], e["error_class"]), ("provider_unavailable", "unobserved", "payload_invalid"),
                         "an unreadable first result is not 'not found', and is not answered by the one after it")
        self.assertNotIn("count", e)


class FirstResult(unittest.TestCase):
    """A lookup asks for ONE result and reads the first, through the same decoder (base.first_member): a first result
    that cannot be read is an unreadable answer, never 'not found' and never answered by the result after it, which
    may be some other work. Oracle: the identity each body names, stated by hand."""

    CORE = {"id": 1, "doi": "10.1038/nature12373", "title": "T"}
    LOOKUPS = [
        ("core", lambda c: core.resolve(c, "doi:10.1038/nature12373"), "https://api.core.ac.uk/v3/search/works",
         lambda ms: {"results": ms}, CORE, "doi:10.1038/nature12373"),
        ("core full text", lambda c: core.enrich(c, "doi:10.1038/nature12373"), "https://api.core.ac.uk/v3/search/works",
         lambda ms: {"results": ms}, CORE, "doi:10.1038/nature12373"),
        ("doaj article", lambda c: doaj.resolve(c, "doi:10.1234/x"), "https://doaj.org/api/search/articles/", lambda ms: {"results": ms},
         {"id": "d1", "bibjson": {"title": "T", "identifier": [{"type": "doi", "id": "10.1234/x"}]}}, "doi:10.1234/x"),
        ("doaj journal", lambda c: doaj.resolve(c, "issn:1234-5679"), "https://doaj.org/api/search/journals/", lambda ms: {"results": ms},
         {"bibjson": {"title": "J", "publisher": {"name": "P"}}}, "issn:1234-5679"),
        ("europepmc", lambda c: europepmc.resolve(c, "doi:10.1234/x"), "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
         lambda ms: {"resultList": {"result": ms}}, {"doi": "10.1234/x", "title": "T", "id": "1", "source": "MED"}, "doi:10.1234/x"),
        ("openaire", lambda c: openaire.resolve(c, "doi:10.1234/x"), "https://api.openaire.eu/graph/v1/researchProducts",
         lambda ms: {"header": {"numFound": len(ms)}, "results": ms},
         {"id": "x", "mainTitle": "T", "pids": [{"scheme": "doi", "value": "10.1234/x"}]}, "doi:10.1234/x"),
        ("opencitations metadata", lambda c: opencitations.enrich(c, "doi:10.1234/x", "metadata"),
         "https://api.opencitations.net/meta/v1/metadata/", lambda ms: ms,
         {"title": "T", "author": "A, B; C, D", "pub_date": "2020-05", "venue": "J [issn:1234-5679]"}, "doi:10.1234/x"),
    ]

    def outcome(self, call, prefix, body):
        """('record', identity) | ('none',) | (the exception's type name, its message)."""
        openaire.reset_token()
        c, t = client()
        t.add("POST", "https://aai.openaire.eu/oidc/token", body={"access_token": "tok", "expires_in": 3600})
        t.add("GET", prefix, body=body)
        try:
            out = call(c)
        except Exception as e:
            return type(e).__name__, str(e)
        if isinstance(out, dict) and "items" in out:   # an enrich: its one item, or none
            out = out["items"][0] if out["items"] else None
        return ("none",) if out is None else ("record", out["identity"])

    def test_control_a_readable_first_result_is_the_record_and_none_is_not_found(self):
        for label, call, prefix, body, ok, identity in self.LOOKUPS:
            with self.subTest(lookup=label):
                self.assertEqual(self.outcome(call, prefix, body([ok])), ("record", identity))
                self.assertEqual(self.outcome(call, prefix, body([ok, 7])), ("record", identity), "only the first result is read")
                self.assertEqual(self.outcome(call, prefix, body([])), ("none",))

    def test_an_unreadable_first_result_is_an_unreadable_answer(self):
        for label, call, prefix, body, ok, identity in self.LOOKUPS:
            for members in ([7], [7, ok]):
                with self.subTest(lookup=label, members=members):
                    got = self.outcome(call, prefix, body(members))
                    self.assertEqual(got[0], "PayloadError", got)
                    self.assertIn("first result cannot be read", got[1])


class DataverseDownloadMembership(unittest.TestCase):
    """A download is authorised against the dataset's own file members (R-6): read through the decoder, a file
    member that cannot be read neither blocks a readable file nor passes for the one asked for."""

    def download(self, files, file_id):
        """What asking for `file_id` of a dataset listing `files` comes to: the bytes, or the refusal's type and message."""
        c, t = client()
        t.add("GET", "https://dataverse.harvard.edu/api/datasets/:persistentId/", body=dataverse(files))
        t.add("GET", "https://dataverse.harvard.edu/api/access/datafile/", body="a,b\n", headers={"Content-Type": "text/csv"})
        try:
            return plain(dv.fetch(c, "doi:10.7910/DVN/OY6CBK", file_id=file_id, download=True)["content"])
        except (AdapterError, PayloadError, AttributeError) as e:
            return type(e).__name__, str(e)

    def test_an_unreadable_member_does_not_block_a_readable_file(self):
        self.assertEqual(self.download([7, DV_FILE], 900), b"a,b\n")

    def test_a_file_that_is_not_in_the_dataset_is_refused_as_such(self):
        kind, why = self.download([DV_FILE], 901)
        self.assertEqual(kind, "AdapterError")
        self.assertIn("does not belong", why)

    def test_a_file_that_may_be_the_unreadable_member_is_not_called_foreign(self):
        kind, why = self.download([7, DV_FILE], 901)
        self.assertEqual(kind, "PayloadError")
        self.assertIn("unreadable", why)


if __name__ == "__main__":
    unittest.main()
