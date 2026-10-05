"""Black-box tests of the supported-source contract (docs/gen2/SOURCE-CONTRACT.md, version 1; task 2q-a-repair-3; Gate D #4 checklist 0, 1 and 2).

The architecture metrics are exact over a declared subset of Python, and anything outside it is refused before anything is measured. These tests run the
contract (`tools/gen2_source_contract.py`, the stage on its own, and through every command that reads the production source) on literal fixture packages
and assert what it recognises or refuses. Every expectation is worked out by hand from the fixture's text (gen2/tests/source_contract_fixtures.py). The
oracle is the fixture and the contract table, never the tool's own output.

  * every refusal category has fixtures that must be refused, in BOTH services, with the file, the line, the construct and a remediation;
  * every row of the contract has fixtures that must be accepted, in both services, with the facts the metrics read (definitions, resolved bases, C3 family,
    method roles and generated methods) checked against the text;
  * a refusal is raised by every command that reads the production source, however it is run, and writes no baseline and no ledger;
  * the contract document and the tool state one contract: the same categories, transformation records, external terminals and loader inventory;
  * the real production inventory of both services is inside the contract.

What this cannot show: that the subset is the whole of Python (it is a stated subset; a form outside it is a refusal fixture, not an extension).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.source_contract_fixtures import POSITIVES, REFUSALS, ROW_OF, ROWS, Fixture
from gen2.tests.tool_repo_fixtures import Repo, py

SERVICES = {"engine": ("gen2/", "gen2"), "gateway": ("gateway/research_gateway/", "research_gateway")}
CONTRACT_DOC = fx.REPO / "docs" / "gen2" / "SOURCE-CONTRACT.md"


def package(service: str, files: dict[str, str]) -> dict[str, str]:
    """The fixture's files under the service's package root, `{pkg}` replaced, with the package's own `__init__` present."""
    prefix, name = SERVICES[service]
    out = {prefix + "__init__.py": ""}
    for relative, text in files.items():
        out[prefix + relative] = text.replace("{pkg}", name)
    return out


class ContractCase(unittest.TestCase):
    def repo(self, files: dict[str, str], *, commit: bool = True) -> Repo:
        repo = Repo(files, commit=commit)
        self.addCleanup(repo.close)
        return repo

    def view(self, repo: Repo) -> tuple[int, dict]:
        """The contract's own stage on a repository: (exit status, the recognised facts and diagnostics)."""
        done = repo.run("--json", tool=fx.CONTRACT_TOOL)
        self.assertIn(done.returncode, (0, 1), msg=done.stderr)
        return done.returncode, json.loads(done.stdout)


class RefusalTest(ContractCase):
    """Each refusal fixture is refused, in each service it means something in, naming file, line, construct and remediation. One test per category (generated
    below, `test_refuses_<category>`), so that a mutant of one guard runs the fixtures of that guard."""

    def refuses(self, category: str) -> None:
        fixtures = [f for f in REFUSALS if f.category == category]
        self.assertTrue(fixtures, msg=f"no refusal fixture for {category}")
        for fixture in fixtures:
            for service, (prefix, _) in SERVICES.items():
                if fixture.only not in (None, service):
                    continue
                with self.subTest(fixture=fixture.name, service=service):
                    status, view = self.view(self.repo(package(service, fixture.files)))
                    self.assertEqual(status, 1, msg=f"{fixture.name} was not refused")
                    wanted = (fixture.category, prefix + fixture.where[0], fixture.where[1])
                    found = [d for d in view["diagnostics"] if (d["category"], d["file"], d["line"]) == wanted]
                    self.assertTrue(found, msg=f"wanted {wanted}; the diagnostics were {[(d['category'], d['file'], d['line'], d['construct']) for d in view['diagnostics']]}")
                    self.assertIn(fixture.construct, found[0]["construct"])
                    self.assertTrue(found[0]["remediation"].strip(), msg="a refusal says what to do")

    def test_a_refusal_names_file_line_construct_and_remediation_in_the_text_a_command_prints(self) -> None:
        repo = self.repo(package("engine", {"a.py": py("class A:", "    pass", "", "class A:", "    pass")}))
        done = repo.run(tool=fx.CONTRACT_TOOL)
        self.assertEqual(done.returncode, 1)
        self.assertRegex(done.stderr, r"SOURCE REFUSED: gen2/a\.py:4: SRC-DEF-DUPLICATE: A is defined more than once in the module \(first at line 1\)\. give each definition")

    def test_a_contract_refusal_names_its_category_file_line_and_construct(self) -> None:
        """A refusal the contract itself makes (a class hook), not the index: its category, file, line and the construct it names. What it says to do is the other test's."""
        for service, (prefix, _) in SERVICES.items():
            with self.subTest(service=service):
                status, view = self.view(self.repo(package(service, {"c.py": py("class C:", "    def __init_subclass__(cls):", "        pass")})))
                self.assertEqual((status, [(d["category"], d["file"], d["line"]) for d in view["diagnostics"]]), (1, [("SRC-CLASS-HOOK", prefix + "c.py", 2)]))
                self.assertIn("defines __init_subclass__", view["diagnostics"][0]["construct"])

    BUILT_ELSEWHERE = {"SRC-INV-UNTRACKED": "UntrackedTest, both services", "SRC-LOADER-INVENTORY": "LoaderInventoryTest and test_source_closure.LoaderBoundaryTest, over a copy of the gateway's real loader"}

    def test_every_category_of_the_contract_has_a_refusal_fixture_in_each_service_it_applies_to(self) -> None:
        """Category BY SERVICE, not the union of the categories: every category the fixtures here are the oracle of has a refusal fixture that runs in the engine AND one that runs in the
        gateway (a fixture marked `only` runs in one), so a rule held by one service's code path and not the other's is found. The two categories whose fixtures are built in other tests
        are named, with where."""
        tool = set(categories_in_the_tool())
        self.assertEqual({f.category for f in REFUSALS} | set(self.BUILT_ELSEWHERE), tool)
        covered = {(f.category, service) for f in REFUSALS for service in SERVICES if f.only in (None, service)}
        missing = sorted((category, service) for category in tool - set(self.BUILT_ELSEWHERE) for service in SERVICES if (category, service) not in covered)
        self.assertEqual(missing, [], msg="a category with no refusal fixture in a service")
        for fixture in REFUSALS:
            self.assertIn(fixture.category, tool, msg=fixture.name)

    def test_a_refusal_is_reported_where_the_construct_is_even_when_nothing_uses_it(self) -> None:
        """Gate D #4: the guard refuses by form, with no collaboration pair to disappear. An isolated unsupported declaration in a file nothing imports is refused."""
        for service in SERVICES:
            with self.subTest(service=service):
                status, view = self.view(self.repo(package(service, {"lonely.py": py("import sys", "", "if sys.platform:", "    class Unused:", "        pass")})))
                self.assertEqual((status, [d["category"] for d in view["diagnostics"]]), (1, ["SRC-CLASS-CONDITIONAL"]))


def _refusal_test(category: str):
    def test(self) -> None:
        self.refuses(category)
    test.__name__ = "test_refuses_" + category.lower().replace("-", "_")
    test.__doc__ = f"every refusal fixture of {category}, in both services"
    return test


for _category in sorted({f.category for f in REFUSALS}):
    _method = _refusal_test(_category)
    setattr(RefusalTest, _method.__name__, _method)


class UntrackedTest(ContractCase):
    def test_a_production_candidate_that_git_does_not_track_is_refused_with_the_command_to_run(self) -> None:
        for service, (prefix, _) in SERVICES.items():
            with self.subTest(service=service):
                repo = self.repo(package(service, {"a.py": "x = 1\n"}))
                repo.write({prefix + "new.py": "y = 2\n"}, commit=False)
                status, view = self.view(repo)
                found = [d for d in view["diagnostics"] if d["category"] == "SRC-INV-UNTRACKED"]
                self.assertEqual((status, [d["file"] for d in found]), (1, [prefix + "new.py"]))
                self.assertIn("git add", found[0]["remediation"])
                repo.git("add", prefix + "new.py")
                self.assertEqual(self.view(repo)[0], 0)

    def test_untracked_files_outside_the_production_inventory_and_ignored_ones_are_not_candidates(self) -> None:
        repo = self.repo(package("engine", {"a.py": "x = 1\n"}) | {".gitignore": "gen2/ignored.py\n"})
        repo.write({"tools/scratch.py": "x = 1\n", "gen2/tests/scratch.py": "x = 1\n", "gen2/ignored.py": "x = 1\n"}, commit=False)
        self.assertEqual(self.view(repo)[0], 0)

    def test_a_tracked_file_missing_from_the_working_tree_is_skipped_and_left_to_the_ledger(self) -> None:
        """The deleted file held a function, so there is something to be accounted for: it is no crash, the file is absent from the inventory and the import graph, and the ratchet fails on the
        identity that is now missing (missing is never an improvement) until the ledger retires it. (A data-only file would show none of this: it has no function before it is deleted.)"""
        doc = {"docs/gen2/INVARIANTS.md": "none\n", "docs/gen2/DEBT-REGISTER.md": "none\n"}
        repo = self.repo(package("engine", {"a.py": py("def f():", "    return 1"), "b.py": py("def g():", "    return 2")}) | doc)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        before = self.view(repo)[1]
        self.assertEqual(sorted(f["key"] for f in before["functions"]), ["gen2/a.py::f", "gen2/b.py::g"])
        (repo.root / "gen2/b.py").unlink()
        status, view = self.view(repo)
        self.assertEqual((status, [f["key"] for f in view["functions"]]), (0, ["gen2/a.py::f"]), msg="no crash, and the deleted file's function is not a fact")
        out = repo.root / "out"
        self.assertEqual(repo.run("report", str(out)).returncode, 0)
        summary = json.loads((out / "metrics-summary.json").read_text())
        self.assertNotIn("gen2/b.py", summary["services"]["engine"]["graph"], msg="the deleted file is out of the file inventory")
        done = repo.run("check")
        self.assertEqual(done.returncode, 1, msg=done.stdout + done.stderr)
        self.assertRegex(done.stderr, r"METRICS REGRESSION: identity engine\|file\|gen2/b\.py: missing; map or retire in committed ledger")
        self.assertNotIn("SOURCE REFUSED", done.stderr)


class AcceptanceTest(ContractCase):
    """Each supported form is accepted in both services, and the facts the metrics read are the ones the text states. One test per row of the contract's
    table (generated below, `test_accepts_<row>`)."""

    def accepts(self, row: str) -> None:
        fixtures = [f for f in POSITIVES if ROW_OF[f.name] == row]
        self.assertTrue(fixtures, msg=f"no positive fixture for the row {row}")
        for fixture in fixtures:
            for service, (prefix, _) in SERVICES.items():
                if fixture.only not in (None, service):
                    continue
                with self.subTest(fixture=fixture.name, service=service):
                    status, view = self.view(self.repo(package(service, fixture.files)))
                    self.assertEqual((status, [(d["category"], d["file"], d["line"]) for d in view["diagnostics"]]), (0, []), msg=fixture.name)
                    self.check_facts(view, prefix, fixture)

    def test_every_positive_fixture_belongs_to_a_row_and_every_row_has_one(self) -> None:
        self.assertEqual(sorted({ROW_OF[f.name] for f in POSITIVES}), ROWS)
        self.assertEqual(len(ROW_OF), len(POSITIVES))
        table_rows = {"source inventory", "function identity", "class and method declarations", "imports and exports", "inheritance", "decorators and descriptors",
                      "receiver calls and attributes", "non-graph mechanisms"}
        self.assertEqual(set(ROWS), table_rows)

    def check_facts(self, view: dict, prefix: str, fixture: Fixture) -> None:
        full = lambda key: prefix + key if "::" in key else key
        classes = {c["class"]: c for c in view["classes"]}
        functions = {f["key"]: f for f in view["functions"]}
        expect = fixture.expect
        if "functions" in expect:
            self.assertEqual(sorted(functions), sorted(prefix + k for k in expect["functions"]), msg="the recognised functions")
        for key in expect.get("classes", ()):
            self.assertIn(full(key), classes)
        for key, methods in expect.get("methods", {}).items():
            self.assertEqual(classes[full(key)]["methods"], methods)
        for key, base in expect.get("bases", {}).items():
            refs = [ref for _, ref in classes[full(key)]["bases"] if ref[0] == "class"]
            self.assertEqual([f"{path}::{qual}" for _, path, qual in refs], [full(base)], msg=key)
        for key, family in expect.get("family", {}).items():
            self.assertEqual(classes[full(key)]["family"], [full(member) for member in family])
        for key, names in expect.get("generated", {}).items():
            self.assertEqual(classes[full(key)]["generated"], names)
        for key, identities in expect.get("transforms", {}).items():
            holder = functions.get(full(key)) or classes[full(key)]
            self.assertEqual(holder["transforms"], identities)

    def test_a_function_and_a_class_of_the_same_short_name_in_different_scopes_have_distinct_identities(self) -> None:
        text = py("class A:", "    def run(self):", "        return 1", "", "class B:", "    def run(self):", "        return 2", "", "def run():", "    def run():", "        return 3", "    return run")
        status, view = self.view(self.repo(package("engine", {"a.py": text})))
        self.assertEqual(sorted(f["key"] for f in view["functions"]), ["gen2/a.py::A.run", "gen2/a.py::B.run", "gen2/a.py::run", "gen2/a.py::run.run"])

    def test_the_receiver_is_the_first_parameter_of_a_method_that_is_not_static(self) -> None:
        text = py("class A:", "    def f(this):", "        return 1", "", "    @staticmethod", "    def s(x):", "        return x", "", "    @classmethod", "    def c(klass):", "        return klass")
        _status, view = self.view(self.repo(package("engine", {"a.py": text})))
        self.assertEqual({f["key"].split("::")[1]: (f["role"], f["receiver"]) for f in view["functions"]}, {"A.f": ("method", "this"), "A.s": ("static", None), "A.c": ("class", "klass")})


def _acceptance_test(row: str):
    def test(self) -> None:
        self.accepts(row)
    test.__name__ = "test_accepts_" + row.replace(" ", "_").replace("-", "_")
    test.__doc__ = f"every supported form of the row {row!r}, in both services"
    return test


for _row in ROWS:
    _method = _acceptance_test(_row)
    setattr(AcceptanceTest, _method.__name__, _method)


class EveryCommandTest(ContractCase):
    """The refusal stage runs first in each command that reads the production source, however it is run, and nothing is written over refused source."""

    GOOD = package("engine", {"a.py": py("def f():", "    return 1")})
    BAD = package("engine", {"a.py": py("def f():", "    return 1", "", "if True:", "    class Late:", "        pass")})
    DOC = {"docs/gen2/INVARIANTS.md": "`gen2/a.py::f`\n", "docs/gen2/DEBT-REGISTER.md": "none\n"}

    def refused_repo(self) -> Repo:
        repo = self.repo(self.GOOD | self.DOC)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        repo.write(self.BAD)
        return repo

    def assertRefused(self, done, partial: bool = False) -> None:
        """The refusal, named with its file, line and construct, and with what the command did. A command that measures nothing from refused source (check, admit, rebaseline) says
        "nothing was measured, recorded or certified"; `report` and `hotspots` DO write the tables they can read, and must not say that: they say the tables are partial, the input incomplete
        and non-passing, and that nothing in them is certified (task 2q-a-repair-4; Astra's 2q-a-repair-3 review)."""
        self.assertEqual(done.returncode, 1, msg=f"{done.stdout}\n{done.stderr}")
        self.assertIn("SOURCE REFUSED: gen2/a.py:5: SRC-CLASS-CONDITIONAL: class Late is declared inside a compound statement", done.stderr)
        if partial:
            self.assertIn("the tables written are PARTIAL, the input is incomplete and non-passing, and nothing in them is certified", done.stderr)
            self.assertNotIn("nothing was measured", done.stderr)
        else:
            self.assertIn("nothing was measured, recorded or certified", done.stderr)
            self.assertNotIn("PARTIAL", done.stderr)

    def test_check_refuses(self) -> None:
        self.assertRefused(self.refused_repo().run("check"))

    def test_rebaseline_refuses_and_leaves_the_baseline_and_the_ledger_as_they_were(self) -> None:
        repo = self.refused_repo()
        baseline = (repo.root / fx.BASELINE).read_bytes()
        done = repo.run("rebaseline")
        self.assertRefused(done)
        self.assertEqual((repo.root / fx.BASELINE).read_bytes(), baseline)
        self.assertFalse((repo.root / "docs/gen2/metrics-ledger.md").exists())

    def test_the_first_baseline_is_never_recorded_over_refused_source(self) -> None:
        repo = self.repo(self.BAD | self.DOC)
        self.assertRefused(repo.run("rebaseline"))
        self.assertFalse((repo.root / fx.BASELINE).exists())

    def test_admit_refuses_and_writes_no_ledger(self) -> None:
        repo = self.refused_repo()
        self.assertRefused(repo.run("admit"))
        self.assertFalse((repo.root / "docs/gen2/metrics-ledger.md").exists())

    def test_report_shows_the_input_as_incomplete_and_non_passing_and_still_writes_what_it_could_read(self) -> None:
        """A refused `report` writes PARTIAL tables, and says exactly that: not "nothing was measured". Its artifacts carry the mark themselves: input.complete, input.passing and
        input.certified are false in the summary and NOT-CERTIFIED.txt beside the tables names the refusals."""
        repo = self.repo(self.BAD)
        out = repo.root / "out"
        done = repo.run("report", str(out))
        self.assertRefused(done, partial=True)
        summary = json.loads((out / "metrics-summary.json").read_text())
        self.assertEqual((summary["input"]["contract"], summary["input"]["complete"], summary["input"]["passing"], summary["input"]["certified"]), ("source-contract/1", False, False, False))
        self.assertTrue(any("SRC-CLASS-CONDITIONAL" in r for r in summary["input"]["refusals"]))
        self.assertEqual(summary["services"]["engine"]["self_calls"], {"sites": 0, "pairs": {}, "families": {}, "measured": False})
        self.assertIn("not measured (source refused)", done.stdout)
        self.assertIn("PARTIAL report written", done.stderr)
        self.assertTrue((out / "file-dependencies.csv").exists() and (out / "function-complexity.csv").exists(), msg="what could be read is written")
        self.assertTrue((out / "NOT-CERTIFIED.txt").exists(), msg="the tables carry the mark: a marker is written beside them")
        marker = (out / "NOT-CERTIFIED.txt").read_text()
        for needle in ("NOT CERTIFIED", "PARTIAL", "incomplete and non-passing", "gen2/a.py:5: SRC-CLASS-CONDITIONAL"):
            self.assertIn(needle, marker)

    def test_a_report_that_passes_has_no_marker(self) -> None:
        repo = self.repo(self.GOOD)
        out = repo.root / "out"
        self.assertEqual(repo.run("report", str(out)).returncode, 0)
        self.assertFalse((out / "NOT-CERTIFIED.txt").exists())

    def test_a_report_measures_the_collaboration_of_the_service_whose_source_is_inside_the_contract(self) -> None:
        """Gate D's historical pins: the gateway of two of them holds a form the contract refuses while the engine's Router is inside it. The refused service's
        collaboration is not measured; the other's still is, so a historical comparison of the engine's inventory (132 sites, 19 pairs at the real pin) stays possible."""
        files = package("engine", {"base.py": py("class Base:", "    def f(self):", "        return 1"), "use.py": py("from gen2.base import Base", "", "class Child(Base):", "    def g(self):", "        return self.f()")})
        files |= package("gateway", {"a.py": py("if True:", "    class Late:", "        pass")})
        repo = self.repo(files)
        out = repo.root / "out"
        done = repo.run("report", str(out))
        self.assertEqual(done.returncode, 1)
        summary = json.loads((out / "metrics-summary.json").read_text())
        self.assertEqual(summary["services"]["engine"]["self_calls"]["pairs"], {"gen2/use.py->gen2/base.py": 1})
        self.assertEqual(summary["services"]["gateway"]["self_calls"], {"sites": 0, "pairs": {}, "families": {}, "measured": False})
        self.assertEqual((summary["input"]["complete"], summary["input"]["passing"]), (False, False))

    def test_a_passing_report_says_so(self) -> None:
        repo = self.repo(self.GOOD)
        out = repo.root / "out"
        self.assertEqual(repo.run("report", str(out)).returncode, 0)
        self.assertEqual(json.loads((out / "metrics-summary.json").read_text())["input"], {"contract": "source-contract/1", "complete": True, "passing": True, "certified": True, "refusals": []})

    def test_hotspots_refuses_too_and_its_tables_are_marked_partial_and_not_certified(self) -> None:
        repo = self.repo(self.BAD)
        out = repo.root / "out"
        self.assertRefused(repo.run("hotspots", str(out)), partial=True)
        self.assertTrue((out / "NOT-CERTIFIED.txt").exists(), msg="the tables carry the mark: a marker is written beside them")
        self.assertIn("NOT CERTIFIED", (out / "NOT-CERTIFIED.txt").read_text())
        self.assertTrue((out / "hotspots-summary.json").exists(), msg="the tables it could write are written")

    def test_the_locator_command_refuses_before_checking_a_locator(self) -> None:
        repo = self.refused_repo()
        done = repo.run(tool=fx.LOCATORS_TOOL)
        self.assertEqual(done.returncode, 1, msg=done.stderr)
        self.assertIn("SOURCE REFUSED: gen2/a.py:5: SRC-CLASS-CONDITIONAL", done.stderr)
        self.assertIn("no locator was checked", done.stderr)
        self.assertNotIn("every file and function locator exists", done.stdout)

    def test_a_clean_source_passes_every_command(self) -> None:
        repo = self.repo(self.GOOD | self.DOC)
        self.assertEqual(repo.run("rebaseline").returncode, 0)
        self.assertEqual(repo.run("check").returncode, 0)
        self.assertEqual(repo.run(tool=fx.LOCATORS_TOOL).returncode, 0)
        self.assertEqual(repo.run(tool=fx.CONTRACT_TOOL).returncode, 0)

    def test_no_numeric_exemption_and_no_ledger_entry_waives_a_refusal(self) -> None:
        repo = self.refused_repo()
        repo.write({fx.EXEMPTIONS: py("### EX-1", "- metric: unresolved_base", "- location: engine:gen2/a.py::Late", "- reason: a long enough reason to look reviewed", "- accepted by: Gate D #4 2026-10-05",
                                      "- removal: when the source is changed to be inside the contract")})
        done = repo.run("check")
        self.assertEqual(done.returncode, 1)
        self.assertIn("SOURCE REFUSED", done.stderr)
        repo.write({"docs/gen2/metrics-ledger.md": py("### ML-0001", "- action: classify", "- metric: unresolved_base", "- location: engine:gen2/a.py::Late", "- reason: a classification", "- task: 2q-a-repair-3")})
        done = repo.run("check")
        self.assertEqual(done.returncode, 1)
        self.assertIn("SOURCE REFUSED", done.stderr)


class RealInventoryTest(ContractCase):
    def test_the_production_inventory_of_both_services_is_inside_the_contract(self) -> None:
        result = fx.run_judged([sys.executable, str(fx.CONTRACT_TOOL), "--root", str(fx.REPO), "--json"], 120)   # judged as a program, with its completion record
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        view = json.loads(result.stdout)
        self.assertEqual(view["diagnostics"], [])
        keys = {f["key"] for f in view["functions"]}
        self.assertTrue(any(k.startswith("gen2/") for k in keys) and any(k.startswith("gateway/research_gateway/") for k in keys), "both services are in the facts")
        self.assertIn("gateway/research_gateway/core/payload.py::_Unread.__bool__", keys, "the explicit methods that replace _no_reading are recognised definitions")
        self.assertFalse([k for k in keys if "_no_reading" in k], "the dynamic decorator is gone")


# --- the document and the tool state one contract ---------------------------------------------------------------------------

def categories_in_the_tool() -> list[str]:
    repo = Repo({})
    try:
        return list(json.loads(repo.run("--contract", tool=fx.CONTRACT_TOOL, root=False).stdout)["categories"])
    finally:
        repo.close()


def table(heading: str) -> list[list[str]]:
    """The cells of the Markdown table that follows a `## heading` of the contract document, header and rule rows dropped."""
    text = CONTRACT_DOC.read_text(encoding="utf-8")
    section = text.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")] for line in section.splitlines() if line.startswith("|")]
    return rows[2:]


def code(cell: str) -> str:
    return cell.strip("`")


class DocumentAndToolTest(unittest.TestCase):
    """The document's tables and the tool's constants are one contract. The tool is asked for its constants in a child (`--contract`), as every consumer meets it."""

    def setUp(self) -> None:
        repo = Repo({})
        self.addCleanup(repo.close)
        done = repo.run("--contract", tool=fx.CONTRACT_TOOL, root=False)
        self.assertEqual(done.returncode, 0, msg=done.stderr)
        self.tool = json.loads(done.stdout)

    def test_the_version_is_stated_once_and_agrees(self) -> None:
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        self.assertEqual((self.tool["version"], self.tool["id"]), (1, "source-contract/1"))
        self.assertIn("**Version 1** (`source-contract/1`)", text)
        self.assertIn("2026-10-05", text)

    def test_the_refusal_categories_and_their_rows_are_the_tools(self) -> None:
        rows = table("Refusal categories")
        self.assertEqual({code(r[0]): [r[1], r[2]] for r in rows}, self.tool["categories"])
        self.assertEqual(len(rows), len(self.tool["categories"]))

    def test_every_category_is_named_in_the_contract_table(self) -> None:
        text = CONTRACT_DOC.read_text(encoding="utf-8").split("## Refusal categories", 1)[0]
        self.assertEqual(sorted(c for c in self.tool["categories"] if f"`{c}`" not in text), [])

    def test_the_transformation_records_are_the_tools(self) -> None:
        rows = table("Transformation records")
        ours = {t["identity"]: (", ".join(t["applies_to"]), t["shape"].replace("`", ""), t["effect"].replace("`", "")) for t in self.tool["transforms"]}
        self.assertEqual({code(r[0]): (r[1], r[2].replace("`", ""), r[3].replace("`", "")) for r in rows}, ours)

    def test_the_external_terminal_lists_are_the_tools(self) -> None:
        listed = {r[0]: [code(i.strip()) for i in r[1].split(",")] for r in table("External terminals")}
        self.assertEqual(listed, {"modelled typing forms": self.tool["modelled_typing"], "mixable with a project base": self.tool["mixable_external"]})

    def test_the_loader_inventory_is_the_tools(self) -> None:
        rows = {r[0]: r[1] for r in table("Dynamic loader inventory")}
        (loader,) = self.tool["loaders"]
        self.assertEqual(code(rows["Site"].split(",")[0]), loader["file"])
        self.assertEqual(code(rows["Site"].split("function")[1].strip()), loader["function"])
        self.assertEqual((code(rows["Call"]), code(rows["Package"]), code(rows["Filter"]), code(rows["Skip prefix"])), (loader["call"], loader["package"], loader["condition"], loader["skip_prefix"]))
        self.assertEqual([code(n.strip()) for n in rows["Skip names"].split("(")[0].split(",")], loader["skip_names"])
        self.assertEqual([code(n.strip()) for n in rows["Discovered files"].split(",")], loader["discovered"])
        self.assertEqual(code(rows["Argument"]), loader["argument"])
        self.assertEqual(code(rows["Fingerprint"]), loader["fingerprint"])

    def test_the_loader_calls_and_hooks_listed_in_the_text_are_the_tools(self) -> None:
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        for call in self.tool["loader_calls"]:
            self.assertIn(f"`{call.removeprefix('builtins.')}`", text, msg=call)
        for hook in self.tool["hooks"]:
            self.assertIn(f"`{hook}`", text)

    def test_the_rulings_and_the_amendment_of_repair_2_are_cited(self) -> None:
        text = CONTRACT_DOC.read_text(encoding="utf-8")
        for needle in ("Option B is adopted", "`_no_reading`", "Sequencing", "Withdrawn (ruling 1)", "Gate D #4", "classify"):
            self.assertIn(needle, text.replace("**", ""), msg=needle)

    def test_the_inventoried_adapters_are_the_adapters_the_loader_finds_in_the_real_package(self) -> None:
        """The inventory is a reviewed boundary: it has to be the files the real package holds (not `base`, not an underscore name)."""
        package_dir = fx.REPO / "gateway" / "research_gateway" / "adapters"
        found = sorted(p.stem for p in package_dir.glob("*.py") if p.stem != "__init__" and p.stem != "base" and not p.stem.startswith("_"))
        self.assertEqual(found, sorted(self.tool["loaders"][0]["discovered"]))


class LoaderInventoryTest(ContractCase):
    """The one inventoried dynamic loader, against a copy of the real adapter package: unchanged it passes, and each change to it is a refusal."""

    LOADER = fx.REPO / "gateway" / "research_gateway" / "adapters" / "__init__.py"
    NAMES = ("bea", "bis", "bls", "census", "core", "crossref", "datacite", "doaj", "doi_org", "ecb", "europepmc", "fred", "globe", "govinfo", "harvard_dataverse", "huggingface",
             "kaggle", "openaire", "openalex_snapshot", "opencitations", "openml", "qdr", "semanticscholar", "socrata", "unpaywall", "wms")

    def files(self, loader: str | None = None, names: tuple[str, ...] | None = None, extra: dict | None = None) -> dict[str, str]:
        text = self.LOADER.read_text(encoding="utf-8") if loader is None else loader
        base = {"gateway/research_gateway/__init__.py": "", "gateway/research_gateway/adapters/__init__.py": text, "gateway/research_gateway/adapters/base.py": "x = 1\n",
                "gateway/research_gateway/adapters/_private.py": "x = 1\n"}
        return base | {f"gateway/research_gateway/adapters/{n}.py": "x = 1\n" for n in (self.NAMES if names is None else names)} | (extra or {})

    def categories(self, files: dict[str, str]) -> list[tuple[str, str]]:
        _status, view = self.view(self.repo(files))
        return [(d["category"], d["construct"]) for d in view["diagnostics"]]

    def test_the_real_loader_over_exactly_the_inventoried_adapters_is_accepted(self) -> None:
        self.assertEqual(self.categories(self.files()), [])

    def test_the_skipped_names_and_underscore_files_are_not_discovered(self) -> None:
        self.assertEqual(self.categories(self.files(extra={"gateway/research_gateway/adapters/_other.py": "x = 1\n"})), [])

    def test_a_new_adapter_the_inventory_does_not_list_is_refused_until_the_contract_is_amended(self) -> None:
        found = self.categories(self.files(extra={"gateway/research_gateway/adapters/newsource.py": "x = 1\n"}))
        self.assertEqual([c for c, _ in found], ["SRC-LOADER-INVENTORY"])
        self.assertIn("newsource", found[0][1])

    def test_an_adapter_missing_from_the_package_is_refused_too(self) -> None:
        found = self.categories(self.files(names=self.NAMES[1:]))
        self.assertEqual([c for c, _ in found], ["SRC-LOADER-INVENTORY"])
        self.assertIn("bea", found[0][1])

    def test_a_subpackage_the_loader_would_discover_counts(self) -> None:
        found = self.categories(self.files(extra={"gateway/research_gateway/adapters/sub/__init__.py": ""}))
        self.assertEqual([c for c, _ in found], ["SRC-LOADER-INVENTORY"])

    def test_a_changed_filter_or_skip_set_or_argument_or_discovery_is_refused(self) -> None:
        real = self.LOADER.read_text(encoding="utf-8")
        changes = {"the skip set": (real.replace('_SKIP = {"base"}', '_SKIP = {"base", "core"}'), "_SKIP is not"), "the filter": (real.replace('info.name.startswith("_")', 'info.name.startswith("x")'), "the filter is not"),
                   "the argument": (real.replace('f"{__name__}.{info.name}"', 'f"{__name__}.{info.name}x"'), "the argument is not"),
                   "the discovery": (real.replace("pkgutil.iter_modules(__path__)", "pkgutil.iter_modules(['/x'])"), "does not read the package's own __path__")}
        for what, (loader, says) in changes.items():
            with self.subTest(change=what):
                self.assertNotEqual(loader, real, msg="the fixture's edit must change the real loader")
                found = self.categories(self.files(loader=loader))
                self.assertIn("SRC-LOADER-INVENTORY", [c for c, _ in found])
                # the fingerprint refuses any change to the loader; the checks of the argument, the discovery, the skip set and the filter say WHICH part changed, and each is held by its own text
                self.assertTrue(any(says in construct for _, construct in found), msg=f"no refusal says {says!r}: {found}")

    def test_a_second_loader_call_in_the_same_function_is_refused(self) -> None:
        real = self.LOADER.read_text(encoding="utf-8")
        loader = real.replace("    return out", "    importlib.import_module('os')\n    return out")
        found = self.categories(self.files(loader=loader))
        self.assertIn("SRC-LOADER-INVENTORY", [c for c, _ in found])

    def test_the_same_call_in_another_function_of_the_inventoried_file_is_not_the_site(self) -> None:
        real = self.LOADER.read_text(encoding="utf-8")
        loader = real + "\n\ndef elsewhere(name):\n    return importlib.import_module(name)\n"
        self.assertEqual([c for c, _ in self.categories(self.files(loader=loader))], ["SRC-LOADER-UNINVENTORIED"])

    def test_the_same_code_in_another_file_is_not_the_inventoried_site(self) -> None:
        real = self.LOADER.read_text(encoding="utf-8")
        files = self.files() | {"gateway/research_gateway/elsewhere.py": real}
        self.assertEqual([c for c, _ in self.categories(files)], ["SRC-LOADER-UNINVENTORIED", "SRC-LOADER-UNINVENTORIED"])


if __name__ == "__main__":
    unittest.main()
