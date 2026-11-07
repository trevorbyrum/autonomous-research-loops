"""CLI-boundary tests only: no daemon, image, container, or qualified profile."""
import copy
import contextlib
import hashlib
import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen2.supervisor import docker_cli as d, jobs
from gen2.supervisor.isolation import LiveProfileRefused
from gen2.supervisor.spool import Spool, SpoolConflict

CID, NET, GENERATION = "a" * 64, "b" * 64, "c" * 32


class DockerBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.real_read_bytes = Path.read_bytes
        self.job = jobs.Job(self.root, "job-fixture")
        self.job.prepare({"test": "unqualified offline fixture"})
        self.job.write("docker-plan.json", {"origin": {"invocation": "fixture"}, "paths": [str(self.root)]})
        self.pin = "sha256:" + hashlib.sha256(b"configuration").hexdigest()
        self.manifest = {"version": 1, "tree": "reviewed-tree", "platform": "linux/amd64", "route": "fixture",
                         "socket": d.SOCKET, "cli_sha256": d.CLI_SHA, "daemon_version": "29.0.0",
                         "credential_ref": "dummy-seed", "credential_version": "v1",
                         "supervision": "supervised", "qualification_state": "qualified", "qualification_ref": self.pin,
                         "images": {r: {"pin": "sha256:" + CID, "kind": "engine-image-id"} for r in d.ROLES},
                         "configurations": {r: {"pin": self.pin} for r in d.ROLES}}
        self.execute = mock.Mock(return_value=(0, b"", b""))
        self.cli = d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: 10)

    def files(self):
        return {str(p.relative_to(self.root)): (tuple(getattr(p.lstat(), k) for k in
                ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")),
                os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None)
                for p in [self.root, *self.root.rglob("*")]}

    def refused(self, action, reason):
        before, memory = self.files(), copy.deepcopy(self.cli.plan)
        self.execute.reset_mock()
        with self.assertRaisesRegex(LiveProfileRefused, reason):
            action()
        self.execute.assert_not_called()
        self.assertEqual(self.files(), before)
        self.assertEqual(self.cli.plan, memory)

    def test_manifest_admitted_operands_and_refusals(self):
        self.assertEqual(d.manifest_gate(self.manifest, lambda pin: b"configuration", "reviewed-tree"), self.manifest)
        for key, value, reason in (("version", 2, "manifest_tree"), ("socket", "/var/run/docker.sock", "manifest_runtime"),
                                   ("route", "real", "manifest_route"), ("platform", "linux/arm64", "manifest_route"),
                                   ("daemon_version", "unbuilt", "manifest_daemon_version"),
                                   ("supervision", "unattended", "manifest_not_supervised"), ("qualification_state", "stale", "manifest_not_qualified"),
                                   ("qualification_ref", "dummy", "manifest_not_qualified"), ("images", {}, "manifest_roles")):
            with self.subTest(key=key):
                bad = {**self.manifest, key: value}
                self.refused(lambda: d.manifest_gate(bad, lambda pin: b"configuration", "reviewed-tree"), reason)
        self.refused(lambda: d.manifest_gate(self.manifest, lambda pin: b"changed", "reviewed-tree"), "manifest_retained")

    def test_exact_argv_environment_and_deadline(self):
        with mock.patch.object(d.Path, "read_bytes", return_value=b"wrong-cli"):
            self.refused(lambda: self.cli.inspect(CID), "cli_pin")
        with mock.patch.object(d.hashlib, "sha256") as digest:
            digest.return_value.hexdigest.return_value = d.CLI_SHA
            self.execute.return_value = (0, json.dumps([{"Id": CID}]).encode(), b"")
            self.assertEqual(self.cli.inspect(CID), {"Id": CID})
        self.execute.assert_called_once_with(self.job, ("/usr/bin/docker", "--host",
            "unix:///run/user/1000/gen2-2e1/docker.sock", "inspect", CID),
            {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "DOCKER_CONFIG": str(self.job.dir / "docker-config")}, 15, (65536, 4096))
        self.refused(lambda: self.cli.inspect("runner-name"), "container_identity")
        self.refused(lambda: self.cli.network("../generation"), "network_generation")
        self.refused(lambda: self.cli._command(("pull", "runner:latest")), "cli_command")

    def test_ambiguous_mutation_never_retried(self):
        self.job.write("runner.json", {"Id": CID})
        with mock.patch.object(d.hashlib, "sha256") as digest:
            digest.return_value.hexdigest.return_value = d.CLI_SHA
            self.execute.side_effect = OSError("missing dedicated daemon")
            with self.assertRaisesRegex(OSError, "missing dedicated daemon"):
                self.cli.contain(CID)
            self.assertEqual(self.execute.call_count, 1)
            self.assertIn("intent", next(iter(self.job.read("docker.json").values())))
            self.refused(lambda: self.cli.contain(CID), "mutation_already_intended")

    def test_wait_inspect_and_descendants_must_agree(self):
        original = {"Id": CID, "Image": "sha256:" + CID, "Config": {}, "HostConfig": {}, "NetworkSettings": {"Networks": {}},
                    "State": {"StartedAt": "original-start", "Running": False, "Restarting": False,
                              "Paused": False, "OOMKilled": False, "ExitCode": 1}}
        self.refused(lambda: self.cli.logs(CID), "logs_before_end")
        self.job.write("runner-start.json", original)
        with mock.patch.object(self.cli, "_command", return_value=b"1\n"), mock.patch.object(self.cli, "inspect", return_value=original):
            self.refused(lambda: self.cli.end(CID, lambda view: False), "end_unconfirmed")
            changed = copy.deepcopy(original)
            changed["State"]["StartedAt"] = "replacement-start"
            with mock.patch.object(self.cli, "inspect", return_value=changed):
                self.refused(lambda: self.cli.end(CID, lambda view: True), "end_state")
            self.assertEqual(self.cli.end(CID, lambda view: True), original)
            for field, reason in (("OOMKilled", "end_state"), ("Running", "end_state"), ("Restarting", "end_state"), ("Paused", "end_state")):
                changed = copy.deepcopy(original)
                changed["State"][field] = True
                with self.subTest(field=field), mock.patch.object(self.cli, "inspect", return_value=changed):
                    self.refused(lambda: self.cli.end(CID, lambda view: True), reason)
        self.refused(lambda: self.cli.remove(CID, False), "remove_before_ack")
        with mock.patch.object(self.cli, "_command", return_value=(b"events", b"diagnostics")) as command:
            self.assertEqual(self.cli.logs(CID), (b"events", b"diagnostics"))
            command.assert_called_once_with(("logs", CID))
        self.refused(lambda: self.cli.logs(CID), "logs_already_intended")

    def test_floor_equal_and_below(self):
        with mock.patch.object(d.os, "statvfs") as stats:
            stats.return_value = mock.Mock(f_bavail=16, f_frsize=1 << 30)
            d.free_space([self.root], 16 << 30)
            stats.return_value.f_bavail = 15
            self.refused(lambda: d.free_space([self.root], 16 << 30), "free_space_floor")
            stats.side_effect = OSError("stat unavailable")
            with self.assertRaisesRegex(OSError, "stat unavailable"):
                d.free_space([self.root], 16 << 30)

    def test_original_generation_and_immutable_publication(self):
        generation = self.root / GENERATION
        generation.mkdir()
        (generation / "outcome.json").write_bytes(b'{"result":"retained"}')
        info = generation.stat()
        identity = (info.st_dev, info.st_ino)
        spool = Spool(self.root / "spool", quota_bytes=64 << 20)
        batch = d.EvidenceBatch(spool, "fleet:fixture")
        slot_fd = d.slot(str(self.root))
        self.addCleanup(os.close, slot_fd)
        with mock.patch.object(d, "free_space"):
            self.refused(lambda: batch.collect(slot_fd, GENERATION, identity, writers_ended=False), "collection_writers_live")
            self.refused(lambda: batch.collect(slot_fd, GENERATION, (0, 0), writers_ended=True), "collection_identity")
            ref = batch.collect(slot_fd, GENERATION, identity, writers_ended=True)
            self.assertEqual(spool.read(ref["content_hash"], topic_id="fleet:fixture"), b'{"result":"retained"}')
            target = spool.root / "fleet:fixture" / ref["content_hash"].split(":")[1]
            target.chmod(0o600)
            target.write_bytes(b"corrupted")
            with self.assertRaisesRegex(SpoolConflict, "failed verification"):
                batch.collect(slot_fd, GENERATION, identity, writers_ended=True)
            target.unlink()
            target.symlink_to(generation / "outcome.json")
            with self.assertRaisesRegex(SpoolConflict, "differs from retained bytes"):
                batch.collect(slot_fd, GENERATION, identity, writers_ended=True)

    def test_collection_refuses_links_empty_missing_and_batch_overflow(self):
        generation = self.root / GENERATION
        generation.mkdir()
        result = generation / "outcome.json"
        info = generation.stat()
        spool = Spool(self.root / "spool", quota_bytes=64 << 20)
        batch = d.EvidenceBatch(spool, "fleet:fixture")
        slot_fd = d.slot(str(self.root))
        self.addCleanup(os.close, slot_fd)
        collect = lambda: batch.collect(slot_fd, GENERATION, (info.st_dev, info.st_ino), writers_ended=True)
        self.refused(collect, "collection_absent")
        result.touch()
        self.refused(collect, "collection_empty")
        result.unlink()
        result.symlink_to("missing")
        self.refused(collect, "collection_refused")
        result.unlink()
        result.write_bytes(b"x")
        os.link(result, generation / "extra-link")
        self.refused(collect, "collection_refused")
        with mock.patch.object(d, "free_space"):
            batch.used = d.BATCH - 1
            self.assertIsNotNone(batch.stage(b"x", "text/plain"))
            self.refused(lambda: batch.stage(b"x", "text/plain"), "collection_batch_cap")

    def test_capture_bounds_deadline_and_confirmed_child_end(self):
        argv = (sys.executable, "-c", "import sys; sys.stdout.write('out'); sys.stderr.write('err')")
        with mock.patch.object(d.subprocess, "Popen", wraps=d.subprocess.Popen) as process:
            self.assertEqual(d.capture(self.job, argv, {}, time.monotonic() + 5, (3, 3)), (0, b"out", b"err"))
            process.assert_called_once_with(argv, env={}, stdin=d.subprocess.DEVNULL, stdout=d.subprocess.PIPE,
                                           stderr=d.subprocess.PIPE, start_new_session=True, close_fds=True)
        for bounds in ((2, 3), (3, 2)):
            with self.subTest(bounds=bounds), mock.patch.object(self.job, "terminate", wraps=self.job.terminate) as end:
                with self.assertRaisesRegex(LiveProfileRefused, "cli_overflow"):
                    d.capture(self.job, argv, {}, time.monotonic() + 5, bounds)
                end.assert_called_once()
                self.assertIsNotNone(self.job.read("docker-cli.json"))
        with mock.patch.object(d.subprocess, "Popen") as process:
            self.refused(lambda: d.capture(self.job, argv, {}, time.monotonic() - 1, (3, 3)), "cli_deadline")
            process.assert_not_called()
        with self.assertRaisesRegex(LiveProfileRefused, "cli_deadline"):
            d.capture(self.job, (sys.executable, "-c", "import time; time.sleep(30)"), {}, time.monotonic() + 0.2, (3, 3))
        with mock.patch.object(self.job, "terminate", return_value={"confirmed": False}):
            with self.assertRaisesRegex(LiveProfileRefused, "cli_end_unconfirmed"):
                d.capture(self.job, argv, {}, time.monotonic() + 5, (3, 3))
        self.assertIsNone(self.job.read("runner-end.json"))

    def test_network_exact_create_and_topology_refusals(self):
        view = {"Id": NET, "Internal": True, "EnableIPv6": False, "Driver": "bridge",
                "IPAM": {"Config": [{"Subnet": "172.31.254.0/29"}]}, "Containers": {}}
        with mock.patch.object(d.Path, "read_bytes", autospec=True, side_effect=lambda path: b"pinned-cli" if str(path) == d.CLI else self.real_read_bytes(path)), mock.patch.object(d, "CLI_SHA", hashlib.sha256(b"pinned-cli").hexdigest()):
            cases = [{}, {"Id": CID}, {"Internal": False}, {"Containers": {CID: {}}}, {"Driver": "host"}]
            for index, change in enumerate(cases):
                generation = f"{index:032x}"
                self.execute.reset_mock()
                self.execute.side_effect = [(0, NET.encode(), b""), (0, json.dumps([{**view, **change}]).encode(), b"")]
                before = self.job.read("network-job.json")
                if change:
                    with self.assertRaisesRegex(LiveProfileRefused, "network_(inspect|members)"):
                        self.cli.network(generation)
                    self.assertEqual(self.job.read("network-job.json"), before)
                else:
                    self.assertEqual(self.cli.network(generation), NET)
                self.assertEqual(self.execute.call_count, 2)
                self.assertEqual(self.execute.call_args_list[0].args[1], (d.CLI, "--host", "unix://" + d.SOCKET,
                    "network", "create", "--internal", "--driver", "bridge", "--subnet", "172.31.254.0/29",
                    "--opt", "com.docker.network.bridge.gateway_mode_ipv4=isolated", "gen2-2e1-live-job-" + generation))
                self.assertIn("intent", next(iter(self.job.read("docker.json").values())))

    def runner_binds(self):
        binds = {name: "/fixture/" + name for name in ("out", "inputs", "seed")}
        self.cli.plan["binds"] = binds
        self.job.write("docker-plan.json", self.cli.plan)
        self.job.write("network-job.json", {"Id": NET})
        return binds

    def test_create_exact_argv_identity_and_preflight_refusal(self):
        binds = self.runner_binds()
        record = {"Id": CID, "Image": "sha256:" + CID, "Config": {"Image": "sha256:" + CID}}
        replies = iter([(0, CID.encode(), b""), (0, json.dumps([record]).encode(), b"")])
        def execute(*args):
            self.assertIn("intent", next(iter(self.job.read("docker.json").values())))
            (self.job.dir / "runner.cid").write_text(CID)
            return next(replies)
        self.execute.side_effect = execute
        with mock.patch.object(d.Path, "read_bytes", autospec=True, side_effect=lambda path: b"pinned-cli" if str(path) == d.CLI else self.real_read_bytes(path)), mock.patch.object(d, "CLI_SHA", hashlib.sha256(b"pinned-cli").hexdigest()):
            self.assertEqual(self.cli.create_runner(NET, binds), CID)
        expected = (d.CLI, "--host", "unix://" + d.SOCKET, "create", "--cidfile", str(self.job.dir / "runner.cid"),
            "--pull=never", "--restart=no", "--read-only", "--user", "10001:10001", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "64", "--memory", "1g", "--memory-swap", "1g",
            "--cpus", "1", "--ulimit", "fsize=16777216:16777216", "--ulimit", "nofile=256:256", "--ulimit", "core=0:0",
            "--dns", "127.0.0.1", "--ipc=private", "--cgroupns=private", "--no-healthcheck", "--log-driver", "local",
            "--log-opt", "max-size=4m", "--log-opt", "max-file=1", "--network", NET, "--ip", "172.31.254.3",
            "--tmpfs", "/work:rw,nodev,nosuid,size=128m,mode=0700,uid=10001,gid=10001",
            "--tmpfs", "/auth/codex:rw,nodev,nosuid,size=16m,mode=0700,uid=10001,gid=10001",
            "--tmpfs", "/tmp:rw,nodev,nosuid,size=64m,mode=1777,uid=10001,gid=10001",
            "--tmpfs", "/run:rw,nodev,nosuid,size=4m,mode=0700,uid=10001,gid=10001",
            "--mount", "type=bind,src=/fixture/out,dst=/out", "--mount", "type=bind,src=/fixture/inputs,dst=/inputs,readonly",
            "--mount", "type=bind,src=/fixture/seed,dst=/seed,readonly", "sha256:" + CID)
        self.assertEqual(self.execute.call_args_list[0].args[1], expected)
        self.assertEqual(self.execute.call_args_list[1].args[1], (d.CLI, "--host", "unix://" + d.SOCKET, "inspect", CID))
        self.refused(lambda: self.cli.create_runner(NET, {**binds, "out": "/different"}), "runner_originals")

    def test_missing_create_identity_retains_intent_and_blocks_retry(self):
        binds = self.runner_binds()
        self.execute.return_value = (0, CID.encode(), b"")
        with mock.patch.object(d.Path, "read_bytes", autospec=True, side_effect=lambda path: b"pinned-cli" if str(path) == d.CLI else self.real_read_bytes(path)), mock.patch.object(d, "CLI_SHA", hashlib.sha256(b"pinned-cli").hexdigest()):
            with self.assertRaisesRegex(LiveProfileRefused, "create_identity"):
                self.cli.create_runner(NET, binds)
            self.assertEqual(self.execute.call_count, 1)
            self.assertIsNone(self.job.read("runner.json"))
            self.assertIn("intent", next(iter(self.job.read("docker.json").values())))
            self.refused(lambda: self.cli.create_runner(NET, binds), "mutation_already_intended")

    def test_auxiliary_argv_and_preflight_rows(self):
        """I/L: exact create argv and retained originals; fake CLI only."""
        self.cli.plan.update(generation=GENERATION, slots={"out": "/slots/out", "evidence": "/slots/evidence"}, relay_config="/reviewed/nginx.conf")
        self.job.write("network-job.json", {"Id": NET})
        for role in ("engine", "relay"):
            self.manifest["images"][role]["kind"] = "repo-digest"
        common = ("--pull=never", "--restart=no", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                  "--pids-limit", "32", "--memory", "128m", "--memory-swap", "128m", "--cpus", ".25", "--no-healthcheck",
                  "--ipc=private", "--cgroupns=private", "--log-driver", "local", "--log-opt", "max-size=4m", "--log-opt", "max-file=1",
                  "--tmpfs", "/tmp:rw,nodev,nosuid,size=16m,mode=0700,uid=10001,gid=10001", "--network")
        for role, network, suffix in (
            ("initializer", None, ("none", "--mount", "type=bind,src=/slots/out,dst=/out", "--mount", "type=bind,src=/slots/evidence,dst=/evidence",
                "--user", "0:0", "--cap-add", "CHOWN", "sha256:" + CID, "/usr/local/bin/python", "-m", "gen2.supervisor.docker_cli", GENERATION)),
            ("relay", NET, (NET, "--mount", f"type=bind,src=/slots/evidence/{GENERATION},dst=/evidence", "--mount",
                "type=bind,src=/reviewed/nginx.conf,dst=/etc/nginx/nginx.conf,readonly", "--user", "10001:10001", "--sysctl", "net.ipv4.ip_forward=0",
                "--ip", "172.31.254.2", "sha256:" + CID))):
            record = {"Id": CID, "Image": "sha256:" + "d" * 64, "Config": {"Image": "sha256:" + CID}}
            def execute(*args):
                (self.job.dir / (role + ".cid")).write_text(CID)
                return (0, CID.encode() if args[1][3] == "create" else json.dumps([record]).encode(), b"")
            self.execute.side_effect = execute
            self.execute.reset_mock()
            with mock.patch.object(d.Path, "read_bytes", autospec=True, side_effect=lambda p: b"pinned" if str(p) == d.CLI else self.real_read_bytes(p)), mock.patch.object(d, "CLI_SHA", hashlib.sha256(b"pinned").hexdigest()):
                self.assertEqual(self.cli.create_auxiliary(role, network), CID)
            self.assertEqual(self.execute.call_args_list[0].args[1], (d.CLI, "--host", "unix://" + d.SOCKET, "create", "--cidfile", str(self.job.dir / (role + ".cid")), *common, *suffix))
        for role, network, reason in (("gateway", NET, "auxiliary_role"), ("relay", CID, "relay_network")):
            self.refused(lambda: self.cli.create_auxiliary(role, network), reason)

    def test_start_projection_and_capture_recovery_rows(self):
        """L/F1: expected settings and original start; mocked inspection, no daemon."""
        record = {"Id": CID, "Image": "sha256:" + CID, "Config": {"User": "10001:10001"}, "HostConfig": {"ReadonlyRootfs": True}, "NetworkSettings": {"Networks": {}}, "State": {"StartedAt": "original"}}
        self.job.write("runner.json", record)
        self.cli.plan["expected"] = {"runner": {"Config": {"User": "10001:10001"}, "HostConfig": {"ReadonlyRootfs": True}}}
        with mock.patch.object(d, "free_space"), mock.patch.object(self.cli, "inspect", return_value=record), mock.patch.object(self.cli, "_command") as command:
            self.cli.start(CID)
            command.assert_called_once_with(("start", CID))
            with mock.patch.object(self.cli, "inspect", side_effect=[record, {**record, "Image": "replaced"}]):
                with self.assertRaisesRegex(LiveProfileRefused, "start_changed"):
                    self.cli.start(CID)
            self.cli.plan["expected"]["runner"]["Config"]["User"] = "0:0"
            self.refused(lambda: self.cli.start(CID), "start_configuration")
        self.job.write("docker-cli.json", {"intent": "crashed-before-identity"})
        with mock.patch.object(d.subprocess, "Popen") as process:
            self.refused(lambda: d.capture(self.job, ("unused",), {}, time.monotonic() + 5, (1, 1)), "cli_previous_unconfirmed")
            process.assert_not_called()

    def test_relay_sequence_and_refusal_rows(self):
        """I/L/E: ordered end/closure/collection, no complete marker on uncertainty; sequencing mocks only."""
        upstream, relay, fixture_id = "d" * 64, "e" * 64, "f" * 64
        record = {"Id": relay, "Image": "sha256:" + CID, "Config": {}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
        connected = {**record, "NetworkSettings": {"Networks": {n: {"NetworkID": n, "IPAMConfig": {"IPv4Address": ip}} for n, ip in ((NET, "172.31.254.2"), (upstream, "172.31.252.2"))}}}
        fixture = {**record, "Id": fixture_id}
        slots = {n: str(self.root / n) for n in ("out", "evidence")}
        for path in slots.values():
            (Path(path) / GENERATION).mkdir(parents=True)
        self.cli.plan.update(generation=GENERATION, slots=slots, binds={"out": str(Path(slots["out"]) / GENERATION)}, fixture=fixture)
        self.job.write("identity.json", {"pid": os.getpid()})
        self.job.write("relay.json", record)
        for reason in (None, "backend_unsupervised", "initializer_failed", "ingress_not_closed", "relay_drain", "relay_stop_failed", "fixture_writers_live"):
            with self.subTest(reason=reason), contextlib.ExitStack() as stack:
                batch, close, drain, ended, watch = mock.Mock(), mock.Mock(), mock.Mock(return_value=reason != "relay_drain"), mock.Mock(return_value=None if reason == "fixture_writers_live" else (0, GENERATION, (1, 2))), mock.Mock()
                stack.enter_context(mock.patch.object(d.jobs, "members", return_value=[] if reason == "backend_unsupervised" else [os.getpid()]))
                batch.held = {"access": b"", "events": b"", "fixture": b'{"v":1,"requests":[{"model":"gpt-5.4"}]}'}
                batch.collect.return_value = batch.stage.return_value = {"content_hash": "sha256:" + CID}
                actions = {"create_auxiliary": [CID, relay], "start": None, "end": [{"State": {"ExitCode": int(reason == "initializer_failed")}}, {"State": {"ExitCode": 1}}, {"State": {"ExitCode": int(reason == "relay_stop_failed")}}], "network": [NET, upstream], "endpoint": None, "create_runner": CID,
                           "inspect": [fixture, connected, {"NetworkSettings": {"Networks": {}}}], "contain": None, "logs": (b"events", b"diagnostics"), "_command": json.dumps([{"Id": NET, "Containers": {relay: {}, **({CID: {}} if reason == "ingress_not_closed" else {})}}]).encode()}
                for name, result in actions.items():
                    patched = stack.enter_context(mock.patch.object(self.cli, name, **({"side_effect": result} if isinstance(result, list) else {"return_value": result})))
                    watch.attach_mock(patched, name)
                if reason == "backend_unsupervised":
                    self.refused(lambda: self.cli.run(close, lambda _: True, ended, drain, batch), reason)
                elif reason:
                    with self.assertRaisesRegex(LiveProfileRefused, reason):
                        self.cli.run(close, lambda _: True, ended, drain, batch)
                    self.assertIsNotNone(self.job.read("docker-attempt.json"))
                    self.assertIsNone(self.job.read("docker-complete.json"))
                    batch.collect.assert_not_called()
                else:
                    refs = self.cli.run(close, lambda _: True, ended, drain, batch)
                    self.assertEqual(len(refs), 6)
                    self.assertEqual(self.job.read("docker-complete.json")["disposition"]["disposition"], "unknown")
                    watch.assert_has_calls([mock.call.start(CID), mock.call.end(CID, mock.ANY), mock.call.endpoint("disconnect", NET, CID), mock.call._command(("network", "inspect", NET)), mock.call.inspect(CID), mock.call.contain(relay, role="relay"), mock.call.end(relay, mock.ANY, "relay"), mock.call.logs(CID)])
                    close.assert_called_once_with()
                    self.assertEqual(batch.collect.call_count, 3)
                for name in ("docker-attempt.json", "docker-generations.json", "docker-complete.json"):
                    (self.job.dir / name).unlink(missing_ok=True)
                self.job.write("relay.json", record)

    def test_supervisor_holds_uncertain_backend_rows(self):
        """L: no capacity release before backend end; direct control-call boundary only."""
        from gen2.supervisor.supervisor import Supervisor, Waiting
        control = mock.Mock()
        supervisor = Supervisor(control, None, self.root, station_id="fixture", host_id="fixture", clock=lambda: "2026-11-04T00:00:00Z")
        for method, request in (("record_transition", {"to_state": "failed"}), ("reconcile", {"resolution": "confirmed_failed"}), ("commit_outcome", {})):
            before = self.files()
            with self.assertRaisesRegex(Waiting, "backend_end_unconfirmed"):
                supervisor._call(self.job, {}, method, request)
            self.assertEqual(self.files(), before)
            self.assertEqual(control.mock_calls, [])
        self.job.write("docker-complete.json", {"origin": self.cli.plan["origin"]})
        supervisor._call(self.job, {"budgets": {}}, "record_transition", {"to_state": "failed"})
        control.record_transition.assert_called_once_with({"to_state": "failed"})

    def test_launch_hook_refuses_before_spawn_or_state_change(self):
        """I/L: closed productive hook; zero spawn and full local state equality."""
        from gen2.supervisor.supervisor import Supervisor
        supervisor = Supervisor(mock.Mock(), None, self.root, station_id="fixture", host_id="fixture", clock=lambda: "2026-11-04T00:00:00Z")
        with mock.patch.object(self.job, "lookup", return_value={"verdict": "not_started"}), mock.patch.object(self.job, "spawn") as spawn:
            self.refused(lambda: supervisor._launching(self.job, {}, {}, {}, {}), "profile_absent")
            spawn.assert_not_called()

    def test_initializer_exclusive_file_mode(self):
        """I: fresh directories and access0600; ownership syscalls are mocked."""
        for name in ("out", "evidence"):
            (self.root / name).mkdir()
        with mock.patch.object(d, "Path", side_effect=lambda root: self.root / root.lstrip("/")), mock.patch.object(d.os, "chown"), mock.patch.object(d.os, "fchown"):
            d.initialize(GENERATION)
            self.assertEqual((self.root / "evidence" / GENERATION / "access.jsonl").stat().st_mode & 0o777, 0o600)
