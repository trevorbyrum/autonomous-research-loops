"""Raw DDL operands/immutability, without claiming SQL capture authentication."""
import sqlite3

from gen2.tests.store_fixtures import StoreTestCase, TOPIC, T, FIND_REQUEST, h


class DDLTest(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.populate_every_table()
        self.x("INSERT INTO source_artifacts VALUES (?, 'wrk_00000001', 'v2', ?, 'inv_pppppppp', 'op_00000001', ?)", TOPIC, h("7"), T)

    def raw(self, **changes):
        row = dict(topic_id=TOPIC, work_id="wrk_00000001", source_version="v2", content_hash=h("7"), observation_id="o1", event_id="e1",
            gateway_call_ref="gw-call:1", acquired_by_invocation_id="inv_pppppppp", attempt=1, lane="crossref", request_type="find",
            provider_record_id="rec-1", retrieved_at=T, verifier_invocation_id="inv_vvvvvvvv", request_identity=h("4"),
            request_bytes=FIND_REQUEST.encode(), response_bytes=b'{}        ', admitted_at=T)
        row.update(changes)
        self.x(f"INSERT INTO source_acquisitions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", *row.values())

    def test_control(self):
        self.raw()
        self.assertEqual(self.rows("SELECT source_version, acquired_by_invocation_id, verifier_invocation_id, request_bytes, response_bytes FROM source_acquisitions WHERE source_version = 'v2'"),
            [("v2", "inv_pppppppp", "inv_vvvvvvvv", FIND_REQUEST.encode(), b'{}        ')])

    def test_binding(self):
        for changes in ({"gateway_call_ref": "gw-call:2"}, {"attempt": 2}, {"lane": "core"}, {"request_type": "enrich"},
                {"acquired_by_invocation_id": "inv_vvvvvvvv"}, {"provider_record_id": "rec-other"},
                {"retrieved_at": "2026-09-28T00:00:00Z"}, {"request_identity": "sha256:" + "0" * 64},
                {"request_bytes": b'{}'}, {"response_bytes": b'{}         '}):
            with self.subTest(changes=changes), self.assertRaisesRegex(sqlite3.IntegrityError, "acquisition must bind"):
                self.raw(**changes)

    def test_verifier(self):
        with self.assertRaisesRegex(sqlite3.IntegrityError, "contract-admitted verifier"):
            self.raw(verifier_invocation_id="inv_pppppppp")

    def test_immutable(self):
        self.raw()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "immutable"):
            self.x("UPDATE source_acquisitions SET admitted_at = 'changed'")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "retained"):
            self.x("DELETE FROM source_acquisitions")
