"""Recorded-content predicates with isolated controls; SQL cannot hash/authenticate bytes."""
import json
import sqlite3
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import db
from gen2.tests import store_fixtures as sf
from gen2.tests.raw_detailed_receipt_fixtures import RawAssessmentFixture
from gen2.tests.ddl_fixtures import restore_triggers
from gen2.tests.detailed_receipt_fixtures import seed_checks, attach_checks
from gen2.tests import test_store_acquisition_relationships as relationships
from gen2.tests.store_fixtures import FIND_REQUEST, TOPIC, T, h

FULL = {"identity": "rec-1", "kind": "full_text", "text": "Complete fixture text"}


def response(record, others=()):
    # Equal sizes permit relational counterfactuals; these are raw SQL operands,
    # not a claim that different octets really have the same authenticated hash.
    return json.dumps({"records": [record, *others]}).encode().ljust(512)


class ContentDDLTest(relationships.RelationshipTest):
    test_binding = test_verifier = test_immutable = test_control = None
    test_relationships = test_relationship_controls = test_natural_key = None
    ATTRIBUTED = True

    def setUp(self):
        if not self.ATTRIBUTED:  # Isolated compatibility/refusal probes use the base fixture.
            super().setUp()
            self.artifact(size=512)
            self.source(version='v4')
            return
        requested = sf.DDL_TEXT
        with patch.object(sf, 'DDL_TEXT', db.schema_text()):
            super().setUp()
            self.assessments = RawAssessmentFixture(self, response(FULL))
            ref = self.assessments.source
            self.x('INSERT INTO artifacts (content_hash,size_bytes,media_type,staged_at) VALUES (?,?,?,?)',
                ref['content_hash'], ref['size_bytes'], ref['media_type'], T)
            self.x("INSERT INTO artifact_topics VALUES (?,?,'inv_pppppppp',?)", ref['content_hash'], TOPIC, T)
            self.source(version='v4')
            seed_checks(self.assessments, dict(topic_id=TOPIC,
                claim=dict(claim_id='clm_00000001', claim_revision=1),
                source=dict(work_id='wrk_00000001', source_version='v4'),
                cited_spans=[dict(start=0, end=5, locator=dict(kind='page', value='3'))],
                obtained_content_hash=ref['content_hash'], extraction=dict(method='canonical_bytes'),
                verifier_invocation_id='inv_vvvvvvvv', checks=self.CHECKS_OK))
        self.restore_views(requested)
        restore_triggers(self, requested)

    def restore_views(self, requested):
        query = "SELECT name,sql FROM sqlite_schema WHERE type='view' ORDER BY rowid"
        with sqlite3.connect(':memory:') as reference:
            reference.executescript(requested)
            expected = list(reference.execute(query))
        for name, _ in self.rows(query):
            self.x('DROP VIEW ' + name)
        for _, sql in expected:
            self.x(sql)
        self.assertEqual(self.rows(query), expected)

    def source(self, **changes):
        if self.ATTRIBUTED:
            changes.setdefault('digest', self.assessments.source['content_hash'])
        super().source(**changes)

    def raw(self, **changes):
        if self.ATTRIBUTED and changes.get('content_hash') == h('e'):
            changes['content_hash'] = self.assessments.source['content_hash']
        super().raw(**changes)

    def verify(self, *args, historical=False, **changes):
        if not self.ATTRIBUTED:
            return super().verify(*args, historical=historical, **changes)
        if changes.get('obtained') == h('e'):
            changes['obtained'] = self.assessments.source['content_hash']
        original = self.x
        def insert(sql, *params):
            if not historical and sql.startswith('INSERT INTO verification_receipts ('):
                cols = sql.split('(', 1)[1].split(')', 1)[0].split(', ')
                row = dict(zip(cols, params)); doc = json.loads(row['receipt'])
                attach_checks(self.assessments, doc)
                for key in ('receipt', 'cited_spans', 'acquisition'):
                    row[key] = canonical.canonical_bytes(doc if key == 'receipt' else doc[key]).decode()
                params = tuple(row[col] for col in cols)
            return original(sql, *params)
        with patch.object(self, 'x', side_effect=insert):
            super().verify(*args, historical=historical, **changes)

    def acquired(self, record, others=(), **changes):
        self.raw(source_version=changes.pop("source_version", "v4"), content_hash=h("e"),
            response_bytes=response(record, others), **changes)
        from gen2.tests.extraction_receipt_fixtures import seed
        seed(self)

    def content_receipt(self, tier, rid="ver_content1", **changes):
        version = changes.pop("version", "v4")
        acq = {"route": "gateway:crossref", "retrieved_at": T, "gateway_call_ref": "gw-call:1", "cache_reuse": False}
        acq.update(changes.pop("acquisition", {}))
        self.verify(rid, tier=tier, required=changes.pop("required", tier), use=changes.pop("use", "sampled"), method=changes.pop("method", "canonical_bytes"),
            extraction=changes.pop("extraction", "inv_pppppppp"), obtained=h("e"), quote=("not_applicable", None),
            gateway=acq["gateway_call_ref"], receipt_overrides={"source": {"work_id": "wrk_00000001", "source_version": version}, "acquisition": acq},
            column_overrides={"source_version": version, "acquisition": json.dumps(acq)}, **changes)

    def refusal(self, tier, **changes):
        before = self.rows("SELECT * FROM verification_receipts")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "tier exceeds recorded content"):
            self.content_receipt(tier, **changes)
        self.assertEqual(self.rows("SELECT * FROM verification_receipts"), before)

    def test_content_controls(self):
        for record, tier in (({"identity": "rec-1", "title": "Fixture"}, "bibliographic"),
                ({"identity": "rec-1", "abstract": "Fixture abstract"}, "abstract"), (FULL, "full_text")):
            with self.subTest(tier=tier):
                self.x("SAVEPOINT content")
                try:
                    self.acquired(record)
                    self.content_receipt(tier)
                    self.assertEqual(self.rows("SELECT access_tier FROM verification_receipts WHERE verification_receipt_id = 'ver_content1'"), [(tier,)])
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                finally:
                    self.x("ROLLBACK TO content")
                    self.x("RELEASE content")

    def test_bibliographic_control(self):
        self.acquired({"identity": "rec-1", "title": "Fixture"})
        self.content_receipt("bibliographic")

    def test_full_text_control(self):
        self.acquired(FULL)
        self.content_receipt("full_text")

    def test_lower_tier_control(self):
        self.acquired(FULL)
        self.content_receipt("bibliographic")

    def test_shapes(self):
        for field, tier in (("abstract", "abstract"), ("text", "full_text")):
            for value in (None, True, 1, [], {}, "", " \t\r\n", "\v", "\f\u00a0", "\u0085", "\u1680", "\u2007", "\u2028", "\u2029",
                    "\u202f", "\u205f", "\u3000", "\u00ad", "\u034f", "\u061c", "\u115f", "\u17b4", "\u180f",
                    "\u200b", "\u202a", "\u2065", "\u3164", "\ufe0f", "\ufeff", "\uffa0", "\ufff8",
                    "\U0001bca3", "\U0001d17a", "\U000e0000", "\U000e0fff"):
                with self.subTest(field=field, value=value):
                    self.x("SAVEPOINT content")
                    try:
                        self.acquired({"identity": "rec-1", "kind": "full_text", field: value})
                        self.refusal(tier)
                        self.content_receipt("bibliographic")
                    finally:
                        self.x("ROLLBACK TO content")
                        self.x("RELEASE content")

    def test_kind(self):
        self.acquired({**FULL, "kind": "article"})
        self.refusal("full_text")
        self.content_receipt("bibliographic")

    def test_record_identity(self):
        self.acquired({"identity": "rec-1"}, [{**FULL, "identity": "rec-2"}, "opaque metadata"])
        self.refusal("full_text")
        self.content_receipt("bibliographic")

    def observation2(self, *, invocation="inv_pppppppp", lane="crossref", call="gw-call:1", coverage="searched_ok"):
        request = FIND_REQUEST.replace("crossref", lane)
        self.x("""INSERT INTO search_observations (observation_id, invocation_id, topic_id, request_identity, attempt,
            lane, request, obligation_ids, started_at, ended_at, coverage_state, result_count, completeness,
            error_class, capability_fact_id, policy_version, cost_units, gateway_call_ref, page_outcome, continuation)
            SELECT 'o2', ?, topic_id, request_identity, 2, ?, ?, obligation_ids, started_at, ended_at, ?, result_count,
            completeness, error_class, capability_fact_id, policy_version, cost_units, ?, page_outcome, continuation
            FROM search_observations WHERE observation_id = 'o1'""",
            invocation, lane, request, coverage, call)
        return dict(observation_id="o2", acquired_by_invocation_id=invocation, attempt=2, lane=lane,
            gateway_call_ref=call, request_bytes=request.encode())

    def test_availability(self):
        changes = self.observation2(coverage="metadata_only")
        self.event(observation="o2")
        self.acquired({**FULL, "identity": "rec-2", "abstract": "Fixture abstract"}, event_id="e2", provider_record_id="rec-2", **changes)
        self.refusal("full_text")
        self.content_receipt("abstract")

    def test_reproduction(self):
        self.acquired({**FULL, "reproduced": True, "access_tier": "reproduced"})
        self.refusal("reproduced")
        self.content_receipt("full_text")

    def test_verdicts(self):
        self.acquired({"identity": "rec-1", "abstract": "Fixture abstract"})
        for verdict in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier"):
            with self.subTest(verdict=verdict):
                self.refusal("full_text", verdict=verdict)
        self.content_receipt("abstract")

    def test_lineage(self):
        for name in ("work", "version", "verifier", "acquirer", "call", "time", "route"):
            with self.subTest(selector=name):
                self.x("SAVEPOINT lineage")
                try:
                    self.acquired({"identity": "rec-1"})
                    changes = self.distractor(name)
                    self.acquired({**FULL, "identity": "rec-2"}, event_id="e2", provider_record_id="rec-2", **changes)
                    self.refusal("full_text")
                    self.content_receipt("bibliographic")
                    self.assertEqual(self.rows("PRAGMA foreign_key_check"), [])
                finally:
                    self.x("ROLLBACK TO lineage")
                    self.x("RELEASE lineage")

    def distractor(self, name):
        changes = {}
        if name == "work":
            self.other_work()
            self.source(work="wrk_other001", version="v4")
            return {"work_id": "wrk_other001"}
        if name == "version":
            self.source(version="v5")
            changes["source_version"] = "v5"
        if name == "verifier":
            self.x("UPDATE leases SET released_at = ?, release_reason = 'finalized' WHERE lease_id = 'lease_vvvvvvvv'", T)
            self.lease("lease_newver1", 99, scope="verification")
            self.invocation("inv_newver01", kind="verification", lease="lease_newver1")
            changes["verifier_invocation_id"] = "inv_newver01"
        if name in ("acquirer", "call", "route"):
            if name == "acquirer":
                self.lease("lease_newacq1", 99, scope="checkpoint")
                self.invocation("inv_newacq01", kind="checkpoint", lease="lease_newacq1")
            changes.update(self.observation2(invocation="inv_newacq01" if name == "acquirer" else "inv_pppppppp",
                call="gw-call:2" if name == "call" else "gw-call:1", lane="core" if name == "route" else "crossref"))
        if name == "time":
            self.x("INSERT INTO retrieval_events VALUES ('e2', 'o1', ?, 'rec-2', 1, '2026-09-28T00:00:00Z')", TOPIC)
            self.x("INSERT INTO record_work_links VALUES ('e2', 'wrk_00000001', 'dedup-1', ?)", T)
            return {"retrieved_at": "2026-09-28T00:00:00Z"}
        self.event(observation=changes.get("observation_id", "o1"))
        return changes

    def test_unicode_text_controls(self):
        for field, tier in (("abstract", "abstract"), ("text", "full_text")):
            for value in ("\v\u1680Results\u2029", "\u200bFindings\ufeff", "\u200d文\U000e0100", "."):
                with self.subTest(field=field, value=value):
                    self.x("SAVEPOINT unicode_control")
                    try:
                        self.acquired({"identity": "rec-1", "kind": "full_text", field: value})
                        self.content_receipt(tier)
                        self.assertEqual(self.rows("SELECT access_tier FROM verification_receipts WHERE verification_receipt_id = 'ver_content1'"), [(tier,)])
                    finally:
                        self.x("ROLLBACK TO unicode_control")
                        self.x("RELEASE unicode_control")
