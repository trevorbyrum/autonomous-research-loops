"""How a test starts a fresh Python child (not collected as tests).

Every gen-2 test that runs gen-2 code in a child interpreter goes through
here, so that the child imports the code tree the mutation runner points it
at (task 1c: Astra's 1b-repair-2 finding that tools/gen2_mutations.py swapped
modules only in its own interpreter, while fresh children imported the
unmutated files from disk, so no kill resting on a child was real).

The tree is the repository by default. The mutation runner copies gen2/ into
a temporary directory, writes the mutant there, and names that directory in
GEN2_CHILD_ROOT; a child started through these helpers has that tree alone on
its import path, with PYTHONSAFEPATH set so that neither its working
directory nor a script's own directory is put in front of it (task 1c-repair
C1: a working directory holding another gen2/ used to win). So `-m gen2...`,
`-c "import gen2..."` and a script under gen2/ all load the mutant, whatever
working directory a caller passes; an environment that names another import
path is refused. test_children.ChildLaunchRuleTest is a narrow lint of the
literal launch it recognises; the mutation runner, not the lint, attests
which bytes a killing child executed (tools/gen2_mutations.py, "Children").

Tools run as children with an explicit file path (tools/check_boundaries.py
and the like) are not gen-2 code trees: the runner already hands their tests
a mutated copy by path. They may still import gen2 (the DDL checker imports
gen2.store.compat), so env() gives them the same import path.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ROOT_VARIABLE = "GEN2_CHILD_ROOT"


def code_root() -> Path:
    """The tree a child imports gen2 from: the mutation runner's copy while a
    mutant is under test, the repository otherwise."""
    named = os.environ.get(ROOT_VARIABLE)
    return Path(named) if named else REPO


def path(relative: str) -> Path:
    """A file of the code tree (a script a child runs by path)."""
    return code_root() / relative


IMPORT_ROOT = ("PYTHONPATH", "PYTHONSAFEPATH")  # what fixes where a child imports gen2 from


def env(base: dict | None = None) -> dict:
    """The child's environment: the code tree alone on its import path, and
    nothing put in front of it (PYTHONSAFEPATH: not the working directory,
    not a script's directory). A caller's environment that sets either to
    something else is refused, not overridden silently."""
    wanted = {"PYTHONPATH": str(code_root()), "PYTHONSAFEPATH": "1"}  # alone: gen2 is a namespace package, and a second tree would merge into it
    if base is not None:
        conflicting = sorted(name for name in IMPORT_ROOT if name in base and base[name] != wanted[name])
        if conflicting:
            raise ValueError(f"a gen-2 child imports from the code tree alone; this environment sets {conflicting} otherwise")
    out = dict(os.environ if base is None else base)
    out.update(wanted, PYTHONDONTWRITEBYTECODE="1")
    return out


def python(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run `python <args>` from the code tree and wait for it (a working
    directory the caller passes changes nothing it imports)."""
    kwargs.setdefault("cwd", code_root())
    kwargs["env"] = env(kwargs.get("env"))
    return subprocess.run([sys.executable, *args], **kwargs)


def popen(args: list[str], **kwargs) -> subprocess.Popen:
    """Start `python <args>` from the code tree without waiting."""
    kwargs.setdefault("cwd", code_root())
    kwargs["env"] = env(kwargs.get("env"))
    return subprocess.Popen([sys.executable, *args], **kwargs)
