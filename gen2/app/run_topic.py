"""The operator's command that walks one topic on the running engine: call `walk` until the next move is the operator's or the walk stops.

Trace: process map v1 gap 3; Astra live-hosting design review (one outstanding call, fixed replies, no local store access); the T17 brief
(the driver only wires and prints). The engine owns the store and the supervisor, so this client opens nothing: it asks the engine's
operator listener for one tick at a time. Oracle: the engine's reply words; the completion hand-off prints the reviewed status block.
Limits: an answer that never comes (timeout, cut connection, not JSON) is ambiguous, so it stops and says to reconcile from status; it is
never repeated automatically. Exit 0 at a wait or done, 2 for a bad call, no answer or a refusal, 3 for a stopped walk.
"""
from __future__ import annotations

import http.client
import json
import os
import sys
import time
from typing import Callable, Mapping, Sequence
from urllib.parse import urlencode

from gen2.app import cli, workflow

COMMANDS = {"apply_operator_decision kind=brief_confirmation", "apply_operator_decision kind=scope_approval",
            "apply_operator_decision kind=contract_approval", "apply_operator_decision kind=completion_approval", "open_review"}
STOPS = {"hold_open": "an open hold stops the walk; clear it, then run this again", "needs_person": "a step needs a person (see status)",
         "contract_changed": "work from another contract revision has not settled", "budget": "the scoping rounds are spent",
         "topic_blocked": "the topic is held, blocked or retired", "live_not_authorized": "a live step needs --live on this run", "live_refused": "live dispatch refused: this station has no qualified live profile (see the runbook)", "refused": "an input was refused", "io": "a file operation failed",
         "malformed": "a record was malformed", "step_failed": "a step failed", "step_unknown": "a step's outcome is unknown", "step_held": "a step is held"}
NO_ANSWER = "no answer from the engine; the tick may or may not have run: check status before running this again"
MAX_CALLS = 1000


def main(argv: Sequence[str], *, environ: Mapping[str, str] = os.environ, call: Callable = cli.request, say: Callable[[str], None] = print,
         sleep: Callable[[float], None] = time.sleep) -> int:
    if len(argv) not in (1, 2) or (len(argv) == 2 and argv[1] != "--live"):
        say("usage: gen2.app.run_topic <topic> [--live]")
        return 2
    topic, live = argv[0], len(argv) == 2   # --live is this run's permission to start live work; every call carries it, nothing stores it
    url, token = environ.get("GEN2_OPERATOR_URL", "http://127.0.0.1:8770"), environ.get("GEN2_OPERATOR_TOKEN")

    def ask(method: str, path: str, body: bytes | None = None):
        try:
            code, reply = call(url, token, method, path, body)
        except (OSError, ValueError, http.client.HTTPException):
            say(NO_ANSWER)
            return None
        if code != 200 or not isinstance(reply, dict) or not isinstance(reply.get("status"), str):
            say("the engine refused the request")
            return None
        return reply
    for _ in range(MAX_CALLS):
        reply = ask("POST", "/v1/commands/walk", json.dumps({"topic_id": topic, **({"live": True} if live else {})}).encode())
        if reply is None or reply["status"] == "refused":
            if reply is not None:
                say("the engine refused the request")
            return 2
        if reply["status"] == "stopped":
            say(f"stopped: {STOPS.get(reply.get('code'), 'the walk stopped')}")
            return 3
        action = reply.get("action")
        if action == "done":
            say("done")
            return 0
        if action == "stop":
            say(f"stopped: {STOPS.get(reply.get('code'), 'the walk stopped')}")
            return 3
        if action == "wait" and reply.get("command") in COMMANDS:
            return _wait(ask, topic, reply["command"], say)
        if action not in ("issue", "advance"):
            say("the engine's reply was not understood")
            return 2
        sleep(1.0)
    say("still working; run this again")
    return 0


def _wait(ask, topic: str, command: str, say) -> int:
    shown = None
    if command == "apply_operator_decision kind=completion_approval":   # the operator reads the review and its evidence from the reviewed status block first
        status = ask("GET", "/v1/status?" + urlencode({"topic": topic}))
        topics = status.get("topics") if isinstance(status, dict) else None
        shown = topics[0].get("review") if topics else None
        if not (shown and shown.get("approvable")):
            say("stopped: cannot show the review for approval: the status carries no sufficiency review for the latest dossier")
            return 3
    say(workflow.waiting_line(workflow.Wait("the next move is the operator's", command), shown))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
