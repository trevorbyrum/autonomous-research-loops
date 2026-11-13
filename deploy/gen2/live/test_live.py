"""LR-1 / S7b: pure policy and fixture witnesses over retained public config.

These assert admission operands, not native nginx TLS/rate behavior or actual
Codex requests; the separately receipted pinned-runtime witnesses own those.
"""
import base64
import hashlib
import io
import json
import tomllib
import unittest
import traceback
from contextlib import redirect_stdout, redirect_stderr
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
                         b"limit_req_status 429;", b"https://192.0.2.9:443/backend-api/codex/responses;",
                         b"proxy_ssl_name chatgpt.com;", b"proxy_ssl_server_name on;", b"proxy_ssl_verify on;",
                         b"proxy_ssl_trusted_certificate /etc/gen2/provider-ca.pem;", b"proxy_ssl_protocols TLSv1.2 TLSv1.3;",
                         b"include /etc/gen2/provider-auth.conf;", b'proxy_set_header Host "chatgpt.com";',
                         b'"POST:/v1/responses:HTTP/1.1" model;', b"location / { return 403; }", b"proxy_next_upstream off;",
                         b"proxy_pass_request_headers off;", b'proxy_set_header originator "codex_cli_rs";', b'proxy_set_header version "0.153.2";'):
            self.assertIn(required, result)
        for forbidden in (b"$http_", b"ChatGPT-Account-ID", b"User-Agent", b"Cookie", b"Proxy-Authorization", b"burst=", b"untrusted.invalid", b"http://172.31.252.3:8081"):
            self.assertNotIn(forbidden, result)
        for change in (dict(fixture_relay=base + b"\n"), dict(provider_ip="::1"), dict(provider_ip="192.0.2.9; evil")):
            with self.subTest(change=change), self.assertRaises(ValueError):
                live.relay_config(view | change)

    def test_jwt_include_and_all_refusals_have_secret_free_diagnostics(self):
        def token(payload):
            return b"e30." + base64.urlsafe_b64encode(payload).rstrip(b"=") + b".c2ln"
        dummy, account = token(b'{"exp":8200}'), b"fixture-session"
        args = dict(access_token=dummy, account_id=account, now=1000, min_remaining_seconds=7200)
        self.assertEqual(live.secret_include(**args), b'proxy_set_header Authorization "Bearer ' + dummy + b'";\nproxy_set_header ChatGPT-Account-ID "fixture-session";\n')
        self.assertIn(token(b'{"exp":8200}'.ljust(6137)), live.secret_include(**(args | dict(access_token=token(b'{"exp":8200}'.ljust(6137))))))
        bad_tokens = [b"bad", dummy + b"\n", dummy + b'";', b"a.e30.c2ln", b"e30.e31.c2ln", token(b'{"exp":8200}'.ljust(6138)), "unread secret"]
        bad_tokens += [token(p) for p in (b"[]", b"{}", b"not-json", b'{"exp":8199}', b'{"exp":true}', b'{"exp":NaN}', b'{"exp":1e999}', b'{"exp":"8200"}', b'{"exp":253402300800}', b"[" * 2000)]
        changes = [dict(access_token=t) for t in bad_tokens]
        changes += [dict(account_id=a) for a in (b"", b"x" * 129, b"$x", b'a";', b"a\n", b"a b", "session")]
        changes += [{k: n} for k in ("now", "min_remaining_seconds") for n in (-1, True, 1.5, float("inf"), 253402300800, None)] + [dict(min_remaining_seconds=0)]
        for change in changes:
            with self.subTest(field=next(iter(change))), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                with self.assertRaises(ValueError) as caught:
                    live.secret_include(**(args | change))
                self.assertEqual(str(caught.exception), "invalid relay credential")
                self.assertEqual(out.getvalue() + err.getvalue(), "")
                diagnostic = "".join(traceback.format_exception(caught.exception))
                self.assertNotIn(dummy.decode(), diagnostic)
                value = change[next(iter(change))]
                if value:
                    self.assertNotIn(value.decode(errors="replace") if isinstance(value, bytes) else str(value), diagnostic)

    def test_tool_less_fixture_completes_once_and_refuses_tools_or_more_sends(self):
        request = dict(model="gpt-5.4", stream=True, tools=[], input=[])
        self.assertEqual(fixture.credential("tool-less"), "accepted")
        self.assertEqual(fixture.response("limited", 1, request)[0], 429)
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
