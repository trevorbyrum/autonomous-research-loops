"""2d-3a matcher guards and independent accepted controls."""
from .base import Mutation

TEST = "test_quote_matching.MatchingTest."
TARGET = "gen2/router/quote_matching.py"
MUTATIONS = []
CONTROLS = {}


def guard(name, killer, old, new, control="test_exact_control"):
    mid = "2D3-" + name
    MUTATIONS.append(Mutation(mid, "2d-3a", name, (TEST + killer,), target=TARGET, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "A separate literal checks an intact UTF-8 artifact, an accepted ligature, or unchanged protected tokens beside a near-match typo; its checked behavior survives this mutation."}


guard("artifact-version", "test_wrong_artifact_version", "if actual_hash != expected_artifact_hash:", "if False:")
guard("span-offsets", "test_span_offsets", "if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(artifact):",
      "if type(start) is not int or type(end) is not int:")
guard("span-types", "test_span_boolean", "if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(artifact):",
      "if not 0 <= start < end <= len(artifact):")
guard("utf8", "test_utf8", 'return QuoteMatch(*args, "mismatch", "utf8")', 'return QuoteMatch(*args, "match", None)')
guard("exact", "test_exact_control", "if quote == span:", "if False:", "test_normalized_control")
guard("nfkc", "test_normalization_rules", 'unicodedata.normalize("NFKC", text)', "text")
guard("curly-quotes", "test_normalization_rules", 'dict.fromkeys("‘’‚‛", "\'")', "{}")
guard("dashes", "test_normalization_rules", 'dict.fromkeys("‐‑‒–—―−", "-")', "{}")
guard("dehyphenation", "test_normalization_rules", 'text = DEHYPHEN.sub("", text)', "text = text")
guard("whitespace", "test_normalization_rules", 'return " ".join(text.split())', "return text")
guard("number", "test_number_change", 'tokens = [("number", m.start(), m.end(), (m.group(), Decimal(m.group()))) for m in NUMBER.finditer(text)]',
      "tokens = []", "test_normalized_control")
guard("negation", "test_negation_change", 'word.casefold() in NEGATIONS or word.casefold().endswith("n\'t")', "False", "test_normalized_control")
guard("unit", "test_unit_change", "if word in UNITS:", "if False:", "test_normalized_control")
guard("protected-position", "test_moved_negation", "if lo < end and start < hi:", "if False:", "test_near_control")
guard("normalized", "test_normalized_control", "if a == b:", "if False:", "test_near_control")
guard("critical-refusal", "test_negation_change", "if critical is not None:", "if False:", "test_near_control")
guard("threshold", "test_threshold", "if score >= 0.98:", "if score >= 0.99:", "test_near_control")
guard("repetition", "test_repetition", "SequenceMatcher(None, a, b, autojunk=False)", "SequenceMatcher(None, a, b, autojunk=True)", "test_normalized_control")
guard("near-is-mismatch", "test_near_match", 'return "mismatch", "near_match", a, b, NearMatch(score, differences)',
      'return "match_normalized", "near_match", a, b, NearMatch(score, differences)', "test_near_control")
guard("quarantine", "test_near_match", 'return self.status == "mismatch"', "return False")
guard("differing-spans", "test_near_match", 'NearMatch(score, differences)', 'NearMatch(score, ())', "test_near_control")
guard("symmetric-score", "test_similarity_symmetry", 'min(matcher.ratio(), SequenceMatcher(None, b, a, autojunk=False).ratio())',
      'matcher.ratio()', "test_near_control")
guard("number-parse", "test_number_parse_failure", 'return QuoteMatch(*args, "mismatch", "number_parse")',
      'return QuoteMatch(*args, "match_normalized", None)')
