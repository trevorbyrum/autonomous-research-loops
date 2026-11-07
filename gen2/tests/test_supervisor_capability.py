"""Rule: the supervisor fills the verifier's own capability id into a verification job's receipts before staging, and nothing else
(T15 hand-off; the id is authority and never reaches the job). Oracle: the staged outcome bytes read back from the spool, and the
journal's grant (the capability the router minted at the claim). Limits: the receipts here are bare dicts; whether the Router then
accepts a full receipt is the Router's own witness (store trigger on `$.verifier_capability_id`).
"""
import hashlib

from gen2.core import canonical
from gen2.tests import router_fixtures as rf
from gen2.tests.supervisor_fixtures import MAIN, SupervisedTestCase


class Capability(SupervisedTestCase):

    def stage(self, kind, receipts, declare=False):
        outcome = {**rf.empty_outcome(MAIN), "verification_receipts": receipts}
        data = canonical.canonical_bytes(outcome)
        steps = [{"op": "write", "name": "outcome.json", "hex": data.hex()}]
        if declare:
            steps.append({"op": "declare_digest", "digest": "sha256:" + hashlib.sha256(data).hexdigest()})
        self.supervisor.prepare(self.order(kind, steps))
        self.supervisor.run(MAIN)   # the Router may refuse these bare receipts; only the staging is under test
        journal = self.supervisor.job(MAIN).read("journal.json")
        collected = journal["collected"]
        result = collected["result"]
        staged = None if result is None else self.spool.read(result["content_hash"], topic_id=rf.TOPIC)
        return data, staged, journal, collected

    def capability(self, journal):
        return journal["grant"]["capability_id"]

    def test_a_receipt_without_the_field_gets_the_verifiers_own_capability(self) -> None:
        data, staged, journal, _ = self.stage("verification", [{"verification_receipt_id": "ver_00000001"}, {"verification_receipt_id": "ver_00000002"}])
        receipts = canonical.parse_json_strict(staged)["verification_receipts"]
        self.assertEqual([r["verifier_capability_id"] for r in receipts], [self.capability(journal)] * 2)
        self.assertNotEqual(staged, data)

    def test_a_receipt_that_already_names_the_right_capability_is_staged_byte_for_byte(self) -> None:
        _, _, journal, _ = self.stage("verification", [{"verification_receipt_id": "ver_00000001"}])
        right = self.capability(journal)       # ids are deterministic in the fixture world, so a fresh world mints the same capability
        self.tearDown()
        self.setUp()
        data, staged, journal, _ = self.stage("verification", [{"verification_receipt_id": "ver_00000001", "verifier_capability_id": right}])
        self.assertEqual((self.capability(journal), staged), (right, data))

    def test_a_receipt_naming_another_capability_refuses_the_output(self) -> None:
        _, staged, _, collected = self.stage("verification", [{"verification_receipt_id": "ver_00000001", "verifier_capability_id": "cap_" + "f" * 32}])
        self.assertIsNone(staged)
        self.assertEqual((collected["observation"]["output"]["status"], collected["observation"]["findings"]), ("refused", ["output_refused"]))

    def test_other_kinds_and_outcomes_without_receipts_are_staged_untouched(self) -> None:
        for kind, receipts in (("checkpoint", [{"verification_receipt_id": "ver_00000001"}]), ("verification", [])):
            with self.subTest(kind=kind, receipts=len(receipts)):
                self.tearDown()
                self.setUp()
                data, staged, _, _ = self.stage(kind, receipts)
                self.assertEqual(staged, data)

    def test_a_declared_digest_is_checked_against_the_jobs_own_bytes(self) -> None:
        _, staged, _, collected = self.stage("verification", [{"verification_receipt_id": "ver_00000001"}], declare=True)
        self.assertIsNotNone(staged)
        self.assertEqual(collected["observation"]["findings"], [])
