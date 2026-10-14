"""Registry predicates paired with independently accepted registered controls."""
from .base import Mutation

MUTATIONS, CONTROLS = [], {}
RAW = "test_store_extractor_registry.RegistryDDLTest."
EXTRACTION = "test_store_extractor_registry.RegistryExtractionDDLTest."
ROUTER = "test_extractor_registry.RegistryTest."


def change(name, killer, old=None, new="1 = 1", scope=None, test=RAW, target="ddl", drop_trigger=None, control="test_control", why=None):
    mid = "2D4B3E2-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3e2", name, (test + "test_" + killer,),
        old=old, new=new, scope=scope, target=target, drop_trigger=drop_trigger))
    CONTROLS[mid] = {"controls": [control if "." in control else test + control],
        "why": why or "An independent accepted registry/extraction control binds the exact approved snapshot; SQL 17 remains fenced."}


for name, predicate in (
        ("kind", "a.kind = 'extractor_registry_registered'"), ("topic", "a.topic_id IS NULL"),
        ("invocation", "a.invocation_id IS NULL"), ("operation", "a.operation_id IS NULL"),
        ("time", "a.at = NEW.created_at"), ("revision", "json_extract(a.detail, '$.registry_version') = NEW.registry_version"),
        ("operator", "json_extract(a.detail, '$.operator_id') = NEW.operator_id"),
        ("reason", "json_extract(a.detail, '$.reason') = NEW.reason")):
    change("audit-" + name, "authority", predicate, scope="extractor_registry_authority")
for name, predicate, killer in (
        ("revision", "r.registry_version = NEW.registry_version", "mapping_revision"),
        ("identity", "json_extract(t.value, '$.extractor_identity') = NEW.extractor_identity", "mapping"),
        ("family", "json_extract(t.value, '$.family') = NEW.family", "mapping")):
    change("mapping-" + name, killer, predicate, scope="extractor_tools_authority")
change("audit-reference", "audit_reference", "a.audit_event_id = NEW.audit_event_id", scope="extractor_registry_authority")
change("mapping-audit", "mapping_revision", "JOIN audit_events a USING (audit_event_id)", "JOIN audit_events a ON 1 = 1", "extractor_tools_authority")
change("revision-order", "order", drop_trigger="extractor_registry_order")
change("revision-domain", "revision_domain", "CHECK (registry_version BETWEEN 1 AND 9007199254740991)", "CHECK (1)", "extractor_registry_revisions")
for field in ("operator_id", "reason"):
    change("revision-" + field, "revision_domain", f"CHECK (length({field}) > 0)", "CHECK (1)", "extractor_registry_revisions")
for field in ("extractor_identity", "family"):
    for name, predicate in (("length", f"length({field}) BETWEEN 1 AND 100"), ("initial", f"{field} GLOB '[a-z]*'"),
            ("alphabet", f"{field} NOT GLOB '*[^a-z0-9._-]*'"), ("nul", f"instr(CAST({field} AS BLOB), X'00') = 0")):
        change(field + "-" + name, "names", predicate, scope="extractor_tools")
for table, prefix in (("extractor_registry", "extractor_registry"), ("extractor_tools", "extractor_tools")):
    for suffix in ("u", "d"):
        change(table + "-" + suffix, "immutable", drop_trigger=prefix + "_immutable_" + suffix)
change("extraction-identity", "registry_membership", "t.extractor_identity = NEW.extractor_identity", scope="source_extractions_registered_tool", test=EXTRACTION)
change("extraction-revision", "registry_revision", "t.registry_version = NEW.extractor_registry_version", scope="source_extractions_registered_tool", test=EXTRACTION)
change("router-membership", "membership", "is None:", "is None and False:", test=ROUTER, target="gen2/router/extractor_registry.py",
    why="Commits a registered extraction through require_tool's exact membership guard and reads back its identity and revision; the weakened guard still accepts it.")
change("router-replay", "registration", 'audit["detail"] != doc', "False", test=ROUTER, target="gen2/router/extractor_registry.py",
    control="test_registration_replay_control",
    why="Registers then identically replays revision 2 through _write's audit-detail comparison, with all-table unchanged-state readback including audit; the weakened comparison still accepts it.")
change("router-duplicates", "duplicates", 'len({t["extractor_identity"] for t in tools}) != len(tools)', "False", test=ROUTER, target="gen2/router/extractor_registry.py")
change("router-admission-wiring", "membership", "self._core._require_extractor_tool(record)", "pass", test=ROUTER, target="gen2/router/extractions.py")
for column in ("registry_version", "extractor_registry_version"):
    change(column + "-classification", "every_integer_column_is_classified_once", f'"{column}",', "",
        test="test_writer.IdentityBoundTest.", target="gen2/store/api.py",
        control=ROUTER + ("test_registration_replay_control" if column == "registry_version" else "test_control"),
        why=f"Writes an integer {column} through Store._prepare, which reads IDENTITY_COLUMNS for that column, with committed readback; the ordinary integer remains accepted when its identity classification is removed.")
