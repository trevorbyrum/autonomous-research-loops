"""V7 §§4–5: pure protocol and file refusals; no daemon, listeners or Q PASS."""
import ast
import contextlib
import io
import json
import os
import re
import subprocess
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from deploy.gen2.live import build, fixture, initialize, qualify, runner, q_net

CONTINUATION = dict(type="custom_tool_call_output", call_id="call_2e1", output=[
    dict(type="input_text", text="Script completed\nWall time 1.0 seconds\nOutput:\n"),
    dict(type="input_text", text=json.dumps(dict(exit_code=0, output="2e1-tool-ok")))])

CAPTURE = Path(__file__).with_name("fixtures") / "cli"
RECEIPTS = {r["step"]: r for r in map(json.loads, (CAPTURE / "receipts.jsonl").read_text().splitlines())}
CONTEXT = json.loads((CAPTURE / "context.json").read_bytes())[0]
LISTING = (CAPTURE / "builders.jsonl").read_text()
VIEW = next(v for v in map(json.loads, LISTING.splitlines()) if v["Name"] == CONTEXT["Name"])
ENTITLEMENT_ERROR = (CAPTURE / "bake-fs-read.stderr").read_bytes()
ENTITLEMENT = re.search(rb'Pass "(--allow=fs.read=[^"]+)"', ENTITLEMENT_ERROR)[1].decode()


class Fixtures(unittest.TestCase):
    def setUp(self):
        """Roots the recorded native capture ran under."""
        data = ENTITLEMENT.removeprefix("--allow=fs.read=").removesuffix("/storage/build-inputs")
        patcher = patch.dict(os.environ, {"GEN2_DATA_ROOT": data, "GEN2_CONFIG_ROOT": "/cfg"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fixture_operands(self):
        self.assertEqual(fixture.operands(["f", "hold", "300"]), ("hold", 300, 1800))
        self.assertEqual(fixture.operands(["f", "hold", "181"])[1], 181)
        self.assertEqual(fixture.operands(["f", "accepted"]), ("accepted", 0, 1800))
        self.assertEqual(fixture.operands(["f", "hold", "30", "600"]), ("hold", 30, 600))
        self.assertEqual(fixture.operands(["f", "hold-first", "30", "600"]), ("hold-first", 30, 600))
        self.assertEqual(fixture.operands(["f", "accepted", "5"]), ("accepted", 0, 5))
        for argv in (["f", "hold", "0"], ["f", "hold", "301"], ["f", "hold", "30", "89"], ["f", "hold", "30", "1801"], ["f", "accepted", "0"],
                     ["f", "hold-first", "0"], ["f", "hold-first", "301"], ["f", "hold-first", "30", "89"], ["f", "hold-first", "30", "1801"]):
            with self.assertRaises(ValueError):
                fixture.operands(argv)

    def exchange(self, case, ordinal, request, now=0, lifetime=600, hold=30):
        """Drive the real handler offline: simulated clock, in-memory sockets; returns (status, ticks, receipts)."""
        clock, ticks, sent = [now], [], []
        body = json.dumps(request).encode()
        headers = {"Authorization": "Bearer 2e1-fixture-accepted", "X-Request-ID": "a" * 32, "Content-Length": str(len(body))}
        server = SimpleNamespace(case=case, count=ordinal - 1, deadline=lifetime, hold_seconds=hold, raw=io.StringIO(), record=io.StringIO(), requests=[])
        handler = object.__new__(fixture.Handler)
        handler.headers = SimpleNamespace(get=headers.get, get_all=lambda k: [headers[k]] if k in headers else None, __iter__=lambda s: iter(headers))
        handler.__dict__.update(server=server, command="POST", path="/v1/responses", connection=None, rfile=io.BytesIO(body), wfile=io.BytesIO())
        with patch.object(fixture, "time", SimpleNamespace(monotonic=lambda: clock[0], sleep=lambda s: (clock.__setitem__(0, clock[0] + s), ticks.append(s)))), \
                patch.multiple(fixture.Handler, send_response=lambda s, c: sent.append(c), send_header=lambda *a: 0, end_headers=lambda s: 0):
            with contextlib.suppress(ValueError):  # a refusal raises after recording; nothing is sent
                handler.exchange()
        return (sent or [0])[0], len(ticks), server.raw.getvalue()

    def test_hold_first_holds_only_its_first_accepted_request(self):
        bare, tooled = dict(model="gpt-6.1-terra", stream=True, input=[]), q_net.model_request("a" * 32)
        status, ticks, raw = self.exchange("hold-first", 1, bare)
        self.assertEqual((status, ticks, json.loads(raw)["case"]), (200, 30, "hold-first"))
        for case, ordinal, request, held in (("hold-first", 2, bare, None), ("hold", 1, tooled, 0), ("hold", 2, tooled | dict(input=tooled["input"] + [CONTINUATION]), 30), ("tool-less", 1, bare, 0)):
            self.assertEqual(self.exchange(case, ordinal, request)[:2], (200, held) if held is not None else (0, 0), (case, ordinal))
        for case, ordinal, request in (("hold-first", 1, bare | dict(model="x")), ("hold", 2, tooled | dict(model="x"))):
            self.assertEqual(self.exchange(case, ordinal, request)[:2], (0, 0), (case, ordinal))
        self.assertEqual(self.exchange("hold-first", 1, bare, now=569)[:2], (200, 30))
        self.assertEqual(self.exchange("hold-first", 1, bare, now=571)[:2], (0, 0))
        self.assertEqual(self.exchange("hold", 1, tooled, now=599)[:2], (200, 0))

    def test_all_compiled_nginx_temp_paths_use_the_existing_tmpfs(self):
        """Retained binary flags and startup refusal pin every temp directory; no daemon."""
        flags = (CAPTURE / "nginx-version.stderr").read_text()
        compiled = {name.replace("-", "_") + "_temp_path": path for name, path in re.findall(r"--http-([a-z-]+)-temp-path=([^\s]+)", flags)}
        self.assertEqual(set(compiled), {"client_body_temp_path", "proxy_temp_path", "fastcgi_temp_path", "uwsgi_temp_path", "scgi_temp_path"})
        failure = (CAPTURE / "nginx-temp.stderr-line").read_text()
        failed = re.search(r'mkdir\(\) "([^"]+)" failed \(30: Read-only file system\)', failure)[1]
        self.assertIn(failed, compiled.values())
        config = Path(__file__).with_name("nginx.conf").read_text()
        declared = dict(re.findall(r"^\s*(\w+_temp_path)\s+([^;\s]+);", config, re.MULTILINE))
        self.assertEqual(set(declared), set(compiled))
        self.assertEqual({Path(path).parent for path in declared.values()}, {Path("/tmp")})

    def test_engine_pins_import_root_without_pythonpath(self):
        """Scrubbed child imports use the namespace package's parent in the pinned image."""
        recipe = Path(__file__).with_name("Dockerfile").read_text()
        engine = recipe.split("FROM base AS engine\n", 1)[1].split("\nFROM base AS gateway\n", 1)[0]
        writes = re.findall(r"^RUN (.+\.pth)$", engine, re.MULTILINE)
        self.assertEqual(writes, ["printf '%s\\n' /opt/gen2 > /usr/local/lib/python3.12/site-packages/gen2.pth"])

    def test_helper_is_pinned_executable_and_beside_codex_in_both_images(self):
        recipe = Path(__file__).with_name("Dockerfile").read_text()
        generic = Path(__file__).parents[1].joinpath("Dockerfile").read_text()
        helper = "e9f2ef68671b2b6ac68902d19e8dafda3f5928e678ecf3f30c74b203a2c403ed"
        self.assertIn("--chmod=0755 codex-code-mode-host /usr/local/bin/codex-code-mode-host", recipe)
        self.assertIn(helper + "  /usr/local/bin/codex-code-mode-host", recipe)
        self.assertIn("COPY --from=runner /usr/local/bin/codex /usr/local/bin/codex-code-mode-host /usr/local/bin/", recipe)
        self.assertIn("COPY --from=approved-inputs npm.tgz", generic)
        self.assertIn(helper, generic)
        self.assertIn("install -m 0755 /tmp/package/vendor/x86_64-unknown-linux-musl/bin/codex-code-mode-host", generic)
        self.assertIn("COPY --from=runner /codex /codex-code-mode-host /usr/local/bin/", generic)

    def test_compose_uses_the_pinned_plugin_and_dedicated_selector(self):
        with patch.object(Path, "read_bytes", return_value=b"retained plugin"), patch.object(build.hashlib, "sha256") as digest:
            digest.return_value.hexdigest.return_value = build.COMPOSE_SHA
            self.assertEqual(build.compose_command("version"), [str(build.COMPOSE), *build.docker_command("version")[1:]])
            digest.return_value.hexdigest.return_value = "changed"
            with self.assertRaisesRegex(ValueError, "Compose plugin pin"):
                build.compose_command("version")

    def test_compose_command_refuses_unset_or_relative_roots(self):
        with patch.object(Path, "read_bytes", return_value=b"plugin"), patch.object(build.hashlib, "sha256") as digest:
            digest.return_value.hexdigest.return_value = build.COMPOSE_SHA
            for name in ("GEN2_CONFIG_ROOT", "GEN2_DATA_ROOT"):
                for value in (None, "./r", "../r"):
                    env = {k: v for k, v in os.environ.items() if k != name} | ({} if value is None else {name: value})
                    with self.subTest(name=name, value=value), patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, name):
                        build.compose_command("config")

    def test_bake_definition_refuses_unset_or_relative_data_root(self):
        """Native HCL validation under the pinned buildx; --print is local, no daemon."""
        buildx = "/usr/libexec/docker/cli-plugins/docker-buildx"
        bake = Path(__file__).with_name("docker-bake.hcl")
        env = {"PATH": "/usr/bin:/bin"}
        self.assertEqual(subprocess.run([buildx, "version"], env=env, capture_output=True, text=True).stdout.strip(), build.BUILDX_VERSION)
        for value in (None, "", "./r", "../r", "r"):
            with self.subTest(value=value):
                run = subprocess.run([buildx, "bake", "--print", "-f", str(bake)], env=env | ({} if value is None else {"GEN2_DATA_ROOT": value}), capture_output=True, text=True, timeout=30)
                self.assertNotEqual(run.returncode, 0)
                self.assertIn("GEN2_DATA_ROOT must be set to an absolute path", run.stderr)
        run = subprocess.run([buildx, "bake", "--print", "-f", str(bake)], env=env | {"GEN2_DATA_ROOT": "/d"}, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        with patch.dict(os.environ, {"GEN2_DATA_ROOT": "/d"}):
            self.assertEqual(json.loads(run.stdout)["target"]["runner"]["contexts"]["approved-inputs"], str(build.build_inputs()))

    def test_compose_refuses_a_shadowing_user_or_extra_directory_plugin(self):
        """Shadow candidates cannot replace the exact executable; mismatched bytes refuse."""
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            shadow = config / "cli-plugins" / "docker-compose"
            shadow.parent.mkdir()
            shadow.write_bytes(b"shadow plugin")
            (config / "config.json").write_text(json.dumps({"cliPluginsExtraDirs": [str(shadow.parent)]}))
            with (
                patch.dict(os.environ, {"DOCKER_CONFIG": directory}),
                patch.object(Path, "read_bytes", return_value=b"retained plugin"),
                patch.object(build.hashlib, "sha256") as digest,
            ):
                digest.return_value.hexdigest.return_value = build.COMPOSE_SHA
                self.assertEqual(build.compose_command("version")[0], "/usr/libexec/docker/cli-plugins/docker-compose")
            with patch.dict(os.environ, {"DOCKER_CONFIG": directory}), patch.object(build, "COMPOSE", shadow):
                with self.assertRaisesRegex(ValueError, "Compose plugin pin"):
                    build.compose_command("version")

    def test_fresh_control_requires_exact_d03_layout(self):
        """A06 admits the two empty D03 directories and refuses partial or unsafe roots."""
        for case in ("valid", "extra", "missing", "content", "mode", "owner", "link", "file"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                journal, state = root / "journal", root / "state"
                journal.mkdir(mode=0o700)
                if case == "link":
                    state.symlink_to(journal)
                elif case == "file":
                    state.touch()
                elif case != "missing":
                    state.mkdir(mode=0o700)
                if case == "extra":
                    (root / "store.sqlite3-wal").touch()
                elif case == "content":
                    (state / "partial").touch()
                elif case == "mode":
                    state.chmod(0o750)
                owner = (os.getuid() + int(case == "owner"), os.getgid())
                guard = nullcontext() if case == "valid" else self.assertRaises((ValueError, OSError))
                with patch.object(initialize, "CONTROL_OWNER", owner), guard:
                    initialize._require_fresh_control(root)

    def test_docker_selection_uses_one_constructor(self):
        """Retained context URI is the oracle; duplicate/bare selectors fail without a CLI."""
        for context, flag, endpoint in ((None, "--host", CONTEXT["Endpoints"]["docker"]["Host"]), (CONTEXT["Name"], "--context", CONTEXT["Name"])):
            self.assertEqual(build.docker_command("info", context=context), [build.CLI, flag, endpoint, "info"])
        for args in (("--host", build.SOCKET), ("--host=" + build.SOCKET,), ("-H" + build.SOCKET,), ("--context", "default")):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "dedicated Docker"):
                build.docker_command(*args)
        with self.assertRaisesRegex(ValueError, "dedicated Docker"):
            build.docker_command("info", context="default")
        for path in Path(build.__file__).parent.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if path.name == "build.py" and isinstance(node, ast.FunctionDef) and node.name == "docker_command":
                    node.body = []
            selectors = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                         and (n.value in ("--host", "--context", "-H") or n.value.startswith(("--host=", "--context=")))]
            self.assertEqual(selectors, [], str(path))

    def test_pinned_buildx_preflight_and_unique_json_view(self):
        """Replay T9 argv/exit, version/context/list captures; malformed cases mutate those bytes."""
        rows = RECEIPTS["class-fix"]["summary"]["rows"]
        name, version = CONTEXT["Name"], (CAPTURE / "version.txt").read_text()
        bake = build.bake_command(name)
        records = [r | {"argv": [*r["argv"][:5], ENTITLEMENT, *r["argv"][5:]]}
                   for r in (rows[0], RECEIPTS["class-noop"]["summary"])]
        self.assertEqual(bake, records[0]["argv"][:-1])
        with patch.object(subprocess, "run", side_effect=[subprocess.CompletedProcess(r["argv"], r["returncode"]) for r in records]) as call:
            build.buildx_preflight(version, bake, {})
            self.assertEqual([c.args[0] for c in call.call_args_list], [r["argv"] for r in records])
            for wrong in ("v0.37.0", version.replace("0dbe87f", "1234567")):
                with self.subTest(version=wrong), self.assertRaisesRegex(ValueError, "version/commit"):
                    build.buildx_preflight(wrong, bake, {})
            with self.assertRaisesRegex(ValueError, "canonical"):
                build.buildx_preflight(version, rows[1]["argv"][:-1], {})
        targets = ("engine", "gateway", "fixture")
        with patch.object(subprocess, "run") as call:
            selected_bake = build.bake_command(name, targets)
            build.buildx_preflight(version, selected_bake, {}, targets)
            self.assertEqual(call.call_args_list[0].args[0], selected_bake + ["--print"])
        selected = build.builder_view(name, LISTING)
        self.assertEqual(selected, VIEW)
        build.builder_gate(name, selected, {name: CONTEXT["Endpoints"]["docker"]["Host"]})
        line, view = json.dumps(VIEW), VIEW
        for listing in ("", "Name: " + name, "[]", "{}", line + "\n" + line, line + "\nnot JSON"):
            with self.subTest(listing=listing), self.assertRaises(ValueError):
                build.builder_view(name, listing)
        for change in (dict(Nodes=None), dict(Nodes=[None]), dict(Nodes=[dict(Endpoint=name, Status="stopped")]), dict(Error="unreadable")):
            with self.subTest(change=change), self.assertRaises(ValueError):
                build.builder_gate(name, view | change, {name: build.SOCKET})

    def test_pinned_read_entitlement(self):
        """I02/D11: native stderr names the sole grant; redirected layout fails before Bake."""
        self.assertEqual(ENTITLEMENT, "--allow=fs.read=" + str(build.build_inputs()))
        with patch.dict(os.environ, {"GEN2_DATA_ROOT": "relative"}), self.assertRaisesRegex(ValueError, "GEN2_DATA_ROOT"):
            build.bake_command(CONTEXT["Name"])
        for targets in (("runner", "engine", "gateway", "fixture"), ("cli-contract",)):
            with self.subTest(targets=targets):
                self.assertEqual([a for a in build.bake_command(CONTEXT["Name"], targets) if a.startswith("--allow=")], [ENTITLEMENT])
        with patch.object(Path, "resolve", return_value=Path("/tmp/other")), self.assertRaisesRegex(ValueError, "staged inputs"):
            build.bake_command(CONTEXT["Name"])

    def test_retained_cli_failures_refuse_before_parsing(self):
        """Actual T9 nonzero process records and stderr must never become successful preflight."""
        for record, name in ((RECEIPTS["dedicated-builder-inspect"], "inspect.stderr"), (RECEIPTS["I02"], "bake.stderr"),
                             (RECEIPTS["r4-I02"], "bake-fs-read.stderr"), (RECEIPTS["post-image-inspect"], "bare-host.stderr-line")):
            error = (CAPTURE / name).read_bytes()
            argv = record.get("argv") or ast.literal_eval(re.search(r"Command '(\[.*\])' returned", error.decode())[1])
            status = record.get("exit_code", record.get("script_result", {}).get("exit_code"))
            failure = subprocess.CalledProcessError(status, argv, stderr=error)
            with patch.object(subprocess, "check_output", side_effect=failure) as call:
                with self.assertRaisesRegex(ValueError, re.escape(error.decode().splitlines()[0])):
                    build.checked(argv)
                call.assert_called_once_with(argv, stderr=subprocess.PIPE)

    def test_dedicated_socket_path_and_context_uri(self):
        """The retained T9 Host URI passes; other sockets and schemes grant no build authority."""
        name, uri = CONTEXT["Name"], CONTEXT["Endpoints"]["docker"]["Host"]
        for endpoint, contexts in ((name, {name: uri}), (uri, {}), (build.SOCKET, {})):
            with self.subTest(endpoint=endpoint):
                build.builder_gate(name, VIEW | {"Nodes": [VIEW["Nodes"][0] | {"Endpoint": endpoint}]}, contexts)
        for wrong in ("/var/run/docker.sock", "unix:///var/run/docker.sock", "tcp://127.0.0.1:2375", "ssh://remote", uri + "?extra"):
            for endpoint, contexts in ((wrong, {}), (name, {name: wrong}), (wrong, {wrong: uri})):
                with self.subTest(endpoint=endpoint, contexts=contexts), self.assertRaisesRegex(ValueError, "not the dedicated daemon"):
                    build.builder_gate(name, VIEW | {"Nodes": [VIEW["Nodes"][0] | {"Endpoint": endpoint}]}, contexts)

    def test_dedicated_builder_and_original_counter(self):
        view, contexts = VIEW, {CONTEXT["Name"]: CONTEXT["Endpoints"]["docker"]["Host"]}
        build.builder_gate(CONTEXT["Name"], view, contexts)
        for driver in ("docker-container", "remote"):
            with self.subTest(driver=driver), self.assertRaises(ValueError):
                build.builder_gate(CONTEXT["Name"], view | {"Driver": driver}, contexts)
        rows = [dict(event=event, nonce="a" * 32, origin={}, count=i, forwarded=0) for i, event in enumerate(("ready", "delivery"))]
        self.assertEqual(qualify.counts("\n".join(map(json.dumps, rows)), "a" * 32, {}), 1)
        with self.assertRaisesRegex(ValueError, "observer_originals"):
            qualify.counts("\n".join(map(json.dumps, rows)), "b" * 32, {})

    def test_workflow_input_names(self):
        with patch.object(runner, "read_file", side_effect=[b"Judge the input", b'{"topic":"fixture"}']) as read:
            self.assertIn('{"topic":"fixture"}', runner.work_prompt(7))
            self.assertEqual([call.args[1] for call in read.call_args_list], ["prompt.md", "input.json"])

    def test_two_sends_and_rejected_branch(self):
        request = q_net.model_request("a" * 32)
        status, _, data = fixture.response("accepted", 1, request)
        event = json.loads(data.decode().split("data: ")[1].split("\n")[0])
        self.assertEqual((status, event["item"]["name"], event["item"]["call_id"]), (200, "exec", "call_2e1"))
        self.assertEqual(event["item"]["type"], "custom_tool_call")
        self.assertIn("tools.exec_command", event["item"]["input"])
        self.assertNotEqual({t.get("name") for t in request.get("tools", [])}, {"exec_command", "write_stdin", "apply_patch"})
        request["input"].append(CONTINUATION)
        self.assertIn(b"2e1 complete", fixture.response("accepted", 2, request)[2])
        self.assertEqual(fixture.response("rejected", 1, request)[0], 401)
        for case, ordinal, change in (("accepted", 3, {}), ("rejected", 2, {}), ("accepted", 1, {"tools": []}),
                                      ("accepted", 2, {"input": []}), ("accepted", 1, {"model": "other"})):
            with self.subTest(case=case, ordinal=ordinal, change=change), self.assertRaises(ValueError):
                fixture.response(case, ordinal, request | change)

    def test_retained_lite_schema_and_continuation_refusals(self):
        request = q_net.model_request("a" * 32)
        native = json.loads((CAPTURE.parent / "catalog/tools.json").read_bytes())
        for old, new in (("exec", "wrong"), ("custom", "function"), ("grammar", "text"),
                         ("apply_patch", "missing_patch"), ("exec_command", "missing_shell"), ("write_stdin", "missing_stdin")):
            changed = json.loads(json.dumps(request).replace(old, new))
            with self.subTest(wrapper_or_operation=old), self.assertRaises(ValueError):
                fixture.response("accepted", 1, changed)
        schema = request["input"][0]
        for inputs in ([native], [schema, schema], [schema | {"tools": schema["tools"] * 2}], [schema | {"role": "user"}], [schema | {"tools": []}], [schema | {"tools": [schema["tools"][0] | {"tools": schema["tools"][0]["tools"][:1]}]}], [None], None):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                fixture.response("accepted", 1, request | dict(input=inputs))
        for output in (CONTINUATION | dict(type="function_call_output"), CONTINUATION | dict(call_id="wrong"), CONTINUATION | dict(output=None),
                       CONTINUATION | dict(output=[dict(type="input_text", text="Script running with cell ID 1\n"), CONTINUATION["output"][1]]),
                       CONTINUATION | dict(output=[CONTINUATION["output"][0], dict(type="input_text", text=json.dumps(dict(exit_code=1, output="2e1-tool-ok")))])):
            with self.subTest(output=output), self.assertRaises(ValueError):
                fixture.response("accepted", 2, request | dict(input=[schema, output]))

    def test_seed_read_refuses_link_and_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "auth.json")
            path.write_bytes(b"dummy")
            path.chmod(0o400)
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                self.assertEqual(runner.read_file(fd, "auth.json", 5), b"dummy")
                with self.assertRaises(ValueError):
                    runner.read_file(fd, "auth.json", 4)
                os.link(path, Path(directory, "link"))
                with self.assertRaises(ValueError):
                    runner.read_file(fd, "auth.json", 5)
            finally:
                os.close(fd)
