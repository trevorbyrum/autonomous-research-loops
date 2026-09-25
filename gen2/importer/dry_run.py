"""Dry-run importer skeleton: gen-1 JSON/JSONL state -> a mapping report
against the gen-2 ID and authority scheme. It reads and never writes.

Trace: task 0b (read gen-1 state read-only; report how it maps to the gen-2
ID/authority scheme without writing a gen-2 store; surface, never silently
resolve, every record that does not map cleanly); design review §10 (Phase 4:
freeze, import, reconcile; this is reconnaissance for it); INVARIANTS §12
(what migration preserves; unavailable history is unknown, never zero; host
PIDs are never adopted), RG-8, E-8, RG-U, §11 (gen-1 defects are not
compatibility targets), G-13 (the importer needs its own audited path), C-13
(identity bounds apply to every writer, the importer's generated identities
included); Astra 0b review A2, A3, A5.

What keeps it read-only, and what each part does not cover:
  * Imports. gen2/boundaries.toml lets this module import gen2.core only
    (no store, no sqlite3), so it cannot write a gen-2 store or open gen-1's
    SQLite. That is an import restriction; the graph does not check file
    I/O.
  * Reads (A2). The gen-1 root is opened once, as a directory. Every read
    starts from that descriptor and opens one path component at a time,
    read-only, with O_NOFOLLOW. A symlink anywhere below the root is
    refused and reported, never followed. A ".." or absolute component is
    refused. What is read is the object that was opened, so a component
    swapped after an earlier look cannot redirect the read outside the
    root. Not covered: a file's bytes changing while it is read, and the
    root path itself being replaced before it is opened (the root is bound
    at that open). Nothing outside the root is read or stat'ed. An item's
    cwd is compared with the root as text.
  * The report (A2). The CLI opens the report's directory once. It checks
    by descriptor that the directory is outside the gen-1 root: the
    directory's ancestry is walked through ".." and compared by device and
    inode with the root the reader holds open. The file is created
    relative to that descriptor (O_CREAT | O_EXCL | O_NOFOLLOW), so
    replacing the directory's path afterwards (with a symlink into the
    root, say) does not move the write. The check runs again just before
    and just after the file is created, and nothing is written if the
    directory is then inside the root. Not covered: another process moving
    the opened directory itself into the gen-1 tree between the last check
    and the write. An empty file can also be left if the move lands just
    before the create. The report directory must be one nothing else is
    moving.
  * The managed store (A3). state/control.sqlite3 is never opened. gen-1
    treats the queue as managed when that path exists (research_loops/
    queue.py, QueueStore.__init__). A regular file there blocks, and every
    queue-derived record is marked as coming from a stale snapshot. A
    symlink (to anywhere, or dangling), a non-file, or an entry that cannot
    be examined also blocks, as "cannot verify", with the same stale
    marking. Only a verified absence lets the JSON queue stand as gen-1's
    queue.

Every record gets an explicit status (maps / partial / unmapped). Anything
short of "maps" carries at least one issue naming what is missing and who
must supply it. Nothing is defaulted: no invented zeros, fleets, owners,
deadlines, templates, ratings, confirmations or approvals. Input the
importer cannot interpret is reported, not dropped (A5): fields of the wrong
type, unsupported versions, fields and keys with no mapping, two records
claiming one gen-2 identity, and numerals that are not exactly what they
would be read as.
"""
from __future__ import annotations

import errno
import json
import os
import re
import reprlib
import stat
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path, PurePosixPath

from gen2.core import canonical

REPORT_VERSION = "gen1-import-dry-run/1"
TOPIC_SLUG = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,95}\Z")  # common.schema.json#/$defs/topic_id, after "<fleet>:"
FLEET_ID = re.compile(r"\A[a-z][a-z0-9-]{0,31}\Z")
LOCAL_ID = re.compile(r"\A[A-Za-z][A-Za-z0-9._-]{0,63}\Z")  # common.schema.json#/$defs/local_id
LEDGER_ENTRY = re.compile(r"^## \[(SRC-\d+)\] (external|internal|local)$")
GEN2_COVERAGE = {"searched_ok", "searched_empty", "provider_unavailable", "auth_failed", "metadata_only"}

# The gen-1 formats this skeleton knows (research_loops/queue.py _empty_state,
# topic_authoring.py). Anything else is reported as unsupported.
QUEUE_VERSION = 1
SEMANTIC_STATE_VERSION = 2
SEMANTIC_STATE_KEYS = {"schema_version", "topic_id", "contract_sha256", "authority_sha256", "obligations", "deliverables",
                       "pending_evidence_refs", "contradictions"}
QUEUE_ITEM_MAPPED = {"id", "status", "cwd", "lane", "managed_kind", "completion_lock", "iterations_completed"}
OBLIGATION_MAPPED = {"id", "text", "disposition"}
TEXT_OR_NULL = (str, type(None))
_SHOW = reprlib.Repr()  # gen-1 values quoted in issue text: bounded in depth and length
_SHOW.maxstring = _SHOW.maxother = 80
_show = _SHOW.repr

# gen-1 queue status -> (gen-2 candidate status or None, issue code, what gen-2 needs that gen-1 lacks)
STATUS_MAP = {
    "queued": ("queued", "contract-approval-unrecorded",
               "gen-2 queued needs an approved Contract v2 revision; gen-1 records no approval decision (approve-topic persists none)"),
    "backoff": ("resting", "backoff-is-two-states",
                "gen-1 backoff is both a failure retry and the normal pause between iterations (last_error_kind tells them apart); neither is a gen-2 retry budget"),
    "paused": ("held", "untyped-hold", "a gen-2 hold is typed (class, recoverability, authority), owned, deadlined and says what clears it; gen-1 has a reason string"),
    "needs_attention": ("held", "untyped-hold", "a gen-2 hold is typed (class, recoverability, authority), owned, deadlined and says what clears it; gen-1 has last_error only"),
    "running": (None, "live-execution", "work was running when the snapshot was taken: freeze gen-1 first (Phase 4); host PIDs are never adopted (L-3)"),
    "completed": (None, "completion-unapproved",
                  "gen-2 completion needs an operator completion_approval of a dossier revision under an approved contract (G-8); gen-1 has neither"),
}


class Gen1ParseError(ValueError):
    pass


class InexactNumeral:
    """A gen-1 numeral with a fraction or exponent that binary64 does not hold
    exactly (9007199254740990.6, 1.0000000000000001, 1e400). The token is
    kept as written. It is never rounded into a plausible value, it is not a
    JSON value, and as an identity it is refused (A5)."""

    def __init__(self, token: str) -> None:
        self.token = token

    def __repr__(self) -> str:
        return self.token


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise Gen1ParseError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _no_constant(name: str) -> object:
    raise Gen1ParseError(f"non-finite number {name}")


def _gen1_float(token: str) -> float | InexactNumeral:
    value = float(token)
    if value != value or value in (float("inf"), float("-inf")) or Decimal(repr(value)) != Decimal(token):
        return InexactNumeral(token)
    return value


def parse_gen1_json(data: bytes) -> object:
    """gen-1 JSON as gen-1 wrote it. Duplicate keys and NaN/Infinity are
    refused, as in canonical.parse_json_strict. Integers of any size are
    kept, so that a single out-of-range identity is surfaced on its own
    record (see _bounded) instead of making the whole file unreadable. A
    fractional or exponent numeral binary64 cannot hold exactly is kept as
    its token (InexactNumeral), not rounded. This parser is for reading
    only; what the report carries is canonicalized."""
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant, parse_float=_gen1_float)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise Gen1ParseError(str(exc)) from exc


def _issue(code: str, detail: str, needs: str) -> dict:
    return {"code": code, "detail": detail, "needs": needs}


def _inexact(value: object) -> list[str]:
    if isinstance(value, InexactNumeral):
        return [value.token]
    if isinstance(value, dict):
        return [t for item in value.values() for t in _inexact(item)]
    if isinstance(value, list):
        return [t for item in value for t in _inexact(item)]
    return []


def _record(kind: str, ref: str, target: str | None, mapping: dict, issues: list[dict], *, unmapped: bool = False) -> dict:
    for key, value in list(mapping.items()):
        try:
            inexact = _inexact(value)
            if inexact:
                mapping[key] = None
                issues.append(_issue("numeral-not-exact", f"{key}: {', '.join(inexact)} is not exactly a binary64 number; kept out, not rounded",
                                     "operator: resolve before import"))
                continue
            canonical.canonical_bytes(value)
        except (canonical.CanonicalizationError, RecursionError) as exc:
            mapping[key] = None
            issues.append(_issue("value-unrepresentable", f"{key}: {exc}", "operator: resolve before import"))
    status = "unmapped" if unmapped or target is None else ("partial" if issues else "maps")
    return {"gen1": kind, "ref": ref, "gen2_target": target, "status": status, "mapping": mapping, "issues": issues}


def _type_name(value: object) -> str:
    return "an InexactNumeral" if isinstance(value, InexactNumeral) else type(value).__name__


def _shape(obj: dict, field: str, allowed: tuple[type, ...], what: str) -> dict | None:
    """An issue if `field` is present with a type outside `allowed`."""
    if field in obj and not isinstance(obj[field], allowed):
        return _issue("field-shape", f"{what}.{field} is {_type_name(obj[field])} ({_show(obj[field])}), not {' or '.join(t.__name__ for t in allowed)}",
                      "operator: correct the gen-1 record (nothing is coerced)")
    return None


def _unmapped_fields(obj: dict, mapped: set[str]) -> list[str]:
    return sorted(k for k in obj if k not in mapped)


# -- read access -------------------------------------------------------------

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC


class _Unread(Exception):
    """A path not read; str() is its sources status ("absent: ...",
    "refused: ...", "unreadable: ...")."""


def _identity(st: os.stat_result) -> tuple[int, int]:
    return st.st_dev, st.st_ino


class Gen1Reader:
    """Read-only access to one gen-1 root, bound to the directory descriptor
    opened here (see the module docstring). Paths are relative to the root
    (PurePosixPath), and each is opened component by component with
    O_NOFOLLOW."""

    def __init__(self, root: Path) -> None:
        self.given = Path(os.path.abspath(root))
        self.root = self.given.resolve()
        self.sources: dict[str, str] = {}
        try:
            self._fd: int | None = os.open(self.root, _DIR)
        except OSError:
            self._fd = None
        self.identity = None if self._fd is None else _identity(os.fstat(self._fd))

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "Gen1Reader":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def relative(self, path_text: str) -> PurePosixPath | None:
        """An absolute path text as a path below the root (compared as text
        with the root as given and as resolved; nothing is touched), else
        None."""
        path = PurePosixPath(os.path.normpath(path_text))
        if not path.is_absolute():
            return None
        for base in (self.root, self.given):
            try:
                return path.relative_to(PurePosixPath(base))
            except ValueError:
                continue
        return None

    @staticmethod
    def _why(dir_fd: int, name: str, shown: str, exc: OSError) -> str:
        try:
            st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return "absent"
        except OSError as lstat_error:
            return f"unreadable: {shown}: {lstat_error.strerror}"
        if stat.S_ISLNK(st.st_mode):
            return f"refused: {shown} is a symlink (links are not followed)"
        if exc.errno == errno.ENOTDIR:
            return f"absent: {shown} is not a directory"
        return f"unreadable: {shown}: {exc.strerror}"

    def _walk(self, rel: PurePosixPath) -> int:
        """A descriptor for the directory `rel` below the root."""
        if self._fd is None:
            raise _Unread("unreadable: the gen-1 root is not open")
        if rel.is_absolute() or ".." in rel.parts:
            raise _Unread(f"refused: {rel} is not a plain path below the root")
        fd = os.dup(self._fd)
        try:
            for depth, name in enumerate(rel.parts):
                try:
                    child = os.open(name, _DIR, dir_fd=fd)
                except ValueError:  # an embedded NUL, from a gen-1 id or cwd
                    raise _Unread(f"refused: {_show('/'.join(rel.parts[:depth + 1]))} is not a usable path") from None
                except OSError as exc:
                    raise _Unread(self._why(fd, name, "/".join(rel.parts[:depth + 1]), exc)) from None
                os.close(fd)
                fd = child
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _note(self, rel: PurePosixPath, status: str) -> None:
        if status == "absent":
            self.sources.setdefault(str(rel), status)
        else:
            self.sources[str(rel)] = status

    def read(self, rel: PurePosixPath) -> bytes | None:
        try:
            if rel.name in ("", ".", ".."):
                raise _Unread(f"refused: {rel} does not name a file")
            parent = self._walk(rel.parent)
            try:
                try:
                    fd = os.open(rel.name, _FILE, dir_fd=parent)
                except OSError as exc:
                    raise _Unread(self._why(parent, rel.name, str(rel), exc)) from None
            finally:
                os.close(parent)
            with open(fd, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise _Unread(f"refused: {rel} is not a regular file")
                data = handle.read()
        except _Unread as why:
            self._note(rel, str(why))
            return None
        self.sources[str(rel)] = f"read ({len(data)} bytes)"
        return data

    def status(self, rel: PurePosixPath) -> str | None:
        return self.sources.get(str(rel))

    def is_dir(self, rel: PurePosixPath) -> bool:
        """Whether `rel` is a directory reached without following a link. A
        refusal is recorded in sources; plain absence is not."""
        try:
            os.close(self._walk(rel))
            return True
        except _Unread as why:
            if not str(why).startswith("absent"):
                self._note(rel, str(why))
            return False

    def list_dir(self, rel: PurePosixPath) -> list[str]:
        try:
            fd = self._walk(rel)
        except _Unread as why:
            if not str(why).startswith("absent"):
                self._note(rel, str(why))
            return []
        try:
            return sorted(os.listdir(fd))
        finally:
            os.close(fd)

    def entry_kind(self, rel: PurePosixPath) -> tuple[str, str]:
        """(kind, detail) of the entry `rel` itself, never following it or
        opening it: "absent", "file", or one of "symlink", "directory",
        "other", "unverifiable" (with what was seen)."""
        try:
            parent = self._walk(rel.parent)
        except _Unread as why:
            text = str(why)
            return ("absent", text) if text == "absent" else ("unverifiable", f"an entry that cannot be examined ({text})")
        try:
            try:
                st = os.stat(rel.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return "absent", "absent"
            except OSError as exc:
                return "unverifiable", f"an entry that cannot be examined ({exc.strerror})"
            if stat.S_ISREG(st.st_mode):
                return "file", "a regular file"
            if stat.S_ISLNK(st.st_mode):
                try:
                    target = os.readlink(rel.name, dir_fd=parent)
                except OSError as exc:
                    target = f"<unreadable link: {exc.strerror}>"
                return "symlink", f"a symlink to {target!r}"
            return ("directory", "a directory") if stat.S_ISDIR(st.st_mode) else ("other", f"a file of mode {stat.filemode(st.st_mode)}")
        finally:
            os.close(parent)

    def json(self, rel: PurePosixPath) -> tuple[object | None, str | None]:
        data = self.read(rel)
        if data is None:
            return None, None
        try:
            return parse_gen1_json(data), None
        except Gen1ParseError as exc:
            return None, str(exc)

    def jsonl(self, rel: PurePosixPath) -> tuple[list[dict], int] | None:
        """(parsed lines, malformed line count): malformed lines are counted
        and reported, never dropped silently (gen-1 defect §11.9)."""
        data = self.read(rel)
        if data is None:
            return None
        good, bad = [], 0
        for line in data.splitlines():
            if not line.strip():
                continue
            try:
                value = parse_gen1_json(line)
            except Gen1ParseError:
                bad += 1
                continue
            if isinstance(value, dict):
                good.append(value)
            else:
                bad += 1
        return good, bad


def _not_read(status: str | None) -> bool:
    return status is not None and status.startswith(("refused", "unreadable"))


def _unread_records(reader: Gen1Reader, prefix: PurePosixPath | None, taken: set[str]) -> list[dict]:
    """A record for every refused or unreadable path (below `prefix`, or
    anywhere when None) not already reported: a refused source is missing
    evidence, not an absent one (A2)."""
    out = []
    for key, status in sorted(reader.sources.items()):
        if key in taken or not _not_read(status):
            continue
        if prefix is not None and not PurePosixPath(key).is_relative_to(prefix):
            continue
        taken.add(key)
        out.append(_record("unread input", key, None, {"status": status},
                           [_issue("input-refused" if status.startswith("refused") else "input-unreadable", status,
                                   "operator: provide the file itself inside the gen-1 root, or confirm it is not evidence")], unmapped=True))
    return out


# -- mapping -----------------------------------------------------------------

def _sections(markdown: str) -> dict[str, str]:
    out, current, lines = {}, None, []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if current is not None:
                out[current] = "\n".join(lines).strip()
            current, lines = line[3:].strip(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        out[current] = "\n".join(lines).strip()
    return out


def gen2_topic_id(gen1_id: str, fleet: str | None) -> tuple[str | None, list[dict]]:
    issues = []
    if fleet is None:
        issues.append(_issue("fleet-unassigned", "gen-2 topic ids are fleet-prefixed ('<fleet>:<slug>'); gen-1 has no fleet", "operator: name the fleet (--fleet)"))
    elif not FLEET_ID.match(fleet):
        issues.append(_issue("fleet-invalid", f"{fleet!r} is not a gen-2 fleet id", "operator: a valid fleet id"))
    if not TOPIC_SLUG.match(gen1_id):
        issues.append(_issue("topic-id-not-a-gen2-slug", f"{gen1_id!r} is not a gen-2 topic slug (lower-case, at most 96 characters)",
                             "operator: an explicit rename (lower-casing could merge distinct topics)"))
    if issues:
        return None, issues
    return f"{fleet}:{gen1_id}", []


def _bounded(value: object, what: str, issues: list[dict]) -> int | None:
    """Apply the RA8 identity bound to a value the import would write as an
    identity. The value is checked as parsed, before any conversion: a
    numeral binary64 does not hold exactly, a fraction, a non-number or a
    boolean is not an integer (A5), and an out-of-range integer is surfaced,
    never truncated."""
    if isinstance(value, InexactNumeral) or isinstance(value, bool) or not isinstance(value, (int, float)) \
            or isinstance(value, float) and not value.is_integer():
        issues.append(_issue("identity-not-an-integer", f"{what}: {_show(value)} is not exactly an integer", "operator: resolve before import"))
        return None
    try:
        return canonical.identity_integer(value)
    except canonical.CanonicalizationError as exc:
        issues.append(_issue("identity-out-of-range", f"{what}: {exc}", "operator: resolve before import (identities past 2**53-1 travel as strings)"))
        return None


def map_queue_item(item: dict, index: int, fleet: str | None) -> list[dict]:
    gen1_id = item["id"]
    topic, issues = gen2_topic_id(gen1_id, fleet)
    records = [_record("queue item", gen1_id, "queue_entries" if topic else None, {"topic_id": topic, "priority": _bounded(index + 1, "priority (queue position)", issues)},
                       issues, unmapped=topic is None)]
    status = item.get("status")
    shape = [i for i in (_shape(item, f, TEXT_OR_NULL, f"items[{index}]") for f in ("lane", "managed_kind")) if i]
    if not isinstance(status, str):
        target, status_issues = None, [_issue("field-shape", f"items[{index}].status is {_type_name(status)} ({_show(status)}), not str",
                                              "operator: correct the gen-1 record (nothing is coerced)")]
    else:
        target, code, detail = STATUS_MAP.get(status, (None, "unknown-status", f"gen-1 status {status!r} has no gen-2 counterpart"))
        status_issues = [_issue(code, detail, "operator decision, or the Phase 4 audited import path (ordinary writes create topics at intake only)")]
    if shape:
        target, status_issues = None, status_issues + shape  # which lane it is in cannot be read, so no status is claimed
    elif item.get("lane") == "intake" or item.get("managed_kind") == "intake_discovery":
        target, status_issues = None, [_issue("intake-discovery-item", "a gen-1 intake discovery item is live pre-contract work, not a topic state", "freeze gen-1 first (Phase 4)")]
    records.append(_record("queue status", f"{gen1_id}.status={status if isinstance(status, str) else _show(status)}", "queue_entries.status" if target else None,
                           {"status": target}, status_issues))
    lock = item.get("completion_lock")
    records.append(_record("completion lock", f"{gen1_id}.completion_lock", None, {"legacy_lock": lock},
                           [_issue("legacy-lock-is-not-a-gen2-hash" if lock else "no-lock",
                                   "gen-1's lock is SHA-256 of its own projection of obligation identity, not a JCS content hash (jcs-rfc8785/1)"
                                   if lock else "no completion lock was recorded (add was run without --lock-sha256)",
                                   "keep as legacy provenance; the gen-2 contract hash is computed on import")], unmapped=True))
    if "iterations_completed" in item:
        count_issues: list[dict] = []
        count = _bounded(item["iterations_completed"], "iterations_completed", count_issues)
        count_issues.append(_issue("ordinals-without-history", "gen-2 research ordinals are one per research_pass invocation with its final receipt; gen-1 kept a count, not that history",
                                   "Phase 4: import the count as provenance, not as ordinal rows (§12: unavailable history is unknown)"))
        records.append(_record("accepted iterations", f"{gen1_id}.iterations_completed", "research_ordinals", {"accepted_count": count}, count_issues))
    else:
        records.append(_record("accepted iterations", f"{gen1_id}.iterations_completed", None, {"accepted_count": None},
                               [_issue("count-unknown", "no iteration count recorded: unknown, not zero (RG-U, E-8)", "nothing to invent")], unmapped=True))
    extra = _unmapped_fields(item, QUEUE_ITEM_MAPPED)
    if extra:
        records.append(_record("unmapped fields", f"{gen1_id}.fields", None, {"fields": extra},
                               [_issue("no-gen2-target", f"queue item fields with no mapping in this skeleton: {', '.join(extra)}", "Phase 4 decision (reported, not dropped)")],
                               unmapped=True))
    return records


def map_brief(reader: Gen1Reader, topic_dir: PurePosixPath, gen1_id: str) -> dict:
    rel = topic_dir / "AUTHORITY.md"
    raw = reader.read(rel)
    if raw is None:
        status = reader.status(rel)
        if _not_read(status):
            return _record("intake brief", f"{gen1_id}/AUTHORITY.md", None, {}, [_issue("input-refused", f"AUTHORITY.md was not read ({status})",
                                                                                           "operator: the brief file itself, inside the gen-1 root")], unmapped=True)
        draft = reader.entry_kind(topic_dir / "DRAFT-AUTHORITY.md")[0] == "file"
        return _record("intake brief", f"{gen1_id}/AUTHORITY.md", None, {}, [_issue("no-brief", "no AUTHORITY.md" + (" (a DRAFT-AUTHORITY.md exists: still in gen-1 intake)" if draft else ""),
                                                                                   "operator: a brief to confirm")], unmapped=True)
    sections = _sections(raw.decode("utf-8", errors="replace"))
    verbatim = sections.get("Operator brief (verbatim)")
    assumptions = [line[2:].strip() for line in sections.get("Assumptions", "").splitlines() if line.startswith("- ")]
    qa = reader.read(topic_dir / "QA-RECORD.md")
    confirmation_evidence = bool(qa) and bool(_sections(qa.decode("utf-8", errors="replace")).get("Operator confirmation"))
    issues = [_issue("brief-slot-missing", f"gen-1 has no {slot!r} slot", "operator, at re-confirmation") for slot in ("feeds", "evidence_that_would_change_it", "constraints", "operator_hypotheses")]
    if verbatim is None:
        issues.append(_issue("brief-slot-missing", "AUTHORITY.md has no 'Operator brief (verbatim)' section", "operator"))
    issues.append(_issue("owner-unknown", "gen-1 records no brief owner", "operator: an owner"))
    issues.append(_issue("deadline-unknown", "gen-1 records no review deadline", "operator: a deadline"))
    issues.append(_issue("confirmation-unrecorded",
                         "QA-RECORD.md has a non-empty 'Operator confirmation' section, but no actor, time or decision record" if confirmation_evidence
                         else "no durable confirmation evidence in gen-1",
                         "operator: a brief_confirmation decision on the imported version (it imports awaiting_confirmation)"))
    mapping = {"brief_id": "brief-1", "version": 1, "parent_version": None, "status": "awaiting_confirmation",
               "objective_in_operator_words": verbatim, "surfaced_assumptions": assumptions, "legacy_confirmation_evidence": confirmation_evidence}
    return _record("intake brief", f"{gen1_id}/AUTHORITY.md", "intake_briefs", mapping, issues)


def map_semantic_state(reader: Gen1Reader, topic_dir: PurePosixPath, gen1_id: str) -> list[dict]:
    rel = topic_dir / "SEMANTIC-STATE.json"
    state, error = reader.json(rel)
    ref = f"{gen1_id}/SEMANTIC-STATE.json"
    if state is None:
        status = reader.status(rel)
        code = "unparseable" if error else ("input-refused" if _not_read(status) else "absent")
        return [_record("semantic state", ref, None, {}, [_issue(code, error or (status if _not_read(status) else "no SEMANTIC-STATE.json"), "operator")], unmapped=True)]
    if not isinstance(state, dict):
        return [_record("semantic state", ref, None, {}, [_issue("unparseable", "not a JSON object", "operator")], unmapped=True)]
    version = state.get("schema_version")
    if type(version) is not int or version != SEMANTIC_STATE_VERSION:
        return [_record("semantic state", ref, None, {"schema_version": version, "keys": sorted(state)},
                        [_issue("unsupported-schema-version", f"schema_version {_show(version)}: this skeleton reads version {SEMANTIC_STATE_VERSION} only, so none of the file is interpreted",
                                "a mapping for that version, or the operator")], unmapped=True)]
    records = []
    unknown = _unmapped_fields(state, SEMANTIC_STATE_KEYS)
    if unknown:
        records.append(_record("semantic state", ref, None, {"keys": unknown},
                               [_issue("unrecognized-material", f"keys outside the version-{SEMANTIC_STATE_VERSION} format: {', '.join(unknown)}", "operator: what they hold (reported, not dropped)")],
                               unmapped=True))
    for key in ("obligations", "deliverables", "contradictions", "pending_evidence_refs"):
        if state.get(key) is not None and not isinstance(state[key], list):
            records.append(_record(key, f"{gen1_id}#{key}", None, {}, [_shape(state, key, (list,), "SEMANTIC-STATE")], unmapped=True))
    obligations = state.get("obligations") if isinstance(state.get("obligations"), list) else []
    ids = [o["id"] for o in obligations if isinstance(o, dict) and isinstance(o.get("id"), str)]
    for index, obl in enumerate(obligations):
        where = f"obligations[{index}]"
        if not isinstance(obl, dict) or not isinstance(obl.get("id"), str):
            what = _type_name(obl) if not isinstance(obl, dict) else f"an object whose id is {_type_name(obl.get('id'))}"
            records.append(_record("obligation", f"{gen1_id}#{where}", None, {},
                                   [_issue("field-shape", f"{where} is {what}, not an object with a string id", "operator: correct the gen-1 record")], unmapped=True))
            continue
        oid = obl["id"]
        issues = [_issue("obligation-contract-fields-missing", "Contract v2 obligations need a template, facet tags, a stopping profile and an operator importance rating; gen-1 has text only",
                         "S3 contract construction on import (operator approves)")]
        if not LOCAL_ID.match(oid):
            issues.append(_issue("obligation-id-not-a-local-id", f"{oid!r} is not a gen-2 local id", "operator: a rename"))
        if ids.count(oid) > 1:
            issues.append(_issue("target-identity-collision", f"{ids.count(oid)} obligations share the id {oid!r}: each would be obligation {oid!r} of this topic",
                                 "operator: which one it is (the importer does not rename or merge)"))
        issues += [i for i in (_shape(obl, f, TEXT_OR_NULL, where) for f in ("text", "disposition")) if i]
        disposition = obl.get("disposition")
        if isinstance(disposition, str) and disposition != "open":
            issues.append(_issue("disposition-is-not-verification", f"gen-1 disposition {disposition!r} is an agent-written state; gen-2 accepted support needs a verification receipt (V-4)",
                                 "import claims provisional at most; re-verify"))
        extra = _unmapped_fields(obl, OBLIGATION_MAPPED)
        if extra:
            issues.append(_issue("fields-not-mapped", f"obligation fields with no mapping in this skeleton: {', '.join(extra)}", "Phase 4 decision (reported, not dropped)"))
        text = obl.get("text")
        records.append(_record("obligation", f"{gen1_id}#{oid}", "obligations", {"obligation_id": oid, "text": text if isinstance(text, TEXT_OR_NULL) else None}, issues))
    for key, why in (("deliverables", "Contract v2 has no deliverables list"), ("contradictions", "the contradiction ledger is built before Phase 2 stopping"),
                     ("pending_evidence_refs", "no gen-2 pending-evidence record")):
        if isinstance(state.get(key), list) and state[key]:
            records.append(_record(key, f"{gen1_id}#{key}", None, {"count": len(state[key])}, [_issue("no-gen2-target", why, "Phase 2/4 decision")], unmapped=True))
    return records


def map_source_ledger(reader: Gen1Reader, topic_dir: PurePosixPath, gen1_id: str) -> list[dict]:
    raw = reader.read(topic_dir / "SOURCE-LEDGER.md")
    if raw is None:
        return []
    records, current = [], None
    for line in raw.decode("utf-8", errors="replace").splitlines() + ["## [END] local"]:
        match = LEDGER_ENTRY.match(line)
        if match or line == "## [END] local":
            if current is not None:
                sid, kind, fields = current
                url = fields.get("url")
                if kind == "external" and url:
                    scheme = "doi" if re.match(r"https?://(dx\.)?doi\.org/", url) else "url"
                    value = re.sub(r"https?://(dx\.)?doi\.org/", "", url) if scheme == "doi" else url
                    records.append(_record("source", f"{gen1_id}#{sid}", "works", {"identity_scheme": scheme, "identity_value": value},
                                           [_issue("work-identity-unverified", "a gen-1 ledger URL is an agent-written citation, not a gateway-captured record", "Phase 4: re-resolve through the gateway")]))
                else:
                    records.append(_record("source", f"{gen1_id}#{sid}", None, {"kind": kind},
                                           [_issue("no-work-identity", f"a {kind} ledger entry has no external identity for works", "Phase 4 decision")], unmapped=True))
            current = (match.group(1), match.group(2), {}) if match else None
        elif current is not None and line.startswith("- ") and ":" in line:
            key, _, value = line[2:].partition(":")
            current[2][key.strip()] = value.strip()
    return records


def map_jsonl_history(reader: Gen1Reader, rel: PurePosixPath, ref: str, what: str) -> dict | None:
    result = reader.jsonl(rel)
    if result is None:
        return None
    lines, bad = result
    issues = [_issue("no-gen2-target", f"{what}: no gen-2 table yet", "Phase 4 (§12: available usage history is preserved)")]
    if bad:
        issues.append(_issue("malformed-lines", f"{bad} line(s) are not JSON objects: reported, not dropped (gen-1 defect §11.9)", "operator review"))
    return _record("history", ref, None, {"lines": len(lines), "malformed_lines": bad}, issues, unmapped=True)


STATE = PurePosixPath("state")
MANAGED = STATE / "control.sqlite3"


def dry_run(root: str | Path, fleet: str | None = None) -> dict:
    """The mapping report for the gen-1 root. Reads only."""
    with Gen1Reader(Path(root)) as reader:
        return map_gen1(reader, fleet)


def _managed_store(reader: Gen1Reader, blocking: list[dict]) -> str | None:
    """None when state/control.sqlite3 is verifiably absent; else the stale
    label's detail, with the blocking issue added (A3: fail closed)."""
    kind, detail = reader.entry_kind(MANAGED)
    if kind == "absent":
        return None
    needs = "a read path for the managed store (a boundary amendment: this module has no sqlite3 grant), or an export from it"
    if kind == "file":
        reader.sources[str(MANAGED)] = "present, not read"
        blocking.append(_issue("managed-store-not-read",
                               "state/control.sqlite3 exists: gen-1's authoritative queue and work state live there, and state/queue.json is a frozen pre-migration snapshot", needs))
        return "from state/queue.json, which a managed deployment no longer updates"
    reader.sources[str(MANAGED)] = f"{detail}; not followed or read"
    blocking.append(_issue("managed-store-unverifiable",
                           f"state/control.sqlite3 is {detail}. gen-1 runs managed when that path exists, and the importer cannot establish whether it does "
                           "without following or opening it, so state/queue.json may be a frozen pre-migration snapshot",
                           "operator: replace it with the store file or remove it, knowing which queue is authoritative; " + needs))
    return "from state/queue.json, which may be a stale snapshot: whether a managed store exists could not be verified"


def map_gen1(reader: Gen1Reader, fleet: str | None) -> dict:
    blocking: list[dict] = []
    if not reader.is_open:
        blocking.append(_issue("no-gen1-root", f"{reader.root} is not a directory", "operator: the gen-1 root"))
        return _report(reader, fleet, blocking, [], [])
    stale = _managed_store(reader, blocking)
    queue, error = reader.json(STATE / "queue.json")
    queue_status = reader.status(STATE / "queue.json")
    topics, other = [], []
    if error:
        blocking.append(_issue("queue-unparseable", error, "operator"))
    elif _not_read(queue_status):
        blocking.append(_issue("queue-not-read", f"state/queue.json was not read ({queue_status})", "operator: the queue file itself, inside the gen-1 root"))
    elif queue is None and stale is None:
        blocking.append(_issue("queue-absent", "no state/queue.json: no gen-1 queue to map (is this a gen-1 root?)", "operator: the gen-1 root"))
    items = queue.get("items") if isinstance(queue, dict) else None
    if queue is not None and not isinstance(items, list):
        blocking.append(_issue("queue-shape", "state/queue.json has no items list", "operator"))
        items = None
    elif isinstance(queue, dict) and (type(queue.get("version")) is not int or queue["version"] != QUEUE_VERSION):
        blocking.append(_issue("queue-version-unsupported", f"state/queue.json version {_show(queue.get('version'))}: this skeleton reads version {QUEUE_VERSION} only, so no item is mapped",
                               "a mapping for that version, or the operator"))
        items = None
    if isinstance(queue, dict) and items is not None:
        extra = _unmapped_fields(queue, {"version", "items"})
        if extra:
            other.append(_record("queue state", "state/queue.json", None, {"fields": extra},
                                 [_issue("no-gen2-target", f"queue-level fields with no mapping in this skeleton: {', '.join(extra)}", "Phase 4 decision (reported, not dropped)")]
                                 + ([_issue("stale-snapshot", stale, "the managed store's state")] if stale is not None else []), unmapped=True))
    valid_ids = [item["id"] for item in items or [] if isinstance(item, dict) and isinstance(item.get("id"), str)]
    taken: set[str] = set()
    for index, item in enumerate(items or []):
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            what = "not an object" if not isinstance(item, dict) else f"its id is {_type_name(item.get('id'))} ({_show(item.get('id'))}), not a string"
            record = _record("queue item", f"items[{index}]", None, {}, [_issue("queue-shape", f"items[{index}]: {what}", "operator")], unmapped=True)
            if stale is not None:
                record["issues"].append(_issue("stale-snapshot", stale, "the managed store's state"))
            other.append(record)
            continue
        gen1_id = item["id"]
        records = map_queue_item(item, index, fleet)
        if valid_ids.count(gen1_id) > 1:
            positions = [f"items[{i}]" for i, it in enumerate(items) if isinstance(it, dict) and it.get("id") == gen1_id]
            records[0]["issues"].append(_issue("target-identity-collision", f"{', '.join(positions)} share the id {gen1_id!r}: each would be the same gen-2 topic",
                                               "operator: which item is the topic (the importer does not rename or merge)"))
            records[0]["status"] = "unmapped" if records[0]["status"] == "unmapped" else "partial"
        if stale is not None:
            for record in records:
                record["issues"].append(_issue("stale-snapshot", stale, "the managed store's state"))
                record["status"] = "unmapped" if record["status"] == "unmapped" else "partial"
        cwd = item.get("cwd")
        cwd_issue = _shape(item, "cwd", TEXT_OR_NULL, f"items[{index}]")
        topic_dir = _topic_dir(reader, cwd, gen1_id)
        if cwd_issue:
            records.append(_record("topic directory", gen1_id, None, {"cwd": None}, [cwd_issue], unmapped=True))
        cwd_rel = reader.relative(cwd) if isinstance(cwd, str) else None
        if topic_dir is not None and isinstance(cwd, str) and cwd_rel != topic_dir:
            records.append(_record("topic directory", gen1_id, None, {"cwd": cwd, "read_from": str(topic_dir)},
                                   [_issue("cwd-not-used", "the item's cwd is not a directory inside the gen-1 root; its files were read from topics/<id>, which gen-1 may not keep in step",
                                           "operator: confirm which directory is the topic's")], unmapped=True))
        if topic_dir is None:
            records.append(_record("topic directory", gen1_id, None, {"cwd": cwd if isinstance(cwd, str) else None},
                                   [_issue("topic-dir-not-found", "neither the item's cwd nor topics/<id> is a directory inside the gen-1 root (links are not followed)",
                                           "operator: the topic's files")], unmapped=True))
        else:
            records.append(map_brief(reader, topic_dir, gen1_id))
            records += map_semantic_state(reader, topic_dir, gen1_id)
            records += map_source_ledger(reader, topic_dir, gen1_id)
            for name in reader.list_dir(topic_dir / "logs"):
                if name.endswith(".jsonl"):
                    record = map_jsonl_history(reader, topic_dir / "logs" / name, f"{gen1_id}/logs/{name}", "topic log history")
                    if record:
                        records.append(record)
            taken |= {str(topic_dir / n) for n in ("AUTHORITY.md", "SEMANTIC-STATE.json")}  # their records already say so
            records += _unread_records(reader, topic_dir, taken)
        topics.append({"gen1_id": gen1_id, "gen2_topic_id": records[0]["mapping"]["topic_id"], "records": records})
    events = map_jsonl_history(reader, STATE / "events.jsonl", "state/events.jsonl", "usage ledger")
    if events:
        other.append(events)
    stations, s_error = reader.json(STATE / "stations.json")
    if stations is not None or s_error:
        other.append(_record("station configuration", "state/stations.json", None, {},
                             [_issue("no-gen2-target", s_error or "station profiles map to the Phase 1 config bundle registry", "Phase 1")], unmapped=True))
    taken.add(str(STATE / "queue.json"))  # its blocking issue already says so
    other += _unread_records(reader, None, taken)
    return _report(reader, fleet, blocking, topics, other)


def _topic_dir(reader: Gen1Reader, cwd: object, gen1_id: str) -> PurePosixPath | None:
    """The item's cwd if it names a directory inside the root, else
    topics/<id> (gen-1's checkpoint publication hardcodes that layout);
    never a path outside, never through a link."""
    candidates = [reader.relative(cwd) if isinstance(cwd, str) else None, PurePosixPath("topics") / gen1_id]
    for candidate in candidates:
        if candidate is not None and reader.is_dir(candidate):
            return candidate
    return None


def _report(reader: Gen1Reader, fleet: str | None, blocking: list[dict], topics: list[dict], other: list[dict]) -> dict:
    records = [r for t in topics for r in t["records"]] + other
    summary = {status: sum(1 for r in records if r["status"] == status) for status in ("maps", "partial", "unmapped")}
    summary["records"] = len(records)
    summary["issues"] = sum(len(r["issues"]) for r in records) + len(blocking)
    summary["blocking"] = len(blocking)
    return {"report_version": REPORT_VERSION, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "gen1_root": str(reader.root), "fleet_id": fleet, "writes": "none: dry run (no gen-2 store, no gen-1 file)",
            "sources": dict(sorted(reader.sources.items())), "blocking": blocking, "topics": topics, "other": other, "summary": summary}


def render(report: dict) -> str:
    """The report as canonical JSON text (deterministic for a given input)."""
    return json.dumps(canonical.parse_json_strict(canonical.canonical_bytes(report)), indent=2, ensure_ascii=False) + "\n"


# -- the report file (the one write) -------------------------------------------

class ReportRefused(Exception):
    pass


def _outside_root(dir_fd: int, root: tuple[int, int] | None) -> bool:
    """Whether the directory dir_fd refers to is outside the gen-1 root, by
    descriptor: its ancestry, walked through "..", is compared by device and
    inode with the root the reader holds open."""
    if root is None:
        return True
    fd = os.dup(dir_fd)
    try:
        while True:
            here = _identity(os.fstat(fd))
            if here == root:
                return False
            parent = os.open("..", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd)
            fd = parent
            if _identity(os.fstat(fd)) == here:
                return True  # "/" is its own parent
    finally:
        os.close(fd)


def _report_directory(target: Path) -> tuple[int, str]:
    """(descriptor of the report's directory, file name), refused early if
    the file exists. Whether the directory is inside the gen-1 root is
    decided by _write_report, by descriptor, just before and after the file
    is created."""
    if target.name in ("", ".", ".."):
        raise ReportRefused(f"{target} does not name a file")
    try:
        dir_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        raise ReportRefused(f"cannot open the report's directory {target.parent}: {exc.strerror}") from None
    try:
        os.stat(target.name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return dir_fd, target.name
    os.close(dir_fd)
    raise ReportRefused(f"{target} exists; the report goes to a new file")


def _write_report(dir_fd: int, name: str, text: str, reader: Gen1Reader) -> None:
    if not _outside_root(dir_fd, reader.identity):
        raise ReportRefused("the report's directory is inside the gen-1 root, and the importer never writes gen-1: nothing was created")
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o666, dir_fd=dir_fd)
    except FileExistsError:
        raise ReportRefused(f"{name} exists; the report goes to a new file") from None
    with open(fd, "w", encoding="utf-8") as handle:
        if not _outside_root(dir_fd, reader.identity):
            raise ReportRefused(f"the report's directory moved inside the gen-1 root while {name} was being created: "
                                f"an empty {name} was left there and nothing was written to it")
        handle.write(text)


def main(argv: list[str] | None = None) -> int:
    """python -m gen2.importer --gen1-root PATH [--fleet ID] [--report PATH].
    Exit 0: report produced, no blocking issue; 1: report produced with
    blocking issues; 2: refused (the report would land inside the gen-1 root,
    or over an existing file, or its directory cannot be opened)."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="gen-2 dry-run importer: map gen-1 JSON/JSONL state, write nothing")
    parser.add_argument("--gen1-root", required=True, type=Path)
    parser.add_argument("--fleet", help="the gen-2 fleet these topics belong to (gen-1 has none; nothing is assumed)")
    parser.add_argument("--report", type=Path, help="write the report to this new file (never inside the gen-1 root); default: stdout")
    args = parser.parse_args(argv)
    root = args.gen1_root.resolve()
    with Gen1Reader(root) as reader:
        destination = None
        try:
            if args.report is not None:
                destination = _report_directory(Path(os.path.abspath(args.report)))
            report = map_gen1(reader, args.fleet)
            text = render(report)
            if destination is None:
                sys.stdout.write(text)
            else:
                _write_report(*destination, text, reader)
        except ReportRefused as refused:
            print(f"refused: {refused}", file=sys.stderr)
            return 2
        finally:
            if destination is not None:
                os.close(destination[0])
    s = report["summary"]
    print(f"gen2 import dry run: {s['records']} records ({s['maps']} map, {s['partial']} partial, {s['unmapped']} unmapped), "
          f"{s['issues']} issues, {s['blocking']} blocking; nothing written to gen-1 or a gen-2 store", file=sys.stderr)
    return 1 if report["blocking"] else 0
