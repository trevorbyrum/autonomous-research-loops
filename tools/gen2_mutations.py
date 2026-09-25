#!/usr/bin/env python3
"""Mutation harness for the gen-2 store DDL and its connection contract.

Each mutation below removes or weakens exactly one guard in memory (never on
disk), reruns every gen2/tests/test_store_*.py test against the mutated
schema, and checks that the guard's own tests catch it:

  KILLED    at least one test fails, and every test listed in `killers` is
            among the failures. A failure is an assertion failure, or an
            sqlite3.IntegrityError raised in a test body outside setUp (a
            write the test expects to succeed — its positive control — was
            refused, i.e. the mutant over-restricts);
  SURVIVED  no test fails — the guard is untested;
  INVALID   the mutation text was not found exactly once, the mutated DDL
            errored a test (setup broke rather than an assertion catching the
            mutant), or a listed killer did not fail.

Exit 0 only if the unmutated baseline passes and every mutation is KILLED.
The inventory is the reviewable claim: Astra's Gate C re-runs it
(`make gen2-mutation`) instead of trusting a count. A kill proves the named
tests notice the guard's absence; it does not prove the guard is the right
rule.

Trace: task 0a-repair ("every fix must be independently mutation-testable");
Astra 0a review, "Independent mutation record".
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
import traceback
import unittest
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "gen2" / "tests"


@dataclass(frozen=True)
class Mutation:
    mid: str
    finding: str
    description: str
    killers: tuple[str, ...]
    drop_trigger: str | None = None
    old: str | None = None
    new: str = ""
    target: str = "ddl"  # ddl | connection
    also: tuple[tuple[str, str], ...] = ()  # further (old, new) edits applied with this one (a dimension-level mutation)
    scope: str | None = None  # apply the edits only inside this trigger (CREATE TRIGGER <scope> ... END;)


H = "test_store_history."
D = "test_store_ddl."
FI = "test_store_ddl.FacetImportanceTest."
AD = "test_store_ddl.AdmissionAndLeaseTest."
IL = "test_store_ddl.InvocationLifecycleTest."
VT = "test_store_ddl.VerificationTest."

MUTATIONS: list[Mutation] = [
    # --- A1: history cannot be rewritten ------------------------------------
    Mutation("A1-recursive-triggers-off", "A1", "connection contract omits recursive_triggers (REPLACE skips delete guards)",
             (H + "ReplaceAndDeleteTest.test_replace_cannot_rewrite_a_receipt_on_any_key",
              H + "ConnectionContractTest.test_connection_contract_reads_back_on",
              D + "CommitFencingTest.test_operation_id_reuse_rejected_and_receipts_immutable"),
             target="connection", old="PRAGMA recursive_triggers = ON;\n"),
    Mutation("A1-receipt-delete-guard", "A1", "drop operation_receipts delete guard",
             (H + "ReplaceAndDeleteTest.test_replace_cannot_rewrite_a_receipt_on_any_key",
              D + "CommitFencingTest.test_operation_id_reuse_rejected_and_receipts_immutable",
              H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into"),
             drop_trigger="operation_receipts_immutable_d"),
    Mutation("A1-sink-generation-delete-guard", "A1", "drop sink_generations delete guard",
             (H + "ReplaceAndDeleteTest.test_sink_watermark_cannot_regress_by_delete_reinsert_or_replace",
              D + "PublicationTest.test_sink_generation_never_regresses"),
             drop_trigger="sink_generations_no_delete"),
    Mutation("A1-review-trigger-delete-guard", "A1", "drop review_triggers delete guard",
             (H + "ReplaceAndDeleteTest.test_handled_trigger_replayed_after_its_episode_closed_stays_handled",
              D + "OrdinalAndTriggerTest.test_trigger_identity_unique_and_handled_is_final"),
             drop_trigger="review_triggers_no_delete"),
    Mutation("A1-contract-delete-guard", "A1", "drop contract_revisions delete guard",
             (H + "ReplaceAndDeleteTest.test_update_or_replace_cannot_delete_the_approved_contract",
              D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted"),
             drop_trigger="contract_no_delete"),
    Mutation("A1-queue-delete-guard", "A1", "drop queue_entries delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="queue_entries_no_delete"),
    Mutation("A1-works-delete-guard", "A1", "drop works delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="works_no_delete"),
    Mutation("A1-record-work-links-delete-guard", "A1", "drop record_work_links delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="record_work_links_no_delete"),
    Mutation("A1-claim-source-links-delete-guard", "A1", "drop claim_source_links delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="claim_source_links_no_delete"),
    Mutation("A1-quote-checks-delete-guard", "A1", "drop quote_checks delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="quote_checks_no_delete"),
    Mutation("A1-delivery-receipts-delete-guard", "A1", "drop sink_delivery_receipts delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="sink_delivery_receipts_no_delete"),
    *(Mutation(f"A1-append-only-update-{trigger}", "A1", f"drop UPDATE guard {trigger}",
               (H + "EveryTableSweepTest.test_append_only_tables_reject_every_update",), drop_trigger=trigger)
      for trigger in ("artifacts_immutable_u", "audit_events_append_only_u", "claim_source_links_immutable_u",
                      "decision_receipts_immutable_u", "decision_specs_immutable_u", "dossiers_immutable_u",
                      "invocation_transitions_append_only_u", "obligations_immutable", "operation_receipts_immutable_u",
                      "operator_decisions_immutable_u", "outbox_events_immutable_u", "quote_checks_immutable_u",
                      "record_work_links_immutable_u", "research_ordinals_immutable_u", "retrieval_events_immutable_u",
                      "screening_assessments_immutable_u", "search_observations_immutable_u",
                      "sink_delivery_receipts_immutable_u", "verification_receipts_immutable_u")),
    # --- A2: decisions bound to their exact subject ---------------------------
    # Each gate is mutated per binding dimension (naming, kind, disposition,
    # topic, subject, currency, protocol); each dimension has a near-miss probe
    # that differs from a valid decision only there. Where the schema makes
    # conjuncts mutually determined (a contract's topic/revision/hash via its
    # unique hash and the decision-time existence check) they are mutated
    # together as one dimension.
    Mutation("A2-queue-created-at-intake", "A2", "topics may be inserted in any status",
             (D + "ContractGovernanceTest.test_terminal_statuses_cannot_be_inserted",), drop_trigger="queue_entries_created_at_intake"),
    Mutation("A2-status-change-advances-revision", "A2", "status may change without a commit",
             (D + "ContractGovernanceTest.test_status_change_is_a_commit",), drop_trigger="queue_status_change_advances_revision"),
    Mutation("A2-status-decision-iff-gated", "A2", "status_decision_id no longer tied to decision-gated statuses",
             (D + "ContractGovernanceTest.test_status_change_is_a_commit",),
             old="\n  CHECK ((status IN ('completed_with_qualified_conclusions', 'retired')) = (status_decision_id IS NOT NULL)),", new=""),
    Mutation("A2-completion-naming", "A2", "completion accepts any valid approval, not the one named",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="    WHERE d.decision_id = NEW.status_decision_id\n      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'completion_approval'", new="    WHERE d.topic_id = NEW.topic_id\n      AND d.kind = 'completion_approval'"),
    Mutation("A2-completion-kind", "A2", "completion gate ignores decision kind",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND d.kind = 'completion_approval'\n", new=""),
    Mutation("A2-completion-disposition", "A2", "completion gate ignores disposition",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND d.kind = 'completion_approval'\n      AND d.disposition = 'approved'\n", new="      AND d.kind = 'completion_approval'\n"),
    Mutation("A2-completion-topic", "A2", "completion gate binds the dossier to the decision's topic, not the transition's",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",),
             old="    JOIN dossiers x ON x.topic_id = NEW.topic_id AND x.dossier_revision = d.subject_revision AND x.content_hash = d.subject_hash",
             new="    JOIN dossiers x ON x.topic_id = d.topic_id AND x.dossier_revision = d.subject_revision AND x.content_hash = d.subject_hash",
             also=(("    WHERE d.decision_id = NEW.status_decision_id\n      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'completion_approval'", "    WHERE d.decision_id = NEW.status_decision_id\n      AND d.kind = 'completion_approval'"),)),
    Mutation("A2-completion-currency", "A2", "completion accepts an approval of a superseded dossier",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",),
             old="      AND x.dossier_revision = (SELECT max(y.dossier_revision) FROM dossiers y WHERE y.topic_id = NEW.topic_id)\n", new=""),
    Mutation("A2-completion-active-contract", "A2", "completion ignores which contract is active",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND x.contract_revision IS NEW.active_contract_revision\n", new=""),
    Mutation("A2-completion-contract-approved", "A2", "completion ignores whether the contract is approved",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",), old="      AND c.status = 'approved')\nBEGIN\n  SELECT RAISE(ABORT, 'completion requires", new=")\nBEGIN\n  SELECT RAISE(ABORT, 'completion requires"),
    Mutation("A2-retirement-naming", "A2", "retirement accepts any valid decision, not the one named",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="    WHERE d.decision_id = NEW.status_decision_id\n      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'retirement'", new="    WHERE d.topic_id = NEW.topic_id\n      AND d.kind = 'retirement'"),
    Mutation("A2-retirement-topic", "A2", "retirement ignores the decision's topic",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="      AND d.topic_id = NEW.topic_id\n      AND d.kind = 'retirement'", new="      AND d.kind = 'retirement'"),
    Mutation("A2-retirement-kind", "A2", "retirement ignores decision kind",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="      AND d.kind = 'retirement'\n", new=""),
    Mutation("A2-retirement-disposition", "A2", "retirement ignores disposition",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="      AND d.kind = 'retirement'\n      AND d.disposition = 'approved'\n", new="      AND d.kind = 'retirement'\n"),
    Mutation("A2-retirement-state-revision", "A2", "a retirement decision about an earlier state is accepted (stale/reuse)",
             (D + "ContractGovernanceTest.test_retirement_needs_operator_decision",), old="\n      AND d.subject_revision = OLD.state_revision)", new=")"),
    Mutation("A2-contract-created-as-draft", "A2", "contracts may be inserted approved",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",), drop_trigger="contract_created_as_draft"),
    Mutation("A2-contract-approval-naming", "A2", "contract approval accepts any valid approval, not the one named",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",), old="    WHERE d.decision_id = NEW.approved_by_decision_id\n", new="    WHERE 1\n"),
    Mutation("A2-contract-approval-kind", "A2", "contract approval ignores decision kind",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",), old="      AND d.kind IN ('contract_approval', 'amendment_approval', 'reframe_approval')\n", new=""),
    Mutation("A2-contract-approval-disposition", "A2", "contract approval ignores disposition",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="      AND d.kind IN ('contract_approval', 'amendment_approval', 'reframe_approval')\n      AND d.disposition = 'approved'\n", new="      AND d.kind IN ('contract_approval', 'amendment_approval', 'reframe_approval')\n"),
    Mutation("A2-contract-approval-subject", "A2", "contract approval ignores subject topic/revision/hash",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="      AND d.topic_id = NEW.topic_id\n      AND d.subject_revision = NEW.revision\n      AND d.subject_hash = NEW.content_hash)", new=")"),
    Mutation("A2-rating-naming", "A2", "an obligation rating accepts any valid rating decision, not the one named",
             (D + "ContractGovernanceTest.test_operator_rating_bound_to_a_rating_decision",), old="        WHERE d.decision_id = NEW.operator_rating_decision_id\n", new="        WHERE 1\n", scope="obligations_rating_bound_to_decision"),
    Mutation("A2-rating-kind", "A2", "rating binding ignores decision kind",
             (D + "ContractGovernanceTest.test_operator_rating_bound_to_a_rating_decision",), old="          AND d.kind = 'rating_approval' AND d.disposition = 'approved'\n", new="          AND d.disposition = 'approved'\n", scope="obligations_rating_bound_to_decision"),
    Mutation("A2-rating-disposition", "A2", "rating binding ignores disposition",
             (D + "ContractGovernanceTest.test_operator_rating_bound_to_a_rating_decision",), old="          AND d.kind = 'rating_approval' AND d.disposition = 'approved'\n", new="          AND d.kind = 'rating_approval'\n", scope="obligations_rating_bound_to_decision"),
    Mutation("A2-rating-topic", "A2", "rating binding ignores topic",
             (D + "ContractGovernanceTest.test_operator_rating_bound_to_a_rating_decision",), old="          AND d.topic_id = NEW.topic_id\n          AND d.subject_revision < NEW.contract_revision))", new="          AND d.subject_revision < NEW.contract_revision))", scope="obligations_rating_bound_to_decision"),
    Mutation("A2-rating-earlier-revision", "A2", "a rating decision may be about the revision that carries it",
             (D + "ContractGovernanceTest.test_operator_rating_bound_to_a_rating_decision",), old="          AND d.subject_revision < NEW.contract_revision))", new="          AND d.subject_revision <= NEW.contract_revision))", scope="obligations_rating_bound_to_decision"),
    Mutation("A2-proposal-receipt-class", "A2", "a Jev proposal may cite any decision class",
             (D + "ContractGovernanceTest.test_proposed_importance_cites_an_importance_receipt",), old="          AND r.topic_id = NEW.topic_id AND r.decision_class = 'importance_score'))", new="          AND r.topic_id = NEW.topic_id))", scope="obligations_rating_bound_to_decision"),
    Mutation("A2-proposal-receipt-topic", "A2", "a Jev proposal may cite another topic's receipt",
             (D + "ContractGovernanceTest.test_proposed_importance_cites_an_importance_receipt",), old="          AND r.topic_id = NEW.topic_id AND r.decision_class = 'importance_score'))", new="          AND r.decision_class = 'importance_score'))", scope="obligations_rating_bound_to_decision"),
    Mutation("A2-holds-created-open", "A2", "holds may be inserted cleared",
             (D + "HoldTest.test_holds_are_created_open",), drop_trigger="holds_created_open"),
    Mutation("A2-hold-clearance-naming", "A2", "a hold clears with any valid clearance, not the one named",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="    WHERE d.decision_id = NEW.cleared_by_decision_id\n", new="    WHERE 1\n"),
    Mutation("A2-hold-clearance-kind", "A2", "hold clearance ignores decision kind",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="      AND d.kind = 'hold_clearance' AND d.disposition = 'approved'\n      AND d.topic_id IS NEW.topic_id", new="      AND d.disposition = 'approved'\n      AND d.topic_id IS NEW.topic_id"),
    Mutation("A2-hold-clearance-disposition", "A2", "hold clearance ignores disposition",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="      AND d.kind = 'hold_clearance' AND d.disposition = 'approved'\n      AND d.topic_id IS NEW.topic_id", new="      AND d.kind = 'hold_clearance'\n      AND d.topic_id IS NEW.topic_id"),
    Mutation("A2-hold-clearance-subject", "A2", "hold clearance ignores which hold (and so topic) it is about",
             (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision",), old="      AND d.topic_id IS NEW.topic_id\n      AND d.subject_ref = NEW.hold_id)", new=")"),
    Mutation("A2-publication-naming", "A2", "publication accepts any valid approval, not the one named",
             (D + "PublicationTest.test_only_approved_work_is_published",), old="  WHERE d.decision_id = NEW.approval_decision_id\n", new="  WHERE 1\n"),
    Mutation("A2-publication-kind", "A2", "publication ignores decision kind (the review's rating-decision probe)",
             (D + "PublicationTest.test_only_approved_work_is_published",), old="    AND d.kind = 'publication_approval' AND d.disposition = 'approved'\n", new="    AND d.disposition = 'approved'\n"),
    Mutation("A2-publication-disposition", "A2", "publication ignores disposition",
             (D + "PublicationTest.test_only_approved_work_is_published",), old="    AND d.kind = 'publication_approval' AND d.disposition = 'approved'\n", new="    AND d.kind = 'publication_approval'\n"),
    Mutation("A2-publication-topic", "A2", "publication ignores the approval's topic",
             (D + "PublicationTest.test_only_approved_work_is_published",), old="    AND d.topic_id = NEW.topic_id\n    AND d.subject_revision = NEW.source_revision", new="    AND d.subject_revision = NEW.source_revision"),
    Mutation("A2-publication-revision", "A2", "publication ignores the approved source revision",
             (D + "PublicationTest.test_only_approved_work_is_published",), old="    AND d.subject_revision = NEW.source_revision\n", new=""),
    Mutation("A2-publication-hash", "A2", "publication ignores the approved source hash",
             (D + "PublicationTest.test_only_approved_work_is_published",), old="\n    AND d.subject_hash = NEW.source_content_hash)", new=")"),
    *(Mutation(f"A2-manifest-binds-{key}", "A2", f"manifest JSON no longer bound to its {key} column",
               (D + "PublicationTest.test_manifest_json_matches_its_columns",), old=f"\n     AND json_extract(manifest, '$.{path}') IS {col}", new="")
      for key, path, col in (("artifact-kind", "artifact_kind", "artifact_kind"), ("source-revision", "source.revision", "source_revision"),
                             ("source-hash", "source.content_hash", "source_content_hash"), ("approval-id", "approval.operator_decision_id", "approval_decision_id"),
                             ("approved-revision", "approval.approved_revision", "source_revision"), ("supersedes", "supersedes.generation", "supersedes_generation"))),
    Mutation("A2-manifest-binds-expected-sinks", "A2", "manifest JSON no longer bound to expected_sinks",
             (D + "PublicationTest.test_manifest_json_matches_its_columns",), old="\n     AND json_extract(manifest, '$.expected_sinks') IS json(expected_sinks))", new=")"),
    Mutation("A2-subject-exists-contract", "A2", "a contract decision may name a nonexistent revision/hash",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="WHEN (NEW.subject_kind = 'contract_revision' AND NOT EXISTS (\n        SELECT 1 FROM contract_revisions c\n        WHERE c.topic_id = NEW.topic_id AND c.revision = NEW.subject_revision AND c.content_hash = NEW.subject_hash))\n  OR ",
             new="WHEN "),
    Mutation("A2-subject-exists-dossier", "A2", "a completion decision may name a nonexistent dossier/hash",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier",),
             old="  OR (NEW.subject_kind = 'dossier' AND NOT EXISTS (\n        SELECT 1 FROM dossiers x\n        WHERE x.topic_id = NEW.topic_id AND x.dossier_revision = NEW.subject_revision AND x.content_hash = NEW.subject_hash))\n", new=""),
    Mutation("A2-subject-exists-hold", "A2", "a clearance may name a nonexistent or other-topic hold",
             (D + "HoldTest.test_decision_subject_must_exist_with_its_topic",),
             old="  OR (NEW.subject_kind = 'hold' AND NOT EXISTS (\n        SELECT 1 FROM holds k WHERE k.hold_id = NEW.subject_ref AND k.topic_id IS NEW.topic_id))\n", new=""),
    Mutation("A2-subject-exists-decision-receipt", "A2", "a blind/advised record may name a nonexistent receipt",
             (D + "HoldTest.test_decision_subject_must_exist_with_its_topic",),
             old="  OR (NEW.subject_kind = 'decision_receipt' AND NOT EXISTS (\n        SELECT 1 FROM decision_receipts r WHERE r.decision_receipt_id = NEW.subject_ref AND r.topic_id = NEW.topic_id))\n", new=""),
    *(Mutation(f"A2-decision-shape-{key}", "A2", f"operator_decisions CHECK removed: {key}",
               (D + "HoldTest.test_decision_subject_shape",), old=old, new="")
      for key, old in (
          ("kind-subject-map", "\n  CHECK ((kind = 'brief_confirmation' AND subject_kind = 'intake_brief')\n      OR (kind = 'scope_approval' AND subject_kind = 'scoping_report')\n      OR (kind IN ('rating_approval', 'contract_approval', 'amendment_approval', 'reframe_approval') AND subject_kind = 'contract_revision')\n      OR (kind = 'completion_approval' AND subject_kind = 'dossier')\n      OR (kind = 'retirement' AND subject_kind = 'topic')\n      OR (kind = 'hold_clearance' AND subject_kind = 'hold')\n      OR (kind = 'publication_approval' AND subject_kind = 'publication_source')\n      OR (kind IN ('blind_initial_disposition', 'advised_feedback') AND subject_kind = 'decision_receipt')),"),
          ("versioned-subject", "\n  CHECK (subject_kind NOT IN ('intake_brief', 'scoping_report', 'contract_revision', 'dossier', 'publication_source')\n      OR (subject_revision IS NOT NULL AND subject_hash IS NOT NULL)),"),
          ("ref-is-topic", "\n  CHECK (subject_kind NOT IN ('contract_revision', 'dossier', 'topic') OR subject_ref IS topic_id),"),
          ("topic-revision", "\n  CHECK (subject_kind != 'topic' OR subject_revision IS NOT NULL),"),
          ("topic-scoped", "\n  CHECK (subject_kind = 'hold' OR topic_id IS NOT NULL),"),
          ("recorded-only-blind", ",\n  CHECK ((kind IN ('blind_initial_disposition', 'advised_feedback')) = (disposition = 'recorded'))"))),
    # --- A3: facet importance is its own record; G-3 gates approval ------------
    Mutation("A3-facet-document-binding", "A3", "facet rows no longer equal their document entry",
             (FI + "test_facet_row_must_equal_its_document_entry",), scope="facets_bound_to_document_and_decision",
             old="WHEN NOT EXISTS (", new="WHEN 0 AND NOT EXISTS ("),
    Mutation("A3-facet-rating-naming", "A3", "facet rating accepts any valid rating decision", (FI + "test_facet_rating_bound_to_a_rating_decision",),
             scope="facets_bound_to_document_and_decision", old="        WHERE d.decision_id = NEW.operator_rating_decision_id\n", new="        WHERE 1\n"),
    Mutation("A3-facet-rating-kind", "A3", "facet rating ignores decision kind", (FI + "test_facet_rating_bound_to_a_rating_decision",),
             scope="facets_bound_to_document_and_decision", old="AND d.kind = 'rating_approval' AND d.disposition = 'approved'", new="AND d.disposition = 'approved'"),
    Mutation("A3-facet-rating-disposition", "A3", "facet rating ignores disposition", (FI + "test_facet_rating_bound_to_a_rating_decision",),
             scope="facets_bound_to_document_and_decision", old="AND d.kind = 'rating_approval' AND d.disposition = 'approved'", new="AND d.kind = 'rating_approval'"),
    Mutation("A3-facet-rating-topic", "A3", "facet rating ignores topic", (FI + "test_facet_rating_bound_to_a_rating_decision",),
             scope="facets_bound_to_document_and_decision", old="          AND d.topic_id = NEW.topic_id\n", new=""),
    Mutation("A3-facet-rating-earlier-revision", "A3", "facet rating may be about the revision carrying it", (FI + "test_facet_rating_bound_to_a_rating_decision",),
             scope="facets_bound_to_document_and_decision", old="d.subject_revision < NEW.contract_revision", new="d.subject_revision <= NEW.contract_revision"),
    Mutation("A3-facet-proposal-class", "A3", "facet proposal may cite any decision class", (FI + "test_facet_proposal_cites_an_importance_receipt",),
             scope="facets_bound_to_document_and_decision", old=" AND r.decision_class = 'importance_score'))", new="))"),
    Mutation("A3-facet-proposal-topic", "A3", "facet proposal may cite another topic's receipt", (FI + "test_facet_proposal_cites_an_importance_receipt",),
             scope="facets_bound_to_document_and_decision", old="          AND r.topic_id = NEW.topic_id AND r.decision_class", new="          AND r.decision_class"),
    Mutation("A3-facet-band-score", "A3", "facet band/score consistency CHECK removed", (FI + "test_facet_rating_bound_to_a_rating_decision",),
             old="  CHECK (operator_importance_score IS NULL\n      OR (operator_importance_band = 'critical' AND operator_importance_score BETWEEN 7 AND 9)\n      OR (operator_importance_band = 'important' AND operator_importance_score BETWEEN 4 AND 6)\n      OR (operator_importance_band = 'limited' AND operator_importance_score BETWEEN 1 AND 3))\n) STRICT;\n\n-- A2/A3: the same rating",
             new="  CHECK (1)\n) STRICT;\n\n-- A2/A3: the same rating"),
    Mutation("A3-obligation-document-binding", "A3", "obligation rows no longer equal their document entry", (FI + "test_obligation_row_equals_its_entry_and_tags_only_its_facets",),
             scope="obligations_bound_to_document_and_facets", old="WHEN NOT EXISTS (", new="WHEN 0 AND NOT EXISTS ("),
    Mutation("A3-obligation-facet-referential", "A3", "obligations may tag facets absent from their revision", (FI + "test_obligation_row_equals_its_entry_and_tags_only_its_facets",),
             scope="obligations_bound_to_document_and_facets", old="  OR EXISTS (\n       SELECT 1 FROM json_each(NEW.facet_ids) j", new="  OR 0 AND EXISTS (\n       SELECT 1 FROM json_each(NEW.facet_ids) j"),
    Mutation("A3-approval-obligation-rows-complete", "A3", "approval ignores missing obligation rows", (FI + "test_approval_needs_complete_rows_and_every_facet_rated",),
             scope="contract_approval_needs_rated_covered_facets", old="       IS NOT json_array_length(NEW.document, '$.obligations')", new="       IS NOT (SELECT count(*) FROM obligations o WHERE o.topic_id = NEW.topic_id AND o.contract_revision = NEW.revision)"),
    Mutation("A3-approval-facet-rows-complete", "A3", "approval ignores missing facet rows", (FI + "test_approval_needs_complete_rows_and_every_facet_rated",),
             scope="contract_approval_needs_rated_covered_facets", old="       IS NOT json_array_length(NEW.document, '$.facet_map.facets')", new="       IS NOT (SELECT count(*) FROM facets f WHERE f.topic_id = NEW.topic_id AND f.contract_revision = NEW.revision)"),
    Mutation("A3-approval-every-facet-rated", "A3", "approval allows unrated facets", (FI + "test_approval_needs_complete_rows_and_every_facet_rated",),
             scope="contract_approval_needs_rated_covered_facets", old="  OR EXISTS (SELECT 1 FROM facets f WHERE f.topic_id = NEW.topic_id AND f.contract_revision = NEW.revision AND f.operator_importance_band IS NULL)\n", new=""),
    Mutation("A3-approval-uncovered-critical", "A3", "approval ignores uncovered critical facets (G-3)", (FI + "test_critical_facet_with_zero_obligations_is_representable_and_blocks_approval",),
             scope="contract_approval_needs_rated_covered_facets", old="  OR EXISTS (SELECT 1 FROM uncovered_critical_facets u WHERE u.topic_id = NEW.topic_id AND u.contract_revision = NEW.revision))", new=")"),
    Mutation("A3-facets-delete-guard", "A3", "drop facets delete guard", (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="facets_no_delete"),
    Mutation("A3-facets-update-guard", "A3", "drop facets update guard", (H + "EveryTableSweepTest.test_append_only_tables_reject_every_update", FI + "test_facet_rating_bound_to_a_rating_decision"), drop_trigger="facets_immutable"),
    # --- A4 / R2.1 / R2.2: admission context, leases, parentage ------------------
    Mutation("R2.2-parent-only-for-delegates", "R2.2", "non-delegates (verifiers) may have a controlling parent",
             (VT + "test_verifier_must_be_separate_verification_invocation",), old="  CHECK ((kind = 'delegate') = (parent_invocation_id IS NOT NULL)),\n", new="  CHECK (kind != 'delegate' OR parent_invocation_id IS NOT NULL),\n"),
    Mutation("R2.2-blanket-requested-by-rule", "R2.2", "over-restriction: a verifier requested by the producer is refused (the rejected blanket rule)",
             (VT + "test_verifier_must_be_separate_verification_invocation",), scope="verification_receipts_role_separation",
             old="  OR (SELECT producer_invocation_id FROM claims", new="  OR (SELECT requested_by_invocation_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NEW.producer_invocation_id\n  OR (SELECT producer_invocation_id FROM claims"),
    Mutation("R2.1-delegate-has-no-lease", "R2.1", "delegates may hold their own lease",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), old="  CHECK ((kind = 'delegate') = (lease_id IS NULL)),\n", new="  CHECK (kind = 'delegate' OR lease_id IS NOT NULL),\n"),
    Mutation("R2.1-one-owner-per-lease", "R2.1", "two invocations may own one lease",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), old="CREATE UNIQUE INDEX invocations_one_owner_per_lease ON invocations (lease_id) WHERE lease_id IS NOT NULL;\n", new=""),
    Mutation("R2.1-lease-scope", "R2.1", "an invocation may own a lease of another scope",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), scope="invocations_lease_matches_kind",
             old="    AND l.scope = CASE NEW.kind", new="    AND 1 OR l.scope = CASE NEW.kind"),
    Mutation("R2.1-lease-topic", "R2.1", "an invocation may own another topic's lease",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), scope="invocations_lease_matches_kind",
             old="l.topic_id = NEW.topic_id AND ", new=""),
    Mutation("R2.1-lease-live", "R2.1", "an invocation may be admitted on a released lease",
             (AD + "test_invocation_owns_a_live_lease_of_its_kind_and_topic",), scope="invocations_lease_matches_kind",
             old=" AND l.released_at IS NULL", new=""),
    Mutation("R2.1-delegate-parent-topic", "R2.1", "a delegate may run under another topic's parent",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old=" AND p.topic_id = NEW.topic_id", new=""),
    Mutation("R2.1-delegate-parent-not-delegate", "R2.1", "delegate chains allowed",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old="    AND p.kind != 'delegate' AND p.state", new="    AND p.state"),
    Mutation("R2.1-delegate-parent-running", "R2.1", "a delegate may start under a parent that is not running",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old=" AND p.state IN ('launching', 'running')", new=""),
    Mutation("R2.1-delegate-inherits-pins", "R2.1", "a delegate may carry other admission pins than its parent",
             (IL + "test_delegate_inherits_a_running_parent_of_its_topic",), scope="invocations_delegate_inherits_parent",
             old="    AND p.admission_context IS NEW.admission_context AND p.contract_revision IS NEW.contract_revision\n", new=""),
    Mutation("R2.2-requested-by-same-topic", "R2.2", "a causal requester may be of another topic (or the invocation itself)",
             (VT + "test_requested_by_is_same_topic_and_never_self",), drop_trigger="invocations_requested_by_same_topic"),
    Mutation("A4-contract-admission-approved", "A4", "contract/1 admission accepts a draft revision",
             (AD + "test_contract_admission_needs_an_approved_revision",), scope="invocations_admission_context",
             old=" AND c.status = 'approved'))", new="))"),
    Mutation("A4-pre-contract-closes-on-approval", "A4", "pre-contract admission stays open after a contract is approved",
             (AD + "test_pre_contract_admission_closes_once_a_contract_is_approved",), scope="invocations_admission_context",
             old="        EXISTS (SELECT 1 FROM contract_revisions c WHERE c.topic_id = NEW.topic_id AND c.status != 'draft')\n     OR NOT EXISTS (", new="        NOT EXISTS ("),
    *(Mutation(f"A4-brief-confirmation-{key}", "A4", f"pre-contract admission ignores the brief confirmation's {key}",
               (AD + "test_pre_contract_admission_needs_the_confirmed_brief",), scope="invocations_admission_context", old=old, new=new)
      for key, old, new in (
          ("naming", "        WHERE d.decision_id = NEW.brief_confirmation_decision_id\n", "        WHERE 1\n"),
          ("kind", "          AND d.kind = 'brief_confirmation' AND d.disposition = 'approved'", "          AND d.disposition = 'approved'"),
          ("disposition", "          AND d.kind = 'brief_confirmation' AND d.disposition = 'approved'", "          AND d.kind = 'brief_confirmation'"),
          ("topic", "          AND d.topic_id = NEW.topic_id\n", ""),
          ("brief-id", "d.subject_ref = NEW.brief_ref AND ", ""),
          ("brief-version", " AND d.subject_revision = NEW.brief_version", ""),
          ("brief-hash", " AND d.subject_hash = NEW.brief_hash", ""))),
    Mutation("A4-pre-contract-kinds", "A4", "any kind may be admitted pre-contract",
             (AD + "test_pre_contract_admission_only_for_scoping_kinds",), old="  CHECK (admission_context = 'contract/1' OR kind IN ('discovery', 'delegate', 'research_pass')),\n", new=""),
    Mutation("A4-contract-pins-exclusive", "A4", "a pre-contract row may carry a contract revision",
             (AD + "test_admission_pins_are_exclusive",), old="  CHECK ((admission_context = 'contract/1') = (contract_revision IS NOT NULL)),\n  CHECK (CASE", new="  CHECK (CASE"),
    Mutation("A4-brief-pins-exclusive", "A4", "a contract row may carry brief pins",
             (AD + "test_admission_pins_are_exclusive",), old="           ELSE brief_ref IS NULL AND brief_version IS NULL AND brief_hash IS NULL AND brief_confirmation_decision_id IS NULL END),", new="           ELSE 1 END),"),
    *(Mutation(f"A4-receipt-pinned-{key}", "A4", f"a receipt may carry another {key} than its invocation",
               (AD + test,), scope="operation_receipts_admission_pinned", old=old, new="")
      for key, test, old in (
          ("contract-revision", "test_receipt_carries_the_invocations_admission_and_config", "    AND i.contract_revision IS NEW.contract_revision\n"),
          ("context", "test_receipt_carries_the_invocations_admission_and_config", "    AND i.admission_context IS NEW.admission_context\n"),
          ("brief", "test_pre_contract_receipt_carries_the_brief_pinned_at_admission", "    AND i.brief_hash IS NEW.brief_hash\n"),
          ("config", "test_receipt_carries_the_invocations_admission_and_config", "\n    AND i.config_bundle_hash IS NEW.config_bundle_hash"))),
    *(Mutation(f"A4-receipt-json-{key}", "A4", f"receipt JSON admission.{key} no longer bound",
               (AD + "test_receipt_json_admission_matches_its_columns",), old=old, new="")
      for key, old in (("context", "\n     AND json_extract(receipt, '$.admission.context') IS admission_context"),
                       ("contract", "\n     AND json_extract(receipt, '$.admission.contract.revision') IS contract_revision"),
                       ("brief", "\n     AND json_extract(receipt, '$.admission.brief.content_hash') IS brief_hash"))),
    Mutation("A4-ordinal-needs-contract", "A4", "a pre-contract research pass may earn an ordinal",
             (AD + "test_pre_contract_research_pass_earns_no_ordinal",), old="  OR (SELECT admission_context FROM operation_receipts WHERE operation_id = NEW.operation_id) IS NOT 'contract/1'\n", new=""),
    # --- A9: capability supersession --------------------------------------
    Mutation("A9-successor-fk-immediate", "A9", "successor FK checked immediately (the documented transaction cannot run)",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",),
             old="REFERENCES capability_facts (fact_id) DEFERRABLE INITIALLY DEFERRED", new="REFERENCES capability_facts (fact_id)"),
    Mutation("A9-self-supersession", "A9", "drop the no-self-supersession CHECK",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",),
             old=",\n  CHECK (superseded_by_fact_id IS NOT fact_id)\n) STRICT;", new="\n) STRICT;"),
    Mutation("A9-insert-current-same-capability", "A9", "drop the insert-current/same-capability trigger",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",), drop_trigger="capability_facts_insert_current_same_capability"),
    Mutation("A9-link-successor", "A9", "drop the successor-link trigger (cross-capability, cyclic)",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",), drop_trigger="capability_facts_link_successor"),
    Mutation("A9-fact-provenance-pins", "A9", "capability fact recorded_at/observer no longer pinned",
             (D + "ObservationTest.test_one_current_capability_fact_supersede_to_transition",),
             old="\n  OR NEW.observed_by_invocation_id IS NOT OLD.observed_by_invocation_id OR NEW.recorded_at IS NOT OLD.recorded_at", new=""),
    Mutation("A1-contract-created-at-pin", "A1", "contract created_at no longer pinned",
             (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",),
             old="  OR NEW.created_at IS NOT OLD.created_at\n  OR (OLD.approved_by_decision_id IS NOT NULL",
             new="  OR (OLD.approved_by_decision_id IS NOT NULL"),
]


class _Collector(unittest.TestResult):
    def __init__(self) -> None:
        super().__init__()
        self.failed: set[str] = set()
        self.errored: dict[str, str] = {}

    def addFailure(self, test, err) -> None:  # noqa: N802 (unittest API)
        self.failed.add(test.id())

    def _record_error(self, test, err) -> None:
        in_setup = any(frame.name in ("setUp", "setUpClass") for frame in traceback.extract_tb(err[2]))
        if issubclass(err[0], sqlite3.IntegrityError) and not in_setup:
            self.failed.add(test.id())
        else:
            self.errored[test.id()] = self._exc_info_to_string(err, test).strip().splitlines()[-1]

    def addError(self, test, err) -> None:  # noqa: N802
        self._record_error(test, err)

    def addSubTest(self, test, subtest, err) -> None:  # noqa: N802
        if err is None:
            return
        if issubclass(err[0], test.failureException):
            self.failed.add(test.id())
        else:
            self._record_error(test, err)


def mutate(text: str, m: Mutation) -> str:
    if m.drop_trigger:
        pattern = re.compile(r"CREATE TRIGGER " + re.escape(m.drop_trigger) + r"\b.*?\nEND;\n", re.DOTALL)
        found = pattern.findall(text)
        if len(found) != 1:
            raise ValueError(f"trigger {m.drop_trigger!r} found {len(found)} times")
        return pattern.sub("", text)
    assert m.old is not None
    prefix, body, suffix = "", text, ""
    if m.scope:
        block = re.compile(r"CREATE TRIGGER " + re.escape(m.scope) + r"\b.*?\nEND;\n", re.DOTALL)
        found = list(block.finditer(text))
        if len(found) != 1:
            raise ValueError(f"scope trigger {m.scope!r} found {len(found)} times")
        prefix, body, suffix = text[: found[0].start()], found[0].group(0), text[found[0].end():]
    for old, new in ((m.old, m.new), *m.also):
        if body.count(old) != 1:
            raise ValueError(f"mutation text found {body.count(old)} times: {old[:60]!r}")
        body = body.replace(old, new)
    return prefix + body + suffix


def load_suite() -> unittest.TestSuite:
    return unittest.defaultTestLoader.discover(str(TESTS), pattern="test_store_*.py")


def run(fx, ddl: str, connection: str) -> _Collector:
    fx.DDL_TEXT, fx.CONNECTION_TEXT = ddl, connection
    result = _Collector()
    load_suite().run(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run only mutations whose id starts with this prefix")
    parser.add_argument("--list", action="store_true", help="print the inventory and exit")
    args = parser.parse_args(argv)
    if args.list:
        for m in MUTATIONS:
            print(f"{m.mid:45} {m.finding:6} {m.description}")
        return 0
    sys.path[:0] = [str(TESTS), str(ROOT)]
    import gen2.tests.store_fixtures as fx  # noqa: E402 (path set above)

    ddl0, conn0 = fx.DDL_TEXT, fx.CONNECTION_TEXT
    started = time.monotonic()
    base = run(fx, ddl0, conn0)
    if base.failed or base.errored or not base.testsRun:
        print(f"BASELINE NOT GREEN: failed={sorted(base.failed)} errored={base.errored}", file=sys.stderr)
        return 1
    selected = [m for m in MUTATIONS if not args.only or m.mid.startswith(args.only)]
    ids = [m.mid for m in MUTATIONS]
    if len(set(ids)) != len(ids):
        print("duplicate mutation ids", file=sys.stderr)
        return 1
    bad = 0
    for m in selected:
        try:
            ddl = mutate(ddl0, m) if m.target == "ddl" else ddl0
            conn = mutate(conn0, m) if m.target == "connection" else conn0
        except ValueError as exc:
            print(f"INVALID   {m.mid}: {exc}")
            bad += 1
            continue
        res = run(fx, ddl, conn)
        missing = [k for k in m.killers if not any(f == k or f.endswith("." + k) for f in res.failed)]
        if res.errored:
            verdict = f"INVALID   {m.mid}: {len(res.errored)} test error(s), e.g. {next(iter(res.errored.items()))}"
        elif not res.failed:
            verdict = f"SURVIVED  {m.mid}: {m.description}"
        elif missing:
            verdict = f"INVALID   {m.mid}: listed killer(s) did not fail: {missing}"
        else:
            verdict = f"KILLED    {m.mid} by {len(res.failed)} test(s)"
        if not verdict.startswith("KILLED"):
            bad += 1
        print(verdict)
    fx.DDL_TEXT, fx.CONNECTION_TEXT = ddl0, conn0
    print(f"gen2 mutation run: {len(selected) - bad}/{len(selected)} killed, baseline {base.testsRun} tests green, {time.monotonic() - started:.1f}s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
