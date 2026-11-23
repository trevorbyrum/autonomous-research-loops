"""LR-3: byte integrity over carried operands; no file reads or qualification authority.
Own pending-record/receipt values exercise packing, not a simulated external CLI.
"""
import json
import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from deploy.gen2.live import build, operands
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

    def test_experiment_authorization_binds_exact_bytes_pair_and_state(self):
        view = experiment_view()
        data, pin = operands.pack(view)
        self.assertEqual((data, pin), (canonical.canonical_bytes(view["record"]), canonical.bytes_digest(data)))
        record = dict(view["record"], state="qualified", witnesses=view["record"]["witnesses"][:-1])
        for field in ("authorization", "authorization_pin"):
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, "stale authorization"):
                operands.pack({key: value for key, value in view.items() if key != field})
            with self.subTest(unexpected=field), self.assertRaisesRegex(ValueError, "requires an experiment record"):
                operands.pack(dict(record=record, manifest=view["manifest"], receipts=view["receipts"], **{field: view[field]}))
        for change in ({"authorization": None}, {"authorization": view["authorization"] + b" "},
                       {"receipts": {ref: raw + b" " for ref, raw in view["receipts"].items()}}):
            with self.subTest(field=next(iter(change))), self.assertRaisesRegex(ValueError, "stale"):
                operands.pack(view | change)
        approval = json.loads(view["authorization"])
        bad_approvals = [None, {}, {key: value for key, value in approval.items() if key != "record_pin"}, approval | {"extra": None}]
        bad_approvals += [approval | {"record_pin": "sha256:" + "1" * 64}, approval | {"manifest_pin": "sha256:" + "2" * 64},
                          approval | {"experiment": approval["experiment"] | {"topic_id": "other-topic"}}]
        for bad in bad_approvals:
            raw = json.dumps(bad).encode()
            with self.subTest(approval=bad), self.assertRaisesRegex(ValueError, "experiment pair"):
                operands.pack(view | dict(authorization=raw, authorization_pin=canonical.bytes_digest(raw)))

    def test_experiment_manifest_claims_must_match_even_when_repinned(self):
        manifest = json.loads(experiment_view()["manifest"])
        for field, value in (("route", "real"), ("qualification_state", "qualified"), ("credential_ref", "other-session")):
            raw = canonical.canonical_bytes(manifest | {field: value})
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "manifest operand does not match"):
                operands.pack(experiment_view(manifest=raw))

    def test_experiment_empty_and_extra_encodings_refuse_even_when_repinned(self):
        view = experiment_view()
        pending = view["record"]["witnesses"][-1]
        scope = view["record"]["experiment"]
        cases = [("witnesses", view["record"]["witnesses"][:-1] + [row], "pending DEBT-004")
                 for row in (None, {}, {"name": "DEBT-004"}, pending | {"receipt": None}, pending | {"passed": 0})]
        cases += [("experiment", keys, "experiment scope")
                  for keys in (None, {}, {key: value for key, value in scope.items() if key != "topic_id"}, scope | {"extra": ""})]
        for field, value, error in cases:
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, error):
                operands.pack(experiment_view(**{field: value}))

    def test_pinned_compose_authorization_bind_and_real_profile(self):
        root = Path(__file__).parent
        env = dict(GEN2_CONFIG_ROOT="/cfg", GEN2_DATA_ROOT="/data", GEN2_GENERATION="0" * 32, GEN2_HOST_ID="render",
                   GEN2_QUALIFICATION_PIN="sha256:" + "a" * 64)
        env.update({f"GEN2_{role}_ID": digit * 64 for role, digit in (("ENGINE", "b"), ("GATEWAY", "c"), ("FIXTURE", "d"))})
        env.update({f"GEN2_{role}_EVIDENCE": "/data/" + role.lower() for role in ("RELAY", "FIXTURE", "SOURCE")})
        pin = experiment_view()["authorization_pin"]
        target = "/etc/gen2/qualification-record-authorization.json"
        source = "/cfg/qualification-record-authorization.json"
        for profile, authorization_pin in ((["--profile", "offline"], pin), (["--profile", "offline"], ""), ([], pin)):
            with self.subTest(profile=profile, authorization_pin=authorization_pin):
                render_env = env | ({"GEN2_EXPERIMENT_AUTHORIZATION_PIN": authorization_pin} if authorization_pin else {})
                with patch.dict(os.environ, render_env, clear=True):
                    argv = build.compose_command("--env-file", os.devnull, *profile, "-f", str(root / "compose.yaml"),
                                                 "-f", str(root / "compose.live.yaml"), "config", "--no-env-resolution", "--format", "json")
                services = json.loads(subprocess.check_output(argv, env=render_env, timeout=10))["services"]
                self.assertEqual(set(services), {"engine", "gateway", "gateway-db"} | ({"relay", "fixture", "source-fixture"} if profile else set()))
                if profile:
                    fixture = services["fixture"]
                    self.assertEqual(fixture["image"], "sha256:" + env["GEN2_FIXTURE_ID"])
                    self.assertEqual([m["source"] for m in fixture["volumes"]], [env["GEN2_FIXTURE_EVIDENCE"]])
                engine = services["engine"]
                self.assertEqual(engine["environment"]["GEN2_EXPERIMENT_AUTHORIZATION_PIN"], authorization_pin)
                self.assertEqual(engine["environment"]["GEN2_EXPERIMENT_AUTHORIZATION"], target if authorization_pin else "")
                binds = [mount for mount in engine["volumes"] if mount["target"].startswith("/etc/gen2/qualification-record")]
                expected = [("/cfg/qualification-record.json", "/etc/gen2/qualification-record.json", True)]
                if authorization_pin:
                    expected.append((source, target, True))
                self.assertCountEqual([(m["source"], m["target"], m["read_only"]) for m in binds], expected)
                self.assertFalse(any(m["source"] == env["GEN2_FIXTURE_EVIDENCE"] for m in engine["volumes"]))
                self.assertFalse(any(m["source"] == source or m["target"] == target
                                     for name, service in services.items() if name != "engine" for m in service.get("volumes", ())))


def experiment_view(manifest=b'{"route":"fixture","qualification_state":"rejection_experiment","credential_ref":"session"}', **changes):
    receipt = b"exact receipt bytes"
    pin = canonical.bytes_digest(receipt)
    record = dict(record_version="qualification-record/1", state="rejection_experiment", route="fixture", credential_ref="session", manifest_pin=canonical.bytes_digest(manifest),
                  experiment=dict(invocation_id="invocation", topic_id="topic", config_bundle_hash="bundle", not_before="2026-01-01T00:00:00Z"),
                  witnesses=[dict(name=name, passed=True, receipt=pin) for name in ("Q1", "Q2", "Q3")] + [dict(name="DEBT-004", passed=False)],
                  plan={}) | changes
    approval = dict(authorization_version="rejection-experiment-authorization/1", record_pin=canonical.logical_hash(record),
                    manifest_pin=record["manifest_pin"], experiment=record["experiment"], ruling_ref="ruling", approved_at="2026-01-01T00:00:00Z")
    authorization = json.dumps(approval, indent=2).encode() + b"\n"
    return dict(record=record, manifest=manifest, receipts={pin: receipt},
                authorization=authorization, authorization_pin=canonical.bytes_digest(authorization))
