"""Admit assessments into a raw owner's disposable store through the Router.

The owner supplies real examined bytes. Raw acquisition response counterfactuals
remain SQL relationship operands; this bridge authenticates assessment inputs.
"""
from gen2.store import api
from gen2.tests import router_fixtures as routed
from gen2.tests import store_fixtures as sf


class RawAssessmentFixture(routed.RouterTestCase):
    def __init__(self, owner, raw):
        super().__init__()
        self.db = owner.db
        self.store = api.adopt_in_memory(self.db)
        self.spool = routed.Spool()
        self.spool.conn = self.db
        self.clock, self.ids, self.faults = routed.Clock(sf.T), routed.Ids(), {}
        self.router = self.make_router()
        # The old raw builders use zero-duration leases and do not advance the
        # queue with their operation rows. Make the admission context live and
        # align its revision before authenticated Router commits, under full DDL.
        owner.x("UPDATE leases SET expires_at='2026-12-31T00:00:00Z' WHERE lease_id='lease_vvvvvvvv'")
        owner.x("UPDATE invocations SET deadline_at='2026-12-30T00:00:00Z' WHERE invocation_id='inv_vvvvvvvv'")
        owner.to_running('inv_vvvvvvvv')
        owner.x("UPDATE queue_entries SET state_revision=(SELECT MAX(state_revision_after) FROM operation_receipts WHERE topic_id=?) WHERE topic_id=?",
            sf.TOPIC, sf.TOPIC)
        self.verifier = self.router._grant('fixture', 'inv_vvvvvvvv')
        self.source = self.artifact(raw, 'application/json')
