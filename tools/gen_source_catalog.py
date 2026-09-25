#!/usr/bin/env python3
"""Generate the gen-2 source catalog and .env example from the gateway registry.

One source of truth. The gateway's source registry
(`gateway/research_gateway/registry/seed/sources.toml`) is authoritative; this
tool derives BOTH operator-facing artifacts from it and nothing else:

  docs/gen2/SOURCE-CATALOG.md   what each source provides, how to get its key,
                                its credential/cost posture, rate limits, which
                                lanes need it, its licence and commercial verdict
  deploy/gen2.env.example       every secret name the gen-2 stack reads, grouped
                                and commented

    python3 tools/gen_source_catalog.py            # write both artifacts
    python3 tools/gen_source_catalog.py --check    # exit 1 if either is stale

`make gen2-catalog` writes them; `make gen2-check` runs `--check`, so a registry
edit that is not regenerated fails the build, and so does a hand edit of either
artifact. The registry is read as TOML: no gen-2 code and no gen-2 build tool
imports `research_gateway` (INVARIANTS B-2), and nothing here touches the
running gen-1 gateway service.

The registry is read strictly. An `auth` value this tool does not know, a
credentialled source with no `secret_ref`, a `secret_ref` that does not spell a
legal environment-variable name, a missing required field: each is a hard
failure naming the source. The alternative — emitting an artifact that silently
omits a key — is the defect this tool exists to remove (`semantic_scholar` needs
a key and was absent from gen-1's `gateway/deploy/gateway.env.example`).

What the registry does NOT record, and this tool therefore never asserts: a
price, a paid tier, or a redistribution permission. Credential and metering
posture are derived from `auth` and `rate.cost_cap_per_day`; anything else is
reported as not recorded.

Trace: task 0c deliverable 2. docs/gen2/DEPLOYMENT-CONTRACT.md §3 (secrets: the
env backend's one mounted file, the vault backend's per-service token-file
wiring). flow §4.2 / INVARIANTS H-2 (a failed secrets read is a dated
capability fact, never "no key configured" — so every secret the stack reads has
to be nameable in one place). BOUNDARIES.md *Gateway* (the only door to external
sources; licensing/provenance fields). design review §9 (keep the gateway's
licensing/provenance handling and coverage vocabulary). INVARIANTS B-2, RG-U.
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = "gateway/research_gateway/registry/seed/sources.toml"
CATALOG = "docs/gen2/SOURCE-CATALOG.md"
ENV_EXAMPLE = "deploy/gen2.env.example"

# The gateway's own env-secret scheme, reproduced (not imported) from
# gateway/research_gateway/core/secrets.py EnvBackend: the prefix, the
# upper-casing, the dash-to-underscore rule and the field suffix.
ENV_PREFIX = "RESEARCH_GATEWAY_SECRET_"

# Which secret fields each auth kind needs, and whether the source can be called
# without them. Derived from the adapters that read them: kaggle reads
# ("kaggle", "username") and ("kaggle", "key"); openaire reads
# ("openaire", "client_id") and ("openaire", "client_secret"); every other
# credentialled adapter reads a single unnamed field. An auth value missing from
# this table is a hard failure, never a source emitted without its key.
AUTH_SECRETS: dict[str, tuple[tuple[str | None, bool], ...]] = {
    "none": (),
    "email": (),                                     # a contact address, deployment config, not a secret
    "account": (),                                   # manual-only source: no programmatic credential exists
    "key": ((None, True),),
    "optional_token": ((None, False),),
    "client_credentials": (("client_id", True), ("client_secret", True)),
    "username_key": (("username", True), ("key", True)),
}
CREDENTIAL_POSTURE = {
    "none": "no credential",
    "email": "no credential (a contact address in the request, not a secret)",
    "account": "manual only — the registry records no programmatic credential",
    "optional_token": "credential optional (raises the documented limits)",
    "key": "credential required",
    "client_credentials": "credential required (client id + secret, exchanged for bearer tokens)",
    "username_key": "credential required (username + key)",
}
KINDS = ("article", "dataset", "citation", "resolver", "statistical", "manual")
KIND_TITLES = {
    "article": "Article indexes",
    "dataset": "Dataset and repository indexes",
    "citation": "Citation graph",
    "resolver": "Resolvers and enrichment",
    "statistical": "Statistical data APIs",
    "manual": "Manual-only sources (documented, never queried)",
}
VERDICTS = {
    "allow": "the source's terms permit commercial use of what the gateway retrieves",
    "per-item": "the platform permits it, but each record carries its own licence; records without an allow-listed licence are dropped in commercial mode",
    "deny": "the source's terms forbid commercial use, or require a paid tier",
    "unknown": "no reuse terms could be located; fails closed for commercial-flagged requests",
}
DOMAINS = ("finance", "market", "social", "management", "ai-ml", "software", "biomed")
REQUIRED_FIELDS = ("id", "name", "kind", "homepage", "capabilities", "auth", "use_commercial",
                   "use_evidence", "key_instructions", "license", "rate")


class RegistryError(Exception):
    """The registry does not support generating a complete artifact."""


# ---------------------------------------------------------------- registry read

def read_registry(path: Path) -> list[dict]:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    sources = data.get("source")
    if not isinstance(sources, list) or not sources:
        raise RegistryError(f"{path}: no [[source]] entries")
    return sources


def validate(sources: list[dict]) -> list[str]:
    """Every reason this registry cannot produce a complete catalog/env pair."""
    problems: list[str] = []
    seen: dict[str, dict] = {}
    for s in sources:
        sid = s.get("id") or "<source with no id>"
        for key in REQUIRED_FIELDS:
            if key not in s:
                problems.append(f"{sid}: missing {key}")
        if sid in seen:
            problems.append(f"{sid}: duplicate id")
        seen[sid] = s
        kind = s.get("kind")
        if kind not in KINDS:
            problems.append(f"{sid}: kind {kind!r} is not one of {list(KINDS)}")
        auth = s.get("auth")
        if auth not in AUTH_SECRETS:
            problems.append(
                f"{sid}: auth {auth!r} is unknown to tools/gen_source_catalog.py, so its secret "
                f"names cannot be derived; known: {sorted(AUTH_SECRETS)}")
        if s.get("use_commercial") not in VERDICTS:
            problems.append(f"{sid}: use_commercial {s.get('use_commercial')!r} is not one of {sorted(VERDICTS)}")
        bad = sorted(set(s.get("domains", [])) - set(DOMAINS))
        if bad:
            problems.append(f"{sid}: unknown domains {bad}")
        rate = s.get("rate")
        if not isinstance(rate, dict):
            problems.append(f"{sid}: rate must be a table")
        elif "verified" not in rate or "evidence" not in rate:
            problems.append(f"{sid}: rate needs verified and evidence")
        ref = (s.get("secret_ref") or "").strip()
        if auth in AUTH_SECRETS:
            if AUTH_SECRETS[auth] and not ref:
                problems.append(f"{sid}: auth {auth} needs a credential, so secret_ref cannot be empty")
            if not AUTH_SECRETS[auth] and ref:
                problems.append(
                    f"{sid}: auth {auth} reads no credential, but secret_ref is {ref!r} — one of the two is wrong, "
                    "and guessing which would drop a key or invent one")
        if ref:
            for field, _ in AUTH_SECRETS.get(auth, ()) or ((None, True),):
                name = env_var(ref, field)
                if not name.replace("_", "A").isalnum() or not name[0].isalpha() or name != name.upper():
                    problems.append(f"{sid}: secret_ref {ref!r} does not spell a legal environment variable ({name})")
    # A shared secret_ref is legitimate (one credential serving several sources),
    # but only if every sharer reads it the same way.
    by_ref: dict[str, list[dict]] = {}
    for s in sources:
        ref = (s.get("secret_ref") or "").strip()
        if ref:
            by_ref.setdefault(ref, []).append(s)
    for ref, group in sorted(by_ref.items()):
        auths = {s.get("auth") for s in group}
        if len(auths) > 1:
            ids = ", ".join(sorted(str(s.get("id")) for s in group))
            problems.append(f"secret_ref {ref!r} is shared by {ids} with different auth kinds {sorted(map(str, auths))}")
    return problems


def env_var(secret_ref: str, field: str | None) -> str:
    name = ENV_PREFIX + secret_ref.upper().replace("-", "_")
    return f"{name}_{field.upper()}" if field else name


@dataclass(frozen=True)
class Secret:
    """One environment variable the stack reads, and who needs it."""
    var: str
    secret_ref: str
    field: str | None
    required: bool
    source_ids: tuple[str, ...]
    source_names: tuple[str, ...]
    key_instructions: str


def secrets_of(sources: list[dict]) -> list[Secret]:
    """Every source secret, in registry order, one entry per environment variable."""
    order: list[str] = []
    rows: dict[str, dict] = {}
    for s in sources:
        ref = (s.get("secret_ref") or "").strip()
        for field, required in AUTH_SECRETS[s["auth"]]:
            if not ref:
                continue
            var = env_var(ref, field)
            if var not in rows:
                order.append(var)
                rows[var] = {"ref": ref, "field": field, "required": required, "ids": [], "names": [],
                             "instructions": s.get("key_instructions", "")}
            rows[var]["ids"].append(s["id"])
            rows[var]["names"].append(s["name"])
            rows[var]["required"] = rows[var]["required"] or required
    return [Secret(var, r["ref"], r["field"], r["required"], tuple(r["ids"]), tuple(r["names"]), r["instructions"])
            for var, r in ((v, rows[v]) for v in order)]


def by_kind(sources: list[dict]) -> list[tuple[str, list[dict]]]:
    """Sources grouped in the registry's kind order, sorted by name inside a kind."""
    groups = []
    for kind in KINDS:
        members = sorted((s for s in sources if s["kind"] == kind), key=lambda s: s["name"])
        if members:
            groups.append((kind, members))
    return groups


# ------------------------------------------------------------------ derivations

def rate_text(rate: dict) -> str:
    parts = []
    for key, unit in (("per_second", "/s"), ("per_minute", "/min"), ("per_hour", "/h"), ("per_day", "/day")):
        if rate.get(key):
            parts.append(f"{rate[key]:g}{unit}")
    if rate.get("burst"):
        parts.append(f"burst {rate['burst']}")
    text = ", ".join(parts) or "no live calls"
    flag = "verified" if rate.get("verified") else "**unverified — a conservative default until confirmed**"
    return f"{text} ({flag})"


def cost_text(rate: dict) -> str:
    if rate.get("cost_cap_per_day"):
        return f"metered: the registry records a cost cap of {rate['cost_cap_per_day']:g}/day"
    return "no cost cap recorded in the registry (the registry has no price field — see § *What this catalog does not know*)"


def lane_text(source: dict) -> str:
    base, domains = source.get("base_for", []), source.get("domains", [])
    if source["kind"] == "manual":
        return "not a lane: documented, never queried by the gateway"
    parts = []
    if base:
        parts.append(f"**base lane** for {', '.join(base)} — queried for every request of that kind")
    if domains:
        parts.append(f"**domain lane** added for {', '.join(domains)} (an `other`-domain request includes every domain lane)")
    if not parts:
        parts.append("neither a base nor a domain lane: reached through the fallback chain for its capabilities")
    return "; ".join(parts)


def credential_text(source: dict) -> str:
    auth = source["auth"]
    posture = CREDENTIAL_POSTURE[auth]
    ref = (source.get("secret_ref") or "").strip()
    if not ref:
        return posture
    variables = ", ".join(f"`{env_var(ref, field)}`" for field, _ in AUTH_SECRETS[auth])
    return f"{posture}; secret name `{ref}`; environment {variables}"


# --------------------------------------------------------------------- catalog

def render_catalog(sources: list[dict]) -> str:
    secrets = secrets_of(sources)
    required = [s for s in secrets if s.required]
    optional = [s for s in secrets if not s.required]
    out: list[str] = [
        "# Gen-2 research source catalog",
        "",
        "**GENERATED — do not edit by hand.** `tools/gen_source_catalog.py` derives this file and",
        f"`{ENV_EXAMPLE}` from the gateway source registry (`{REGISTRY}`), which is the one source of",
        "truth. `make gen2-catalog` regenerates both; `make gen2-check` fails if either disagrees with the",
        "registry, so a new source without a regenerated catalog, and a hand edit of either artifact, both",
        "break the build.",
        "",
        "**Trace.** Task 0c deliverable 2. `docs/gen2/DEPLOYMENT-CONTRACT.md` §3 (secrets surface, both",
        "backends, the two outage-hardening rules). Flow architecture §4.2 and `docs/gen2/INVARIANTS.md` H-2:",
        "a failed secrets read is a dated `secrets backend failing` capability fact, never \"no key",
        "configured\" — which is only possible if every secret the stack reads is named in one place.",
        "`docs/gen2/BOUNDARIES.md` *Gateway* (the only door to external research sources; licensing and",
        "provenance fields; coverage vocabulary). Design review §9. `docs/gen2/SOURCE-GOVERNANCE.md` covers",
        "how a source gets *into* the registry.",
        "",
        "## How this file is derived",
        "",
        "- **Environment variable names** reproduce the gateway's own scheme",
        f"  (`gateway/research_gateway/core/secrets.py`, `EnvBackend`): `{ENV_PREFIX}<NAME>` with the logical",
        "  secret name upper-cased and `-` replaced by `_`, plus a `_<FIELD>` suffix for the two multi-field",
        "  credentials. The gen-2 stack runs the gateway service unmodified, so the gateway's names are the",
        "  gen-2 names.",
        "- **Which fields a credential has** comes from the registry's `auth` value, checked against the",
        "  adapters that read it. An `auth` value the generator does not know is a build failure, not a",
        "  source emitted without its key.",
        "- **Credential and cost posture** come from `auth` and `rate.cost_cap_per_day`.",
        "- **Lane placement** comes from `base_for` (queried for every request of that kind) and `domains`",
        "  (added for those domains).",
        "",
        "## What this catalog does not know",
        "",
        "The registry records no **price** and no **paid-tier** field, so this catalog never claims a source",
        "is free or paid. It reports whether a credential is required, optional or absent, and whether a",
        "daily cost cap is recorded. Where a source's own key instructions say registration is free, that",
        "is the source's wording, quoted under *How to get access*.",
        "",
        "The registry also records no **redistribution** permission. That question is per record, not per",
        "source (a CC0 metadata record can describe a copyrighted paper), and the gateway answers it per",
        "record: `gateway.record_sources` carries a `redistributable` flag and the content licence beside",
        "each contributing payload. Export bundles rely on that per-record answer, never on this file",
        "(`docs/gen2/EXPORT-SINKS.md`).",
        "",
        f"## Secrets index ({len(secrets)} variables across {len({s.secret_ref for s in secrets})} secret names)",
        "",
        "| Environment variable | Secret name | Requirement | Needed by |",
        "|---|---|---|---|",
    ]
    for s in secrets:
        out.append(f"| `{s.var}` | `{s.secret_ref}`{f' field `{s.field}`' if s.field else ''} | "
                   f"{'required' if s.required else 'optional'} | {', '.join(s.source_ids)} |")
    out += [
        "",
        f"{len(required)} required, {len(optional)} optional. A source whose required credential is absent is a",
        "lane the gateway cannot call: it reports `auth_failed` coverage and a dated capability fact, never",
        "`searched_empty` and never a zero in any count (INVARIANTS RG-4, RG-U).",
        "",
    ]
    for kind, members in by_kind(sources):
        out += [f"## {KIND_TITLES[kind]}", ""]
        for s in members:
            rate = s["rate"]
            caps = ", ".join(s.get("capabilities", [])) or "none"
            out += [
                f"### {s['name']} (`{s['id']}`)",
                "",
                f"- **Provides:** {kind} records; gateway requests: {caps}"
                + (f"; identifiers: {', '.join(s['identifiers'])}" if s.get("identifiers") else ""),
                f"- **Lanes:** {lane_text(s)}",
                f"- **Credential:** {credential_text(s)}",
                f"- **How to get access:** {s.get('key_instructions', '')}",
                f"- **Website:** {s['homepage']}"
                + (f" — **API documentation:** {s['docs_url']}" if s.get("docs_url") else ""),
                f"- **Rate limit:** {rate_text(rate)} — {rate.get('evidence', '')}",
                f"- **Cost:** {cost_text(rate)}",
                f"- **Licence:** {s.get('license', '')}",
                f"- **Commercial posture:** **{s['use_commercial']}** — {VERDICTS[s['use_commercial']]}. "
                f"Evidence: {s.get('use_evidence', '')}",
            ]
            if s.get("freshness_lag"):
                out.append(f"- **Freshness:** {s['freshness_lag']}")
            out.append(f"- **Substitution family:** {s['substitution_group']}" if s.get("substitution_group")
                       else "- **Substitution family:** none")
            enabled = "yes" if s.get("enabled") else "no"
            if not s.get("enabled") and not rate.get("verified"):
                enabled += " — its rate limit is not verified, and the registry keeps unverified sources disabled"
            out.append(f"- **Enabled in the registry's default seed:** {enabled}")
            if s.get("notes"):
                out.append(f"- **Notes:** {s['notes']}")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


# ----------------------------------------------------------------- env example

@dataclass(frozen=True)
class Key:
    var: str
    value: str
    comment: str = ""
    commented: bool = False


@dataclass(frozen=True)
class Group:
    title: str
    notes: tuple[str, ...]
    keys: tuple[Key, ...]


# The gen-2 stack's own keys. The research-source keys are not here: they are
# generated from the registry (see SOURCE_SECRETS_TITLE below). Every value is an
# example. Keys marked `commented` are alternatives or optional features, and are
# emitted commented out so an uncommented file is a working minimum.
SERVICE_GROUPS: tuple[Group, ...] = (
    Group(
        "Gen-2 engine — router, station supervisor, operator transports",
        ("The control store is mounted into THIS container only: the router is the sole writer, so no",
         "second process opens the SQLite file (DEPLOYMENT-CONTRACT.md §1)."),
        (
            Key("GEN2_CONTROL_STORE", "/var/lib/gen2/control.sqlite3", "the one authoritative store"),
            Key("GEN2_SPOOL_DIR", "/var/lib/gen2/spool", "protected spool for content-addressed artifacts"),
            Key("GEN2_CONFIG_BUNDLE_DIR", "/etc/gen2/bundle",
                "mounted read-only: stations.yaml, fleet policy, prompts, question registry, thresholds"),
            Key("GEN2_WRAPPERS_DIR", "/etc/gen2/wrappers",
                "operator-owned, operator-trusted, read-only; agents never write here (§4)"),
            Key("GEN2_OPERATOR_LISTEN", "127.0.0.1:8770", "operator command service: HTTP + POST /mcp; loopback only"),
            Key("GEN2_OPERATOR_TOKENS", "operator=example-operator-token,mcp=example-mcp-token",
                "one bearer token per operator client; the service refuses to start without any"),
            Key("GEN2_SECRETS", "env", "env | vault"),
        ),
    ),
    Group(
        "Gen-2 engine secrets, vault backend",
        ("Selected with GEN2_SECRETS=vault. GEN2_VAULT_TOKEN_FILE is REQUIRED explicitly: there is no",
         "home-directory fallback, and a service configured for vault without it refuses to start",
         "(DEPLOYMENT-CONTRACT.md §3.3 rule 1)."),
        (
            Key("GEN2_VAULT_ADDR", "https://vault.example.org:8200", commented=True),
            Key("GEN2_VAULT_TOKEN_FILE", "/run/secrets/gen2-vault-token", "mounted read-only, 0400", commented=True),
            Key("GEN2_VAULT_MOUNT", "secret", commented=True),
            Key("GEN2_VAULT_PREFIX", "services", commented=True),
            Key("GEN2_VAULT_ALIASES", "jev=typesafe-jev", "logical=vault-name, when paths differ", commented=True),
        ),
    ),
    Group(
        "Decision layer — Jev primary, LLM fallback",
        ("Optional by charter: the engine must run and be testable with the decision layer disabled, so",
         "the shipped default is off. Initial rollout is screening in shadow and method-selection",
         "advisory; nothing else (flow §5)."),
        (
            Key("GEN2_DECISION_ENABLED", "false", "true only once a question registry and thresholds are mounted"),
            Key("GEN2_DECISION_JEV_ENDPOINT", "https://api.typesafe.ai", commented=True),
            Key("GEN2_SECRET_JEV", "example-jev-api-key", commented=True),
            Key("GEN2_DECISION_FALLBACK_ENDPOINT", "https://api.example-llm.invalid", commented=True),
            Key("GEN2_SECRET_DECISION_FALLBACK", "example-fallback-api-key", commented=True),
        ),
    ),
    Group(
        "Tier-0 checker — local NLI claim-vs-span screen",
        ("Optional. Absent, the engine records a dated capability fact and verification proceeds without",
         "the screen; the screen never gated a load-bearing claim (BOUNDARIES.md Tier-0 checker)."),
        (
            Key("GEN2_TIER0_ENABLED", "true"),
            Key("GEN2_TIER0_URL", "http://tier0:8773"),
        ),
    ),
    Group(
        "Gateway client — the engine's only door to external research sources",
        ("The engine reaches the gateway over HTTP and never imports it (INVARIANTS B-2). The token is one",
         "of the gateway's own client tokens, issued to the engine."),
        (
            Key("GEN2_GATEWAY_URL", "http://gateway:8765"),
            Key("GEN2_SECRET_GATEWAY_TOKEN", "example-token-issued-to-the-gen2-engine"),
        ),
    ),
    Group(
        "Projector — publication sinks, named physically",
        ("Neo4j and Qdrant are referenced external services: this stack connects to them, and reports a",
         "dated capability fact when it cannot. A failed sink leaves publication partial; it never rewrites",
         "completion (INVARIANTS P-2, P-4)."),
        (
            Key("GEN2_PROJECTOR_HEALTH_LISTEN", "0.0.0.0:8772", "in-network only; not published to the host"),
            Key("GEN2_NEO4J_URI", "bolt://neo4j-host:7687"),
            Key("GEN2_NEO4J_USER", "neo4j"),
            Key("GEN2_SECRET_NEO4J_PASSWORD", "example-neo4j-password"),
            Key("GEN2_QDRANT_URL", "http://qdrant-host:6333"),
            Key("GEN2_SECRET_QDRANT_API_KEY", "example-qdrant-api-key"),
        ),
    ),
    Group(
        "Export sinks — operator-pluggable research export",
        ("Which sinks are enabled, their destinations, and the per-topic export options are MOUNTED CONFIG.",
         "Only the credential-bearing part lives here (docs/gen2/EXPORT-SINKS.md §4): one variable per",
         "enabled sink id, GEN2_SECRET_EXPORT_SINK_<SINK_ID>, upper-cased with - replaced by _. A sink whose",
         "destination carries no credential (a mounted file path) has no variable here at all."),
        (
            Key("GEN2_EXPORT_SINKS_CONFIG", "/etc/gen2/bundle/export-sinks.toml", "mounted read-only"),
            Key("GEN2_SECRET_EXPORT_SINK_WAREHOUSE",
                "postgresql://exporter:example-password@warehouse-host:5432/research",
                "generic_sql sink `warehouse`: the DSN embeds the credential, so the whole DSN is the secret",
                commented=True),
            Key("GEN2_SECRET_EXPORT_SINK_HOOK", "example-webhook-bearer-token",
                "webhook_http sink `hook`: the endpoint URL is mounted config; only the token is here",
                commented=True),
        ),
    ),
    Group(
        "Gen-2 research gateway instance",
        ("The gateway service runs unmodified, so it keeps its own variable names. This instance is the",
         "GEN-2 one: it must have its own database. Pointing it at gen-1's DSN or its port (127.0.0.1:8765",
         "on this host) is a deployment error — one gateway service per database."),
        (
            Key("RESEARCH_GATEWAY_LISTEN", "0.0.0.0:8765", "inside the container; published on 127.0.0.1:8771"),
            Key("RESEARCH_GATEWAY_CONTACT_EMAIL", "you@example.org",
                "sent to sources whose polite pool wants a contact address"),
            Key("RESEARCH_GATEWAY_DSN", "postgresql://gateway@gateway-db:5432/gen2_research_loops",
                "the gen-2 database, never gen-1's"),
            Key("PGPASSWORD", "example-database-password"),
            Key("RESEARCH_GATEWAY_TOKENS", "loops=example-token-issued-to-the-gen2-engine,mcp=example-token-for-mcp",
                "one bearer token per client; the gateway refuses to start without any"),
            Key("RESEARCH_GATEWAY_WORKERS", "2"),
            Key("RESEARCH_GATEWAY_SECRETS", "env", "env | vault"),
            Key("RESEARCH_GATEWAY_LANE_CONCURRENCY", "4", "1 restores the serial lane loop", commented=True),
            Key("RESEARCH_GATEWAY_LANE_TOTAL", "16", "aggregate lanes in flight across all requests", commented=True),
            Key("RESEARCH_GATEWAY_NTFY_URL", "https://ntfy.example.org", commented=True),
            Key("RESEARCH_GATEWAY_NTFY_TOPIC", "gen2-research-gateway", commented=True),
        ),
    ),
    Group(
        "Gateway secrets, vault backend",
        ("Selected with RESEARCH_GATEWAY_SECRETS=vault. RESEARCH_GATEWAY_VAULT_TOKEN_FILE is REQUIRED",
         "explicitly: unset, the gateway's VaultBackend falls back to ~/.vault-token, which in a container",
         "resolves somewhere nobody chose and makes a missing token file indistinguishable from a missing",
         "key. That is the 2026-09-21..24 outage (DEPLOYMENT-CONTRACT.md §3.3)."),
        (
            Key("RESEARCH_GATEWAY_VAULT_ADDR", "https://vault.example.org:8200", commented=True),
            Key("RESEARCH_GATEWAY_VAULT_TOKEN_FILE", "/run/secrets/gateway-vault-token",
                "mounted read-only, 0400, its own path", commented=True),
            Key("RESEARCH_GATEWAY_VAULT_MOUNT", "secret", commented=True),
            Key("RESEARCH_GATEWAY_VAULT_PREFIX", "services", commented=True),
            Key("RESEARCH_GATEWAY_VAULT_ALIASES", "api_data_gov=api-data-gov",
                "logical=vault-name, when paths differ", commented=True),
        ),
    ),
)
SOURCE_SECRETS_TITLE = "Research source keys — GENERATED FROM THE REGISTRY"


def _wrap_comment(text: str, width: int = 96) -> list[str]:
    words, lines, line = text.split(), [], "#"
    for word in words:
        if len(line) + 1 + len(word) > width and line != "#":
            lines.append(line)
            line = "#   " + word
        else:
            line = f"{line} {word}"
    lines.append(line)
    return lines


def render_env_example(sources: list[dict]) -> str:
    out: list[str] = [
        f"# {ENV_EXAMPLE} — GENERATED by tools/gen_source_catalog.py. Do not edit by hand.",
        "#",
        f"# Copy to deploy/gen2.env (gitignored), fill in real values, mount it read-only and 0400 into the",
        "# gen-2 containers that need it. Example values only — nothing here is a real credential.",
        "#",
        f"# The research source keys at the end are derived from {REGISTRY},",
        "# which is the one source of truth. `make gen2-catalog` regenerates this file and",
        f"# {CATALOG}; `make gen2-check` fails if either drifts from the registry, or if this",
        "# file was edited by hand.",
        "#",
        "# This is the GEN-2 stack's environment. It is never pointed at the running gen-1 gateway service",
        "# or its database (docs/gen2/DEPLOYMENT-CONTRACT.md, \"Hard boundary against gen-1\").",
        "#",
        "# Trace: task 0c deliverable 2; DEPLOYMENT-CONTRACT.md §3; INVARIANTS H-2 (a failed secrets read is",
        "# a dated capability fact, never \"no key configured\").",
    ]
    for group in SERVICE_GROUPS:
        out += ["", f"# {'=' * 96}", f"# {group.title}", f"# {'=' * 96}"]
        for note in group.notes:
            out.append(f"# {note}")
        for key in group.keys:
            if key.comment:
                out += _wrap_comment(key.comment)
            out.append(f"{'# ' if key.commented else ''}{key.var}={key.value}")
    secrets = secrets_of(sources)
    by_id = {s["id"]: s for s in sources}
    out += [
        "",
        f"# {'=' * 96}",
        f"# {SOURCE_SECRETS_TITLE}",
        f"# {'=' * 96}",
        "# One variable per secret a source needs. Every entry below exists because a registry row says the",
        "# source reads it; nothing is listed from memory and nothing a row needs is omitted. Optional",
        "# credentials are emitted commented out: the source works without them, at its unauthenticated",
        f"# limits. Per-source acquisition instructions are in {CATALOG}.",
        "#",
        "# A read that FAILS (403, unreachable vault, unreadable token file) is a dated",
        "# `secrets backend failing` capability fact. A read that SUCCEEDS AND FINDS NOTHING is \"no secret",
        "# configured\". The two are never collapsed, and neither ever becomes searched_empty or a zero.",
    ]
    for kind, members in by_kind(sources):
        kind_secrets = [s for s in secrets if any(by_id[sid]["kind"] == kind for sid in s.source_ids)]
        if not kind_secrets:
            continue
        out += ["", f"# ---- {KIND_TITLES[kind]} " + "-" * max(0, 92 - len(KIND_TITLES[kind]))]
        for s in kind_secrets:
            names = ", ".join(s.source_names)
            field = f" field `{s.field}`" if s.field else ""
            out += _wrap_comment(f"{names} [{', '.join(s.source_ids)}]{field} — "
                                 f"{'required' if s.required else 'OPTIONAL (higher limits)'}. {s.key_instructions}")
            out.append(f"{'' if s.required else '# '}{s.var}=example-{s.secret_ref.replace('_', '-')}"
                       f"{'-' + s.field.replace('_', '-') if s.field else '-key'}")
    return "\n".join(out).rstrip() + "\n"


# ------------------------------------------------------------------------ main

def first_difference(current: str, expected: str) -> str:
    cur, exp = current.splitlines(), expected.splitlines()
    for i, (a, b) in enumerate(zip(cur, exp), start=1):
        if a != b:
            return f"line {i}: committed {a!r} != generated {b!r}"
    if len(cur) != len(exp):
        longer, which = (cur, "committed") if len(cur) > len(exp) else (exp, "generated")
        return f"line {min(len(cur), len(exp)) + 1}: only the {which} file has {longer[min(len(cur), len(exp))]!r}"
    return "files differ only in trailing bytes"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="repository root the default paths resolve against")
    parser.add_argument("--registry", type=Path, help=f"default <root>/{REGISTRY}")
    parser.add_argument("--catalog", type=Path, help=f"default <root>/{CATALOG}")
    parser.add_argument("--env", type=Path, help=f"default <root>/{ENV_EXAMPLE}")
    parser.add_argument("--check", action="store_true", help="exit 1 if either artifact disagrees with the registry")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    registry = (args.registry or root / REGISTRY).resolve()
    catalog = (args.catalog or root / CATALOG).resolve()
    env = (args.env or root / ENV_EXAMPLE).resolve()

    try:
        sources = read_registry(registry)
    except (OSError, tomllib.TOMLDecodeError, RegistryError) as exc:
        print(f"CATALOG ERROR: cannot read the source registry {registry}: {exc}", file=sys.stderr)
        return 2
    problems = validate(sources)
    if problems:
        print(f"CATALOG ERROR: {registry} cannot produce a complete catalog and .env example:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    artifacts = ((catalog, render_catalog(sources)), (env, render_env_example(sources)))
    if args.check:
        stale = []
        for path, expected in artifacts:
            if not path.exists():
                stale.append(f"{path} does not exist")
            else:
                current = path.read_text(encoding="utf-8")
                if current != expected:
                    stale.append(f"{path} disagrees with {registry.name}: {first_difference(current, expected)}")
        if stale:
            print("CATALOG DRIFT: the registry and its generated artifacts disagree:", file=sys.stderr)
            for entry in stale:
                print(f"  - {entry}", file=sys.stderr)
            print("regenerate with: make gen2-catalog", file=sys.stderr)
            return 1
        print(f"source catalog OK: {len(sources)} sources, {len(secrets_of(sources))} secret variables; "
              f"{catalog.name} and {env.name} match the registry")
        return 0
    for path, text in artifacts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
