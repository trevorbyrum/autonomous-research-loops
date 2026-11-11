"""Rule: v7 §4 negative-oracle conjunction and §5 reported-or-unknown usage.

Oracle: hand-authored logs/events beside one positive; every refusal changes one
operand of that positive. The usage record is checked against the shared schema.
Limit: hand-written Codex events, not captured runner output (Q11/Q12 own that).
"""
import json
import unittest

from gen2.router.schemas import SchemaSet
from gen2.supervisor import rejection as r
from gen2.supervisor.isolation import LiveProfileRefused

ROW = {"v": 3, "id": "rid1", "src": "172.31.254.3", "port": "40000", "conn": "1", "ordinal": "1", "listener": "model",
       "server_port": "8080", "method": "POST", "route": "model", "upstream": "172.31.252.3:8081", "status": "401",
       "upstream_status": "401", "complete": "OK", "at": "1.5"}
FIXTURE = {"v": 1, "requests": [{"id": "rid1", "route": "/v1/responses", "model": "gpt-5.4", "credential": "rejected"}]}
IDENTITY = {"invocation_id": "inv_trial0001", "kind": "research", "topic": "t", "run_id": "trial-1", "attempt": 1}


def jl(*rows):
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


FAILED = jl({"type": "thread.started"}, {"type": "turn.started"}, {"type": "turn.failed", "error": {"message": "401"}})


class Classifier(unittest.TestCase):
    def verdict(self, access=None, events=FAILED, fixture=None, code=1):
        access = jl(ROW) if access is None else access
        fixture = json.dumps(FIXTURE).encode() if fixture is None else fixture
        return r.classify(access, events, fixture, code, model="gpt-5.4")

    def test_conjunction_and_each_single_operand_refusal(self):
        self.assertEqual(self.verdict(), {"disposition": "credentials_rejected", "reason": "relay_401"})
        bad_fixture = lambda **kw: json.dumps({**FIXTURE, "requests": [{**FIXTURE["requests"][0], **kw}]}).encode()
        cases = {
            "missing log": dict(access=b""),
            "extra request": dict(access=jl(ROW, {**ROW, "id": "rid2"})),
            "text 401 only": dict(access=jl({**ROW, "upstream_status": "-"})),
            "local 401": dict(access=jl({**ROW, "upstream": "-", "upstream_status": "-"})),
            "wrong source": dict(access=jl({**ROW, "src": "172.31.254.9"})),
            "second ordinal": dict(access=jl({**ROW, "ordinal": "2"})),
            "not complete": dict(access=jl({**ROW, "complete": ""})),
            "malformed": dict(access=b"{not json}\n"),
            "unterminated": dict(access=jl(ROW)[:-1]),
            "duplicate key": dict(access=jl(ROW).replace(b'"v": 3', b'"v": 3, "v": 3')),
            "unknown key": dict(access=jl({**ROW, "extra": "x"})),
            "missing key": dict(access=jl({k: v for k, v in ROW.items() if k != "at"})),
            "non-string field": dict(access=jl({**ROW, "status": 401})),
            "wrong version": dict(access=jl({**ROW, "v": 2})),
            "duplicate id": dict(access=jl(ROW, ROW)),
            "completed turn": dict(events=jl({"type": "turn.completed", "usage": {}})),
            "prior tool": dict(events=jl({"type": "item.completed", "item": {}}, {"type": "turn.failed"})),
            "no failed turn": dict(events=jl({"type": "turn.started"})),
            "exit 0": dict(code=0),
            "fixture other id": dict(fixture=bad_fixture(id="rid9")),
            "fixture accepted": dict(fixture=bad_fixture(credential="accepted")),
            "fixture other model": dict(fixture=bad_fixture(model="gpt-5.5")),
            "fixture missing": dict(fixture=b"not json"),
            "fixture two requests": dict(fixture=json.dumps({**FIXTURE, "requests": FIXTURE["requests"] * 2}).encode()),
        }
        for name, operands in cases.items():
            with self.subTest(name):
                self.assertEqual(self.verdict(**operands)["disposition"], "unknown")

    def test_known_transport_failures_are_never_credential_facts(self):
        for status in ("429", "504"):
            with self.subTest(status):
                self.assertEqual(self.verdict(access=jl({**ROW, "status": status, "upstream_status": status}))["disposition"], "transport_failed")

    def test_bounds(self):
        big = jl({"type": "turn.failed", "pad": "x" * (64 << 10)})
        self.assertEqual(self.verdict(events=big)["reason"], "events_bound")
        self.assertEqual(self.verdict(access=jl(*[{**ROW, "id": str(i)} for i in range(1025)]))["reason"], "access_bound")


class RealRoute(unittest.TestCase):
    """The real lane: no fixture, the plan's upstream, and a fixture label can never stand for real provenance."""
    REAL = {**ROW, "upstream": "203.0.113.7:443"}

    def verdict(self, route="real", fixture=None, upstream="203.0.113.7:443", access=None):
        return r.classify(jl(self.REAL) if access is None else access, FAILED, fixture, 1, model="gpt-5.4", route=route, upstream=upstream)

    def test_a_real_route_row_against_the_plans_upstream_with_no_fixture_is_a_rejection(self):
        self.assertEqual(self.verdict(), {"disposition": "credentials_rejected", "reason": "relay_401"})

    def test_each_operand_that_is_wrong_for_the_route_is_unknown(self):
        for name, args in {"a fixture given on a real route": dict(fixture=json.dumps(FIXTURE).encode()), "no upstream in the plan": dict(upstream=None),
                           "another upstream": dict(upstream="203.0.113.8:443"), "the fixture's upstream": dict(access=jl(ROW)),
                           "a fixture route with no fixture": dict(route="fixture"), "an unknown route": dict(route="magic")}.items():
            with self.subTest(name):
                self.assertEqual(self.verdict(**args)["disposition"], "unknown")

    def test_a_real_run_records_the_model_as_unknown_with_the_configured_string_kept_as_configured(self):
        record = r.usage_record(IDENTITY, b"", elapsed=1, gateway_refs=[], raw_refs=[], observed_model=None, configured_model="gpt-5.4", observed=False)
        self.assertEqual(record["model"], {"state": "unknown", "configured": "gpt-5.4"})
        with self.assertRaisesRegex(LiveProfileRefused, "usage_model_mismatch"):   # a known mismatch still refuses
            r.usage_record(IDENTITY, b"", elapsed=1, gateway_refs=[], raw_refs=[], observed_model="gpt-5.5", configured_model="gpt-5.4", observed=False)
        with self.assertRaisesRegex(LiveProfileRefused, "usage_model_mismatch"):   # the fixture route still needs the observed model
            r.usage_record(IDENTITY, b"", elapsed=1, gateway_refs=[], raw_refs=[], observed_model=None, configured_model="gpt-5.4")


class Usage(unittest.TestCase):
    schemas = SchemaSet()

    def record(self, events, **kw):
        args = dict(elapsed=1.5, gateway_refs=["g1"], raw_refs=["sha256:a"], observed_model="gpt-5.4", configured_model="gpt-5.4")
        return r.usage_record(IDENTITY, events, **{**args, **kw})

    def test_reported_or_unknown_and_schema(self):
        done = jl({"type": "turn.completed", "usage": {"input_tokens": 11, "cached_input_tokens": 3, "output_tokens": 7}})
        record = self.record(done)
        self.assertEqual(self.schemas.errors(record["usage"], "live-vocabulary.schema.json#/$defs/usage"), [])
        usage = record["usage"]
        self.assertEqual([usage[k]["value"] for k in ("input_tokens", "output_tokens", "cached_tokens")], [11, 7, 3])
        self.assertEqual((usage["cost"]["state"], usage["gateway_credits"]["state"], usage["elapsed_seconds"]["value"]), ("unknown", "unknown", 1.5))
        self.assertEqual((record["gateway_refs"], record["raw_refs"], record["invocation_id"]), (["g1"], ["sha256:a"], "inv_trial0001"))

    def test_absent_zero_duplicate_and_malformed_are_unknown_never_zero(self):
        one = {"type": "turn.completed", "usage": {"input_tokens": 0, "output_tokens": True}}
        cases = {"zero or bool": jl(one), "absent": jl({"type": "turn.completed"}), "none": b"",
                 "duplicate": jl(one, one), "malformed": b"{\n"}
        for name, events in cases.items():
            with self.subTest(name):
                usage = self.record(events, elapsed=None)["usage"]
                self.assertEqual(self.schemas.errors(usage, "live-vocabulary.schema.json#/$defs/usage"), [])
                self.assertTrue(all(usage[k]["state"] == "unknown" for k in usage), usage)

    def test_model_mismatch_refuses(self):
        with self.assertRaisesRegex(LiveProfileRefused, "usage_model_mismatch"):
            self.record(b"", observed_model="gpt-5.5")


if __name__ == "__main__":
    unittest.main()
