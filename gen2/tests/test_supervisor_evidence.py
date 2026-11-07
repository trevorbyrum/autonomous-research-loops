"""Rule: a job's outcome may cite the evidence artifacts the job set aside, and no other ref (T16/T17 envelope; Astra T12 F3).

Oracle: the real Router's commit, observed in raw store rows (a registry disposition exists or does not, and which reason ended
the job). Limits: only `evidence-<sha256 hex>.json` scratch files count; media type is fixed, and the router still judges the
document that cites them.
"""
from gen2.core import canonical
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import MAIN, SupervisedTestCase
from gen2.tests.test_registry_dispositions import example_disposition

EVIDENCE = b'{"judgment_version": "judgment-challenge/1"}'


def ref_of(data: bytes) -> dict:
    return {"content_hash": canonical.bytes_digest(data), "size_bytes": len(data), "media_type": "application/json"}


class Evidence(SupervisedTestCase):

    def run_job(self, cited: bytes, files: dict[str, bytes]) -> str:
        outcome = {**rf.empty_outcome(MAIN), "registry_dispositions": [example_disposition(ref_of(cited), 0)]}
        steps = [{"op": "write", "name": name, "hex": data.hex()} for name, data in files.items()]
        steps.append({"op": "write", "name": "outcome.json", "text": canonical.canonical_bytes(outcome).decode()})
        self.supervisor.prepare(self.order("checkpoint", steps))
        return self.supervisor.run(MAIN)

    def name(self, data: bytes = EVIDENCE) -> str:
        return "evidence-" + canonical.bytes_digest(data)[len("sha256:"):] + ".json"

    def dispositions(self) -> int:
        return self.value("SELECT count(*) FROM registry_dispositions")

    def test_an_outcome_citing_its_staged_evidence_commits_through_the_router(self) -> None:
        self.assertEqual(self.run_job(EVIDENCE, {self.name(): EVIDENCE}), "committed")
        self.assertEqual(self.dispositions(), 1)

    def refused(self, files: dict[str, bytes]) -> None:
        self.assertEqual(self.run_job(self.OTHER, files), "failed")
        self.assertEqual(self.dispositions(), 0)
        self.assertIn("payload_missing", self.value("SELECT group_concat(detail) FROM audit_events") or "")

    OTHER = b'{"another": "artifact"}'

    def test_a_ref_with_no_evidence_file_is_still_refused(self) -> None:
        self.refused({})

    def test_a_ref_that_only_another_file_stages_is_still_refused(self) -> None:
        self.refused({self.name(): EVIDENCE})

    def test_a_file_whose_bytes_do_not_match_its_name_stages_nothing(self) -> None:
        self.refused({self.name(self.OTHER): EVIDENCE})
