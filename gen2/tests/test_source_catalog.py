"""Black-box tests for tools/gen_source_catalog.py — the registry/artifact drift check.

Trace: task 0c deliverable 2 ("drift between registry and either artifact fails
`make gen2-check`"); charter Gate C.

**What the drift tests assert.** Not that the artifacts were regenerated — that
would pass on a checker that always says yes. Each drift test builds a complete
registry + artifact pair in a temp directory, generates the pair so it is known
current, then changes *one* thing (a registry row, a line of the .env example, a
word of the catalog, a deleted file) and requires `--check` to exit non-zero
*and to name what disagrees*. A checker that stopped comparing, or that reported
a missing file by crashing instead of saying so, fails these tests; the mutation
inventory in `tools/gen2_mutations.py` runs exactly those mutants.

**The independent oracle.** For the real repository pair, the expected secret
variables are enumerated by hand below (`EXPECTED_SECRET_VARIABLES`) from the
registry rows and the adapters that read them — not from the generator, and not
from the generated file. If the generator's derivation is wrong, or a source is
added and nobody reviewed its keys, that list disagrees. Updating it is
deliberate: a new credential is a reviewed event, not a regeneration.

**What these tests structurally cannot catch.** That a secret name is the one the
provider actually requires; that an adapter reads the field name its `auth` kind
implies (that correspondence was read once, by hand, and is recorded in the
generator's `AUTH_SECRETS` comment); that a variable present in the example file
reaches a running container; that a rate limit or licence verdict in the registry
is true. They check the derivation and the drift gate, nothing about the world.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "gen_source_catalog.py"  # module global: tools/gen2_mutations.py points this at mutated copies
REAL_REGISTRY = REPO / "gateway" / "research_gateway" / "registry" / "seed" / "sources.toml"
REAL_CATALOG = REPO / "docs" / "gen2" / "SOURCE-CATALOG.md"
REAL_ENV = REPO / "deploy" / "gen2.env.example"

# Hand-enumerated from the registry rows and the adapters that read them:
#   auth = "key" / "optional_token"      -> one variable, no field suffix
#   auth = "client_credentials"          -> _CLIENT_ID and _CLIENT_SECRET   (adapters/openaire.py)
#   auth = "username_key"                -> _USERNAME and _KEY             (adapters/kaggle.py)
#   auth = "none" / "email" / "account"  -> no variable
# Required means the source cannot be called without it; optional means the
# credential only raises the documented limits.
EXPECTED_SECRET_VARIABLES: dict[str, bool] = {
    "RESEARCH_GATEWAY_SECRET_OPENAIRE_CLIENT_ID": True,
    "RESEARCH_GATEWAY_SECRET_OPENAIRE_CLIENT_SECRET": True,
    "RESEARCH_GATEWAY_SECRET_SEMANTIC_SCHOLAR": True,
    "RESEARCH_GATEWAY_SECRET_API_DATA_GOV": True,
    "RESEARCH_GATEWAY_SECRET_HARVARD_DATAVERSE": False,
    "RESEARCH_GATEWAY_SECRET_SOCRATA": False,
    "RESEARCH_GATEWAY_SECRET_KAGGLE_USERNAME": True,
    "RESEARCH_GATEWAY_SECRET_KAGGLE_KEY": True,
    "RESEARCH_GATEWAY_SECRET_HUGGINGFACE": False,
    "RESEARCH_GATEWAY_SECRET_QDR": True,
    "RESEARCH_GATEWAY_SECRET_CORE": True,
    "RESEARCH_GATEWAY_SECRET_FRED": True,
    "RESEARCH_GATEWAY_SECRET_BEA": True,
    "RESEARCH_GATEWAY_SECRET_CENSUS": True,
    "RESEARCH_GATEWAY_SECRET_BLS": False,
}

# A minimal well-formed source row. Tests vary one field at a time from it.
BASE_SOURCE = {
    "id": "example_index",
    "name": "Example Index",
    "kind": "article",
    "homepage": "https://example.invalid/",
    "docs_url": "https://example.invalid/api",
    "capabilities": ["find"],
    "identifiers": ["doi"],
    "base_for": ["article"],
    "domains": [],
    "auth": "key",
    "secret_ref": "example_index",
    "key_instructions": "Register at https://example.invalid/signup for a key.",
    "license": "CC0.",
    "use_commercial": "allow",
    "use_evidence": "https://example.invalid/terms",
    "freshness_lag": "hours",
    "substitution_group": "",
    "enabled": True,
    "notes": "A fixture source, not a real one.",
    "rate": {"per_second": 2, "verified": True, "evidence": "fixture"},
}


def toml_source(source: dict) -> str:
    """Render one [[source]] table. Test-local so a fixture registry is written
    literally here rather than produced by anything under test."""
    rate = source["rate"]
    lines = ["[[source]]"]
    for key, value in source.items():
        if key == "rate":
            continue
        lines.append(f"{key} = {json.dumps(value)}")
    lines.append("[source.rate]")
    for key, value in rate.items():
        lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def write_registry(directory: Path, sources: list[dict]) -> Path:
    path = directory / "sources.toml"
    path.write_text("# fixture registry\n\n" + "\n".join(toml_source(s) for s in sources), encoding="utf-8")
    return path


def variant(**overrides) -> dict:
    source = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
              for k, v in BASE_SOURCE.items()}
    for key, value in overrides.items():
        if value is None:
            source.pop(key, None)
        else:
            source[key] = value
    return source


class CatalogToolTest(unittest.TestCase):
    def run_tool(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)

    def fixture_pair(self, sources: list[dict]) -> tuple[Path, Path, Path]:
        """A generated, known-current registry/catalog/env triple in a temp dir."""
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        registry = write_registry(directory, sources)
        catalog, env = directory / "CATALOG.md", directory / "example.env"
        written = self.generate(registry, catalog, env)
        self.assertEqual(written.returncode, 0, written.stderr)
        self.assertEqual(self.check(registry, catalog, env).returncode, 0, "the freshly generated pair must be current")
        return registry, catalog, env

    def generate(self, registry: Path, catalog: Path, env: Path) -> subprocess.CompletedProcess:
        return self.run_tool("--registry", str(registry), "--catalog", str(catalog), "--env", str(env))

    def check(self, registry: Path, catalog: Path, env: Path) -> subprocess.CompletedProcess:
        return self.run_tool("--registry", str(registry), "--catalog", str(catalog), "--env", str(env), "--check")

    # ---------------------------------------------------------------- drift gate

    def test_check_passes_only_while_nothing_changed(self):
        """Positive control: the gate says yes exactly once, before anything moves."""
        registry, catalog, env = self.fixture_pair([variant()])
        result = self.check(registry, catalog, env)
        self.assertEqual(result.returncode, 0)
        self.assertIn("match the registry", result.stdout)

    def test_a_new_credentialled_source_makes_both_artifacts_stale(self):
        """The failure the gate exists for: a source is added and nobody regenerated."""
        registry, catalog, env = self.fixture_pair([variant()])
        registry.write_text(registry.read_text(encoding="utf-8")
                            + toml_source(variant(id="second_index", name="Second Index",
                                                  secret_ref="second_index", base_for=[])), encoding="utf-8")
        result = self.check(registry, catalog, env)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("CATALOG DRIFT", result.stderr)
        self.assertIn(catalog.name, result.stderr)
        self.assertIn(env.name, result.stderr)
        # and the stale artifact genuinely lacks the new key
        self.assertNotIn("RESEARCH_GATEWAY_SECRET_SECOND_INDEX", env.read_text(encoding="utf-8"))

    def test_deleting_a_secret_line_from_the_env_example_is_drift(self):
        """A hand edit that drops a key — the exact defect in gen-1's env example."""
        registry, catalog, env = self.fixture_pair([variant()])
        kept = [line for line in env.read_text(encoding="utf-8").splitlines(keepends=True)
                if not line.startswith("RESEARCH_GATEWAY_SECRET_EXAMPLE_INDEX=")]
        self.assertEqual(len(kept), len(env.read_text(encoding="utf-8").splitlines()) - 1, "the line must have existed")
        env.write_text("".join(kept), encoding="utf-8")
        result = self.check(registry, catalog, env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(env.name, result.stderr)

    def test_a_hand_edited_catalog_is_drift(self):
        registry, catalog, env = self.fixture_pair([variant()])
        text = catalog.read_text(encoding="utf-8")
        self.assertIn("credential required", text)
        catalog.write_text(text.replace("credential required", "no credential needed", 1), encoding="utf-8")
        result = self.check(registry, catalog, env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(catalog.name, result.stderr)
        self.assertIn("line ", result.stderr)

    def test_a_registry_change_with_no_secret_effect_is_still_drift(self):
        """The catalog carries rate limits and verdicts, not just keys."""
        registry, catalog, env = self.fixture_pair([variant()])
        registry.write_text(registry.read_text(encoding="utf-8").replace("per_second = 2", "per_second = 9"),
                            encoding="utf-8")
        result = self.check(registry, catalog, env)
        self.assertEqual(result.returncode, 1)
        self.assertIn(catalog.name, result.stderr)

    def test_a_missing_artifact_is_reported_not_crashed_on(self):
        registry, catalog, env = self.fixture_pair([variant()])
        env.unlink()
        result = self.check(registry, catalog, env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not exist", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_regenerating_clears_the_drift(self):
        registry, catalog, env = self.fixture_pair([variant()])
        registry.write_text(registry.read_text(encoding="utf-8")
                            + toml_source(variant(id="second_index", name="Second Index",
                                                  secret_ref="second_index", base_for=[])), encoding="utf-8")
        self.assertEqual(self.check(registry, catalog, env).returncode, 1)
        self.assertEqual(self.generate(registry, catalog, env).returncode, 0)
        self.assertEqual(self.check(registry, catalog, env).returncode, 0)
        self.assertIn("RESEARCH_GATEWAY_SECRET_SECOND_INDEX", env.read_text(encoding="utf-8"))

    # ------------------------------------------------- refusal, not partial output

    def assert_refused(self, sources: list[dict], *expected_in_stderr: str) -> None:
        """A registry the generator cannot render completely: exit 2, the reason
        named, and — the property that matters — nothing written."""
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        registry = write_registry(directory, sources)
        catalog, env = directory / "CATALOG.md", directory / "example.env"
        result = self.generate(registry, catalog, env)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        for fragment in expected_in_stderr:
            self.assertIn(fragment, result.stderr)
        self.assertFalse(catalog.exists(), "a refused registry must not leave a partial catalog")
        self.assertFalse(env.exists(), "a refused registry must not leave a partial .env example")

    def test_an_unknown_auth_kind_is_refused_rather_than_emitted_without_its_key(self):
        self.assert_refused([variant(auth="oauth_device_code")], "example_index", "oauth_device_code", "unknown")

    def test_a_credentialled_source_without_a_secret_ref_is_refused(self):
        self.assert_refused([variant(secret_ref="")], "example_index", "secret_ref cannot be empty")

    def test_a_secret_ref_on_a_source_that_reads_no_credential_is_refused(self):
        """Refused rather than resolved: guessing would drop a key or invent one."""
        self.assert_refused([variant(auth="none", secret_ref="example_index")], "example_index", "reads no credential")

    def test_a_secret_ref_that_is_not_a_legal_variable_name_is_refused(self):
        self.assert_refused([variant(secret_ref="example index")], "legal environment variable")

    def test_one_secret_ref_shared_with_two_different_auth_kinds_is_refused(self):
        self.assert_refused(
            [variant(secret_ref="shared"), variant(id="other", name="Other", auth="username_key",
                                                  secret_ref="shared", base_for=[])],
            "shared", "different auth kinds")

    def test_a_missing_required_field_is_refused(self):
        self.assert_refused([variant(key_instructions=None)], "missing key_instructions")

    def test_a_duplicate_source_id_is_refused(self):
        self.assert_refused([variant(), variant(secret_ref="example_index_2", base_for=[])], "duplicate id")

    def test_an_unknown_commercial_verdict_is_refused(self):
        self.assert_refused([variant(use_commercial="probably_fine")], "use_commercial")

    # --------------------------------------------------- derivation, hand-checked

    def test_multi_field_credentials_emit_one_variable_per_field(self):
        """Hand-written expectation: the field suffixes are not the tool's word for it."""
        _, _, env = self.fixture_pair([
            variant(id="cc_source", name="CC Source", auth="client_credentials", secret_ref="cc_source"),
            variant(id="uk_source", name="UK Source", auth="username_key", secret_ref="uk_source", base_for=[]),
        ])
        text = env.read_text(encoding="utf-8")
        for expected in ("RESEARCH_GATEWAY_SECRET_CC_SOURCE_CLIENT_ID=",
                         "RESEARCH_GATEWAY_SECRET_CC_SOURCE_CLIENT_SECRET=",
                         "RESEARCH_GATEWAY_SECRET_UK_SOURCE_USERNAME=",
                         "RESEARCH_GATEWAY_SECRET_UK_SOURCE_KEY="):
            self.assertIn(expected, text)
        self.assertNotIn("RESEARCH_GATEWAY_SECRET_CC_SOURCE=", text)
        self.assertNotIn("RESEARCH_GATEWAY_SECRET_UK_SOURCE=", text)

    def test_a_dash_in_a_secret_name_becomes_an_underscore(self):
        _, _, env = self.fixture_pair([variant(secret_ref="two-part-name")])
        self.assertIn("RESEARCH_GATEWAY_SECRET_TWO_PART_NAME=", env.read_text(encoding="utf-8"))

    def test_required_credentials_are_live_lines_and_optional_ones_are_commented(self):
        _, _, env = self.fixture_pair([
            variant(),
            variant(id="opt_source", name="Opt Source", auth="optional_token", secret_ref="opt_source", base_for=[]),
        ])
        lines = env.read_text(encoding="utf-8").splitlines()
        self.assertIn("RESEARCH_GATEWAY_SECRET_EXAMPLE_INDEX=example-example-index-key", lines)
        self.assertIn("# RESEARCH_GATEWAY_SECRET_OPT_SOURCE=example-opt-source-key", lines)
        self.assertNotIn("RESEARCH_GATEWAY_SECRET_OPT_SOURCE=example-opt-source-key", lines)

    def test_sources_that_read_no_credential_contribute_no_variable(self):
        _, _, env = self.fixture_pair([
            variant(auth="none", secret_ref=""),
            variant(id="mail_source", name="Mail Source", auth="email", secret_ref="", base_for=[]),
            variant(id="manual_source", name="Manual Source", kind="manual", auth="account", secret_ref="",
                    capabilities=[], base_for=[], enabled=False),
        ])
        assignments = [line for line in env.read_text(encoding="utf-8").splitlines()
                       if (line[2:] if line.startswith("# ") else line).startswith("RESEARCH_GATEWAY_SECRET_")
                       and "=" in line]
        self.assertEqual(assignments, [], "a source with no credential produced a secret variable")

    def test_the_catalog_never_claims_a_source_is_free_or_paid(self):
        """The registry has no price field, so no artifact may assert one."""
        _, catalog, _ = self.fixture_pair([variant()])
        text = catalog.read_text(encoding="utf-8")
        self.assertIn("no cost cap recorded in the registry", text)
        body = text.split("## Article indexes", 1)[1]
        for word in ("free tier", "paid tier", "is free", "costs "):
            self.assertNotIn(word, body, f"the catalog asserted {word!r} from a registry that records no price")

    def test_a_cost_cap_in_the_registry_is_reported_as_metered(self):
        _, catalog, _ = self.fixture_pair([variant(rate={"per_second": 2, "cost_cap_per_day": 25,
                                                        "verified": True, "evidence": "fixture"})])
        self.assertIn("metered: the registry records a cost cap of 25/day", catalog.read_text(encoding="utf-8"))

    def test_lane_placement_distinguishes_base_domain_and_fallback(self):
        _, catalog, _ = self.fixture_pair([
            variant(),                                                           # base_for = ["article"]
            variant(id="domain_source", name="Domain Source", base_for=[], domains=["biomed"],
                    secret_ref="domain_source"),
            variant(id="chain_source", name="Chain Source", base_for=[], domains=[], secret_ref="chain_source"),
        ])
        text = catalog.read_text(encoding="utf-8")
        self.assertIn("**base lane** for article", text)
        self.assertIn("**domain lane** added for biomed", text)
        self.assertIn("neither a base nor a domain lane", text)

    def test_services_listen_on_their_container_interface(self):
        """Astra 0c review A6: a listener bound to 127.0.0.1 inside a container
        is that container's own loopback, unreachable from the exporter or
        through a host publication. Every listen address the example emits is
        the container's interfaces; host exposure is Compose's 127.0.0.1
        publication, not the bind. Literal oracle, from the port map in
        DEPLOYMENT-CONTRACT.md §1.1."""
        _, _, env = self.fixture_pair([variant()])
        settings = dict(line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines()
                        if line and not line.startswith("#") and "=" in line)
        listens = {name: value for name, value in settings.items() if name.endswith("_LISTEN")}
        self.assertEqual(listens, {"GEN2_OPERATOR_LISTEN": "0.0.0.0:8770", "GEN2_EXPORTER_HEALTH_LISTEN": "0.0.0.0:8772",
                                   "RESEARCH_GATEWAY_LISTEN": "0.0.0.0:8765"})
        self.assertEqual(settings.get("GEN2_ENGINE_URL"), "http://engine:8770",
                         "the exporter reaches the engine by its Compose service name, not by a loopback address")

    def test_the_engine_settings_name_no_export_destination(self):
        """Operator ruling 2026-09-26 (task 0d): a database receives exports
        through a connector named in mounted config, so the engine's own
        settings name none — the exporter group has its token, health listener,
        the connector config path and per-connector secrets only. Every GEN2_
        variable the example emits, live or commented, against a hand-
        enumerated list: a setting added for one particular store fails here."""
        _, _, env = self.fixture_pair([variant()])
        names = set(re.findall(r"^(?:# )?(GEN2_[A-Z0-9_]+)=", env.read_text(encoding="utf-8"), re.M))
        self.assertEqual(names, {
            "GEN2_CONTROL_STORE", "GEN2_SPOOL_DIR", "GEN2_CONFIG_BUNDLE_DIR", "GEN2_WRAPPERS_DIR", "GEN2_OPERATOR_LISTEN",
            "GEN2_OPERATOR_TOKENS", "GEN2_SECRETS", "GEN2_VAULT_ADDR", "GEN2_VAULT_TOKEN_FILE", "GEN2_VAULT_MOUNT", "GEN2_VAULT_PREFIX",
            "GEN2_VAULT_ALIASES", "GEN2_DECISION_ENABLED", "GEN2_DECISION_JEV_ENDPOINT", "GEN2_SECRET_JEV",
            "GEN2_DECISION_FALLBACK_ENDPOINT", "GEN2_SECRET_DECISION_FALLBACK", "GEN2_TIER0_ENABLED", "GEN2_TIER0_URL",
            "GEN2_GATEWAY_URL", "GEN2_SECRET_GATEWAY_TOKEN", "GEN2_EXPORTER_HEALTH_LISTEN", "GEN2_ENGINE_URL",
            "GEN2_SECRET_EXPORTER_TOKEN", "GEN2_CONNECTORS_CONFIG", "GEN2_SECRET_CONNECTOR_WAREHOUSE", "GEN2_SECRET_CONNECTOR_HOOK",
        })

    # ------------------------------------------ the real repository pair and its keys

    def test_the_committed_pair_is_current_for_the_real_registry(self):
        """The check that makes `make gen2-check` mean something: the committed
        artifacts and the real registry agree right now."""
        result = self.check(REAL_REGISTRY, REAL_CATALOG, REAL_ENV)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_the_real_env_example_holds_exactly_the_hand_enumerated_variables(self):
        """Independent oracle: EXPECTED_SECRET_VARIABLES is written from the
        registry rows and the adapters, not read from the generated file."""
        lines = REAL_ENV.read_text(encoding="utf-8").splitlines()
        found: dict[str, bool] = {}
        for line in lines:
            stripped = line[2:] if line.startswith("# ") else line
            if stripped.startswith("RESEARCH_GATEWAY_SECRET_") and "=" in stripped:
                found[stripped.split("=", 1)[0]] = not line.startswith("# ")
        self.assertEqual(found, EXPECTED_SECRET_VARIABLES)

    def test_semantic_scholar_needs_a_key_and_has_one_here(self):
        """The named gap: `semantic_scholar` requires a key
        (registry `auth = "key"`, read by adapters/semanticscholar.py as the
        x-api-key header) and was absent from gen-1's
        gateway/deploy/gateway.env.example. It is present here by construction."""
        self.assertIn("RESEARCH_GATEWAY_SECRET_SEMANTIC_SCHOLAR=", REAL_ENV.read_text(encoding="utf-8"))
        self.assertIn("RESEARCH_GATEWAY_SECRET_SEMANTIC_SCHOLAR", REAL_CATALOG.read_text(encoding="utf-8"))

    def test_no_example_value_in_the_committed_env_example_looks_like_a_real_secret(self):
        """A generated file that is committed must never carry a credential."""
        for line in REAL_ENV.read_text(encoding="utf-8").splitlines():
            stripped = line[2:] if line.startswith("# ") else line
            if "=" not in stripped or stripped.startswith("#"):
                continue
            name, _, value = stripped.partition("=")
            # Credential-bearing names only: `GEN2_SECRETS` selects a backend and
            # `*_VAULT_TOKEN_FILE` is a path, so neither holds a value to leak.
            if "_SECRET_" in name or name.endswith(("PASSWORD", "TOKENS")):
                self.assertTrue("example" in value.lower(), f"{name} has a non-example value: {value!r}")
        self.assertIn("GEN2_SECRETS=env", REAL_ENV.read_text(encoding="utf-8"),
                      "the backend selector must still be present — the filter above skips it deliberately")

    def test_the_tool_does_not_import_gen1_gateway_code(self):
        """INVARIANTS B-2: the registry is read as TOML, not through
        research_gateway. The boundary graph does not cover tools/."""
        source = TOOL.read_text(encoding="utf-8")
        for forbidden in ("import research_gateway", "from research_gateway", "import research_loops"):
            self.assertNotIn(forbidden, source)
        self.assertIn("import tomllib", source)


class CatalogHelpTest(unittest.TestCase):
    def test_help_runs_without_a_repository(self):
        """The tool is run from a temp copy by the mutation harness; --help must
        not depend on anything beside it."""
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / TOOL.name
            copy.write_text(TOOL.read_text(encoding="utf-8"), encoding="utf-8")
            result = subprocess.run([sys.executable, str(copy), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--check", result.stdout)


if __name__ == "__main__":
    unittest.main()
