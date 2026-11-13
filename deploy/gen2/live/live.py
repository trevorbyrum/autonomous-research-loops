"""Supervised live operands: derive public policy from retained pinned bytes.

No filesystem, credential acquisition, launcher or qualification authority.
"""
import base64
import hashlib
import ipaddress
import json
import re

RELAY_SHA = "0688d2355b9e327d66fa3be1f9b5654275ef333bbe47f28a091749b34eddd276"
CONFIG_SHA = "f14d75f89c958edde311e0cbb5d90e83b68517c0cc720920641bc3ec5fbe6f4e"
CATALOG_SHA = "62d809889367324c104b13a4881e115286085d5674ffa77ab790b48c63002d10"


def pinned(data, expected):
    if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("stale public policy operand")
    return data.decode("utf-8")


def runner_config(offline):
    """The reviewed live seed disables tools; configuration is not model observation."""
    return pinned(offline, CONFIG_SHA).replace("shell_tool = true", "shell_tool = false").replace(
        "unified_exec = true", "unified_exec = false").encode()


def model_catalog(offline):
    """Null disables the independent patch tool; preserve every other catalog value."""
    catalog = json.loads(pinned(offline, CATALOG_SHA))
    model, = [row for row in catalog["models"] if row["slug"] == "gpt-5.4"]
    model["apply_patch_tool_type"] = None
    return json.dumps(catalog, sort_keys=True, ensure_ascii=False, indent=2).encode() + b"\n"


def relay_config(view):
    """Use only carried public operands; the operator separately approves this fixed IP."""
    base = pinned(view["fixture_relay"], RELAY_SHA)
    upstream = str(ipaddress.IPv4Address(view["provider_ip"]))
    base = base.replace("client_max_body_size 1m;", "client_max_body_size 128k;\n"
                        "    limit_req_zone $binary_remote_addr zone=model:1m rate=1r/m;\n"
                        "    limit_req_status 429;")
    base = base.replace("proxy_pass http://172.31.252.3:8081/v1/responses;",
                        "limit_req zone=model nodelay;\n"  # omitted burst means B=0
                        f"            proxy_pass https://{upstream}:443/backend-api/codex/responses;\n"
                        "            proxy_ssl_server_name on;\n"
                        "            proxy_ssl_name chatgpt.com;\n"
                        "            proxy_ssl_verify on;\n"
                        "            proxy_ssl_trusted_certificate /etc/gen2/provider-ca.pem;\n"
                        "            proxy_ssl_protocols TLSv1.2 TLSv1.3;")
    return base.replace("proxy_set_header Authorization $http_authorization;",
                        "include /etc/gen2/provider-auth.conf;\n"
                        # Codex 0.153.2: login/src/auth/default_client.rs DEFAULT_ORIGINATOR;
                        # model-provider-info/src/lib.rs create_openai_provider, workspace version.
                        '            proxy_set_header originator "codex_cli_rs";\n'
                        '            proxy_set_header version "0.153.2";').replace(
        'proxy_set_header Host "172.31.252.3:8081";', 'proxy_set_header Host "chatgpt.com";').encode()


def secret_include(access_token, account_id, *, now, min_remaining_seconds):
    """Freshness precheck only, not JWT authentication; no acquisition, logging or hashing."""
    try:
        if not isinstance(access_token, bytes) or len(access_token) > 8192 or not re.fullmatch(rb"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}", access_token):
            raise ValueError
        parts = access_token.split(b".")
        decoded = [base64.b64decode(p + b"=" * (-len(p) % 4), altchars=b"-_", validate=True) for p in parts]
        if any(base64.urlsafe_b64encode(d).rstrip(b"=") != p for d, p in zip(decoded, parts)):
            raise ValueError
        payload = json.loads(decoded[1])
        exp = payload.get("exp") if isinstance(payload, dict) else None
        if any(type(n) is not int or not 0 <= n <= 253402300799 for n in (exp, now, min_remaining_seconds)) or min_remaining_seconds == 0 or exp - now < min_remaining_seconds:
            raise ValueError
        if not isinstance(account_id, bytes) or not re.fullmatch(rb"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", account_id):
            raise ValueError
    except (ValueError, RecursionError):
        raise ValueError("invalid relay credential") from None
    return (b'proxy_set_header Authorization "Bearer ' + access_token + b'";\n'
            b'proxy_set_header ChatGPT-Account-ID "' + account_id + b'";\n')
