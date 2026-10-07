"""Self-tests of tools/gen2_differential.py, the shared exact, manifest-complete, fail-closed differential core (task 2q-e1; Astra 2q-b5 C1 and C2).

The core is only worth its verdict if a change in what a driver saw cannot pass and a run that saw nothing cannot be evidence. Each counterfactual below changes ONE observation of a hand-built
run (the shape a driver records) and must come out `different` in that group alone; each refusal removes coverage, from every run alike, and must come out `unresolved`, never equivalent;
the controls show an identical run, a run that differs only by the harness's allocated port, and an unstable baseline get the answers the contract gives them.
Oracle: hand-built observations. What they cannot show: that a driver observes what it should (the drivers' own counterfactuals, in the task's evidence, run the real drivers on altered trees).
"""
from __future__ import annotations

import collections
import copy
import datetime
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CORE = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "gen2_differential.py"))
Run, compare, freeze, encode, loopback, load_run = (CORE[n] for n in ("Run", "compare", "freeze", "encode", "loopback", "load_run"))


def world(edit=lambda observations: None, port: int = 41001, drop=()):
    """The artifacts of one run of two drivers: provider content, URLs, downloads (kept exactly), a bulk group (digest only) and a digested group."""
    seen = {"answers": {"a": {"records": [{"raw": {"updated": "2026-10-06T01:02:03+00:00", "value": {"a": 1}, "tags": ["x"]}}]}, "b": {"ok": True, "n": 1}},
            "urls": {"page": {"url": loopback(f"http://127.0.0.1:{port}/page?q=1", port), "error": loopback(f"URLError: <urlopen error 127.0.0.1:{port}>", port)}},
            "downloads": {"one": b"xyz", "none": b""}}
    edit(seen)
    run, other = Run("d"), Run("e")
    for group, cases in seen.items():
        for case, value in cases.items():
            if (group, case) not in drop:
                run.observe(group, case, value, keep="exact")
    for i in range(30):
        run.observe("bulk", str(i), [i, str(i)], keep="none")
    other.observe("digested", "x", {"k": [1, 2]})
    return {"d": run.artifact(), "e": other.artifact()}


MANIFEST = freeze([world(), world(port=41002)])
VERDICT = lambda before, after: compare(before, after, MANIFEST)   # noqa: E731


def edited(edit):
    return VERDICT([world(), world(port=41002)], [world(edit)])


class Counterfactuals(unittest.TestCase):
    def test_each_change_is_different_in_its_group_alone(self) -> None:
        cases = {
            "a changed URL origin": ("urls", lambda s: s["urls"]["page"].update(url="https://example.invalid/page?q=1")),
            "a changed URL path": ("urls", lambda s: s["urls"]["page"].update(url="http://127.0.0.1:<port>/other?q=1")),
            "a changed URL query": ("urls", lambda s: s["urls"]["page"].update(url="http://127.0.0.1:<port>/page?q=2")),
            "a changed URL scheme": ("urls", lambda s: s["urls"]["page"].update(url="https://127.0.0.1:<port>/page?q=1")),
            "another loopback port": ("urls", lambda s: s["urls"]["page"].update(url="http://127.0.0.1:9/page?q=1")),
            "a changed provider timestamp": ("answers", lambda s: s["answers"]["a"]["records"][0]["raw"].update(updated="2026-10-07T01:02:03+00:00")),
            "a dict that became its pairs": ("answers", lambda s: s["answers"]["a"]["records"][0]["raw"].update(value=[["'a'", 1]])),
            "a list that became a tuple": ("answers", lambda s: s["answers"]["a"]["records"][0]["raw"].update(tags=("x",))),
            "a dict that became an OrderedDict": ("answers", lambda s: s["answers"].update(b=collections.OrderedDict(s["answers"]["b"]))),
            "a true that became a one": ("answers", lambda s: s["answers"]["b"].update(ok=1)),
            "a one that became a float": ("answers", lambda s: s["answers"]["b"].update(n=1.0)),
            "a dict's insertion order": ("answers", lambda s: s["answers"].update(b={"n": 1, "ok": True})),
            "a changed download body": ("downloads", lambda s: s["downloads"].update(one=b"changed")),
            "a download that became text": ("downloads", lambda s: s["downloads"].update(one="xyz")),
            "an empty download that became a missing one": ("downloads", lambda s: s["downloads"].update(none=None)),
        }
        for label, (group, edit) in cases.items():
            with self.subTest(label):
                got = edited(edit)
                self.assertEqual(got["result"], "DIFFERENT", label)
                self.assertEqual({k: v["verdict"] for k, v in got["tests"].items() if v["verdict"] != "same"}, {f"d/{group}": "different"}, label)

    def test_encoding_keeps_what_the_old_normalisations_lost(self) -> None:
        Pair = collections.namedtuple("Pair", "a b")
        twins = [({"a": 1}, [["'a'", 1]]), ([1], (1,)), (1, True), (1, 1.0), ("1", 1), (b"x", "x"), (b"x", bytearray(b"x")), ({1, 2}, [1, 2]), ({}, []), ("", None), ((1, 2), Pair(1, 2)),
                 ("2026-10-06T01:02:03+00:00", "2026-10-07T01:02:03+00:00"), ({"a": 1, "b": 2}, {"b": 2, "a": 1}), (CORE["Obj"](("Rec", 1)), ("Rec", 1)), (0.0, -0.0)]
        for a, b in twins:
            self.assertNotEqual(json.dumps(encode(a)), json.dumps(encode(b)), (a, b))
        self.assertEqual(json.dumps(encode({3, 1, 2})), json.dumps(encode({2, 3, 1})), "a set has no order")
        with self.assertRaises(TypeError):
            encode(object())

    def test_loopback_names_only_the_allocated_port(self) -> None:
        self.assertEqual(loopback("http://127.0.0.1:4100/a?b=1#c", 4100), "http://127.0.0.1:<port>/a?b=1#c")
        for kept in ("http://127.0.0.1:41000/a", "http://localhost:4100/a", "http://127.0.0.1:41001", "http://10.127.0.0.1:4100/a", "https://example.org/127.0.0.1:41"):
            self.assertEqual(loopback(kept, 4100), kept)


class Controls(unittest.TestCase):
    def test_runs_that_differ_only_by_the_allocated_port_are_equivalent_and_counted_once(self) -> None:
        got = VERDICT([world(port=1111), world(port=2222)], [world(port=3333), world(port=4444)])
        self.assertEqual((got["result"], got["counts"], got["observed"]), ("EQUIVALENT", {"same": 5}, 5 + 30 + 1))

    def test_an_unstable_baseline_or_after_run_is_unresolved_and_names_its_source(self) -> None:
        moved = lambda s: s["answers"]["a"]["records"][0]["raw"].update(updated="2026-10-07T01:02:03+00:00")   # noqa: E731
        for label, got in (("before", VERDICT([world(), world(moved)], [world()])), ("after", VERDICT([world(), world()], [world(), world(moved)]))):
            self.assertEqual(got["result"], "UNRESOLVED", label)
            self.assertEqual(list(got["tests"]["d/answers"]["sources"]), [f"{label}[1]: a"])
        gone = VERDICT([world(), world(moved)], [world(moved)])
        self.assertEqual((gone["result"], gone["tests"]["d/answers"]["verdict"]), ("UNRESOLVED", "unresolved"), "noise first: nothing is concluded")

    def test_a_nan_is_the_same_observation_as_a_nan_and_fewer_runs_than_the_rule_asks_are_unresolved(self) -> None:
        nan = lambda s: s["answers"]["b"].update(n=float("nan"))   # noqa: E731
        self.assertEqual(VERDICT([world(nan), world(nan)], [world(nan)])["result"], "EQUIVALENT")
        self.assertEqual(VERDICT([world()], [world()])["result"], "UNRESOLVED")
        self.assertEqual(VERDICT([world(), world()], [])["result"], "UNRESOLVED")


class Refusals(unittest.TestCase):
    """Coverage that is not there is never equivalence: every case below leaves the runs of BOTH trees without it (a generator that failed for both), or only the after run's."""

    def refused(self, mutate, both: bool = True, driver: str = "d") -> dict:
        def run():
            runs = world()
            mutate(runs)
            return runs
        got = VERDICT([run(), run()] if both else [world(), world()], [run()])
        self.assertEqual((got["result"], got["tests"][driver]["verdict"]), ("UNRESOLVED", "unresolved"))
        return got

    def test_an_empty_partial_or_failed_run_is_unresolved(self) -> None:
        empties = {"an empty JSON object": {}, "no groups": {"driver": "d", "version": 1, "complete": True, "groups": {}}, "the surface driver's old empty shape": {"compared": {}, "informational": {}},
                   "a driver that did not complete": {**world()["d"], "complete": False}, "a group with no cases": {**world()["d"], "groups": {**world()["d"]["groups"], "urls": {"n": 0, "keys": "", "digest": ""}}},
                   "the runner's reason for no artifact": "no finished marker: a driver failed", "a null artifact": None}
        for label, art in empties.items():
            with self.subTest(label):
                why = self.refused(lambda runs: runs.update(d=art))["tests"]["d"]["sources"]
                self.assertTrue(all(isinstance(v, str) and v for v in why.values()))
        with self.assertRaises(SystemExit):
            Run("d").artifact()   # a driver that observed nothing writes nothing

    def test_removed_added_and_renamed_groups_and_cases_are_unresolved_for_both_trees_alike(self) -> None:
        def group(name, edit):
            return lambda runs: edit(runs["d"]["groups"], name)
        self.refused(group("downloads", lambda groups, name: groups.pop(name)))
        self.refused(group("extra", lambda groups, name: groups.update({name: groups["bulk"]})))
        self.refused(lambda runs: runs.pop("e"), driver="e")
        removed = self.refused(lambda runs: runs.update(d=world(drop=[("downloads", "one")])["d"]))
        self.assertIn("cases missing, added or renamed in: ['downloads']", str(removed["tests"]["d"]["sources"]))
        self.refused(lambda runs: runs.update(d=world(lambda s: s["answers"].update(c=1))["d"]))
        self.refused(lambda runs: runs.update(d=world(lambda s: s["downloads"].update({"two": s["downloads"].pop("one")}))["d"]), both=False)

    def test_a_manifest_is_frozen_only_from_complete_runs_that_agree(self) -> None:
        empty = {"driver": "d", "version": 1, "complete": True, "groups": {}}
        no_cases = {**world()["d"], "groups": {"g": {"n": 0, "keys": "k", "digest": "d"}}}
        for runs in ([world()], [world(), {"d": {}, "e": world()["e"]}], [world(), world(lambda s: s["answers"].update(c=1))], [world(), {"d": world()["d"]}],
                     [{"d": empty}, {"d": empty}], [{"d": no_cases}, {"d": no_cases}]):
            with self.assertRaises(ValueError):
                freeze(runs)
        self.assertEqual(compare([{"d": empty}] * 2, [{"d": empty}], {"d": {}})["result"], "UNRESOLVED", "even a manifest that declares nothing does not make an empty run evidence")


class RunDirectories(unittest.TestCase):
    def write(self, root: Path, name: str, finished: bool = True, runs=None) -> str:
        (root / name).mkdir()
        for driver, art in (runs or world()).items():
            (root / name / f"{driver}.json").write_text(json.dumps(art))
        if finished:
            (root / name / "finished").write_text("done\n")
        return str(root / name)

    def test_a_run_counts_only_with_its_finished_marker_and_the_cli_exits_with_the_verdict(self) -> None:
        main = CORE["main"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [self.write(root, name) for name in ("b1", "b2", "a1")]
            self.assertEqual(main(["freeze", str(root / "manifest.json"), runs[0], runs[1]]), 0)
            check = lambda *after: main(["compare", str(root / "manifest.json"), "--before", runs[0], runs[1], "--after", *after, "--report", str(root / "r.json")])   # noqa: E731
            self.assertEqual(check(runs[2]), 0)
            self.assertEqual(check(self.write(root, "a2", runs=world(lambda s: s["downloads"].update(one=b"changed")))), 1)
            self.assertEqual(check(self.write(root, "a3", finished=False)), 2, "a run whose runner did not finish is no evidence")
            half = world()
            (root / "a4").mkdir()
            (root / "a4" / "d.json").write_text(json.dumps(half["d"]))
            (root / "a4" / "finished").write_text("done\n")
            self.assertEqual(check(str(root / "a4")), 2, "a driver with no artifact")
            self.assertEqual(json.loads((root / "r.json").read_text())["tests"]["e"]["sources"], {"after[0]": "a4/e.json: FileNotFoundError"})

    def test_the_artifact_is_written_whole_or_not_at_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("d")
            with self.assertRaises(SystemExit):
                run.finish(Path(tmp) / "d.json")
            self.assertEqual(list(Path(tmp).iterdir()), [])
            run.observe("g", "c", {"k": b"v"}, keep="exact")
            run.finish(Path(tmp) / "d.json", note={"seen": (1, 2)})
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ["d.json"])
            self.assertEqual(json.loads((Path(tmp) / "d.json").read_text())["groups"]["g"]["cases"]["c"], ["dict", [["k", ["bytes", "76"]]]])
            (Path(tmp) / "d.json").unlink()
            with mock.patch("json.dump", side_effect=OSError("disk full")), self.assertRaises(OSError):
                run.finish(Path(tmp) / "d.json")
            self.assertFalse((Path(tmp) / "d.json").exists(), "a write that fails part-way leaves nothing under the artifact's name")

    def test_a_cases_identity_is_part_of_its_group(self) -> None:
        a, b = Run("d"), Run("d")
        a.observe("g", "one", 1), b.observe("g", "two", 1)
        self.assertNotEqual(a.artifact()["groups"]["g"]["digest"], b.artifact()["groups"]["g"]["digest"])
        self.assertNotEqual(a.artifact()["groups"]["g"]["keys"], b.artifact()["groups"]["g"]["keys"])
        with self.assertRaises(ValueError):
            a.observe("g", "one", 1)   # a kept case occurs once


class Clock(unittest.TestCase):
    def test_a_generated_clock_is_fixed_at_its_source(self) -> None:
        instant = datetime.datetime(2026, 10, 7, 1, 2, 3, tzinfo=datetime.timezone.utc)
        fixed = CORE["fixed_datetime"](instant)
        self.assertEqual(fixed.now(datetime.timezone.utc).isoformat(timespec="seconds"), "2026-10-07T01:02:03+00:00")
        self.assertEqual(fixed.now(), instant)
        self.assertTrue(issubclass(fixed, datetime.datetime))


if __name__ == "__main__":
    unittest.main()
