"""Black-box tests of the effective transition plan (task 2q-a-repair-3; Gate D #4 R3 and checklist 4).

Gate D #4 reproduced it: with an explicit valid `f -> g` map and a new isolated file, `admit` kept the map and also drafted a retirement of the same identity,
and the filled-in ledger failed with `duplicate/conflicting subject`. Checking, drafting and folding now read ONE plan, computed from the baseline, the current
facts and the entries already written: the author's explicit maps, retirements and moves first; then the retirements and admissions still owed; then the numeric
budgets derived from that plan. These tests state the acceptance cases of the checklist and the deterministic expansion of an explicit move, with literal
fixtures and hand-counted expectations:

  * a rename plus a new file and import passes after valid entries, and the old ceilings and persistent IDs survive;
  * the drafter never drafts the retirement of a mapped identity, nor the admission of a destination the map already claims;
  * drafting is idempotent before and after the reasons are filled;
  * a destination below both thresholds is a valid target (an old budget follows the function, not the threshold);
  * collisions and stale maps fail, naming the identity;
  * an explicit file or directory move expands, deterministically and only from what the author stated, to a map of every identity that mentions the file; an
    identity with no counterpart at the destination is owed an explicit retirement, and no wildcard or similarity admits or maps anything.

What this cannot show: that an author's stated reason is true (reviewed metadata, trust model B).
"""
from __future__ import annotations

from gen2.tests.test_metrics_dependencies import CHAIN
from gen2.tests.test_metrics_identity import LEDGER, entry, identity, write_ledger
from gen2.tests.test_metrics_offenders import scored
from gen2.tests.test_metrics_ratchet import RatchetTestCase
from gen2.tests.tool_repo_fixtures import BASELINE, py


def sections(repo) -> list[dict]:
    """The entries of the ledger as dicts, in order (the file's own text, not the tool's view of it)."""
    out, current = [], None
    for line in (repo.root / LEDGER).read_text().splitlines():
        if line.startswith("### ML-"):
            current = {"id": line[4:]}
            out.append(current)
        elif current is not None and line.startswith("- ") and ": " in line:
            key, _, value = line[2:].partition(": ")
            current[key] = value
    return out


def fill(repo, reason="Reviewed fixture transition for task 2q-a-repair-3") -> str:
    """The drafted entries with their reasons and tasks filled (the header text, which mentions `reason: TODO`, is the tool's own and is left alone), committed."""
    text = (repo.root / LEDGER).read_text().replace("\n- reason: TODO\n", f"\n- reason: {reason}\n").replace("\n- task: TODO\n", "\n- task: 2q-a-repair-3\n")
    repo.write({LEDGER: text})
    return text


class RenameAndNewFileTest(RatchetTestCase):
    """Gate D #4 R3, step by step."""

    def renamed(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20), "gen2/p/b.py": "v=1\n"})
        registry = dict(repo.baseline()["identities"])
        repo.write({"gen2/p/a.py": scored(0, 19, "g"), "gen2/p/new.py": "import gen2.p.b\n"})   # f is now g (cyclomatic 20, below both thresholds), and a new file imports b
        return repo, registry, identity(repo, "engine|function|gen2/p/a.py::f")

    def test_without_a_map_the_drafter_owes_a_retirement_and_three_admissions(self):
        repo, _registry, ident = self.renamed()
        self.assertEqual(repo.run("admit").returncode, 0)
        drafted = sections(repo)
        self.assertEqual(sorted((s["action"], s.get("identity") or s.get("target")) for s in drafted),
                         [("admit", "engine|edge|gen2/p/new.py->gen2/p/b.py"), ("admit", "engine|file|gen2/p/new.py"), ("admit", "engine|reach|gen2/p/new.py->gen2/p/b.py"), ("retire", ident)])

    def test_with_an_explicit_map_the_drafter_drafts_no_retirement_of_the_mapped_identity(self):
        repo, _registry, ident = self.renamed()
        write_ledger(repo, entry("map", identity=ident, target="engine|function|gen2/p/a.py::g"))
        self.assertEqual(repo.run("admit").returncode, 0)
        drafted = sections(repo)
        self.assertEqual([s for s in drafted if s["action"] == "retire"], [])
        self.assertEqual(sorted(s["target"] for s in drafted if s["action"] == "admit"),
                         ["engine|edge|gen2/p/new.py->gen2/p/b.py", "engine|file|gen2/p/new.py", "engine|reach|gen2/p/new.py->gen2/p/b.py"])
        self.assertEqual(sum(s["action"] == "map" for s in drafted), 1)   # the author's own entry is kept, not rewritten and not duplicated

    def test_the_filled_ledger_passes_keeps_the_old_ceilings_and_the_persistent_ids_and_adds_new_ones(self):
        repo, registry, ident = self.renamed()
        write_ledger(repo, entry("map", identity=ident, target="engine|function|gen2/p/a.py::g"))
        self.assertEqual(repo.run("admit").returncode, 0)
        fill(repo)
        self.assertEqual(repo.run("check").returncode, 0, msg=repo.run("check").stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        after = repo.baseline()
        self.assertEqual(after["identities"][ident], "engine|function|gen2/p/a.py::g")   # the same MI id, the new location
        self.assertEqual(after["services"]["engine"]["functions"]["gen2/p/a.py::g"], {"cyclomatic": 20, "cognitive": 0})   # f's budget followed the function below the threshold, tightened to its score
        self.assertTrue({k: v for k, v in registry.items() if k != ident}.items() <= after["identities"].items(), msg="every other identity kept its id")
        self.assertEqual(len(after["identities"]) - len(registry), 3)   # the file, the edge and the reach pair were admitted with new ids
        self.assertEqual(sections(repo), [])   # the ledger starts empty again: every transition is folded into the baseline

    def test_a_rename_that_raises_a_score_above_the_old_ceiling_still_fails_after_the_map(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20)})   # cyclomatic 21
        ident = identity(repo, "engine|function|gen2/p/a.py::f")
        repo.write({"gen2/p/a.py": scored(0, 21, "g")})   # cyclomatic 22
        write_ledger(repo, entry("map", identity=ident, target="engine|function|gen2/p/a.py::g"))
        self.assertIn("function_cyclomatic engine:gen2/p/a.py::g: 22 against a baseline of 21", self.check(repo, 1).stderr)

    def test_the_destination_of_a_map_is_not_drafted_as_a_new_admission(self):
        """A destination that is an offender is a claimed identity: the old drafter proposed its admission beside the map."""
        repo = self.baselined({"gen2/p/a.py": scored(0, 20)})
        ident = identity(repo, "engine|function|gen2/p/a.py::f")
        repo.write({"gen2/p/a.py": scored(0, 20, "g")})
        write_ledger(repo, entry("map", identity=ident, target="engine|function|gen2/p/a.py::g"))
        self.assertEqual(repo.run("admit").returncode, 0)
        self.assertEqual([s["action"] for s in sections(repo)], ["map"])
        repo.write({})   # the re-rendered ledger is committed, as the author would
        self.check(repo, 0)


class IdempotentDraftingTest(RatchetTestCase):
    def test_drafting_twice_changes_nothing_before_or_after_the_reasons_are_filled(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": py("import gen2.p.b", "import gen2.p.c"), "gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b")})
        self.assertEqual(repo.run("admit").returncode, 0)
        first = (repo.root / LEDGER).read_text()
        self.assertEqual(repo.run("admit").returncode, 0)
        self.assertEqual((repo.root / LEDGER).read_text(), first, "before: the TODO entries are the ledger's entries, not drafted again")
        filled = fill(repo)
        self.assertEqual(repo.run("admit").returncode, 0)
        self.assertEqual((repo.root / LEDGER).read_text(), filled, "after: the reasoned entries are not drafted again either")

    def test_a_ledger_that_already_covers_the_plan_drafts_nothing(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": "v=1\n"})
        write_ledger(repo, entry("admit", target="engine|file|gen2/p/new.py"))
        before = sections(repo)
        done = repo.run("admit")
        self.assertIn("drafted 0 entries", done.stdout)
        self.assertEqual(sections(repo), before)

    def test_a_budget_the_plan_derives_is_drafted_once_with_its_limit(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/new.py": py("import gen2.p.c")})
        self.assertEqual(repo.run("admit").returncode, 0)
        budgets = [s for s in sections(repo) if s["action"] == "budget"]
        self.assertEqual([(b["metric"], b["location"], b.get("limit")) for b in budgets], [("fan_in", "engine:gen2/p/c.py", "2")])
        self.assertEqual(repo.run("admit").returncode, 0)
        self.assertEqual(len([s for s in sections(repo) if s["action"] == "budget"]), 1)


class MapFailureTest(RatchetTestCase):
    def two_functions(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20) + scored(0, 20, "g")})
        return repo, identity(repo, "engine|function|gen2/p/a.py::f"), identity(repo, "engine|function|gen2/p/a.py::g")

    def test_two_identities_mapped_to_one_destination_fail_naming_it(self):
        repo, f, g = self.two_functions()
        repo.write({"gen2/p/a.py": scored(0, 19, "h")})
        write_ledger(repo, entry("map", identity=f, target="engine|function|gen2/p/a.py::h"), entry("map", identity=g, target="engine|function|gen2/p/a.py::h"))
        done = self.check(repo, 1)
        self.assertIn("engine|function|gen2/p/a.py::h: two identities map to one location", done.stderr)

    def test_a_map_onto_the_location_of_an_identity_that_is_still_present_is_a_collision(self):
        repo, f, g = self.two_functions()
        repo.write({"gen2/p/a.py": scored(0, 20, "g")})   # f is gone, g stays where it was
        write_ledger(repo, entry("map", identity=f, target="engine|function|gen2/p/a.py::g"))
        done = self.check(repo, 1)
        self.assertIn("two identities map to one location", done.stderr)
        self.assertEqual(repo.run("rebaseline").returncode, 1)

    def test_a_map_whose_old_location_is_still_present_is_stale(self):
        repo, f, _g = self.two_functions()
        repo.write({"gen2/p/a.py": scored(0, 20) + scored(0, 20, "g") + scored(0, 19, "h")})   # nothing moved: h is new
        write_ledger(repo, entry("map", identity=f, target="engine|function|gen2/p/a.py::h"))
        self.assertIn("invalid map: old must be absent, target present in same service/kind", self.check(repo, 1).stderr)

    def test_a_map_repeated_after_the_rebaseline_that_folded_it_is_stale(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20)})
        ident = identity(repo, "engine|function|gen2/p/a.py::f")
        repo.write({"gen2/p/a.py": scored(0, 19, "g")})
        write_ledger(repo, entry("map", identity=ident, target="engine|function|gen2/p/a.py::g"))
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        repo.write({BASELINE: (repo.root / BASELINE).read_text()})
        write_ledger(repo, entry("map", identity=ident, target="engine|function|gen2/p/a.py::g"))   # the identity is already at g: g is present, so the old location is not absent
        self.assertIn("invalid map", self.check(repo, 1).stderr)

    def test_a_map_whose_destination_is_missing_is_not_overwritten_by_a_drafted_retirement(self):
        repo, f, _g = self.two_functions()
        repo.write({"gen2/p/a.py": scored(0, 20, "g")})
        write_ledger(repo, entry("map", identity=f, target="engine|function|gen2/p/a.py::nowhere"))   # the author's map names a destination that is not there
        self.assertEqual(repo.run("admit").returncode, 0)
        self.assertEqual([s["action"] for s in sections(repo)], ["map"])   # the drafter does not contradict it: the check reports the map, the author fixes it
        repo.write({})
        self.assertIn("invalid map", self.check(repo, 1).stderr)

    def test_a_retirement_of_an_identity_that_is_still_present_is_refused_as_such(self):
        repo, f, _g = self.two_functions()
        write_ledger(repo, entry("retire", identity=f))   # nothing moved: f is where it was
        self.assertIn("engine|function|gen2/p/a.py::f: retirement requires absence", self.check(repo, 1).stderr)

    def test_a_map_to_a_destination_that_is_not_there_or_of_another_kind_fails(self):
        repo, f, _g = self.two_functions()
        repo.write({"gen2/p/a.py": scored(0, 20, "g")})
        for target in ("engine|function|gen2/p/a.py::nowhere", "engine|file|gen2/p/a.py", "gateway|function|gen2/p/a.py::g"):
            with self.subTest(target=target):
                write_ledger(repo, entry("map", identity=f, target=target))
                self.assertIn("invalid map", self.check(repo, 1).stderr)


class MoveTest(RatchetTestCase):
    """An explicit move: one statement, deterministic expansion, grouped presentation, nothing inferred and nothing admitted."""

    def move_entry(self, old, new, **extra):
        return {"action": "move", "from": old, "to": new, "reason": "Explicit fixture move for task 2q-a-repair-3", "task": "2q-a-repair-3", **extra}

    def test_a_file_move_is_one_entry_and_maps_every_identity_that_mentions_the_file(self):
        repo = self.baselined(CHAIN)
        registry = dict(repo.baseline()["identities"])
        mentioning = {k for k, v in registry.items() if "gen2/p/a.py" in v}
        repo.write({"gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b")})
        self.assertIn("missing", self.check(repo, 1).stderr)
        write_ledger(repo, self.move_entry("gen2/p/a.py", "gen2/p/renamed.py"))
        done = self.check(repo, 0)
        self.assertIn("ledger move gen2/p/a.py", done.stdout)
        self.assertRegex(done.stdout, r"ledger ML-1 move gen2/p/a.py -> gen2/p/renamed.py maps \d+ identities: gen2/p/a.py: .*\b1 file\b")
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        after = repo.baseline()["identities"]
        self.assertEqual(after, {k: v.replace("gen2/p/a.py", "gen2/p/renamed.py") if k in mentioning else v for k, v in registry.items()})
        self.assertEqual(repo.baseline()["services"]["engine"]["fan_out"]["gen2/p/renamed.py"], 1)
        self.assertEqual(sections(repo), [])

    def test_the_move_equals_the_hand_written_maps_it_replaces(self):
        """The same transition, written once per identity as in repair-2 and as one move, leaves the same baseline: the expansion is deterministic."""
        hand, one = self.baselined(CHAIN), self.baselined(CHAIN)
        for repo in (hand, one):
            repo.write({"gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b")})
        registry = dict(hand.baseline()["identities"])
        write_ledger(hand, *(entry("map", identity=k, target=v.replace("gen2/p/a.py", "gen2/p/renamed.py")) for k, v in registry.items() if "gen2/p/a.py" in v))
        write_ledger(one, self.move_entry("gen2/p/a.py", "gen2/p/renamed.py"))
        for repo in (hand, one):
            self.assertEqual(repo.run("rebaseline").returncode, 0)
        a, b = hand.baseline(), one.baseline()
        for key in ("identities", "identity_serial", "services", "cross_service_imports", "thresholds"):
            self.assertEqual(a[key], b[key], msg=key)

    def test_a_move_admits_nothing_so_a_new_import_in_the_moved_file_still_needs_admission(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b", "import gen2.p.c")})
        write_ledger(repo, self.move_entry("gen2/p/a.py", "gen2/p/renamed.py"))
        done = self.check(repo, 1)
        self.assertIn("fan_out engine:gen2/p/renamed.py: 2 against a baseline of 1", done.stderr)
        self.assertIn("admission engine|edge|gen2/p/renamed.py->gen2/p/c.py", done.stderr)

    def test_an_identity_with_no_counterpart_at_the_destination_needs_its_own_retirement(self):
        repo = self.baselined({"gen2/p/a.py": scored(0, 20) + scored(0, 20, "g")})
        f, g = identity(repo, "engine|function|gen2/p/a.py::f"), identity(repo, "engine|function|gen2/p/a.py::g")
        repo.write({"gen2/p/a.py": None, "gen2/p/b.py": scored(0, 20)})   # only f moved: g was dropped in the move
        write_ledger(repo, self.move_entry("gen2/p/a.py", "gen2/p/b.py"))
        done = self.check(repo, 1)
        self.assertIn("engine|function|gen2/p/a.py::g: invalid map: old must be absent, target present in same service/kind (expanded from ML-1)", done.stderr)
        write_ledger(repo, self.move_entry("gen2/p/a.py", "gen2/p/b.py"), entry("retire", identity=g))   # an explicit entry overrides the expansion for that identity
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        after = repo.baseline()["identities"]
        self.assertEqual((after[f], g in after), ("engine|function|gen2/p/b.py::f", False))

    def test_a_directory_move_maps_the_files_it_finds_at_the_destination_and_the_edges_that_mention_them(self):
        files = {"gen2/old/__init__.py": "", "gen2/old/a.py": py("import gen2.old.b"), "gen2/old/b.py": "v=1\n", "gen2/user.py": py("import gen2.old.a")}
        repo = self.baselined(files)
        registry = dict(repo.baseline()["identities"])
        repo.write({"gen2/old/__init__.py": None, "gen2/old/a.py": None, "gen2/old/b.py": None, "gen2/new/__init__.py": "", "gen2/new/a.py": py("import gen2.new.b"),
                    "gen2/new/b.py": "v=1\n", "gen2/user.py": py("import gen2.new.a")})
        write_ledger(repo, self.move_entry("gen2/old/", "gen2/new/"))
        done = self.check(repo, 0)   # every identity of the old files, and the edge and reach pairs of the importer that name them, are mapped by the one statement
        self.assertRegex(done.stdout, r"ML-1 move gen2/old/ -> gen2/new/ maps 8 identities: ")
        self.assertIn("gen2/user.py: 1 edge, 2 reach", done.stdout)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        after = repo.baseline()["identities"]
        self.assertEqual(after, {k: v.replace("gen2/old/", "gen2/new/") for k, v in registry.items()})

    def test_a_directory_move_maps_only_the_files_the_destination_holds(self):
        files = {"gen2/old/a.py": py("import gen2.old.b"), "gen2/old/b.py": "v=1\n"}
        repo = self.baselined(files)
        repo.write({"gen2/old/a.py": None, "gen2/old/b.py": None, "gen2/new/a.py": "v=2\n"})   # b has no counterpart at the destination: nothing is inferred for it
        write_ledger(repo, self.move_entry("gen2/old/", "gen2/new/"))
        done = self.check(repo, 1)
        self.assertIn("engine|file|gen2/old/b.py: missing; map or retire in committed ledger", done.stderr)
        self.assertNotIn("engine|file|gen2/old/a.py", done.stderr)
        for line in done.stderr.splitlines():   # a file the destination lacks is not mapped by the move at all: it is plainly missing
            if "engine|file|gen2/old/b.py" in line:
                self.assertNotIn("(expanded from", line)

    def test_a_move_rewrites_every_path_a_reference_names_and_keeps_a_cycle_sorted(self):
        """A file in a cycle moves to a name that sorts after its neighbour: the cycle's identity lists its files sorted, so the move must rewrite it sorted. The
        component names of the cycle's component identity are not paths of the move, so the author maps that one by hand."""
        repo = self.baselined({"gen2/a.py": py("import gen2.b"), "gen2/b.py": py("import gen2.a")})
        registry = dict(repo.baseline()["identities"])
        cycle_file = identity(repo, "engine|cycle_file|gen2/a.py,gen2/b.py")
        cycle_component = identity(repo, "engine|cycle_component|gen2.a,gen2.b")
        repo.write({"gen2/a.py": None, "gen2/z.py": py("import gen2.b"), "gen2/b.py": py("import gen2.z")})
        write_ledger(repo, self.move_entry("gen2/a.py", "gen2/z.py"),
                     entry("map", identity=cycle_component, target="engine|cycle_component|gen2.b,gen2.z"))
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        after = repo.baseline()["identities"]
        self.assertEqual((after[cycle_file], after[cycle_component]), ("engine|cycle_file|gen2/b.py,gen2/z.py", "engine|cycle_component|gen2.b,gen2.z"))
        self.assertEqual(set(after), set(registry))

    def test_a_move_of_the_importee_rewrites_the_far_side_of_each_edge_and_reach_pair(self):
        repo = self.baselined(CHAIN)   # a -> b -> c
        registry = dict(repo.baseline()["identities"])
        repo.write({"gen2/p/b.py": None, "gen2/p/renamed.py": py("import gen2.p.c"), "gen2/p/a.py": py("import gen2.p.renamed")})
        write_ledger(repo, self.move_entry("gen2/p/b.py", "gen2/p/renamed.py"))
        self.check(repo, 0)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        after = repo.baseline()["identities"]
        for ref in ("engine|edge|gen2/p/a.py->gen2/p/renamed.py", "engine|reach|gen2/p/a.py->gen2/p/renamed.py", "engine|edge|gen2/p/renamed.py->gen2/p/c.py"):
            self.assertIn(ref, after.values())
        self.assertEqual(set(after), set(registry))

    def test_a_wildcard_or_a_similarity_maps_nothing(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b")})
        write_ledger(repo, self.move_entry("gen2/p/*.py", "gen2/p/renamed.py"))
        done = self.check(repo, 1)
        self.assertIn("missing", done.stderr)
        self.assertIn("unused ledger entry", done.stderr)

    def test_a_move_that_maps_nothing_is_an_unused_entry(self):
        repo = self.baselined(CHAIN)
        write_ledger(repo, self.move_entry("gen2/p/nowhere.py", "gen2/p/elsewhere.py"))
        self.assertIn("ML-1: unused ledger entry", self.check(repo, 1).stderr)

    def test_a_move_whose_old_file_is_still_present_is_stale(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/renamed.py": py("import gen2.p.b")})   # a copy, not a move
        write_ledger(repo, self.move_entry("gen2/p/a.py", "gen2/p/renamed.py"))
        self.assertIn("(expanded from ML-1)", self.check(repo, 1).stderr)

    def test_admit_with_move_states_the_move_as_an_entry_and_previews_its_expansion(self):
        repo = self.baselined(CHAIN)
        repo.write({"gen2/p/a.py": None, "gen2/p/renamed.py": py("import gen2.p.b")})
        done = repo.run("admit", "--move", "gen2/p/a.py", "gen2/p/renamed.py")
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        drafted = sections(repo)
        self.assertEqual([(s["action"], s["from"], s["to"]) for s in drafted if s["action"] == "move"], [("move", "gen2/p/a.py", "gen2/p/renamed.py")])
        self.assertEqual([s for s in drafted if s["action"] in ("retire", "map")], [], "the move claims every identity it expands to: nothing is drafted for them")
        self.assertRegex(done.stdout, r"ML-0001 move gen2/p/a.py -> gen2/p/renamed.py maps \d+ identities")
        before = (repo.root / LEDGER).read_text()
        self.assertEqual(repo.run("admit", "--move", "gen2/p/a.py", "gen2/p/renamed.py").returncode, 0)
        self.assertEqual((repo.root / LEDGER).read_text(), before, "stating the same move twice drafts it once")
        fill(repo)
        self.check(repo, 0)

    def test_the_move_entry_needs_both_paths_a_reason_and_a_task(self):
        repo = self.baselined(CHAIN)
        write_ledger(repo, {"action": "move", "from": "gen2/p/a.py", "reason": "x", "task": "t"})
        self.assertIn("to missing or placeholder", self.check(repo, 1).stderr)
