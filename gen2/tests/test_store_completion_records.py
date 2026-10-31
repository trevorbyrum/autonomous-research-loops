"""Raw integrity guards for completion records; in-memory fixtures only."""
import json
import sqlite3

from gen2.tests.router_fixtures import TOPIC, OTHER, h
from gen2.tests.store_fixtures import StoreTestCase

BOUND = "completion record needs its primary commit and exact contract pin"
# kind -> the subject columns that kind's shape pairs allow
SUBJECTS = {"counterevidence_search": ("clm_00000001", 1, None), "competing_explanation": ("rdp_fixture1", None, None),
            "sufficiency_review": (TOPIC, 1, h("3")), "verification_adjudication": ("ver_00000001", 1, None)}


class DDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()
        columns = [r[1] for r in self.rows("PRAGMA table_info(completion_records)")]
        self.base = dict(zip(columns, self.rows("SELECT * FROM completion_records WHERE record_id = 'cr-fixture'")[0]))

    def insert(self, **changes):
        row = {**self.base, "record_id": "cr-raw", **changes}
        self.x(f"INSERT INTO completion_records ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *row.values())

    def refused(self, fragment, **changes):
        before = self.snapshot("completion_records")
        with self.subTest(changes=changes), self.assertRaises(sqlite3.IntegrityError) as caught:
            self.insert(**changes)
        self.assertIn(fragment, str(caught.exception))
        self.assertEqual(self.snapshot("completion_records"), before)

    def test_one_accepted_row_per_kind(self):
        for kind, (ref, revision, subject_hash) in SUBJECTS.items():
            self.insert(record_id=f"cr-{kind}", kind=kind, subject_ref=ref, subject_revision=revision, subject_hash=subject_hash)
        self.assertEqual(self.rows("SELECT kind, subject_ref, subject_revision, subject_hash IS NOT NULL FROM completion_records WHERE record_id != 'cr-fixture' ORDER BY rowid"),
            [(kind, ref, revision, subject_hash is not None) for kind, (ref, revision, subject_hash) in SUBJECTS.items()])

    def test_shape_guards(self):
        counter = dict(zip(("kind", "subject_ref", "subject_revision", "subject_hash"), ("counterevidence_search", "clm_00000001", 1, None)))
        self.refused("kind IN ('counterevidence_search'", kind="invented")
        self.refused("(subject_revision IS NOT NULL) = (kind != 'competing_explanation')", **{**counter, "subject_revision": None})
        self.refused("(subject_revision IS NOT NULL) = (kind != 'competing_explanation')", kind="competing_explanation", subject_ref="rdp_fixture1", subject_hash=None)
        self.refused("(subject_hash IS NOT NULL) = (kind = 'sufficiency_review')", **{**counter, "subject_hash": h("3")})
        self.refused("(subject_hash IS NOT NULL) = (kind = 'sufficiency_review')", subject_hash=None)
        self.refused("subject_hash GLOB 'sha256:*'", subject_hash="sha256:short")
        self.refused("kind != 'sufficiency_review' OR subject_ref IS topic_id", subject_ref="other-fleet:topic")
        self.refused("json_array_length(evidence_refs) > 0", evidence_refs="[]")
        self.refused("json_type(assessment) = 'object'", assessment="[]")
        self.refused("actor_kind = 'primary'", actor_kind="operator")
        self.refused("length(subject_ref) > 0", **{**counter, "subject_ref": ""})

    def test_role_binding(self):
        self.insert(record_id="cr-control")  # the control's operation belongs to its invocation, topic and pin
        for changes in ({"recorded_by_operation_id": "op_extractval"},                         # another invocation's operation
                        {"recorded_by_operation_id": "op_missing001"},                         # no such operation
                        {"topic_id": OTHER},                                                    # another topic
                        {"invocation_id": "inv_vvvvvvvv", "recorded_by_operation_id": "op_extractval"},  # a verification invocation
                        {"contract_revision": 1}):                                              # another contract pin
            self.refused(BOUND, **changes)

    def test_admission_context_binding(self):
        # Pre-contract admission and a contract pin cannot coexist under the invocations CHECKs, so this
        # isolates the context predicate by switching only those CHECKs off while the context is forced.
        self.lease("lease_context01", 9, scope="checkpoint")
        self.invocation("inv_context001", kind="checkpoint", lease="lease_context01")
        self.receipt("op_context001", "inv_context001", lease="lease_context01", gen=9, before=self.rows("SELECT max(state_revision_after) FROM operation_receipts WHERE topic_id = ?", TOPIC)[0][0])
        self.insert(record_id="cr-control", invocation_id="inv_context001", recorded_by_operation_id="op_context001")
        self.x("DROP TRIGGER invocations_identity_immutable")
        self.x("PRAGMA ignore_check_constraints = ON")
        self.x("UPDATE invocations SET admission_context = 'pre-contract/1' WHERE invocation_id = 'inv_context001'")
        self.x("PRAGMA ignore_check_constraints = OFF")
        self.assertEqual(self.rows("SELECT admission_context, contract_revision FROM invocations WHERE invocation_id = 'inv_context001'"), [("pre-contract/1", self.base["contract_revision"])])
        self.refused(BOUND, invocation_id="inv_context001", recorded_by_operation_id="op_context001")

    def test_append_only(self):
        before = self.snapshot("completion_records")
        self.rejects("completion records are append-only", "UPDATE completion_records SET created_at = created_at")
        self.rejects("completion records are retained", "DELETE FROM completion_records")
        self.assertEqual(self.snapshot("completion_records"), before)
