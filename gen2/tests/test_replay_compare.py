"""Self-tests of tools/gen2_replay_compare.py, the exact Router-replay comparison (task 2q-b3b; Astra 2q-b3 C1, C2).

The comparator is only worth its verdict if a changed observation cannot pass: each counterfactual below changes one thing in a recorded run (the shape the recorder
writes) and must come out `different`, not `same` and not `unresolved`; the controls show an identical run and an unstable baseline get the answers the contract gives them.
Oracle: hand-built records. What they cannot show: that the recorder captures an observation at all (RecorderTest runs it twice) or that its seams are complete
(the baseline runs of the evidence, which report what is still unstable).
"""
from __future__ import annotations

import contextlib
import copy
import io
import runpy
import tempfile
import unittest
from pathlib import Path

from gen2.tests import children

TOOLS = Path(__file__).resolve().parents[2] / "tools"
COMPARE = runpy.run_path(str(TOOLS / "gen2_replay_compare.py"))
H1, H2 = "sha256:" + "a" * 64, "sha256:" + "b" * 64
INV = "inv_" + "0" * 31 + "1"
FP, FP2 = "pid=1001;starttime=2001;session=1001", "pid=1002;starttime=2002;session=1002"  # a job process's identity as the replay's identity seam writes it (tools/gen2_replay_seams.py)


def call(method, result, **more):
    return {"method": method, "router": 0, "args": [{"invocation_id": INV, "start_fingerprint": FP, "expected": float("nan")}], "kwargs": {}, "result": result, **more}


def record():
    rows = {"leases": [{"lease_id": "lease_1", "expires_at": "2026-09-27T10:00:01.002Z"}], "invocations": [{"invocation_id": INV, "state": "running", "start_fingerprint": FP}]}
    return {"outcome": "pass", "calls": [
        call("request_launch", {"status": "recorded", "invocation_id": INV, "lease_expires_at": "2026-09-27T10:00:01.002Z", "content_hash": H1, "evidence": [H1, H2], "units": 1}),
        call("invocation_status", {"state": "running"}),
        call("invocation_status", {"state": "running"}),  # a repeated poll: it is its own observation
        call("activate_config_bundle", {"status": "recorded"}, store=rows)],
        "end": [{"router": 0, "store": rows, "shadow_answers": [["2026-09-27T10:30:00.000Z", "status", {"holds": []}], ["2031-01-01T00:00:00.000Z", "healthy", True]], "store_after_shadow": rows}]}


def run():
    return {"scenario": record(), "other": {"outcome": "pass", "calls": [], "end": []}}


def verdict(before, after, name="scenario"):
    got = COMPARE["compare"](before, [after])
    return got["result"], got["tests"][name]


class CounterfactualTest(unittest.TestCase):
    """One change to one recorded run each: all must be `different`."""

    def changed(self, edit):
        after = copy.deepcopy(run())
        edit(after["scenario"])
        return verdict([run(), run()], after)

    def test_each_change_is_different(self) -> None:
        launch = lambda r: r["calls"][0]["result"]
        cases = {
            "a changed answer": lambda r: launch(r).update(status="refused"),
            "a removed store observation": lambda r: r["calls"][3].pop("store"),
            "a changed store observation": lambda r: r["calls"][3]["store"]["invocations"][0].update(state="failed"),
            "a changed job process identity in a call's arguments": lambda r: r["calls"][0]["args"][0].update(start_fingerprint=FP2),
            "a changed job process identity in a stored row": lambda r: r["calls"][3]["store"]["invocations"][0].update(start_fingerprint=FP2),
            "a changed status answer (the second of two identical polls)": lambda r: r["calls"][2]["result"].update(state="failed"),
            "a dropped poll": lambda r: r["calls"].pop(2),
            "a reordered ordered list": lambda r: launch(r)["evidence"].reverse(),
            "a changed duration": lambda r: launch(r).update(lease_expires_at="2026-09-27T11:00:00.002Z"),
            "a changed id namespace": lambda r: launch(r).update(invocation_id=INV.replace("inv_", "lease_")),
            "a changed content hash": lambda r: launch(r).update(content_hash=H2),
            "an integer that became a float": lambda r: launch(r).update(units=1.0),
            "a removed end-of-test store observation": lambda r: r["end"][0].pop("store_after_shadow"),
            "a removed shadow answer": lambda r: r["end"][0]["shadow_answers"].pop(),
            "a changed outcome": lambda r: r.update(outcome="fail"),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                result, found = self.changed(edit)
                self.assertEqual((result, found["verdict"]), ("DIFFERENT", "different"), found)
                self.assertTrue(found["sources"])

    def test_a_test_missing_from_the_after_run_is_different(self) -> None:
        after = run()
        del after["scenario"]
        self.assertEqual(verdict([run(), run()], after)[0], "DIFFERENT")

    def test_a_test_skipped_in_one_run_is_different(self) -> None:
        after = run()
        after["other"] = {"outcome": "skip"}  # a skipped test records no calls
        self.assertEqual(verdict([run(), run()], after, "other")[1]["verdict"], "different")

    def test_an_identical_run_is_equivalent_and_the_observations_compared_are_counted(self) -> None:
        got = COMPARE["compare"]([run(), run(), run()], [run(), run()])
        self.assertEqual((got["result"], got["counts"]), ("EQUIVALENT", {"same": 2}))
        self.assertEqual((got["observed"]["calls"], got["observed"]["invocation_status"], got["observed"]["immediate store readable row snapshots"],
                          got["observed"]["end-of-test records"], got["observed"]["end-of-test store readable row snapshots"]), (4, 2, 1, 1, 1))

    def test_readable_row_snapshots_are_counted_apart_from_closed_store_markers(self) -> None:
        """DEBT-023 item 3: a run with one readable immediate snapshot, two markers after a call (a closed store, a store in a transaction), and two end records, one readable and
        one a marker. The counts are written by hand; a marker is not a row, so no total may merge them."""
        mixed = run()
        mixed["scenario"]["calls"] += [call("record_gateway_facts", {"status": "recorded"}, store="unreadable: ProgrammingError"),
                                       call("record_capability_probe", {"status": "recorded"}, store="in-transaction"),
                                       call("healthy", True)]  # a call of a route that is not tracked has no observation at all
        mixed["scenario"]["end"].append({"router": 1, "store": "unreadable: ProgrammingError", "shadow_answers": [], "store_after_shadow": "unreadable: ProgrammingError"})
        got = COMPARE["compare"]([mixed, copy.deepcopy(mixed)], [copy.deepcopy(mixed)])
        self.assertEqual(got["result"], "EQUIVALENT")
        seen = got["observed"]
        self.assertEqual((seen["calls"], seen["immediate store readable row snapshots"], seen["immediate store closed-store or in-transaction markers (not rows)"]), (7, 1, 2))
        self.assertEqual((seen["end-of-test records"], seen["end-of-test store readable row snapshots"], seen["end-of-test store closed-store or in-transaction markers (not rows)"]),
                         (2, 1, 1))
        self.assertNotIn("store observations after a call", seen)  # the old total counted both kinds as one

    def test_a_summary_that_has_no_markers_says_zero_not_nothing(self) -> None:
        seen = COMPARE["compare"]([run(), run()], [run()])["observed"]
        self.assertEqual((seen["immediate store closed-store or in-transaction markers (not rows)"], seen["end-of-test store closed-store or in-transaction markers (not rows)"]), (0, 0))


class FailClosedTest(unittest.TestCase):
    def unstable(self):
        other = run()
        other["scenario"]["calls"].insert(2, call("invocation_status", {"state": "running"}))  # one more poll: a timing difference
        other["scenario"]["calls"][0]["result"]["content_hash"] = H2
        return other

    def test_baselines_that_disagree_are_unresolved_never_equivalent_and_name_their_sources(self) -> None:
        for after in (run(), self.unstable()):  # the after run equal to a baseline run changes nothing
            result, found = verdict([run(), self.unstable()], after)
            self.assertEqual((result, found["verdict"]), ("UNRESOLVED", "unresolved"))
            self.assertEqual(set(found["sources"]), {"calls: the number of invocation_status calls differs", "request_launch result.content_hash"})

    def test_an_after_run_that_disagrees_with_the_other_after_run_is_unresolved(self) -> None:
        got = COMPARE["compare"]([run(), run()], [run(), self.unstable()])
        self.assertEqual((got["result"], got["tests"]["scenario"]["verdict"]), ("UNRESOLVED", "unresolved"))

    def test_a_difference_outside_the_noise_is_named_but_the_test_stays_unresolved(self) -> None:
        after = copy.deepcopy(run())
        after["scenario"]["calls"][0]["result"].update(status="refused")
        other = run()
        other["scenario"]["calls"][0]["result"]["content_hash"] = H2  # the baselines disagree about the hash only
        got = COMPARE["compare"]([run(), other], [after])
        self.assertEqual((got["result"], got["tests"]["scenario"]["verdict"]), ("UNRESOLVED", "unresolved"))
        self.assertEqual(got["tests"]["scenario"]["outside_noise"], ["request_launch result.status"])

    def test_a_real_job_process_identity_that_differs_between_runs_is_unresolved_and_named(self) -> None:
        """A test that runs with the real identity (REAL_IDENTITY of tools/gen2_replay_seams.py) has a different pid, start time and session in each run: nothing is concluded."""
        varied = run()
        varied["scenario"]["calls"][0]["args"][0]["start_fingerprint"] = FP2
        varied["scenario"]["calls"][3]["store"]["invocations"][0]["start_fingerprint"] = FP2
        result, found = verdict([run(), varied], run())
        self.assertEqual((result, found["verdict"]), ("UNRESOLVED", "unresolved"))
        self.assertEqual({k for k in found["sources"] if "start_fingerprint" not in k}, set())
        self.assertIn("request_launch args.start_fingerprint", found["sources"])
        self.assertIn("activate_config_bundle store.invocations.start_fingerprint", found["sources"])

    def test_the_command_refuses_a_single_baseline_run(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(COMPARE["main"](["--before", "only.json.gz", "--after", "after.json.gz"]), 2)


class RecorderTest(unittest.TestCase):
    def test_two_replays_of_one_tree_are_exactly_equal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outs = [str(Path(tmp) / f"{i}.json.gz") for i in (1, 2)]
            for out in outs:
                done = children.python([str(TOOLS / "gen2_replay.py"), str(children.code_root()), out, "gen2.tests.test_router_time"], capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, done.stderr)
            runs = [COMPARE["load"](out) for out in outs]
        self.assertGreater(sum(len(t["calls"]) for t in runs[0].values()), 50)  # it recorded the calls, not nothing
        self.assertEqual(COMPARE["compare"](runs, [runs[0]])["result"], "EQUIVALENT")
