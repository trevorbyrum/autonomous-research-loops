#!/usr/bin/env python3
"""Gen-2 debt-register check (stdlib only; task 2q-a): fails when a closed phase
or task still owns an open entry.

Charter "Root-cause fixes, not patches": "A MITIGATION always blocks and
escalates to the operator. Only the operator can accept one, and an accepted
one is logged in docs/gen2/DEBT-REGISTER.md with its owning phase and removal
condition; the build fails if that phase closes with the entry still open."
The register also holds the OWNED OBLIGATIONS that operator rulings carry
(a rule a later task must satisfy, a release step a later phase must run): not
mitigations, but they must not be lost. An epistemic fact (a documented
boundary of the trust model, finite testing, a language limit) is neither and
has no entry.

Two files, both read from the repository root:
  docs/gen2/DEBT-REGISTER.md   the entries
  docs/gen2/phase-status.json  {"phases": {"<id>": "<state>"},
                                "tasks": {"<id>": {"phase": "<id>", "state": "<state>"}}}
                               with state one of pending, open, closed. Whoever
                               records a task's or a phase's acceptance sets it
                               to closed here; that is what arms this check.

An entry is a `### DEBT-<n> <title>` section of `- key: value` lines (a long
value continues on lines indented two spaces; fenced blocks are skipped):
  kind        mitigation | obligation
  status      open | closed
  owner       `task <id>` or `phase <id>`, an id that phase-status.json names
  what        what it is
  removal     the condition under which the entry is closed
  source      (obligation) the operator ruling or review that carries it, dated
  found by    (mitigation) the review that found it
  accepted by (mitigation) the operator's acceptance, with its date
  closed by   (when closed) the evidence that the removal condition was met

It fails (exit 1) on: an OPEN entry whose owner is closed, itself or through
its phase (the phase-close check); an entry that is incomplete, malformed or
duplicated; an owner that phase-status.json does not name; a closed entry with
no `closed by`; a phase marked closed that has a task not closed. Exit 2: a
file is missing or unreadable.

What this does not establish: that the register is COMPLETE (it checks the
entries that exist; whoever records an operator ruling adds its entry), or
that a `closed by` is true. The phase-close check is only as good as the
discipline of setting a task or phase to closed at its acceptance.

Trace: task 2q-a; charter "Root-cause fixes, not patches"; Gate D #2 (trust
model B: documented boundaries are not debt).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

EXIT_OK, EXIT_FAIL, EXIT_TOOL = 0, 1, 2
REGISTER = "docs/gen2/DEBT-REGISTER.md"
STATUS = "docs/gen2/phase-status.json"
STATES = ("pending", "open", "closed")
KINDS = ("mitigation", "obligation")
KEYS = {"kind": "kind", "status": "status", "owner": "owner", "what": "what", "removal": "removal", "source": "source",
        "found by": "found_by", "accepted by": "accepted_by", "closed by": "closed_by"}
PLACEHOLDER = re.compile(r"^\W*(todo|tbd|n/?a|none|nil|unknown|\?+|-+|x+)\W*$", re.IGNORECASE)
DATED = re.compile(r"\d{4}-\d{2}-\d{2}")
CITED = re.compile(r"\d{4}-\d{2}-\d{2}|\.md\b|Gate D\s*#\d+", re.IGNORECASE)


class ToolError(Exception):
    pass


@dataclass
class Entry:
    ident: str
    fields: dict[str, str]
    line: int


def parse_register(text: str) -> tuple[list[Entry], list[str]]:
    entries: list[Entry] = []
    problems: list[str] = []
    current: Entry | None = None
    last = ""
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = re.match(r"^### (DEBT-[\w.-]*)\b", line)
        if heading:
            current = Entry(heading.group(1), {}, number)
            entries.append(current)
            last = ""
            continue
        if line.startswith("#"):
            current = None
            continue
        if current is None:
            continue
        field = re.match(r"^- ([A-Za-z_ ]+?):\s*(.*)$", line)
        if field:
            key = KEYS.get(field.group(1).strip().lower().replace("_", " "))
            if key is None:
                problems.append(f"{current.ident} (line {number}): unknown field {field.group(1)!r}")
                last = ""
                continue
            if key in current.fields:
                problems.append(f"{current.ident} (line {number}): field {key} given twice")
            current.fields[key] = field.group(2).strip()
            last = key
        elif line.startswith("  ") and line.strip() and last:
            current.fields[last] = (current.fields[last] + " " + line.strip()).strip()
    return entries, problems


def load_status(path: Path) -> dict:
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolError(f"no phase status at {path}") from exc
    except (OSError, ValueError) as exc:
        raise ToolError(f"{path} cannot be read: {exc}") from exc
    if not isinstance(status, dict) or not isinstance(status.get("phases"), dict) or not isinstance(status.get("tasks"), dict):
        raise ToolError(f"{path} must hold the objects `phases` and `tasks`")
    return status


def status_problems(status: dict) -> list[str]:
    problems = []
    for phase, state in status["phases"].items():
        if state not in STATES:
            problems.append(f"phase {phase}: state {state!r} is not one of {', '.join(STATES)}")
    for task, record in status["tasks"].items():
        if not isinstance(record, dict) or record.get("phase") not in status["phases"]:
            problems.append(f"task {task}: names a phase that phase-status.json does not")
            continue
        if record.get("state") not in STATES:
            problems.append(f"task {task}: state {record.get('state')!r} is not one of {', '.join(STATES)}")
        elif status["phases"][record["phase"]] == "closed" and record["state"] != "closed":
            problems.append(f"phase {record['phase']} is closed but task {task} is {record['state']}")
    return problems


def owner_state(owner: str, status: dict) -> str | None:
    """The state an owner counts as: closed when it is closed itself or, for a task, when its phase is; None when no such owner."""
    kind, _, ident = owner.partition(" ")
    if kind == "phase" and ident in status["phases"]:
        return status["phases"][ident]
    if kind == "task" and ident in status["tasks"] and isinstance(status["tasks"][ident], dict):
        record = status["tasks"][ident]
        return "closed" if status["phases"].get(record.get("phase")) == "closed" else record.get("state")
    return None


def entry_problems(entry: Entry, status: dict) -> list[str]:
    fields, problems = entry.fields, []
    kind = fields.get("kind", "")
    required = ["kind", "status", "owner", "what", "removal"] + (["found_by", "accepted_by"] if kind == "mitigation" else ["source"])
    for key in required:
        if not fields.get(key) or PLACEHOLDER.match(fields[key]):
            problems.append(f"{entry.ident}: field {key.replace('_', ' ')} is missing or a placeholder")
    if kind and kind not in KINDS:
        problems.append(f"{entry.ident}: kind {kind!r} is not one of {', '.join(KINDS)}")
    if fields.get("status") and fields["status"] not in ("open", "closed"):
        problems.append(f"{entry.ident}: status {fields['status']!r} is not open or closed")
    if kind == "mitigation":
        if fields.get("accepted_by") and not PLACEHOLDER.match(fields["accepted_by"]) \
                and not ("operator" in fields["accepted_by"].lower() and DATED.search(fields["accepted_by"])):
            problems.append(f"{entry.ident}: accepted by must be the operator's acceptance, with its date (only the operator accepts a mitigation)")
        if fields.get("found_by") and not PLACEHOLDER.match(fields["found_by"]) and not CITED.search(fields["found_by"]):
            problems.append(f"{entry.ident}: found by must cite the review (a report file name, a date or `Gate D #n`)")
    elif kind == "obligation" and fields.get("source") and not PLACEHOLDER.match(fields["source"]) and not CITED.search(fields["source"]):
        problems.append(f"{entry.ident}: source must cite the ruling or review that carries it (a report file name, a date or `Gate D #n`)")
    if fields.get("owner") and owner_state(fields["owner"], status) is None:
        problems.append(f"{entry.ident}: owner {fields['owner']!r} is not a `task <id>` or `phase <id>` that phase-status.json names")
    if fields.get("status") == "closed" and (not fields.get("closed_by") or PLACEHOLDER.match(fields["closed_by"])):
        problems.append(f"{entry.ident}: a closed entry needs `closed by`: the evidence that its removal condition was met")
    return problems


def check(root: Path) -> tuple[list[str], list[str]]:
    """(lines to print, problems)"""
    try:
        text = (root / REGISTER).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise ToolError(f"no debt register at {root / REGISTER}: {exc}") from exc
    status = load_status(root / STATUS)
    entries, problems = parse_register(text)
    problems += status_problems(status)
    seen: set[str] = set()
    for entry in entries:
        if entry.ident in seen:
            problems.append(f"{entry.ident}: appears twice")
        seen.add(entry.ident)
        problems += entry_problems(entry, status)
        owner = entry.fields.get("owner", "")
        if entry.fields.get("status") == "open" and owner_state(owner, status) == "closed":
            problems.append(f"DEBT OWNED BY A CLOSED PHASE OR TASK IS STILL OPEN: {entry.ident} ({owner} is closed): "
                            f"{entry.fields.get('removal', '')}")
    open_entries = [e for e in entries if e.fields.get("status") == "open"]
    by_owner: dict[str, int] = {}
    for entry in open_entries:
        by_owner[entry.fields.get("owner", "?")] = by_owner.get(entry.fields.get("owner", "?"), 0) + 1
    lines = [f"debt register: {len(entries)} entries, {len(open_entries)} open"
             + (": " + ", ".join(f"{owner} {n}" for owner, n in sorted(by_owner.items())) if by_owner else "")]
    return lines, problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="the repository (default: this one)")
    args = parser.parse_args(argv)
    try:
        lines, problems = check(Path(args.root))
    except ToolError as exc:
        print(f"gen2-debt: {exc}", file=sys.stderr)
        return EXIT_TOOL
    for line in lines:
        print(line)
    for problem in problems:
        print(f"DEBT REGISTER PROBLEM: {problem}", file=sys.stderr)
    if problems:
        print(f"gen2-debt: {len(problems)} problem(s)", file=sys.stderr)
        return EXIT_FAIL
    print("gen2-debt: no closed phase or task owns an open entry")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
