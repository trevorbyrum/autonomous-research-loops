"""The overlap-probe comparison and presence logic, offline."""
import unittest

from research_gateway import adapters
from research_gateway.adapters.base import Client, FakeTransport
from research_gateway.core.broker import Broker, RatePolicy
from tests.regression import overlap_probe as probe
from tests.test_adapters_articles import CROSSREF_WORK


class Compare(unittest.TestCase):
    def test_rates_and_tolerance(self):
        expected = [{"doi": "10.1/a", "found": {"crossref": True, "doaj": False, "core": None}},
                    {"doi": "10.1/b", "found": {"crossref": True, "doaj": True}},
                    {"doi": "10.1/c", "found": {"crossref": False, "doaj": True}},
                    {"doi": "10.1/d", "found": {"crossref": True, "doaj": False}}]
        observed = {("10.1/a", "crossref"): True, ("10.1/b", "crossref"): True, ("10.1/c", "crossref"): False, ("10.1/d", "crossref"): True,
                    ("10.1/a", "doaj"): False, ("10.1/b", "doaj"): False, ("10.1/c", "doaj"): True, ("10.1/d", "doaj"): False,
                    ("10.1/a", "core"): True}
        out = probe.compare(expected, observed, 0.05)
        self.assertEqual(out["crossref"], {"n": 4, "then": 0.75, "now": 0.75, "agreement": 1.0, "ok": True})
        self.assertEqual(out["doaj"]["then"], 0.5)
        self.assertEqual(out["doaj"]["now"], 0.25)
        self.assertFalse(out["doaj"]["ok"], "a 25-point drop is outside the 5-point tolerance")
        self.assertNotIn("core", out, "a source with no expectation on record is not compared")
        self.assertIn("doaj", probe.render(out))
        swapped = {**observed, ("10.1/a", "crossref"): False, ("10.1/c", "crossref"): True}
        out = probe.compare(expected, swapped, 0.05)
        self.assertEqual(out["crossref"]["now"], 0.75, "same share present ...")
        self.assertFalse(out["crossref"]["ok"], "... but different works: paired agreement gates it")

    def test_present_asks_through_the_metered_client(self):
        t = FakeTransport()
        t.add("GET", "https://api.crossref.org/works/10.1234/abc", body={"message": CROSSREF_WORK})
        t.add("GET", "https://api.unpaywall.org/v2/10.1234/abc", body={"is_oa": False, "oa_locations": []})
        t.add("GET", "https://api.unpaywall.org/v2/10.1234/none", status=404)
        c = Client(broker=Broker({sid: RatePolicy(per_second=100) for sid in ("crossref", "unpaywall", "doaj")}), transport=t)
        mods = adapters.load_all()
        self.assertTrue(probe.present(mods, c, "crossref", "10.1234/abc"))
        self.assertTrue(probe.present(mods, c, "unpaywall", "10.1234/abc"), "Unpaywall knows the DOI even with no OA copy")
        self.assertFalse(probe.present(mods, c, "unpaywall", "10.1234/none"))
        self.assertFalse(probe.present(mods, c, "doaj", "10.1234/abc"), "404 → not present")
        self.assertIsNone(probe.present({}, c, "crossref", "10.1234/abc"), "no adapter → cannot say")
        self.assertEqual([r.source_id for r in c.log], ["crossref", "unpaywall", "unpaywall", "doaj"])


if __name__ == "__main__":
    unittest.main()
