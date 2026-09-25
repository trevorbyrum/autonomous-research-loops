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
  INVALID   the mutation text was not found exactly once, a listed killer
            did not fail, or tests errored (setup broke rather than an
            assertion catching the mutant) while some listed killer did not
            fail in its own body. Setup errors elsewhere are reported but
            tolerated when every listed killer failed in its body: an
            over-restricting mutant can also break a shared fixture.

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
import multiprocessing
import os
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
    target: str = "ddl"  # ddl | connection | a repo-relative file in FILE_TARGETS
    also: tuple[tuple[str, str], ...] = ()  # further (old, new) edits applied with this one (a dimension-level mutation)
    scope: str | None = None  # apply the edits only inside this trigger or table (CREATE TRIGGER <scope> ... END; / CREATE TABLE <scope> ... STRICT;)


# File targets: how the named tests are pointed at a mutated copy. ("attr",
# module, name): the file is written to a temp dir and module.name is set to
# its path (tests that run tools as subprocesses or read config files);
# ("module", dotted): the mutated source is loaded as that module and the
# killer test modules are reloaded so their imports rebind to it.
FILE_TARGETS = {
    "tools/check_boundaries.py": ("attr", "test_check_boundaries", "CHECKER"),
    "gen2/boundaries.toml": ("attr", "test_check_boundaries", "REAL_BOUNDARIES"),
    "tools/check_gen2_schemas.py": ("attr", "test_check_ddl_rules", "CHECKER"),
    "gen2/core/instants.py": ("module", "gen2.core.instants"),
    "gen2/core/canonical.py": ("module", "gen2.core.canonical"),
}

H = "test_store_history."
D = "test_store_ddl."
FI = "test_store_ddl.FacetImportanceTest."
AD = "test_store_ddl.AdmissionAndLeaseTest."
IL = "test_store_ddl.InvocationLifecycleTest."
VT = "test_store_ddl.VerificationTest."
LT = "test_store_ddl.InvocationLifecycleTest."
DC = "test_store_ddl.DecisionReceiptConsistencyTest."
SD = "test_store_ddl.ScreeningAndDecisionTest."
OB = "test_store_ddl.ObservationTest."
VO = "test_store_ddl.DraftVocabularyTransitionTest."
CB = "test_check_boundaries.BoundaryCheckerTest."
DR = "test_check_ddl_rules.DdlRuleTest."
IN = "test_instants.UtcInstantTest."
CN = "test_canonical."
RI = "test_store_history.RecordIdentityTest."

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
    # --- A5: lifecycle pins, launch handle, reconciliation; D06 matrix ------------
    Mutation("A5-D06-reopen-committed-cancelled", "A5", "the review's surviving mutant: committed/cancelled may return to running",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="  OR (OLD.state = 'outcome_unknown' AND NEW.state IN (", new="  OR (OLD.state IN ('committed', 'cancelled') AND NEW.state = 'running')\n  OR (OLD.state = 'outcome_unknown' AND NEW.state IN ("),
    Mutation("A5-D06-unknown-back-to-launching", "A5", "outcome_unknown may return to launching",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="NEW.state IN ('running', 'result_ready', 'committed', 'failed', 'cancelled')))", new="NEW.state IN ('launching', 'running', 'result_ready', 'committed', 'failed', 'cancelled')))"),
    Mutation("A5-D06-skip-admitted-to-running", "A5", "admitted may skip straight to running",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="(OLD.state = 'admitted' AND NEW.state IN ('launching', 'cancelled'))", new="(OLD.state = 'admitted' AND NEW.state IN ('launching', 'running', 'cancelled'))"),
    Mutation("A5-D06-drop-result-ready-to-committed", "A5", "over-restriction: result_ready may no longer commit",
             (LT + "test_terminal_states_are_final",), scope="invocations_allowed_transitions",
             old="(OLD.state = 'result_ready' AND NEW.state IN ('committed', 'failed', 'outcome_unknown'))", new="(OLD.state = 'result_ready' AND NEW.state IN ('failed', 'outcome_unknown'))"),
    Mutation("A5-launch-intent-carries-handle", "A5", "launch intent may be recorded without the stable job handle",
             (LT + "test_launching_requires_launch_intent",), old="  CHECK (launch_intent_at IS NULL OR job_handle IS NOT NULL),\n", new=""),
    *(Mutation(f"A5-pin-{key}", "A5", f"invocation {key} no longer write-once",
               (LT + "test_process_identity_is_write_once",), scope="invocations_identity_immutable", old=old, new="")
      for key, old in (("host", "\n  OR (OLD.host_id IS NOT NULL AND NEW.host_id IS NOT OLD.host_id)"),
                       ("container", "\n  OR (OLD.container_id IS NOT NULL AND NEW.container_id IS NOT OLD.container_id)"),
                       ("admitted-at", "\n  OR NEW.admitted_at IS NOT OLD.admitted_at"),
                       ("requested-by", "\n  OR NEW.requested_by_invocation_id IS NOT OLD.requested_by_invocation_id"),
                       ("admission-context", "\n  OR NEW.admission_context IS NOT OLD.admission_context"),
                       ("contract-revision", "\n  OR NEW.contract_revision IS NOT OLD.contract_revision"),
                       ("brief-pins", "\n  OR NEW.brief_ref IS NOT OLD.brief_ref OR NEW.brief_version IS NOT OLD.brief_version"),
                       ("brief-hash-decision", "\n  OR NEW.brief_hash IS NOT OLD.brief_hash OR NEW.brief_confirmation_decision_id IS NOT OLD.brief_confirmation_decision_id"),
                       ("config", "\n  OR NEW.config_bundle_hash IS NOT OLD.config_bundle_hash"),
                       ("result-digest", "\n  OR (OLD.result_payload_digest IS NOT NULL AND NEW.result_payload_digest IS NOT OLD.result_payload_digest)"))),
    Mutation("A5-unknown-needs-reconciliation", "A5", "outcome_unknown may be left with a timestamp and a digest (the review's probe)",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), drop_trigger="invocations_unknown_needs_reconciliation"),
    Mutation("A5-reconciliation-episode", "A5", "an earlier episode's reconciliation may be reused",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocations_unknown_needs_reconciliation", old=" AND r.unknown_since = OLD.outcome_unknown_since", new=""),
    Mutation("A5-reconciliation-running-branch", "A5", "over-restriction: found_running no longer supports running",
             (LT + "test_terminal_states_are_final",), scope="invocations_unknown_needs_reconciliation", old="(NEW.state = 'running' AND r.resolution = 'found_running')", new="(0)"),
    Mutation("A5-reconciliation-result-digest", "A5", "result_ready accepted with another digest than the one found",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocations_unknown_needs_reconciliation", old=" AND r.result_payload_digest = NEW.result_payload_digest)", new=")"),
    Mutation("A5-reconciliation-committed-receipt", "A5", "found_committed accepted without a final receipt",
             (LT + "test_found_committed_needs_the_final_receipt",), scope="invocations_unknown_needs_reconciliation",
             old="\n            AND EXISTS (SELECT 1 FROM operation_receipts o WHERE o.invocation_id = NEW.invocation_id AND o.operation_kind = 'final_outcome'))", new=")"),
    Mutation("A5-reconciliation-failed-resolution", "A5", "failed accepted with any resolution",
             (LT + "test_reconciliation_resolutions_and_evidence",), scope="invocations_unknown_needs_reconciliation", old="(NEW.state = 'failed' AND r.resolution IN ('confirmed_failed', 'terminated_group'))", new="(NEW.state = 'failed')"),
    Mutation("A5-reconciliation-cancelled-resolution", "A5", "cancelled accepted with any resolution",
             (LT + "test_reconciliation_resolutions_and_evidence",), scope="invocations_unknown_needs_reconciliation", old="(NEW.state = 'cancelled' AND r.resolution = 'terminated_group')", new="(NEW.state = 'cancelled')"),
    Mutation("A5-reconciliation-current-episode", "A5", "a reconciliation may be recorded for a past episode or a known state",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), drop_trigger="invocation_reconciliations_for_current_episode"),
    Mutation("A5-reconciliation-digest-iff-found-result", "A5", "digest no longer tied to found_result",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped", LT + "test_reconciliation_resolutions_and_evidence"),
             old="  CHECK ((resolution = 'found_result') = (result_payload_digest IS NOT NULL)),\n", new=""),
    Mutation("A5-reconciliation-descendants", "A5", "terminal resolutions without descendant confirmation",
             (LT + "test_reconciliation_resolutions_and_evidence",), old="  CHECK (resolution NOT IN ('confirmed_failed', 'terminated_group') OR descendants_confirmed_at IS NOT NULL),\n", new=""),
    Mutation("A5-reconciliation-termination-method", "A5", "termination method no longer tied to terminated_group",
             (LT + "test_reconciliation_resolutions_and_evidence",), old=",\n  CHECK ((resolution = 'terminated_group') = (method = 'execution_group_termination'))", new=""),
    Mutation("A5-reconciliation-update-guard", "A5", "reconciliation records may be edited",
             (LT + "test_reconciliation_resolutions_and_evidence", H + "EveryTableSweepTest.test_append_only_tables_reject_every_update"), drop_trigger="invocation_reconciliations_immutable_u"),
    Mutation("A5-reconciliation-delete-guard", "A5", "reconciliation records may be deleted",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="invocation_reconciliations_no_delete"),
    # --- A6 / A10: verification support integrity and receipt binding -------------
    Mutation("A6-D32-byte-mismatch", "A6", "the review's surviving mutant: a byte mismatch need not quarantine the quote",
             (VT + "test_nli_alarm_quarantines_the_quote",), old=",\n  CHECK (exact_match != 'mismatch' OR quote_quarantined = 1)", new=""),
    Mutation("A6-verifier-extraction-is-own", "A6", "a producer's extraction may be passed off as the verifier's own",
             (VT + "test_producer_unvalidated_extraction_rejected",), old="  CHECK (extraction_method != 'verifier_extraction' OR extraction_invocation_id = verifier_invocation_id),\n", new=""),
    Mutation("A6-validated-extraction-cites-validation", "A6", "a 'validated' extraction need not cite its validation",
             (VT + "test_producer_unvalidated_extraction_rejected",), old="  CHECK (extraction_method != 'validated_extraction' OR extraction_validation_ref IS NOT NULL),\n", new=""),
    Mutation("A6-canonical-bytes-authenticated", "A6", "canonical bytes need no authenticated acquisition",
             (VT + "test_producer_unvalidated_extraction_rejected",), old="  CHECK (extraction_method != 'canonical_bytes' OR json_extract(acquisition, '$.gateway_call_ref') IS NOT NULL),\n", new=""),
    Mutation("A6-canonical-bytes-staged", "A6", "canonical bytes need not be a staged artifact with the obtained hash",
             (VT + "test_producer_unvalidated_extraction_rejected",), scope="verification_receipts_bindings",
             old="  OR (NEW.extraction_method = 'canonical_bytes' AND NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.content_hash = NEW.obtained_content_hash))\n", new=""),
    Mutation("A6-D28-old-over-restriction", "A6", "over-restriction restored: producer-acquired canonical bytes refused (the review's D28 finding)",
             (VT + "test_producer_unvalidated_extraction_rejected",),
             old="  CHECK (extraction_method != 'verifier_extraction' OR extraction_invocation_id = verifier_invocation_id),\n",
             new="  CHECK (extraction_method != 'verifier_extraction' OR extraction_invocation_id = verifier_invocation_id),\n  CHECK (extraction_invocation_id != producer_invocation_id OR extraction_validation_ref IS NOT NULL),\n"),
    Mutation("A6-quote-check-iff-status", "A6", "a matched/mismatched quote need not name its quote check",
             (VT + "test_quote_check_binding",), old="  CHECK ((coalesce(json_extract(receipt, '$.checks.exact_quote.status'), 'missing') IN ('matched', 'mismatch')) = (quote_check_id IS NOT NULL)),\n", new=""),
    *(Mutation(f"A6-support-needs-{name.replace('_', '-')}", "A6", f"'supports' accepted with an adverse/unperformed {name} check",
               (VT + "test_support_needs_successful_checks_or_adjudication",), scope="verification_receipts",
               old=f"coalesce(json_extract(receipt, '$.checks.{name}'), 'missing') IN ('checked_ok', 'not_applicable')", new="1")
      for name in ("numeric_units", "denominators", "negation", "qualifications")),
    Mutation("A6-support-needs-no-tier0-alarm", "A6", "'supports' accepted over an unadjudicated tier-0 alarm",
             (VT + "test_support_needs_successful_checks_or_adjudication",), old="\n     AND json_extract(receipt, '$.checks.tier0.signal') IS NOT 'alarm'))", new="))"),
    Mutation("A6-support-adjudication-escape", "A6", "over-restriction: an explicit adjudication no longer resolves an adverse check",
             (VT + "test_support_needs_successful_checks_or_adjudication",), old="  CHECK (verdict != 'supports' OR json_type(receipt, '$.adjudication') IS 'object' OR (", new="  CHECK (verdict != 'supports' OR ("),
    Mutation("A6-load-bearing-support-checks-performed", "A6", "a load-bearing partial support may skip its checks",
             (VT + "test_truthful_unsuccessful_verdicts_may_record_unperformed_checks",), old="  CHECK (use != 'load_bearing' OR verdict NOT IN ('supports', 'partially_supports') OR (", new="  CHECK (1 OR ("),
    Mutation("A6-truthful-cannot-assess-over-restriction", "A6", "over-restriction restored: load-bearing checks required for every verdict (the review's rejected truthful receipt)",
             (VT + "test_truthful_unsuccessful_verdicts_may_record_unperformed_checks",), old="  CHECK (use != 'load_bearing' OR verdict NOT IN ('supports', 'partially_supports') OR (", new="  CHECK (use != 'load_bearing' OR ("),
    Mutation("A6-binds-verifier-capability", "A10", "the receipt may name another invocation's capability",
             (VT + "test_receipt_names_the_verifiers_own_capability",), scope="verification_receipts_bindings",
             old="WHEN (SELECT capability_id FROM invocations WHERE invocation_id = NEW.verifier_invocation_id) IS NOT json_extract(NEW.receipt, '$.verifier_capability_id')\n  OR ", new="WHEN "),
    *(Mutation(f"A6-quote-binding-{key}", "A6", f"a bound quote check may differ in {key}", (VT + "test_quote_check_binding",), scope="verification_receipts_bindings", old=old, new=new)
      for key, old, new in (
          ("claim", "          AND q.claim_id = NEW.claim_id AND q.claim_revision = NEW.claim_revision\n", ""),
          ("source", "          AND q.source_artifact_hash IS json_extract(NEW.receipt, '$.checks.exact_quote.source_artifact_hash')\n", ""),
          ("status", "          AND q.exact_match IS json_extract(NEW.receipt, '$.checks.exact_quote.status')\n", ""),
          ("quarantine", "          AND (NEW.verdict != 'supports' OR q.quote_quarantined = 0\n               OR (q.exact_match = 'matched' AND q.nli_signal = 'alarm' AND json_type(NEW.receipt, '$.adjudication') IS 'object'))))", "))"),
          ("adjudication-escape", "\n               OR (q.exact_match = 'matched' AND q.nli_signal = 'alarm' AND json_type(NEW.receipt, '$.adjudication') IS 'object'))))", ")))"))),
    *(Mutation(f"A10-verification-json-{path.replace('.', '-').replace('_', '-')}", "A10", f"verification receipt column {col} no longer bound to $.{path}",
               (VT + "test_receipt_row_matches_its_json",), scope="verification_receipts", old=f"\n     AND json_extract(receipt, '$.{path}') IS {col}", new="")
      for path, col in (("topic_id", "topic_id"), ("claim.claim_id", "claim_id"), ("claim.claim_revision", "claim_revision"), ("source.work_id", "work_id"),
                        ("source.source_version", "source_version"), ("cited_spans", "json(cited_spans)"), ("obtained_content_hash", "obtained_content_hash"),
                        ("access_tier", "access_tier"), ("requested_for.use", "use"), ("requested_for.required_access_tier", "required_access_tier"),
                        ("acquisition", "json(acquisition)"), ("extraction.method", "extraction_method"), ("extraction.produced_by_invocation_id", "extraction_invocation_id"),
                        ("extraction.validation_ref", "extraction_validation_ref"), ("producer_invocation_id", "producer_invocation_id"),
                        ("verifier_invocation_id", "verifier_invocation_id"), ("quote_check_id", "quote_check_id"))),
    Mutation("A10-verification-json-verdict", "A10", "verification verdict column no longer bound to the receipt JSON (the review's contradiction probe)",
             (VT + "test_receipt_row_matches_its_json",), scope="verification_receipts", old="\n     AND json_extract(receipt, '$.verdict') IS verdict),", new="),"),
    Mutation("A10-verification-json-receipt-id", "A10", "verification receipt id no longer bound to the JSON",
             (VT + "test_receipt_row_matches_its_json",), scope="verification_receipts", old="  CHECK (json_extract(receipt, '$.verification_receipt_id') IS verification_receipt_id\n     AND ", new="  CHECK ("),
    # --- A7 / A10: decision spec and receipt consistency; screening/observation binding ---
    Mutation("A7-spec-provider-primitive", "A7", "a fallback spec may answer with a Jev primitive",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK ((provider = 'jev' AND primitive IN ('noul', 'choice', 'score')) OR (provider = 'llm_fallback' AND primitive = 'label')),\n", new=""),
    Mutation("A7-spec-options-object", "A7", "spec options may be a list (duplicate ids possible)",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK (json_type(document, '$.options') IS 'object'),\n", new=""),
    Mutation("A7-spec-at-least-two-options", "A7", "a spec may offer one option",
             (DC + "test_spec_shape_by_class_and_provider",), scope="decision_specs_option_count", old="WHEN (SELECT count(*) FROM json_each(NEW.document, '$.options')) < 2\n  OR ", new="WHEN "),
    Mutation("A7-spec-noul-two-options", "A7", "a Noul may offer other than two options",
             (DC + "test_spec_shape_by_class_and_provider",), scope="decision_specs_option_count", old="\n  OR (NEW.primitive = 'noul' AND (SELECT count(*) FROM json_each(NEW.document, '$.options')) != 2)", new=""),
    Mutation("A7-spec-screening-protocol", "A7", "a screening spec may have no eligibility protocol (the review's probe)",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK (decision_class != 'screening' OR json_type(document, '$.protocol.eligibility_protocol_version') IS 'integer'),\n", new=""),
    Mutation("NULL-spec-screening-protocol", "A7", "NULL-CHECK regression: '=' instead of IS lets an absent protocol pass",
             (DC + "test_spec_shape_by_class_and_provider",), old="json_type(document, '$.protocol.eligibility_protocol_version') IS 'integer'", new="json_type(document, '$.protocol.eligibility_protocol_version') = 'integer'"),
    Mutation("NULL-support-adjudication", "A6", "NULL-CHECK regression: '=' instead of IS lets an absent adjudication key pass an adverse check",
             (VT + "test_absent_keys_are_not_passes",), old="  CHECK (verdict != 'supports' OR json_type(receipt, '$.adjudication') IS 'object' OR (", new="  CHECK (verdict != 'supports' OR json_type(receipt, '$.adjudication') = 'object' OR ("),
    Mutation("NULL-support-quote-status", "A6", "NULL-CHECK regression: an absent exact-quote status passes",
             (VT + "test_absent_keys_are_not_passes",), old="  CHECK (verdict != 'supports' OR coalesce(json_extract(receipt, '$.checks.exact_quote.status'), 'missing') IN ('matched', 'not_applicable')),",
             new="  CHECK (verdict != 'supports' OR json_extract(receipt, '$.checks.exact_quote.status') IN ('matched', 'not_applicable')),"),
    Mutation("A7-spec-method-protocol", "A7", "a method_selection spec may have no contract protocol",
             (DC + "test_spec_shape_by_class_and_provider",), old="  CHECK (decision_class != 'method_selection' OR json_type(document, '$.protocol') IS 'object'),\n", new=""),
    *(Mutation(f"A7-spec-json-{key}", "A7", f"spec {key} column no longer bound to its document",
               (DC + "test_spec_shape_by_class_and_provider",), scope="decision_specs", old=old, new="")
      for key, old in (("primitive", "\n     AND json_extract(document, '$.primitive') IS primitive"),
                       ("policy-id", "\n     AND json_extract(document, '$.action_policy.policy_id') IS policy_id"),
                       ("policy-version", "\n     AND json_extract(document, '$.action_policy.version') IS policy_version"),
                       ("protocol-topic", "\n     AND json_extract(document, '$.protocol.topic_id') IS protocol_topic_id"))),
    Mutation("A7-shadow-no-commit", "A7", "a shadow receipt may carry a committed operation (the review's probe)",
             (DC + "test_action_fixes_the_outcome_shape",), old="  CHECK ((action = 'commit_reversible_action') = (commit_operation_id IS NOT NULL)),\n", new="  CHECK (action != 'commit_reversible_action' OR commit_operation_id IS NOT NULL),\n"),
    Mutation("A7-proposal-iff-attach", "A7", "proposal ref no longer tied to attach_proposal",
             (DC + "test_action_fixes_the_outcome_shape",), old="  CHECK ((action = 'attach_proposal') = (proposal_ref IS NOT NULL)),\n", new=""),
    Mutation("A7-hold-only-for-hold-actions", "A7", "a hold may be named by shadow/commit/proposal actions",
             (DC + "test_action_fixes_the_outcome_shape",), old="  CHECK (action NOT IN ('shadow_log_only', 'commit_reversible_action', 'attach_proposal') OR hold_id IS NULL),\n", new=""),
    Mutation("A7-abstention-keeps-raw", "A7", "an abstention may discard the raw response (the review's probe)",
             (DC + "test_abstention_retains_the_raw_response",), old="  CHECK (response_status NOT IN ('answered', 'abstained') OR raw_response_digest IS NOT NULL),\n", new="  CHECK (response_status != 'answered' OR raw_response_digest IS NOT NULL),\n"),
    Mutation("A7-raw-is-retained-artifact", "A7", "the raw digest need not be a retained artifact",
             (DC + "test_abstention_retains_the_raw_response",), old="  raw_response_digest TEXT REFERENCES artifacts (content_hash),", new="  raw_response_digest TEXT,"),
    *(Mutation(f"A7-match-spec-{key}", "A7", f"receipt may differ from its spec in {key}", (DC + "test_receipt_matches_its_spec",), scope="decision_receipts_match_spec", old=old, new="")
      for key, old in (
          ("primitive", "  OR (NEW.answer IS NOT NULL AND (SELECT primitive FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT json_extract(NEW.answer, '$.primitive'))\n"),
          ("policy-id", "  OR (SELECT policy_id FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.policy_id\n"),
          ("policy-version", "  OR (SELECT policy_version FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT NEW.policy_version\n"),
          ("protocol-topic", "  OR coalesce((SELECT protocol_topic_id FROM decision_specs WHERE spec_hash = NEW.spec_hash), NEW.topic_id) IS NOT NEW.topic_id\n"),
          ("selected-option", "  OR (json_extract(NEW.answer, '$.selected_option_id') IS NOT NULL AND NOT EXISTS (\n        SELECT 1 FROM decision_specs sp, json_each(sp.document, '$.options') o\n        WHERE sp.spec_hash = NEW.spec_hash AND o.key = json_extract(NEW.answer, '$.selected_option_id')))\n"),
          ("distribution", "\n  OR EXISTS (\n        SELECT 1 FROM json_each(NEW.answer, '$.distribution') d\n        WHERE NOT EXISTS (SELECT 1 FROM decision_specs sp, json_each(sp.document, '$.options') o WHERE sp.spec_hash = NEW.spec_hash AND o.key = d.key))"))),
    *(Mutation(f"A10-decision-json-{path.replace('.', '-').replace('_', '-')}", "A10", f"decision receipt {col} no longer bound to $.{path}",
               (DC + "test_receipt_row_matches_its_json",), scope="decision_receipts", old=f"\n     AND json_extract(receipt, '$.{path}') IS {col}", new="")
      for path, col in (("invocation_id", "invocation_id"), ("topic_id", "topic_id"), ("spec.spec_hash", "spec_hash"), ("decision_class", "decision_class"),
                        ("provider", "provider"), ("subject.kind", "subject_kind"), ("subject.ref", "subject_ref"), ("input_manifest.input_status", "input_status"),
                        ("provider_response.status", "response_status"), ("provider_response.raw_response_digest", "raw_response_digest"),
                        ("provider_response.raw_response_artifact.content_hash", "raw_response_digest"), ("provider_response.answer", "json(answer)"),
                        ("policy.policy_id", "policy_id"), ("policy.version", "policy_version"), ("authorization.authority_level", "authority_level"),
                        ("authorization.qualification_ref", "qualification_ref"), ("action", "action"), ("outcome.commit_operation_id", "commit_operation_id"),
                        ("outcome.proposal_ref", "proposal_ref"), ("outcome.hold_id", "hold_id"), ("blind_sample.selected", "blind_sample"))),
    Mutation("A10-decision-json-receipt-id", "A10", "decision receipt id no longer bound to its JSON",
             (DC + "test_receipt_row_matches_its_json",), scope="decision_receipts", old="  CHECK (json_extract(receipt, '$.decision_receipt_id') IS decision_receipt_id\n     AND ", new="  CHECK ("),
    *(Mutation(f"A10-screening-binds-{key}", "A10", f"a provider assessment may differ from its receipt in {key}", (SD + "test_provider_assessment_is_exactly_its_receipts_committed_action",),
               scope="screening_assessments_bound", old=old, new=new)
      for key, old, new in (("class", "AND r.decision_class = 'screening' ", ""), ("invocation", " AND r.invocation_id IS NEW.invocation_id", ""),
                            ("commit", "          AND r.commit_operation_id = NEW.recorded_by_operation_id\n", ""),
                            ("subject-kind", "AND r.subject_kind = 'work' ", ""), ("subject-ref", " AND r.subject_ref = NEW.work_id))", "))"))),
    Mutation("A10-screening-operation-topic", "A10", "the recording operation may be another topic's", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old="  OR (SELECT topic_id FROM operation_receipts WHERE operation_id = NEW.recorded_by_operation_id) IS NOT NEW.topic_id\n", new=""),
    Mutation("A10-screening-invocation-topic", "A10", "the assessing invocation may be another topic's", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old="  OR (NEW.invocation_id IS NOT NULL AND (SELECT topic_id FROM invocations WHERE invocation_id = NEW.invocation_id) IS NOT NEW.topic_id)\n", new=""),
    Mutation("A10-screening-reversal-same-work", "A10", "a reversal may supersede another work's assessment", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old=" AND o.work_id = NEW.work_id))", new="))"),
    Mutation("A10-screening-reversal-same-topic", "A10", "a reversal may supersede another topic's assessment", (SD + "test_assessment_operation_invocation_and_reversal_are_of_its_topic",),
             scope="screening_assessments_bound", old=" AND o.topic_id = NEW.topic_id AND", new=" AND"),
    Mutation("A10-observation-invocation-topic", "A10", "an observation may be recorded under another topic's invocation (the review's probe)",
             (OB + "test_observation_invocation_is_of_its_topic",), drop_trigger="search_observations_invocation_topic"),
    # --- A11: partial results kept and marked (RG-4) -------------------------------
    Mutation("A11-completeness-tied-to-coverage", "A11", "completeness no longer tied to the coverage state", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK ((coverage_state IN ('searched_ok', 'searched_empty', 'metadata_only')) = (completeness != 'unobserved')),\n", new=""),
    Mutation("A11-searched-empty-only-complete", "A11", "an empty partial page may read as an empty search", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (coverage_state != 'searched_empty' OR completeness = 'complete'),\n", new=""),
    Mutation("A11-partial-says-why", "A11", "a partial result need not name its error class", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (completeness != 'partial' OR error_class IS NOT NULL),\n", new=""),
    Mutation("A11-complete-has-no-error", "A11", "a complete successful search may carry an error", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR completeness = 'partial' OR error_class IS NULL),", new="  CHECK (1),"),
    Mutation("A11-old-partial-ban", "A11", "over-restriction restored: a partial result may keep no count/error (the review's A11 finding)", (OB + "test_partial_results_are_kept_and_marked_incomplete",),
             old="  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR completeness = 'partial' OR error_class IS NULL),", new="  CHECK (coverage_state NOT IN ('searched_ok', 'searched_empty') OR error_class IS NULL),"),
    # --- R2.5: draft vocabularies with explicit transition semantics --------------
    *(Mutation(f"R2.5-queue-{key}", "R2.5", desc, (VO + "test_queue_status_transitions",), scope="queue_status_transitions", old=old, new=new)
      for key, desc, old, new in (
          ("revive-retired", "retired topics may be requeued", "  OR (OLD.status = 'completed_with_qualified_conclusions' AND NEW.status IN ('queued', 'retired')))",
           "  OR (OLD.status = 'completed_with_qualified_conclusions' AND NEW.status IN ('queued', 'retired'))\n  OR (OLD.status = 'retired' AND NEW.status = 'queued'))"),
          ("skip-intake", "intake may jump straight to active", "(OLD.status = 'awaiting_brief_confirmation' AND NEW.status IN ('scoping', 'retired'))",
           "(OLD.status = 'awaiting_brief_confirmation' AND NEW.status IN ('scoping', 'active', 'retired'))"),
          ("complete-from-queued", "a queued (never active) topic may complete", "(OLD.status = 'queued' AND NEW.status IN ('active', 'held', 'capability_blocked', 'retired'))",
           "(OLD.status = 'queued' AND NEW.status IN ('active', 'held', 'capability_blocked', 'completed_with_qualified_conclusions', 'retired'))"),
          ("resource-stop-as-completion", "a resource stop may be relabeled as completion", "(OLD.status = 'stopped_for_resources' AND NEW.status IN ('queued', 'awaiting_judgment', 'retired'))",
           "(OLD.status = 'stopped_for_resources' AND NEW.status IN ('queued', 'awaiting_judgment', 'completed_with_qualified_conclusions', 'retired'))"),
          ("drop-contract-approval-to-queued", "over-restriction: an approved contract can no longer be queued",
           "(OLD.status = 'awaiting_contract_approval' AND NEW.status IN ('queued', 'scoping', 'retired'))", "(OLD.status = 'awaiting_contract_approval' AND NEW.status IN ('scoping', 'retired'))"))),
    *(Mutation(f"R2.5-claim-{key}", "R2.5", desc, (VO + "test_claim_status_transitions",), scope="claims_status_transitions", old=old, new=new)
      for key, desc, old, new in (
          ("revive-superseded", "a superseded claim may return to provisional", "  OR (OLD.status = 'rejected' AND NEW.status = 'superseded'))",
           "  OR (OLD.status = 'rejected' AND NEW.status = 'superseded')\n  OR (OLD.status = 'superseded' AND NEW.status = 'provisional'))"),
          ("rejected-to-support", "a rejected claim may become accepted support", "(OLD.status = 'rejected' AND NEW.status = 'superseded')",
           "(OLD.status = 'rejected' AND NEW.status IN ('superseded', 'accepted_support'))"),
          ("quarantine-to-support", "a quarantined claim may skip re-capture straight to support", "(OLD.status = 'quarantined' AND NEW.status IN ('provisional', 'rejected', 'superseded'))",
           "(OLD.status = 'quarantined' AND NEW.status IN ('provisional', 'accepted_support', 'rejected', 'superseded'))"),
          ("drop-provisional-to-support", "over-restriction: a provisional claim can no longer be accepted",
           "(OLD.status = 'provisional' AND NEW.status IN ('accepted_support', 'contested', 'rejected', 'quarantined', 'superseded'))",
           "(OLD.status = 'provisional' AND NEW.status IN ('contested', 'rejected', 'quarantined', 'superseded'))"))),
    Mutation("R2.5-mandatory-signals-not-model-raised", "R2.5", "a model observation may raise (and so be ranked below) a retraction signal",
             (VO + "test_mandatory_signals_are_code_or_operator_raised",), old=",\n  CHECK (reason_code NOT IN ('retraction', 'decision_record_change') OR signal_source IN ('deterministic', 'operator'))", new=""),
    # --- A8 (checker), and the Python-side A1/A11 guards: file-target mutants ---------
    Mutation("A8-global-alias-map", "A8", "the original bug: one last-wins alias map for the whole file", (CB + "test_alias_reuse_in_another_scope_does_not_hide_a_capability",),
             target="tools/check_boundaries.py", old="        scope = self._target_scope(name)\n        scope.bound.add(name)\n        if import_target is not None:\n            scope.imports.setdefault(name, set()).add(import_target)",
             new="        scope = self.scope.module()\n        scope.bound.add(name)\n        if import_target is not None:\n            scope.imports[name] = {import_target}"),
    Mutation("A8-global-declaration-ignored", "A8", "`global y; import os as y` treated as a local binding", (CB + "test_alias_reuse_in_another_scope_does_not_hide_a_capability",),
             target="tools/check_boundaries.py", old="        if name in self.scope.global_names:\n            return self.scope.module()\n        return self.scope", new="        return self.scope"),
    Mutation("A8-builtins-import-alias", "A8", "`from builtins import eval as evaluate` not reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old='        if target.startswith("builtins.") and target.split(".", 1)[1] in forbidden:', new='        if False:'),
    Mutation("A8-builtins-module-alias", "A8", "`import builtins as b; b.exec(...)` not reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old='            if base == "builtins" and chain[1] and chain[1][0] in forbidden:', new='            if False:'),
    Mutation("A8-dunder-builtins", "A8", "`__builtins__[...]` not reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old='        if node.id == "__builtins__":\n            refs.append((node.lineno, "__builtins__", "builtin", ""))\n        elif', new='        if'),
    Mutation("A8-bare-references", "A8", "forbidden builtins reached by name are no longer reported", (CB + "test_forbidden_builtin_calls",),
             target="tools/check_boundaries.py", old="        elif node.id in forbidden:", new="        elif False:"),
    Mutation("A8-unscoped-builtin-names", "A8", "over-restriction: any name spelled like a builtin is flagged (re.compile, parameters)", (CB + "test_shadowed_names_are_not_builtins",),
             target="tools/check_boundaries.py", old='            if targets is None or any(t == f"builtins.{node.id}" for t in targets):', new='            if True:'),
    *(Mutation(f"A8-real-graph-{name.strip('_')}", "A8", f"{name} dropped from the real restricted list", (CB + "test_real_graph_restricts_low_level_and_alternate_surfaces",),
               target="gen2/boundaries.toml", old=f'"{name}", ', new="")
      for name in ("_sqlite3", "_posixsubprocess", "imaplib")),
    Mutation("A1-replace-lint", "A1", "the REPLACE lint no longer runs", (CB + "test_replace_sql_in_a_store_write_path_fails",),
             target="tools/check_boundaries.py", old="    if mod.name not in cfg.forbidden_sql_exempt:", new="    if False:"),
    Mutation("A1-ddl-rule-delete-guards", "A1", "the build no longer requires a delete guard on every table", (DR + "test_table_without_delete_guard_fails", DR + "test_conditional_delete_guard_does_not_count"),
             target="tools/check_gen2_schemas.py", old="        if not guarded:", new="        if False:"),
    Mutation("A1-ddl-rule-on-conflict", "A1", "the build no longer refuses ON CONFLICT clauses", (DR + "test_on_conflict_replace_clause_fails",),
             target="tools/check_gen2_schemas.py", old='    if re.search(r"\\bON\\s+CONFLICT\\b", _strip_sql_comments(text), re.IGNORECASE):', new="    if False:"),
    Mutation("A1-ddl-rule-pragmas", "A1", "the build no longer reads the connection pragmas back", (DR + "test_connection_contract_without_recursive_triggers_fails",),
             target="tools/check_gen2_schemas.py", old='            if conn.execute(f"PRAGMA {pragma}").fetchone() != (1,):', new="            if False:"),
    Mutation("A11-instants-calendar", "A11", "timestamps checked for shape only (February 31 accepted)", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old="        datetime(*(int(part) for part in match.groups()))\n", new="        pass\n"),
    Mutation("A11-instants-utc-only", "A11", "offsets other than Z accepted", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old=r"(?:\.\d{1,9})?Z\Z", new=r"(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})\Z"),
    Mutation("A11-instants-strings-only", "A11", "non-strings accepted", (IN + "test_non_strings_refused",),
             target="gen2/core/instants.py", old="    if not isinstance(value, str):\n        return False", new="    if not isinstance(value, str):\n        return True"),
    # --- R1: RFC 8785 JCS canonicalization; raw bytes kept raw -------------------------
    *(Mutation(f"R1-{key}", "R1", desc, tuple(CN + k for k in killers), target="gen2/core/canonical.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("sort-keys-is-not-jcs", "json.dumps(sort_keys=True) substituted for JCS (the ruling's explicit counterexample)",
           ("PublishedVectorsTest.test_rfc_3_2_3_utf16_property_order", "PublishedVectorsTest.test_cross_implementation_vectors"),
           "        return rfc8785.dumps(value)", '        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")'),
          ("duplicate-keys-merged", "duplicate keys silently merged (last wins)", ("StrictBoundaryTest.test_parse_rejects",),
           "        if key in out:\n            raise CanonicalizationError(f\"duplicate object key {key!r}\")\n", ""),
          ("precision-lost-silently", "precision-losing literals rounded instead of refused", ("StrictBoundaryTest.test_parse_rejects",),
           "        if Decimal(repr(value)) != Decimal(text):", "        if False:"),
          ("integers-unbounded", "integers beyond 2**53-1 accepted by the strict parser", ("StrictBoundaryTest.test_parse_rejects",),
           "        if abs(value) > INT_BOUND:", "        if False:"),
          ("lone-surrogates-accepted", "invalid Unicode (lone surrogates) accepted by the strict parser", ("StrictBoundaryTest.test_parse_rejects",),
           "            value.encode(\"utf-8\")\n", "            pass\n"),
          ("fingerprint-drops-lease", "an authority-bearing field (lease) excluded from the fingerprint",
           ("HashSemanticsTest.test_semantically_changed_envelopes_fingerprint_differently", "HashSemanticsTest.test_contract_versions_are_declared"),
           'FINGERPRINT_EXCLUDES = ("submitted_at",)', 'FINGERPRINT_EXCLUDES = ("submitted_at", "lease")'),
          ("fingerprint-keeps-submitted-at", "submitted_at (non-identity metadata) included in the fingerprint",
           ("HashSemanticsTest.test_request_fingerprint_excludes_exactly_submitted_at",), 'FINGERPRINT_EXCLUDES = ("submitted_at",)', "FINGERPRINT_EXCLUDES = ()"),
          ("content-hash-covers-itself", "a document's content hash covers its own content_hash field",
           ("HashSemanticsTest.test_content_hash_excludes_exactly_itself",), 'CONTENT_HASH_EXCLUDES = ("content_hash",)', "CONTENT_HASH_EXCLUDES = ()"),
          ("raw-bytes-canonicalized", "raw provider bytes canonicalized before hashing (the ruling's false-provenance case)",
           ("HashSemanticsTest.test_raw_bytes_are_hashed_raw_never_canonicalized",), "    return _sha256(bytes(raw))", "    return logical_hash(parse_json_strict(bytes(raw)))"))),
    # --- coverage pass: pre-existing 0a guards, so the inventory spans the whole DDL ----
    *(Mutation(f"cov-delete-guard-{trigger}", "C-11", f"drop delete guard {trigger}",
               (H + ("EveryTableSweepTest.test_unreferenced_rows_cannot_be_deleted_either" if trigger in ("claims_no_delete", "invocations_no_delete", "leases_no_delete", "outbox_events_immutable_d")
                     else "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into"),), drop_trigger=trigger)
      for trigger in ("artifacts_immutable_d", "audit_events_append_only_d", "capability_facts_no_delete", "claims_no_delete", "decision_receipts_immutable_d",
                      "decision_specs_immutable_d", "dossiers_immutable_d", "holds_no_delete", "invocation_transitions_append_only_d", "invocations_no_delete",
                      "leases_no_delete", "obligations_no_delete", "operator_decisions_immutable_d", "outbox_events_immutable_d", "research_ordinals_immutable_d",
                      "retrieval_events_immutable_d", "review_episodes_no_delete", "screening_assessments_immutable_d", "search_observations_immutable_d",
                      "verification_receipts_immutable_d")),
    *(Mutation(f"cov-{trigger}", "0a", f"drop {trigger} (a pre-existing 0a guard)", tuple(killers), drop_trigger=trigger)
      for trigger, killers in (
          ("operation_receipts_fenced", (D + "CommitFencingTest.test_stale_generation_rejected", D + "CommitFencingTest.test_released_lease_cannot_commit",
                                         D + "CommitFencingTest.test_cross_topic_commit_rejected", D + "CommitFencingTest.test_commit_under_another_invocations_lease_rejected")),
          ("claims_accepted_support_needs_receipt", (VT + "test_accepted_support_needs_receipt_at_required_tier",)),
          ("sink_generations_never_regress", (D + "PublicationTest.test_sink_generation_never_regresses",)),
          ("invocations_start_admitted", (LT + "test_invocations_start_admitted",)),
          ("leases_generation_increases", (D + "LeaseFencingTest.test_generation_strictly_increases_per_topic",)),
          ("leases_release_final_identity_immutable", (D + "LeaseFencingTest.test_release_is_write_once",)),
          ("queue_state_revision_advances_by_one", (D + "CommitFencingTest.test_state_revision_advances_by_exactly_one",)),
          ("contract_status_forward_only", (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted",)),
          ("claims_start_provisional", (VT + "test_claims_start_provisional",)),
          ("retrieval_events_from_successful_search", (OB + "test_retrieval_events_only_from_successful_searches",)),
          ("review_triggers_handled_is_final", (D + "OrdinalAndTriggerTest.test_trigger_identity_unique_and_handled_is_final",)),
          ("outbox_events_generation_increases", (D + "PublicationTest.test_generations_strictly_increase",)),
          ("holds_clear_once_identity_immutable", (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision", RI + "test_hold_identity_class_and_authority_are_immutable")),
          ("queue_topic_identity_immutable", (RI + "test_topic_identity_is_immutable",)),
          ("review_episodes_close_once", (RI + "test_review_episode_closes_once",)),
          ("claims_identity_immutable", (RI + "test_claim_content_is_immutable_per_revision",)),
          ("works_identity_immutable", (RI + "test_work_identity_is_immutable",)))),
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


# Guards deliberately kept as a second layer behind another guard that
# always fires first for every row that reaches them, so no test can kill
# their removal alone. Listed so a reviewer does not mistake them for missed
# coverage; each names the first layer (which IS in the inventory).
SECOND_LAYER = {
    "screening_provider_needs_qualified_authority (trigger)":
        "screening_assessments_bound requires the receipt's commit_operation_id to be the assessment's recording operation; a receipt has a "
        "commit_operation_id only for commit_reversible_action, which a CHECK allows only at qualified authority (A10-screening-binds-commit)",
    "verification_receipts CHECK (verdict != 'supports' OR exact_quote.status IN ('matched', 'not_applicable'))":
        "a mismatched quote is always quarantined (quote_checks CHECK, A6-D32-byte-mismatch) and a matched/mismatched status needs a bound check "
        "(A6-quote-check-iff-status), so verification_receipts_bindings refuses support on it first (A6-quote-binding-*)",
}


SECOND_LAYER_TRIGGERS = {"screening_provider_needs_qualified_authority"}


def uncovered_triggers(ddl: str) -> list[str]:
    """DDL triggers that no mutation drops, scopes or edits, minus the
    documented second layers. The run fails while this is non-empty, so a new
    guard cannot land without a mutant (CHECK constraints are anonymous in
    SQLite and are not enumerated here; their mutants edit their text)."""
    blocks = {m.group(1): m.group(0) for m in re.finditer(r"CREATE TRIGGER (\w+)\b.*?\nEND;\n", ddl, re.DOTALL)}
    covered: set[str] = set()
    for m in MUTATIONS:
        if m.target != "ddl":
            continue
        if m.drop_trigger:
            covered.add(m.drop_trigger)
        if m.scope in blocks:
            covered.add(m.scope)
        for old in [m.old, *(o for o, _ in m.also)]:
            if old:
                covered.update(name for name, body in blocks.items() if old in body)
    return sorted(set(blocks) - covered - SECOND_LAYER_TRIGGERS)


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
        found = list(re.finditer(r"CREATE TRIGGER " + re.escape(m.scope) + r"\b.*?\nEND;\n", text, re.DOTALL))
        found += list(re.finditer(r"CREATE TABLE " + re.escape(m.scope) + r" \(.*?\n\) STRICT;\n", text, re.DOTALL))
        if len(found) != 1:
            raise ValueError(f"scope {m.scope!r} found {len(found)} times")
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


_FX = None  # the fixtures module, bound in main() before workers fork


def _run_file_mutation(m: Mutation) -> _Collector:
    """Mutate a Python/config file into a temp copy, point the killers' test
    modules at it, run just those modules. Runs in a forked worker (or at the
    end of a serial run), so module state it changes is not reused."""
    import importlib
    import tempfile
    import types

    text = mutate((ROOT / m.target).read_text(encoding="utf-8"), m)
    how = FILE_TARGETS[m.target]
    modules = sorted({k.split(".")[0] for k in m.killers})
    with tempfile.TemporaryDirectory() as tmp:
        if how[0] == "attr":
            path = Path(tmp) / Path(m.target).name
            path.write_text(text, encoding="utf-8")
            loaded = [importlib.import_module(name) for name in modules]
            setattr(importlib.import_module(how[1]), how[2], path)
        else:
            mutant = types.ModuleType(how[1])
            mutant.__file__ = str(ROOT / m.target)
            exec(compile(text, str(ROOT / m.target), "exec"), mutant.__dict__)
            sys.modules[how[1]] = mutant
            parent, _, leaf = how[1].rpartition(".")
            setattr(importlib.import_module(parent), leaf, mutant)
            loaded = [importlib.reload(importlib.import_module(name)) for name in modules]
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(mod) for mod in loaded)
        result = _Collector()
        suite.run(result)
        return result


def _run_file_mutation_unmutated(m: Mutation) -> _Collector:
    """The file target's killer modules against the file as it is (a mutation
    that finds its text is only meaningful if these pass unmutated)."""
    import importlib

    modules = sorted({k.split(".")[0] for k in m.killers})
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)) for name in modules)
    result = _Collector()
    suite.run(result)
    return result


def _evaluate(m: Mutation) -> str:
    fx = _FX
    ddl0, conn0 = fx.DDL_TEXT, fx.CONNECTION_TEXT
    try:
        if m.target in FILE_TARGETS:
            res = _run_file_mutation(m)
        else:
            ddl = mutate(ddl0, m) if m.target == "ddl" else ddl0
            conn = mutate(conn0, m) if m.target == "connection" else conn0
            try:
                res = run(fx, ddl, conn)
            finally:
                fx.DDL_TEXT, fx.CONNECTION_TEXT = ddl0, conn0
    except ValueError as exc:
        return f"INVALID   {m.mid}: {exc}"
    missing = [k for k in m.killers if not any(f == k or f.endswith("." + k) for f in res.failed)]
    if res.errored and (missing or not m.killers):
        return f"INVALID   {m.mid}: {len(res.errored)} test error(s), e.g. {next(iter(res.errored.items()))}"
    if not res.failed:
        return f"SURVIVED  {m.mid}: {m.description}"
    if missing:
        return f"INVALID   {m.mid}: listed killer(s) did not fail: {missing}"
    note = f" ({len(res.errored)} other test(s) errored in setup: the mutant also breaks a shared fixture)" if res.errored else ""
    return f"KILLED    {m.mid} by {len(res.failed)} test(s){note}"


def main(argv: list[str] | None = None) -> int:
    global _FX
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="run only mutations whose id starts with this prefix")
    parser.add_argument("--list", action="store_true", help="print the inventory and exit")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="worker processes (default: all cores)")
    args = parser.parse_args(argv)
    if args.list:
        for m in MUTATIONS:
            print(f"{m.mid:45} {m.finding:6} {m.description}")
        for guard, reason in SECOND_LAYER.items():
            print(f"second layer (not independently killable): {guard}\n    first layer: {reason}")
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
    for target in sorted({m.target for m in selected if m.target in FILE_TARGETS}):
        clean = Mutation("baseline", "-", "unmutated", tuple(k for m in selected if m.target == target for k in m.killers), target=target, old="", new="")
        res = _run_file_mutation_unmutated(clean)
        if res.failed or res.errored:
            print(f"BASELINE NOT GREEN for {target}: failed={sorted(res.failed)} errored={res.errored}", file=sys.stderr)
            return 1
    ids = [m.mid for m in MUTATIONS]
    if len(set(ids)) != len(ids):
        print("duplicate mutation ids", file=sys.stderr)
        return 1
    missing = uncovered_triggers(ddl0)
    if missing and not args.only:
        print(f"UNCOVERED TRIGGERS (add a mutant or document a second layer): {missing}", file=sys.stderr)
        return 1
    _FX = fx
    if args.jobs > 1 and len(selected) > 1:
        with multiprocessing.get_context("fork").Pool(args.jobs, maxtasksperchild=1) as pool:
            verdicts = pool.map(_evaluate, selected, chunksize=1)
    else:
        verdicts = [_evaluate(m) for m in selected if m.target not in FILE_TARGETS]
        verdicts += [_evaluate(m) for m in selected if m.target in FILE_TARGETS]  # these may rebind modules: run last
    bad = 0
    for verdict in verdicts:
        if not verdict.startswith("KILLED"):
            bad += 1
        print(verdict)
    coverage = "" if args.only else f"every DDL trigger covered (second layers: {len(SECOND_LAYER_TRIGGERS)}), "
    print(f"gen2 mutation run: {len(selected) - bad}/{len(selected)} killed, baseline {base.testsRun} tests green, {coverage}{time.monotonic() - started:.1f}s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
