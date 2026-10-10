"""Pure V-6 operands for 2d-3a; governed admission/persistence belongs to 3b.

Standards, lexical sources and diagnostic-only similarity rationale: DOSSIER.md
2d-3. Artifact versions are content-addressed. No supplied match label is used.
"""
from __future__ import annotations

import hashlib
import re
import sys
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

NORMALIZATION = ("quote-nfkc", "1+ucd" + unicodedata.unidata_version)
SIMILARITY = ("difflib.SequenceMatcher.ratio/min-bidirectional/autojunk=False", sys.version.split()[0])
NEGATION_VERSION = "english-negation/1"
NUMBER_VERSION = "decimal-token/1"
NEGATIONS = frozenset("no not never none nobody nothing nowhere neither nor cannot without hardly scarcely barely seldom".split())
UNIT_VERSION = "si9-2022+clinical/1"
BASE_UNITS = "m g s A K mol cd rad sr Hz N Pa J W C V F Ω S Wb T H lm lx Bq Gy Sv kat L l eV".split()
PREFIXES = "Q R Y Z E P T G M k h da d c m μ n p f a z y r q".split()
UNITS = frozenset(BASE_UNITS + [p + u for p in PREFIXES for u in BASE_UNITS] +
                  "kg °C min h d t Da au ha ° ′ ″ % mcg IU U mmHg bpm gram grams milligram milligrams microgram micrograms litre litres liter liters".split())
FOLD = str.maketrans({**dict.fromkeys("‘’‚‛", "'"), **dict.fromkeys("“”„‟", '"'), **dict.fromkeys("‐‑‒–—―−", "-")})
DEHYPHEN = re.compile(r"(?<=[^\W\d_])[-\u00ad][ \t]*\r?\n[ \t]*(?=[^\W\d_])")
NUMBER = re.compile(r"(?<![\d.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|[%°′″]+[^\W\d_]*")


def normalize(text: str) -> str:
    """NFKC, typographic folds, alphabetic line-break dehyphenation, whitespace."""
    text = unicodedata.normalize("NFKC", text).translate(FOLD)
    text = DEHYPHEN.sub("", text)
    return " ".join(text.split())


def protected(text: str) -> tuple[tuple[str, int, int, object], ...]:
    """Explicit lexical guards; numeric spelling AND parsed value are retained."""
    tokens = [("number", m.start(), m.end(), (m.group(), Decimal(m.group()))) for m in NUMBER.finditer(text)]
    for m in WORD.finditer(text):
        word = m.group()
        if word.casefold() in NEGATIONS or word.casefold().endswith("n't"):
            tokens.append(("negation", m.start(), m.end(), word.casefold()))
        if word in UNITS:
            tokens.append(("unit", m.start(), m.end(), word))
    return tuple(tokens)


@dataclass(frozen=True)
class Difference:
    """Half-open character offsets in the two retained NORMALIZED strings."""
    quote_start: int
    quote_end: int
    source_start: int
    source_end: int


@dataclass(frozen=True)
class NearMatch:
    similarity: float
    differing_spans: tuple[Difference, ...]
    measure: tuple[str, str] = SIMILARITY


@dataclass(frozen=True)
class QuoteMatch:
    quoted_bytes: bytes
    source_span_bytes: bytes
    expected_artifact_hash: str
    artifact_hash: str
    span_start: int
    span_end: int
    status: str
    reason: str | None
    normalized_quote: str | None = None
    normalized_source: str | None = None
    diagnostic: NearMatch | None = None
    normalization: tuple[str, str] = NORMALIZATION
    token_versions: tuple[str, str, str] = (NUMBER_VERSION, NEGATION_VERSION, UNIT_VERSION)

    @property
    def quote_quarantined(self) -> bool:
        return self.status == "mismatch"


def _protected_difference(a: str, b: str, differences: tuple[Difference, ...]) -> str | None:
    left, right = protected(a), protected(b)
    for kind in ("number", "negation", "unit"):
        if [t[3] for t in left if t[0] == kind] != [t[3] for t in right if t[0] == kind]:
            return kind
    # Also refuse moving/replacing a protected token, even if its count stays equal.
    for diff in differences:
        for tokens, start, end in ((left, diff.quote_start, diff.quote_end), (right, diff.source_start, diff.source_end)):
            for kind, lo, hi, _ in tokens:
                if lo < end and start < hi:
                    return kind
    return None


def _layers(quote: bytes, span: bytes) -> tuple[str, str | None, str, str, NearMatch | None]:
    a, b = normalize(quote.decode("utf-8")), normalize(span.decode("utf-8"))
    if quote == span:
        return "match", None, a, b, None
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    differences = tuple(Difference(i, j, k, l) for tag, i, j, k, l in matcher.get_opcodes() if tag != "equal")
    critical = _protected_difference(a, b, differences)
    if critical is not None:
        return "mismatch", "protected_" + critical, a, b, None
    if a == b:
        return "match_normalized", None, a, b, None
    score = min(matcher.ratio(), SequenceMatcher(None, b, a, autojunk=False).ratio())
    if score >= 0.98:
        return "mismatch", "near_match", a, b, NearMatch(score, differences)
    return "mismatch", "text_difference", a, b, None


def check_quote(quote: bytes, artifact: bytes, start: int, end: int, expected_artifact_hash: str) -> QuoteMatch:
    """Check authenticated artifact identity, half-open byte span, then layers.

    The governed caller must derive expected_artifact_hash from the recorded
    work/source version. These pure arguments supply no admission authority.
    """
    actual_hash = "sha256:" + hashlib.sha256(artifact).hexdigest()
    args = (quote, b"", expected_artifact_hash, actual_hash, start, end)
    if actual_hash != expected_artifact_hash:
        return QuoteMatch(*args, "mismatch", "artifact_version")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(artifact):
        return QuoteMatch(*args, "mismatch", "span_offsets")
    span = artifact[start:end]
    args = (quote, span, expected_artifact_hash, actual_hash, start, end)
    try:
        result = _layers(quote, span)
    except UnicodeDecodeError:
        return QuoteMatch(*args, "mismatch", "utf8")
    except InvalidOperation:
        return QuoteMatch(*args, "mismatch", "number_parse")
    return QuoteMatch(*args, *result)
