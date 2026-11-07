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

    def run_job(self, cited: bytes, files: dict[str, bytes], **extra) -> str:
        outcome = {**rf.empty_outcome(MAIN), "registry_dispositions": [example_disposition(ref_of(cited), 0)], **extra}
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

    def test_a_file_whose_bytes_do_not_match_its_name_is_never_listed(self) -> None:
        self.refused({self.name(self.OTHER): EVIDENCE})

    def test_a_malformed_hash_in_the_outcome_ends_the_job_through_the_routers_refusal_not_a_crash(self) -> None:
        """A list or object where a content_hash belongs once raised TypeError in the traversal and left the job in result_ready."""
        for case, malformed in (("list", []), ("object", {"a": 1}), ("number", 7)):
            with self.subTest(case):
                self.setUp()
                self.assertEqual(self.run_job(EVIDENCE, {self.name(): EVIDENCE}, content_hash=malformed), "failed")
                self.assertEqual(self.value("SELECT state FROM invocations WHERE invocation_id = ?", MAIN), "failed")
                self.assertEqual(self.dispositions(), 0)

    def test_text_evidence_is_staged_as_text_and_unsupported_forms_are_ignored(self) -> None:
        text = b"claim words"
        name = "evidence-" + canonical.bytes_digest(text)[len("sha256:"):] + ".txt"
        outcome = {**rf.empty_outcome(MAIN), "registry_dispositions": [example_disposition({**ref_of(text), "media_type": "text/plain"}, 0)]}
        self.supervisor.prepare(self.order("checkpoint", [{"op": "write", "name": name, "hex": text.hex()},
                                                           {"op": "write", "name": name.replace(".txt", ".bin"), "hex": text.hex()},
                                                           {"op": "write", "name": "outcome.json", "text": canonical.canonical_bytes(outcome).decode()}]))
        self.assertEqual(self.supervisor.run(MAIN), "committed")
        collected = self.supervisor.job(MAIN).read("journal.json")["collected"]
        self.assertEqual([r["media_type"] for r in collected["evidence"]], ["text/plain"])     # the .bin file was never a candidate

    def test_more_than_sixteen_files_and_a_media_conflict_are_handled_without_an_error(self) -> None:
        from gen2.supervisor import supervisor as module
        files = {"evidence-" + canonical.bytes_digest(b"n%d" % n)[len("sha256:"):] + ".json": b"n%d" % n for n in range(module.MAX_EVIDENCE - 1)}
        self.assertEqual(self.run_job(EVIDENCE, {**files, self.name(): EVIDENCE}), "committed")    # well past the old cap of 16, and the citation is still listed
        self.assertEqual(len(self.supervisor.job(MAIN).read("journal.json")["collected"]["evidence"]), module.MAX_EVIDENCE)

    def test_bytes_the_topic_already_holds_under_another_media_are_not_listed_and_do_not_raise(self) -> None:
        self.spool.stage(rf.TOPIC, EVIDENCE, "text/plain")                                      # the same bytes, staged earlier as text
        self.assertEqual(self.run_job(EVIDENCE, {self.name(): EVIDENCE}), "failed")             # payload_missing, a normal refusal
        self.assertEqual(self.dispositions(), 0)
