"""Successful full-suite coverage, bound to the checkout and collected bytes."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from coverage import Coverage, __version__

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "build/gen2-coverage.sqlite"


def source_state():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT)
    digest = hashlib.sha256(git("diff", "--binary", "HEAD"))
    for name in sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z", "--",
                    "gen2", "tools", "gateway", "docs", "deploy", "Makefile", "Jenkinsfile", ".github", ".gitignore").split(b"\0"))):
        if name:
            path = ROOT / name.decode()
            digest.update(name + b"\0" + (hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"deleted"))
    return dict(head=git("rev-parse", "HEAD").decode().strip(), source=digest.hexdigest(), root=str(ROOT),
                python=sys.version, coverage=__version__)


class Baseline:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.receipt = self.path.with_suffix(".json")
        self.coverage = Coverage(data_file=str(self.path), config_file=False,
            source=[str(ROOT / "gen2")], omit=[str(ROOT / "gen2/tests/*")])

    def valid(self):
        try:
            data = json.loads(self.receipt.read_text())
            return data["state"] == source_state() and data["tests_run"] > 0 and data["sha256"] == hashlib.sha256(self.path.read_bytes()).hexdigest()
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def start(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.receipt.unlink(missing_ok=True)
        self.coverage.erase()
        self.before, self.started = source_state(), time.monotonic()
        self.coverage.start()

    def finish(self, result):
        self.coverage.stop()
        self.coverage.save()
        if result.wasSuccessful() and result.testsRun > 0 and self.before == source_state():
            self.receipt.write_text(json.dumps(dict(state=self.before, tests_run=result.testsRun,
                seconds=time.monotonic() - self.started, sha256=hashlib.sha256(self.path.read_bytes()).hexdigest())) + "\n")
