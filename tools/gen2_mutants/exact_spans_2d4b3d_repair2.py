"""Each exact-name/numeral guard has independently admitted page controls."""
from .base import Mutation

TESTS = tuple("test_store_exact_spans." + cls + ".test_" for cls in
    ("ExactSpanDDLTest", "ExtractionExactSpanDDLTest", "ValidatedExactSpanDDLTest"))
MUTATIONS, CONTROLS = [], {}


def change(name, old, new, killer):
    mid = "2D4B3DR2-" + name
    MUTATIONS.append(Mutation(mid, "2d-4b3d-repair-2", name,
        tuple(t + k for t in TESTS for k in (killer if isinstance(killer, tuple) else (killer,))),
        old=old, new=new, scope="verification_receipts_span_domain_v3"))
    CONTROLS[mid] = {"controls": [t + "exact_control" for t in TESTS],
        "why": "Separately admitted page receipts retain Unicode/NUL locator values, bibliographic access and the ordinary integer offsets under this predicate mutation."}


change("required-names", "m.parent = o.id AND m.key = r.value COLLATE BINARY", "m.parent = o.id", "required_members")
change("extra-names", "m.parent = o.id AND NOT EXISTS", "0 AND m.parent = o.id AND NOT EXISTS", ("extra_members", "split_receipt"))
change("span-names", "m.key COLLATE BINARY NOT IN ('start', 'end', 'locator')", "0", "span_names")
change("locator-names", "m.key COLLATE BINARY NOT IN ('kind', 'value')", "0", "locator_names")
change("nullable-shape", "p.nullable AND o.type IS 'null'", "p.nullable", "adjudication_shape")
change("optional-shape", "p.absent AND o.id IS NULL", "p.absent", "tier0_shape")
for key in ("start", "end"):
    change(key + "-fraction", f"name = '{key}' AND rtrim(digits, '0') <> '' AND exponent < scale",
        f"name = '{key}' AND 0 AND exponent < scale", key + "_exact")
    change(key + "-sign", f"name = '{key}' AND " + ("substr(n, 1, 1) = '-'" if key == "start" else "(substr(n, 1, 1) = '-' OR"),
        f"name = '{key}' AND " + ("0" if key == "start" else "(0 OR"), key + "_negative")
change("late-number", "FROM json_each(NEW.cited_spans) s WHERE", "FROM json_each(NEW.cited_spans) s WHERE s.key = 0 AND", "late_numeral")
change("decimal-scale", "length(mantissa) - instr(mantissa, '.')", "0", "start_exact")
change("zero-scale", "name = 'start' AND rtrim(digits, '0') <> '' AND exponent <", "name = 'start' AND 1 AND exponent <", "numeric_controls")
change("end-zero", "OR rtrim(digits, '0') = ''", "OR 0", "numeric_controls")
for label in ("json_tree_names", "json_numeral_text"):
    mid = "2D4B3DR2-compat-" + label
    MUTATIONS.append(Mutation(mid, "2d-4b3d-repair-2", "skip " + label,
        ("test_sqlite_gate.JsonCapabilityTest.test_exact_representation_probes_fail_closed",),
        target="gen2/store/compat.py", old="for name, sql, expected in JSON_PROBES:",
        new=f"for name, sql, expected in JSON_PROBES:\n        if name == '{label}': continue"))
    CONTROLS[mid] = {"controls": ["test_sqlite_gate.VersionFloorTest.test_this_interpreters_sqlite_passes"],
        "why": "An independent real SQLite connection still passes all enabled compatibility probes and reads back both connection pragmas."}
