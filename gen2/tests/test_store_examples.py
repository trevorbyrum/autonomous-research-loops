"""Integration controls: the schema-validated example documents, stored whole.

Trace: Astra re-review RA6 ("use full schema-valid JSON in at least one
integration control per family"; "'validate the JSON schema' cannot compare
two separately valid representations"); INVARIANTS A10, G-2, C-12.

The documents are fixtures under gen2/schema/examples/ that `make
gen2-schemas` validates against their schemas: the contract
(valid-two-obligations), the commit receipt (valid-receipt-final), the
DecisionSpec (valid-jev-screening-choice) and the decision receipt
(valid-jev-screening-shadow). They describe one world — topic
fleet-a:intake-latency, approved contract revision 2, invocation
inv_01J8ZQ3W2X under lease generation 7 — which setUp builds around them:
normalized rows are derived from the documents field by field, and every
accept/refuse expectation is written by hand. Each probe changes one field
of a schema-valid document (or of the row beside it), so only the
JSON/row binding can refuse it. The third review's reproductions (Astra
RA2-R, RA3-R) also start from the whole example contract.

What this cannot show: that the example hashes are true hashes (they are
labels; recomputing hashes from stored bytes is the router boundary's,
Phase 1), or anything about runtime behaviour.
"""
from __future__ import annotations

import copy
import json
import sqlite3
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.tests.store_fixtures import StoreTestCase, T, connect, h

EXAMPLES = Path(__file__).resolve().parents[1] / "schema" / "examples"
WORLD = "fleet-a:intake-latency"


def example(rel: str) -> dict:
    return json.loads((EXAMPLES / rel).read_text(encoding="utf-8"))["instance"]


def with_field(document: dict, path: str, value) -> dict:
    out = copy.deepcopy(document)
    *parents, last = path.split(".")
    node = out
    for part in parents:
        node = node[part]
    node[last] = value
    return out


class ExampleWorldTest(StoreTestCase):
    def setUp(self) -> None:
        self.db = connect()
        self.contract_doc = example("contract-v2/valid-two-obligations.json")
        self.receipt_doc = example("commit-outcome/valid-receipt-final.json")
        self.spec_doc = example("decision-spec/valid-jev-screening-choice.json")
        self.decision_doc = example("decision-receipt/valid-jev-screening-shadow.json")
        self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)", WORLD, T, T)
        # S1-S3 before any approved contract: the drafting pass runs pre-contract
        # and obtains the Jev importance proposals the example cites.
        self.lease("lease_draft001", 1, tid=WORLD)
        self.invocation("inv_draft001", tid=WORLD, lease="lease_draft001", pre_contract=True)
        importance = self.spec("dspec_import01", cls="importance_score", primitive="score", options=("low", "high"))
        for rid, subject in (("dec_facet0001", ("facet", "F-effect")), ("dec_imp00001", ("obligation", "O-1"))):
            self.decision_receipt(rid, "inv_draft001", importance, cls="importance_score", tid=WORLD, subject=subject,
                                  answer={"primitive": "score", "score": 8, "confidence": 0.7})
        # The draft the operator rated (revision 1): the example's entries without
        # operator ratings; the rating decision retains what the operator rated.
        draft = copy.deepcopy(self.contract_doc)
        draft.update(revision=1, parent_revision=None, content_hash=self.chash(WORLD, 1))
        payload = self.rating_payload(draft)
        for entry in draft["facet_map"]["facets"] + draft["obligations"]:
            entry["importance"]["operator_rating"] = None
        self.store_contract(draft)
        self.decision("opd_rate0001", "rating_approval", WORLD, rev=1, hsh=self.chash(WORLD, 1), payload=payload)

    # -- building the world from the documents -----------------------------------
    @staticmethod
    def rating_payload(doc: dict) -> dict:
        """A rating decision's retained payload: the band and score each of the
        document's facets and obligations carries."""
        payload: dict = {"facets": {}, "obligations": {}}
        for group, key, entries in (("facets", "facet_id", doc["facet_map"]["facets"]), ("obligations", "obligation_id", doc["obligations"])):
            for entry in entries:
                rating = entry["importance"]["operator_rating"]
                payload[group][entry[key]] = {"band": rating["band"], "score": rating.get("score")}
        return payload

    def store_contract(self, doc: dict, text: str | None = None) -> None:
        """The row of a contract document, stored as `text` (default json.dumps)."""
        self.x("INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?)", doc["topic_id"], doc["revision"], doc["parent_revision"], doc["protocol_revision"],
               doc["facet_map"]["framing_version"], doc["content_hash"], json.dumps(doc) if text is None else text, doc["created_at"])

    def store_rows(self, doc: dict) -> None:
        for entry in doc["facet_map"]["facets"]:
            self.insert_facet(WORLD, doc["revision"], entry)
        for entry in doc["obligations"]:
            self.insert_obligation(WORLD, doc["revision"], entry)

    def approved_example_contract(self) -> None:
        self.store_contract(self.contract_doc)
        self.store_rows(self.contract_doc)
        self.decision("opd_contract2", "contract_approval", WORLD, rev=2, hsh=self.contract_doc["content_hash"])
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = 'opd_contract2' WHERE topic_id = ? AND revision = 2", WORLD)

    def example_invocation(self) -> None:
        """inv_01J8ZQ3W2X, research pass under lease_01J8ZQ3V9T generation 7 and
        contract revision 2 — the identities every example document names."""
        self.approved_example_contract()
        self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_draft001'", T)
        self.lease("lease_01J8ZQ3V9T", 7, tid=WORLD)
        self.invocation("inv_01J8ZQ3W2X", tid=WORLD, lease="lease_01J8ZQ3V9T", contract_rev=2)

    def insert_commit_receipt(self, doc: dict) -> None:
        """The row a commit receipt document describes (the config bundle is the
        invocation's; the fencing lease is the one the receipt releases). The
        row always carries the valid example's own values; `doc` is the JSON."""
        self.x("INSERT INTO operation_receipts (operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, "
               "admission_context, contract_revision, brief_hash, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               self.receipt_doc["operation_id"], self.receipt_doc["receipt_id"], self.receipt_doc["operation_kind"], self.receipt_doc["invocation_id"],
               self.receipt_doc["topic_id"], self.receipt_doc["request_fingerprint"], self.receipt_doc["payload_digest"],
               self.receipt_doc["effects"]["lease_release"]["lease_id"], self.receipt_doc["effects"]["lease_release"]["generation"],
               self.receipt_doc["admission"]["context"], self.receipt_doc["admission"]["contract"]["revision"], None, h("c"),
               self.receipt_doc["state_revision_before"], self.receipt_doc["state_revision_after"], self.receipt_doc["validation"]["validator_version"],
               self.receipt_doc["validation"]["policy_version"], json.dumps(doc), self.receipt_doc["committed_at"])

    def store_spec(self) -> None:
        d = self.spec_doc
        self.x("INSERT INTO decision_specs (spec_hash, spec_id, decision_class, provider, primitive, policy_id, policy_version, protocol_topic_id, document, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", self.decision_doc["spec"]["spec_hash"], d["spec_id"], d["decision_class"], d["provider"], d["primitive"],
               d["action_policy"]["policy_id"], d["action_policy"]["version"], d["protocol"]["topic_id"], json.dumps(d), T)

    def insert_decision_receipt(self, doc: dict) -> None:
        d, r = self.decision_doc, self.decision_doc["provider_response"]
        self.raw_artifact(r["raw_response_digest"])
        self.x("INSERT INTO decision_receipts (decision_receipt_id, invocation_id, topic_id, spec_hash, decision_class, provider, input_status, response_status, raw_response_digest, answer, "
               "subject_kind, subject_ref, policy_id, policy_version, authority_level, qualification_ref, action, commit_operation_id, hold_id, proposal_ref, blind_sample, receipt, decided_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               d["decision_receipt_id"], d["invocation_id"], d["topic_id"], d["spec"]["spec_hash"], d["decision_class"], d["provider"],
               d["input_manifest"]["input_status"], r["status"], r["raw_response_digest"], json.dumps(r["answer"]), d["subject"]["kind"], d["subject"]["ref"],
               d["policy"]["policy_id"], d["policy"]["version"], d["authorization"]["authority_level"], d["authorization"]["qualification_ref"], d["action"],
               d["outcome"]["commit_operation_id"], d["outcome"]["hold_id"], d["outcome"]["proposal_ref"], int(d["blind_sample"]["selected"]), json.dumps(doc), d["decided_at"])

    # -- the controls ----------------------------------------------------------------
    def test_the_example_documents_are_stored_whole(self) -> None:
        """Positive control: every example document is accepted as its row, and
        the normalized rows read back as the document's values."""
        self.example_invocation()
        self.store_spec()
        self.insert_decision_receipt(self.decision_doc)
        self.insert_commit_receipt(self.receipt_doc)
        self.assertEqual(self.rows("SELECT status FROM contract_revisions WHERE topic_id = ? ORDER BY revision", WORLD), [("draft",), ("approved",)])
        self.assertEqual(self.rows("SELECT facet_id, operator_importance_band, operator_importance_score, operator_rating_decision_id FROM facets WHERE contract_revision = 2 ORDER BY facet_id"),
                         [("F-cost", "important", None, "opd_rate0001"), ("F-effect", "critical", 8, "opd_rate0001")])
        self.assertEqual(self.rows("SELECT obligation_id, template_id, template_version, claim_type, stopping_profile_id, exploratory FROM obligations WHERE contract_revision = 2 ORDER BY obligation_id"),
                         [("O-1", "T-comparison", 1, "comparison", "SP-effect", 0), ("O-2", "T-comparison", 1, "comparison", "SP-effect", 0)])
        self.assertEqual(self.rows("SELECT operation_id, topic_id, invocation_id, state_revision_before, validator_version FROM operation_receipts"),
                         [("op_01J8ZQ4K7M", WORLD, "inv_01J8ZQ3W2X", 41, "outcome-validator/1.0.0")])
        self.assertEqual(self.rows("SELECT spec_hash FROM decision_receipts WHERE decision_receipt_id = 'dec_01J8ZQ40AA'"), [(h("7"),)])

    def test_commit_receipt_cannot_describe_another_row(self) -> None:
        """RA6(a) on the schema-valid example receipt. The review's probe first:
        the row is the example's, while the JSON names the row the review used
        (topic fleet-a:t1, invocation inv_pppppppp, revision-before 0,
        validator v1) — then each of those fields alone, then the other
        duplicated identities and the admission reference."""
        self.example_invocation()
        doc = self.receipt_doc
        review = with_field(with_field(with_field(with_field(doc, "topic_id", "fleet-a:t1"), "invocation_id", "inv_pppppppp"),
                                       "state_revision_before", 0), "validation.validator_version", "v1")
        probes = [("the review's four fields together", review)]
        probes += [(path, with_field(doc, path, value)) for path, value in (
            ("topic_id", "fleet-a:t1"), ("invocation_id", "inv_pppppppp"), ("state_revision_before", 0), ("validation.validator_version", "v1"),
            ("operation_id", "op_01J8ZQ4K7N"), ("receipt_id", "rcpt_01J8ZQ4M1B"), ("operation_kind", "interim_transition"),
            ("request_fingerprint", h("0")), ("payload_digest", h("0")), ("state_revision_after", 43), ("validation.policy_version", "engine-policy/other"),
            ("committed_at", "2026-09-26T00:00:00Z"), ("admission.contract.revision", 1), ("admission.contract.content_hash", h("0")),
            ("effects.lease_release.lease_id", "lease_draft001"), ("effects.lease_release.generation", 6))]
        for label, probe in probes:
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_commit_receipt(probe)
                self.assertTrue(any(f in str(ctx.exception) for f in ("CHECK constraint failed", "admission references must be its pins")), str(ctx.exception))
        self.assertEqual(self.rows("SELECT count(*) FROM operation_receipts"), [(0,)])
        self.insert_commit_receipt(doc)

    def test_decision_receipt_cannot_name_another_spec(self) -> None:
        """RA6(b) on the schema-valid example receipt: its spec hash selects
        dspec_screen_v1_jev; the same receipt naming dspec_wrong001 — or the id
        of another stored spec — with that correct hash is refused."""
        self.example_invocation()
        self.store_spec()
        self.spec("dspec_screen02", protocol_topic=WORLD)
        for spec_id in ("dspec_wrong001", "dspec_screen02"):
            with self.subTest(spec_id=spec_id):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_decision_receipt(with_field(self.decision_doc, "spec.spec_id", spec_id))
                self.assertIn("must match its spec", str(ctx.exception))
        self.insert_decision_receipt(self.decision_doc)

    def test_obligation_rows_cannot_contradict_the_example_document(self) -> None:
        """RA6(c): the review's probe values — template T-approved, version 3,
        claim type mechanism, stopping profile SP-approved, exploratory — each
        against the example document's entry (T-comparison, 1, comparison,
        SP-effect, false), on a revision carrying the example's entries
        forward (its ratings still the operator's, from draft 1); then the
        rows equal to the document are accepted."""
        self.approved_example_contract()
        forward = copy.deepcopy(self.contract_doc)
        forward.update(revision=3, parent_revision=2, content_hash=self.chash(WORLD, 3))
        self.store_contract(forward)
        for entry in forward["facet_map"]["facets"]:
            self.insert_facet(WORLD, 3, entry)
        o1 = forward["obligations"][0]
        for column, value in (("template_id", "T-approved"), ("template_version", 3), ("claim_type", "mechanism"),
                              ("stopping_profile_id", "SP-approved"), ("exploratory", 1)):
            with self.subTest(column=column):
                with self.assertRaises(sqlite3.IntegrityError) as ctx:
                    self.insert_obligation(WORLD, 3, o1, **{column: value})
                self.assertIn("equal its document entry", str(ctx.exception))
        for entry in forward["obligations"]:
            self.insert_obligation(WORLD, 3, entry)
        self.assertEqual(self.rows("SELECT count(*) FROM obligations WHERE contract_revision = 3"), [(2,)])

    def test_review_ra2r_self_parent_contract_cannot_rate_itself(self) -> None:
        """RA2-R, the review's reproduction on the whole example contract:
        revision 2 naming itself as parent, every facet and obligation rating
        citing opd_selfrated, its content hash recomputed by the canonical
        helper and the document stored as its actual JCS serialization; then an
        approved rating decision opd_selfrated about revision 2 with that hash
        and the matching payload; then the normalized facet and obligation
        rows. Before RA2-R every step succeeded (the revision was its own
        ancestor). Now the history is refused — or, were it stored, the
        self-rated rows (either reason is accepted) — and nothing is written.
        The example's genuine history, revision 2 under the rated draft 1, is
        then stored whole with its rows and approved."""
        doc = copy.deepcopy(self.contract_doc)
        doc["parent_revision"] = 2
        for entry in doc["facet_map"]["facets"] + doc["obligations"]:
            entry["importance"]["operator_rating"]["operator_decision_id"] = "opd_selfrated"
        doc["content_hash"] = canonical.content_hash(doc)
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.store_contract(doc, text=canonical.canonical_bytes(doc).decode("utf-8"))
            self.decision("opd_selfrated", "rating_approval", WORLD, rev=2, hsh=doc["content_hash"], payload=self.rating_payload(doc))
            self.store_rows(doc)
        self.assertTrue(any(f in str(ctx.exception) for f in ("contract_parent_is_earlier", "exactly what the operator rated")), str(ctx.exception))
        self.assertEqual(self.rows("SELECT revision, parent_revision FROM contract_revisions WHERE topic_id = ?", WORLD), [(1, None)])
        self.assertEqual(self.rows("SELECT (SELECT count(*) FROM facets), (SELECT count(*) FROM obligations), "
                                   "(SELECT count(*) FROM operator_decisions WHERE decision_id = 'opd_selfrated')"), [(0, 0, 0)])
        self.approved_example_contract()
        self.assertEqual(self.rows("SELECT revision, parent_revision, status FROM contract_revisions WHERE topic_id = ? ORDER BY revision", WORLD),
                         [(1, None, "draft"), (2, 1, "approved")])


if __name__ == "__main__":
    unittest.main()
