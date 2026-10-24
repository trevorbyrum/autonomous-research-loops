"""Literal contract fixtures run the native-write gate as a program."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools/check_gen2_sqlite_native.py"
APIS = ("blobopen", "backup", "deserialize", "enable_load_extension", "load_extension")


class SQLiteNativeGateTest(unittest.TestCase):
    def gate(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel, text in files.items():
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True, timeout=60)
            subprocess.run(["git", "-C", str(root), "add", "--", *files], check=True, capture_output=True, timeout=60)
            return subprocess.run([sys.executable, str(TOOL), "--root", str(root)],
                                  env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "tools")},
                                  capture_output=True, text=True, timeout=60)

    def test_each_api_is_forbidden_as_call_and_attribute(self):
        for api in APIS:
            for source in (f"conn.{api}()\n", f"operation = arbitrary.{api}\n"):
                with self.subTest(api=api, source=source):
                    result = self.gate({"gen2/store/native.py": source})
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(f"gen2/store/native.py:1: forbidden SQLite native API {api}", result.stderr)

    def test_literal_getattr_is_forbidden(self):
        for api in APIS:
            for function in ("getattr", "builtins.getattr"):
                with self.subTest(api=api, function=function):
                    result = self.gate({"gen2/native.py": f'operation = {function}(renamed, "{api}")\n'})
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(f"forbidden SQLite native API {api}", result.stderr)

    def test_aliased_receiver_is_forbidden(self):
        result = self.gate({"gen2/native.py": "alias = connection\nalias.backup(target)\n"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("gen2/native.py:2: forbidden SQLite native API backup", result.stderr)

    def test_b3_surface_is_checked(self):
        for rel in ("gateway/research_gateway/native.py", "tools/gen2_native.py", "tools/check_native.py",
                    "tools/gen_native.py", "deploy/gen2/native.py", ".github/native.py"):
            with self.subTest(rel=rel):
                result = self.gate({rel: "conn.deserialize(image)\n"})
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"{rel}:1: forbidden SQLite native API deserialize", result.stderr)

    def test_test_trees_and_unrelated_names_pass(self):
        result = self.gate({"gen2/tests/test_native.py": "conn.blobopen()\n",
                            "gateway/tests/test_native.py": "conn.backup(target)\n",
                            "gen2/local.py": 'backup = 1\nlabel = "deserialize"\n# conn.load_extension()\n',
                            "outside/native.py": "conn.backup(target)\n"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no forbidden native write/replace APIs", result.stdout)

    def test_unreadable_syntax_fails_closed(self):
        result = self.gate({"gen2/broken.py": "def broken(\n"})
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("cannot check source", result.stderr)

    def test_store_dml_requires_the_generation_path(self):
        for sql in ('INSERT INTO works VALUES (1)', 'update works set value=1', 'DELETE FROM works'):
            for source in (f'conn.execute({sql!r})', f'class Store:\n def update(self):\n  conn.execute({sql!r})'):
                with self.subTest(sql=sql, source=source):
                    result = self.gate({'gen2/store/api.py': source})
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn('forbidden Store DML', result.stderr)

    def test_store_counter_and_maintenance_dml_are_allowed(self):
        source = "class Store:\n def _bump_once(self):\n  conn.execute('UPDATE store_generation SET generation=generation+1')\n def maintain(self):\n  conn.execute('INSERT INTO store_generation VALUES (1)')\n"
        self.assertEqual(self.gate({'gen2/store/api.py': source}).returncode, 0)

    def test_store_write_keyword_variants(self):
        for sql in ('INSERT OR ABORT INTO works VALUES (1)',
                    "UPDATE OR ABORT works SET identity_value='x'",
                    'DELETE /* c */ FROM works', 'REPLACE INTO works VALUES (1)',
                    'uPsErT works', "SELECT 'UPDATE'", 'SELECT 1; -- harmless\nDELETE FROM works',
                    "SELECT '--', '/*'; UPDATE works SET value=1",
                    'SELECT "--", `/*`, [--]; INSERT INTO works VALUES (1)'):
            with self.subTest(sql=sql):
                result = self.gate({'gen2/store/extra.py': f'conn.execute({sql!r})'})
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('forbidden Store DML', result.stderr)

        nested = '''class Store:
 def insert(self):
  conn.execute(f"INSERT INTO {conn.execute('DELETE FROM works')} ({columns}) VALUES ({values})")
'''
        self.assertEqual(self.gate({'gen2/store/api.py': nested}).returncode, 1)

    def test_store_comments_and_word_boundaries(self):
        for literal in ('SELECT 1 /* INSERT UPDATE DELETE REPLACE UPSERT */ -- UPDATE\n',
                        'SELECT 1 /* DELETE to EOF', 'inserted updated deleted replacements upserts'):
            with self.subTest(literal=literal):
                result = self.gate({'gen2/store/extra.py': f'label = {literal!r}'})
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_store_primitive_sites_are_allowed(self):
        source = '''"""Store API: INSERT, UPDATE, REPLACE documentation."""
class Store:
 def insert(self):
  conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({values})")
  raise ValueError('an insert names at least one column')
 def update(self):
  """UPDATE exactly one row."""
  conn.execute(f"UPDATE {table} SET {changes} WHERE {where}")
  raise ValueError('an update names its key and at least one change')
  raise ValueError(f"update of {table} matched {count} rows for {key} with {expect}; expected exactly one")
 def advance(self):
  """Delegates to update()."""
'''
        result = self.gate({'gen2/store/api.py': source})
        self.assertEqual(result.returncode, 0, result.stderr)
        # Neither the primitive nor documentation exception follows the bytes
        # to a different file, or admits an extra fixed SQL statement.
        self.assertEqual(self.gate({'gen2/store/extra.py': source}).returncode, 1)
        self.assertEqual(self.gate({'gen2/store/api.py': source + "\nconn.execute('DELETE FROM works')"}).returncode, 1)

    def test_other_modules_cannot_claim_the_helper_exception(self):
        source = "class Store:\n def _bump_once(self):\n  conn.execute('DELETE FROM works')\n"
        self.assertEqual(self.gate({'gen2/store/other.py': source}).returncode, 1)
        nested = "def unrelated():\n class Store:\n  def _bump_once(self):\n   conn.execute('DELETE FROM works')\n"
        self.assertEqual(self.gate({'gen2/store/api.py': nested}).returncode, 1)


if __name__ == "__main__":
    unittest.main()
