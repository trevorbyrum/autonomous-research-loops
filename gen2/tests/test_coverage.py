"""Certain-answer coverage: literal inventories and knowledge refinement."""
import unittest
from dataclasses import replace

from gen2 import accounting as a
from gen2.accounting import stopping as s
from gen2.tests import children
from gen2.tests.test_stopping import CTX, DATE, N, S, U, inventory


def attempts(complete=0, uncertain=0):
    observations = tuple(a.Observation(f"o{i}", f"p{i}", "lane", f"q{i}", "find", "complete", "exhausted", 0,
                         a.SearchPage(a.search_identity({"query": f"q{i}"}), 1, None, None)) for i in range(complete))
    return a.Inventory("native", observations=observations,
                       passes=tuple(a.Pass(f"p{i}", "research_pass", "committed") for i in range(complete + uncertain)),
                       current_contract_revision=1)


def evaluate(inv, minimum=1, **kwargs):
    pins = tuple(s.WindowPin(p.invocation_id, 1) for p in inv.passes if p.kind == "research_pass")
    return s.coverage(CTX, "coverage", inv, pins, minimum, **kwargs)


class CoverageTest(unittest.TestCase):
    def assert_standing(self, inv, invocation, state, reason):
        self.assertEqual(a.window_standings(inv), (a.WindowStanding(invocation, state, reason),))

    def assert_counts(self, result, expected):
        operands = result.operands
        self.assertEqual((operands.eligible, operands.ineligible, operands.indeterminate), expected)

    def test_control_no_attempt(self):
        result = evaluate(attempts())
        self.assertEqual((result.state, result.operands.windows), (N, ()))
        self.assert_counts(result, (0, 0, 0))

    def test_discovery_is_not_window(self):
        inv = replace(attempts(0, 1), passes=(a.Pass("p0", "discovery", "committed"),))
        self.assertEqual(evaluate(inv).state, N)
        self.assertEqual(a.window_standings(inv), ())

    def test_control_complete(self):
        result = evaluate(attempts(1))
        self.assertEqual(result.state, S)
        self.assert_counts(result, (1, 0, 0))
        self.assertEqual(result.operands.windows, (s.WindowOperand("p0", 1, "current"),))
        self.assertEqual(a.window_standings(attempts(1)), (a.WindowStanding("p0", "eligible", "completed distinct search"),))

    def test_missing_capture(self):
        inv = attempts(0, 1)
        self.assert_standing(inv, "p0", "indeterminate", "invocation capture missing: p0")
        result = evaluate(inv)
        self.assertEqual(result.state, U)
        self.assert_counts(result, (0, 0, 1))
        self.assertEqual(result.operands.windows, (s.WindowOperand("p0", 1, "current", "indeterminate", "invocation capture missing: p0"),))
        self.assertEqual(a.saturation_passes(inv), ())

    def test_partial_capture(self):
        inv = replace(inventory(), observations=(replace(inventory().observations[0], completeness="partial", page_outcome="end_unknown"),))
        self.assert_standing(inv, "p", "indeterminate", "capture partial or unknown")
        result = evaluate(inv)
        self.assertEqual(result.state, U)
        self.assertEqual(result.operands.windows[0].reason, "capture partial or unknown")
        self.assert_counts(result, (0, 0, 1))
        self.assertEqual(a.saturation_passes(inv), ())

    def test_unobserved_request(self):
        inv = replace(inventory(), observations=(replace(inventory().observations[0], completeness="unobserved", page_outcome="end_unknown", result_count=None),))
        self.assert_standing(inv, "p", "indeterminate", "request unobserved")
        result = evaluate(inv)
        self.assertEqual(result.state, U)
        self.assertEqual(result.operands.windows[0].reason, "request unobserved")

    def test_unknown_end(self):
        for end, continuation in (("end_unknown", None), ("continuation", "next")):
            with self.subTest(end=end):
                obs = replace(inventory().observations[0], page_outcome=end, page=replace(inventory().observations[0].page, continuation=continuation))
                inv = replace(inventory(), observations=(obs,))
                self.assert_standing(inv, "p", "indeterminate", "pagination end unknown")
                self.assertEqual(a.candidate_units(inv).retrieved_records.value, 1)
                result = evaluate(inv)
                self.assertEqual(result.state, U)
                self.assertEqual(result.operands.windows[0].reason, "pagination end unknown")
                self.assertEqual(a.saturation_passes(inv), ())

    def test_delegate_uncertainty(self):
        for depth in (1, 2):
            for mode, reason in (("missing", f"invocation capture missing: d{depth}"), ("partial", "capture partial or unknown"),
                                 ("unobserved", "request unobserved"), ("end_unknown", "pagination end unknown")):
                with self.subTest(depth=depth, mode=mode):
                    inv = inventory()
                    delegates = tuple(a.Pass(f"d{i}", "delegate", "committed", "p" if i == 1 else f"d{i-1}") for i in range(1, depth + 1))
                    captures = tuple(replace(inv.observations[0], observation_id=f"od{i}", invocation_id=f"d{i}", result_count=0,
                                             page=replace(inv.observations[0].page, search=a.search_identity({"query": f"delegate{i}"}))) for i in range(1, depth + 1))
                    changed = replace(captures[-1], completeness="partial" if mode == "partial" else "unobserved" if mode == "unobserved" else "complete",
                                      page_outcome="end_unknown", result_count=None if mode == "unobserved" else 0)
                    captures = captures[:-1] if mode == "missing" else (*captures[:-1], changed)
                    inv = replace(inv, passes=(*inv.passes, *delegates), observations=(*inv.observations, *captures))
                    self.assert_standing(inv, "p", "indeterminate", reason)
                    result = evaluate(inv)
                    self.assertEqual(result.state, U)
                    self.assert_counts(result, (0, 0, 1))
                    self.assertEqual(result.operands.windows, (s.WindowOperand("p", 1, "current", "indeterminate", reason),))
                    self.assertEqual(a.saturation_passes(inv), ())

    def test_control_complete_delegate(self):
        inv = inventory()
        inv = replace(inv, passes=(*inv.passes, a.Pass("d", "delegate", "committed", "p")),
                      observations=(replace(inv.observations[0], invocation_id="d"),))
        result = evaluate(inv)
        self.assertEqual(result.state, S)
        self.assert_counts(result, (1, 0, 0))
        self.assertEqual(a.saturation_passes(inv), ("p",))

    def test_control_nonpaging(self):
        inv = attempts(1)
        inv = replace(inv, observations=(replace(inv.observations[0], request_type="resolve", page=None, page_outcome="end_unknown"),))
        self.assert_standing(inv, "p0", "ineligible", "no complete distinct search")
        result = evaluate(inv)
        self.assertEqual(result.state, N)
        self.assert_counts(result, (0, 1, 0))
        self.assertEqual(result.operands.windows, (s.WindowOperand("p0", 1, "current", "ineligible", "no complete distinct search"),))

    def test_control_lower_bound(self):
        result = evaluate(attempts(1, 1))
        self.assertEqual(result.state, S)
        self.assert_counts(result, (1, 0, 1))

    def test_control_upper_bound(self):
        result = evaluate(attempts(1, 1), 3)
        self.assertEqual(result.state, N)
        self.assert_counts(result, (1, 0, 1))

    def test_between_bounds(self):
        inv = attempts(1, 1)
        self.assertEqual(a.window_standings(inv), (a.WindowStanding("p0", "eligible", "completed distinct search"),
                                                  a.WindowStanding("p1", "indeterminate", "invocation capture missing: p1")))
        result = evaluate(inv, 2)
        self.assertEqual(result.state, U)
        self.assert_counts(result, (1, 0, 1))

    def test_known_exclusions(self):
        inv = attempts(1)
        for changed, reason in (
            (replace(inv, passes=(replace(inv.passes[0], state="failed"),)), "invocation failed or cancelled"),
            (replace(inv, observations=(replace(inv.observations[0], page_outcome="limit_reached"),)), "request failed or capped"),
            (replace(inv, observations=(replace(inv.observations[0], page_outcome="failed", completeness="unobserved", result_count=None),)), "request failed or capped"),
            (replace(inv, observations=(replace(inv.observations[0], request_type="resolve", page=None, page_outcome="end_unknown"),)), "no complete distinct search"),
            (replace(inv, observations=(replace(inv.observations[0], page=replace(inv.observations[0].page, number=2)),)), "no complete distinct search"),
        ):
            with self.subTest(reason=reason):
                self.assert_standing(changed, "p0", "ineligible", reason)
                result = evaluate(changed)
                self.assertEqual(result.state, N)
                self.assert_counts(result, (0, 1, 0))
                self.assertEqual(result.operands.windows[0].reason, reason)
        repeat = replace(attempts(2), observations=(inv.observations[0], replace(inv.observations[0], observation_id="o1", invocation_id="p1")))
        result = evaluate(repeat, 2)
        self.assertEqual(result.state, N)
        self.assert_counts(result, (1, 1, 0))
        self.assertEqual(a.saturation_passes(repeat), ("p0",))

    def test_failed_delegate_is_known(self):
        inv = replace(attempts(1), passes=(*attempts(1).passes, a.Pass("d", "delegate", "failed", "p0")))
        self.assert_standing(inv, "p0", "ineligible", "invocation failed or cancelled")
        result = evaluate(inv)
        self.assertEqual(result.state, N)
        self.assertEqual(result.operands.windows[0].reason, "invocation failed or cancelled")
        self.assert_counts(result, (0, 1, 0))

    def test_known_ineligible_without_pin(self):
        inv = replace(attempts(1), passes=(a.Pass("p0", "research_pass", "failed"),))
        result = s.coverage(CTX, "coverage", inv, (), 1)
        self.assertEqual(result.state, N)
        self.assert_counts(result, (0, 1, 0))
        self.assertEqual(result.operands.windows[0].reason, "invocation failed or cancelled")

    def test_unfinished_and_metadata(self):
        for inv, reason in ((replace(attempts(1), passes=(a.Pass("p0", "research_pass", "running"),)), "invocation unfinished"),
                            (replace(attempts(1), observations=(replace(attempts(1).observations[0], page=None),)), "search page metadata missing"),
                            (replace(attempts(1), history="legacy_unknown"), "legacy historical capture unknown")):
            with self.subTest(reason=reason):
                self.assert_standing(inv, "p0", "indeterminate", reason)
                result = evaluate(inv)
                self.assertEqual(result.state, U)
                self.assertEqual(result.operands.windows[0].reason, reason)
                self.assert_counts(result, (0, 0, 1))

    def test_rule_scope(self):
        inv = attempts(1, 1)
        for scope, minimum, state, counts, ids in ((frozenset({"p0"}), 2, N, (1, 0, 0), ("p0",)),
                (frozenset({"p1"}), 1, U, (0, 0, 1), ("p1",)), (frozenset(), 1, N, (0, 0, 0), ())):
            with self.subTest(scope=scope):
                result = evaluate(inv, minimum, scope=scope)
                self.assertEqual(result.state, state)
                self.assert_counts(result, counts)
                self.assertEqual(tuple(w.invocation_id for w in result.operands.windows), ids)
                self.assertEqual(result.operands.scope, scope)

    def test_g1_bounds(self):
        impact = a.AmendmentImpact("amendment", 1, (a.RevisionStanding(2, "protocol_changed"),), (), DATE)
        inv = replace(attempts(2), amendment_impacts=(impact,))
        result = s.coverage(CTX, "coverage", inv, (s.WindowPin("p0", 1), s.WindowPin("p1", 2)), 1)
        self.assertEqual(result.state, S)
        self.assert_counts(result, (1, 1, 0))
        self.assertEqual(result.operands.windows[1], s.WindowOperand("p1", 2, "stale", "ineligible", "contract revision stale"))
        result = s.coverage(CTX, "coverage", attempts(2), (s.WindowPin("p0", 1),), 1)
        self.assertEqual(result.state, S)
        self.assert_counts(result, (1, 0, 1))

    def test_g1_unknown_upper_bound(self):
        result = s.coverage(CTX, "coverage", attempts(1), (s.WindowPin("p0", 2),), 1)
        self.assertEqual(result.state, U)
        self.assert_counts(result, (0, 0, 1))
        self.assertEqual(result.operands.windows[0].reason, "contract standing unknown; completed distinct search")

    def test_router_recorded_attempts(self):
        from gen2.tests.test_accounting import WindowTest
        from gen2.tests.router_fixtures import TOPIC
        for mode in ("missing", "partial", "unknown_end", "delegate", "complete"):
            with self.subTest(mode=mode):
                fixture = WindowTest()
                fixture.setUp()
                try:
                    parent = fixture.started("inv_coverage001")
                    if mode != "missing":
                        fixture.page(parent, "obs_coverage001", partial=mode == "partial",
                                     end="end_unknown" if mode in ("partial", "unknown_end") else "exhausted")
                    if mode == "delegate":
                        delegate = fixture.started("inv_coverage002", kind="delegate", parent=parent)
                        fixture.committed(delegate)
                    fixture.committed(parent)
                    inv = fixture.router.evidence_inventory(TOPIC, history="native")
                    revision, protocol = fixture.rows("SELECT revision, protocol_revision FROM contract_revisions WHERE topic_id = ? AND status = 'approved'", TOPIC)[0]
                    result = s.coverage(s.Context(TOPIC, revision, protocol), "coverage", inv,
                                        (s.WindowPin(parent["invocation_id"], revision),), 1)
                    self.assertEqual(result.state, S if mode == "complete" else U)
                    self.assert_counts(result, (1, 0, 0) if mode == "complete" else (0, 0, 1))
                finally:
                    fixture.tearDown()
                    fixture.doCleanups()

    def test_properties(self):
        result = children.python(["-c", PROPERTIES], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


PROPERTIES = '''
from dataclasses import replace
from hypothesis import given, settings, strategies as st
from gen2.tests.test_coverage import attempts, evaluate
@settings(max_examples=100, derandomize=True, database=None)
@given(st.integers(0, 6), st.integers(1, 6), st.integers(1, 14), st.integers(0, 5),
       st.sampled_from(("missing", "partial", "unobserved", "end_unknown")))
def knowledge_monotone(complete, uncertain, minimum, slot, mode):
    inv = attempts(complete, uncertain)
    if mode != "missing":
        captures = attempts(complete + uncertain).observations[complete:]
        captures = tuple(replace(o, completeness="partial" if mode == "partial" else "unobserved" if mode == "unobserved" else "complete",
                                 page_outcome="end_unknown", result_count=None if mode == "unobserved" else 0) for o in captures)
        inv = replace(inv, observations=(*inv.observations, *captures))
    before = evaluate(inv, minimum).state
    i = complete + slot % uncertain
    observed = attempts(i + 1).observations[-1]
    eligible = replace(inv, observations=(*(o for o in inv.observations if o.invocation_id != f"p{i}"), observed))
    ineligible = replace(inv, passes=tuple(replace(p, state="failed") if p.invocation_id == f"p{i}" else p for p in inv.passes))
    if before != "unknown":
        assert evaluate(eligible, minimum).state == before
        assert evaluate(ineligible, minimum).state == before
knowledge_monotone()
'''
