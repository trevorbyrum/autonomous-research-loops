"""Pure conversion boundaries, paired with existing result controls."""
from .base import Mutation

TARGET = 'gen2/router/accounting.py'
TEST = 'test_accounting_capture.CaptureTest.'
MUTATIONS, CONTROLS = [], {}
for name, expression, control in (
    ('units', 'a.candidate_units(convert_inventory(topic_id, raw, history))',
     'test_accounting.DurableAccountingTest.test_reads_committed_inventories_without_writes_or_clock'),
    ('inventory', 'convert_inventory(topic_id, raw, history)', 'test_accrual.SnapshotTest.test_control_context'),
    ('coverage', 'convert_coverage_snapshot(raw, topic_id, history)', 'test_branch_windows.AdmissionTest.test_control')):
    old = expression.replace('raw', 'self.capture(topic_id, history)')
    mid = '2D6A2-' + name + '-transaction'
    MUTATIONS.append(Mutation(mid, '2d-6a-p2', name, (TEST + 'test_existing_entries_and_precontract_control',),
        target=TARGET, old='        return ' + old,
        new='        raw = self.capture(topic_id, history)\n        with self._core._store.transaction():\n            return ' + expression))
    CONTROLS[mid] = {'controls': [control], 'why':
        'The existing result oracle exercises the relocated reader with valid inputs; a read-only writer transaction changes no result, while the separate boundary killer requires conversion after closure.'}
