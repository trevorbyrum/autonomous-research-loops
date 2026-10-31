"""6b2' PR 2: the material-operand digest binds scientific operands, not bookkeeping."""
from dataclasses import replace

from gen2.core import canonical
from gen2.router import material
from gen2.store.capture import RawTable, input_hash
from gen2.tests.test_completion_records import World, TOPIC

SEVEN = {"dossiers", "audit_events", "operation_receipts", "queue_entries", "leases", "artifacts", "artifact_topics"}


def table_of(raw, name):
    return next(t for t in raw.tables if t.name == name)


def replacing(raw, name, **changes):
    return replace(raw, tables=tuple(replace(t, **changes) if t.name == name else t for t in raw.tables))


def perturbed(table):
    """The group with one cell changed, or one all-text row added when it is empty."""
    if not table.rows:
        return replace(table, rows=(tuple("x" for _ in table.columns),))
    first = tuple(("x" if cell is None else cell + 1 if isinstance(cell, int) else cell + "~") for cell in table.rows[0][:1]) + table.rows[0][1:]
    return replace(table, rows=(first, *table.rows[1:]))


class DigestTest(World):
    def setUp(self):
        super().setUp()
        for kind in ("counterevidence_search", "competing_explanation", "sufficiency_review"):
            self.accepted(kind)
        self.raw = self.store.capture_topic(TOPIC)
        self.base = material.digest(self.raw, "native")

    def digest(self, raw=None, history="native"):
        return material.digest(raw or self.raw, history)

    def cell(self, name, column, value, row=0):
        table = table_of(self.raw, name)
        at = table.columns.index(column)
        rows = list(table.rows)
        rows[row] = tuple(value if i == at else c for i, c in enumerate(rows[row]))
        return replacing(self.raw, name, rows=tuple(rows))

    def test_the_exclusion_set_is_the_seven_bookkeeping_groups_and_all_exist(self):
        self.assertEqual(material.EXCLUDED, SEVEN)
        self.assertLessEqual(SEVEN, {t.name for t in self.raw.tables})

    def test_digest_is_the_versioned_hash_of_the_filtered_projection(self):
        self.assertEqual(self.base, canonical.logical_hash({"material_version": "material-operands/1", "projection": input_hash(material.project(self.raw), "native")}))
        self.assertNotEqual(self.digest(history="legacy_unknown"), self.base)

    def test_bookkeeping_is_inert(self):
        for name in sorted(SEVEN):
            self.assertEqual(self.digest(replacing(self.raw, name, rows=perturbed(table_of(self.raw, name)).rows)), self.base, name)
        queue = table_of(self.raw, "queue_entries")
        self.assertEqual(self.digest(self.cell("queue_entries", "state_revision", queue.rows[0][queue.columns.index("state_revision")] + 5)), self.base)

    def test_a_sufficiency_review_and_checkpoint_lifecycle_are_inert(self):
        records = table_of(self.raw, "completion_records")
        kind = records.columns.index("kind")
        review = next(r for r in records.rows if r[kind] == "sufficiency_review")
        added = tuple(c + "-second" if i == 0 else c for i, c in enumerate(review))
        self.assertEqual(self.digest(replacing(self.raw, "completion_records", rows=(*records.rows, added))), self.base)
        invocations = table_of(self.raw, "invocations")
        at = next(i for i, r in enumerate(invocations.rows) if r[invocations.columns.index("kind")] == "checkpoint")
        self.assertEqual(self.digest(self.cell("invocations", "state", "changed", at)), self.base)
        research = next(i for i, r in enumerate(invocations.rows) if r[invocations.columns.index("kind")] == "research_pass")
        self.assertEqual(self.digest(self.cell("invocations", "lease_id", "changed", research)), self.base)  # an excluded column
        self.assertNotEqual(self.digest(self.cell("invocations", "state", "changed", research)), self.base)

    def test_every_included_group_is_sensitive(self):
        projected = material.project(self.raw)
        self.assertGreater(len(projected.tables), 30)
        for table in projected.tables:
            self.assertNotEqual(self.digest(replacing(projected, table.name, rows=perturbed(table).rows)), self.base, table.name)

    def test_the_scientific_pin_on_a_record_is_bound(self):
        records = table_of(self.raw, "completion_records")
        self.assertNotEqual(self.digest(self.cell("completion_records", "contract_revision", records.rows[0][records.columns.index("contract_revision")] + 1)), self.base)

    def test_holds_a_delegate_and_a_research_state_change_flip_it(self):
        self.hold(self.capture_grant, "hold_judge0001")
        held = material.digest(self.store.capture_topic(TOPIC), "native")
        self.assertNotEqual(held, self.base)
        self.started("inv_delegate001", "delegate", parent=self.capture_grant)
        self.assertNotEqual(material.digest(self.store.capture_topic(TOPIC), "native"), held)

    def test_order_empties_and_new_relations_bind(self):
        records = table_of(self.raw, "completion_records")
        self.assertGreater(len(records.rows), 1)
        self.assertNotEqual(self.digest(replacing(self.raw, "completion_records", rows=records.rows[::-1])), self.base)
        emptied = replacing(self.raw, "completion_records", rows=())
        absent = replace(self.raw, tables=tuple(t for t in self.raw.tables if t.name != "completion_records"))
        self.assertNotEqual(self.digest(emptied), self.digest(absent))
        synthetic = RawTable("a_new_scientific_relation", ("id",), (), (("r1",),))
        self.assertNotEqual(self.digest(replace(self.raw, tables=(*self.raw.tables, synthetic))), self.base)  # default inclusion

    def test_the_assembled_document_carries_a_digest_that_survives_its_own_bookkeeping(self):
        recorded = self.router.record_dossier(TOPIC, invocation_id="inv_capture001", history="native")
        document = self.store.select("dossiers", {"topic_id": TOPIC, "dossier_revision": recorded["dossier_revision"]})[0]["document"]
        self.assertEqual(document["material_digest"], material.digest(self.store.capture_topic(TOPIC), "native"))
        first = self.store.select("dossiers", {"topic_id": TOPIC, "dossier_revision": 1})[0]["document"]
        self.assertNotEqual(first["material_digest"], document["material_digest"])  # three records were committed between the two assemblies
        self.assertEqual(document["material_digest"], self.base)

    def test_old_documents_without_the_member_stay_valid_and_a_malformed_member_does_not(self):
        document = self.store.select("dossiers", {"topic_id": TOPIC})[0]["document"]
        schemas = self.router._schemas
        self.assertEqual(schemas.errors(document, "dossier-v2.schema.json"), [])
        legacy = {k: v for k, v in document.items() if k != "material_digest"}
        self.assertEqual(schemas.errors(legacy, "dossier-v2.schema.json"), [])
        self.assertTrue(schemas.errors({**document, "material_digest": "sha256:short"}, "dossier-v2.schema.json"))
