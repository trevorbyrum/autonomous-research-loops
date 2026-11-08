"""The live agent step (PR-L2). Oracles: the files the agent leaves (judgment.json, scratch evidence), the child's exit code, and the Router-facing
rejection operands the authority derives from the backend's own records. Limits: DockerCLI is a stub here (its own sequence is test_docker_cli's);
the host-side observers are lane C's, so the mailbox is tested only as the in-engine side of the exchange. No container and no provider run (F1).
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gen2.app import child, live
from gen2.core import canonical
from gen2.exec.common import Refused
from gen2.supervisor import docker_cli, jobs
from gen2.supervisor.isolation import LiveProfileRefused

NONCE, CID = "n" * 32, "c" * 64


class Mail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.requests, self.responses = Path(self.tmp.name, "requests"), Path(self.tmp.name, "responses")
        self.requests.mkdir()
        self.responses.mkdir()
        self.box = live.Mailbox(self.requests, self.responses, NONCE, 1, sleep=lambda s: None)

    def answer(self, op, cid=None, **fields):
        name = f"{NONCE}-1-{cid or 'attempt'}-{op}.json"
        (self.responses / name).write_bytes(canonical.canonical_bytes({"op": op, "nonce": NONCE, "attempt": 1, "cid": cid, **fields}))

    def test_an_end_is_confirmed_only_by_a_matching_host_answer_never_by_default(self):
        original = {"Id": CID}
        self.assertFalse(self.box.descendants_ended(original))                      # no answer
        self.answer("ended", CID, ended=False)
        self.assertFalse(self.box.descendants_ended(original))                      # the host says not ended
        self.answer("ended", "d" * 64, ended=True)
        self.assertFalse(self.box.descendants_ended(original))                      # an answer about another container
        self.answer("ended", CID, ended=True)
        self.assertTrue(self.box.descendants_ended(original))
        (self.responses / f"{NONCE}-1-{CID}-ended.json").write_bytes(canonical.canonical_bytes({"op": "ended", "nonce": "x" * 32, "attempt": 1, "cid": CID, "ended": True}))
        self.assertFalse(self.box.descendants_ended(original))                      # another nonce in the right file name
        (self.responses / f"{NONCE}-1-{CID}-ended.json").write_bytes(b"{not json")
        self.assertFalse(self.box.descendants_ended(original))
        self.assertTrue((self.requests / f"{NONCE}-1-{CID}-ended.json").exists())   # each question was written for the host to read

    def test_drain_waits_for_the_hosts_answer_and_times_out_false(self):
        self.assertFalse(self.box.drain(0.0))
        self.answer("drain", drained=True)
        self.assertTrue(self.box.drain(1.0))
        self.answer("drain", drained=False)
        self.assertFalse(self.box.drain(1.0))

    def test_close_admission_writes_one_request_and_no_router_call(self):
        self.box.close_admission()
        self.assertEqual([p.name for p in self.requests.iterdir()], [f"{NONCE}-1-attempt-close_admission.json"])


class Batch(unittest.TestCase):
    def test_collected_files_are_set_aside_in_scratch_by_digest_bounded_and_held_for_the_classifier(self):
        with tempfile.TemporaryDirectory() as directory:
            batch = live.ScratchBatch(Path(directory))
            ref = batch.stage(b"raw log", "application/x-ndjson", "access")
            self.assertEqual((ref["size_bytes"], batch.held["access"]), (7, b"raw log"))
            self.assertEqual([p.suffix for p in Path(directory).iterdir()], [".ndjson"])
            batch.stage(b"events", "application/octet-stream")
            with self.assertRaisesRegex(LiveProfileRefused, "evidence_media"):
                batch.stage(b"x", "image/png")
            batch.used = docker_cli.BATCH
            with self.assertRaisesRegex(LiveProfileRefused, "collection_batch_cap"):
                batch.stage(b"y", "application/json")


class Agent(unittest.TestCase):
    ENV = {"GEN2_MANIFEST": "m", "GEN2_RETAINED_DIR": "r", "GEN2_MAILBOX_REQUESTS": "q", "GEN2_MAILBOX_RESPONSES": "p"}

    def world(self, *, plan=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        job = jobs.Job(root, "job-inv_live00001")
        job.prepare({"x": 1})
        if plan:
            job.write("docker-plan.json", {"origin": {"invocation_id": "inv_live00001"}, "generation": "g" * 32})
        (root / "manifest.json").write_text(json.dumps({"tree": "t"}))
        (root / "r").mkdir()
        env = {**self.ENV, "GEN2_MANIFEST": str(root / "manifest.json"), "GEN2_RETAINED_DIR": str(root / "r"), "GEN2_MAILBOX_REQUESTS": str(root / "q"), "GEN2_MAILBOX_RESPONSES": str(root / "p")}
        return job, job.scratch, env

    def stub(self, *, disposition="credentials_unused", judgment=b'{"judgment_version": "judgment-review/1", "outcome": "sufficient", "summary": "ok"}', refuse=None):
        class Stub:
            def __init__(self, job_, manifest, retained, tree, **kw):
                self.job = job_

            def run(self, close, ended, fixture, drain, batch):
                if refuse:
                    raise LiveProfileRefused(refuse)
                assert fixture() is None                                   # a real route has no fixture
                if judgment is not None:
                    batch.stage(judgment, "application/json", "judgment")
                self.job.write("docker-complete.json", {"origin": {}, "refs": [], "disposition": {"disposition": disposition}})
        return mock.patch.object(docker_cli, "DockerCLI", Stub)

    def run_agent(self, job, scratch, env, **kw):
        out = scratch / "out"
        out.mkdir(exist_ok=True)
        with self.stub(**kw):
            return live.agent_for(scratch, env)(b"", b"", out), out

    def test_a_job_without_a_plan_keeps_the_closed_entrance_and_one_without_observers_refuses_by_name(self):
        job, scratch, env = self.world(plan=False)
        with self.assertRaisesRegex(Refused, "live runner entrance is closed"):
            live.agent_for(scratch, env)
        job, scratch, env = self.world()
        for missing in self.ENV:
            with self.subTest(missing=missing), self.assertRaisesRegex(Refused, "observers_unavailable"):
                live.agent_for(scratch, {k: v for k, v in env.items() if k != missing})

    def test_the_judgment_bytes_the_backend_collected_are_what_job_run_will_read(self):
        job, scratch, env = self.world()
        code, out = self.run_agent(job, scratch, env)
        self.assertEqual((code, (out / "judgment.json").read_bytes()), (0, b'{"judgment_version": "judgment-review/1", "outcome": "sufficient", "summary": "ok"}'))
        self.assertTrue(list(scratch.glob("evidence-*.json")))                       # the collected file is set aside for the supervisor to stage

    def test_a_rejected_credential_is_exit_one_a_backend_refusal_or_missing_judgment_is_exit_two_and_nothing_is_written(self):
        job, scratch, env = self.world()
        with self.assertRaises(live.CredentialsRejected):
            self.run_agent(job, scratch, env, disposition="credentials_rejected", judgment=None)
        self.assertEqual(self.main(scratch, env), 0)                                  # a clean live run: the judgment is validated and the outcome built
        self.assertTrue((scratch / "outcome.json").exists())
        self.assertEqual(self.main(scratch, env, disposition="credentials_rejected"), 1)
        self.assertEqual(self.main(scratch, env, refuse="end_unconfirmed"), 2)
        self.assertEqual(self.main(scratch, env, judgment=None), 2)

    def main(self, scratch, env, **kw):
        """The child's own `main` over the real live agent (DockerCLI stubbed): the exit code is what the supervisor and the Router see."""
        (scratch / "inputs").mkdir(exist_ok=True)
        document = {"input_version": "work-input/1", "kind": "checkpoint", "purpose": "review", "invocation_id": "inv_live00001", "topic_id": "fleet-a:t1",
                    "admission": {}, "limits": {"max_input_bytes": 10**6, "max_output_bytes": 10**6}, "view": {}, "truncation": []}
        data = canonical.canonical_bytes(document)
        (scratch / "inputs" / "input.json").write_bytes(data)
        (scratch / "inputs" / "prompt.md").write_bytes(b"p")
        (scratch / "outcome.json").unlink(missing_ok=True)
        with self.stub(**kw):
            return child.main([str(scratch)], env={**env, "GEN2_PURPOSE": "checkpoint/review", "GEN2_INPUT_DIGEST": canonical.bytes_digest(data)},
                              table={"checkpoint/review": lambda stage, bytes_of: (lambda work, judgment: {})})
