"""Black-box tests of how the ratchet in `tools/gen2_metrics.py` treats a
BASELINED function over the thresholds (task 2q-a-repair F2; Astra's 2q-a
review: the report filtered functions to those currently over a threshold
before the ratchet compared them, so a baselined function whose cyclomatic
score fell under its threshold while its cognitive score rose, or the other
way about, left the comparison and was recorded as an improvement).

The rule under test is the tool's own promise: an existing offender may not
grow in either metric. A baselined function is compared in BOTH dimensions
with its baseline whatever the thresholds say; the thresholds only decide
which OTHER functions are new offenders; a baselined entry leaves the
baseline only when neither dimension grew and neither is over a threshold.

Scores are worked out by hand from the fixture's text. With `k` asserts and
a chain of `m` nested ifs, a function has cyclomatic 1 + k + m (an assert
and an if are a branch each) and cognitive 1 + 2 + ... + m (each if costs
one plus its depth; an assert costs nothing). The thresholds are 20
(cyclomatic) and 30 (cognitive), "over" meaning strictly more.

What this cannot show: that the proxies measure what a reviewer needs (that
is test_metrics_measure.py), or that splitting a function into smaller ones
is not score manipulation (a limit of any per-function measure; review
distinguishes real decomposition).
"""
from __future__ import annotations

from gen2.tests.test_metrics_ratchet import RatchetTestCase, exemption
from gen2.tests.tool_repo_fixtures import BASELINE, EXEMPTIONS, py


def scored(nested: int = 0, asserts: int = 0, name: str = "f") -> str:
    """A function with `asserts` asserts and a chain of `nested` ifs: cyclomatic 1 + asserts + nested, cognitive nested * (nested + 1) / 2."""
    chain = [f"{'    ' * (i + 1)}if a:" for i in range(nested)]
    return py(f"def {name}(a):", *chain, f"{'    ' * (nested + 1)}pass", *(["    assert a"] * asserts))


PATH, LOCATION = "gen2/m.py", "engine:gen2/m.py::f"


class BaselinedOffenderTest(RatchetTestCase):
    def baselined_at(self, source: str, expect: dict):
        repo = self.baselined({PATH: source})
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"], {PATH + "::f": expect})
        return repo

    def test_astras_probe_a_function_that_leaves_both_thresholds_while_one_score_grows_fails(self) -> None:
        repo = self.baselined_at(scored(0, 20), {"cyclomatic": 21, "cognitive": 0})   # twenty asserts: over the cyclomatic limit only
        repo.write({PATH: scored(7, 0)})                                              # seven nested ifs: cyclomatic 8, cognitive 28: under both limits
        done = self.check(repo, 1)
        self.assertIn(f"function_cognitive {LOCATION}: 28 against a baseline of 0", done.stderr)
        self.assertNotIn("function_cyclomatic", done.stderr)   # cyclomatic fell 21 -> 8: only the cognitive growth is a regression
        self.assertNotIn("no longer over", done.stdout)        # and it is not an improvement

    def test_the_rebaseline_refuses_it_and_the_entry_stays(self) -> None:
        repo = self.baselined_at(scored(0, 20), {"cyclomatic": 21, "cognitive": 0})
        repo.write({PATH: scored(7, 0)})
        before = (repo.root / BASELINE).read_bytes()
        done = repo.run("rebaseline")
        self.assertEqual(done.returncode, 1)
        self.assertIn("refused", done.stderr)
        self.assertEqual((repo.root / BASELINE).read_bytes(), before)

    def test_the_opposite_direction_across_the_thresholds_fails_too(self) -> None:
        # baselined for its cognitive score alone: nine nested ifs would be 45; eight are 36 (cyclomatic 9)
        repo = self.baselined_at(scored(8, 0), {"cyclomatic": 9, "cognitive": 36})
        # cyclomatic grows to exactly the limit (17 asserts and 2 nested ifs: 20) while cognitive falls to 3: under both thresholds
        repo.write({PATH: scored(2, 17)})
        done = self.check(repo, 1)
        self.assertIn(f"function_cyclomatic {LOCATION}: 20 against a baseline of 9", done.stderr)
        self.assertNotIn("function_cognitive", done.stderr)

    def test_growth_across_a_threshold_in_the_other_metric_fails_while_the_first_improves(self) -> None:
        repo = self.baselined_at(scored(0, 20), {"cyclomatic": 21, "cognitive": 0})
        repo.write({PATH: scored(8, 0)})   # cyclomatic 9 (under), cognitive 36 (over)
        done = self.check(repo, 1)
        self.assertIn(f"function_cognitive {LOCATION}: 36 against a baseline of 0", done.stderr)

    def test_both_scores_improving_passes_and_the_entry_leaves_the_baseline(self) -> None:
        repo = self.baselined_at(scored(8, 22), {"cyclomatic": 31, "cognitive": 36})
        repo.write({PATH: scored(3, 10)})   # cyclomatic 14, cognitive 6: both fell, both are under the limits
        done = self.check(repo, 0)
        self.assertIn(f"improved: function {LOCATION} is no longer over the thresholds", done.stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"], {})
        repo.write({BASELINE: (repo.root / BASELINE).read_text(), PATH: scored(0, 20)})   # and it may not come back as an offender
        self.assertIn(f"function_cyclomatic {LOCATION}: 21 against a baseline of limit 20, not an offender", self.check(repo, 1).stderr)

    def test_one_score_improving_and_the_other_unchanged_passes_and_records_the_lower_value(self) -> None:
        repo = self.baselined_at(scored(8, 22), {"cyclomatic": 31, "cognitive": 36})
        repo.write({PATH: scored(8, 14)})   # cyclomatic 23 (still over), cognitive 36 unchanged
        done = self.check(repo, 0)
        self.assertIn(f"improved: function {LOCATION}: 23/36, baseline 31/36", done.stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"][PATH + "::f"], {"cyclomatic": 23, "cognitive": 36})

    def test_a_score_that_stays_where_it_was_is_no_growth_even_under_the_thresholds(self) -> None:
        repo = self.baselined_at(scored(0, 20), {"cyclomatic": 21, "cognitive": 0})
        repo.write({PATH: scored(0, 20) + "# a comment\n"})
        self.check(repo, 0)

    def test_an_exempted_growth_is_never_recorded_and_the_entry_stays_with_the_old_value(self) -> None:
        repo = self.baselined_at(scored(0, 20), {"cyclomatic": 21, "cognitive": 0})
        repo.write({PATH: scored(7, 0), EXEMPTIONS: exemption("EX-1", metric="function_cognitive", location=LOCATION, limit="28")})
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        # cyclomatic improved 21 -> 8 and is recorded; cognitive 0 -> 28 is exempted and is NOT: the entry stays although both scores are under the limits
        self.assertEqual(repo.baseline()["services"]["engine"]["functions"][PATH + "::f"], {"cyclomatic": 8, "cognitive": 0})
        repo.write({EXEMPTIONS: "# no exemptions\n"})
        self.assertIn(f"function_cognitive {LOCATION}: 28 against a baseline of 0", self.check(repo, 1).stderr)

    def test_each_dimension_is_its_own_violation_with_its_own_location(self) -> None:
        repo = self.baselined_at(scored(0, 20), {"cyclomatic": 21, "cognitive": 0})
        repo.write({PATH: scored(8, 14)})   # cyclomatic 23 (grew by two), cognitive 36 (grew by 36)
        done = self.check(repo, 1)
        self.assertIn(f"function_cyclomatic {LOCATION}: 23 against a baseline of 21", done.stderr)
        self.assertIn(f"function_cognitive {LOCATION}: 36 against a baseline of 0", done.stderr)


class NewOffenderTest(RatchetTestCase):
    """The thresholds, applied to a function the baseline does not hold."""

    def test_a_new_function_under_both_thresholds_is_not_an_offender_however_close(self) -> None:
        repo = self.baselined({PATH: "v = 1\n"})
        repo.write({PATH: scored(7, 12)})   # cyclomatic 20, cognitive 28: at and under the limits
        self.check(repo, 0)

    def test_a_renamed_offender_is_a_new_function_and_the_old_name_is_gone(self) -> None:
        repo = self.baselined({PATH: scored(0, 20)})
        repo.write({PATH: scored(0, 20, "g")})
        done = self.check(repo, 1)
        self.assertIn("function_cyclomatic engine:gen2/m.py::g: 21 against a baseline of limit 20, not an offender", done.stderr)
        self.assertIn("function engine:gen2/m.py::f is no longer over the thresholds (or is gone)", done.stdout)
