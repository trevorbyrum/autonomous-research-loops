"""The executor child and the evidence helper (T17 PR3a). Oracles: exec.job.run's own digest and judgment checks, the judgment and
outcome schemas (SchemaSet), and hashlib for the evidence names. Limits: builders and the agent are stubs (the real kits and T18's
fixture agent are other PRs'); that the supervisor stages what the child sets aside is witnessed in test_supervisor_evidence.
"""
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from gen2.app import child
from gen2.core import canonical
from gen2.exec import common, orders
from gen2.router.schemas import SchemaSet
from gen2.tests import children

TOPIC = "fleet:topic"
ENTRY = {"max_input_bytes": 65536, "max_output_bytes": 65536}
REVIEW = json.loads(Path(children.path("gen2/schema/examples/judgment-review/valid-example.json")).read_text())["instance"]


def inputs(directory: Path, kind: str, purpose: str) -> dict:
    document = orders.work_input(kind=kind, purpose=purpose, invocation_id="inv_aaaaaaaa", topic_id=TOPIC, admission={"context": "contract/1"},
                                 entry=ENTRY, view={}, truncation=[])
    digest = orders.write_inputs(directory, entry=ENTRY, prompt=b"prompt", document=document)
    return {"GEN2_PURPOSE": f"{kind}/{purpose}", "GEN2_INPUT_DIGEST": digest}


def review_factory(stage):
    def build(work, judgment):
        ref = stage(canonical.canonical_bytes(judgment), "application/json")
        return {**common.scaffold(work["invocation_id"], work["topic_id"]), "probe": ref}   # not an outcome section: only the staged ref is under test
    return build


def empty_factory(stage):
    return lambda work, judgment: common.scaffold(work["invocation_id"], work["topic_id"])


def agent_writing(judgment):
    def agent(prompt, raw_input, out):
        (out / "judgment.json").write_bytes(canonical.canonical_bytes(judgment))
        return 0
    return agent


class ChildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_evidence_is_set_aside_under_its_own_digest_and_nothing_else_is_accepted(self):
        stage = child.evidence_stage(self.dir)
        data = b'{"a": 1}'
        ref = stage(data, "application/json")
        name = f"evidence-{hashlib.sha256(data).hexdigest()}.json"
        self.assertEqual((ref, (self.dir / name).read_bytes()), ({"content_hash": "sha256:" + hashlib.sha256(data).hexdigest(), "size_bytes": 8, "media_type": "application/json"}, data))
        self.assertEqual(stage(data, "application/json"), ref)   # staging the same bytes again is a no-op
        with self.assertRaises(common.Refused):
            stage(data, "text/plain")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [name])

    def test_a_model_purpose_runs_the_agent_validates_and_writes_outcome_and_evidence_in_one_directory(self):
        env = inputs(self.dir, "checkpoint", "review")
        path = child.run(env["GEN2_PURPOSE"], self.dir, input_digest=env["GEN2_INPUT_DIGEST"], table={"checkpoint/review": review_factory}, agent=agent_writing(REVIEW))
        self.assertEqual(path, self.dir / "outcome.json")
        outcome = json.loads(path.read_text())
        cited = outcome["probe"]["content_hash"]
        self.assertTrue((self.dir / f"evidence-{cited.removeprefix('sha256:')}.json").is_file())   # beside outcome.json: the supervisor's one collection point

    def test_a_judgment_that_does_not_fit_its_schema_writes_no_outcome(self):
        env = inputs(self.dir, "checkpoint", "review")
        with self.assertRaises(common.Refused):
            child.run(env["GEN2_PURPOSE"], self.dir, input_digest=env["GEN2_INPUT_DIGEST"], table={"checkpoint/review": review_factory},
                      agent=agent_writing({**REVIEW, "outcome": "approved"}))
        self.assertFalse((self.dir / "outcome.json").exists())

    def test_a_model_purpose_without_an_agent_refuses_because_the_live_runner_entrance_is_closed(self):
        env = inputs(self.dir, "checkpoint", "review")
        with self.assertRaisesRegex(common.Refused, "live runner entrance is closed"):
            child.run(env["GEN2_PURPOSE"], self.dir, input_digest=env["GEN2_INPUT_DIGEST"], table={"checkpoint/review": review_factory})
        self.assertFalse((self.dir / "outcome.json").exists())

    def test_the_code_only_dossier_purpose_needs_no_agent_and_writes_an_empty_outcome(self):
        env = inputs(self.dir, "checkpoint", "dossier")
        path = child.run("checkpoint/dossier", self.dir, input_digest=env["GEN2_INPUT_DIGEST"], table={"checkpoint/dossier": empty_factory})
        self.assertEqual(SchemaSet().errors(json.loads(path.read_text()), "outcome-document.schema.json"), [])

    def test_a_purpose_with_no_builder_and_a_tampered_input_both_refuse(self):
        env = inputs(self.dir, "checkpoint", "dossier")
        with self.assertRaisesRegex(common.Refused, "no builder is installed"):
            child.run("checkpoint/dossier", self.dir, input_digest=env["GEN2_INPUT_DIGEST"], table={})
        (self.dir / "inputs" / "input.json").write_bytes(b"{}")
        with self.assertRaisesRegex(common.Refused, "does not match the order's digest"):
            child.run("checkpoint/dossier", self.dir, input_digest=env["GEN2_INPUT_DIGEST"], table={"checkpoint/dossier": empty_factory})

    def test_main_returns_zero_on_success_and_two_with_a_named_reason_on_refusal(self):
        env = inputs(self.dir, "checkpoint", "dossier")
        self.assertEqual(child.main([str(self.dir)], env=env, table={"checkpoint/dossier": empty_factory}), 0)
        for case, argv, environment in (("no directory", [], env), ("no purpose in the environment", [str(self.dir)], {}), ("no agent", [str(self.dir)], {**env, "GEN2_PURPOSE": "checkpoint/review"})):
            with self.subTest(case), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(child.main(argv, env=environment, table={"checkpoint/review": review_factory}), 2)
                self.assertIn("gen2.app.child:", err.getvalue())
