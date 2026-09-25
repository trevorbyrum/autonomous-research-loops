"""Tests for gen2/core/canonical.py — RFC 8785 JCS logical hashing (Astra ruling R1).

Oracles, all independent of the code under test:
  * RFC 8785's own published examples (section 3.2.2 serialization, 3.2.3
    UTF-16 sort order, 3.2.4 UTF-8 bytes, Appendix B number table), typed
    from https://www.rfc-editor.org/rfc/rfc8785.txt;
  * the RFC development portal's published test data (byte-exact below);
  * cross-implementation vectors produced by the RFC's Appendix A
    ECMAScript canonicalizer on V8 (tools/gen2_jcs_cross_vectors.js);
  * hashlib over those expected bytes, for the digests.
What these tests cannot show: that every producer of a hashed document
calls this helper (the router boundary does, from Phase 1), or anything
about the pinned package beyond the vectors exercised.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import unittest
from decimal import Decimal
from pathlib import Path

from gen2.core import canonical
from gen2.core.canonical import CanonicalizationError, bytes_digest, canonical_bytes, content_hash, identity_integer, logical_hash, parse_json_strict, request_fingerprint

ENVELOPE_FIXTURE = Path(__file__).resolve().parents[1] / "schema" / "examples" / "commit-outcome" / "valid-final-outcome-envelope.json"


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate {key!r}")
        out[key] = value
    return out


def ecmascript_parse(text: str):
    """Parse as ECMAScript does for the vectors: one number type (double).
    (Our strict boundary parser deliberately refuses integers beyond 2**53-1
    and precision-losing literals; the vectors test the algorithm.)"""
    return json.loads(text, object_pairs_hook=_no_duplicates, parse_int=float)


# RFC 8785 section 3.2.2 input and output; 3.2.4 UTF-8 bytes of that output.
RFC_3_2_2_INPUT = '{\n  "numbers": [333333333.33333329, 1E30, 4.50,\n              2e-3, 0.000000000000000000000000001],\n  "string": "\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",\n  "literals": [null, true, false]\n}'
RFC_3_2_2_OUTPUT = '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"\u20ac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}'
RFC_3_2_4_HEX = (
    "7b 22 6c 69 74 65 72 61 6c 73 22 3a 5b 6e 75 6c 6c 2c 74 72"
    " 75 65 2c 66 61 6c 73 65 5d 2c 22 6e 75 6d 62 65 72 73 22 3a"
    " 5b 33 33 33 33 33 33 33 33 33 2e 33 33 33 33 33 33 33 2c 31"
    " 65 2b 33 30 2c 34 2e 35 2c 30 2e 30 30 32 2c 31 65 2d 32 37"
    " 5d 2c 22 73 74 72 69 6e 67 22 3a 22 e2 82 ac 24 5c 75 30 30"
    " 30 66 5c 6e 41 27 42 5c 22 5c 5c 5c 5c 5c 22 2f 22 7d"
)
# RFC 8785 section 3.2.3: property order is by UTF-16 code units.
RFC_3_2_3_INPUT = '{"\\u20ac":"Euro Sign","\\r":"Carriage Return","\\ufb33":"Hebrew Letter Dalet With Dagesh","1":"One","\\ud83d\\ude00":"Emoji: Grinning Face","\\u0080":"Control","\\u00f6":"Latin Small Letter O With Diaeresis"}'
RFC_3_2_3_ORDER = ["Carriage Return", "One", "Control", "Latin Small Letter O With Diaeresis", "Euro Sign", "Emoji: Grinning Face", "Hebrew Letter Dalet With Dagesh"]
# RFC 8785 Appendix B: IEEE 754 bits -> JSON representation ("" = must be rejected).
RFC_APPENDIX_B = (
    ("0000000000000000", "0"), ("8000000000000000", "0"), ("0000000000000001", "5e-324"), ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"), ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"), ("c340000000000000", "-9007199254740992"), ("4430000000000000", "295147905179352830000"),
    ("7fffffffffffffff", ""), ("7ff0000000000000", ""),
    ("44b52d02c7e14af5", "9.999999999999997e+22"), ("44b52d02c7e14af6", "1e+23"), ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"), ("444b1ae4d6e2ef4f", "999999999999999900000"), ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"), ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"), ("41b3de4355555554", "333333333.33333325"), ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"), ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"), ("43143ff3c1cb0959", "1424953923781206.2"),
)

# cyberphone/json-canonicalization testdata (the RFC 8785 development portal,
# Appendix I), fetched 2026-09-25 from
# https://github.com/cyberphone/json-canonicalization/tree/master/testdata;
# embedded byte-exact: (name, input text, expected output UTF-8 bytes,
# sha256[:16] of the input file, sha256[:16] of the output file).
PORTAL_VECTORS = (
    ('arrays', '[\n  56,\n  {\n    "d": true,\n    "10": null,\n    "1": [ ]\n  }\n]\n',
     b'[56,{"1":[],"10":null,"d":true}]', 'e503b6d71d1afa59', '099601b171cafed9'),
    ('french', '{\n  "peach": "This sorting order",\n  "péché": "is wrong according to French",\n  "pêche": "but canonicalization MUST",\n  "sin":   "ignore locale"\n}\n',
     b'{"peach":"This sorting order","p\xc3\xa9ch\xc3\xa9":"is wrong according to French","p\xc3\xaache":"but canonicalization MUST","sin":"ignore locale"}', '03676a951cd8753a', 'd99d0ebdcb0033cb'),
    ('structures', '{\n  "1": {"f": {"f": "hi","F": 5} ,"\\n": 56.0},\n  "10": { },\n  "": "empty",\n  "a": { },\n  "111": [ {"e": "yes","E": "no" } ],\n  "A": { }\n}',
     b'{"":"empty","1":{"\\n":56,"f":{"F":5,"f":"hi"}},"10":{},"111":[{"E":"no","e":"yes"}],"A":{},"a":{}}', 'd66893805be17841', '605f65004ec2db76'),
    ('unicode', '{\n  "Unnormalized Unicode":"A\\u030a"\n}\n',
     b'{"Unnormalized Unicode":"A\xcc\x8a"}', '4621864e014d4a80', '0d99aad92a125196'),
    ('values', '{\n  "numbers": [333333333.33333329, 1E30, 4.50, 2e-3, 0.000000000000000000000000001],\n  "string": "\\u20ac$\\u000F\\u000aA\'\\u0042\\u0022\\u005c\\\\\\"\\/",\n  "literals": [null, true, false]\n}',
     b'{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"\xe2\x82\xac$\\u000f\\nA\'B\\"\\\\\\\\\\"/"}', 'c4a041b503d6bc23', '2d5e01a318d0f087'),
    ('weird', '{\n  "\\u20ac": "Euro Sign",\n  "\\r": "Carriage Return",\n  "\\u000a": "Newline",\n  "1": "One",\n  "\\u0080": "Control\\u007f",\n  "\\ud83d\\ude02": "Smiley",\n  "\\u00f6": "Latin Small Letter O With Diaeresis",\n  "\\ufb33": "Hebrew Letter Dalet With Dagesh",\n  "</script>": "Browser Challenge"\n}\n',
     b'{"\\n":"Newline","\\r":"Carriage Return","1":"One","</script>":"Browser Challenge","\xc2\x80":"Control\x7f","\xc3\xb6":"Latin Small Letter O With Diaeresis","\xe2\x82\xac":"Euro Sign","\xf0\x9f\x98\x82":"Smiley","\xef\xac\xb3":"Hebrew Letter Dalet With Dagesh"}', 'a3a905266bd4a49a', '6af595a9aa80110b'),
)

# Cross-implementation vectors: RFC 8785 Appendix A (ECMAScript) run on V8,
# `node tools/gen2_jcs_cross_vectors.js` (node v22.23.2), inputs chosen for the
# ruling's edge cases: negative zero, fractional/exponent numbers, UTF-16 key
# order (surrogate pairs above U+FB33), escapes, contract-style fractions,
# decision probabilities, integer bounds, and two envelopes differing only in
# lease generation. (input JSON text, expected UTF-8 bytes as hex).
CROSS_VECTORS = (
    ('{"b":-0,"a":0.0,"c":-0.0,"d":[-0,0]}',
     '7b2261223a302c2262223a302c2263223a302c2264223a5b302c305d7d'),
    ('[1.5e300,1e-7,1e-6,0.000001,123456789012345680000,1e21,1e+21,5e-324,-5e-324,0.1,0.2,0.30000000000000004,100,1.0,12.3456e2,1E3,2.5E-5,-1.25e-10]',
     '5b312e35652b3330302c31652d372c302e3030303030312c302e3030303030312c3132333435363738393031323334353638303030302c31652b32312c31652b32312c35652d3332342c2d35652d3332342c302e312c302e322c302e33303030303030303030303030303030342c3130302c312c313233342e35362c313030302c302e3030303032352c2d312e3235652d31305d'),
    ('{"\\u00e9":1,"e":2,"Z":3,"\\ud83d\\ude00":4,"\\ufb33":5,"\\u0080":6,"a":7,"":8,"\\u20ac":9,"aa":10,"A":11}',
     '7b22223a382c2241223a31312c225a223a332c2261223a372c226161223a31302c2265223a322c22c280223a362c22c3a9223a312c22e282ac223a392c22f09f9880223a342c22efacb3223a357d'),
    ('["\\u0000\\u001f\\u007f\\u2028\\u2029\\t\\b\\f\\n\\r","\\"\\\\/","\\ud834\\udd1e"]',
     '5b225c75303030305c75303031667fe280a8e280a95c745c625c665c6e5c72222c225c225c5c2f222c22f09d849e225d'),
    ('{"z":[{"b":[],"a":{}}],"a":[3,2,1],"m":{"y":null,"x":true,"w":false}}',
     '7b2261223a5b332c322c315d2c226d223a7b2277223a66616c73652c2278223a747275652c2279223a6e756c6c7d2c227a223a5b7b2261223a7b7d2c2262223a5b5d7d5d7d'),
    ('{"stopping":{"target_recall":0.95,"threshold":0.8,"p":0.123456789,"alpha":0.05}}',
     '7b2273746f7070696e67223a7b22616c706861223a302e30352c2270223a302e3132333435363738392c227461726765745f726563616c6c223a302e39352c227468726573686f6c64223a302e387d7d'),
    ('{"answer":{"primitive":"choice","selected_option_id":"include","distribution":{"include":0.8,"exclude":0.2},"confidence":0.7}}',
     '7b22616e73776572223a7b22636f6e666964656e6365223a302e372c22646973747269627574696f6e223a7b226578636c756465223a302e322c22696e636c756465223a302e387d2c227072696d6974697665223a2263686f696365222c2273656c65637465645f6f7074696f6e5f6964223a22696e636c756465227d7d'),
    ('[9007199254740991,-9007199254740991,0,-1,1,4294967296]',
     '5b393030373139393235343734303939312c2d393030373139393235343734303939312c302c2d312c312c343239343936373239365d'),
    ('{"envelope_version":"commit-outcome/1","operation_id":"op_01J8ZQ4K7M","lease":{"lease_id":"lease_01J8ZQ3V9T","generation":7},"expected_state_revision":41}',
     '7b22656e76656c6f70655f76657273696f6e223a22636f6d6d69742d6f7574636f6d652f31222c2265787065637465645f73746174655f7265766973696f6e223a34312c226c65617365223a7b2267656e65726174696f6e223a372c226c656173655f6964223a226c656173655f30314a385a5133563954227d2c226f7065726174696f6e5f6964223a226f705f30314a385a51344b374d227d'),
    ('{"envelope_version":"commit-outcome/1","operation_id":"op_01J8ZQ4K7M","lease":{"lease_id":"lease_01J8ZQ3V9T","generation":8},"expected_state_revision":41}',
     '7b22656e76656c6f70655f76657273696f6e223a22636f6d6d69742d6f7574636f6d652f31222c2265787065637465645f73746174655f7265766973696f6e223a34312c226c65617365223a7b2267656e65726174696f6e223a382c226c656173655f6964223a226c656173655f30314a385a5133563954227d2c226f7065726174696f6e5f6964223a226f705f30314a385a51344b374d227d'),
)


def sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class PublishedVectorsTest(unittest.TestCase):
    def test_rfc_3_2_2_serialization_and_3_2_4_utf8_bytes(self) -> None:
        out = canonical_bytes(ecmascript_parse(RFC_3_2_2_INPUT))
        self.assertEqual(out, RFC_3_2_2_OUTPUT.encode("utf-8"))
        self.assertEqual(out, bytes.fromhex(RFC_3_2_4_HEX.replace(" ", "")))
        self.assertEqual(logical_hash(ecmascript_parse(RFC_3_2_2_INPUT)), sha(bytes.fromhex(RFC_3_2_4_HEX.replace(" ", ""))))

    def test_rfc_3_2_3_utf16_property_order(self) -> None:
        values = list(json.loads(canonical_bytes(ecmascript_parse(RFC_3_2_3_INPUT)).decode("utf-8")).values())
        self.assertEqual(values, RFC_3_2_3_ORDER)

    def test_rfc_appendix_b_number_serialization(self) -> None:
        for bits, expected in RFC_APPENDIX_B:
            with self.subTest(bits=bits):
                value = struct.unpack(">d", bytes.fromhex(bits))[0]
                if expected:
                    self.assertEqual(canonical_bytes(value), expected.encode("ascii"))
                else:
                    self.assertFalse(math.isfinite(value))
                    self.assertRaises(CanonicalizationError, canonical_bytes, value)

    def test_development_portal_vectors(self) -> None:
        for name, text, expected, _in_sha, _out_sha in PORTAL_VECTORS:
            with self.subTest(vector=name):
                self.assertEqual(canonical_bytes(ecmascript_parse(text)), expected)

    def test_cross_implementation_vectors(self) -> None:
        for text, expected_hex in CROSS_VECTORS:
            with self.subTest(input=text[:60]):
                self.assertEqual(canonical_bytes(ecmascript_parse(text)).hex(), expected_hex)

    def test_negative_zero_and_python_json_dumps_is_not_jcs(self) -> None:
        self.assertEqual(canonical_bytes({"z": -0.0}), b'{"z":0}')
        # json.dumps(sort_keys=True) differs from JCS on numbers and on non-ASCII key order
        value = ecmascript_parse(RFC_3_2_3_INPUT)
        self.assertNotEqual(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"), canonical_bytes(value))
        self.assertEqual((json.dumps(1e-06), json.dumps(1e16)), ("1e-06", "1e+16"))  # Python's repr
        self.assertEqual((canonical_bytes(1e-06), canonical_bytes(1e16)), (b"0.000001", b"10000000000000000"))  # ECMAScript / JCS


class StrictBoundaryTest(unittest.TestCase):
    """Ruling R1: reject duplicate keys, non-finite numbers, invalid Unicode and
    unsupported numeric precision before hashing; bound integers."""

    def test_parse_rejects(self) -> None:
        for text in ('{"a":1,"a":2}', '{"x":{"a":1,"a":1}}', 'NaN', '[Infinity]', '{"v":-Infinity}', '"\\ud800"', '{"\\udfff":1}',
                     '12345678901234567890', '-9007199254740992', '0.1000000000000000055511151231257827', '333333333.33333329',
                     '1e400', '{"a":1} x', "{'a':1}", '',
                     '1e-400', '-1e-400', '[2.4e-324]'):  # underflow: the double would be 0.0, a value the text never named
            with self.subTest(text=text):
                self.assertRaises(CanonicalizationError, parse_json_strict, text)

    def test_parse_accepts_exact_values(self) -> None:
        for text, value in (('0.1', 0.1), ('4.50', 4.5), ('1E30', 1e30), ('9007199254740991', 9007199254740991), ('-0', 0), ('{"a":[true,null]}', {"a": [True, None]}),
                            ('5e-324', 5e-324)):  # the smallest subnormal is a real, exact double
            with self.subTest(text=text):
                self.assertEqual(parse_json_strict(text), value)

    def test_parse_decodes_bytes_as_utf8(self) -> None:
        """Byte input is UTF-8 (RFC 8259 §8.1), non-ASCII included."""
        for raw, value in (('"é"'.encode("utf-8"), "é"), ('{"k":"€ ☃"}'.encode("utf-8"), {"k": "€ ☃"}), (b'"\xf0\x9f\x98\x80"', "\U0001F600")):
            with self.subTest(raw=raw):
                try:
                    parsed = parse_json_strict(raw)
                except CanonicalizationError as exc:  # a refusal here is the defect under test, so report it as a failure
                    self.fail(f"valid UTF-8 JSON bytes refused: {exc}")
                self.assertEqual(parsed, value)
        self.assertRaises(CanonicalizationError, parse_json_strict, b'"\xff"')  # not UTF-8

    # bound - 1, bound, bound + 1 (bound = 2**53 - 1), each in integer, decimal and exponent notation
    IDENTITY_NOTATIONS = {
        9007199254740990: ("9007199254740990", "9007199254740990.0", "9.00719925474099e15"),
        9007199254740991: ("9007199254740991", "9007199254740991.0", "9.007199254740991e15"),
        9007199254740992: ("9007199254740992", "9007199254740992.0", "9007199254740992e0"),
    }

    def test_identity_bound_holds_by_value_in_every_notation(self) -> None:
        """RA8: '9007199254740992' was refused but '9007199254740992.0' and
        '9007199254740992e0' parsed and canonicalized to the same value. An
        identity/revision/generation field is now bounded by VALUE — whatever
        the notation and whichever type the parser produced: bound - 1 and
        bound pass as ints in all three notations; bound + 1 is refused in all
        three (the bare integer by the parser, the others by the bound)."""
        def identity_from(text: str) -> int:
            return identity_integer(parse_json_strict(text))
        for value in (9007199254740990, 9007199254740991):
            for text in self.IDENTITY_NOTATIONS[value]:
                with self.subTest(text=text):
                    self.assertEqual(identity_from(text), value)
                    self.assertIs(type(identity_from(text)), int)
        for text in self.IDENTITY_NOTATIONS[9007199254740992]:
            with self.subTest(text=text):
                self.assertRaises(CanonicalizationError, identity_from, text)
        for value in (2**53, 2.0**53, -1, -1.0, 1.5, float("inf"), float("nan"), True, "7", None):
            with self.subTest(value=repr(value)):
                self.assertRaises(CanonicalizationError, identity_integer, value)
        self.assertEqual(identity_integer(0), 0)
        self.assertRaises(CanonicalizationError, identity_integer, 0, minimum=1)  # revisions start at 1

    def test_large_numbers_stay_legitimate_outside_identity_fields(self) -> None:
        """RA8 without breaking JCS: outside identity fields a large integral
        double is an ordinary binary64 number (RFC 8785 Appendix B serializes
        2**53 as 9007199254740992), so the parser accepts it in decimal or
        exponent notation and JCS serializes it."""
        for text in ("9007199254740992.0", "9007199254740992e0", "1E30"):
            with self.subTest(text=text):
                value = parse_json_strict(text)
                self.assertIsInstance(value, float)
        self.assertEqual(canonical_bytes(parse_json_strict("9007199254740992.0")), b"9007199254740992")
        self.assertEqual(canonical_bytes(parse_json_strict("1E30")), b"1e+30")

    def test_value_rejects(self) -> None:
        for value in (float("nan"), float("inf"), 2**53, -(2**53), {1: "a"}, {"a": {2.0: "b"}}, {"s": "\ud800"}, b"bytes", {"x"}, Decimal("0.1"), object()):
            with self.subTest(value=repr(value)[:40]):
                self.assertRaises(CanonicalizationError, canonical_bytes, value)


class HashSemanticsTest(unittest.TestCase):
    def envelope(self) -> dict:
        return json.loads(ENVELOPE_FIXTURE.read_text(encoding="utf-8"))["instance"]

    def test_contract_versions_are_declared(self) -> None:
        self.assertEqual(canonical.CANONICALIZATION, "jcs-rfc8785/1")
        self.assertEqual(canonical.FINGERPRINT_CONTRACT, "commit-fingerprint/1")
        self.assertEqual(canonical.FINGERPRINT_EXCLUDES, ("submitted_at",))
        self.assertEqual(canonical.CONTENT_HASH_EXCLUDES, ("content_hash",))

    def test_content_hash_excludes_exactly_itself(self) -> None:
        doc = {"schema_version": "contract-v2", "revision": 3, "stopping": {"target_recall": 0.95}, "content_hash": "sha256:" + "0" * 64}
        expected = sha(b'{"revision":3,"schema_version":"contract-v2","stopping":{"target_recall":0.95}}')
        self.assertEqual(content_hash(doc), expected)
        self.assertEqual(content_hash(dict(doc, content_hash="anything")), expected)
        self.assertEqual(content_hash(parse_json_strict('{ "stopping" : {"target_recall":0.950}, "revision":3, "schema_version":"contract-v2"}')), expected)
        for key, value in (("revision", 4), ("stopping", {"target_recall": 0.9}), ("schema_version", "contract-v3")):
            with self.subTest(changed=key):
                self.assertNotEqual(content_hash(dict(doc, **{key: value})), expected)

    def test_request_fingerprint_excludes_exactly_submitted_at(self) -> None:
        env = self.envelope()
        base = request_fingerprint(env)
        without = {k: v for k, v in env.items() if k != "submitted_at"}
        self.assertEqual(base, sha(canonical_bytes(without)))
        self.assertEqual(request_fingerprint(dict(env, submitted_at="2026-09-26T00:00:00Z")), base)
        self.assertEqual(request_fingerprint(dict(reversed(list(env.items())))), base)

    def test_semantically_changed_envelopes_fingerprint_differently(self) -> None:
        env = self.envelope()
        base = request_fingerprint(env)
        changes = {
            "operation_id": "op_01J8ZQ4K7N", "operation_kind": "interim_transition", "invocation_id": "inv_01J8ZQ3W2Y",
            "capability_id": "cap_01J8ZQ3W2Y", "topic_id": "fleet-a:other-topic", "config_bundle_hash": "sha256:" + "0" * 64,
            "lease": dict(env["lease"], generation=env["lease"]["generation"] + 1), "expected_state_revision": env["expected_state_revision"] + 1,
            "payload_digest": "sha256:" + "0" * 64, "payload_size_bytes": env["payload_size_bytes"] + 1, "result_refs": [],
            "admission": dict(env["admission"], contract=dict(env["admission"]["contract"], revision=env["admission"]["contract"]["revision"] + 1)),
            "envelope_version": "commit-outcome/2",
        }
        for key, value in changes.items():
            with self.subTest(field=key):
                self.assertNotEqual(request_fingerprint(dict(env, **{key: value})), base)

    def test_raw_bytes_are_hashed_raw_never_canonicalized(self) -> None:
        raw_a = b'{"b": 1, "a": 2.50}'
        raw_b = b'{"a":2.5,"b":1}'
        self.assertEqual(bytes_digest(raw_a), sha(raw_a))
        self.assertNotEqual(bytes_digest(raw_a), bytes_digest(raw_b))  # different retained bytes
        self.assertEqual(logical_hash(parse_json_strict(raw_a)), logical_hash(parse_json_strict(raw_b)))  # same logical value
        self.assertNotEqual(bytes_digest(raw_a), logical_hash(parse_json_strict(raw_a)))
        self.assertEqual(bytes_digest(b"not json at all \xff"), sha(b"not json at all \xff"))
        self.assertRaises(TypeError, bytes_digest, raw_a.decode())
        # leading/trailing bytes are retained bytes too (whitespace, newline, BOM)
        for raw in (b" x\n", b"\n{\"a\":1}\n", b"\xef\xbb\xbf{}", b"\t"):
            with self.subTest(raw=raw):
                self.assertEqual(bytes_digest(raw), sha(raw))
        self.assertNotEqual(bytes_digest(b" x\n"), sha(b"x"))


if __name__ == "__main__":
    unittest.main()
