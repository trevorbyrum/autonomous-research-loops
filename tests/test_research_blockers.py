"""Phase 8c/8d acceptance (gateway docs/STATION-CONTRACT.md): topic research policy on
the queue item, REQUEST-KEYED research blockers from ordered coverage transitions, the
one saturation/DONE condition, explicit blocker resolution, and the activity-file
summarizer the chassis result writer uses."""
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


def failure(source, coverage, request_type="find", subject="q"):
    return {"key": research_activity.request_key(source, request_type, subject),
            "source": source, "request_type": request_type, "subject": subject, "coverage": coverage}


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
    def test_blocking_states_add_and_only_the_same_request_clears(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            out = s.update_research_blockers(item["id"], failures=[
                failure("crossref", "provider_unavailable", subject="query A"),
                failure("semanticscholar", "auth_failed", subject="query A"),
                failure("fred", "not_searched"),       # policy skip, never a blocker
                failure("hf", "metadata_only"),        # partial, never a blocker
            ], cleared=[])
            self.assertEqual(sorted(b["source"] for b in out), ["crossref", "semanticscholar"])
            unrelated = research_activity.request_key("crossref", "find", "a DIFFERENT query")
            out = s.update_research_blockers(item["id"], failures=[], cleared=[unrelated])
            self.assertEqual(sorted(b["source"] for b in out), ["crossref", "semanticscholar"],
                             "a success on an unrelated query never clears a blocker (finding 4)")
            same = research_activity.request_key("crossref", "find", "query A")
            out = s.update_research_blockers(item["id"], failures=[], cleared=[same])
            self.assertEqual([b["source"] for b in out], ["semanticscholar"],
                             "the SAME request succeeding clears its blocker")

    def test_ordinary_resume_preserves_blockers_and_resolution_is_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            s.update_research_blockers(item["id"], failures=[failure("crossref", "auth_failed")], cleared=[])
            s.pause_item(item["id"])
            resumed = s.resume_item(item["id"])
            self.assertEqual(len(resumed["research_blockers"]), 1,
                             "pause/resume is not an evidence decision (finding 18)")
            with self.assertRaises(QueueError):
                s.resolve_research_blockers(item["id"], reason="   ")
            resolved = s.resolve_research_blockers(item["id"], reason="covered by DOAJ + OpenAlex for this claim")
            self.assertEqual(resolved["research_blockers"], [])
            self.assertEqual(len(resolved["research_resolutions"]), 1)
            self.assertIn("covered by", resolved["research_resolutions"][0]["reason"])

    def test_source_scoped_resolution(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            s.update_research_blockers(item["id"], failures=[
                failure("crossref", "auth_failed"), failure("fred", "provider_unavailable")], cleared=[])
            resolved = s.resolve_research_blockers(item["id"], reason="fred series reproduced from BEA", sources=["fred"])
            self.assertEqual([b["source"] for b in resolved["research_blockers"]], ["crossref"])

    def test_coverage_accumulates_for_the_completion_stamp(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            s.update_research_blockers(item["id"], failures=[], cleared=[],
                                       coverage={"crossref": "searched_ok", "semanticscholar": "provider_unavailable"})
            s.update_research_blockers(item["id"], failures=[], cleared=[],
                                       coverage={"semanticscholar": "searched_ok"})
            got = s.get(item["id"])["research_coverage"]
            self.assertEqual({k: v["coverage"] for k, v in got.items()},
                             {"crossref": "searched_ok", "semanticscholar": "searched_ok"},
                             "the stamp accumulates across iterations, last state per source (finding 10)")

    def test_completion_coverage_stamp(self):
        with tempfile.TemporaryDirectory() as d:
            s = store(d)
            item = add_item(s)
            stamped = s.record_completion_coverage(item["id"], {"at": "x", "policy": None,
                                                                "coverage": {"crossref": {"coverage": "searched_ok"}},
                                                                "blockers": []})
            self.assertEqual(stamped["completion_coverage"]["coverage"]["crossref"]["coverage"], "searched_ok")


class SaturationDecision(unittest.TestCase):
    def test_the_acceptance_case_a_blocked_pass_never_completes(self):
        """Plan 8d: one pass short of saturation, required-source failure, no semantic
        change → the topic does NOT complete."""
        streak, verdict = saturation_decision(signature_changed=False, previous_streak=2, limit=3,
                                              blocked_this_pass=True, blockers=[failure("crossref", "auth_failed")])
        self.assertEqual((streak, verdict), (2, "continue"),
                         "a blocked pass pauses the streak instead of advancing it")

    def test_clean_passes_advance_and_complete(self):
        self.assertEqual(saturation_decision(signature_changed=False, previous_streak=2, limit=3,
                                             blocked_this_pass=False, blockers=[]), (3, "complete"))
        self.assertEqual(saturation_decision(signature_changed=False, previous_streak=0, limit=3,
                                             blocked_this_pass=False, blockers=[]), (1, "continue"))

    def test_semantic_change_resets_even_when_blocked(self):
        self.assertEqual(saturation_decision(signature_changed=True, previous_streak=2, limit=3,
                                             blocked_this_pass=True, blockers=[failure("x", "auth_failed")]),
                         (0, "continue"))

    def test_lingering_blockers_hold_completion_at_the_limit(self):
        streak, verdict = saturation_decision(signature_changed=False, previous_streak=3, limit=3,
                                              blocked_this_pass=False,
                                              blockers=[failure("semanticscholar", "provider_unavailable")])
        self.assertEqual(verdict, "held",
                         "an unresolved blocker holds DONE until it clears or is explicitly resolved")


class ActivitySummarizer(unittest.TestCase):
    def _write(self, d, lines):
        path = Path(d) / "activity.jsonl"
        path.write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in lines) + "\n")
        return str(path)

    def test_final_state_per_request_in_file_order(self):
        """Pass-1 finding 6: fail → ok recovery for the same request ends CLEARED; the
        reverse ends blocked; unrelated requests never interact."""
        with tempfile.TemporaryDirectory() as d:
            path = self._write(d, [
                {"source": "crossref", "request_type": "find", "query_or_identity": "A", "coverage": "provider_unavailable"},
                {"source": "crossref", "request_type": "find", "query_or_identity": "A", "coverage": "searched_ok"},
                {"source": "doaj", "request_type": "find", "query_or_identity": "B", "coverage": "searched_ok"},
                {"source": "doaj", "request_type": "find", "query_or_identity": "B", "coverage": "auth_failed"},
                {"source": "fred", "request_type": "data", "query_or_identity": "GDP", "coverage": "not_searched"},
                "not json at all",
                {"coverage": "searched_ok"},
            ])
            out = research_activity.summarize(path)
        self.assertEqual([(f["source"], f["coverage"]) for f in out["failures"]],
                         [("doaj", "auth_failed"), ("fred", "not_searched")])
        self.assertEqual(out["ok_keys"], [research_activity.request_key("crossref", "find", "A")])
        self.assertEqual(out["coverage_by_source"],
                         {"crossref": "searched_ok", "doaj": "auth_failed", "fred": "not_searched"})

    def test_missing_file_is_no_signal_never_an_error(self):
        self.assertEqual(research_activity.summarize("/nope/nothing.jsonl"),
                         {"failures": [], "ok_keys": [], "coverage_by_source": {}})
        self.assertEqual(research_activity.summarize(None),
                         {"failures": [], "ok_keys": [], "coverage_by_source": {}})


if __name__ == "__main__":
    unittest.main()
