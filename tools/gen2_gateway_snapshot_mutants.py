"""Task 2b-repair-14 (Astra F5 / R13C-4): the gateway mutants of the OpenAlex snapshot loader's failure scope (harvest/openalex_snapshot.py).

The unit of a snapshot is its line: one that cannot be read is refused, counted and named, and the lines beside it are loaded; a file that cannot be read, decompressed or framed fails the load.
Each mutant removes ONE part of that in a temporary copy (tests/test_snapshot_lines.py, tests/test_harvest.py, tests/test_openers.py):

  SN-line-*    a bad line aborts the load (13c's policy change), or is skipped without a word, per kind of refusal; a line is decoded as part of a text file, so an invalid byte spoils its neighbours;
  SN-file-*    a file that cannot be read is skipped instead of failing the load;
  SN-report-*  the report does not count, or does not bound what it keeps.

A killer must FAIL in its assertions, not error (tools/gen2_gateway_mutations.py). A control takes the accepted path through the same code.
"""
from __future__ import annotations

SNAPSHOT = "research_gateway/harvest/openalex_snapshot.py"
SL = "tests.test_snapshot_lines."
ONE, VIA, FILE = SL + "OneBadLine.", SL + "ThroughTheIndexLoad.", SL + "AFileThatCannotBeRead."
CLEAN = (ONE + "test_control_a_snapshot_of_valid_lines_loads_every_one_and_refuses_none", VIA + "test_control_a_clean_snapshot_loads_all_three")
FAMILY = "tests.test_openers.ByteCorruption.test_the_snapshot_reader_refuses_each_corrupted_line_alone_and_names_it"
SHAPES = "tests.test_harvest.Shapes.test_openalex_records_and_snapshot_reader"


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("SN-line-a-line-that-is-not-json-aborts-the-load", "a line the strict opener refuses raises, and the readable lines after it are never read (13c's whole-file abort)", SNAPSHOT,
               "                        report.refuse(path, number, str(e))\n                        continue\n", "                        raise PayloadError(f\"{path.name} line {number}: {e}\") from None\n",
               (ONE + "test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded", ONE + "test_the_bad_line_may_stand_anywhere_first_last_or_alone", VIA + "test_valid_bad_valid_loads_the_two_valid_lines_and_commits_without_a_rollback",
                FAMILY, SHAPES), CLEAN),
        Mutant("SN-line-a-line-that-is-not-json-is-skipped-without-a-word", "a line the strict opener refuses is skipped and not reported", SNAPSHOT,
               "                        report.refuse(path, number, str(e))\n                        continue\n", "                        continue\n",
               (ONE + "test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded", ONE + "test_every_bad_line_across_files_is_counted_and_named_with_its_file_and_line", FAMILY, SHAPES), CLEAN),
        Mutant("SN-line-json-that-is-not-an-object-is-skipped-without-a-word", "JSON that is an array, text, a number or null is skipped and not reported", SNAPSHOT,
               "                        report.refuse(path, number, f\"JSON that is not a source object ({type(obj).__name__})\")\n", "",
               (ONE + "test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded", FAMILY), CLEAN),
        Mutant("SN-line-an-object-no-record-can-be-made-of-is-skipped-without-a-word", "a wrong-shaped source object (a title that is false) is skipped and not reported", SNAPSHOT,
               "                        report.refuse(path, number, f\"a source object no record can be made of ({type(e).__name__}: {str(e)[:100]})\")\n", "",
               (ONE + "test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded", VIA + "test_valid_bad_valid_loads_the_two_valid_lines_and_commits_without_a_rollback"), CLEAN),
        Mutant("SN-line-an-object-with-no-id-is-skipped-without-a-word", "a source object with no id is skipped and not reported", SNAPSHOT,
               "                        report.refuse(path, number, \"a source object with no id\")\n", "",
               (ONE + "test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded", SHAPES), CLEAN),
        Mutant("SN-line-the-file-is-decoded-as-text", "the part file is opened as UTF-8 text, so an invalid byte raises while the file is iterated and takes the lines after it", SNAPSHOT,
               'with opener(path, "rb") as f:', 'with opener(path, "rt", encoding="utf-8") as f:',
               (ONE + "test_an_invalid_utf8_byte_spoils_its_line_only",), CLEAN),
        Mutant("SN-file-a-file-that-cannot-be-read-is-skipped", "a gzip cut short, corrupt or not gzip ends that file silently and the load goes on (a load of the rest, reported as whole)", SNAPSHOT,
               "            raise PayloadError(f\"{path.name}: the file cannot be read, decompressed or framed ({type(e).__name__}: {e})\") from None\n", "            continue\n",
               (FILE + "test_a_gzip_cut_short_fails_the_load_whatever_was_read_before_the_cut", FILE + "test_a_corrupt_gzip_member_fails_the_load", FILE + "test_a_gz_that_is_not_gzip_fails_the_load",
                FILE + "test_a_path_that_cannot_be_opened_fails_the_load", FILE + "test_a_good_file_beside_a_damaged_one_does_not_make_the_damaged_one_a_bad_line"),
               (*CLEAN, ONE + "test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded")),
        Mutant("SN-report-does-not-count", "the report names the first lines but its count stays at zero", SNAPSHOT,
               "        self.count += 1\n", "",
               (ONE + "test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded", ONE + "test_the_report_counts_every_refusal_and_lists_the_first_ones_only", SHAPES), CLEAN),
        Mutant("SN-report-is-not-bounded", "the report keeps every refused line (a snapshot of garbage fills memory with its own account)", SNAPSHOT,
               "        if len(self.lines) < self.keep:\n            self.lines.append(", "        if True:\n            self.lines.append(",
               (ONE + "test_the_report_counts_every_refusal_and_lists_the_first_ones_only",), CLEAN),
    ]
