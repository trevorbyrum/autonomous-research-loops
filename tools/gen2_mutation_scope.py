"""Automatic mutation of changed production lines; full campaigns are advisory."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import re
import io
import tokenize
import time
from types import SimpleNamespace

from attrs import asdict
from cosmic_ray.work_db import use_db
from cosmic_ray.mutating import mutate_and_test
from cosmic_ray.testing import run_tests
from coverage import CoverageData
import toml

from gen2_mutation_runner import marker, normalize
from gen2_coverage import Baseline, DEFAULT, source_state

ROOT = Path(__file__).resolve().parents[1]


def covering_tests(data, mutations, module=False):
    return sorted({test for mutation in mutations
        for line, contexts in data.contexts_by_lineno(str(ROOT / mutation.module_path)).items()
        if module or mutation.start_pos[0] <= line <= mutation.end_pos[0] - (mutation.end_pos[1] == 0)
        for test in contexts if test})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("GEN2_BASE", "origin/gen2"))
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--tests", nargs="+", help="targeted coder demonstrations only; default: full unittest discovery")
    parser.add_argument("--coverage", type=Path, default=DEFAULT)
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("GEN2_CI_EVIDENCE", "build/mutation-evidence")))
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ.pop("GEN2_TEST_COVERAGE", None)
    args.out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="campaign-", dir=args.out)).resolve()
    started = time.monotonic()
    report = dict(status="incomplete", scope="full" if args.full else "changed-lines", tests=args.tests,
                  blocking=not args.report_only, mutants=[], qualifications=[])
    def git(*argv):
        return subprocess.check_output(["git", *argv], text=True).strip()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(out / "empty-pycache")}
    os.environ.update({name: env[name] for name in ("PYTHONDONTWRITEBYTECODE", "PYTHONPYCACHEPREFIX")})
    def command(*argv):
        with (out / "commands.log").open("a") as log:
            subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    try:
        report.update(head=git("rev-parse", "HEAD"), base=git("merge-base", args.base, "HEAD"),
                      source_dirty=bool(git("status", "--porcelain", "--untracked-files=no")))
        names = git("ls-files", "gen2") if args.full else git("diff", "--name-only", "--diff-filter=ACMR", report["base"], "--", "gen2")
        targets = sorted(name for name in names.splitlines() if name.endswith(".py") and not name.startswith("gen2/tests/"))
        report["targets"] = targets
        def runner(config, name="baseline"):
            request = out / f"{name}.json"
            request.write_text(json.dumps(config))
            return [sys.executable, str(ROOT / "tools/gen2_mutation_runner.py"), str(request)]
        qualified, accepted = {}, set()
        def qualify(stage):
            tests = stage["tests"]
            cutoff = stage["boundary"] if all(event.get("boundary") == stage["boundary"]
                for event in stage["events"]) else None
            identity = json.dumps(source_state(), sort_keys=True)
            key = (tuple(tests) if tests is not None else None, tuple(cutoff) if cutoff else None, identity)
            if key not in qualified:
                began = time.monotonic()
                name = f"qualification-{len(qualified)}"
                outcome, output = run_tests(shlex.join(runner(dict(targets=targets, tests=tests, cutoff=cutoff), name)), 7200)
                (out / f"{name}.log").write_text(output)
                verdict = normalize(SimpleNamespace(worker_outcome="normal", output=output, test_outcome=outcome))
                qualified[key] = (verdict == "SURVIVED" and (cutoff is None or marker(output)["boundary"] == cutoff)
                    and identity == json.dumps(source_state(), sort_keys=True))
                report["qualifications"].append(dict(tests=tests, cutoff=cutoff, identity=identity, verdict=verdict, valid=qualified[key],
                    seconds=time.monotonic() - began))
            return qualified[key]
        cached = Baseline(args.coverage)
        baseline = dict(targets=targets, tests=args.tests, coverage=str(cached.path if not args.tests else out / "coverage.sqlite"))
        cfg, session = out / "cosmic-ray.toml", out / "session.sqlite"
        cfg.write_text(toml.dumps({"cosmic-ray": {"module-path": targets, "timeout": 7200,
            "test-command": shlex.join(runner(baseline)), "distributor": {"name": "local"},
            "filters": {"git-filter": {"branch": report["base"]}}}}))
        if targets:
            command(str(Path(sys.executable).with_name("cosmic-ray")), "init", str(cfg), str(session))
            if not args.full:
                command(str(Path(sys.executable).with_name("cr-filter-git")), "--config", str(cfg), str(session))
            with use_db(session) as db:
                git_skipped = {job for job, result in db.results if result.worker_outcome == "skipped"}
            command(str(Path(sys.executable).with_name("cr-filter-pragma")), str(session))
            with use_db(session) as db:
                selected = list(db.pending_work_items)
            if selected:
                began = time.monotonic()
                reuse = not args.tests and cached.valid()
                if not reuse:
                    command(*runner(baseline))
                report["baseline_seconds"] = time.monotonic() - began
                report.update(baseline_reused=reuse, coverage=baseline["coverage"])
                if Path(baseline["coverage"]) != out / "coverage.sqlite":
                    shutil.copyfile(baseline["coverage"], out / "coverage.sqlite")
                    shutil.copyfile(cached.receipt, out / "coverage.json")
                data = CoverageData(basename=str(out / "coverage.sqlite"))
                data.read()
                selection = {item.job_id: covering_tests(data, item.mutations) for item in selected}
                modules = {item.job_id: covering_tests(data, item.mutations, module=True) for item in selected}
                (out / "test-selection.json").write_text(json.dumps(selection, indent=2) + "\n")
                (out / "module-selection.json").write_text(json.dumps(modules, indent=2) + "\n")
                with use_db(session) as db:
                    for index, item in enumerate(selected, 1):
                        for tests, stage in ((selection[item.job_id], 1), (modules[item.job_id], "1b"), (args.tests, 2)):
                            if stage != 2 and not tests:
                                continue
                            config = dict(targets=targets, tests=tests, full_tests=args.tests, stage=stage)
                            result = mutate_and_test(item.mutations, shlex.join(runner(config, item.job_id)), 7200)
                            if normalize(result) in {"ASSERTION_KILL", "ERROR_KILL"}:
                                last = marker(result.output)["stages"][-1]
                                if qualify(last):
                                    accepted.add(item.job_id)
                                elif last["stage"] != 2:
                                    continue
                            break
                        db.set_result(item.job_id, result)
                        print(f"gen2-mutation: {index}/{len(selected)} result recorded", flush=True)
            report["status"] = "complete"
        else:
            report["status"] = "no-applicable-files"
    except Exception as exc:
        report["error"] = repr(exc)
    finally:
        if (out / "session.sqlite").exists():
            with use_db(out / "session.sqlite") as db:
                results = dict(db.results)
                for item in db.work_items:
                    result = results.get(item.job_id)
                    verdict = ("FILTERED_GIT" if item.job_id in locals().get("git_skipped", set()) else
                               "PRAGMA" if result and result.worker_outcome == "skipped" else normalize(result))
                    if verdict in {"ASSERTION_KILL", "ERROR_KILL"} and item.job_id not in accepted:
                        verdict = "INVALID"
                    mutation = item.mutations[0]
                    pragma = None
                    if verdict == "PRAGMA":
                        line = mutation.end_pos[0] - (1 if mutation.end_pos[1] == 0 else 0)
                        pragma = mutation.module_path.read_text().splitlines()[line - 1]
                        comments = [token for token in tokenize.generate_tokens(io.StringIO(mutation.module_path.read_text()).readline)
                                    if token.type == tokenize.COMMENT and token.start[0] == line]
                        if not any(token.start[1] > 0 and pragma[:token.start[1]].strip() and
                                   re.fullmatch(r"# pragma: no mutate\s*[-:;# ]*\w.*", token.string) for token in comments):
                            verdict = "INVALID_PRAGMA"
                    spec = asdict(mutation, value_serializer=lambda _, __, v: str(v) if isinstance(v, Path) else v)
                    report["mutants"].append(dict(id=f"{spec['module_path']}:{spec['operator_name']}:{spec['occurrence']}",
                        mutation=spec, verdict=verdict, pragma=pragma, native=asdict(result) if result else None))
        report["counts"] = dict(Counter(row["verdict"] for row in report["mutants"]))
        report["stage_counts"] = dict(Counter(str(stage["stage"]) for row in report["mutants"]
            if row["native"] for stage in marker(row["native"]["output"] or "").get("stages", [])))
        report["stage_verdicts"] = dict(Counter(f"{stage['stage']}:{stage['verdict']}" for row in report["mutants"]
            if row["native"] for stage in marker(row["native"]["output"] or "").get("stages", [])))
        report["seconds"] = time.monotonic() - started
        report["qualification_seconds"] = sum(row["seconds"] for row in report["qualifications"])
        if report["counts"].get("PENDING"):
            report["status"] = "incomplete"
        report["failed"] = report["status"] not in ("complete", "no-applicable-files") or any(
            row["verdict"] not in {"FILTERED_GIT", "PRAGMA", "ASSERTION_KILL", "ERROR_KILL", "SYNTAX_INVALID"} for row in report["mutants"])
        (out / "mutation-report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"gen2-mutation: {out / 'mutation-report.json'}: {report['status']} {report['counts']}", flush=True)
    return int(report["failed"] and not args.report_only)


if __name__ == "__main__":
    sys.exit(main())
