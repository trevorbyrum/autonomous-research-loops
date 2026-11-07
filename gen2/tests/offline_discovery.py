"""The offline discovery child: `python -m gen2.tests.offline_discovery <directory>`, the production discovery entry over the canned gateway.

Not collected as tests. It is gen2.discovery.child.main with the canned gateway injected as the client's transport and the schema check
injected: the real client, request builder, intake and stamping run; only the network is replaced. `GEN2_OFFLINE_COUNTER` picks how a
counterevidence search goes (empty, found, degraded). The driver's `discovery_module` names it; the production module refuses to run
without an injected transport until T19.
"""
import os
import sys

from gen2.discovery import child
from gen2.router.schemas import SchemaSet
from gen2.tests.offline_gateway import OfflineGateway


def validate(name, document):
    errors = SchemaSet().errors(document, name + ".schema.json")
    if errors:
        raise child.Refused(f"{name}: {errors[0]}")


if __name__ == "__main__":
    sys.exit(child.main(sys.argv[1:], validate=validate, transport=OfflineGateway(counter=os.environ.get("GEN2_OFFLINE_COUNTER", "empty"))))
