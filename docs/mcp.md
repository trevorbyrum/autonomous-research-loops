# The MCP server: the engine as agent-callable tools

`research-loops-mcp` exposes the engine's control plane over the Model
Context Protocol, so any MCP-capable session — a local harness, or a
phone/web session reaching through an MCP gateway — can inspect and (when
explicitly granted) operate the queue.

```bash
pip install research-loops[mcp]     # the engine's only optional dependency
research-loops-mcp --root /path/to/deployment                  # stdio, read-only
research-loops-mcp --root /path/to/deployment --operator       # stdio, full surface
research-loops-mcp --root /path/to/deployment --operator \
    --http --host 192.168.x.x --port 8321                      # HTTP, for gateways
```

## Two tiers, gated by the instance — never by the model

| Tier | Tools | Who gets it |
| --- | --- | --- |
| read-only (always) | `queue_status`, `topic_state`, `doctor`, `recent_events`, `usage_summary` | any operator-facing session |
| operator (`--operator`) | `pause_topic`/`resume_topic`/`pause_all`/`resume_all`, `move_topic`, `restart_topic`, `swap_active`, `set_agents`, `refresh_topic`, `relock_topic`, `draft_topic`, `read_draft`, `approve_and_queue` | sessions the human explicitly configured for queue control |

A read-only instance does not *register* the operator tools, so a session
attached to it cannot reach them no matter what the model is asked to do —
the gate lives in harness/gateway configuration, outside the conversation.

**Never attach either tier to a research iteration.** The loops need no
queue awareness, and CONTRACT-CORE forbids a research agent from reshaping
scope or scheduling. This server is for operator sessions and meta-tooling.

## Transports

- **stdio** (default): the harness spawns the server as a child process.
  Client and server must share a host — stdio cannot cross machines.
- **streamable HTTP** (`--http`): for MCP gateways, which federate external
  servers by URL, and for any remote client. An operator-tier HTTP endpoint
  mutates a live queue: bind it to a trusted interface only and put it
  behind your gateway's authentication; never expose it raw.

Both transports serve the same tool definitions from the same module.

## The remote authoring flow (add a topic from your phone)

Through a gateway-federated operator instance:

1. `draft_topic(topic_id, title, brief)` — scaffolds DRAFT files and returns
   the obligations parsed from the brief. Re-call with a refined brief to
   overwrite; nothing is binding yet.
2. `read_draft(topic_id)` — review the full draft contract in chat.
3. `approve_and_queue(topic_id, confirm=topic_id, position=...)` — promotes
   the draft (binding obligations + pinned completion lock, exactly like
   `research-loops approve-topic`), registers the queue item with the fleet
   defaults, and optionally positions it. Because this mints binding scope,
   `confirm` must repeat the topic id verbatim; anything else is refused.

`relock_topic` is the same sanctioned re-pin path as the `relock` CLI
command; both share `topic_authoring.compute_lock()` so their lock
semantics cannot drift.

## Example harness registration (stdio, read-only)

```json
{
  "mcpServers": {
    "research-loops": {
      "command": "research-loops-mcp",
      "args": ["--root", "/path/to/deployment"]
    }
  }
}
```

Add `"--operator"` to args only in sessions that should hold queue control.
