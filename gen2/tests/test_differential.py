"""Self-tests of tools/gen2_differential.py, the shared exact, inventory-complete, fail-closed differential core (tasks 2q-e1 and 2q-e2; Astra's 2q-b5 and 2q-e1 reviews, C1 and C2).

The core is only worth its verdict if a change in what a driver saw cannot pass and a run that saw nothing cannot be evidence. Each counterfactual below changes ONE observation of a hand-built
run (the shape a driver records) and must come out `different` in that group alone; each refusal removes or damages coverage, from every run alike, and must come out `unresolved` (or be refused
before any verdict), never equivalent; the controls show an identical run, a run that differs only by the harness's allocated port, and an unstable baseline get the answers the contract gives them.
Oracle: hand-built observations. What they cannot show: that a driver observes what it should (the drivers' own counterfactuals, in the task's evidence, run the real drivers on altered trees).
"""
from __future__ import annotations

import collections
import contextlib
import copy
import datetime
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CORE = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools" / "gen2_differential.py"))
Run, Corpus, LoopbackURL, compare, freeze, encode, loopback, unnamed, load_run, corpus, main = (CORE[n] for n in ("Run", "Corpus", "LoopbackURL", "compare", "freeze", "encode", "loopback", "unnamed", "load_run", "corpus", "main"))
DRIVERS = ["d", "e"]


def world(edit=lambda observations: None, port: int = 41001, drop=()):
    """The artifacts of one run of two drivers: provider content, URLs, downloads (kept exactly), a bulk group (digest only) and a digested group."""
    seen = {"answers": {"a": {"records": [{"raw": {"updated": "2026-10-06T01:02:03+00:00", "value": {"a": 1}, "tags": ["x"]}}]}, "b": {"ok": True, "n": 1}},
            "urls": {"page": {"url": loopback(f"http://127.0.0.1:{port}/page?q=1", port), "error": unnamed("URLError: <urlopen error [Errno 111] Connection refused>", port)}},
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


MANIFEST = freeze([world(), world(port=41002)], DRIVERS)
VERDICT = lambda before, after: compare(before, after, MANIFEST, DRIVERS)   # noqa: E731


def edited(edit):
    return VERDICT([world(), world(port=41002)], [world(edit)])


def url(value, port: int = 41001):
    """An edit of the page's URL: what the driver would have observed had the tree answered `value`, normalised as the drivers normalise."""
    return lambda s: s["urls"]["page"].update(url=loopback(value, port))


def cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main([str(a) for a in argv])
        except SystemExit as e:
            code = e.code
    return code, out.getvalue(), err.getvalue()


class Counterfactuals(unittest.TestCase):
    def test_each_change_is_different_in_its_group_alone(self) -> None:
        cases = {
            "a changed URL origin": ("urls", url("https://example.invalid/page?q=1")),
            "a changed URL path": ("urls", url("http://127.0.0.1:41001/other?q=1")),
            "a changed URL query": ("urls", url("http://127.0.0.1:41001/page?q=2")),
            "a changed URL fragment": ("urls", url("http://127.0.0.1:41001/page?q=1#f")),
            "a changed URL scheme": ("urls", url("https://127.0.0.1:41001/page?q=1")),
            "a URL with userinfo": ("urls", url("http://u@127.0.0.1:41001/page?q=1")),
            "another loopback port": ("urls", url("http://127.0.0.1:9/page?q=1")),
            "the literal text <port> for the port": ("urls", url("http://127.0.0.1:<port>/page?q=1")),
            "the same URL as plain text": ("urls", lambda s: s["urls"]["page"].update(url="http://127.0.0.1:41001/page?q=1")),
            "a changed error message": ("urls", lambda s: s["urls"]["page"].update(error="URLError: <urlopen error timed out>")),
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
        marker = LoopbackURL("http://127.0.0.1:", "/x")
        twins = [({"a": 1}, [["'a'", 1]]), ([1], (1,)), (1, True), (1, 1.0), ("1", 1), (b"x", "x"), (b"x", bytearray(b"x")), ({1, 2}, [1, 2]), ({}, []), ("", None), ((1, 2), Pair(1, 2)),
                 ("2026-10-06T01:02:03+00:00", "2026-10-07T01:02:03+00:00"), ({"a": 1, "b": 2}, {"b": 2, "a": 1}), (CORE["Obj"](("Rec", 1)), ("Rec", 1)), (0.0, -0.0),
                 (marker, "http://127.0.0.1:<port>/x"), (marker, "http://127.0.0.1:41001/x"), (marker, LoopbackURL("http://127.0.0.1:", "/y")), (marker, LoopbackURL("https://127.0.0.1:", "/x")),
                 (marker, ["loopback-url", ["http://127.0.0.1:", "/x"]]), (marker, ("loopback-url", ["http://127.0.0.1:", "/x"])), (marker, {"loopback-url": ["http://127.0.0.1:", "/x"]}),
                 (marker, [["loopback-url"], [["http://127.0.0.1:", "/x"]]]), (marker, ["http://127.0.0.1:", "/x"]), (marker, CORE["Obj"](("loopback-url", ["http://127.0.0.1:", "/x"])))]
        for a, b in twins:
            self.assertNotEqual(json.dumps(encode(a)), json.dumps(encode(b)), (a, b))
        self.assertEqual(json.dumps(encode({3, 1, 2})), json.dumps(encode({2, 3, 1})), "a set has no order")
        with self.assertRaises(TypeError):
            encode(object())
        with self.assertRaises(TypeError):
            encode(type("Sub", (LoopbackURL,), {})("a", "b"))   # the marker is not subclassed into something else

    def test_loopback_finds_the_allocated_port_by_parsing_and_keeps_every_other_byte(self) -> None:
        for value, head, tail in (("http://127.0.0.1:4100/a?b=1#c", "http://127.0.0.1:", "/a?b=1#c"), ("http://127.0.0.1:4100", "http://127.0.0.1:", ""), ("http://127.0.0.1:4100?q=1", "http://127.0.0.1:", "?q=1"),
                                  ("HTTP://127.0.0.1:4100/A", "HTTP://127.0.0.1:", "/A"), ("http://u:p%40@127.0.0.1:4100/x", "http://u:p%40@127.0.0.1:", "/x"), ("ftp://127.0.0.1:4100/x\ny", "ftp://127.0.0.1:", "/x\ny"),
                                  ("http://127.0.0.1:4100/127.0.0.1:4100?127.0.0.1:4100#127.0.0.1:4100", "http://127.0.0.1:", "/127.0.0.1:4100?127.0.0.1:4100#127.0.0.1:4100"),
                                  ("javascript://127.0.0.1:4100/a", "javascript://127.0.0.1:", "/a"), ("//127.0.0.1:4100/a", "//127.0.0.1:", "/a")):   # any scheme: the scheme is kept to the byte, the authority is what is structural
            got = loopback(value, 4100)
            self.assertIs(type(got), LoopbackURL, value)
            self.assertEqual((got.head, got.tail), (head, tail), value)
            self.assertEqual(got.head + "4100" + got.tail, value, "nothing but the port is left out")
        for kept in ("https://example.org/127.0.0.1:4100/a", "https://example.org/?next=http://127.0.0.1:4100/a", "https://example.org/#127.0.0.1:4100", "https://example.org/a?x=http://127.0.0.1:4100",
                     "http://127.0.0.1:<port>/a", "http://127.0.0.1:41000/a", "http://127.0.0.1:410/a", "http://127.0.0.1:04100/a", "http://127.0.0.1:4100:80/a", "http://127.0.0.1/a", "http://localhost:4100/a",
                     "http://10.127.0.0.1:4100/a", "http://127.0.0.1:4100@example.org/a", "http://x@127.0.0.1:4100.example.org/a", "///127.0.0.1:4100/a", "127.0.0.1:4100/a", "x//127.0.0.1:4100/a", "/127.0.0.1:4100/a", "",
                     " http://127.0.0.1:4100/a", " //127.0.0.1:4100/a", "http://127.0.0.1:4\n100/a", "ht\ntp://127.0.0.1:4100/a", "http:\n//127.0.0.1:4100/a", "\nhttp://127.0.0.1:4100/a", "http://[::1", "http://127.0.0.1:4100\\@example.org/", "javascript:127.0.0.1:4100/a"):
            self.assertIs(loopback(kept, 4100), kept, kept)
        for other in (None, 4100, b"http://127.0.0.1:4100/a", ["http://127.0.0.1:4100/a"]):
            self.assertIs(loopback(other, 4100), other)
        for bad in (0, -1, 65536, None, "4100", True, 4100.0):
            with self.assertRaises(ValueError):
                loopback("http://127.0.0.1:4100/a", bad)

    def test_loopback_looking_data_and_literal_marker_text_are_observed_exactly(self) -> None:
        """Astra's 2q-e1 reproductions: the same text that carries the allocated port, or the literal `<port>`, in a path, query, fragment or as a whole URL, is one observation and not the other."""
        embedded = {"a path": "https://example.org/127.0.0.1:{}/a", "a query": "https://example.org/?next=http://127.0.0.1:{}/a", "a fragment": "https://example.org/#127.0.0.1:{}",
                    "a next link": "http://127.0.0.1:{}/next"}
        for label, template in embedded.items():
            with self.subTest(label):
                real, literal = template.format(41001), template.format("<port>")
                got = VERDICT([world(url(real)), world(url(real))], [world(url(literal))])
                self.assertEqual((got["result"], got["tests"]["d/urls"]["verdict"]), ("DIFFERENT", "different"))
                same = VERDICT([world(url(literal)), world(url(literal))], [world(url(literal))])
                self.assertEqual(same["result"], "EQUIVALENT", "the same text on both sides is the same observation")
                moving = VERDICT([world(url(template.format(41001))), world(url(template.format(41002), 41002))], [world(url(literal))])
                if label != "a next link":
                    self.assertEqual((moving["result"], moving["tests"]["d/urls"]["verdict"]), ("UNRESOLVED", "unresolved"), "a value that moves from run to run is named, not hidden")
                else:   # an authority at the allocated port is the marker, whatever the port was
                    self.assertEqual(moving["result"], "DIFFERENT")

    def test_an_error_message_is_never_scrubbed_and_one_naming_the_listener_is_refused(self) -> None:
        for message in ("boom", "", None, 41001, "127.0.0.1:<port>", "127.0.0.1:410010", "127.0.0.1:4100", "10 127.0.0.1 41001", "localhost:41001", b"127.0.0.1:41001"):
            self.assertIs(unnamed(message, 41001), message)
        for message in ("URLError: <urlopen error 127.0.0.1:41001>", "http://127.0.0.1:41001/x refused", "x127.0.0.1:41001"):
            with self.assertRaises(ValueError):
                unnamed(message, 41001)


class Controls(unittest.TestCase):
    def test_runs_that_differ_only_by_the_allocated_port_are_equivalent_and_counted_once(self) -> None:
        got = VERDICT([world(port=1111), world(port=2222)], [world(port=3333), world(port=4444)])
        self.assertEqual((got["result"], got["counts"], got["observed"], got["drivers"], got["not_compared"]), ("EQUIVALENT", {"same": 5}, 5 + 30 + 1, DRIVERS, []))

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
        whole = world()["d"]
        empties = {"an empty JSON object": {}, "no groups": {**whole, "groups": {}}, "the surface driver's old empty shape": {"compared": {}, "informational": {}},
                   "a driver that did not complete": {**whole, "complete": False}, "a group with no cases": {**whole, "groups": {**whole["groups"], "urls": {"n": 0, "keys": "", "digest": ""}}},
                   "the runner's reason for no artifact": "no finished marker: a driver failed", "a null artifact": None}
        for label, art in empties.items():
            with self.subTest(label):
                why = self.refused(lambda runs: runs.update(d=art))["tests"]["d"]["sources"]
                self.assertTrue(all(isinstance(v, str) and v for v in why.values()))
        with self.assertRaises(SystemExit):
            Run("d").artifact()   # a driver that observed nothing writes nothing

    def test_a_malformed_envelope_or_erased_observations_are_unresolved_whatever_the_manifest_says(self) -> None:
        """Astra's erased-envelope reproduction (keep and cases removed, the digest blanked, count and identities kept) and each other way an artifact can stop being whole."""
        def erase(g):
            g.pop("keep"), g.pop("cases"), g.update(digest="")
        group = lambda name: ("d", name)   # noqa: E731  (driver, group): the damage is to that group; (driver, None): to the artifact's envelope
        faults = {
            "keep and cases removed and the digest blanked": (group("urls"), erase), "no keep": (group("urls"), lambda g: g.pop("keep")), "no cases": (group("urls"), lambda g: g.pop("cases")),
            "an empty digest": (group("urls"), lambda g: g.update(digest="")), "an upper-case digest": (group("urls"), lambda g: g.update(digest=g["digest"].upper())),
            "a short digest": (group("urls"), lambda g: g.update(digest=g["digest"][:63])), "a non-hex digest": (group("urls"), lambda g: g.update(digest="z" * 64)),
            "a non-hex identity digest": (group("urls"), lambda g: g.update(keys="z" * 64)), "a number for a digest": (group("urls"), lambda g: g.update(digest=7)),
            "a count that is a bool": (group("urls"), lambda g: g.update(n=True)), "a count that is a float": (group("urls"), lambda g: g.update(n=1.0)),
            "an unknown keep": (group("urls"), lambda g: g.update(keep="all")), "an extra field in a group": (group("urls"), lambda g: g.update(more=1)),
            "cases not an object": (group("urls"), lambda g: g.update(cases=[])), "a case fewer than counted": (group("answers"), lambda g: g["cases"].pop("a")),
            "a case renamed": (group("answers"), lambda g: g["cases"].update({"z": g["cases"].pop("a")})), "an observation replaced under its digest": (group("downloads"), lambda g: g["cases"].update(one=["bytes", "00"])),
            "cases kept by a bulk group": (group("bulk"), lambda g: g["cases"].update(x=1)), "a bulk group's digest erased": (group("bulk"), lambda g: g.update(digest="")),
            "a bulk group's identity digest short": (group("bulk"), lambda g: g.update(keys="a" * 63)), "a bulk group of no cases": (group("bulk"), lambda g: g.update(n=0)),
            "an unknown keep on a digested group": (("e", "digested"), lambda g: g.update(keep="all")),
            "a digested case renamed": (("e", "digested"), lambda g: g["cases"].update({"y": g["cases"].pop("x")})), "a digested count above its cases": (("e", "digested"), lambda g: g.update(n=2)),
            "a group count above its exact cases": (group("urls"), lambda g: g.update(n=2)), "a malformed case digest": (("e", "digested"), lambda g: g["cases"].update(x="zz")),
            "a case digest too long": (("e", "digested"), lambda g: g["cases"].update(x="a" * 64)),
            "no note": (("d", None), lambda a: a.pop("note")), "no version": (("d", None), lambda a: a.pop("version")), "another version": (("d", None), lambda a: a.update(version=2)),
            "a truthy mark that is not true": (("d", None), lambda a: a.update(complete="yes")), "another driver's name": (("d", None), lambda a: a.update(driver="e")),
            "an extra field": (("d", None), lambda a: a.update(extra=1)), "malformed inputs": (("d", None), lambda a: a.update(inputs={"n": 1})), "null inputs": (("d", None), lambda a: a.update(inputs=None)),
            "groups that are a list": (("d", None), lambda a: a.update(groups=[])),
        }
        for label, ((driver, name), fault) in faults.items():
            with self.subTest(label):
                damage = lambda runs: fault(runs[driver] if name is None else runs[driver]["groups"][name])   # noqa: E731
                got = self.refused(damage, driver=driver)
                self.assertTrue(all(isinstance(v, str) and v for t in got["tests"].values() for v in t["sources"].values()))
                runs = [world(), world()]
                for run in runs:
                    damage(run)
                with self.assertRaises(ValueError, msg="and no manifest is frozen from runs that are all alike damaged"):
                    freeze(runs, DRIVERS)
        broken = world()
        erase(broken["d"]["groups"]["urls"])
        with self.assertRaises(ValueError):
            freeze([broken, broken], DRIVERS)   # and no manifest is made from them

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

    def test_a_manifest_is_frozen_only_from_a_declared_driver_set_of_complete_runs_that_agree(self) -> None:
        empty = {"driver": "d", "version": 1, "complete": True, "note": None, "groups": {}}
        no_cases = {**world()["d"], "groups": {"g": {"n": 0, "keys": "k", "digest": "d"}}}
        for runs, drivers in (([world()], DRIVERS), ([world(), {"d": {}, "e": world()["e"]}], DRIVERS), ([world(), world(lambda s: s["answers"].update(c=1))], DRIVERS), ([world(), {"d": world()["d"]}], DRIVERS),
                              ([{"d": empty}, {"d": empty}], ["d"]), ([{"d": no_cases}, {"d": no_cases}], ["d"]), ([{}, {}], DRIVERS), ([{"d": world()["d"]}, {"d": world()["d"]}], DRIVERS)):
            with self.assertRaises(ValueError):
                freeze(runs, drivers)
        for drivers in ([], (), None, "d", ["d", "d"], ["d", ""], ["../d"], ["D"], ["d", 1], ["d e"], ["nope"]):
            with self.assertRaises(ValueError, msg=repr(drivers)):
                freeze([world(), world()], drivers)
        for odd in ("../d", "D", "d e", "", "9d", "d.json"):
            art = {odd: (lambda run: (run.observe("g", "c", 1), run.artifact())[1])(Run(odd))}
            with self.assertRaises(ValueError, msg=odd):
                freeze([art, art], [odd])   # a whole artifact of a driver that has no name a path can carry
        self.assertEqual(sorted(freeze([world(), world()], ["d"])["drivers"]), ["d"], "a driver subset is a declared one")
        got = compare([{"d": empty}] * 2, [{"d": empty}], {"version": 2, "drivers": {"d": {"groups": {"g": {"n": 1, "keys": "0" * 64}}, "inputs": None}}}, ["d"])
        self.assertEqual(got["result"], "UNRESOLVED", "even a manifest that declares one case does not make an empty run evidence")

    def test_a_manifest_is_checked_and_the_drivers_compared_are_declared(self) -> None:
        run, groups = world(), {"g": {"n": 1, "keys": "0" * 64}}
        base = {"version": 2, "drivers": {"d": {"groups": groups, "inputs": None}}}
        self.assertEqual(compare([run, run], [run], base, ["d"])["result"], "UNRESOLVED", "the base manifest is whole: only what each case below adds refuses it")
        for label, manifest in {"none": None, "empty": {}, "no drivers": {"version": 2, "drivers": {}}, "the old shape": {"d": groups}, "another version": {**base, "version": 1}, "a version that is a string": {**base, "version": "2"},
                                "an extra field": {**base, "more": 1}, "no version": {"drivers": base["drivers"]}, "drivers that are a list": {"version": 2, "drivers": []},
                                "a driver with no groups": {"version": 2, "drivers": {"d": {"groups": {}, "inputs": None}}},
                                "a group of no cases": {"version": 2, "drivers": {"d": {"groups": {"g": {"n": 0, "keys": "0" * 64}}, "inputs": None}}},
                                "a malformed digest": {"version": 2, "drivers": {"d": {"groups": {"g": {"n": 1, "keys": "x"}}, "inputs": None}}},
                                "an extra field in a group": {"version": 2, "drivers": {"d": {"groups": {"g": {"n": 1, "keys": "0" * 64, "more": 1}}, "inputs": None}}},
                                "no inputs field": {"version": 2, "drivers": {"d": {"groups": groups}}}, "malformed inputs": {"version": 2, "drivers": {"d": {"groups": groups, "inputs": {"n": 1}}}}}.items():
            with self.subTest(label), self.assertRaises(ValueError):
                compare([run, run], [run], manifest, ["d"])
        for label, drivers, subset in (("none declared", [], False), ("one of two, not declared a subset", ["d"], False), ("a driver the manifest lacks", ["d", "e", "f"], True), ("a driver the manifest lacks, alone", ["f"], True),
                                       ("duplicates", ["d", "d"], True), ("no names", None, True)):
            with self.subTest(label), self.assertRaises(ValueError):
                compare([run, run], [run], MANIFEST, drivers, subset)
        got = compare([world(), world()], [world()], MANIFEST, ["e"], subset=True)
        self.assertEqual((got["result"], got["drivers"], got["not_compared"], sorted(got["tests"])), ("EQUIVALENT", ["e"], ["d"], ["e/digested"]))
        with self.assertRaises(ValueError):
            compare([run, run], [run], MANIFEST, DRIVERS, inputs={"f": {}})


class Inventory(unittest.TestCase):
    """A corpus a generator wrote is an inventory only when sealed, and a driver fed by it covers exactly that inventory."""

    def generate(self, root: Path, n: int = 3, fail_after: int | None = None, name: str = "cases.jsonl", tag: str = "") -> Path:
        path = root / name
        with Corpus(path) as out:
            for i in range(n):
                if i == fail_after:
                    raise RuntimeError("the generator failed")
                out.add("g1" if i % 2 == 0 else "g2", f"c{i}", {"body": [i], "label": f"c{i}", "tag": tag})
        return path

    def driven(self, path: Path, skip=(), rename=(), group=None):
        run = Run("f", inputs=corpus(path))
        for line in path.read_text().splitlines():
            case = json.loads(line)
            if case["case"] not in skip:
                run.observe(group or case["group"], case["case"] + ("!" if case["case"] in rename else ""), case["record"]["body"], keep="digest")
        return {"f": run.artifact()}

    def test_a_sealed_corpus_is_an_inventory_and_a_failed_or_empty_generator_leaves_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.generate(root)
            sealed = corpus(path)
            self.assertEqual((sealed["n"], {g: v["n"] for g, v in sealed["groups"].items()}), (3, {"g1": 2, "g2": 1}))
            self.assertEqual(corpus(path, count=3, digest=sealed["digest"]), sealed)
            for declared in ({"count": 4}, {"digest": "0" * 64}, {"count": 3, "digest": "0" * 64}):
                with self.assertRaises(ValueError, msg=declared):
                    corpus(path, **declared)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["cases.jsonl", "cases.jsonl.seal"])
            with self.assertRaises(RuntimeError):   # a generator that fails after valid partial output, and removes what an earlier run left
                self.generate(root, fail_after=1)
            self.assertEqual(list(root.iterdir()), [], "no file, no seal and no temporary file")
            with self.assertRaises(SystemExit):
                self.generate(root, n=0)
            self.assertEqual(list(root.iterdir()), [])
            with self.assertRaises(ValueError):
                corpus(path)

    def test_a_file_that_is_not_the_sealed_one_or_a_seal_that_is_not_whole_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.generate(root)
            seal, lines = path.with_name("cases.jsonl.seal"), path.read_text().splitlines(keepends=True)
            good = json.loads(seal.read_text())
            for label, damage in {"a truncated file": lambda: path.write_text("".join(lines[:1])), "an appended line": lambda: path.write_text("".join(lines) + lines[0]),
                                  "a changed line of the same length": lambda: path.write_text("".join(lines).replace('"c1"', '"c9"')), "a missing file": lambda: path.unlink(), "an empty file": lambda: path.write_text(""),
                                  "a missing seal": lambda: seal.unlink(), "an unreadable seal": lambda: seal.write_text("{"), "an incomplete seal": lambda: seal.write_text(json.dumps({**good, "complete": False})),
                                  "a seal of no cases": lambda: seal.write_text(json.dumps({**good, "n": 0, "groups": {}})),
                                  "groups that do not add up to the count": lambda: seal.write_text(json.dumps({**good, "groups": {**good["groups"], "g1": {**good["groups"]["g1"], "n": 3}}})),
                                  "a count that is not the file's lines": lambda: seal.write_text(json.dumps({**good, "n": 4, "groups": {**good["groups"], "g1": {**good["groups"]["g1"], "n": 3}}})),
                                  "a malformed digest": lambda: seal.write_text(json.dumps({**good, "digest": "x"})), "an extra field": lambda: seal.write_text(json.dumps({**good, "more": 1})),
                                  "another version": lambda: seal.write_text(json.dumps({**good, "version": 2})), "a group digest erased": lambda: seal.write_text(json.dumps({**good, "groups": {**good["groups"], "g1": {"n": 2}}}))}.items():
                with self.subTest(label):
                    path.write_text("".join(lines))
                    seal.write_text(json.dumps(good))
                    damage()
                    with self.assertRaises(ValueError):
                        corpus(path)

    def test_a_driver_fed_by_a_sealed_corpus_covers_exactly_that_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.generate(Path(tmp))
            inventory, two = corpus(path), lambda **kw: [self.driven(path, **kw), self.driven(path, **kw)]
            manifest = freeze(two(), ["f"], {"f": inventory}, {"f": {"groups": 2, "cases": 3}})
            self.assertEqual(manifest["drivers"]["f"]["inputs"], {"n": 3, "digest": inventory["digest"]})
            self.assertEqual(manifest["drivers"]["f"]["groups"], inventory["groups"], "the expectation is the inventory's, group by group and identity by identity")
            for label, kw in {"a case fewer": {"skip": ("c2",)}, "a case renamed": {"rename": ("c0",)}, "one group for all": {"group": "g"}}.items():
                with self.subTest(label), self.assertRaises(ValueError):
                    freeze(two(**kw), ["f"], {"f": inventory})   # runs that agree with each other on a partial read are not an inventory
            other = self.generate(Path(tmp), n=4, name="other.jsonl")
            twin = corpus(self.generate(Path(tmp), name="twin.jsonl", tag="other content"))
            self.assertEqual((twin["n"], twin["groups"]), (inventory["n"], inventory["groups"]), "the same cases and identities")
            self.assertNotEqual(twin["digest"], inventory["digest"])
            for another in (corpus(other), twin):
                with self.assertRaises(ValueError):
                    freeze(two(), ["f"], {"f": another})   # runs that consumed another file
            for label, args in {"no inventory declared": (two(), ["f"], None), "an inventory for an undeclared driver": (two(), ["f"], {"f": inventory, "g": inventory}),
                                "an input for a driver that has none": ([world(), world()], DRIVERS, {"d": inventory}), "a size that is not the declared one": (two(), ["f"], {"f": inventory}, {"f": {"groups": 2, "cases": 4}}),
                                "no size for a driver": (two(), ["f"], {"f": inventory}, {})}.items():
                with self.subTest(label), self.assertRaises(ValueError):
                    freeze(*args)
            before, after = two(), self.driven(path)
            verdict = lambda ran, **kw: compare(before, ran, manifest, ["f"], **kw)   # noqa: E731
            self.assertEqual(verdict([after], inputs={"f": inventory})["result"], "EQUIVALENT")
            self.assertEqual(verdict([after])["result"], "UNRESOLVED", "a manifest bound to an input is compared only with that input supplied")
            self.assertEqual(verdict([after], inputs={"f": corpus(other)})["result"], "UNRESOLVED")
            self.assertEqual(verdict([after], inputs={"f": twin})["result"], "UNRESOLVED", "the same identities, another file")
            for label, kw in {"a case fewer": {"skip": ("c2",)}, "a case renamed": {"rename": ("c0",)}}.items():
                with self.subTest(label):
                    self.assertEqual(verdict([self.driven(path, **kw)], inputs={"f": inventory})["result"], "UNRESOLVED", label)
            unread = self.driven(path)
            unread["f"].pop("inputs")
            self.assertEqual(verdict([unread], inputs={"f": inventory})["result"], "UNRESOLVED", "a run that does not say what it consumed")


class RunDirectories(unittest.TestCase):
    def write(self, root: Path, name: str, finished=True, runs=None, ran=None) -> str:
        (root / name).mkdir()
        for driver, art in (runs or world()).items():
            (root / name / f"{driver}.json").write_text(json.dumps(art))
        if finished:
            (root / name / "finished").write_text(finished if isinstance(finished, str) else json.dumps({"version": 1, "drivers": ran or DRIVERS}))
        return str(root / name)

    def test_a_run_counts_only_with_its_finished_marker_and_the_cli_exits_with_the_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs = [self.write(root, name) for name in ("b1", "b2", "a1")]
            self.assertEqual(cli("freeze", root / "manifest.json", "--drivers", *DRIVERS, "--runs", runs[0], runs[1])[0], 0)
            check = lambda *after, drivers=DRIVERS, extra=(): cli("compare", root / "manifest.json", "--drivers", *drivers, *extra, "--before", runs[0], runs[1], "--after", *after, "--report", root / "r.json")   # noqa: E731
            self.assertEqual(check(runs[2])[0], 0)
            self.assertEqual(check(self.write(root, "a2", runs=world(lambda s: s["downloads"].update(one=b"changed"))))[0], 1)
            self.assertEqual(check(self.write(root, "a3", finished=False))[0], 2, "a run whose runner did not finish is no evidence")
            half = world()
            (root / "a4").mkdir()
            (root / "a4" / "d.json").write_text(json.dumps(half["d"]))
            (root / "a4" / "finished").write_text(json.dumps({"version": 1, "drivers": DRIVERS}))
            self.assertEqual(check(str(root / "a4"))[0], 2, "a driver with no artifact")
            self.assertEqual(json.loads((root / "r.json").read_text())["tests"]["e"]["sources"], {"after[0]": "a4/e.json: FileNotFoundError"})
            code, out, _ = check(runs[2], drivers=["e"], extra=["--subset"])
            self.assertEqual((code, "drivers not compared (a declared subset): ['d']" in out), (0, True))

    def test_the_cli_refuses_an_undeclared_driver_set_missing_directories_and_an_empty_manifest(self) -> None:
        """Astra's zero-driver reproduction: three directories that do not exist, no artifact and no marker, froze `{}` and compared EQUIVALENT."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = [str(root / name) for name in ("missing-1", "missing-2", "missing-3")]
            manifest = root / "manifest.json"
            for argv in (("freeze", manifest, *missing[:2]), ("freeze", manifest, "--runs", *missing[:2]), ("freeze", manifest, "--drivers", "--runs", *missing[:2]), ("compare", manifest, "--before", *missing[:2], "--after", missing[2])):
                self.assertEqual(cli(*argv)[0], 2, argv)   # no driver is declared
            code, _, err = cli("freeze", manifest, "--drivers", *DRIVERS, "--runs", *missing[:2])
            self.assertEqual((code, manifest.exists(), "no such run directory" in err or "no finished marker" in err), (2, False, True), "nothing is frozen from nothing")
            manifest.write_text("{}")
            for drivers in (DRIVERS, ["d"]):
                self.assertEqual(cli("compare", manifest, "--drivers", *drivers, "--before", *missing[:2], "--after", missing[2])[0], 2, "an empty manifest compares nothing")
            manifest.write_text(json.dumps({"version": 2, "drivers": {}}))
            self.assertEqual(cli("compare", manifest, "--drivers", *DRIVERS, "--before", *missing[:2], "--after", missing[2])[0], 2)
            self.assertEqual(cli("compare", root / "absent.json", "--drivers", *DRIVERS, "--before", *missing[:2], "--after", missing[2])[0], 2)
            runs = [self.write(root, name) for name in ("b1", "b2", "a1")]
            self.assertEqual(cli("freeze", manifest, "--drivers", *DRIVERS, "--runs", runs[0], runs[1])[0], 0)
            for label, argv in {"the same run twice for a baseline": ("freeze", root / "m2.json", "--drivers", *DRIVERS, "--runs", runs[0], runs[0]),
                                "one run": ("freeze", root / "m3.json", "--drivers", *DRIVERS, "--runs", runs[0]),
                                "the same run on both sides": ("compare", manifest, "--drivers", *DRIVERS, "--before", runs[0], runs[1], "--after", runs[0]),
                                "a driver not in the manifest": ("compare", manifest, "--drivers", "d", "e", "f", "--subset", "--before", runs[0], runs[1], "--after", runs[2]),
                                "a subset not declared": ("compare", manifest, "--drivers", "d", "--before", runs[0], runs[1], "--after", runs[2]),
                                "an input that is not a pair": ("compare", manifest, "--drivers", *DRIVERS, "--input", "cases", "--before", runs[0], runs[1], "--after", runs[2]),
                                "an input that is not sealed": ("compare", manifest, "--drivers", *DRIVERS, "--input", f"d={root / 'nope.jsonl'}", "--before", runs[0], runs[1], "--after", runs[2])}.items():
                self.assertEqual(cli(*argv)[0], 2, label)
            self.assertIn("DRIVER=CASES.jsonl", cli("compare", manifest, "--drivers", *DRIVERS, "--input", "cases", "--before", runs[0], runs[1], "--after", runs[2])[2])
            self.assertFalse((root / "m2.json").exists() or (root / "m3.json").exists())
            for label, marker in {"a marker of the old kind": "done\n", "a marker naming other drivers": json.dumps({"version": 1, "drivers": ["x"]}), "a marker naming one of the two": json.dumps({"version": 1, "drivers": ["d"]})}.items():
                self.assertEqual(cli("compare", manifest, "--drivers", *DRIVERS, "--before", runs[0], runs[1], "--after", self.write(root, "x" + str(len(label)), finished=marker))[0], 2, label)

    def test_the_corpus_command_checks_a_sealed_generator_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.jsonl"
            self.assertEqual(cli("corpus", path)[0], 2, "no corpus")
            with Corpus(path) as out:
                out.add("g", "c", {"x": 1})
            self.assertEqual(cli("corpus", path)[0], 0)
            self.assertEqual(cli("corpus", path, "--count", 1)[0], 0)
            self.assertEqual(cli("corpus", path, "--count", 2)[0], 2)
            self.assertEqual(cli("corpus", path, "--digest", "0" * 64)[0], 2)
            self.assertEqual(cli("corpus", path, "--digest", corpus(path)["digest"])[0], 0)
            path.write_text("")
            self.assertEqual(cli("corpus", path)[0], 2)

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
            def partly(doc, handle, **kw):
                handle.write("{")
                self.assertFalse((Path(tmp) / "d.json").exists(), "a reader never sees a part of an artifact under its name")
                raise OSError("disk full")
            with mock.patch("json.dump", side_effect=partly), self.assertRaises(OSError):
                run.finish(Path(tmp) / "d.json")
            self.assertEqual(list(Path(tmp).iterdir()), [], "a write that fails part-way leaves nothing, not even its temporary file")

    def test_an_artifact_keeps_its_cases_in_order_so_a_written_run_is_whole_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("d")
            for case in ("b", "a", "c"):
                run.observe("g", case, [case], keep="exact")
            run.finish(Path(tmp) / "d.json")
            written = json.loads((Path(tmp) / "d.json").read_text())
            self.assertEqual(list(written["groups"]["g"]["cases"]), ["b", "a", "c"])
            self.assertEqual(CORE["shaped"](written, "d"), None)

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
