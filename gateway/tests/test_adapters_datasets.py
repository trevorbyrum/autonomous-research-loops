"""Contract tests: doi_org, govinfo, Dataverse family (harvard_dataverse, qdr, wms), globe, socrata, kaggle, huggingface, openml."""
import base64
import json
import unittest

from research_gateway.adapters import doi_org, globe, govinfo, harvard_dataverse as dv, huggingface, kaggle, openml, qdr, socrata, wms
from research_gateway.adapters.base import AdapterError, Client, FakeTransport
from research_gateway.core.broker import Broker, RatePolicy

SIDS = ("doi_org", "govinfo", "harvard_dataverse", "qdr", "wms", "globe", "socrata", "kaggle", "huggingface", "openml")


def client(secrets=None):
    t = FakeTransport()
    store = secrets or {}
    c = Client(broker=Broker({sid: RatePolicy(per_second=100) for sid in SIDS}), transport=t,
               secrets=lambda n, f=None: store.get(f"{n}.{f}" if f else n))
    return c, t


class DoiOrg(unittest.TestCase):
    def test_resolve_routes_by_agency_and_caches_prefix(self):
        c, t = client()
        t.add("GET", "https://doi.org/ra/10.7910/", body=[{"DOI": "10.7910/DVN/OY6CBK", "RA": "DataCite"}])
        out = doi_org.resolve(c, "doi:10.7910/DVN/OY6CBK")
        self.assertEqual(out["agency"], "DataCite")
        self.assertEqual(out["adapter"], "datacite")
        self.assertEqual(out["prefix"], "10.7910")
        self.assertIsNone(doi_org.resolve(c, "not a doi"))
        self.assertEqual(len(t.calls), 1)
        self.assertEqual(c.log[0].source_id, "doi_org")


GOVINFO_PKG = {"packageId": "CRPT-118hrpt1", "title": "Report on X", "collectionCode": "CRPT", "dateIssued": "2023-02-01",
               "lastModified": "2023-02-02T00:00:00Z", "governmentAuthor1": "House Committee",
               "download": {"pdfLink": "https://api.govinfo.gov/packages/CRPT-118hrpt1/pdf", "txtLink": "https://api.govinfo.gov/packages/CRPT-118hrpt1/txt"}}


class GovInfo(unittest.TestCase):
    def test_find_resolve_fetch(self):
        c, t = client({"api_data_gov": "K"})
        t.add("POST", "https://api.govinfo.gov/search", body={"count": 1, "offsetMark": "AoJ", "results": [GOVINFO_PKG]})
        out = govinfo.find(c, "supply chain", limit=5)
        self.assertEqual(out["records"][0]["identity"], "govinfo:CRPT-118hrpt1")
        self.assertEqual(out["records"][0]["year"], 2023)
        self.assertEqual(out["next_offset_mark"], "AoJ")
        self.assertEqual(t.calls[0][2]["X-Api-Key"], "K")
        self.assertEqual(json.loads(t.calls[0][3])["query"], "supply chain")
        t.add("GET", "https://api.govinfo.gov/packages/CRPT-118hrpt1/summary", body=GOVINFO_PKG)
        rec = govinfo.resolve(c, "govinfo:CRPT-118hrpt1")
        self.assertEqual(rec["formats"], ["pdf", "txt"])
        self.assertEqual(rec["raw"], GOVINFO_PKG, "the whole source object is kept (I-8)")
        files = govinfo.fetch(c, "govinfo:CRPT-118hrpt1")
        self.assertEqual([f["format"] for f in files["records"]], ["pdf", "txt"])
        self.assertEqual(files["records"][0]["links"], ["https://api.govinfo.gov/packages/CRPT-118hrpt1/pdf"])
        self.assertIn("https://api.govinfo.gov/packages/CRPT-118hrpt1/pdf", rec["links"])
        t.add("GET", "https://api.govinfo.gov/packages/CRPT-118hrpt1/txt", body="plain text", headers={"Content-Type": "text/plain"})
        got = govinfo.fetch(c, "CRPT-118hrpt1", fmt="txt", download=True)
        self.assertEqual(got["content"], b"plain text")
        with self.assertRaises(AdapterError):
            govinfo.fetch(c, "x", fmt="docx")

    def test_no_key(self):
        c, t = client()
        self.assertIn("capability_fact", govinfo.find(c, "q"))
        self.assertIsNone(govinfo.resolve(c, "govinfo:x"))
        self.assertEqual(t.calls, [])


DV_SEARCH = {"data": {"total_count": 1, "items": [{"name": "World Management Survey", "global_id": "doi:10.7910/DVN/OY6CBK",
                                                   "url": "https://doi.org/10.7910/DVN/OY6CBK", "authors": ["Bloom, Nicholas"],
                                                   "published_at": "2021-05-01T00:00:00Z", "fileCount": 2, "subjects": ["Business"]}]}}
DV_DATASET = {"data": {"id": 42, "authority": "10.7910", "identifier": "DVN/OY6CBK", "persistentUrl": "https://doi.org/10.7910/DVN/OY6CBK",
                       "publisher": "Harvard Dataverse",
                       "latestVersion": {"versionNumber": 1, "versionMinorNumber": 0, "releaseTime": "2021-05-01", "license": {"name": "CC0 1.0"},
                                         "metadataBlocks": {"citation": {"fields": [
                                             {"typeName": "title", "value": "World Management Survey"},
                                             {"typeName": "author", "value": [{"authorName": {"value": "Bloom, Nicholas"}}]}]}},
                                         "files": [{"label": "wms.csv", "restricted": False,
                                                    "dataFile": {"id": 900, "filename": "wms.csv", "contentType": "text/csv", "filesize": 12}}]}}}


class Dataverse(unittest.TestCase):
    def test_harvard_find_resolve_fetch(self):
        c, t = client({"harvard_dataverse": "TOK"})
        t.add("GET", "https://dataverse.harvard.edu/api/search?", body=DV_SEARCH)
        out = dv.find(c, "management survey")
        self.assertEqual(out["records"][0]["identity"], "doi:10.7910/dvn/oy6cbk")
        self.assertEqual(out["records"][0]["authors"], ["Bloom, Nicholas"])
        self.assertIsNone(out["next_page"])
        self.assertEqual(t.calls[0][2]["X-Dataverse-key"], "TOK")
        t.add("GET", "https://dataverse.harvard.edu/api/datasets/:persistentId/?", body=DV_DATASET)
        rec = dv.resolve(c, "doi:10.7910/DVN/OY6CBK")
        self.assertEqual(rec["title"], "World Management Survey")
        self.assertEqual(rec["license"], "CC0 1.0")
        self.assertEqual(rec["file_count"], 1)
        files = dv.fetch(c, "doi:10.7910/DVN/OY6CBK")
        self.assertEqual(files["records"][0]["kind"], "file")
        self.assertEqual(files["records"][0]["file_id"], 900)
        self.assertEqual(files["records"][0]["license"], "CC0 1.0")
        t.add("GET", "https://dataverse.harvard.edu/api/access/datafile/900", body="a,b\n1,2\n", headers={"Content-Type": "text/csv"})
        got = dv.fetch(c, "doi:10.7910/DVN/OY6CBK", file_id=900, download=True)
        self.assertEqual(got["content"], b"a,b\n1,2\n")
        with self.assertRaises(AdapterError):
            dv.fetch(c, "doi:10.7910/DVN/OY6CBK", download=True)
        with self.assertRaises(AdapterError):
            dv.resolve(c, "nope")

    def test_qdr_uses_its_own_host_and_key(self):
        c, t = client({"qdr": "QK"})
        t.add("GET", "https://data.qdr.syr.edu/api/search?", body=DV_SEARCH)
        t.add("GET", "https://data.qdr.syr.edu/api/datasets/:persistentId/?", body=DV_DATASET)
        self.assertEqual(qdr.find(c, "interviews")["records"][0]["source_id"], "qdr")
        self.assertEqual(qdr.resolve(c, "10.7910/DVN/OY6CBK")["source_id"], "qdr")
        self.assertTrue(all(call[2]["X-Dataverse-key"] == "QK" for call in t.calls))
        self.assertEqual({r.source_id for r in c.log}, {"qdr"})

    def test_wms_is_pinned_to_its_doi_and_metered_as_wms(self):
        c, t = client()
        t.add("GET", "https://dataverse.harvard.edu/api/datasets/:persistentId/?", body=DV_DATASET)
        out = wms.fetch(c)
        self.assertEqual(out["records"][0]["source_id"], "wms")
        self.assertEqual(c.log[0].source_id, "wms")
        self.assertIn("capability_fact", wms.fetch(c, "doi:10.1000/other"))
        self.assertEqual(len(t.calls), 1)


class Globe(unittest.TestCase):
    def test_fetch(self):
        c, t = client()
        self.assertEqual(globe.fetch(c)["records"][0]["links"], ["https://globeproject.com/data/"])
        listing = globe.fetch(c, "https://globeproject.com/data/GLOBE-Phase-2.xls")
        self.assertEqual(listing["records"][0]["kind"], "file")
        self.assertEqual(t.calls, [])
        t.add("GET", "https://globeproject.com/data/GLOBE-Phase-2.xls", body=b"\xd0\xcf", headers={"Content-Type": "application/vnd.ms-excel"})
        got = globe.fetch(c, "url:https://globeproject.com/data/GLOBE-Phase-2.xls", download=True)
        self.assertEqual(got["content"], b"\xd0\xcf")
        with self.assertRaises(AdapterError):
            globe.fetch(c, "https://example.org/file.xls", download=True)


SOCRATA_CATALOG = {"resultSetSize": 1, "results": [{"resource": {"id": "abcd-1234", "name": "Business Licenses", "type": "dataset", "updatedAt": "2026-01-05T00:00:00Z"},
                                                   "metadata": {"domain": "data.cityofchicago.org", "license": "Public Domain"},
                                                   "permalink": "https://data.cityofchicago.org/d/abcd-1234"}]}


class Socrata(unittest.TestCase):
    def test_find_resolve_fetch(self):
        c, t = client({"socrata": "APP"})
        t.add("GET", "https://api.us.socrata.com/api/catalog/v1?", body=SOCRATA_CATALOG)
        out = socrata.find(c, "business licenses", domain="data.cityofchicago.org")
        r = out["records"][0]
        self.assertEqual(r["identity"], "socrata:data.cityofchicago.org:abcd-1234")
        self.assertEqual(r["license"], "Public Domain")
        self.assertIn("domains=data.cityofchicago.org", t.calls[0][1])
        self.assertEqual(t.calls[0][2]["X-App-Token"], "APP")
        t.add("GET", "https://data.cityofchicago.org/api/views/abcd-1234.json", body={"id": "abcd-1234", "name": "Business Licenses",
                                                                                         "license": {"name": "Public Domain", "termsLink": "https://example.org/terms"},
                                                                                         "columns": [{"fieldName": "license_id"}]})
        rec = socrata.resolve(c, r["identity"])
        self.assertEqual(rec["columns"], ["license_id"])
        self.assertEqual(rec["license_link"], "https://example.org/terms")
        t.add("GET", "https://data.cityofchicago.org/resource/abcd-1234.json?", body=[{"license_id": "1"}, {"license_id": "2"}])
        rows = socrata.fetch(c, r["identity"], limit=2, where="license_id > 0")
        self.assertEqual(rows["records"][0]["row_count"], 2)
        self.assertEqual(rows["next_offset"], 2)
        self.assertIn("%24where=license_id+%3E+0", t.calls[-1][1])
        with self.assertRaises(AdapterError):
            socrata.resolve(c, "abcd-1234")

    def test_only_catalog_vouched_portals_are_called(self):
        socrata.reset_known_domains()
        c, t = client()
        t.add("GET", "https://api.us.socrata.com/api/catalog/v1?domains=evil.example", body={"resultSetSize": 0, "results": []})
        with self.assertRaises(AdapterError):
            socrata.resolve(c, "socrata:evil.example:abcd-1234")
        self.assertEqual(len(t.calls), 1, "the catalog was asked; the portal was never contacted")
        t.add("GET", "https://api.us.socrata.com/api/catalog/v1?domains=data.example.gov", body={"resultSetSize": 3, "results": []})
        t.add("GET", "https://data.example.gov/resource/xy12-3456.json?", body=[{"a": 1}])
        out = socrata.fetch(c, "socrata:data.example.gov:xy12-3456", limit=5)
        self.assertEqual(out["records"][0]["row_count"], 1)
        socrata.fetch(c, "socrata:DATA.example.gov:xy12-3456", limit=5)
        self.assertEqual(sum("catalog/v1" in call[1] for call in t.calls), 2, "vouching is remembered per portal")
        socrata.reset_known_domains()


class Kaggle(unittest.TestCase):
    def test_find_and_fetch_with_basic_auth(self):
        c, t = client({"kaggle.username": "u", "kaggle.key": "k"})
        t.add("GET", "https://www.kaggle.com/api/v1/datasets/list?", body=[{"ref": "owner/ds", "title": "DS", "licenseName": "CC0-1.0",
                                                                             "url": "https://www.kaggle.com/datasets/owner/ds", "lastUpdated": "2025-03-01",
                                                                             "ownerName": "Owner", "totalBytes": 10}])
        out = kaggle.find(c, "housing")
        self.assertEqual(out["records"][0]["identity"], "kaggle:owner/ds")
        self.assertEqual(out["records"][0]["license"], "CC0-1.0")
        self.assertIsNone(out["next_page"])
        self.assertEqual(t.calls[0][2]["Authorization"], "Basic " + base64.b64encode(b"u:k").decode())
        t.add("GET", "https://www.kaggle.com/api/v1/datasets/list/owner/ds", body={"datasetFiles": [{"name": "train.csv", "totalBytes": 10}]})
        files = kaggle.fetch(c, "kaggle:owner/ds")
        self.assertEqual(files["records"][0]["title"], "train.csv")
        self.assertEqual(files["records"][0]["links"], ["https://www.kaggle.com/api/v1/datasets/download/owner/ds/train.csv"])
        t.add("GET", "https://www.kaggle.com/api/v1/datasets/download/owner/ds/train.csv", body="x,y\n")
        self.assertEqual(kaggle.fetch(c, "owner/ds", file_name="train.csv", download=True)["content"], b"x,y\n")
        with self.assertRaises(AdapterError):
            kaggle.fetch(c, "kaggle:bad")

    def test_no_credentials(self):
        c, t = client({"kaggle.username": "u"})
        self.assertIn("capability_fact", kaggle.find(c, "q"))
        self.assertIn("capability_fact", kaggle.fetch(c, "owner/ds"))
        self.assertEqual(t.calls, [])


HF_DATASET = {"id": "owner/corpus", "author": "owner", "lastModified": "2026-02-01T00:00:00Z", "tags": ["license:cc-by-4.0", "task:text"],
              "cardData": {"license": "cc-by-4.0"}, "siblings": [{"rfilename": "README.md"}, {"rfilename": "data/train.parquet"}], "gated": False}


class HuggingFace(unittest.TestCase):
    def test_find_resolve_fetch(self):
        c, t = client({"huggingface": "hf_x"})
        t.add("GET", "https://huggingface.co/api/datasets?", body=[HF_DATASET])
        out = huggingface.find(c, "corpus", limit=1)
        self.assertEqual(out["records"][0]["identity"], "hf:owner/corpus")
        self.assertEqual(out["records"][0]["license"], "cc-by-4.0")
        self.assertEqual(out["next_offset"], 1)
        self.assertEqual(t.calls[0][2]["Authorization"], "Bearer hf_x")
        t.add("GET", "https://huggingface.co/api/datasets/owner/corpus", body={**HF_DATASET, "cardData": {}})
        rec = huggingface.resolve(c, "hf:owner/corpus")
        self.assertEqual(rec["license"], "cc-by-4.0")  # falls back to the license: tag
        files = huggingface.fetch(c, "owner/corpus")
        self.assertEqual([f["path"] for f in files["records"]], ["README.md", "data/train.parquet"])
        self.assertEqual(files["records"][1]["links"], ["https://huggingface.co/datasets/owner/corpus/resolve/main/data/train.parquet"])
        t.add("GET", "https://huggingface.co/datasets/owner/corpus/resolve/main/README.md", body="# hi")
        self.assertEqual(huggingface.fetch(c, "owner/corpus", path="README.md", download=True)["content"], b"# hi")
        with self.assertRaises(AdapterError):
            huggingface.fetch(c, "owner/corpus", download=True)
        with self.assertRaises(AdapterError):
            huggingface.resolve(c, "hf:")


OPENML_LIST = {"data": {"dataset": [{"did": 61, "name": "iris", "version": 1, "status": "active", "format": "ARFF", "file_id": 61,
                                     "quality": [{"name": "NumberOfInstances", "value": "150"}, {"name": "NumberOfFeatures", "value": "5"}]}]}}
OPENML_DESC = {"data_set_description": {"id": "61", "name": "iris", "version": "1", "format": "ARFF", "licence": "Public", "upload_date": "2014-04-06",
                                        "url": "https://api.openml.org/data/v1/download/61/iris.arff",
                                        "parquet_url": "https://data.openml.org/datasets/0000/0061/dataset_61.pq", "creator": "R.A. Fisher"}}


class OpenML(unittest.TestCase):
    def test_find_resolve_fetch(self):
        c, t = client()
        t.add("GET", "https://www.openml.org/api/v1/json/data/list/data_name/iris/", body=OPENML_LIST)
        out = openml.find(c, "iris", limit=10)
        self.assertEqual(out["records"][0]["identity"], "openml:61")
        self.assertEqual(out["records"][0]["instances"], "150")
        self.assertIsNone(out["next_offset"])
        t.add("GET", "https://www.openml.org/api/v1/json/data/61", body=OPENML_DESC)
        rec = openml.resolve(c, "openml:61")
        self.assertEqual(rec["license"], "Public")
        self.assertEqual(rec["authors"], ["R.A. Fisher"])
        self.assertEqual(rec["year"], 2014)
        files = openml.fetch(c, "61")
        self.assertEqual(files["records"][0]["links"], ["https://data.openml.org/datasets/0000/0061/dataset_61.pq"])
        t.add("GET", "https://api.openml.org/data/v1/download/61/iris.arff", body="@relation iris")
        got = openml.fetch(c, "openml:61", download=True, prefer="arff")
        self.assertEqual(got["content"], b"@relation iris")
        with self.assertRaises(AdapterError):
            openml.resolve(c, "openml:iris")


if __name__ == "__main__":
    unittest.main()
