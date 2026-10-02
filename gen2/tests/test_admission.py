"""The observation admission contract, at the router and at the store alike (task 2b-repair-13d; Astra R13B-2).

The 13b review found that the checks compared assertions with each other and left what an end needs undefined: a complete
exhausted page with no capture acknowledgement, a missing or invented request type, the `exhausted` sentinel as a cursor, an end
claimed by a page nothing was read from, and a cursor domain the router and the store drew differently. The contract
(gen2/router/boundary.py `check_page_outcome`; INVARIANTS RG-4, E-2; gen2/router/README.md) is one set of rules, held by the
router and by the store's CHECKs alike, over the one vocabulary of gen2/core/pagination.py:

  * the request names its type from a closed set;
  * only a request that pages (a find) can be an exhausted, a continuation or a limit_reached; every other type says end_unknown;
  * a page read whole, an exhausted end among them, names the gateway's durable row of its request (gateway_call_ref);
  * a page nothing was read from ends nothing;
  * a cursor is an integer in 0..2^53-1 or 1..8000 characters, none NUL, that is not the sentinel.

Every case is ONE document with a hand-written verdict (the cases are written out here, not read from the code under test). The same
cases are put to the router (`AtTheRouter`: through `record_observation`, and a refusal must be the router's own, not the store's CHECK
behind it), to the store (`AtTheStore`: the same document as a direct INSERT) and, for cursors, to the client's reading of a `next`
(`AtTheClient`): each layer must give the verdict by itself, so a rule held by one and not the other, or drawn differently, fails here,
and a mutant of either layer is killed by its own class. What the contract does not establish — that an asserted outcome is the one the
gateway's answer implied — is not tested as if it were: `TheTrustModel` says so.
"""
from __future__ import annotations

import itertools
import json
import re
import sqlite3
import unittest
from pathlib import Path

from gen2.core import canonical
from gen2.gateway_client import client, observe
from gen2.router import boundary, service
from gen2.router.boundary import Refusal
from gen2.tests.router_fixtures import RouterTestCase, find_request
from gen2.tests.store_fixtures import TOPIC, StoreTestCase

INV = "inv_discover1"
DDL = (Path(__file__).resolve().parents[1] / "store" / "schema" / "03-evidence-and-decisions.sql").read_text(encoding="utf-8")
REQUEST_TYPES = ("find", "resolve", "enrich", "fetch", "data")   # written out, not read from the code under test (OneVocabulary holds them equal)
PAGED = ("find",)
NON_PAGED = ("resolve", "enrich", "fetch", "data")
UNREAD = dict(state="provider_unavailable", completeness="unobserved", count=None, error="provider_outage", call=None)
CURSORS_OK = (("a short string", "c2"), ("a digit string", "0"), ("zero", 0), ("one", 1), ("the JSON bound", 2 ** 53 - 1), ("8000 characters", "x" * 8000),
              ("8000 characters, two bytes each", "é" * 8000), ("8000 characters outside the BMP", "\U0001f600" * 8000), ("the sentinel's case", "Exhausted"),
              ("the sentinel with company", "exhausted "), ("a prefix of the sentinel", "exhaust"), ("one space", " "))
CURSORS_REFUSED = (("the sentinel", "exhausted"), ("an empty string", ""), ("a negative integer", -1), ("a very negative integer", -2 ** 53),
                   ("one beyond the JSON bound", 2 ** 53), ("two beyond it", 2 ** 53 + 1), ("far beyond it", 10 ** 20), ("true", True), ("false", False),
                   ("a fraction", 1.5), ("8001 characters", "x" * 8001), ("8001 two-byte characters", "é" * 8001),
                   ("8001 characters outside the BMP", "\U0001f600" * 8001), ("NUL", "\x00"), ("NUL inside", "a\x00b"), ("NUL, 8000 times", "\x00" * 8000),
                   ("a list", ["c2"]), ("an object", {"cursor": "c2"}))


def page(kind: str = "find", *, outcome: str = "end_unknown", cursor=None, state: str = "searched_ok", completeness: str = "complete", count: int | None = 1,
         error: str | None = None, call: str | None = "gw-call:1", request=None, continuation="default") -> dict:
    """An observation document: a find page read whole unless said otherwise, differing from the valid one only as its arguments say."""
    return {"request": request if request is not None else find_request(request_type=kind), "coverage_state": state, "completeness": completeness,
            "result_count": count, "error_class": error, "gateway_call_ref": call, "page_outcome": outcome,
            "continuation": ({"cursor": cursor} if cursor is not None else None) if continuation == "default" else continuation}


def typed(kind) -> dict:
    return find_request("q", request_type=kind)


class Cases:
    """The contract as cases (a mixin: the concrete classes below put every document to ONE layer; `verdicts` is theirs)."""

    def parts(self, doc: dict) -> tuple[dict, list[dict]]:
        n = next(self.counter)
        events = [{"event_id": f"rev_{n:012d}{i:04d}", "provider_record_id": f"rec-{n}-{i}", "rank": i + 1, "captured_at": "2026-09-27T10:00:04Z"}
                  for i in range(doc["result_count"] or 0)]
        full = {"observation_id": f"obs_{n:012d}", "request": doc["request"], "request_identity": canonical.logical_hash(doc["request"]), "attempt": n,
                "lane": "crossref", "obligation_ids": [], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:05Z",
                "coverage_state": doc["coverage_state"], "result_count": doc["result_count"], "completeness": doc["completeness"],
                "error_class": doc["error_class"], "capability_fact_id": None, "policy_version": "gw-policy/1", "cost_units": None,
                "gateway_call_ref": doc["gateway_call_ref"], "page_outcome": doc["page_outcome"], "continuation": doc["continuation"]}
        return full, events

    def test_the_request_names_its_type_from_a_closed_set(self) -> None:
        for kind in REQUEST_TYPES:
            self.verdicts(f"a {kind} request", page(kind, request=typed(kind)), True)
        for label, request in (("no inner request", {"lane": "crossref", "page": 1}), ("no request type", {"lane": "crossref", "page": 1, "request": {"query": "q"}}),
                               ("an invented type", typed("invented")), ("a type's case", typed("FIND")), ("a type with company", typed("find ")),
                               ("a number", typed(5)), ("null", typed(None)), ("a list", typed(["find"])), ("an empty string", typed("")),
                               ("the request not an object", {"lane": "crossref", "page": 1, "request": "find"}),
                               ("the request a list", {"lane": "crossref", "page": 1, "request": ["find"]}),
                               ("an untyped query", {"lane": "crossref", "query": "intake latency", "cursor": None}), ("an empty request", {})):
            self.verdicts(label, page(request=request), False)

    def test_only_a_request_that_pages_can_report_an_end_or_a_continuation(self) -> None:
        """end_unknown means "paged, end unknown" for a find and "does not page" for the rest, which say nothing else."""
        for kind in REQUEST_TYPES:
            self.verdicts(f"{kind}: an unknown end", page(kind, outcome="end_unknown", request=typed(kind)), True)
            self.verdicts(f"{kind}: unreadable", page(kind, request=typed(kind), outcome="failed", **UNREAD), True)
        for kind in PAGED:
            self.verdicts(f"{kind}: an end", page(kind, outcome="exhausted", request=typed(kind)), True)
            self.verdicts(f"{kind}: a continuation", page(kind, outcome="continuation", cursor="c2", request=typed(kind)), True)
            self.verdicts(f"{kind}: a page cap", page(kind, outcome="limit_reached", cursor=20, request=typed(kind)), True)
        for kind in NON_PAGED:
            self.verdicts(f"{kind}: an end", page(kind, outcome="exhausted", request=typed(kind)), False)
            self.verdicts(f"{kind}: a continuation", page(kind, outcome="continuation", cursor="c2", request=typed(kind)), False)
            self.verdicts(f"{kind}: a page cap", page(kind, outcome="limit_reached", cursor=20, request=typed(kind)), False)

    def test_a_page_read_whole_names_the_gateways_durable_row_of_its_request(self) -> None:
        """An answer the gateway did not capture is at most a partial lower bound (RG-4, E-2): complete needs the row, and so does an end."""
        self.verdicts("complete, captured", page(), True)
        self.verdicts("complete, captured, an end", page(outcome="exhausted"), True)
        self.verdicts("complete, no capture", page(call=None), False)
        self.verdicts("complete, no capture, an end", page(outcome="exhausted", call=None), False)
        self.verdicts("complete, no capture, a continuation", page(outcome="continuation", cursor="c2", call=None), False)
        self.verdicts("complete, an empty acknowledgement", page(call=""), False)
        self.verdicts("complete, empty, an end", page(state="searched_empty", count=0, outcome="exhausted", call=""), False)
        self.verdicts("a lower bound with no capture", page(completeness="partial", error="telemetry_missing", call=None), True)
        self.verdicts("a lower bound with one", page(completeness="partial", error="partial_pagination"), True)
        self.verdicts("unread, no capture", page(outcome="failed", **UNREAD), True)
        self.verdicts("not searched, no capture", page(state="not_searched", completeness="unobserved", count=None, call=None), True)

    def test_a_page_nothing_was_read_from_ends_nothing(self) -> None:
        """No exhausted unobserved lane, whatever coverage it reports (a lane restating an end earlier reported included)."""
        for state in ("not_searched", "exhausted"):
            unobserved = dict(state=state, completeness="unobserved", count=None, call=None)
            self.verdicts(f"{state}: no end", page(**unobserved), True)
            self.verdicts(f"{state}: no end, captured", page(**{**unobserved, "call": "gw-call:1"}), True)
            self.verdicts(f"{state}: an end", page(outcome="exhausted", **unobserved), False)
            self.verdicts(f"{state}: an end, captured", page(outcome="exhausted", **{**unobserved, "call": "gw-call:1"}), False)
            self.verdicts(f"{state}: a continuation", page(outcome="continuation", cursor="c2", **unobserved), False)
        self.verdicts("a partial page's end", page(completeness="partial", error="partial_pagination", outcome="exhausted"), False)

    def test_the_cursor_domain_is_one(self) -> None:
        """The same rules at the router, the store and the client: an integer 0..2^53-1, or 1..8000 characters, none NUL, that is not the
        sentinel; and in particular empty, negative, beyond-the-bound, boolean, fractional and structured values are no cursor."""
        for outcome in ("continuation", "limit_reached"):
            for label, cursor in CURSORS_OK:
                self.verdicts(f"{outcome}: {label}", page(outcome=outcome, cursor=cursor), True)
            for label, cursor in CURSORS_REFUSED:
                self.verdicts(f"{outcome}: {label}", page(outcome=outcome, cursor=cursor, continuation={"cursor": cursor}), False)


class AtTheRouter(Cases, RouterTestCase):
    """Every case put to `record_observation`. A refusal must be the router's own (its schema or its boundary), not the store's CHECK
    behind it: each layer holds the contract by itself."""

    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()
        self.grant = self.started(INV, "discovery")
        self.counter = itertools.count(1)

    def verdicts(self, label: str, doc: dict, admitted: bool) -> None:
        full, events = self.parts(doc)
        out = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV, "observation": full, "retrieval_events": events})
        with self.subTest(label):
            if admitted:
                self.assertEqual(out["status"], "recorded", f"{label}: the router should admit it: {out}")
            else:
                self.assertEqual(out["status"], "refused", f"{label}: the router should refuse it")
                self.assertNotIn("the store refused the write", out["detail"], f"{label}: the router let it through to the store's CHECK")


class AtTheStore(Cases, StoreTestCase):
    """Every case as one INSERT (what the router's writer would send), straight at the store's CHECKs."""

    def setUp(self) -> None:
        super().setUp()
        self.lease("lease_aaaaaaaa", 1)
        self.invocation("inv_pppppppp")
        self.counter = itertools.count(1)

    def verdicts(self, label: str, doc: dict, admitted: bool) -> None:
        full, _ = self.parts(doc)
        row = {**full, "invocation_id": "inv_pppppppp", "topic_id": TOPIC, "request": json.dumps(full["request"]), "obligation_ids": "[]",
               "continuation": None if full["continuation"] is None else json.dumps(full["continuation"])}
        columns = sorted(row)
        sql = f"INSERT INTO search_observations ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})"
        with self.subTest(label):
            if admitted:
                self.x(sql, *[row[c] for c in columns])
            else:
                with self.assertRaises(sqlite3.IntegrityError, msg=f"{label}: the store should refuse it"):
                    self.x(sql, *[row[c] for c in columns])


class AtTheClient(unittest.TestCase):
    """The client reads a `next` by the same domain: what the router and the store keep is what it follows, and no other."""

    def test_the_client_reads_a_next_by_the_same_domain(self) -> None:
        for label, cursor in CURSORS_OK:
            with self.subTest(label):
                self.assertEqual(observe.cursor_of({"next": cursor}), cursor)
        for label, cursor in CURSORS_REFUSED:
            with self.subTest(label):
                self.assertIsNone(observe.cursor_of({"next": cursor}), "a `next` that is no cursor is no continuation")
        self.assertIsNone(observe.cursor_of({}))


class TheBoundaryAlone(unittest.TestCase):
    """What the router's own checks refuse when called directly (the command schema is not in front of them)."""

    def check(self, **changes) -> None:
        doc = {**self.valid(), **changes}
        boundary.check_observation(doc, [{"provider_record_id": "rec-1"}] if doc["result_count"] else [])

    def valid(self, **sent) -> dict:
        request = find_request(**sent)
        return {"observation_id": "obs_000000000001", "request": request, "request_identity": canonical.logical_hash(request), "ended_at": None,
                "started_at": "2026-09-27T10:00:00Z", "coverage_state": "searched_ok", "completeness": "complete", "result_count": 1,
                "gateway_call_ref": "gw-call:1", "page_outcome": "end_unknown", "continuation": None}

    def refused(self, detail: str, **changes) -> None:
        with self.assertRaises(Refusal) as caught:
            self.check(**changes)
        self.assertIn(detail, caught.exception.detail)

    def test_the_request_discriminator(self) -> None:
        self.check()
        for request in ({"lane": "crossref", "page": 1}, {"lane": "crossref", "page": 1, "request": {}}, typed("invented"), typed(5)):
            with self.subTest(request):
                self.refused("names no type", request=request, request_identity=canonical.logical_hash(request))

    def test_a_request_that_does_not_page_has_only_an_unknown_end(self) -> None:
        for kind in NON_PAGED:
            request = typed(kind)
            for changes in ({"page_outcome": "exhausted"}, {"page_outcome": "continuation", "continuation": {"cursor": "c2"}},
                            {"page_outcome": "limit_reached", "continuation": {"cursor": 20}}):
                with self.subTest(kind=kind, **changes):
                    self.refused("does not page", request=request, request_identity=canonical.logical_hash(request), **changes)
            self.check(request=request, request_identity=canonical.logical_hash(request))

    def test_a_page_read_whole_names_its_capture(self) -> None:
        self.refused("durable row", gateway_call_ref=None)
        self.refused("durable row", gateway_call_ref="")
        self.refused("durable row", gateway_call_ref=None, page_outcome="exhausted")
        self.check(gateway_call_ref=None, completeness="partial", error_class="telemetry_missing")

    def test_a_page_nothing_was_read_from_reports_no_end(self) -> None:
        for state in ("not_searched", "exhausted"):
            with self.subTest(state):
                self.refused("read whole", coverage_state=state, completeness="unobserved", result_count=None, gateway_call_ref=None, page_outcome="exhausted")
                self.check(coverage_state=state, completeness="unobserved", result_count=None, gateway_call_ref=None)

    def test_the_cursor_domain(self) -> None:
        for label, cursor in CURSORS_REFUSED:
            if isinstance(cursor, (dict, list, float)):
                continue   # a shape the command schema holds; the boundary reads cursors that came through it
            with self.subTest(label):
                self.refused("", page_outcome="continuation", continuation={"cursor": cursor})
        for label, cursor in CURSORS_OK:
            with self.subTest(label):
                self.check(page_outcome="limit_reached", continuation={"cursor": cursor})


class OneVocabulary(unittest.TestCase):
    """The router's schema, the client and the store's DDL each repeat the closed sets of gen2/core/pagination.py; they are held equal to the
    sets written out above (and so to each other)."""
    OUTCOMES = ("exhausted", "continuation", "end_unknown", "limit_reached", "failed")

    def test_the_shared_module_is_the_written_out_vocabulary(self) -> None:
        from gen2.core import pagination
        self.assertEqual((pagination.REQUEST_TYPES, pagination.PAGED_REQUEST_TYPES, pagination.PAGE_OUTCOMES, pagination.PAGING_OUTCOMES,
                          pagination.CURSOR_MAX_CHARS, pagination.EXHAUSTED_CURSOR),
                         (REQUEST_TYPES, PAGED, self.OUTCOMES, ("exhausted", "continuation", "limit_reached"), 8000, "exhausted"))

    def test_the_command_schema_names_the_same_outcomes(self) -> None:
        schema = service.COMMANDS["$defs"]["observation"]["properties"]["observation"]["properties"]
        self.assertEqual(schema["page_outcome"]["enum"], list(self.OUTCOMES))

    def test_the_client_sends_the_same_request_types(self) -> None:
        self.assertEqual(client.REQUEST_TYPES, REQUEST_TYPES)

    def test_the_store_names_the_same_types_outcomes_and_cursor_bounds(self) -> None:
        listed = lambda text: re.findall(r"'([a-z_]+)'", text)   # noqa: E731
        types = re.search(r"request_type'\) IN \(([^)]*)\)", DDL)
        outcomes = re.search(r"page_outcome TEXT NOT NULL CHECK \(page_outcome IN \(([^)]*)\)", DDL)
        self.assertEqual(listed(types.group(1)), list(REQUEST_TYPES))
        self.assertEqual(listed(outcomes.group(1)), list(self.OUTCOMES))
        self.assertIn(f"BETWEEN 0 AND {canonical.INT_BOUND}", DDL)
        self.assertIn("BETWEEN 1 AND 8000", DDL)
        self.assertIn("!= 'exhausted'", DDL)
        paged = re.search(r"CHECK \(page_outcome IN \(([^)]*)\) OR json_extract\(request, '\$\.request\.request_type'\) = '([a-z]+)'\)", DDL)
        self.assertEqual((set(listed(paged.group(1))), (paged.group(2),)), ({"end_unknown", "failed"}, PAGED))


class TheTrustModel(RouterTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.to_scoping()
        self.grant = self.started(INV, "discovery")

    def test_a_relabelled_outcome_is_not_detected_here(self) -> None:
        """What the contract does NOT establish, stated as a test so it is not mistaken for a guarantee (INVARIANTS E-2; gen2/router/README.md,
        "What an observation command is trusted for"): the router sees the command, never the gateway's reply. A well-formed command from trusted
        station code that says `exhausted` for a page the gateway's reply left open is admitted, because nothing in it says otherwise; it carries
        what the audit needs to catch it (the capture's reference, and the request), and the state-integrity audit's re-derivation from the
        captured raw evidence is what does."""
        request = find_request()
        honest = {"observation_id": "obs_000000000001", "request": request, "request_identity": canonical.logical_hash(request), "attempt": 1, "lane": "crossref",
                  "obligation_ids": [], "started_at": "2026-09-27T10:00:00Z", "ended_at": "2026-09-27T10:00:05Z", "coverage_state": "searched_ok",
                  "result_count": 1, "completeness": "complete", "error_class": None, "capability_fact_id": None, "policy_version": "gw-policy/1",
                  "cost_units": None, "gateway_call_ref": "gw-call:1", "page_outcome": "limit_reached", "continuation": {"cursor": "c2"}}
        relabelled = {**honest, "page_outcome": "exhausted", "continuation": None}
        events = [{"event_id": "rev_000000000001", "provider_record_id": "rec-1", "rank": 1, "captured_at": "2026-09-27T10:00:04Z"}]
        out = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV, "observation": relabelled, "retrieval_events": events})
        self.assertEqual(out["status"], "recorded")
        self.assertEqual(self.rows("SELECT page_outcome, continuation, gateway_call_ref FROM search_observations"), [("exhausted", None, "gw-call:1")])
        again = self.router.record_observation({"capability_id": self.grant["capability_id"], "invocation_id": INV, "observation": honest, "retrieval_events": events})
        self.assertEqual((again["status"], again.get("reason")), ("refused", "observation_id_conflict"), "the honest command then conflicts with the first record")


if __name__ == "__main__":
    unittest.main()
