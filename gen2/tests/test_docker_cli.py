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
                                   ("route", "magic", "manifest_route"), ("route", "real", "manifest_roles"), ("platform", "linux/arm64", "manifest_route"),
                                   ("daemon_version", "unbuilt", "manifest_daemon_version"),
                                   ("supervision", "unattended", "manifest_not_supervised"), ("qualification_state", "stale", "manifest_not_qualified"),
                                   ("qualification_ref", "dummy", "manifest_not_qualified"), ("images", {}, "manifest_roles")):
            with self.subTest(key=key):
                bad = {**self.manifest, key: value}
                self.refused(lambda: d.manifest_gate(bad, lambda pin: b"configuration", "reviewed-tree"), reason)
        self.refused(lambda: d.manifest_gate(self.manifest, lambda pin: b"changed", "reviewed-tree"), "manifest_retained")

    def test_a_real_route_manifest_has_the_roles_without_the_fixture(self):
        real = {**self.manifest, "route": "real", "images": {r: v for r, v in self.manifest["images"].items() if r != "fixture"},
                "configurations": {r: v for r, v in self.manifest["configurations"].items() if r != "fixture"}}
        self.assertEqual(d.manifest_gate(real, lambda pin: b"configuration", "reviewed-tree"), real)
        self.refused(lambda: d.manifest_gate({**real, "images": self.manifest["images"]}, lambda pin: b"configuration", "reviewed-tree"), "manifest_roles")

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

    STARTED, FINISHED = "2026-11-08T10:00:00.123456789Z", "2026-11-08T10:00:05.5Z"

    def exited(self, **state):
        return {"Id": CID, "Image": "sha256:" + CID, "Config": {}, "HostConfig": {"PidMode": ""}, "NetworkSettings": {"Networks": {}},
                "State": {"Status": "exited", "Pid": 0, "Error": "", "StartedAt": self.STARTED, "FinishedAt": self.FINISHED, "Running": False,
                          "Restarting": False, "Paused": False, "OOMKilled": False, "ExitCode": 1, **state}}

    def test_the_end_proof_is_the_final_inspect_of_the_same_container_one_operand_at_a_time(self):
        """Gate S #7c: wait, then the SAME post-wait inspect must show exited, no process, no runtime error, finish not before start."""
        original = self.exited()
        self.refused(lambda: self.cli.logs(CID), "logs_before_end")
        self.job.write("runner-start.json", original)
        with mock.patch.object(self.cli, "_command", return_value=b"1\n"), mock.patch.object(self.cli, "inspect", return_value=original):
            self.assertEqual(self.cli.end(CID), original)
            self.assertEqual(self.job.read("runner-end.json"), original)
            for label, change, reason in (
                    ("restarted", {"StartedAt": "2026-11-08T10:00:01Z"}, "end_state"), ("running", {"Running": True}, "end_state"),
                    ("restarting", {"Restarting": True}, "end_state"), ("paused", {"Paused": True}, "end_state"), ("oom", {"OOMKilled": True}, "end_state"),
                    ("running status", {"Status": "running"}, "end_state"), ("status absent", {"Status": None}, "end_state"),
                    ("pid", {"Pid": 7}, "end_state"), ("pid bool", {"Pid": False}, "end_state"), ("pid str", {"Pid": "0"}, "end_state"),
                    ("error", {"Error": "cgroup busy"}, "end_state"), ("error absent", {"Error": None}, "end_state"),
                    ("zero finish", {"FinishedAt": "0001-01-01T00:00:00Z"}, "end_state"), ("bad finish", {"FinishedAt": "yesterday"}, "end_state"),
                    ("early finish", {"FinishedAt": "2026-11-08T09:59:59Z"}, "end_state"), ("no finish", {"FinishedAt": None}, "end_state"),
                    ("exit mismatch", {"ExitCode": 2}, "end_unconfirmed"), ("exit bool", {"ExitCode": True}, "end_unconfirmed")):
                changed = copy.deepcopy(original)
                changed["State"].update(change)
                with self.subTest(label), mock.patch.object(self.cli, "inspect", return_value=changed):
                    self.refused(lambda: self.cli.end(CID), reason)
            replaced = {**original, "Image": "sha256:" + NET}
            with mock.patch.object(self.cli, "inspect", return_value=replaced):
                self.refused(lambda: self.cli.end(CID), "end_binding")
            (self.job.dir / "runner-start.json").unlink()
            self.refused(lambda: self.cli.end(CID), "end_original")
        self.job.write("runner-start.json", original)
        self.job.write("runner-end.json", original)
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

    def test_start_projection_private_pid_namespace_seal_and_capture_recovery_rows(self):
        """L/F1: expected settings, a pinned private PID namespace, the seal, and original start; mocked inspection, no daemon."""
        record = {"Id": CID, "Image": "sha256:" + CID, "Config": {"User": "10001:10001"}, "HostConfig": {"ReadonlyRootfs": True, "PidMode": ""}, "NetworkSettings": {"Networks": {}}, "State": {"StartedAt": self.STARTED}}
        self.job.write("runner.json", record)
        self.cli.plan["expected"] = {"runner": {"Config": {"User": "10001:10001"}, "HostConfig": {"ReadonlyRootfs": True, "PidMode": ""}}}
        with mock.patch.object(d, "free_space"), mock.patch.object(self.cli, "inspect", return_value=record), mock.patch.object(self.cli, "_command") as command:
            self.cli.start(CID)
            command.assert_called_once_with(("start", CID))
            with mock.patch.object(self.cli, "inspect", side_effect=[record, {**record, "Image": "replaced"}]):
                with self.assertRaisesRegex(LiveProfileRefused, "start_changed"):
                    self.cli.start(CID)
            with mock.patch.object(self.cli, "inspect", side_effect=[record, {**record, "State": {"StartedAt": "0001-01-01T00:00:00Z"}}]):
                with self.assertRaisesRegex(LiveProfileRefused, "start_changed"):
                    self.cli.start(CID)
            for label, expected, original in (("missing", None, record), ("shared", "host", record), ("original shared", "", {**record, "HostConfig": {**record["HostConfig"], "PidMode": "host"}})):
                plan = copy.deepcopy(self.cli.plan["expected"])
                if expected is None:
                    del plan["runner"]["HostConfig"]["PidMode"]
                else:
                    plan["runner"]["HostConfig"]["PidMode"] = expected
                self.cli.plan["expected"] = plan
                self.job.write("runner.json", original)
                with self.subTest(label):
                    self.refused(lambda: self.cli.start(CID), "start_configuration|start_pid_mode")
                self.cli.plan["expected"]["runner"]["HostConfig"]["PidMode"] = ""
                self.job.write("runner.json", record)
            command.reset_mock()
            self.cli.close_admission()
            self.refused(lambda: self.cli.start(CID), "start_after_seal")
            command.assert_not_called()
            (self.job.dir / d.SEAL).write_text("not json")                       # an ambiguous seal also stops every start
            self.refused(lambda: self.cli.start(CID), "start_after_seal")
            (self.job.dir / d.SEAL).unlink()
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
                batch, ended, watch = mock.Mock(), mock.Mock(return_value=None if reason == "fixture_writers_live" else (0, GENERATION, (1, 2))), mock.Mock()
                stack.enter_context(mock.patch.object(d.jobs, "members", return_value=[] if reason == "backend_unsupervised" else [os.getpid()]))
                batch.held = {"access": b"", "events": b"", "fixture": b'{"v":1,"requests":[{"model":"gpt-5.4"}]}'}
                batch.collect.return_value = batch.stage.return_value = {"content_hash": "sha256:" + CID}
                actions = {"create_auxiliary": [CID, relay], "start": None, "end": [{"State": {"ExitCode": int(reason == "initializer_failed")}}, {"State": {"ExitCode": 1}}, {"State": {"ExitCode": int(reason == "relay_stop_failed")}}], "network": [NET, upstream], "endpoint": None, "create_runner": CID,
                           "inspect": [fixture, connected, {"NetworkSettings": {"Networks": {}}}], "contain": None, "runtime": None, "close_admission": None,
                           "drain": None if reason != "relay_drain" else LiveProfileRefused("relay_drain"), "logs": (b"events", b"diagnostics"), "_command": json.dumps([{"Id": NET, "Containers": {relay: {}, **({CID: {}} if reason == "ingress_not_closed" else {})}}]).encode()}
                for name, result in actions.items():
                    patched = stack.enter_context(mock.patch.object(self.cli, name, **({"side_effect": result} if isinstance(result, (list, BaseException)) else {"return_value": result})))
                    watch.attach_mock(patched, name)
                if reason == "backend_unsupervised":
                    self.refused(lambda: self.cli.run(ended, batch), reason)
                elif reason:
                    with self.assertRaisesRegex(LiveProfileRefused, reason):
                        self.cli.run(ended, batch)
                    self.assertIsNotNone(self.job.read("docker-attempt.json"))
                    self.assertIsNone(self.job.read("docker-complete.json"))
                    batch.collect.assert_not_called()
                else:
                    refs = self.cli.run(ended, batch)
                    self.assertEqual(len(refs), 6)
                    self.assertEqual(self.job.read("docker-complete.json")["disposition"]["disposition"], "unknown")
                    watch.assert_has_calls([mock.call.start(CID), mock.call.close_admission(), mock.call.end(CID), mock.call.endpoint("disconnect", NET, CID), mock.call._command(("network", "inspect", NET)), mock.call.inspect(CID), mock.call.drain(), mock.call.contain(relay, role="relay"), mock.call.end(relay, "relay"), mock.call.logs(CID)])
                    self.assertEqual(batch.collect.call_count, 3)
                for name in ("docker-attempt.json", "docker-generations.json", "docker-complete.json"):
                    (self.job.dir / name).unlink(missing_ok=True)
                self.job.write("relay.json", record)

    def real_world(self):
        """A real-route cli: manifest without the fixture role, the plan's route, egress bridge ID and upstream, output = judgment."""
        manifest = {**self.manifest, "route": "real", "images": {r: v for r, v in self.manifest["images"].items() if r != "fixture"},
                    "configurations": {r: v for r, v in self.manifest["configurations"].items() if r != "fixture"}}
        cli = d.DockerCLI(self.job, manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: 10)
        slots = {n: str(self.root / n) for n in ("out", "evidence")}
        for path in slots.values():
            (Path(path) / GENERATION).mkdir(parents=True, exist_ok=True)
        egress = "9" * 64
        cli.plan.update(generation=GENERATION, slots=slots, binds={"out": str(Path(slots["out"]) / GENERATION)}, route="real", output="judgment",
                        egress={"network_id": egress}, upstream="203.0.113.7:443")
        self.job.write("identity.json", {"pid": os.getpid()})
        relay = "e" * 64
        record = {"Id": relay, "Image": "sha256:" + CID, "Config": {}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
        self.job.write("relay.json", record)
        return cli, egress, relay, record

    def real_run(self, cli, egress, relay, record, *, collect=None, end_error=None):
        connected = {**record, "NetworkSettings": {"Networks": {NET: {"NetworkID": NET, "IPAMConfig": {"IPv4Address": "172.31.254.2"}},
                                                               egress: {"NetworkID": egress, "IPAMConfig": None}}}}
        batch = mock.Mock()
        batch.held = {"access": b"", "events": b"", "judgment": b'{"judgment_version": "x"}'}
        batch.collect.side_effect = collect or (lambda *a, **k: {"content_hash": "sha256:" + CID})
        batch.stage.return_value = {"content_hash": "sha256:" + CID}
        ends = [{"State": {"ExitCode": 0}}, {"State": {"ExitCode": 0}}, {"State": {"ExitCode": 0}}]
        egress_view = json.dumps([{"Id": egress, "Internal": False, "Containers": {}}]).encode()
        ingress = json.dumps([{"Id": NET, "Containers": {relay: {}}}]).encode()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(d.jobs, "members", return_value=[os.getpid()]))
            actions = {"create_auxiliary": [CID, relay], "start": None, "end": end_error or [ends[0], {"State": {"ExitCode": 1}}, ends[2]], "network": [NET], "endpoint": None,
                       "create_runner": CID, "inspect": [connected, {"NetworkSettings": {"Networks": {}}}], "contain": None, "logs": (b"events", b"diagnostics"),
                       "runtime": None, "close_admission": None, "drain": None, "_command": [egress_view, ingress]}
            watch = mock.Mock()
            for name, result in actions.items():
                patched = stack.enter_context(mock.patch.object(cli, name, **({"side_effect": result} if isinstance(result, list) or isinstance(result, BaseException) else {"return_value": result})))
                watch.attach_mock(patched, name)
            contained = stack.enter_context(mock.patch.object(d, "contain_job"))
            try:
                refs = cli.run(lambda: self.fail("a real route has no fixture"), batch)
            except BaseException as error:
                return error, batch, watch, contained
            return refs, batch, watch, contained

    def test_a_real_route_run_has_no_fixture_joins_the_egress_bridge_by_id_and_collects_the_judgment(self):
        cli, egress, relay, record = self.real_world()
        refs, batch, watch, contained = self.real_run(cli, egress, relay, record)
        self.assertEqual(len(refs), 5)                                              # events, diagnostics, judgment, access, usage: no fixture file
        self.assertEqual([c.kwargs["kind"] for c in batch.collect.call_args_list], ["judgment", "access"])
        self.assertIn(mock.call.endpoint("connect", egress, relay, None), watch.mock_calls)   # joined by the plan's ID, no fixed address
        self.assertNotIn("fixture", " ".join(str(c) for c in watch.mock_calls))
        done = self.job.read("docker-complete.json")
        self.assertEqual(done["disposition"]["disposition"], "unknown")             # this fake leaves no log row; classification used route=real
        contained.assert_not_called()

    def test_a_real_route_with_a_missing_judgment_is_still_classified_but_any_other_collection_refusal_is_not_swallowed(self):
        cli, egress, relay, record = self.real_world()
        def absent(slot_fd, generation, identity, *, writers_ended, kind):
            if kind == "judgment":
                raise LiveProfileRefused("collection_absent")
            return {"content_hash": "sha256:" + CID}
        refs, *_ = self.real_run(cli, egress, relay, record, collect=absent)
        self.assertEqual(len(refs), 4)                                              # no judgment ref, and the run still completed
        (self.job.dir / "docker-attempt.json").unlink()
        (self.job.dir / "docker-complete.json").unlink()
        def empty(slot_fd, generation, identity, *, writers_ended, kind):
            raise LiveProfileRefused("collection_empty")
        error, *_ = self.real_run(*self.real_world(), collect=empty)
        self.assertIsInstance(error, LiveProfileRefused)

    def test_a_real_route_needs_an_empty_egress_bridge_a_manifest_and_plan_that_agree_and_contains_a_partial_start(self):
        cli, egress, relay, record = self.real_world()
        cli.plan["route"] = "fixture"
        error, *_ = self.real_run(cli, egress, relay, record)
        self.assertRegex(str(error), "plan_route")
        (self.job.dir / "docker-attempt.json").unlink(missing_ok=True)
        cli, egress, relay, record = self.real_world()
        error, batch, watch, contained = self.real_run(cli, egress, relay, record, end_error=[{"State": {"ExitCode": 0}}, LiveProfileRefused("end_unconfirmed")])
        self.assertRegex(str(error), "end_unconfirmed")
        contained.assert_called_once()                                              # whatever was started is ended before the failure leaves

    def test_runtime_identity_and_the_bounded_drain(self):
        """Gate S #7c: the proof is bound to the installed runtime; a changed field, or a drain that overran or was cut short, refuses."""
        info = {**d.RUNTIME, **{k: {"ID": v} for k, v in d.RUNTIME_IDS.items()}, "Runtimes": {"runc": {}}}
        with mock.patch.object(self.cli, "_command", return_value=json.dumps(info).encode()) as command:
            self.cli.runtime()
            command.assert_called_once_with(("info", "--format", "{{json .}}"))
            for key, value in (("ServerVersion", "29.9.1"), ("CgroupVersion", "1"), ("CgroupDriver", "cgroupfs"), ("LiveRestoreEnabled", True),
                               ("LiveRestoreEnabled", None), ("ContainerdCommit", {"ID": "0" * 40}), ("RuncCommit", {}), ("RuncCommit", None)):
                with self.subTest(key=key, value=value):
                    command.return_value = json.dumps({**info, key: value}).encode()
                    with self.assertRaisesRegex(LiveProfileRefused, "runtime_identity"):
                        self.cli.runtime()
            command.return_value = b"[]"
            with self.assertRaisesRegex(LiveProfileRefused, "runtime_identity"):
                self.cli.runtime()
        clock, slept = [0.0], []
        cli = d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: clock[0], sleep=lambda n: (slept.append(n), clock.__setitem__(0, clock[0] + n + 3)))
        with self.assertRaisesRegex(LiveProfileRefused, "relay_drain"):            # 8 s of grace plus scheduling overhead past the ten-second budget
            cli.drain()
        self.assertEqual(slept, [d.DRAIN_SECONDS])
        cli.sleep = lambda n: clock.__setitem__(0, clock[0] + n + 1)
        cli.drain()
        cli.sleep = mock.Mock(side_effect=KeyboardInterrupt)                         # an interrupted grace is not completion
        with self.assertRaises(KeyboardInterrupt):
            cli.drain()

    def contain_world(self, execute, roles=(("runner", "a" * 64), ("relay", "b" * 64), ("initializer", "c" * 64))):
        for role, cid in roles:
            (self.job.dir / (role + ".cid")).write_text(cid)
        pin = mock.patch.object(d.hashlib, "sha256")
        digest = pin.start()
        self.addCleanup(pin.stop)
        digest.return_value.hexdigest.return_value = d.CLI_SHA
        return mock.patch.object(d.Path, "read_bytes", self.real_read_bytes)

    def test_contain_job_kills_then_removes_every_journaled_container_and_tolerates_the_gone(self):
        calls = []
        def execute(job, argv, env, deadline, bounds):
            calls.append(argv[3:])
            return (0, b"", b"") if argv[3] != "rm" or argv[-1] != "b" * 64 else (1, b"", b"Error: No such container: " + argv[-1].encode())
        with self.contain_world(execute):
            outcomes = d.contain_job(self.job, execute=execute, now=lambda: 0)
        self.assertEqual(calls, [("kill", "a" * 64), ("rm", "-f", "a" * 64), ("kill", "b" * 64), ("rm", "-f", "b" * 64), ("kill", "c" * 64), ("rm", "-f", "c" * 64)])
        self.assertEqual([(o["role"], o["kill"], o["rm"]) for o in outcomes], [("runner", "ok", "ok"), ("relay", "ok", "gone"), ("initializer", "ok", "ok")])
        self.assertEqual(self.job.read("containment.json")["outcomes"], outcomes)                 # each outcome is journaled
        self.assertEqual(d.contain_job(jobs.Job(self.root, "job-empty"), execute=execute, now=lambda: 0), [])   # nothing journaled, nothing run

    def test_a_failed_kill_of_the_runner_does_not_stop_the_relay_or_the_initializer_and_the_end_is_unconfirmed(self):
        calls = []
        def execute(job, argv, env, deadline, bounds):
            calls.append(argv[3:])
            return (1, b"", b"permission denied") if argv[3:] == ("kill", "a" * 64) else (0, b"", b"")
        with self.contain_world(execute), self.assertRaises(d.ContainFailed) as caught:
            d.contain_job(self.job, execute=execute, now=lambda: 0)
        self.assertEqual(len(calls), 6)                                                          # every CID, kill and removal, attempted
        self.assertEqual([(o["role"], o["kill"], o["rm"]) for o in caught.exception.outcomes],
                         [("runner", "failed", "ok"), ("relay", "ok", "ok"), ("initializer", "ok", "ok")])
        self.assertEqual(self.job.read("containment.json")["outcomes"], caught.exception.outcomes)

    def test_an_error_in_one_command_or_an_unreadable_journal_entry_still_attempts_the_rest(self):
        def execute(job, argv, env, deadline, bounds):
            if argv[3] == "kill" and argv[-1] == "a" * 64:
                raise OSError("socket gone")
            return (0, b"", b"")
        with self.contain_world(execute, roles=(("runner", "a" * 64), ("relay", "not-a-cid"), ("initializer", "c" * 64))), self.assertRaises(d.ContainFailed) as caught:
            d.contain_job(self.job, execute=execute, now=lambda: 0)
        self.assertEqual([(o["role"], o["kill"], o["rm"]) for o in caught.exception.outcomes],
                         [("runner", "error", "ok"), ("relay", "journal_unreadable", "journal_unreadable"), ("initializer", "ok", "ok")])

    def test_a_wrong_cli_pin_stops_containment_it_is_not_relaxed_around(self):
        calls = []
        (self.job.dir / "runner.cid").write_text("a" * 64)
        with mock.patch.object(d.Path, "read_bytes", return_value=b"not the pinned cli"), self.assertRaisesRegex(LiveProfileRefused, "cli_pin"):
            d.contain_job(self.job, execute=lambda *a: calls.append(a) or (0, b"", b""), now=lambda: 0)
        self.assertEqual(calls, [])

    def test_a_rejection_is_retained_even_when_the_optional_usage_record_cannot_be_built(self):
        cli, egress, relay, record = self.real_world()
        with mock.patch.object(d.rejection, "usage_record", side_effect=LiveProfileRefused("usage_model_mismatch")):
            refs, *_ = self.real_run(cli, egress, relay, record)
        done = self.job.read("docker-complete.json")
        self.assertEqual((done["usage"], len(done["refs"]), len(refs)), ("refused", 4, 4))     # the classified disposition and every raw reference are still there

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
