import unittest

from research_loops.runner import FailureKind, classify_failure, retry_delay


class FailurePolicyTests(unittest.TestCase):
    def test_subscription_limits_receive_long_nonfatal_backoff(self):
        kind = classify_failure(1, "You have hit your weekly usage limit; resets at 10:00 UTC")
        self.assertEqual(kind, FailureKind.SUBSCRIPTION_LIMIT)
        self.assertGreaterEqual(retry_delay(kind, 1), 1800)

    def test_provider_outages_back_off_exponentially_with_cap(self):
        kind = classify_failure(1, "HTTP 503 service temporarily unavailable")
        self.assertEqual(kind, FailureKind.OUTAGE)
        self.assertEqual(retry_delay(kind, 1), 60)
        self.assertEqual(retry_delay(kind, 20), 3600)

    def test_rate_limit_wording_is_not_misclassified_as_subscription_limit(self):
        kind = classify_failure(1, "You hit your rate limit; retry later")
        self.assertEqual(kind, FailureKind.RATE_LIMIT)
        self.assertEqual(retry_delay(kind, 1), 300)

    def test_429_wrapped_subscription_limit_is_still_subscription_limit(self):
        # Providers commonly return HTTP 429 for an exhausted subscription
        # window; the more specific pattern must win so the failure does not
        # consume the ordinary retry budget.
        kind = classify_failure(
            1, "HTTP 429: weekly usage limit reached; resets at 10:00 UTC"
        )
        self.assertEqual(kind, FailureKind.SUBSCRIPTION_LIMIT)
        delay = retry_delay(kind, 1)
        assert delay is not None
        self.assertGreaterEqual(delay, 1800)

    def test_auth_and_configuration_errors_require_attention(self):
        self.assertEqual(classify_failure(1, "401 unauthorized invalid API key"), FailureKind.AUTH)
        self.assertEqual(classify_failure(127, "command not found"), FailureKind.CONFIGURATION)

    def test_loop_entrypoint_exit_codes_map_to_operator_attention(self):
        # run-topic.sh contracts: 3 = STOP present, 4 = PAUSED present.
        # Adapter contracts: 64 = usage error, 78 = NEEDS-OPERATOR. None may retry.
        for code in (3, 4, 64, 78, 126):
            with self.subTest(code=code):
                kind = classify_failure(code, "no matching text at all")
                self.assertEqual(kind, FailureKind.CONFIGURATION)
                self.assertIsNone(retry_delay(kind, 1))

    def test_exit_5_is_not_a_configuration_error(self):
        # Exit 5 was the pre-2026-09 chassis's first-miss stall signal; mapping
        # it to CONFIGURATION parked contract-compliant discovery-only
        # iterations before the stall guard's stall_limit could apply.
        # The chassis no longer emits it; a stale chassis that still does must
        # fall through to tail classification and retry with backoff instead
        # of instantly parking.
        kind = classify_failure(5, "stalled: semantic state unchanged")
        self.assertEqual(kind, FailureKind.TRANSIENT)
        self.assertIsNotNone(retry_delay(kind, 1))

    def test_classification_scans_only_the_log_tail(self):
        # LLM research prose early in a long transcript must not classify the
        # exit; only the tail (where the entrypoint prints its error) counts.
        prose = "the paper notes requests timed out under 429 pressure. " * 400
        output = prose + "x" * 9000 + "\nfinal state: no recognizable error"
        self.assertEqual(classify_failure(1, output), FailureKind.TRANSIENT)
        tail_error = "filler " * 2000 + "HTTP 503 service unavailable"
        self.assertEqual(classify_failure(1, tail_error), FailureKind.OUTAGE)

    def test_success_is_not_classified_as_failure(self):
        self.assertEqual(classify_failure(0, "ok"), FailureKind.NONE)


if __name__ == "__main__":
    unittest.main()
