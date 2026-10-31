"""Independent wire oracles for the supported, schema-valid result domain."""
import inspect
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from pathlib import Path

from gen2 import accounting as a
from gen2.core import canonical
from gen2.accounting import dossier, stopping as s
from gen2.router.schemas import SchemaSet
from gen2.tests.test_stopping import CTX, DATE, inventory

EXAMPLES = Path(__file__).resolve().parents[1] / 'schema/examples/dossier-v2'


def document():
    return json.loads((EXAMPLES / 'valid-rich.json').read_text())['instance']


def admitted(case, call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except Exception as exc:
        case.fail(f"admitted production call raised {type(exc).__name__}: {exc}")


def decoded(case, value):
    result = admitted(case, dossier.decode, value)
    case.assertIsInstance(result, s.ProfileResult)
    for rules in (result.rules, result.dropped):
        case.assertIsInstance(rules, tuple)
        case.assertTrue(all(isinstance(rule, s.RuleResult) for rule in rules))
    return result


class CodecTest(unittest.TestCase):
    def encode(self, result):
        return admitted(self, dossier.encode, result)

    def decode(self, result):
        return decoded(self, result)

    def test_independent_shape_and_all_variants(self):
        doc = document()
        result = self.decode(doc['result'])
        self.assertEqual(self.encode(result), doc['result'])
        self.assertEqual(result.context, s.Context('fleet-a:t1', 2, 2))
        self.assertEqual(result.rules[0].operands.new_fraction, Fraction(1, 9007199254740991))
        self.assertEqual(result.rules[1].operands.scope, frozenset())
        self.assertEqual(result.rules[2].operands.found, frozenset({'a'}))
        self.assertEqual(result.gates[0].evidence_refs, (a.EvidenceReference('sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 9007199254740991, 'application/json'),))
        self.assertEqual(result.profile.completion_condition.operands[1].op, 'any')
        self.assertEqual(result.gates[0].context, s.Context('fleet-a:t1', 1, 2))
        for path in EXAMPLES.glob('valid-*.json'):
            doc = json.loads(path.read_text())['instance']
            self.assertEqual(SchemaSet().errors(doc, 'dossier-v2.schema.json'), [])
            self.assertEqual(self.encode(self.decode(doc['result'])), doc['result'])
        for change in ({'extra': 1}, {}):
            bad = {**document()['result'], **change}
            if not change:
                del bad['dropped']
            with self.assertRaisesRegex(ValueError, 'fields differ'):
                dossier.decode(bad)

    def test_counts_sorting_fractions_and_nullable_alternatives(self):
        for ids, reason, value in (({'b', 'a'}, None, 2), ({'a'}, 'partial', None), (set(), None, 0), (set(), 'missing', None)):
            result = self.decode(document()['result'])
            operands = replace(result.rules[2].operands, retrieved=a.Count(frozenset(ids), reason))
            result = replace(result, rules=(replace(result.rules[2], operands=operands),))
            encoded = self.encode(result)
            self.assertEqual(encoded['rules'][0]['operands']['retrieved'], {'known_ids': sorted(ids), 'unknown_reason': reason})
            self.assertEqual(self.decode(encoded).rules[0].operands.retrieved.value, value)
        for fraction in (None, Fraction(0), Fraction(2, 3)):
            doc = document()['result']
            doc['rules'][0]['operands']['new_fraction'] = None if fraction is None else {'numerator': float(fraction.numerator), 'denominator': float(fraction.denominator)}
            self.assertEqual(self.decode(doc).rules[0].operands.new_fraction, fraction)
        class Nonlexical(frozenset):
            def __iter__(self):
                return iter(('z', 'a', 'm'))
        self.assertEqual(self.encode(Nonlexical({'a', 'm', 'z'})), ['a', 'm', 'z'])

    def test_effective_labels_preserve_standing(self):
        for revision, classification, standing, labels in ((1, None, 'current', ('not_novel', 'independent', 'applicable', 'answer')),
                (2, 'compatible', 'compatible', ('not_novel', 'independent', 'applicable', 'answer')),
                (2, 'protocol_changed', 'stale', ('unknown',) * 4), (2, None, 'unknown', ('unknown',) * 4)):
            inv = replace(inventory(), current_contract_revision=revision,
                amendment_impacts=() if classification is None else (a.AmendmentImpact('amendment', 2, (a.RevisionStanding(1, classification),), (), DATE),))
            label = s.descriptive(replace(CTX, contract_revision=revision), 'yield', inv, DATE).operands.labels[0]
            self.assertEqual(label, s.LabelOperand('label', 'w1', standing, *labels))
            with self.assertRaises(FrozenInstanceError):
                label.novelty = 'unknown'

    def test_literal_declared_surfaces(self):
        self.assertEqual(str(inspect.signature(dossier.encode)), '(value)')
        self.assertEqual(str(inspect.signature(dossier.decode)), '(result: dict) -> gen2.accounting.stopping.ProfileResult')
        self.assertEqual(str(inspect.signature(dossier._decode)), '(value, hint)')
        self.assertEqual(str(inspect.signature(s.LabelOperand)), '(assessment_id: str, work_id: str, standing: Literal[\'current\', \'compatible\', \'stale\', \'unknown\'], novelty: str, independence: str, applicability: str, contribution: str) -> None')

    def test_added_dataclass_parameters(self):
        self.assertEqual(tuple(inspect.signature(s.CoverageOperands).parameters), ('minimum_windows', 'windows', 'history', 'eligible', 'ineligible', 'indeterminate', 'scope', 'lower', 'upper', 'raw_windows'))
        self.assertEqual(tuple(inspect.signature(s.DescriptiveOperands).parameters), ('units', 'labels', 'new_fraction'))
        self.assertEqual(tuple(inspect.signature(s.ProfileResult).parameters), ('context', 'profile', 'rules', 'gates', 'state', 'dropped', 'schema_version'))
        self.assertEqual(inspect.signature(s.ProfileResult).parameters['dropped'].default, ())
        self.assertEqual(str(inspect.signature(s.CoverageOperands).parameters['raw_windows'].annotation), 'tuple[gen2.accounting.stopping.WindowOperand, ...]')
        self.assertEqual(str(inspect.signature(s.ProfileResult).parameters['dropped'].annotation), 'tuple[gen2.accounting.stopping.RuleResult, ...]')
        self.assertEqual(str(inspect.signature(s.DescriptiveOperands).parameters['labels'].annotation), 'tuple[gen2.accounting.stopping.LabelOperand, ...]')

    def test_literal_schema_domains_and_integer_constraints(self):
        schema = json.loads((EXAMPLES.parent.parent / 'dossier-v2.schema.json').read_text())
        defs = schema['$defs']
        docs = [json.loads(p.read_text())['instance'] for p in EXAMPLES.glob('valid-*.json')]
        expected = {'state': {'satisfied', 'not_satisfied', 'unknown'}, 'standing': {'current', 'compatible', 'stale', 'unknown'},
            'window_state': {'eligible', 'ineligible', 'indeterminate'}, 'history': {'native', 'legacy_unknown'},
            'gate': {'challenge_pass_completed', 'coverage_integrity', 'load_bearing_verification_tiers'}}
        keys = {'state': ('state',), 'standing': ('standing',), 'window_state': ('state',), 'history': ('history',), 'gate': ('gate', 'conjunctive_gates')}
        def values(value, names):
            if isinstance(value, dict):
                for k, v in value.items():
                    if k in names:
                        yield from v if isinstance(v, list) else (v,)
                    yield from values(v, names)
            elif isinstance(value, list):
                for v in value:
                    yield from values(v, names)
        for name, literal in expected.items():
            self.assertEqual(set(defs[name]['enum']), literal)
            self.assertEqual(set(values(docs, keys[name])) & literal, literal)
        self.assertEqual({b['properties']['evaluator']['const'] for b in defs['rule']['oneOf']}, {'descriptive', 'coverage', 'known_item'})
        self.assertEqual(set(values(docs, ('evaluator',))), {'descriptive', 'coverage', 'known_item'})
        self.assertEqual(set(values(docs, ('op',))), {'all', 'any', None})
        for name, literal in {'novelty': {'novel', 'not_novel', 'unknown'}, 'independence': {'independent', 'shared_origin', 'unknown'},
                'applicability': {'applicable', 'not_applicable', 'unknown'}, 'contribution': {'answer', 'confidence', 'applicability', 'options', 'question_formulation', 'boundary_condition', 'contradiction', 'unknown'}}.items():
            self.assertEqual(set(defs['label']['properties'][name]['enum']), literal)
            self.assertEqual(set(values(docs, (name,))), literal)
        self.assertEqual(defs['integer'], {'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991})
        self.assertEqual(defs['revision'], {'type': 'integer', 'minimum': 1, 'maximum': 9007199254740991})
        for name, members in {'fraction': {'numerator': 'integer', 'denominator': 'revision'},
                'context': {'contract_revision': 'revision', 'protocol_revision': 'revision'},
                'coverage': {'minimum_windows': 'revision', 'eligible': 'integer', 'ineligible': 'integer', 'indeterminate': 'integer', 'lower': 'integer', 'upper': 'integer'},
                'reference': {'size_bytes': 'integer'}}.items():
            for member, target in members.items():
                self.assertEqual(defs[name]['properties'][member], {'$ref': f'#/$defs/{target}'})
        doc = document()
        before = canonical.content_hash(doc)
        doc['result']['gates'][0]['evidence_refs'][0]['content_hash'] = 'sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff'
        self.assertNotEqual(canonical.content_hash(doc), before)
