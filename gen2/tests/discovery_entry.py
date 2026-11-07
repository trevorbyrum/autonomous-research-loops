"""A `python -m` entry for the discovery child over the test suite's canned gateway: `python -m gen2.tests.discovery_entry <scratch>`.

Not collected as tests. It is gen2.discovery.child.main with the canned `Gateway` (test_discovery_child) injected as the transport and the schema
check injected, which is exactly what an offline caller must do: the production module itself refuses to run without a transport (pre-T19).
"""
import sys

from gen2.discovery import child
from gen2.tests.test_discovery_child import Gateway, validate

if __name__ == "__main__":
    sys.exit(child.main(sys.argv[1:], validate=validate, transport=Gateway()))
