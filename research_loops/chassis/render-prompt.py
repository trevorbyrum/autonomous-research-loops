#!/usr/bin/env python3
"""Render a chassis prompt template with LITERAL substitutions.

Replaces the old `sed -e "s#\\${VAR}#$VAR#g"` pipeline, which corrupted
prompts whenever a substituted value contained sed metacharacters: `&`
expanded to the matched pattern and `#` (the delimiter) silently truncated
the value — both reachable through operator-supplied strings like
agent_secondary ("codex exec ... 2>&1"). str.replace has no metacharacters.

Usage: render-prompt.py <template> VAR=value [VAR=value ...]
Values may contain anything, including newlines; every `${VAR}` occurrence
in the template is replaced verbatim.
"""

import sys


def main() -> int:
    template = open(sys.argv[1], encoding="utf-8").read()
    for pair in sys.argv[2:]:
        key, _, value = pair.partition("=")
        template = template.replace("${%s}" % key, value)
    sys.stdout.write(template)
    return 0


if __name__ == "__main__":
    sys.exit(main())
