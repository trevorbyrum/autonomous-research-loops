"""6b2' PR 1: completion-record admission, hold clearance and rollback.

Literal row oracles through the real Router. Each refusal asserts a fragment
unique to its rule and is paired with a commit of the unchanged valid record.
"""
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from gen2.router.schemas import SchemaSet
from gen2.tests.router_fixtures import TOPIC, OTHER, HOLD, AttentionCase, empty_outcome
from gen2.tests.test_dossier_record import evaluate
from gen2.tests.test_registry_dispositions import example_disposition

SCHEMA = "completion-record.schema.json"
RECEIPT = "ver_quote00001"  # the adverse receipt of claim clm_quote00001 revision 1, and its hold HOLD
FIELDS = "record_id, kind, contract_revision, subject_ref, subject_revision, subject_hash, actor_kind, invocation_id, recorded_by_operation_id"


class World(AttentionCase):
    def setUp(self):
        super().setUp()
        self.attention()
        self.cp = self.started("inv_checkpoint1", "checkpoint")
        self.ref = self.artifact(b"completion evidence")
        text = self.artifact(b"a load-bearing claim")
        claim = {"claim_id": "clm_lbearing01", "revision": 1, "text_ref": text, "load_bearing": True, "required_access_tier": "full_text"}
        self.assertEqual(self.send([], grant=self.capture_grant, refs=[text], claims=[claim])["status"], "committed")
        self.assertEqual(self.send([], grant=self.capture_grant, refs=[self.ref], registry_dispositions=[
            example_disposition(self.ref, 0), example_disposition(self.ref, 1, registry_kind="branch", registry_id="B-1", disposition="promote")])["status"], "committed")
        self.dossier = self.router.record_dossier(TOPIC, invocation_id="inv_capture001", history="native", evaluate=evaluate)
        self.assertEqual(self.dossier["status"], "recorded")

    def completion(self, kind, **changes):
        subject = {"counterevidence_search": ("clm_lbearing01", 1, None, "none_found"),
                   "competing_explanation": ("rdp_history00", None, None, "explanation_rejected"),
                   "sufficiency_review": (TOPIC, 1, self.dossier["content_hash"], "insufficient"),
                   "verification_adjudication": (RECEIPT, 1, None, "verdict_upheld")}[kind]
        return {"record_id": f"cr-{kind}", "kind": kind, "contract_revision": 1, "subject_ref": subject[0], "subject_revision": subject[1],
                "subject_hash": subject[2], "assessment": {"outcome": subject[3], "summary": "Recorded by the independent seat"},
                "evidence_refs": [self.ref], **changes}

    def submit(self, records, grant=None, **sections):
        return self.send([], grant=grant or self.cp, refs=[self.ref], completion_records=records, **sections)

    def stored(self):
        return self.rows(f"SELECT {FIELDS} FROM completion_records ORDER BY rowid")

    def refuse(self, record, fragment, reason="payload_invalid", **kwargs):
        before = self.state()
        out = self.submit([record], **kwargs)
        self.assertEqual((out["status"], out.get("reason")), ("rejected", reason), out)
        self.assertIn(fragment, out.get("detail", ""))
        self.assert_audited_state(before, 1)

    def accepted(self, kind, **changes):
        out = self.submit([self.completion(kind, **changes)])
        self.assertEqual(out["status"], "committed", out)
        return out


class AdmissionTest(World):
    def test_each_kind_is_stored_with_router_attribution(self):
        expected = []
        for kind, ref, revision, subject_hash in (("counterevidence_search", "clm_lbearing01", 1, None), ("competing_explanation", "rdp_history00", None, None),
                ("sufficiency_review", TOPIC, 1, self.dossier["content_hash"]), ("verification_adjudication", RECEIPT, 1, None)):
            self.accepted(kind)
            expected.append((f"cr-{kind}", kind, 1, ref, revision, subject_hash, "primary", "inv_checkpoint1", self.env["operation_id"]))
            self.assertEqual(self.stored()[-1], expected[-1])
        self.assertEqual(self.stored(), expected)
        self.assertEqual(json.loads(self.value("SELECT assessment FROM completion_records WHERE kind = 'sufficiency_review'")),
            {"outcome": "insufficient", "summary": "Recorded by the independent seat"})
        self.assertEqual(json.loads(self.value("SELECT evidence_refs FROM completion_records WHERE kind = 'sufficiency_review'")), [self.ref])

    def test_research_pass_may_record(self):
        out = self.submit([self.completion("competing_explanation")], grant=self.capture_grant)
        self.assertEqual(out["status"], "committed", out)

    def test_counterevidence_guards(self):
        self.foreign("claims", "clm_foreign0001", "claim_id")
        for changes, reason, fragment in (
                ({"subject_ref": "clm_missing0001"}, "payload_invalid", "counterevidence subject claim revision does not exist"),
                ({"subject_revision": 2}, "payload_invalid", "counterevidence subject claim revision does not exist"),
                ({"subject_ref": "clm_foreign0001"}, "cross_topic", "counterevidence subject claim revision belongs to another topic"),
                ({"subject_ref": "clm_quote00001"}, "payload_invalid", "counterevidence subject claim is not load-bearing"),
                ({"contract_revision": 2}, "payload_invalid", "completion record differs from its invocation's contract pin")):
            self.refuse(self.completion("counterevidence_search", **changes), fragment, reason)
        self.refuse(self.completion("counterevidence_search"), "other than the claim's producer", grant=self.capture_grant)
        self.accepted("counterevidence_search")

    def test_competing_explanation_guards(self):
        self.foreign("registry_dispositions", "rdp_foreign001", "disposition_id")
        self.assertEqual(self.send([], grant=self.capture_grant, refs=[self.ref], registry_dispositions=[
            example_disposition(self.ref, 2, disposition="resolved", supersedes_id="rdp_history00")])["status"], "committed")
        for changes, reason, fragment in (
                ({"subject_ref": "rdp_missing0001"}, "payload_invalid", "competing-explanation subject disposition does not exist"),
                ({"subject_ref": "rdp_foreign001"}, "cross_topic", "competing-explanation subject disposition belongs to another topic"),
                ({"subject_ref": "rdp_history01"}, "payload_invalid", "competing-explanation subject is not a contradiction disposition"),
                ({"subject_ref": "rdp_history00"}, "payload_invalid", "competing-explanation subject disposition is explicitly superseded")):
            self.refuse(self.completion("competing_explanation", **changes), fragment, reason)
        self.accepted("competing_explanation", subject_ref="rdp_history02")

    def test_sufficiency_review_guards(self):
        for changes, reason, fragment in (
                ({"subject_revision": 2}, "payload_invalid", "sufficiency-review dossier does not exist"),
                ({"subject_ref": OTHER}, "cross_topic", "sufficiency review names another topic's dossier"),
                ({"subject_hash": "sha256:" + "0" * 64}, "payload_invalid", "sufficiency review hash differs from its dossier"),
                ({"contract_revision": 2}, "payload_invalid", "completion record differs from its invocation's contract pin")):
            self.refuse(self.completion("sufficiency_review", **changes), fragment, reason)
        self.refuse(self.completion("sufficiency_review"), "other than the dossier's producer", grant=self.capture_grant)
        self.x("PRAGMA foreign_keys = OFF")
        self.x("DROP TRIGGER dossiers_immutable_u")  # a retained dossier of another pin; Router authority alone
        self.x("UPDATE dossiers SET contract_revision = 2")
        self.refuse(self.completion("sufficiency_review"), "sufficiency review contract pin differs from its dossier's")
        self.x("UPDATE dossiers SET contract_revision = 1")  # restore only the mismatched pin: the same setup, now valid
        self.x("PRAGMA foreign_keys = ON")
        out = self.accepted("sufficiency_review")
        self.assertEqual(self.stored(), [("cr-sufficiency_review", "sufficiency_review", 1, TOPIC, 1, self.dossier["content_hash"], "primary",
            "inv_checkpoint1", self.env["operation_id"])])
        self.assertEqual(out["receipt"]["effects"]["holds_created"], [])

    def test_adjudication_guards(self):
        self.foreign("verification_receipts", "ver_foreign0001", "verification_receipt_id")
        self.foreign("verification_receipts", "ver_supports001", "verification_receipt_id", TOPIC, verdict="supports")
        for changes, reason, fragment in (
                ({"subject_ref": "ver_missing0001"}, "payload_invalid", "adjudication subject receipt does not exist"),
                ({"subject_ref": "ver_foreign0001"}, "cross_topic", "adjudication subject receipt belongs to another topic"),
                ({"subject_revision": 2}, "payload_invalid", "adjudication claim revision differs from its receipt's")):
            self.refuse(self.completion("verification_adjudication", **changes), fragment, reason)
        self.refuse(self.completion("verification_adjudication", subject_ref="ver_supports001"), "adjudication subject receipt raised no disagreement")
        self.accepted("verification_adjudication")

    def foreign(self, table, new_id, key, topic=OTHER, **changes):
        """A copy of the topic's first row of `table` under `new_id` and `topic` (DDL mirrors off: Router authority alone)."""
        for (name,) in self.rows("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = ?", table):
            self.x(f"DROP TRIGGER {name}")
        columns = [r[1] for r in self.rows(f"PRAGMA table_info({table})")]
        row = {**dict(zip(columns, self.rows(f"SELECT * FROM {table} LIMIT 1")[0])), key: new_id, "topic_id": topic, **changes}
        if "receipt" in row:  # the stored document repeats its columns
            row["receipt"] = json.dumps({**json.loads(row["receipt"]), key: new_id, "topic_id": topic, **changes})
        self.x("PRAGMA foreign_keys = OFF")
        self.x(f"INSERT INTO {table} ({','.join(row)}) VALUES ({','.join('?' for _ in row)})", *row.values())
        self.x("PRAGMA foreign_keys = ON")

    def test_roles_and_mixed_documents(self):
        self.refuse(self.completion("verification_adjudication"), "a verification invocation cannot commit completion_records", "kind_not_permitted", grant=self.grant)
        mixed = self.attention_document()
        before = self.state()
        out = self.send([], grant=self.cp, refs=[self.ref], completion_records=[self.completion("verification_adjudication")], verification_receipts=[mixed])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "kind_not_permitted"), out)
        self.assertIn("a checkpoint invocation cannot commit verification_receipts", out["detail"])
        self.assert_audited_state(before, 1)
        self.accepted("verification_adjudication")

    def attention_document(self):
        doc = self.document()
        doc["verification_receipt_id"] = "ver_mixed000001"
        return doc

    def test_record_identity_conflict_rolls_back(self):
        self.accepted("competing_explanation")
        before = self.state()
        out = self.submit([self.completion("competing_explanation", assessment={"outcome": "explanation_stands", "summary": "changed"})])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assert_audited_state(before, 1)

    def test_empty_section_control(self):
        self.assertEqual(self.submit([])["status"], "committed")
        self.assertEqual(self.stored(), [])


class GenerationTest(World):
    def counter(self):
        return self.value("SELECT generation FROM store_generation")

    def test_record_only_transaction_bumps_once_and_is_captured(self):
        self.assertEqual(self.submit([]).get("status"), "committed")  # a primary commit whose operation the rows name
        op = self.env["operation_id"]
        def row(n):
            return {**self.completion("competing_explanation", record_id=f"cr-gen{n}"), "topic_id": TOPIC, "actor_kind": "primary",
                    "invocation_id": "inv_checkpoint1", "recorded_by_operation_id": op, "created_at": "2026-09-27T10:40:00Z"}
        for rows in ((row(1),), (row(2), row(3), row(4))):
            before = self.counter()
            with self.store.transaction():
                for r in rows:
                    self.store.insert("completion_records", r)
            self.assertEqual(self.counter(), before + 1)
        captured = {t.name: t for t in self.store.capture_topic(TOPIC).tables}["completion_records"]
        self.assertEqual(sorted(r[captured.columns.index("record_id")] for r in captured.rows), ["cr-gen1", "cr-gen2", "cr-gen3", "cr-gen4"])


class HoldTest(World):
    def hold_row(self, hold=HOLD):
        return self.rows("SELECT hold_id, subject_ref, cleared_at, cleared_by_decision_id, cleared_by_operation_id FROM holds WHERE hold_id = ?", hold)[0]

    def test_adjudication_clears_exactly_its_hold(self):
        self.hold(self.capture_grant, "hold_unrelated01")
        unrelated = self.hold_row("hold_unrelated01")
        self.assertEqual(self.hold_row()[2:], (None, None, None))
        out = self.accepted("verification_adjudication")
        self.assertEqual(self.hold_row(), (HOLD, f"verification:{RECEIPT}", out["receipt"]["committed_at"], None, self.env["operation_id"]))
        self.assertEqual(self.hold_row("hold_unrelated01"), unrelated)
        self.assertEqual(self.rows("SELECT count(*) FROM completion_records"), [(1,)])

    def test_non_adjudication_clears_nothing(self):
        before = self.hold_row()
        self.accepted("counterevidence_search")
        self.assertEqual(self.hold_row(), before)

    def test_already_cleared_hold_is_skipped(self):
        self.x("UPDATE holds SET cleared_at = '2026-09-27T10:10:00Z', cleared_by_operation_id = 'op_capture001' WHERE hold_id = ?", HOLD)
        cleared = self.hold_row()
        self.accepted("verification_adjudication")
        self.assertEqual(self.hold_row(), cleared)
        self.assertEqual(len(self.stored()), 1)

    def test_replay_writes_nothing(self):
        out = self.accepted("verification_adjudication")
        before = self.state(exclude=())
        replay = self.router.commit_outcome(self.env)
        self.assertEqual((replay["status"], replay["receipt"]), ("replayed", out["receipt"]))
        self.assertEqual(self.state(exclude=()), before)

    def test_late_fault_rolls_back_record_and_hold(self):
        before = self.state(exclude=())
        self.faults["in_transaction:end"] = RuntimeError("fixture after adjudication")
        with self.assertRaisesRegex(RuntimeError, "after adjudication"):
            self.submit([self.completion("verification_adjudication")])
        self.assertEqual(self.state(exclude=()), before)
        self.assertEqual(self.hold_row()[2:], (None, None, None))

    def test_failed_hold_update_rolls_back_record(self):
        before = self.state(exclude=())
        update = self.store.update
        def fail(table, key, changes, **kwargs):
            if table == "holds":
                raise sqlite3.IntegrityError("fixture failed hold clearing")
            update(table, key, changes, **kwargs)
        with patch.object(self.store, "update", side_effect=fail):
            out = self.submit([self.completion("verification_adjudication")])
        self.assertEqual((out["status"], out.get("reason")), ("rejected", "payload_invalid"), out)
        self.assert_audited_state(before, 1)
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.hold_row()[2:], (None, None, None))


class SchemaTest(World):
    schemas = SchemaSet(extra={SCHEMA: json.loads((Path(__file__).resolve().parents[1] / "schema" / SCHEMA).read_text())})

    def errors(self, kind, **changes):
        return self.schemas.errors(self.completion(kind, **changes), SCHEMA)

    def test_every_kind_validates(self):
        for kind in ("counterevidence_search", "competing_explanation", "sufficiency_review", "verification_adjudication"):
            self.assertEqual(self.errors(kind), [], kind)

    def test_required_and_closed(self):
        for field in self.completion("counterevidence_search"):
            record = self.completion("counterevidence_search")
            del record[field]
            self.assertTrue(self.schemas.errors(record, SCHEMA), field)
        for changes in ({"unknown": 1}, {"actor_kind": "primary"}, {"evidence_refs": []}, {"evidence_refs": [self.ref, self.ref]},
                        {"assessment": {"outcome": "none_found"}}, {"assessment": {"outcome": "none_found", "summary": "s", "extra": 1}},
                        {"contract_revision": 0}, {"subject_revision": 0}, {"record_id": ""}):
            self.assertTrue(self.errors("counterevidence_search", **changes), changes)

    def test_kind_pairings(self):
        for kind, bad in (("counterevidence_search", {"subject_hash": self.dossier["content_hash"]}), ("counterevidence_search", {"subject_revision": None}),
                          ("competing_explanation", {"subject_revision": 1}), ("competing_explanation", {"subject_hash": self.dossier["content_hash"]}),
                          ("sufficiency_review", {"subject_hash": None}), ("sufficiency_review", {"subject_revision": None}),
                          ("sufficiency_review", {"subject_ref": "clm_lbearing01"}), ("verification_adjudication", {"subject_hash": self.dossier["content_hash"]}),
                          ("verification_adjudication", {"subject_ref": "clm_lbearing01"}), ("counterevidence_search", {"subject_ref": RECEIPT})):
            self.assertTrue(self.errors(kind, **bad), (kind, bad))
        for kind, outcome in (("counterevidence_search", "sufficient"), ("competing_explanation", "none_found"),
                              ("sufficiency_review", "incomplete"), ("verification_adjudication", "explanation_stands")):
            self.assertTrue(self.errors(kind, assessment={"outcome": outcome, "summary": "s"}), (kind, outcome))
        for kind, outcome in (("counterevidence_search", "incomplete"), ("competing_explanation", "explanation_stands"),
                              ("sufficiency_review", "sufficient"), ("verification_adjudication", "verdict_overturned")):
            self.assertEqual(self.errors(kind, assessment={"outcome": outcome, "summary": "s"}), [], (kind, outcome))

    def test_outcome_document_section(self):
        document = {**empty_outcome("inv_checkpoint1", "interim_transition"), "completion_records": [self.completion("counterevidence_search")]}
        self.assertEqual(self.router._schemas.errors(document, "outcome-document.schema.json"), [])
        self.assertTrue(self.router._schemas.errors({**document, "completion_records": [{**self.completion("counterevidence_search"), "actor_kind": "operator"}]},
            "outcome-document.schema.json"))
