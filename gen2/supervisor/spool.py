"""The protected spool: immutable, content-addressed, topic-scoped, size-bounded
artifact storage that trusted station code stages into and the router reads
references from (task 1c).

Trace: design review §5 ("Artifacts and the sole-writer promise": agents write
only isolated scratch outputs; a trusted station stages immutable,
content-addressed artifacts in a protected spool; the router commits
references; never let privileged code open an agent-selected destination
path; bound size; authorize topic-scoped uploads; prevent symlink traversal
and cross-topic access; "a full spool ... is an explicit infrastructure
failure, never a successful completion"); BOUNDARIES.md Station supervisor;
INVARIANTS C-9, C-10; gen2/core/control.py StagedBytes (the read side the
router is handed).

Layout: <root>/<topic id>/<hex digest> holds the bytes and
<root>/<topic id>/<hex digest>.meta their media type and size. Every path is
computed from a validated topic id and the SHA-256 of the bytes, never from
anything an agent chose. Entries are written once: a temporary file is
written, synced and hard-linked to its name (a link never replaces an
existing entry), so a reader sees a whole entry or none. Files are read-only.

Collecting an agent's output (collect) opens one fixed name in the job's
scratch directory relative to a directory descriptor, refusing a symlink
(O_NOFOLLOW, on the directory and on the file), anything that is not a
regular file (a FIFO would block, a device is not output), a file with other
hard links (it may be a file the agent does not own), and anything over the
size bound; it reads at most bound + 1 bytes.

Structural limits: the spool is protected by being a directory the station
owns and agents are never given; nothing here isolates it from another
process of the same user (OS-level isolation is deployment's, 1e). Retention
and pruning are not implemented: entries stay until an explicit, audited
retention policy exists (C-11). A quota counts staged bytes as they are
written by this process; bytes staged by another process on the same root
are counted once this process lists the root again (usage()).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import stat
from pathlib import Path

from gen2.core import canonical

TOPIC = re.compile(r"\A[a-z][a-z0-9-]{0,31}:[a-z0-9][a-z0-9._-]{0,95}\Z")  # common.schema.json#/$defs/topic_id
DIGEST = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")  # one component of a scratch directory: no separator, no "..", no dot-file
MEDIA = re.compile(r"\A[a-z]+/[a-z0-9.+-]{1,64}\Z")


class SpoolFull(Exception):
    """The spool cannot take these bytes: an infrastructure failure, never a
    completion (C-10)."""


class SpoolConflict(Exception):
    """These bytes are already staged for this topic under another media type."""


def _write_once(dir_fd: int, name: str, payload: bytes) -> None:
    tmp = f".tmp-{os.getpid()}-{secrets.token_hex(8)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444, dir_fd=dir_fd)
    try:
        view = memoryview(payload)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(tmp, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd, follow_symlinks=False)
    except FileExistsError:
        pass  # staged meanwhile; content-addressed, so the entry is these bytes (the reader re-hashes)
    finally:
        os.unlink(tmp, dir_fd=dir_fd)
    os.fsync(dir_fd)


def _read_bounded(fd: int, bound: int) -> bytes:
    chunks, total = [], 0
    while total <= bound:
        chunk = os.read(fd, min(1 << 20, bound + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    return b"".join(chunks)


def read_scratch(scratch: str | Path, name: str, bound: int) -> dict:
    """Read the file `name` of a job's scratch directory, as found, without
    following anything. {"status": present | absent | empty | refused, "data",
    "detail"}; refused covers a symlink (on the directory or the file), a
    non-regular file, a hard-linked file and a file over `bound` (C-9). The
    agent chose neither path: the scratch directory is the job's, the name
    the supervisor's."""
    if not NAME.match(name):
        raise ValueError(f"{name!r} is not one component of a scratch directory")
    try:
        dir_fd = os.open(scratch, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {"status": "absent", "data": None, "detail": "the scratch directory is gone"}
    except OSError as exc:
        return {"status": "refused", "data": None, "detail": f"the scratch directory is not a plain directory ({exc.strerror})"}
    try:
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
        except FileNotFoundError:
            return {"status": "absent", "data": None, "detail": None}
        except OSError as exc:  # ELOOP: a symlink
            return {"status": "refused", "data": None, "detail": f"{name} is not a regular file ({exc.strerror})"}
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                return {"status": "refused", "data": None, "detail": f"{name} is not a regular file"}
            if info.st_nlink != 1:
                return {"status": "refused", "data": None, "detail": f"{name} has {info.st_nlink} links"}
            data = _read_bounded(fd, bound)
        finally:
            os.close(fd)
    finally:
        os.close(dir_fd)
    if len(data) > bound:
        return {"status": "refused", "data": None, "detail": f"{name} exceeds the {bound}-byte bound"}
    return {"status": "present" if data else "empty", "data": data or None, "detail": None}


class Spool:
    def __init__(self, root: str | Path, *, max_artifact_bytes: int = 16 << 20, quota_bytes: int = 1 << 30) -> None:
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not stat.S_ISDIR(os.lstat(self.root).st_mode):
            raise SpoolFull(f"{self.root} is not a directory the station owns")
        self.max_artifact_bytes = max_artifact_bytes
        self.quota_bytes = quota_bytes
        self._used: int | None = None

    # -- paths ---------------------------------------------------------------
    def _topic_fd(self, topic_id: str, *, create: bool) -> int | None:
        if not isinstance(topic_id, str) or not TOPIC.match(topic_id):
            raise ValueError(f"{topic_id!r} is not a topic id")
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if create:
                try:
                    os.mkdir(topic_id, 0o700, dir_fd=root_fd)
                except FileExistsError:
                    pass
            try:
                return os.open(topic_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
            except FileNotFoundError:
                return None
        finally:
            os.close(root_fd)

    @staticmethod
    def _name(content_hash: str) -> str:
        if not isinstance(content_hash, str) or not DIGEST.match(content_hash):
            raise ValueError(f"{content_hash!r} is not a sha256 content hash")
        return content_hash[len("sha256:"):]

    # -- staging -------------------------------------------------------------
    def usage(self) -> int:
        """Bytes staged under the root (every topic's entries)."""
        total = 0
        for topic in self.root.iterdir():
            if topic.is_dir() and not topic.is_symlink():
                total += sum(entry.lstat().st_size for entry in topic.iterdir() if not entry.name.startswith(".") and not entry.name.endswith(".meta"))
        self._used = total
        return total

    def stage(self, topic_id: str, data: bytes, media_type: str) -> dict:
        """Stage bytes for a topic; returns their artifact reference. Staging
        the same bytes again is idempotent; the same bytes under another
        media type are a conflict."""
        if not isinstance(media_type, str) or not MEDIA.match(media_type):
            raise ValueError(f"{media_type!r} is not a media type")
        data = bytes(data)
        if len(data) > self.max_artifact_bytes:
            raise SpoolFull(f"{len(data)} bytes exceed the {self.max_artifact_bytes}-byte artifact bound")
        content_hash = canonical.bytes_digest(data)
        ref = {"content_hash": content_hash, "size_bytes": len(data), "media_type": media_type}
        name = self._name(content_hash)
        dir_fd = self._topic_fd(topic_id, create=True)
        try:
            recorded = self._meta(dir_fd, name)
            if recorded is not None and recorded["media_type"] != media_type:
                raise SpoolConflict(f"{content_hash} is staged for {topic_id} as {recorded['media_type']}, not {media_type}")
            if recorded is not None and self._exists(dir_fd, name):
                return ref
            used = self.usage() if self._used is None else self._used
            if used + len(data) > self.quota_bytes:
                raise SpoolFull(f"staging {len(data)} bytes would exceed the {self.quota_bytes}-byte spool quota ({used} used)")
            if recorded is None:
                _write_once(dir_fd, name + ".meta", canonical.canonical_bytes({"media_type": media_type, "size_bytes": len(data)}))
            _write_once(dir_fd, name, data)
            self._used = used + len(data)
            return ref
        finally:
            os.close(dir_fd)

    def collect(self, topic_id: str, scratch: str | Path, name: str, media_type: str) -> dict:
        """Stage the file `name` of a job's scratch directory, as found.
        Returns {"status": present | absent | empty | refused, "ref", "detail"}
        (read_scratch); only present bytes are staged."""
        found = read_scratch(scratch, name, self.max_artifact_bytes)
        ref = self.stage(topic_id, found["data"], media_type) if found["status"] == "present" else None
        return {"status": found["status"], "ref": ref, "detail": found["detail"]}

    # -- the read side (StagedBytes) -----------------------------------------
    @staticmethod
    def _exists(dir_fd: int, name: str) -> bool:
        try:
            return stat.S_ISREG(os.stat(name, dir_fd=dir_fd, follow_symlinks=False).st_mode)
        except FileNotFoundError:
            return False

    def _meta(self, dir_fd: int, name: str) -> dict | None:
        try:
            fd = os.open(name + ".meta", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        try:
            return json.loads(_read_bounded(fd, 4096))
        finally:
            os.close(fd)

    def read(self, content_hash: str, *, topic_id: str) -> bytes | None:
        name = self._name(content_hash)
        dir_fd = self._topic_fd(topic_id, create=False)
        if dir_fd is None:
            return None
        try:
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dir_fd)
            except FileNotFoundError:
                return None
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    return None
                return _read_bounded(fd, self.max_artifact_bytes)
            finally:
                os.close(fd)
        finally:
            os.close(dir_fd)

    def media_type(self, content_hash: str, *, topic_id: str) -> str | None:
        name = self._name(content_hash)
        dir_fd = self._topic_fd(topic_id, create=False)
        if dir_fd is None:
            return None
        try:
            meta = self._meta(dir_fd, name)
            return meta["media_type"] if meta is not None and self._exists(dir_fd, name) else None
        finally:
            os.close(dir_fd)
