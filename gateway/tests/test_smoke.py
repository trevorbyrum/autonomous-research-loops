"""The smoke runner itself: covers every adapter, never crashes on refusals, reports what happened."""
import unittest

from research_gateway import adapters, smoke
from research_gateway.adapters.base import FakeTransport
from research_gateway.registry.load import read_seed


class NoSecrets:
    def get(self, name, field=None):
        return None


class SmokePlan(unittest.TestCase):
    def test_plan_covers_every_adapter_once(self):
        planned = {sid for sid, _, _ in smoke.PLAN} | set(smoke.LOCAL_ONLY)
        self.assertEqual(planned, set(adapters.load_all()))
        self.assertEqual(len(smoke.PLAN), len({sid for sid, _, _ in smoke.PLAN}))

    def test_offline_run_reports_without_crashing(self):
        client = smoke.build_client(read_seed(), transport=FakeTransport(), secrets=NoSecrets())
        rows = smoke.run(client)
        by_source = {r["source"]: r for r in rows}
        self.assertEqual(set(by_source), {sid for sid, _, _ in smoke.PLAN} | set(smoke.LOCAL_ONLY))
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
