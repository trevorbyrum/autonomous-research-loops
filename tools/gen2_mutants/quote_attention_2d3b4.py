"""V-6 existing owner attention and independent byte-adjudication guards."""
from .base import Mutation

TEST = "test_quote_attention."
TARGET = "gen2/router/evidence_writer.py"
MUTATIONS, CONTROLS = [], {}


def guard(name, killer, old=None, new="", target=TARGET, trigger=None, control="AttentionTest.test_nli_adjudication_control", scope=None):
    mid = "2D3B4-" + name
    MUTATIONS.append(Mutation(mid, "2d-3b4", name, (TEST + killer,), target=target, old=old, new=new, drop_trigger=trigger, scope=scope))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "Literal accepted NLI, matched bytes or a shared-owner mismatch crosses the changed boundary and retains its independently specified result."}


guard("notification", "AttentionTest.test_mismatch_notification", 'if record["quote_quarantined"]:', 'if False:',
      control="AttentionTest.test_match_control")
guard("capture-owner", "AttentionTest.test_mismatch_notification",
      'producer = self._core._one("invocations", {"invocation_id": claim["producer_invocation_id"]})',
      'producer = self._core._store.select("invocations", {"topic_id": check["topic_id"], "kind": "verification"})[0]',
      control="SharedOwnerTest.test_control")
guard("notification-receipt", "AttentionTest.test_mismatch_notification",
      ' + self._evidence_writer.quote_hold_ids(checked)', target="gen2/router/service.py", control="AttentionTest.test_match_control")
guard("matched-receipt", "AttentionTest.test_match_control", ' if q["quote_quarantined"]]', ']',
      control="AttentionTest.test_mismatch_notification")
guard("adjudication", "RouterGuardTest.test_mismatch_adjudication", 'self._require_quote_adjudication(doc)', 'pass')
guard("declared-byte", "RouterGuardTest.test_declared_mismatch", 'doc["checks"]["exact_quote"]["status"] == "mismatch"', 'False')
guard("capture-byte", "RouterGuardTest.test_capture_mismatch", 'q["quote_quarantined"] and (q["exact_match"] != "matched" or q["nli_signal"] != "alarm")', 'False')
guard("nli-required", "RouterGuardTest.test_non_nli_quarantine", 'q["nli_signal"] != "alarm"', 'False')
guard("decision-wiring", "RouterGuardTest.test_clearance", 'self._evidence_writer.require_quote_hold_clearance(row)', 'pass',
      target="gen2/router/service.py", control="AttentionTest.test_nli_clearance_control")
guard("decision-byte", "RouterGuardTest.test_clearance", 'if check is not None and check["quote_quarantined"] and (check["exact_match"] != "matched" or check["nli_signal"] != "alarm"):', 'if False:',
      control="AttentionTest.test_nli_clearance_control")
guard("decision-nli-required", "RouterGuardTest.test_non_nli_clearance", 'check["nli_signal"] != "alarm"', 'False',
      control="AttentionTest.test_nli_clearance_control")

guard("ddl-adjudication", "AdjudicationDDLTest.test_byte_adjudication", target="ddl",
      trigger="verification_receipts_no_byte_adjudication", control="AdjudicationDDLTest.test_nli_control")
guard("ddl-declared-byte", "AdjudicationDDLTest.test_declared_mismatch_adjudication",
      "json_extract(NEW.receipt, '$.checks.exact_quote.status') = 'mismatch'", "0", target="ddl",
      control="AdjudicationDDLTest.test_nli_control")
guard("ddl-capture-byte", "AdjudicationDDLTest.test_capture_adjudication",
      "AND (q.match_result IS NOT NULL OR q.check_id = NEW.quote_check_id)", "AND q.check_id = NEW.quote_check_id", target="ddl",
      control="AdjudicationDDLTest.test_nli_control")
guard("ddl-nli-required", "AdjudicationDDLTest.test_non_nli_quarantine",
      "(q.quote_quarantined = 1 AND q.nli_signal != 'alarm')", "0", target="ddl",
      control="AdjudicationDDLTest.test_nli_control", scope="verification_receipts_no_byte_adjudication")
guard("ddl-decision", "AdjudicationDDLTest.test_byte_clearance_decision", target="ddl",
      trigger="operator_decisions_no_byte_clearance", control="AdjudicationDDLTest.test_nli_clearance_control")
guard("ddl-direct-clearance", "AdjudicationDDLTest.test_direct_clearance", target="ddl",
      trigger="holds_no_byte_clearance", control="AdjudicationDDLTest.test_nli_clearance_control")
for scope in ("operator_decisions_no_byte_clearance", "holds_no_byte_clearance"):
    guard("ddl-nli-" + scope, "AdjudicationDDLTest.test_non_nli_clearance",
          "(q.quote_quarantined = 1 AND q.nli_signal != 'alarm')", "0", target="ddl", scope=scope,
          control="AdjudicationDDLTest.test_nli_clearance_control")
