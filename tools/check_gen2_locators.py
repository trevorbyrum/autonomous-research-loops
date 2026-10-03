#!/usr/bin/env python3
"""Gen-2 locator check (stdlib only; task 2q-a): every file and function locator
a gen-2 document cites in backticks must exist.

Gate D #1 finding 6 and Gate D #2 found INVARIANTS entries still describing
helpers (`need()`, `optional()`) that a repair had removed, because nothing
checked a locator against the code. Line numbers drift and are not checked;
NAMES may not drift: a locator that names a file or a function that is not
there fails.

What counts as a locator, in the documents named below (default
docs/gen2/INVARIANTS.md and docs/gen2/DEBT-REGISTER.md), always inside inline
backticks (fenced blocks are skipped). Every backticked span is classified by
its SHAPE alone, never by whether what it names still exists (task
2q-a-repair F4: a citation whose module or class was deleted used to stop
being recognised and so stopped being checked):
  file        `path/to/file.py`, `file.py`, with `:LINE` or `:LINE-LINE`, a
              `#fragment` or trailing arguments ignored; any file with a known
              suffix (.py .sql .json .toml .md .yaml .yml .sh .js .txt .csv
              .example) must be a tracked file, matched whole or as the tail of
              a tracked path (a bare name matches any tracked file of that
              name); a glob (`tools/check_*.py`) needs one match; a directory
              (`gen2/store/schema/`) needs a tracked file under it.
  symbol      `path::name`, and the pair written as a file span, one space, and
              a name span (`adapters/base.py` `_read_body`): the name must be
              defined in that file. For Python, a def, class or assignment of
              that name anywhere in the file (`Class.method` and
              `Outer.Inner.name` must match the nesting); for SQL a table,
              view, trigger or index; for other files the quoted or bare word.
  module path a dotted name whose first part is a first-party package
              (`gen2` or `research_gateway`): `gen2.router.service`,
              `gen2.router.service.Router.commit_outcome`. The longest prefix
              that is a tracked module of the gen-2 surface (production, tests
              or tools) is the module, the rest is a name that must be defined
              in it; no such module fails. A package (a directory) alone is
              enough.
  marked      `code: text` for an ordinary code or data expression (a standard
              library name, a database column, a command) and `history: text`
              for something as it was at an earlier revision or in a retired
              code base: counted, never checked. The marker is the author's
              explicit statement that the span is not a locator.
Any other backticked dotted name (`Class.name`, `module.name`, `os.system`) is
an ERROR, whatever its prefix: it is neither a form above nor marked, and
reading it as prose when its prefix is unknown (or has since been deleted) is
what let a stale locator pass. Write `path::name` for a locator, or mark it.
Outside this: the design record (the flow architecture and methodology
documents and the review reports) is kept outside the repository by the
charter and cited by identity, and a few paths name what is absent by design;
EXTERNAL lists them, each with its reason. Nothing else is exempt.

What this does not establish: that the locator points at the RIGHT definition
(only that the name exists where it says), that the prose around it is true,
or that a span marked `code:` or `history:` is not a locator in disguise (the
marker is a reviewed choice; the summary counts them). A locator spelled
without backticks is not seen. A code name whose last part is a file suffix
(an attribute `Response.json`) reads as a file; mark it. A name a package
`__init__` only re-exports is not defined there: cite the defining file.

Exit 0 all exist, 1 a locator does not, 2 a document cannot be read.

Trace: task 2q-a; Gate D #1 finding 6; Gate D #2 section 5 ("stale H-5 locators"); task 2q-a-repair F4.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

EXIT_OK, EXIT_FAIL, EXIT_TOOL = 0, 1, 2
DEFAULT_DOCS = ("docs/gen2/INVARIANTS.md", "docs/gen2/DEBT-REGISTER.md")
FILE_SUFFIXES = (".py", ".sql", ".json", ".toml", ".md", ".yaml", ".yml", ".sh", ".js", ".txt", ".csv", ".example")
SURFACE = ("gen2/", "gateway/", "tools/")
PACKAGES = ("gen2", "research_gateway")  # first-party packages: a dotted name that starts with one is a module path
MARKED = re.compile(r"^(code|history):\s+\S")
EXTERNAL = (  # (pattern a locator is matched against, why it is not a file of this repository)
    (r"^gen2-flow-architecture-\d{8}\.md$", "the flow architecture, part of the design record kept outside this repository (charter, source-of-truth documents)"),
    (r"^methodology-synthesis-\d{8}\.md$", "the methodology synthesis, part of the design record kept outside this repository (charter)"),
    (r"^reviews/[\w.-]+\.md$", "a review report, part of the design record kept outside this repository (charter)"),
    (r"^preflight\.sh$", "the topic-shipped script of gen-1, absent by design: the behaviour gen-2 refuses (INVARIANTS section 12, item 4)"),
)
SPAN = re.compile(r"`([^`\n]+)`")
PATHLIKE = re.compile(r"^[A-Za-z0-9_./*-]+$")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?$")


class ToolError(Exception):
    pass


def tracked(root: Path) -> list[str]:
    try:
        return subprocess.run(["git", "-C", str(root), "ls-files"], check=True, capture_output=True, text=True, timeout=60).stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"git ls-files failed in {root}: {exc}") from exc


def prose(text: str) -> str:
    """The text with fenced blocks blanked (their lines kept, so line numbers hold)."""
    out, fenced = [], False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            out.append("")
        else:
            out.append("" if fenced else line)
    return "\n".join(out)


def file_core(span: str) -> str | None:
    """The path part of a file-like span (line number, fragment, `::name` and trailing arguments removed), or None."""
    token = span.split()[0] if span.split() else ""
    core = re.sub(r"(::[\w.#]+|#\S*|:\d+(?:-\d+)?)+$", "", token)
    if not PATHLIKE.match(core) or core.startswith(("$", "-")):
        return None
    base = core.rsplit("/", 1)[-1]
    if core.endswith("/"):
        return core if core.strip("/") else None
    if base.endswith(FILE_SUFFIXES) and base.rsplit(".", 1)[0]:
        return core
    return None


def resolve(core: str, files: list[str]) -> list[str]:
    """The tracked files a path locator names: exact, glob, directory prefix, or the tail of a path."""
    if core.endswith("/"):
        return [f for f in files if f.startswith(core) or ("/" + core) in "/" + f][:1]
    if "*" in core:
        return [f for f in files if fnmatch.fnmatchcase(f, core) or fnmatch.fnmatchcase(f, "*/" + core)]
    return [f for f in files if f == core or f.endswith("/" + core)]


def external(core: str) -> str | None:
    for pattern, why in EXTERNAL:
        if re.match(pattern, core):
            return why
    return None


def python_names(text: str) -> set[str]:
    """Every name a Python file defines, plain and qualified by its nesting: defs, classes and assignments."""
    names: set[str] = set()

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(child.name)
                names.add(".".join(scope + [child.name]))
                visit(child, scope + [child.name])
            elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    for leaf in ast.walk(target):
                        if isinstance(leaf, ast.Name):
                            names.add(leaf.id)
                            names.add(".".join(scope + [leaf.id]))
            else:
                visit(child, scope)

    try:
        visit(ast.parse(text), [])
    except SyntaxError:
        pass
    return names


def defines(root: Path, path: str, name: str) -> bool:
    text = (root / path).read_text(encoding="utf-8", errors="replace")
    name = name.removesuffix("()")
    if path.endswith(".py"):
        return name in python_names(text)
    if path.endswith(".sql"):
        return re.search(rf"\b(?:TABLE|VIEW|TRIGGER|INDEX)\s+(?:IF NOT EXISTS\s+)?(?:\w+\.)?{re.escape(name)}\b", text, re.IGNORECASE) is not None
    return re.search(rf'(?<![\w]){re.escape(name)}(?![\w])', text) is not None


def check_document(root: Path, doc: str, files: list[str], modules: dict[str, str]) -> tuple[Counter, list[str]]:
    try:
        text = (root / doc).read_text(encoding="utf-8")
    except OSError as exc:
        raise ToolError(f"{doc} cannot be read: {exc}") from exc
    cleaned = prose(text)
    spans = [(m.start(), m.end(), m.group(1)) for m in SPAN.finditer(cleaned)]
    line_of = lambda offset: cleaned.count("\n", 0, offset) + 1
    problems: list[str] = []
    checked: Counter = Counter()

    def fail(offset: int, span: str, why: str) -> None:
        problems.append(f"{doc}:{line_of(offset)}: `{span}`: {why}")

    consumed: set[int] = set()  # a name span that is the symbol of a file span is that locator's, not a dotted one of its own
    for index, (start, end, span) in enumerate(spans):
        if index in consumed:
            continue
        marked = MARKED.match(span)
        if marked:
            checked[marked.group(1)] += 1
            continue
        core = file_core(span)
        if core is not None:
            checked["files"] += 1
            if external(core):
                continue
            found = resolve(core, files)
            if not found:
                fail(start, span, "names no tracked file")
                continue
            symbol = None
            if "::" in span.split()[0]:
                symbol = span.split()[0].split("::", 1)[1]
            elif index + 1 < len(spans) and spans[index + 1][0] == end + 1 and cleaned[end] == " " and IDENT.match(spans[index + 1][2]) \
                    and file_core(spans[index + 1][2]) is None:
                symbol = spans[index + 1][2]
                consumed.add(index + 1)
            if symbol:
                checked["symbols"] += 1
                symbol = re.sub(r"[#:].*$", "", symbol)
                if not any(defines(root, f, symbol) for f in found):
                    fail(start, f"{span}` `{symbol}" if "::" not in span else span, f"{symbol} is not defined in {', '.join(found[:3])}")
            continue
        if IDENT.match(span) and "." in span:
            name = span.removesuffix("()")
            if name.partition(".")[0] not in PACKAGES:
                problems.append(f"{doc}:{line_of(start)}: `{span}`: UNMARKED DOTTED NAME: write `path::name` for a locator, a full module path (`gen2...`), "
                                "or mark it `code:` (an ordinary expression) or `history:` (a name as it was)")
                continue
            checked["modules"] += 1
            why = module_path_problem(root, name, modules)
            if why:
                fail(start, span, why)
    return checked, problems


def module_path_problem(root: Path, name: str, modules: dict[str, str]) -> str | None:
    """Why a full module path names nothing (or None): the longest prefix that is a module holds the rest as a name."""
    parts = name.split(".")
    for length in range(len(parts), 1, -1):
        path = modules.get(".".join(parts[:length]))
        if path:
            symbol = ".".join(parts[length:])
            return f"{symbol} is not defined in {path}" if symbol and not defines(root, path, symbol) else None
    return None if any(m.startswith(name + ".") for m in modules) else "names no module of this repository"


def module_files(root: Path, files: list[str]) -> dict[str, str]:
    """Dotted module name -> file, for the gen-2 surface (production, tests, tools); a package's `__init__` is the package."""
    return {path.removeprefix("gateway/").removesuffix(".py").replace("/", ".").removesuffix(".__init__"): path
            for path in files if path.endswith(".py") and path.startswith(SURFACE) and (root / path).is_file()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="the repository (default: this one)")
    parser.add_argument("docs", nargs="*", help=f"documents to check (default: {', '.join(DEFAULT_DOCS)})")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        files = tracked(root)
        modules = module_files(root, files)
        total: Counter = Counter()
        problems: list[str] = []
        for doc in args.docs or DEFAULT_DOCS:
            checked, found = check_document(root, doc, files, modules)
            total += checked
            problems += found
    except ToolError as exc:
        print(f"gen2-locators: {exc}", file=sys.stderr)
        return EXIT_TOOL
    print(f"locators: {total['files']} file, {total['symbols']} symbol and {total['modules']} module path checked, "
          f"{total['code']} marked code and {total['history']} marked history, in {len(args.docs or DEFAULT_DOCS)} documents, {len(problems)} that do not exist or are unmarked")
    for problem in problems:
        print(problem if "UNMARKED DOTTED NAME" in problem else f"LOCATOR DOES NOT EXIST: {problem}", file=sys.stderr)
    if problems:
        print(f"gen2-locators: {len(problems)} problem(s): a locator that names something that is not there, or a dotted name that is neither a locator nor marked; "
              "line numbers may drift, names may not", file=sys.stderr)
        return EXIT_FAIL
    print("gen2-locators: every file and function locator exists")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
