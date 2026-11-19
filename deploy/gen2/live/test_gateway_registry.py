import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest import mock
from pathlib import Path

from deploy.gen2.live import build, gateway_registry as g

ROOT = Path(__file__).parent
PUBLIC, Q = g.read_inputs()
SEED = g.derive(PUBLIC, Q, g.ENABLED)
ROWS = tomllib.loads(SEED.decode())["source"]


class Registry(unittest.TestCase):
    def test_exact_enabled_set_with_q_2e1_explicitly_false(self):
        rows = {r["id"]: r for r in tomllib.loads(g.check(PUBLIC, Q, SEED, g.ENABLED).decode())["source"]}
        self.assertEqual({i: r["enabled"] for i, r in rows.items() if r["enabled"] or i == "q_2e1"}, {"semanticscholar": True, "q_2e1": False})

    def test_metadata_rate_and_policy_survive(self):
        rows = {r["id"]: r for r in tomllib.loads(SEED.decode())["source"]}
        s2 = rows["semanticscholar"]
        self.assertEqual((s2["rate"]["per_second"], s2["domains"], s2["use_commercial"]), (1, ["ai-ml", "software"], "deny"))
        self.assertEqual(rows["q_2e1"]["rate"], {"per_second": 2, "burst": 2, "per_day": 64, "cost_cap_per_day": 1, "verified": True, "evidence": "2e1 finite Q fixture; no external service"})

    def test_check_refuses_flag_and_byte_drift(self):
        for bad in (SEED.replace(b'enabled = false\n', b'enabled = true\n', 1), SEED.replace(b"Mixed: CC BY-NC", b"Mixed: CC BY", 1), SEED + Q, SEED.replace(b'enabled = true\n', b'enabled = "true"\n')):
            with self.assertRaises(ValueError):
                g.check(PUBLIC, Q, bad, g.ENABLED)

    def test_offline_seed_matches_initializer(self):
        disabled = PUBLIC.replace(b"enabled = true\n", b"enabled = false\n")
        self.assertEqual(hashlib.sha256(disabled).hexdigest(), "b95efce7dea15e644f62f8b7a23770380f40a1274ca7dc9fb02e5164da84b81c")
        seed = g.derive(PUBLIC, Q, g.OFFLINE)
        self.assertEqual(g.check(PUBLIC, Q, seed, g.OFFLINE), disabled + Q)

    def test_exact_readbacks_reject_drift(self):
        flags = [{k: row[k] for k in ("id", "enabled")} for row in ROWS]
        g.same(reversed(ROWS), ROWS)
        g.same(reversed(flags), ROWS, flags_only=True)
        s2 = next(row for row in ROWS if row["id"] == "semanticscholar")
        core = next(row for row in ROWS if row["id"] == "core")
        rest = [row for row in ROWS if row is not s2 and row is not core]
        tighter = [dict(row, rate=dict(row["rate"], per_second=1)) if row["id"] == "q_2e1" else row for row in ROWS]
        cases = (
            ("tighter rate", tighter, "q_2e1"),
            ("integer type", [*rest, core, dict(s2, rate=dict(s2["rate"], per_second=1.0))], "semanticscholar"),
            ("fractional rate", [*rest, s2, dict(core, rate=dict(core["rate"], per_second=0.75))], "core"),
            ("extra enabled", [*ROWS, {"id": "untrusted", "enabled": True}], "<unexpected id>"),
            ("extra disabled", [*ROWS, {"id": "untrusted", "enabled": False}], "<unexpected id>"),
            ("missing", [*rest, core], "semanticscholar"),
            ("duplicate", [*ROWS, s2], "semanticscholar"),
            ("nonboolean", [*rest, core, dict(s2, enabled=1)], "semanticscholar"),
        )
        for case, view, source in cases:
            with self.subTest(case=case), self.assertRaisesRegex(ValueError, f"^registry differs at {source}$"):
                g.same(view, ROWS)
        with self.assertRaisesRegex(ValueError, "^registry differs at semanticscholar$"):
            g.same([dict(row, enabled=False) for row in flags], ROWS, flags_only=True)

    def test_each_changed_pin_and_missing_input_refused(self):
        for path in g.PINS:
            with self.subTest(path=path.name), mock.patch.dict(g.PINS, {path: "0" * 64}), self.assertRaises(ValueError):
                g.read_inputs()
        with tempfile.TemporaryDirectory() as temp:
            public, q = g.PINS
            with mock.patch.object(g, "PINS", {public: g.PINS[public], Path(temp) / q.name: g.PINS[q]}), self.assertRaises(FileNotFoundError):
                g.read_inputs()

    def test_module_publication_and_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "seed"
            argv = [sys.executable, "-m", g.__name__, str(path)]
            subprocess.run(argv, cwd=g.ROOT, env={}, check=True, capture_output=True, timeout=10)
            self.assertEqual(path.read_bytes(), SEED)
            self.assertNotEqual(subprocess.run(argv, cwd=g.ROOT, env={}, capture_output=True, timeout=10).returncode, 0)
            self.assertEqual(path.read_bytes(), SEED)

    def test_refused_validation_and_failed_write_leave_no_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "seed"
            with mock.patch.object(g, "check", side_effect=ValueError), self.assertRaises(ValueError):
                g.publish(path)
            self.assertFalse(path.exists())
            def interrupted_write(staged, data):
                with staged.open("wb") as stream:
                    stream.write(data[:16])
                raise OSError("interrupted write")

            with mock.patch.object(Path, "write_bytes", interrupted_write), self.assertRaises(OSError):
                g.publish(path)
            self.assertEqual(list(Path(temp).iterdir()), [])


def render(*files):
    env = dict(GEN2_CONFIG_ROOT="/config", GEN2_DATA_ROOT="/data", GEN2_GENERATION="0" * 32, GEN2_HOST_ID="render",
               GEN2_EGRESS_ADDRESS="192.0.2.2", GEN2_EGRESS_SUBNET="192.0.2.0/29", GEN2_EGRESS_DNS="198.51.100.53",
               GEN2_REGISTRY_SEED="/config/seed.toml")
    env.update({f"GEN2_{role}_ID": "a" * 64 for role in ("ENGINE", "GATEWAY", "FIXTURE")})
    env.update({f"GEN2_{role}_EVIDENCE": "/data/" + role.lower() for role in ("RELAY", "FIXTURE", "SOURCE")})
    with mock.patch.dict(os.environ, env, clear=True):
        argv = build.compose_command("--env-file", os.devnull, "--profile", "offline", "-f", str(ROOT / "compose.yaml"),
                                     *(arg for name in files for arg in ("-f", str(ROOT / name))),
                                     "config", "--no-env-resolution", "--format", "json")
    return json.loads(subprocess.check_output(argv, env=env, stderr=subprocess.PIPE, timeout=10))


class Overlay(unittest.TestCase):
    def test_pinned_merged_render_and_frozen_offline_profile(self):
        base, merged = render(), render("compose.gateway.yaml")
        services = base["services"]
        self.assertEqual({k: v["profiles"] for k, v in services.items() if "profiles" in v},
                         {k: ["offline"] for k in ("fixture", "source-fixture", "relay")})
        self.assertEqual({k: set(v["networks"]) for k, v in services.items()},
                         {"engine": {"service"}, "gateway-db": {"db"}, "fixture": {"fixture-upstream"},
                          "source-fixture": {"research-egress-offline"}, "relay": {"job", "fixture-upstream"},
                          "gateway": {"service", "db", "research-egress-offline"}})
        self.assertTrue(all(net["internal"] for net in base["networks"].values()))
        self.assertEqual(merged["networks"].pop("egress", None),
                         {"name": "gen2-2e1-live-egress-" + "0" * 32, "driver": "bridge", "enable_ipv6": False,
                          "ipam": {"config": [{"subnet": "192.0.2.0/29"}]}})
        gateway = merged["services"]["gateway"]
        self.assertEqual(gateway.pop("dns", None), ["198.51.100.53"])
        self.assertEqual(gateway.pop("sysctls", None), {"net.ipv4.ip_forward": "0", "net.ipv6.conf.all.forwarding": "0"})
        self.assertEqual(gateway.pop("volumes", None), [{"type": "bind", "source": "/config/seed.toml", "read_only": True,
                         "target": "/opt/gateway/research_gateway/registry/seed/sources.toml", "bind": {}}])
        self.assertEqual(gateway["networks"].pop("egress", None), {"ipv4_address": "192.0.2.2"})
        self.assertEqual(gateway.get("ports"), [{"mode": "ingress", "host_ip": "127.0.0.1", "target": 8765, "published": "8771", "protocol": "tcp"}])
        del gateway["entrypoint"]
        self.assertIsNone(services["gateway"].pop("entrypoint"))
        self.assertEqual(merged, base)

    def test_entrypoint_failure_is_safe_and_success_execs(self):
        entrypoint = render("compose.gateway.yaml")["services"]["gateway"]["entrypoint"]
        # A trailing command prevents Bash from optimizing a plain tail call into exec.
        entrypoint[-1] += "; exit 97"
        with tempfile.TemporaryDirectory() as temp:
            stub = Path(temp) / "python3"
            stub.write_text("""#!/bin/bash
case "$*" in
    '-m research_gateway.registry.load --load --seed-operational')
        echo untrusted-input; echo untrusted-input >&2; exit "$LOAD_STATUS" ;;
    '-m research_gateway.api.http') echo "$$" ;;
    *) exit 99 ;;
esac
""")
            stub.chmod(0o700)
            for status in (37, 0):
                with self.subTest(status=status), subprocess.Popen(
                    entrypoint, env={"PATH": temp, "LOAD_STATUS": str(status)},
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ) as shell:
                    out, err = shell.communicate(timeout=5)
                    self.assertEqual((shell.returncode, out, err),
                                     (37, "", "gateway registry load failed\n") if status else (0, f"{shell.pid}\n", ""))
