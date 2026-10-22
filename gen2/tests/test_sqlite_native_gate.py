"""Literal contract fixtures run the native-write gate as a program."""
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


if __name__ == "__main__":
    unittest.main()
