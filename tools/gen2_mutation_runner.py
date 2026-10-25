"""Fresh unittest process and conservative Cosmic Ray outcome normalization."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

MARKER = "GEN2_MUTATION_RESULT "
ROOT = Path(__file__).resolve().parents[1]


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []

    def event(self, kind, test, err):
        self.events.append(dict(kind=kind, test=test.id(),
            exception_type=f"{err[0].__module__}.{err[0].__qualname__}", message=str(err[1])))

    def addError(self, test, err):
        self.event("error", test, err)
        super().addError(test, err)

    def addFailure(self, test, err):
        self.event("failure", test, err)
        super().addFailure(test, err)

    def addSubTest(self, test, subtest, err):
        if err:
            self.event("failure" if issubclass(err[0], test.failureException) else "error", subtest, err)
        super().addSubTest(test, subtest, err)


def marker(output):
    lines = [line[len(MARKER):] for line in output.splitlines() if line.startswith(MARKER)]
    try:
        data = json.loads(lines[0]) if len(lines) == 1 else {}
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def normalize(result):
    if result is None:
        return "PENDING"
    output = result.output or ""
    if output == "timeout":
        return "TIMEOUT"
    if result.worker_outcome != "normal":
        return "INVALID"
    data = marker(output)
    if data.get("kind") == "SYNTAX_INVALID":
        return "SYNTAX_INVALID"
    rc = data.get("exit")
    if isinstance(rc, int) and rc < 0:
        return "CRASH"
    if rc not in (0, 1) or not data.get("tests_run") or data.get("unexpected_successes"):
        return "INVALID"
    if data.get("errors"):
        return "TEST_ERROR"
    if rc == 1 and data.get("failures", 0) > 0 and result.test_outcome == "killed":
        return "ASSERTION_KILL"
    if rc == 0 and data.get("failures") == 0 and result.test_outcome == "survived":
        return "SURVIVED"
    return "INVALID"


def run(config):
    if config.pop("inner", False):
        sys.path[:0] = [str(ROOT / "gen2/tests"), str(ROOT)]
        os.environ.pop("GEN2_CI_EVIDENCE", None)
        loader = unittest.defaultTestLoader
        suite = (loader.loadTestsFromNames(config["tests"]) if config["tests"] else
                 loader.discover(str(ROOT / "gen2/tests"), pattern="test_*.py"))
        result = unittest.TextTestRunner(stream=sys.stdout, verbosity=0, failfast=True,
                                         resultclass=EvidenceResult).run(suite)
        data = dict(tests_run=result.testsRun, errors=len(result.errors), failures=len(result.failures),
                    skipped=len(result.skipped), unexpected_successes=len(result.unexpectedSuccesses), events=result.events)
        print(MARKER + json.dumps(data), flush=True)
        return 0 if result.wasSuccessful() else 1
    try:
        for name in config["targets"]:
            compile(Path(name).read_bytes(), name, "exec")
    except SyntaxError as exc:
        print(MARKER + json.dumps(dict(kind="SYNTAX_INVALID", detail=str(exc))), flush=True)
        return 86
    child = subprocess.Popen([sys.executable, __file__, json.dumps({**config, "inner": True})],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output, _ = child.communicate()
    # Keep all diagnostics, with exactly one wrapper-owned result marker.
    print("\n".join(line for line in output.splitlines() if not line.startswith(MARKER)))
    print(MARKER + json.dumps({**marker(output), "exit": child.returncode, "test_pid": child.pid}), flush=True)
    return child.returncode if child.returncode in (0, 1) else 86


if __name__ == "__main__":
    sys.exit(run(json.loads(sys.argv[1])))
