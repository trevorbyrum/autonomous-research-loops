"""Print the config-bundle `policy.executors` pin fragment for mounted prompt files.

Trace: 2e2-min T12-D; DEPLOYMENT-CONTRACT §2 (prompts are mounted, hash-pinned);
config-bundle policy.executors (T12-A). Reads `<dir>/<kind>.<purpose>.md` and
prints [{kind, purpose, prompt: {version, content_hash}}] with the byte digest
of each file (canonical.bytes_digest). It adds no limits or deadlines: those are
the operator's, so the fragment is merged into a bundle, never accepted whole.
Not covered: that the active bundle's version binds this content (the router
checks that); a file whose name does not fit the pattern is refused, not skipped.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from gen2.core import canonical

NAME = re.compile(r"\A(research_pass|discovery|delegate|verification|checkpoint)\.([A-Za-z][A-Za-z0-9_-]{0,63})\.md\Z")


def pins(directory: Path, version: int) -> list[dict]:
    out = []
    for path in sorted(directory.iterdir()):
        match = NAME.match(path.name)
        if match is None or not path.is_file():
            raise ValueError(f"not a prompt file name <kind>.<purpose>.md: {path.name}")
        out.append({"kind": match[1], "purpose": match[2],
                    "prompt": {"version": version, "content_hash": canonical.bytes_digest(path.read_bytes())}})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        sys.stdout.write(json.dumps(pins(args.directory, args.version), indent=1) + "\n")
    except (OSError, ValueError) as error:
        sys.stderr.write(f"gen2_prompt_pins: {error}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
