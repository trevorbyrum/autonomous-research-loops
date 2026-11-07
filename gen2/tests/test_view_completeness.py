"""A builder reads nothing its view does not carry (Gate S #7 §7.1): so when the retained evidence changes and every label stays the
same, the view, and with it `input.json` and its digest, must change. One check for each view that names retained bytes. Oracle: the
two inputs differ in exactly the artifact reference (and what is derived from the digest), compared to the unchanged labels.
Limits: it shows the view carries the evidence's identity; the bytes themselves are the driver's to set aside and the child's to verify."""
import copy
import unittest

from gen2.app.support_gate import RouterSupport
from gen2.core import canonical
from gen2.exec import challenge, verify, views
from gen2.tests.test_exec_challenge import Exchanges as ChallengeExchanges, observation, proposal, records as challenge_records, view as challenge_view
from gen2.tests.test_exec_research import ADMISSION, exchanges, records as research_records
from gen2.tests.test_exec_verify import claim, link, records as verify_records

SAME_LABELS = {"identity": "doi:10.1/a", "abstract": "An abstract."}


def retained(extra):
    """A retained response whose record labels are fixed and whose other bytes differ."""
    return canonical.canonical_bytes({"gateway_response": {"records": [{**SAME_LABELS, **extra}]}})


def strip_refs(value):
    """The view with every artifact reference and version derived from the digest removed: what the labels alone say."""
    if isinstance(value, dict):
        return {k: strip_refs(v) for k, v in value.items() if k not in ("artifact_ref", "source_version")}
    return [strip_refs(v) for v in value] if isinstance(value, list) else value


class CompletenessTest(unittest.TestCase):
    def test_the_research_view_changes_with_the_retained_bytes_and_not_its_labels(self):
        one, two = (views.research_view(ADMISSION, research_records(), exchanges(retained(extra)), lambda ref: None, "2026-11-05T12:00:00Z", 1, [])
                    for extra in ({"title": "first"}, {"title": "second"}))
        self.assertNotEqual(one, two)
        self.assertEqual(strip_refs(one), strip_refs(two))
        self.assertNotEqual(one["works"][0]["artifact_ref"]["content_hash"], two["works"][0]["artifact_ref"]["content_hash"])

    def test_the_verify_view_changes_with_the_retained_bytes_and_not_its_labels(self):
        def made(extra):
            data = retained(extra)
            digest = canonical.bytes_digest(data)
            recs = verify_records(claim_source_links=[link(source_version=digest)], source_artifacts=[{"work_id": "wrk_aaaaaaaa", "source_version": digest}])
            return verify.verify_view(ADMISSION, recs, RouterSupport, exchanges(data), lambda ref: "A claim.", "2026-11-05T12:00:00Z", [])
        one, two = made({"title": "first"}), made({"title": "second"})
        self.assertNotEqual(one, two)
        self.assertEqual(strip_refs(one), strip_refs(two))
        self.assertNotEqual(one["claims"][0]["sources"][0]["artifact_ref"], two["claims"][0]["sources"][0]["artifact_ref"])

    def test_the_challenge_view_changes_with_the_retained_bytes_and_not_its_labels(self):
        recs = challenge_records(search_observations=[observation(1)])
        one, two = (challenge_view(recs, [proposal(1)], ChallengeExchanges(content={"call-1": data})) for data in (b"first response", b"second response"))
        self.assertNotEqual(one, two)
        refs = lambda v: v["searches"][0]["observations"][0]["artifact_ref"]
        self.assertNotEqual(refs(one), refs(two))
        for v in (one, two):
            v["searches"][0]["observations"][0].pop("artifact_ref")
            v["searches"][0]["observations"][0]["content"] = None
        self.assertEqual(one, two)
