"""tools/gen2_prompt_pins.py: the pin is the byte digest of the mounted file.
Oracle: hashlib, not the code under test. Limit: the bundle schema's own
`executors` shape is T12-A's and is not checked here."""
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

from gen2.tests import children

_spec = importlib.util.spec_from_file_location("prompt_pins_under_test", children.path("tools/gen2_prompt_pins.py"))
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)


class PromptPinsTest(unittest.TestCase):
    def run_tool(self, files, *args):
        with tempfile.TemporaryDirectory() as root:
            for name, data in files.items():
                (Path(root) / name).write_bytes(data)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = tool.main([root, *args])
            return code, out.getvalue(), err.getvalue()

    def test_pins_are_byte_digests_ordered_by_name(self):
        body = b"line one\r\nline two\n"   # CRLF kept: bytes, not a normalized text
        code, out, _ = self.run_tool({"research_pass.scope.md": body, "checkpoint.review.md": b"x"}, "--version", "3")
        self.assertEqual(code, 0)
        pinned = json.loads(out)
        self.assertEqual([(p["kind"], p["purpose"]) for p in pinned], [("checkpoint", "review"), ("research_pass", "scope")])
        self.assertEqual(pinned[1]["prompt"], {"version": 3, "content_hash": "sha256:" + hashlib.sha256(body).hexdigest()})

    def test_misnamed_file_is_refused_not_skipped(self):
        for name in ("notes.md", "bogus.scope.md", "research_pass.scope.txt"):
            with self.subTest(name=name):
                code, out, err = self.run_tool({"research_pass.scope.md": b"x", name: b"y"})
                self.assertEqual((code, out), (2, ""))
                self.assertIn(name, err)
