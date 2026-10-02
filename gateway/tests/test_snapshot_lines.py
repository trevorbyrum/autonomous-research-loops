"""Task 2b-repair-14 (Astra F5 / R13C-4): the OpenAlex snapshot loader's unit is the line; a file that cannot be read fails the load.

Repair-8's accepted scope for this offline loader was per-line parsing and construction isolation: a line it could not read did not cost the readable lines beside it. Repair-13c made a line that
is not JSON abort the whole load — strict refusal of the line (right) escalated to refusal of the file (a policy change that nothing authorized; Astra, R13C-4, and the two tests that endorsed
it). Restored here, with what the earlier loader lacked: a refused line is COUNTED and NAMED (the `LineReport`), never skipped without a word.

  * valid / bad / valid for malformed JSON, a duplicate name and a wrong-shaped record — and every other refusal of the strict opener (NaN, a number past a double, an invalid byte, text after the
    object, a truncated line, nesting past the limit), JSON that is not an object, an object with no id and one no record can be made of: the neighbours are loaded, the line is in the report
  * through the real `index.load` (a database that records what it is asked): the readable lines are written and committed, nothing rolled back, and the loader's count is theirs
  * a FILE that cannot be read, decompressed or framed — a gzip cut short, a corrupt member, a `.gz` that is not gzip, a path that cannot be opened — fails the load, naming the file, and rolls the
    open batch back
  * the report: counts every refusal, lists the first `keep`, names file and line

What this does not claim: that a snapshot that loaded with refusals is complete (the report says how many lines were not), or that an uncompressed file cut mid-line differs from a bad line
(nothing in JSON Lines marks the end of a file).
"""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from research_gateway.core.payload import PayloadError
from research_gateway.harvest import index, openalex_snapshot as snap
from tests.test_openers import Fake


ISSN = {1: "9999-9991", 2: "9999-9983", 3: "9999-9975"}


def source(n: int, **fields) -> str:
    return json.dumps({"id": f"https://openalex.org/S{n}", "display_name": f"Journal {n}", "issn_l": ISSN[n], "issn": [ISSN[n]], "type": "journal", **fields})


def identity(n: int) -> str:
    return f"issn:{ISSN[n]}"


GOOD = [source(1), source(2), source(3)]


class Snapshot(tempfile.TemporaryDirectory):
    """A temporary snapshot directory holding these files (name -> bytes, gzipped when the name ends in .gz and the bytes are given as text lines)."""

    def __enter__(self):
        return self   # not the directory's name: `.root` is its Path

    def __init__(self, files: dict):
        super().__init__()
        self.root = Path(self.name)
        for name, content in files.items():
            path = self.root / "updated_date=2026-09-01" / name
            path.parent.mkdir(exist_ok=True)
            if isinstance(content, list):
                data = "".join(line + "\n" for line in content).encode("utf-8")
            else:
                data = content
            path.write_bytes(gzip.compress(data) if name.endswith(".gz") and isinstance(content, list) else data)


def read(files: dict, **kw) -> tuple:
    """(identities read, the report) of the real reader; an exception ends it, so (identities so far, report, exception)."""
    report = snap.LineReport(**kw)
    got = []
    with Snapshot(files) as d:
        try:
            for rec in snap.read_snapshot(d.root, report=report):
                got.append(rec["identity"])
        except Exception as e:
            return got, report, e
    return got, report, None


class OneBadLine(unittest.TestCase):
    CORRUPT = {
        "a line that is not JSON": "not json",
        "an object cut short": '{"id": "https://openalex.org/S9", "display_name": "J',
        "a name twice (ambiguous)": '{"id": "https://openalex.org/S9", "id": "https://openalex.org/S8"}',
        "a name twice in a nested object": '{"id": "https://openalex.org/S9", "topics": [{"display_name": "a", "display_name": "b"}]}',
        "NaN": '{"id": "https://openalex.org/S9", "works_count": NaN}',
        "Infinity": '{"id": "https://openalex.org/S9", "works_count": [Infinity]}',
        "a number past a double": '{"id": "https://openalex.org/S9", "works_count": 1e999}',
        "text after the object": '{"id": "https://openalex.org/S9"} x',
        "a trailing comma": '{"id": "https://openalex.org/S9",}',
        "nesting past the limit": '{"id": "https://openalex.org/S9", "x": ' + "[" * 70 + "]" * 70 + "}",
        "JSON that is an array": "[]",
        "JSON that is text": '"x"',
        "JSON that is a number": "5",
        "JSON that is null": "null",
        "an object with no id": '{"display_name": "no id"}',
        "an object whose id is empty": '{"id": ""}',
        "a wrong-shaped record (a title that is false)": '{"id": "https://openalex.org/S9", "display_name": false}',
        "a wrong-shaped record (a title that is a list)": '{"id": "https://openalex.org/S9", "display_name": ["x"]}',
        "a wrong-shaped record (topics that is a number)": '{"id": "https://openalex.org/S9", "topics": 5}',
    }

    def test_each_bad_line_is_refused_and_named_and_both_neighbours_are_loaded(self):
        for gz in (True, False):
            name = "part_000.gz" if gz else "part_000.jsonl"
            for label, line in self.CORRUPT.items():
                with self.subTest(label, gz=gz):
                    got, report, error = read({name: [GOOD[0], line, GOOD[1]]})
                    self.assertEqual((got, error), ([identity(1), identity(2)], None))
                    self.assertEqual(report.count, 1)
                    self.assertTrue(report.lines[0].startswith(f"{name} line 2: "), report.lines)

    def test_the_bad_line_may_stand_anywhere_first_last_or_alone(self):
        line = "not json"
        for label, lines, want, at in (("first", [line, GOOD[0], GOOD[1]], [identity(1), identity(2)], 1), ("last", [GOOD[0], GOOD[1], line], [identity(1), identity(2)], 3),
                                       ("alone", [line], [], 1), ("two in a row", [GOOD[0], line, line, GOOD[1]], [identity(1), identity(2)], 2)):
            with self.subTest(label):
                got, report, error = read({"part_000.gz": lines})
                self.assertEqual((got, error), (want, None))
                self.assertTrue(report.lines[0].startswith(f"part_000.gz line {at}: "), report.lines)

    def test_an_invalid_utf8_byte_spoils_its_line_only(self):
        """The reader decodes each line itself, strictly (core/wire.py): a file-level decode would raise mid-iteration and take the neighbours with it."""
        data = (GOOD[0] + "\n").encode() + b'{"id": "https://openalex.org/S9", "display_name": "caf\xff"}\n' + (GOOD[1] + "\n").encode()
        for name, content in (("part_000.jsonl", data), ("part_000.gz", gzip.compress(data))):
            with self.subTest(name):
                got, report, error = read({name: content})
                self.assertEqual((got, error, report.count), ([identity(1), identity(2)], None, 1))
                self.assertIn("UTF-8", report.lines[0])

    def test_blank_lines_are_not_lines_of_the_snapshot(self):
        got, report, error = read({"part_000.gz": [GOOD[0], "", "   ", GOOD[1]]})
        self.assertEqual((got, error, report.count), ([identity(1), identity(2)], None, 0))

    def test_control_a_snapshot_of_valid_lines_loads_every_one_and_refuses_none(self):
        for name in ("part_000.gz", "part_000.jsonl"):
            got, report, error = read({name: GOOD})
            self.assertEqual((got, error, report.count, report.lines), ([identity(1), identity(2), identity(3)], None, 0, []))

    def test_every_bad_line_across_files_is_counted_and_named_with_its_file_and_line(self):
        got, report, error = read({"part_000.gz": [GOOD[0], "bad one", GOOD[1]], "part_001.gz": ["[]", GOOD[2], "", '{"id": ""}'], "part_002.jsonl": ['{"a": 1, "a": 2}']})
        self.assertEqual((got, error, report.count), ([identity(1), identity(2), identity(3)], None, 4))
        self.assertEqual([line.split(":")[0] for line in report.lines], ["part_000.gz line 2", "part_001.gz line 1", "part_001.gz line 4", "part_002.jsonl line 1"])

    def test_the_limit_counts_records_read_not_lines(self):
        report = snap.LineReport()
        with Snapshot({"part_000.gz": ["bad", GOOD[0], "bad", GOOD[1], GOOD[2]]}) as d:
            self.assertEqual([r["identity"] for r in snap.read_snapshot(d.root, report=report, limit=2)], [identity(1), identity(2)])
        self.assertEqual(report.count, 2)

    def test_the_report_counts_every_refusal_and_lists_the_first_ones_only(self):
        got, report, error = read({"part_000.gz": ["bad"] * 5 + GOOD}, keep=2)
        self.assertEqual((got, error, report.count, len(report.lines)), ([identity(1), identity(2), identity(3)], None, 5, 2))
        self.assertEqual(report.as_dict(), {"refused": 5, "refused_lines": report.lines, "refused_lines_listed": 2})
        self.assertTrue(all(len(line) <= 300 for line in report.lines))


class ThroughTheIndexLoad(unittest.TestCase):
    """The real `index.load`, against a database that records what it is asked: the readable lines are written and committed, and a refusal is not a rollback."""

    def load(self, files: dict):
        db, report = Fake(), snap.LineReport()
        with Snapshot(files) as d:
            try:
                return index.load(db, lambda: snap.read_snapshot(d.root, report=report), snap.SOURCE_ID, metadata_license="CC0"), None, db, report
            except Exception as e:
                return None, e, db, report

    def test_valid_bad_valid_loads_the_two_valid_lines_and_commits_without_a_rollback(self):
        for label, line in OneBadLine.CORRUPT.items():
            with self.subTest(label):
                count, error, db, report = self.load({"part_000.gz": [GOOD[0], line, GOOD[1]]})
                self.assertEqual((count, error, db.rollbacks, report.count), (2, None, 0, 1))
                self.assertEqual(db.commits, 3, "the loader's lock, the one batch of two records, and its unlock: each committed")
                stored = [args[0] for sql, args in db.statements if args and "INSERT INTO gateway.records" in sql]
                self.assertEqual(stored, [identity(1), identity(2)])

    def test_control_a_clean_snapshot_loads_all_three(self):
        count, error, db, report = self.load({"part_000.gz": GOOD})
        self.assertEqual((count, error, db.rollbacks, report.count), (3, None, 0, 0))


class AFileThatCannotBeRead(unittest.TestCase):
    """A file that cannot be read, decompressed or framed is not a bad line: nothing says which of its lines were lost. The load fails, naming the file."""

    def assert_load_fails(self, files: dict, name: str):
        db, report = Fake(), snap.LineReport()
        with Snapshot(files) as d:
            with self.assertRaises(PayloadError) as why:
                index.load(db, lambda: snap.read_snapshot(d.root, report=report), snap.SOURCE_ID, metadata_license="CC0")
        self.assertIn(name, str(why.exception))
        self.assertIn("cannot be read, decompressed or framed", str(why.exception))
        self.assertEqual(db.rollbacks, 1, "the open batch is rolled back, not committed as the whole snapshot")

    def test_a_gzip_cut_short_fails_the_load_whatever_was_read_before_the_cut(self):
        whole = gzip.compress(("".join(line + "\n" for line in GOOD * 40)).encode())
        for label, cut in (("a member cut in the middle", len(whole) // 2), ("only the header", 12), ("without its trailer", len(whole) - 8)):
            with self.subTest(label):
                self.assert_load_fails({"part_000.gz": whole[:cut]}, "part_000.gz")

    def test_a_corrupt_gzip_member_fails_the_load(self):
        whole = bytearray(gzip.compress(("".join(line + "\n" for line in GOOD * 40)).encode()))
        whole[len(whole) // 2] ^= 0xFF
        self.assert_load_fails({"part_000.gz": bytes(whole)}, "part_000.gz")

    def test_a_gz_that_is_not_gzip_fails_the_load(self):
        self.assert_load_fails({"part_000.gz": b"this is plain text, not a gzip member\n"}, "part_000.gz")

    def test_a_path_that_cannot_be_opened_fails_the_load(self):
        with Snapshot({"part_000.gz": GOOD}) as d:
            (d.root / "updated_date=2026-09-01" / "part_001.gz").mkdir()   # a directory called *.gz
            db, report = Fake(), snap.LineReport()
            with self.assertRaises(PayloadError) as why:
                index.load(db, lambda: snap.read_snapshot(d.root, report=report), snap.SOURCE_ID, metadata_license="CC0")
        self.assertIn("part_001.gz", str(why.exception))

    def test_a_good_file_beside_a_damaged_one_does_not_make_the_damaged_one_a_bad_line(self):
        """Files are read in order; the damaged one ends the load whatever its neighbours are, and a bad LINE in a good file is still only a line."""
        got, report, error = read({"part_000.gz": [GOOD[0], "bad", GOOD[1]], "part_001.gz": b"not gzip"})
        self.assertEqual(got, [identity(1), identity(2)])
        self.assertIsInstance(error, PayloadError)
        self.assertEqual(report.count, 1)


class FakeWithNoVenues(Fake):
    """`run` first loads the stored ISSN map, which asks the database for its venues: this one has none."""

    def cursor(self):
        cursor = super().cursor()
        cursor.fetchall = lambda: []
        return cursor


class TheRunner(unittest.TestCase):
    def test_run_returns_the_loaded_count_and_fills_the_report(self):
        for label, lines, loaded, refused in (("a clean snapshot", GOOD, 3, 0), ("valid, bad, valid", [GOOD[0], "bad", GOOD[1]], 2, 1)):
            with self.subTest(label), Snapshot({"part_000.gz": lines}) as d:
                db, report = FakeWithNoVenues(), snap.LineReport()
                self.assertEqual(snap.run(db, d.root, report=report), loaded)
                self.assertEqual((report.count, db.rollbacks), (refused, 0))

    def test_run_and_read_snapshot_take_the_report_and_it_is_not_optional(self):
        import inspect
        self.assertEqual(list(inspect.signature(snap.run).parameters), ["conn", "root", "report", "limit"])
        self.assertTrue(inspect.signature(snap.read_snapshot).parameters["report"].kind is inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(inspect.signature(snap.read_snapshot).parameters["report"].default, inspect.Parameter.empty, "a reader that refuses lines has someone to tell: the report is not optional")


if __name__ == "__main__":
    unittest.main()
