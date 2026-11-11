"""LR-3: byte integrity over carried operands; no file reads or qualification authority.
Own pending-record/receipt values exercise packing, not a simulated external CLI.
"""
import json
import unittest

from deploy.gen2.live import operands
from gen2.core import canonical


class Operands(unittest.TestCase):
    def test_exact_pins_pending_state_and_single_operand_staleness(self):
        manifest, receipt = b'{ "route": "fixture", "qualification_state": "unqualified" }\n', b'{"passed":false,"reason":"not_run"}\n'
        ref = canonical.bytes_digest(receipt)
        record = dict(record_version="qualification-record/1", state="unqualified", route="fixture",
                      manifest_pin=canonical.bytes_digest(manifest), witnesses=[dict(name="Q1", passed=False, receipt=ref)], plan={})
        view = dict(record=record, manifest=manifest, receipts={ref: receipt})
        data, pin = operands.pack(view)
        self.assertEqual(json.loads(data), record)
        self.assertEqual(pin, canonical.bytes_digest(data))
        self.assertEqual(data, canonical.canonical_bytes(record))
        for change in (dict(manifest=manifest + b" "), dict(receipts={ref: receipt + b" "})):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "stale"):
                operands.pack(view | change)

    def test_real_record_carries_exact_relay_only_provider_files(self):
        manifest = b'{"route":"real"}'
        record = dict(route="real", manifest_pin=canonical.bytes_digest(manifest), witnesses=[], plan=dict(operands.PROVIDER_FILES))
        view = dict(record=record, manifest=manifest, receipts={})
        data, _ = operands.pack(view)
        self.assertEqual(json.loads(data)["plan"], operands.PROVIDER_FILES)
        for key in operands.PROVIDER_FILES:
            for replacement in (None, "/tmp/unreviewed"):
                with self.subTest(key=key, replacement=replacement), self.assertRaisesRegex(ValueError, "provider file operand"):
                    operands.pack(view | {"record": record | {"plan": record["plan"] | {key: replacement}}})
