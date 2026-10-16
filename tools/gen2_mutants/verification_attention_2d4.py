"""V-5/V-2 adverse-verdict routing, with literal accepted controls."""
from .base import Mutation

TEST = "test_verification_attention."
TARGET = "gen2/router/verification.py"
MUTATIONS, CONTROLS = [], {}


def guard(name, killer, old, new, control="AttentionTest.test_support_control", target=TARGET):
    mid = "2D4-" + name
    MUTATIONS.append(Mutation(mid, "2d-4", name, (TEST + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "Literal supportive no-op, another adverse verdict, or equal primary/verifier ownership traverses the changed guard and retains its specified effects."}


guard("support-routed", "AttentionTest.test_support_control", 'if not self._needs_hold(doc):', 'if False:',
      control="AttentionTest.test_disagreement")
guard("disagreement-omitted", "AttentionTest.test_disagreement", 'if not self._needs_hold(doc):', 'if not self._needs_hold(doc) or doc["verdict"] == "does_not_support":',
      control="AttentionTest.test_partial_disagreement")
guard("partial-omitted", "AttentionTest.test_partial_disagreement", 'if not self._needs_hold(doc):', 'if not self._needs_hold(doc) or doc["verdict"] == "partially_supports":',
      control="AttentionTest.test_disagreement")
guard("missing-omitted", "AttentionTest.test_missing_content", 'if not self._needs_hold(doc):', 'if not self._needs_hold(doc) or doc["verdict"] == "cannot_assess_at_required_tier":',
      control="AttentionTest.test_disagreement")
guard("owner", "AttentionTest.test_disagreement", 'producer = self._core._one("invocations", {"invocation_id": claim["producer_invocation_id"]})',
      'producer = self._core._one("invocations", {"invocation_id": doc["verifier_invocation_id"]})', control="SharedOwnerTest.test_control")
guard("deadline", "AttentionTest.test_disagreement", '"deadline_at": producer["deadline_at"]',
      '"deadline_at": self._core._one("invocations", {"invocation_id": doc["verifier_invocation_id"]})["deadline_at"]', control="SharedOwnerTest.test_control")
guard("missing-classification", "AttentionTest.test_missing_content", 'missing = doc["verdict"] == "cannot_assess_at_required_tier"', 'missing = False',
      control="AttentionTest.test_disagreement")
guard("effects", "AttentionTest.test_disagreement", ' + self._verification.hold_ids(payload, admitted=True)', '', target="gen2/router/service.py")
guard("effects-support", "AttentionTest.test_support_control", ' if self._needs_hold(doc, admitted=admitted)]', ']', control="AttentionTest.test_disagreement")
guard("write-wiring", "AttentionTest.test_disagreement", 'verification = self._core._write_verification_holds(payload, op_id, now)',
      'verification = {"verification_holds": []}', target="gen2/router/evidence_writer.py")
guard("delegate", "AttentionTest.test_disagreement", 'return self._verification.write_holds(payload, op_id, now)',
      'return {"verification_holds": []}', target="gen2/router/service.py")


def attention(name, killer, old, new, control, target=TARGET):
    mid = '2D4ATTN-' + name
    prefix = 'test_extraction_attention.ExtractionAttentionTest.'
    MUTATIONS.append(Mutation(mid, '2d-4b3e3 part 2', name, (prefix + killer,), target=target, old=old, new=new))
    CONTROLS[mid] = dict(controls=[prefix + control], why='Separate committed bound receipt, durable fenced receipt, or truthful missing-content receipt reaches the changed attention predicate.')


attention('verdict', 'test_missing_content', 'if doc["verdict"] != "supports":', 'if False:', 'test_bound_control')
attention('canonical', 'test_canonical_control', 'if doc["extraction"]["method"] == "canonical_bytes":', 'if False:', 'test_bound_control')
attention('planning', 'test_same_outcome_control', 'if admitted:', 'if False:', 'test_fenced')
attention('basis-required', 'test_fenced',
    'return not self._core._store.bound_extraction_receipt(doc["verification_receipt_id"])', 'return False', 'test_bound_control')
attention('bound-exempt', 'test_bound_control',
    'return not self._core._store.bound_extraction_receipt(doc["verification_receipt_id"])', 'return True', 'test_fenced')
attention('receipt-id', 'test_bound_control',
    'bound_extraction_receipt(doc["verification_receipt_id"])', 'bound_extraction_receipt("absent")', 'test_fenced')
attention('pending-classification', 'test_fenced', 'missing = missing or pending', 'missing = missing', 'test_missing_content')
attention('effects-planning', 'test_same_outcome_control',
    'self._verification.hold_ids(payload, admitted=True)', 'self._verification.hold_ids(payload)', 'test_missing_content', 'gen2/router/service.py')
attention('exact-receipt', 'test_fenced_with_bound_distractor',
    'WHERE verification_receipt_id = ?', 'WHERE verification_receipt_id = ? OR 1 = 1', 'test_same_outcome_control', 'gen2/store/api.py')
