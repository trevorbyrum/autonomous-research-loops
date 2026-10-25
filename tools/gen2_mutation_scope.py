"""Automatic mutation of changed production lines; full campaigns are advisory."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import re
import io
import tokenize

from attrs import asdict
from cosmic_ray.work_db import use_db
import toml

from gen2_mutation_runner import normalize

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default=os.environ.get("GEN2_BASE", "origin/gen2"))
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--tests", nargs="+", help="targeted coder demonstrations only; default: full unittest discovery")
    parser.add_argument("--out", type=Path, default=Path(os.environ.get("GEN2_CI_EVIDENCE", "build/mutation-evidence")))
    args = parser.parse_args()
    os.chdir(ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    out = Path(tempfile.mkdtemp(prefix="campaign-", dir=args.out)).resolve()
    report = dict(status="incomplete", scope="full" if args.full else "changed-lines", tests=args.tests,
                  blocking=not args.report_only, mutants=[])
    def git(*argv):
        return subprocess.check_output(["git", *argv], text=True).strip()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(out / "empty-pycache")}
    def command(*argv):
        with (out / "commands.log").open("a") as log:
            subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    try:
        report.update(head=git("rev-parse", "HEAD"), base=git("merge-base", args.base, "HEAD"),
                      source_dirty=bool(git("status", "--porcelain", "--untracked-files=no")))
        names = git("ls-files", "gen2") if args.full else git("diff", "--name-only", "--diff-filter=ACMR", report["base"], "--", "gen2")
        targets = sorted(name for name in names.splitlines() if name.endswith(".py") and not name.startswith("gen2/tests/"))
        report["targets"] = targets
        runner = shlex.join([sys.executable, str(ROOT / "tools/gen2_mutation_runner.py"),
                             json.dumps(dict(targets=targets, tests=args.tests))])
        cfg, session = out / "cosmic-ray.toml", out / "session.sqlite"
        cfg.write_text(toml.dumps({"cosmic-ray": {"module-path": targets, "timeout": 7200,
            "test-command": runner, "distributor": {"name": "local"},
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
                command(sys.executable, str(ROOT / "tools/gen2_mutation_runner.py"), json.dumps(dict(targets=targets, tests=args.tests)))
                command(str(Path(sys.executable).with_name("cosmic-ray")), "exec", str(cfg), str(session))
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
        if report["counts"].get("PENDING"):
            report["status"] = "incomplete"
        report["failed"] = report["status"] not in ("complete", "no-applicable-files") or any(
            row["verdict"] not in {"FILTERED_GIT", "PRAGMA", "ASSERTION_KILL", "SYNTAX_INVALID"} for row in report["mutants"])
        (out / "mutation-report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"gen2-mutation: {out / 'mutation-report.json'}: {report['status']} {report['counts']}", flush=True)
    return int(report["failed"] and not args.report_only)


if __name__ == "__main__":
    sys.exit(main())
