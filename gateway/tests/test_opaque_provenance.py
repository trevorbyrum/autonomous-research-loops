"""Task 2b-repair-13c (Astra R13A-2): provenance stays opaque THROUGH the canonical record, and becomes plain only where the gateway serializes or stores a result.

13a sealed what the decoder hands an adapter: a Response with no readable payload, a `Sealed` raw object, a `Passive` for every `any_()` field. Astra then wrote a source mutant of the OpenCitations
adapter that needed none of the spellings the source scans looked for:

    copied = make_record(identity="doi:10.1000/copy", kind="citation", source_id=SOURCE_ID, raw=row.raw)["raw"]
    if copied.get("timespan") == {"skip": True}:
        return OMIT

`make_record` returned `plain(record)`, so the dictionary it handed back held the provider's raw object in the clear. `timespan` is declared `any_()`: metadata, never read. The mutant read it, and the
adapter silently dropped the first of three citations while the lane reported `complete`, count 3 → 2. Every import, reflection and read-inventory check passed, and a 565-test run passed with it. The
source scan had been the guarantee. It was a convention: the exit it knew about (`.raw` outside a `raw=` argument) was closed, and the one beside it (the returned copy) was not.

The construction now: `make_record` returns a plain dict whose provenance is still opaque — `raw` is a `Sealed`, every `extra` value built from an `any_()` field is the `Passive` it was, and a
download's bytes are a `Sealed` — and the router turns the whole answer into plain data at one place, after every lane has run and every selection, coverage and licence decision is made
(`router.execute`), as the index does for what it stores (`harvest/index.upsert`). This file runs, for every exit the review listed:

  * TheCopyEscape        Astra's mutant (tests/test_astra_13a.py runs it as a regression that fails on 2d62753): the scan that cannot see it, and the variants
  * EveryExit            canonical-record construction (raw, extra, a typed field, the identity), `download()`, an unreadable member's raw, equality as a way to read, and `plain` itself
  * WhereItBecomesPlain  before the router's boundary every operation's records still hold `Sealed` raw (nothing between the builder and the router materialized it), after it every answer is plain
                         JSON; the index load writes plain data and never the object's repr
  * BytesAreOpenedOnlyWhere  the claim "only the decoder opens a payload's bytes", stated for what it covers: the exact inventory of reads of a Response's bytes, with what each is for

What this cannot show, and nothing in Python can: that private storage is unreachable by a name (`Sealed._value`), that `x is None` on a Passive can be intercepted, or that a finite corpus proves a
family closed. They are the language-level residuals the task report lists; no workaround is built for them.
"""
from __future__ import annotations

import ast
import copy
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_gateway.adapters import opencitations as OC
from research_gateway.adapters.base import FakeTransport, Response
from research_gateway.core import router as R
from research_gateway.core import schema as S
from research_gateway.core.canonical import make_record
from research_gateway.core.payload import (MemberList, OMIT, Passive, PassiveRead, PayloadError, Rec, Sealed, SealedRead, Unreadable, UndeclaredRead, plain)
from research_gateway.harvest import index, registries
from tests import test_member_isolation as M
from tests.invariant_ops import corrupt_route, oc_row
from tests.test_invariants import ALL, run
from tests.test_astra_13a import COPY_READ, OLD, SKIP_FIRST, lane_with, opencitations_with
from tests.test_openers import Fake, doaj_client, THREE

ROOT = Path(__file__).resolve().parents[1] / "research_gateway"
THREE_IDS = ["doi:10.9000/c1", "doi:10.9000/c2", "doi:10.9000/c3"]


class Judged(unittest.TestCase):
    """A read or a build that must be a programming error (UndeclaredRead): anything else — including the right result — is a FAILURE of the assertion, not an error of the test, so that a mutant that
    removes the construction is killed by an assertion (tools/gen2_gateway_mutations.py)."""

    def programming_error(self, call, label: str = "") -> None:
        try:
            call()
        except UndeclaredRead:
            return
        except Exception as e:
            self.fail(f"{label}raised {type(e).__name__}, which is a malformed member's loss or a bug, not the programming error an opaque read is: {str(e)[:80]}")
        self.fail(f"{label}was read")


class TheCopyEscape(Judged):
    def test_the_source_scan_still_cannot_see_it_which_is_why_the_scan_is_a_backstop(self):
        """The inventory of reads and the import and reflection checks find nothing in the mutated tree (Astra's own finding). That is unchanged and no longer matters: what stops the mutant is the
        object it reads."""
        source, _ = opencitations_with(OLD, COPY_READ + OLD)
        with tempfile.TemporaryDirectory() as tmp:
            tree = M.Imports.tree(Path(tmp), **{M.Imports.OC: [(OLD, COPY_READ + OLD)]})
            self.assertEqual((M.import_findings(tree), [f for f in M.reflection_in_adapters(tree) if f[0] == "adapters/opencitations.py"]), ([], []))
            real = M.reads()
            changed = {k: v for k, v in M.reads(tree).items() if v != real.get(k)}
            self.assertEqual(changed, {}, "the mutant adds no use the inventory lists")

    def test_the_variants_each_fail_where_the_value_is_read(self):
        """The copy is not the only way a record's provenance could be read back: an `extra` value built from the passive field, a typed field built from it, a record's raw tested for truth."""
        row = S.decode("x", S.obj({"id": S.text(), "oci": S.any_(), "timespan": S.any_()}), {"id": "a", "oci": "1-1", "timespan": {"skip": True}})
        rec = make_record(identity="doi:10.1000/x", kind="citation", source_id="x", extra={"timespan": row["timespan"], "both": [row["oci"], row["timespan"]]}, raw=row.raw)
        for label, read in {"the extra, compared": lambda: rec["timespan"] == {"skip": True}, "the extra, tested for truth": lambda: bool(rec["timespan"]),
                            "the extra, inside a list": lambda: rec["both"][1] == {"skip": True}, "the extra, formatted": lambda: f"{rec['timespan']}",
                            "the raw, read as a mapping": lambda: rec["raw"].get("timespan"), "the raw, subscripted": lambda: rec["raw"]["timespan"],
                            "the raw, tested for truth": lambda: bool(rec["raw"]), "the raw, iterated": lambda: list(rec["raw"]), "the raw, its length": lambda: len(rec["raw"])}.items():
            with self.subTest(label):
                self.programming_error(read, "a read of provenance ")
        self.assertFalse(rec["raw"] == {"timespan": {"skip": True}}, "compared with a plain value it is not equal, and asking read nothing")
        for label, build in {"a title": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", title=row["timespan"]),
                             "a venue": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", venue=row["timespan"]),
                             "an authors list": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", authors=[row["timespan"]]),
                             "a links list": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", links=(row["oci"],)),
                             "identifiers": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", identifiers={"doi": row["oci"]}),
                             "a year": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", year=row["oci"]),
                             "a licence": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", license=row["oci"]),
                             "the identity": lambda: make_record(identity=row["oci"], kind="citation", source_id="x"),
                             "a title built from the raw": lambda: make_record(identity="doi:10.1000/x", kind="citation", source_id="x", title=row.raw)}.items():
            with self.subTest(f"{label} is a typed field: it refuses an opaque value"):
                self.programming_error(build, "a record built from an opaque value ")

    def test_each_variant_run_through_the_real_adapter_and_router_is_never_a_complete_lane(self):
        variants = {"the extra, compared": ('    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, year=year_from(row["creation"]),\n',
                                           '    if make_record(identity="doi:10.1000/x", kind="citation", source_id=SOURCE_ID, extra={"t": row["timespan"]})["t"] == "P1Y":\n        return OMIT\n'
                                           '    return make_record(identity=f"doi:{doi}", kind="citation", source_id=SOURCE_ID, year=year_from(row["creation"]),\n'),
                    "the raw, tested": (OLD, '    if make_record(identity="doi:10.1000/x", kind="citation", source_id=SOURCE_ID, raw=row.raw)["raw"]:\n        return OMIT\n' + OLD)}
        for label, (old, new) in variants.items():
            _, enrich = opencitations_with(old, new)
            out, lane = lane_with(enrich, [oc_row(i, "citing") for i in (1, 2, 3)])
            with self.subTest(label):
                self.assertNotEqual(lane["completeness"], "complete", lane)
                self.assertRegex(lane.get("error", ""), "SealedRead|PassiveRead")


class EveryExit(Judged):
    """The indirect exits of the review: canonical-record construction, `download()`, and the ones beside them."""

    def decoded(self):
        return S.decode("x", S.obj({"id": S.text(), "m": S.any_(), "inner": S.obj({"k": S.any_()}), "l": S.own(S.any_())}), {"id": "a", "m": [1, {"a": 2}], "inner": {"k": 5}, "l": [1, [2]]})

    def test_a_record_is_a_plain_dict_with_plain_typed_fields_and_opaque_provenance(self):
        d = self.decoded()
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", title="T", authors=["A"], year=2020, venue="V", identifiers={"doi": "10.1/a"}, links=["u"], license="CC0",
                          extra={"m": d["m"], "inner": d["inner"], "l": d["l"], "pair": (d["m"], 1), "typed": [1, 2], "nested": {"deep": [d["m"]]}}, raw=d.raw)
        self.assertIs(type(rec), dict)
        self.assertEqual({k: v for k, v in rec.items() if k in ("title", "authors", "year", "venue", "identifiers", "links", "license")},
                         {"title": "T", "authors": ["A"], "year": 2020, "venue": "V", "identifiers": {"doi": "10.1/a"}, "links": ["u"], "license": "CC0"})
        self.assertIsInstance(rec["raw"], Sealed)
        self.assertIsInstance(rec["m"], Passive)
        self.assertIsInstance(rec["l"], list)   # an own list of Passives is a list of Passives: the structure is plain, each element opaque
        self.assertTrue(all(isinstance(x, Passive) for x in rec["l"]))
        self.assertIsInstance(rec["pair"][0], Passive)
        self.assertIsInstance(rec["nested"]["deep"][0], Passive)
        self.assertEqual((rec["typed"], plain(rec["typed"])), ([1, 2], [1, 2]), "an extra value that holds nothing opaque is just plain data")
        self.assertIsInstance(rec["inner"], Rec, "a decoded object kept in an extra stays the Rec: its declared fields read, its undeclared ones do not, its raw is sealed")
        self.programming_error(lambda: rec["inner"]["k"] == 5)

    def test_extra_is_a_copy_of_the_structure_and_never_an_alias_of_the_adapters_list(self):
        mine = [1, [2, 3]]
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", extra={"a": mine})
        mine[1].append(4)
        self.assertEqual(rec["a"], [1, [2, 3]])

    def test_the_materialized_record_is_what_the_old_constructor_returned(self):
        """`plain(record)` is the dictionary `make_record` used to return: same keys, same values, JSON-serializable, and a copy at every level."""
        d = self.decoded()
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", extra={"m": d["m"], "inner": d["inner"], "l": d["l"]}, raw=d.raw)
        out = plain(rec)
        self.assertEqual(json.loads(json.dumps(out))["m"], [1, {"a": 2}])
        self.assertEqual((out["raw"], out["l"], out["inner"]), ({"id": "a", "m": [1, {"a": 2}], "inner": {"k": 5}, "l": [1, [2]]}, [1, [2]], {"k": 5}),
                         "a Rec in an extra leaves as the object the provider sent for it")
        self.assertIsNot(plain(rec)["raw"], out["raw"], "each materialization is its own copy")
        out["raw"]["m"].append("changed")
        self.assertEqual(plain(rec)["raw"]["m"], [1, {"a": 2}], "what a materialized record holds cannot reach back into what the decoder kept")
        self.assertEqual(plain(d.raw)["m"], [1, {"a": 2}])

    def test_a_raw_that_is_a_plain_value_is_sealed_too(self):
        """The snapshot loader and tests hand `make_record` a plain dict: it is sealed here (as a copy), so a record's raw is opaque whoever made it."""
        mine = {"k": [1]}
        rec = make_record(identity="doi:10.1/a", kind="article", source_id="x", raw=mine)
        mine["k"].append(2)
        self.assertIsInstance(rec["raw"], Sealed)
        self.assertEqual(plain(rec["raw"]), {"k": [1]})
        self.assertIsNone(make_record(identity="doi:10.1/a", kind="article", source_id="x")["raw"], "a record with no raw says so")

    def test_a_download_is_sealed_and_only_the_router_boundary_makes_it_bytes(self):
        resp = Response(200, {"content-type": "application/octet-stream"}, b"secret-bytes-7f3a", "https://example.org/f")
        got = resp.download()
        self.assertIsInstance(got, Sealed)
        for label, read in {"len": lambda: len(got), "bytes": lambda: bytes(got), "decode": lambda: got.decode(), "index": lambda: got[0], "iterate": lambda: list(got), "startswith": lambda: got.startswith(b"s"),
                            "truth": lambda: bool(got), "in": lambda: b"s" in got, "str": lambda: str(got), "format": lambda: f"{got}", "hash": lambda: hash(got), "add": lambda: got + b"x",
                            "equal to bytes": lambda: got == b"secret-bytes-7f3a" or got.attribute}.items():
            with self.subTest(label):
                self.programming_error(read, "a read of a download ")
        self.assertEqual(repr(got), "<Sealed>")
        self.assertEqual(plain(got), b"secret-bytes-7f3a")

    def test_an_unreadable_members_raw_and_a_rec_raw_and_without_are_sealed(self):
        (bad,) = S.decode("x", S.members(S.obj({"id": S.key()})), [{"id": False, "x": 1}]).unreadable()
        rec = S.decode("x", S.obj({"id": S.text()}), {"id": "a", "extra": {"k": 1}})
        for raw in (bad.raw, rec.raw, rec.raw.without("extra")):
            self.assertIsInstance(raw, Sealed)
            self.programming_error(lambda: raw.get("id"))

    def test_equality_is_not_a_way_to_read_a_sealed_object_by_guessing_it(self):
        """A record builder may ask whether the provider repeated itself (two decoder-issued objects compare); `row.raw == Sealed({...})` asks whether it holds a value the adapter chose, which is
        reading it one guess at a time. Only objects the decoder issued compare."""
        a, b = S.decode("x", S.obj({"id": S.text()}), {"id": "a"}), S.decode("x", S.obj({"id": S.text()}), {"id": "a"})
        self.assertEqual(a.raw, b.raw)
        self.assertNotEqual(a.raw, S.decode("x", S.obj({"id": S.text()}), {"id": "b"}).raw)
        self.assertEqual(a, b)
        for guess in (Sealed({"id": "a"}), Sealed({"id": "b"}), Sealed({"id": "a"}, _issued=False)):
            with self.subTest(guess=repr(guess)):
                self.programming_error(lambda: a.raw == guess, "a comparison with a guess ")
                self.programming_error(lambda: guess == a.raw, "a comparison with a guess ")
        self.assertFalse(a.raw == {"id": "a"}, "a sealed object is not equal to a plain value, and asking reads nothing")
        self.assertFalse(a.raw == None)   # noqa: E711

    def test_a_decoded_object_kept_in_a_record_is_not_a_way_to_its_raw(self):
        rec = S.decode("x", S.obj({"id": S.text()}), {"id": "a", "hidden": 1})
        self.programming_error(lambda: rec["hidden"])
        self.assertEqual(rec["id"], "a")
        self.assertIsInstance(rec.raw, Sealed)

    def test_plain_is_how_a_sealed_value_leaves_and_a_provider_module_that_uses_it_is_listed(self):
        """`plain` is the trusted boundary's door, and the inventory of doors lists every use of it in provider modules, with its reason: the one use is the index load (the storage boundary)."""
        uses = {k: v for k, v in M.reads().items() if any(w in ("call plain", "reference plain", "attribute plain") for w in v)}
        self.assertEqual(uses, {("harvest/index.py", "upsert"): ["call plain"]})

    def test_constructing_a_sealed_or_passive_in_a_provider_module_is_listed_and_so_is_the_issuing_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "adapters").mkdir()
            (root / "core").mkdir()
            for name in ("schema", "sdmx", "identity"):
                (root / "core" / f"{name}.py").write_text("")
            (root / "adapters" / "new_lane.py").write_text(
                "from ..core.payload import Sealed, Passive\n\ndef guess(raw):\n    return raw == Sealed({'a': 1})\n\ndef issue():\n    return Sealed({'a': 1}, _issued=True)\n\ndef make():\n    return Passive(1)\n")
            found = {fn: sorted(v) for (_, fn), v in M.reads(root).items() if fn != "<module>"}
        self.assertEqual(found, {"guess": ["call Sealed"], "issue": ["call Sealed", "private _issued"], "make": ["call Passive"]})


class WhereItBecomesPlain(Judged):
    def test_before_the_routers_boundary_every_operations_records_still_hold_a_sealed_raw(self):
        """Nothing between the builder and the router materialized provenance: with the boundary's `plain` turned off, every record of every operation of the harness (and its populated variants)
        carries a Sealed raw (or none), and the answer is not JSON — it is the boundary that makes it so."""
        checked = sealed = 0
        for name, op in ALL.items():
            with mock.patch.object(R, "plain", lambda x: x):
                out, _ = run(op, copy.deepcopy(corrupt_route(op).body))
            for rec in out.get("records") or []:
                checked += 1
                with self.subTest(op=name, identity=rec.get("identity")):
                    self.assertTrue(rec.get("raw") is None or isinstance(rec["raw"], Sealed), type(rec.get("raw")))
                    sealed += isinstance(rec.get("raw"), Sealed)
            if out.get("records") and any(isinstance(r.get("raw"), Sealed) for r in out["records"]):
                with self.assertRaises((TypeError, PassiveRead, SealedRead)):
                    json.dumps(out)   # the answer is not JSON until the boundary makes it so
        self.assertGreater(checked, 80)
        self.assertGreater(sealed, 60)

    def test_after_it_every_operations_answer_is_plain_json_with_raw_as_what_the_provider_sent(self):
        for name, op in ALL.items():
            out, _ = run(op, copy.deepcopy(corrupt_route(op).body))
            with self.subTest(op=name):
                try:
                    again = json.loads(json.dumps(out))
                except Exception as e:
                    self.fail(f"the answer is not plain JSON: {type(e).__name__}: {str(e)[:80]}")
                for rec in out.get("records") or []:
                    self.assertFalse(isinstance(rec.get("raw"), (Sealed, Passive)))
                    for k, v in rec.items():
                        self.assertNotIsInstance(v, (Sealed, Passive, Rec, MemberList, Unreadable), k)
                self.assertEqual(len(again.get("records") or []), len(out.get("records") or []))

    def test_a_downloads_bytes_are_sealed_until_the_router_boundary_and_bytes_after_it(self):
        from tests.test_routing import ADAPTERS, SEED
        from research_gateway.adapters.base import Client
        from research_gateway.core.broker import Broker, RatePolicy
        seed = copy.deepcopy(SEED)
        for entry in seed:
            if entry["id"] in ("huggingface", "globe"):
                entry["enabled"] = True
        router = R.Router(seed, ADAPTERS)
        transport = FakeTransport()
        transport.add("GET", "https://huggingface.co/api/datasets/owner/corpus", body={"id": "owner/corpus", "cardData": {"license": "cc0-1.0"}, "siblings": [{"rfilename": "data.csv"}], "gated": False})
        transport.add("GET", "https://huggingface.co/datasets/owner/corpus/resolve/main/data.csv", body="a,b\n1,2\n")
        client = Client(broker=Broker({"huggingface": RatePolicy(per_second=100)}), transport=transport, sleep=lambda s: None)
        request = {"request_type": "fetch", "target": "hf:owner/corpus", "params": {"path": "data.csv", "download": True}}
        with mock.patch.object(R, "plain", lambda x: x):
            before = R.execute(router, request, client)
        self.assertIsInstance(before["content"], Sealed, "nothing before the boundary made the bytes readable")
        after = R.execute(router, request, client)
        self.assertEqual(after["content"], b"a,b\n1,2\n")

    def load(self, stream, source: str, **kw):
        """(count, the fake database) of an index load; a load that raises is a FAILURE of the assertion that it writes plain data, not an error of the test's setup."""
        db = Fake()
        try:
            return index.load(db, stream, source, **kw), db
        except Exception as e:
            self.fail(f"the load raised {type(e).__name__}: {str(e)[:100]}")

    def test_the_index_load_writes_plain_data_never_the_object_it_holds(self):
        """The loaders yield records whose provenance is sealed; `index.upsert` is the storage boundary. The statements it executes hold the provider's row and the metadata as JSON, and no repr."""
        n, db = self.load(lambda: registries.doaj_journals(doaj_client(THREE.encode())), "doaj", metadata_license="CC0")
        self.assertEqual(n, 3)
        arguments = [json.dumps(args, default=str) for sql, args in db.statements if args and "record_sources" in sql]
        self.assertEqual(len(arguments), 3)
        for text in arguments:
            self.assertNotIn("<Sealed>", text)
            self.assertNotIn("<Passive>", text)
        self.assertIn("Journal ISSN (print version)", arguments[0], "the stored raw is the provider's row")
        canonical = [json.loads(args[2]) for sql, args in db.statements if args and "gateway.records" in sql and "INSERT" in sql]
        self.assertEqual([c["in_doaj"] for c in canonical], [True, True, True])

    def test_the_cache_is_a_storage_boundary_too_in_memory_and_in_the_database(self):
        """`Cache.put_record` persists a record's raw: a record built straight from an adapter or a loader, with its provenance still sealed, is made plain there (the router's answer already is)."""
        from research_gateway.core.cache import Cache
        d = S.decode("x", S.obj({"id": S.text(), "m": S.any_()}), {"id": "a", "m": [1, {"a": 2}]})
        record = make_record(identity="doi:10.1/a", kind="article", source_id="crossref", title="T", license="CC0", extra={"m": d["m"]}, raw=d.raw)
        self.assertIsInstance(record["raw"], Sealed)
        db = Fake()
        cache = Cache()
        cache.conn = db   # a database that records what it is asked (the constructor's own check of the stored rows is not what is tested)
        try:
            cache.put_record(record, storable=True, persist_members=[0])
        except Exception as e:
            self.fail(f"the cache raised {type(e).__name__}: {str(e)[:100]}")
        written = [json.dumps(args, default=str) for sql, args in db.statements if args]
        self.assertTrue(written and not any("<Sealed>" in text or "<Passive>" in text for text in written), written)
        (stored_raw,) = [json.loads(args[2]) for sql, args in db.statements if args and "record_sources" in sql]
        self.assertEqual(stored_raw, {"id": "a", "m": [1, {"a": 2}]}, "the stored raw is the provider's object")
        kept = cache.get_record("doi:10.1/a")
        self.assertEqual(kept["m"], [1, {"a": 2}])
        self.assertEqual(kept["raw"], {"id": "a", "m": [1, {"a": 2}]})
        self.assertIsNot(kept, record, "the cache keeps its own copy")

    def test_the_index_load_of_a_crossref_page_stores_the_passive_counts_as_plain_numbers(self):
        from tests.test_harvest import CROSSREF_PAGE, client
        c, t = client()
        t.add("GET", "https://api.crossref.org/journals?", body=CROSSREF_PAGE)
        _, db = self.load(lambda: registries.crossref_journals(c), "crossref", metadata_license="x")
        canonical = [json.loads(args[2]) for sql, args in db.statements if args and "gateway.records" in sql and "INSERT" in sql]
        self.assertEqual(canonical[0]["works_count"], 1234, "an `any_()` count, stored as the number the provider sent")


class BytesAreOpenedOnlyWhere(unittest.TestCase):
    """The scope of "only the decoder opens bytes", stated for what it covers. A payload's bytes — what a provider's answer SAYS — are opened by core/schema.py's decode/parse_xml/decode_csv alone
    (through core/wire.py). The client holds the bytes too, and reads them in four places for its own purposes, none of which says what a provider's data is or can produce a record or an answer:
    this is the exact inventory, and a new read of `_body` fails until it is listed."""

    READS = {
        ("adapters/base.py", "Response.download"): ("returns the bytes sealed, for a file the caller asked to download: content handed to the router and never read (EveryExit)"),
        ("adapters/base.py", "Response.__repr__"): ("the length of the body, for a diagnostic"),
        ("adapters/base.py", "_text_of"): ("the text of a 401/403 body, to classify the failure of the CALL (calllog.classify); it never leaves the client"),
        ("adapters/base.py", "_count_of"): ("the number of results, for the call log, through the decoder's own opener (core/wire.py): bookkeeping"),
        ("adapters/base.py", "check"): ("the first bytes of a success answer, to refuse an HTML page wearing it: it can only make a lane unavailable, never produce a record or an empty answer"),
        ("adapters/base.py", "FakeTransport.request"): ("the test transport copies a canned answer's body into a new Response"),
        ("core/schema.py", "_open_json"): ("the decoder: a provider's JSON"),
        ("core/schema.py", "_bytes_or_text"): ("the decoder: the bytes SDMX-ML and CSV openers read"),
    }

    @staticmethod
    def found() -> dict:
        out: dict = {}
        for path in sorted(ROOT.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if rel.startswith("api/") or rel in ("core/payload.py",):
                continue   # api/http.py's own `_body()` is a request body, a different thing; payload.py is where the storage is declared
            tree = ast.parse(path.read_text(encoding="utf-8"))
            spans = sorted(((fn.lineno, fn.end_lineno, q) for q, fn in M.functions(tree)), key=lambda s: s[1] - s[0])
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "_body":
                    out.setdefault((rel, next((q for a, b, q in spans if a <= node.lineno <= b), "<module>")), []).append(node.lineno)
        return out

    def test_every_read_of_a_responses_bytes_is_listed_with_what_it_is_for(self):
        found = self.found()
        self.assertEqual(sorted(set(found) - set(self.READS)), [], "a new read of a Response's bytes: say what it is for, and why it is not a payload decision")
        self.assertEqual(sorted(set(self.READS) - set(found)), [], "a listed read that is no longer there")
        self.assertTrue(all(len(why.split()) >= 5 for why in self.READS.values()))

    def test_no_provider_module_reads_them_at_all(self):
        provider = {p.relative_to(ROOT).as_posix() for p in M.provider_modules()}
        self.assertEqual([k for k in self.found() if k[0] in provider], [])

    def test_the_clients_own_reads_say_nothing_a_decision_can_use(self):
        """What each of the client's reads returns, for a body that is a marker: a count, a bool, a class name — never the marker, never a value of the payload."""
        from research_gateway.adapters import base
        body = b'{"results": [{"secret_marker_7f3a": 1}, 2, 3]}'
        resp = Response(200, {"content-type": "application/json"}, body, "https://example.org/x")
        self.assertEqual(base._count_of(resp), 3)
        self.assertTrue(base.check("x", resp))
        self.assertNotIn("secret_marker_7f3a", repr(resp))
        refused = Response(403, {}, b"Forbidden secret_marker_7f3a", "https://example.org/x")
        self.assertNotIn("secret_marker_7f3a", repr(refused))


if __name__ == "__main__":
    unittest.main()
