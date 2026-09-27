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
import json
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
    "gen2/store/compat.py": ("module", "gen2.store.compat"),
    "gen2/store/db.py": ("module", "gen2.store.db"),
    "gen2/store/api.py": ("module", "gen2.store.api"),
    "gen2/importer/dry_run.py": ("module", "gen2.importer.dry_run"),
    # task 1b. A router module's dependents (named after the dotted module) are
    # reloaded over the mutant, in order, before the killers are.
    "gen2/router/service.py": ("module", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/router/boundary.py": ("module", "gen2.router.boundary", "gen2.router.service", "gen2.tests.router_fixtures"),
    "gen2/router/schemas.py": ("attr", "test_router_schemas", "VALIDATOR"),  # the oracle tool loads the mutated copy
    "tools/gen2_trigger_order.py": ("attr", "test_trigger_order_tool", "TOOL"),
    "tools/gen_source_catalog.py": ("attr", "test_source_catalog", "TOOL"),
    # A schema file: the whole schema tree is re-checked with this file replaced (0c-repair, C1).
    "gen2/schema/export-bundle.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_BUNDLE_SCHEMA"),
    "gen2/schema/export-delivery-receipt.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_RECEIPT_SCHEMA"),
    "gen2/schema/export-manifest.schema.json": ("attr", "test_schema_counterfactuals", "EXPORT_MANIFEST_SCHEMA"),
    "gen2/schema/freshness-envelope.schema.json": ("attr", "test_schema_counterfactuals", "FRESHNESS_SCHEMA"),
    "gen2/schema/common.schema.json": ("attr", "test_schema_counterfactuals", "COMMON_SCHEMA"),
    "gen2/schema/decision-receipt.schema.json": ("attr", "test_schema_counterfactuals", "DECISION_RECEIPT_SCHEMA"),
    "gen2/schema/invocation.schema.json": ("attr", "test_schema_counterfactuals", "INVOCATION_SCHEMA"),
}

H = "test_store_history."
D = "test_store_ddl."
FI = "test_store_ddl.FacetImportanceTest."
AD = "test_store_ddl.AdmissionAndLeaseTest."
IL = "test_store_ddl.InvocationLifecycleTest."
VT = "test_store_ddl.VerificationTest."
CS = "test_store_ddl.ContractAdmittedSupportTest."
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
EX = "test_store_examples.ExampleWorldTest."
CG = "test_store_ddl.ContractGovernanceTest."
SG = "test_sqlite_gate."
IB = "test_store_intake.IntakeBriefTest."
SC = "test_source_catalog.CatalogToolTest."
SF = "test_schema_counterfactuals.FixtureCounterfactualTest."
X = "ExportOutboxTest."
RC = "test_router_commit."
RO = "test_router_ops."
RE = "test_router_evidence."
RX = "test_router_crash."
RS = "test_router_schemas."
RT = "test_router_time."
RR = "test_router_restart."
SVC = "gen2/router/service.py"
BND = "gen2/router/boundary.py"
RECEIPT = "gen2/schema/export-delivery-receipt.schema.json"
MANIFEST = "gen2/schema/export-manifest.schema.json"
ENVELOPE = "gen2/schema/freshness-envelope.schema.json"
IDENTITY = ("job_handle", "host_id", "container_id", "boot_id", "start_fingerprint")
IDENTITY_KILLER = {  # each identity member's own one-error negative (0c-repair-2)
    "host_id": "test_a_process_identity_without_its_host_is_refused",
    "boot_id": "test_a_process_identity_without_its_boot_id_is_refused",
    "start_fingerprint": "test_a_process_identity_without_its_start_fingerprint_is_refused",
}

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
    Mutation("A1-connector-watermark-delete-guard", "A1", "drop connector_watermarks delete guard (carries the sink-watermark case, 0d)",
             (H + "ReplaceAndDeleteTest.test_connector_watermark_cannot_regress_by_delete_reinsert_or_replace",
              D + "ExportOutboxTest.test_connector_watermark_never_regresses"),
             drop_trigger="connector_watermarks_no_delete"),
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
    Mutation("A1-delivery-receipts-delete-guard", "A1", "drop export_delivery_receipts delete guard",
             (H + "EveryTableSweepTest.test_no_table_can_be_deleted_from_or_replaced_into",), drop_trigger="export_delivery_receipts_no_delete"),
    *(Mutation(f"A1-append-only-update-{trigger}", "A1", f"drop UPDATE guard {trigger}",
               (H + "EveryTableSweepTest.test_append_only_tables_reject_every_update",), drop_trigger=trigger)
      for trigger in ("artifacts_immutable_u", "audit_events_append_only_u", "claim_source_links_immutable_u",
                      "decision_receipts_immutable_u", "decision_specs_immutable_u", "dossiers_immutable_u",
                      "invocation_transitions_append_only_u", "obligations_immutable", "operation_receipts_immutable_u",
                      "operator_decisions_immutable_u", "outbox_events_immutable_u", "quote_checks_immutable_u",
                      "record_work_links_immutable_u", "research_ordinals_immutable_u", "retrieval_events_immutable_u",
                      "screening_assessments_immutable_u", "search_observations_immutable_u",
                      "export_delivery_receipts_immutable_u", "verification_receipts_immutable_u")),
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
    Mutation("RA1-terminal-decision-pointer", "RA1", "the review's probe: a completed/retired topic's authorizing decision may be swapped or cleared without a status change",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier", D + "ContractGovernanceTest.test_retirement_needs_operator_decision"),
             drop_trigger="queue_status_decision_moves_with_status"),
    Mutation("RA1-pointer-moves-with-revision", "RA1", "advancing state_revision alone counts as the transition that may move the pointer",
             (D + "ContractGovernanceTest.test_completion_needs_approval_of_current_dossier", D + "ContractGovernanceTest.test_retirement_needs_operator_decision"),
             scope="queue_status_decision_moves_with_status", old="AND NEW.status IS OLD.status", new="AND NEW.status IS OLD.status AND NEW.state_revision IS OLD.state_revision"),
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
    # --- RA2: a rating is exactly what the operator rated (facets and obligations alike) ---
    *(Mutation(f"RA2-{kind}-{key}", "RA2", f"{kind} rating: {desc}", (killer,), scope=f"{kind}s_rating_is_what_the_operator_rated", old=old, new=new)
      for kind, killer, subject in (("facet", FI + "test_facet_rating_bound_to_a_rating_decision", "facet_id"),
                                    ("obligation", D + "ContractGovernanceTest.test_operator_rating_bound_to_a_rating_decision", "obligation_id"))
      for key, desc, old, new in (
          ("naming", "any valid rating decision will do, not the one named", "  WHERE d.decision_id = NEW.operator_rating_decision_id\n", "  WHERE 1\n"),
          ("disposition", "a rejected rating decision authorizes", "AND d.kind = 'rating_approval' AND d.disposition = 'approved'", "AND d.kind = 'rating_approval'"),
          ("topic", "another topic's rating decision authorizes", "    AND d.topic_id = NEW.topic_id\n", ""),
          ("lineage", "the rated draft may be any revision, not an ancestor (unrelated draft; self-hash cycle)",
           "    AND d.subject_revision IN (\n          WITH RECURSIVE lineage(rev) AS (\n            SELECT parent_revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision\n"
           "            UNION SELECT c.parent_revision FROM contract_revisions c JOIN lineage l ON c.topic_id = NEW.topic_id AND c.revision = l.rev)\n          SELECT rev FROM lineage)\n", ""),
          ("lineage-includes-self", "a decision about the revision carrying it counts (self-hash cycle)",
           "            SELECT parent_revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision\n",
           "            SELECT revision FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision\n"),
          ("payload-subject", "any rated entry of the payload stands for this one (a subject the operator did not rate)", f"    AND p.key = NEW.{subject}\n", ""),
          ("payload-band", "the band may differ from what the operator rated", "    AND json_extract(p.value, '$.band') IS NEW.operator_importance_band\n", ""),
          ("payload-score", "the score may differ from what the operator rated", "    AND json_extract(p.value, '$.score') IS NEW.operator_importance_score\n", ""),
          ("subject-definition", "the same id may carry a redefined subject", "\n    AND json_remove(he.value, '$.importance') IS json_remove(re.value, '$.importance'))", ")"),
          ("rated-draft", "the definition may be compared with any revision, not the rated draft",
           "    AND rated.topic_id = d.topic_id AND rated.revision = d.subject_revision\n", "    AND rated.topic_id = d.topic_id\n"))),
    Mutation("RA2-payload-only-on-rating-decisions", "RA2", "a rating decision may lack its payload, or another kind carry one",
             (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",),
             old="  CHECK ((kind = 'rating_approval') = (payload IS NOT NULL)),\n", new=""),
    Mutation("RA2-payload-shape", "RA2", "a rating payload need not carry facet and obligation objects",
             (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",),
             old="  CHECK (kind != 'rating_approval' OR (json_type(payload, '$.facets') IS 'object' AND json_type(payload, '$.obligations') IS 'object')),\n", new=""),
    Mutation("RA2-payload-of-its-draft", "RA2", "a rating payload may name subjects its draft does not have",
             (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",), drop_trigger="operator_decisions_rating_payload_of_its_draft"),
    *(Mutation(f"RA2-payload-{key}", "RA2", desc, (D + "ContractGovernanceTest.test_only_a_rating_decision_carries_a_rating_payload",),
               scope="operator_decisions_rating_payload_of_its_draft", old=old, new=new)
      for key, desc, old, new in (
          ("facet-band", "a rated facet need not carry a band from the vocabulary",
           "             WHERE coalesce(json_extract(p.value, '$.band'), '') NOT IN ('critical', 'important', 'limited')\n                OR NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.facet_map.facets') e",
           "             WHERE NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.facet_map.facets') e"),
          ("obligation-band", "a rated obligation need not carry a band",
           "             WHERE coalesce(json_extract(p.value, '$.band'), '') NOT IN ('critical', 'important', 'limited')\n                OR NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.obligations') e",
           "             WHERE NOT EXISTS (SELECT 1 FROM contract_revisions c, json_each(c.document, '$.obligations') e"),
          ("facet-in-draft", "a payload facet need not be a facet of the rated draft",
           "                                 AND json_extract(e.value, '$.facet_id') IS p.key))", "                                 AND 1))"),
          ("obligation-in-draft", "a payload obligation need not be an obligation of the rated draft",
           "                                 AND json_extract(e.value, '$.obligation_id') IS p.key)))", "                                 AND 1)))"))),
    # --- RA2-R: a contract's parent is a strictly earlier revision (proper ancestry) ---
    *(Mutation(f"RA2R-{key}", "RA2-R", desc, killers, scope="contract_revisions",
               old="\n  CONSTRAINT contract_parent_is_earlier CHECK (parent_revision IS NULL OR parent_revision < revision),", new=new)
      for key, desc, killers, new in (
          ("dropped", "the review's probe: a revision may be its own parent, a later revision's child, or on a cycle",
           (CG + "test_parent_is_a_strictly_earlier_revision", CG + "test_operator_rating_bound_to_a_rating_decision",
            FI + "test_facet_rating_bound_to_a_rating_decision", EX + "test_review_ra2r_self_parent_contract_cannot_rate_itself"), ""),
          ("self-parent", "a revision may name itself as its parent (the review's probe)",
           (CG + "test_parent_is_a_strictly_earlier_revision", CG + "test_operator_rating_bound_to_a_rating_decision",
            FI + "test_facet_rating_bound_to_a_rating_decision", EX + "test_review_ra2r_self_parent_contract_cannot_rate_itself"),
           "\n  CONSTRAINT contract_parent_is_earlier CHECK (parent_revision IS NULL OR parent_revision <= revision),"),
          ("only-self-excluded", "only self-parentage is refused: a later parent, and so a cycle, is admitted",
           (CG + "test_parent_is_a_strictly_earlier_revision", CG + "test_operator_rating_bound_to_a_rating_decision",
            FI + "test_facet_rating_bound_to_a_rating_decision"),
           "\n  CONSTRAINT contract_parent_is_earlier CHECK (parent_revision IS NULL OR parent_revision != revision),"))),
    Mutation("A2-proposal-receipt-class", "A2", "a Jev proposal may cite any decision class",
             (D + "ContractGovernanceTest.test_proposed_importance_cites_an_importance_receipt",), scope="obligations_proposal_cites_importance_receipt",
             old=" AND r.decision_class = 'importance_score')", new=")"),
    Mutation("A2-proposal-receipt-topic", "A2", "a Jev proposal may cite another topic's receipt",
             (D + "ContractGovernanceTest.test_proposed_importance_cites_an_importance_receipt",), scope="obligations_proposal_cites_importance_receipt",
             old="          AND r.topic_id = NEW.topic_id AND r.decision_class", new="          AND r.decision_class"),
    Mutation("A3-facet-band-score", "A3", "facet band/score consistency CHECK removed", (FI + "test_facet_rating_bound_to_a_rating_decision",), scope="facets",
             old="  CHECK (operator_importance_score IS NULL\n      OR (operator_importance_band = 'critical' AND operator_importance_score BETWEEN 7 AND 9)\n      OR (operator_importance_band = 'important' AND operator_importance_score BETWEEN 4 AND 6)\n      OR (operator_importance_band = 'limited' AND operator_importance_score BETWEEN 1 AND 3))",
             new="  CHECK (1)"),
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
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="  WHERE d.decision_id = NEW.approval_decision_id\n", new="  WHERE 1\n"),
    Mutation("A2-publication-kind", "A2", "publication ignores decision kind (the review's rating-decision probe)",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.kind = 'publication_approval' AND d.disposition = 'approved'\n", new="    AND d.disposition = 'approved'\n"),
    Mutation("A2-publication-disposition", "A2", "publication ignores disposition",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.kind = 'publication_approval' AND d.disposition = 'approved'\n", new="    AND d.kind = 'publication_approval'\n"),
    Mutation("A2-publication-topic", "A2", "publication ignores the approval's topic",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.topic_id = NEW.topic_id\n    AND d.subject_revision = NEW.source_revision", new="    AND d.subject_revision = NEW.source_revision"),
    Mutation("A2-publication-revision", "A2", "publication ignores the approved source revision",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="    AND d.subject_revision = NEW.source_revision\n", new=""),
    Mutation("A2-publication-hash", "A2", "publication ignores the approved source hash",
             (D + "ExportOutboxTest.test_only_approved_work_is_exported",), old="\n    AND d.subject_hash = NEW.source_content_hash)", new=")"),
    *(Mutation(f"A2-manifest-binds-{key}", "A2", f"manifest JSON no longer bound to its {key} column",
               (D + "ExportOutboxTest.test_manifest_json_matches_its_columns",), old=f"\n     AND json_extract(manifest, '$.{path}') IS {col}", new="")
      for key, path, col in (("artifact-kind", "artifact_kind", "artifact_kind"), ("source-revision", "source.revision", "source_revision"),
                             ("source-hash", "source.content_hash", "source_content_hash"), ("approval-id", "approval.operator_decision_id", "approval_decision_id"),
                             ("approved-revision", "approval.approved_revision", "source_revision"), ("supersedes", "supersedes.generation", "supersedes_generation"),
                             # 0d: what export-manifest/2 adds to the stored manifest
                             ("generation", "generation", "generation"), ("options-revision", "options_revision", "options_revision"),
                             ("bundle-hash", "bundle.content_hash", "bundle_content_hash"),
                             ("supersedes-options-revision", "supersedes.options_revision", "supersedes_options_revision"))),
    Mutation("A2-manifest-binds-expected-connectors", "A2", "manifest JSON no longer bound to expected_connectors (carries expected_sinks, 0d)",
             (D + "ExportOutboxTest.test_manifest_json_matches_its_columns",), old="\n     AND json_extract(manifest, '$.expected_connectors') IS json(expected_connectors))", new=")"),
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
    Mutation("A3-facet-proposal-class", "A3", "facet proposal may cite any decision class", (FI + "test_facet_proposal_cites_an_importance_receipt",),
             scope="facets_bound_to_document_and_decision", old=" AND r.decision_class = 'importance_score'))", new="))"),
    Mutation("A3-facet-proposal-topic", "A3", "facet proposal may cite another topic's receipt", (FI + "test_facet_proposal_cites_an_importance_receipt",),
             scope="facets_bound_to_document_and_decision", old="          AND r.topic_id = NEW.topic_id AND r.decision_class", new="          AND r.decision_class"),
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
    *(Mutation(f"A4-brief-confirmation-{key}", "A4/0b", f"pre-contract admission ignores the pinned brief row's {key}",
               (AD + "test_pre_contract_admission_needs_the_confirmed_brief",), scope="invocations_admission_context", old=old, new=new)
      for key, old, new in (
          ("confirming-decision", "\n          AND b.confirmed_by_decision_id = NEW.brief_confirmation_decision_id))))", "))))"),
          ("topic", "        WHERE b.topic_id = NEW.topic_id\n          AND b.brief_id", "        WHERE b.brief_id"),
          ("brief-hash", " AND b.content_hash = NEW.brief_hash", ""),
          ("brief-version", " AND b.version = NEW.brief_version", ""),
          ("brief-id", "          AND b.brief_id = NEW.brief_ref AND ", "          AND "))),
    Mutation("A4-brief-confirmation-status", "A4/0b", "pre-contract admission accepts a superseded (no longer current) brief version",
             (AD + "test_pre_contract_admission_pins_the_current_confirmed_version",),
             scope="invocations_admission_context", old="\n          AND b.status = 'confirmed'", new=""),
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
             (LT + "test_outcome_unknown_is_reconciled_not_skipped", LT + "test_every_exit_needs_its_own_episodes_record"),
             scope="invocations_unknown_needs_reconciliation", old=" AND r.unknown_episode = OLD.unknown_episode", new=""),
    # --- RA4: each unknown episode has its own, never-reused identity -----------------
    Mutation("RA4-episode-keyed-by-timestamp", "RA4", "the pre-RA4 key: an exit is reconciled by any record whose start time matches (a re-entry at a reused timestamp)",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocations_unknown_needs_reconciliation",
             old=" AND r.unknown_episode = OLD.unknown_episode", new=" AND r.unknown_since = OLD.outcome_unknown_since"),
    Mutation("RA4-episode-identity-dropped", "RA4", "the review's attack: an active episode's start time can be rewound (and its identity rewritten)",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), drop_trigger="invocations_unknown_episode_is_fresh"),
    *(Mutation(f"RA4-{key}", "RA4", desc, (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocations_unknown_episode_is_fresh", old=old, new=new)
      for key, desc, old, new in (
          ("entry-takes-next-identity", "a re-entry may keep or reuse an earlier episode's identity",
           "          THEN NEW.unknown_episode IS NOT OLD.unknown_episode + 1\n", "          THEN 0\n"),
          ("identity-immutable", "an episode's identity may be rewritten outside an entry",
           "          ELSE NEW.unknown_episode IS NOT OLD.unknown_episode OR NEW.outcome_unknown_since", "          ELSE NEW.outcome_unknown_since"),
          ("start-time-immutable", "the review's rewind: an episode's start time may be changed outside an entry",
           " OR NEW.outcome_unknown_since IS NOT OLD.outcome_unknown_since END", " END"))),
    Mutation("RA4-reconciliation-names-current-episode", "RA4", "a record may be written for an earlier episode sharing the current start time",
             (LT + "test_outcome_unknown_is_reconciled_not_skipped",), scope="invocation_reconciliations_for_current_episode",
             old="\n    AND i.unknown_episode = NEW.unknown_episode AND i.outcome_unknown_since = NEW.unknown_since)", new=" AND i.outcome_unknown_since = NEW.unknown_since)"),
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
    # --- RA5: promotion from the stored claim; sampling never qualifies ----------
    Mutation("RA5-promotion-accepts-sampling", "RA5", "the review's probe: a sampled receipt (any checks, any adjudication) promotes a load-bearing claim",
             (VT + "test_sampling_never_qualifies_a_load_bearing_claim",), scope="claims_accepted_support_needs_receipt",
             old="    AND v.use = 'load_bearing'\n", new=""),
    Mutation("RA5-promotion-verdict", "RA5", "a load-bearing partial support promotes the claim",
             (VT + "test_sampling_never_qualifies_a_load_bearing_claim",), scope="claims_accepted_support_needs_receipt",
             old="AND v.verdict = 'supports'\n", new="AND v.verdict IN ('supports', 'partially_supports')\n"),
    Mutation("RA5-use-matches-claim-dropped", "RA5", "a load-bearing-use receipt may re-describe its claim's designation",
             (VT + "test_load_bearing_receipt_states_its_claims_designation",), drop_trigger="verification_receipts_use_matches_claim"),
    Mutation("RA5-use-matches-claim-load-bearing", "RA5", "a load-bearing-use receipt may be about a claim that is not load-bearing",
             (VT + "test_load_bearing_receipt_states_its_claims_designation",), scope="verification_receipts_use_matches_claim",
             old="    AND c.load_bearing = 1\n", new=""),
    Mutation("RA5-use-matches-claim-tier", "RA5", "a load-bearing-use receipt may name another required tier than its claim's",
             (VT + "test_load_bearing_receipt_states_its_claims_designation",), scope="verification_receipts_use_matches_claim",
             old="\n    AND c.required_access_tier = NEW.required_access_tier)", new=")"),
    # --- task 1a / V-10: accepted support needs contract-admitted production ---------
    Mutation("V10-dropped", "1a", "the limited-consumer rule restored: pre-contract (scoping) output becomes accepted support",
             (CS + "test_pre_contract_claim_with_a_qualifying_receipt_is_refused", CS + "test_every_claim_needs_admission_not_only_load_bearing",
              CS + "test_adopted_pre_contract_claim_with_a_receipt_is_allowed", CS + "test_contested_to_accepted_support_follows_the_same_rule",
              CS + "test_the_producer_is_work_of_the_claims_own_topic"), drop_trigger="claims_accepted_support_needs_contract_admission"),
    *(Mutation(f"V10-{key}", "1a", desc, tuple(CS + k for k in killers), scope=scope, old=old, new=new)
      for key, desc, killers, scope, old, new in (
          ("admission-context", "any producer of the claim's topic qualifies, pre-contract (scoping) work included",
           ("test_pre_contract_claim_with_a_qualifying_receipt_is_refused", "test_every_claim_needs_admission_not_only_load_bearing",
            "test_adopted_pre_contract_claim_with_a_receipt_is_allowed", "test_contested_to_accepted_support_follows_the_same_rule"),
           "claims_accepted_support_needs_contract_admission", "\n    AND p.admission_context = 'contract/1'", ""),
          ("producer-topic", "another topic's contract-admitted work qualifies as this topic's production",
           ("test_the_producer_is_work_of_the_claims_own_topic",),
           "claims_accepted_support_needs_contract_admission", "\n    AND p.topic_id = NEW.topic_id)", ")"),
          ("load-bearing-only", "the rule narrowed to V-4's scope: only load-bearing claims need admission",
           ("test_every_claim_needs_admission_not_only_load_bearing",),
           "claims_accepted_support_needs_contract_admission", "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS ("),
          ("contested-exempt", "contested -> accepted_support skips the admission rule",
           ("test_contested_to_accepted_support_follows_the_same_rule",),
           "claims_accepted_support_needs_contract_admission", "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND OLD.status IS NOT 'contested' AND NOT EXISTS ("),
          ("receipt-substitutes-for-admission", "the two conditions merged: a supporting load-bearing receipt stands in for contract admission",
           ("test_pre_contract_claim_with_a_qualifying_receipt_is_refused",),
           "claims_accepted_support_needs_contract_admission", "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND NOT EXISTS (SELECT 1 FROM verification_receipts v WHERE v.claim_id = NEW.claim_id "
           "AND v.claim_revision = NEW.revision AND v.use = 'load_bearing' AND v.verdict = 'supports') AND NOT EXISTS ("),
          ("admission-substitutes-for-receipt", "the two conditions merged: contract admission stands in for the verification receipt",
           ("test_contract_admitted_claim_without_a_receipt_is_refused",),
           "claims_accepted_support_needs_receipt", "WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS (",
           "WHEN NEW.status = 'accepted_support' AND NEW.load_bearing = 1 AND NOT EXISTS (SELECT 1 FROM invocations p "
           "WHERE p.invocation_id = NEW.producer_invocation_id AND p.admission_context = 'contract/1') AND NOT EXISTS ("),
          ("adoption-per-claim", "adoption read per claim id, not per revision: an adopted revision admits the scoping revision and a relabelled one too",
           ("test_adopted_pre_contract_claim_with_a_receipt_is_allowed",),
           "claims_accepted_support_needs_contract_admission", "  WHERE p.invocation_id = NEW.producer_invocation_id\n",
           "  WHERE p.invocation_id IN (SELECT producer_invocation_id FROM claims WHERE claim_id = NEW.claim_id)\n"),
          ("adoption-refused", "over-restriction: a claim with any pre-contract revision can never become accepted support (no adoption)",
           ("test_adopted_pre_contract_claim_with_a_receipt_is_allowed",),
           "claims_accepted_support_needs_contract_admission", "\n    AND p.topic_id = NEW.topic_id)",
           "\n    AND p.topic_id = NEW.topic_id\n    AND NOT EXISTS (SELECT 1 FROM claims o JOIN invocations q ON q.invocation_id = o.producer_invocation_id "
           "WHERE o.claim_id = NEW.claim_id AND q.admission_context = 'pre-contract/1'))"))),
    # --- RA3: scientific rows only under contract-admitted work and approved pins -------
    *(Mutation(f"RA3-{key}", "RA3", desc, tuple(AD + k for k in killers), drop_trigger=trigger)
      for key, desc, killers, trigger in (
          ("screening-dropped", "pre-contract work may record a screening disposition against a draft (the review's probe)",
           ("test_pre_contract_work_records_no_scientific_disposition", "test_scientific_rows_bind_the_approved_protocol_they_name"), "screening_assessments_under_approved_protocol"),
          ("link-dropped", "a claim-source link may tie pre-contract or other-protocol work to an obligation",
           ("test_pre_contract_work_records_no_scientific_disposition", "test_scientific_rows_bind_the_approved_protocol_they_name"), "claim_source_links_under_approved_protocol"),
          ("dossier-dropped", "a dossier may be evaluated against a draft",
           ("test_pre_contract_work_records_no_scientific_disposition", "test_scientific_rows_bind_the_approved_protocol_they_name"), "dossiers_under_approved_protocol"))),
    # --- RA3-R: the approving decision is recorded only by the draft -> approved transition ---
    Mutation("RA3R-dropped", "RA3-R", "the review's probe: an approving decision may be recorded on a still-draft revision, which then admits a dossier",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition", AD + "test_pre_contract_work_records_no_scientific_disposition",
              EX + "test_review_ra3r_approval_pointer_without_approval"), drop_trigger="contract_approval_pointer_set_by_approval"),
    # (RA3R-superseded-too — the pointer first recorded by draft -> superseded — is a second layer since
    # the draft -> superseded edge was removed; see SECOND_LAYER.)
    # --- 0a-repair-3 ruling 1: draft -> superseded is not an edge -------------------
    Mutation("R1c-draft-superseded-edge-restored", "0b-cleanup-1", "the unreachable draft -> superseded edge is back in the status machine (the CHECK then refuses in its place)",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition",), scope="contract_status_forward_only",
             old="(OLD.status = 'draft' AND NEW.status IN ('draft', 'approved'))", new="(OLD.status = 'draft' AND NEW.status IN ('draft', 'approved', 'superseded'))"),
    Mutation("R1c-approved-without-decision", "0b-cleanup-1", "drop the CHECK that a non-draft revision holds its approving decision",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition",),
             old="  CHECK (status = 'draft' OR approved_by_decision_id IS NOT NULL),\n", new=""),
    Mutation("RA3R-approval-refused-too", "RA3-R", "over-restriction: not even the draft -> approved transition may record its decision",
             (CG + "test_approval_pointer_is_set_only_by_the_approval_transition", AD + "test_scientific_rows_bind_the_approved_protocol_they_name",
              EX + "test_review_ra3r_approval_pointer_without_approval"), scope="contract_approval_pointer_set_by_approval",
             old="\n  AND NEW.status IS NOT 'approved'\n", new="\n"),
    *(Mutation(f"RA3-{key}", "RA3", desc, (AD + "test_scientific_rows_bind_the_approved_protocol_they_name",), scope=scope, old=old, new=new)
      for key, desc, scope, old, new in (
          ("screening-operation-pin", "a screening row may be recorded by a commit pinned to another revision", "screening_assessments_under_approved_protocol",
           "WHERE o.operation_id = NEW.recorded_by_operation_id AND o.contract_revision = NEW.contract_revision)", "WHERE o.operation_id = NEW.recorded_by_operation_id)"),
          ("screening-invocation-pin", "a screening row may be assessed by work pinned to another revision", "screening_assessments_under_approved_protocol",
           "WHERE i.invocation_id = NEW.invocation_id AND i.contract_revision = NEW.contract_revision))", "WHERE i.invocation_id = NEW.invocation_id))"),
          ("screening-framing", "a screening row may carry another framing version than its revision's", "screening_assessments_under_approved_protocol",
           "\n         AND c.framing_version = NEW.framing_version", ""),
          ("screening-eligibility", "a screening row may carry another eligibility-protocol version than its revision's", "screening_assessments_under_approved_protocol",
           "\n         AND json_extract(c.document, '$.eligibility_protocol.protocol_version') IS NEW.eligibility_protocol_version)", ")"),
          ("link-topic", "a link may name this topic's obligation for another topic's claim", "claim_source_links_under_approved_protocol",
           "\n    AND c.topic_id = NEW.topic_id", ""),
          ("link-producer-pin", "a link may name another protocol revision than its claim's producing work", "claim_source_links_under_approved_protocol",
           "\n    AND p.contract_revision = NEW.contract_revision)", ")"))),
    # --- RA6: one representation — every duplicated identity field equals its twin ------
    *(Mutation(f"RA6-receipt-json-{field.replace('.', '-')}", "RA6", f"a commit receipt's JSON {field} may differ from its row",
               (AD + "test_receipt_json_admission_matches_its_columns", EX + "test_commit_receipt_cannot_describe_another_row"), scope="operation_receipts",
               old=f"\n     AND json_extract(receipt, '$.{field}') IS {column}", new="")
      for field, column in (("operation_kind", "operation_kind"), ("invocation_id", "invocation_id"), ("topic_id", "topic_id"),
                            ("request_fingerprint", "request_fingerprint"), ("state_revision_before", "state_revision_before"),
                            ("state_revision_after", "state_revision_after"), ("validation.validator_version", "validator_version"),
                            ("validation.policy_version", "policy_version"), ("committed_at", "committed_at"))),
    Mutation("RA6-receipt-json-lease-release-lease", "RA6", "a commit receipt may record the release of another lease than its fencing one",
             (AD + "test_receipt_json_admission_matches_its_columns", EX + "test_commit_receipt_cannot_describe_another_row"), scope="operation_receipts",
             old="json_extract(receipt, '$.effects.lease_release.lease_id') IS lease_id\n          AND ", new=""),
    Mutation("RA6-receipt-json-lease-release-generation", "RA6", "a commit receipt may record another released generation than its fencing one",
             (AD + "test_receipt_json_admission_matches_its_columns", EX + "test_commit_receipt_cannot_describe_another_row"), scope="operation_receipts",
             old="\n          AND json_extract(receipt, '$.effects.lease_release.generation') IS lease_generation", new=""),
    Mutation("RA6-receipt-admission-references-dropped", "RA6", "a commit receipt's JSON may name another contract hash or brief than its pins",
             (AD + "test_receipt_json_admission_matches_its_columns", AD + "test_pre_contract_receipt_json_names_the_pinned_brief"),
             drop_trigger="operation_receipts_admission_references"),
    *(Mutation(f"RA6-receipt-admission-{key}", "RA6", desc, (killer,), scope="operation_receipts_admission_references", old=old, new=new)
      for key, desc, killer, old, new in (
          ("contract-hash", "the receipt JSON may name another contract content hash", AD + "test_receipt_json_admission_matches_its_columns",
           "WHEN json_extract(NEW.receipt, '$.admission.contract.content_hash')\n       IS NOT (SELECT content_hash FROM contract_revisions WHERE topic_id = NEW.topic_id AND revision = NEW.contract_revision)\n  OR ", "WHEN "),
          ("brief-id", "the receipt JSON may name another brief", AD + "test_pre_contract_receipt_json_names_the_pinned_brief",
           "         AND json_extract(NEW.receipt, '$.admission.brief.brief_id') IS i.brief_ref\n", ""),
          ("brief-version", "the receipt JSON may name another brief version", AD + "test_pre_contract_receipt_json_names_the_pinned_brief",
           "         AND json_extract(NEW.receipt, '$.admission.brief.version') IS i.brief_version\n", ""),
          ("brief-confirmation", "the receipt JSON may name another confirming decision", AD + "test_pre_contract_receipt_json_names_the_pinned_brief",
           "\n         AND json_extract(NEW.receipt, '$.admission.brief_confirmation_decision_id') IS i.brief_confirmation_decision_id)", ")"))),
    Mutation("RA6-decision-spec-id", "RA6", "the review's probe: a decision receipt may name another spec id than its hash selects",
             (DC + "test_receipt_matches_its_spec", EX + "test_decision_receipt_cannot_name_another_spec"), scope="decision_receipts_match_spec",
             old="WHEN (SELECT spec_id FROM decision_specs WHERE spec_hash = NEW.spec_hash) IS NOT json_extract(NEW.receipt, '$.spec.spec_id')\n  OR ", new="WHEN "),
    Mutation("RA6-decision-decided-at", "RA6", "a decision receipt's JSON decided_at may differ from its row", (DC + "test_receipt_row_matches_its_json",),
             scope="decision_receipts", old="\n     AND json_extract(receipt, '$.decided_at') IS decided_at", new=""),
    *(Mutation(f"RA6-obligation-{key}", "RA6", f"the review's probe: an obligation row's {key} may differ from its document entry",
               (FI + "test_obligation_row_equals_its_entry_and_tags_only_its_facets", EX + "test_obligation_rows_cannot_contradict_the_example_document"),
               scope="obligations_bound_to_document_and_facets", old=f"         AND json_extract(e.value, '$.{path}') IS NEW.{key}\n", new="")
      for key, path in (("template_id", "template.template_id"), ("template_version", "template.template_version"), ("claim_type", "template.claim_type"),
                        ("stopping_profile_id", "stopping_profile_id"), ("exploratory", "exploratory"))),
    *(Mutation(f"RA6-contract-{key}", "RA6", f"a contract document's {key} may differ from its row", (CG + "test_hash_lock_binds_document_to_row",),
               scope="contract_revisions", old=f"\n     AND json_extract(document, '$.{key}') IS {key}", new="")
      for key in ("parent_revision", "created_at")),
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
             target="tools/check_boundaries.py", old="        scope = self._target_scope(name)\n        scope.bound.add(name)\n        if import_target is not None:\n            if name in scope.nonlocal_names:",
             new="        scope = self.scope.module()\n        scope.bound.add(name)\n        if import_target is not None:\n            scope.imports[name] = set()  # last binding wins, file-wide\n            if name in scope.nonlocal_names:"),
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
    # --- RA7: signature expressions, nonlocal imports, posix; the review's 3 scope survivors ---
    *(Mutation(f"RA7-{key}", "RA7", desc, tuple(CB + k for k in killers), target="tools/check_boundaries.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("annotations-not-visited", "the review's probe: parameter annotations are not visited (def f(x: eval('1')))",
           ("test_forbidden_builtin_calls", "test_review_ra7_reproductions_under_the_real_graph"),
           ",\n                     *(a.annotation for a in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg) if a is not None)", ""),
          ("returns-not-visited", "return annotations are not visited", ("test_forbidden_builtin_calls",),
           "*args.kw_defaults, node.returns,", "*args.kw_defaults,"),
          ("type-params-not-visited", "type-parameter bounds are not visited", ("test_forbidden_builtin_calls",),
           '        for param in getattr(node, "type_params", ()):', "        for param in ():"),
          ("nonlocal-import-binds-locally", "the review's probe: `nonlocal x; import os as x` binds only the inner scope",
           ("test_review_ra7_reproductions_under_the_real_graph",), "            if name in scope.nonlocal_names:", "            if False:"),
          ("class-scope-visible", "Astra's survivor: a class body is treated as visible to its methods",
           ("test_scope_resolution_witnesses",), 'visible = scope is start or scope.kind != "class"', "visible = True"),
          ("walrus-binds-in-comprehension", "Astra's survivor: a comprehension walrus binds inside the comprehension",
           ("test_scope_resolution_witnesses",),
           '        while scope.kind == "comprehension" and scope.parent is not None:  # PEP 572: binds in the enclosing scope\n            scope = scope.parent\n', ""),
          ("global-ignored-in-resolution", "Astra's survivor: `global` is ignored when resolving a reference",
           ("test_scope_resolution_witnesses",), "    if name in scope.global_names:\n        scope = scope.module()\n    while scope is not None:", "    while scope is not None:"))),
    Mutation("RA7-real-graph-posix", "RA7", "the review's probe: posix (the module behind os) unrestricted in the real graph",
             (CB + "test_review_ra7_reproductions_under_the_real_graph", CB + "test_real_graph_restricts_low_level_and_alternate_surfaces"),
             target="gen2/boundaries.toml", old='"posix", ', new=""),
    Mutation("RA7-real-graph-nt", "RA7", "nt (the Windows module behind os) unrestricted in the real graph",
             (CB + "test_real_graph_restricts_low_level_and_alternate_surfaces",), target="gen2/boundaries.toml", old='"nt", ', new=""),
    *(Mutation(f"A8-real-graph-{name.strip('_')}", "A8", f"{name} dropped from the real restricted list", (CB + "test_real_graph_restricts_low_level_and_alternate_surfaces",),
               target="gen2/boundaries.toml", old=f'"{name}", ', new="")
      for name in ("_sqlite3", "_posixsubprocess", "imaplib")),
    Mutation("A1-replace-lint", "A1", "the REPLACE lint no longer runs", (CB + "test_replace_sql_in_a_store_write_path_fails",),
             target="tools/check_boundaries.py", old="    if mod.name not in cfg.forbidden_sql_exempt:", new="    if False:"),
    Mutation("A1-ddl-rule-delete-guards", "A1", "the build no longer requires a delete guard on every table", (DR + "test_table_without_delete_guard_fails", DR + "test_conditional_delete_guard_does_not_count"),
             target="tools/check_gen2_schemas.py", old="        if not guarded:", new="        if False:"),
    Mutation("A1-ddl-rule-on-conflict", "A1", "the build no longer refuses ON CONFLICT clauses", (DR + "test_on_conflict_replace_clause_fails",),
             target="tools/check_gen2_schemas.py", old='    if re.search(r"\\bON\\s+CONFLICT\\b", _strip_sql_comments(text), re.IGNORECASE):', new="    if False:"),
    Mutation("A1-ddl-rule-pragmas", "A1", "the build no longer reads the connection pragmas back (contract executed, not gated)", (DR + "test_connection_contract_without_recursive_triggers_fails",),
             target="tools/check_gen2_schemas.py", old='        compat.apply_connection_contract(conn, (root / conn_rel).read_text(encoding="utf-8"))',
             new='        conn.executescript((root / conn_rel).read_text(encoding="utf-8"))'),
    Mutation("SQLC-build-skips-library-gate", "0b-R4", "the DDL check no longer runs the store's SQLite gate on the build's SQLite", (DR + "test_refused_sqlite_fails_the_ddl_check",),
             target="tools/check_gen2_schemas.py", old="        compat.check_library(conn)\n    except compat.StoreCompatibilityError as exc:\n        conn.close()",
             new="        pass\n    except compat.StoreCompatibilityError as exc:\n        conn.close()"),
    Mutation("SQLC-build-unprobed-json", "0b-R4", "the DDL check no longer refuses a JSON function the gate does not probe", (DR + "test_json_function_without_a_gate_probe_fails",),
             target="tools/check_gen2_schemas.py", old="    if unprobed:", new="    if False:"),
    Mutation("A11-instants-calendar", "A11", "timestamps checked for shape only (February 31 accepted)", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old="        datetime(*(int(part) for part in match.groups()))\n", new="        pass\n"),
    Mutation("A11-instants-utc-only", "A11", "offsets other than Z accepted", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old=r"(?:\.[0-9]{1,9})?Z\Z", new=r"(?:\.[0-9]{1,9})?(?:Z|[+-][0-9]{2}:[0-9]{2})\Z"),
    # Astra's independent survivors (re-review), now killed; and the ASCII cleanup
    Mutation("A11-instants-empty-fraction", "A11", "Astra's survivor: a decimal point with no fraction digits accepted", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old=r"(?:\.[0-9]{1,9})?Z\Z", new=r"(?:\.[0-9]{0,9})?Z\Z"),
    Mutation("A11-instants-pre-1970", "A11", "Astra's survivor: real instants before 1970 refused", (IN + "test_real_instants_accepted",),
             target="gen2/core/instants.py", old="    if match is None:\n        return False\n", new="    if match is None or int(match.group(1)) < 1970:\n        return False\n"),
    Mutation("A11-instants-unicode-digits", "A11", "the helper's \\d admits Unicode decimal digits the schema's ASCII pattern refuses", (IN + "test_impossible_or_malformed_instants_refused",),
             target="gen2/core/instants.py", old=r'_SHAPE = re.compile(r"\A([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]{1,9})?Z\Z")',
             new=r'_SHAPE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?Z\Z")'),
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
           ("HashSemanticsTest.test_raw_bytes_are_hashed_raw_never_canonicalized",), "    return _sha256(bytes(raw))", "    return logical_hash(parse_json_strict(bytes(raw)))"),
          # Astra's independent survivors (re-review), now killed
          ("underflow-to-zero", "Astra's survivor: a numeral that underflows is accepted as 0.0", ("StrictBoundaryTest.test_parse_rejects",),
           "        if Decimal(repr(value)) != Decimal(text):", "        if value != 0 and Decimal(repr(value)) != Decimal(text):"),
          ("raw-bytes-stripped", "Astra's survivor: retained bytes stripped of leading/trailing whitespace before hashing",
           ("HashSemanticsTest.test_raw_bytes_are_hashed_raw_never_canonicalized",), "    return _sha256(bytes(raw))", "    return _sha256(bytes(raw).strip())"),
          ("bytes-decoded-as-ascii", "Astra's survivor: JSON bytes decoded as ASCII, not UTF-8", ("StrictBoundaryTest.test_parse_decodes_bytes_as_utf8",),
           '            text = text.decode("utf-8")', '            text = text.decode("ascii")'),
          # RA8: identity bounds by value
          ("identity-bounded-by-type", "the review's RA8 probe: only int identities are bounded (9007199254740992.0 / ...e0 pass)",
           ("StrictBoundaryTest.test_identity_bound_holds_by_value_in_every_notation",),
           "    if not minimum <= value <= INT_BOUND:", "    if isinstance(value, int) and not minimum <= value <= INT_BOUND:"),
          ("identity-non-integral", "a non-integral float passes as an identity", ("StrictBoundaryTest.test_identity_bound_holds_by_value_in_every_notation",),
           "    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):", "    if isinstance(value, float) and not math.isfinite(value):"),
          ("identity-bool", "a JSON boolean passes as an identity", ("StrictBoundaryTest.test_identity_bound_holds_by_value_in_every_notation",),
           "    if isinstance(value, bool) or not isinstance(value, (int, float)):", "    if not isinstance(value, (int, float)):"))),
    # --- 0b: the SQLite compatibility gate (Astra third review ruling 4) and the store's open path ----
    *(Mutation(f"SQLC-{key}", "0b-R4", desc, tuple(SG + k for k in killers), target="gen2/store/compat.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("version-string-compare", "the version compared as a string (3.9.0 passes, 3.100.0 is refused)",
           ("VersionFloorTest.test_version_is_compared_as_numbers",), "    if not meets_floor(version):", '    if reported < ".".join(map(str, SQLITE_FLOOR)):'),
          ("version-unanchored", "a version with trailing text parsed as its prefix instead of refused",
           ("VersionFloorTest.test_unparseable_version_is_refused_not_guessed",),
           r'_VERSION = re.compile(r"\A([0-9]+)\.([0-9]+)\.([0-9]+)\Z")', r'_VERSION = re.compile(r"\A([0-9]+)\.([0-9]+)\.([0-9]+)")'),
          ("json-not-probed", "JSON never probed: the version check alone admits a JSON-less build",
           ("JsonCapabilityTest.test_missing_json_function_is_refused_at_a_passing_version", "JsonCapabilityTest.test_json_function_answering_wrongly_is_refused"),
           "    for name, sql, expected in JSON_PROBES:", "    for name, sql, expected in ():"),
          ("json-presence-only", "a JSON function that exists but answers wrongly is accepted",
           ("JsonCapabilityTest.test_json_function_answering_wrongly_is_refused",), "        if got != expected:", "        if False:"),
          ("pragmas-not-read-back", "the connection contract executed but its pragmas never read back",
           ("ConnectionContractGateTest.test_a_contract_without_a_required_pragma_is_refused", "ConnectionContractGateTest.test_a_misspelled_pragma_does_not_pass_silently"),
           "        if row != (1,):", "        if False:"),
          ("required-pragmas-from-file-only", "only the pragmas the contract file names are read back (a file dropping one is trusted)",
           ("ConnectionContractGateTest.test_a_contract_without_a_required_pragma_is_refused", "ConnectionContractGateTest.test_a_misspelled_pragma_does_not_pass_silently"),
           "[*REQUIRED_PRAGMAS, *pragmas_set_by(text)]", "[*pragmas_set_by(text)]"))),
    *(Mutation(f"DBO-{key}", "0b-R4", desc, tuple(SG + k for k in killers), target="gen2/store/db.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("gate-after-open", "the library is checked only on the durable connection, after the path is created",
           ("OpenStoreTest.test_refused_library_creates_nothing_on_disk",),
           "        compat.check_connection(probe)  # the library itself; nothing on disk exists or is opened yet", "        pass"),
          ("implicit-create", "a missing store is opened as if it existed (no startup error)",
           ("OpenStoreTest.test_missing_store_is_an_error_not_a_mode",), "    if not create and not path.is_file():", "    if False:"),
          ("create-over-existing", "create proceeds over an existing file",
           ("OpenStoreTest.test_create_refuses_an_existing_path",), "    if create and path.exists():", "    if False:"),
          ("durable-contract-skipped", "the durable connection gets the library check but not the connection contract",
           ("OpenStoreTest.test_created_store_reopens_with_the_contract_applied",),
           "        observed = compat.check_connection(conn)  # the durable connection: contract applied and read back here",
           "        observed = compat.check_library(conn)"),
          ("no-schema-identity", "an existing store is admitted whatever its schema",
           ("OpenStoreTest.test_a_store_with_another_schema_is_not_admitted",), "        check_schema_identity(conn)\n    except BaseException:", "        pass\n    except BaseException:"),
          ("schema-names-only", "schema identity compares object names, not their SQL (a weakened guard passes)",
           ("OpenStoreTest.test_a_store_with_another_schema_is_not_admitted",),
           "    changed = sorted(f\"{k} {n}\" for (k, n) in expected.keys() & actual.keys() if expected[(k, n)] != actual[(k, n)])", "    changed = []"),
          ("user-version-ignored", "another schema version is admitted",
           ("OpenStoreTest.test_a_store_with_another_schema_is_not_admitted",),
           "    if missing or extra or changed or stored_version != version:", "    if missing or extra or changed:"))),
    # --- 0b carried requirements: writer-side JCS storage and identity bounds (RA2/RA8 rulings) ----
    *(Mutation(f"WR-{key}", "0b-writer", desc, tuple("test_writer." + k for k in killers), target="gen2/store/api.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("json-not-canonicalized", "JSON values stored as json.dumps output, not JCS",
           ("CanonicalStorageTest.test_json_is_stored_in_its_jcs_form", "CanonicalStorageTest.test_canonical_storage_makes_equal_entries_equal_text"),
           '                return canonical.canonical_bytes(parsed).decode("utf-8")', '                return __import__("json").dumps(parsed)'),
          ("text-stored-as-given", "JSON text from the caller stored as given (only parsed values canonicalized)",
           ("CanonicalStorageTest.test_json_is_stored_in_its_jcs_form",),
           '                parsed = canonical.parse_json_strict(value) if isinstance(value, (str, bytes)) else value\n',
           '                if isinstance(value, str):\n                    return value\n                parsed = canonical.parse_json_strict(value) if isinstance(value, bytes) else value\n'),
          ("identity-unbounded", "identity columns written without the RA8 bound (insert, update and advance share it)",
           ("IdentityBoundTest.test_identity_columns_are_bounded_by_value_on_insert", "IdentityBoundTest.test_advance_is_bounded_and_compare_and_set"),
           "                    return canonical.identity_integer(value)", "                    return value"),
          ("sequence-unbounded", "a generated next value is returned past 2**53-1",
           ("IdentityBoundTest.test_a_generated_increment_past_the_bound_writes_nothing",),
           "            return canonical.identity_integer((current or 0) + 1)", "            return (current or 0) + 1"),
          ("no-rollback", "a failing transaction commits what it wrote before the failure",
           ("IdentityBoundTest.test_a_generated_increment_past_the_bound_writes_nothing", "WritePathTest.test_a_ddl_refusal_propagates_and_rolls_back_the_transaction",
            "WritePathTest.test_a_refusal_at_commit_rolls_back_and_the_store_stays_usable"),
           '        try:\n            self._conn.execute("ROLLBACK")', '        try:\n            self._conn.execute("COMMIT")'),
          ("autocommit-writes", "writes accepted outside a transaction",
           ("WritePathTest.test_writes_run_inside_a_transaction",), "        if not (self._in_transaction and self._conn.in_transaction):", "        if False:"),
          # Astra 0b review A1: the whole transaction lifecycle, COMMIT included
          ("A1-rollback-unconditional", "ROLLBACK issued even when SQLite already ended the transaction (its error closes the store)",
           ("WritePathTest.test_a_transaction_sqlite_already_ended_is_not_rolled_back_again",),
           "        if not self._conn.in_transaction:\n            return\n        try:\n", "        try:\n"),
          ("A1-rollback-failure-ignored", "a failed ROLLBACK is ignored: the connection stays open inside the failed transaction",
           ("WritePathTest.test_a_failed_rollback_closes_the_connection_and_the_store_refuses_use",),
           '        except BaseException as rollback_error:\n            self._close_unusable(f"ROLLBACK failed ({rollback_error!r})", exc)\n',
           "        except BaseException as rollback_error:\n            pass\n"),
          ("A1-closed-store-reused", "a Store whose connection was closed after a failed rollback is used again",
           ("WritePathTest.test_a_failed_rollback_closes_the_connection_and_the_store_refuses_use",), "        if self._unusable is not None:", "        if False:"),
          ("A1-any-open-transaction-admits-writes", "writes accepted inside any transaction SQLite reports, not only the Store's own",
           ("WritePathTest.test_writes_need_the_stores_own_transaction",),
           "        if not (self._in_transaction and self._conn.in_transaction):", "        if not self._conn.in_transaction:"),
          ("measures-unbounded", "non-identity integers written past +/-(2**53-1)",
           ("IdentityBoundTest.test_other_integers_stay_json_interoperable",), " or abs(value) > canonical.INT_BOUND:", ":"),
          ("bool-as-measure", "a boolean accepted as a non-flag integer",
           ("IdentityBoundTest.test_other_integers_stay_json_interoperable",),
           '                raise StoreWriteError(f"{table}.{column}: a boolean is not an integer here")', "                return int(value)"),
          ("update-many-rows", "an update matching several rows is accepted",
           ("WritePathTest.test_an_update_touches_exactly_one_row",), "        if cursor.rowcount != 1:", "        if cursor.rowcount == 0:"),
          ("unknown-names-passed", "a table name outside the schema reaches the SQL text",
           ("WritePathTest.test_names_come_from_the_schema_only",),
           '        if table not in self._columns:\n            raise StoreWriteError(f"unknown table {table!r}")\n        known = self._columns[table]',
           "        known = self._columns.get(table, {})"))),
    # --- 0b: the hashing contract recorded (and frozen) on receipts (Astra 0a ruling R1) ----
    *(Mutation(f"C13-{key}", "0b-R1-freeze", desc, tuple("test_store_ddl.HashContractTest." + k for k in killers), scope=scope, old=old, new=new)
      for key, desc, killers, scope, old, new in (
          ("commit-contract-unchecked", "a commit receipt may record any hashing contract, or none",
           ("test_commit_receipt_records_the_frozen_contracts", "test_frozen_versions_agree_across_ddl_schema_and_helper"), "operation_receipts",
           "  CONSTRAINT operation_receipts_hash_contract_frozen CHECK (\n        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')\n    AND coalesce(json_extract(receipt, '$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1'))",
           "  CHECK (1)"),
          ("commit-fingerprint-unchecked", "a commit receipt's fingerprint contract is not checked",
           ("test_commit_receipt_records_the_frozen_contracts",), "operation_receipts",
           "\n    AND coalesce(json_extract(receipt, '$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1'))", ")"),
          ("commit-absent-passes", "an absent contract passes (a NULL CHECK result is a pass)",
           ("test_commit_receipt_records_the_frozen_contracts",), "operation_receipts",
           "        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')\n    AND coalesce(json_extract(receipt, '$.hash_contract.fingerprint'), '') IN ('commit-fingerprint/1'))",
           "        json_extract(receipt, '$.hash_contract.canonicalization') IN ('jcs-rfc8785/1')\n    AND json_extract(receipt, '$.hash_contract.fingerprint') IN ('commit-fingerprint/1'))"),
          ("decision-contract-unchecked", "a decision receipt may record any canonicalization contract, or none",
           ("test_decision_receipt_records_the_frozen_canonicalization_only",), "decision_receipts",
           "        coalesce(json_extract(receipt, '$.hash_contract.canonicalization'), '') IN ('jcs-rfc8785/1')\n    AND json_type(receipt, '$.hash_contract.fingerprint') IS NULL),",
           "        1),"),
          ("decision-claims-fingerprint", "a decision receipt may name a fingerprint contract it has no fingerprint for",
           ("test_decision_receipt_records_the_frozen_canonicalization_only",), "decision_receipts",
           "\n    AND json_type(receipt, '$.hash_contract.fingerprint') IS NULL),", "),"))),
    Mutation("WR-A1-commit-unprotected", "0b-writer", "the review's shape: COMMIT after the rollback path (a deferred-FK refusal leaves the transaction open)",
             ("test_writer.WritePathTest.test_a_refusal_at_commit_rolls_back_and_the_store_stays_usable",), target="gen2/store/api.py",
             old='            yield self\n            self._conn.execute("COMMIT")\n', new="            yield self\n",
             also=(("        finally:\n            self._in_transaction = False\n",
                    '        finally:\n            self._in_transaction = False\n        self._conn.execute("COMMIT")\n'),)),
    # --- 0b repair A4: no unchecked route to a Store --------------------------------
    *(Mutation(f"WR-A4-{key}", "0b-A4", desc, tuple(SG + "OpenStoreTest." + k for k in killers), target="gen2/store/api.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("constructor-unchecked", "the review's reproduction: Store(connection, {}) admits a caller-built store",
           ("test_a_store_is_made_only_through_a_checked_route", "test_refused_library_creates_nothing_on_disk"),
           "        if _admitted_by is not _ADMITTED:", "        if False:"),
          ("adoption-ungated", "adoption takes the connection's pragmas on trust (no gate, no contract read-back)",
           ("test_a_store_is_made_only_through_a_checked_route", "test_refused_library_creates_nothing_on_disk"),
           "    observed = compat.check_connection(conn)\n    db.check_schema_identity(conn)\n",
           '    observed = {"pragmas": {"foreign_keys": 1, "recursive_triggers": 1}}\n    db.check_schema_identity(conn)\n'),
          ("adoption-any-schema", "adoption admits a connection whatever its schema",
           ("test_a_store_is_made_only_through_a_checked_route",),
           "    observed = compat.check_connection(conn)\n    db.check_schema_identity(conn)\n", "    observed = compat.check_connection(conn)\n"),
          ("adoption-of-a-file", "a durable file is adopted, bypassing open_store",
           ("test_a_store_is_made_only_through_a_checked_route",), "    if files:\n", "    if False:\n"),
          ("adoption-inside-a-transaction", "a connection with a transaction open is adopted",
           ("test_a_store_is_made_only_through_a_checked_route",), "    if conn.in_transaction:\n        raise db.StoreOpenError(\"adopt_in_memory", "    if False:\n        raise db.StoreOpenError(\"adopt_in_memory"),
          ("adoption-not-autocommit", "a connection Python opens transactions on implicitly is adopted",
           ("test_a_store_is_made_only_through_a_checked_route",), "    if conn.isolation_level is not None:", "    if False:"))),
    Mutation("C13-writer-unchecked", "0b-R1-freeze", "the writer does not check a receipt's recorded hash contract (only the DDL would)",
             ("test_writer.ReceiptHashContractWriterTest.test_commit_receipt_contract_checked_before_sql",
              "test_writer.ReceiptHashContractWriterTest.test_decision_receipt_contract_checked_before_sql"),
             target="gen2/store/api.py", old="        self._check_hash_contract(table, prepared)\n", new=""),
    # --- 0b: durable intake briefs (G-4, C-12, G-13; INVARIANTS §13) ------------------
    *(Mutation(f"IB-{key}-dropped", "0b-intake", desc, tuple(IB + k for k in killers), drop_trigger=trigger)
      for key, desc, killers, trigger in (
          ("created-awaiting", "a brief may be inserted confirmed, overdue or closed", ("test_a_brief_is_written_awaiting_confirmation_with_owner_and_deadline",),
           "intake_briefs_created_awaiting"),
          ("transitions", "any brief status move is allowed", ("test_cancellation_and_archival_are_explicit_and_final",), "intake_briefs_status_transitions"),
          ("confirmation-bound", "a brief may be confirmed under any decision", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_bound"),
          ("pointer", "the confirming decision may be recorded without the transition, or changed after", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_pointer_set_by_confirmation"),
          ("superseded-by-later", "a version may be superseded with no later version", ("test_a_version_is_superseded_only_by_a_later_one_and_one_is_confirmed",),
           "intake_briefs_superseded_by_a_later_version"),
          ("overdue", "overdue may be re-marked, cleared, set on a confirmed brief or with a status change", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only"),
          ("content", "a brief version's content, lineage, owner or deadline may change", ("test_content_lineage_owner_and_deadline_are_immutable",),
           "intake_briefs_content_immutable"),
          ("terminal", "a cancelled/superseded/archived version may still change", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs_terminal_immutable"),
          ("delete-guard", "intake briefs may be deleted or REPLACEd", ("test_content_lineage_owner_and_deadline_are_immutable",), "intake_briefs_no_delete"),
          ("queue-gate", "a topic leaves intake without a confirmed brief (G-4)", ("test_an_unconfirmed_brief_cannot_advance_the_topic",),
           "queue_scoping_needs_confirmed_brief"))),
    *(Mutation(f"IB-{key}", "0b-intake", desc, tuple(IB + k for k in killers), scope=scope, old=old, new=new)
      for key, desc, killers, scope, old, new in (
          ("archive-from-awaiting", "an unconfirmed brief may be archived instead of cancelled", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs_status_transitions", "(OLD.status = 'confirmed' AND NEW.status IN ('superseded', 'archived'))",
           "(OLD.status IN ('confirmed', 'awaiting_confirmation') AND NEW.status IN ('superseded', 'archived'))"),
          ("confirmation-kind", "any decision kind confirms", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_bound", "    AND d.kind = 'brief_confirmation' AND d.disposition = 'approved'\n", "    AND d.disposition = 'approved'\n"),
          ("confirmation-disposition", "a rejected confirmation confirms", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_bound", "    AND d.kind = 'brief_confirmation' AND d.disposition = 'approved'\n", "    AND d.kind = 'brief_confirmation'\n"),
          ("confirmation-subject", "an approved confirmation of any brief of the topic confirms (subject conjuncts removed together)",
           ("test_confirmation_names_an_approved_decision_about_exactly_this_version",), "intake_briefs_confirmation_bound",
           "\n    AND d.subject_ref = NEW.brief_id AND d.subject_revision = NEW.version AND d.subject_hash = NEW.content_hash)", ")"),
          ("pointer-changes-after", "the recorded confirming decision may be swapped for another valid one", ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_pointer_set_by_confirmation", "  AND (OLD.status IS NOT 'awaiting_confirmation' OR ", "  AND ("),
          ("pointer-without-transition", "the confirming decision may be recorded without the confirming transition",
           ("test_confirmation_names_an_approved_decision_about_exactly_this_version",),
           "intake_briefs_confirmation_pointer_set_by_confirmation", " OR NEW.status IS NOT 'confirmed')", ")"),
          ("overdue-remarked", "overdue may be re-marked or cleared", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only", "  AND (OLD.overdue_since IS NOT NULL OR ", "  AND ("),
          ("overdue-advances", "marking overdue may carry a status change with it", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only", " OR NEW.status IS NOT OLD.status)", ")"),
          ("overdue-on-confirmed", "a confirmed brief may be marked overdue", ("test_expiry_marks_overdue_and_never_advances",),
           "intake_briefs_overdue_marks_only", " OR OLD.status IS NOT 'awaiting_confirmation'", ""),
          ("queue-gate-any-brief", "an unconfirmed (awaiting or cancelled) brief lets a topic leave intake", ("test_an_unconfirmed_brief_cannot_advance_the_topic",),
           "queue_scoping_needs_confirmed_brief", " AND b.status = 'confirmed')", ")"),
          ("queue-gate-any-topic", "another topic's confirmed brief lets this topic leave intake", ("test_an_unconfirmed_brief_cannot_advance_the_topic",),
           "queue_scoping_needs_confirmed_brief", "WHERE b.topic_id = NEW.topic_id AND b.status", "WHERE b.status"),
          ("parent-earlier", "a brief version may name itself (or a later version) as its parent", ("test_content_lineage_owner_and_deadline_are_immutable",),
           "intake_briefs", "  CONSTRAINT intake_brief_parent_is_earlier CHECK (parent_version IS NULL OR parent_version < version),\n", ""),
          ("closed-iff-cancelled-archived", "a brief may be cancelled or archived without recording the act", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs", "  CHECK ((status IN ('cancelled', 'archived')) = (closed_at IS NOT NULL)),\n", ""),
          ("closed-fields-together", "the closing act may omit its actor", ("test_cancellation_and_archival_are_explicit_and_final",),
           "intake_briefs", "  CHECK ((closed_by IS NULL) = (closed_at IS NULL) AND (closed_at IS NULL) = (close_reason IS NULL)),\n", ""),
          ("document-binding", "the brief document may describe another topic, brief, version, lineage, time or hash than its row",
           ("test_a_brief_is_written_awaiting_confirmation_with_owner_and_deadline",), "intake_briefs",
           "  CHECK (json_extract(document, '$.topic_id') IS topic_id\n     AND json_extract(document, '$.brief_id') IS brief_id\n     AND json_extract(document, '$.version') IS version\n     AND json_extract(document, '$.parent_version') IS parent_version\n     AND json_extract(document, '$.created_at') IS created_at\n     AND json_extract(document, '$.content_hash') IS content_hash)\n",
           "  CHECK (1)\n"))),
    Mutation("IB-one-confirmed-per-topic", "0b-intake", "two brief versions of a topic may be confirmed at once",
             (IB + "test_a_version_is_superseded_only_by_a_later_one_and_one_is_confirmed",),
             old="CREATE UNIQUE INDEX intake_briefs_one_confirmed_per_topic\n  ON intake_briefs (topic_id) WHERE status = 'confirmed';\n", new=""),
    Mutation("IB-decision-subject-exists", "0b-intake", "a brief_confirmation may be recorded about a brief that is not stored (G-13 subject existence)",
             (AD + "test_pre_contract_admission_needs_the_confirmed_brief",), scope="operator_decisions_subject_exists",
             old="\n  OR (NEW.subject_kind = 'intake_brief' AND NOT EXISTS (\n        SELECT 1 FROM intake_briefs b\n        WHERE b.topic_id = NEW.topic_id AND b.brief_id = NEW.subject_ref AND b.version = NEW.subject_revision AND b.content_hash = NEW.subject_hash))",
             new=""),
    # --- 0b: the dry-run importer skeleton (reads gen-1 only; surfaces, never resolves) ----
    Mutation("IMP-report-overwrites-open", "0b-importer", "the report may overwrite an existing file (the existence check and the exclusive open removed together)",
             ("test_importer.CommandTest.test_report_is_refused_inside_the_gen1_root_or_over_a_file",), target="gen2/importer/dry_run.py",
             old="        os.stat(target.name, dir_fd=dir_fd, follow_symlinks=False)\n    except FileNotFoundError:\n",
             new="        raise FileNotFoundError\n    except FileNotFoundError:\n",
             also=(("os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW", "os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW"),)),
    *(Mutation(f"IMP-{key}", "0b-importer", desc, tuple("test_importer." + k for k in killers), target="gen2/importer/dry_run.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("managed-store-ignored", "a managed deployment's stale JSON queue is mapped as authority",
           ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale", "CommandTest.test_report_written_outside_and_exit_status_reflects_blocking",
            "ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence"),
           "    stale = _managed_store(reader, blocking)\n", "    stale = None\n"),
          ("stale-not-marked", "queue records from a stale snapshot are not marked", ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale",),
           "        if stale is not None:\n            for record in records:", "        if False:\n            for record in records:"),
          ("malformed-lines-dropped", "malformed JSONL lines are dropped silently (gen-1 defect §11.9)", ("DryRunMappingTest.test_obligations_sources_and_logs",),
           "    if bad:\n        issues.append(", "    if False:\n        issues.append("),
          ("fleet-invented", "a missing fleet is defaulted", ("DryRunMappingTest.test_without_a_fleet_no_topic_id_is_invented",),
           "    if fleet is None:\n        issues.append(", '    fleet = fleet or "default"\n    if fleet is None:\n        issues.append('),
          ("id-lowercased", "a non-slug gen-1 id is lower-cased silently", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           "    if not TOPIC_SLUG.match(gen1_id):", "    gen1_id = gen1_id.lower()\n    if not TOPIC_SLUG.match(gen1_id):"),
          ("completed-maps", "gen-1 completed maps to gen-2 completion without an operator approval", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           '    "completed": (None, "completion-unapproved",', '    "completed": ("completed_with_qualified_conclusions", "completion-unapproved",'),
          ("running-maps", "live gen-1 execution maps to an active topic", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           '    "running": (None, "live-execution",', '    "running": ("active", "live-execution",'),
          ("identity-unbounded", "an identity past 2**53-1 is carried into the mapping", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           "        return canonical.identity_integer(value)", "        return value"),
          ("unknown-count-is-zero", "a missing iteration count becomes zero (RG-U)", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",),
           '{"accepted_count": None},\n                               [_issue("count-unknown"', '{"accepted_count": 0},\n                               [_issue("count-unknown"'),
          ("issues-do-not-downgrade", "a record with issues still reports that it maps", ("DryRunMappingTest.test_queue_items_map_with_the_authority_they_lack_named",
                                                                                          "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           '("partial" if issues else "maps")', '"maps"'),
          ("brief-imported-confirmed", "the imported brief is presented as confirmed", ("DryRunMappingTest.test_the_brief_imports_awaiting_confirmation_with_its_gaps_named",),
           '"status": "awaiting_confirmation",', '"status": "confirmed",'),
          ("disposition-trusted", "a gen-1 agent-written disposition is not flagged as unverified", ("DryRunMappingTest.test_obligations_sources_and_logs",),
           '        if isinstance(disposition, str) and disposition != "open":', "        if False:"),
          ("queue-absent-silent", "a root with no queue yields an empty report with nothing blocking", ("ReadOnlyTest.test_absent_queue_is_blocking",),
           "    elif queue is None and stale is None:", "    elif False:"),
          ("report-inside-root", "the report may be written inside the gen-1 root (the descriptor check before the file is created removed)",
           ("CommandTest.test_report_is_refused_inside_the_gen1_root_or_over_a_file", "CommandTest.test_a_report_directory_moved_into_the_root_gets_no_report"),
           '    if not _outside_root(dir_fd, reader.identity):\n        raise ReportRefused("the report', '    if False:\n        raise ReportRefused("the report'),
          ("unrepresentable-fatal", "a gen-1 value JCS cannot represent is kept, so the report cannot be rendered",
           ("CommandTest.test_an_unrepresentable_gen1_value_is_surfaced_not_fatal",),
           '            mapping[key] = None\n            issues.append(_issue("value-unrepresentable"', '            issues.append(_issue("value-unrepresentable"'),
          # --- 0b repair A2: reads and the report bound to the objects checked ---
          ("A2-file-link-followed", "a source file that is a symlink is followed (O_NOFOLLOW dropped on files)",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           "_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC", "_FILE = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC"),
          ("A2-dir-link-followed", "a directory on the way to a source that is a symlink is followed (O_NOFOLLOW dropped on directories)",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           "_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC", "_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC"),
          ("A2-path-reopened", "the review's shape: the file is reopened by pathname after the walk, not opened from the walked directory",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           "                    fd = os.open(rel.name, _FILE, dir_fd=parent)", "                    fd = os.open(self.root / rel, os.O_RDONLY)"),
          ("A2-dotdot-walks-out", "a '..' or absolute path component (from a gen-1 id) is walked, out of the root",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read",), '        if rel.is_absolute() or ".." in rel.parts:', "        if False:"),
          ("A2-refusal-as-absence", "a refused or unreadable source is reported as absent, not as missing evidence",
           ("ReadOnlyTest.test_paths_outside_the_root_are_not_read", "ReadOnlyTest.test_a_source_replaced_by_a_link_as_it_is_opened_is_not_followed"),
           '    return status is not None and status.startswith(("refused", "unreadable"))', "    return False"),
          ("A2-report-by-path", "the review's shape: the report is opened by pathname after the check, following a swapped parent",
           ("CommandTest.test_a_report_directory_swapped_for_a_link_after_the_check_is_not_followed",),
           "                _write_report(*destination, text, reader)\n", '                open(args.report, "x", encoding="utf-8").write(text)\n'),
          ("A2-report-unchecked-after-create", "no descriptor check after the file is created: the report is written into a directory moved into the root",
           ("CommandTest.test_a_report_directory_moved_into_the_root_gets_no_report",),
           "        if not _outside_root(dir_fd, reader.identity):\n            raise ReportRefused(f\"the report's directory moved",
           "        if False:\n            raise ReportRefused(f\"the report's directory moved"),
          ("A2-ancestry-not-walked", "only the report directory itself is compared with the root, not its ancestors",
           ("CommandTest.test_report_is_refused_inside_the_gen1_root_or_over_a_file", "CommandTest.test_a_report_directory_moved_into_the_root_gets_no_report"),
           '            parent = os.open("..",', '            return True\n            parent = os.open("..",'),
          # --- 0b repair A3: managed-store evidence fails closed ---
          ("A3-link-taken-as-absent", "a symlink at state/control.sqlite3 counts as no managed store",
           ("ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence",), '    if kind == "absent":\n        return None', '    if kind in ("absent", "symlink"):\n        return None'),
          ("A3-unexaminable-taken-as-absent", "an entry that is not a file, or cannot be examined, counts as no managed store",
           ("ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence",), '    if kind == "absent":\n        return None',
           '    if kind in ("absent", "unverifiable", "directory", "other"):\n        return None'),
          ("A3-entry-followed", "the review's shape: the managed-store entry is judged through its link (a dangling link reads as absent)",
           ("ReadOnlyTest.test_managed_store_evidence_is_never_mistaken_for_absence",),
           "                st = os.stat(rel.name, dir_fd=parent, follow_symlinks=False)", "                st = os.stat(rel.name, dir_fd=parent, follow_symlinks=True)"),
          ("A3-stale-not-on-malformed-items", "a malformed queue item from a stale snapshot is not marked stale",
           ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale",),
           '            if stale is not None:\n                record["issues"].append(', '            if False:\n                record["issues"].append('),
          ("A3-stale-not-on-queue-state", "the queue-level record from a stale snapshot is not marked stale",
           ("ReadOnlyTest.test_managed_store_blocks_and_the_json_queue_is_marked_stale",),
           '                                 + ([_issue("stale-snapshot", stale, "the managed store\'s state")] if stale is not None else []), unmapped=True))',
           "                                 , unmapped=True))"),
          # --- 0b repair A5: input the importer cannot interpret is reported ---
          ("A5-numerals-rounded", "the review's shape: a numeral binary64 does not hold exactly is rounded (9007199254740990.6 becomes 9007199254740991)",
           ("DryRunMappingTest.test_identity_numerals_are_checked_as_written", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced",
            "CommandTest.test_an_unrepresentable_gen1_value_is_surfaced_not_fatal"),
           "    if Decimal(repr(value)) != written:\n        return InexactNumeral(token)\n", ""),
          ("A5-fraction-as-identity", "a fractional identity is judged only by the range check (reported as out of range, not as a non-integer)",
           ("DryRunMappingTest.test_identity_numerals_are_checked_as_written",), "            or isinstance(value, float) and not value.is_integer():", "            or False:"),
          ("A5-inexact-kept-in-mapping", "an inexact numeral in a mapped value is reported as merely unrepresentable",
           ("CommandTest.test_an_unrepresentable_gen1_value_is_surfaced_not_fatal",), "        if inexact:\n", "        if False:\n"),
          ("A5-status-shape-unchecked", "the review's reproduction: status [] reaches the status table (uncaught TypeError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '    if not isinstance(status, str):\n        target, status_issues = None, [_issue("field-shape"', '    if False:\n        target, status_issues = None, [_issue("field-shape"'),
          ("A5-lane-shape-unchecked", "a wrong-typed lane/managed_kind is read as 'not intake' and the status mapped",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",), "    if shape:\n        target, status_issues = None,", "    if False:\n        target, status_issues = None,"),
          ("A5-collection-shape-unchecked", "the review's reproduction: obligations 3 (a non-list collection) goes unreported",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "        if state.get(key) is not None and not isinstance(state[key], list):", "        if False:"),
          ("A5-obligation-id-unchecked", "an obligation whose id is not a string is mapped (uncaught TypeError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '        if not isinstance(obl, dict) or not isinstance(obl.get("id"), str):', "        if not isinstance(obl, dict):"),
          ("A5-obligation-fields-unchecked", "an obligation's wrong-typed text/disposition goes unreported",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '        issues += [i for i in (_shape(obl, f, TEXT_OR_NULL, where) for f in ("text", "disposition")) if i]\n', ""),
          ("A5-item-id-unchecked", "a queue item whose id is not a string is mapped (uncaught TypeError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           '        if not isinstance(item, dict) or not isinstance(item.get("id"), str):', "        if not isinstance(item, dict):"),
          ("A5-cwd-shape-unchecked", "a wrong-typed cwd is ignored silently", ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "        if cwd_issue:", "        if False:"),
          ("A5-queue-collision-unflagged", "the review's reproduction: two queue items with one id both map, to one primary key",
           ("DryRunMappingTest.test_two_records_claiming_one_gen2_identity_are_flagged", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "        if valid_ids.count(gen1_id) > 1:", "        if False:"),
          ("A5-obligation-collision-unflagged", "two obligations with one id both map",
           ("DryRunMappingTest.test_two_records_claiming_one_gen2_identity_are_flagged", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "        if ids.count(oid) > 1:", "        if False:"),
          ("A5-semantic-version-unchecked", "the review's reproduction: schema_version 999 is interpreted as the known format, silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "    if type(version) is not int or version != SEMANTIC_STATE_VERSION:", "    if False:"),
          ("A5-queue-version-unchecked", "a queue of another version is mapped as version 1",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported",),
           '    elif isinstance(queue, dict) and (type(queue.get("version")) is not int or queue["version"] != QUEUE_VERSION):', "    elif False:"),
          ("A5-unknown-keys-dropped", "semantic-state keys outside the format are dropped silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "    unknown = _unmapped_fields(state, SEMANTIC_STATE_KEYS)\n    if unknown:", "    unknown = _unmapped_fields(state, SEMANTIC_STATE_KEYS)\n    if False:"),
          ("A5-item-fields-dropped", "queue item fields with no mapping are dropped silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           "    extra = _unmapped_fields(item, QUEUE_ITEM_MAPPED)\n    if extra:", "    extra = _unmapped_fields(item, QUEUE_ITEM_MAPPED)\n    if False:"),
          ("A5-queue-fields-dropped", "queue-level fields with no mapping are dropped silently",
           ("DryRunMappingTest.test_unsupported_versions_and_unmapped_material_are_reported", "DryRunMappingTest.test_every_record_is_classified_and_every_gap_is_surfaced"),
           '        extra = _unmapped_fields(queue, {"version", "items"})\n        if extra:', '        extra = _unmapped_fields(queue, {"version", "items"})\n        if False:'),
          ("A5-nul-path-crashes", "a NUL in a gen-1 id or cwd reaches os.open unguarded (uncaught ValueError)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "                except ValueError:  # an embedded NUL, from a gen-1 id or cwd\n                    raise _Unread(", "                except OSError as _:\n                    raise _Unread("),
          ("A5-deep-json-crashes", "JSON nested past the parser's depth is an uncaught RecursionError",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:", "    except (UnicodeDecodeError, json.JSONDecodeError) as exc:"),
          ("A5-deep-value-crashes", "a parsed value too deep to walk crashes the record check",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",),
           "        except (canonical.CanonicalizationError, RecursionError) as exc:", "        except canonical.CanonicalizationError as exc:"),
          ("A5-unbounded-repr", "gen-1 values are quoted in issue text whole, however large (plain repr)",
           ("DryRunMappingTest.test_malformed_fields_are_reported_and_the_report_is_still_produced",), "_show = _SHOW.repr\n", "_show = repr\n"),
          ("A5-obligation-fields-dropped", "obligation fields with no mapping are dropped silently", ("DryRunMappingTest.test_obligations_sources_and_logs",),
           "        extra = _unmapped_fields(obl, OBLIGATION_MAPPED)\n        if extra:", "        extra = _unmapped_fields(obl, OBLIGATION_MAPPED)\n        if False:"),
          # --- 0b repair-2 A5-R1: text that is not valid Unicode is reported, escaped, never substituted ---
          ("A5R1-item-id-unchecked", "the review's probe: a queue id holding a lone surrogate is mapped, into the topic id, refs and paths",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), '        elif not _is_text(item["id"]):', "        elif False:"),
          ("A5R1-ref-not-escaped", "the review's probe: a ref quoting a lone surrogate (from a status) reaches the report as it is",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), '    ref = _text(ref, "ref", escaped)\n', ""),
          ("A5R1-issue-text-not-escaped", "the review's probe: issue text quoting a lone surrogate (from an unknown key) reaches the report as it is",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), '            issue[field] = _text(issue[field], f"issues[{n}].{field}", escaped)\n', "            pass\n"),
          ("A5R1-escape-unreported", "a record's text is escaped with no issue saying so (the locator passes for the name)",
           ("CommandTest.test_the_reviews_invalid_unicode_probes_get_a_report", "CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map"), "    if escaped:\n        issues.append(_escaped_issue(", "    if False:\n        issues.append(_escaped_issue("),
          ("A5R1-escape-not-reversible", "backslashes are not doubled, so an escaped lone surrogate reads the same as a written backslash-u",
           ("CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map",), r'    return text.replace("\\", "\\\\").encode(', "    return text.encode("),
          ("A5R1-source-key-kept", "a source path that is not valid Unicode stays a key of sources",
           ("CommandTest.test_invalid_unicode_is_reported_beside_records_that_still_map",), "        if _is_text(path) and _is_text(status):", "        if True:"),
          ("A5R1-root-not-escaped", "a gen-1 root path that is not UTF-8 reaches the report as it is",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), '    root = _text(str(reader.root), "gen1_root", escaped)', "    root = str(reader.root)"),
          ("A5R1-fleet-not-escaped", "a fleet holding a lone surrogate reaches the report as it is",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), '    fleet_id = None if fleet is None else _text(fleet, "fleet_id", escaped)', "    fleet_id = fleet"),
          ("A5R1-blocking-text-not-escaped", "a blocking issue quoting a root path that is not UTF-8 reaches the report as it is",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), '            issue[field] = _text(issue[field], f"blocking[{n}].{field}", escaped)\n', "            pass\n"),
          ("A5R1-report-escape-unreported", "the report's own fields are escaped with no blocking issue saying so",
           ("CommandTest.test_a_root_path_or_fleet_that_is_not_valid_unicode_is_reported",), "    if escaped:\n        blocking.append(_escaped_issue(", "    if False:\n        blocking.append(_escaped_issue("),
          # --- 0b repair-2 A5-R2: a numeral the parser cannot convert is reported, never fatal ---
          ("A5R2-int-limit-uncaught", "the review's probe: a 4,301-digit integer escapes the parser as a ValueError (no integer hook)",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), ", parse_float=_gen1_float, parse_int=_gen1_int)", ", parse_float=_gen1_float)"),
          ("A5R2-oversize-int-zeroed", "an integer past the conversion limit is read as 0, not refused",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), '        raise Gen1ParseError(f"an integer numeral of', '        return 0\n        raise Gen1ParseError(f"an integer numeral of'),
          ("A5R2-limit-lifted", "the fix the review forbids: the integer-conversion limit is lifted for the parse (then restored), so the numeral is converted",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",),
           '        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant, parse_float=_gen1_float, parse_int=_gen1_int)\n',
           '        limit = __import__("sys").get_int_max_str_digits()\n        __import__("sys").set_int_max_str_digits(0)\n        try:\n'
           '            return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant, parse_float=_gen1_float, parse_int=_gen1_int)\n'
           '        finally:\n            __import__("sys").set_int_max_str_digits(limit)\n'),
          ("A5R2-exponent-uncaught", "an exponent past Decimal's range escapes the parser as InvalidOperation",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), "    except InvalidOperation:\n        raise Gen1ParseError(", "    except ZeroDivisionError:\n        raise Gen1ParseError("),
          ("A5R2-overflow-unparseable", "an exponent so large the number overflows makes the file unparseable instead of an inexact numeral on its record",
           ("CommandTest.test_numerals_the_parser_cannot_convert_are_reported_not_fatal",), '    if value != value or value in (float("inf"), float("-inf")):\n        return InexactNumeral(token)\n', ""))),
    # --- task 1a / V-10: a gen-1 disposition never imports as accepted support ---
    *(Mutation(f"V10-importer-{key}", "1a", desc, ("test_importer.DryRunMappingTest.test_no_gen1_disposition_imports_as_accepted_support",),
               target="gen2/importer/dry_run.py", old=old, new=new)
      for key, desc, old, new in (
          ("maps-disposition", "gen-1's agent-written 'supported' disposition is mapped as an accepted-support claim status",
           '"obligations", {"obligation_id": oid, "text": text if isinstance(text, TEXT_OR_NULL) else None}, issues))',
           '"obligations", {"obligation_id": oid, "text": text if isinstance(text, TEXT_OR_NULL) else None, '
           '"claim_status": "accepted_support" if disposition == "supported" else "provisional"}, issues))'),
          ("report-omits-admission", "the report states only the receipt condition, not contract-admitted production",
           '"contract-admitted production (V-10) and, for a load-bearing claim, a verification receipt (V-4), and gen-1 work has neither"',
           '"a verification receipt (V-4)"'))),
    *(Mutation(f"IMP-graph-{key}", "0b-importer", desc, (CB + "test_importer_cannot_reach_a_store_under_the_real_graph",), target="gen2/boundaries.toml",
               old='may_import = ["core"]\nstdlib_capabilities = []\nthird_party = []\n\n[modules.operator]', new=new)
      for key, desc, new in (
          ("store-granted", "the boundary graph lets the importer import the store (and so write a gen-2 store)",
           'may_import = ["core", "store"]\nstdlib_capabilities = []\nthird_party = []\n\n[modules.operator]'),
          ("sqlite-granted", "the boundary graph grants the importer sqlite3",
           'may_import = ["core"]\nstdlib_capabilities = ["sqlite3"]\nthird_party = []\n\n[modules.operator]'))),
    # --- 0b cleanup 2: the permanent reversed-trigger-order check ----------------------
    *(Mutation(f"TO-{key}", "0b-cleanup-2", desc, tuple("test_trigger_order_tool.TriggerOrderToolTest." + k for k in killers),
               target="tools/gen2_trigger_order.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("not-reversed", "the rebuild re-creates the triggers in their original order",
           ("test_rebuild_creates_the_same_triggers_in_reverse",), r'"\n".join(reversed(blocks))', r'"\n".join(blocks)'),
          ("rebuild-order-unchecked", "a rebuild that did not reverse the order is not detected",
           ("test_a_rebuild_that_keeps_the_order_is_refused",), "    if r_order != list(reversed(order)):", "    if False:"),
          ("rebuild-triggers-unchecked", "a rebuild that lost or changed a trigger is not detected",
           ("test_a_rebuild_that_keeps_the_order_is_refused",), "    if r_sql != sql:", "    if False:"),
          ("differences-ignored", "outcomes that differ between the two orders are not reported",
           ("test_outcomes_must_be_green_and_identical",), "        if a != b:", "        if False:"),
          ("original-failures-ignored", "a failure in the original order is not reported when both orders agree",
           ("test_outcomes_must_be_green_and_identical",), '        if outcome != "pass":', "        if False:"))),
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
          ("claims_accepted_support_needs_receipt", (VT + "test_accepted_support_needs_receipt_at_required_tier", CS + "test_contract_admitted_claim_without_a_receipt_is_refused")),
          ("connector_watermarks_never_regress", (D + "ExportOutboxTest.test_connector_watermark_never_regresses",)),
          ("invocations_start_admitted", (LT + "test_invocations_start_admitted",)),
          ("leases_generation_increases", (D + "LeaseFencingTest.test_generation_strictly_increases_per_topic",)),
          ("leases_release_final_identity_immutable", (D + "LeaseFencingTest.test_release_is_write_once",)),
          ("queue_state_revision_advances_by_one", (D + "CommitFencingTest.test_state_revision_advances_by_exactly_one",)),
          ("contract_status_forward_only", (D + "ContractGovernanceTest.test_contract_content_immutable_never_deleted", CG + "test_approval_pointer_is_set_only_by_the_approval_transition")),
          ("claims_start_provisional", (VT + "test_claims_start_provisional",)),
          ("retrieval_events_from_successful_search", (OB + "test_retrieval_events_only_from_successful_searches",)),
          ("review_triggers_handled_is_final", (D + "OrdinalAndTriggerTest.test_trigger_identity_unique_and_handled_is_final",)),
          ("outbox_events_pair_increases", (D + "ExportOutboxTest.test_ordering_pairs_strictly_increase",)),
          ("holds_clear_once_identity_immutable", (D + "HoldTest.test_operator_hold_cleared_only_by_operator_decision", RI + "test_hold_identity_class_and_authority_are_immutable")),
          ("queue_topic_identity_immutable", (RI + "test_topic_identity_is_immutable",)),
          ("review_episodes_close_once", (RI + "test_review_episode_closes_once",)),
          ("claims_identity_immutable", (RI + "test_claim_content_is_immutable_per_revision",)),
          ("works_identity_immutable", (RI + "test_work_identity_is_immutable",)))),
    Mutation("D48-any-declared-connector", "A2", "the review's surviving mutant, carried (0d): any connector of a declared type accepted, not just the ones the manifest names",
             (D + "ExportOutboxTest.test_delivery_receipt_only_for_named_connectors",), scope="export_delivery_receipts_expected_connector",
             old="WHEN NOT EXISTS (\n  SELECT 1 FROM outbox_events e, json_each(e.expected_connectors) j\n  WHERE e.manifest_id = NEW.manifest_id AND j.key = NEW.connector_id\n    AND json_extract(j.value, '$.connector_type') IS NEW.connector_type)",
             new="WHEN NEW.connector_type NOT IN ('sql', 'jsonl_file', 'webhook', 'extension')"),
    Mutation("D48-expected-connector-dropped", "A2", "drop the expected-connector trigger", (D + "ExportOutboxTest.test_delivery_receipt_only_for_named_connectors",),
             drop_trigger="export_delivery_receipts_expected_connector"),
    Mutation("D48-connector-type-unmatched", "0d", "a receipt may name the manifest's connector under another type",
             (D + "ExportOutboxTest.test_delivery_receipt_only_for_named_connectors",), scope="export_delivery_receipts_expected_connector",
             old="\n    AND json_extract(j.value, '$.connector_type') IS NEW.connector_type)", new=")"),
    # --- 0d: the export tables (operator ruling 2026-09-26) ---------------------
    # outbox_events is the export-manifest table; export_delivery_receipts and
    # connector_watermarks replace the per-sink tables. Each mutant removes one
    # rule, and its test's probe for that rule is the only one it admits.
    *(Mutation(f"0D-{key}", "0d", desc, (D + X + killer,), old=old, new=new, scope=scope)
      for key, desc, killer, scope, old, new in (
          ("pair-lower-generation-admitted", "a lower generation is admitted when its options revision is higher",
           "test_ordering_pairs_strictly_increase", "outbox_events_pair_increases",
           "    AND (e.generation > NEW.generation\n         OR (e.generation = NEW.generation AND e.options_revision >= NEW.options_revision)))",
           "    AND ((e.generation = NEW.generation AND e.options_revision >= NEW.options_revision)))"),
          ("pair-lower-options-admitted", "a lower options revision of the same generation is admitted",
           "test_ordering_pairs_strictly_increase", "outbox_events_pair_increases",
           "    AND (e.generation > NEW.generation\n         OR (e.generation = NEW.generation AND e.options_revision >= NEW.options_revision)))",
           "    AND (e.generation > NEW.generation))"),
          ("one-generation-another-approved-revision", "a re-export of a generation may carry another approved revision (source, hash and approval together)",
           "test_one_generation_is_one_approved_revision", "outbox_events_generation_is_one_approved_revision",
           "    AND (e.source_revision IS NOT NEW.source_revision\n         OR e.source_content_hash IS NOT NEW.source_content_hash\n"
           "         OR e.approval_decision_id IS NOT NEW.approval_decision_id\n         OR e.artifact_kind",
           "    AND (e.artifact_kind"),
          ("one-generation-another-approval", "a re-export of a generation may cite another approval of the same revision",
           "test_one_generation_is_one_approved_revision", "outbox_events_generation_is_one_approved_revision",
           "\n         OR e.approval_decision_id IS NOT NEW.approval_decision_id", ""),
          ("one-generation-another-kind", "a re-export of a generation may change its artifact kind",
           "test_one_generation_is_one_approved_revision", "outbox_events_generation_is_one_approved_revision",
           "\n         OR e.artifact_kind IS NOT NEW.artifact_kind))", "))"),
          ("connector-types-widened", "the manifest trigger admits a store kind as a connector type",
           "test_manifest_names_only_declared_connector_types", "outbox_events_connectors_declared",
           "        NOT IN ('sql', 'jsonl_file', 'webhook', 'extension'))", "        NOT IN ('sql', 'jsonl_file', 'webhook', 'extension', 'graph_store'))"),
          ("connectors-need-not-be-an-object", "expected_connectors may be an array (the retired expected_sinks shape)",
           "test_manifest_names_only_declared_connector_types", None, "AND json_type(expected_connectors) = 'object' ", ""),
          ("connectors-may-be-empty", "a manifest may name no connector",
           "test_manifest_names_only_declared_connector_types", None, " AND json(expected_connectors) != '{}'", ""),
          ("supersedes-pair-incomplete", "a superseded generation may be stored without its options revision",
           "test_supersession_names_a_lower_pair", None,
           "\n  CHECK ((supersedes_generation IS NULL) = (supersedes_options_revision IS NULL)),", ""),
          ("supersedes-generation-floor", "a manifest may supersede generation 0",
           "test_supersession_names_a_lower_pair", None,
           "OR (supersedes_generation >= 1 AND supersedes_options_revision >= 1\n", "OR (supersedes_options_revision >= 1\n"),
          ("supersedes-options-floor", "a manifest may supersede options revision 0",
           "test_supersession_names_a_lower_pair", None,
           "OR (supersedes_generation >= 1 AND supersedes_options_revision >= 1\n", "OR (supersedes_generation >= 1\n"),
          ("supersedes-a-later-generation", "a manifest may supersede a later generation",
           "test_supersession_names_a_lower_pair", None,
           "         AND (supersedes_generation < generation\n", "         AND (1\n"),
          ("supersedes-its-own-pair", "a manifest may supersede its own pair",
           "test_supersession_names_a_lower_pair", None,
           "supersedes_options_revision < options_revision)))", "supersedes_options_revision <= options_revision)))"),
          ("receipt-status-queued", "a receipt may say `queued` (durable enqueueing counted as delivery state)",
           "test_receipt_status_rules", None,
           "status IN ('delivered', 'failed', 'skipped_superseded', 'outcome_unknown')",
           "status IN ('delivered', 'failed', 'skipped_superseded', 'outcome_unknown', 'queued')"),
          ("receipt-failure-without-class", "a failure need not name its class (carried publication CHECK)",
           "test_receipt_status_rules", "export_delivery_receipts", "\n  CHECK (status != 'failed' OR error_class IS NOT NULL),", ""),
          ("receipt-class-on-a-settled-non-failure", "an error class may ride on a delivery",
           "test_receipt_status_rules", None, "\n  CHECK (error_class IS NULL OR status = 'failed'),", ""),
          ("receipt-unreadable-response-is-a-class", "unreadable_response is a failure class (A2, restored in the store)",
           "test_receipt_status_rules", None, "'conflict', 'partial_write'))", "'conflict', 'partial_write', 'unreadable_response'))"),
          ("receipt-delivered-without-ack", "a delivery need not carry its acknowledgement time (carried publication CHECK)",
           "test_receipt_status_rules", "export_delivery_receipts",
           "CHECK (status != 'delivered' OR (acked_at IS NOT NULL AND tombstones_acknowledged = 1))",
           "CHECK (status != 'delivered' OR (tombstones_acknowledged = 1))"),
          ("receipt-delivered-without-tombstones", "a delivery need not acknowledge its tombstones (carried publication CHECK)",
           "test_receipt_status_rules", "export_delivery_receipts",
           "CHECK (status != 'delivered' OR (acked_at IS NOT NULL AND tombstones_acknowledged = 1))",
           "CHECK (status != 'delivered' OR (acked_at IS NOT NULL))"),
          ("receipt-ack-on-a-non-delivery", "a failure may carry an acknowledgement time",
           "test_receipt_status_rules", None, "\n  CHECK (acked_at IS NULL OR status = 'delivered'),", ""),
          ("receipt-tombstones-on-a-non-delivery", "a skipped delivery may claim its tombstones were acknowledged",
           "test_receipt_status_rules", None, "\n  CHECK (tombstones_acknowledged = 0 OR status = 'delivered'),", ""),
          ("receipt-unknown-without-cause", "an unknown outcome need not say why",
           "test_receipt_status_rules", None,
           "CHECK ((unknown_cause IS NOT NULL) = (status = 'outcome_unknown'))", "CHECK (unknown_cause IS NULL OR status = 'outcome_unknown')"),
          ("receipt-cause-on-a-settled-result", "a settled result may carry an unknown cause",
           "test_receipt_status_rules", None,
           "CHECK ((unknown_cause IS NOT NULL) = (status = 'outcome_unknown'))", "CHECK (status != 'outcome_unknown' OR unknown_cause IS NOT NULL)"),
          ("receipt-cause-vocabulary-widened", "an unknown cause may be a failure class",
           "test_receipt_status_rules", None,
           "'unreadable_response', 'unauthoritative_response'))", "'unreadable_response', 'unauthoritative_response', 'timeout'))"),
          ("receipt-unknown-not-reconciled", "an unknown outcome need not be reconciled (P-7)",
           "test_receipt_status_rules", None,
           "CHECK (reconciliation_required = (status = 'outcome_unknown'))", "CHECK (reconciliation_required = 0 OR status = 'outcome_unknown')"),
          ("receipt-reconciliation-on-a-settled-result", "reconciliation may be left open on a settled result",
           "test_receipt_status_rules", None,
           "CHECK (reconciliation_required = (status = 'outcome_unknown'))", "CHECK (reconciliation_required = 1 OR status != 'outcome_unknown')"),
          ("receipt-failure-without-fact", "a failure need not raise a capability fact (H-2)",
           "test_receipt_status_rules", None,
           "status NOT IN ('failed', 'outcome_unknown') OR capability_fact_id IS NOT NULL", "status NOT IN ('outcome_unknown') OR capability_fact_id IS NOT NULL"),
          ("receipt-unknown-without-fact", "an unknown outcome need not raise a capability fact (H-2)",
           "test_receipt_status_rules", None,
           "status NOT IN ('failed', 'outcome_unknown') OR capability_fact_id IS NOT NULL", "status NOT IN ('failed') OR capability_fact_id IS NOT NULL"),
          ("receipt-fact-on-a-delivery", "a delivery may carry a capability fact",
           "test_receipt_status_rules", None,
           ",\n  CHECK (status != 'delivered' OR capability_fact_id IS NULL)\n) STRICT;", "\n) STRICT;"),
          ("receipt-connector-id-unshaped", "a receipt may name a connector id that is not a legal id",
           "test_connector_ids_are_well_formed", "export_delivery_receipts",
           "connector_id TEXT NOT NULL CHECK (connector_id GLOB '[a-z]*' AND connector_id NOT GLOB '*[^a-z0-9-]*' AND connector_id NOT GLOB '*-' AND length(connector_id) <= 64),",
           "connector_id TEXT NOT NULL,"),
          ("watermark-connector-id-unshaped", "a watermark may be kept under a connector id that is not a legal id (replaces the product-vocabulary CHECK)",
           "test_connector_ids_are_well_formed", "connector_watermarks",
           "connector_id TEXT NOT NULL CHECK (connector_id GLOB '[a-z]*' AND connector_id NOT GLOB '*[^a-z0-9-]*' AND connector_id NOT GLOB '*-' AND length(connector_id) <= 64),",
           "connector_id TEXT NOT NULL,"),
          ("watermark-lower-generation", "a watermark may fall to a lower generation with a higher options revision",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "WHEN NEW.generation < OLD.generation\n  OR (NEW.generation", "WHEN (NEW.generation"),
          ("watermark-lower-options", "a watermark may fall to a lower options revision of the same generation",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "\n  OR (NEW.generation = OLD.generation AND NEW.options_revision < OLD.options_revision)", ""),
          ("watermark-moves-topic", "a watermark may move to another topic",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "\n  OR NEW.topic_id IS NOT OLD.topic_id OR NEW.connector_id IS NOT OLD.connector_id", "\n  OR NEW.connector_id IS NOT OLD.connector_id"),
          ("watermark-moves-connector", "a watermark may move to another connector",
           "test_connector_watermark_never_regresses", "connector_watermarks_never_regress",
           "\n  OR NEW.topic_id IS NOT OLD.topic_id OR NEW.connector_id IS NOT OLD.connector_id", "\n  OR NEW.topic_id IS NOT OLD.topic_id"),
      )),
    # --- 1b-repair A2: the whole delivery receipt, bound to its columns (EXPORT-API.md §9 item 3) ---
    Mutation("1BR-receipt-binds-version", "1b-A2", "a delivery receipt's document need not be export-delivery-receipt/2",
             (D + X + "test_receipt_document_matches_its_columns",), scope="export_delivery_receipts",
             old="CHECK (json_extract(receipt, '$.receipt_version') IS 'export-delivery-receipt/2'\n     AND ", new="CHECK ("),
    *(Mutation(f"1BR-receipt-binds-{key}", "1b-A2", f"a delivery receipt's document is no longer bound to its {col} column",
               (D + X + "test_receipt_document_matches_its_columns",), scope="export_delivery_receipts",
               old=f"\n     AND json_extract(receipt, '$.{path}') IS {col}", new="")
      for key, path, col in (("receipt-id", "export_receipt_id", "export_receipt_id"), ("manifest", "manifest_id", "manifest_id"),
                             ("connector-id", "connector.connector_id", "connector_id"), ("connector-type", "connector.connector_type", "connector_type"),
                             ("attempt", "attempt", "attempt"), ("status", "status", "status"), ("tombstones", "tombstones_acknowledged", "tombstones_acknowledged"),
                             ("reconciliation", "reconciliation_required", "reconciliation_required"), ("error-class", "error_class", "error_class"),
                             ("unknown-cause", "unknown_cause", "unknown_cause"), ("capability-fact", "capability_fact_id", "capability_fact_id"),
                             ("written-status", "written.status", "written_status"), ("written-value", "written.value", "written_value"),
                             ("hold", "hold_id", "hold_id"), ("attempted-at", "attempted_at", "attempted_at"), ("acked-at", "acked_at", "acked_at"))),
    *(Mutation(f"1BR-{key}", "1b-A2", desc, (D + X + "test_written_count_rules",), scope="export_delivery_receipts", old=old, new=new)
      for key, desc, old, new in (
          ("written-unknown-with-a-value", "an unknown count may carry a value (RG-U: unknown is never zero)",
           "CHECK ((written_value IS NULL) = (written_status = 'unknown')),", "CHECK (written_value IS NOT NULL OR written_status = 'unknown'),"),
          ("written-observed-without-a-value", "an observed or partial count may have no value",
           "CHECK ((written_value IS NULL) = (written_status = 'unknown')),", "CHECK (written_status != 'unknown' OR written_value IS NULL),"),
          ("written-delivery-not-observed", "a delivery or a skipped delivery may report a count it did not observe",
           "\n  CHECK (status NOT IN ('delivered', 'skipped_superseded') OR written_status = 'observed'),", ""),
          ("written-skipped-wrote", "a skipped delivery may report records written",
           "\n  CHECK (status != 'skipped_superseded' OR written_value = 0),", ""),
          ("written-partial-write-total", "a partial write may claim an observed total",
           "\n  CHECK (status != 'failed' OR error_class IS NOT 'partial_write' OR written_status = 'partial'),", ""),
          ("written-refusal-wrote", "a failure that applied nothing may report records written",
           "(written_status = 'observed' AND written_value = 0)),", "(written_status = 'observed')),"),
          ("written-refusal-partial", "a failure that applied nothing may report a partial count",
           "(written_status = 'observed' AND written_value = 0)),", "(written_value = 0)),"),
          ("written-unknown-observed", "an unknown outcome may claim an observed count (P-7)",
           "\n  CHECK (status != 'outcome_unknown' OR written_status IN ('unknown', 'partial')),", ""),
      )),
    Mutation("1BR-receipt-describes-manifest-dropped", "1b-A2", "a receipt may report another topic, pair or hold than its manifest's",
             (D + X + "test_receipt_describes_its_manifest",), drop_trigger="export_delivery_receipts_describe_their_manifest"),
    *(Mutation(f"1BR-receipt-describes-{key}", "1b-A2", desc, (D + X + "test_receipt_describes_its_manifest",),
               scope="export_delivery_receipts_describe_their_manifest", old=old, new=new)
      for key, desc, old, new in (
          ("topic", "a receipt may report another topic than its manifest's", "\n    AND e.topic_id IS json_extract(NEW.receipt, '$.topic_id')", ""),
          ("generation", "a receipt may report another generation", "\n    AND e.generation IS json_extract(NEW.receipt, '$.generation')", ""),
          ("options-revision", "a receipt may report another options revision", "\n    AND e.options_revision IS json_extract(NEW.receipt, '$.options_revision')", ""),
          ("hold", "a receipt may name a hold that is not recorded",
           "\n    AND (NEW.hold_id IS NULL OR EXISTS (SELECT 1 FROM holds h WHERE h.hold_id = NEW.hold_id AND h.topic_id = e.topic_id)))", ")"),
          ("hold-topic", "a receipt may name another topic's hold", " AND h.topic_id = e.topic_id", ""),
      )),
    Mutation("0D-one-generation-dropped", "0d", "drop the one-generation-one-approved-revision trigger",
             (D + X + "test_one_generation_is_one_approved_revision",), drop_trigger="outbox_events_generation_is_one_approved_revision"),
    Mutation("0D-connectors-declared-dropped", "0d", "drop the declared-connector-type trigger (the store's undeclared-type negative)",
             (D + X + "test_manifest_names_only_declared_connector_types",), drop_trigger="outbox_events_connectors_declared"),
    Mutation("A1-D01-live-lease-replace", "A1", "drop leases delete guard (REPLACE of the live lease)", (D + "LeaseFencingTest.test_one_live_lease_per_topic_and_scope_until_released",),
             drop_trigger="leases_no_delete"),
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
    # --- 0c: the registry/artifact drift gate (task 0c deliverable 2, Gate C) ------
    # Each of these is a way the drift check could stop meaning anything while
    # `make gen2-check` still passed. The named tests must notice every one.
    *(Mutation(f"0C-{key}", "0c-drift", desc, tuple(SC + k for k in killers),
               target="tools/gen_source_catalog.py", old=old, new=new)
      for key, desc, killers, old, new in (
          ("comparison-removed", "the check stops comparing the artifacts with the registry (it only reports success)",
           ("test_a_new_credentialled_source_makes_both_artifacts_stale",
            "test_deleting_a_secret_line_from_the_env_example_is_drift",
            "test_a_hand_edited_catalog_is_drift",
            "test_a_registry_change_with_no_secret_effect_is_still_drift"),
           "                if current != expected:", "                if False:"),
          ("missing-artifact-unreported", "a missing artifact is no longer reported (the checker crashes on it instead)",
           ("test_a_missing_artifact_is_reported_not_crashed_on",), "            if not path.exists():", "            if False:"),
          ("env-not-checked", "the check covers only the first artifact, so the .env example may drift freely",
           ("test_deleting_a_secret_line_from_the_env_example_is_drift",
            "test_a_missing_artifact_is_reported_not_crashed_on"),
           "        for path, expected in artifacts:\n            if not path.exists():",
           "        for path, expected in artifacts[:1]:\n            if not path.exists():"),
          ("unknown-auth-accepted", "an auth kind the generator cannot map is accepted instead of refused",
           ("test_an_unknown_auth_kind_is_refused_rather_than_emitted_without_its_key",),
           "        if auth not in AUTH_SECRETS:", "        if False:"),
          ("empty-secret-ref-accepted", "a credentialled source with no secret_ref is accepted (its key vanishes)",
           ("test_a_credentialled_source_without_a_secret_ref_is_refused",),
           "            if AUTH_SECRETS[auth] and not ref:", "            if False:"),
          ("stray-secret-ref-accepted", "a secret_ref on a source that reads no credential is silently dropped",
           ("test_a_secret_ref_on_a_source_that_reads_no_credential_is_refused",),
           "            if not AUTH_SECRETS[auth] and ref:", "            if False:"),
          ("illegal-variable-name-accepted", "a secret_ref that cannot spell an environment variable is accepted",
           ("test_a_secret_ref_that_is_not_a_legal_variable_name_is_refused",),
           "                if not name.replace(\"_\", \"A\").isalnum() or not name[0].isalpha() or name != name.upper():",
           "                if False:"),
          ("shared-ref-conflict-ignored", "one secret_ref shared by sources that read it differently is accepted",
           ("test_one_secret_ref_shared_with_two_different_auth_kinds_is_refused",),
           "        if len(auths) > 1:", "        if False:"),
          ("required-fields-unchecked", "a source missing a required field is rendered with blanks",
           ("test_a_missing_required_field_is_refused",), "            if key not in s:", "            if False:"),
          ("duplicate-id-accepted", "two rows with one id are accepted",
           ("test_a_duplicate_source_id_is_refused",), "        if sid in seen:", "        if False:"),
          ("invalid-problems-ignored", "validation runs but its findings no longer stop generation",
           ("test_an_unknown_auth_kind_is_refused_rather_than_emitted_without_its_key",
            "test_a_credentialled_source_without_a_secret_ref_is_refused",
            "test_a_missing_required_field_is_refused"),
           "    if problems:\n        print(f\"CATALOG ERROR: {registry} cannot produce a complete catalog and .env example:\", file=sys.stderr)",
           "    if False:\n        print(f\"CATALOG ERROR: {registry} cannot produce a complete catalog and .env example:\", file=sys.stderr)"),
          ("optional-emitted-live", "an optional credential is emitted as a live line, so a blank looks configured",
           ("test_required_credentials_are_live_lines_and_optional_ones_are_commented",),
           "            out.append(f\"{'' if s.required else '# '}{s.var}=example-{s.secret_ref.replace('_', '-')}\"",
           "            out.append(f\"{s.var}=example-{s.secret_ref.replace('_', '-')}\""),
          ("multi-field-collapsed", "a multi-field credential emits one unsuffixed variable",
           ("test_multi_field_credentials_emit_one_variable_per_field",),
           '    return f"{name}_{field.upper()}" if field else name', "    return name"),
          ("cost-cap-not-reported", "a recorded cost cap is not reported, so a metered source reads as uncapped",
           ("test_a_cost_cap_in_the_registry_is_reported_as_metered",),
           '    if rate.get("cost_cap_per_day"):', "    if False:"),
      )),
    # --- 0c-repair: schema rules, each with a negative that fails for it alone ----
    # Astra 0c review C1: a negative whose declared (keyword, path) is also
    # produced by another rule survives removal of its own rule. Each mutant
    # deletes one rule from a schema; the whole tree is re-checked with the
    # mutated file, and the named negative must stop behaving as declared (it
    # validates). The bundle's mixed rule is two rules, mutated separately.
    *(Mutation(f"0CR-{key}", finding, desc, tuple(SF + k for k in killers), target=target, old=old, new=new)
      for key, finding, desc, killers, target, old, new in (
          ("mixed-hold-list-not-required", "C1", "a mixed disposition no longer requires its hold list (the review's surviving mutant)",
           ("test_a_mixed_disposition_without_its_hold_list_is_refused",), "gen2/schema/export-bundle.schema.json",
           '"then": {"required": ["open_adjudication_hold_ids"], "properties": {"open_adjudication_hold_ids": {"minItems": 1}}}',
           '"then": {"properties": {"open_adjudication_hold_ids": {"minItems": 1}}}'),
          ("mixed-hold-list-may-be-empty", "A3", "a mixed disposition's hold list may be empty",
           ("test_a_mixed_disposition_with_an_empty_hold_list_is_refused",), "gen2/schema/export-bundle.schema.json",
           '"then": {"required": ["open_adjudication_hold_ids"], "properties": {"open_adjudication_hold_ids": {"minItems": 1}}}',
           '"then": {"required": ["open_adjudication_hold_ids"]}'),
          ("partial-write-count-unconstrained", "A4", "a partial_write failure may report an observed total (the review's substitution)",
           ("test_a_partial_write_claiming_an_observed_total_is_refused",), RECEIPT,
           '"then": {"properties": {"written": {"properties": {"status": {"const": "partial"}}}}}', '"then": {}'),
          ("settled-failure-count-unconstrained", "A2", "a failure other than a partial write may report any count, an unknown one included",
           ("test_a_failure_whose_count_is_unknown_is_refused", "test_a_refusal_claiming_it_wrote_records_is_refused",
            "test_the_reviews_unreadable_response_reproduction_is_refused_twice"), RECEIPT,
           '"then": {"properties": {"written": {"properties": {"status": {"const": "observed"}, "value": {"const": 0}}}}}', '"then": {}'),
          ("unreadable-response-is-a-failure-class", "A2", "unreadable_response is a settled failure's class again",
           ("test_an_unreadable_response_is_not_a_failure_class", "test_the_reviews_unreadable_response_reproduction_is_refused_twice"), RECEIPT,
           '"partial_write"]\n    },\n    "unknown_cause"', '"partial_write", "unreadable_response"]\n    },\n    "unknown_cause"'),
          ("unknown-cause-not-required", "A2", "an unknown outcome need not say why it is unknown",
           ("test_an_unknown_outcome_without_a_cause_is_refused",), RECEIPT,
           '"required": ["capability_fact_id", "unknown_cause"],', '"required": ["capability_fact_id"],'),
          ("unknown-cause-on-a-settled-result", "A2", "a settled result may carry an unknown cause",
           ("test_a_settled_result_carrying_an_unknown_cause_is_refused",), RECEIPT,
           '"if": {"required": ["unknown_cause"]},\n      "then": {"properties": {"status": {"const": "outcome_unknown"}}}',
           '"if": {"required": ["unknown_cause"]},\n      "then": {}'),
          # The audit of every other negative for the same collapse found four
          # (0a fixtures). The checker now counts errors (below); these show
          # each hidden rule is noticed on its own. intake-brief's
          # invalid-version-zero states one floor twice, so it has no mutant.
          ("abstention-artifact-not-required", "C1-audit", "an abstention no longer needs its raw response artifact",
           ("test_an_abstention_that_discards_its_raw_artifact_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           '"then": {"properties": {"raw_response_digest": {"type": "string"}, "raw_response_artifact": {"type": "object"}}}}',
           '"then": {"properties": {"raw_response_digest": {"type": "string"}}}}'),
          ("digest-without-artifact", "C1-audit", "a raw response digest may travel without its artifact",
           ("test_an_abstention_that_discards_its_raw_artifact_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           '"then": {"properties": {"raw_response_artifact": {"type": "object"}}},\n          "else"', '"else"'),
          ("shadow-may-commit", "C1-audit", "shadow_log_only no longer forbids a commit operation",
           ("test_a_shadow_receipt_with_a_commit_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           '"then": {"properties": {"outcome": {"properties": {"commit_operation_id": {"type": "null"}, "proposal_ref": {"type": "null"}, "hold_id": {"type": "null"}}}}}}',
           '"then": {"properties": {"outcome": {"properties": {"proposal_ref": {"type": "null"}, "hold_id": {"type": "null"}}}}}}'),
          ("non-commit-action-may-commit", "C1-audit", "an action other than commit_reversible_action may carry a commit operation",
           ("test_a_shadow_receipt_with_a_commit_is_refused_by_both_rules",), "gen2/schema/decision-receipt.schema.json",
           ',\n         "else": {"properties": {"outcome": {"properties": {"commit_operation_id": {"type": "null"}}}}}}', "}"),
          # Each identity member's removal: its own one-error negative now
          # validates, and the bare-identity count drops from three to two.
          *((f"identity-{member.replace('_', '-')}-not-required", "C1-audit", f"a running invocation's identity no longer requires {member}",
             (IDENTITY_KILLER[member], "test_a_bare_process_identity_is_refused_three_times"), "gen2/schema/invocation.schema.json",
             '"required": ["job_handle", "host_id", "container_id", "boot_id", "start_fingerprint"]',
             '"required": ' + json.dumps([m for m in IDENTITY if m != member]))
            for member in IDENTITY_KILLER),
          # Astra 0c-repair re-review BLOCK 3: drop one member and require
          # another twice. The bare-identity negative still reports three
          # `required` errors, so its count cannot see this (it survives).
          # The dropped member's own negative validates; the doubled one's
          # reports two errors where it declares one. The first is the
          # review's mutant, the other two its rotations.
          *((f"identity-{dropped.replace('_', '-')}-traded-for-a-second-{doubled.replace('_', '-')}", "C1-audit",
             f"identity stops requiring {dropped} and requires {doubled} twice, so the bare-identity count is unchanged",
             (IDENTITY_KILLER[dropped], IDENTITY_KILLER[doubled]), "gen2/schema/invocation.schema.json",
             '"required": ["job_handle", "host_id", "container_id", "boot_id", "start_fingerprint"],',
             '"required": ' + json.dumps([m for m in IDENTITY if m != dropped])
             + ',\n      "allOf": [{"required": ["' + doubled + '"]}],')
            for dropped, doubled in (("host_id", "boot_id"), ("boot_id", "start_fingerprint"), ("start_fingerprint", "host_id"))),
      )),
    # --- 0d: the one export API (operator ruling 2026-09-26) -------------------
    # export-manifest/2 absorbs publication-manifest/1 and export-manifest/1;
    # freshness-envelope/2 is re-scoped to engine reads of the local record.
    # Each mutant removes one rule (or restores a retired one) and the named
    # isolated negative must validate - or, for the over-restriction mutant, the
    # positive it names must stop validating.
    *(Mutation(f"0D-{key}", "0d", desc, tuple(SF + k for k in killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("connector-types-open-to-a-store-name", "the closed connector vocabulary gains a store kind (the retired named-store-as-sink shape)",
           ("test_an_undeclared_connector_type_is_refused",), "gen2/schema/common.schema.json",
           '"enum": ["sql", "jsonl_file", "webhook", "extension"]', '"enum": ["sql", "jsonl_file", "webhook", "extension", "graph_store"]'),
          ("manifest-connector-type-any-string", "the manifest stops using the closed connector vocabulary",
           ("test_an_undeclared_connector_type_is_refused",), MANIFEST,
           '"connector_type": {"$ref": "common.schema.json#/$defs/connector_type"},', '"connector_type": {"type": "string"},'),
          ("extension-implementation-not-required", "an extension connector need not name its implementation and review",
           ("test_an_extension_connector_without_its_implementation_is_refused",), MANIFEST,
           '{"if": {"properties": {"connector_type": {"const": "extension"}}}, "then": {"required": ["implementation"]}},\n', ''),
          ("reference-connector-may-claim-an-implementation", "a reference connector may name a module and a review",
           ("test_a_reference_connector_claiming_an_implementation_is_refused",), MANIFEST,
           ',\n          {"if": {"properties": {"connector_type": {"enum": ["sql", "jsonl_file", "webhook"]}}},\n           "then": {"not": {"required": ["implementation"]}}}', ''),
          ("connector-id-pattern-dropped", "a connector id need not spell its secret variable's suffix",
           ("test_a_connector_id_that_cannot_spell_its_variable_is_refused",), MANIFEST,
           '"propertyNames": {"$ref": "common.schema.json#/$defs/connector_id"},\n', ''),
          ("export-for-no-connector", "a manifest may name no connector",
           ("test_an_export_for_no_connector_is_refused",), MANIFEST,
           '"minProperties": 1,\n      "maxProperties": 100,', '"maxProperties": 100,'),
          ("approval-not-required", "a manifest need not name its approval (P-5)",
           ("test_an_export_without_an_approval_is_refused",), MANIFEST,
           '    "approval",\n    "bundle",\n', '    "bundle",\n'),
          ("tombstones-without-supersession", "a first manifest may carry tombstones",
           ("test_a_first_manifest_with_tombstones_is_refused",), MANIFEST,
           '"then": {"properties": {"tombstones": {"maxItems": 0}}}', '"then": {}'),
          ("generation-1-may-supersede-another-generation", "generation 1 may supersede a later generation",
           ("test_generation_1_supersedes_only_generation_1",), MANIFEST,
           '"then": {"properties": {"supersedes": {"properties": {"generation": {"const": 1}}}}}', '"then": {}'),
          ("generation-1-supersedes-nothing-restored", "the retired publication rule restored: generation 1 supersedes nothing, refusing a re-export of generation 1",
           ("test_generation_1_supersedes_only_generation_1",), MANIFEST,
           '"then": {"properties": {"supersedes": {"properties": {"generation": {"const": 1}}}}}', '"then": {"properties": {"supersedes": {"type": "null"}}}'),
          ("supersession-without-its-options-revision", "a supersession may name a generation without its options revision",
           ("test_a_supersession_names_its_whole_pair",), MANIFEST,
           '"required": ["manifest_id", "generation", "options_revision"],', '"required": ["manifest_id", "generation"],'),
          ("delivery-state-admitted", "a manifest may carry fields it does not define (delivery state included)",
           ("test_delivery_state_is_not_a_manifest_field",), MANIFEST,
           '"type": "object",\n  "additionalProperties": false,\n  "required": [', '"type": "object",\n  "additionalProperties": true,\n  "required": ['),
          ("publication-manifest-version-admitted", "the retired publication-manifest/1 version is accepted beside export-manifest/2",
           ("test_the_retired_publication_manifest_version_is_refused",), MANIFEST,
           '"manifest_version": {"const": "export-manifest/2"}', '"manifest_version": {"enum": ["export-manifest/2", "publication-manifest/1"]}'),
          ("complete-without-every-connector", "export delivery may be complete while a connector failed (P-4)",
           ("test_complete_export_delivery_needs_every_connector_delivered",), ENVELOPE,
           '"then": {"properties": {"connectors": {"additionalProperties": {"properties": {"status": {"const": "delivered"}}}}}}', '"then": {}'),
          ("delivered-without-its-pair", "a connector may be reported delivered without the pair it holds",
           ("test_a_delivered_connector_names_its_pair",), ENVELOPE,
           '"then": {"properties": {"delivered": {"type": "object"}, "last_successful_delivery_at": {"type": "string"}}}',
           '"then": {"properties": {"last_successful_delivery_at": {"type": "string"}}}'),
          ("projected-revision-restored", "the retired projected_revision field is back, so a read may claim a projection",
           ("test_a_read_cannot_claim_a_projected_revision",), ENVELOPE,
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n',
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n    "projected_revision": {"oneOf": [{"type": "null"}, {"$ref": "common.schema.json#/$defs/revision"}]},\n'),
          ("no-connectors-may-list-one", "no_connectors may list a connector",
           ("test_no_connectors_lists_none",), ENVELOPE,
           '"then": {"properties": {"connectors": {"maxProperties": 0}}},', '"then": {},'),
          ("delivery-status-about-no-connector", "a delivery status other than no_connectors may list no connector",
           ("test_a_delivery_status_is_about_at_least_one_connector",), ENVELOPE,
           '"else": {"properties": {"connectors": {"minProperties": 1}}}', '"else": {}'),
          ("served-without-an-approval", "a read may name an approved revision it served when nothing is approved (P-5)",
           ("test_nothing_approved_means_nothing_served",), ENVELOPE,
           '"then": {"properties": {"approved_revision_served": {"type": "null"}}}', '"then": {}'),
          ("completion-without-a-dossier", "completed may carry no dossier revision (P-4)",
           ("test_completion_is_at_a_dossier_revision",), ENVELOPE,
           '"then": {"properties": {"dossier_revision": {"type": "integer"}, "outcome": {"type": "string"}}}', '"then": {"properties": {"outcome": {"type": "string"}}}'),
          ("current-with-feed-issues", "current currency may list feed issues (P-6)",
           ("test_an_overdue_feed_is_not_current",), ENVELOPE,
           '"then": {"properties": {"as_of": {"type": "string"}, "feed_issues": {"maxProperties": 0}}}', '"then": {"properties": {"as_of": {"type": "string"}}}'),
          ("degraded-without-a-feed", "degraded currency may name no feed (A11)",
           ("test_degraded_currency_names_a_feed",), ENVELOPE,
           '"then": {"properties": {"feed_issues": {"minProperties": 1}}}', '"then": {}'),
          ("feed-reasons-open", "a feed issue may be any string (A11)",
           ("test_feed_issue_reasons_are_closed",), ENVELOPE,
           '"additionalProperties": {"enum": ["overdue", "failed_before_due", "never_ran", "unparseable_payload", "cursor_lost", "unknown"]}',
           '"additionalProperties": {"type": "string"}'),
      )),
    # --- 0d-repair: per-member replacement coverage (Astra 0d review, finding
    # 2). Each rule above had a negative that removed a whole object, so
    # weakening one member of it survived. Each mutant here weakens one member
    # (or restores the retired field in one shape), and its own one-error
    # negative must validate.
    *(Mutation(f"0DR-{key}", "0d-F2", desc, tuple(SF + k for k in killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          ("implementation-module-not-required", "an extension's implementation may omit its module (the review's survivor)",
           ("test_an_extension_implementation_names_its_module",), MANIFEST,
           '"required": ["module", "review_ref"],', '"required": ["review_ref"],'),
          ("implementation-review-not-required", "an extension's implementation may omit its review (the review's survivor)",
           ("test_an_extension_implementation_names_its_review",), MANIFEST,
           '"required": ["module", "review_ref"],', '"required": ["module"],'),
          ("mixed-generation-restored-as-a-boolean", "the retired mixed_generation field is back as a boolean (the review's survivor)",
           ("test_a_read_cannot_claim_mixed_generation",), ENVELOPE,
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n',
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n    "mixed_generation": {"type": "boolean"},\n'),
          ("mixed-generation-restored-as-in-envelope-1", "the retired mixed_generation field is back in its freshness-envelope/1 shape",
           ("test_a_read_cannot_claim_mixed_generation",), ENVELOPE,
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n',
           '    "approval_status": {"enum": ["approved", "no_approved_revision"]},\n'
           '    "mixed_generation": {"type": "object", "additionalProperties": false, "required": ["detected", "resolution"],'
           ' "properties": {"detected": {"type": "boolean"}, "resolution": {"enum": ["not_applicable", "pinned", "degraded"]}}},\n'),
          ("delivered-pair-without-its-options-revision", "a delivered pair may omit its options revision (the review's survivor)",
           ("test_a_delivered_pair_names_its_options_revision",), ENVELOPE,
           '"required": ["generation", "options_revision"],', '"required": ["generation"],'),
          ("delivered-pair-without-its-generation", "a delivered pair may omit its generation (the mirror of the review's survivor)",
           ("test_a_delivered_pair_names_its_generation",), ENVELOPE,
           '"required": ["generation", "options_revision"],', '"required": ["options_revision"],'),
      )),
    Mutation("0CR-operator-listen-on-container-loopback", "A6", "the review's defect restored: the engine binds its container's loopback",
             (SC + "test_services_listen_on_their_container_interface",), target="tools/gen_source_catalog.py",
             old='Key("GEN2_OPERATOR_LISTEN", "0.0.0.0:8770",', new='Key("GEN2_OPERATOR_LISTEN", "127.0.0.1:8770",'),
    Mutation("0D-store-specific-setting-added", "0d", "the generator emits a setting for one particular export destination (operator ruling 2026-09-26)",
             (SC + "test_the_engine_settings_name_no_export_destination",), target="tools/gen_source_catalog.py",
             old='            Key("GEN2_CONNECTORS_CONFIG", "/etc/gen2/bundle/connectors.toml", "mounted read-only"),\n',
             new='            Key("GEN2_CONNECTORS_CONFIG", "/etc/gen2/bundle/connectors.toml", "mounted read-only"),\n'
                 '            Key("GEN2_GRAPH_STORE_URL", "https://graph-store.example.org"),\n'),
    Mutation("0CR-checker-errors-collapsed-to-a-set", "C1", "the schema check compares declared and actual errors as sets again, so two rules at one signature pass as one",
             ("test_check_ddl_rules.SchemaFixtureRuleTest.test_two_rules_reporting_one_signature_must_both_be_declared",),
             target="tools/check_gen2_schemas.py", old="            if actual != expected:", new="            if set(actual) != set(expected):"),
    # --- 1b: the router (task 1b) -----------------------------------------------------
    # Each guard of the router boundary removed or weakened in a mutated copy
    # (gen2/router/*.py are "module" targets: the router and the test fixtures
    # are reloaded over the mutant) and killed by its isolated negative. Where
    # the DDL is the second layer the killer pins the router's own reason or
    # detail, so a mutant the store would still catch is killed by the
    # reason changing, not survived.
    *(Mutation(f"1B-{key}", "1b", desc, tuple(killers), target=target, old=old, new=new)
      for key, desc, killers, target, old, new in (
          # replay and identity
          ("replay-any-fingerprint", "a reused operation id replays whatever its content",
           (RC + "ReplayAndIdentityTest.test_the_same_operation_id_with_different_content_is_refused",), SVC,
           '        if row["request_fingerprint"] != fingerprint:', '        if False:'),
          ("replay-never", "a committed operation is not replayed (it is re-run)",
           (RC + "ReplayAndIdentityTest.test_replaying_a_committed_operation_returns_the_identical_receipt",
            RC + "ReplayAndIdentityTest.test_a_lost_reply_is_recovered_by_operation_id"), SVC,
           '        if row is None:\n            return None\n        if row["request_fingerprint"]', '        if True:\n            return None\n        if row["request_fingerprint"]'),
          ("rejection-not-logged", "a rejection is not logged (the audit trail loses refused operations)",
           (RC + "FencingTest.test_a_wrong_expected_revision_is_refused",), SVC,
           '            self._audit("commit_rejected", now,', '            None and self._audit("commit_rejected", now,'),
          # fencing
          ("lease-any", "a commit may name a lease the invocation does not run under",
           (RC + "FencingTest.test_the_gen1_probe_shapes_are_refused",), SVC,
           '        if lease_ref is not None and lease_ref["lease_id"] != lease["lease_id"]:', '        if False:'),
          ("lease-released-ignored", "a released lease still fences nothing (the store's check becomes the only one)",
           (RC + "ReplayAndIdentityTest.test_a_retained_receipt_authorizes_nothing_after_its_lease_ends",
            RC + "FencingTest.test_an_expired_lease_is_fenced_by_its_successor"), SVC,
           '        if lease["released_at"] is not None:\n            raise Refusal("lease_released"', '        if False:\n            raise Refusal("lease_released"'),
          ("generation-ignored", "a stale generation is not the router's refusal",
           (RC + "FencingTest.test_a_stale_generation_is_refused",), SVC,
           '        if lease_ref is not None and lease_ref["generation"] != lease["generation"]:', '        if False:'),
          ("expiry-ignored", "an expired, unreleased lease still commits and launches",
           (RC + "FencingTest.test_an_expired_but_unreleased_lease_is_not_current", RO + "TransitionTest.test_the_final_launch_admission_check"), SVC,
           '        if instant(now) >= instant(lease["expires_at"]):', '        if False:'),
          # time (Astra 1b review A1, C1): the clock is read once the write lock is held, and a lease or
          # deadline is over at its own instant; each lock-wait killer crosses the boundary while its request waits
          ("clock-before-lock", "every operation reads the clock before waiting for the write lock",
           tuple(RT + "LockWaitTest." + t for t in ("test_a_claim_whose_lease_ends_during_the_wait", "test_a_claim_whose_deadline_passes_during_the_wait",
                                                     "test_a_launch_whose_lease_ends_during_the_wait", "test_a_launch_whose_deadline_passes_during_the_wait",
                                                     "test_an_observation_whose_lease_ends_during_the_wait", "test_a_commit_whose_lease_ends_during_the_wait")), SVC,
           '            with self._store.transaction():\n                return body(self._now())',
           '            now = self._now()\n            with self._store.transaction():\n                return body(now)'),
          ("claim-clock-before-lock", "a claim is judged at the time it asked for the lock",
           (RT + "LockWaitTest.test_a_claim_whose_lease_ends_during_the_wait", RT + "LockWaitTest.test_a_claim_whose_deadline_passes_during_the_wait"), SVC,
           '            return self._guarded("request_invalid", lambda now: self._claim_in_transaction(req, now))',
           '            stale = self._now()\n            return self._guarded("request_invalid", lambda now: self._claim_in_transaction(req, stale))'),
          ("transition-clock-before-lock", "a launch is judged at the time it asked for the lock (L-7)",
           (RT + "LockWaitTest.test_a_launch_whose_lease_ends_during_the_wait", RT + "LockWaitTest.test_a_launch_whose_deadline_passes_during_the_wait"), SVC,
           '            return self._guarded("transition_not_allowed", lambda now: self._transition_in_transaction(req, facts, now))',
           '            stale = self._now()\n            return self._guarded("transition_not_allowed", lambda now: self._transition_in_transaction(req, facts, stale))'),
          ("observation-clock-before-lock", "an observation is judged at the time it asked for the lock",
           (RT + "LockWaitTest.test_an_observation_whose_lease_ends_during_the_wait",), SVC,
           '            return self._guarded("payload_invalid", lambda now: self._observation_in_transaction(req, now))',
           '            stale = self._now()\n            return self._guarded("payload_invalid", lambda now: self._observation_in_transaction(req, stale))'),
          ("commit-clock-before-lock", "a commit is fenced at the time it asked for the lock",
           (RT + "LockWaitTest.test_a_commit_whose_lease_ends_during_the_wait",), SVC,
           '            status, receipt = self._guarded("payload_invalid", lambda now: self._commit_in_transaction(env, fingerprint, checked, now))',
           '            stale = self._now()\n            status, receipt = self._guarded("payload_invalid", lambda now: self._commit_in_transaction(env, fingerprint, checked, stale))'),
          ("expiry-at-the-instant", "a lease is still current at its expiry instant",
           (RT + "ExactInstantTest.test_a_commit_at_its_lease_expiry_is_refused", RT + "ExactInstantTest.test_a_launch_at_its_lease_expiry_is_refused",
            RT + "ExactInstantTest.test_an_observation_at_its_lease_expiry_is_refused"), SVC,
           '        if instant(now) >= instant(lease["expires_at"]):', '        if instant(now) > instant(lease["expires_at"]):'),
          ("deadline-at-the-instant", "a launch at its deadline instant is admitted (L-7)",
           (RT + "ExactInstantTest.test_a_launch_at_its_deadline_is_refused",), SVC,
           '            if instant(now) >= instant(inv["deadline_at"]):', '            if instant(now) > instant(inv["deadline_at"]):'),
          ("claim-times-at-the-instant", "a claim whose lease or deadline is the current instant is granted",
           (RT + "ExactInstantTest.test_a_claim_whose_lease_or_deadline_is_now_is_refused",), SVC,
           '            if field in req and instant(req[field]) <= instant(now):', '            if field in req and instant(req[field]) < instant(now):'),
          ("lease-held-at-the-instant", "a lease still holds off its successor at its expiry instant",
           (RT + "ExactInstantTest.test_a_lease_is_superseded_at_its_expiry_and_not_before",), SVC,
           '            if instant(now) < instant(live["expires_at"]):', '            if instant(now) <= instant(live["expires_at"]):'),
          ("state-revision-ignored", "the expected state revision is not compared",
           (RC + "FencingTest.test_a_wrong_expected_revision_is_refused",), SVC,
           '        if topic["state_revision"] != env["expected_state_revision"]:', '        if False:'),
          ("admission-ignored", "the envelope's admission is not compared with the pins",
           (RC + "FencingTest.test_a_stale_admission_or_config_is_refused",), SVC,
           '        if not canonical.canonical_bytes(env["admission"]) == canonical.canonical_bytes(admission):', '        if False:'),
          ("config-ignored", "the envelope's config bundle is not compared with the pin",
           (RC + "FencingTest.test_a_stale_admission_or_config_is_refused",), SVC,
           '        if env["config_bundle_hash"] != inv["config_bundle_hash"]:\n            raise Refusal("config_bundle_mismatch", "the envelope',
           '        if False:\n            raise Refusal("config_bundle_mismatch", "the envelope'),
          ("pause-ignored", "a paused topic still commits",
           (RC + "FencingTest.test_a_paused_topic_commits_nothing",), SVC,
           '        if topic["paused_at"] is not None:\n            raise Refusal("topic_paused", f"paused at {topic[\'paused_at\']}")\n        self._require_current_pins(inv)',
           '        self._require_current_pins(inv)'),
          ("amendment-ignored", "work pinned to a superseded contract revision still commits (G-1 hook)",
           (RC + "FencingTest.test_work_pinned_to_a_superseded_contract_is_not_committed",), SVC,
           '            if row["status"] != "approved":\n                raise Refusal("amendment_pending"', '            if False:\n                raise Refusal("amendment_pending"'),
          ("brief-amendment-ignored", "pre-contract work pinned to a superseded brief still commits",
           (RC + "FencingTest.test_work_pinned_to_a_superseded_brief_is_not_committed",), SVC,
           '            if row["status"] != "confirmed":\n                raise Refusal("amendment_pending"', '            if False:\n                raise Refusal("amendment_pending"'),
          ("final-twice", "a second final outcome is not the router's refusal",
           (RC + "FencingTest.test_one_final_outcome_per_invocation",), SVC,
           '            if finals:\n                raise Refusal("final_outcome_exists"', '            if False:\n                raise Refusal("final_outcome_exists"'),
          ("final-without-result", "a final outcome commits without a staged result",
           (RC + "FencingTest.test_the_invocation_must_be_in_the_state_the_operation_needs",), SVC,
           '            if inv["state"] != "result_ready" or inv["result_payload_digest"] != env["payload_digest"]:', '            if False:'),
          ("final-other-document", "a final outcome commits a document other than the staged result",
           (RC + "FencingTest.test_the_invocation_must_be_in_the_state_the_operation_needs",), SVC,
           '            if inv["state"] != "result_ready" or inv["result_payload_digest"] != env["payload_digest"]:', '            if inv["state"] != "result_ready":'),
          ("interim-not-running", "an interim transition commits after the result was staged",
           (RC + "FencingTest.test_the_invocation_must_be_in_the_state_the_operation_needs",), SVC,
           '        elif inv["state"] != "running":\n            raise Refusal("invocation_state_invalid", f"an interim',
           '        elif False:\n            raise Refusal("invocation_state_invalid", f"an interim'),
          # authority
          ("capability-any-invocation", "a capability records facts for another invocation",
           (RO + "TransitionTest.test_only_the_invocations_capability_records_its_facts",), SVC,
           '        if inv["invocation_id"] != invocation_id:\n            raise Refusal("capability_invocation_mismatch"',
           '        if False:\n            raise Refusal("capability_invocation_mismatch"'),
          ("document-any-invocation", "an outcome document of another invocation is committed under this capability",
           (RC + "AuthorityTest.test_an_outcome_document_is_its_own_invocations",), SVC,
           '        if payload["invocation_id"] != inv["invocation_id"]:', '        if False:'),
          ("envelope-cross-topic", "an envelope naming another topic is committed to the invocation's",
           (RC + "FencingTest.test_a_cross_topic_write_is_refused", RC + "BoundaryValidationTest.test_an_unknown_topic_reports_no_state_revision"), SVC,
           '        if env["topic_id"] != inv["topic_id"]:', '        if False:'),
          ("document-cross-topic", "an outcome document about another topic is committed",
           (RC + "FencingTest.test_a_cross_topic_write_is_refused",), SVC,
           '        if payload["topic_id"] != inv["topic_id"]:', '        if False:'),
          ("envelope-schema-skipped", "the envelope is not validated (a role label is ignored, not refused)",
           (RC + "AuthorityTest.test_a_role_label_is_refused_not_ignored",), SVC,
           '            boundary.require_schema(self._schemas, env, "commit-outcome.schema.json", "envelope_invalid")\n', ''),
          ("sections-any-kind", "any invocation kind may commit any section",
           (RC + "AuthorityTest.test_a_producer_cannot_verify_its_own_work", RC + "AuthorityTest.test_discovery_and_delegate_work_hold_no_evidence_write_capability",
            RE + "ExportTest.test_only_primary_class_work_commits_exports"), BND,
           '        if kind not in kinds:', '        if False:'),
          ("pre-contract-sections", "pre-contract work commits protocol-bound sections",
           (RE + "ProductionAndAdoptionTest.test_scoping_work_promotes_nothing",), BND,
           '        if admission_context == "pre-contract/1" and section not in PRE_CONTRACT_SECTIONS:', '        if False:'),
          ("next-state-any-kind", "any kind proposes the topic's next queue state",
           (RC + "AuthorityTest.test_only_a_research_pass_proposes_the_next_queue_state",), SVC,
           '        if payload["next_queue_state"] is not None and inv["kind"] != "research_pass":', '        if False:'),
          ("verifier-not-committer", "a verification receipt is committed by an invocation other than its verifier",
           (RC + "AuthorityTest.test_a_producer_cannot_verify_its_own_work",), BND,
           '    if doc["verifier_invocation_id"] != invocation_id or doc["verifier_capability_id"] != capability_id:', '    if False:'),
          ("producer-verifies", "a receipt naming its verifier as the producer is not the router's refusal",
           (RC + "AuthorityTest.test_a_producer_cannot_verify_its_own_work",), BND,
           '    if doc["producer_invocation_id"] == invocation_id:', '    if False:'),
          # boundary validation: bytes, documents, sizes
          ("digest-unchecked", "staged bytes are not re-hashed against their label",
           (RC + "BoundaryValidationTest.test_a_payload_digest_that_does_not_match_the_bytes_is_refused",
            RC + "BoundaryValidationTest.test_a_result_ref_whose_label_is_not_its_bytes_is_refused"), BND,
           '    if digest != content_hash:', '    if False:'),
          ("size-unchecked", "staged sizes are not compared with the declared size",
           (RC + "BoundaryValidationTest.test_a_payload_digest_that_does_not_match_the_bytes_is_refused",), BND,
           '    if size is not None and len(raw) != size:', '    if False:'),
          ("document-schema-skipped", "the outcome document is not validated against its schema",
           (RC + "AuthorityTest.test_a_role_label_in_the_outcome_document_is_refused",), SVC,
           '        boundary.require_schema(self._schemas, payload, "outcome-document.schema.json", "payload_invalid")\n', ''),
          ("operation-kind-unchecked", "a final document is committed as an interim transition",
           (RC + "BoundaryValidationTest.test_the_document_is_for_the_envelopes_operation_kind",), SVC,
           '        if payload["operation_kind"] != env["operation_kind"]:', '        if False:'),
          ("envelope-unbounded", "the envelope's byte cap is not enforced",
           (RC + "BoundaryValidationTest.test_an_oversized_or_non_canonical_envelope_is_refused",), SVC,
           '            if len(canonical.canonical_bytes(env)) > ENVELOPE_MAX_BYTES:', '            if False:'),
          ("artifact-metadata-unchecked", "a reference may disagree with the recorded artifact's size or media type (A10)",
           (RC + "BoundaryValidationTest.test_an_artifact_is_one_record_whoever_references_it",), SVC,
           '            if stored is not None and (stored["size_bytes"], stored["media_type"]) != (ref["size_bytes"], ref["media_type"]):', '            if False:'),
          # atomicity is structural (one transaction); the store's refusal must roll back the claim written before it
          ("store-refusal-swallowed", "a write the store refuses is reported as a failure, not a refusal",
           (RC + "AtomicityTest.test_a_store_refusal_inside_the_transaction_rolls_everything_back",), SVC,
           '        except (api.ConstraintViolation, api.StoreWriteError) as exc:', '        except api.StoreWriteError as exc:'),
          # effects
          ("ordinal-any-kind", "every final outcome asks for an ordinal (C-7)",
           (RE + "TriggerAndOrdinalTest.test_only_contract_research_passes_earn_ordinals", RX + "CrashMatrixTest.test_every_boundary_for_every_finalizing_kind"), SVC,
           '        if final and inv["kind"] == "research_pass" and inv["admission_context"] == "contract/1":', '        if final:'),
          ("lease-kept-after-final", "a final outcome does not release its lease",
           (RX + "CrashMatrixTest.test_every_boundary_for_every_finalizing_kind",
            RC + "ReplayAndIdentityTest.test_a_retained_receipt_authorizes_nothing_after_its_lease_ends"), SVC,
           '        if final and inv["kind"] != "delegate":\n            lease_release =', '        if False:\n            lease_release ='),
          ("delegate-releases-parent-lease", "a delegate's final outcome releases its parent's lease",
           (RX + "CrashMatrixTest.test_every_boundary_for_every_finalizing_kind",), SVC,
           '        if final and inv["kind"] != "delegate":\n            lease_release =', '        if final:\n            lease_release ='),
          ("queue-transition-dropped", "a research pass's final outcome leaves its topic active",
           (RC + "AtomicityTest.test_a_fault_at_each_point_leaves_nothing_or_everything",), SVC,
           '        if final and inv["kind"] == "research_pass" and topic["status"] == "active":', '        if False:'),
          ("held-rest-state", "a pass finishing under a hold reports its lease resting idle",
           (RC + "FencingTest.test_a_held_topic_is_left_held",), SVC,
           '        elif topic["status"] == "held":', '        elif False:'),
          ("trigger-reinserted", "a recorded trigger identity is recorded again (RG-1b(e))",
           (RE + "TriggerAndOrdinalTest.test_a_replayed_trigger_opens_nothing_new",), SVC,
           '        new_triggers = list({identity: t for identity, t in triggers if identity not in known}.items())',
           '        new_triggers = list({identity: t for identity, t in triggers}.items())'),
          # claims: production, adoption, promotion (V-10, the 1a review's carried obligation)
          ("claim-revision-gap", "a claim revision may skip numbers",
           (RE + "ProductionAndAdoptionTest.test_a_scoping_claim_is_adopted_by_a_revision_the_admitted_commit_produces",), SVC,
           '            if claim["revision"] != max((row["revision"] for row in prior), default=0) + 1:', '            if False:'),
          ("claim-cross-topic-revision", "a new revision of another topic's claim is recorded under this topic",
           (RC + "FencingTest.test_another_topics_claim_cannot_be_revised_or_promoted",), SVC,
           '            if any(row["topic_id"] != topic_id for row in prior):', '            if False:'),
          ("promotion-cross-topic", "another topic's claim is promoted",
           (RC + "FencingTest.test_another_topics_claim_cannot_be_revised_or_promoted",), SVC,
           '            if row["topic_id"] != topic_id:\n                raise Refusal("cross_topic", f"{promotion', '            if False:\n                raise Refusal("cross_topic", f"{promotion'),
          ("promotion-any-status", "an already accepted revision is promoted again",
           (RE + "ProductionAndAdoptionTest.test_only_a_provisional_or_contested_revision_is_promoted",), SVC,
           '            if row["status"] not in ("provisional", "contested"):', '            if False:'),
          ("text-ref-unstaged", "a claim's text need not be staged or recorded",
           (RE + "ProductionAndAdoptionTest.test_a_claims_text_is_staged_or_recorded",), SVC,
           '            known = artifacts.get(text["content_hash"]) or self._one("artifacts", {"content_hash": text["content_hash"]})', '            known = text'),
          ("text-ref-metadata", "a claim's text reference may disagree with its artifact",
           (RE + "ProductionAndAdoptionTest.test_a_claims_text_is_staged_or_recorded",), SVC,
           '            if (known["size_bytes"], known["media_type"]) != (text["size_bytes"], text["media_type"]):', '            if False:'),
          ("canonical-bytes-unstaged", "reused canonical bytes need not be staged (V-3)",
           (RC + "AuthorityTest.test_canonical_bytes_are_staged_or_recorded",), SVC,
           '            if doc["extraction"]["method"] == "canonical_bytes" and not available(doc["obtained_content_hash"]):', '            if False:'),
          # decisions and screening (A10)
          ("raw-response-unstaged", "a decision's raw response need not be staged (D-1)",
           (RE + "ProviderScreeningTest.test_the_raw_response_must_be_staged",), SVC,
           '            if digest is not None and not available(digest):', '            if False:'),
          ("abstention-hold-unknown", "an abstention may name a hold that does not exist",
           (RE + "ProviderScreeningTest.test_an_abstention_hold_is_one_this_commit_creates_or_one_recorded",), SVC,
           '            if hold is not None and hold not in hold_ids and self._one("holds", {"hold_id": hold}) is None:', '            if False:'),
          ("decision-other-invocation", "a decision receipt of another invocation is committed",
           (RE + "ProviderScreeningTest.test_a_receipt_records_a_call_of_the_committing_invocation",), BND,
           '    if doc["invocation_id"] != invocation_id:', '    if False:'),
          ("spec-hash-untrue", "a stored DecisionSpec's hash is not recomputed (RA6)",
           (RE + "ProviderScreeningTest.test_the_spec_must_hash_to_its_label_and_be_for_this_protocol",), BND,
           '    if canonical.logical_hash(spec_document) != doc["spec"]["spec_hash"]:', '    if False:'),
          ("qualification-unchecked", "a qualification reference is taken as qualification (INVARIANTS §13)",
           (RE + "ProviderScreeningTest.test_no_registry_entry_means_no_qualified_authority",), BND,
           '    if authorization["authority_level"] == "qualified" and not qualifications.is_qualified(', '    if False and not qualifications.is_qualified('),
          ("decision-commit-elsewhere", "a receipt whose action another operation committed is recorded here (D-2)",
           (RE + "ProviderScreeningTest.test_a_receipt_committed_by_another_operation_is_refused",), BND,
           '    if doc["outcome"]["commit_operation_id"] not in (None, operation_id):', '    if False:'),
          ("screening-foreign-criteria", "an assessment may cite criteria its protocol version does not have",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '    criteria = {c["criterion_id"]: c for c in protocol["criteria"]}',
           '    criteria = {c["criterion_id"]: c for c in protocol["criteria"]} | {cid: {"stage": "metadata"} for cid in assessment["criterion_results"]}'),
          ("screening-stage", "a criterion may be decided before its stage",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '        if result != "unknown" and STAGE[criteria[cid]["stage"]] > STAGE[assessment["stage"]]:', '        if False:'),
          ("screening-exclusion-on-unknown", "missing information excludes (an exclusion without a criterion not met)",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '    if assessment["decision"] == "exclude" and not not_met:', '    if False:'),
          ("screening-inclusion-with-not-met", "an inclusion may have criteria not met",
           (RE + "ScreeningTest.test_criterion_results_are_the_protocols_and_consistent",), BND,
           '    if assessment["decision"] == "include" and not_met:', '    if False:'),
          ("screening-answer", "a provider assessment need not be its receipt's answer",
           (RE + "ProviderScreeningTest.test_the_assessment_must_be_the_receipts_answer",), BND,
           '            or answer.get("selected_option_id") != assessment["decision"] or receipt["action"]', '            or receipt["action"]'),
          ("screening-subject", "a provider assessment need not be about its receipt's work",
           (RE + "ProviderScreeningTest.test_the_assessment_must_be_the_receipts_answer",), BND,
           '    if (receipt["decision_class"] != "screening" or receipt["subject"] != {"kind": "work", "ref": assessment["work_id"]}',
           '    if (receipt["decision_class"] != "screening"'),
          ("screening-spec-protocol", "a receipt's spec may be for another protocol version",
           (RE + "ProviderScreeningTest.test_the_spec_must_hash_to_its_label_and_be_for_this_protocol",), BND,
           '    if ((spec_document or {}).get("protocol") or {}).get("eligibility_protocol_version") != version:', '    if False:'),
          # observations (A10, E-2, H-5, RG-U)
          ("observation-count", "an observed count need not be its captured identities (E-2)",
           (RO + "ObservationTest.test_a_complete_count_is_its_captured_identities", RO + "ObservationTest.test_a_partial_set_keeps_what_was_seen_as_a_lower_bound"), BND,
           '    if observation["result_count"] != len(events):', '    if False:'),
          ("observation-unobserved", "an unobserved set may carry records or a count (RG-U)",
           (RO + "ObservationTest.test_unknown_is_not_zero",), BND,
           '        if events or observation["result_count"] is not None:', '        if False:'),
          ("request-identity", "a request identity need not be its request's hash (H-5)",
           (RO + "ObservationTest.test_a_request_identity_is_the_hash_of_its_request",), BND,
           '    if canonical.logical_hash(observation["request"]) != observation["request_identity"]:', '    if False:'),
          ("observation-time-order", "an observation may end before it starts",
           (RO + "ObservationTest.test_impossible_or_contradictory_times_are_refused",), BND,
           '    if observation["ended_at"] is not None and instant(observation["ended_at"]) < instant(observation["started_at"]):', '    if False:'),
          ("observation-duplicate-record", "a record is captured twice for one observation",
           (RO + "ObservationTest.test_a_record_is_captured_once_per_observation",), BND,
           '    if len(set(records)) != len(records):', '    if False:'),
          ("observation-running-only", "a failed invocation records observations",
           (RO + "ObservationTest.test_only_a_running_invocation_records_observations",), SVC,
           '        if inv["state"] != "running":\n            raise Refusal("invocation_state_invalid", f"observations',
           '        if False:\n            raise Refusal("invocation_state_invalid", f"observations'),
          ("observation-lease-unchecked", "a running invocation records observations after its lease expired (Astra 1b review C1)",
           (RO + "ObservationTest.test_a_running_invocation_past_its_lease_records_nothing", RT + "ExactInstantTest.test_an_observation_at_its_lease_expiry_is_refused"), SVC,
           '        self._require_current_lease(inv, now)\n        topic = self._one(', '        topic = self._one('),
          ("observation-pause-unchecked", "a paused topic records observations",
           (RO + "ObservationTest.test_a_paused_topic_records_no_observation",), SVC,
           '        if topic["paused_at"] is not None:\n            raise Refusal("topic_paused", f"paused at {topic[\'paused_at\']}")\n        self._store.insert("search_observations"',
           '        self._store.insert("search_observations"'),
          ("observation-conflict", "an observation id with other content replays",
           (RO + "ObservationTest.test_replay_and_conflict_by_observation_id",), SVC,
           '            if not same:\n                raise Refusal("observation_id_conflict"', '            if False:\n                raise Refusal("observation_id_conflict"'),
          # exports (EXPORT-API.md §5, §7)
          ("extension-admitted-by-name", "an extension connector is admitted by naming a module and review",
           (RE + "ExportTest.test_an_extension_is_admitted_only_by_the_registry",), BND,
           '            if not extensions.is_admitted(module=impl["module"], review_ref=impl["review_ref"]):', '            if False:'),
          ("bundle-not-with-commit", "the bundle may be any staged bytes, not staged with the commit",
           (RE + "ExportTest.test_the_bundle_is_staged_canonical_and_valid",), SVC,
           '            if bundle_hash not in staged:\n                raise Refusal("payload_missing", f"{manifest[\'manifest_id\']}: its bundle {bundle_hash} is not staged with this commit")\n'
           '            manifests.append((manifest, boundary.check_manifest(manifest, inv["topic_id"], self._extensions, staged[bundle_hash], self._schemas)))',
           '            manifests.append((manifest, boundary.check_manifest(manifest, inv["topic_id"], self._extensions, staged.get(bundle_hash) or self._spool.read(bundle_hash), self._schemas)))'),
          ("bundle-not-canonical", "a bundle staged in a non-canonical form is exported",
           (RE + "ExportTest.test_the_bundle_is_staged_canonical_and_valid",), BND,
           '    if canonical.canonical_bytes(bundle) != bundle_raw:', '    if False:'),
          ("bundle-schema-skipped", "the bundle is not validated against export-bundle/1",
           (RE + "ExportTest.test_the_bundle_is_staged_canonical_and_valid",), BND,
           '    require_schema(schemas, bundle, "export-bundle.schema.json", "payload_invalid")', '    pass'),
          ("bundle-identity", "the staged bundle need not be the one the manifest names",
           (RE + "ExportTest.test_the_staged_bundle_is_the_one_the_manifest_names",), BND,
           '    if bundle["bundle_id"] != manifest["bundle"]["bundle_id"] or bundle["topic_id"] != topic_id:', '    if False:'),
          ("manifest-cross-topic", "a manifest of another topic is not the router's refusal",
           (RE + "ExportTest.test_unapproved_or_foreign_material_is_not_exported",), BND,
           '    if manifest["topic_id"] != topic_id:', '    if False:'),
          ("hold-fact-unrecorded", "a capability hold may cite an unrecorded fact (the store's key becomes the only check)",
           (RE + "HoldTest.test_a_capability_hold_cites_a_recorded_fact",), SVC,
           '            if fact is not None and self._one("capability_facts", {"fact_id": fact}) is None:', '            if False:'),
          # claim (leases, admission, delegates)
          ("claim-status-gate", "a lease is granted whatever the topic's status",
           (RO + "ClaimTest.test_topic_state_gates_claims",), SVC,
           '        if topic["status"] not in claimable:', '        if False:'),
          ("lease-held-ignored", "a live lease is superseded as if expired",
           (RO + "ClaimTest.test_one_live_lease_per_topic_and_scope",), SVC,
           '            if instant(now) < instant(live["expires_at"]):', '            if False:'),
          ("expired-lease-kept", "an expired lease is not released before its successor",
           (RO + "ClaimTest.test_an_expired_lease_is_released_and_superseded",), SVC,
           '            self._store.update("leases", {"lease_id": live["lease_id"]}, {"released_at": now, "release_reason": "expired"})', '            pass'),
          ("admission-any-kind", "pre-contract admission is offered to every kind (C-12)",
           (RO + "ClaimTest.test_pre_contract_admission_is_for_scoping_kinds_only",), SVC,
           '        if kind not in ("discovery", "research_pass") or any(c["status"] != "draft" for c in contracts):',
           '        if any(c["status"] != "draft" for c in contracts):'),
          ("claim-replay-after-time-checks", "a lost claim reply is refused once its deadline has passed",
           (RO + "ClaimTest.test_a_lost_claim_reply_is_recovered_by_invocation_id",), SVC,
           '        if existing is not None:\n            return self._claim_replay(req, existing)  # a lost reply gets its grant back, whatever the time now\n'
           '        for field in ("deadline_at", "lease_expires_at"):\n            if field in req and instant(req[field]) <= instant(now):\n'
           '                raise Refusal("request_invalid", f"{field} {req[field]} is not after {now}")\n',
           '        for field in ("deadline_at", "lease_expires_at"):\n            if field in req and instant(req[field]) <= instant(now):\n'
           '                raise Refusal("request_invalid", f"{field} {req[field]} is not after {now}")\n'
           '        if existing is not None:\n            return self._claim_replay(req, existing)  # a lost reply gets its grant back, whatever the time now\n'),
          ("claim-replay-any-request", "an invocation id replays whatever the request",
           (RO + "ClaimTest.test_a_lost_claim_reply_is_recovered_by_invocation_id",), SVC,
           '        if not same:\n            raise Refusal("invocation_id_conflict"', '        if False:\n            raise Refusal("invocation_id_conflict"'),
          ("delegate-parent-state", "a delegate is admitted under a parent that is not running (L-8)",
           (RO + "ClaimTest.test_a_delegate_runs_under_its_running_parent",), SVC,
           '        if parent["kind"] == "delegate" or parent["state"] not in ("launching", "running"):', '        if False:'),
          ("delegate-config", "a delegate is admitted under another config bundle than its parent's",
           (RO + "ClaimTest.test_a_delegate_runs_under_its_running_parent",), SVC,
           '        if parent["config_bundle_hash"] != req["config_bundle_hash"]:', '        if False:'),
          ("delegate-cross-topic", "a delegate's parent may be another topic's",
           (RO + "ClaimTest.test_a_delegate_runs_under_its_running_parent",), SVC,
           '        if parent["topic_id"] != topic["topic_id"]:', '        if False:'),
          # lifecycle facts (L-1, L-2, L-7)
          ("launch-when-paused", "launch skips the pause check (L-7)",
           (RO + "TransitionTest.test_the_final_launch_admission_check",), SVC,
           '            if topic["paused_at"] is not None:\n                raise Refusal("topic_paused", f"paused at {topic[\'paused_at\']}")\n            if instant(now) >= instant(inv["deadline_at"]):',
           '            if instant(now) >= instant(inv["deadline_at"]):'),
          ("launch-without-lease", "launch skips the lease check (L-7)",
           (RO + "TransitionTest.test_the_final_launch_admission_check",), SVC,
           '            self._require_current_lease(inv, now)\n            topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})\n            if topic["paused_at"]',
           '            topic = self._one("queue_entries", {"topic_id": inv["topic_id"]})\n            if topic["paused_at"]'),
          ("launch-after-deadline", "launch skips the deadline check (L-7)",
           (RO + "TransitionTest.test_launch_after_the_deadline_is_refused",), SVC,
           '            if instant(now) >= instant(inv["deadline_at"]):', '            if False:'),
          ("result-not-staged", "a result is recorded ready without its bytes staged (C-9)",
           (RO + "TransitionTest.test_a_result_is_ready_only_when_its_bytes_are_staged",), SVC,
           '                boundary.staged(self._spool, facts["result_payload_digest"])', '                pass'),
          ("failure-keeps-lease", "a failed invocation keeps its lease and its topic active",
           (RO + "TransitionTest.test_a_failure_releases_the_lease_and_requeues",), SVC,
           '        if target == "failed" and inv["kind"] != "delegate":', '        if False:'),
          ("transition-facts-unchecked", "a lifecycle state is recorded with other facts than its own",
           (RO + "TransitionTest.test_each_state_is_recorded_with_exactly_its_facts",), SVC,
           '            if set(facts) - wanted or wanted - {"container_id"} - set(facts):', '            if False:'),
          ("transition-replay-current-only", "a recorded fact replays only while it is the current state (Astra 1b review A5)",
           (RO + "TransitionTest.test_a_recorded_fact_replays_after_the_invocation_moves_on", RR + "RestartTest.test_recorded_facts_replay_after_a_restart"), SVC,
           '        recorded = self._one("invocation_transitions", {"invocation_id": inv["invocation_id"], "to_state": target, "cause": LIFECYCLE_CAUSE[target]}) is not None',
           '        recorded = inv["state"] == target'),
          ("transition-omitted-fact-ignored", "a replay that leaves out a recorded optional fact (container_id) is taken for the same fact",
           (RO + "TransitionTest.test_a_recorded_fact_replays_after_the_invocation_moves_on",), SVC,
           '            facts = {k: facts.get(k) for k in LIFECYCLE_FACTS[req["to_state"]]}  # an omitted container_id is recorded, and compared, as none\n', ''),
          ("transition-conflict-replayed", "a recorded fact is replaced by a conflicting one as a replay",
           (RO + "TransitionTest.test_the_lifecycle_moves_along_l1_only",), SVC,
           '            if any(inv[k] != v for k, v in facts.items()):', '            if False:'),
          # operator decisions (G-13, RA6)
          ("subject-hash-untrue", "a stored subject's hash label is not recomputed before approval (RA6)",
           (RO + "OperatorDecisionTest.test_approval_binds_to_a_hash_that_is_true_of_the_stored_document",), SVC,
           '        if stored is not None and canonical.content_hash(stored["document"]) != stored["content_hash"]:', '        if False:'),
          ("decision-replay-any-content", "a decision id replays whatever the content",
           (RO + "OperatorDecisionTest.test_brief_confirmation_moves_intake_to_scoping",), SVC,
           '            if canonical.canonical_bytes(existing) != canonical.canonical_bytes(row):', '            if False:'),
          ("decision-move-optional", "a decision whose transition the state forbids is recorded anyway",
           (RO + "OperatorDecisionTest.test_a_decision_whose_transition_the_state_forbids_is_refused_whole",), SVC,
           '        if target is None and required:', '        if False:'),
          ("approval-without-supersession", "an amendment approval leaves the earlier revision approved",
           (RO + "OperatorDecisionTest.test_contract_approval_queues_the_topic_and_an_amendment_supersedes",), SVC,
           '            self._store.update("contract_revisions", {"topic_id": d["topic_id"], "revision": old["revision"]}, {"status": "superseded"})', '            pass'),
          # delivery receipts (P-2, P-7, H-2)
          ("ack-replay-any-content", "an export receipt id replays whatever the content",
           (RO + "AckDeliveryTest.test_a_delivery_is_recorded_once_and_advances_the_watermark", RO + "AckDeliveryTest.test_a_replay_is_the_same_document"), SVC,
           '            if canonical.canonical_bytes(existing["receipt"]) != canonical.canonical_bytes(doc):', '            if False:'),
          ("ack-replay-projection-only", "a replay compares only the old column projection (Astra 1b review A2: topic, pair, count and references ignored)",
           (RO + "AckDeliveryTest.test_a_replay_is_the_same_document", RR + "RestartTest.test_delivery_receipts_read_back_whole_after_a_restart"), SVC,
           '            if canonical.canonical_bytes(existing["receipt"]) != canonical.canonical_bytes(doc):',
           '            if any(existing[k] != doc.get(k) for k in ("manifest_id", "attempt", "status", "error_class", "unknown_cause", "capability_fact_id", "attempted_at", "acked_at")):'),
          ("ack-hold-unchecked", "a receipt may name a hold that is not recorded (the store's trigger becomes the only check)",
           (RO + "AckDeliveryTest.test_a_named_hold_is_one_of_the_manifests_topic",), SVC,
           '        if hold is not None and self._one("holds", {"hold_id": hold, "topic_id": event["topic_id"]}) is None:', '        if False:'),
          ("ack-hold-any-topic", "a receipt may name another topic's hold",
           (RO + "AckDeliveryTest.test_a_named_hold_is_one_of_the_manifests_topic",), SVC,
           '{"hold_id": hold, "topic_id": event["topic_id"]}', '{"hold_id": hold}'),
          ("ack-manifest-description", "a receipt need not describe its manifest's topic and pair",
           (RO + "AckDeliveryTest.test_a_receipt_must_describe_its_manifest",), SVC,
           '        if doc["topic_id"] != event["topic_id"] or (doc["generation"], doc["options_revision"]) != (event["generation"], event["options_revision"]):', '        if False:'),
          ("ack-attempt-order", "attempts need not be numbered in order",
           (RO + "AckDeliveryTest.test_a_receipt_must_describe_its_manifest",), SVC,
           '        if doc["attempt"] != len(attempts) + 1:', '        if False:'),
          ("watermark-regression", "a delivery of an older pair is recorded without refusal (P-2)",
           (RO + "AckDeliveryTest.test_the_watermark_never_regresses",), SVC,
           '        elif pair < (mark["generation"], mark["options_revision"]):', '        elif False:'),
          ("watermark-not-advanced", "a delivery of a newer pair leaves the watermark behind",
           (RO + "AckDeliveryTest.test_the_watermark_never_regresses",), SVC,
           '        elif pair > (mark["generation"], mark["options_revision"]):', '        elif False:'),
          ("fact-not-transition-only", "a failure raises a new fact while the connector is already failing (H-2)",
           (RO + "AckDeliveryTest.test_failures_raise_capability_facts_on_transitions",), SVC,
           '        elif current is not None and current["state"] == state:', '        elif False:'),
          ("fact-recovery-dropped", "a delivery after a failure records no recovery",
           (RO + "AckDeliveryTest.test_failures_raise_capability_facts_on_transitions",), SVC,
           '            if current is None or current["state"] == state:\n                return', '            if True:\n                return'),
          # instants (task 1b's exact ordering)
          ("instant-fraction-unscaled", "fraction digits are read as an integer, not as nanoseconds",
           (IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_time_order_is_not_text_order",
            IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_nanoseconds_since_the_epoch"), "gen2/core/instants.py",
           '+ int(fraction.ljust(9, "0"))', '+ int(fraction or "0")'),
          ("instant-fraction-dropped", "the fraction is ignored",
           (IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_time_order_is_not_text_order",), "gen2/core/instants.py",
           '    fraction = value[20:-1] if value[19] == "." else ""', '    fraction = ""'),
          ("instant-unvalidated", "an impossible instant is converted instead of refused",
           (IN.replace("UtcInstantTest.", "UtcInstantOrderTest.") + "test_invalid_instants_are_refused",), "gen2/core/instants.py",
           '    if not is_utc_instant(value):\n        raise ValueError', '    if False:\n        raise ValueError'),
      )),
    # the router's validator, against the jsonschema oracle (tools/gen2_schema_oracle.py)
    *(Mutation(f"1B-schema-{key}", "1b", desc, (RS + "DifferentialTest.test_every_fixture_and_its_mutations_get_the_oracles_verdict", *extra),
               target="gen2/router/schemas.py", old=old, new=new)
      for key, desc, extra, old, new in (
          ("additional-properties", "additionalProperties is ignored", (), '            elif "additionalProperties" in schema:', '            elif False:'),
          ("required", "required is ignored", (), "            if key not in value:\n", "            if False:\n"),
          ("one-of-zero", "oneOf accepts a value matching none", (), "            if matched != 1:", "            if matched > 1:"),
          ("if-then", "if/then/else is ignored", (), '            if branch in schema:', '            if False:'),
          ("integer-strict", "an integral float is not an integer (2020-12 says it is)", (),
           "    return _is_number(value) and (isinstance(value, int) or value.is_integer())", "    return _is_number(value) and isinstance(value, int)"),
          ("bool-is-number", "true is a number", (), "    return isinstance(value, (int, float)) and not isinstance(value, bool)", "    return isinstance(value, (int, float))"),
          ("unique", "uniqueItems is ignored", (), "                if key in seen:", "                if False:"),
          ("min-items", "minItems is ignored", (), '        if "minItems" in schema and len(value) < schema["minItems"]:', "        if False:"),
          ("enum", "enum is ignored", (), '        if "enum" in schema and not any(json_equal(value, option) for option in schema["enum"]):', "        if False:"),
          ("not", "not is ignored", (), '        if "not" in schema and self.is_valid(value, schema["not"], base):', "        if False:"),
          ("contains", "minContains is ignored", (), '            if found < schema.get("minContains", 1):', "            if False:"),
          ("property-names", "propertyNames is ignored", (), '            if "propertyNames" in schema:', "            if False:"),
          ("minimum", "minimum is ignored", (), '(("minimum", lambda b: value < b),', '(("minimum", lambda b: False),'),
          ("pattern", "pattern is ignored", (), '        if "pattern" in schema and not self._patterns[schema["pattern"]].search(value):', "        if False:"),
          ("date-time", "date-time is only a shape (February 30 passes)", (RS + "StricterThanOracleTest.test_date_time_is_a_real_instant",),
           '        if schema.get("format") == "date-time" and not instants.is_utc_instant(value):', "        if False:"),
      )),
    *(Mutation(f"1B-schema-{key}", "1b", desc, (RS + killer,), target="gen2/router/schemas.py", old=old, new=new)
      for key, desc, killer, old, new in (
          ("max-length", "maxLength is ignored", "BoundsTest.test_bounds_at_their_edges", '        if "maxLength" in schema and len(value) > schema["maxLength"]:', "        if False:"),
          ("max-items", "maxItems is ignored", "BoundsTest.test_bounds_at_their_edges", '        if "maxItems" in schema and len(value) > schema["maxItems"]:', "        if False:"),
          ("max-properties", "maxProperties is ignored", "BoundsTest.test_bounds_at_their_edges", '        if "maxProperties" in schema and len(value) > schema["maxProperties"]:', "        if False:"),
          ("exclusive-minimum", "exclusiveMinimum is read as minimum", "BoundsTest.test_bounds_at_their_edges",
           '("exclusiveMinimum", lambda b: value <= b)', '("exclusiveMinimum", lambda b: value < b)'),
          ("maximum", "maximum is ignored", "BoundsTest.test_bounds_at_their_edges", '("maximum", lambda b: value > b)', '("maximum", lambda b: False)'),
      )),
    Mutation("1B-schema-end-anchor-python", "1b", "a pattern's `$` also matches before a trailing newline (Python's reading, not ECMA-262's)",
             (RS + "StricterThanOracleTest.test_a_trailing_newline_does_not_satisfy_an_anchored_pattern",), target="gen2/router/schemas.py",
             old='    body = pattern[:-1] + r"\\Z" if pattern.endswith("$") and not pattern.endswith("\\\\$") else pattern\n    if re.search(r"(?<!\\\\)\\$", body):\n        raise SchemaError(f"pattern {pattern!r}: `$` is supported only at the end")\n', new="    body = pattern\n"),
    # rule 9 of the boundary graph: only the router reaches the store's write primitives
    Mutation("1B-store-writer-rule-dropped", "1b", "the boundary checker no longer reports a store write primitive reached outside the store writers",
             (CB + "test_only_the_store_writers_reach_store_write_primitives", CB + "test_store_writes_are_the_routers_under_the_real_graph"),
             target="tools/check_boundaries.py", old="    violations.extend(store_write_violations(rel, mod, refs, cfg))\n", new=""),
    Mutation("1B-store-writer-defining-module-flagged", "1b", "the store module is reported for using its own primitives (the rule over-restricts)",
             (CB + "test_only_the_store_writers_reach_store_write_primitives",), target="tools/check_boundaries.py",
             old="            if (owner is not None and owner.name != mod.name and (lineno, primitive) not in seen", new="            if (owner is not None and (lineno, primitive) not in seen"),
    Mutation("1B-store-writer-attribute-chains-ignored", "1b", "only imports are checked, not attribute chains (api.Store.insert passes)",
             (CB + "test_only_the_store_writers_reach_store_write_primitives",), target="tools/check_boundaries.py",
             old='        if kind == "builtin":\n            continue\n        for primitive in cfg.store_write_primitives:',
             new='        if kind != "import":\n            continue\n        for primitive in cfg.store_write_primitives:'),
    Mutation("1B-store-writer-config-unchecked", "1b", "a store_writers entry naming no module is accepted",
             (CB + "test_store_rule_configuration_is_checked",), target="tools/check_boundaries.py",
             old='                errors.append(f"{config_rel}: {key} names undeclared module {name!r}")', new="                pass"),
    Mutation("1B-real-graph-writers-widened", "1b", "the real graph lets the composition root write the store",
             (CB + "test_store_writes_are_the_routers_under_the_real_graph",), target="gen2/boundaries.toml",
             old='store_writers = ["router"]', new='store_writers = ["router", "app"]'),
    Mutation("1B-real-graph-primitives-dropped", "1b", "the real graph lists no store write primitive (rule 9 off)",
             (CB + "test_store_writes_are_the_routers_under_the_real_graph",), target="gen2/boundaries.toml",
             old='store_write_primitives = ["gen2.store.api.Store", "gen2.store.api.open_store", "gen2.store.api.adopt_in_memory", "gen2.store.db.connect"]',
             new='store_write_primitives = []\nstore_writers_unused = ["gen2.store.api.Store"]'),
]


# Guards deliberately kept as a second layer behind another guard that
# always fires first for every row that reaches them, so no test can kill
# their removal alone. Listed so a reviewer does not mistake them for missed
# coverage; each names the first layer (which IS in the inventory).
SECOND_LAYER = {
    "export_delivery_receipts CHECK (connector_type IN ('sql', 'jsonl_file', 'webhook', 'extension')) (0d)":
        "a receipt is refused unless its manifest names that connector with that type (export_delivery_receipts_expected_connector, "
        "D48-*), and a manifest names only declared types (outbox_events_connectors_declared, 0D-connectors-*); the trigger fires before "
        "the CHECK, so an undeclared type is refused there first. The CHECK is the store's last word on the vocabulary if either trigger goes",
    "outbox_events_generation_is_one_approved_revision: the source_revision and source_content_hash conjuncts alone (0d)":
        "an approval names exactly one source revision and hash (outbox_events_only_approved, A2-publication-revision/-hash), so a re-export "
        "whose revision or hash differs cites a different approval as well; the three are mutated together as one dimension "
        "(0D-one-generation-another-approved-revision), and the approval conjunct alone (0D-one-generation-another-approval)",
    "screening_provider_needs_qualified_authority (trigger)":
        "screening_assessments_bound requires the receipt's commit_operation_id to be the assessment's recording operation; a receipt has a "
        "commit_operation_id only for commit_reversible_action, which a CHECK allows only at qualified authority (A10-screening-binds-commit)",
    "verification_receipts CHECK (verdict != 'supports' OR exact_quote.status IN ('matched', 'not_applicable'))":
        "a mismatched quote is always quarantined (quote_checks CHECK, A6-D32-byte-mismatch) and a matched/mismatched status needs a bound check "
        "(A6-quote-check-iff-status), so verification_receipts_bindings refuses support on it first (A6-quote-binding-*)",
    "invocations CHECK: the unknown_episode >= 1 conjunct of the outcome_unknown shape (RA4)":
        "an invocation is inserted admitted with unknown_episode 0 (column CHECK >= 0), and every entry into outcome_unknown takes "
        "exactly the previous number + 1 (invocations_unknown_episode_is_fresh, RA4-entry-takes-next-identity), so the conjunct cannot fail on its own",
    "facets/obligations_rating_is_what_the_operator_rated: the d.kind = 'rating_approval' conjunct (RA2)":
        "only a rating decision carries a payload (operator_decisions CHECK, RA2-payload-only-on-rating-decisions) and a decision without one joins "
        "no payload row, so a decision of another kind is refused before the kind conjunct is read",
    "contract_approval_pointer_set_by_approval: its superseded case (RA3-R — no pointer first recorded by draft -> superseded)":
        "since 0a-repair-3 ruling 1, contract_status_forward_only refuses draft -> superseded outright (R1c-draft-superseded-edge-restored), and a "
        "pointer can only be first recorded on a draft (a non-draft holds one by CHECK, R1c-approved-without-decision); the trigger's approved "
        "exemption and the trigger itself are mutated (RA3R-approval-refused-too, RA3R-dropped). Which of the two triggers reports first is "
        "SQLite trigger order, which no test may depend on",
    "intake_briefs_confirmation_bound: each subject conjunct alone (topic; brief id and version; hash)":
        "a brief_confirmation is recorded only about a stored brief with exactly that topic, id, version and hash (IB-decision-subject-exists), "
        "and brief hashes are unique, so any one of them identifies the same stored subject as the rest; they are mutated together "
        "(IB-confirmation-subject). At admission the pins are not otherwise checked, so there each conjunct is mutated alone (A4-brief-confirmation-*)",
    "intake_briefs CHECKs: confirmed/archived hold a confirming decision; awaiting/cancelled hold none (0b)":
        "a brief is confirmed only through intake_briefs_confirmation_bound, which needs an existing decision (IB-confirmation-bound-dropped), "
        "archived is reached only from confirmed (IB-archive-from-awaiting), and the pointer is set only by that transition and never "
        "changes (IB-pointer-dropped, IB-pointer-changes-after); so neither CHECK can be the first refusal",
    "claims_accepted_support_needs_receipt: its required-tier, obtained-tier and performed-checks conjuncts (RA5, re-checked at promotion)":
        "a load-bearing-use receipt is written only at its claim's own required tier (verification_receipts_use_matches_claim, RA5-use-matches-claim-*), "
        "'supports' never exceeds the obtained tier (verification_receipts CHECK), and a load-bearing support cannot record an unperformed check "
        "(A6-load-bearing-support-checks-performed); the trigger's own use and verdict conjuncts are mutated (RA5-promotion-*)",
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
        elif m.scope:
            if m.scope in blocks:
                covered.add(m.scope)  # a scoped edit covers its scope only, whatever else shares the text
        else:
            for old in [m.old, *(o for o, _ in m.also)]:
                if old:  # unscoped edits must match the DDL exactly once; credit the trigger holding that match
                    covered.update(name for name, body in blocks.items() if old in body and ddl.count(old) == 1)
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
            for dependent in how[2:]:  # modules that bound names from the mutated one at import
                importlib.reload(importlib.import_module(dependent))
            loaded = [importlib.reload(importlib.import_module(name)) for name in modules]
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(mod) for mod in loaded)
        result = _Collector()
        suite.run(result)
        return result


def _run_file_mutation_unmutated(m: Mutation) -> _Collector:
    """The file target's killer modules against the file as it is (a mutation
    that finds its text is only meaningful if these pass unmutated). An "attr"
    target is run from an unmodified temp copy, exactly as its mutants are, so
    a file that only works from its own location (an import resolved relative
    to itself) fails here instead of letting every mutant "die" of it."""
    import importlib
    import tempfile

    modules = sorted({k.split(".")[0] for k in m.killers})
    how = FILE_TARGETS[m.target]
    with tempfile.TemporaryDirectory() as tmp:
        loaded = [importlib.import_module(name) for name in modules]
        if how[0] == "attr":
            path = Path(tmp) / Path(m.target).name
            path.write_text((ROOT / m.target).read_text(encoding="utf-8"), encoding="utf-8")
            holder = importlib.import_module(how[1])
            original = getattr(holder, how[2])
            setattr(holder, how[2], path)
        try:
            suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(mod) for mod in loaded)
            result = _Collector()
            suite.run(result)
        finally:
            if how[0] == "attr":
                setattr(holder, how[2], original)
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
