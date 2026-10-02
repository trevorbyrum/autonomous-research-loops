"""Task 2b-repair-13c: Astra's 13a probes as regressions, written against the PUBLIC surface only so that the same file runs unchanged on 2d62753, where it fails.

R13A-1 (evidence/astra-2b-repair-13a/new-parser-probes.json, index-zero-probe.json): a DOAJ CSV dump with malformed quoting, or with a column the schema reads named twice, loaded as a
successful result — zero journals for an unterminated quote in the header — and `index.load` returned a count of 0 and committed it. R13A-2 (copy-escape.diff): a source mutant of the
OpenCitations builder that read a returned record's raw copy to drop the first of three citations, with the lane still `complete`.

Nothing here imports core/wire.py, `Sealed` or any 13c name: the cases are the inputs and the observable results (the loader's identities or its error, the index's count and rollbacks, the
lane's coverage and count). tests/test_openers.py and tests/test_opaque_provenance.py hold the family and the construction these are two probes of.
"""
from __future__ import annotations

import copy
import unittest
from pathlib import Path

from research_gateway.adapters import opencitations as OC
from research_gateway.adapters.base import Client, FakeTransport, PayloadError
from research_gateway.core.broker import Broker, RatePolicy
from research_gateway.harvest import index, registries
from tests.invariant_ops import oc_row
from tests.test_invariants import ALL, run

HEAD = "Journal title,Journal ISSN (print version),Publisher,Journal license\n"
THREE = HEAD + "First,9999-9991,P,CC-BY\nSecond,9999-9983,Q,CC-BY\nThird,9999-9975,R,CC-BY\n"


def doaj_client(body: bytes) -> Client:
    t = FakeTransport()
    t.add("GET", registries.DOAJ_CSV, 200, body, headers={"Content-Type": "text/csv"})
    return Client(broker=Broker({"doaj": RatePolicy(per_second=100000)}), transport=t, sleep=lambda s: None)


def load_doaj(text: str):
    """(identities, error) of the real DOAJ loader over these bytes; a PayloadError is the channel, anything else is a failure of it."""
    try:
        return [r["identity"] for r in registries.doaj_journals(doaj_client(text.encode()))], None
    except Exception as e:
        return None, e


class Fake:
    """A database that records what it is asked: Astra's index-zero probe."""
    def __init__(self):
        self.statements, self.commits, self.rollbacks = [], 0, 0

    def cursor(self):
        db = self

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, sql, args=None):
                db.statements.append((sql, args))

            def fetchone(self):
                return None   # no stored record: every journal is new
        return Cursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class R13A1(unittest.TestCase):
    """Astra's probes, byte for byte. On 2d62753 every refused case below loads."""

    PROBES = {
        "unterminated_title": (HEAD + '"First,9999-9991,P,CC-BY\nSecond,9999-9983,Q,CC-BY\nThird,9999-9975,R,CC-BY\n', "refused"),
        "unterminated_publisher": (HEAD + 'First,9999-9991,"P,CC-BY\nSecond,9999-9983,Q,CC-BY\nThird,9999-9975,R,CC-BY\n', "refused"),
        "unterminated_header": ('Journal title,"Journal ISSN (print version),Publisher,Journal license\nFirst,9999-9991,P,CC-BY\nSecond,9999-9983,Q,CC-BY\n', "refused"),
        "junk_after_closing_quote": (HEAD + '"First"junk,9999-9991,P,CC-BY\nSecond,9999-9983,Q,CC-BY\n', "refused"),
        "duplicate_title_erases_identity": ("Journal title,Journal title\nFirst,\nSecond,\n", "refused"),
        "duplicate_license": ("Journal title,Journal ISSN (print version),Journal license,Journal license\nFirst,9999-9991,All rights reserved,CC-BY\n", "refused"),
        "valid_three": (THREE, ["issn:9999-9991", "issn:9999-9983", "issn:9999-9975"]),
        "valid_quoted_multiline": (HEAD + '"First\nJournal",9999-9991,P,CC-BY\nSecond,9999-9983,Q,CC-BY\n', ["issn:9999-9991", "issn:9999-9983"]),
    }

    def test_each_probe(self):
        for name, (text, want) in self.PROBES.items():
            identities, error = load_doaj(text)
            with self.subTest(name):
                if want == "refused":
                    self.assertIsInstance(error, PayloadError, f"loaded {identities}")
                else:
                    self.assertEqual((identities, error), (want, None))

    def test_the_valid_multiline_title_is_one_journal_with_its_newline(self):
        (record,) = list(registries.doaj_journals(doaj_client((HEAD + '"First\nJournal",9999-9991,P,CC-BY\n').encode())))
        self.assertEqual(record["title"], "First\nJournal")

    def test_the_index_load_that_returned_zero_now_fails_and_rolls_back(self):
        """Astra's index-zero probe: the unterminated header through the real `index.load` with a fake connection. It returned a loaded count of 0 with no rollback."""
        text, _ = self.PROBES["unterminated_header"]
        db, result = Fake(), None
        try:
            result = index.load(db, lambda: registries.doaj_journals(doaj_client(text.encode())), "doaj", metadata_license="CC0")
        except PayloadError:
            pass
        self.assertIsNone(result, f"the load returned {result}: a successful load of nothing")
        self.assertEqual(db.rollbacks, 1, "the failed load is rolled back, not committed as a load of nothing")

    def test_the_valid_dump_still_loads_through_index_load(self):
        db = Fake()
        n = index.load(db, lambda: registries.doaj_journals(doaj_client(THREE.encode())), "doaj", metadata_license="CC0")
        self.assertEqual((n, db.rollbacks), (3, 0))


SKIP_FIRST = [{**oc_row(1, "citing"), "timespan": {"skip": True}}, oc_row(2, "citing"), oc_row(3, "citing")]   # Astra's three citations: the first one's timespan is {"skip": true}
OLD = '    doi = next((part[4:] for part in (row[key] or "").split(" ") if part.startswith("doi:")), None)\n'
COPY_READ = ('    copied = make_record(identity="doi:10.1000/copy", kind="citation", source_id=SOURCE_ID, raw=row.raw)["raw"]\n'
             '    if copied.get("timespan") == {"skip": True}:\n        return OMIT\n')   # Astra's source mutant (evidence/astra-2b-repair-13a/copy-escape.diff), byte for byte


def opencitations_with(old: str, new: str):
    """The OpenCitations adapter with one edit, as a module-level namespace whose `enrich` can stand in for the real one."""
    source = Path(OC.__file__).read_text(encoding="utf-8")
    assert source.count(old) == 1, old
    namespace = dict(OC.__dict__)
    exec(compile(source.replace(old, new), OC.__file__, "exec"), namespace)
    return source.replace(old, new), namespace["enrich"]


def lane_with(enrich, body) -> tuple[dict, dict]:
    original = OC.enrich
    OC.enrich = enrich
    try:
        op = next(op for name, op in ALL.items() if name.startswith("opencitations.enrich citations"))
        return run(op, copy.deepcopy(body))
    finally:
        OC.enrich = original


class R13A2(unittest.TestCase):
    def test_the_unmodified_adapter_keeps_all_three_citations(self):
        out, lane = lane_with(OC.enrich, SKIP_FIRST)
        self.assertEqual((lane["coverage"], lane["completeness"], lane["count"], lane["retrieved"]), ("searched_ok", "complete", 3, ["doi:10.9000/c1", "doi:10.9000/c2", "doi:10.9000/c3"]))

    def test_astras_mutant_cannot_read_the_copy_it_made_so_it_fails_loudly_instead_of_dropping_a_candidate(self):
        """On 2d62753 this lane was `complete`, count 2, the first identity silently omitted. Now the returned record's `raw` is Sealed: `.get` is a SealedRead, a programming error that no builder net
        swallows and no lane blames on the provider."""
        _, enrich = opencitations_with(OLD, COPY_READ + OLD)
        out, lane = lane_with(enrich, SKIP_FIRST)
        self.assertNotEqual(lane["completeness"], "complete", lane)
        self.assertIn("SealedRead", lane.get("error", ""), lane)
        self.assertNotIn("count", lane, "no count: nothing was established")
        _, control = lane_with(enrich, [oc_row(i, "citing") for i in (1, 2, 3)])   # the same mutant over rows with no skip marker still fails: it fails on the READ, not on the data
        self.assertNotEqual(control["completeness"], "complete")


if __name__ == "__main__":
    unittest.main()
