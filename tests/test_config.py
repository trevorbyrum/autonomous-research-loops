import tempfile
import unittest
from pathlib import Path

from research_loops.config import TopicSettings, load_config
from research_loops.queue import QueueError


class ConfigTests(unittest.TestCase):
    def _write(self, tmp: str, text: str) -> Path:
        path = Path(tmp) / "research-loops.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_defaults_apply_when_nothing_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "")
            config = load_config(path)
            self.assertEqual(config.workers, 1)
            self.assertEqual(config.poll_seconds, 1.0)
            self.assertEqual(config.idle_sleep, 5.0)
            self.assertEqual(config.for_topic("anything"), TopicSettings())

    def test_topic_override_layers_on_top_of_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                """
                workers = 3

                [defaults]
                gap_policy = "review"

                [topics.my-topic]
                max_attempts = 3
                gap_policy = "auto"
                gap_auto_limit = 5
                """,
            )
            config = load_config(path)
            self.assertEqual(config.workers, 3)
            resolved = config.for_topic("my-topic")
            self.assertEqual(resolved.max_attempts, 3)
            self.assertEqual(resolved.gap_policy, "auto")
            self.assertEqual(resolved.gap_auto_limit, 5)
            # A topic not named under [topics.*] falls back to [defaults] only.
            fallback = config.for_topic("untouched-topic")
            self.assertEqual(fallback.max_attempts, 5)
            self.assertEqual(fallback.gap_policy, "review")

    def test_repeat_seconds_and_agent_fields_are_rejected_as_station_config(self):
        # These were topic-config fields pre-refactor; mechanics now live
        # exclusively on stations (state/stations.json), so a TOML config
        # still carrying them must fail loudly rather than be silently
        # ignored (operator ruling 2026-09-09).
        for mechanics_key, value in (
            ("repeat_seconds", 900),
            ("agent_main", "claude"),
            ("agent_secondary", "codex exec"),
        ):
            with tempfile.TemporaryDirectory() as tmp:
                path = self._write(tmp, f'[defaults]\n{mechanics_key} = {value!r}\n')
                with self.assertRaises(QueueError) as ctx:
                    load_config(path)
                self.assertIn("station configuration", str(ctx.exception))

    def test_invalid_gap_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp, '[defaults]\ngap_policy = "sometimes"\n'
            )
            with self.assertRaises(QueueError):
                load_config(path)

    def test_negative_gap_auto_limit_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp, "[topics.t]\ngap_auto_limit = -1\n"
            )
            with self.assertRaises(QueueError):
                load_config(path)

    def test_internal_citations_defaults_off_and_layers_like_gap_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(
                tmp,
                "[defaults]\n"
                "internal_citations = false\n\n"
                "[topics.opted-in]\n"
                "internal_citations = true\n",
            )
            config = load_config(path)
            self.assertFalse(config.for_topic("untouched").internal_citations)
            self.assertTrue(config.for_topic("opted-in").internal_citations)

    def test_internal_citations_must_be_a_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, '[defaults]\ninternal_citations = "yes"\n')
            with self.assertRaises(QueueError):
                load_config(path)

    def test_zero_workers_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "workers = 0\n")
            with self.assertRaises(QueueError):
                load_config(path)

    def test_missing_file_raises_queue_error(self):
        with self.assertRaises(QueueError):
            load_config("/nonexistent/research-loops.toml")

    def test_invalid_toml_raises_queue_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, "this is not [valid toml")
            with self.assertRaises(QueueError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
