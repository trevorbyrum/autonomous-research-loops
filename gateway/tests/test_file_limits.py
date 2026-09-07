"""I-11: no file under gateway/ may exceed 1,500 lines. Hard rule; fails the suite."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIMIT = 1500
CODE_SUFFIXES = {".py", ".sql", ".toml", ".md", ".yml", ".yaml", ".sh"}
SKIP_DIRS = {"__pycache__", ".git"}


def offenders() -> list[tuple[str, int]]:
    found = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
            continue
        if path.suffix not in CODE_SUFFIXES:
            continue
        with path.open("rb") as fh:
            lines = sum(1 for _ in fh)
        if lines > LIMIT:
            found.append((str(path.relative_to(ROOT)), lines))
    return found


class FileLimits(unittest.TestCase):
    def test_no_file_exceeds_limit(self):
        self.assertEqual(offenders(), [], f"files over {LIMIT} lines: {offenders()}")

    def test_no_placeholders(self):
        """I-10: shipped code carries no placeholder markers."""
        markers = ("TODO", "FIXME", "XXX", "NotImplementedError", "placeholder", "lorem ipsum")
        hits = []
        for path in ROOT.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts) or not path.is_file():
                continue
            if path.suffix not in {".py", ".sql", ".toml"} or path == Path(__file__).resolve():
                continue
            text = path.read_text(errors="replace")
            for m in markers:
                if m in text:
                    hits.append(f"{path.relative_to(ROOT)}: {m}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
