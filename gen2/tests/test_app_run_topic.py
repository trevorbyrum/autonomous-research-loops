"""The operator's walk client (T19 step 1). Oracle: the requests it sends (a scripted engine records them) and the lines and exit codes it
produces. Limits: the engine's side is test_app_walk's, over real HTTP.
"""
import http.client
import json
import unittest

from gen2.app import run_topic

TOPIC = "fleet-a:t1"
WAIT = {"status": "ok", "action": "wait", "command": "apply_operator_decision kind=scope_approval"}
SHOWN = {"dossier": {"revision": 2, "content_hash": "sha256:" + "d" * 64, "state": "satisfied", "gates": []}, "approvable": True,
         "reviews": [{"outcome": "insufficient", "summary": "claim 2 unsearched", "evidence": []}]}


class Engine:
    """Scripted: each call answers with the next item (a reply, or an exception to raise)."""
    def __init__(self, *items):
        self.items, self.calls = list(items), []

    def __call__(self, url, token, method, path, body=None, **kw):
        self.calls.append((method, path, body, token))
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item if isinstance(item, tuple) else (200, item)


class ClientTest(unittest.TestCase):
    def run_client(self, *items, argv=(TOPIC,), environ=None):
        engine, said = Engine(*items), []
        code = run_topic.main(list(argv), environ=environ or {"GEN2_OPERATOR_TOKEN": "tok"}, call=engine, say=said.append, sleep=lambda s: None)
        return code, said, engine

    def test_it_calls_walk_one_tick_at_a_time_until_the_operators_move_and_prints_the_command(self):
        code, said, engine = self.run_client({"status": "ok", "action": "issue"}, {"status": "ok", "action": "advance"}, WAIT)
        self.assertEqual((code, said), (0, ["waiting for: the next move is the operator's; run: apply_operator_decision kind=scope_approval"]))
        self.assertEqual([(m, p, json.loads(b), t) for m, p, b, t in engine.calls], [("POST", "/v1/commands/walk", {"topic_id": TOPIC}, "tok")] * 3)

    def test_the_completion_wait_prints_the_reviewed_status_block_and_an_unreviewed_one_is_refused(self):
        completion = {"status": "ok", "action": "wait", "command": "apply_operator_decision kind=completion_approval"}
        code, said, engine = self.run_client(completion, {"status": "ok", "topics": [{"review": SHOWN}]})
        self.assertEqual(code, 0)
        for fragment in ("run: apply_operator_decision kind=completion_approval", "dossier revision 2", "review insufficient: claim 2 unsearched"):
            self.assertIn(fragment, said[0])
        self.assertEqual(engine.calls[1][:2], ("GET", f"/v1/status?topic={TOPIC.replace(':', '%3A')}"))
        for review in (None, {**SHOWN, "approvable": False}):
            with self.subTest(review=review):
                code, said, _ = self.run_client(completion, {"status": "ok", "topics": [{"review": review}]})
                self.assertEqual((code, said[0].startswith("stopped: cannot show the review")), (3, True))

    def test_done_and_stops_use_fixed_words_only(self):
        self.assertEqual(self.run_client({"status": "ok", "action": "done"})[:2], (0, ["done"]))
        self.assertEqual(self.run_client({"status": "ok", "action": "stop", "code": "hold_open"})[:2], (3, [f"stopped: {run_topic.STOPS['hold_open']}"]))
        self.assertEqual(self.run_client({"status": "stopped", "code": "refused"})[:2], (3, [f"stopped: {run_topic.STOPS['refused']}"]))
        self.assertEqual(self.run_client({"status": "ok", "action": "stop", "code": "SENTINEL\nx"})[:2], (3, ["stopped: the walk stopped"]))   # an unknown word is not echoed

    def test_an_answer_that_never_comes_is_ambiguous_stops_and_is_never_repeated(self):
        for failure in (OSError("timed out"), ValueError("not json"), http.client.IncompleteRead(b"")):
            with self.subTest(type(failure).__name__):
                code, said, engine = self.run_client(failure)
                self.assertEqual((code, said, len(engine.calls)), (2, [run_topic.NO_ANSWER], 1))

    def test_a_refusal_a_bad_http_status_a_bad_reply_and_a_bad_call_are_exit_two_and_fixed(self):
        for items, argv in (([{"status": "refused", "reason": "SENTINEL\nx"}], (TOPIC,)), ([(403, {"status": "refused"})], (TOPIC,)),
                            ([(200, ["x"])], (TOPIC,)), ([{"status": "ok", "action": "dance"}], (TOPIC,)),
                            ([{"status": "ok", "action": "wait", "command": "rm -rf /"}], (TOPIC,)), ([], ()), ([], (TOPIC, "extra"))):
            with self.subTest(items=items, argv=argv):
                code, said, engine = self.run_client(*items, argv=argv)
                self.assertEqual(code, 2)
                self.assertNotIn("SENTINEL", " ".join(said))
                self.assertEqual(len(engine.calls), len(items))

    def test_it_stops_after_the_call_cap_rather_than_loop_forever(self):
        code, said, engine = self.run_client(*[{"status": "ok", "action": "issue"}] * run_topic.MAX_CALLS)
        self.assertEqual((code, said, len(engine.calls)), (0, ["still working; run this again"], run_topic.MAX_CALLS))
