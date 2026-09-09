"""Lease-scoped checkpoint delegate broker entry point.

The controller imports :func:`dispatch` after it has authenticated the execution
capability.  The command-line form sends the same request over that controller;
it never opens the SQLite store as an agent process.
"""
from __future__ import annotations

import argparse
import os
from typing import Any, Mapping

from .service import execute_delegate


def dispatch(control: Any, params: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(params, Mapping) or set(params) != {"episode_id", "lease_id", "invocation_id", "role", "prompt"}:
        raise ValueError("checkpoint.delegate requires episode_id, lease_id, invocation_id, role, prompt")
    return execute_delegate(control, **dict(params))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episode-id", required=True); parser.add_argument("--lease-id", required=True)
    parser.add_argument("--invocation-id", required=True); parser.add_argument("--role", required=True)
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args(argv)
    socket_path, token = os.environ.get("RESEARCH_LOOP_CONTROLLER_SOCKET"), os.environ.get("RESEARCH_LOOP_EXECUTION_CAPABILITY")
    if not socket_path or not token: parser.exit(2, "checkpoint delegate requires a managed controller capability\n")
    from ..controller_client import call
    result = call(socket_path, "checkpoint.delegate", {"episode_id": args.episode_id, "lease_id": args.lease_id,
                  "invocation_id": args.invocation_id, "role": args.role, "prompt": args.prompt}, token=token)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
