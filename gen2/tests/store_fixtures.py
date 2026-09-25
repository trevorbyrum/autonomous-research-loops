"""Shared fixtures for the gen-2 store DDL tests (not collected as tests).

Every connection applies gen2/store/connection.sql — the integrity-bearing
per-connection pragmas (foreign_keys, recursive_triggers) — before the DDL,
exactly as the store module must (INVARIANTS C-11).

DDL_TEXT and CONNECTION_TEXT are module globals so that the mutation harness
(tools/gen2_mutations.py) can substitute a mutated schema in memory and rerun
the same tests; nothing else should reassign them.

Builders construct input rows only. Expected accept/reject outcomes are
written by hand in each test, never derived from the DDL under test.
"""
from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path

STORE_DIR = Path(__file__).resolve().parents[1] / "store"
DDL_TEXT = (STORE_DIR / "schema.sql").read_text(encoding="utf-8")
CONNECTION_TEXT = (STORE_DIR / "connection.sql").read_text(encoding="utf-8")

T = "2026-09-25T12:00:00Z"
TOPIC = "fleet-a:t1"
OTHER = "fleet-a:t2"

# The one subject kind each operator-decision kind admits (hand-copied from
# the A2 rule, so builders can default it; tests that probe the rule pass
# subject_kind explicitly).
SUBJECT_KIND = {
    "brief_confirmation": "intake_brief", "scope_approval": "scoping_report",
    "rating_approval": "contract_revision", "contract_approval": "contract_revision",
    "amendment_approval": "contract_revision", "reframe_approval": "contract_revision",
    "completion_approval": "dossier", "retirement": "topic", "hold_clearance": "hold",
    "publication_approval": "publication_source",
    "blind_initial_disposition": "decision_receipt", "advised_feedback": "decision_receipt",
}


def h(ch: str) -> str:
    return "sha256:" + ch * 64


def importance(band=None, score=None, decision=None, psource=None, pscore=None, preceipt=None) -> dict:
    """The contract-v2 importance object (proposed vs operator rating kept apart)."""
    proposed = None if psource is None and pscore is None else {"source": psource, "score": pscore, "decision_receipt_id": preceipt}
    rating = None if band is None and score is None and decision is None else {"band": band, "score": score, "operator_decision_id": decision}
    return {"proposed": proposed, "operator_rating": rating}


def facet(fid: str, **imp) -> dict:
    return {"facet_id": fid, "label": fid, "kind": "effect", "importance": importance(**imp)}


def obligation(oid: str, facet_ids=("F-1",), **imp) -> dict:
    return {"obligation_id": oid, "facet_ids": list(facet_ids), "importance": importance(**imp)}


def connect(apply_connection_contract: bool = True) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", isolation_level=None)
    if apply_connection_contract:
        db.executescript(CONNECTION_TEXT)
    else:
        db.execute("PRAGMA foreign_keys = ON")  # FK enforcement only; recursive_triggers left at SQLite's default (off)
    db.executescript(DDL_TEXT)
    return db


class StoreTestCase(unittest.TestCase):
    APPLY_CONNECTION_CONTRACT = True

    def setUp(self) -> None:
        self.db = connect(self.APPLY_CONNECTION_CONTRACT)
        for tid in (TOPIC, OTHER):
            self.x("INSERT INTO queue_entries (topic_id, fleet_id, priority, status, created_at, updated_at) VALUES (?, 'fleet-a', 1, 'awaiting_brief_confirmation', ?, ?)", tid, T, T)
            self.contract(tid, 1)

    def tearDown(self) -> None:
        self.db.close()

    def x(self, sql: str, *params):
        return self.db.execute(sql, params)

    def rows(self, sql: str, *params) -> list[tuple]:
        return self.db.execute(sql, params).fetchall()

    def rejects(self, fragment: str, sql: str, *params) -> None:
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            self.x(sql, *params)
        self.assertIn(fragment, str(ctx.exception))

    def snapshot(self, table: str) -> list[tuple]:
        return self.rows(f"SELECT * FROM {table} ORDER BY rowid")

    # -- builders --------------------------------------------------------
    def contract(self, tid: str, rev: int, status: str = "draft", approved_by: str | None = None, ch: str | None = None,
                 facets: tuple = (), obligations: tuple = ()) -> str:
        content = h(ch or ("a" if tid == TOPIC else "b") if rev == 1 else ch or str(rev))
        doc = json.dumps({"topic_id": tid, "revision": rev, "content_hash": content, "protocol_revision": 1,
                          "facet_map": {"framing_version": 1, "facets": list(facets)}, "obligations": list(obligations)})
        self.x("INSERT INTO contract_revisions (topic_id, revision, parent_revision, protocol_revision, framing_version, content_hash, document, status, approved_by_decision_id, created_at) VALUES (?, ?, ?, 1, 1, ?, ?, ?, ?, ?)",
               tid, rev, None if rev == 1 else rev - 1, content, doc, status, approved_by, T)
        return content

    def decision(self, did: str, kind: str, tid: str | None = TOPIC, disposition: str = "approved", *, ref: str | None = None,
                 rev: int | None = None, hsh: str | None = None, subject_kind: str | None = None) -> str:
        """Record an operator decision. Subject defaults: contract/dossier/topic
        subjects are referenced by topic id; other refs must be passed."""
        sk = subject_kind or SUBJECT_KIND[kind]
        if ref is None:
            ref = tid if sk in ("contract_revision", "dossier", "topic") else "ref-" + did
        self.x("INSERT INTO operator_decisions (decision_id, topic_id, kind, disposition, subject_kind, subject_ref, subject_revision, subject_hash, operator_id, decided_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'trevor', ?)",
               did, tid, kind, disposition, sk, ref, rev, hsh, T)
        return did

    @staticmethod
    def _importance_columns(entry: dict) -> tuple:
        proposed = entry["importance"]["proposed"] or {}
        rating = entry["importance"]["operator_rating"] or {}
        return (proposed.get("source"), proposed.get("score"), proposed.get("decision_receipt_id"),
                rating.get("band"), rating.get("score"), rating.get("operator_decision_id"))

    def insert_facet(self, tid: str, rev: int, entry: dict) -> None:
        self.x("INSERT INTO facets (topic_id, contract_revision, facet_id, proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, "
               "operator_importance_band, operator_importance_score, operator_rating_decision_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
               tid, rev, entry["facet_id"], *self._importance_columns(entry))

    def insert_obligation(self, tid: str, rev: int, entry: dict) -> None:
        self.x("INSERT INTO obligations (topic_id, contract_revision, obligation_id, template_id, template_version, claim_type, facet_ids, stopping_profile_id, exploratory, "
               "proposed_importance_source, proposed_importance_score, proposed_decision_receipt_id, operator_importance_band, operator_importance_score, operator_rating_decision_id) "
               "VALUES (?, ?, ?, 'T1', 1, 'effect', ?, 'SP-1', 0, ?, ?, ?, ?, ?, ?)",
               tid, rev, entry["obligation_id"], json.dumps(entry["facet_ids"]), *self._importance_columns(entry))

    def contract_with_rows(self, tid: str, rev: int, facets: tuple = (), obligations: tuple = (), **kwargs) -> str:
        """A draft revision whose document carries these entries, plus their normalized rows."""
        content = self.contract(tid, rev, facets=facets, obligations=obligations, **kwargs)
        for entry in facets:
            self.insert_facet(tid, rev, entry)
        for entry in obligations:
            self.insert_obligation(tid, rev, entry)
        return content

    def content_hash_of(self, tid: str, rev: int) -> str:
        return self.rows("SELECT content_hash FROM contract_revisions WHERE topic_id = ? AND revision = ?", tid, rev)[0][0]

    def approve_contract(self, tid: str, rev: int, did: str | None = None, kind: str = "contract_approval") -> str:
        did = did or f"opd_ca{rev:02d}{tid[-2:]}xx".replace(":", "")
        self.decision(did, kind, tid, rev=rev, hsh=self.content_hash_of(tid, rev))
        self.x("UPDATE contract_revisions SET status = 'approved', approved_by_decision_id = ? WHERE topic_id = ? AND revision = ?", did, tid, rev)
        return did

    def set_status(self, tid: str, status: str, decision: str | None = None) -> None:
        self.x("UPDATE queue_entries SET status = ?, status_decision_id = ?, state_revision = state_revision + 1 WHERE topic_id = ?", status, decision, tid)

    def state_revision(self, tid: str = TOPIC) -> int:
        return self.rows("SELECT state_revision FROM queue_entries WHERE topic_id = ?", tid)[0][0]

    def lease(self, lid: str, gen: int, tid: str = TOPIC, scope: str = "research") -> None:
        self.x("INSERT INTO leases (lease_id, topic_id, scope, generation, station_id, granted_at, expires_at) VALUES (?, ?, ?, ?, 'st1', ?, ?)", lid, tid, scope, gen, T, T)

    def invocation(self, iid: str, kind: str = "research_pass", lease: str | None = "lease_aaaaaaaa", tid: str = TOPIC, parent: str | None = None) -> None:
        self.x("INSERT INTO invocations (invocation_id, kind, topic_id, parent_invocation_id, lease_id, capability_id, config_bundle_hash, state, admitted_at, deadline_at, state_changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'admitted', ?, ?, ?)",
               iid, kind, tid, parent, lease, "cap_" + iid[4:], h("c"), T, T, T)

    def receipt(self, op: str, inv: str, lease: str = "lease_aaaaaaaa", gen: int = 1, before: int = 0, kind: str = "final_outcome", tid: str = TOPIC, rid: str | None = None, digest: str = "d") -> None:
        rid = rid or "rcpt_" + op[3:]
        body = json.dumps({"operation_id": op, "receipt_id": rid, "payload_digest": h(digest)})
        self.x("INSERT INTO operation_receipts (operation_id, receipt_id, operation_kind, invocation_id, topic_id, request_fingerprint, payload_digest, lease_id, lease_generation, contract_revision, config_bundle_hash, state_revision_before, state_revision_after, validator_version, policy_version, receipt, committed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, 'v1', 'p1', ?, ?)",
               op, rid, kind, inv, tid, h("f"), h(digest), lease, gen, h("c"), before, before + 1, body, T)

    def spec(self, spec_id: str = "dspec_screen01", provider: str = "jev", cls: str = "screening") -> str:
        sh = "sha256:" + (spec_id.encode().hex() + "0" * 64)[:64]
        self.x("INSERT INTO decision_specs (spec_hash, spec_id, decision_class, provider, document, created_at) VALUES (?, ?, ?, ?, ?, ?)",
               sh, spec_id, cls, provider, json.dumps({"spec_id": spec_id, "provider": provider, "decision_class": cls}), T)
        return sh

    def decision_receipt(self, did: str, inv: str, spec_hash: str, provider: str = "jev", answer: dict | None = None, authority: str = "shadow",
                         qualification: str | None = None, action: str = "shadow_log_only", commit_op: str | None = None, hold: str | None = None,
                         cls: str = "screening", tid: str = TOPIC) -> None:
        if answer is None:
            answer = {"primitive": "choice", "selected_option_id": "include", "distribution": {"include": 0.8, "exclude": 0.2}, "confidence": 0.7}
        self.x("INSERT INTO decision_receipts (decision_receipt_id, invocation_id, topic_id, spec_hash, decision_class, provider, input_status, response_status, raw_response_digest, answer, policy_id, policy_version, authority_level, qualification_ref, action, commit_operation_id, hold_id, blind_sample, receipt, decided_at) VALUES (?, ?, ?, ?, ?, ?, 'complete', 'answered', ?, ?, 'P1', 1, ?, ?, ?, ?, ?, 0, '{}', ?)",
               did, inv, tid, spec_hash, cls, provider, h("5"), json.dumps(answer), authority, qualification, action, commit_op, hold, T)

    def to_running(self, iid: str) -> None:
        self.x("UPDATE invocations SET state = 'launching', launch_intent_at = ? WHERE invocation_id = ?", T, iid)
        self.x("UPDATE invocations SET state = 'running', job_handle = ?, host_id = 'dev', boot_id = 'b1', start_fingerprint = 'st=1' WHERE invocation_id = ?", "job-" + iid, iid)

    # -- one coherent row in every table -------------------------------------
    def populate_every_table(self) -> None:
        """A positive control that the whole schema admits one coherent history,
        and the population the history-rewrite sweep attacks. Keep one row in
        every table: test_every_table_is_populated fails if a table is added
        without extending this."""
        self.x("INSERT INTO artifacts (content_hash, size_bytes, media_type, topic_id, staged_at) VALUES (?, 10, 'application/json', ?, ?)", h("7"), TOPIC, T)
        # S3: the operator rates draft revision 1; revision 2 carries the ratings and is approved
        self.decision("opd_rating001", "rating_approval", rev=1, hsh=self.content_hash_of(TOPIC, 1))
        self.contract_with_rows(TOPIC, 2, facets=(facet("F-1", band="critical", score=8, decision="opd_rating001"),),
                                obligations=(obligation("O-1", ("F-1",), band="critical", score=8, decision="opd_rating001"),))
        self.approve_contract(TOPIC, 2, "opd_contract1")
        self.x("UPDATE queue_entries SET active_contract_revision = 2 WHERE topic_id = ?", TOPIC)
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.to_running("inv_pppppppp")
        self.x("INSERT INTO invocation_transitions (invocation_id, seq, from_state, to_state, at, cause) VALUES ('inv_pppppppp', 1, NULL, 'admitted', ?, 'admit')", T)
        self.x("INSERT INTO dossiers (topic_id, dossier_revision, contract_revision, evidence_revision, evaluator_version, content_hash, document_ref, created_at) VALUES (?, 1, 2, 1, 'eval-1', ?, ?, ?)", TOPIC, h("3"), h("7"), T)
        self.receipt("op_00000001", "inv_pppppppp", kind="final_outcome", before=0)
        self.x("INSERT INTO research_ordinals VALUES (?, 1, 'inv_pppppppp', 'op_00000001')", TOPIC)
        self.x("INSERT INTO review_episodes (episode_id, topic_id, kind, opened_at, opened_by_operation_id) VALUES ('ep-1', ?, 'method_fit', ?, 'op_00000001')", TOPIC, T)
        self.x("INSERT INTO review_triggers (trigger_identity, topic_id, reason_code, signal_source, cause_ref, observed_at, episode_id, handled_at) VALUES (?, ?, 'persistent_contradiction', 'deterministic', 'CL-3', ?, 'ep-1', ?)", h("1"), TOPIC, T, T)
        self.x("INSERT INTO capability_facts (fact_id, capability, state, detail, since, affected_lanes, recorded_at) VALUES ('cf-1', 'secrets_backend', 'failing', 'vault 403', ?, '[\"semantic_scholar\"]', ?)", T, T)
        self.x("INSERT INTO holds (hold_id, topic_id, subject_ref, hold_class, cause, recoverability, required_authority, owner, deadline_at, clears_when, capability_fact_id, created_at) "
               "VALUES ('hold_00000001', ?, 'lane:semantic_scholar', 'capability', 'vault 403', 'needs_remediation', 'router', 'router', ?, 'secrets backend healthy', 'cf-1', ?)", TOPIC, T, T)
        self.x("INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt, lane, request, obligation_ids, started_at, coverage_state, result_count, policy_version) "
               "VALUES ('o1', 'inv_pppppppp', ?, ?, 1, 'crossref', '{}', '[\"O-1\"]', ?, 'searched_ok', 1, 'pol1')", TOPIC, h("4"), T)
        self.x("INSERT INTO retrieval_events (event_id, observation_id, topic_id, provider_record_id, rank, captured_at) VALUES ('e1', 'o1', ?, 'rec-1', 1, ?)", TOPIC, T)
        self.x("INSERT INTO works (work_id, identity_scheme, identity_value, created_at) VALUES ('wrk_00000001', 'doi', '10.1/x', ?)", T)
        self.x("INSERT INTO record_work_links (event_id, work_id, dedup_method_version, linked_at) VALUES ('e1', 'wrk_00000001', 'dedup-1', ?)", T)
        self.x("INSERT INTO screening_assessments (assessment_id, topic_id, work_id, contract_revision, eligibility_protocol_version, framing_version, stage, decision, reason_code, criterion_results, actor_kind, invocation_id, recorded_by_operation_id, created_at) "
               "VALUES ('sa1', ?, 'wrk_00000001', 2, 1, 1, 'abstract', 'include', NULL, '{}', 'primary', 'inv_pppppppp', 'op_00000001', ?)", TOPIC, T)
        self.x("INSERT INTO claims (claim_id, revision, topic_id, text_ref, producer_invocation_id, load_bearing, required_access_tier, status, created_at) VALUES ('clm_00000001', 1, ?, ?, 'inv_pppppppp', 1, 'full_text', 'provisional', ?)", TOPIC, h("7"), T)
        self.x("INSERT INTO claim_source_links (claim_id, claim_revision, work_id, source_version, topic_id, contract_revision, obligation_id, spans, contribution, evidence_origin_lineage, created_at) "
               "VALUES ('clm_00000001', 1, 'wrk_00000001', 'v1', ?, 2, 'O-1', '[]', 'answer', 'study-1', ?)", TOPIC, T)
        self.lease("lease_vvvvvvvv", 2, scope="verification")
        self.invocation("inv_vvvvvvvv", kind="verification", lease="lease_vvvvvvvv")
        self.x("INSERT INTO quote_checks (check_id, claim_id, claim_revision, source_artifact_hash, span_start, span_end, normalization_version, exact_match, nli_signal, quote_quarantined, checked_at) "
               "VALUES ('qc-1', 'clm_00000001', 1, ?, 0, 5, 'n1', 'matched', 'not_run', 0, ?)", h("7"), T)
        self.x("INSERT INTO verification_receipts (verification_receipt_id, topic_id, claim_id, claim_revision, work_id, source_version, cited_spans, obtained_content_hash, access_tier, use, required_access_tier, acquisition, extraction_method, extraction_invocation_id, extraction_validation_ref, producer_invocation_id, verifier_invocation_id, verdict, receipt, verified_at) "
               "VALUES ('ver_00000001', ?, 'clm_00000001', 1, 'wrk_00000001', 'v1', '[{\"start\":0,\"end\":5}]', ?, 'full_text', 'load_bearing', 'full_text', '{}', 'verifier_extraction', 'inv_vvvvvvvv', NULL, 'inv_pppppppp', 'inv_vvvvvvvv', 'supports', '{}', ?)", TOPIC, h("7"), T)
        self.x("UPDATE claims SET status = 'accepted_support' WHERE claim_id = 'clm_00000001' AND revision = 1")
        jev = self.spec()
        self.decision_receipt("dec_00000001", "inv_pppppppp", jev)
        self.decision("opd_publish01", "publication_approval", ref="dossier-1", rev=1, hsh=h("3"))
        self.outbox("obx_00000001", "man_00000001", 1, None, "opd_publish01", h("6"), source_rev=1, source_hash=h("3"), sinks=("neo4j",))
        self.x("INSERT INTO sink_delivery_receipts (delivery_receipt_id, outbox_event_id, sink, attempt, status, tombstones_acknowledged, attempted_at, acked_at) VALUES ('d1', 'obx_00000001', 'neo4j', 1, 'delivered', 1, ?, ?)", T, T)
        self.x("INSERT INTO sink_generations (topic_id, sink, delivered_generation, delivered_at) VALUES (?, 'neo4j', 1, ?)", TOPIC, T)
        self.x("INSERT INTO audit_events (audit_event_id, at, kind, topic_id, detail) VALUES ('aud_00000001', ?, 'commit', ?, '{}')", T, TOPIC)

    def outbox(self, eid: str, mid: str, gen: int, sup: int | None, decision: str, manifest_hash: str, *, source_rev: int = 3,
               source_hash: str | None = None, sinks: tuple[str, ...] = ("neo4j", "qdrant"), kind: str = "completion_publication",
               tid: str = TOPIC, op: str = "op_00000001", manifest_overrides: dict | None = None) -> None:
        source_hash = source_hash or h("5")
        manifest = {"manifest_id": mid, "topic_id": tid, "artifact_kind": kind, "generation": gen,
                    "source": {"revision": source_rev, "content_hash": source_hash},
                    "approval": {"operator_decision_id": decision, "approved_revision": source_rev},
                    "expected_sinks": list(sinks), "supersedes": None if sup is None else {"manifest_id": "man_prev0000", "generation": sup}}
        manifest.update(manifest_overrides or {})
        self.x("INSERT INTO outbox_events (outbox_event_id, topic_id, manifest_id, manifest_hash, artifact_kind, generation, supersedes_generation, source_revision, source_content_hash, approval_decision_id, expected_sinks, manifest, committed_by_operation_id, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               eid, tid, mid, manifest_hash, kind, gen, sup, source_rev, source_hash, decision, json.dumps(list(sinks)), json.dumps(manifest), op, T)

    def tables(self) -> list[str]:
        return [r[0] for r in self.rows("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
