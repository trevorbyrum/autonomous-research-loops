"""The loops' local tool: an MCP server over stdio that forwards to the gateway's HTTP API.

Mounted by a station via --mcp-config exactly like the read-only GitHub tool:
  {"research": {"type": "stdio", "command": "python3", "args": ["-m", "research_gateway.clients.mcp_stdio"]}}
Environment: RESEARCH_GATEWAY_URL (default http://127.0.0.1:8765) and
RESEARCH_GATEWAY_TOKEN or RESEARCH_GATEWAY_TOKEN_FILE. Newline-delimited JSON-RPC 2.0; no third-party deps.
"""
from __future__ import annotations

import json
import sys

from .http_client import GatewayClient, from_env

STR, INT, BOOL, OBJ = {"type": "string"}, {"type": "integer"}, {"type": "boolean"}, {"type": "object"}
COMMON = {"domain": {**STR, "description": "finance|market|social|management|ai-ml|software|biomed|other (default other)"},
          "commercial": {**BOOL, "description": "true when the topic's output may be used commercially: deny/unknown sources are skipped"},
          "accept_per_item": {**BOOL, "description": "with commercial=true, also use per-item-licensed sources and keep only allow-listed records"},
          "topic_id": STR}
TOOLS = [
    ("research_find", "Search articles and datasets across the registry's lanes for a domain; deduplicated, with provenance and capability facts.",
     {"query": STR, "kind": {**STR, "description": "article|dataset (default both)"}, "limit": INT, "year_from": INT,
      "published_after": {**STR, "description": "ISO date; within 30 days skips the local index"}, **COMMON}, ["query"]),
    ("research_resolve", "Look up one identity (doi:, arxiv:, issn:, hf:, openml:, ...) at the registry that owns it, with fallbacks.",
     {"identity": STR, **COMMON}, ["identity"]),
    ("research_enrich", "Citations, references, open-access location or full text link for an identity.",
     {"identity": STR, "what": {**STR, "description": "citations|references|oa_location|full_text|metadata"}, **COMMON}, ["identity", "what"]),
    ("research_fetch", "List a dataset's or document's files (or download one) from a registry source: doi:, hf:, kaggle:, openml:, socrata:, govinfo:, url:.",
     {"target": STR, "params": {**OBJ, "description": "adapter options, e.g. {\"download\": true, \"file_id\": 123}"}, **COMMON}, ["target"]),
    ("research_data", "A statistical series/table from exactly one source: fred|bea|census|bls|bis|ecb, with source-native params.",
     {"source": STR, "params": OBJ, **COMMON}, ["source", "params"]),
    ("research_status", "Gateway health, breaker states, budgets, cache and queue counts.", {}, []),
]


def tool_specs() -> list[dict]:
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, "required": r}} for n, d, p, r in TOOLS]


REQUEST_TOOLS = {"research_find": "find", "research_resolve": "resolve", "research_enrich": "enrich",
                 "research_fetch": "fetch", "research_data": "data"}


def strip_bytes(out: dict) -> dict:
    """A download's bytes are reported, never dumped into a model context."""
    if isinstance(out.get("content"), (bytes, bytearray)):
        return {**out, "content": None, "content_bytes": len(out["content"])}
    return out


def call_tool(client: GatewayClient, name: str, args: dict) -> dict:
    """Tool dispatch for the stdio server: everything goes over HTTP to the gateway."""
    if name == "research_status":
        return client.status()
    if name not in REQUEST_TOOLS:
        raise LookupError(name)
    return strip_bytes(client.request(REQUEST_TOOLS[name], args))


def handle(msg: dict, call) -> dict:
    """One JSON-RPC request → result. `call(name, args)` performs the tool; shared by the
    stdio server (HTTP-backed) and the gateway's own MCP endpoint (in-process)."""
    method = msg.get("method")
    if method == "initialize":
        return {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}}, "serverInfo": {"name": "research-gateway", "version": "0.1"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_specs()}
    if method == "tools/call":
        params = msg.get("params") or {}
        try:
            result = call(params.get("name", ""), params.get("arguments") or {})
            is_error = str(result.get("capability_fact", "")).startswith("gateway_")
            return {"content": [{"type": "text", "text": json.dumps(result, indent=1, default=str)}], "isError": is_error}
        except LookupError as e:
            return {"content": [{"type": "text", "text": f"error: unknown tool {e}"}], "isError": True}
        except Exception as e:  # tool errors go back in-band, never crash the server
            return {"content": [{"type": "text", "text": f"error: {type(e).__name__}: {e}"}], "isError": True}
    raise LookupError(method)


def main() -> int:
    client = from_env()
    call = lambda name, args: call_tool(client, name, args)  # noqa: E731 - the one binding of tools to transport
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if "id" not in msg:  # notification
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg, call)}
        except LookupError:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": f"method not found: {msg.get('method')}"}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
