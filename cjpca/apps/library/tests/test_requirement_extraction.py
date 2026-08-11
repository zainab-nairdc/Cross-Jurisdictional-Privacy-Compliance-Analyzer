"""Tests for native requirement extraction.

The invariant under test is that nothing reaches the store unless the
regulation itself supports it: every requirement carries a source chunk and a
quote that genuinely occurs in that chunk. The model is treated as an untrusted
proposer throughout.
"""

from django.test import TestCase

from apps.library.extraction import build_extractor, extract_for_regulation
from apps.library.models import Document, Requirement
from apps.library.requirements import make_key
from reasoning.requirement_extract import (
    candidate_chunks, extract_from_chunk, is_obligation_chunk, verify_candidate,
)

PROVISION = (
    'Article 15. The data controller shall notify the Authority within 72 hours '
    'of becoming aware of a personal data breach. The data controller must also '
    'inform the affected data subject without undue delay.'
)

CHUNK = {'node_id': 'chunk-1', 'content': PROVISION, 'article_ref': 'Art. 15'}


def _reg(name='Reg', **kw):
    return Document.objects.create(name=name, doc_type=Document.REGULATION,
                                   jurisdiction='bahrain', **kw)


def _reply(*items):
    """A stubbed model reply."""
    return lambda prompt, model=None: {'requirements': list(items)}


class CandidateFilterTests(TestCase):

    def test_binding_language_is_the_candidate_signal(self):
        self.assertTrue(is_obligation_chunk('The controller shall notify.'))
        self.assertTrue(is_obligation_chunk('Processors must encrypt data.'))
        self.assertFalse(is_obligation_chunk(
            'This Law is called the Personal Data Protection Law.'))

    def test_preamble_is_excluded_even_with_binding_words(self):
        self.assertFalse(is_obligation_chunk(
            'Whereas the Council shall consider the following recitals,'))

    def test_candidate_chunks_narrows_to_obligation_bearing(self):
        chunks = [
            {'node_id': 'a', 'content': 'Definitions. "Controller" means ...'},
            {'node_id': 'b', 'content': 'The controller shall keep records.'},
        ]
        self.assertEqual([c['node_id'] for c in candidate_chunks(chunks)], ['b'])


class VerificationTests(TestCase):

    def test_quote_must_occur_in_the_chunk(self):
        ok, why = verify_candidate({
            'requirement_text': 'The controller must notify within 72 hours.',
            'source_quote': 'shall notify the Regulator within 24 hours',
        }, PROVISION)
        self.assertFalse(ok)
        self.assertIn('not present', why)

    def test_verbatim_quote_passes_despite_whitespace_differences(self):
        ok, why = verify_candidate({
            'requirement_text': 'The controller must notify the Authority within 72 hours.',
            'source_quote': 'shall notify   the Authority\nwithin 72 hours',
        }, PROVISION)
        self.assertTrue(ok, why)

    def test_missing_fields_are_rejected(self):
        for cand in ({'source_quote': 'shall notify the Authority within 72 hours'},
                     {'requirement_text': 'The controller must notify the Authority.'},
                     {'requirement_text': 'x', 'source_quote': 'y'},
                     'not a dict'):
            ok, _ = verify_candidate(cand, PROVISION)
            self.assertFalse(ok)

    def test_coverage_verdicts_are_rejected_as_requirements(self):
        # The failure mode the migrated data exhibits: a verdict about a policy
        # masquerading as a requirement of the law.
        ok, why = verify_candidate({
            'requirement_text': 'Breach notification is fully covered by the policy.',
            'source_quote': 'shall notify the Authority within 72 hours',
        }, PROVISION)
        self.assertFalse(ok)
        self.assertIn('verdict', why)

    def test_unsupported_statement_is_rejected_by_nli(self):
        ok, why = verify_candidate({
            'requirement_text': 'The controller must appoint a data protection officer.',
            'source_quote': 'shall notify the Authority within 72 hours',
        }, PROVISION, nli=lambda text, quote: 0.99)
        self.assertFalse(ok)
        self.assertIn('not supported', why)

    def test_nli_failure_does_not_block_a_structurally_sound_candidate(self):
        def broken(text, quote):
            raise RuntimeError('model down')
        ok, _ = verify_candidate({
            'requirement_text': 'The controller must notify the Authority within 72 hours.',
            'source_quote': 'shall notify the Authority within 72 hours',
        }, PROVISION, nli=broken)
        self.assertTrue(ok)


class ExtractFromChunkTests(TestCase):

    def test_extracts_a_requirement_from_an_obligation_chunk(self):
        chat = _reply({
            'requirement_text': 'The controller must notify the Authority within 72 hours of a breach.',
            'source_quote': 'shall notify the Authority within 72 hours',
            'applicability': 'controller', 'inherent_severity': 'high',
            'topics': ['Breach Notification'],
        })
        got, rejected = extract_from_chunk(CHUNK, chat=chat)

        self.assertEqual(len(got), 1)
        self.assertEqual(rejected, [])
        r = got[0]
        self.assertEqual(r['source_chunk_id'], 'chunk-1')
        self.assertEqual(r['article_ref'], 'Art. 15')
        self.assertEqual(r['applicability'], 'controller')
        self.assertEqual(r['inherent_severity'], 'high')
        self.assertEqual(r['topics'], ['breach notification'])
        # The two texts are distinct: a normalised rule and verbatim evidence.
        self.assertNotEqual(r['text'], r['source_quote'])
        self.assertIn(r['source_quote'].split()[0], PROVISION)

    def test_multiple_requirements_from_one_chunk(self):
        chat = _reply(
            {'requirement_text': 'The controller must notify the Authority within 72 hours.',
             'source_quote': 'shall notify the Authority within 72 hours'},
            {'requirement_text': 'The controller must inform the affected data subject.',
             'source_quote': 'must also inform the affected data subject without undue delay'},
        )
        got, rejected = extract_from_chunk(CHUNK, chat=chat)
        self.assertEqual(len(got), 2)
        self.assertEqual(rejected, [])
        # Same chunk, different keys — both can coexist.
        keys = {make_key(g['source_chunk_id'], g['text']) for g in got}
        self.assertEqual(len(keys), 2)

    def test_invalid_model_output_is_rejected_not_persisted(self):
        for bad in (lambda p, m=None: {},
                    lambda p, m=None: {'requirements': 'nonsense'},
                    lambda p, m=None: []):
            got, rejected = extract_from_chunk(CHUNK, chat=bad)
            self.assertEqual(got, [])
            self.assertTrue(rejected)

    def test_invented_requirement_without_evidence_is_rejected(self):
        chat = _reply({
            'requirement_text': 'The controller must encrypt all data at rest.',
            'source_quote': 'shall encrypt all data at rest using AES-256',
        })
        got, rejected = extract_from_chunk(CHUNK, chat=chat)
        self.assertEqual(got, [])
        self.assertIn('not present in the source chunk', rejected[0])

    def test_duplicate_requirements_in_one_reply_are_collapsed(self):
        item = {'requirement_text': 'The controller must notify the Authority within 72 hours.',
                'source_quote': 'shall notify the Authority within 72 hours'}
        got, rejected = extract_from_chunk(CHUNK, chat=_reply(item, dict(item)))
        self.assertEqual(len(got), 1)
        self.assertIn('duplicate', rejected[0])

    def test_a_provision_imposing_nothing_yields_nothing(self):
        got, rejected = extract_from_chunk(CHUNK, chat=lambda p, m=None: {'requirements': []})
        self.assertEqual(got, [])
        self.assertEqual(rejected, [])


class ExtractForRegulationTests(TestCase):

    def setUp(self):
        self.reg = _reg()
        self.chat = _reply({
            'requirement_text': 'The controller must notify the Authority within 72 hours.',
            'source_quote': 'shall notify the Authority within 72 hours',
            'topics': ['breach'],
        })

    def test_persists_verified_requirements(self):
        rep = extract_for_regulation(self.reg, chat=self.chat, chunks=[CHUNK])
        self.assertEqual(rep['created'], 1)
        req = self.reg.requirements.get()
        self.assertEqual(req.extraction_source, Requirement.LLM)
        self.assertEqual(req.extraction_model, 'qwen2.5:7b')
        self.assertEqual(req.source_chunk_id, 'chunk-1')
        self.assertEqual(req.article_ref, 'Art. 15')
        self.assertFalse(req.is_migrated)

    def test_extraction_is_idempotent(self):
        first  = extract_for_regulation(self.reg, chat=self.chat, chunks=[CHUNK])
        ids    = set(self.reg.requirements.values_list('pk', flat=True))
        second = extract_for_regulation(self.reg, chat=self.chat, chunks=[CHUNK])

        self.assertEqual(first['created'], 1)
        self.assertEqual(second['created'], 0)
        self.assertEqual(self.reg.requirements.count(), 1)
        self.assertEqual(set(self.reg.requirements.values_list('pk', flat=True)), ids)

    def test_dry_run_writes_nothing(self):
        rep = extract_for_regulation(self.reg, chat=self.chat, chunks=[CHUNK],
                                     dry_run=True)
        self.assertEqual(rep['would_create'], 1)
        self.assertEqual(self.reg.requirements.count(), 0)

    def test_migrated_requirements_are_not_overwritten(self):
        migrated = Requirement.objects.create(
            regulation=self.reg, key=make_key('chunk-1'),
            text='verbatim historical quote', source_chunk_id='chunk-1',
            source_quote='verbatim historical quote',
            extraction_source=Requirement.MIGRATED)

        rep = extract_for_regulation(self.reg, chat=self.chat, chunks=[CHUNK])

        migrated.refresh_from_db()
        self.assertEqual(migrated.text, 'verbatim historical quote')
        self.assertEqual(migrated.extraction_source, Requirement.MIGRATED)
        self.assertEqual(self.reg.requirements.count(), 2)   # coexist
        # ...and the relationship is reported rather than silently resolved.
        self.assertEqual(len(rep['migrated_overlap']), 1)
        self.assertEqual(rep['migrated_overlap'][0]['migrated_requirement_id'],
                         migrated.pk)

    def test_version_isolation(self):
        v2 = _reg('Reg v2', version_of=self.reg)
        extract_for_regulation(self.reg, chat=self.chat, chunks=[CHUNK])
        extract_for_regulation(v2, chat=self.chat, chunks=[CHUNK])

        self.assertEqual(self.reg.requirements.count(), 1)
        self.assertEqual(v2.requirements.count(), 1)
        self.assertNotEqual(self.reg.requirements.get().pk, v2.requirements.get().pk)
        # carried_from is never inferred.
        self.assertIsNone(v2.requirements.get().carried_from_id)

    def test_rejected_output_is_reported_not_persisted(self):
        bad = _reply({'requirement_text': 'The controller must do something else.',
                      'source_quote': 'a quote that is not in the provision at all'})
        rep = extract_for_regulation(self.reg, chat=bad, chunks=[CHUNK])
        self.assertEqual(rep['created'], 0)
        self.assertEqual(rep['rejected_candidates'], 1)
        self.assertEqual(self.reg.requirements.count(), 0)

    def test_non_obligation_chunks_are_never_sent_to_the_model(self):
        seen = []

        def spy(prompt, model=None):
            seen.append(prompt)
            return {'requirements': []}

        extract_for_regulation(self.reg, chat=spy, chunks=[
            {'node_id': 'd', 'content': 'Definitions. "Controller" means a person.'},
            CHUNK,
        ])
        self.assertEqual(len(seen), 1, 'a non-obligation chunk was sent to the model')
        self.assertIn('72 hours', seen[0])


class IsolationTests(TestCase):
    """Extraction must never be able to see the policy side."""

    def test_extractor_receives_only_regulation_chunk_text(self):
        reg, pol = _reg(), Document.objects.create(
            name='Secret Policy', doc_type=Document.POLICY, jurisdiction='bahrain')
        prompts = []

        def spy(prompt, model=None):
            prompts.append(prompt)
            return {'requirements': []}

        extract_for_regulation(reg, chat=spy, chunks=[CHUNK])

        self.assertTrue(prompts)
        for p in prompts:
            self.assertNotIn('Secret Policy', p)
            self.assertNotIn('coverage', p.lower().split('provision')[0])
            self.assertIn(PROVISION[:40], p)

    def test_extraction_module_does_not_depend_on_policy_or_coverage_code(self):
        # A structural guard on real DEPENDENCIES, not on prose: checking the
        # raw source would trip over the module's own docstring explaining what
        # it deliberately does not touch.
        import ast
        import inspect
        import reasoning.requirement_extract as mod

        tree = ast.parse(inspect.getsource(mod))
        imported: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or '')
                imported.update(f'{node.module}.{a.name}' for a in node.names)

        for name in imported:
            self.assertNotIn('mapping', name.lower(),
                             f'extractor imports {name}')
            self.assertNotIn('comparison', name.lower(),
                             f'extractor imports {name}')

        # And no policy/coverage symbol is bound in its namespace at runtime.
        for forbidden in ('ObligationMapping', 'MappingAnalysis', 'Gap',
                          'PolicyCoverageItem'):
            self.assertNotIn(forbidden, vars(mod),
                             f'{forbidden} is bound in the extractor')
