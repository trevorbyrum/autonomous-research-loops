"""Task 2q-b1: the gateway mutants of the executor's own client interface (core/router.py `LaneClient`).

The router, in core, used to import `Client` from adapters.base, which made core depend on the adapters that depend on it. It now declares what it needs of the client as a protocol, and
tests/test_core_foundations.py keeps that protocol true in both directions, for the fields and the methods it declares alike (task 2q-t2; DEBT-019 NB-1: the test reads both from the
protocol's class body, so no member is listed in the test). The mutants break one direction each in a temporary copy:

  L-lane-client-omits-a-member     the executor uses `client.topic` and the protocol no longer declares it;
  L-lane-client-omits-a-method     the executor calls `client.correlation()` and the protocol no longer declares it;
  L-lane-client-declares-a-ghost   the protocol declares a member no client has;
  L-lane-client-declares-a-ghost-method   the protocol declares a method no client has.

A killer fails in its assertion and the other direction's test is its paired control (it passes under the mutant).
"""
from __future__ import annotations

ROUTER = "research_gateway/core/router.py"
CF = "tests.test_core_foundations.ExecutorClientInterface."
USED, REAL = CF + "test_every_client_member_the_executor_uses_is_declared", CF + "test_control_every_declared_member_is_one_a_real_client_has"


def build(Mutant) -> list:
    """The mutants (tools/gen2_gateway_mutants.py: `Mutant`)."""
    return [
        Mutant("L-lane-client-omits-a-member", "the protocol no longer declares a member of the client the executor uses", ROUTER,
               "    request_identity: str | None\n    secret_values: set\n    topic: str | None\n", "    request_identity: str | None\n    secret_values: set\n", (USED,), (REAL,)),
        Mutant("L-lane-client-declares-a-ghost", "the protocol declares a member no client has", ROUTER,
               "    request_identity: str | None\n    secret_values: set\n    topic: str | None\n", "    request_identity: str | None\n    secret_values: set\n    topic: str | None\n    ghost: str | None\n",
               (REAL,), (USED,)),
        Mutant("L-lane-client-omits-a-method", "the protocol no longer declares a method of the client the executor calls", ROUTER,
               "    topic: str | None\n\n    def correlation(self) -> dict: ...\n", "    topic: str | None\n", (USED,), (REAL,)),
        Mutant("L-lane-client-declares-a-ghost-method", "the protocol declares a method no client has", ROUTER,
               "    def correlation(self) -> dict: ...\n", "    def correlation(self) -> dict: ...\n    def ghost(self) -> None: ...\n", (REAL,), (USED,)),
    ]
