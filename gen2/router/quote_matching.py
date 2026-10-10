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

NORMALIZATION = ("quote-nfc-safe", "2+ucd" + unicodedata.unidata_version)
SIMILARITY = ("difflib.SequenceMatcher.ratio/min-bidirectional/autojunk=False", sys.version.split()[0])
NEGATION_VERSION = "english-negation/3"
PROTECTION_VERSION = "quote-protection/3"
NUMBER_VERSION = "decimal-expression/2"
NEGATIONS = frozenset("no not never none nobody nothing nowhere neither nor cannot without hardly scarcely barely seldom".split())
NEGATIVE_WORDS = frozenset("unavailable unable uncertain unclear unlikely unknown ineffective incorrect incomplete impossible improbable irregular irrelevant illegal illogical dishonest dissimilar disagree disadvantage non-effective".split())
NEGATIVE_PREFIXES = ("non", "un", "in", "im", "ir", "il", "dis")
UNIT_VERSION = "si9-2022+clinical/2"
BASE_UNITS = "m g s A K mol cd rad sr Hz N Pa J W C V F Ω S Wb T H lm lx Bq Gy Sv kat L l eV".split()
PREFIXES = "Q R Y Z E P T G M k h da d c m μ n p f a z y r q".split()
UNITS = frozenset(BASE_UNITS + [p + u for p in PREFIXES for u in BASE_UNITS] +
                  "kg °C min h d t Da au ha ° ′ ″ % µg mcg IU U mmHg bpm gram grams milligram milligrams microgram micrograms litre litres liter liters second seconds minute minutes hour hours day days percent".split())
FOLD = str.maketrans({**dict.fromkeys("‘’‚‛", "'"), **dict.fromkeys("“”„‟", '"'), **dict.fromkeys("‐‑‒–—―", "-")})
DEHYPHEN = re.compile(r"\u00ad[^\S\r\n]*\r?\n\s*")
POWERS = "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻₀₁₂₃₄₅₆₇₈₉₊₋"
EXPONENT = rf"(?:\^[-+−]?\d+|[{POWERS}]+)"
NUMBER = re.compile(rf"(?<![\d.])[-+−]?(?:\d+(?:[.,;' ]\d+)*\.?|\.\d+)(?:[eE][-+−]?\d+)?(?:{EXPONENT})?")
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+|-\s*[^\W\d_]+)*")
UNIT_ATOM = "(?:" + "|".join(re.escape(u) for u in sorted(UNITS, key=lambda u: (-len(u), u))) + ")" + rf"(?:{EXPONENT}|[-+−]?\d+)?"
UNIT = re.compile(rf"(?<![^\W\d_]){UNIT_ATOM}(?:\s*[/·×]\s*{UNIT_ATOM})*(?!\w)")
LEXEME = re.compile(r"\w+(?:['-]\w+)*|[^\w\s]")
LETTER_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")
ENCLOSING_LEXEME = re.compile(r"\S+")
OPERATORS = frozenset("+-−±×·/^%‰=<>≤≥⁄")


def safe_typography(text: str) -> str:
    """Only the brief's whitelist; U+2212 and compatibility forms survive."""
    text = text.translate(FOLD)
    text = DEHYPHEN.sub("", text)
    return " ".join(text.split())


def normalize(text: str) -> str:
    """Finish with NFC after all deletions: no later pass can create composition."""
    return unicodedata.normalize("NFC", safe_typography(text))


def negative(word: str) -> bool:
    """Whole listed words/contractions; prefix edits are checked separately."""
    word = word.casefold().replace("- ", "-")
    if word in NEGATIONS or word.endswith("n't") or word in NEGATIVE_WORDS:
        return True
    return False


def protected(text: str) -> tuple[tuple[str, int, str], ...]:
    """Original safe-folded spellings, sorted in text order with lexical slots.

    This extra lexical layer retains complete expression spellings before
    normalization/equality. Slots alone cannot authorize diagnostics: the
    independent skeleton and enclosing-edit checks below must also pass.
    """
    units = tuple(UNIT.finditer(text))
    tokens = [("unit", m.start(), m.group()) for m in units]
    for m in NUMBER.finditer(text):
        if any(u.start() <= m.start() < u.end() for u in units):
            continue
        # Validate the decimal core, retaining ALL grouping/power/sign spelling.
        core = re.split(rf"\^|[{POWERS}]", m.group())[0]
        Decimal(core.translate(str.maketrans({"−": "-", ",": "", ";": "", "'": "", " ": ""})))
        tokens.append(("number", m.start(), m.group()))
    # Standalone superscripts, subscripts and numeric compatibility characters
    # are protected too; they are not converted to decimal approximations.
    covered = tuple(NUMBER.finditer(text)) + units
    tokens.extend(("number", i, char) for i, char in enumerate(text)
                  if unicodedata.category(char).startswith("N") and not any(m.start() <= i < m.end() for m in covered))
    for m in WORD.finditer(text):
        word = m.group()
        if negative(word):
            tokens.append(("negation", m.start(), word))
    # Operators outside a recognized expression still retain their identity.
    tokens.extend(("unit", m.start(), m.group()) for m in re.finditer(r"[−/·×^]", text)
                  if not any(u.start() <= m.start() < u.end() for u in units))
    return tuple((kind, len(LEXEME.findall(unicodedata.normalize("NFC", text[:offset]))), spelling)
                 for kind, offset, spelling in sorted(tokens, key=lambda t: (t[1], t[0])))


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
    protection: str = PROTECTION_VERSION

    @property
    def quote_quarantined(self) -> bool:
        return self.status == "mismatch"


def _protected_difference(a: str, b: str) -> str | None:
    a, b = safe_typography(a), safe_typography(b)
    left = protected(a)
    right = protected(b)
    if left != right:
        for kind in ("number", "negation", "unit"):
            if [t for t in left if t[0] == kind] != [t for t in right if t[0] == kind]:
                return kind
    return None


def protected_character(char: str) -> bool:
    return (char in OPERATORS or unicodedata.category(char).startswith("N") or
            unicodedata.decomposition(char).startswith(("<super>", "<sub>")))


def skeleton(text: str) -> tuple[tuple[str, int], ...]:
    """Ordered protected characters and exact gaps BETWEEN them, not offsets."""
    positions = [(i, char) for i, char in enumerate(text) if protected_character(char)]
    return tuple((char, i - positions[n - 1][0] - 1 if n else 0)
                 for n, (i, char) in enumerate(positions))


def enclosing(text: str, start: int, end: int) -> tuple[re.Match, ...]:
    """Extend both nonempty edits and insertion points to adjacent lexemes."""
    return tuple(m for m in ENCLOSING_LEXEME.finditer(text)
                 if m.start() <= end and start <= m.end())


def material(lexeme: str) -> bool:
    """Letter boundaries split hyphens, digits and punctuation, never letters."""
    return (any(protected_character(char) for char in lexeme) or
            any(negative(m.group()) or m.group() in UNITS
                for m in LETTER_WORD.finditer(lexeme)))


def safe_edits(a: str, b: str, differences: tuple[Difference, ...]) -> bool:
    return not any(material(m.group()) for d in differences
                   for text, start, end in ((a, d.quote_start, d.quote_end),
                                            (b, d.source_start, d.source_end))
                   for m in enclosing(text, start, end))


def prefix_edit(text: str, start: int, end: int) -> bool:
    return any(start == m.start() and end >= start + len(prefix) and
               m.group().casefold().startswith(prefix)
               for m in enclosing(text, start, end) for prefix in NEGATIVE_PREFIXES)


def prefix_changes(a: str, b: str, differences: tuple[Difference, ...]) -> bool:
    for d in differences:
        if prefix_edit(a, d.quote_start, d.quote_end) or prefix_edit(b, d.source_start, d.source_end):
            return True
        # Alignment can preserve the first of two identical prefixes. Compare
        # the actual enclosing operands too, never another word's shared stem.
        left = enclosing(a, d.quote_start, d.quote_end)
        right = enclosing(b, d.source_start, d.source_end)
        if any(long.group().casefold() == prefix + short.group().casefold()
               for x in left for y in right for long, short in ((x, y), (y, x))
               for prefix in NEGATIVE_PREFIXES):
            return True
    return False


def relocation(a: str, b: str, differences: tuple[Difference, ...]) -> bool:
    """A moved substring's path must not cross or touch protected lexemes.

    Include replacement operands: a move can share an opcode with another
    edit. A one-character common substring is already a possible move.
    """
    for removed in differences:
        deleted = set(a[removed.quote_start:removed.quote_end]) - set(" \t\r\n")
        for added in differences:
            if removed == added or not deleted.intersection(b[added.source_start:added.source_end]):
                continue
            corridor = Difference(min(removed.quote_start, added.quote_start),
                                  max(removed.quote_end, added.quote_end),
                                  min(removed.source_start, added.source_start),
                                  max(removed.source_end, added.source_end))
            if not safe_edits(a, b, (corridor,)):
                return True
    return False


def edit_protection(a: str, b: str, differences: tuple[Difference, ...]) -> str | None:
    if skeleton(a) != skeleton(b):
        return "protected_character"
    if not safe_edits(a, b, differences):
        return "protected_edit"
    if prefix_changes(a, b, differences):
        return "protected_prefix"
    if relocation(a, b, differences):
        return "protected_relocation"
    return None


def _layers(quote: bytes, span: bytes) -> tuple[str, str | None, str, str, NearMatch | None]:
    original_a, original_b = quote.decode("utf-8"), span.decode("utf-8")
    a, b = normalize(original_a), normalize(original_b)
    if quote == span:
        return "match", None, a, b, None
    critical = _protected_difference(original_a, original_b)
    if critical is not None:
        return "mismatch", "protected_" + critical, a, b, None
    if a == b:
        return "match_normalized", None, a, b, None
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    differences = tuple(Difference(i, j, k, l) for tag, i, j, k, l in matcher.get_opcodes() if tag != "equal")
    critical_edit = edit_protection(a, b, differences)
    if critical_edit is not None:
        return "mismatch", critical_edit, a, b, None
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
