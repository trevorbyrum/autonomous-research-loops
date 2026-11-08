"""Supervised live operands: derive public policy from retained pinned bytes.

No filesystem, credential acquisition, launcher or qualification authority.
"""
import hashlib
import ipaddress
import re

RELAY_SHA = "aa8cfe6647b72fee6ddb883cbe7264ec730d9f1a6f53266e31a8e62c3ad642a5"
CONFIG_SHA = "f14d75f89c958edde311e0cbb5d90e83b68517c0cc720920641bc3ec5fbe6f4e"


def pinned(data, expected):
    if not isinstance(data, bytes) or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("stale public policy operand")
    return data.decode("utf-8")


def runner_config(offline):
    """The reviewed live seed disables tools; configuration is not model observation."""
    return pinned(offline, CONFIG_SHA).replace("shell_tool = true", "shell_tool = false").replace(
        "unified_exec = true", "unified_exec = false").encode()


def relay_config(view):
    """Use only carried public operands; the operator separately approves this fixed IP."""
    base = pinned(view["fixture_relay"], RELAY_SHA)
    upstream = str(ipaddress.IPv4Address(view["provider_ip"]))
    base = base.replace("client_max_body_size 1m;", "client_max_body_size 128k;\n"
                        "    limit_req_zone $binary_remote_addr zone=model:1m rate=1r/m;\n"
                        "    limit_req_status 429;")
    base = base.replace("proxy_pass http://172.31.252.3:8081/v1/responses;",
                        "limit_req zone=model nodelay;\n"  # omitted burst means B=0
                        f"            proxy_pass https://{upstream}:443/v1/responses;\n"
                        "            proxy_ssl_server_name on;\n"
                        "            proxy_ssl_name api.openai.com;\n"
                        "            proxy_ssl_verify on;\n"
                        "            proxy_ssl_trusted_certificate /etc/gen2/provider-ca.pem;\n"
                        "            proxy_ssl_protocols TLSv1.2 TLSv1.3;")
    return base.replace("proxy_set_header Authorization $http_authorization;",
                        "include /etc/gen2/provider-auth.conf;").replace(
        'proxy_set_header Host "172.31.252.3:8081";', 'proxy_set_header Host "api.openai.com";').encode()


def secret_include(key):
    """Operator provisioning only: constrained syntax, fixed diagnostics, never a secret hash."""
    if not isinstance(key, bytes) or not re.fullmatch(rb"[A-Za-z0-9_-]{20,256}", key):
        raise ValueError("invalid relay credential syntax")
    return b'proxy_set_header Authorization "Bearer ' + key + b'";\n'
