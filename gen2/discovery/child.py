"""The supervised discovery child: the ONE place a GatewayClient is constructed and `resolve()` is called.

Trace: 2e2-min design O13.3; INVARIANTS H-6, RG-4; DEBT-001 (construction and resolve() only inside a supervised job
child, so the job deadline bounds the name lookup) and DEBT-002 (this child's client is its own, used serially);
the wrapper names (`inputs/input.json` read, `outcome.json` written in scratch). Oracle: the gateway client's own
observations; the child adds none. Limits: it records nothing in the router (the station's recorder does, from
`discovery-result.json`), picks no search, and a search that raises is not retried: the job fails and an operator
requeues (L-6), because a zero-result stand-in would be a false negative. The entry (`main`) builds a client only over a transport its caller injects: the ordinary `python -m` route refuses (pre-T19 fence). Every observation is stamped with its proposal's identity (stamp.py). The result is parsed JSON the client
returned, not transport octets.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Mapping, Sequence

from gen2.core import canonical
from gen2.discovery import requests, stamp
from gen2.exec import orders
from gen2.exec.common import Refused, outcome_bytes, scaffold
from gen2.gateway_client.client import GatewayClient, GrantRefused

RESULT, OUTCOME = "discovery-result.json", "outcome.json"
URL, TOKEN_FILE = "GEN2_GATEWAY_URL", "GEN2_SECRET_GATEWAY_TOKEN_FILE"   # the token is a file the supervisor mounts, never a value in order.json


def run(directory: Path, *, environ: Mapping[str, str], validate: Callable[[str, object], None],
        factory: Callable[[str, str], GatewayClient]) -> Path:
    """Run the proposals in `directory/inputs/input.json` one after another; returns the result path."""
    root = Path(directory)
    try:
        raw = (root / orders.INPUT_DIR / orders.INPUT).read_bytes()
    except OSError as error:
        raise Refused(f"input.json unreadable: {error.strerror}") from None
    if canonical.bytes_digest(raw) != environ.get("GEN2_INPUT_DIGEST"):
        raise Refused("input.json does not match the order's digest")
    work = canonical.parse_json_strict(raw)
    if (work["kind"], work["purpose"]) != ("discovery", "search"):
        raise Refused("input.json is not a discovery/search input")
    view, invocation_id = work["view"], work["invocation_id"]
    if {"proposals", "proposed_by"} & set(view):
        raise Refused("proposals and their proposer come from the committed outcome only, never beside it")
    committed = requests.intake(view["committed"]["payload"].encode(), view["committed"]["receipt"], work["topic_id"], work["limits"]["max_input_bytes"], validate)
    built = [(p, requests.gateway_request(p)) for p in committed.proposals]   # every request is built before any I/O
    try:
        token = Path(environ[TOKEN_FILE]).read_text(encoding="utf-8").strip()
    except (KeyError, OSError) as error:
        raise Refused(f"the gateway token file is unreadable: {type(error).__name__}") from None
    client = factory(environ[URL], token)
    gateway = view["gateway"]
    grant = client.grant(topic_id=work["topic_id"], commercial=gateway["commercial"],
                         accept_per_item=gateway["accept_per_item"], invocation_id=invocation_id)
    searches = []
    for proposal, request in built:
        if client.endpoint_stale:
            client.resolve()
        out = client.search(request, invocation_id=invocation_id, attempt=view["attempt"], policy_version=gateway["policy_version"],
                            obligation_ids=proposal["obligation_ids"], pages=requests.pages(proposal), token=grant["token"])
        stamp.stamp(out, stamp.ref_of(committed.invocation_id, proposal["proposal_id"]), invocation_id=invocation_id, attempt=view["attempt"])
        searches.append({"proposal_id": proposal["proposal_id"], "out": out})
    resolution = client.last_resolution
    document = {"result_version": "discovery-result/1", "invocation_id": invocation_id, "attempt": view["attempt"],
                "diagnostics": {"resolution": None if resolution is None else {**resolution._asdict(), "addresses": list(resolution.addresses)}},
                "searches": searches}
    try:
        data = canonical.canonical_bytes(document)
    except canonical.CanonicalizationError as error:
        raise Refused(f"the gateway's answers are not canonical JSON: {error}") from None
    if len(data) > work["limits"]["max_output_bytes"]:
        raise Refused("discovery-result.json is over the output cap")
    (root / RESULT).write_bytes(data)
    path = root / OUTCOME
    path.write_bytes(outcome_bytes(scaffold(invocation_id, work["topic_id"])))   # empty: discovery commits no scientific section
    return path


def main(argv: Sequence[str], *, env: Mapping[str, str] | None = None, validate: Callable[[str, object], None] | None = None,
         transport: Callable | None = None) -> int:
    """`python -m gen2.discovery.child <scratch>`: read the pinned input, run the proposals, write `discovery-result.json` and `outcome.json`; 0, or 2
    with a named reason and nothing written. THE PRE-T19 FENCE: the client is built only over a `transport` the caller injects; the ordinary
    route (no transport) never builds a client from environment credentials, so it reaches no gateway: live use is refused until T19 opens it
    deliberately. Offline, the caller (T18's entry) injects the canned gateway and the schema check."""
    env = os.environ if env is None else env
    try:
        if len(argv) != 1:
            raise Refused("usage: gen2.discovery.child <scratch>")
        if transport is None or validate is None:
            raise Refused("the live gateway entrance is closed: this child runs only over an injected transport (pre-T19)")
        run(Path(argv[0]), environ=env, validate=validate, factory=lambda url, token: GatewayClient(url, token, transport=transport))
    except (Refused, KeyError, TypeError, OSError, ValueError, GrantRefused) as error:
        print(f"gen2.discovery.child: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
