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


def dossier(name, killer, old, new, target=TARGET):
    mid = '2D6A2-' + name
    MUTATIONS.append(Mutation(mid, '2d-6a-p2', name, ('test_dossier_inputs.' + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {'controls': ['test_dossier_inputs.AdapterTest.test_control_route'], 'why':
        'The approved native empty-history route retains its exact hash and typed contract; the independent killer requires the missing admission, complete history or history-bound hash.'}


dossier('approved', 'RefusalTest.test_requires_approved_contract', 'raise Refusal("no_approved_contract", topic_id)', 'pass')
dossier('attributed', 'AdapterTest.test_unattributed_contract_refuses', 'and r["approved_by_decision_id"] is not None for r in records(raw,', 'for r in records(raw,')
dossier('hash-history', 'HistoryTest.test_adverse_then_support_and_attention_retained', 'input_hash(raw, history))', 'input_hash(raw, "native"))')
dossier('route-hash-codec', 'HistoryTest.test_adverse_then_support_and_attention_retained', '"history": history, "tables": tables', '"history": "native", "tables": tables', 'gen2/store/capture.py')
for name, group, rows in (('receipts', 'verification_receipts', 't.rows[-1:]'), ('attention', 'holds', '()')):
    projection = f'type(raw)(raw.topic_id, tuple(type(t)(t.name, t.columns, t.json_columns, {rows} if t.name == "{group}" else t.rows) for t in raw.tables))'
    dossier(name, 'HistoryTest.test_adverse_then_support_and_attention_retained', 'return DossierInput(raw,', 'return DossierInput(' + projection + ',')
