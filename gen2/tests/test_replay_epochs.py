"""Replay epoch draws remain distinct and repeat across equivalent runs."""
import os
import runpy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gen2.store import db
from gen2.tests.test_replay_seams import at_once

SEAMS = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'tools/gen2_replay_seams.py'))


class EpochSeamTest(unittest.TestCase):
    def test_maintenance_and_child_draws_share_distinct_epochs(self):
        connect = SEAMS['sqlite_epochs'](sqlite3.connect)
        code = "import sqlite3,json; c=sqlite3.connect(':memory:'); print(json.dumps(c.execute('SELECT lower(hex(randomblob(16)))').fetchone()[0]))"
        for _ in range(2):
            with tempfile.TemporaryDirectory() as registry, patch.dict(os.environ, {SEAMS['ENV']: registry}):
                with connect(':memory:') as first, connect(':memory:') as second:
                    first.executescript(db.schema_text())
                    second.executescript(db.schema_text())
                    for conn in (first, second):
                        self.assertEqual(db.generation_state(conn)[:2], (None, 0))
                        conn.execute("INSERT INTO store_generation VALUES ('store',NULL,0)")
                        conn.execute("UPDATE store_generation SET epoch=lower(hex(randomblob(16)))")
                    self.assertEqual(db.generation_state(first)[:2], (f'{1:032x}', 0))
                    self.assertEqual(db.generation_state(second)[:2], (f'{2:032x}', 0))
                    first.execute("UPDATE store_generation SET epoch=lower(hex(randomblob(16)))")
                    self.assertEqual(db.generation_state(first)[:2], (f'{3:032x}', 0))
                self.assertEqual(sorted(at_once(registry, 2, code)), [f'{4:032x}', f'{5:032x}'])

    def test_without_registry_epoch_is_random_and_factory_is_preserved(self):
        class Custom(sqlite3.Connection):
            pass
        with patch.dict(os.environ, {SEAMS['ENV']: ''}):
            conn = SEAMS['sqlite_epochs'](sqlite3.connect)(':memory:', factory=Custom)
            self.addCleanup(conn.close)
            self.assertIsInstance(conn, Custom)
            epochs = [conn.execute('SELECT randomblob(16)').fetchone()[0] for _ in range(2)]
            self.assertEqual([len(e) for e in epochs], [16, 16])
            self.assertNotEqual(*epochs)
