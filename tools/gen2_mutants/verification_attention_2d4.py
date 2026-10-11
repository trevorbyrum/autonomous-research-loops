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
guard("effects", "AttentionTest.test_disagreement", ' + self._verification.hold_ids(payload)', '', target="gen2/router/service.py")
guard("effects-support", "AttentionTest.test_support_control", ' if self._needs_hold(doc)]', ']', control="AttentionTest.test_disagreement")
guard("write-wiring", "AttentionTest.test_disagreement", 'verification = self._core._write_verification_holds(payload, op_id, now)',
      'verification = {"verification_holds": []}', target="gen2/router/evidence_writer.py")
guard("delegate", "AttentionTest.test_disagreement", 'return self._verification.write_holds(payload, op_id, now)',
      'return {"verification_holds": []}', target="gen2/router/service.py")
