"""The offline executor child: `python -m gen2.tests.offline_child <directory>`, the production child with the fixture agent installed.

Not collected as tests. It is gen2.app.child.main with `agent=OfflineAgent()` and the production builder table, so every model purpose
runs the real job, validator and pure builder against canned judgments (the live runner entrance stays closed). The driver's `child_module`
names it. Replays the T6 wrapper contract: `inputs/prompt.md` and `inputs/input.json` read, `out/judgment.json` written, `outcome.json` collected.
"""
import sys

from gen2.app import child
from gen2.tests.offline_agent import OfflineAgent

if __name__ == "__main__":
    sys.exit(child.main(sys.argv[1:], agent=OfflineAgent()))
