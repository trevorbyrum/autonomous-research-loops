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


def review_factory(stage, bytes_of):
    def build(work, judgment):
        ref = stage(canonical.canonical_bytes(judgment), "application/json")
        return {**common.scaffold(work["invocation_id"], work["topic_id"]), "probe": ref}   # not an outcome section: only the staged ref is under test
    return build


def empty_factory(stage, bytes_of):
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
            stage(data, "image/png")                  # only the forms core.evidence_media names
        text = stage("claim text".encode(), "text/plain")
        self.assertEqual((text["media_type"], (self.dir / f"evidence-{hashlib.sha256(b'claim text').hexdigest()}.txt").read_bytes()), ("text/plain", b"claim text"))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), sorted([name, f"evidence-{hashlib.sha256(b'claim text').hexdigest()}.txt"]))   # nothing written for the refused one

    def test_bytes_of_reads_only_digest_checked_evidence_files(self):
        stage, read = child.evidence_stage(self.dir), child.bytes_of(self.dir)
        ref = stage(b'{"a": 1}', "application/json")
        text = stage(b"words", "text/plain")
        self.assertEqual((read(ref["content_hash"]), read(text["content_hash"])), (b'{"a": 1}', b"words"))
        with self.assertRaises(common.Refused):
            read("sha256:" + "0" * 64)                                # nothing was set aside for it
        (self.dir / f"evidence-{ref['content_hash'].removeprefix('sha256:')}.json").write_bytes(b"tampered")
        with self.assertRaises(common.Refused):
            read(ref["content_hash"])                                 # the name is a claim the bytes must meet

    def verify_case(self, stage):
        """A claim whose cited quote is in a retained response the parent set aside: the builder must USE `stage` and `bytes_of` correctly."""
        response = canonical.canonical_bytes({"lanes": [{"source": "semanticscholar"}], "records": [{"identity": "doi:10.1/x", "abstract": "an abstract"}]})
        ref = stage(response, "application/json")
        source = {"work_id": "wrk_00000001", "source_version": ref["content_hash"], "content_hash": ref["content_hash"], "identity": "doi:10.1/x", "content_tier": "abstract",
                  "content": "an abstract", "artifact_ref": ref, "acquired_by": "inv_capture1",
                  "acquisition": {"gateway_call_ref": "call-1", "retrieved_at": "2026-11-08T09:00:00Z", "route": "gateway:semanticscholar"}}
        claim = {"claim_ref": "clm_00000001", "revision": 1, "tier": "abstract", "producer": "inv_producer1", "text": "t", "sources": [source]}
        checks = {kind: {"outcome": "not_applicable", "note": "nothing to check"} for kind in ("numeric_units", "denominators", "negation", "qualifications")}
        return ({"as_of": "2026-11-08T09:00:00Z", "claims": [claim]},
                {"items": [{"claim_ref": "clm_00000001", "verdict": "supports", "cited_spans": [{"quote": "an abstract", "locator": "abstract"}], "checks": checks}]})

    def test_the_default_table_builds_and_runs_every_purposes_pure_builder_on_a_minimal_input(self):
        """Production path: the child's own table, `stage` and `bytes_of`, each builder INVOKED (a swapped argument fails here, not in review)."""
        from gen2.app import factories
        self.assertEqual(set(factories.TABLE), set(child.JUDGMENT) | set(child.CODE_ONLY))
        stage, read = child.evidence_stage(self.dir), child.bytes_of(self.dir)
        pin = {"revision": 1, "content_hash": "sha256:" + "a" * 64}
        contract = {**pin, "framing_version": 1, "eligibility_protocol": {"protocol_version": 1}}
        dossier = {"revision": 1, "content_hash": "sha256:" + "d" * 64, "contract_revision": 1}
        cases = {
            "research_pass/scope": ({}, {"search_proposals": [{"proposal_id": "p1"}]}),
            "research_pass/research": ({"contract": contract, "works": []}, {"claims": [], "screening": [], "obligations": [], "triggers": [],
                                                                            "search_proposals": [], "next_queue_state": None}),
            "verification/verify": self.verify_case(stage),
            "checkpoint/challenge": ({"pass": 1, "claims": [], "adverse_receipts": [], "contradictions": [], "searches": [], "review_episodes": []},
                                     {"counterevidence": [], "explanations": [], "adjudications": [], "promotions": [], "search_proposals": []}),
            "checkpoint/review": ({"dossier": dossier}, {"outcome": "sufficient", "summary": "ok"}),
            "checkpoint/dossier": ({}, {}),
        }
        for key, (view, judgment) in cases.items():
            with self.subTest(key):
                work = {"invocation_id": "inv_aaaaaaaa", "topic_id": TOPIC, "admission": {"context": "contract/1", "contract": pin}, "view": view}
                outcome = factories.TABLE[key](stage, read)(work, judgment)
                self.assertEqual((outcome["invocation_id"], outcome["topic_id"]), ("inv_aaaaaaaa", TOPIC))
                if key == "verification/verify":   # the supervisor fills the verifier's own capability id before staging (#141); model that here
                    outcome = {**outcome, "verification_receipts": [{**r, "verifier_capability_id": "cap_" + "0" * 32} for r in outcome["verification_receipts"]]}
                    self.assertEqual(len(outcome["verification_receipts"]), 1)
                if key != "research_pass/scope":   # the scope case carries a bare proposal, which the schema rightly refuses
                    self.assertEqual(SchemaSet().errors(outcome, "outcome-document.schema.json"), [], key)

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
        tampered = self.dir / "inputs" / "input.json"
        tampered.chmod(0o600)  # the producer writes inputs 0400; a same-UID tamperer can still chmod
        tampered.write_bytes(b"{}")
        with self.assertRaisesRegex(common.Refused, "does not match the order's digest"):
            child.run("checkpoint/dossier", self.dir, input_digest=env["GEN2_INPUT_DIGEST"], table={"checkpoint/dossier": empty_factory})

    def test_main_returns_zero_on_success_and_two_with_a_named_reason_on_refusal(self):
        env = inputs(self.dir, "checkpoint", "dossier")
        self.assertEqual(child.main([str(self.dir)], env=env, table={"checkpoint/dossier": empty_factory}), 0)
        for case, argv, environment in (("no directory", [], env), ("no purpose in the environment", [str(self.dir)], {}), ("no agent", [str(self.dir)], {**env, "GEN2_PURPOSE": "checkpoint/review"})):
            with self.subTest(case), redirect_stderr(io.StringIO()) as err:
                self.assertEqual(child.main(argv, env=environment, table={"checkpoint/review": review_factory}), 2)
                self.assertIn("gen2.app.child:", err.getvalue())
