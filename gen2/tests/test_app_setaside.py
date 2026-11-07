"""F2: newly retained bytes the view names are admitted with the commit. Oracle: the real Router's commit through the real supervisor,
spool and collection, observed in raw rows (a registry disposition exists or does not) and the audited refusal. Limits: the cited ref
is carried by a registry disposition, the Router's plainest section that takes evidence refs; that the research builder cites it in
`source_artifacts` and claims is the pure builders' (PR3b-D) and T18's end-to-end witness.
"""
from gen2.app.driver import Driver
from gen2.app.workflow import Step
from gen2.core import canonical
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import MAIN, SupervisedTestCase
from gen2.tests.test_registry_dispositions import example_disposition

RESPONSE = b'{"lanes": [{"source": "semanticscholar", "coverage": "searched_ok"}], "records": [{"identity": "doi:10.1/x", "abstract": "an abstract"}]}'


class SetAside(SupervisedTestCase):

    def run_job(self, *, set_aside: bool) -> str:
        ref = self.spool.stage(rf.TOPIC, RESPONSE, "application/json")   # what the discovery recorder did: spooled, never recorded by a commit
        outcome = {**rf.empty_outcome(MAIN), "registry_dispositions": [example_disposition(ref, 0)]}
        self.supervisor.prepare(self.order("checkpoint", [{"op": "write", "name": "outcome.json", "text": canonical.canonical_bytes(outcome).decode()}]))
        if set_aside:
            station = type("Station", (), {"spool": self.spool})()
            driver = Driver(station, topic_id=rf.TOPIC, bundle_hash="sha256:" + "b" * 64, kits={}, prompt_dir=self.root)
            driver.set_aside(Step("checkpoint", "challenge", 1, "c1.rev_one"), {"searches": [{"observations": [{"artifact_ref": ref}]}]},
                             self.supervisor.job(MAIN).scratch)
        return self.supervisor.run(MAIN)

    def test_a_spooled_but_unrecorded_response_the_view_named_is_admitted_with_the_commit(self) -> None:
        self.assertEqual(self.run_job(set_aside=True), "committed")
        self.assertEqual(self.value("SELECT count(*) FROM registry_dispositions"), 1)

    def test_without_the_set_aside_the_same_outcome_is_refused_not_admitted_from_the_spool(self) -> None:
        self.assertEqual(self.run_job(set_aside=False), "failed")
        self.assertEqual(self.value("SELECT count(*) FROM registry_dispositions"), 0)
        self.assertIn("payload_missing", self.value("SELECT group_concat(detail) FROM audit_events") or "")
