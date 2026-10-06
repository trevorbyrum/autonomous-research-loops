"""Task 2b-repair-13a (Astra R12-1): a declaration is COMPLETE for every field that decides something, and that is enforced by the decoder's own output, not by scanning.

Repair-12 declared a schema per operation, and left `any_()` for "fields the adapter only stores". But `any_()` meant "any value, carried as sent", and an adapter could read such a value for
a decision — which candidate a catalogue lists, what its next request names — without anything noticing: a BEA dataset named `true` or `["BAD"]` became a returned identifier and a request argument, a
falsy one was silently filtered out, and all of it reported `complete`. 30 wrong-kind identifier cases of five operations (BEA, BLS, FRED), and eight label cases beside them, went through. Fixing those five
fields would have been the next access-pattern patch; the cause was that nothing STOPPED a decision from reading an untyped value. Now (core/payload.py, core/schema.py):

  * a field declared `any_()` is handed to the adapter as a `Passive`: carried as sent, for storing in a record's `extra` or raw, and every attempt to read it raises PassiveRead — so the schema of a field that
    identifies, selects, ends, continues or is sent in a request MUST give it a kind, and a mistake shows on the first answer that reaches it (EnforcedByTheDecoder, below, runs three of the mistakes);
  * every `any_()` that remains was audited by what the adapter does with it downstream (AUDITED): metadata stored in `extra`, content stored whole, a list whose length is all that is read — never an identity,
    a choice, an end, a continuation or a request argument; a new one, or a removed one, is a failure until the table is read again;
  * the fields that were `any_()` and decide something are kinds now (DecisionFieldsAreKinds), with a refused wrong kind through the real adapter and router for each, and readable controls.

What this cannot show: that a `Passive` is never given to something that does not read it — an `is None` test, which Python cannot intercept, says "there" for a field that is not, and a handful of CPython
functions type-check an argument before calling anything on it (`x in "abc"` raises TypeError, not PassiveRead): none of them can hand a decision a value, and a read of that kind in a path the valid
answers do not take would show as a member lost. The valid answers of every operation and their populated variants (tests/test_invariants.py's baselines) are what exercise the paths.
"""
from __future__ import annotations

import ast
import collections
import copy
import unittest
from pathlib import Path
from unittest import mock

from research_gateway import adapters
from research_gateway.adapters import bea, bls, census, fred, govinfo, harvard_dataverse as dv, huggingface, openaire, openml, socrata, unpaywall
from research_gateway.core import schema as S, sdmx
from tests import invariant_ops as ops
from tests import test_invariants as H
from tests.invariant_ops import corrupt_route

ROOT = Path(__file__).resolve().parents[1] / "research_gateway"

# Every `any_()` the provider modules still declare, by file and the field names around it (innermost first), how many there are, and what the adapter does with it. The roles:
#   extra     copied into a record's `extra` (record metadata), never read
#   content   a provider's statistical or row content, stored whole in a record, never read
#   counted   only its LENGTH is read (a count that is unknown when it cannot be read)
#   shape     the schema declares the shape (a list, or the value itself) and what is in it is metadata
#   context   structural context kept with a record's raw (I-8)
#   ignored   never read at all: a key selects, its value is not looked at
AUDITED: dict[str, dict[tuple, tuple[int, str, str]]] = {
    "adapters/bls.py": {("survey_name", "catalog"): (1, "extra", "record extra `survey`"), ("seasonality", "catalog"): (1, "extra", "record extra `seasonality`"),
                        ("value", "data"): (1, "content", "an observation's value, in the record's observations")},
    "adapters/census.py": {(): (1, "content", "a table's data cells (its header row is text: S.grid)")},
    "adapters/crossref.py": {("type",): (1, "extra", "record extra `type`"), ("is-referenced-by-count",): (1, "extra", "record extra `cited_by_count`"),
                             ("reference-count",): (1, "extra", "record extra `reference_count`"), ("unstructured",): (1, "extra", "a reference record's extra")},
    "adapters/datacite.py": {("id", "data", "client"): (1, "extra", "record extra `client_id`")},
    "adapters/fred.py": {("date", "observations"): (1, "content", "an observation's date, in the record's observations"), ("value", "observations"): (1, "content", "an observation's value"),
                         ("units", "seriess"): (1, "extra", "record extra `units` (a catalogue entry's units are text)"), ("frequency", "seriess"): (1, "extra", "record extra `frequency`")},
    "adapters/govinfo.py": {("lastModified",): (1, "extra", "record extra `last_modified`"), ("docClass",): (1, "extra", "record extra `doc_class`"),
                            ("download",): (1, "ignored", "a package's download links: the KEY names a format, the value is never read (links are built from the requested package)")},
    "adapters/harvard_dataverse.py": {("fileCount",): (1, "extra", "a hit's `file_count`"), ("subjects",): (1, "extra", "a hit's `subjects`"),
                                      ("contentType", "dataFile"): (1, "extra", "a file's `content_type`"), ("filesize", "dataFile"): (1, "extra", "a file's `size`"),
                                      ("description", "dataFile"): (1, "extra", "a file's `description`"), ("files", "latestVersion"): (1, "counted", "a dataset's `file_count` only")},
    "adapters/huggingface.py": {("downloads",): (1, "extra", "record extra"), ("likes",): (1, "extra", "record extra"), ("private",): (1, "extra", "record extra"),
                                ("tags",): (1, "extra", "a tag that is not text is only stored (the licence is read from the text ones)"), ("siblings",): (1, "counted", "a repository's `file_count` only")},
    "adapters/kaggle.py": {("subtitle",): (1, "extra", "record extra"), ("totalBytes",): (1, "extra", "a dataset's `total_bytes` (a FILE's size is typed: whole)"),
                           ("downloadCount",): (1, "extra", "record extra"), ("usabilityRating",): (1, "extra", "record extra"), ("creationDate",): (1, "extra", "a file's `created`")},
    "adapters/openaire.py": {("label", "bestAccessRight"): (1, "extra", "record extra `access_right`")},
    "adapters/opencitations.py": {("oci",): (1, "extra", "record extra"), ("timespan",): (1, "extra", "record extra")},
    "adapters/openml.py": {("version",): (2, "extra", "record extra `version`, in a listing and in a description"), ("status",): (1, "extra", "record extra"),
                           ("format",): (2, "extra", "record extra `format`"), ("default_target_attribute",): (1, "extra", "record extra `default_target`"),
                           ("file_id",): (1, "extra", "record extra `file_id`"), ("value", "quality"): (1, "extra", "a quality's value, in the record's `instances`/`features`")},
    "adapters/semanticscholar.py": {("citationCount",): (1, "extra", "record extra"), ("referenceCount",): (1, "extra", "record extra"), ("publicationTypes",): (1, "extra", "record extra")},
    "adapters/socrata.py": {(): (1, "counted", "a dataset's rows: stored whole, and their COUNT drives the next offset"), ("attribution",): (1, "extra", "a view's attribution"),
                            ("type", "resource"): (1, "extra", "a hit's type"), ("attribution", "resource"): (1, "extra", "a hit's attribution"),
                            ("termsLink", "license"): (1, "extra", "record extra `license_link`")},
    "adapters/unpaywall.py": {("host_type",): (1, "extra", "a location's extra"), ("version",): (1, "extra", "a location's extra")},
    "core/sdmx.py": {("attributes",): (1, "context", "structural context"), ("annotations",): (1, "context", "structural context"), ("name",): (1, "context", "structural context"),
                     ("names",): (1, "context", "structural context"),
                     ("observations",): (2, "shape", "an observation is `[value, ...]` or the value itself: the shape is declared (oneof(own(any_), any_)), the value is metadata")},
    "harvest/registries.py": {("total-dois", "counts"): (1, "extra", "a journal's `works_count`"), ("current-dois", "counts"): (1, "extra", "a journal's `current_dois`"),
                              ("clientType", "attributes"): (1, "extra", "a repository's `client_type`"), ("isActive", "attributes"): (1, "extra", "a repository's `active` flag"),
                              ("language", "attributes"): (1, "extra", "a repository's `language`"), ("name", "subjects"): (1, "extra", "a subject's name, in the record's subjects")},
}
PASSIVE_ROLES = {"extra", "content", "counted", "shape", "context", "ignored"}
PROVIDER_FILES = [p for p in sorted(ROOT.rglob("*.py")) if (p.relative_to(ROOT).as_posix().startswith(("adapters/", "harvest/")) or p.relative_to(ROOT).as_posix() in ("core/sdmx.py", "core/identity.py"))
                  and p.name not in ("base.py", "__init__.py", "_response.py", "_transport.py", "_links.py")]


def any_uses() -> collections.Counter:
    """(file, the dict keys around the constructor, innermost first) for every `S.any_(...)` of the provider modules: read from the syntax tree, independently of any schema object."""
    found: collections.Counter = collections.Counter()
    for path in PROVIDER_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "any_" and isinstance(node.func.value, ast.Name) and node.func.value.id == "S":
                fields, current = [], node
                for _ in range(5):
                    parent = parents.get(id(current))
                    if isinstance(parent, ast.Dict):
                        fields += [k.value for k, v in zip(parent.keys, parent.values) if v is current and isinstance(k, ast.Constant)]
                    if parent is None:
                        break
                    current = parent
                found[(path.relative_to(ROOT).as_posix(), tuple(fields))] += 1
    return found


class AuditedInventory(unittest.TestCase):
    def test_every_remaining_any_is_audited_by_what_the_adapter_does_with_it(self):
        found = any_uses()
        audited = collections.Counter({(f, fields): n for f, table in AUDITED.items() for fields, (n, role, why) in table.items()})
        self.assertEqual(dict(found - audited), {}, "an `any_()` that is not in the table: read what the adapter does with it, and say (or give it a kind)")
        self.assertEqual(dict(audited - found), {}, "an audited `any_()` that is no longer there")

    def test_every_role_is_passive_and_every_use_says_why(self):
        for f, table in AUDITED.items():
            for fields, (n, role, why) in table.items():
                with self.subTest(file=f, fields=fields):
                    self.assertIn(role, PASSIVE_ROLES)
                    self.assertGreater(len(why.split()), 1)

    def test_the_inventory_is_the_89_of_astras_audit_less_what_became_a_kind(self):
        """Astra counted 89 (any-inventory.json, the explicit constructors of the converted modules); 2b-repair-13a re-typed the fields that decide something or are shown, and added two uses of
        its own (the SDMX observation shape, the tags that are not text)."""
        total = sum(any_uses().values())
        self.assertEqual(total, 65)
        self.assertLess(total, 89)


def kind_at(spec: S.Spec, *route) -> str:
    """The kind of the node at `route` (field names, `[]` for a container's element, `|i` for a union's i-th branch), read from the schema alone."""
    while spec.kind in ("soft", "isolated", "maybe"):
        spec = spec.of
    for step in route:
        while spec.kind in ("soft", "isolated", "maybe"):
            spec = spec.of
        if step == "[]":
            spec = spec.of[1] if spec.kind == "grid" else spec.of
        elif isinstance(step, str) and step.startswith("|"):
            spec = spec.of[int(step[1:])]
        elif spec.kind == "grid":
            spec = spec.of[0]
        else:
            spec = spec.of[step]
            if spec.kind in ("matching", "deep"):   # a field the object declares by name whose value is read through containers, or by prefix: its leaf is the kind
                spec = spec.of[1]
    while spec.kind in ("soft", "isolated", "maybe"):
        spec = spec.of
    return spec.kind


class DecisionFieldsAreKinds(unittest.TestCase):
    """The fields that were `any_()` and decide something — identity, selection, an argument, a continuation, a label the caller reads — each has a concrete kind in the schema."""
    FIELDS = (
        (bea.CATALOG_DATASETS, ("BEAAPI", "Results", "Dataset", "[]", "DatasetName"), "maybe_key"), (bea.CATALOG_DATASETS, ("BEAAPI", "Results", "Dataset", "[]", "DatasetDescription"), "text"),
        (bea.CATALOG_PARAMETERS, ("BEAAPI", "Results", "Parameter", "[]", "ParameterName"), "maybe_key"), (bea.CATALOG_PARAMETERS, ("BEAAPI", "Results", "Parameter", "[]", "ParameterDescription"), "text"),
        (bea.values_schema("Frequency"), ("BEAAPI", "Results", "ParamValue", "[]", "span"), "maybe_key"),
        (bls.SURVEYS, ("Results", "survey", "[]", "survey_abbreviation"), "maybe_key"), (bls.SURVEYS, ("Results", "survey", "[]", "survey_name"), "text"),
        (bls.POPULAR, ("Results", "series", "[]", "seriesID"), "maybe_key"),
        (fred.SERIES, ("seriess", "[]", "id"), "maybe_key"),
        (fred.CATALOG, ("seriess", "[]", "id"), "maybe_key"), (fred.CATALOG, ("seriess", "[]", "title"), "text"), (fred.CATALOG, ("seriess", "[]", "units"), "text"),
        (fred.CATALOG, ("seriess", "[]", "frequency"), "text"), (fred.CATALOG, ("seriess", "[]", "observation_start"), "text"), (fred.CATALOG, ("seriess", "[]", "observation_end"), "text"),
        (govinfo.FORMATS_OF, ("packageId",), "key"), (socrata.VIEW, ("id",), "key"),
        (dv.SCHEMAS["resolve"], ("data", "latestVersion", "versionNumber"), "maybe_key"),
        (dv.SCHEMAS["resolve"], ("data", "latestVersion", "versionMinorNumber"), "maybe_key"),
        (huggingface.DATASET, ("gated",), "oneof"), (huggingface.DATASET, ("tags", "[]"), "oneof"),
        (openaire.TOKEN, ("access_token",), "text"), (openaire.TOKEN, ("expires_in",), "oneof"),
        (unpaywall.SCHEMA, ("is_oa",), "flag"), (unpaywall.SCHEMA, ("oa_status",), "text"),
        (census.TABLE, (), "grid"),
        (openml.ERROR, ("error.code",), "oneof"),
        (sdmx.DATASET, ("series", "[]", "observations", "[]"), "oneof"),
    )

    def test_each_is_a_concrete_kind_in_the_schema(self):
        for spec, route, kind in self.FIELDS:
            with self.subTest(route=route):
                self.assertEqual(kind_at(spec, *route), kind)

    def test_a_catalogues_identifiers_and_selectors_are_refused_in_every_wrong_kind_and_the_falsy_ones_are_not_silently_dropped(self):
        """Astra's 30 cases (new_family_probes.py): five operations, six corruptions of the identifier each — `true`, `false`, `[]`, `{}`, `["BAD"]`, `{"x": "BAD"}` — which returned `complete` with the
        truthy ones as identifiers and request arguments, and with the falsy ones silently removed."""
        cases = ((ops.BEA_CATALOG, ("BEAAPI", "Results", "Dataset", 0, "DatasetName")), (ops.BEA_PARAMETERS, ("BEAAPI", "Results", "Parameter", 0, "ParameterName")),
                 (ops.BLS_CATALOG, ("Results", "survey", 0, "survey_abbreviation")), (ops.BLS_POPULAR, ("Results", "series", 0, "seriesID")), (ops.FRED_CATALOG, ("seriess", 0, "id")))
        runs = 0
        for op, path in cases:
            valid_out, valid_lane = H.run(op, copy.deepcopy(corrupt_route(op).body))
            self.assertEqual(valid_lane["completeness"], "complete", op.name)
            self.assertTrue(valid_out["entries"], op.name)
            for value in (True, False, [], {}, ["BAD"], {"x": "BAD"}):
                runs += 1
                out, lane = H.run(op, H.put(corrupt_route(op).body, path, value))
                with self.subTest(op=op.name, value=repr(value)):
                    self.assertEqual((lane["coverage"], lane["completeness"], lane.get("error_class"), "count" in lane), ("provider_unavailable", "unobserved", "payload_invalid", False), lane)
                    self.assertFalse(out.get("entries"), "no candidate is returned from a catalogue that cannot be read")
        self.assertEqual(runs, 30)

    def test_readable_identifiers_still_work_and_a_row_that_names_nothing_is_still_skipped(self):
        """The accepted policy for a genuinely missing identifier is untouched (Astra: 'truthy malformed identifiers alone establish the defect')."""
        for op, path in ((ops.BEA_CATALOG, ("BEAAPI", "Results", "Dataset", 0, "DatasetName")), (ops.BLS_CATALOG, ("Results", "survey", 0, "survey_abbreviation")),
                         (ops.FRED_CATALOG, ("seriess", 0, "id"))):
            valid, _ = H.run(op, copy.deepcopy(corrupt_route(op).body))
            for nothing in (None, "", H.MISSING):
                out, lane = H.run(op, H.put(corrupt_route(op).body, path, nothing))
                with self.subTest(op=op.name, nothing=repr(nothing)):
                    self.assertEqual(lane["completeness"], "complete")
                    self.assertEqual(len(out["entries"]), len(valid["entries"]) - 1, "the row that names nothing is skipped, and the rest of the catalogue stands")

    def test_the_labels_a_caller_reads_are_text(self):
        """Astra's eight label cases and the rest of the shown fields: a boolean or a list is no label, and the catalogue that carries one is unreadable."""
        cases = ((ops.BEA_CATALOG, ("BEAAPI", "Results", "Dataset", 0, "DatasetDescription")), (ops.BEA_PARAMETERS, ("BEAAPI", "Results", "Parameter", 0, "ParameterDescription")),
                 (ops.BLS_CATALOG, ("Results", "survey", 0, "survey_name")), (ops.FRED_CATALOG, ("seriess", 0, "title")), (ops.FRED_CATALOG, ("seriess", 0, "units")),
                 (ops.FRED_CATALOG, ("seriess", 0, "frequency")))
        for op, path in cases:
            for value in (False, True, ["BAD"], {"x": "BAD"}, 0, 7):
                out, lane = H.run(op, H.put(corrupt_route(op).body, path, value))
                with self.subTest(op=op.name, path=path[-1], value=repr(value)):
                    self.assertEqual((lane["completeness"], lane.get("error_class")), ("unobserved", "payload_invalid"))
            out, lane = H.run(op, H.put(corrupt_route(op).body, path, "A label"))
            self.assertEqual(lane["completeness"], "complete", f"control: {op.name} {path[-1]} as text")

    def test_the_other_decision_fields_through_their_real_operations(self):
        for op, path, wrong in ((ops.GOVINFO_FETCH, ("packageId",), (False, 0.5, [], {}, ["x"], "", None)), (ops.SOCRATA_RESOLVE, ("id",), (False, 0.5, [], {}, ["x"], "", None))):
            for value in wrong:
                out, lane = H.run(op, H.put(corrupt_route(op).body, path, value))
                with self.subTest(op=op.name, value=repr(value)):
                    self.assertEqual((lane["completeness"], lane.get("error_class")), ("unobserved", "payload_invalid"))
        for op, path in ((ops.HF_FETCH, ("gated",)), (ops.UNPAYWALL, ("is_oa",)), (ops.UNPAYWALL, ("oa_status",))):
            for value in (7, [1], {"a": 1}):
                out, lane = H.run(op, H.put(corrupt_route(op).body, path, value))
                with self.subTest(op=op.name, path=path, value=repr(value)):
                    self.assertNotEqual(lane["completeness"], "unobserved", "metadata the caller reads says nothing when it cannot be read, and costs no member beside it")
                    self.assertEqual(lane["retrieved"], list(op.ids))

    def test_huggingface_tags_that_are_not_text_are_stored_and_never_a_licence(self):
        body = copy.deepcopy(corrupt_route(ops.HF_RESOLVE).body)
        body.pop("cardData", None)
        body["tags"] = [5, None, {"license": "x"}, "license:cc-by-4.0", ["license:mit"]]
        out, lane = H.run(ops.HF_RESOLVE, body)
        self.assertEqual(lane["completeness"], "complete")
        self.assertEqual(out["records"][0]["license"], "cc-by-4.0")
        self.assertEqual(out["records"][0]["tags"], [5, None, {"license": "x"}, "license:cc-by-4.0", ["license:mit"]], "the tags as sent, for storing")


class EnforcedByTheDecoder(unittest.TestCase):
    """Astra's required correction made enforceable: declare a decision field `any_()` and the first answer that reaches the read fails — as a lane error that names PassiveRead, never as a
    complete answer with a wrong-kind identifier in it."""

    def enforced(self, module, name: str, spec: S.Spec, op, expected_in_error="PassiveRead"):
        with mock.patch.object(module, name, spec):
            out, lane = H.run(op, copy.deepcopy(corrupt_route(op).body))
        self.assertNotEqual(lane["completeness"], "complete", lane)
        self.assertIn(expected_in_error, lane.get("error", ""), lane)
        self.assertFalse(out.get("entries"))

    def test_bea_dataset_names_declared_untyped(self):
        spec = bea._answer({"Dataset": bea._rows(S.obj({"DatasetName": S.any_(), "DatasetDescription": S.text()}))}, bea._stated("Dataset"))
        self.enforced(bea, "CATALOG_DATASETS", spec, ops.BEA_CATALOG)

    def test_bls_survey_abbreviations_declared_untyped(self):
        spec = S.obj({"Results": S.required(S.obj({"survey": S.required(S.own(S.obj({"survey_abbreviation": S.any_(), "survey_name": S.text(default="")})))}))})
        self.enforced(bls, "SURVEYS", spec, ops.BLS_CATALOG)

    def test_fred_series_ids_declared_untyped(self):
        spec = S.obj({"seriess": S.required(S.own(S.obj({"id": S.any_(), "title": S.text(), "units": S.text(), "frequency": S.text(), "observation_start": S.text(), "observation_end": S.text()})))})
        self.enforced(fred, "CATALOG", spec, ops.FRED_CATALOG)

    def test_control_the_typed_declarations_read_and_the_same_operations_are_complete(self):
        for op in (ops.BEA_CATALOG, ops.BLS_CATALOG, ops.FRED_CATALOG):
            out, lane = H.run(op, copy.deepcopy(corrupt_route(op).body))
            self.assertEqual(lane["completeness"], "complete", op.name)
            self.assertTrue(out["entries"])


if __name__ == "__main__":
    unittest.main()
