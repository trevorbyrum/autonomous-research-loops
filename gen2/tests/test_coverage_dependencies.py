"""Literal round-2 counterexamples and controls for global credit dependencies."""
import unittest
from dataclasses import replace

from gen2 import accounting as a
from gen2.accounting import stopping as s
from gen2.tests.test_stopping import CTX, DATE, N, S, U


def page(root, query, number=1, cursor=None, continuation=None, end="exhausted"):
    return a.Observation(f"o-{root}-{query}-{number}", root, "lane", query, "find", "complete", end, 0,
                         a.SearchPage(a.search_identity({"query": query}), number, cursor, continuation))


def history(roots, observations):
    return a.Inventory("native", observations=tuple(observations),
                       passes=tuple(a.Pass(i, "research_pass", "committed") for i in roots), current_contract_revision=1)


def evaluate(inv, minimum=1, **kwargs):
    # Bind the evaluator in this test module, which the harness reloads over a mutant.
    pins = tuple(s.WindowPin(p.invocation_id, 1) for p in inv.passes if p.kind == "research_pass")
    return s.coverage(CTX, "coverage", inv, pins, minimum, **kwargs)


class DependencyTest(unittest.TestCase):
    def test_overlap_probe(self):
        before = history(("p0", "p1", "p2"), (page("p1", "q1"), page("p2", "q2")))
        result = evaluate(before, 2)
        self.assertEqual((result.state, result.operands.lower, result.operands.upper), (U, 1, 3))
        overlap = replace(before, observations=(*before.observations, page("p0", "q1"), page("p0", "q2")))
        disjoint = replace(before, observations=(*before.observations, page("p0", "q0")))
        failed = replace(before, passes=(replace(before.passes[0], state="failed"), *before.passes[1:]))
        self.assertEqual(evaluate(overlap, 2).state, N)
        self.assertEqual(evaluate(disjoint, 2).state, S)
        self.assertEqual(evaluate(failed, 2).state, S)
        self.assertEqual(evaluate(before).state, S)  # A completing in-scope thief contributes one.

    def test_scoped_overlap_probe(self):
        before = history(("p0", "p1"), (page("p1", "q"),))
        scope = frozenset({"p1"})
        result = evaluate(before, scope=scope)
        self.assertEqual((result.state, result.operands.lower, result.operands.upper), (U, 0, 1))
        for captured, expected in (((page("p0", "q"),), N), ((page("p0", "other"),), S)):
            resolved = replace(before, observations=(*before.observations, *captured))
            self.assertEqual(evaluate(resolved, scope=scope).state, expected)
        failed = replace(before, passes=(replace(before.passes[0], state="failed"), before.passes[1]))
        self.assertEqual(evaluate(failed, scope=scope).state, S)

    def test_known_search_discount(self):
        before = history(("p0", "p1", "p2"),
                         (replace(page("p0", "q1"), completeness="partial", page_outcome="end_unknown"),
                          page("p1", "q1"), page("p2", "q2")))
        result = evaluate(before, 2)
        self.assertEqual((result.state, result.operands.lower), (S, 2))
        self.assertEqual(evaluate(before, 2, scope=frozenset({"p1", "p2"})).state, U)
        # Partial overlap alone cannot consume both searches of a multi-search root.
        multi = history(("p0", "p1"), (before.observations[0], page("p1", "q1"), page("p1", "q2")))
        self.assertEqual(evaluate(multi, scope=frozenset({"p1"})).state, S)

    def test_control_disjoint(self):
        inv = history(("p0", "p1", "p2"),
                      (replace(page("p0", "q0"), completeness="partial", page_outcome="end_unknown"),
                       page("p1", "q1"), page("p2", "q2")))
        result = evaluate(inv, 2, scope=frozenset({"p1", "p2"}))
        self.assertEqual((result.state, result.operands.lower, result.operands.upper), (S, 2, 2))

    def test_combined_thieves_and_existing_credit(self):
        inv = history(("p0", "p1", "p2"),
                      (replace(page("p0", "q1"), completeness="partial"),
                       replace(page("p1", "q2"), completeness="partial"), page("p2", "q1"), page("p2", "q2")))
        self.assertEqual(evaluate(inv, scope=frozenset({"p2"})).state, U)
        self.assertEqual(evaluate(inv).operands.lower, 1)
        # q0 was already credited; only the new q1 is vulnerable.
        inv = history(("p0", "p1", "p2"), (page("p0", "q0"),
                      replace(page("p1", "q1"), completeness="partial"), page("p2", "q0"), page("p2", "q1")))
        self.assertEqual(evaluate(inv, scope=frozenset({"p2"})).state, U)

    def test_stale_thief(self):
        inv = history(("p0", "p1"), (page("p1", "q"),))
        impact = a.AmendmentImpact("amendment", 1, (a.RevisionStanding(2, "protocol_changed"),), (), DATE)
        inv = replace(inv, amendment_impacts=(impact,))
        result = s.coverage(CTX, "coverage", inv, (s.WindowPin("p0", 2), s.WindowPin("p1", 1)), 1)
        self.assertEqual((result.state, result.operands.lower, result.operands.ineligible), (U, 0, 1))

    def test_recoverable_prefix_and_interior(self):
        for captures, added in (((page("p", "q", 2, "next"),), (page("p", "q", 1, None, "next", "continuation"),)),
                               ((page("p", "q", 1, None, "a", "continuation"), page("p", "q", 3, "b")),
                                (page("p", "q", 2, "a", "b", "continuation"),))):
            with self.subTest(captures=captures):
                inv = history(("p",), captures)
                self.assertEqual(evaluate(inv).state, U)
                self.assertEqual(a.window_standings(inv)[0].state, "indeterminate")
                self.assertEqual(a.window_standings(inv)[0].reason, "pagination pages missing")
                self.assertEqual(a.saturation_passes(inv), ())
                self.assertEqual(evaluate(replace(inv, observations=(*captures, *added))).state, S)
                self.assertEqual(evaluate(replace(inv, passes=(replace(inv.passes[0], state="failed"),))).state, N)

    def test_control_invalid_chain(self):
        for captures in ((page("p", "q", 2),), (page("p", "q"), page("p", "q", 2, "next")),
                         (page("p", "q", 1, None, "a", "continuation"), page("p", "q", 2, "b")),
                         (page("p", "q"), replace(page("p", "q"), observation_id="conflicting"))):
            with self.subTest(captures=captures):
                inv = history(("p",), captures)
                self.assertEqual(evaluate(inv).state, N)
                self.assertEqual(a.window_standings(inv)[0].state, "ineligible")

    def test_router_overlap_probe(self):
        from gen2.tests.test_accounting import WindowTest
        from gen2.tests.router_fixtures import TOPIC, find_request
        for mode, expected in (("missing_first", U), ("complete_overlap", N), ("complete_disjoint", S)):
            fixture = WindowTest()
            fixture.setUp()
            try:
                first = fixture.started("inv_overlap000")
                if mode == "complete_overlap":
                    fixture.page(first, "obs_overlap001", find_request("q1"))
                    fixture.page(first, "obs_overlap002", find_request("q2"))
                elif mode == "complete_disjoint":
                    fixture.page(first, "obs_overlap000", find_request("q0"))
                fixture.committed(first)
                for i in (1, 2):
                    grant = fixture.started(f"inv_overlap00{i}")
                    fixture.page(grant, f"obs_overlap01{i}", find_request(f"q{i}"))
                    fixture.committed(grant)
                inv = fixture.router.evidence_inventory(TOPIC, history="native")
                revision, protocol = fixture.rows("SELECT revision, protocol_revision FROM contract_revisions WHERE topic_id = ? AND status = 'approved'", TOPIC)[0]
                for scope in (None, frozenset({"inv_overlap001", "inv_overlap002"})):
                    result = s.coverage(s.Context(TOPIC, revision, protocol), "coverage", inv,
                                        tuple(s.WindowPin(p.invocation_id, revision) for p in inv.passes), 2, scope=scope)
                    self.assertEqual(result.state, expected)
            finally:
                fixture.tearDown()
                fixture.doCleanups()

    def test_router_missing_prefix_probe(self):
        from gen2.tests.test_accounting import WindowTest
        from gen2.tests.router_fixtures import TOPIC, find_request
        for add_prefix, expected in ((False, U), (True, S)):
            fixture = WindowTest()
            fixture.setUp()
            try:
                grant = fixture.started("inv_prefixr2001")
                fixture.page(grant, "obs_prefixr2002", {**find_request("q", cursors={"crossref": "next"}), "page": 2})
                if add_prefix:
                    fixture.page(grant, "obs_prefixr2001", find_request("q"), end="continuation", next_cursor="next")
                fixture.committed(grant)
                inv = fixture.router.evidence_inventory(TOPIC, history="native")
                revision, protocol = fixture.rows("SELECT revision, protocol_revision FROM contract_revisions WHERE topic_id = ? AND status = 'approved'", TOPIC)[0]
                result = s.coverage(s.Context(TOPIC, revision, protocol), "coverage", inv, (s.WindowPin(grant["invocation_id"], revision),), 1)
                self.assertEqual(result.state, expected)
            finally:
                fixture.tearDown()
                fixture.doCleanups()
