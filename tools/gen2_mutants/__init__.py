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
from .second_layer import SECOND_LAYER, SECOND_LAYER_TRIGGERS

MUTATIONS: list[Mutation] = [
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
]
