#!/usr/bin/env python3
"""The shared differential core of the gateway drivers (task 2q-e1, repaired in 2q-e2; Astra's 2q-b5 and 2q-e1 reviews, C1 and C2), built on the ideas of tools/gen2_replay_compare.py: one exact relation, no weaker one.

A driver observes the old tree and the new one with the same code and records what it saw: `run = Run("link"); run.observe(group, case, value, keep=...); run.finish(path)`.
  * Exact encoding (`encode`): a value is kept as it is. str contents, int, float, bool and None are their own JSON scalars; every container is tagged with its type (a list, a tuple,
    a dict as its ordered pairs, a set, a subclass by its qualified name, bytes by their hex), so `{"a": 1}` and `[["'a'", 1]]` never meet. A type it does not know is refused, never
    `repr`ed. Nothing is normalised in what a driver records: a generated clock is fixed at its source (`fixed_datetime`).
  * Parse, don't substitute: the one harness-owned value, a loopback listener's allocated port, is replaced by its position and never by its spelling. `loopback` parses a URL and, when its
    authority is 127.0.0.1 at that port, returns a `LoopbackURL` (the text before the port and the text after it), which encodes as a tagged array no string or other value can equal. Any
    other value is what it is: a path, query or fragment that names the same authority, the literal text `<port>`, another host or port. An error message is never scrubbed: `unnamed` hands it
    on and refuses one that names the listener, to be handled by a rule written for that message.
  * The inventory comes first, from the inputs. A driver set is declared by name (never discovered from the files that exist); a corpus a generator wrote is an inventory only when sealed
    (`Corpus`: its count, its digest and, per group, the count and digest of the case identities, written only when the generator reached its end) and checked (`corpus`). A manifest
    (`freeze`) holds, per driver and group, the number of cases and the digest of their identities, from at least two baseline runs that must be whole, agree and, for a driver fed by a sealed
    corpus, be that corpus's own inventory. A run is refused, and the verdict is `unresolved`, never equivalent, when its envelope is malformed or its observations erased, it is empty or
    partial, has a group or a case more or fewer, consumed other inputs, was not completed by its driver, or its runner did not write `finished` (naming the drivers it ran, after checking
    every exit status). A comparison covers the manifest's drivers, or a subset only when the subset is declared.
  * Verdicts, per group, as the engine's: `same` (every run of a tree equals its tree's first, and the two firsts are equal), `different` (no run disagrees with its own tree's first and
    the firsts differ), `unresolved` (some run disagrees with its own tree's first, or the driver is refused: the source is named, to be fixed at its seam). Exit 0, 1, 2 (also 2: refused
    before any verdict, with the reason on stderr).

    python tools/gen2_differential.py corpus CASES.jsonl [--count N] [--digest HEX]             check a generator's sealed output (and the count and digest it was declared to have)
    python tools/gen2_differential.py freeze OUT.json --drivers NAME [...] --runs RUN_DIR RUN_DIR [...] [--input DRIVER=CASES.jsonl] [--expect SIZES.json]
    python tools/gen2_differential.py compare MANIFEST.json --drivers NAME [...] [--subset] --before RUN_DIR RUN_DIR [...] --after RUN_DIR [...] [--input DRIVER=CASES.jsonl] [--report OUT.json]
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
import urllib.parse

differences = runpy.run_path(str(pathlib.Path(__file__).with_name("gen2_replay_compare.py")))["differences"]   # type for type, NaN equal to NaN: the engine's own
HEX64, HEX32, NAME, KEEPS = re.compile(r"[0-9a-f]{64}"), re.compile(r"[0-9a-f]{32}"), re.compile(r"[a-z][a-z0-9-]*"), ("exact", "digest", "none")


class Obj(tuple):
    """A driver's stand-in for an object that cannot be encoded as itself (a Rec, an Element): its kind and its parts. It never equals the same parts as a plain tuple."""


class LoopbackURL:
    """The URL of the harness's own listener: the text before its allocated port and the text after it (the port is the one thing it does not hold). Made only by `loopback`."""
    __slots__ = ("head", "tail")

    def __init__(self, head: str, tail: str):
        self.head, self.tail = head, tail


def encode(x):
    """The exact JSON-safe form of `x`. Every array in it is tagged (`["list", [...]]`), so no value can be taken for another."""
    kind = type(x)
    if x is None or kind in (bool, int, float, str):
        return x
    if kind is LoopbackURL:
        return ["loopback-url", [x.head, x.tail]]   # a tag no other value has (a class's tag holds a colon): no str, list or dict encodes to it
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


def ident(case: str) -> bytes:
    """What a case's identity adds to the digest of a group's identities."""
    return text(case).encode() + b"\n"


def outcome(fn, *args, **kwargs):
    """The result of `fn(...)`, or the exact exception (its type's name and message): both are observations."""
    try:
        return ("ok", fn(*args, **kwargs))
    except Exception as e:
        return ("raised", type(e).__name__, str(e))


def loopback(value, port: int):
    """`value` (a URL) as a `LoopbackURL` when it has an authority (after any userinfo) that is 127.0.0.1 at the allocated `port`: the text before the port and the text after it, so
    the scheme, userinfo, path, query and fragment are kept to the byte. Found by parsing, never by spelling: the same authority named in a path, query or fragment, another host, another port, the
    literal text `<port>`, or a URL that does not parse as one, is returned as it is, and is compared as it is (a value that varies from run to run is `unresolved`, not hidden)."""
    if type(port) is not int or not 0 < port < 65536:
        raise ValueError(f"{port!r} is not a port")
    if type(value) is not str:
        return value
    try:
        parts = urllib.parse.urlsplit(value)
    except ValueError:
        return value
    start = len(parts.scheme) + 3 if parts.scheme else 2   # `scheme://`, or the `//` of a network-path reference
    if value[start:start + len(parts.netloc)] != parts.netloc or parts.netloc.rpartition("@")[2] != f"127.0.0.1:{port}":   # urlsplit drops tabs, newlines and leading blanks: that text is not at this offset
        return value
    end = start + len(parts.netloc)
    return LoopbackURL(value[:end - len(str(port))], value[end:])


def unnamed(message, port: int):
    """An error message, exactly as it is, unless it names the listener at `port` (127.0.0.1:port): that is refused, not scrubbed. A message that carries a harness value is handled by a rule
    written for that message, never by a search through text."""
    if type(message) is str and re.search(rf"127\.0\.0\.1:{port}(?!\d)", message):
        raise ValueError(f"an error message names the harness's listener ({message[:80]!r}): handle that message explicitly")
    return message


def fixed_datetime(instant: datetime.datetime):
    """A `datetime` class whose `now()` is `instant` (aware): a module's generated clock fixed at its source (patch it where the module imports `datetime`)."""
    class Fixed(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant if tz is None else instant.astimezone(tz)
    return Fixed


def write(path, doc, **dump) -> None:
    """`doc` as JSON at `path`, whole or not at all."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w") as handle:
            json.dump(doc, handle, **dump)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def load_json(path):
    try:
        return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError) as e:
        raise ValueError(f"{path}: not readable JSON ({type(e).__name__})") from e


class Run:
    """One driver run: groups of cases, each case a `str` identity and an observation. `keep` says how much of a group's observations the artifact holds: "exact" (the encoded value, for
    a group a person reads), "digest" (a digest per case, to name the case that differs) or "none" (the group's digest alone: for millions of cases). Every group also holds its count,
    the digest of its case identities and the digest of identities and observations in order. A kept group refuses a case identity twice. `inputs` (the `corpus` a driver read) is recorded."""

    def __init__(self, driver: str, inputs: dict | None = None):
        self.driver, self.groups, self.inputs = driver, {}, inputs

    def observe(self, group: str, case: str, value, keep: str = "digest") -> None:
        if not isinstance(case, str):
            raise TypeError(f"a case identity is a str, not {type(case).__name__}")
        g = self.groups.setdefault(group, {"n": 0, "keep": keep, "cases": {}, "ids": hashlib.sha256(), "all": hashlib.sha256()})
        if g["keep"] != keep or case in g["cases"]:
            raise ValueError(f"{group}/{case}: a group keeps its cases one way, and a kept case occurs once")
        encoded = encode(value)
        body = text(encoded).encode()
        g["n"] += 1
        g["ids"].update(ident(case))
        g["all"].update(ident(case) + body + b"\n")
        if keep != "none":
            g["cases"][case] = encoded if keep == "exact" else hashlib.sha256(body).hexdigest()[:32]

    def artifact(self, note=None) -> dict:
        if not self.groups:
            raise SystemExit(f"{self.driver}: observed nothing: an empty run is no evidence")
        doc = {"driver": self.driver, "version": 1, "complete": True, "note": encode(note), "groups": {   # `note` is carried and never compared
            name: {"n": g["n"], "keep": g["keep"], "keys": g["ids"].hexdigest(), "digest": g["all"].hexdigest(), "cases": g["cases"]} for name, g in sorted(self.groups.items())}}
        return {**doc, "inputs": {"n": self.inputs["n"], "digest": self.inputs["digest"]}} if self.inputs else doc

    def finish(self, path, note=None) -> None:
        """Write the artifact, whole, only once the driver has reached its end: a driver that fails leaves no file that looks complete."""
        write(path, self.artifact(note))   # the cases' order is part of the artifact: no sort_keys


class Corpus:
    """A generator's output, sealed only at its end: `with Corpus(path) as out: out.add(group, case, record)` writes `path` (one JSON line per case) and `path.seal` (the count, the file's digest
    and, per group, the count and the digest of the case identities, as `Run` forms it), both whole, only when the block ends without an error. A generator that fails or finds nothing leaves
    neither (an earlier run's are removed first), so a file that is not sealed is not an inventory. `corpus` checks a file against its seal."""

    def __init__(self, path):
        self.path, self.groups, self.n, self.sha = str(path), {}, 0, hashlib.sha256()

    def __enter__(self):
        for stale in (self.path, f"{self.path}.seal"):
            pathlib.Path(stale).unlink(missing_ok=True)
        self.handle = open(f"{self.path}.tmp", "wb")
        return self

    def add(self, group: str, case: str, record) -> None:
        line = (text({"group": group, "case": case, "record": record}) + "\n").encode()
        g = self.groups.setdefault(group, {"n": 0, "ids": hashlib.sha256()})
        g["n"] += 1
        g["ids"].update(ident(case))
        self.n += 1
        self.sha.update(line)
        self.handle.write(line)

    def __exit__(self, kind, error, trace):
        self.handle.close()
        if kind is not None or not self.n:
            pathlib.Path(f"{self.path}.tmp").unlink(missing_ok=True)
            if kind is None:
                raise SystemExit(f"{self.path}: the generator found nothing: an empty corpus is no inventory")
            return False
        os.replace(f"{self.path}.tmp", self.path)
        write(f"{self.path}.seal", {"version": 1, "complete": True, "n": self.n, "digest": self.sha.hexdigest(),
                                    "groups": {g: {"n": v["n"], "keys": v["ids"].hexdigest()} for g, v in sorted(self.groups.items())}})
        return False


def counted(n) -> bool:
    return type(n) is int and n >= 1


def hashed(x) -> bool:
    return isinstance(x, str) and bool(HEX64.fullmatch(x))


def sized(groups) -> bool:
    """A non-empty `{group: {"n", "keys"}}`."""
    return isinstance(groups, dict) and bool(groups) and all(isinstance(k, str) and isinstance(g, dict) and set(g) == {"n", "keys"} and counted(g["n"]) and hashed(g["keys"]) for k, g in groups.items())


def consumed(inputs) -> bool:
    return isinstance(inputs, dict) and set(inputs) == {"n", "digest"} and counted(inputs["n"]) and hashed(inputs["digest"])


def corpus(path, count: int | None = None, digest: str | None = None) -> dict:
    """The inventory a generator sealed for `path` ({"n", "digest", "groups"}), after checking the file against it. Refuses a file with no seal (the generator did not reach its end), a seal
    that is not complete or whole, a file that is not the sealed one (another digest or line count) and, when a `count` or a `digest` is declared, another one."""
    seal = load_json(f"{path}.seal")
    if not (isinstance(seal, dict) and set(seal) == {"version", "complete", "n", "digest", "groups"} and seal["version"] == 1 and seal["complete"] is True and consumed({"n": seal["n"], "digest": seal["digest"]})
            and sized(seal["groups"]) and sum(g["n"] for g in seal["groups"].values()) == seal["n"]):
        raise ValueError(f"{path}.seal is not a complete seal")
    sha, lines = hashlib.sha256(), 0
    try:
        with open(path, "rb") as handle:
            for line in handle:
                sha.update(line)
                lines += 1
    except OSError as e:
        raise ValueError(f"{path}: {type(e).__name__}") from e
    if sha.hexdigest() != seal["digest"] or lines != seal["n"]:
        raise ValueError(f"{path} is not the file its seal describes")
    if count is not None and seal["n"] != count:
        raise ValueError(f"{path}: {seal['n']} cases are sealed, {count} were declared")
    if digest is not None and seal["digest"] != digest:
        raise ValueError(f"{path}: the sealed digest {seal['digest'][:16]} is not the declared {str(digest)[:16]}")
    return {key: seal[key] for key in ("n", "digest", "groups")}


def faulty(g) -> str | None:
    """Why a group is not whole (None when it is): its fields, a count, 64-hex digests; a kept group's cases as many as it counts, their identities forming the digest it holds, and, when exact,
    their observations forming the other. A digest-kept group's case digests are 32-hex."""
    if not (isinstance(g, dict) and set(g) == {"n", "keep", "keys", "digest", "cases"} and counted(g["n"]) and g["keep"] in KEEPS and hashed(g["keys"]) and hashed(g["digest"]) and isinstance(g["cases"], dict)):
        return "is empty or malformed"
    cases = g["cases"]
    if g["keep"] == "none":
        return None if not cases else "keeps cases it declares it does not"
    ids, seen = hashlib.sha256(), hashlib.sha256()
    for case, value in cases.items():
        ids.update(ident(case))
        seen.update(ident(case) + text(value).encode() + b"\n")
    if len(cases) != g["n"] or ids.hexdigest() != g["keys"]:
        return "does not keep the cases it counts"
    if g["keep"] == "exact":
        return None if seen.hexdigest() == g["digest"] else "keeps observations that are not the ones its digest covers"
    return None if all(isinstance(v, str) and HEX32.fullmatch(v) for v in cases.values()) else "keeps a malformed case digest"


def shaped(art, driver: str) -> str | None:
    """Why `art` is no evidence of `driver` (None when its envelope is whole): exactly the fields `Run.artifact` writes, the completion mark, well-formed inputs when it has them, and groups that are whole."""
    if not isinstance(art, dict):
        return "no artifact"
    if set(art) - {"inputs"} != {"driver", "version", "complete", "note", "groups"}:
        return f"its fields are {sorted(art)}, not an artifact's"
    if art["driver"] != driver or art["version"] != 1:
        return f"it is not a version 1 artifact of {driver}"
    if art["complete"] is not True:
        return "the driver did not complete (no completion mark)"
    if "inputs" in art and not consumed(art["inputs"]):
        return "its inputs are malformed"
    if not isinstance(art["groups"], dict) or not art["groups"]:
        return "no groups: an empty corpus is no evidence"
    return next((f"group {name!r} {why}" for name, g in art["groups"].items() if (why := faulty(g))), None)


def expectation(art, driver: str) -> tuple[str | None, dict | None]:
    """(why the artifact is no evidence, None), or (None, what it covers: {"groups": {group: {"n", "keys"}}, "inputs": {"n", "digest"} or None})."""
    why = art if isinstance(art, str) else shaped(art, driver)
    return (why, None) if why else (None, {"groups": {name: {"n": g["n"], "keys": g["keys"]} for name, g in art["groups"].items()}, "inputs": art.get("inputs")})


def refusal(art, driver: str, expect: dict) -> str | None:
    why, got = expectation(art, driver)
    if why or got == expect:
        return why
    missing, extra = sorted(set(expect["groups"]) - set(got["groups"])), sorted(set(got["groups"]) - set(expect["groups"]))
    wrong = sorted(g for g in set(got["groups"]) & set(expect["groups"]) if got["groups"][g] != expect["groups"][g])
    return "; ".join(p for p in (missing and f"groups missing: {missing[:4]}", extra and f"groups the manifest does not declare: {extra[:4]}", wrong and f"cases missing, added or renamed in: {wrong[:4]}",
                                 got["inputs"] != expect["inputs"] and "it consumed other inputs than the manifest's") if p)


def declared(drivers) -> list[str]:
    """The driver inventory, refused unless explicit: a non-empty list of distinct names."""
    if not isinstance(drivers, (list, tuple)) or not drivers or len(set(drivers)) != len(drivers) or not all(isinstance(d, str) and NAME.fullmatch(d) for d in drivers):
        raise ValueError(f"the drivers must be declared: a non-empty list of distinct names, not {drivers!r}")
    return list(drivers)


def unbound(expect: dict, inventory: dict | None) -> str | None:
    """Why what a driver covers (a frozen run's, or the manifest's) is not what its sealed input inventory declares: the groups, their counts and identity digests, and the file consumed."""
    if inventory is None:
        return None if expect["inputs"] is None else "its input inventory is not supplied"
    if expect["inputs"] != {"n": inventory["n"], "digest": inventory["digest"]} or expect["groups"] != inventory["groups"]:
        return "it is not the inventory its input declares (groups, counts, identities, or the file consumed)"
    return None


def freeze(runs: list[dict], drivers, inputs: dict | None = None, expected: dict | None = None) -> dict:
    """The manifest of runs that agree, for the declared `drivers`. Refuses: no driver, fewer than two runs, a driver any run lacks or shows empty, malformed or incomplete, runs that disagree, a
    driver fed by a sealed corpus (`inputs`: {driver: its `corpus`}) whose runs are not exactly that inventory, and sizes `expected` ({driver: {"groups", "cases"}}) the runs do not have."""
    drivers, inputs = declared(drivers), inputs or {}
    if len(runs) < 2:
        raise ValueError("a manifest is frozen from at least two runs that agree")
    if set(inputs) - set(drivers) or (expected is not None and set(expected) != set(drivers)):
        raise ValueError("an input inventory or an expected size is declared for a driver that is not declared (or an expected size is missing)")
    manifest = {}
    for driver in drivers:
        seen = [expectation(run.get(driver), driver) for run in runs]
        if any(why for why, _ in seen) or any(got != seen[0][1] for _, got in seen):
            raise ValueError(f"{driver}: not frozen, the runs must each be complete and agree: " + "; ".join(f"run {i}: {why or 'complete'}" for i, (why, _) in enumerate(seen)))
        got = seen[0][1]
        if why := unbound(got, inputs.get(driver)):
            raise ValueError(f"{driver}: not frozen, {why}")
        if expected is not None and expected[driver] != {"groups": len(got["groups"]), "cases": sum(g["n"] for g in got["groups"].values())}:
            raise ValueError(f"{driver}: not frozen, its size {len(got['groups'])} groups, {sum(g['n'] for g in got['groups'].values())} cases is not the declared {expected[driver]}")
        manifest[driver] = got
    return {"version": 2, "drivers": manifest}


def manifested(manifest, drivers, subset: bool = False) -> dict:
    """The manifest's per-driver expectations, after checking that it is whole (version 2; a driver with groups of a count and an identity digest, and inputs or none) and not empty, and that the
    drivers declared are its drivers, or, only when a `subset` is declared, some of them."""
    declared(drivers)
    if not (isinstance(manifest, dict) and set(manifest) == {"version", "drivers"} and manifest["version"] == 2 and isinstance(manifest["drivers"], dict)
            and all(isinstance(v, dict) and set(v) == {"groups", "inputs"} and sized(v["groups"]) and (v["inputs"] is None or consumed(v["inputs"])) for v in manifest["drivers"].values())):
        raise ValueError("the manifest is empty or malformed")
    have = set(manifest["drivers"])
    if set(drivers) != have and not (subset and set(drivers) <= have):
        raise ValueError(f"the drivers declared {sorted(drivers)} are not the manifest's {sorted(have)}" + ("" if subset else " (a subset is compared only when declared)"))
    return manifest["drivers"]


def load_run(path: str, drivers) -> dict:
    """{driver: its artifact, or the reason there is none}. A run counts only when its directory exists and its runner wrote `finished` naming the driver, after checking every exit status."""
    root = pathlib.Path(path)
    try:
        ran = load_json(root / "finished")
    except ValueError:
        ran = None
    if not (isinstance(ran, dict) and set(ran) == {"version", "drivers"} and ran["version"] == 1 and isinstance(ran["drivers"], list)):
        return {d: f"{root.name} has no finished marker (or no run directory): a driver failed, the run stopped or there was none" for d in drivers}
    out = {}
    for driver in drivers:
        if driver not in ran["drivers"]:
            out[driver] = f"{root.name} did not run {driver}"
            continue
        try:
            out[driver] = json.loads((root / f"{driver}.json").read_text())
        except (OSError, ValueError) as e:
            out[driver] = f"{root.name}/{driver}.json: {type(e).__name__}"
    return out


def where(a: dict, b: dict) -> list:
    """What names the difference between one group of two runs: the case identities (a kept group), or the group alone."""
    if a["keep"] == "none" or a["keep"] != b["keep"]:
        return ["the group's digest (its cases are not kept)"]
    found: collections.Counter = collections.Counter()
    differences(a["cases"], b["cases"], (), found)
    return sorted({path[0] for path in found})[:3] or ["the order of the cases"]


def compare(before: list[dict], after: list[dict], manifest: dict, drivers, subset: bool = False, inputs: dict | None = None) -> dict:
    """before, after: the runs ({driver: artifact or reason}) of each tree; manifest: what every run must cover; drivers: the declared inventory (the manifest's, or a declared `subset`); inputs:
    {driver: its `corpus`}, required for each driver the manifest binds to one. Returns {'result', 'tests': {name: {'verdict', 'sources'}}, 'counts', 'observed', 'drivers', 'not_compared'}."""
    expect, inputs = manifested(manifest, drivers, subset), inputs or {}
    if set(inputs) - set(drivers):
        raise ValueError("an input inventory is supplied for a driver that is not declared")
    shown = {"drivers": sorted(drivers), "not_compared": sorted(set(expect) - set(drivers))}
    if len(before) < 2 or not after:
        return {"result": "UNRESOLVED", "counts": {"unresolved": 1}, "observed": 0, **shown, "tests": {"runs": {"verdict": "unresolved", "sources": {"one baseline run cannot show whether the drivers are stable: at least two before and one after": 1}}}}
    verdicts, observed = {}, 0
    for driver in sorted(drivers):
        refused = {f"{side}[{i}]": why for side, runs in (("before", before), ("after", after)) for i, run in enumerate(runs) if (why := refusal(run.get(driver), driver, expect[driver]))}
        if not refused and (why := unbound(expect[driver], inputs.get(driver))):
            refused = {"inputs": why}
        if refused:
            verdicts[driver] = {"verdict": "unresolved", "sources": refused}
            continue
        for name in sorted(expect[driver]["groups"]):
            sides = {side: [run[driver]["groups"][name] for run in runs] for side, runs in (("before", before), ("after", after))}
            noise = {f"{side}[{i}]: {w}": 1 for side, gs in sides.items() for i, g in enumerate(gs[1:], 1) if g["digest"] != gs[0]["digest"] for w in where(gs[0], g)}
            first, new = sides["before"][0], sides["after"][0]
            delta = {w: 1 for w in where(first, new)} if first["digest"] != new["digest"] else {}
            verdicts[f"{driver}/{name}"] = {"verdict": "unresolved" if noise else "different" if delta else "same", "sources": noise or delta}
            if not noise and not delta:
                observed += first["n"]
    counts = collections.Counter(v["verdict"] for v in verdicts.values())
    return {"result": "DIFFERENT" if counts["different"] else "UNRESOLVED" if counts["unresolved"] else "EQUIVALENT", "tests": verdicts, "counts": dict(counts), "observed": observed, **shown}


def bound_inputs(items: list[str]) -> dict:
    """{driver: `corpus`} from `DRIVER=CASES.jsonl` arguments: each file checked against its seal."""
    pairs = [item.partition("=") for item in items]
    if any(not sep for _, sep, _ in pairs):
        raise ValueError("an input is named DRIVER=CASES.jsonl")
    return {driver: corpus(path) for driver, _, path in pairs}


def distinct(paths: list[str]) -> None:
    if len({os.path.realpath(p) for p in paths}) != len(paths):
        raise ValueError("a run directory is named twice: two runs are two executions")


def command(args) -> int:
    if args.command == "corpus":
        found = corpus(args.path, args.count, args.digest)
        print(f"sealed: {found['n']} cases in {len(found['groups'])} groups, digest {found['digest'][:16]} ({args.path})")
        return 0
    declared(args.drivers)
    if args.command == "freeze":
        distinct(args.runs)
        manifest = freeze([load_run(run, args.drivers) for run in args.runs], args.drivers, bound_inputs(args.input), load_json(args.expect) if args.expect else None)
        write(args.out, manifest, indent=1, sort_keys=True)
        found = manifest["drivers"].values()
        print(f"frozen: {len(manifest['drivers'])} drivers, {sum(len(d['groups']) for d in found)} groups, {sum(g['n'] for d in found for g in d['groups'].values())} cases -> {args.out}")
        return 0
    distinct(args.before + args.after)
    manifest = load_json(args.manifest)
    report = compare([load_run(r, args.drivers) for r in args.before], [load_run(r, args.drivers) for r in args.after], manifest, args.drivers, args.subset, bound_inputs(args.input))
    if args.report:
        write(args.report, report, indent=1, sort_keys=True)
    print(f"{report['result']}: {len(report['tests'])} verdicts: " + ", ".join(f"{n} {v}" for v, n in sorted(report["counts"].items())) + f"; {report['observed']} observations compared exactly, each counted once"
          + (f"; drivers not compared (a declared subset): {report['not_compared']}" if report["not_compared"] else ""))
    for name, verdict in report["tests"].items():
        if verdict["verdict"] != "same":
            print(f"  {verdict['verdict'].upper()} {name}: " + "; ".join(f"{k} ({v})" for k, v in sorted(verdict["sources"].items())[:6]))
    return {"EQUIVALENT": 0, "DIFFERENT": 1, "UNRESOLVED": 2}[report["result"]]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sealing, freezing, comparing = sub.add_parser("corpus"), sub.add_parser("freeze"), sub.add_parser("compare")
    for each in (freezing, comparing):
        each.add_argument("--drivers", nargs="+"), each.add_argument("--input", action="append", default=[], metavar="DRIVER=CASES.jsonl")
    sealing.add_argument("path"), sealing.add_argument("--count", type=int), sealing.add_argument("--digest")
    freezing.add_argument("out"), freezing.add_argument("--runs", nargs="+", required=True), freezing.add_argument("--expect")
    comparing.add_argument("manifest"), comparing.add_argument("--before", nargs="+", required=True), comparing.add_argument("--after", nargs="+", required=True)
    comparing.add_argument("--subset", action="store_true"), comparing.add_argument("--report")
    args = parser.parse_args(argv)
    try:
        return command(args)
    except ValueError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
