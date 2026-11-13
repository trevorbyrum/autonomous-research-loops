"""gen2/exec core, orders and job. Oracles: outcome-document.schema.json's own `required` list, the schema set's
verdict on work-input/1, and the digest of the bytes written (hashlib). Limits: purpose builders, views and the
real agent step are other PRs'; the agent here is a stub that writes one canned file."""
import hashlib
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from gen2.core import canonical, instants
from gen2.exec import common, job, orders
from gen2.router.schemas import SCHEMA_DIR, SchemaSet

PROMPT = b"You are the scoping pass.\n"
TOPIC = "fleet:topic"
CONTRACT = {"context": "contract/1", "contract": {"revision": 1, "content_hash": "sha256:" + "a" * 64}}
NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


def entry(**over):
    pin = "sha256:" + hashlib.sha256(PROMPT).hexdigest()
    return {"kind": "research_pass", "purpose": "scope", "prompt": {"version": 1, "content_hash": pin},
            "deadline_s": 600, "lease_s": 900, "max_input_bytes": 4096, "max_output_bytes": 2048, **over}


def bundle(*entries):
    return {"policy": {"executors": list(entries)}}


class CommonTest(unittest.TestCase):
    def test_scaffold_has_exactly_the_schema_required_sections(self):
        required = json.loads((SCHEMA_DIR / "outcome-document.schema.json").read_text())["required"]
        document = common.scaffold("inv_aaaaaaaa", TOPIC)
        self.assertEqual(set(required), set(document))
        self.assertEqual(SchemaSet().errors(document, "outcome-document.schema.json"), [])

    def test_scaffold_refuses_a_section_the_outcome_does_not_have(self):
        with self.assertRaises(common.Refused):
            common.scaffold("inv_aaaaaaaa", TOPIC, verdicts=[])

    def test_derived_ids_are_stable_and_distinct_by_kind_and_index(self):
        a = common.derived_id("clm", "inv_aaaaaaaa", "claim", 0)
        self.assertEqual(a, common.derived_id("clm", "inv_aaaaaaaa", "claim", 0))
        self.assertRegex(a, r"^clm_[A-Za-z0-9_-]{8,64}$")
        others = {common.derived_id("clm", "inv_aaaaaaaa", "claim", 1), common.derived_id("clm", "inv_aaaaaaaa", "link", 0),
                  common.derived_id("clm", "inv_bbbbbbbb", "claim", 0)}
        self.assertNotIn(a, others)
        self.assertEqual(len(others), 3)


class OrdersTest(unittest.TestCase):
    def test_entry_lookup_refuses_absent_and_malformed(self):
        self.assertEqual(orders.executor_entry(bundle(entry()), "research_pass", "scope")["lease_s"], 900)
        for case, b in (("absent", bundle()), ("other purpose", bundle(entry(purpose="research"))),
                        ("zero cap", bundle(entry(max_input_bytes=0))), ("missing deadline", bundle({k: v for k, v in entry().items() if k != "deadline_s"}))):
            with self.subTest(case), self.assertRaises(common.Refused):
                orders.executor_entry(b, "research_pass", "scope")

    def test_mounted_prompt_must_match_its_pin(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "research_pass.scope.md"
            path.write_bytes(PROMPT)
            self.assertEqual(orders.mounted_prompt(Path(root), entry()), PROMPT)
            path.write_bytes(PROMPT + b"tampered")
            with self.assertRaises(common.Refused):
                orders.mounted_prompt(Path(root), entry())
            path.unlink()
            with self.assertRaises(common.Refused):
                orders.mounted_prompt(Path(root), entry())

    def document(self, **over):
        return orders.work_input(kind="research_pass", purpose="scope", invocation_id="inv_aaaaaaaa", topic_id=TOPIC,
                                 admission=CONTRACT, entry=entry(), view={"brief": {}}, truncation=[], **over)

    def test_work_input_validates_against_the_schema(self):
        self.assertEqual(SchemaSet().errors(self.document(), "work-input.schema.json"), [])

    def test_written_inputs_are_digested_and_capped(self):
        with tempfile.TemporaryDirectory() as root:
            digest = orders.write_inputs(Path(root), entry=entry(), prompt=PROMPT, document=self.document())
            written = (Path(root) / "inputs" / "input.json").read_bytes()
            self.assertEqual(digest, "sha256:" + hashlib.sha256(written).hexdigest())
            self.assertEqual((Path(root) / "inputs" / "prompt.md").read_bytes(), PROMPT)
            with self.assertRaises(common.Refused):
                orders.write_inputs(Path(root), entry=entry(max_input_bytes=10), prompt=PROMPT, document=self.document())

    def test_order_is_deterministic_and_carries_the_pins(self):
        args = dict(bundle=bundle(entry()), bundle_hash="sha256:" + "b" * 64, kind="research_pass", purpose="scope",
                    topic_id=TOPIC, ordinal=1, now=NOW, directory="/scratch/x", input_digest="sha256:" + "c" * 64)
        order = orders.build_order(**args)
        self.assertEqual(order, orders.build_order(**args))
        self.assertNotEqual(order.invocation_id, orders.build_order(**{**args, "ordinal": 2}).invocation_id)
        self.assertRegex(order.invocation_id, r"^inv_[A-Za-z0-9_-]{8,64}$")
        self.assertEqual((order.deadline_at, order.lease_expires_at), ("2026-11-05T12:10:00Z", "2026-11-05T12:15:00Z"))
        self.assertTrue(instants.is_utc_instant(order.deadline_at))
        self.assertEqual(order.env, {"GEN2_PURPOSE": "research_pass/scope", "GEN2_INPUT_DIGEST": "sha256:" + "c" * 64})
        self.assertEqual(order.command[-2:], ("scope", "/scratch/x"))
        with self.assertRaises(common.Refused):
            orders.build_order(**{**args, "bundle": bundle()})

    def test_producer_inputs_pass_the_tracked_runner_and_safely_replace_links_on_reissue(self):
        source = Path(__file__).resolve().parents[2] / "deploy/gen2/live/runner.py"
        spec = importlib.util.spec_from_file_location("tracked_runner", source)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)  # stdlib loader: deployment is outside the component import graph
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            target = root / "inputs"
            target.mkdir()
            victim = root / "unchanged"
            victim.write_bytes(b"original target")
            (target / "prompt.md").symlink_to(victim)
            os.link(victim, target / "input.json")
            before = victim.stat()
            raw = canonical.canonical_bytes(self.document())
            for attempt in range(2):
                with self.subTest(attempt=attempt):
                    # Keep old files open so inode reuse cannot hide a rewrite instead of replacement.
                    with (target / "prompt.md").open("rb") as old_prompt, (target / "input.json").open("rb") as old_input:
                        digest = orders.write_inputs(root, entry=entry(), prompt=PROMPT, document=self.document())
                        for name, old in (("prompt.md", old_prompt), ("input.json", old_input)):
                            info = (target / name).stat()
                            self.assertTrue(stat.S_ISREG(info.st_mode))
                            self.assertEqual((stat.S_IMODE(info.st_mode), info.st_nlink, info.st_uid), (0o400, 1, os.geteuid()))
                            self.assertNotEqual(info.st_ino, os.fstat(old.fileno()).st_ino)
                    fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        self.assertEqual(runner.read_file(fd, "input.json", len(raw)), raw)
                        self.assertEqual(digest, canonical.bytes_digest(raw))
                        self.assertEqual(runner.work_prompt(fd), PROMPT.decode() + "\n\nInput JSON:\n" + raw.decode())
                        with self.assertRaisesRegex(ValueError, "oversized"):
                            runner.read_file(fd, "input.json", len(raw) - 1)
                    finally:
                        os.close(fd)
                    with self.assertRaises(common.Refused):
                        orders.write_inputs(root, entry=entry(max_input_bytes=len(raw) - 1), prompt=b"changed", document=self.document())
                    self.assertEqual((target / "prompt.md").read_bytes(), PROMPT)
                    self.assertEqual((target / "input.json").read_bytes(), raw)
            self.assertEqual(victim.read_bytes(), b"original target")
            self.assertEqual((victim.stat().st_ino, victim.stat().st_mode), (before.st_ino, before.st_mode))


class JobTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        document = orders.work_input(kind="research_pass", purpose="scope", invocation_id="inv_aaaaaaaa", topic_id=TOPIC,
                                     admission=CONTRACT, entry=entry(), view={}, truncation=[])
        self.digest = orders.write_inputs(self.root, entry=entry(), prompt=PROMPT, document=document)
        self.seen = []

    def tearDown(self):
        self.tmp.cleanup()

    def agent(self, text=b'{"ok": true}', code=0):
        def run(prompt, raw_input, out):
            self.seen.append((prompt, raw_input))
            if text is not None:
                (out / "judgment.json").write_bytes(text)
            return code
        return run

    def run_job(self, agent, digest=None, validate=lambda purpose, judgment: None):
        build = lambda work, judgment: common.scaffold(work["invocation_id"], work["topic_id"], search_proposals=[judgment])
        return job.run("scope", self.root, input_digest=digest or self.digest, agent=agent, builder=build, validate=validate)

    def test_outcome_is_the_canonical_build_of_the_judgment(self):
        path = self.run_job(self.agent())
        self.assertEqual(path, self.root / "outcome.json")
        expected = common.scaffold("inv_aaaaaaaa", TOPIC, search_proposals=[{"ok": True}])
        self.assertEqual(path.read_bytes(), canonical.canonical_bytes(expected))
        self.assertEqual(self.seen[0][0], PROMPT)

    def test_each_failure_leaves_no_outcome(self):
        def invalid(purpose, judgment):
            raise common.Refused("schema")
        cases = {"digest drift": dict(agent=self.agent(), digest="sha256:" + "0" * 64),
                 "agent exit": dict(agent=self.agent(code=3)),
                 "no judgment": dict(agent=self.agent(text=None)),
                 "over cap": dict(agent=self.agent(text=b'{"x": "' + b"a" * 3000 + b'"}')),
                 "not strict json": dict(agent=self.agent(text=b'{"a": 1, "a": 2}')),
                 "schema refused": dict(agent=self.agent(), validate=invalid)}
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(common.Refused):
                self.run_job(**kwargs)
            self.assertFalse((self.root / "outcome.json").exists())
