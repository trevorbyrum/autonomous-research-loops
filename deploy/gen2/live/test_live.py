"""LR-1 / S7b: pure policy and fixture witnesses over retained public config.

These assert admission operands, not native nginx TLS/rate behavior or actual
Codex requests; the separately receipted pinned-runtime witnesses own those.
"""
import hashlib
import json
import tomllib
import unittest
from pathlib import Path

from deploy.gen2.live import fixture, live, runner

ROOT = Path(__file__).parent


class LivePolicy(unittest.TestCase):
    def test_retained_configuration_mount_is_engine_only_and_read_only(self):
        """S8: protect the child's digest lookup; native UID accessibility is a host witness."""
        document = (ROOT / "compose.live.yaml").read_text()
        self.assertIn("      GEN2_RETAINED_DIR: /etc/gen2/retained-configurations\n", document)
        self.assertIn("      - ${GEN2_CONFIG_ROOT:?configuration root}/retained-configurations:/etc/gen2/retained-configurations:ro\n", document)
        self.assertEqual([line for line in document.splitlines() if line.startswith("  ") and not line.startswith("   ")], ["  engine:"])
        self.assertNotIn("provider-auth.conf", document)
        self.assertNotIn("retained-configurations", (ROOT / "compose.yaml").read_text())

    def test_live_seed_changes_only_the_two_tool_features(self):
        original = (ROOT / "runner-config.toml").read_bytes()
        data = live.runner_config(original)
        expected = tomllib.loads(original.decode())
        expected["features"].update(shell_tool=False, unified_exec=False)
        self.assertEqual(tomllib.loads(data.decode()), expected)
        self.assertIn(hashlib.sha256(data).hexdigest(), runner.PINS["config.toml"])
        with self.assertRaisesRegex(ValueError, "stale public"):
            live.runner_config(original + b"\n")

    def test_live_catalog_changes_only_the_patch_tool(self):
        original = (ROOT / "fixtures/catalog/models.json").read_bytes()
        data = live.model_catalog(original)
        expected = json.loads(original)
        next(row for row in expected["models"] if row["slug"] == "gpt-5.4")["apply_patch_tool_type"] = None
        self.assertEqual(json.loads(data), expected)
        self.assertIn(hashlib.sha256(data).hexdigest(), runner.PINS["models.json"])
        with self.assertRaisesRegex(ValueError, "stale public"):
            live.model_catalog(original + b"\n")

    def test_real_policy_keeps_route_closed_and_overwrites_auth(self):
        base = (ROOT / "nginx.conf").read_bytes()
        view = dict(fixture_relay=base, provider_ip="192.0.2.9", hostname="untrusted.invalid")
        result = live.relay_config(view)
        for required in (b"client_max_body_size 128k;", b"rate=1r/m;", b"limit_req zone=model nodelay;",
                         b"limit_req_status 429;", b"https://192.0.2.9:443/v1/responses;",
                         b"proxy_ssl_name api.openai.com;", b"proxy_ssl_server_name on;", b"proxy_ssl_verify on;",
                         b"proxy_ssl_trusted_certificate /etc/gen2/provider-ca.pem;", b"proxy_ssl_protocols TLSv1.2 TLSv1.3;",
                         b"include /etc/gen2/provider-auth.conf;", b'proxy_set_header Host "api.openai.com";',
                         b'"POST:/v1/responses:HTTP/1.1" model;', b"location / { return 403; }", b"proxy_next_upstream off;"):
            self.assertIn(required, result)
        for forbidden in (b"$http_authorization", b"burst=", b"untrusted.invalid", b"http://172.31.252.3:8081"):
            self.assertNotIn(forbidden, result)
        for change in (dict(fixture_relay=base + b"\n"), dict(provider_ip="::1"), dict(provider_ip="192.0.2.9; evil")):
            with self.subTest(change=change), self.assertRaises(ValueError):
                live.relay_config(view | change)

    def test_dummy_secret_is_separate_and_bad_syntax_never_echoed(self):
        dummy = b"2e1-fixture-accepted"
        self.assertEqual(live.secret_include(dummy), b'proxy_set_header Authorization "Bearer ' + dummy + b'";\n')
        for bad in (dummy + b'";', dummy + b"\n", b"$" + dummy, b"x" * 257, "unread secret"):
            with self.subTest(kind=type(bad).__name__), self.assertRaisesRegex(ValueError, "^invalid relay credential syntax$"):
                live.secret_include(bad)

    def test_tool_less_fixture_completes_once_and_refuses_tools_or_more_sends(self):
        request = dict(model="gpt-5.4", stream=True, tools=[], input=[])
        self.assertEqual(fixture.credential("tool-less"), "accepted")
        status, media, data = fixture.response("tool-less", 1, request)
        events = [json.loads(line[6:]) for line in data.decode().splitlines() if line.startswith("data: ")]
        self.assertEqual((status, media), (200, "text/event-stream"))
        self.assertEqual(events[0]["item"]["type"], "message")
        self.assertEqual(events[1]["response"]["status"], "completed")
        self.assertEqual(fixture.response("tool-less", 1, {k: v for k, v in request.items() if k != "tools"})[0], 200)
        for ordinal, change in ((2, {}), (1, {"tools": None}), (1, {"tools": [{"name": "exec_command"}]}), (1, {"model": "other"})):
            with self.subTest(ordinal=ordinal, change=change), self.assertRaises(ValueError):
                fixture.response("tool-less", ordinal, request | change)

    def test_hold_uses_the_accepted_tool_sequence(self):
        request = dict(model="gpt-5.4", stream=True, tools=[{"name": n} for n in ("exec_command", "write_stdin", "apply_patch")])
        self.assertEqual(fixture.credential("hold"), "accepted")
        self.assertEqual(fixture.response("hold", 1, request), fixture.response("accepted", 1, request))
        request["input"] = [dict(type="function_call_output", call_id="call_2e1", output="2e1-tool-ok")]
        self.assertEqual(fixture.response("hold", 2, request), fixture.response("accepted", 2, request))
        with self.assertRaisesRegex(ValueError, "extra send"):
            fixture.response("hold", 3, request)
