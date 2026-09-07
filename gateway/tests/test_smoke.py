"""The smoke runner: probes declared per adapter (I-2), never crashes on refusals, reports what happened."""
import unittest

from research_gateway import adapters, smoke
from research_gateway.adapters.base import FakeTransport
from research_gateway.registry.load import read_seed


class NoSecrets:
    def get(self, name, field=None):
        return None


class SmokePlan(unittest.TestCase):
    def test_every_adapter_declares_its_probe(self):
        plan, local = smoke.probes()
        self.assertEqual(set(plan) | set(local), set(adapters.load_all()),
                         "an adapter without a SMOKE declaration cannot be verified (I-2)")
        self.assertEqual(set(local), {"openalex_snapshot", "globe"})
        for sid, spec in plan.items():
            self.assertIn(spec["capability"], ("find", "resolve", "enrich", "fetch", "data"), sid)
            self.assertIn(spec["capability"], adapters.load_all()[sid].CAPABILITIES, sid)

    def test_offline_run_reports_without_crashing(self):
        client = smoke.build_client(read_seed(), transport=FakeTransport(), secrets=NoSecrets())
        rows = smoke.run(client)
        by_source = {r["source"]: r for r in rows}
        plan, local = smoke.probes()
        self.assertEqual(set(by_source), set(plan) | set(local))
        self.assertNotIn("crash", {r["outcome"] for r in rows})
        self.assertEqual(by_source["openalex_snapshot"]["outcome"], "skipped")
        self.assertEqual(by_source["fred"]["detail"], "no FRED key configured")
        self.assertEqual(by_source["crossref"]["calls"][0]["status"], 404)
        text = smoke.render(rows)
        self.assertIn("crossref", text)
        self.assertIn("no FRED key configured", text)

    def test_dry_plan_exit_zero(self):
        self.assertEqual(smoke.main(["--only", "fred"]), 0)


if __name__ == "__main__":
    unittest.main()
