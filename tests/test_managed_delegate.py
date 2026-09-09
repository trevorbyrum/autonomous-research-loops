import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "research_loops" / "chassis" / "managed-delegate.py"


class ManagedDelegateTests(unittest.TestCase):
    def test_role_profile_selects_packaged_adapter_without_model_guessing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner_dir = ROOT / "research_loops" / "runners"
            adapter = runner_dir / "testmanaged.sh"
            adapter.write_text("#!/bin/sh\nprintf '%s|%s|%s' \"$RESEARCH_LOOP_TESTMANAGED_MODEL\" \"$RESEARCH_LOOP_TESTMANAGED_BIN\" \"$RESEARCH_LOOP_TESTMANAGED_ARGV_JSON\"\n")
            adapter.chmod(0o755)
            try:
                env = os.environ | {"RESEARCH_LOOP_MANAGED_SECONDARY_PROFILE": '{"id":"sec","adapter":"testmanaged","model":"configured-secondary","executable":"configured-bin","argv":["--flag"]}'}
                result = subprocess.run(["python3", str(WRAPPER), "secondary", tmp, "task"], env=env, capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, 'configured-secondary|configured-bin|["--flag"]')
                adapter.write_text("#!/bin/sh\nexit 23\n")
                failed = subprocess.run(["python3", str(WRAPPER), "secondary", tmp, "task"], env=env, capture_output=True)
                self.assertEqual(failed.returncode, 23)
            finally:
                adapter.unlink(missing_ok=True)

    def test_chassis_note_uses_configured_wrapper_not_pinned_models(self):
        note = (ROOT / "research_loops" / "chassis" / "run-topic.sh").read_text()
        self.assertIn("managed-delegate.py secondary", note)
        self.assertIn("managed-delegate.py primary", note)
        self.assertNotIn("Use its default gpt-5.6-luna", note)


if __name__ == "__main__":
    unittest.main()
