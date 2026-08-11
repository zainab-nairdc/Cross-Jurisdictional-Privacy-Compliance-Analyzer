"""Tests for the canonical requirement store and its backfill.

The property under test throughout is the separation the store exists to make:
a Requirement is persistent knowledge about a REGULATION; an ObligationMapping
is one run's observation about a POLICY. Analysing the same regulation twice
must reuse the requirements, while the two runs' verdicts stay independent.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.library.models import Document, Requirement
from apps.library.requirements import ensure_requirements, make_key
from apps.mapping.models import Gap, MappingAnalysis, ObligationMapping


def _reg(name='Test Reg', **kw):
    return Document.objects.create(name=name, doc_type=Document.REGULATION,
                                   jurisdiction='bahrain', **kw)


def _policy(name='Test Policy'):
    return Document.objects.create(name=name, doc_type=Document.POLICY,
                                   jurisdiction='bahrain')


def _run(policy, regs):
    a = MappingAnalysis.objects.create(policy_doc=policy,
                                       status=MappingAnalysis.COMPLETE)
    a.regulations.set(regs)
    return a


def _mapping(analysis, reg, chunk, evidence, **kw):
    """A legacy-shaped row: grounded in a chunk, quoting it verbatim."""
    defaults = dict(
        article_ref='Art. 5', obligation_title='t', obligation_text='run commentary',
        coverage=ObligationMapping.NONE, confidence=0.9,
        regulation_chunk_id=chunk, regulation_evidence=evidence,
    )
    defaults.update(kw)
    return ObligationMapping.objects.create(analysis=analysis, regulation=reg, **defaults)


class RequirementStoreTests(TestCase):

    def test_a_regulation_can_hold_persistent_requirements(self):
        reg = _reg()
        rows = [{'text': 'The controller shall retain data no longer than necessary.',
                 'source_chunk_id': 'c1', 'article_ref': 'Art. 15',
                 'source_quote': 'shall retain...', 'topics': ['retention']}]
        out = ensure_requirements(reg, extractor=lambda r: rows)

        self.assertEqual(out['created'], 1)
        self.assertEqual(reg.requirements.count(), 1)
        # Persistent: it outlives any run, and there are none.
        self.assertFalse(MappingAnalysis.objects.exists())

    def test_second_extraction_reuses_the_same_requirements(self):
        reg = _reg()
        rows = [{'text': 'Retain no longer than necessary.', 'source_chunk_id': 'c1'},
                {'text': 'Notify the Authority of a breach.', 'source_chunk_id': 'c2'}]

        first = ensure_requirements(reg, extractor=lambda r: rows)
        ids_after_first = set(reg.requirements.values_list('pk', flat=True))

        second = ensure_requirements(reg, extractor=lambda r: rows)
        ids_after_second = set(reg.requirements.values_list('pk', flat=True))

        self.assertEqual(first['created'], 2)
        self.assertEqual(second['created'], 0)
        self.assertEqual(ids_after_first, ids_after_second,
                         'a repeat extraction minted new requirement rows')

    def test_two_runs_against_one_regulation_share_requirements(self):
        reg, pol = _reg(), _policy()
        ensure_requirements(reg, extractor=lambda r: [
            {'text': 'Retain no longer than necessary.', 'source_chunk_id': 'c1'}])
        req = reg.requirements.get()

        run_a, run_b = _run(pol, [reg]), _run(pol, [reg])
        m_a = _mapping(run_a, reg, 'c1', 'quote', requirement=req,
                       coverage=ObligationMapping.COVERED)
        m_b = _mapping(run_b, reg, 'c1', 'quote', requirement=req,
                       coverage=ObligationMapping.NONE)

        self.assertEqual(m_a.requirement_id, m_b.requirement_id)
        self.assertEqual(Requirement.objects.count(), 1)
        # ...but the observations stay independent.
        self.assertNotEqual(m_a.coverage, m_b.coverage)
        self.assertEqual(req.mappings.count(), 2)

    def test_mapping_results_stay_independent_between_runs(self):
        reg, pol = _reg(), _policy()
        ensure_requirements(reg, extractor=lambda r: [
            {'text': 'Do the thing.', 'source_chunk_id': 'c1'}])
        req = reg.requirements.get()

        run_a, run_b = _run(pol, [reg]), _run(pol, [reg])
        m_a = _mapping(run_a, reg, 'c1', 'q', requirement=req,
                       coverage=ObligationMapping.COVERED, confidence=0.95)
        m_b = _mapping(run_b, reg, 'c1', 'q', requirement=req,
                       coverage=ObligationMapping.PARTIAL, confidence=0.4)

        m_a.lifecycle = ObligationMapping.APPROVED
        m_a.save()
        m_b.refresh_from_db()

        self.assertEqual(m_b.lifecycle, ObligationMapping.DRAFT,
                         "one run's review state leaked into another")
        self.assertEqual(m_b.confidence, 0.4)

    def test_versions_can_hold_different_requirement_sets(self):
        v1 = _reg('Law v1')
        v2 = _reg('Law v2', version_of=v1)

        ensure_requirements(v1, extractor=lambda r: [
            {'text': 'Retain 5 years.', 'source_chunk_id': 'c1'}])
        ensure_requirements(v2, extractor=lambda r: [
            {'text': 'Retain 5 years.', 'source_chunk_id': 'c1'},
            {'text': 'Appoint a DPO.',  'source_chunk_id': 'c2'}])

        self.assertEqual(v1.requirements.count(), 1)
        self.assertEqual(v2.requirements.count(), 2)
        # Requirements belong to a version — v2's set is its own, not shared.
        self.assertFalse(set(v1.requirements.values_list('pk', flat=True)) &
                         set(v2.requirements.values_list('pk', flat=True)))
        # The shared provision keeps the same KEY under both owners, which is
        # what makes a cross-version comparison possible later.
        self.assertEqual(v1.requirements.first().key,
                         v2.requirements.get(source_chunk_id='c1').key)

    def test_same_key_may_be_reused_across_regulations(self):
        a, b = _reg('A'), _reg('B')
        for reg in (a, b):
            ensure_requirements(reg, extractor=lambda r: [
                {'text': 'Same provision.', 'source_chunk_id': 'shared'}])
        self.assertEqual(Requirement.objects.count(), 2,
                         'uniqueness must be per regulation, not global')

    def test_requirements_retain_traceability(self):
        reg = _reg()
        ensure_requirements(reg, extractor=lambda r: [{
            'text': 'The controller shall notify within 72 hours.',
            'title': 'Breach notification', 'article_ref': 'Art. 33',
            'source_chunk_id': 'chunk-abc', 'source_quote': 'shall notify ... 72 hours',
            'topics': ['breach'], 'applicability': 'controller'}])
        req = reg.requirements.get()

        self.assertEqual(req.regulation_id, reg.pk)
        self.assertEqual(req.article_ref, 'Art. 33')
        self.assertEqual(req.source_chunk_id, 'chunk-abc')
        self.assertIn('72 hours', req.source_quote)
        self.assertEqual(req.topics, ['breach'])
        self.assertEqual(req.applicability, 'controller')
        self.assertEqual(req.extraction_source, Requirement.LLM)
        self.assertFalse(req.is_migrated)

    def test_untraceable_items_are_skipped_not_invented(self):
        reg = _reg()
        out = ensure_requirements(reg, extractor=lambda r: [
            {'text': 'no chunk here', 'source_chunk_id': ''},
            {'text': '',              'source_chunk_id': 'c1'},
            {'text': 'good',          'source_chunk_id': 'c2'},
        ])
        self.assertEqual(out['created'], 1)
        self.assertEqual(out['skipped'], 2)

    def test_key_is_deterministic_and_whitespace_insensitive(self):
        self.assertEqual(make_key('c1', 'The  controller\nshall act.'),
                         make_key('c1', 'the controller shall act.'))
        self.assertNotEqual(make_key('c1', 'a'), make_key('c1', 'b'))
        self.assertNotEqual(make_key('c1'), make_key('c2'))
        # Chunk-only and text-scoped keys are different identities.
        self.assertNotEqual(make_key('c1'), make_key('c1', 'text'))


class BackfillTests(TestCase):
    """The migration path: rebuild a baseline from what past runs cited."""

    def setUp(self):
        self.reg, self.pol = _reg(), _policy()
        self.run1, self.run2 = _run(self.pol, [self.reg]), _run(self.pol, [self.reg])
        # Two runs citing the SAME chunk with different commentary — the real
        # shape in the live database.
        self.m1 = _mapping(self.run1, self.reg, 'chunk-A', 'The controller shall retain data.',
                           obligation_text='Access right is present.',
                           coverage=ObligationMapping.NONE,
                           lifecycle=ObligationMapping.APPROVED)
        self.m2 = _mapping(self.run2, self.reg, 'chunk-A',
                           'The controller shall retain data no longer than necessary.',
                           obligation_text='Retention gap.',
                           coverage=ObligationMapping.PARTIAL)
        # A row on its own chunk.
        self.m3 = _mapping(self.run1, self.reg, 'chunk-B', 'The processor shall assist.',
                           obligation_text='Assist duty.')
        # Rows that cannot be safely linked.
        self.no_chunk = _mapping(self.run1, self.reg, '', 'has evidence but no chunk')
        self.no_evid  = _mapping(self.run1, self.reg, 'chunk-C', '')
        # m1 is APPROVED and not covered, so the existing sync_gap_on_approval
        # receiver has already created its Gap — take that one rather than a
        # second, which the OneToOne would reject.
        self.gap = Gap.objects.get(obligation_mapping=self.m1)

    def _backfill(self, apply=True):
        out = StringIO()
        args = ['backfill_requirements'] + (['--apply'] if apply else [])
        call_command(*args, stdout=out)
        return out.getvalue()

    def test_dry_run_writes_nothing(self):
        report = self._backfill(apply=False)
        self.assertIn('DRY RUN', report)
        self.assertEqual(Requirement.objects.count(), 0)
        self.assertEqual(ObligationMapping.objects.filter(requirement__isnull=False).count(), 0)

    def test_backfill_creates_one_requirement_per_chunk_and_links(self):
        self._backfill()
        # chunk-A and chunk-B → 2 requirements. chunk-C has no evidence.
        self.assertEqual(Requirement.objects.count(), 2)
        self.m1.refresh_from_db(); self.m2.refresh_from_db(); self.m3.refresh_from_db()
        self.assertEqual(self.m1.requirement_id, self.m2.requirement_id,
                         'rows citing one chunk must share one requirement')
        self.assertNotEqual(self.m3.requirement_id, self.m1.requirement_id)

    def test_unlinkable_rows_get_no_invented_requirement(self):
        self._backfill()
        self.no_chunk.refresh_from_db(); self.no_evid.refresh_from_db()
        self.assertIsNone(self.no_chunk.requirement_id)
        self.assertIsNone(self.no_evid.requirement_id)

    def test_canonical_text_comes_from_evidence_not_obligation_text(self):
        self._backfill()
        req = Requirement.objects.get(source_chunk_id='chunk-A')
        # The longest verbatim quote of the chunk, never the run commentary.
        self.assertEqual(req.text, 'The controller shall retain data no longer than necessary.')
        self.assertNotIn('Access right', req.text)
        self.assertNotIn('Retention gap', req.text)

    def test_migrated_rows_are_distinguishable(self):
        self._backfill()
        for req in Requirement.objects.all():
            self.assertEqual(req.extraction_source, Requirement.MIGRATED)
            self.assertTrue(req.is_migrated)

    def test_backfill_is_idempotent(self):
        self._backfill()
        n_req = Requirement.objects.count()
        keys = sorted(Requirement.objects.values_list('key', flat=True))
        links = dict(ObligationMapping.objects.values_list('pk', 'requirement_id'))

        self._backfill()          # again

        self.assertEqual(Requirement.objects.count(), n_req)
        self.assertEqual(sorted(Requirement.objects.values_list('key', flat=True)), keys)
        self.assertEqual(dict(ObligationMapping.objects.values_list('pk', 'requirement_id')),
                         links)

    def test_backfill_preserves_original_text_and_evidence(self):
        before = dict(ObligationMapping.objects.values_list(
            'pk', 'obligation_text'))
        evidence_before = dict(ObligationMapping.objects.values_list(
            'pk', 'regulation_evidence'))
        self._backfill()
        self.assertEqual(dict(ObligationMapping.objects.values_list(
            'pk', 'obligation_text')), before)
        self.assertEqual(dict(ObligationMapping.objects.values_list(
            'pk', 'regulation_evidence')), evidence_before)

    def test_backfill_does_not_touch_gaps(self):
        before = list(Gap.objects.order_by('pk').values_list(
            'pk', 'priority', 'severity', 'remediation_text', 'obligation_mapping_id'))
        self._backfill()
        self.assertEqual(list(Gap.objects.order_by('pk').values_list(
            'pk', 'priority', 'severity', 'remediation_text', 'obligation_mapping_id')),
            before)

    def test_backfill_does_not_rewrite_approved_findings(self):
        before = ObligationMapping.objects.filter(
            lifecycle=ObligationMapping.APPROVED).values(
            'pk', 'coverage', 'confidence', 'obligation_text', 'article_ref',
            'lifecycle', 'reviewer_notes')
        snapshot = list(before)
        self._backfill()
        after = list(ObligationMapping.objects.filter(
            lifecycle=ObligationMapping.APPROVED).values(
            'pk', 'coverage', 'confidence', 'obligation_text', 'article_ref',
            'lifecycle', 'reviewer_notes'))
        self.assertEqual(snapshot, after)

    def test_coverage_and_gap_semantics_unchanged(self):
        """The vocabulary and the approval-driven Gap sync must be untouched."""
        self._backfill()
        self.assertEqual(
            [c[0] for c in ObligationMapping.COVERAGE_CHOICES],
            ['covered', 'partial', 'review', 'none'])
        # The post_save Gap sync still behaves as before, on a linked row.
        self.m2.refresh_from_db()
        self.assertIsNotNone(self.m2.requirement_id)
        self.m2.lifecycle = ObligationMapping.APPROVED
        self.m2.save()
        self.assertTrue(Gap.objects.filter(obligation_mapping=self.m2).exists())
        self.m2.coverage = ObligationMapping.COVERED
        self.m2.save()
        self.assertFalse(Gap.objects.filter(obligation_mapping=self.m2).exists())

    def test_requirement_cited_by_a_finding_cannot_be_deleted(self):
        from django.db.models import ProtectedError
        self._backfill()
        req = Requirement.objects.get(source_chunk_id='chunk-A')
        with self.assertRaises(ProtectedError):
            req.delete()
