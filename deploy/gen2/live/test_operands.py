"""LR-3: byte integrity over carried operands; no file reads or qualification authority.
Own pending-record/receipt values exercise packing, not a simulated external CLI.
"""
import json
import os
import unittest
from unittest.mock import patch

from deploy.gen2.live import operands
from gen2.core import canonical


class Operands(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(os.environ, {"GEN2_CONFIG_ROOT": "/cfg", "GEN2_DATA_ROOT": "/data"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unset_or_relative_roots_refuse(self):
        for name in ("GEN2_CONFIG_ROOT", "GEN2_DATA_ROOT"):
            for value in (None, "", "relative/path"):
                env = {k: v for k, v in os.environ.items() if k != name} | ({} if value is None else {name: value})
                with self.subTest(name=name, value=value), patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(ValueError, name):
                    operands.root(name)
        with patch.dict(os.environ, {"GEN2_CONFIG_ROOT": "relative"}), self.assertRaisesRegex(ValueError, "GEN2_CONFIG_ROOT"):
            operands.provider_files()

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
        files = operands.provider_files()
        manifest = b'{"route":"real"}'
        record = dict(route="real", manifest_pin=canonical.bytes_digest(manifest), witnesses=[], plan=dict(files))
        view = dict(record=record, manifest=manifest, receipts={})
        data, _ = operands.pack(view)
        self.assertEqual(json.loads(data)["plan"], files)
        for key in files:
            for replacement in (None, "/tmp/unreviewed"):
                with self.subTest(key=key, replacement=replacement), self.assertRaisesRegex(ValueError, "provider file operand"):
                    operands.pack(view | {"record": record | {"plan": record["plan"] | {key: replacement}}})
