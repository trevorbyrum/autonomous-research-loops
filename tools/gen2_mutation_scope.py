"""Automatic mutation of changed production lines; full campaigns are advisory."""
import argparse
import ast
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
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
import threading
from types import SimpleNamespace

from attrs import asdict, evolve
from cosmic_ray.work_db import use_db
from cosmic_ray.testing import run_tests
from cosmic_ray.work_item import WorkResult, WorkerOutcome
from coverage import CoverageData
import toml

from gen2_mutation_runner import MARKER, marker, normalize
from gen2_coverage import Baseline, DEFAULT

ROOT = Path(__file__).resolve().parents[1]


def moved_scope(base):
    """Read Git's per-line move classification, including cross-file moves."""
    patch = subprocess.check_output(["git", "-c", "core.quotePath=false",
        "-c", "color.diff.newMoved=magenta", "-c", "color.diff.new=green",
        "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--diff-algorithm=myers",
        "--src-prefix=a/", "--dst-prefix=b/", "--unified=0", "--color=always",
        "--ws-error-highlight=none", "--color-moved=plain",
        "--color-moved-ws=allow-indentation-change", base], cwd=ROOT, text=True)
    changed, moved = {}, {}
    name = None
    for raw in patch.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", raw)
        if line.startswith("+++ "):
            name = line[4:]
            if name.startswith('"'):
                name = ast.literal_eval(name)
            name = name[2:] if name.startswith("b/") else None
        elif line.startswith("@@ "):
            number = int(re.search(r"\+(\d+)", line)[1])
        elif name is not None and line.startswith("+"):
            changed.setdefault(name, set()).add(number)
            if "\x1b[35m" in raw[:raw.index("+")]:
                moved.setdefault(name, set()).add(number)
            number += 1
        elif line.startswith(" "):
            number += 1
    return changed, moved


def line_ranges(lines):
    ranges = []
    for line in sorted(lines):
        if ranges and line == ranges[-1][1] + 1:
            ranges[-1][1] = line
        else:
            ranges.append([line, line])
    return ranges


def moved_only(item, changed, moved):
    for mutation in item.mutations:
        name = str(mutation.module_path)
        span = set(range(mutation.start_pos[0], mutation.end_pos[0] + (mutation.end_pos[1] != 0)))
        touched = span & changed.get(name, set())
        if not touched or not touched <= moved.get(name, set()):
            return False
    return True


def item_order(item):
    mutation = item.mutations[0]
    return (str(mutation.module_path), mutation.start_pos, mutation.end_pos,
            mutation.operator_name, mutation.occurrence, item.job_id)


def control_key(stage, cutoff, identity):
    return (tuple(stage["tests"]) if stage["tests"] is not None else None,
            tuple(cutoff) if cutoff else None, identity, tuple(stage.get("shard") or (1, 1)))


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
    parser.add_argument("--workers", type=int, default=1, choices=range(1, 65))
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("GEN2_CI_EVIDENCE", "build/mutation-evidence")))
    args = parser.parse_args()
    os.chdir(ROOT)
    os.environ.pop("GEN2_TEST_COVERAGE", None)
    args.out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="campaign-", dir=args.out)).resolve()
    started = time.monotonic()
    report = dict(status="incomplete", scope="full" if args.full else "changed-lines", tests=args.tests,
                  blocking=not args.report_only, workers=args.workers, mutants=[], qualifications=[],
                  moved_exclusions={}, moved_excluded_lines=0, selected_files=[], omitted_files=[])
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
        paths = ("gen2", "gateway/research_gateway")
        names = git("ls-files", *paths) if args.full else git("diff", "--name-only", "--diff-filter=ACMR", report["base"], "--", *paths)
        targets = sorted(name for name in names.splitlines() if name.endswith(".py") and not name.startswith("gen2/tests/"))
        report["targets"] = targets
        def runner(config, name="baseline", root=ROOT):
            config.setdefault("workers", args.workers)
            config["shard_logs"] = str(out)
            request = out / f"{name}.json"
            request.write_text(json.dumps(config))
            return [sys.executable, str(root / "tools/gen2_mutation_runner.py"), str(request)]
        qualified, accepted = {}, set()
        def qualify(stage, identity, root):
            tests = stage["tests"]
            cutoff = stage["boundary"] if all(event.get("boundary") == stage["boundary"]
                for event in stage["events"]) else None
            identity = json.dumps(identity, sort_keys=True)
            key = control_key(stage, cutoff, identity)
            if key not in qualified:
                began = time.monotonic()
                name = f"qualification-{root.name}-{len(qualified)}"
                shard = stage.get("shard")
                outcome, output = run_tests(shlex.join(runner(dict(targets=targets, tests=tests,
                    cutoff=cutoff, shard=shard, identity=True), name, root)), 7200)
                (out / f"{name}.log").write_text(output)
                verdict = normalize(SimpleNamespace(worker_outcome="normal", output=output, test_outcome=outcome))
                control = marker(output)
                qualified[key] = (verdict == "SURVIVED" and (cutoff is None or control["boundary"] == cutoff)
                    and all(identity == json.dumps(control.get(key), sort_keys=True)
                            for key in ("source_before", "source_after")))
                report["qualifications"].append(dict(tests=tests, cutoff=cutoff, shard=shard, identity=identity, verdict=verdict, valid=qualified[key],
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
            move_skipped = set()
            if not args.full:
                changed, moved = moved_scope(report["base"])
                report["moved_exclusions"] = {name: dict(ranges=line_ranges(moved[name]), count=len(moved[name]))
                    for name in targets if moved.get(name)}
                report["moved_excluded_lines"] = sum(row["count"] for row in report["moved_exclusions"].values())
                with use_db(session) as db:
                    for item in list(db.pending_work_items):
                        if moved_only(item, changed, moved):
                            move_skipped.add(item.job_id)
                            db.set_result(item.job_id, WorkResult(worker_outcome=WorkerOutcome.SKIPPED))
            command(str(Path(sys.executable).with_name("cr-filter-pragma")), str(session))
            with use_db(session) as db:
                selected = sorted(db.pending_work_items, key=item_order)
            report["selected_files"] = sorted({str(m.module_path) for item in selected for m in item.mutations})
            report["omitted_files"] = sorted(set(targets) - set(report["selected_files"]))
            report["selected_mutants"] = len(selected)
            report["moved_excluded_mutants"] = len(move_skipped)
            if selected:
                case_workers = min(args.workers, len(selected))
                stage2_workers = max(1, args.workers // case_workers)
                report.update(case_workers=case_workers, stage2_workers=stage2_workers)
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
                local = threading.local()
                source_names = subprocess.check_output(["git", "ls-files", "--cached", "--others",
                    "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
                def prepare_worker():
                    root = Path(tempfile.mkdtemp(prefix="worker-", dir=out))
                    subprocess.run(["git", "clone", "--shared", "--quiet", str(ROOT), str(root)], check=True)
                    # Overlay the actual candidate, including dirty and untracked inputs.
                    for name in source_names:
                        if name:
                            source, destination = ROOT / name, root / name
                            if source.is_file():
                                destination.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copyfile(source, destination)
                            elif not source.exists():
                                destination.unlink(missing_ok=True)
                    local.root = root
                def execute(item):
                    stages, diagnostics, valid = [], [], False
                    choices = [(selection[item.job_id], 1), (modules[item.job_id], "1b"), (args.tests, 2)]
                    while choices:
                        tests, stage = choices.pop(0)
                        if stage != 2 and not tests:
                            continue
                        config = dict(targets=targets, tests=tests, full_tests=args.tests, stage=stage,
                            stage_only=True, workers=stage2_workers, mutations=[asdict(m, value_serializer=lambda _, __, v:
                                str(v) if isinstance(v, Path) else v) for m in item.mutations])
                        output = subprocess.check_output(runner(config, item.job_id, local.root),
                            cwd=local.root, env=env, text=True)
                        receipt = json.loads(output)
                        result = WorkResult(**receipt["result"])
                        if receipt["before"] != receipt["after"]:
                            result = evolve(result, worker_outcome=WorkerOutcome.EXCEPTION)
                        evidence = marker(result.output)
                        stages.extend(evidence.get("stages", []))
                        diagnostics.extend(line for line in (result.output or "").splitlines() if not line.startswith(MARKER))
                        if normalize(result) in {"ASSERTION_KILL", "ERROR_KILL", "TEST_ERROR"}:
                            valid = qualify(evidence["stages"][-1], receipt["before"], local.root)
                            if not valid and stage != 2:
                                stages, diagnostics = [], []
                                continue
                        elif normalize(result) == "SURVIVED" and stage != 2:
                            choices = [(args.tests, 2)]
                            continue
                        break
                    if evidence:
                        result = evolve(result, output="\n".join([*diagnostics, MARKER + json.dumps({**evidence, "stages": stages})]))
                    return result, valid
                with ThreadPoolExecutor(max_workers=case_workers, initializer=prepare_worker) as pool, use_db(session) as db:
                    for index, (item, (result, valid)) in enumerate(zip(selected, pool.map(execute, selected)), 1):
                        if valid:
                            accepted.add(item.job_id)
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
                for item in sorted(db.work_items, key=item_order):
                    result = results.get(item.job_id)
                    verdict = ("FILTERED_GIT" if item.job_id in locals().get("git_skipped", set()) else
                               "FILTERED_MOVE" if item.job_id in locals().get("move_skipped", set()) else
                               "PRAGMA" if result and result.worker_outcome == "skipped" else normalize(result))
                    if verdict in {"ASSERTION_KILL", "ERROR_KILL", "TEST_ERROR"} and item.job_id not in accepted:
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
        report["qualifications"].sort(key=lambda row: json.dumps([row["tests"], row["cutoff"], row["shard"]], sort_keys=True))
        report["stage_counts"] = dict(Counter(str(stage["stage"]) for row in report["mutants"]
            if row["native"] for stage in marker(row["native"]["output"] or "").get("stages", [])))
        report["stage_verdicts"] = dict(Counter(f"{stage['stage']}:{stage['verdict']}" for row in report["mutants"]
            if row["native"] for stage in marker(row["native"]["output"] or "").get("stages", [])))
        report["seconds"] = time.monotonic() - started
        report["qualification_seconds"] = sum(row["seconds"] for row in report["qualifications"])
        if report["counts"].get("PENDING"):
            report["status"] = "incomplete"
        report["failed"] = report["status"] not in ("complete", "no-applicable-files") or any(
            row["verdict"] not in {"FILTERED_GIT", "FILTERED_MOVE", "PRAGMA", "ASSERTION_KILL", "ERROR_KILL", "SYNTAX_INVALID"} for row in report["mutants"])
        (out / "mutation-report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"gen2-mutation: {out / 'mutation-report.json'}: {report['status']} {report['counts']}", flush=True)
    return int(report["failed"] and not args.report_only)


if __name__ == "__main__":
    sys.exit(main())
