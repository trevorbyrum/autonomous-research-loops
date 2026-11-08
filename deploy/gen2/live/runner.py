"""V7 §4: no-argument static-dummy-key launcher; real qualification is Q11."""
import hashlib
import os
import stat
import sys

PINS = {
    "config.toml": {"f14d75f89c958edde311e0cbb5d90e83b68517c0cc720920641bc3ec5fbe6f4e",
                    "091116a3ed2da058bf14c48bcb267ce2004971b1866db403f0830ae82e556752"},
    "models.json": {"62d809889367324c104b13a4881e115286085d5674ffa77ab790b48c63002d10"},
    "auth.json": {"65790c43345b599f4b6a86174bfce09490505e81f62aeb0f0ecd3d664d7ed1b5",
                  "440dfaf98b1ca5b7603cead505789bf8cd025b39658679c4a6d2a347018f33bc"},
}


def read_file(directory, name, bound):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o400 or before.st_uid != os.geteuid():
            raise ValueError("seed/input type, links or mode")
        data = bytearray()
        while len(data) <= bound:
            chunk = os.read(fd, min(65536, bound + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        stable = ("st_dev", "st_ino", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, k) != getattr(os.fstat(fd), k) for k in stable) or len(data) != before.st_size or len(data) > bound:
            raise ValueError("changed or oversized seed/input")
        return bytes(data)
    finally:
        os.close(fd)


def work_prompt(directory):
    prompt = read_file(directory, "prompt.md", 16384).decode("utf-8")
    task = read_file(directory, "input.json", 1 << 20).decode("utf-8")
    if not prompt.strip():
        raise ValueError("empty prompt")
    return prompt + "\n\nInput JSON:\n" + task


def launch(seed="/seed", home="/auth/codex", inputs="/inputs"):
    if len(sys.argv) != 1:
        raise ValueError("runner accepts no arguments")
    with_dir = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    seed_fd, home_fd = os.open(seed, with_dir), os.open(home, with_dir)
    try:
        for fd in (seed_fd, home_fd):
            info = os.fstat(fd)
            if stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid():
                raise ValueError("seed/auth directory ownership or mode")
        if set(os.listdir(seed_fd)) != set(PINS) or os.listdir(home_fd):
            raise ValueError("seed membership or nonfresh auth home")
        files = {name: read_file(seed_fd, name, 1 << 20) for name in PINS}
        if sum(map(len, files.values())) > 1 << 20:
            raise ValueError("aggregate seed bound")
        for name, data in files.items():
            if hashlib.sha256(data).hexdigest() not in PINS[name]:
                raise ValueError("seed hash")
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=home_fd)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            if read_file(home_fd, name, len(data)) != data:
                raise ValueError("auth copy hash")
        if set(os.listdir(seed_fd)) != set(PINS) or any(read_file(seed_fd, n, len(d)) != d for n, d in files.items()):
            raise ValueError("seed changed")
    finally:
        os.close(seed_fd)
        os.close(home_fd)
    input_fd = os.open(inputs, with_dir)
    try:
        prompt = work_prompt(input_fd)
    finally:
        os.close(input_fd)
    invocation = os.environ["GEN2_INVOCATION_ID"]
    if not prompt or not invocation or len(invocation) > 256:
        raise ValueError("prompt/invocation")
    os.mkdir("/work/home", 0o700)
    env = dict(PATH="/usr/local/bin:/usr/bin:/bin", HOME="/work/home", CODEX_HOME="/auth/codex",
               SHELL="/bin/bash", LANG="C.UTF-8", LC_ALL="C.UTF-8", TMPDIR="/tmp", TERM="dumb",
               GEN2_INVOCATION_ID=invocation)
    os.execve("/usr/local/bin/codex", ["codex", "exec", "--strict-config", "--json", "--ephemeral",
              "--skip-git-repo-check", "--ignore-rules", "--cd", "/work", "--color", "never", "--output-last-message", "/out/judgment.json", "--", prompt], env)


if __name__ == "__main__":
    launch()
