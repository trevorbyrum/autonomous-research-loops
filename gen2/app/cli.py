"""The operator CLI (task 1e): a thin client of the engine's listener — the same
routes, the same service, no second code path.

Trace: design review §10 ("CLI/MCP/API operations behind one command
service"); DEPLOYMENT-CONTRACT.md §1.1 (operator clients on the host reach
127.0.0.1:8770 with an operator token); gen2/operator/service.py (the routes).

    python -m gen2.app.cli status [--topic TOPIC_ID]
    python -m gen2.app.cli health
    python -m gen2.app.cli call OPERATION [FILE]     (the JSON body: FILE, or stdin)

OPERATION is a router operation the service routes (apply_operator_decision,
request_cancel, requeue, close_brief, activate_config_bundle, version_brief,
mark_brief_overdue, propose_amendment); the body is sent as it is, and the
service supplies who acts from the token. The engine is GEN2_OPERATOR_URL
(default http://127.0.0.1:8770); the token is GEN2_OPERATOR_TOKEN, read from
the environment and never from the command line, where other users of the
host could read it. The reply is printed as JSON. Exit 0 when the engine
answered and the operation did not refuse; 1 when it refused (the reply's
status is refused or rejected); 2 when there was no answer to give — the
engine unreachable, or the request refused by the transport (401, 403, 404,
400, 413, 5xx). Nothing is retried: a lost reply is sent again by running the
same command, which every operation replays under its key.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlencode, urlsplit

REFUSED = ("refused", "rejected")


def request(url: str, token: str | None, method: str, path: str, body: bytes | None = None, *, timeout: float = 60.0) -> tuple[int, dict]:
    """One request to the engine; (HTTP status, the JSON reply). Raises
    OSError when the engine cannot be reached."""
    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        raise ValueError(f"GEN2_OPERATOR_URL must be an http:// URL, not {url!r}")
    connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read() or b"null")
    finally:
        connection.close()


def main(argv: list[str] | None = None, environ=os.environ, stdin=None, stdout=None, stderr=None) -> int:
    stdin, stdout, stderr = stdin or sys.stdin, stdout or sys.stdout, stderr or sys.stderr
    parser = argparse.ArgumentParser(prog="python -m gen2.app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    commands.add_parser("status").add_argument("--topic")
    call = commands.add_parser("call")
    call.add_argument("operation")
    call.add_argument("file", nargs="?")
    args = parser.parse_args(argv)
    url, token = environ.get("GEN2_OPERATOR_URL", "http://127.0.0.1:8770"), environ.get("GEN2_OPERATOR_TOKEN")
    try:
        if args.command == "health":
            code, reply = request(url, None, "GET", "/v1/health")
        elif args.command == "status":
            code, reply = request(url, token, "GET", "/v1/status" + (f"?{urlencode({'topic': args.topic})}" if args.topic else ""))
        else:
            text = Path(args.file).read_text(encoding="utf-8") if args.file else stdin.read()
            code, reply = request(url, token, "POST", f"/v1/commands/{args.operation}", text.encode("utf-8"))
    except (OSError, ValueError) as failure:
        print(f"no answer from the engine at {url}: {failure}", file=stderr)
        return 2
    print(json.dumps(reply, indent=2, sort_keys=True), file=stdout)
    if code != 200:
        print(f"the engine refused the request: HTTP {code}", file=stderr)
        return 2
    return 1 if isinstance(reply, dict) and reply.get("status") in REFUSED else 0


if __name__ == "__main__":
    sys.exit(main())
