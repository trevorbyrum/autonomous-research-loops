"""CLI-boundary tests only: no daemon, image, container, or qualified profile."""
import copy
import contextlib
import hashlib
import json
import os
import subprocess
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen2.supervisor import docker_cli as d, jobs
from gen2.tests import children
from gen2.tests.test_rejection import ROW, jl
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
        self.job.prepare({"test": "unqualified offline fixture", "deadline_at": "1970-01-01T00:20:10Z"})   # 210 s after the injected clock: the allowance ends at now() + 120
        self.job.write("docker-plan.json", {"origin": {"invocation": "fixture", "invocation_id": "inv_fixture0001"}, "paths": [str(self.root)]})
        self.job.write("docker.json", {})   # what the fresh-attempt transition in `run` creates; methods driven directly start from an attempt in progress
        self.pin = "sha256:" + hashlib.sha256(b"configuration").hexdigest()
        self.manifest = {"version": 1, "tree": "reviewed-tree", "platform": "linux/amd64", "route": "fixture",
                         "socket": d.SOCKET, "cli_sha256": d.CLI_SHA, "daemon_version": "29.0.0",
                         "credential_ref": "dummy-seed", "credential_version": "v1",
                         "supervision": "supervised", "qualification_state": "qualified", "qualification_ref": self.pin,
                         "images": {r: {"pin": "sha256:" + CID, "kind": "engine-image-id"} for r in d.ROLES},
                         "configurations": {r: {"pin": self.pin} for r in d.ROLES}}
        self.execute = mock.Mock(return_value=(0, b"", b""))
        self.cli = d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: 10, clock=lambda: 1000.0)

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

    def test_a_linked_or_non_directory_generation_is_a_collection_refusal_that_stages_nothing_in_every_mode(self):
        """DCK-14: the descriptor-relative open's own OS errors are the documented refusal; other infrastructure errors still escape."""
        (self.root / "elsewhere").mkdir()
        (self.root / "elsewhere" / "outcome.json").write_bytes(b"x")
        (self.root / GENERATION).symlink_to(self.root / "elsewhere", target_is_directory=True)
        (self.root / ("5" * 32)).write_bytes(b"not a directory")
        slot_fd = d.slot(str(self.root))
        self.addCleanup(os.close, slot_fd)
        for kind in ("outcome", "judgment"):
            for name in (GENERATION, "5" * 32):
                with self.subTest(kind=kind, generation=name):
                    batch = d.EvidenceBatch(Spool(self.root / "spool", quota_bytes=64 << 20), "fleet:fixture")
                    with mock.patch.object(d, "free_space"):
                        self.refused(lambda: batch.collect(slot_fd, name, (0, 0), writers_ended=True, kind=kind), "collection_generation")
                    self.assertEqual((batch.used, batch.held), (0, {}))
        with mock.patch.object(d.os, "open", side_effect=PermissionError(13, "denied")), self.assertRaises(PermissionError):
            d.EvidenceBatch(Spool(self.root / "spool", quota_bytes=64 << 20), "fleet:fixture").collect(slot_fd, "6" * 32, (0, 0), writers_ended=True)

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

    def test_capture_recovers_only_a_complete_stale_identity_and_never_overwrites_an_ambiguous_record(self):
        stale = {"pid": 4242, "session": 4242, "starttime": 7, "boot_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12}   # a valid identity from an older boot
        for name, record, ended in (("intent only", {"intent": ["/usr/bin/docker", "wait"]}, True), ("malformed", {"pid": "4242", "boot_id": "boot"}, True),
                                    *((name, {**stale, **change}, True) for name, change in (("empty boot id", {"boot_id": ""}), ("boot id not a boot id", {"boot_id": "boot"}), ("negative pid", {"pid": -1}),
                                      ("negative session", {"session": -1}), ("zero starttime", {"starttime": 0}), ("session is not the pid", {"session": 1}),
                                      ("bool field", {"pid": True}), ("truthy confirmation", {"confirmed": "yes"}), ("falsy confirmation", {"confirmed": False}))),
                                    ("not terminable", stale, False)):
            with self.subTest(name), mock.patch.object(d.subprocess, "Popen") as process, \
                    mock.patch.object(self.job, "terminate", return_value={"confirmed": ended}) as end:
                self.job.write("docker-cli.json", record)
                self.refused(lambda: d.capture(self.job, ("unused",), {}, time.monotonic() + 5, (1, 1)), "cli_previous_unconfirmed")
                process.assert_not_called()
                self.assertEqual(self.job.read("docker-cli.json"), record)   # the unresolved record is kept, never overwritten
                self.assertEqual(end.call_count, name == "not terminable")
        (self.job.dir / "docker-cli.json").write_text("{")   # unreadable
        with mock.patch.object(d.subprocess, "Popen") as process:
            self.refused(lambda: d.capture(self.job, ("unused",), {}, time.monotonic() + 5, (1, 1)), "cli_previous_unconfirmed")
            process.assert_not_called()
        self.job.write("docker-cli.json", stale)   # a complete identity that the existing session mechanism ends: the command proceeds, within its own deadline
        with mock.patch.object(self.job, "terminate", return_value={"confirmed": True}) as end:
            self.assertEqual(d.capture(self.job, (sys.executable, "-c", "print()"), {}, time.monotonic() + 5, (3, 3))[0], 0)
        first = end.call_args_list[0]   # the later calls are the new command's own end
        self.assertEqual((first.args, first.kwargs["term_grace"]), ((stale,), 0))
        self.assertLessEqual(first.kwargs["kill_grace"], 5)

    def test_capture_leaves_a_live_original_and_its_record_alone_when_the_identity_is_malformed(self):
        sleeper = children.popen(["-c", "import time; time.sleep(60)"], start_new_session=True)   # a disposable original, in its own session
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        real = {"pid": sleeper.pid, "session": sleeper.pid, "starttime": jobs.proc_stat(sleeper.pid)[2], "boot_id": jobs.boot_id()}
        for name, record in (("empty boot id", {**real, "boot_id": ""}), ("all fields -1", {"pid": -1, "session": -1, "starttime": -1, "boot_id": ""}),
                             ("negative fields, valid boot", {**real, "pid": -1, "session": -1, "starttime": -1}), ("confirmation is not True", {**real, "confirmed": 1}),
                             ("intent only", {"intent": [sys.executable]})):
            with self.subTest(name), mock.patch.object(d.subprocess, "Popen") as launch:
                self.job.write("docker-cli.json", record)
                self.refused(lambda: d.capture(self.job, (sys.executable, "-c", "pass"), {}, time.monotonic() + 5, (1, 1)), "cli_previous_unconfirmed")
                launch.assert_not_called()                                                   # no replacement launch
                self.assertEqual(self.job.read("docker-cli.json"), record)                    # no overwrite
                self.assertIsNone(sleeper.poll())                                            # the original was neither ended nor promoted
                self.assertIsNone(self.job.read("docker-complete.json"))
        self.job.write("docker-cli.json", real)                                              # control: the same process under a valid identity IS ended by the recovery
        d.capture(self.job, (sys.executable, "-c", "pass"), {}, time.monotonic() + 5, (1, 1))
        self.assertIsNotNone(sleeper.wait(timeout=5))

    def test_the_backend_allowance_is_the_pinned_orders_deadline_minus_the_reserve(self):
        def build(remaining, ticks=None):
            self.job.write("order.json", {"deadline_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1000 + remaining))})
            return d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: 10, clock=lambda: 1000.0)
        cli = build(300)   # the first-topic bundle's model purposes: deadline_s 300
        self.assertEqual((cli.absolute, cli.deadline), (310, 220))
        self.assertGreater(cli.deadline - 10, 120)   # the old 120 s allowance is gone
        self.assertEqual(build(100).deadline, 20)   # a late construction shrinks the allowance instead of overrunning
        for remaining in (90, 0, -5):
            with self.assertRaisesRegex(LiveProfileRefused, "backend_deadline_passed"):
                build(remaining)
        for order in ({}, {"deadline_at": "tomorrow"}, {"deadline_at": 5}):
            self.job.write("order.json", order)
            with self.assertRaisesRegex(LiveProfileRefused, "backend_deadline_missing"):
                d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: 10, clock=lambda: 1000.0)

    def test_only_the_runners_wait_runs_to_the_allowance_and_its_final_inspect_runs_under_the_order_deadline(self):
        clock, seen = [10.0], []
        self.job.write("order.json", {"deadline_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1300))})
        cli = d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", now=lambda: clock[0], clock=lambda: 1000.0,
                          execute=lambda job, argv, env, deadline, bounds: (seen.append((argv[3], deadline)), clock.__setitem__(0, 225.0) if argv[3] == "wait" and len(seen) == 1 else None, (0, b"143", b""))[2])
        started = {"Id": CID, "Image": "i", "Config": {}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}, "State": {"StartedAt": "2026-11-13T01:00:00Z"}}
        ended = {**started, "State": {"StartedAt": "2026-11-13T01:00:00Z", "FinishedAt": "2026-11-13T01:00:01Z", "ExitCode": 143, "Status": "exited", "Pid": 0, "Error": "",
                                      **{k: False for k in ("Running", "Restarting", "Paused", "OOMKilled")}}}
        self.job.write("runner-start.json", started)
        with mock.patch.object(cli, "inspect", side_effect=lambda cid: (seen.append(("inspect", cli.deadline)), ended)[1]):
            cli.end(CID)   # the turn's wait returns at 225 s: after the cutoff (220), before the order's deadline (310)
        self.assertEqual(seen[0], ("wait", 220))   # the model turn waits to the allowance: 300 s order, 90 s reserve, no 120 s cap
        self.assertEqual(seen[1], ("inspect", 310))   # the final inspect after a wait that ends at the cutoff still runs, under the order's deadline
        seen.clear()
        self.assertEqual(cli.deadline, cli.absolute)
        cli._command(("wait", "f" * 64))
        self.assertEqual(seen, [("wait", 225.0 + 10)])   # every other wait is short and finite

    def test_every_provider_backed_purpose_of_the_protected_bundle_gets_its_allowance_from_its_pinned_order_across_restart_and_reuse(self):
        from gen2.core.instants import utc_instant_ns
        from gen2.tests import first_topic_files
        orders = first_topic_files.generate("2026-11-13T00:00:00Z")["subscription-proposal"]["orders"]
        self.assertEqual(sorted(o["env"]["GEN2_PURPOSE"] for o in orders), ["checkpoint/challenge", "checkpoint/review", "research_pass/research", "research_pass/scope", "verification/verify"])
        def build(job, clock, now=10):
            return d.DockerCLI(job, self.manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: now, clock=lambda: clock)
        for number, order in enumerate(orders):
            with self.subTest(order["env"]["GEN2_PURPOSE"]):
                deadline = utc_instant_ns(order["deadline_at"]) / 1e9
                job = jobs.Job(self.root, f"job-purpose{number}")
                job.prepare({**order})
                job.write("docker-plan.json", {"origin": {"invocation_id": order["invocation_id"]}, "paths": [str(self.root)]})
                cli = build(job, deadline - 300)                                   # the order was pinned with 300 s
                self.assertEqual((cli.absolute, cli.deadline), (310, 220))
                self.assertGreater(cli.deadline - 10, 120)
                restarted = build(job, deadline - 200, now=500)                    # a restart 100 s later: the same pinned deadline, never replenished
                self.assertEqual((restarted.absolute, restarted.deadline), (700, 610))
                self.assertEqual(restarted.absolute - 500, deadline - (deadline - 200))
                self.job.write("order.json", job.read("order.json"))               # the same pinned order reused by another job: its own bundle's value, not a recomputed one
                self.assertEqual(build(self.job, deadline - 300).absolute, 310)

    def test_the_final_inspect_runs_through_the_production_command_after_a_wait_that_ends_past_the_allowance(self):
        clock, seen = [10.0], []
        self.job.write("order.json", {"deadline_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(1300))})
        started = {"Id": CID, "Image": "i", "Config": {}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}, "State": {"StartedAt": "2026-11-13T01:00:00Z"}}
        ended = {**started, "State": {"StartedAt": "2026-11-13T01:00:00Z", "FinishedAt": "2026-11-13T01:00:01Z", "ExitCode": 143, "Status": "exited", "Pid": 0, "Error": "",
                                      **{k: False for k in ("Running", "Restarting", "Paused", "OOMKilled")}}}
        def execute(job, argv, env, deadline, bounds):
            seen.append((argv[3], deadline))
            if argv[3] == "wait":
                clock[0] = 225.0   # the model turn's wait returns after the allowance's cutoff (220), before the order's deadline (310)
                return 0, b"143", b""
            return 0, json.dumps([ended]).encode(), b""
        cli = d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", now=lambda: clock[0], clock=lambda: 1000.0, execute=execute)
        self.job.write("runner-start.json", started)
        self.assertEqual(cli.end(CID)["State"]["ExitCode"], 143)                       # the production `end` and `inspect`, over the transport
        self.assertEqual(seen, [("wait", 220), ("inspect", 230.0)])                     # the inspect ran, bounded by its own five seconds, past the cutoff

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
            "--log-opt", "max-size=4m", "--log-opt", "max-file=1", "--log-opt", "compress=false", "--network", NET, "--ip", "172.31.254.3",
            "--env", "GEN2_INVOCATION_ID=inv_fixture0001",
            "--tmpfs", "/work:rw,nodev,nosuid,size=128m,mode=0700,uid=10001,gid=10001",
            "--tmpfs", "/auth/codex:rw,nodev,nosuid,size=16m,mode=0700,uid=10001,gid=10001",
            "--tmpfs", "/tmp:rw,nodev,nosuid,size=64m,mode=1777,uid=10001,gid=10001",
            "--tmpfs", "/run:rw,nodev,nosuid,size=4m,mode=0700,uid=10001,gid=10001",
            "--mount", "type=bind,src=/fixture/out,dst=/out", "--mount", "type=bind,src=/fixture/inputs,dst=/inputs,readonly",
            "--mount", "type=bind,src=/fixture/seed,dst=/seed,readonly", "sha256:" + CID)
        self.assertEqual(self.execute.call_args_list[0].args[1], expected)
        self.assertEqual(self.execute.call_args_list[1].args[1], (d.CLI, "--host", "unix://" + d.SOCKET, "inspect", CID))
        self.refused(lambda: self.cli.create_runner(NET, {**binds, "out": "/different"}), "runner_originals")

    def test_the_runner_gets_exactly_one_environment_variable_its_invocation_and_the_relay_an_explicit_command(self):
        """Retained native receipts (host-T9/native-window-20261111T061545Z): the runner image has no GEN2_INVOCATION_ID and runner.launch reads it; the
        official nginx image's CMD is `nginx -g "daemon off;"` while the mounted conf already says `daemon off;`."""
        binds = self.runner_binds()
        record = {"Id": CID, "Image": "sha256:" + CID, "Config": {"Image": "sha256:" + CID}}
        self.execute.side_effect = lambda *a: ((self.job.dir / "runner.cid").write_text(CID), (0, CID.encode() if a[1][3] == "create" else json.dumps([record]).encode(), b""))[1]
        with mock.patch.object(d.Path, "read_bytes", autospec=True, side_effect=lambda path: b"pinned-cli" if str(path) == d.CLI else self.real_read_bytes(path)), mock.patch.object(d, "CLI_SHA", hashlib.sha256(b"pinned-cli").hexdigest()):
            self.cli.create_runner(NET, binds)
        argv = self.execute.call_args_list[0].args[1]
        self.assertEqual([argv[i + 1] for i, a in enumerate(argv) if a in ("--env", "-e", "--env-file")], ["GEN2_INVOCATION_ID=inv_fixture0001"])
        self.assertNotIn("capability", " ".join(argv).lower())
        for label, origin in (("missing", {}), ("empty", {"invocation_id": ""}), ("space", {"invocation_id": "a b"}), ("equals", {"invocation_id": "a=b"}),
                              ("long", {"invocation_id": "a" * 257}), ("number", {"invocation_id": 7})):
            self.cli.plan = {**self.cli.plan, "origin": origin}
            (self.job.dir / "runner.cid").unlink(missing_ok=True)
            with self.subTest(label), self.assertRaisesRegex(LiveProfileRefused, "runner_invocation"):
                self.cli.create_runner(NET, binds)
        nginx = json.loads((Path(__file__).parent / "fixtures" / "docker_inspect" / "nginx-image-20261111.json").read_text())["Config"]
        conf = (Path(__file__).parents[2] / "deploy" / "gen2" / "live" / "nginx.conf").read_text()
        self.assertEqual((nginx["Entrypoint"], nginx["Cmd"]), (["/docker-entrypoint.sh"], ["nginx", "-g", "daemon off;"]))
        self.assertIn("\ndaemon off;\n", "\n" + conf)                                              # so the image's own CMD would repeat the directive

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
                  "--ipc=private", "--cgroupns=private", "--log-driver", "local", "--log-opt", "max-size=4m", "--log-opt", "max-file=1", "--log-opt", "compress=false",
                  "--tmpfs", "/tmp:rw,nodev,nosuid,size=16m,mode=0700,uid=10001,gid=10001", "--network")
        for role, network, suffix in (
            ("initializer", None, ("none", "--mount", "type=bind,src=/slots/out,dst=/out", "--mount", "type=bind,src=/slots/evidence,dst=/evidence",
                "--user", "0:0", "--cap-add", "CHOWN", "--entrypoint", "/usr/local/bin/python", "sha256:" + CID, "-m", "gen2.supervisor.docker_cli", GENERATION)),
            ("relay", NET, (NET, "--mount", f"type=bind,src=/slots/evidence/{GENERATION},dst=/evidence", "--mount",
                "type=bind,src=/reviewed/nginx.conf,dst=/etc/nginx/nginx.conf,readonly", "--user", "10001:10001", "--sysctl", "net.ipv4.ip_forward=0",
                "--ip", "172.31.254.2", "sha256:" + CID, "nginx", "-c", "/etc/nginx/nginx.conf"))):
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

    def test_the_initializer_overrides_the_engine_images_entrypoint_and_the_real_relay_alone_mounts_the_provider_files(self):
        """Retained engine image record (host-T9/reuse-20261110T090130Z): ENTRYPOINT is the engine, no CMD, so args alone would run the engine."""
        image = json.loads((Path(__file__).parent / "fixtures" / "docker_inspect" / "engine-image-20261110.json").read_text())["Config"]
        self.assertEqual((image["Entrypoint"], image["Cmd"]), (["python3", "-m", "gen2.app.engine"], None))
        self.cli.plan.update(generation=GENERATION, slots={"out": "/slots/out", "evidence": "/slots/evidence"}, relay_config="/reviewed/nginx.conf")
        self.job.write("network-job.json", {"Id": NET})
        record = {"Id": CID, "Image": "sha256:" + "d" * 64, "Config": {"Image": "sha256:" + CID}}
        files = {"provider_auth": "/protected/provider-auth.conf", "provider_ca": "/protected/provider-ca.pem"}

        def argv(role, plan):
            self.cli.plan = {**self.cli.plan, **plan}
            self.execute.reset_mock()
            self.execute.side_effect = lambda *a: ((self.job.dir / (role + ".cid")).write_text(CID), (0, CID.encode() if a[1][3] == "create" else json.dumps([record]).encode(), b""))[1]
            (self.job.dir / (role + ".cid")).unlink(missing_ok=True)
            self.job.write("docker.json", {})
            for r in ("engine", "relay"):
                self.manifest["images"][r]["kind"] = "repo-digest"
            with mock.patch.object(d.Path, "read_bytes", autospec=True, side_effect=lambda p: b"pinned" if str(p) == d.CLI else self.real_read_bytes(p)), mock.patch.object(d, "CLI_SHA", hashlib.sha256(b"pinned").hexdigest()):
                self.cli.create_auxiliary(role, NET if role == "relay" else None)
            return self.execute.call_args_list[0].args[1]
        initializer = argv("initializer", {})
        self.assertEqual(initializer[initializer.index("--entrypoint"):][:2], ("--entrypoint", "/usr/local/bin/python"))
        self.assertLess(initializer.index("--entrypoint"), initializer.index("sha256:" + CID))   # a flag after the image would be an argument to it
        self.assertEqual(initializer[-3:], ("-m", "gen2.supervisor.docker_cli", GENERATION))
        fixture_relay = argv("relay", {"route": "fixture"})
        self.assertNotIn("provider", " ".join(fixture_relay))
        real_relay = argv("relay", {"route": "real", **files})
        for destination, source in (("etc/gen2/provider-auth.conf", files["provider_auth"]), ("etc/gen2/provider-ca.pem", files["provider_ca"])):
            self.assertIn(f"type=bind,src={source},dst=/{destination},readonly", real_relay)
        self.assertNotIn("provider", " ".join(argv("initializer", {"route": "real", **files})))      # only the relay sees them
        for label, plan in (("real without them", {"route": "real"}), ("real with one", {"route": "real", "provider_auth": files["provider_auth"]}),
                            ("fixture with them", {"route": "fixture", **files})):
            self.cli.plan = {k: v for k, v in self.cli.plan.items() if k not in files}
            self.cli.plan.update(plan)
            with self.subTest(label):
                self.refused(lambda: self.cli.create_auxiliary("relay", NET), "relay_provider_files")

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
        """I/L/E: ordered end/closure/collection, no complete marker on uncertainty; actual fixture end and collection; other Docker operations are sequencing doubles."""
        upstream, relay, fixture_id = "d" * 64, "e" * 64, "f" * 64
        record = {"Id": relay, "Image": "sha256:" + CID, "Config": {}, "HostConfig": {}, "NetworkSettings": {"Networks": {}}}
        jobn, fixn = "gen2-2e1-live-job-" + GENERATION, "gen2-2e1-live-fixture-" + GENERATION
        self.job.write("network-job.json", {"Id": NET, "Name": jobn})
        created = lambda **over: {**record, "NetworkSettings": {"Networks": {jobn: {"NetworkID": "", "IPAMConfig": {"IPv4Address": "172.31.254.2"}},
                                                                            fixn: {"NetworkID": "", "IPAMConfig": {"IPv4Address": "172.31.252.2"}}, **over}}}   # the real daemon's created state: every ID empty
        connected = created()
        topology = {"relay_topology": created(**{fixn: {"NetworkID": "", "IPAMConfig": {"IPv4Address": "172.31.252.9"}}}),
                    "relay_topology_id": created(**{fixn: {"NetworkID": "9" * 64, "IPAMConfig": {"IPv4Address": "172.31.252.2"}}}),
                    "relay_topology_extra": created(extra={"NetworkID": "", "IPAMConfig": None}), "relay_topology_job_ip": created(**{jobn: {"NetworkID": "", "IPAMConfig": {"IPv4Address": "172.31.254.9"}}})}
        member = {"NetworkID": upstream, "IPAMConfig": {"IPv4Address": "172.31.252.3"}, "Aliases": None}
        fixture = {**record, "Id": fixture_id, "NetworkSettings": {"Networks": {"fixture-upstream": member}}}   # created ON lane C's per-attempt network (a `none`-mode container joins nothing)
        # the fixture's network and its members as the daemon would show them, and the single-operand ways the hand-off can be wrong
        view = {"Id": upstream, "Name": fixn, "Internal": True, "EnableIPv6": False, "Driver": "bridge", "IPAM": {"Config": [{"Subnet": d.NETWORKS["fixture"]}]}, "Containers": {fixture_id: {}}}
        wrong = {"fixture_network_none": {"NetworkSettings": {"Networks": {"none": {"NetworkID": "9" * 64, "IPAMConfig": None, "Aliases": None}}}},   # the retained T9 native shape: connect was refused by the daemon
                 "fixture_network_ip": {"NetworkSettings": {"Networks": {"fixture-upstream": {**member, "IPAMConfig": {"IPv4Address": "172.31.252.9"}}}}},
                 "fixture_network_two": {"NetworkSettings": {"Networks": {"fixture-upstream": member, "other": {**member, "NetworkID": "8" * 64}}}},
                 "fixture_network_short": {"NetworkSettings": {"Networks": {"fixture-upstream": {**member, "NetworkID": "abc"}}}}}
        views = {"fixture_network_members": {**view, "Containers": {fixture_id: {}, "7" * 64: {}}}, "fixture_network_members_empty": {**view, "Containers": {}},
                 "fixture_network_members_open": {**view, "Internal": False}, "fixture_network_members_v6": {**view, "EnableIPv6": True},
                 "fixture_network_members_subnet": {**view, "IPAM": {"Config": [{"Subnet": "172.31.250.0/29"}]}}}
        slots = {n: str(self.root / n) for n in ("out", "evidence")}
        for path in slots.values():
            (Path(path) / GENERATION).mkdir(parents=True)
        fixture_directory = Path(slots["evidence"]) / ("4" * 32)
        fixture_directory.mkdir()
        fixture.update(Mounts=[{"Type": "bind", "Source": str(fixture_directory), "Destination": "/evidence"}],
                       HostConfig={"PidMode": "", "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                                   "Mounts": [{"Type": "bind", "Source": str(fixture_directory), "Target": "/evidence"}]},
                       State={"StartedAt": "2026-11-13T01:00:00Z"})
        for key, mounts in {"missing": [], "multiple": fixture["Mounts"] * 2,
                            "wrong_destination": [{**fixture["Mounts"][0], "Destination": "/other"}],
                            "wrong_type": [{**fixture["Mounts"][0], "Type": "volume"}],
                            "out_of_slot": [{**fixture["Mounts"][0], "Source": str(self.root / ("4" * 32))}],
                            "bad_generation": [{**fixture["Mounts"][0], "Source": str(fixture_directory.parent / "bad")} ]}.items():
            wrong["fixture_mount_" + key] = {"Mounts": mounts}
        for key, change in {"mount_source": {"Mounts": [{"Type": "bind", "Source": "/other", "Target": "/evidence"}]},
                            "multiple": {"Mounts": fixture["HostConfig"]["Mounts"] * 2}, "pid": {"PidMode": "host"},
                            "restart": {"RestartPolicy": {"Name": "always"}}}.items():
            wrong["fixture_host_" + key] = {"HostConfig": {**fixture["HostConfig"], **change}}
        self.cli.plan.update(generation=GENERATION, slots=slots, binds={"out": str(Path(slots["out"]) / GENERATION)}, fixture=fixture)
        self.job.write("identity.json", {"pid": os.getpid()})
        self.job.write("relay.json", record)
        live_wrong = {"fixture_live_mount_source": {"Mounts": [{"Type": "bind", "Source": "/other", "Destination": "/evidence"}]},   # DCK-03: only the daemon's own top-level mounts contradict the plan
                      "fixture_live_mount_missing": {"Mounts": []},
                      "fixture_live_mount_type": {"Mounts": [{**fixture["Mounts"][0], "Type": "volume"}]},
                      "fixture_live_mount_destination": {"Mounts": [{**fixture["Mounts"][0], "Destination": "/elsewhere"}]}}
        for reason in (None, "backend_unsupervised", "initializer_failed", "ingress_not_closed", "relay_drain", "relay_stop_failed", "fixture_stop_failed", "end_binding", "end_state", "end_unconfirmed", "collection_absent", "collection_identity", "generation_symlink", *wrong, *views, *topology, *live_wrong):
            with self.subTest(reason=reason), contextlib.ExitStack() as stack:
                shown = copy.deepcopy({**fixture, **wrong.get(reason, {})})
                self.cli.plan["fixture"] = shown
                live = copy.deepcopy({**shown, **live_wrong[reason]}) if reason in live_wrong else shown
                network_view = views.get(reason, view)
                connected = topology.get(reason, created())
                batch, watch = mock.Mock(), mock.Mock()
                (fixture_directory / "fixture.json").write_bytes(b'{"v":1,"requests":[{"model":"gpt-6.1-terra"}]}')
                if reason == "generation_symlink":
                    fixture_directory.rename(fixture_directory.with_name("saved"))
                    fixture_directory.symlink_to(fixture_directory.with_name("saved"), target_is_directory=True)
                actual_batch = d.EvidenceBatch(Spool(self.root / "spool", quota_bytes=64 << 20), "fleet:fixture")
                actual_end = self.cli.end
                def collect(*args, **kwargs):
                    if kwargs["kind"] == "fixture":
                        return actual_batch.collect(*args, **kwargs)
                    return {"content_hash": "sha256:" + CID}
                def end(cid, role="runner"):
                    if role == "fixture":
                        return actual_end(cid, role)
                    return {"State": {"ExitCode": int(reason == "initializer_failed" if role == "initializer" else reason == "relay_stop_failed" if role == "relay" else True)}}
                def contain(cid, *, role):
                    if role == "fixture":
                        if reason == "fixture_stop_failed":
                            raise LiveProfileRefused(reason)
                        if reason == "collection_absent":
                            (fixture_directory / "fixture.json").unlink()
                        if reason == "collection_identity":
                            fixture_directory.rename(fixture_directory.with_name("saved"))
                            fixture_directory.mkdir()
                final = {**fixture, "State": {"StartedAt": fixture["State"]["StartedAt"], "FinishedAt": "2026-11-13T01:01:00Z",
                                             "ExitCode": 143, "Status": "exited", "Pid": 0, "Error": "",
                                             **{k: False for k in ("Running", "Restarting", "Paused", "OOMKilled")}}}
                if reason == "end_binding": final = {**final, "Image": "sha256:" + "9" * 64}
                if reason == "end_state":
                    self.cli.plan["fixture"] = copy.deepcopy(fixture)
                    final["State"]["StartedAt"] = "2026-11-13T01:00:01Z"
                    shown["State"] = dict(final["State"])  # a restart before admission must not replace the protected start snapshot
                def command(args, long=False):
                    if args[0] == "wait": return b"0" if reason == "end_unconfirmed" else b"143"
                    return json.dumps([network_view if args[2] == upstream else {"Id": NET, "Containers": {relay: {}, **({CID: {}} if reason == "ingress_not_closed" else {})}}]).encode()
                stack.enter_context(mock.patch.object(d, "free_space"))
                stack.enter_context(mock.patch.object(d, "contain_job"))
                stack.enter_context(mock.patch.object(d.jobs, "members", return_value=[] if reason == "backend_unsupervised" else [os.getpid()]))
                batch.held = {"access": b"", "events": b"", "fixture": b'{"v":1,"requests":[{"model":"gpt-6.1-terra"}]}'}
                batch.collect.side_effect = collect
                batch.stage.return_value = {"content_hash": "sha256:" + CID}
                actions = {"create_auxiliary": [CID, relay], "start": None, "end": end, "network": [NET], "endpoint": None, "create_runner": CID,
                           "inspect": [live, connected, {"NetworkSettings": {"Networks": {}}}, final], "contain": contain, "runtime": None, "close_admission": None,
                           "drain": None if reason != "relay_drain" else LiveProfileRefused("relay_drain"), "logs": (b"events", b"diagnostics"), "_command": command}
                for name, result in actions.items():
                    patched = stack.enter_context(mock.patch.object(self.cli, name, **({"side_effect": result} if isinstance(result, (list, BaseException)) or callable(result) else {"return_value": result})))
                    watch.attach_mock(patched, name)
                if reason == "backend_unsupervised":
                    self.refused(lambda: self.cli.run(batch), reason)
                elif reason == "generation_symlink":
                    with self.assertRaisesRegex(LiveProfileRefused, "^collection_generation$"):
                        self.cli.run(batch)
                    self.assertIsNone(self.job.read("docker-complete.json"))
                elif reason:
                    expected = "fixture_evidence_mount" if reason.startswith("fixture_mount_") or reason in live_wrong or reason in ("fixture_host_mount_source", "fixture_host_multiple") else "fixture_runtime" if reason.startswith("fixture_host_") else "fixture_network" if reason in wrong else "fixture_network_members" if reason in views else "relay_topology" if reason in topology else reason
                    with self.assertRaisesRegex(LiveProfileRefused, "^" + expected + "$"):
                        self.cli.run(batch)
                    self.assertNotIn(mock.call.endpoint("connect", mock.ANY, mock.ANY, mock.ANY), watch.mock_calls) if reason in (*wrong, *views) else None
                    self.assertNotIn(mock.call.start(relay, "relay"), watch.mock_calls) if reason in topology else None   # refused before the relay starts   # refused before any connect
                    self.assertIsNotNone(self.job.read("docker-attempt.json"))
                    self.assertIsNone(self.job.read("docker-complete.json"))
                    if reason not in ("collection_absent", "collection_identity"):
                        batch.collect.assert_not_called()
                else:
                    refs = self.cli.run(batch)
                    self.assertEqual(len(refs), 6)
                    self.assertEqual(self.job.read("docker-complete.json")["disposition"]["disposition"], "unknown")
                    watch.assert_has_calls([mock.call.start(CID), mock.call.close_admission(), mock.call.end(CID), mock.call.endpoint("disconnect", NET, CID), mock.call._command(("network", "inspect", NET)), mock.call.inspect(CID), mock.call.drain(), mock.call.contain(relay, role="relay"), mock.call.end(relay, "relay"), mock.call.contain(fixture_id, role="fixture"), mock.call.end(fixture_id, "fixture"), mock.call._command(("wait", fixture_id), long=False), mock.call.inspect(fixture_id), mock.call.logs(CID)])
                    self.assertEqual(batch.collect.call_count, 3)
                    self.assertEqual(self.job.read("fixture-start.json"), fixture)
                    self.assertEqual(self.job.read("fixture-end.json"), final)
                    self.assertEqual(actual_batch.held["fixture"], (fixture_directory / "fixture.json").read_bytes())
                if fixture_directory.is_symlink(): fixture_directory.unlink()
                saved = fixture_directory.with_name("saved")
                if saved.exists():
                    if fixture_directory.exists(): fixture_directory.rmdir()
                    saved.rename(fixture_directory)
                for name in ("docker-attempt.json", "docker-generations.json", "docker-complete.json"):
                    (self.job.dir / name).unlink(missing_ok=True)
                self.job.write("relay.json", record)

    def real_world(self):
        """A real-route cli: manifest without the fixture role, the plan's route, egress bridge ID and upstream, output = judgment."""
        manifest = {**self.manifest, "route": "real", "images": {r: v for r, v in self.manifest["images"].items() if r != "fixture"},
                    "configurations": {r: v for r, v in self.manifest["configurations"].items() if r != "fixture"}}
        cli = d.DockerCLI(self.job, manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: 10, clock=lambda: 1000.0)
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

    def real_run(self, cli, egress, relay, record, *, collect=None, end_error=None, batch=None, logs=(b"events", b"diagnostics"), code=1):
        self.job.write("network-job.json", {"Id": NET, "Name": "gen2-2e1-live-job-" + GENERATION})
        connected = {**record, "NetworkSettings": {"Networks": {"gen2-2e1-live-job-" + GENERATION: {"NetworkID": "", "IPAMConfig": {"IPv4Address": "172.31.254.2"}},
                                                               "egress": {"NetworkID": "", "IPAMConfig": None}}}}   # created, not started: names and addresses, no IDs
        if batch is None:
            batch = mock.Mock()
            batch.held = {"access": b"", "events": b"", "judgment": b'{"judgment_version": "x"}'}
            batch.collect.side_effect = collect or (lambda *a, **k: {"content_hash": "sha256:" + CID})
            batch.stage.return_value = {"content_hash": "sha256:" + CID}
        ends = [{"State": {"ExitCode": 0}}, {"State": {"ExitCode": 0}}, {"State": {"ExitCode": 0}}]
        egress_view = json.dumps([{"Id": egress, "Name": "egress", "Internal": False, "Containers": {}}]).encode()
        ingress = json.dumps([{"Id": NET, "Containers": {relay: {}}}]).encode()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(d.jobs, "members", return_value=[os.getpid()]))
            actions = {"create_auxiliary": [CID, relay], "start": None, "end": end_error or [ends[0], {"State": {"ExitCode": code}}, ends[2]], "network": [NET], "endpoint": None,
                       "create_runner": CID, "inspect": [connected, {"NetworkSettings": {"Networks": {}}}], "contain": None, "logs": logs,
                       "runtime": None, "close_admission": None, "drain": None, "_command": [egress_view, ingress]}
            watch = mock.Mock()
            for name, result in actions.items():
                patched = stack.enter_context(mock.patch.object(cli, name, **({"side_effect": result} if isinstance(result, list) or isinstance(result, BaseException) else {"return_value": result})))
                watch.attach_mock(patched, name)
            contained = stack.enter_context(mock.patch.object(d, "contain_job"))
            try:
                refs = cli.run(batch)
            except BaseException as error:
                return error, batch, watch, contained
            return refs, batch, watch, contained

    def test_a_real_route_run_has_no_fixture_joins_the_egress_bridge_by_id_and_collects_the_judgment(self):
        cli, egress, relay, record = self.real_world()
        refs, batch, watch, contained = self.real_run(cli, egress, relay, record, code=0)
        self.assertEqual(len(refs), 5)                                              # events, diagnostics, judgment, access, usage: no fixture file
        self.assertEqual([c.kwargs["kind"] for c in batch.collect.call_args_list], ["judgment", "access"])
        self.assertIn(mock.call.endpoint("connect", egress, relay, None), watch.mock_calls)   # joined by the plan's ID, no fixed address
        self.assertNotIn("fixture", " ".join(str(c) for c in watch.mock_calls))
        done = self.job.read("docker-complete.json")
        self.assertEqual(done["disposition"]["disposition"], "unknown")             # this fake leaves no log row; classification used route=real
        contained.assert_not_called()

    def test_normal_publication_is_create_only_an_end_fact_that_appears_first_is_retained_and_the_run_fails_closed(self):
        for raw in ("[]", "null", "{", json.dumps({"origin": {"x": 1}, "refs": [], "usage": "refused"})):
            with self.subTest(raw=raw):
                for name in ("docker-attempt.json", "docker-complete.json"):
                    (self.job.dir / name).unlink(missing_ok=True)
                cli, egress, relay, record = self.real_world()
                def appears(*a, **k):   # the end fact is published by someone else between classification and our publication
                    (self.job.dir / "docker-complete.json").write_text(raw)
                    return {}
                with mock.patch.object(d.rejection, "usage_record", appears):
                    error, *_ = self.real_run(cli, egress, relay, record)
                self.assertIsInstance(error, LiveProfileRefused)
                self.assertEqual((self.job.dir / "docker-complete.json").read_text(), raw)

    def test_a_failed_exit_never_opens_the_answer_file(self):
        cli, egress, relay, record = self.real_world()
        refs, batch, *_ = self.real_run(cli, egress, relay, record, code=2)
        self.assertEqual(len(refs), 4)                                              # events, diagnostics, access, usage: no judgment ref
        self.assertEqual([c.kwargs["kind"] for c in batch.collect.call_args_list], ["access"])

    def retained(self, *, judgment, code=1, access=None, events=b"", kind="out"):
        """A real route run over real scratch files and the real EvidenceBatch: `judgment` None = no leaf, b"" = the 0.169 convention (its destination is
        bound, created empty, before the turn and a failed turn never writes it: exec/src/lib.rs:1086, event_processor_with_jsonl_output.rs:541). Operands are the retained
        failed-turn events and one 401 relay row, authored independently of the classifier."""
        cli, egress, relay, record = self.real_world()
        out, evidence = self.root / "out" / GENERATION, self.root / "evidence" / GENERATION
        if judgment is not None:
            fd = os.open(out / "judgment.json", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NOCTTY | os.O_NONBLOCK, 0o600)   # the CLI's own open
            try:
                os.write(fd, judgment) if judgment else None
            finally:
                os.close(fd)
        if access is not False:
            (evidence / "access.jsonl").write_bytes(jl({**ROW, "upstream": "203.0.113.7:443"}) if access is None else access)
        batch = d.EvidenceBatch(Spool(self.root / "spool", quota_bytes=64 << 20), "fleet:real")
        with mock.patch.object(d, "free_space"):
            result, *_ = self.real_run(cli, egress, relay, record, batch=batch, logs=(events, b"diagnostics"), code=code)
        return result, batch, self.job.read("docker-complete.json")

    def fresh(self):
        for name in ("docker-attempt.json", "docker-complete.json", "docker-generations.json"):
            (self.job.dir / name).unlink(missing_ok=True)
        for leaf in (self.root / "out" / GENERATION / "judgment.json", self.root / "evidence" / GENERATION / "access.jsonl"):
            leaf.unlink(missing_ok=True)

    def test_a_failed_exit_is_classified_and_leaves_the_answer_file_uncollected_whatever_it_holds_or_says(self):
        for code in (1, 2, 137):
            for label, judgment in (("absent", None), ("empty", b""), ("whitespace", b" "), ("valid", b'{"judgment_version": "x"}')):
                with self.subTest(code=code, judgment=label):
                    self.fresh()
                    refs, batch, done = self.retained(judgment=judgment, code=code)
                    self.assertEqual(done["disposition"], {"disposition": "credentials_rejected", "reason": "relay_401"})
                    self.assertEqual(len(refs), 4)                                  # events, diagnostics, access, usage
                    self.assertNotIn("judgment", batch.held)
                    self.assertEqual(done["refs"], refs)

    def test_the_rejection_does_not_depend_on_what_the_cli_printed(self):
        canonical = jl({"type": "thread.started"}, {"type": "turn.started"}, {"type": "turn.failed", "error": {"message": "401"}})
        extras = ({"type": "warning"}, {"type": "turn.completed", "usage": {"input_tokens": 3}}, {"type": ["turn.failed"]},
                  {"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}}, {"unrelated": 1}, {"type": "turn.failed"})
        for label, events, code in (("none", b"", 2), ("unfamiliar", jl({"type": "warning"}, {"type": "turn.failed"}, {"type": "turn.failed"}), 2),
                                    ("list type", jl({"type": ["turn.failed"]}, {"type": {"a": 1}}), 2), ("not json", b"{not json", 2),
                                    *((f"canonical + {extra}", canonical + jl(extra), 1) for extra in extras)):   # F-1: a list-valued type once raised TypeError
            with self.subTest(label):
                self.fresh()
                _, batch, done = self.retained(judgment=None, code=code, events=events)
                self.assertEqual(done["disposition"]["disposition"], "credentials_rejected")
                self.assertEqual(done["usage"], "recorded")
                if "usage" not in label:   # no well-formed completed turn: every staged count is unknown, none invented
                    counts = json.loads(batch.spool.read(done["refs"][-1]["content_hash"], topic_id="fleet:real"))["usage"]   # the published usage artifact, not the call's return value
                    self.assertEqual({k: counts[k]["state"] for k in ("input_tokens", "output_tokens", "cached_tokens")}, dict.fromkeys(("input_tokens", "output_tokens", "cached_tokens"), "unknown"))

    def test_a_successful_exit_collects_a_nonempty_answer_and_refuses_an_empty_or_missing_one(self):
        self.fresh()
        refs, batch, done = self.retained(judgment=b'{"judgment_version": "x"}', code=0)
        self.assertIn("judgment", batch.held)
        self.assertEqual(done["disposition"]["disposition"], "unknown")             # exit 0 is never a rejection
        for label, judgment, reason in (("empty", b"", "collection_empty"), ("missing", None, "collection_absent")):
            with self.subTest(label):
                self.fresh()
                error, _, done = self.retained(judgment=judgment, code=0)
                self.assertRegex(str(error), "^" + reason + "$")
                self.assertIsNone(done)                                             # no completion: containment's fallback is the only end fact

    def test_empty_or_missing_access_and_an_unsafe_judgment_are_never_swallowed_on_the_failed_exit(self):
        for label, kwargs, reason in (("empty access", dict(judgment=b"", access=b""), "collection_empty"), ("missing access", dict(judgment=b"", access=False), "collection_absent")):
            with self.subTest(label):
                for name in ("docker-attempt.json", "docker-complete.json", "docker-generations.json"):
                    (self.job.dir / name).unlink(missing_ok=True)
                (self.root / "evidence" / GENERATION / "access.jsonl").unlink(missing_ok=True)
                error, _, done = self.retained(**kwargs)
                self.assertRegex(str(error), "^" + reason + "$")
                self.assertIsNone(done)
        generation = self.root / "out" / GENERATION
        spool = Spool(self.root / "collect-spool", quota_bytes=64 << 20)
        slot_fd = d.slot(str(self.root / "out"))
        self.addCleanup(os.close, slot_fd)
        info = generation.stat()
        batch = d.EvidenceBatch(spool, "fleet:real")
        collect = lambda: batch.collect(slot_fd, GENERATION, (info.st_dev, info.st_ino), writers_ended=True, kind="judgment")
        leaf = generation / "judgment.json"
        for leaf_name in ("judgment.json",):
            (generation / leaf_name).unlink(missing_ok=True)
        leaf.symlink_to("missing")
        self.refused(collect, "collection_refused")
        leaf.unlink()
        leaf.touch()
        os.link(leaf, generation / "extra-link")
        self.refused(collect, "collection_refused")
        (generation / "extra-link").unlink()
        self.refused(collect, "collection_empty")                                   # a safe empty leaf is never an answer
        with mock.patch.object(d.os, "stat", return_value=os.stat_result((0,) * 10)):
            self.refused(collect, "collection_replaced")
        self.refused(lambda: batch.collect(slot_fd, GENERATION, (info.st_dev, info.st_ino + 1), writers_ended=True, kind="judgment"), "collection_identity")

    def test_valid_transport_failure_operands_stay_a_transport_disposition_on_a_failed_exit(self):
        row = {**ROW, "upstream": "203.0.113.7:443", "status": "504", "upstream_status": "504"}
        refs, batch, done = self.retained(judgment=b"", access=jl(row))
        self.assertIsInstance(refs, list)
        self.assertEqual(done["disposition"]["disposition"], "transport_failed")

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

    def test_the_real_daemons_two_start_transitions_are_accepted_and_nothing_else_is(self):
        """Replays the retained created/started/ended inspect records of the T9 log probe (host-T9/reuse-20261110T090130Z, CID 53bcee86...)."""
        real = json.loads((Path(__file__).parent / "fixtures" / "docker_inspect" / "log-probe-20261110.json").read_text())
        created, started, ended = real["created"], real["started"], real["ended"]
        self.assertEqual(d._binding(d._started(created, started, {})), d._binding(started))        # OomScoreAdj 0->200, OomKillDisable false->null and the none network's ID
        self.assertNotEqual(d._binding(created), d._binding(started))                           # so strict equality alone would refuse (T9 start_changed)
        self.assertEqual(d._binding(started), d._binding(ended))                               # stable after start: the end check stays strict
        self.assertEqual(started["HostConfig"]["LogConfig"]["Config"], {"compress": "false", "max-file": "1", "max-size": "4m"})
        cid = created["Id"]
        self.job.write("runner.json", created)
        self.cli.plan["expected"] = {"runner": {"Config": {"User": created["Config"]["User"]}, "HostConfig": {"PidMode": ""}}}
        with mock.patch.object(d, "free_space"), mock.patch.object(self.cli, "_command"):
            with mock.patch.object(self.cli, "inspect", side_effect=[created, started]):
                self.cli.start(cid)
            self.assertEqual(self.job.read("runner-start.json")["HostConfig"]["OomScoreAdj"], 200)
            for label, change in (("score other", {"OomScoreAdj": 300}), ("score reverted", {"OomScoreAdj": 0}), ("score bool", {"OomScoreAdj": False}),
                                  ("kill disable true", {"OomKillDisable": True}), ("kill disable false", {"OomKillDisable": False}),
                                  ("kill disable zero", {"OomKillDisable": 0}), ("other field", {"Privileged": True}), ("memory", {"Memory": 1})):
                with self.subTest(label), mock.patch.object(self.cli, "inspect", side_effect=[created, {**started, "HostConfig": {**started["HostConfig"], **change}}]):
                    self.refused(lambda: self.cli.start(cid), "start_changed")
            net = lambda value, name="none": {**started, "NetworkSettings": {"Networks": {name: {**started["NetworkSettings"]["Networks"]["none"], "NetworkID": value}}}}
            for label, record in (("short id", net("abc")), ("other network", net(started["NetworkSettings"]["Networks"]["none"]["NetworkID"], "bridge"))):
                with self.subTest(label), mock.patch.object(self.cli, "inspect", side_effect=[created, record]):
                    self.refused(lambda: self.cli.start(cid), "start_changed")
            odd = {**created, "HostConfig": {**created["HostConfig"], "OomScoreAdj": 5}}       # a created value off the table must stay equal, not become 200
            self.job.write("runner.json", odd)
            with mock.patch.object(self.cli, "inspect", side_effect=[odd, started]):
                self.refused(lambda: self.cli.start(cid), "start_changed")

    def test_every_attached_network_id_is_empty_until_start_and_then_exactly_the_expected_one(self):
        """Replays the relay's retained created-state networks (host-T9/native-pr172-20261111T085554Z): names and IPAM addresses, every NetworkID empty."""
        real = json.loads((Path(__file__).parent / "fixtures" / "docker_inspect" / "relay-created-networks-20261111.json").read_text())
        ids = real["expected_network_ids"]
        job = next(n for n in real["created_networks"] if "-job-" in n)
        fixture = next(n for n in real["created_networks"] if "-fixture-" in n)
        self.assertEqual({v["NetworkID"] for v in real["created_networks"].values()}, {""})
        created = {"Id": CID, "Image": "sha256:" + CID, "Config": {}, "HostConfig": {}, "NetworkSettings": {"Networks": real["created_networks"]}}
        expected = {job: ids["job"], fixture: ids["fixture"]}
        after = lambda **ids_: {**created, "NetworkSettings": {"Networks": {n: {**v, "NetworkID": ids_.get(n, expected.get(n))} for n, v in real["created_networks"].items()}}}
        self.assertEqual(d._binding(d._started(created, after(), expected)), d._binding(after()))             # exactly the expected IDs are accepted
        for label, started in (("job id other", after(**{job: "9" * 64})), ("fixture id other", after(**{fixture: "9" * 64})), ("job id swapped", after(**{job: ids["fixture"]})),
                               ("id still empty", after(**{fixture: ""})), ("short id", after(**{job: "abc"}))):
            with self.subTest(label):
                self.assertNotEqual(d._binding(d._started(created, started, expected)), d._binding(started))
        extra = {**created["NetworkSettings"]["Networks"], "other": {**created["NetworkSettings"]["Networks"][job]}}   # a network the backend did not attach cannot take an ID
        self.assertNotEqual(d._binding(d._started({**created, "NetworkSettings": {"Networks": extra}}, {**after(), "NetworkSettings": {"Networks": {**after()["NetworkSettings"]["Networks"], "other": {**extra["other"], "NetworkID": "7" * 64}}}}, expected)),
                            d._binding({**after(), "NetworkSettings": {"Networks": {**after()["NetworkSettings"]["Networks"], "other": {**extra["other"], "NetworkID": "7" * 64}}}}))
        self.cli.plan["expected"] = {"relay": {"Config": {}, "HostConfig": {"PidMode": ""}}}                    # through start(): the journal names the expected IDs
        self.job.write("relay.json", {**created, "HostConfig": {"PidMode": ""}, "State": {}})
        self.job.write("network-job.json", {"Id": ids["job"], "Name": job})
        self.job.write("network-upstream.json", {"Id": ids["fixture"], "Name": fixture})
        later = {**after(), "HostConfig": {"PidMode": ""}, "State": {"StartedAt": self.STARTED}}
        with mock.patch.object(d, "free_space"), mock.patch.object(self.cli, "_command"):
            with mock.patch.object(self.cli, "inspect", side_effect=[{**created, "HostConfig": {"PidMode": ""}}, later]):
                self.cli.start(CID, "relay")
            wrong = {**later, "NetworkSettings": {"Networks": {n: {**v, "NetworkID": "9" * 64} for n, v in later["NetworkSettings"]["Networks"].items()}}}
            (self.job.dir / "relay-start.json").unlink()
            with mock.patch.object(self.cli, "inspect", side_effect=[{**created, "HostConfig": {"PidMode": ""}}, wrong]):
                self.refused(lambda: self.cli.start(CID, "relay"), "start_changed")

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
        cli = d.DockerCLI(self.job, self.manifest, lambda pin: b"configuration", "reviewed-tree", execute=self.execute, now=lambda: clock[0], clock=lambda: 1000.0, sleep=lambda n: (slept.append(n), clock.__setitem__(0, clock[0] + n + 3)))
        with self.assertRaisesRegex(LiveProfileRefused, "relay_drain"):            # 8 s of grace plus scheduling overhead past the ten-second budget
            cli.drain()
        self.assertEqual(slept, [d.DRAIN_SECONDS])
        cli.sleep = lambda n: clock.__setitem__(0, clock[0] + n + 1)
        cli.drain()
        cli.sleep = mock.Mock(side_effect=KeyboardInterrupt)                         # an interrupted grace is not completion
        with self.assertRaises(KeyboardInterrupt):
            cli.drain()

    def contain_world(self, execute, roles=(("runner", "a" * 64), ("relay", "b" * 64), ("initializer", "c" * 64)), fixture="d" * 64):
        for role, cid in roles:
            (self.job.dir / (role + ".cid")).write_text(cid)
        self.job.write("docker-plan.json", {**self.job.read("docker-plan.json"), **({"fixture": {"Id": fixture}} if fixture else {})})   # the protected plan's fixture: a fixture route owes it
        pin = mock.patch.object(d.hashlib, "sha256")
        digest = pin.start()
        self.addCleanup(pin.stop)
        digest.return_value.hexdigest.return_value = d.CLI_SHA
        return mock.patch.object(d.Path, "read_bytes", self.real_read_bytes)

    def test_contain_job_ends_the_relay_first_then_every_original_and_publishes_the_end_fact(self):
        calls = []
        def execute(job, argv, env, deadline, bounds):
            calls.append(argv[3:])
            return (0, b"", b"") if argv[3] != "rm" or argv[-1] != "b" * 64 else (1, b"", b"Error: No such container: " + argv[-1].encode())
        with self.contain_world(execute):
            outcomes = d.contain_job(self.job, execute=execute, now=lambda: 0, clock=lambda: 1000.0)
        self.assertEqual(calls, [(op, *flag, cid * 64) for cid in "bacd" for op, flag in (("kill", ()), ("rm", ("-f",)))])   # relay, runner, initializer, plan fixture
        self.assertEqual([(o["role"], o["kill"], o["rm"]) for o in outcomes],
                         [("relay", "ok", "gone"), ("runner", "ok", "ok"), ("initializer", "ok", "ok"), ("fixture", "ok", "ok")])
        self.assertEqual(self.job.read("containment.json")["outcomes"], outcomes)                 # each outcome is journaled
        self.assertEqual(self.job.read("docker-complete.json"), {"origin": self.cli.plan["origin"], "refs": [], "usage": "refused",
                         "disposition": {"disposition": "unknown", "reason": "contained_without_collection"}})
        empty = jobs.Job(self.root, "job-empty")
        empty.prepare({"test": "no plan"})   # no plan, nothing created: nothing run, nothing completed
        self.assertEqual([(o["role"], o["kill"]) for o in d.contain_job(empty, execute=execute, now=lambda: 0)], [(r, "never_created") for r in ("relay", "runner", "initializer")])
        self.assertIsNone(empty.read("docker-complete.json"))
        self.assertEqual(len(calls), 8)

    def test_a_failed_kill_of_the_runner_does_not_stop_the_relay_or_the_initializer_and_the_end_is_unconfirmed(self):
        calls = []
        def execute(job, argv, env, deadline, bounds):
            calls.append(argv[3:])
            return (1, b"", b"permission denied") if argv[3:] == ("kill", "a" * 64) else (0, b"", b"")
        with self.contain_world(execute), self.assertRaises(d.ContainFailed) as caught:
            d.contain_job(self.job, execute=execute, now=lambda: 0, clock=lambda: 1000.0)
        self.assertEqual(len(calls), 8)                                                          # every CID, kill and removal, attempted
        self.assertEqual([(o["role"], o["kill"], o["rm"]) for o in caught.exception.outcomes],
                         [("relay", "ok", "ok"), ("runner", "failed", "ok"), ("initializer", "ok", "ok"), ("fixture", "ok", "ok")])
        self.assertEqual(self.job.read("containment.json")["outcomes"], caught.exception.outcomes)
        self.assertIsNone(self.job.read("docker-complete.json"))

    def test_an_error_in_one_command_or_an_unreadable_journal_entry_still_attempts_the_rest(self):
        def execute(job, argv, env, deadline, bounds):
            if argv[3] == "kill" and argv[-1] == "a" * 64:
                raise OSError("socket gone")
            return (0, b"", b"")
        with self.contain_world(execute, roles=(("runner", "a" * 64), ("relay", "not-a-cid"), ("initializer", "c" * 64))), self.assertRaises(d.ContainFailed) as caught:
            d.contain_job(self.job, execute=execute, now=lambda: 0, clock=lambda: 1000.0)
        self.assertEqual([(o["role"], o["kill"], o["rm"]) for o in caught.exception.outcomes],
                         [("relay", "journal_unreadable", "journal_unreadable"), ("runner", "error", "ok"), ("initializer", "ok", "ok"), ("fixture", "ok", "ok")])
        self.assertIsNone(self.job.read("docker-complete.json"))

    def test_the_plan_fixture_is_an_original_writer_a_failed_fixture_end_cannot_be_promoted_by_three_removals(self):
        def execute(job, argv, env, deadline, bounds):
            return (1, b"", b"daemon error") if argv[-1] == "d" * 64 else (0, b"", b"")
        with self.contain_world(execute), self.assertRaises(d.ContainFailed):
            d.contain_job(self.job, execute=execute, now=lambda: 0, clock=lambda: 1000.0)
        self.assertIsNone(self.job.read("docker-complete.json"))                                 # relay, runner and initializer are gone; the fixture is not
        self.job.write("docker-plan.json", {k: v for k, v in self.job.read("docker-plan.json").items() if k != "fixture"})
        with self.assertRaises(d.ContainFailed) as caught:                                       # a fixture route whose plan names no fixture is unknown, not a real route
            d.contain_job(self.job, execute=lambda *a: (0, b"", b""), now=lambda: 0, clock=lambda: 1000.0)
        self.assertEqual(caught.exception.outcomes[-1]["kill"], "journal_unreadable")
        self.job.write("docker-plan.json", {**self.job.read("docker-plan.json"), "route": "real"})   # a real route has no fixture to end
        self.assertEqual([o["role"] for o in d.contain_job(self.job, execute=lambda *a: (0, b"", b""), now=lambda: 0, clock=lambda: 1000.0)], ["relay", "runner", "initializer"])
        self.assertIsNotNone(self.job.read("docker-complete.json"))

    def test_an_early_refusal_before_the_fixture_is_journaled_still_ends_the_plan_fixture(self):
        calls = []
        self.execute.side_effect = lambda job, argv, *rest: calls.append(argv[3:]) or (0, b"", b"")
        self.job.write("docker-plan.json", {**self.job.read("docker-plan.json"), "fixture": {"Id": "d" * 64}})
        self.job.write("identity.json", {"pid": os.getpid()})
        with self.contain_world(self.execute, roles=(), fixture="d" * 64), mock.patch.object(d.jobs, "members", return_value=[os.getpid()]), \
                mock.patch.object(self.cli, "runtime", side_effect=LiveProfileRefused("runtime_identity")), self.assertRaisesRegex(LiveProfileRefused, "runtime_identity"):
            self.cli.plan.update(route="fixture", binds={"out": str(self.root / "o" / GENERATION)}, slots={"out": str(self.root / "o")}, generation=GENERATION)
            self.cli.run(mock.Mock())
        self.assertEqual(calls, [("kill", "d" * 64), ("rm", "-f", "d" * 64)])                    # nothing else was ever created
        self.assertIsNotNone(self.job.read("docker-complete.json"))
        self.assertEqual([(o["role"], o["kill"]) for o in self.job.read("containment.json")["outcomes"]],
                         [("relay", "never_created"), ("runner", "never_created"), ("initializer", "never_created"), ("fixture", "ok")])

    def test_a_create_without_its_cidfile_is_unknown_and_an_unreadable_journal_is_never_an_absence(self):
        ran = []
        execute = lambda job, argv, *rest: ran.append(argv[-1]) or (0, b"", b"")
        with self.contain_world(execute, roles=(("relay", "b" * 64),)):
            self.job.write("docker.json", {"k": {"intent": ["/usr/bin/docker", "create", "--cidfile", str(self.job.dir / "runner.cid")]}})
            with self.assertRaises(d.ContainFailed) as caught:
                d.contain_job(self.job, execute=execute, now=lambda: 0, clock=lambda: 1000.0)
            self.assertEqual([(o["role"], o["kill"]) for o in caught.exception.outcomes],
                             [("relay", "ok"), ("runner", "created_unrecorded"), ("initializer", "never_created"), ("fixture", "ok")])
            self.assertEqual(ran, ["b" * 64, "b" * 64, "d" * 64, "d" * 64])                      # the others were still ended
            self.assertIsNone(self.job.read("docker-complete.json"))
            (self.job.dir / "docker.json").write_text("not json")
            with self.assertRaises(d.ContainFailed):
                d.contain_job(self.job, execute=execute, now=lambda: 0, clock=lambda: 1000.0)
            self.assertIsNone(self.job.read("docker-complete.json"))

    def test_unresolved_mutation_history_or_cli_state_blocks_the_end_fact_even_when_every_original_is_never_created(self):
        calls = []
        execute = lambda *a: calls.append(a[1][3:]) or (0, b"", b"")
        self.job.write("docker-plan.json", {**self.job.read("docker-plan.json"), "route": "real"})
        create = {"intent": ["/usr/bin/docker", "create", "--cidfile", str(self.job.dir / "relay.cid")]}
        identity = {"pid": 4242, "session": 4242, "starttime": 7, "boot_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12}
        def attempt(history=None, cli=None, raw=None):
            for name in ("docker-complete.json", "docker-cli.json", "containment.json", "docker.json"):
                (self.job.dir / name).unlink(missing_ok=True)
            self.job.write("docker-attempt.json", {"origin": self.job.read("docker-plan.json")["origin"]})   # the attempt began: only an intact history proves an absence
            if raw is not None:
                (self.job.dir / "docker.json").write_text(raw)
            elif history is not None:
                self.job.write("docker.json", history)
            if cli is not None:
                self.job.write("docker-cli.json", cli)
            return lambda: d.contain_job(self.job, execute=execute, now=lambda: 0, clock=lambda: 1000.0)
        with self.contain_world(execute, roles=(), fixture=None):
            run = attempt({})   # control: an intact, empty history with no CLI record is a genuine early refusal, and still completes
            self.assertEqual({o["kill"] for o in run()}, {"never_created"})
            self.assertIsNotNone(self.job.read("docker-complete.json"))
            attempt({}, cli={**identity, "confirmed": True})()   # control: a resolved (confirmed, well-formed) CLI record does not block it
            self.assertIsNotNone(self.job.read("docker-complete.json"))
            with self.assertRaises(d.ContainFailed):
                attempt({"k": create})()   # control: a well-formed journal that shows the relay create, with no cidfile, is unknown
            for name, kwargs in (("malformed nested entry", {"history": {"create-relay": {}}}), ("non-object entry", {"history": {"k": "x"}}), ("null entry", {"history": {"k": None}}),
                                 ("empty intent", {"history": {"k": {"intent": []}}}), ("non-string intent", {"history": {"k": {"intent": [1]}}}),
                                 ("missing history", {}), ("null history", {"raw": "null"}), ("unreadable history", {"raw": "{"}),
                                 ("intent-only CLI", {"history": {}, "cli": {"intent": ["/usr/bin/docker", "wait"]}}),
                                 ("malformed CLI identity", {"history": {}, "cli": {**identity, "boot_id": "", "confirmed": True}}),
                                 ("unconfirmed CLI identity", {"history": {}, "cli": identity})):
                with self.subTest(name), self.assertRaises(d.ContainFailed):
                    attempt(**kwargs)()
                self.assertIsNone(self.job.read("docker-complete.json"), name)   # held: no fallback end fact
            self.assertEqual(calls, [])   # nothing was run for an original that has no cidfile
            run = attempt({"create-relay": {}}, raw=None)
            (self.job.dir / "runner.cid").write_text("a" * 64)   # an independently identifiable original is still attempted under the global uncertainty
            with self.assertRaises(d.ContainFailed):
                run()
            self.assertEqual(calls, [("kill", "a" * 64), ("rm", "-f", "a" * 64)])
            self.assertIsNone(self.job.read("docker-complete.json"))

    def test_the_end_fact_needs_the_relay_gone_within_the_lateness_allowance_and_the_relay_goes_first(self):
        now = [0.0]
        def execute(job, argv, env, deadline, bounds):
            now[0] += 30 if argv[-1] == "a" * 64 else 5   # a slow runner; everything else quick
            return (0, b"", b"")
        with self.contain_world(execute):
            # the order's deadline is 10 s away: the relay must be removed by 10 + LATE_END_S = 60 s after entry
            d.contain_job(self.job, execute=execute, now=lambda: now[0], clock=lambda: 1200.0 + 0.0)
            self.assertIsNotNone(self.job.read("docker-complete.json"))                          # relay first: removed at 10 s, the slow runner after it
            self.assertFalse(self.job.read("containment.json")["late"])
            (self.job.dir / "docker-complete.json").unlink()
            now[0] = 0.0
            d.contain_job(self.job, execute=execute, now=lambda: now[0], clock=lambda: 1200.0 + 55)   # entered 55 s after the deadline: the relay's removal lands at 65 > 50
            self.assertTrue(self.job.read("containment.json")["late"])
            self.assertIsNone(self.job.read("docker-complete.json"))                             # confirmed ended but outside the qualified window: unknown, held

    def test_the_fallback_end_fact_can_never_replace_a_normal_one_even_when_it_appears_between_absence_and_publication(self):
        normal = {"origin": self.cli.plan["origin"], "refs": [{"content_hash": "sha256:" + CID}], "usage": "recorded", "disposition": {"disposition": "credentials_rejected"}}
        raced, link, replace = [], os.link, os.replace
        def before(real):
            def publish(source, target, *a, **k):
                if str(target).endswith("docker-complete.json") and not raced:   # a surviving child's normal marker lands at the last instant
                    raced.append(1)
                    (self.job.dir / "normal.tmp").write_text(json.dumps(normal))
                    replace(self.job.dir / "normal.tmp", target)
                return real(source, target, *a, **k)
            return publish
        with self.contain_world(lambda *a: (0, b"", b"")), mock.patch.object(jobs.os, "link", before(link)), mock.patch.object(jobs.os, "replace", before(replace)):
            d.contain_job(self.job, execute=lambda *a: (0, b"", b""), now=lambda: 0, clock=lambda: 1000.0)
        self.assertEqual(raced, [1])
        self.assertEqual(self.job.read("docker-complete.json"), normal)
        self.assertFalse(list(self.job.dir.glob("docker-complete.json.*")))                      # no staged file is left behind

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
        self.assertEqual((done["usage"], len(done["refs"]), len(refs)), ("refused", 3, 3))     # the classified disposition and every raw reference (no answer file on a failed exit) are still there

    def test_supervisor_holds_uncertain_backend_rows(self):
        """L: no capacity release before backend end; direct control-call boundary only."""
        from gen2.supervisor.supervisor import Supervisor, Waiting
        control = mock.Mock()
        supervisor = Supervisor(control, None, self.root, station_id="fixture", host_id="fixture", clock=lambda: "2026-11-04T00:00:00Z")
        journal = {"budgets": {}}
        attempts = supervisor.policy.unknown_attempts
        requests = (("record_transition", {"to_state": "failed"}), ("reconcile", {"resolution": "confirmed_failed"}), ("commit_outcome", {}))
        for attempt in range(attempts + 1):
            method, request = requests[attempt % len(requests)]
            with self.assertRaisesRegex(Waiting, "backend_end_unconfirmed" if attempt < attempts else "stalled"):
                supervisor._call(self.job, journal, method, request)
        self.assertEqual((journal["budgets"]["unknown"], journal["incident"]["kind"]), (attempts, "backend_end_unconfirmed"))
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
