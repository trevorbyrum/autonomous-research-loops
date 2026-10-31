"""6b2' PR 2: the three completion gates, sentinel bytes and profile selection.

Pure gate functions take hand-written operands; a few worlds show the wiring
through the real Router. Each refusal has a fragment unique to its rule.
"""
import json
import unittest
from dataclasses import replace

from gen2 import accounting as a
from gen2.accounting import stopping as s
from gen2.core import canonical
from gen2.router import gates
from gen2.router.boundary import Refusal
from gen2.tests import router_fixtures as rf
from gen2.tests.test_completion_records import World
from gen2.tests.test_coverage_dependencies import history, page

S, N, U = "satisfied", "not_satisfied", "unknown"
NOW = "2026-09-27T10:00:00Z"
REF = {"content_hash": rf.h("a"), "size_bytes": 10, "media_type": "application/json"}


def claim(cid="c1", revision=1, status="accepted_support"):
    return {"claim_id": cid, "revision": revision, "status": status}


def receipt(rid="ver_1", cid="c1", revision=1, verdict="does_not_support"):
    return {"verification_receipt_id": rid, "claim_id": cid, "claim_revision": revision, "verdict": verdict}


def adjudication(rid="ver_1", revision=1, ref=REF):
    return {"subject_ref": rid, "subject_revision": revision, "evidence_refs": [ref]}


def disposition(did="rdp_1", state="unresolved", revision=1, supersedes=None, registry_id="C-1"):
    return a.RegistryDisposition(did, "contradiction", registry_id, "subject", state, revision, 1, 1, supersedes, "reason", (), "primary", "inv_1", "op_1", NOW)


def completion(kind, subject, revision=None, outcome="none_found", pin=1, ref=REF):
    return {"kind": kind, "subject_ref": subject, "subject_revision": revision, "contract_revision": pin,
            "assessment": {"outcome": outcome, "summary": "s"}, "evidence_refs": [ref]}


def standing(revision):
    return {1: "current", 2: "compatible", 3: "stale"}.get(revision, "unknown")


class VerificationTest(unittest.TestCase):
    def state(self, required, receipts=(), adjudications=(), supported=True):
        return gates.verification_state(required, list(receipts), list(adjudications), lambda c: supported)[0]

    def test_literal_states(self):
        self.assertEqual(self.state([claim()]), S)
        self.assertEqual(self.state([claim()], supported=False), N)
        self.assertEqual(self.state([claim()], [receipt()]), U)
        self.assertEqual(self.state([]), U)

    def test_unresolved_adverse_receipt_gates_everything_before_combining(self):
        two = [claim("c1"), claim("c2")]
        unsupported = lambda c: c["claim_id"] == "c1"  # noqa: E731
        self.assertEqual(gates.verification_state(two, [receipt(cid="c1")], [], unsupported)[0], U)  # c2 alone would be not_satisfied
        self.assertEqual(gates.verification_state(two, [], [], unsupported)[0], N)  # control: no adverse receipt
        both = [receipt("ver_1", "c1"), receipt("ver_2", "c2", verdict="partially_supports")]
        self.assertEqual(self.state(two, both, [adjudication("ver_1")]), U)
        self.assertEqual(self.state(two, both, [adjudication("ver_1"), adjudication("ver_2")]), S)

    def test_an_adjudication_must_name_the_receipts_claim_revision(self):
        self.assertEqual(self.state([claim()], [receipt()], [adjudication(revision=2)]), U)
        self.assertEqual(self.state([claim()], [receipt()], [adjudication()]), S)

    def test_an_adjudication_never_supplies_missing_support(self):
        self.assertEqual(self.state([claim()], [receipt()], [adjudication()], supported=False), N)

    def test_only_accepted_support_claims_count(self):
        for status in ("contested", "quarantined", "provisional"):
            self.assertEqual(self.state([claim(status=status)]), N, status)
        self.assertEqual(self.state([claim(status="accepted_support")]), S)

    def test_only_required_claims_have_adverse_receipts_considered(self):
        self.assertEqual(self.state([claim("c1")], [receipt(cid="other")]), S)

    def test_relied_adjudications_are_the_ones_resolving_adverse_receipts(self):
        _, relied = gates.verification_state([claim()], [receipt()], [adjudication(), adjudication("ver_9")], lambda c: True)
        self.assertEqual([r["subject_ref"] for r in relied], ["ver_1"])

    def test_counting_requires_performed_work_under_usable_standing(self):
        for outcome, pin, expected in (("verdict_upheld", 1, True), ("verdict_upheld", 2, True), ("verdict_upheld", 3, False), ("verdict_upheld", 9, False), ("incomplete", 1, False)):
            record = completion("verification_adjudication", "ver_1", 1, outcome, pin)
            self.assertEqual(gates._counts(record, standing), expected, (outcome, pin))


class ChallengeTest(unittest.TestCase):
    def state(self, required, contradictions=(), records=()):
        return gates.challenge_state(required, tuple(contradictions), list(records), standing)

    def counter(self, outcome="none_found", pin=1, cid="c1"):
        return completion("counterevidence_search", cid, 1, outcome, pin)

    def compete(self, did="rdp_1", outcome="explanation_rejected", pin=1):
        return completion("competing_explanation", did, None, outcome, pin)

    def test_claims_need_a_counting_record(self):
        self.assertEqual(self.state([claim()], records=[self.counter()])[0], S)
        self.assertEqual(self.state([claim()])[0], N)
        self.assertEqual(self.state([claim()], records=[self.counter("incomplete")])[0], U)
        self.assertEqual(self.state([claim()], records=[self.counter(pin=3)])[0], U)  # stale standing is not performed work
        self.assertEqual(self.state([claim()], records=[self.counter("counterevidence_found")])[0], S)  # performed, not a survival finding
        self.assertEqual(self.state([claim()], records=[self.counter(), self.counter("incomplete")])[0], U)  # the newest record is current
        self.assertEqual(self.state([claim()], records=[self.counter("incomplete"), self.counter()])[0], S)

    def test_empty_required_set_is_unknown(self):
        self.assertEqual(self.state([])[0], U)

    def test_an_open_contradiction_needs_its_own_record(self):
        self.assertEqual(self.state([], [disposition()], [self.compete()])[0], S)
        self.assertEqual(self.state([], [disposition()])[0], N)
        self.assertEqual(self.state([], [disposition()], [self.compete("rdp_other")])[0], N)
        self.assertEqual(self.state([], [disposition()], [self.compete(outcome="incomplete")])[0], U)

    def test_resolved_contradictions_require_nothing_but_unusable_standing_is_unknown(self):
        self.assertEqual(self.state([claim()], [disposition(state="resolved")], [self.counter()])[0], S)
        self.assertEqual(self.state([claim()], [disposition(state="resolved", revision=9)], [self.counter()])[0], U)
        self.assertEqual(self.state([claim()], [disposition(revision=9)], [self.counter(), self.compete()])[0], U)

    def test_unusable_standing_does_not_hide_a_definite_missing_record(self):
        self.assertEqual(self.state([claim()], [disposition(revision=9)])[0], N)

    def test_unrelated_resolved_row_does_not_close_an_unresolved_one(self):
        rows = a.active_records((disposition("rdp_1", "unresolved"), disposition("rdp_2", "resolved")))
        self.assertEqual([r.disposition_id for r in rows], ["rdp_1", "rdp_2"])
        self.assertEqual(self.state([], rows)[0], N)
        self.assertEqual(self.state([], rows, [self.compete("rdp_1")])[0], S)

    def test_explicit_supersession_closes_and_competing_successors_both_stay(self):
        closed = a.active_records((disposition("rdp_1", "unresolved"), disposition("rdp_2", "resolved", supersedes="rdp_1")))
        self.assertEqual(self.state([], closed)[0], U)  # nothing required: unknown by the empty rule
        self.assertEqual(self.state([claim()], closed, [self.counter()])[0], S)
        competing = a.active_records((disposition("rdp_1", "unresolved"), disposition("rdp_2", "unresolved", supersedes="rdp_1"), disposition("rdp_3", "contested", supersedes="rdp_1")))
        self.assertEqual([r.disposition_id for r in competing], ["rdp_2", "rdp_3"])
        self.assertEqual(self.state([], competing, [self.compete("rdp_2")])[0], N)
        self.assertEqual(self.state([], competing, [self.compete("rdp_2"), self.compete("rdp_3")])[0], S)

    def test_relied_records_are_the_current_counting_ones(self):
        state, relied = self.state([claim()], records=[self.counter()])
        self.assertEqual((state, [r["subject_ref"] for r in relied]), (S, ["c1"]))
        self.assertEqual(self.state([claim()], records=[self.counter("incomplete")])[1], [])


class CoverageTest(unittest.TestCase):
    def test_defects_are_unknown_never_not_satisfied(self):
        self.assertEqual(gates.coverage_state(history((), ())), S)
        self.assertEqual(gates.coverage_state(replace(history((), ()), history="legacy_unknown")), U)
        self.assertEqual(gates.coverage_state(history(("p0",), ())), U)  # invocation capture missing
        self.assertEqual(gates.coverage_state(history(("p0",), (page("p0", "q"),))), S)
        self.assertEqual(gates.coverage_state(history(("p0",), (replace(page("p0", "q"), completeness="partial"),))), U)

    def test_any_indeterminate_window_counts_even_beyond_a_rules_scope(self):
        inventory = history(("p0", "p1"), (page("p0", "q"), page("p1", "q", end="end_unknown")))
        self.assertIsNone(a.candidate_units(inventory).retrieved_records.unknown_reason)
        self.assertEqual(gates.coverage_state(inventory), U)


class EvidenceTest(unittest.TestCase):
    def test_references_are_deduplicated_and_hash_sorted(self):
        other = {**REF, "content_hash": rf.h("0")}
        refs = gates._refs([{"evidence_refs": [REF, other]}, {"evidence_refs": [REF]}])
        self.assertEqual([r.content_hash for r in refs], [rf.h("0"), rf.h("a")])


class SentinelTest(rf.RouterTestCase):
    def binding(self, raw, media="application/json", **ref):
        reference = {"content_hash": self.spool.put(raw, media_type=media), "size_bytes": len(raw), "media_type": "application/json", **ref}
        rule = {"rule_id": "R", "family": "known_item", "evaluation": "automatic", "params": {"sentinel_set": reference, "tests": "retrieval", "seeded_into_prompts": False}}
        return s.bind_rule(rule)

    def read(self, binding):
        return gates._sentinels(binding, self.spool, rf.TOPIC)

    def refuses(self, binding, reason, fragment):
        with self.assertRaises(Refusal) as caught:
            self.read(binding)
        self.assertEqual(caught.exception.reason, reason)
        self.assertIn(fragment, caught.exception.detail)

    def test_valid_sets_including_noncanonical_whitespace_and_empty(self):
        for raw, ids in ((b'["w1","w2"]', {"w1", "w2"}), (b' [ "w1" ] ', {"w1"}), (b"[]", set())):
            self.assertEqual(self.read(self.binding(raw)).work_ids, frozenset(ids), raw)

    def test_typed_refusals_each_with_its_own_fragment(self):
        self.refuses(self.binding(b'{"w": 1}'), "payload_invalid", "sentinel set is not an array")
        self.refuses(self.binding(b'["w1", 7]'), "payload_invalid", "non-string or empty work id")
        self.refuses(self.binding(b'["w1", ""]'), "payload_invalid", "non-string or empty work id")
        self.refuses(self.binding(b'["w1", "w1"]'), "payload_invalid", "duplicate work ids")
        self.refuses(self.binding(b'["w1",'), "payload_invalid", "not canonical JSON")
        self.refuses(self.binding(b'{"a":1,"a":2}'), "payload_invalid", "not canonical JSON")
        self.refuses(self.binding(b'["w1"]', media="text/plain"), "payload_invalid", "staged as text/plain")
        self.refuses(self.binding(b'["w1"]', size_bytes=99), "payload_digest_mismatch", "declared")
        self.refuses(self.binding(b'["w1"]', content_hash=rf.h("9")), "payload_missing", "nothing is staged")

    def test_bytes_that_do_not_hash_to_their_label_are_refused(self):
        binding = self.binding(b'["w1"]')
        self.spool.put(b'["w2"]', label=binding.params["sentinel_set"]["content_hash"])  # other bytes of the same length
        self.refuses(binding, "payload_digest_mismatch", "hash to")

    def test_only_known_item_rules_read_the_spool(self):
        descriptive = s.bind_rule({"rule_id": "D", "family": "descriptive", "evaluation": "automatic", "params": {}})
        self.assertIsNone(self.read(descriptive))

    def test_a_parsed_empty_array_keeps_the_rule_unknown(self):
        declared = self.read(self.binding(b"[]"))
        self.assertEqual(s.known_item(s.Context(rf.TOPIC, 1, 1), "R", history((), ()), declared).state, U)


def with_contract(inputs, edit):
    """The same detached inputs with every captured contract document passed through `edit`."""
    tables = []
    for table in inputs.raw.tables:
        if table.name == "contract_revisions":
            at = table.columns.index("document")
            rows = []
            for row in table.rows:
                doc = json.loads(row[at])
                edit(doc)
                rows.append(tuple(canonical.canonical_bytes(doc).decode() if i == at else c for i, c in enumerate(row)))
            table = replace(table, rows=tuple(rows))
        tables.append(table)
    return replace(inputs, raw=replace(inputs.raw, tables=tuple(tables)))


class ProfileSelectionTest(rf.ContractWorld):
    def setUp(self):
        super().setUp()
        self.started("inv_gate0001")
        self.inputs = self.router._accounting.dossier_inputs(rf.TOPIC, history="native")

    def with_profiles(self, edit):
        return with_contract(self.inputs, edit)

    def evaluate(self, inputs):
        return gates.evaluate(inputs, self.spool, NOW)

    def test_the_sole_completing_profile_is_evaluated(self):
        result = self.evaluate(self.inputs)
        self.assertEqual(result.profile.profile_id, "SP-effect")
        self.assertEqual([g.gate for g in result.gates], ["load_bearing_verification_tiers", "challenge_pass_completed", "coverage_integrity"])
        self.assertEqual(result.state, U)  # its completion rules are reviewed judgments, which read as unknown

    def test_zero_or_several_completing_profiles_are_refused_naming_the_count(self):
        def none(doc):
            for profile in doc["stopping_profiles"]:
                profile["permitted_outcomes"] = ["awaiting_judgment"]
        def two(doc):
            doc["stopping_profiles"].append({**doc["stopping_profiles"][0], "profile_id": "SP-second"})
        for edit, fragment in ((none, "0 stopping profiles permit completion ()"), (two, "2 stopping profiles permit completion (SP-effect, SP-second)")):
            with self.assertRaises(Refusal) as caught:
                self.evaluate(self.with_profiles(edit))
            self.assertEqual(caught.exception.reason, "payload_invalid")
            self.assertIn(fragment, caught.exception.detail)

    def test_an_unsupported_automatic_rule_is_a_typed_refusal(self):
        def unsupported(doc):
            doc["stopping_profiles"][0]["rules"][0]["evaluation"] = "automatic"
        with self.assertRaises(Refusal) as caught:
            self.evaluate(self.with_profiles(unsupported))
        self.assertEqual(caught.exception.reason, "payload_invalid")
        self.assertIn("G-11", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()


class WiringTest(World):
    """Gate states through the real Router's detached capture and the production evaluator."""
    PROFILES = rf.contract_doc(1, None)["stopping_profiles"]

    def states(self):
        inputs = with_contract(self.router._accounting.dossier_inputs(rf.TOPIC, history="native"), lambda doc: doc.update(stopping_profiles=self.PROFILES))
        return {g.gate: (g.state, g.evidence_refs) for g in gates.evaluate(inputs, self.spool, NOW).gates}

    def load_bearing_quote_claim(self):
        triggers = self.rows("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'claims'")
        for name, _ in triggers:
            self.x(f"DROP TRIGGER {name}")
        self.x("UPDATE claims SET load_bearing = 1, required_access_tier = 'full_text' WHERE claim_id = 'clm_quote00001'")
        for _, sql in triggers:  # the store refuses to capture a schema that differs from the DDL
            self.x(sql)

    def test_verification_gate_follows_the_adverse_receipt_and_its_adjudication(self):
        self.assertEqual(self.states()["load_bearing_verification_tiers"], (N, ()))  # the receipt's claim is not load-bearing; the other has no support
        self.load_bearing_quote_claim()
        self.assertEqual(self.states()["load_bearing_verification_tiers"], (U, ()))  # D3: an adverse receipt without an adjudication
        self.accepted("verification_adjudication")
        self.assertEqual(self.states()["load_bearing_verification_tiers"], (N, (a.EvidenceReference(**self.ref),)))  # adjudicated, still no qualifying support

    def test_challenge_gate_needs_every_claim_and_open_contradiction(self):
        self.load_bearing_quote_claim()
        self.assertEqual(self.states()["challenge_pass_completed"], (N, ()))
        records = [self.completion("counterevidence_search"), self.completion("counterevidence_search", record_id="cr-second", subject_ref="clm_quote00001"),
                   self.completion("competing_explanation")]
        for index, record in enumerate(records):
            self.assertEqual(self.submit([record])["status"], "committed")
            expected = (S, (a.EvidenceReference(**self.ref),)) if index == 2 else (N, ())
            self.assertEqual(self.states()["challenge_pass_completed"][0], expected[0], index)
        self.assertEqual(self.states()["challenge_pass_completed"], expected)

    def test_coverage_gate_reads_the_capture(self):
        self.assertEqual(self.states()["coverage_integrity"], (U, ()))  # research passes here have no observations
