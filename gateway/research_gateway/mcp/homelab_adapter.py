"""The homelab MCP gateway front door (PLAN.md §9).

The homelab gateway consumes peer MCP servers listed in its `external-mcp.json`
and exposes their tools as `<peer>_call` / `<peer>_list`. So the research
gateway serves the same five tools itself, as a stateless MCP-over-HTTP endpoint
(`POST /mcp`, one JSON-RPC message per request, bearer token like every other
route), and the operator adds one peer entry pointing at it. Same broker, same
call log, same licence rules as the loops' stdio client (I-1): the only
difference is that tool calls run in-process instead of over HTTP.
"""
from __future__ import annotations

import json

from ..app import Gateway, validate_payload
from ..clients.mcp_stdio import REQUEST_TOOLS, handle, strip_bytes

PEER_NAME = "research"


def make_call(gateway: Gateway, client_id: str):
    """Tool dispatch bound to an in-process gateway for one authenticated client. Arguments go
    through the SAME payload validation as the HTTP door — the MCP door is not a side entrance
    around type checks (D-23)."""
    def call(name: str, args: dict) -> dict:
        if name == "research_status":
            return gateway.status()
        if name not in REQUEST_TOOLS:
            raise LookupError(name)
        problem = validate_payload(args or {})
        if problem:
            return {"capability_fact": "gateway_error_400", "error": problem}
        payload = {**(args or {}), "request_type": REQUEST_TOOLS[name]}
        return strip_bytes(gateway.handle(payload, client_id))
    return call


def rpc(gateway: Gateway, client_id: str, msg: dict) -> dict | None:
    """One JSON-RPC message → reply dict (None for notifications, which have no id)."""
    if not isinstance(msg, dict) or "id" not in msg:
        return None
    try:
        return {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg, make_call(gateway, client_id))}
    except LookupError:
        return {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"method not found: {msg.get('method')}"}}


def peer_entry(url: str, token_env: str = "RESEARCH_GATEWAY_TOKEN") -> str:
    """The `servers` entry the operator adds to the homelab gateway's `external-mcp.json`
    (same shape as its other bearer-authenticated peers). The token itself comes from that
    gateway's own hydrated environment, never from this file."""
    return json.dumps({PEER_NAME: {
        "url": url.rstrip("/") + "/mcp",
        "description": "Research gateway - find/resolve/enrich/fetch/data across the registered research sources, "
                       "rate-limited and licence-aware. Use research_list to see the tools.",
        "enabled": True,
        "auth": {"type": "bearer", "token": "${" + token_env + "}"},
        "transport": "http",
    }}, indent=2)
