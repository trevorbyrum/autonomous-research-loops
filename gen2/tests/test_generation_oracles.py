"""Exact metadata expectations without excluding it from full snapshots."""
import copy

from gen2.tests import router_fixtures as rf, supervisor_fixtures as sf


class GenerationOracleTest(rf.RouterTestCase):
    def test_bad_generation_or_business_effect_is_refused(self):
        with self.store.transaction():
            self.store.update('queue_entries', {'topic_id': rf.TOPIC}, {'priority': 1})
        before = self.state(exclude=())
        for row in (('other', 'a' * 32, 1), ('store', 'b' * 32, 1),
                    (*before['store_generation'][0][:2], before['store_generation'][0][2] + 2)):
            after = copy.deepcopy(before)
            after['store_generation'] = [row]
            with self.subTest(row=row), self.assertRaises(AssertionError):
                self.assert_generation_delta(before, after, 1)
        after = copy.deepcopy(before)
        singleton, epoch, counter = before['store_generation'][0]
        after['store_generation'] = [(singleton, epoch, counter + 1)]
        self.assert_generation_delta(before, after, 1)
        self.assertEqual(after, before)
        self.x('UPDATE queue_entries SET priority=priority+1')
        with self.assertRaises(AssertionError):
            self.assert_audited_state(before, 0, audits=0)


class SupervisorGenerationTest(sf.SupervisedTestCase):
    def test_claim_effect_and_same_handle_replay(self):
        before = self.state(exclude=())
        grant = self.claim(sf.MAIN, 'checkpoint')
        after = self.state(exclude=())
        # One transaction records the lease, invocation and audit.
        self.assert_generation_delta(before, after, 1)
        self.assertEqual(self.ended()['other_tables'], [])
        request = dict(invocation_id=grant['invocation_id'], kind='checkpoint', topic_id=rf.TOPIC,
            station_id='station-1', config_bundle_hash=rf.CONFIG, deadline_at=rf.DEADLINE,
            lease_expires_at=rf.EXPIRES)
        before = self.state(exclude=())
        self.assertEqual(self.router.claim(request)['status'], 'replayed')
        self.assertEqual(self.state(exclude=()), before)
        self.x("UPDATE store_generation SET epoch=?", 'f' * 32)
        self.assertEqual(self.ended()['other_tables'], ['store_generation'])
