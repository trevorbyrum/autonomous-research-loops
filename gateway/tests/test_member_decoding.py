"""Task 2b-repair-7b: every provider member is decoded alone, through the one decoder.

An adapter that builds records from a provider's list in a loop of its own lets one member that is not
an object (or whose decoding raises) lose the whole answer. OpenCitations' enrich did, and an audit found
the same in Crossref's and Semantic Scholar's enrich, Unpaywall, the Kaggle and Dataverse file listings,
BLS series and ECB series (2b-repair A4 and the Socrata page of 2b-repair-7 were this defect, one adapter at
a time). The property now lives in one place, base.members(), and two checks hold it:

  * OneDecoder reads the SOURCE: code under adapters/ that builds records in a loop, comprehension or
    map of its own, a call to make_record or to a function that builds records outside the arguments of
    members() or first_member(), fails here, unless NOT_PROVIDER_MEMBERS lists it with why. What it covers is the
    provider's members that become records; payload rows of one record (a table's, a series'
    observations) and catalogue entries are not those, and a statement of what the check does not
    see is below.
  * EveryMemberAlone is the behaviour, through the real adapters and the real router: for every path
    that turns a provider's list into records, one member that is not an object beside readable ones
    costs that member only, the readable ones stand as a partial lower bound, and a member that is
    readable but names nothing to report (a reference with no DOI) is omitted, not counted as lost.
    The single-result lookups (resolve) read their first result the same way (FirstResult).
    Oracle: the identities the bodies below name, stated here by hand.

The check does not see: a record built by a loop that calls no builder (a dict copied from the
gateway's own database in the local index, which is no provider), iteration that builds no record
(socrata's portal vouching skips a non-object itself; fred's observations and census's rows are the payload
of ONE record, which a malformed row makes unreadable rather than shorter, while bea's and socrata's fetch rows
are stored whole, never iterated; catalogue entries are not records and the router keeps no dropped-entry
account of them, so a malformed entry makes its whole catalogue answer unreadable: bls, fred, census and bea),
and a list reached through reflection.
"""
from __future__ import annotations

import ast
import tempfile
import textwrap
import unittest
from pathlib import Path

from research_gateway import adapters
from research_gateway.adapters import (bis, bls, core, crossref, doaj, ecb, europepmc, harvard_dataverse as dv, kaggle, openaire,
                                       opencitations, semanticscholar, unpaywall)
from research_gateway.adapters.base import AdapterError, Client, FakeTransport, PayloadError
from research_gateway.core import router as R
from research_gateway.core.broker import Broker, RatePolicy
from tests.test_routing import SEED_NO_INDEX

ADAPTERS = Path(__file__).resolve().parents[1] / "research_gateway" / "adapters"
SIDS = ("crossref", "semanticscholar", "unpaywall", "opencitations", "kaggle", "harvard_dataverse", "bls", "ecb", "bis", "core", "doaj",
        "europepmc", "openaire")
KEYS = {("kaggle", "username"): "u", ("kaggle", "key"): "k", ("bls", None): "REG", ("core", None): "c",
        ("openaire", "client_id"): "i", ("openaire", "client_secret"): "s"}

# the loops that build records from data that is not a provider's list of members, by (file, function), each with why
NOT_PROVIDER_MEMBERS = {
    ("govinfo.py", "fetch"): "its download links, listed from the formats of the package record this adapter already decoded",
    ("huggingface.py", "fetch"): "its file records, listed from the files of the dataset record this adapter already decoded",
    ("openml.py", "fetch"): "its file records, listed from the two URLs of the dataset record this adapter already decoded",
}
LOOPS = (ast.For, ast.AsyncFor, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


def callee(call: ast.Call) -> str | None:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def builds(node: ast.AST, builders: set[str]) -> bool:
    """Does this code call make_record, or a function that does? The arguments of members() are the one
    place that may: they are what it decodes each member with. A nested def is its own function."""
    if isinstance(node, ast.Call):
        name = callee(node)
        if name in ("members", "first_member"):
            return False
        if name in builders or name == "make_record":
            return True
        if name in ("map", "filter") and any(isinstance(n, (ast.Name, ast.Attribute)) and (getattr(n, "id", None) or n.attr) in builders
                                             for a in node.args for n in ast.walk(a)):
            return True   # map(_record, members): the same loop, spelled as a call
    return any(builds(child, builders) for child in ast.iter_child_nodes(node) if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)))


def functions(tree: ast.AST):
    """(qualified name, node) for every function in the module."""
    def visit(node, scope):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield ".".join((*scope, child.name)), child
                yield from visit(child, (*scope, child.name))
            else:
                yield from visit(child, scope)
    return visit(tree, ())


def builder_names(trees: list[ast.AST]) -> set[str]:
    """The functions that build records: those that call make_record or, as far as that goes, another of them."""
    found: set[str] = set()
    while True:
        more = {fn.name for tree in trees for _, fn in functions(tree) if fn.name not in found and builds(fn, found)}
        if not more:
            return found
        found |= more


def own_loops(fn: ast.AST):
    """Every loop in this function's own body (not those of the functions defined inside it)."""
    for child in ast.iter_child_nodes(fn):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(child, LOOPS) or isinstance(child, ast.Call) and callee(child) in ("map", "filter"):
            yield child
        yield from own_loops(child)


def record_loops(root: Path = ADAPTERS) -> list[tuple[str, str]]:
    """(file, function) for every loop under `root` (but base.py, the decoder) that builds records on its own."""
    trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in sorted(root.glob("*.py")) if p.name != "base.py"}
    names = builder_names(list(trees.values()))
    return sorted({(p.name, qual) for p, tree in trees.items() for qual, fn in functions(tree)
                   for loop in own_loops(fn) if builds(loop, names)})


class OneDecoder(unittest.TestCase):
    def test_no_adapter_builds_records_from_a_provider_list_around_the_decoder(self):
        found = record_loops()
        self.assertEqual([f for f in found if f not in NOT_PROVIDER_MEMBERS], [],
                         "a provider's list becomes records through base.members(), which decodes each member alone")
        self.assertEqual(sorted(found), sorted(NOT_PROVIDER_MEMBERS), "each listed loop is still there")

    def test_control_the_check_finds_a_loop_of_an_adapters_own(self):
        """The check's own oracle: a record-building loop in each form it takes is found; the decoder's
        own use, a single record, and loops that build no record are not."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "new_lane.py").write_text(textwrap.dedent('''\
                from .base import members
                def _row(r):
                    return make_record(identity=r["id"], kind="citation", source_id="x")
                def a_loop(rows):
                    out = []
                    for r in rows:
                        out.append(make_record(identity=r["id"], kind="citation", source_id="x"))
                    return out
                def a_comprehension(rows):
                    return [make_record(identity=r["id"], kind="citation", source_id="x") for r in rows]
                def through_a_builder(rows):
                    return [_row(r) for r in rows]
                def a_generator(rows):
                    return sorted(_row(r) for r in rows)
                def a_map(rows):
                    return list(map(_row, rows))
                def nested(rows):
                    def inner():
                        for r in rows:
                            _row(r)
                    return inner
                def through_the_decoder(rows):
                    return members("x", rows, _row)
                def through_the_decoder_with_a_lambda(rows):
                    return members("x", rows, lambda r: _row(r))
                def a_single_record(r):
                    return _row(r)
                def a_loop_with_no_record(rows):
                    return [r["id"] for r in rows]
                '''))
            self.assertEqual(record_loops(Path(tmp)), [("new_lane.py", name) for name in
                                                       ("a_comprehension", "a_generator", "a_loop", "a_map", "nested.inner", "through_a_builder")])


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
               "opencitations citations": {**OC, "citing": 7}}
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
            return dv.fetch(c, "doi:10.7910/DVN/OY6CBK", file_id=file_id, download=True)["content"]
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
