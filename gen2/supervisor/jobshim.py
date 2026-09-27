"""python jobshim.py <job directory>: the launcher of one supervisor-owned job
(task 1c). Standard library only, and run by path, so it depends on nothing
the supervisor process holds: a job outlives the supervisor that started it
(design review §6: delegates and verifiers run as supervisor-owned jobs
outside any harness's child lifetime).

The supervisor starts this in a new session, so the session is the job's
execution group: the executor and every descendant that does not leave the
session belong to it. In order, and only in this order:
  1. take the job's lock, an open-file-description write lock on `lock`
     held for this process's life: "a launcher is alive" is "the lock is
     held" (a lookup only asks whether it is held, F_OFD_GETLK, and never
     takes it, so no lookup can make a launcher give up);
  2. give up if the supervisor has abandoned the job (it looked the job up,
     found no launcher and no identity, and recorded that the executor never
     started — it wrote `abandoned` before taking the lock itself, so a
     launcher that takes the lock afterwards sees it);
  3. record its identity (pid, start time in clock ticks since boot, boot
     id, session) atomically: the supervisor verifies a process by all of
     them, never by pid alone (L-3);
  4. start the executor in the scratch directory, and wait for it;
  5. record how it ended (exit code or signal) atomically.
So an identity file means step 4 may have run, and no identity file with a
free lock means it never did.
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

FLOCK = "hhqqi4x"  # struct flock on Linux (jobs.py asks about this lock with the same layout)


def starttime(pid: int) -> int:
    """Field 22 of /proc/<pid>/stat: start time in clock ticks after boot."""
    stat = Path(f"/proc/{pid}/stat").read_text()
    return int(stat[stat.rindex(")") + 2:].split()[19])


def atomic_write(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def main(argv: list[str]) -> int:
    job = Path(argv[1])
    lock = os.open(job / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.fcntl(lock, fcntl.F_OFD_SETLK, struct.pack(FLOCK, fcntl.F_WRLCK, os.SEEK_SET, 0, 0, 0))
    except OSError as exc:
        if exc.errno in (errno.EAGAIN, errno.EACCES):
            return 75  # another launcher of this job is alive
        raise
    if (job / "abandoned").exists():
        return 0
    order = json.loads((job / "order.json").read_text(encoding="utf-8"))
    pid = os.getpid()
    atomic_write(job / "identity.json", {"pid": pid, "session": os.getsid(0), "starttime": starttime(pid),
                                         "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()})
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", **order["env"]}
    with open(job / "executor.log", "ab") as log:
        executor = subprocess.Popen(order["command"], cwd=job / "scratch", env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True)
        code = executor.wait()
    atomic_write(job / "exit.json", {"code": code if code >= 0 else None, "signal": -code if code < 0 else None})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
