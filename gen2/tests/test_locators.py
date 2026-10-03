"""Black-box tests of `tools/check_gen2_locators.py` (task 2q-a; Gate D #1
finding 6 and Gate D #2 section 5: INVARIANTS cited helpers a repair had
removed, because nothing checked a locator against the code).

Each test writes a throwaway repository of literal files and one document of
backtick locators, runs the tool and asserts its exit status and what it
names. The oracle is the rule the tool states: a file locator must be a
tracked file (line numbers and fragments may drift), a function locator must
be defined where it says (names may not drift), and what is not a locator is
not checked.

What this cannot show: that a locator points at the RIGHT definition (only
that the name exists where it is cited), or that the prose around it is true.
"""
from __future__ import annotations

import unittest

from gen2.tests import tool_repo_fixtures as fx
from gen2.tests.tool_repo_fixtures import Repo, py

DOC = "docs/gen2/INVARIANTS.md"

CODE = {
    "gen2/router/service.py": py("from gen2.router.registries import Registries", "", "class Router(Registries):", "    def commit_outcome(self):", "        return 1", "",
                                 "    class Inner:", "        def deep(self):", "            return 2", "", "LIMIT = 3", "", "def write_evidence():", "    return 4"),
    "gen2/router/registries.py": py("class Registries:", "    def is_qualified(self):", "        return True", "    SPEC = 1"),
    "gen2/store/schema.sql": "CREATE TABLE IF NOT EXISTS operation_receipts (id TEXT);\nCREATE TRIGGER receipts_immutable BEFORE UPDATE ON operation_receipts BEGIN SELECT 1; END;\n",
    "gen2/schema/common.schema.json": '{"$defs": {"sha256": {"type": "string"}}}\n',
    "gen2/tests/test_router.py": py("class ObservationTest:", "    pass"),
    "gateway/research_gateway/adapters/base.py": py("def next_link(resp):", "    return None"),
    "tools/check_x.py": "x = 1\n",
    "tools/check_y.py": "y = 1\n",
    "docs/gen2/BOUNDARIES.md": "# boundaries\n",
}


class LocatorTestCase(unittest.TestCase):
    def check(self, text: str, expect: int, files: dict[str, str] | None = None):
        repo = Repo((CODE if files is None else files) | {DOC: "# Invariants\n\n" + text + "\n"})
        self.addCleanup(repo.close)
        done = repo.run(DOC, tool=fx.LOCATORS_TOOL)
        self.assertEqual(done.returncode, expect, msg=f"{done.stdout}\n{done.stderr}")
        return done


class FileLocatorTest(LocatorTestCase):
    def test_a_locator_of_a_tracked_file_passes_whatever_its_line_number(self) -> None:
        for span in ("gen2/router/service.py", "gen2/router/service.py:9999", "gen2/router/service.py:12-40", "gen2/schema/common.schema.json#/$defs/sha256",
                     "tools/check_x.py --flag", "docs/gen2/BOUNDARIES.md"):
            with self.subTest(span=span):
                done = self.check(f"See `{span}`.", 0)
                self.assertIn("every file and function locator exists", done.stdout)

    def test_a_locator_of_a_file_that_is_not_tracked_fails_with_its_line(self) -> None:
        done = self.check("A first line.\nSee `gen2/router/gone.py` for it.", 1)
        self.assertIn("LOCATOR DOES NOT EXIST: docs/gen2/INVARIANTS.md:4: `gen2/router/gone.py`: names no tracked file", done.stderr)
        for span in ("gen2/router/gone.py:12", "gen2/router/gone.py:12-40", "gen2/router/gone.py#/x", "gen2/router/gone.py --check"):
            with self.subTest(span=span):   # a line number or a fragment does not hide a missing file
                self.assertIn(f"`{span}`: names no tracked file", self.check(f"`{span}`", 1).stderr)

    def test_a_file_on_disk_that_git_does_not_track_is_no_file(self) -> None:
        repo = Repo(CODE | {DOC: "# I\n\nSee `gen2/new.py`.\n"})
        self.addCleanup(repo.close)
        repo.write({"gen2/new.py": "x = 1\n"}, commit=False)
        self.assertEqual(repo.run(DOC, tool=fx.LOCATORS_TOOL).returncode, 1)
        repo.git("add", "gen2/new.py")
        self.assertEqual(repo.run(DOC, tool=fx.LOCATORS_TOOL).returncode, 0)

    def test_a_bare_name_and_the_tail_of_a_path_match_any_tracked_file_of_that_name(self) -> None:
        self.check("`registries.py` and `router/service.py` and `adapters/base.py`.", 0)
        done = self.check("`router/gone.py` and `other/service.py`.", 1)
        self.assertEqual(done.stderr.count("names no tracked file"), 2)

    def test_a_tail_must_start_at_a_path_component(self) -> None:
        self.check("`ervice.py`.", 1)   # a suffix of the name, not of the path

    def test_a_glob_needs_one_match_and_a_directory_one_tracked_file_under_it(self) -> None:
        self.check("`tools/check_*.py` and `gen2/router/` and `gen2/`.", 0)
        self.assertIn("`tools/nothing_*.py`", self.check("`tools/nothing_*.py`.", 1).stderr)
        self.assertIn("`gen2/missing/`", self.check("`gen2/missing/`.", 1).stderr)

    def test_the_design_record_kept_outside_the_repository_is_cited_by_identity(self) -> None:
        self.check("`gen2-flow-architecture-20260924.md`, `methodology-synthesis-20260924.md`, `reviews/gen2-design-astra-review-20260922.md`, `preflight.sh`.", 0)

    def test_the_exemption_is_only_for_what_the_list_names(self) -> None:
        self.check("`gen2-flow-architecture-2026.md`.", 1)       # not a dated identity
        self.check("`reviews/sub/dir/report.md`.", 1)
        self.check("`other-preflight.sh`.", 1)


class NotALocatorTest(LocatorTestCase):
    def test_what_is_not_a_file_or_function_locator_is_not_checked(self) -> None:
        text = ("`.py`, `/`, `$TOPIC_DIR/STOP`, `commit-fingerprint/1`, `state/control.sqlite3`, `--check`, `make gen2-check`, `os.system`, "
                "`queue_entries.status_decision_id`, `gateway.calls`, `QueueStore.finalize_run`, `some_name`, `a/b`, `jcs-rfc8785/1`.")
        self.check(text, 0)

    def test_a_fenced_block_is_skipped_and_the_line_numbers_still_count(self) -> None:
        done = self.check("```\n`gen2/router/gone.py`\n```\nthen `gen2/router/missing.py`.", 1)
        self.assertNotIn("gone.py", done.stderr)
        self.assertIn("docs/gen2/INVARIANTS.md:6: `gen2/router/missing.py`", done.stderr)   # the document's own line: header, blank, then four lines

    def test_a_locator_written_without_backticks_is_not_seen(self) -> None:
        self.check("See gen2/router/gone.py for it.", 0)


class SymbolLocatorTest(LocatorTestCase):
    def test_a_defined_name_passes_in_the_double_colon_and_the_pair_forms(self) -> None:
        self.check("`gen2/router/service.py::write_evidence`, `gen2/router/service.py::Router.commit_outcome`, `gen2/router/service.py::LIMIT`, "
                   "`gen2/router/service.py` `write_evidence`, `service.py` `Router.Inner.deep`, `gen2/router/service.py::commit_outcome`, "
                   "`gen2/router/registries.py::SPEC`.", 0)   # a method and a class attribute by their plain names

    def test_a_removed_or_misspelled_name_fails_naming_the_file(self) -> None:
        done = self.check("`gen2/router/service.py::need`.", 1)
        self.assertIn("`gen2/router/service.py::need`: need is not defined in gen2/router/service.py", done.stderr)
        done = self.check("(`adapters/base.py` `optional`: formerly)", 1)
        self.assertIn("optional is not defined in gateway/research_gateway/adapters/base.py", done.stderr)

    def test_a_missing_pair_is_reported_once_even_when_its_name_looks_dotted(self) -> None:
        done = self.check("`service.py` `Router.missing`.", 1)
        self.assertEqual(done.stderr.count("LOCATOR DOES NOT EXIST"), 1)

    def test_a_qualified_name_must_match_its_nesting(self) -> None:
        self.check("`gen2/router/service.py::Router.commit_outcome`.", 0)
        self.assertIn("Wrong.commit_outcome", self.check("`gen2/router/service.py::Wrong.commit_outcome`.", 1).stderr)
        self.assertIn("Router.deep", self.check("`gen2/router/service.py::Router.deep`.", 1).stderr)

    def test_a_pair_needs_exactly_one_space_and_a_name(self) -> None:
        self.check("`gen2/router/service.py`, `nothing_here` and `gen2/router/service.py`; a `nothing_here`.", 0)   # a list or prose is not a symbol locator
        self.check("`gen2/router/service.py` and `nothing_here`.", 0)

    def test_a_sql_name_is_a_table_view_trigger_or_index(self) -> None:
        self.check("`gen2/store/schema.sql::operation_receipts`, `gen2/store/schema.sql` `receipts_immutable`.", 0)
        self.assertIn("is not defined in gen2/store/schema.sql", self.check("`gen2/store/schema.sql::dropped_table`.", 1).stderr)

    def test_in_a_json_or_other_file_the_name_must_appear_as_a_word(self) -> None:
        self.check("`gen2/schema/common.schema.json::sha256`.", 0)
        self.check("`gen2/schema/common.schema.json::sha25`.", 1)

    def test_a_name_in_a_markdown_file_is_found_as_a_word(self) -> None:
        self.check("`docs/gen2/BOUNDARIES.md::boundaries`.", 0)

    def test_a_symbol_of_a_missing_file_fails_as_the_file(self) -> None:
        self.assertIn("names no tracked file", self.check("`gen2/router/gone.py::write_evidence`.", 1).stderr)


class DottedLocatorTest(LocatorTestCase):
    def test_a_module_or_class_member_that_exists_passes(self) -> None:
        # service.write_evidence (module stem); Router.commit_outcome (class); Router.is_qualified (inherited from the mixin Registries);
        # Registries.is_qualified(); ObservationTest (a class of a tests module): test_router.ObservationTest
        self.check("`service.write_evidence`, `Router.commit_outcome`, `Router.is_qualified`, `Registries.is_qualified()`, `test_router.ObservationTest`, `base.next_link`, "
                   "`Router.Inner.deep`.", 0)

    def test_a_member_that_does_not_exist_fails(self) -> None:
        done = self.check("`base.optional` and `Router.missing` and `service.need()`.", 1)
        for member in ("base.optional", "Router.missing", "service.need()"):
            self.assertIn(f"`{member}`", done.stderr)

    def test_an_unknown_first_part_is_not_a_locator(self) -> None:
        self.check("`registry.anything`, `Unknown.method`.", 0)

    def test_a_class_member_is_a_def_or_an_assignment_of_the_class_or_a_base(self) -> None:
        self.check("`Registries.SPEC`, `Router.SPEC`.", 0)


class ToolFailureTest(LocatorTestCase):
    def test_a_document_that_cannot_be_read_is_a_tool_failure(self) -> None:
        repo = Repo(CODE)
        self.addCleanup(repo.close)
        done = repo.run("docs/gen2/NOPE.md", tool=fx.LOCATORS_TOOL)
        self.assertEqual(done.returncode, 2)
        self.assertIn("cannot be read", done.stderr)

    def test_the_summary_counts_what_was_checked(self) -> None:
        done = self.check("`gen2/router/service.py` `write_evidence` and `Router.commit_outcome` and `tools/check_x.py`.", 0)
        self.assertIn("locators: 2 file, 1 symbol and 1 dotted checked in 1 documents, 0 that do not exist", done.stdout)


class RealRepositoryTest(unittest.TestCase):
    def test_the_stale_helpers_gate_d_named_are_no_longer_cited_as_current(self) -> None:
        """INVARIANTS H-5 once named `need()` and `optional()` as the payload enforcement and `Response.json`: the decoder removed them."""
        text = (fx.REPO / DOC).read_text(encoding="utf-8")
        h5 = next(block for block in text.split("\n\n") if block.startswith("**H-5"))
        self.assertNotIn("`need()`", h5)
        self.assertNotIn("`base.optional`", h5)
        self.assertNotIn("`Response.json`", h5)
        self.assertNotIn("2q's to reconcile", h5)


if __name__ == "__main__":
    unittest.main()
