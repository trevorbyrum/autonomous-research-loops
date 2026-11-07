"""The trusted input assembly (Astra #127 F1): the proposals and their proposer come from one receipt-verified committed
outcome. Oracles: the router's receipt row shape (operation_receipts) as a hand-written double, the digest recomputed from the
staged bytes, and the child's own refusal on the assembled input. Limits: the receipts here are doubles; the real Router's
`topic_records` does not carry `operation_receipts` yet (lane A), and the Router-backed adapter is tested against a double of
that route. What is shown is that a well-formed but wrong invocation id can never reach a stamp."""
import tempfile
import unittest

from gen2.core import canonical
from gen2.discovery import binding
from gen2.exec.common import Refused
from gen2.tests.test_discovery_child import PROPOSER, TOPIC, Fixture, committed, proposal, validate
from gen2.tests.test_discovery_stamp import observations, result_of


class Spool:
    def __init__(self, staged):
        self.staged = staged

    def read(self, content_hash, *, topic_id):
        return self.staged.get((topic_id, content_hash))


class Receipts:
    def __init__(self, rows):
        self.rows = rows

    def receipt(self, invocation_id):
        if invocation_id not in self.rows:
            raise Refused("no receipt")
        return self.rows[invocation_id]


def world(by=PROPOSER, proposals=None):
    view = committed(proposals or [proposal(1, obligation_ids=[]), proposal(2, query="other", obligation_ids=[])], by)["committed"]
    payload, digest = view["payload"].encode(), view["receipt"]["payload_digest"]
    receipt = {"operation_id": "op_aaaaaaaa", "invocation_id": by, "topic_id": TOPIC, "payload_digest": digest, "operation_kind": "final_outcome"}
    return Receipts({by: receipt}), Spool({(TOPIC, digest): payload}), digest


class AssembleTest(Fixture, unittest.TestCase):
    def test_committed_payload_to_assembled_input_to_stamped_observation(self):
        receipts, spool, digest = world()
        view = binding.assemble(receipts, spool, TOPIC, PROPOSER, validate, 100_000)
        self.assertEqual(view["committed"]["receipt"], {"invocation_id": PROPOSER, "payload_digest": digest})
        env = self.stage([], committed=view["committed"])
        self.run_child(env)
        refs = [i["observation"]["request"]["proposal_ref"] for i in observations(result_of(self))]
        self.assertEqual(refs, [f"{PROPOSER}:p1", f"{PROPOSER}:p2"])

    def test_a_well_formed_but_different_invocation_is_refused_at_every_step(self):
        receipts, spool, digest = world()
        other, other_spool, _ = world(by="inv_forged0001")
        mixed = Receipts({PROPOSER: {**receipts.rows[PROPOSER], "invocation_id": "inv_forged0001"}})      # the receipt names another invocation
        wrong_payload = Spool({(TOPIC, digest): committed([proposal(1, obligation_ids=[])], "inv_forged0001")["committed"]["payload"].encode()})   # bytes do not hash to the receipt
        cases = {"receipt for another invocation": (mixed, spool),
                 "payload bytes that are not the receipt's": (receipts, wrong_payload),
                 "nothing staged": (receipts, Spool({})),
                 "receipt of another topic": (Receipts({PROPOSER: {**receipts.rows[PROPOSER], "topic_id": "fleet:other"}}), spool)}
        for name, (r, s) in cases.items():
            with self.subTest(name), self.assertRaises(Refused):
                binding.assemble(r, s, TOPIC, PROPOSER, validate, 100_000)
        with self.assertRaises(Refused):
            binding.assemble(other, other_spool, TOPIC, PROPOSER, validate, 100_000)   # asked for one invocation, the store holds another's

    def test_a_payload_that_names_another_invocation_than_its_receipt_is_refused(self):
        forged = committed([proposal(1, obligation_ids=[])], "inv_forged0001")["committed"]
        receipt = {"operation_id": "op_aaaaaaaa", "invocation_id": PROPOSER, "topic_id": TOPIC, "payload_digest": forged["receipt"]["payload_digest"], "operation_kind": "final_outcome"}
        spool = Spool({(TOPIC, receipt["payload_digest"]): forged["payload"].encode()})
        with self.assertRaises(Refused):
            binding.assemble(Receipts({PROPOSER: receipt}), spool, TOPIC, PROPOSER, validate, 100_000)


class TopicReceiptsTest(unittest.TestCase):
    class Reader:
        def __init__(self, answer):
            self.answer, self.asked = answer, []

        def topic_records(self, request):
            self.asked.append(request)
            return self.answer

    def row(self, **over):
        return {"operation_id": "op_aaaaaaaa", "invocation_id": PROPOSER, "topic_id": TOPIC, "payload_digest": "sha256:" + "a" * 64, "operation_kind": "final_outcome", **over}

    def test_exactly_one_final_outcome_of_the_invocation_is_the_receipt(self):
        ok = self.Reader({"status": "ok", "topic_id": TOPIC, "records": {"operation_receipts": [self.row(), self.row(operation_id="op_bbbbbbbb", operation_kind="interim_transition"),
                                                                                              self.row(operation_id="op_cccccccc", invocation_id="inv_other0001")]}})
        self.assertEqual(binding.TopicReceipts(ok, TOPIC).receipt(PROPOSER)["operation_id"], "op_aaaaaaaa")
        self.assertEqual(ok.asked, [{"topic_id": TOPIC, "families": ["operation_receipts"]}])

    def test_none_two_or_a_refused_read_give_no_receipt(self):
        two = {"status": "ok", "topic_id": TOPIC, "records": {"operation_receipts": [self.row(), self.row(operation_id="op_bbbbbbbb")]}}
        none = {"status": "ok", "topic_id": TOPIC, "records": {"operation_receipts": []}}
        refused = {"status": "refused", "reason": "request_invalid"}
        other_topic = {"status": "ok", "topic_id": "fleet:other", "records": {"operation_receipts": [self.row()]}}
        for name, answer in (("two", two), ("none", none), ("refused (the family is not allowed yet)", refused), ("another topic's answer", other_topic)):
            with self.subTest(name), self.assertRaises(Refused):
                binding.TopicReceipts(self.Reader(answer), TOPIC).receipt(PROPOSER)
