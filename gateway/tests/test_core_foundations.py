"""Phase 3 foundations: identity, secrets, canonical records, the metered client."""
import os
import unittest

from research_gateway.adapters.base import Client, FakeTransport, SourceUnavailable, check
from research_gateway.core import canonical, identity, secrets
from research_gateway.core.broker import Broker, RatePolicy


class Identity(unittest.TestCase):
    def test_doi_normalisation(self):
        for raw in ("https://doi.org/10.1000/ABC.DEF", "doi:10.1000/abc.def", "10.1000/abc.def.", " 10.1000/ABC.def, "):
            self.assertEqual(identity.normalize_doi(raw), "10.1000/abc.def")
        self.assertIsNone(identity.normalize_doi("not a doi"))
        self.assertIsNone(identity.normalize_doi(""))

    def test_issn_and_arxiv(self):
        self.assertEqual(identity.normalize_issn("12345678"), "1234-5678")
        self.assertEqual(identity.normalize_issn("1234-567x"), "1234-567X")
        self.assertIsNone(identity.normalize_issn("12-34"))
        self.assertEqual(identity.normalize_arxiv("arXiv:2301.10140v2"), "2301.10140")
        self.assertEqual(identity.normalize_arxiv("https://arxiv.org/abs/hep-th/9901001"), "hep-th/9901001")
        self.assertIsNone(identity.normalize_arxiv("10.1000/x"))

    def test_parse_and_canonical(self):
        self.assertEqual(identity.parse("10.1000/ABC"), ("doi", "10.1000/abc"))
        self.assertEqual(identity.parse("series:fred:GDP"), ("series", "fred:GDP"))
        self.assertEqual(identity.parse("AI:ML systems"), ("title", "ai ml systems"), "undeclared schemes are titles")
        self.assertEqual(identity.parse("Reranking: a survey")[0], "title")
        identity.register_schemes(["hf", "HTTPS", "bad scheme"])
        self.assertEqual(identity.parse("hf:owner/corpus"), ("hf", "owner/corpus"))
        self.assertEqual(identity.parse("https://doi.org/10.1000/x"), ("doi", "10.1000/x"))
        self.assertNotIn("https", identity.KNOWN_SCHEMES)
        self.assertEqual(identity.canonical("DOI:10.1000/ABC"), "doi:10.1000/abc")
        self.assertEqual(identity.canonical("Reranking: A Survey!"), "title:reranking a survey")
        self.assertEqual(identity.canonical("issn:12345678"), "issn:1234-5678")


class Secrets(unittest.TestCase):
    def test_env_backend(self):
        os.environ["RESEARCH_GATEWAY_SECRET_FRED"] = "abc"
        os.environ["RESEARCH_GATEWAY_SECRET_KAGGLE_USERNAME"] = "u"
        try:
            b = secrets.EnvBackend()
            self.assertEqual(b.get("fred"), "abc")
            self.assertEqual(b.get("kaggle", "username"), "u")
            self.assertIsNone(b.get("nope"))
        finally:
            del os.environ["RESEARCH_GATEWAY_SECRET_FRED"], os.environ["RESEARCH_GATEWAY_SECRET_KAGGLE_USERNAME"]

    def test_vault_backend_without_address_is_inert(self):
        b = secrets.VaultBackend(addr="")
        self.assertIsNone(b.get("anything"))

    def test_chain_prefers_first_hit(self):
        class A:
            def get(self, n, f=None):
                return None

        class B:
            def get(self, n, f=None):
                return "from-b"

        self.assertEqual(secrets.Chain(A(), B()).get("x"), "from-b")


class Canonical(unittest.TestCase):
    def test_make_record_shape_and_kind_check(self):
        r = canonical.make_record(identity="doi:10.1/x", kind="article", source_id="crossref", title="T",
                                  extra={"cited_by_count": 3, "raw": "ignored"}, raw={"a": 1})
        self.assertEqual(r["identity"], "doi:10.1/x")
        self.assertEqual(r["cited_by_count"], 3)
        self.assertEqual(r["raw"], {"a": 1}, "extra cannot overwrite reserved fields")
        with self.assertRaises(ValueError):
            canonical.make_record(identity="x", kind="novel", source_id="s")

    def test_year_from(self):
        self.assertEqual(canonical.year_from("2021-03-04T00:00:00Z"), 2021)
        self.assertEqual(canonical.year_from("published 1999"), 1999)
        self.assertIsNone(canonical.year_from("n/a"))


def make_client(policies=None, transport=None):
    broker = Broker(policies or {"src": RatePolicy(per_second=100)})
    return Client(broker=broker, transport=transport or FakeTransport(), contact_email="t@example.org", sleep=lambda s: None)


class MeteredClient(unittest.TestCase):
    def test_get_parses_json_and_logs(self):
        t = FakeTransport()
        t.add("GET", "https://api.example/items", body={"items": [1, 2, 3]}, headers={"X-RateLimit-Limit": "50"})
        c = make_client(transport=t)
        r = c.get("src", "find", "https://api.example/items", params={"q": "x", "skip": None}, query="x")
        self.assertTrue(r.ok)
        self.assertEqual(r.json["items"], [1, 2, 3])
        self.assertIn("q=x", t.calls[0][1])
        self.assertNotIn("skip", t.calls[0][1])
        self.assertEqual(t.calls[0][2]["User-Agent"], c.user_agent)
        self.assertEqual(len(c.log), 1)
        self.assertEqual(c.log[0].result_count, 3)
        self.assertEqual(c.log[0].ratelimit, {"x-ratelimit-limit": "50"})
        self.assertEqual(c.log[0].failure_class, "ok")

    def test_no_policy_is_refused_and_logged_not_sent(self):
        t = FakeTransport()
        c = make_client(transport=t)
        r = c.get("unregistered", "find", "https://api.example/x")
        self.assertFalse(r.ok)
        self.assertIn("NoPolicy", r.error)
        self.assertEqual(t.calls, [], "refused calls never reach the network (I-1/I-3)")
        self.assertEqual(c.log[0].failure_class, "refused")

    def test_429_storm_opens_breaker_and_subsequent_calls_are_refused(self):
        t = FakeTransport()
        t.add("GET", "https://api.example/x", status=429)
        clock = [1000.0]
        broker = Broker({"src": RatePolicy(per_second=100)}, clock=lambda: clock[0])
        c = Client(broker=broker, transport=t, contact_email="t@example.org",
                   sleep=lambda s: clock.__setitem__(0, clock[0] + s))  # backoff waits advance the fake clock
        for _ in range(3):
            c.get("src", "find", "https://api.example/x")
        self.assertEqual(len(t.calls), 3)
        self.assertEqual(clock[0], 1030.0, "10 s then 20 s backoff before the second and third attempts")
        r = c.get("src", "find", "https://api.example/x")
        self.assertIn("BreakerOpen", r.error)
        self.assertEqual(len(t.calls), 3, "breaker open: no network call")
        self.assertEqual([l.failure_class for l in c.log], ["quota", "quota", "quota", "refused"])

    def test_retry_after_is_honoured(self):
        t = FakeTransport()
        t.add("GET", "https://api.example/x", status=429, headers={"Retry-After": "600"})
        c = make_client(transport=t)
        c.get("src", "find", "https://api.example/x")
        r = c.get("src", "find", "https://api.example/x")
        self.assertIn("BreakerOpen", r.error)
        self.assertEqual(len(t.calls), 1)

    def test_redirects_are_validated_metered_and_stripped_of_credentials(self):
        """D-23: no hop is followed blindly. IP-literal locations keep the test off DNS."""
        t = FakeTransport()
        t.add("GET", "https://93.184.216.34/start", status=302, headers={"Location": "https://93.184.216.35/next"})
        t.add("GET", "https://93.184.216.35/next", body={"ok": 1})
        c = make_client(policies={"src": RatePolicy(per_second=100)}, transport=t)
        r = c.get("src", "find", "https://93.184.216.34/start", headers={"Authorization": "Bearer sekrit", "X-Api-Key": "k"})
        self.assertTrue(r.ok)
        self.assertEqual(len(t.calls), 2)
        self.assertIn("Authorization", t.calls[0][2])
        self.assertNotIn("Authorization", t.calls[1][2], "credentials never cross origins")
        self.assertNotIn("X-Api-Key", t.calls[1][2])
        self.assertEqual([rec.status for rec in c.log], [302, 200], "every hop is logged")

    def test_redirects_to_private_or_downgraded_destinations_are_refused(self):
        for location in ("http://93.184.216.34/x",      # https → http downgrade
                         "https://127.0.0.1/steal",     # loopback
                         "https://10.0.0.7/x",          # private range
                         "ftp://93.184.216.34/x"):      # non-http scheme
            t = FakeTransport()
            t.add("GET", "https://93.184.216.34/start", status=301, headers={"Location": location})
            c = make_client(policies={"src": RatePolicy(per_second=100)}, transport=t)
            r = c.get("src", "find", "https://93.184.216.34/start", headers={"X-Api-Key": "k"})
            self.assertFalse(r.ok, location)
            self.assertIn("redirect", r.error or "", location)
            self.assertEqual(len(t.calls), 1, f"the refused hop was never contacted: {location}")
            self.assertEqual(c.log[-1].failure_class, "refused")

    def test_real_transport_never_raises(self):
        from research_gateway.adapters.base import Transport
        r = Transport().request("GET", "http://127.0.0.1:9/none", {"User-Agent": "t"}, None, 0.5)
        self.assertIsNone(r.status)
        self.assertTrue(r.error, "a connect failure is an error Response, so the call row always exists (I-6)")

    def test_broken_call_log_fails_closed(self):
        """I-6/D-23: when the log cannot be written, nothing keeps dispatching unaudited."""
        from research_gateway.core import calllog

        class DeadConn:
            def cursor(self):
                raise RuntimeError("connection is closed")

            def rollback(self):
                pass

        t = FakeTransport()
        t.add("GET", "https://api.example/x", body={"ok": 1})
        c = make_client(transport=t)
        c.conn = DeadConn()
        with self.assertRaises(calllog.AuditError):
            c.get("src", "find", "https://api.example/x")

    def test_post_json(self):
        t = FakeTransport()
        t.add("POST", "https://api.example/batch", body=[{"id": 1}])
        c = make_client(transport=t)
        r = c.post("src", "resolve", "https://api.example/batch", body={"ids": ["a"]})
        self.assertTrue(r.ok)
        self.assertEqual(t.calls[0][3], b'{"ids": ["a"]}')
        self.assertEqual(t.calls[0][2]["Content-Type"], "application/json")

    def test_check_semantics(self):
        t = FakeTransport()
        t.add("GET", "https://api.example/missing", status=404)
        t.add("GET", "https://api.example/broken", status=500)
        c = make_client(transport=t)
        self.assertFalse(check("src", c.get("src", "resolve", "https://api.example/missing")))
        with self.assertRaises(SourceUnavailable):
            check("src", c.get("src", "resolve", "https://api.example/broken"))


if __name__ == "__main__":
    unittest.main()
