"""DEBT-001/002 inventory (H-6): in gen2 outside tests, a GatewayClient is constructed, and its resolve() called, only in the
supervised discovery child. Oracle: an AST scan, paired with a synthetic second site that it must find. Limits: a static name
scan; reflection and aliasing are review's. `resolve()` is looked for only in files that import the gateway client, because
pathlib's resolve() is everywhere else, and the client's own package is the definition, not a site."""
import ast
import unittest
from pathlib import Path

from gen2.tests import children

ROOT = Path(children.path("gen2"))
ALLOWED = {"gen2/discovery/child.py"}
SKIP = ("tests/", "gateway_client/")


def sites(source: str) -> list[str]:
    tree = ast.parse(source)
    imports_client = any((isinstance(n, ast.ImportFrom) and "gateway_client" in (n.module or "")) or
                         (isinstance(n, ast.Import) and any("gateway_client" in a.name for a in n.names)) for n in ast.walk(tree))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else None
        if name == "GatewayClient" or (name == "resolve" and imports_client and not node.args and not node.keywords):
            found.append(name)
    return found


class ClientSitesTest(unittest.TestCase):
    def test_production_sites_are_only_the_discovery_child(self):
        found = {}
        for path in sorted(ROOT.rglob("*.py")):
            relative = path.relative_to(ROOT.parent).as_posix()
            if any(part in relative for part in SKIP):
                continue
            if (hit := sites(path.read_text())):
                found[relative] = hit
        self.assertEqual(set(found), ALLOWED, found)
        self.assertEqual(sorted(found["gen2/discovery/child.py"]), ["GatewayClient", "resolve"])

    def test_the_scan_finds_a_second_construction_and_a_resolve_call(self):
        self.assertEqual(sites("from gen2.gateway_client.client import GatewayClient\nc = GatewayClient('u', 't')\nc.resolve()\n"), ["GatewayClient", "resolve"])
        self.assertEqual(sites("import gen2.gateway_client.client as g\ng.GatewayClient('u', 't')\n"), ["GatewayClient"])

    def test_resolve_elsewhere_is_not_a_client_call(self):
        self.assertEqual(sites("from pathlib import Path\nPath('.').resolve()\n"), [])
        self.assertEqual(sites("from gen2.gateway_client import client\nname.resolve(host)\n"), [])
