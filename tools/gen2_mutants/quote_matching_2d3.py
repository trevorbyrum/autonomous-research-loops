"""2d-3a matcher guards and independent accepted controls."""
from .base import Mutation

TEST = "test_quote_matching.MatchingTest."
TARGET = "gen2/router/quote_matching.py"
MUTATIONS = []
CONTROLS = {}


def guard(name, killer, old, new, control="test_exact_control"):
    mid = "2D3-" + name
    MUTATIONS.append(Mutation(mid, "2d-3a", name, (TEST + killer,), target=TARGET, old=old, new=new))
    CONTROLS[mid] = {"controls": [TEST + control], "why": "A separate full-result literal checks an intact UTF-8 artifact, permitted whitespace, an ordinary difference below threshold, or unchanged protected tokens beside a near-match typo; its checked behavior survives this mutation."}


guard("artifact-version", "test_wrong_artifact_version", "if actual_hash != expected_artifact_hash:", "if False:")
guard("span-offsets", "test_span_offsets", "if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(artifact):",
      "if type(start) is not int or type(end) is not int:")
guard("span-types", "test_span_boolean", "if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(artifact):",
      "if not 0 <= start < end <= len(artifact):")
guard("utf8", "test_utf8", 'return QuoteMatch(*args, "mismatch", "utf8")', 'return QuoteMatch(*args, "match", None)')
guard("exact", "test_exact_control", "if quote == span:", "if False:", "test_normalized_control")
guard("nfc", "test_normalization_rules", 'return unicodedata.normalize("NFC", safe_typography(text))', "return safe_typography(text)")
guard("curly-quotes", "test_normalization_rules", 'dict.fromkeys("‘’‚‛", "\'")', "{}")
guard("dashes", "test_normalization_rules", 'dict.fromkeys("‐‑‒–—―", "-")', "{}")
guard("dehyphenation", "test_normalization_rules", 'text = DEHYPHEN.sub("", text)', "text = text")
guard("whitespace", "test_normalization_rules", 'return " ".join(text.split())', "return text")
guard("number", "test_lexical_layer", 'tokens.append(("number", m.start(), m.group()))', "pass", "test_normalized_control")
guard("negation", "test_lexical_layer", 'word in NEGATIONS or word.endswith("n\'t") or word in NEGATIVE_WORDS', "False", "test_normalized_control")
guard("unit", "test_lexical_layer", 'tokens = [("unit", m.start(), m.group()) for m in units]', "tokens = []", "test_normalized_control")
guard("protected-position", "test_aligned_relocation", 'len(LEXEME.findall(unicodedata.normalize("NFC", text[:offset])))', "0", "test_near_control")
guard("normalized", "test_normalized_control", "if a == b:", "if False:", "test_near_control")
guard("critical-refusal", "test_negation_change", "if critical is not None:", "if False:", "test_near_control")
guard("threshold", "test_threshold", "if score >= 0.98:", "if score >= 0.99:", "test_near_control")
guard("repetition", "test_repetition", "SequenceMatcher(None, a, b, autojunk=False)", "SequenceMatcher(None, a, b, autojunk=True)", "test_normalized_control")
guard("near-is-mismatch", "test_near_match", 'return "mismatch", "near_match", a, b, NearMatch(score, differences)',
      'return "match_normalized", "near_match", a, b, NearMatch(score, differences)', "test_below_threshold_control")
guard("quarantine", "test_near_match", 'return self.status == "mismatch"', "return False")
guard("differing-spans", "test_near_match", 'NearMatch(score, differences)', 'NearMatch(score, ())', "test_below_threshold_control")
guard("symmetric-score", "test_similarity_symmetry", 'min(matcher.ratio(), SequenceMatcher(None, b, a, autojunk=False).ratio())',
      'matcher.ratio()', "test_near_control")
guard("number-parse", "test_number_parse_failure", 'return QuoteMatch(*args, "mismatch", "number_parse")',
      'return QuoteMatch(*args, "match_normalized", None)')

# Repair-1: each structural guard has an independent literal and surviving control.
guard("no-compatibility-fold", "test_compatibility_preserved", 'return unicodedata.normalize("NFC", safe_typography(text))',
      'return unicodedata.normalize("NFKC", safe_typography(text))')
guard("final-composition", "test_hangul_idempotence", 'return unicodedata.normalize("NFC", safe_typography(text))',
      'return safe_typography(unicodedata.normalize("NFC", text))')
guard("soft-hyphen-only", "test_hard_hyphen_and_minus", r'r"\u00ad[^\S\r\n]*\r?\n\s*"',
      r'r"[-\u00ad][^\S\r\n]*\r?\n\s*"')
guard("retain-minus", "test_hard_hyphen_and_minus", 'dict.fromkeys("‐‑‒–—―", "-")',
      'dict.fromkeys("‐‑‒–—―−", "-")')
guard("original-protection", "test_original_protection", '_protected_difference(original_a, original_b)',
      '_protected_difference(a, b)', "test_near_control")
guard("lossless-protection", "test_compatibility_preserved", 'a, b = safe_typography(a), safe_typography(b)',
      'a, b = safe_typography(unicodedata.normalize("NFKC", a)), safe_typography(unicodedata.normalize("NFKC", b))', "test_near_control")
guard("grouped-number", "test_complete_numbers", r"(?:[.,;' ]\d+)*", "", "test_near_control")
guard("numeric-powers", "test_lexical_layer", 'm.group()))\n    # Standalone',
      're.sub(rf"[{POWERS}]", "", m.group())))\n    # Standalone', "test_near_control")
guard("numeric-characters", "test_lexical_layer", 'if unicodedata.category(char).startswith("N") and', "if False and", "test_near_control")
guard("unit-structure", "test_unit_expressions", 'm.group()) for m in units]',
      're.sub(r"[/·×^²]", "", m.group())) for m in units]', "test_near_control")
guard("unit-words", "test_lexical_layer", 'second seconds minute minutes hour hours day days percent', "", "test_near_control")
guard("unit-operators", "test_hard_hyphen_and_minus", 're.finditer(r"[−/·×^]", text)',
      're.finditer(r"(?!)", text)', "test_near_control")
guard("listed-prefix", "test_negative_prefixes", 'or word in NEGATIVE_WORDS', "", "test_near_control")
guard("prefix-not-enough", "test_prefix_positive_control", 'return False\n\n\ndef protected',
      'return any(word.startswith(prefix) for prefix in NEGATIVE_PREFIXES)\n\n\ndef protected', "test_near_control")
guard("ordered-sequence", "test_complete_numbers", 'if left != right:', "if False:", "test_near_control")
guard("diagnostic-after-protection", "test_protection_before_diagnostic", 'critical = _protected_difference(original_a, original_b)',
      'SequenceMatcher(None, a, b, autojunk=False)\n    critical = _protected_difference(original_a, original_b)', "test_near_control")

# Repair-2: each of the researched rules (a)-(d) has a killer and control.
guard("protected-skeleton", "test_skeleton", 'if skeleton(a) != skeleton(b):', "if False:", "test_near_control")
guard("skeleton-gaps", "test_skeleton", 'i - positions[n - 1][0] - 1 if n else 0', "0", "test_near_control")
guard("safe-edit-regions", "test_safe_edit_regions", 'if not safe_edits(a, b, differences):', "if False:", "test_near_control")
guard("prefix-edits", "test_prefix_edit_regions", 'if prefix_changes(a, b, differences):', "if False:", "test_near_control")
guard("no-relocation", "test_relocation_regions", 'if relocation(a, b, differences):', "if False:", "test_near_control")

# DEBT-038: restoring contraction grouping must lose the protected-word guard.
guard("apostrophe-boundaries", "test_apostrophe_boundaries", r'LETTER_WORD = re.compile(r"[^\W\d_]+")',
      r'''LETTER_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*")''', "test_apostrophe_near_control")
CONTROLS["2D3-apostrophe-boundaries"]["why"] = (
    "The full-result ordinary apostrophe suffix-edit literal exercises material()'s LETTER_WORD lookup; "
    "its near diagnostic survives contraction grouping, while protected apostrophe edits lose their guard.")
guard("whitespace-endpoint", "test_apostrophe_whitespace_control",
      'm.end() == start and fragment[:1].isspace()', 'False', "test_apostrophe_near_control")
