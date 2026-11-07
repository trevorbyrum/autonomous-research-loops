"""gen2/exec/verify: which claims need a verifier, and what the verifier reads. Oracles: the router's rows (hand-built to
topic_records' shape), the retained response bytes' own digest, and judgment-verify.schema.json for the prompt's example.
Limits: the builder that turns the judgment into receipts is the next PR's; here nothing decides a verdict. The acquisition
triple is compared with literal values taken from the rows, not recomputed with the code under test."""
import base64
import json
import re
import unittest
from unittest import mock
from pathlib import Path

from gen2.core import canonical
from gen2.app.support_gate import RouterSupport
from gen2.exec import artifacts, common, verify
from gen2.router.schemas import SchemaSet
from gen2.tests import children
from gen2.tests.test_discovery_child import TOPIC, Fixture
from gen2.tests.test_exec_scope import Exchanges, lineage
from gen2.tests.test_verify_p7 import P7Test
from gen2.tests.test_exec_research import ADMISSION, RAW, exchanges

SCHEMAS = SchemaSet()
DIGEST = canonical.bytes_digest(RAW)


def claim(n=1, revision=1, **over):
    return {"claim_id": f"clm_{n:08d}", "revision": revision, "load_bearing": 1, "required_access_tier": "abstract", "status": "provisional",
            "text_ref": f"sha256:{n:064d}", "producer_invocation_id": "inv_producer01", **over}


def link(n=1, revision=1, **over):
    return {"claim_id": f"clm_{n:08d}", "claim_revision": revision, "work_id": "wrk_aaaaaaaa", "source_version": DIGEST, **over}


def records(**over):
    base = {**lineage(), "claims": [claim()], "claim_source_links": [link()], "verification_receipts": [],
            "source_artifacts": [{"work_id": "wrk_aaaaaaaa", "source_version": DIGEST}]}
    return {**base, **over}


def ids(rows):
    return [c["claim_id"] for c in rows]


class FakeSupport:
    """Stands for the router's predicate in the structural cases: these ids are the ones it accepts."""
    def __init__(self, accepted=()):
        self.accepted = set(accepted)

    def qualified(self, records):
        return lambda claim: claim["claim_id"] in self.accepted

    def nonblank(self, text):
        return RouterSupport.nonblank(text)


class SelectTest(unittest.TestCase):
    def test_table(self):
        table = [
            ("a provisional load-bearing claim with a source the router does not accept", records(), (), ["clm_00000001"]),
            ("the router's predicate accepts its support", records(), ("clm_00000001",), []),
            ("not load-bearing", records(claims=[claim(load_bearing=0)]), (), []),
            ("already accepted", records(claims=[claim(status="accepted_support")]), (), []),
            ("rejected", records(claims=[claim(status="rejected")]), (), []),
            ("no retained source link", records(claim_source_links=[]), (), []),
            ("only the latest revision is considered", records(claims=[claim(revision=1), claim(revision=2, status="rejected")], claim_source_links=[link(), link(revision=2)]), (), []),
            ("two claims, one accepted", records(claims=[claim(1), claim(2)], claim_source_links=[link(1), link(2)]), ("clm_00000002",), ["clm_00000001"]),
        ]
        for name, recs, accepted, expected in table:
            with self.subTest(name):
                self.assertEqual(ids(verify.select(recs, FakeSupport(accepted))), expected)


class AuthorityTest(Fixture, unittest.TestCase):
    """Exclusion is `support.require_support`'s answer, over real retained operands (the P7 witness's), never a label check."""

    def world(self):
        rows, acquisition, claim_row = P7Test.operands(self, "retained")
        tables = {name: list(rows.tables.get(name, [])) for name in ("source_acquisitions", "search_observations", "source_artifacts", "verification_receipts", "detailed_check_records")}
        claim_row = {**claim_row, "status": "provisional", "text_ref": "sha256:" + "0" * 64, "producer_invocation_id": "inv_producer01"}
        tables.update(claims=[claim_row], claim_source_links=[{"claim_id": claim_row["claim_id"], "claim_revision": 1, "work_id": "wrk_abstract01", "source_version": "v1"}], quote_checks=[])
        return tables

    def chosen(self, tables):
        return ids(verify.select(tables, RouterSupport))

    def encoded(self, tables):
        return {**tables, "source_acquisitions": [{**row, "response_bytes": {"encoding": "base64", "data": base64.b64encode(row["response_bytes"]).decode()}} for row in tables["source_acquisitions"]]}

    def test_genuinely_qualified_support_is_excluded_even_in_topic_records_encoding(self):
        tables = self.world()
        self.assertEqual(self.chosen(tables), [])
        self.assertEqual(self.chosen(self.encoded(tables)), [])

    def test_support_the_router_would_refuse_leaves_the_claim_selected(self):
        quarantined = {"check_id": "qck_00000001", "claim_id": "clm_abstract01", "claim_revision": 1, "topic_id": TOPIC, "quote_quarantined": True,
                       "exact_match": "mismatch", "match_result": {"artifact_hash": "sha256:" + "0" * 64}}
        cases = {"no detailed-check rows (historical, unbound)": lambda t: t.update(detailed_check_records=[]),
                 "a quarantined capture": lambda t: t.update(quote_checks=[quarantined]),
                 "no acquisition behind the receipt": lambda t: t.update(source_acquisitions=[]),
                 "the receipt names a hash the acquisition lacks": lambda t: t.update(verification_receipts=[{**t["verification_receipts"][0], "obtained_content_hash": "sha256:" + "0" * 64}]),
                 "a receipt below the required tier": lambda t: t.update(verification_receipts=[{**t["verification_receipts"][0], "access_tier": "bibliographic"}]),
                 "an operand family missing altogether": lambda t: t.pop("detailed_check_records")}
        for name, edit in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                tables = self.world()
                self.assertEqual(self.chosen(tables), [], "control: the unedited world qualifies")
                edit(tables)
                self.assertEqual(self.chosen(tables), ["clm_abstract01"])


def view(recs=None, ex=None, notes=None):
    return verify.verify_view(ADMISSION, recs or records(), RouterSupport, ex or exchanges(), lambda ref: "A claim.", "2026-11-05T12:00:00Z", [] if notes is None else notes)


class ViewTest(unittest.TestCase):
    def test_the_verifier_reads_the_retained_text_and_the_triple_comes_from_retained_rows(self):
        (item,) = view()["claims"]
        self.assertEqual((item["claim_ref"], item["tier"], item["text"]), ("clm_00000001", "abstract", "A claim."))
        (source,) = item["sources"]
        self.assertEqual(source, {"work_id": "wrk_aaaaaaaa", "source_version": DIGEST, "content_hash": DIGEST, "identity": "doi:10.1/a", "content_tier": "abstract", "content": "An abstract.",
                                  "acquisition": {"gateway_call_ref": "call-1", "retrieved_at": "2026-11-05T11:00:00Z", "route": "gateway:semanticscholar"}})

    def test_a_response_without_a_usable_abstract_is_labelled_bibliographic_with_no_content(self):
        for name, body in (("missing", {"records": [{"identity": "doi:10.1/a"}]}), ("blank", {"records": [{"identity": "doi:10.1/a", "abstract": " \t"}]}),
                           ("invisible only (the router's rule, not str.strip)", {"records": [{"identity": "doi:10.1/a", "abstract": "\u200b\u200b"}]})):
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
            verify.verify_view({"context": "pre-contract/1"}, records(), RouterSupport, exchanges(), lambda ref: None, "2026-11-05T12:00:00Z", [])

    def test_one_pass_is_capped_at_one_commits_receipts_and_the_cut_is_recorded(self):
        n = verify.RECEIPT_CAP + 3
        recs = records(claims=[claim(i) for i in range(1, n + 1)], claim_source_links=[link(i) for i in range(1, n + 1)])
        notes: list = []
        self.assertEqual(len(view(recs, notes=notes)["claims"]), verify.RECEIPT_CAP)
        self.assertEqual(notes, [{"family": "claims", "kept": verify.RECEIPT_CAP, "total": n}])
        self.assertEqual(verify.RECEIPT_CAP * 4, 64, "four detailed checks per receipt against one commit's 64")

    def test_a_claim_resting_on_more_sources_than_one_commit_carries_is_refused_not_silently_empty(self):
        ref = {"content_hash": DIGEST, "size_bytes": len(RAW), "media_type": "application/json"}
        recs = records(record_work_links=[{"event_id": "e1", "work_id": "wrk_aaaaaaaa"}, {"event_id": "e2", "work_id": "wrk_bbbbbbbb"}],
                       claim_source_links=[link(), link(work_id="wrk_bbbbbbbb")],
                       source_artifacts=[{"work_id": "wrk_aaaaaaaa", "source_version": DIGEST}, {"work_id": "wrk_bbbbbbbb", "source_version": DIGEST}])
        both = Exchanges({"call-1": (ref, RAW), "call-2": (ref, RAW)})
        self.assertEqual(len(view(recs, both)["claims"][0]["sources"]), 2, "control: two sources fit the real cap")
        with mock.patch.object(verify, "RECEIPT_CAP", 1), self.assertRaisesRegex(common.Refused, "needs a split"):
            view(recs, both)

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
