import tomllib
import unittest
import unittest.mock
from pathlib import Path

import yaml

from deploy.gen2.live import gateway_registry as g

ROOT = Path(__file__).parent
PUBLIC, Q = g.read_inputs()
SEED = g.derive(PUBLIC, Q)
overlay = lambda: yaml.safe_load((ROOT / "compose.gateway.yaml").read_text())


class Registry(unittest.TestCase):
    def test_exact_enabled_set_with_q_2e1_explicitly_false(self):
        rows = {r["id"]: r for r in tomllib.loads(g.check(PUBLIC, Q, SEED).decode())["source"]}
        self.assertEqual({i: r["enabled"] for i, r in rows.items() if r["enabled"] or i == "q_2e1"}, {"semanticscholar": True, "q_2e1": False})

    def test_metadata_rate_and_policy_survive(self):
        rows = {r["id"]: r for r in tomllib.loads(SEED.decode())["source"]}
        s2 = rows["semanticscholar"]
        self.assertEqual((s2["rate"]["per_second"], s2["domains"], s2["use_commercial"]), (1, ["ai-ml", "software"], "deny"))
        self.assertEqual(rows["q_2e1"]["rate"], {"per_second": 2, "burst": 2, "per_day": 64, "cost_cap_per_day": 1, "verified": True, "evidence": "2e1 finite Q fixture; no external service"})

    def test_check_refuses_flag_and_byte_drift(self):
        for bad in (SEED.replace(b'enabled = false\n', b'enabled = true\n', 1), SEED.replace(b"Mixed: CC BY-NC", b"Mixed: CC BY", 1), SEED + Q, SEED.replace(b'enabled = true\n', b'enabled = "true"\n')):
            with self.assertRaises(ValueError):
                g.check(PUBLIC, Q, bad)

    def test_changed_input_pin_is_refused(self):
        with unittest.mock.patch.dict(g.PINS, {next(iter(g.PINS)): "0" * 64}), self.assertRaisesRegex(ValueError, "pin changed"):
            g.read_inputs()


class Overlay(unittest.TestCase):
    def test_only_gateway_gets_the_one_external_bridge_and_dns(self):
        doc = overlay()
        self.assertEqual(list(doc["services"]), ["gateway"])
        self.assertEqual(list(doc["networks"]), ["egress"])
        net = doc["networks"]["egress"]
        self.assertEqual((net["internal"], net["enable_ipv6"]), (False, False))
        self.assertEqual((list(doc["services"]["gateway"]["networks"]), doc["services"]["gateway"]["sysctls"]["net.ipv4.ip_forward"]), (["egress"], "0"))

    def test_loader_runs_before_http_and_seed_mounts_read_only(self):
        gateway = overlay()["services"]["gateway"]
        self.assertIn("registry.load --load --seed-operational && exec python3 -m research_gateway.api.http", gateway["entrypoint"][-1])
        self.assertTrue(gateway["volumes"][0].endswith(":/opt/gateway/research_gateway/registry/seed/sources.toml:ro"))

    def test_frozen_base_and_engine_contract_unchanged(self):
        base, live = (ROOT / "compose.yaml").read_text(), (ROOT / "compose.live.yaml").read_text()
        self.assertNotIn("registry", base + live)
        self.assertEqual((base.count("internal: true"), base.count("egress:")), (1, 0))
