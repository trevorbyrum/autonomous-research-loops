"""Replay epoch draws remain distinct and repeat across equivalent runs."""
import os
import runpy
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gen2.store import api, db
from gen2.tests.test_replay_seams import at_once

SEAMS = runpy.run_path(str(Path(__file__).resolve().parents[2] / 'tools/gen2_replay_seams.py'))


class EpochSeamTest(unittest.TestCase):
    def test_maintenance_and_child_draws_share_distinct_epochs(self):
        connect = SEAMS['sqlite_epochs'](sqlite3.connect)
        code = """import tempfile,json
from pathlib import Path
from gen2.store import api,db
with tempfile.TemporaryDirectory() as td:
 p=Path(td)/'child.db'
 api.open_store(p,create=True).close()
 api.Store.maintain(p,lambda path:None)
 with api.open_store(p) as store:
  print(json.dumps(db.generation_state(store._conn)[0]))
"""
        for _ in range(2):
            with tempfile.TemporaryDirectory() as registry, patch.dict(os.environ, {SEAMS['ENV']: registry}):
                with patch.object(sqlite3, 'connect', connect):
                    paths = [Path(registry) / name for name in ('first.db', 'second.db')]
                    for p in paths:
                        with api.open_store(p, create=True) as store:
                            self.assertEqual(db.generation_state(store._conn)[:2], (None, 0))
                    for ordinal, p in enumerate((*paths, paths[0]), 1):
                        api.Store.maintain(p, lambda path: None)
                        with api.open_store(p) as store:
                            self.assertEqual(db.generation_state(store._conn)[:2], (f'{ordinal:032x}', 0))
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
