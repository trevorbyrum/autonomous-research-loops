"""Contract tests: FRED, BEA, Census, BLS, BIS, ECB (recorded response shapes; no network)."""
import unittest
from urllib.parse import parse_qs, urlsplit

from research_gateway.adapters import bea, bis, bls, census, ecb, fred
from research_gateway.adapters.base import AdapterError, Client, FakeTransport
from research_gateway.core import sdmx
from research_gateway.core.broker import Broker, RatePolicy


def client(secrets=None):
    t = FakeTransport()
    b = Broker({sid: RatePolicy(per_second=100) for sid in ("fred", "bea", "census", "bls", "bis", "ecb")})
    store = secrets or {}
    return Client(broker=b, transport=t, secrets=lambda n, f=None: store.get(n)), t


class Fred(unittest.TestCase):
    def test_observations_and_meta(self):
        c, t = client({"fred": "K"})
        t.add("GET", "https://api.stlouisfed.org/fred/series/observations?", body={"observations": [{"date": "2026-01-01", "value": "31865.7"}, {"date": "2026-04-01", "value": "32486.1"}]})
        t.add("GET", "https://api.stlouisfed.org/fred/series?", body={"seriess": [{"title": "Gross Domestic Product", "units": "Billions of Dollars", "frequency": "Quarterly", "notes": "..."}]})
        out = fred.data(c, {"series": "GDP", "start": "2026-01-01"})
        r = out["records"][0]
        self.assertEqual(r["identity"], "series:fred:GDP")
        self.assertEqual(r["observations"][-1], ("2026-04-01", "32486.1"))
        self.assertEqual(r["title"], "Gross Domestic Product")
        sent = parse_qs(urlsplit(t.calls[0][1]).query)
        self.assertEqual(sent["api_key"], ["K"])
        self.assertEqual(sent["observation_start"], ["2026-01-01"])
        self.assertEqual(r["attribution"], fred.ATTRIBUTION)

    def test_no_key_is_a_capability_fact(self):
        c, t = client()
        self.assertIn("capability_fact", fred.data(c, {"series": "GDP"}))
        self.assertEqual(t.calls, [])
        with self.assertRaises(AdapterError):
            fred.data(c, {})


class Bea(unittest.TestCase):
    def test_getdata_and_api_error(self):
        c, t = client({"bea": "K"})
        t.add("GET", "https://apps.bea.gov/api/data/?UserID=K&method=GetData", body={"BEAAPI": {"Results": {
            "Data": [{"TableName": "T10101", "LineDescription": "Gross domestic product", "TimePeriod": "2025", "DataValue": "3.1"}],
            "Notes": [{"NoteText": "Percent change"}]}}})
        out = bea.data(c, {"dataset": "NIPA", "table": "T10101", "frequency": "A", "year": "2025"})
        r = out["records"][0]
        self.assertEqual(r["row_count"], 1)
        self.assertEqual(r["notes"], ["Percent change"])
        self.assertIn("DataSetName=NIPA", t.calls[0][1])
        self.assertIn("TableName=T10101", t.calls[0][1])
        t.add("GET", "https://apps.bea.gov/api/data/?UserID=K&method=GETDATASETLIST", body={"BEAAPI": {"Results": {"Error": {"APIErrorCode": "4", "APIErrorDescription": "This UserId is not active."}}}})
        out2 = bea.data(c, {"method": "GETDATASETLIST"})
        self.assertIn("not active", out2["capability_fact"])


class Census(unittest.TestCase):
    def test_table_to_rows(self):
        c, t = client({"census": "K"})
        t.add("GET", "https://api.census.gov/data/2022/acs/acs1?", body=[["NAME", "B01001_001E", "state"], ["North Carolina", "10698973", "37"]])
        out = census.data(c, {"dataset": "2022/acs/acs1", "get": ["NAME", "B01001_001E"], "for": "state:37"})
        r = out["records"][0]
        self.assertEqual(r["rows"], [{"NAME": "North Carolina", "B01001_001E": "10698973", "state": "37"}])
        self.assertIn("for=state%3A37", t.calls[0][1])
        self.assertIn("key=K", t.calls[0][1])
        with self.assertRaises(AdapterError):
            census.data(c, {"dataset": "x"})


class Bls(unittest.TestCase):
    def test_series_post(self):
        c, t = client({"bls": "REG"})
        t.add("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/", body={"status": "REQUEST_SUCCEEDED", "message": [], "Results": {"series": [
            {"seriesID": "CUUR0000SA0", "catalog": {"series_title": "CPI-U All items"},
             "data": [{"year": "2026", "period": "M07", "value": "320.1"}, {"year": "2026", "period": "M06", "value": "319.5"}]}]}})
        out = bls.data(c, {"series": "CUUR0000SA0", "start_year": 2026, "catalog": True})
        r = out["records"][0]
        self.assertEqual(r["observations"], [("2026-M06", "319.5"), ("2026-M07", "320.1")])
        self.assertEqual(r["title"], "CPI-U All items")
        import json
        sent = json.loads(t.calls[0][3])
        self.assertEqual(sent["registrationkey"], "REG")
        self.assertEqual(sent["startyear"], "2026")

    def test_failed_status_is_capability_fact(self):
        c, t = client()
        t.add("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/", body={"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold reached"]})
        self.assertIn("daily threshold", bls.data(c, {"series": ["A", "B"]})["capability_fact"])


SDMX_10 = {"structure": {"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "D"}]}, {"id": "CURRENCY", "values": [{"id": "USD"}]}],
                                         "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2026-09-01"}, {"id": "2026-09-02"}]}]}},
           "dataSets": [{"series": {"0:0": {"observations": {"0": [1.08], "1": [1.09]}}}}]}
SDMX_20 = {"data": {"structures": [{"dimensions": {"series": [{"id": "FREQ", "values": [{"id": "Q"}]}],
                                                    "observation": [{"id": "TIME_PERIOD", "values": [{"id": "2025-Q4"}]}]}}],
                    "dataSets": [{"series": {"0": {"observations": {"0": [42.5]}}}}]}}


BIS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<message:StructureSpecificData xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message"
 xmlns:ss="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/data/structurespecific">
 <message:Header><message:ID>x</message:ID></message:Header>
 <message:DataSet ss:dataScope="DataStructure">
  <Group EER_TYPE="N" EER_BASKET="B" REF_AREA="US"/>
  <Series FREQ="M" EER_TYPE="N" EER_BASKET="B" REF_AREA="US" COLLECTION="A" TITLE_TS="United States - Nominal - Broad (64 economies)">
   <Obs TIME_PERIOD="2026-01" OBS_VALUE="102.25" OBS_STATUS="A"/>
   <Obs TIME_PERIOD="2026-02" OBS_VALUE="101.12" OBS_STATUS="A"/>
  </Series>
 </message:DataSet>
</message:StructureSpecificData>"""


class Sdmx(unittest.TestCase):
    def test_parser_both_versions(self):
        s10 = sdmx.series(SDMX_10)
        self.assertEqual(s10[0]["key"], {"FREQ": "D", "CURRENCY": "USD"})
        self.assertEqual(s10[0]["observations"], [("2026-09-01", 1.08), ("2026-09-02", 1.09)])
        s20 = sdmx.series(SDMX_20)
        self.assertEqual(s20[0]["key"], {"FREQ": "Q"})
        self.assertEqual(s20[0]["observations"], [("2025-Q4", 42.5)])
        self.assertEqual(sdmx.series({}), [])


class BisEcb(unittest.TestCase):
    def test_ecb(self):
        c, t = client()
        t.add("GET", "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?", body=SDMX_10)
        out = ecb.data(c, {"dataflow": "EXR", "key": "D.USD.EUR.SP00.A", "start": "2026-09-01"})
        self.assertEqual(out["records"][0]["identity"], "series:ecb:EXR:D.USD")
        self.assertEqual(out["records"][0]["observations"][0], ("2026-09-01", 1.08))
        self.assertIn("format=jsondata", t.calls[0][1])
        self.assertIn("startPeriod=2026-09-01", t.calls[0][1])

    def test_bis_reads_sdmx_ml(self):
        c, t = client()
        t.add("GET", "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_EER/1.0/M.N.B.US?", body=BIS_XML, headers={"Content-Type": "application/xml"})
        out = bis.data(c, {"dataflow": "WS_EER", "key": "M.N.B.US", "start": "2026-01"})
        r = out["records"][0]
        self.assertEqual(r["identity"], "series:bis:WS_EER:M.N.B.US.A")
        self.assertEqual(r["title"], "United States - Nominal - Broad (64 economies)")
        self.assertEqual(r["observations"], [("2026-01", 102.25), ("2026-02", 101.12)])
        self.assertEqual(t.calls[0][2]["Accept"], "application/xml")
        self.assertIn("startPeriod=2026-01", t.calls[0][1])
        self.assertEqual(sdmx.series_xml("<not xml"), [])
        with self.assertRaises(AdapterError):
            bis.data(c, {})


if __name__ == "__main__":
    unittest.main()
