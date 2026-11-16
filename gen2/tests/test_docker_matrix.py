"""The completion invariant as one table. `docker-complete.json` carrying the plan's origin exists only if every original is ended or proven never created by an
intact journal, no CLI is unresolved and the end was not late; it is never replaced. The uniform read rule: a file's absence is no information yet, a file that is
present but not an object (null, a list, malformed) is uncertain and never absent. Every cell is (entrance, file, state) -> what launches, what is overwritten, what is
published. No Docker, no provider."""
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
from gen2.supervisor.supervisor import Supervisor

ORIGIN = {"invocation": "fixture", "invocation_id": "inv_fixture0001"}
IDENTITY = {"pid": 4242, "session": 4242, "starttime": 7, "boot_id": "0" * 8 + "-0000-0000-0000-" + "0" * 12, "confirmed": True}
FILES = ("docker-plan.json", "docker-attempt.json", "docker.json", "docker-cli.json", "docker-complete.json")
STATES = ("absent", "null", "list", "malformed", "valid")
RAW = {"null": "null", "list": "[]", "malformed": "{"}
VALID = {"docker-plan.json": {"origin": ORIGIN, "route": "real", "binds": {"out": "/s/out/" + "c" * 32}, "slots": {"out": "/s/out"}, "generation": "c" * 32},
         "docker-attempt.json": {"origin": ORIGIN}, "docker.json": {}, "docker-cli.json": IDENTITY,
         "docker-complete.json": {"origin": ORIGIN, "refs": [], "usage": "refused", "disposition": {"disposition": "unknown", "reason": "x"}}}
QUIET = {"docker-plan.json": "valid", "docker-attempt.json": "valid", "docker.json": "valid", "docker-cli.json": "absent", "docker-complete.json": "absent"}   # a started, empty attempt


class Matrix(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.job = jobs.Job(self.root, "job-fixture")
        self.job.prepare({"deadline_at": "1970-01-01T00:20:10Z"})
        pin = "sha256:" + hashlib.sha256(b"configuration").hexdigest()
        self.manifest = {"version": 1, "tree": "t", "platform": "linux/amd64", "route": "real", "socket": d.SOCKET, "cli_sha256": hashlib.sha256(b"pinned").hexdigest(), "daemon_version": "29.0.0",
                         "credential_ref": "x", "credential_version": "v1", "supervision": "supervised", "qualification_state": "qualified", "qualification_ref": pin,
                         "images": {r: {"pin": "sha256:" + "1" * 64, "kind": "engine-image-id"} for r in d.ROLES - {"fixture"}},
                         "configurations": {r: {"pin": pin} for r in d.ROLES - {"fixture"}}}
        self.execute = mock.Mock(return_value=(0, b"", b""))
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(d.Path, "read_bytes", lambda p, real=Path.read_bytes: b"pinned" if str(p) == d.CLI else real(p)).start()   # the pinned CLI, rehashed at use
        mock.patch.object(d, "CLI_SHA", hashlib.sha256(b"pinned").hexdigest()).start()
        mock.patch.object(d, "_deadline", lambda job: 1210.0).start()

    def put(self, name, state, *, base=None):
        path = self.job.dir / name
        path.unlink(missing_ok=True)
        if state == "valid":
            self.job.write(name, VALID[name])
        elif state != "absent":
            path.write_text(RAW[state])

    def world(self, file, state):
        """A started, empty attempt with exactly one file changed to `state`; returns every file's bytes."""
        for name, base in QUIET.items():
            self.put(name, state if name == file else base)
        return self.bytes()

    def bytes(self):
        return {n: (self.job.dir / n).read_bytes() if (self.job.dir / n).exists() else None for n in FILES}

    def cli(self):
        return d.DockerCLI(self.job, {**self.manifest, "tree": "t"}, lambda pin: b"configuration", "t", execute=self.execute, now=lambda: 10, clock=lambda: 1000.0)

    def outcome(self, action):
        try:
            action()
            return "ok"
        except (LiveProfileRefused, ValueError) as refused:
            return "held" if isinstance(refused, d.ContainFailed) else "refused"

    # -- entrances: each returns what the cell asserts --------------------------------------------------------------------------------------------------------
    def enter_constructor(self):
        return self.outcome(self.cli)

    def enter_run(self):
        cli = self.cli() if self.job.read("docker-plan.json") else None
        with mock.patch.object(d.jobs, "members", return_value=[os.getpid()]), mock.patch.object(d.DockerCLI, "_run", lambda self, batch, real: self._command(("kill", "a" * 64))):
            self.job.write("identity.json", {"pid": os.getpid()})
            return self.outcome(lambda: cli.run(None))

    def enter_command(self):
        return self.outcome(lambda: self.cli()._command(("kill", "a" * 64)))

    def enter_capture(self):
        marker = self.root / "launched"
        marker.unlink(missing_ok=True)
        script = self.root / "launch.py"
        script.write_text(f"open({str(marker)!r}, 'w')")   # run by path: the CLI under test is any process
        result = self.outcome(lambda: d.capture(self.job, [sys.executable, str(script)], {"PATH": "/usr/bin:/bin"}, time.monotonic() + 30, (4096, 4096)))
        return result, marker.exists()

    def enter_contain(self):
        for role in ("relay", "runner", "initializer"):
            (self.job.dir / (role + ".cid")).unlink(missing_ok=True)
        return self.outcome(lambda: d.contain_job(self.job, execute=self.execute, now=lambda: 0, clock=lambda: 1000.0))

    def enter_terminate(self):
        supervisor, called = Supervisor.__new__(Supervisor), []
        with mock.patch.object(Supervisor, "_end_group", return_value={"confirmed": True}), mock.patch.object(Supervisor, "_process"), mock.patch.object(Supervisor, "_handled"), \
                mock.patch.object(Supervisor, "_save"), mock.patch.object(Supervisor, "_retain"), mock.patch.object(d, "contain_job", lambda job: called.append(1)):
            supervisor._terminate(self.job, {}, {}, {"identity": {}}, "timeout")
        return bool(called)

    # -- the table --------------------------------------------------------------------------------------------------------------------------------------------
    def test_constructor_launches_nothing_and_writes_nothing_and_needs_only_an_object_plan_with_an_origin(self):
        for file in FILES:
            for state in STATES:
                with self.subTest(file=file, state=state):
                    before = self.world(file, state)
                    ok = file != "docker-plan.json" or state == "valid"
                    self.assertEqual(self.enter_constructor(), "ok" if ok else "refused")
                    self.assertEqual(self.bytes(), before)   # in particular, an absent history stays absent: freshness is created at the attempt transition only
                    self.execute.assert_not_called()

    def test_run_starts_an_attempt_only_from_a_truly_absent_marker_and_never_rewrites_a_present_one_or_a_present_history(self):
        for state in STATES:
            for history in STATES:
                with self.subTest(attempt=state, history=history):
                    self.world("docker-attempt.json", state)
                    self.put("docker.json", history)
                    before = self.bytes()
                    self.execute.reset_mock()
                    result = self.enter_run()
                    after = self.bytes()
                    if state != "absent":   # present, valid or not: a started attempt, refused, nothing rewritten, nothing launched
                        self.assertEqual((result, after, self.execute.called), ("refused", before, False))
                    elif history in ("absent", "valid"):   # fresh: history born with the marker, only if absent; the first mutation launches
                        self.assertEqual((result, self.execute.called, json.loads(after["docker-attempt.json"])), ("ok", True, {"origin": ORIGIN}))
                    else:   # a present, invalid history is never rewritten and no mutation launches on it
                        self.assertEqual((result, after["docker.json"], self.execute.called), ("held", before["docker.json"], False))   # the first mutation refuses on the unknown history and containment then holds

    def test_command_journals_only_on_an_intact_history_and_absent_after_the_attempt_is_unknown(self):
        for state in STATES:
            with self.subTest(history=state):
                before = self.world("docker.json", state)
                self.execute.reset_mock()
                result = self.enter_command()
                if state == "valid":
                    self.assertEqual((result, self.execute.called), ("ok", True))   # the intact history admits the mutation, which launches
                else:
                    self.assertEqual((result, self.bytes(), self.execute.called), ("refused", before, False))

    def test_capture_launches_only_over_an_absent_or_ended_record_and_never_overwrites_an_uncertain_one(self):
        for state in STATES:
            with self.subTest(cli=state):
                before = self.world("docker-cli.json", state)
                result, launched = self.enter_capture()
                if state in ("absent", "valid"):
                    self.assertTrue(launched)   # absent: no CLI; valid: an ended (confirmed) one
                    self.assertEqual(json.loads(self.bytes()["docker-cli.json"]).get("confirmed"), True)   # and this launch's own end was recorded
                else:
                    self.assertEqual((launched, self.bytes()["docker-cli.json"]), (False, before["docker-cli.json"]))
                    self.assertEqual(result, "refused")

    def test_containment_publishes_the_end_fact_only_when_every_original_is_proven_never_created_by_an_intact_journal_and_never_replaces_it(self):
        expected = {"docker-plan.json": {"absent": "none", "null": "held", "list": "held", "malformed": "held", "valid": "published"},
                    "docker-attempt.json": {"absent": "published", "null": "held", "list": "held", "malformed": "held", "valid": "published"},
                    "docker.json": {"absent": "held", "null": "held", "list": "held", "malformed": "held", "valid": "published"},
                    "docker-cli.json": {"absent": "published", "null": "held", "list": "held", "malformed": "held", "valid": "published"},
                    "docker-complete.json": {"absent": "published", "null": "held", "list": "held", "malformed": "held", "valid": "kept"}}
        for file in FILES:
            for state in STATES:
                with self.subTest(file=file, state=state):
                    before = self.world(file, state)
                    result = self.enter_contain()
                    after = self.bytes()["docker-complete.json"]
                    published = json.loads(after) if after and after not in (b"null", b"[]", b"{") else None
                    want = expected[file][state]
                    self.assertEqual(result == "held", want == "held")
                    if want == "published":
                        self.assertEqual((published or {}).get("disposition", {}).get("reason"), "contained_without_collection")
                    elif want == "kept":
                        self.assertEqual(after, before["docker-complete.json"])   # never replaced
                    else:
                        self.assertEqual(after, before["docker-complete.json"])   # held or no plan: nothing published
                    self.assertEqual(self.bytes()["docker-cli.json"], before["docker-cli.json"])   # containment resolves nothing by rewriting the CLI record
                    self.assertEqual(self.bytes()["docker.json"], before["docker.json"])

    def test_before_the_attempt_transition_nothing_could_have_been_created_so_containment_ends_the_plan_fixture_by_id_and_may_publish(self):
        self.world("docker-attempt.json", "absent")
        self.put("docker.json", "absent")   # no marker, no history, no CLI record: a `backend_unsupervised` refusal
        self.job.write("docker-plan.json", {**VALID["docker-plan.json"], "route": "fixture", "fixture": {"Id": "d" * 64}})
        self.execute.side_effect = lambda *a: (0, b"", b"")
        outcomes = d.contain_job(self.job, execute=self.execute, now=lambda: 0, clock=lambda: 1000.0)
        self.assertEqual({o["role"]: o["kill"] for o in outcomes}, {"relay": "never_created", "runner": "never_created", "initializer": "never_created", "fixture": "ok"})
        self.assertEqual([c.args[1][3:] for c in self.execute.call_args_list], [("kill", "d" * 64), ("rm", "-f", "d" * 64)])
        self.assertIsNotNone(self.job.read("docker-complete.json"))

    def test_a_published_completion_is_never_replaced_and_no_attempt_begins_over_it(self):
        for state in ("null", "list", "malformed", "valid"):
            with self.subTest(complete=state):
                self.world("docker-attempt.json", "absent")
                self.put("docker.json", "absent")
                self.put("docker-complete.json", state)
                before = self.bytes()
                self.execute.reset_mock()
                self.assertEqual(self.enter_run(), "refused")
                self.assertEqual((self.bytes(), self.execute.called), (before, False))   # bytes unchanged, no history, no attempt marker, nothing launched

    def test_contain_job_publishes_a_pre_attempt_end_and_a_later_run_refuses_leaving_it_byte_for_byte(self):
        self.world("docker-attempt.json", "absent")
        self.put("docker.json", "absent")
        self.put("docker-complete.json", "absent")
        self.enter_contain()
        before = self.bytes()
        self.assertIsNotNone(before["docker-complete.json"])
        self.assertEqual(self.enter_run(), "refused")
        self.assertEqual(self.bytes(), before)

    def test_the_supervisors_terminate_contains_for_every_plan_that_is_present_whatever_its_state(self):
        for state in STATES:
            with self.subTest(plan=state):
                self.world("docker-plan.json", state)
                self.assertEqual(self.enter_terminate(), state != "absent")


if __name__ == "__main__":
    unittest.main()
