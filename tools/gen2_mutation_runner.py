"""Fresh unittest process and conservative Cosmic Ray outcome normalization."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

from attrs import asdict
from cosmic_ray.mutating import mutate_and_test
from cosmic_ray.work_item import MutationSpec
import shlex

from gen2_coverage import Baseline, source_state
from gen2_ci_evidence import complete_union, parallel, partition, tests

MARKER = "GEN2_MUTATION_RESULT "
ROOT = Path(__file__).resolve().parents[1]


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, coverage=None, cutoff=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []
        self.coverage = coverage
        self.cutoff = cutoff
        self.boundary = None

    def startTest(self, test):
        if self.coverage:
            self.coverage.switch_context(test.id())
        super().startTest(test)
        self.boundary = [self.testsRun, test.id()]

    def stopTest(self, test):
        super().stopTest(test)
        if self.coverage:
            self.coverage.switch_context("")
        if self.boundary == self.cutoff:
            self.stop()

    def event(self, kind, test, err):
        self.events.append(dict(kind=kind, test=test.id(),
            exception_type=f"{err[0].__module__}.{err[0].__qualname__}", message=str(err[1]),
            executed=not isinstance(test, unittest.loader._FailedTest),
            boundary=self.boundary if isinstance(test, unittest.TestCase) else None))

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
    if rc not in (0, 1) or not isinstance(data.get("tests_run"), int) or data.get("unexpected_successes"):
        return "INVALID"
    if data.get("errors"):
        errors = [event for event in data.get("events", []) if event.get("kind") == "error"]
        return "ERROR_KILL" if (rc == 1 and result.test_outcome == "killed" and
            len(errors) == data["errors"] and all(event.get("executed") for event in errors)) else "INVALID"
    if not data["tests_run"] and not (data.get("shard") and data.get("expected") and data.get("selected") == []):
        return "INVALID"
    if rc == 1 and data.get("failures", 0) > 0 and result.test_outcome == "killed":
        return "ASSERTION_KILL"
    if rc == 0 and data.get("failures") == 0 and result.test_outcome == "survived":
        return "SURVIVED"
    return "INVALID"


def run(config):
    if mutations := config.pop("mutations", None):
        # This process owns a separate checkout. Every test still starts fresh.
        before = source_state()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as request:
            json.dump(config, request)
            request.flush()
            result = mutate_and_test([MutationSpec(**m) for m in mutations],
                shlex.join([sys.executable, __file__, request.name]), 7200)
        print(json.dumps(dict(result=asdict(result), before=before, after=source_state())), flush=True)
        return 0
    if config.get("coverage") and not config["tests"] and config.get("workers", 1) > 1:
        return subprocess.call([sys.executable, str(ROOT / "tools/gen2_test.py"), "--workers", str(config["workers"])],
            env={**os.environ, "GEN2_TEST_COVERAGE": config["coverage"]})
    if config.pop("inner", False):
        sys.path[:0] = [str(ROOT / "gen2/tests"), str(ROOT)]
        if config.get("shard"):
            tempfile.tempdir = tempfile.mkdtemp(prefix="gen2-mutation-shard-")
        os.environ.pop("GEN2_CI_EVIDENCE", None)
        baseline = Baseline(config["coverage"]) if config.get("coverage") else None
        if baseline:
            baseline.start()
        loader = unittest.defaultTestLoader
        suite = (loader.loadTestsFromNames(config["tests"]) if config["tests"] else
                 loader.discover(str(ROOT / "gen2/tests"), pattern="test_*.py"))
        expected = [test.id() for test in tests(suite)]
        if config.get("shard"):
            suite = partition(suite, config["shard"])
        selected = [test.id() for test in tests(suite)]
        stream = open(config["coverage"] + ".log", "w", buffering=1) if baseline else sys.stdout
        result = unittest.TextTestRunner(stream=stream, verbosity=2 if baseline else 0, failfast=True,
            resultclass=lambda *a, **kw: EvidenceResult(*a, coverage=baseline.coverage if baseline else None,
                cutoff=config.get("cutoff"), **kw)).run(suite)
        if baseline:
            if not config["tests"]:
                baseline.finish(result)
            else:
                baseline.coverage.stop()
                baseline.coverage.save()
            stream.close()
        data = dict(tests_run=result.testsRun, errors=len(result.errors), failures=len(result.failures),
                    skipped=len(result.skipped), unexpected_successes=len(result.unexpectedSuccesses),
                    events=result.events, boundary=result.boundary, expected=expected, selected=selected,
                    shard=config.get("shard"), success=result.wasSuccessful(), test_pid=os.getpid())
        print(MARKER + json.dumps(data), flush=True)
        return 0 if result.wasSuccessful() else 1
    try:
        for name in config["targets"]:
            compile(Path(name).read_bytes(), name, "exec")
    except SyntaxError as exc:
        print(MARKER + json.dumps(dict(kind="SYNTAX_INVALID", detail=str(exc))), flush=True)
        return 86
    before = source_state() if config.get("identity") else None
    stages = []
    while True:
        started = time.monotonic()
        if config.get("stage") == 2 and config.get("workers", 1) > 1 and not config["tests"] and not config.get("shard"):
            count = config["workers"]
            directory = Path(tempfile.mkdtemp(prefix="stage2-", dir=config.get("shard_logs")))
            commands = []
            for i in range(1, count + 1):
                request = directory / f"request-{i}.json"
                request.write_text(json.dumps({**config, "inner": True, "shard": [i, count]}))
                commands.append([sys.executable, __file__, str(request)])
            runs = parallel(commands, directory)
            shards = [{**marker((path / "console.log").read_text()), "exit": code,
                       "log": str(path / "console.log")} for code, path in runs]
            verdicts = [normalize(SimpleNamespace(worker_outcome="normal", output=MARKER + json.dumps(row),
                test_outcome="survived" if row["exit"] == 0 else "killed")) for row in shards]
            chosen = next((i for i, verdict in enumerate(verdicts) if verdict in {"ASSERTION_KILL", "ERROR_KILL"}), None)
            if chosen is None and all(verdict == "SURVIVED" for verdict in verdicts):
                complete_union(shards, count)
                data = {**shards[0], "tests_run": sum(row["tests_run"] for row in shards), "shard": None}
            else:
                data = shards[chosen if chosen is not None else next(i for i, v in enumerate(verdicts) if v != "SURVIVED")]
            data = {**data, "shards": shards}
            output, returncode = "", data["exit"]
        else:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as request:
                json.dump({**config, "inner": True}, request)
                request.flush()
                child = subprocess.Popen([sys.executable, __file__, request.name],
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                output, _ = child.communicate()
            data = {**marker(output), "exit": child.returncode, "test_pid": child.pid}
            returncode = child.returncode
        verdict = normalize(SimpleNamespace(worker_outcome="normal", output=MARKER + json.dumps(data),
                                           test_outcome="survived" if returncode == 0 else "killed"))
        # Keep diagnostics and per-stage evidence, with one final result marker.
        print("\n".join(line for line in output.splitlines() if not line.startswith(MARKER)))
        stages.append(dict(stage=config.get("stage", "baseline"), tests=config["tests"],
                           seconds=time.monotonic() - started, verdict=verdict, **data))
        if config.get("stage_only") or config.get("stage") not in (1, "1b") or verdict != "SURVIVED":
            break
        config.update(tests=config["full_tests"], stage=2)
    identity = dict(source_before=before, source_after=source_state()) if before else {}
    print(MARKER + json.dumps({**data, "stages": stages, **identity}), flush=True)
    return returncode if returncode in (0, 1) else 86


if __name__ == "__main__":
    argument = sys.argv[1]
    os.chdir(ROOT)
    sys.exit(run(json.loads(argument if argument.startswith("{") else Path(argument).read_text())))
