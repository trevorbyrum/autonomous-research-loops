"""The order `Router.status` lists its capability facts and its engine-wide holds in (task 2q-t3; DEBT-023 item 2, Astra's 2q-b3b review, ruling 5).

status.py lists the current capability facts by capability name and the open holds of no topic by the instant each was opened. No test held two of either, so a reversal of
either sort (one `reverse=True`) changed nothing the engine suite or the exact replay (tools/gen2_replay.py) observed. These fixtures hold two facts and two holds that tell the
orders apart: the two probes are recorded in the reverse of their capabilities' alphabetical order, so the facts come out alphabetical, not as written, and the holds come out as
opened, not alphabetical (the opposite orders). Everything is the router's own `record_capability_probe` over the test's clock and ids: no process, no real time, so the replay
recorder sees the same records on every run (evidence/2q-t3/debt-023).

Expected orders are written by hand from the rule above. One control reads the rows back as raw SQL and shows the fixtures hold what the tests need them to; the other that status
lists the same rows whichever order it puts them in. What this cannot show: the order of anything else status lists (its topics, bundles and invocations have their own keys), or
that two rows tell apart every wrong key (they tell apart a reversal, and the two other keys the 2QT3 mutants sort by).
"""
from __future__ import annotations

from gen2.tests import router_fixtures as rf

ZETA, ALPHA = "provider-auth:zeta", "provider-auth:alpha"   # recorded in this order: the reverse of their alphabetical one


def probe(pid: str, capability: str, outcome: str, detail: str, observed: str) -> dict:
    return {"probe_id": "probe_" + pid.ljust(32, "0"), "capability": capability, "outcome": outcome, "detail": detail, "declared_expiry": None, "started_at": observed,
            "observed_at": observed, "runner": {"name": "codex", "version": "0.153.2"}, "affected_lanes": ["station:station-1"], "requested_by": "alice"}


class StatusOrderTest(rf.RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        for request in (probe("a1", ZETA, "unusable_credential", "the zeta credential was refused", "2026-09-27T10:00:05Z"),
                        probe("a2", ALPHA, "runner_error", "the alpha runner timed out", "2026-09-27T10:00:06Z")):
            assert self.router.record_capability_probe(request)["status"] == "recorded", request

    def test_status_lists_the_current_capability_facts_by_capability_name(self) -> None:
        facts = self.router.status({})["capability_facts"]
        self.assertEqual([(f["capability"], f["state"]) for f in facts], [(ALPHA, "unknown"), (ZETA, "failing")])

    def test_status_lists_the_open_global_holds_in_the_order_they_were_opened(self) -> None:
        holds = self.router.status({})["holds"]
        self.assertEqual([h["subject_ref"] for h in holds], ["capability:" + ZETA, "capability:" + ALPHA])

    def test_control_the_fixtures_hold_two_rows_each_that_the_two_orders_tell_apart(self) -> None:
        """Raw SQL, not status: two current facts and two open holds of no topic, the facts written zeta first and named alpha first, the holds opened zeta first, strictly later."""
        written = self.rows("SELECT capability FROM capability_facts WHERE superseded_by_fact_id IS NULL ORDER BY rowid")
        self.assertEqual(written, [(ZETA,), (ALPHA,)])
        self.assertEqual(sorted(written), [(ALPHA,), (ZETA,)])
        opened = self.rows("SELECT subject_ref, created_at FROM holds WHERE topic_id IS NULL AND cleared_at IS NULL ORDER BY rowid")
        self.assertEqual([subject for subject, _ in opened], ["capability:" + ZETA, "capability:" + ALPHA])
        self.assertLess(opened[0][1], opened[1][1])
        self.assertNotEqual([subject.removeprefix("capability:") for subject, _ in opened], [name for (name,) in sorted(written)])

    def test_control_status_lists_the_same_two_rows_of_each_whatever_their_order(self) -> None:
        doc = self.router.status({})
        self.assertEqual(sorted(f["capability"] for f in doc["capability_facts"]), [ALPHA, ZETA])
        self.assertEqual(sorted(h["subject_ref"] for h in doc["holds"]), ["capability:" + ALPHA, "capability:" + ZETA])
