"""S10: tool-less seed and plan data; no native run, Docker, provider or qualification claim."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


class T10Apparatus(unittest.TestCase):
    def test_seed_case_and_relay_plan_bind_the_reviewed_bytes(self):
        root = Path(__file__).resolve().parents[2]
        modules = {}
        for name in ("live", "fixture", "runner"):
            spec = importlib.util.spec_from_file_location(name, root / f"deploy/gen2/live/{name}.py")
            modules[name] = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(modules[name])
        live, fixture, runner = (modules[n] for n in ("live", "fixture", "runner"))
        source, data = root / "deploy/gen2/live", root / "examples/gen2/t10-fixture"
        apparatus = json.loads((data / "apparatus.json").read_bytes())
        seed = data / apparatus["seed_source"]
        expected = {"config.toml": live.runner_config((source / "runner-config.toml").read_bytes()),
                    "models.json": live.model_catalog((source / "fixtures/catalog/models.json").read_bytes()),
                    "auth.json": b'{"OPENAI_API_KEY":"2e1-fixture-accepted"}\n'}
        self.assertEqual({p.name for p in seed.iterdir()}, set(expected))
        for name, raw in expected.items():
            self.assertEqual((seed / name).read_bytes(), raw)
            digest = hashlib.sha256(raw).hexdigest()
            self.assertIn(digest, runner.PINS[name])
            self.assertEqual(apparatus["seed_pins"][name], "sha256:" + digest)
        self.assertEqual(apparatus["fixture_command"], ["/opt/live/fixture.py", "tool-less"])
        status, _, stream = fixture.response(apparatus["fixture_case"], 1, {"model": "gpt-5.4", "stream": True, "tools": []})
        self.assertEqual(status, 200)
        self.assertIn(b'"text": "2e1 complete"', stream)
        self.assertNotIn(b'"function_call"', stream)
        pin = hashlib.sha256((source / "nginx.conf").read_bytes()).hexdigest()
        self.assertEqual(apparatus["relay_configuration_pin"], "sha256:" + pin)
        self.assertEqual(apparatus["plan"]["relay_config"], "${GEN2_CONFIG_ROOT}/retained-configurations/" + pin)
        self.assertEqual(apparatus["relay_host_source"], apparatus["plan"]["relay_config"])
        self.assertEqual(apparatus["relay_engine_source"], "/etc/gen2/retained-configurations/" + pin)
        self.assertEqual(apparatus["backend_relay_destination"], "/etc/nginx/nginx.conf")
        self.assertEqual(apparatus["offline_relay_destination"], "/etc/gen2/nginx.conf")
