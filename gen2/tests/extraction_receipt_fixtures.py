"""Recorded fixture outputs for receipt controls; no extractor execution claim."""
import json

from gen2.core import canonical
from gen2.tests import store_fixtures as sf


def seed(case, verifier=None):
    rows = case.db.execute("SELECT * FROM source_acquisition_content_tiers").fetchall()
    names = [d[0] for d in case.db.execute("SELECT * FROM source_acquisition_content_tiers LIMIT 0").description]
    for values in rows:
        a = dict(zip(names, values))
        key = {k: a[k] for k in ("topic_id", "work_id", "source_version", "event_id", "verifier_invocation_id")}
        eid = "receipt-" + canonical.logical_hash(key)[7:]
        if case.rows("SELECT 1 FROM source_extractions WHERE extraction_id = ?", eid):
            continue
        routed = hasattr(case, 'router')
        if not case.rows("SELECT 1 FROM extractor_tools"):
            approval = dict(registry_version=1, operator_id="fixture-operator", reason="approve receipt fixture tool",
                tools=[dict(extractor_identity="receipt-tool", family="receipt-family")])
            if routed:
                case.assertEqual(case.router.register_extractor_registry(approval)['status'], 'registered')
            else:
                case.x("INSERT INTO audit_events VALUES ('aud_receipt_registry', ?, 'extractor_registry_registered', NULL, NULL, NULL, ?)", sf.T, json.dumps(approval))
                case.x("INSERT INTO extractor_registry_revisions VALUES (1, 'fixture-operator', 'approve receipt fixture tool', 'aud_receipt_registry', ?)", sf.T)
                case.x("INSERT INTO extractor_tools VALUES (1, 'receipt-tool', 'receipt-family')")
        revision, tool = case.rows("SELECT registry_version, extractor_identity FROM extractor_tools ORDER BY registry_version DESC, extractor_identity LIMIT 1")[0]
        inv = a['verifier_invocation_id']; op = 'op_receipt_' + inv
        if not routed and not case.rows("SELECT 1 FROM operation_receipts WHERE operation_id = ?", op):
            lease, generation = case.rows("SELECT i.lease_id, l.generation FROM invocations i JOIN leases l USING (lease_id) WHERE i.invocation_id = ?", inv)[0]
            sf.StoreTestCase.receipt(case, op, inv, lease=lease, gen=generation, tid=a['topic_id'], kind='interim_transition', before=100000 + len(case.rows('SELECT 1 FROM operation_receipts')))
        size, media = case.rows("SELECT size_bytes, media_type FROM artifacts WHERE content_hash = ?", a['content_hash'])[0]
        ref = dict(content_hash=a['content_hash'], size_bytes=size, media_type=media)
        row = dict(extraction_id=eid, **key, extractor_identity=tool, extractor_version='fixture/1', extracting_invocation_id=inv,
            output_ref=json.dumps(ref), supported_tier=('bibliographic', 'abstract', 'full_text')[min(a['recorded_tier_rank'], 3)-1],
            recorded_by_operation_id=op, created_at=sf.T, extractor_registry_version=revision)
        if routed:
            from gen2.tests.router_fixtures import empty_outcome
            grant = next(g for g in (verifier, getattr(case, 'verifier', None), getattr(case, 'grant', None)) if g and g['invocation_id'] == inv)
            record = {k: v for k, v in row.items() if k not in ('topic_id', 'extracting_invocation_id', 'recorded_by_operation_id', 'created_at')}
            record['output_ref'] = ref
            out = case.router.commit_outcome(case.envelope(grant, op + eid[-12:], {**empty_outcome(inv, 'interim_transition'), 'source_extractions': [record]}))
            case.assertEqual(out['status'], 'committed', out)
            continue
        case.x(f"INSERT INTO source_extractions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())


def attach(case, doc):
    if doc['extraction']['method'] == 'verifier_extraction':
        rows = case.rows("SELECT x.extraction_id, x.extractor_identity FROM source_extractions x JOIN source_acquisitions a USING(topic_id,work_id,source_version,event_id,verifier_invocation_id) WHERE x.work_id = ? AND x.source_version = ? AND x.verifier_invocation_id = ? AND x.extracting_invocation_id = ? AND a.content_hash = ? AND a.gateway_call_ref = ? AND a.retrieved_at = ? AND 'gateway:' || a.lane = ? ORDER BY x.extraction_id",
            doc['source']['work_id'], doc['source']['source_version'], doc['verifier_invocation_id'], doc['extraction']['produced_by_invocation_id'],
            doc['obtained_content_hash'], doc['acquisition']['gateway_call_ref'], doc['acquisition']['retrieved_at'], doc['acquisition']['route'])
        if rows:
            doc['extraction'].update(extraction_id=rows[0][0], extractor=rows[0][1])
    return doc
