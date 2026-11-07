"""gen2/exec/verify: which claims need a verifier, and what the verifier reads. Oracles: the router's rows (hand-built to
topic_records' shape), the retained response bytes' own digest, and judgment-verify.schema.json for the prompt's example.
Limits: the builder that turns the judgment into receipts is the next PR's; here nothing decides a verdict. The acquisition
triple is compared with literal values taken from the rows, not recomputed with the code under test."""
import json
import re
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.exec import artifacts, common, verify
from gen2.router.schemas import SchemaSet
from gen2.tests import children
from gen2.tests.test_exec_scope import Exchanges, lineage, staged
from gen2.tests.test_exec_research import ADMISSION, RAW, exchanges

SCHEMAS = SchemaSet()
DIGEST = canonical.bytes_digest(RAW)


def claim(n=1, revision=1, **over):
    return {"claim_id": f"clm_{n:08d}", "revision": revision, "load_bearing": 1, "required_access_tier": "abstract", "status": "provisional",
            "text_ref": f"sha256:{n:064d}", "producer_invocation_id": "inv_producer01", **over}


def link(n=1, revision=1, **over):
    return {"claim_id": f"clm_{n:08d}", "claim_revision": revision, "work_id": "wrk_aaaaaaaa", "source_version": DIGEST, **over}


def receipt(n=1, revision=1, **over):
    return {"claim_id": f"clm_{n:08d}", "claim_revision": revision, "verdict": "supports", "use": "load_bearing", "required_access_tier": "abstract",
            "access_tier": "abstract", **over}


def records(**over):
    base = {**lineage(), "claims": [claim()], "claim_source_links": [link()], "verification_receipts": [],
            "source_artifacts": [{"work_id": "wrk_aaaaaaaa", "source_version": DIGEST}]}
    return {**base, **over}


def ids(rows):
    return [c["claim_id"] for c in rows]


class SelectTest(unittest.TestCase):
    def test_table(self):
        table = [
            ("a provisional load-bearing claim with a source and no receipt", records(), ["clm_00000001"]),
            ("not load-bearing", records(claims=[claim(load_bearing=0)]), []),
            ("already accepted", records(claims=[claim(status="accepted_support")]), []),
            ("rejected", records(claims=[claim(status="rejected")]), []),
            ("no retained source link", records(claim_source_links=[]), []),
            ("a qualifying receipt exists", records(verification_receipts=[receipt()]), []),
            ("a receipt that does not support", records(verification_receipts=[receipt(verdict="does_not_support")]), ["clm_00000001"]),
            ("a receipt at a lower tier than required", records(claims=[claim(required_access_tier="full_text")], verification_receipts=[receipt(required_access_tier="full_text", access_tier="abstract")]), ["clm_00000001"]),
            ("a sampled receipt", records(verification_receipts=[receipt(use="sampled")]), ["clm_00000001"]),
            ("a receipt for another revision", records(claims=[claim(revision=2)], claim_source_links=[link(revision=2)], verification_receipts=[receipt(revision=1)]), ["clm_00000001"]),
            ("only the latest revision is considered", records(claims=[claim(revision=1), claim(revision=2, status="rejected")], claim_source_links=[link(), link(revision=2)]), []),
        ]
        for name, recs, expected in table:
            with self.subTest(name):
                self.assertEqual(ids(verify.select(recs)), expected)


def view(recs=None, ex=None, notes=None):
    return verify.verify_view(ADMISSION, recs or records(), ex or exchanges(), lambda ref: "A claim.", "2026-11-05T12:00:00Z", [] if notes is None else notes)


class ViewTest(unittest.TestCase):
    def test_the_verifier_reads_the_retained_text_and_the_triple_comes_from_retained_rows(self):
        (item,) = view()["claims"]
        self.assertEqual((item["claim_ref"], item["tier"], item["text"]), ("clm_00000001", "abstract", "A claim."))
        (source,) = item["sources"]
        self.assertEqual(source, {"work_id": "wrk_aaaaaaaa", "source_version": DIGEST, "identity": "doi:10.1/a", "content_tier": "abstract", "content": "An abstract.",
                                  "acquisition": {"gateway_call_ref": "call-1", "retrieved_at": "2026-11-05T11:00:00Z", "route": "gateway:semanticscholar"}})

    def test_a_response_without_a_usable_abstract_is_labelled_bibliographic_with_no_content(self):
        for name, body in (("missing", {"records": [{"identity": "doi:10.1/a"}]}), ("blank", {"records": [{"identity": "doi:10.1/a", "abstract": " \t"}]})):
            with self.subTest(name):
                data = canonical.canonical_bytes({"gateway_response": body})
                recs = records(claim_source_links=[link(source_version=canonical.bytes_digest(data))], source_artifacts=[{"work_id": "wrk_aaaaaaaa", "source_version": canonical.bytes_digest(data)}])
                (source,) = view(recs, exchanges(data))["claims"][0]["sources"]
                self.assertEqual((source["content_tier"], source["content"]), ("bibliographic", None))

    def test_the_route_follows_the_lane_of_the_retrieval_not_anything_else(self):
        recs = records(search_observations=[{**o, "lane": "crossref"} for o in lineage()["search_observations"]])
        self.assertEqual(view(recs)["claims"][0]["sources"][0]["acquisition"]["route"], "gateway:crossref")

    def test_what_has_nothing_to_check_against_is_left_out_and_what_disagrees_is_refused(self):
        self.assertEqual(view(records(source_artifacts=[]))["claims"], [])
        self.assertEqual(view(records(), ex=exchanges())["claims"][0]["sources"][0]["source_version"], DIGEST)
        other = canonical.canonical_bytes({"gateway_response": {"records": [{"identity": "doi:10.1/a", "abstract": "Another."}]}})
        with self.assertRaises(common.Refused):
            view(ex=exchanges(other))   # the retained response is not the version the link names
        with self.assertRaises(common.Refused):
            verify.verify_view({"context": "pre-contract/1"}, records(), exchanges(), lambda ref: None, "2026-11-05T12:00:00Z", [])

    def test_one_pass_is_capped_and_the_cut_is_recorded(self):
        n = verify.CLAIM_CAP + 3
        recs = records(claims=[claim(i) for i in range(1, n + 1)], claim_source_links=[link(i) for i in range(1, n + 1)])
        notes: list = []
        self.assertEqual(len(view(recs, notes=notes)["claims"]), verify.CLAIM_CAP)
        self.assertEqual(notes, [{"family": "claims", "kept": verify.CLAIM_CAP, "total": n}])

    def test_the_retained_lineage_now_names_its_call_event_and_instant(self):
        found = artifacts.retained("wrk_aaaaaaaa", records(), exchanges())
        self.assertEqual((found.event_id, found.observation_id, found.gateway_call_ref, found.captured_at), ("e1", "obs_00000001", "call-1", "2026-11-05T11:00:00Z"))


class PromptTest(unittest.TestCase):
    path = Path(children.path("gen2/prompts/verification.verify.md"))

    def test_its_example_is_a_valid_judgment_and_it_names_every_verdict_and_outcome(self):
        text = self.path.read_text()
        example = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
        self.assertEqual(SCHEMAS.errors(example, "judgment-verify.schema.json"), [])
        for word in ("supports", "partially_supports", "does_not_support", "cannot_assess_at_required_tier", "succeeded", "failed", "not_applicable", "not_checked"):
            self.assertIn(f"`{word}`", text)
