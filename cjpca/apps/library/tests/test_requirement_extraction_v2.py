"""Tests for Requirement Extractor v2.

Covers only what v2 adds over v1: deterministic clause segmentation, the
two-stage split, and the two new gates (anti-copy, applicability grounding).
v1's own tests still run unchanged.
"""

from django.test import TestCase

from apps.library.models import Document, Requirement
from apps.library.requirements import make_key
from reasoning.requirement_extract_v2 import (
    EXTRACTOR_VERSION, extract_from_chunk, find_spans, jaccard,
    normalise_span, segment_clauses, verify,
)

# Shortened from the real Article (10). The trailing "shall" clause is kept
# because the chunk-level obligation filter needs binding language SOMEWHERE in
# the chunk — the sub-clauses inherit it from the stem and carry none of their
# own, which is the whole reason segmentation happens after that filter.
ART10 = (
    '1. The Data Protection Guardian is responsible for the following: '
    '1. Assisting the data controller in exercising his rights and adhering to his duties; '
    '2. liaising between the Authority and Data Controller with respect to implementation; '
    '3. ensuring that the Data Controller processes personal data in compliance with this Law; '
    '4. notifying the Authority upon obtaining new evidence concerning committed violations. '
    'The Data Controller shall maintain the register if a Guardian is not appointed.'
)

CHUNK = {'node_id': 'chunk-10', 'content': ART10,
         'article_ref': 'Article (10) Data Protection Guardian'}


def _reg(name='Reg', **kw):
    return Document.objects.create(name=name, doc_type=Document.REGULATION,
                                   jurisdiction='bahrain', **kw)


class SegmentationTests(TestCase):

    def test_enumerated_subclauses_become_separate_segments(self):
        segs = segment_clauses(ART10)
        # stem + four duties
        self.assertGreaterEqual(len(segs), 5)
        joined = ' '.join(s['text'] for s in segs)
        for duty in ('Assisting', 'liaising', 'ensuring', 'notifying'):
            self.assertIn(duty, joined)

    def test_every_segment_is_a_verbatim_substring_of_the_chunk(self):
        # This is what lets a quote verified against a segment also be verified
        # against the chunk it came from.
        for s in segment_clauses(ART10):
            self.assertIn(s['text'].split(' ')[0], ART10)

    def test_a_number_inside_a_sentence_does_not_split_it(self):
        text = 'The controller shall notify the Authority within 72 hours of the breach.'
        self.assertEqual(len(segment_clauses(text)), 1)

    def test_unnumbered_text_is_one_segment(self):
        text = 'The Authority shall carry out its duties efficiently and transparently.'
        segs = segment_clauses(text)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]['text'], text)

    def test_runt_segments_are_merged_not_emitted(self):
        for s in segment_clauses('1. a; 2. b; 3. The controller shall keep records of processing.'):
            self.assertGreaterEqual(len(s['text']), 10)

    def test_empty_input(self):
        self.assertEqual(segment_clauses(''), [])


class StageOneTests(TestCase):

    def test_returns_only_verbatim_spans(self):
        chat = lambda p, m=None: {'spans': [
            {'source_quote': 'ensuring that the Data Controller processes personal data in compliance with this Law',
             'marker': '3'}]}
        spans, bad = find_spans(ART10, 'Art 10', chat=chat)
        self.assertEqual(len(spans), 1)
        self.assertEqual(bad, [])
        self.assertIn(spans[0]['source_quote'][:30], ART10)

    def test_a_span_not_in_the_passage_is_rejected(self):
        chat = lambda p, m=None: {'spans': [
            {'source_quote': 'The controller shall encrypt all data at rest using AES-256.'}]}
        spans, bad = find_spans(ART10, chat=chat)
        self.assertEqual(spans, [])
        self.assertIn('not verbatim', bad[0])

    def test_malformed_stage1_output(self):
        for bad_chat in (lambda p, m=None: {},
                         lambda p, m=None: {'spans': 'nope'},
                         lambda p, m=None: []):
            spans, bad = find_spans(ART10, chat=bad_chat)
            self.assertEqual(spans, [])
            self.assertTrue(bad)

    def test_duplicate_spans_collapse(self):
        q = 'liaising between the Authority and Data Controller with respect to implementation'
        chat = lambda p, m=None: {'spans': [{'source_quote': q}, {'source_quote': q}]}
        spans, bad = find_spans(ART10, chat=chat)
        self.assertEqual(len(spans), 1)
        self.assertIn('duplicate', bad[0])


class GateTests(TestCase):
    QUOTE = 'ensuring that the Data Controller processes personal data in compliance with this Law'

    def _rule(self, **kw):
        base = {'requirement_text': 'The Data Protection Guardian must ensure the controller '
                                    'processes personal data lawfully.',
                'applicability': 'Data Controller', 'topics': [], 'title': 't'}
        base.update(kw)
        return base

    def test_a_good_candidate_passes(self):
        ok, why = verify(self._rule(), self.QUOTE, ART10)
        self.assertTrue(ok, why)

    def test_identical_to_quote_is_rejected(self):
        ok, why = verify(self._rule(requirement_text=self.QUOTE), self.QUOTE, ART10)
        self.assertFalse(ok)
        self.assertIn('identical', why)

    def test_near_copy_is_rejected(self):
        # same words, trivially reordered — v1's dominant failure mode
        near = 'ensuring the Data Controller processes personal data in compliance with this Law'
        ok, why = verify(self._rule(requirement_text=near), self.QUOTE, ART10)
        self.assertFalse(ok)
        self.assertIn('near-copy', why)

    def test_applicability_must_be_supported_by_the_chunk(self):
        ok, why = verify(self._rule(applicability='hospital'), self.QUOTE, ART10)
        self.assertFalse(ok)
        self.assertIn('applicability', why)

    def test_empty_applicability_is_allowed(self):
        ok, why = verify(self._rule(applicability=''), self.QUOTE, ART10)
        self.assertTrue(ok, why)

    def test_quote_must_be_in_the_chunk(self):
        ok, why = verify(self._rule(), 'a quote that appears nowhere in the article', ART10)
        self.assertFalse(ok)
        self.assertIn('not present', why)

    def test_verdict_language_still_rejected(self):
        ok, why = verify(self._rule(requirement_text='Breach notification is fully covered here.'),
                         self.QUOTE, ART10)
        self.assertFalse(ok)
        self.assertIn('verdict', why)

    def test_jaccard(self):
        self.assertEqual(jaccard('a b c', 'a b c'), 1.0)
        self.assertEqual(jaccard('a b', 'c d'), 0.0)


class PipelineTests(TestCase):

    def _chat(self, spans, rule):
        """Stub answering stage 1 then stage 2 by prompt shape."""
        def chat(prompt, model=None):
            if 'marking up' in prompt:
                return {'spans': [{'source_quote': s} for s in spans
                                  if s in prompt]}
            return dict(rule)
        return chat

    def test_multiple_requirements_from_one_chunk(self):
        spans = [
            'Assisting the data controller in exercising his rights and adhering to his duties',
            'notifying the Authority upon obtaining new evidence concerning committed violations',
        ]
        seen = {'n': 0}

        def chat(prompt, model=None):
            if 'marking up' in prompt:
                return {'spans': [{'source_quote': s} for s in spans if s in prompt]}
            seen['n'] += 1
            return {'requirement_text': f'The Guardian must perform duty number {seen["n"]} '
                                        f'as set out by the Authority.',
                    'title': f'duty {seen["n"]}', 'applicability': 'Data Controller',
                    'topics': ['governance']}

        got, rejected = extract_from_chunk(CHUNK, chat=chat)
        self.assertEqual(len(got), 2, rejected)
        self.assertEqual({g['source_quote'] for g in got}, set(spans))
        # distinct keys -> both can be stored
        self.assertEqual(len({make_key(g['source_chunk_id'], g['text']) for g in got}), 2)

    def test_severity_is_never_populated(self):
        chat = self._chat(
            ['Assisting the data controller in exercising his rights and adhering to his duties'],
            {'requirement_text': 'The Guardian must assist the controller with its duties.',
             'title': 'assist', 'applicability': '', 'topics': []})
        got, _ = extract_from_chunk(CHUNK, chat=chat)
        self.assertTrue(got)
        for g in got:
            self.assertIsNone(g['inherent_severity'])

    def test_extractor_version_is_stamped(self):
        chat = self._chat(
            ['Assisting the data controller in exercising his rights and adhering to his duties'],
            {'requirement_text': 'The Guardian must assist the controller with its duties.',
             'title': 'assist', 'applicability': '', 'topics': []})
        got, _ = extract_from_chunk(CHUNK, chat=chat)
        self.assertEqual(got[0]['extraction_model'], EXTRACTOR_VERSION)
        self.assertEqual(EXTRACTOR_VERSION, 'qwen2.5:7b/v2')

    def test_copying_the_quote_produces_nothing(self):
        q = 'Assisting the data controller in exercising his rights and adhering to his duties'
        chat = self._chat([q], {'requirement_text': q, 'title': 't',
                                'applicability': '', 'topics': []})
        got, rejected = extract_from_chunk(CHUNK, chat=chat)
        self.assertEqual(got, [])
        self.assertTrue(any('identical' in r or 'near-copy' in r for r in rejected))


ART4 = (
    "Processing Personal data is prohibited without the data subject's consent, "
    'unless the processing is necessary for: '
    '1. performance of a contract to which the data subject is a party; '
    '2. taking steps at the request of the data subject with the purpose of '
    'entering into a contract; '
    '3. protecting the vital interests of the data subject; or '
    '4. Pursuing the legitimate interests of the Data Controller.'
)


class ExceptionHandlingTests(TestCase):
    """Exception clauses are conditions of the parent rule, never rules."""

    def test_exception_stems_are_recognised(self):
        from reasoning.requirement_extract_v2 import stem_introduces_exceptions
        for stem in ("Processing is prohibited without consent, unless necessary for:",
                     'The controller may process data except where the subject objects.',
                     'This applies provided that adequate safeguards exist.',
                     'Records are kept subject to the retention schedule.'):
            self.assertTrue(stem_introduces_exceptions(stem), stem)

    def test_duty_stems_are_not_treated_as_exceptions(self):
        from reasoning.requirement_extract_v2 import stem_introduces_exceptions
        self.assertFalse(stem_introduces_exceptions(
            'The Data Protection Guardian is responsible for the following:'))

    def test_exception_items_never_become_obligations(self):
        """The Article 4 regression: an exception became a duty on the subject."""
        prompts = []

        def chat(prompt, model=None):
            prompts.append(prompt)
            if 'marking up' in prompt:
                stem = "Processing Personal data is prohibited without the data subject's consent"
                return {'spans': [{'source_quote': stem}] if stem in prompt else []}
            return {'requirement_text': 'The data controller may process personal data '
                                        'without consent where necessary for a contract.',
                    'title': 'lawful basis', 'applicability': 'data controller',
                    'topics': ['lawful basis']}

        got, _ = extract_from_chunk(
            {'node_id': 'c4', 'content': ART4, 'article_ref': 'Article (4)'}, chat=chat)

        self.assertEqual(len(got), 1, 'exceptions were extracted as separate rules')
        # No prompt should ever have asked stage 1 about an exception item alone.
        stage1 = [p for p in prompts if 'marking up' in p]
        self.assertEqual(len(stage1), 1)
        self.assertNotIn('taking steps at the request', stage1[0])
        # The exception text is offered to stage 2 as CONDITIONS instead.
        stage2 = [p for p in prompts if 'Restate ONE' in p]
        self.assertTrue(any('not separate obligations' in p for p in stage2))


class ActorVerificationTests(TestCase):
    QUOTE = 'ensuring that the Data Controller processes personal data in compliance with this Law'

    def _v(self, text, chunk=ART10, stem=''):
        return verify({'requirement_text': text, 'applicability': '', 'topics': [],
                       'title': 't'}, self.QUOTE, chunk, stem=stem)

    def test_subjectless_fragments_are_rejected(self):
        for frag in ('shall comply with legal obligations',
                     'must adhere to prescribed duties',
                     'must rectify issues as soon as possible'):
            ok, why = self._v(frag)
            self.assertFalse(ok, frag)
            self.assertIn('subject', why)

    def test_non_actor_subject_is_rejected(self):
        ok, why = self._v('processing must be necessary for the performance of a contract')
        self.assertFalse(ok)
        self.assertIn('legal actor', why)

    def test_invented_actor_is_rejected(self):
        ok, why = self._v('Undertakers must rectify issues as soon as possible.')
        self.assertFalse(ok)
        self.assertIn('actor', why)

    def test_grounded_actor_passes(self):
        ok, why = self._v('The Data Controller shall process personal data lawfully.')
        self.assertTrue(ok, why)

    def test_actor_may_be_inherited_from_the_stem(self):
        # A sub-clause's subject legitimately lives in the lead-in.
        ok, why = verify(
            {'requirement_text': 'The Guardian shall assist the controller with its duties.',
             'applicability': '', 'topics': [], 'title': 't'},
            'assisting the data controller in exercising his rights',
            'assisting the data controller in exercising his rights',
            stem='The Data Protection Guardian is responsible for the following:')
        self.assertTrue(ok, why)


class ShortQuoteTests(TestCase):
    CHUNK = ('The record shall be published in the Official Gazette. '
             'The Board is composed of seven members appointed by Decree.')

    def test_a_short_but_complete_provision_is_accepted(self):
        ok, why = verify(
            {'requirement_text': 'The Authority shall publish the record in the Official Gazette.',
             'applicability': '', 'topics': [], 'title': 't'},
            'shall be published in the Official Gazette',      # 41 chars
            self.CHUNK + ' The Authority is responsible.')
        self.assertTrue(ok, why)

    def test_a_very_short_quote_with_binding_language_is_accepted(self):
        ok, why = verify(
            {'requirement_text': 'The record shall be published by the Authority.',
             'applicability': '', 'topics': [], 'title': 't'},
            'shall be published',                              # 18 chars
            self.CHUNK + ' The Authority is responsible.')
        self.assertTrue(ok, why)

    def test_a_short_quote_without_binding_language_is_rejected(self):
        ok, why = verify(
            {'requirement_text': 'The Board shall have seven members.',
             'applicability': '', 'topics': [], 'title': 't'},
            'seven members',                                   # no modal
            self.CHUNK)
        self.assertFalse(ok)
        self.assertIn('binding language', why)

    def test_below_the_floor_is_still_rejected(self):
        ok, why = verify(
            {'requirement_text': 'The Board shall meet regularly.',
             'applicability': '', 'topics': [], 'title': 't'},
            'shall meet',                                      # 10 chars
            self.CHUNK)
        self.assertFalse(ok)
        self.assertIn('too short', why)


class SubjectPositionActorTests(TestCase):
    """The actor must be the SUBJECT, not merely a word somewhere in the rule."""

    CHUNK = ('The Data Controller shall notify the Data Subject within ten working days. '
             'The Authority shall maintain the register. The Data Protection Guardian '
             'shall notify the Authority. A processor must implement appropriate '
             'measures. The record shall be published by the Authority.')
    # Deliberately unrelated to the rules under test, so the anti-copy gate
    # cannot fire and mask what these cases are actually checking.
    QUOTE = 'A processor must implement appropriate measures'

    def _v(self, text):
        return verify({'requirement_text': text, 'applicability': '', 'topics': [],
                       'title': 't'}, self.QUOTE, self.CHUNK)

    def test_valid_subjects_are_accepted(self):
        for good in (
            'The Data Controller shall notify the Data Subject within ten working days.',
            'The Authority shall maintain the register.',
            'The Data Protection Guardian shall notify the Authority.',
        ):
            ok, why = self._v(good)
            self.assertTrue(ok, f'{good} -> {why}')

    def test_explicit_passive_agent_is_accepted(self):
        ok, why = self._v('The record shall be published by the Authority.')
        self.assertTrue(ok, why)

    def test_object_position_actor_is_not_enough(self):
        # "controller" is the OBJECT here; nobody is bound.
        for bad in ('shall assist the data controller in exercising rights',
                    'shall immediately inform the data controller',
                    'Must comply with legal obligations.',
                    'must process data fairly and lawfully'):
            ok, why = self._v(bad)
            self.assertFalse(ok, bad)
            self.assertIn('subject', why)

    def test_passive_without_an_agent_is_rejected(self):
        ok, why = self._v('The record shall be published in the Official Gazette.')
        self.assertFalse(ok)

    def test_non_actor_subject_is_rejected(self):
        ok, why = self._v('Processing must be necessary for the performance of a contract.')
        self.assertFalse(ok)
        self.assertIn('not a legal actor', why)

    def test_actor_must_be_named_in_the_source(self):
        ok, why = self._v('The licensee shall submit an annual return.')
        self.assertFalse(ok)
        self.assertIn('not named in the source', why)


class TemplateLeakTests(TestCase):
    CHUNK = ('The data controller must satisfy the condition set out in Article 4 '
             'before processing personal data. The Authority shall act on any '
             'condition or requirement it imposes.')
    QUOTE = 'The data controller must satisfy the condition set out in Article 4'

    def _v(self, text):
        return verify({'requirement_text': text, 'applicability': '', 'topics': [],
                       'title': 't'}, self.QUOTE, self.CHUNK)

    def test_template_skeleton_is_rejected(self):
        for leak in ('WHO must/shall process data only if necessary for a contract.',
                     'WHO must process personal data lawfully at all times.',
                     'WHO shall notify the Authority within ten working days.',
                     'ACTION must be completed before the processing begins.',
                     'CONDITION or deadline applies to this processing activity.',
                     'The controller must/shall notify the Authority promptly.'):
            ok, why = self._v(leak)
            self.assertFalse(ok, leak)
            self.assertIn('template', why)

    def test_leak_check_is_case_insensitive(self):
        ok, why = self._v('who must/shall process data only if necessary for a contract.')
        self.assertFalse(ok)
        self.assertIn('template', why)

    def test_legitimate_provision_mentioning_condition_is_kept(self):
        ok, why = self._v(
            'The data controller must satisfy every condition prescribed by the Authority.')
        self.assertTrue(ok, why)

    def test_legitimate_provision_mentioning_action_is_kept(self):
        ok, why = self._v(
            'The Authority shall take action against any controller that fails to comply.')
        self.assertTrue(ok, why)


class StageOneFragmentTests(TestCase):
    """Empty and lead-in spans are distinguished from genuinely short ones."""

    PASSAGE = ('the data controller shall: 1. keep records; '
               '2. shall be published in the Official Gazette.')

    def test_empty_span_reported_as_such(self):
        chat = lambda p, m=None: {'spans': [{'source_quote': ''}, {'source_quote': '   '}]}
        spans, bad = find_spans(self.PASSAGE, chat=chat)
        self.assertEqual(spans, [])
        self.assertTrue(all('had no quote' in b for b in bad))

    def test_list_lead_in_is_not_a_provision(self):
        chat = lambda p, m=None: {'spans': [{'source_quote': 'the data controller shall:'}]}
        spans, bad = find_spans(self.PASSAGE, chat=chat)
        self.assertEqual(spans, [])
        self.assertIn('lead-in', bad[0])

    def test_a_legitimate_short_provision_survives(self):
        chat = lambda p, m=None: {'spans': [
            {'source_quote': 'shall be published in the Official Gazette'}]}
        spans, bad = find_spans(self.PASSAGE, chat=chat)
        self.assertEqual(len(spans), 1, bad)

    def test_a_meaningless_short_fragment_is_still_rejected(self):
        chat = lambda p, m=None: {'spans': [{'source_quote': 'records'}]}
        spans, bad = find_spans(self.PASSAGE, chat=chat)
        self.assertEqual(spans, [])
        self.assertIn('too short', bad[0])


class CoexistenceTests(TestCase):
    """v2 must not disturb v1 or migrated rows."""

    def test_v2_rows_coexist_with_v1_and_migrated(self):
        reg = _reg()
        migrated = Requirement.objects.create(
            regulation=reg, key=make_key('chunk-10'), text='verbatim historical quote',
            source_chunk_id='chunk-10', extraction_source=Requirement.MIGRATED)
        v1 = Requirement.objects.create(
            regulation=reg, key=make_key('chunk-10', 'v1 wording of the rule'),
            text='v1 wording of the rule', source_chunk_id='chunk-10',
            extraction_source=Requirement.LLM, extraction_model='qwen2.5:7b')
        v2_key = make_key('chunk-10', 'The Guardian must assist the controller.')

        self.assertNotEqual(v2_key, migrated.key)
        self.assertNotEqual(v2_key, v1.key)

        Requirement.objects.create(
            regulation=reg, key=v2_key,
            text='The Guardian must assist the controller.',
            source_chunk_id='chunk-10', extraction_source=Requirement.LLM,
            extraction_model=EXTRACTOR_VERSION)

        self.assertEqual(reg.requirements.count(), 3)
        migrated.refresh_from_db(); v1.refresh_from_db()
        self.assertEqual(migrated.text, 'verbatim historical quote')
        self.assertEqual(v1.extraction_model, 'qwen2.5:7b')
        # v1 and v2 are distinguishable by extraction_model, no schema change.
        self.assertEqual(
            reg.requirements.filter(extraction_model=EXTRACTOR_VERSION).count(), 1)
