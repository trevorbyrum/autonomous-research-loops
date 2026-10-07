#!/usr/bin/env python3
"""The shared differential core of the gateway drivers (task 2q-e1; Astra's 2q-b5 review, C1 and C2), built on the ideas of tools/gen2_replay_compare.py: one exact relation, no weaker one.

A driver observes the old tree and the new one with the same code and records what it saw: `run = Run("link"); run.observe(group, case, value, keep=...); run.finish(path)`.
  * Exact encoding (`encode`): a value is kept as it is. str contents, int, float, bool and None are their own JSON scalars; every container is tagged with its type (a list, a tuple,
    a dict as its ordered pairs, a set, a subclass by its qualified name, bytes by their hex), so `{"a": 1}` and `[["'a'", 1]]` never meet. A type it does not know is refused, never
    `repr`ed. Nothing is normalised in what a driver records: a generated clock is fixed at its source (`fixed_datetime`), and the one harness-owned value, a loopback listener's
    allocated port, is named (`loopback`).
  * Completeness: a manifest (`freeze`) holds, per driver and group, the number of cases and the digest of their identities. A run is refused, and the verdict is `unresolved`, never
    equivalent, when it is empty or partial, has a group or a case more or fewer, was not completed by its driver, or its runner did not write `finished` (after checking every exit status).
  * Verdicts, per group, as the engine's: `same` (every run of a tree equals its tree's first, and the two firsts are equal), `different` (no run disagrees with its own tree's first and
    the firsts differ), `unresolved` (some run disagrees with its own tree's first, or the driver is refused: the source is named, to be fixed at its seam). Exit 0, 1, 2.

    python tools/gen2_differential.py freeze OUT.json RUN_DIR RUN_DIR [...]        the manifest that (at least two) baseline runs agree on
    python tools/gen2_differential.py compare MANIFEST.json --before RUN_DIR RUN_DIR [...] --after RUN_DIR [...] [--report OUT.json]
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import os
import pathlib
import re
import runpy
import sys

differences = runpy.run_path(str(pathlib.Path(__file__).with_name("gen2_replay_compare.py")))["differences"]   # type for type, NaN equal to NaN: the engine's own


class Obj(tuple):
    """A driver's stand-in for an object that cannot be encoded as itself (a Rec, an Element): its kind and its parts. It never equals the same parts as a plain tuple."""


def encode(x):
    """The exact JSON-safe form of `x`. Every array in it is tagged (`["list", [...]]`), so no value can be taken for another."""
    kind = type(x)
    if x is None or kind in (bool, int, float, str):
        return x
    if kind in (bytes, bytearray):
        return [kind.__name__, x.hex()]
    for base in (dict, list, tuple, frozenset, set):
        if isinstance(x, base):
            break
    else:
        raise TypeError(f"{kind.__qualname__} cannot be encoded exactly: convert it in the driver, where the conversion can be read")
    tag = base.__name__ if kind is base else f"{base.__name__}:{kind.__qualname__}"   # a class by its qualified name, not its module: where a class lives is what a refactoring changes
    if base is dict:
        return [tag, [[encode(k), encode(v)] for k, v in x.items()]]   # insertion order is part of what a dict says
    return [tag, [encode(i) for i in x] if base in (list, tuple) else sorted((encode(i) for i in x), key=text)]


def text(x) -> str:
    return json.dumps(x, ensure_ascii=True, separators=(",", ":"))


def outcome(fn, *args, **kwargs):
    """The result of `fn(...)`, or the exact exception (its type's name and message): both are observations."""
    try:
        return ("ok", fn(*args, **kwargs))
    except Exception as e:
        return ("raised", type(e).__name__, str(e))


def loopback(value: str, port: int) -> str:
    """`value` (a URL, an error message) with the allocated port of the harness's own 127.0.0.1 listener replaced by `<port>`, wherever that authority stands. The scheme, path, query,
    fragment and every other host or port are kept, so a changed origin, path or query is a changed observation."""
    return re.sub(rf"(?<![\w.])127\.0\.0\.1:{port}(?!\d)", "127.0.0.1:<port>", value)


def fixed_datetime(instant: datetime.datetime):
    """A `datetime` class whose `now()` is `instant` (aware): a module's generated clock fixed at its source (patch it where the module imports `datetime`)."""
    class Fixed(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)
    return Fixed


class Run:
    """One driver run: groups of cases, each case a `str` identity and an observation. `keep` says how much of a group's observations the artifact holds: "exact" (the encoded value, for
    a group a person reads), "digest" (a digest per case, to name the case that differs) or "none" (the group's digest alone: for millions of cases). Every group also holds its count,
    the digest of its case identities and the digest of identities and observations in order. A kept group refuses a case identity twice."""

    def __init__(self, driver: str):
        self.driver, self.groups = driver, {}

    def observe(self, group: str, case: str, value, keep: str = "digest") -> None:
        if not isinstance(case, str):
            raise TypeError(f"a case identity is a str, not {type(case).__name__}")
        g = self.groups.setdefault(group, {"n": 0, "keep": keep, "cases": {}, "ids": hashlib.sha256(), "all": hashlib.sha256()})
        if g["keep"] != keep or case in g["cases"]:
            raise ValueError(f"{group}/{case}: a group keeps its cases one way, and a kept case occurs once")
        encoded = encode(value)
        body = text(encoded).encode()
        g["n"] += 1
        g["ids"].update(text(case).encode() + b"\n")
        g["all"].update(text(case).encode() + b"\n" + body + b"\n")
        if keep != "none":
            g["cases"][case] = encoded if keep == "exact" else hashlib.sha256(body).hexdigest()[:32]

    def artifact(self, note=None) -> dict:
        if not self.groups:
            raise SystemExit(f"{self.driver}: observed nothing: an empty run is no evidence")
        return {"driver": self.driver, "version": 1, "complete": True, "note": encode(note), "groups": {   # `note` is carried and never compared
            name: {"n": g["n"], "keep": g["keep"], "keys": g["ids"].hexdigest(), "digest": g["all"].hexdigest(), "cases": g["cases"]} for name, g in sorted(self.groups.items())}}

    def finish(self, path, note=None) -> None:
        """Write the artifact, whole, only once the driver has reached its end: a driver that fails leaves no file that looks complete."""
        doc = self.artifact(note)
        with open(f"{path}.tmp", "w") as handle:
            json.dump(doc, handle)
        os.replace(f"{path}.tmp", path)


def shaped(art: dict) -> str | None:
    groups = art.get("groups")
    if art.get("version") != 1 or art.get("complete") is not True:
        return "the driver did not complete (no completion mark)"
    if not isinstance(groups, dict) or not groups:
        return "no groups: an empty corpus is no evidence"
    for name, g in groups.items():
        if not (isinstance(g, dict) and type(g.get("n")) is int and g["n"] >= 1 and isinstance(g.get("keys"), str) and isinstance(g.get("digest"), str)):
            return f"group {name!r} is empty or malformed"
    return None


def expectation(art) -> tuple[str | None, dict | None]:
    """(why the artifact is no evidence, None), or (None, what it covers: {group: {"n", "keys"}})."""
    if not isinstance(art, dict):
        return (art if isinstance(art, str) else "no artifact"), None
    why = shaped(art)
    return why, None if why else {name: {"n": g["n"], "keys": g["keys"]} for name, g in art["groups"].items()}


def refusal(art, expect: dict) -> str | None:
    why, got = expectation(art)
    if why or got == expect:
        return why
    missing, extra = sorted(set(expect) - set(got)), sorted(set(got) - set(expect))
    wrong = sorted(g for g in set(got) & set(expect) if got[g] != expect[g])
    return "; ".join(p for p in (missing and f"groups missing: {missing[:4]}", extra and f"groups the manifest does not declare: {extra[:4]}", wrong and f"cases missing, added or renamed in: {wrong[:4]}") if p)


def freeze(runs: list[dict]) -> dict:
    """The manifest of runs that agree. Refuses fewer than two runs, a driver any run lacks or shows empty or incomplete, and runs that disagree."""
    if len(runs) < 2:
        raise ValueError("a manifest is frozen from at least two runs that agree")
    manifest = {}
    for driver in sorted(set().union(*runs)):
        seen = [expectation(run.get(driver)) for run in runs]
        if any(why for why, _ in seen) or any(got != seen[0][1] for _, got in seen):
            raise ValueError(f"{driver}: not frozen, the runs must each be complete and agree: " + "; ".join(f"run {i}: {why or 'complete'}" for i, (why, _) in enumerate(seen)))
        manifest[driver] = seen[0][1]
    return manifest


def load_run(path: str, drivers) -> dict:
    """{driver: its artifact, or the reason there is none}. A run counts only when its runner wrote `finished`, after checking every driver's exit status."""
    root = pathlib.Path(path)
    if not (root / "finished").is_file():
        return {d: f"{root.name} has no finished marker: a driver failed or the run stopped" for d in drivers}
    out = {}
    for driver in drivers:
        try:
            out[driver] = json.loads((root / f"{driver}.json").read_text())
        except (OSError, ValueError) as e:
            out[driver] = f"{root.name}/{driver}.json: {type(e).__name__}"
            continue
        if not isinstance(out[driver], dict) or out[driver].get("driver") != driver:
            out[driver] = f"{root.name}/{driver}.json is not {driver}'s artifact"
    return out


def where(a: dict, b: dict) -> list:
    """What names the difference between one group of two runs: the case identities (a kept group), or the group alone."""
    if a["keep"] == "none" or a["keep"] != b["keep"]:
        return ["the group's digest (its cases are not kept)"]
    found: collections.Counter = collections.Counter()
    differences(a["cases"], b["cases"], (), found)
    return sorted({path[0] for path in found})[:3] or ["the order of the cases"]


def compare(before: list[dict], after: list[dict], manifest: dict) -> dict:
    """before, after: the runs ({driver: artifact or reason}) of each tree; manifest: what every run must cover. Returns {'result', 'tests': {name: {'verdict', 'sources'}}, 'counts', 'observed'}."""
    if len(before) < 2 or not after:
        return {"result": "UNRESOLVED", "counts": {"unresolved": 1}, "observed": 0, "tests": {"runs": {"verdict": "unresolved", "sources": {"one baseline run cannot show whether the drivers are stable: at least two before and one after": 1}}}}
    verdicts, observed = {}, 0
    for driver in sorted(manifest):
        refused = {f"{side}[{i}]": why for side, runs in (("before", before), ("after", after)) for i, run in enumerate(runs) if (why := refusal(run.get(driver), manifest[driver]))}
        if refused:
            verdicts[driver] = {"verdict": "unresolved", "sources": refused}
            continue
        for name in sorted(manifest[driver]):
            sides = {side: [run[driver]["groups"][name] for run in runs] for side, runs in (("before", before), ("after", after))}
            noise = {f"{side}[{i}]: {w}": 1 for side, gs in sides.items() for i, g in enumerate(gs[1:], 1) if g["digest"] != gs[0]["digest"] for w in where(gs[0], g)}
            first, new = sides["before"][0], sides["after"][0]
            delta = {w: 1 for w in where(first, new)} if first["digest"] != new["digest"] else {}
            verdicts[f"{driver}/{name}"] = {"verdict": "unresolved" if noise else "different" if delta else "same", "sources": noise or delta}
            if not noise and not delta:
                observed += first["n"]
    counts = collections.Counter(v["verdict"] for v in verdicts.values())
    return {"result": "DIFFERENT" if counts["different"] else "UNRESOLVED" if counts["unresolved"] else "EQUIVALENT", "tests": verdicts, "counts": dict(counts), "observed": observed}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    freezing, comparing = sub.add_parser("freeze"), sub.add_parser("compare")
    freezing.add_argument("out"), freezing.add_argument("runs", nargs="+")
    comparing.add_argument("manifest"), comparing.add_argument("--before", nargs="+", required=True), comparing.add_argument("--after", nargs="+", required=True), comparing.add_argument("--report")
    args = parser.parse_args(argv)
    if args.command == "freeze":
        drivers = sorted({p.stem for run in args.runs for p in pathlib.Path(run).glob("*.json")})
        manifest = freeze([load_run(run, drivers) for run in args.runs])
        pathlib.Path(args.out).write_text(json.dumps(manifest, indent=1, sort_keys=True))
        print(f"frozen: {len(manifest)} drivers, {sum(len(g) for g in manifest.values())} groups, {sum(g['n'] for d in manifest.values() for g in d.values())} cases -> {args.out}")
        return 0
    manifest = json.loads(pathlib.Path(args.manifest).read_text())
    report = compare([load_run(r, manifest) for r in args.before], [load_run(r, manifest) for r in args.after], manifest)
    if args.report:
        pathlib.Path(args.report).write_text(json.dumps(report, indent=1, sort_keys=True))
    print(f"{report['result']}: {len(report['tests'])} verdicts: " + ", ".join(f"{n} {v}" for v, n in sorted(report["counts"].items())) + f"; {report['observed']} observations compared exactly, each counted once")
    for name, verdict in report["tests"].items():
        if verdict["verdict"] != "same":
            print(f"  {verdict['verdict'].upper()} {name}: " + "; ".join(f"{k} ({v})" for k, v in sorted(verdict["sources"].items())[:6]))
    return {"EQUIVALENT": 0, "DIFFERENT": 1, "UNRESOLVED": 2}[report["result"]]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
