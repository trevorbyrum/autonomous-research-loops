"""The gen-2 mutation inventory: every mutant tools/gen2_mutations.py runs,
in order, and the guards kept as a documented second layer.

Task 2r split the one inventory list (then in tools/gen2_mutations.py) so
that no file passes the 1,500-line limit: one module per family, by the task
that added it, each moved verbatim; MUTATIONS joins them in the original
order. base.py holds the Mutation record and the names the families share.
The runner keeps how each target is loaded (FILE_TARGETS) and everything
that runs a mutant.
"""
from __future__ import annotations

from . import ddl_0a, store_0b_0d, router_1b, supervisor_1c, registries_1d, operator_1e_1f, workflow_2a, size_2r, gateway_client_2b, gateway_client_2b17, gateway_client_2b18, metrics_2qa, metrics_2qa_repair, metrics_identity, metrics_source, metrics_closure, metrics_binding, metrics_scope, metrics_2q7, metrics_2qt1, router_composition_2qb2, router_composition_2qb3, router_composition_2qb6, router_composition_2qb7, router_composition_2qb8, router_composition_2qb10, router_evidence_2qb9, router_commit_2qb11, replay_2qt3
from .base import Mutation
from . import topic_capture_2d6a1
from . import accounting_capture_2d6a2
from . import detailed_support
from . import tier0_disabled_2d5
from . import span_cap
from . import detailed_checks, detailed_check_receipts
from . import validation_current_registry, own_extraction_receipts, validated_extraction_receipts, bound_extraction_support
from . import accounting_2c1
from . import assessments_2c2a
from . import lifecycle_2c2b1
from . import dispositions_2c2b2
from . import accrual_2c2b2b
from . import stopping_2c3
from . import stopping_2c3b
from . import stopping_2c3b2
from . import views_2c4b
from . import confidence_2c4a
from . import reconciliation_2c4a2
from . import reconciliation_2c4a3
from . import obligations_2d1
from . import branch_windows_2d2
from . import quote_matching_2d3
from . import source_artifacts_2d3b2
from . import governed_quotes_2d3b3
from . import quote_attention_2d3b4
from . import verification_attention_2d4
from . import reaccess_2d4b
from . import acquisitions_2d4b2
from . import canonical_receipts_2d4b3
from . import content_tiers_2d4b3b
from . import extraction_acquisitions_2d4b3c
from . import extraction_content_2d4b3c2
from . import table_availability_2d4b3d
from . import span_domain_2d4b3d_repair1
from . import exact_spans_2d4b3d_repair2
from . import extraction_records_2d4b3e1
from . import json_member_domain_repair1
from . import json_inventory_repair2
from . import attempted_request_json2
from . import json_rollout_json2b
from . import json_completion_json2b
from . import extraction_validations_v2
from . import extractor_registry_2d4b3e2
from .second_layer import SECOND_LAYER, SECOND_LAYER_TRIGGERS

MUTATIONS: list[Mutation] = [
    *topic_capture_2d6a1.MUTATIONS,
    *accounting_capture_2d6a2.MUTATIONS,
    *tier0_disabled_2d5.MUTATIONS,
    *detailed_support.MUTATIONS,
    *span_cap.MUTATIONS,
    *detailed_checks.MUTATIONS,
    *detailed_check_receipts.MUTATIONS,
    *ddl_0a.MUTATIONS,
    *store_0b_0d.MUTATIONS,
    *router_1b.MUTATIONS,
    *supervisor_1c.MUTATIONS,
    *registries_1d.MUTATIONS,
    *operator_1e_1f.MUTATIONS,
    *workflow_2a.MUTATIONS,
    *size_2r.MUTATIONS,
    *gateway_client_2b.MUTATIONS,
    *gateway_client_2b17.MUTATIONS,
    *gateway_client_2b18.MUTATIONS,
    *metrics_2qa.MUTATIONS,
    *metrics_2qa_repair.MUTATIONS,
    *metrics_identity.MUTATIONS,
    *metrics_source.MUTATIONS,
    *metrics_closure.MUTATIONS,
    *metrics_binding.MUTATIONS,
    *metrics_scope.MUTATIONS,
    *metrics_2q7.MUTATIONS,
    *metrics_2qt1.MUTATIONS,
    *router_composition_2qb2.MUTATIONS,
    *router_composition_2qb3.MUTATIONS,
    *router_composition_2qb6.MUTATIONS,
    *router_composition_2qb7.MUTATIONS,
    *router_composition_2qb8.MUTATIONS,
    *router_composition_2qb10.MUTATIONS,
    *router_evidence_2qb9.MUTATIONS,
    *router_commit_2qb11.MUTATIONS,
    *replay_2qt3.MUTATIONS,
    *accounting_2c1.MUTATIONS,
    *assessments_2c2a.MUTATIONS,
    *lifecycle_2c2b1.MUTATIONS,
    *dispositions_2c2b2.MUTATIONS,
    *accrual_2c2b2b.MUTATIONS,
    *stopping_2c3.MUTATIONS,
    *stopping_2c3b.MUTATIONS,
    *stopping_2c3b2.MUTATIONS,
    *views_2c4b.MUTATIONS,
    *confidence_2c4a.MUTATIONS,
    *reconciliation_2c4a2.MUTATIONS,
    *reconciliation_2c4a3.MUTATIONS,
    *obligations_2d1.MUTATIONS,
    *branch_windows_2d2.MUTATIONS,
    *quote_matching_2d3.MUTATIONS,
    *source_artifacts_2d3b2.MUTATIONS,
    *governed_quotes_2d3b3.MUTATIONS,
    *quote_attention_2d3b4.MUTATIONS,
    *verification_attention_2d4.MUTATIONS,
    *reaccess_2d4b.MUTATIONS,
    *acquisitions_2d4b2.MUTATIONS,
    *canonical_receipts_2d4b3.MUTATIONS,
    *content_tiers_2d4b3b.MUTATIONS,
    *extraction_acquisitions_2d4b3c.MUTATIONS,
    *extraction_content_2d4b3c2.MUTATIONS,
    *table_availability_2d4b3d.MUTATIONS,
    *span_domain_2d4b3d_repair1.MUTATIONS,
    *exact_spans_2d4b3d_repair2.MUTATIONS,
    *extraction_records_2d4b3e1.MUTATIONS,
    *json_member_domain_repair1.MUTATIONS,
    *json_inventory_repair2.MUTATIONS,
    *attempted_request_json2.MUTATIONS,
    *json_rollout_json2b.MUTATIONS,
    *json_completion_json2b.MUTATIONS,
    *extractor_registry_2d4b3e2.MUTATIONS,
    *extraction_validations_v2.MUTATIONS,
    *validation_current_registry.MUTATIONS,
    *own_extraction_receipts.MUTATIONS,
    *validated_extraction_receipts.MUTATIONS,
    *bound_extraction_support.MUTATIONS,
]
