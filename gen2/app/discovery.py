"""Live discovery composition (H-6, RG-2/4; DEBT-001/002/057).
The supervised child alone constructs its per-job client and bounds lookup by job termination.
"""
import sys

from gen2.app.walk import validate
from gen2.discovery import child
from gen2.gateway_client.client import http_transport


def main(argv):
    return child.main(argv, validate=validate, transport=http_transport)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
