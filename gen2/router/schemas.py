"""JSON Schema validation at the router boundary (task 1b).

Trace: gen2/store/README.md "What stays router logic" (consistency of the JSON
documents beyond their bound fields is validated against gen2/schema/ at the
router boundary; timestamps are validated there as real instants, A11);
EXPORT-API.md §5 (every manifest is validated against export-manifest/2
before outbox admission); INVARIANTS C-2.

Why a validator here rather than the `jsonschema` package: that package is a
dev-only dependency (gen2/requirements-dev.txt) granted to no module, and
granting a third-party package is a boundary amendment (gen2/boundaries.toml).
This module implements exactly the Draft 2020-12 keywords the schemas in
gen2/schema/ use, and refuses to load a schema that uses anything else (fail
closed: an unimplemented keyword would otherwise validate silently). The
pinned `jsonschema` stays the independent oracle:
gen2/tests/test_router_schemas.py checks that both give the same verdict on
every committed fixture and on mutated instances.

Deliberate differences, both stricter than the oracle and both tested:
  * `pattern` is read as ECMA-262 (the dialect JSON Schema names): `$` at the
    end matches only at the end of the string (Python's `$` also matches
    before a trailing newline, so "inv_abcdefgh\\n" would pass
    ^inv_[A-Za-z0-9_-]{8,64}$), and \\d \\w are ASCII (re.ASCII);
  * `format: date-time` is always asserted, with gen2/core/instants.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from gen2.core import instants

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schema"
ID_BASE = "https://research-loops.invalid/gen2/schema/"
ANNOTATIONS = frozenset({"$schema", "$id", "$comment", "$defs", "title", "description"})
SCHEMA_VALUED = ("items", "additionalProperties", "propertyNames", "contains", "not", "if", "then", "else")
SCHEMA_LISTS = ("allOf", "anyOf", "oneOf")
SCHEMA_MAPS = ("properties", "$defs")
DATA_VALUED = ("const", "enum", "type", "required", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
               "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "minContains", "maxContains",
               "minProperties", "maxProperties", "pattern", "format", "$ref")
KEYWORDS = ANNOTATIONS | set(SCHEMA_VALUED) | set(SCHEMA_LISTS) | set(SCHEMA_MAPS) | set(DATA_VALUED)
TYPES = ("null", "boolean", "object", "array", "string", "number", "integer")


class SchemaError(ValueError):
    """A schema this validator cannot evaluate faithfully (refused at load)."""


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_type(value: object, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "number":
        return _is_number(value)
    return _is_number(value) and (isinstance(value, int) or value.is_integer())  # 2020-12: 1.0 is an integer


def json_equal(a: object, b: object) -> bool:
    """JSON value equality: 1 == 1.0, but true is not 1."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _frozen(value: object) -> object:
    """A hashable key equal exactly when the JSON values are (json_equal):
    1 and 1.0 hash and compare equal in Python; true is tagged apart from 1."""
    if isinstance(value, bool) or value is None:
        return ("literal", value)
    if isinstance(value, dict):
        return ("object", frozenset((k, _frozen(v)) for k, v in value.items()))
    if isinstance(value, list):
        return ("array", tuple(_frozen(v) for v in value))
    return ("number" if _is_number(value) else "string", value)


def _ecma(pattern: str) -> re.Pattern:
    body = pattern[:-1] + r"\Z" if pattern.endswith("$") and not pattern.endswith("\\$") else pattern
    if re.search(r"(?<!\\)\$", body):
        raise SchemaError(f"pattern {pattern!r}: `$` is supported only at the end")
    return re.compile(body, re.ASCII)


class SchemaSet:
    """Every gen2/schema/*.schema.json (plus router command schemas passed as
    `extra`, keyed by a name their `$ref`s use), audited once at load."""

    def __init__(self, directory: Path = SCHEMA_DIR, extra: dict[str, dict] | None = None) -> None:
        self._docs: dict[str, dict] = {}
        for path in sorted(Path(directory).glob("*.schema.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            if doc.get("$id") != ID_BASE + path.name:
                raise SchemaError(f"{path.name}: $id is not {ID_BASE + path.name}")
            self._docs[path.name] = doc
        self._docs.update(extra or {})
        self._patterns: dict[str, re.Pattern] = {}
        for name, doc in self._docs.items():
            self._audit(doc, name, "")

    def _audit(self, node: object, name: str, where: str) -> None:
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            raise SchemaError(f"{name}{where}: a schema is an object or a boolean")
        for key, value in node.items():
            if key not in KEYWORDS:
                raise SchemaError(f"{name}{where}: keyword {key!r} is not implemented here (fail closed)")
            if key in SCHEMA_VALUED:
                self._audit(value, name, f"{where}/{key}")
            elif key in SCHEMA_LISTS:
                for index, sub in enumerate(value):
                    self._audit(sub, name, f"{where}/{key}/{index}")
            elif key in SCHEMA_MAPS:
                for sub_key, sub in value.items():
                    self._audit(sub, name, f"{where}/{key}/{sub_key}")
            elif key == "$ref":
                self._resolve_ref(value, name)
            elif key == "pattern":
                self._patterns.setdefault(value, _ecma(value))
            elif key == "format" and value != "date-time":
                raise SchemaError(f"{name}{where}: format {value!r} is not implemented here")
            elif key == "type" and any(t not in TYPES for t in ([value] if isinstance(value, str) else value)):
                raise SchemaError(f"{name}{where}: unknown type {value!r}")

    def _resolve_ref(self, ref: str, base: str) -> tuple[str, object]:
        target, _, fragment = ref.partition("#")
        name = target or base
        if name not in self._docs:
            raise SchemaError(f"$ref {ref!r} from {base}: unknown schema {name!r}")
        node: object = self._docs[name]
        if fragment:
            if not fragment.startswith("/"):
                raise SchemaError(f"$ref {ref!r}: only JSON-pointer fragments are supported")
            for token in fragment[1:].split("/"):
                token = token.replace("~1", "/").replace("~0", "~")
                if not isinstance(node, dict) or token not in node:
                    raise SchemaError(f"$ref {ref!r} from {base} does not resolve")
                node = node[token]
        return name, node

    def errors(self, instance: object, target: str) -> list[str]:
        """Every violation of `target` ("name.schema.json" or
        "name.schema.json#/pointer") by `instance`, a parsed JSON value.
        Empty means valid."""
        name, schema = self._resolve_ref(target, target.partition("#")[0])
        out: list[str] = []
        self._check(instance, schema, name, "", out)
        return out

    def is_valid(self, instance: object, schema: object, base: str) -> bool:
        out: list[str] = []
        self._check(instance, schema, base, "", out)
        return not out

    def _check(self, value: object, schema: object, base: str, path: str, out: list[str]) -> None:
        if schema is True:
            return
        if schema is False:
            out.append(f"{path or '/'}: no value is allowed here")
            return
        assert isinstance(schema, dict)
        where = path or "/"
        if "$ref" in schema:
            ref_base, target = self._resolve_ref(schema["$ref"], base)
            self._check(value, target, ref_base, path, out)
        if "type" in schema:
            names = [schema["type"]] if isinstance(schema["type"], str) else schema["type"]
            if not any(_is_type(value, t) for t in names):
                out.append(f"{where}: type is not {names}")
        if "const" in schema and not json_equal(value, schema["const"]):
            out.append(f"{where}: not the constant {schema['const']!r}")
        if "enum" in schema and not any(json_equal(value, option) for option in schema["enum"]):
            out.append(f"{where}: not one of {schema['enum']!r}")
        if _is_number(value):
            self._number(value, schema, where, out)
        elif isinstance(value, str):
            self._string(value, schema, where, out)
        elif isinstance(value, list):
            self._array(value, schema, base, path, out)
        elif isinstance(value, dict):
            self._object(value, schema, base, path, out)
        for sub in schema.get("allOf", ()):
            self._check(value, sub, base, path, out)
        if "anyOf" in schema and not any(self.is_valid(value, sub, base) for sub in schema["anyOf"]):
            out.append(f"{where}: matches none of anyOf")
        if "oneOf" in schema:
            matched = sum(self.is_valid(value, sub, base) for sub in schema["oneOf"])
            if matched != 1:
                out.append(f"{where}: matches {matched} of oneOf, not exactly one")
        if "not" in schema and self.is_valid(value, schema["not"], base):
            out.append(f"{where}: matches a `not` schema")
        if "if" in schema:
            branch = "then" if self.is_valid(value, schema["if"], base) else "else"
            if branch in schema:
                self._check(value, schema[branch], base, path, out)

    @staticmethod
    def _number(value: float, schema: dict, where: str, out: list[str]) -> None:
        for key, fails in (("minimum", lambda b: value < b), ("maximum", lambda b: value > b),
                           ("exclusiveMinimum", lambda b: value <= b), ("exclusiveMaximum", lambda b: value >= b)):
            if key in schema and fails(schema[key]):
                out.append(f"{where}: {key} {schema[key]} violated by {value}")

    def _string(self, value: str, schema: dict, where: str, out: list[str]) -> None:
        if "minLength" in schema and len(value) < schema["minLength"]:
            out.append(f"{where}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{where}: longer than {schema['maxLength']}")
        if "pattern" in schema and not self._patterns[schema["pattern"]].search(value):
            out.append(f"{where}: does not match {schema['pattern']!r}")
        if schema.get("format") == "date-time" and not instants.is_utc_instant(value):
            out.append(f"{where}: not a real RFC 3339 UTC instant")

    def _array(self, value: list, schema: dict, base: str, path: str, out: list[str]) -> None:
        where = path or "/"
        if "minItems" in schema and len(value) < schema["minItems"]:
            out.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{where}: more than {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            seen = set()
            for item in value:
                key = _frozen(item)
                if key in seen:
                    out.append(f"{where}: items are not unique")
                    break
                seen.add(key)
        if "items" in schema:
            for index, item in enumerate(value):
                self._check(item, schema["items"], base, f"{path}/{index}", out)
        if "contains" in schema:
            found = sum(self.is_valid(item, schema["contains"], base) for item in value)
            if found < schema.get("minContains", 1):
                out.append(f"{where}: fewer than {schema.get('minContains', 1)} items match `contains`")
            if "maxContains" in schema and found > schema["maxContains"]:
                out.append(f"{where}: more than {schema['maxContains']} items match `contains`")

    def _object(self, value: dict, schema: dict, base: str, path: str, out: list[str]) -> None:
        where = path or "/"
        for key in schema.get("required", ()):
            if key not in value:
                out.append(f"{where}: missing required {key!r}")
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            out.append(f"{where}: fewer than {schema['minProperties']} properties")
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            out.append(f"{where}: more than {schema['maxProperties']} properties")
        properties = schema.get("properties", {})
        for key, item in value.items():
            child = f"{path}/{key}"
            if key in properties:
                self._check(item, properties[key], base, child, out)
            elif "additionalProperties" in schema:
                self._check(item, schema["additionalProperties"], base, child, out)
            if "propertyNames" in schema:
                self._check(key, schema["propertyNames"], base, child, out)
