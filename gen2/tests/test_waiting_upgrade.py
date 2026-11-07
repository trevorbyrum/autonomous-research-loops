"""§4.6 exception: synthetic exact predecessor, preserved rows/dossiers and transactional upgrade; real-store debt stays open."""
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from gen2.core import canonical
from gen2.store import api, db, upgrade_waiting as upgrade
from gen2.tests import test_dossier_record as dossier_tests


class UpgradeTest(unittest.TestCase):
    def test_exact_predecessor_copy_preserves_rows_and_reopens(self):
        """Only the waiting edge changes; source bytes, dossier hashes and all authoritative rows are retained."""
        text = db.schema_text().replace("OLD.status = 'resting' AND NEW.status IN ('active', 'queued', 'held', 'awaiting_judgment', 'retired')",
                                       "OLD.status = 'resting' AND NEW.status IN ('active', 'queued', 'held', 'retired')")
        with patch.object(db, "schema_text", return_value=text):
            case = dossier_tests.DossierCase()
            case.setUp()
            self.addCleanup(case.tearDown)
            case.record()
            before = case.state()
        source = case.directory / "store.sqlite3"
        case.router.close()
        case.db.close()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "kept.sqlite3"
        shutil.copy2(source, path)
        digest = canonical.bytes_digest(source.read_bytes())
        with self.assertRaises(db.StoreOpenError):
            api.open_store(path)
        with closing(sqlite3.connect(path)) as conn:
            upgrade._previous(conn)
        with patch.object(db, "check_schema_identity", side_effect=RuntimeError("rollback DDL")):
            with self.assertRaisesRegex(RuntimeError, "rollback DDL"):
                upgrade.upgrade(path)
        with closing(sqlite3.connect(path)) as conn:
            upgrade._previous(conn)
        upgrade.upgrade(path)
        with api.open_store(path):
            pass
        with closing(sqlite3.connect(path, isolation_level=None)) as conn:
            for table, rows in before.items():
                if table != "store_generation":
                    self.assertEqual(conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall(), rows, table)
            conn.execute("UPDATE queue_entries SET status='resting', state_revision=state_revision+1 WHERE topic_id='fleet-a:t1'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE queue_entries SET status='completed_with_qualified_conclusions', state_revision=state_revision+1 WHERE topic_id='fleet-a:t1'")
            conn.execute("UPDATE queue_entries SET status='awaiting_judgment', state_revision=state_revision+1 WHERE topic_id='fleet-a:t1'")
            self.assertEqual(conn.execute("SELECT status FROM queue_entries WHERE topic_id='fleet-a:t1'").fetchone(), ("awaiting_judgment",))
        prior = path.read_bytes()
        with self.assertRaisesRegex(db.StoreOpenError, "exact predecessor"):
            upgrade.upgrade(path)
        self.assertEqual(path.read_bytes(), prior)
        self.assertEqual(canonical.bytes_digest(source.read_bytes()), digest)
