"""Phase 8c/8d acceptance (gateway docs/STATION-CONTRACT.md): topic research policy on
the queue item, research blockers from iteration coverage, the one saturation/DONE
condition, and the activity-file summarizer the chassis result writer uses."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from research_loops.queue import QueueError, QueueStore
from research_loops.runner import saturation_decision

_spec = importlib.util.spec_from_file_location(
    "research_activity", Path(__file__).resolve().parent.parent / "research_loops" / "chassis" / "research_activity.py")
research_activity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(research_activity)


def store(tmp):
    return QueueStore(Path(tmp) / "state" / "queue.json")


def add_item(s, item_id="topic-a", **kw):
    return s.add(title="T", cwd="/tmp", command=["true"], item_id=item_id,
                 repeat_seconds=900, **kw)


class ResearchPolicy(unittest.TestCase):
    def test_policy_is_validated_and_stored(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s, research_policy={"commercial": True, "domain": "finance"})
            self.assertEqual(item["research_policy"], {"commercial": True, "domain": "finance"})
            self.assertEqual(item["research_blockers"], [])
            for bad in ({"commercial": "yes"}, {"unknown_field": 1}, {"domain": True}, "not-a-dict"):
                with self.assertRaises(QueueError, msg=bad):
                    s.set_research_policy(item["id"], bad)
            updated = s.set_research_policy(item["id"], {"accept_per_item": True})
            self.assertEqual(updated["research_policy"], {"accept_per_item": True})
            self.assertIsNone(s.set_research_policy(item["id"], None)["research_policy"],
                              "clearing unbinds the policy")


class Blockers(unittest.TestCase):
    def test_blocking_states_add_and_successes_clear(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            out = s.update_research_blockers(item["id"], failures=[
                {"source": "crossref", "coverage": "provider_unavailable"},
                {"source": "semanticscholar", "coverage": "auth_failed"},
                {"source": "fred", "coverage": "not_searched"},       # policy skip, never a blocker
                {"source": "hf", "coverage": "metadata_only"},        # partial, never a blocker
            ], cleared=[])
            self.assertEqual(out, ["crossref", "semanticscholar"])
            out = s.update_research_blockers(item["id"], failures=[], cleared=["crossref"])
            self.assertEqual(out, ["semanticscholar"], "a source that answers again clears itself")

    def test_operator_resume_clears_blockers(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            s.update_research_blockers(item["id"], failures=[
                {"source": "crossref", "coverage": "auth_failed"}], cleared=[])
            s.pause_item(item["id"])
            resumed = s.resume_item(item["id"])
            self.assertEqual(resumed["research_blockers"], [],
                             "resume is the sanctioned alternative-evidence override")

    def test_completion_coverage_stamp(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            stamped = s.record_completion_coverage(item["id"], {"at": "x", "blockers": [],
                                                                "sources_ok_final_pass": ["crossref"]})
            self.assertEqual(stamped["completion_coverage"]["sources_ok_final_pass"], ["crossref"])


class SaturationDecision(unittest.TestCase):
    def test_the_acceptance_case_a_blocked_pass_never_completes(self):
        """Plan 8d: one pass short of saturation, required-source failure, no semantic
        change → the topic does NOT complete."""
        streak, verdict = saturation_decision(signature_changed=False, previous_streak=2, limit=3,
                                              blocked_this_pass=True, blockers=["crossref"])
        self.assertEqual((streak, verdict), (2, "continue"),
                         "a blocked pass pauses the streak instead of advancing it")

    def test_clean_passes_advance_and_complete(self):
        self.assertEqual(saturation_decision(signature_changed=False, previous_streak=2, limit=3,
                                             blocked_this_pass=False, blockers=[]), (3, "complete"))
        self.assertEqual(saturation_decision(signature_changed=False, previous_streak=0, limit=3,
                                             blocked_this_pass=False, blockers=[]), (1, "continue"))

    def test_semantic_change_resets_even_when_blocked(self):
        self.assertEqual(saturation_decision(signature_changed=True, previous_streak=2, limit=3,
                                             blocked_this_pass=True, blockers=["x"]), (0, "continue"))

    def test_lingering_blockers_hold_completion_at_the_limit(self):
        streak, verdict = saturation_decision(signature_changed=False, previous_streak=3, limit=3,
                                              blocked_this_pass=False, blockers=["semanticscholar"])
        self.assertEqual(verdict, "held",
                         "an unresolved blocker holds DONE until it clears or the operator resumes")


class ActivitySummarizer(unittest.TestCase):
    def test_reduces_to_distinct_failures_and_ok_sources(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "activity.jsonl"
            lines = [
                {"source": "crossref", "coverage": "provider_unavailable"},
                {"source": "crossref", "coverage": "provider_unavailable"},   # duplicate collapses
                {"source": "doaj", "coverage": "searched_empty"},
                {"source": "openalex_snapshot", "coverage": "searched_ok"},
                {"source": "fred", "coverage": "not_searched"},
                "not json at all",
                {"coverage": "searched_ok"},                                   # no source: ignored
            ]
            path.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines) + "\n")
            failures, ok = research_activity.summarize(str(path))
        self.assertEqual(failures, [{"source": "crossref", "coverage": "provider_unavailable"},
                                    {"source": "fred", "coverage": "not_searched"}])
        self.assertEqual(ok, ["doaj", "openalex_snapshot"])

    def test_missing_file_is_no_signal_never_an_error(self):
        self.assertEqual(research_activity.summarize("/nope/nothing.jsonl"), ([], []))
        self.assertEqual(research_activity.summarize(None), ([], []))


if __name__ == "__main__":
    unittest.main()
