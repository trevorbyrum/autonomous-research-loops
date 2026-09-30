"""Task 2b-repair-5 F2: every read that serves a stored record goes through one gate.

gateway.servable_records (registry/schema.sql) is the one place a stored record is read to be
served. A row not yet converted (an earlier writer's, `restriction_inputs` false) is there only
withheld: its identity and kind, its canonical NULL. A reader can count what it refused and can
never serve it; the lane router turns a withheld match into a partial lane, or one that observed
nothing — never a complete, exhausted answer (tests/test_lane_outcomes.py).

  * OneServingRead reads the SOURCE: production code (research_gateway/**/*.py) names
    gateway.records only to write it, or in the reads NOT_SERVING lists, each with why it serves
    nothing; a new read of the table, on any path, fails here. A statement is a string constant
    (implicit concatenation and f-string literal parts included); a docstring is not one. A
    relation name assembled at run time from pieces is not seen.
  * AssembledGateway is the regression Astra's 2b-repair-4 review asked for, on the running
    service: a gateway started on a database holding no unconverted row; then, after startup,
    the actual historical writers (read from this repository's history) store indexed venues the
    view withholds — f58d802's harvest writer, and gen-1's cache writer (f4a7a5c, the commit the
    live gen-1 gateway runs) with a lead prohibiting redistribution, and its index rebuild —
    beside a current writer's venue. HTTP /v1/find, the HTTP MCP door, a queued job and the stdio
    MCP bridge each serve the current venue only, the lane partial; a search matching only
    withheld rows observes nothing; once migrated, the same doors serve all three, the prohibition
    kept. DB cases need RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database).
"""
from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.request
import uuid
from pathlib import Path

from research_gateway import app
from research_gateway.api import http as api
from research_gateway.adapters.base import FakeTransport
from research_gateway.core import db
from research_gateway.core import identity as ident
from research_gateway.core.canonical import make_record
from research_gateway.harvest import index

HAVE_DB = db.configured() and os.environ.get("RESEARCH_GATEWAY_TEST_OK") == "1"
GATEWAY_DIR = Path(__file__).resolve().parents[1]
PRODUCTION = GATEWAY_DIR / "research_gateway"
RAW = re.compile(r'\bgateway"?\s*\.\s*"?records\b|\b(?:from|join)\s+"?records\b', re.IGNORECASE)
WRITE = re.compile(r"\s*(?:insert|update|delete)\b", re.IGNORECASE)
# the reads of gateway.records that serve nothing, by (file, function), each with why
NOT_SERVING = {
    ("harvest/index.py", "IssnMap.__init__"): "the loader's ISSN map: which identity a harvested record is written to",
    ("harvest/index.py", "upsert"): "the harvest writer merging into the row it rewrites",
    ("harvest/index.py", "reindex"): "rebuilding the index's search terms; a search serves records through the gate",
    ("harvest/index.py", "counts"): "the operator's row counts (--counts)",
    ("registry/migrate.py", "migrate"): "the conversion itself, of the rows the gate withholds",
    ("app.py", "Gateway.health"): "the planner's estimate of the table's size, from pg_class: no row is read",
}


def statements(tree: ast.AST) -> list[tuple[str, str]]:
    """(the function holding it, its text) for every string that is not a docstring; an
    f-string's literal parts are joined, each value as {}."""
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str)}
    found: list[tuple[str, str]] = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                visit(child, (*scope, child.name))
            elif isinstance(child, ast.JoinedStr):
                found.append((".".join(scope), "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in child.values)))
            elif isinstance(child, ast.Constant) and isinstance(child.value, str) and id(child) not in docs:
                found.append((".".join(scope), child.value))
            else:
                visit(child, scope)
    visit(tree, ())
    return found


def raw_reads(root: Path = PRODUCTION) -> list[tuple[str, str, str]]:
    """(file, function, statement) for every statement under `root` that reads gateway.records."""
    return [(path.relative_to(root).as_posix(), scope, text) for path in sorted(root.rglob("*.py"))
            for scope, text in statements(ast.parse(path.read_text(encoding="utf-8"))) if RAW.search(text) and not WRITE.match(text)]


class OneServingRead(unittest.TestCase):
    def test_no_production_code_reads_stored_records_around_the_gate(self):
        found = raw_reads()
        self.assertEqual([r for r in found if r[:2] not in NOT_SERVING], [],
                         "a stored record is read to be served through gateway.servable_records (registry/schema.sql)")
        self.assertEqual(sorted({r[:2] for r in found}), sorted(NOT_SERVING), "each listed read is still there")

    def test_control_the_check_finds_a_read_around_the_gate(self):
        """The check's own oracle: a read around the gate, in each form a statement takes, is found;
        a docstring, a write and a read through the gate are not."""
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "adapters").mkdir()
            (Path(tmp) / "adapters" / "new_lane.py").write_text(textwrap.dedent('''\
                """Serves gateway.records, says its docstring."""
                def find(cur, where):
                    cur.execute("SELECT canonical FROM gateway.records WHERE identity = %s", ("x",))
                    cur.execute("SELECT count(*) FROM gateway.index_docs d "
                                f"JOIN gateway.records r ON r.identity = d.identity WHERE {where}")
                    cur.execute('SELECT canonical FROM "gateway"."records"')
                    cur.execute("SELECT canonical FROM gateway.servable_records")
                    cur.execute("UPDATE gateway.records SET last_seen = now()")
                '''))
            self.assertEqual([r[:2] for r in raw_reads(Path(tmp))], [("adapters/new_lane.py", "find")] * 3)


def historical(commit: str, script: str, *argv: str) -> None:
    """Run `script` on commit `commit`'s gateway, read from this repository's history (or the one a
    mutation run copied gateway/ from), in a fresh process on this database."""
    root = os.environ.get("GATEWAY_SOURCE_REPOSITORY") or str(GATEWAY_DIR.parent)
    archive = subprocess.run(["git", "-C", root, "archive", commit, "gateway"], capture_output=True, timeout=60)
    if archive.returncode:
        raise RuntimeError(f"commit {commit}: {archive.stderr.decode()}")
    with tempfile.TemporaryDirectory() as tmp:
        tarfile.open(fileobj=io.BytesIO(archive.stdout)).extractall(tmp, filter="data")
        old = os.path.join(tmp, "gateway")
        done = subprocess.run([sys.executable, "-c", script, *argv], cwd=old, env={**os.environ, "PYTHONPATH": old},
                              capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise RuntimeError(done.stderr)


# f58d802, the last commit before 2b-repair-4: its harvest writer never marked a row current
HARVEST_WRITER = """
import json, sys
from research_gateway.core import db
from research_gateway.core.canonical import make_record
from research_gateway.harvest import index
with db.connect() as conn:
    with conn.cursor() as cur:
        for identity, title in json.loads(sys.argv[1]).items():
            index.upsert(cur, make_record(identity=identity, kind="venue", source_id="doaj", title=title, license="CC BY", raw={}), "doaj")
    conn.commit()
"""
# gen-1's cache writer at f4a7a5c (a venue whose lead forbids redistribution), then its index rebuild
LIVE_WRITER = """
import json, sys
from research_gateway import adapters
from research_gateway.core import db, dedup
from research_gateway.core import router as R
from research_gateway.core.cache import Cache
from research_gateway.core.canonical import make_record
from research_gateway.harvest import index
from research_gateway.registry.load import read_seed
router = R.Router(read_seed(), adapters.load_all())
titles = json.loads(sys.argv[1])
with db.connect() as conn:
    for identity, title in titles.items():
        (rec,) = dedup.cluster([make_record(identity=identity, kind="venue", source_id="crossref", title=title, license="cc0",
                                            raw={"payload": identity}, extra={"redistributable": False})])
        Cache(conn).put_record(rec, redistributable=router.redistributable_all(rec), persist_members=router.persistable_members(rec))
    index.reindex(conn, list(titles))
"""
INVOCATION = {"X-Research-Invocation": "inv_recordgate01", "X-Research-Attempt": "1"}


def answer(value):
    """The research answer a door's response carries, however it is wrapped (an MCP text part is JSON)."""
    if isinstance(value, str) and value.lstrip().startswith("{"):
        value = json.loads(value)
    if isinstance(value, dict):
        if "lanes" in value and "records" in value:
            return value
        value = list(value.values())
    if isinstance(value, list):
        return next((found for found in map(answer, value) if found is not None), None)
    return None


@unittest.skipUnless(HAVE_DB, "needs RESEARCH_GATEWAY_DSN and RESEARCH_GATEWAY_TEST_OK=1 (a scratch database)")
class AssembledGateway(unittest.TestCase):
    def setUp(self):
        self.tag = uuid.uuid4().hex[:8]
        self.gw = app.Gateway(app.Settings(tokens={"engine": "t"}, workers=1), use_db=True, transport=FakeTransport())
        self.gw.start()
        self.server = api.serve(self.gw, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.addCleanup(self.cleanup)
        word, only = f"gatecheck{self.tag}", f"withheldonly{self.tag}"
        self.current, self.harvested, self.restricted = (ident.canonical(f"issn:gate-{self.tag}-{n}") for n in ("cur", "old", "gen1"))
        # the gateway is running, on a database with no unconverted row; now the writers
        historical("f58d802", HARVEST_WRITER, json.dumps({self.harvested: f"{word} {only} harvested earlier"}))
        historical("f4a7a5c", LIVE_WRITER, json.dumps({self.restricted: f"{word} {only} cached by gen-1"}))
        with db.connect() as conn:
            with conn.cursor() as cur:
                index.upsert(cur, make_record(identity=self.current, kind="venue", source_id="doaj", title=f"{word} current",
                                              license="CC BY", raw={}), "doaj")
                cur.execute("SELECT identity, restriction_inputs, canonical->>'redistributable' FROM gateway.records "
                            "WHERE identity = ANY(%s) ORDER BY identity", ([self.current, self.harvested, self.restricted],))
                stored = cur.fetchall()
            conn.commit()
        self.assertEqual(sorted(stored), sorted([(self.current, True, None), (self.harvested, False, None), (self.restricted, False, "false")]),
                         "two rows the view withholds, one carrying its lead's prohibition, beside a current one")
        self.word, self.only = word, only

    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.gw.stop()
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM gateway.index_docs WHERE identity ILIKE %s", (f"%{self.tag}%",))
            cur.execute("DELETE FROM gateway.records WHERE identity ILIKE %s", (f"%{self.tag}%",))
            conn.commit()

    def post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.url + path, json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer t", **INVOCATION})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def door(self, name: str, query: str, limit: int) -> dict:
        """One find through the named door; each call a distinct request, never a replay of another's."""
        args = {"query": query, "kind": "venue", "limit": limit}
        call = {"jsonrpc": "2.0", "id": limit, "method": "tools/call", "params": {"name": "research_find", "arguments": args}}
        if name == "http":
            return answer(self.post("/v1/find", args))
        if name == "mcp":
            return answer(self.post("/mcp", call))
        if name == "queued":
            job = self.post("/v1/find?async=1", args)["job_id"]
            for _ in range(300):
                req = urllib.request.Request(f"{self.url}/v1/jobs/{job}", headers={"Authorization": "Bearer t", **INVOCATION})
                with urllib.request.urlopen(req, timeout=30) as r:
                    found = answer(json.load(r))
                if found is not None:
                    return found
                time.sleep(0.05)
            self.fail(f"job {job} never answered")
        done = subprocess.run([sys.executable, "-m", "research_gateway.clients.mcp_stdio"], input=json.dumps(call) + "\n",
                              capture_output=True, text=True, timeout=60, cwd=GATEWAY_DIR,
                              env={**os.environ, "RESEARCH_GATEWAY_URL": self.url, "RESEARCH_GATEWAY_TOKEN": "t",
                                   "RESEARCH_INVOCATION_ID": "inv_recordgate02"})
        self.assertEqual(done.returncode, 0, done.stderr)
        return answer(done.stdout)

    def local(self, out: dict) -> tuple[dict, set]:
        """The local index's lane, and the identities of this test's venues the answer serves."""
        self.assertIsNotNone(out)
        (lane,) = [lane for lane in out["lanes"] if lane["source"] == "openalex_snapshot"]
        return lane, {r["identity"] for r in out["records"] if self.tag.upper() in str(r.get("identity")).upper()}

    def test_a_row_written_after_startup_is_withheld_on_every_door(self):
        for i, name in enumerate(("http", "mcp", "queued", "stdio")):
            with self.subTest(name):
                out = self.door(name, self.word, 10 + i)
                lane, served = self.local(out)
                self.assertEqual(served, {self.current}, "the current venue is served; the two the view withholds are not")
                self.assertEqual({k: lane.get(k) for k in ("coverage", "completeness", "count", "error_class", "exhausted")},
                                 {"coverage": "searched_ok", "completeness": "partial", "count": 1, "error_class": "payload_invalid",
                                  "exhausted": None}, "a lower bound, never a complete answer")
                self.assertIn("openalex_snapshot: 2 matching stored record(s) withheld", " ".join(out["facts"]))

    def test_a_search_only_withheld_rows_match_observes_nothing(self):
        lane, served = self.local(self.door("http", self.only, 10))
        self.assertEqual(served, set())
        self.assertEqual({k: lane.get(k) for k in ("coverage", "completeness", "count", "error_class", "exhausted")},
                         {"coverage": "provider_unavailable", "completeness": "unobserved", "count": None, "error_class": "payload_invalid",
                          "exhausted": None}, "never searched_empty, never a zero")

    def test_control_once_converted_every_row_is_served_with_its_restrictions(self):
        done = subprocess.run([sys.executable, "-m", "research_gateway.registry.migrate"], capture_output=True, text=True, timeout=120,
                              cwd=GATEWAY_DIR)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        for i, name in enumerate(("http", "stdio")):
            with self.subTest(name):
                out = self.door(name, self.word, 20 + i)
                lane, served = self.local(out)
                self.assertEqual(served, {self.current, self.harvested, self.restricted})
                self.assertEqual((lane["coverage"], lane["completeness"], lane["count"]), ("searched_ok", "complete", 3))
                (restricted,) = [r for r in out["records"] if r["identity"] == self.restricted]
                self.assertEqual(restricted["permissions"]["redistribution"], "prohibited", "gen-1's lead prohibition, kept")


if __name__ == "__main__":
    unittest.main()
