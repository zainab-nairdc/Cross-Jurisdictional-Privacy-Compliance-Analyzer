"""Phase 1 — legal cross-references on requirements.

Two layers, tested separately because they fail differently:

  detection  (reasoning.legal_refs)  — pure, deterministic, no database. The
             risk here is FALSE POSITIVES: reading "31 days" as a citation.
  resolution (apps.library.references) — needs the chunk index. The risk here
             is WRONG TARGETS: pointing a reference at a plausible chunk that
             is not the one cited.

The safety rule under test throughout is that the system prefers `ambiguous`
or `unresolved` over an incorrect `resolved`. A wrong legal reference is worse
than a missing one because it manufactures traceability nobody can audit, so
several tests below assert that a resolution did NOT happen.
"""

from django.test import SimpleTestCase, TestCase

from apps.library.models import Document, Requirement, RequirementReference as RR
from apps.library.references import (
    ArticleIndex, detect_for_requirement, detect_references_for_regulation,
    find_document_for_citation,
)
from reasoning.legal_refs import (
    KIND_ARTICLE, KIND_LAW, KIND_PARAGRAPH, KIND_SCHEDULE, KIND_SECTION,
    REL_FOLLOWING, REL_PRECEDING, REL_SELF, SCOPE_EXTERNAL, SCOPE_INTERNAL,
    SCOPE_UNKNOWN, article_number_of, detect_references,
)


def _one(text):
    refs = detect_references(text)
    assert len(refs) == 1, f'expected exactly one reference in {text!r}, got {refs}'
    return refs[0]


# ═══════════════════════════════════════════════════════════════════════════
# Detection
# ═══════════════════════════════════════════════════════════════════════════

class ArticleReferenceDetectionTests(SimpleTestCase):
    """A — plain article references."""

    def test_plain_article(self):
        r = _one('The Authority shall perform the duties referred to in Article 31.')
        self.assertEqual((r.ref_kind, r.ref_number), (KIND_ARTICLE, '31'))

    def test_parenthesised_article_is_the_corpus_default(self):
        """Bahrain and Egypt both write "Article (10)" — the dominant form in
        the indexed corpus, so it is the one that must not regress."""
        r = _one('appointed by the Authority pursuant to Article (10) of this Law.')
        self.assertEqual((r.ref_kind, r.ref_number), (KIND_ARTICLE, '10'))

    def test_of_this_law_marks_the_reference_internal(self):
        r = _one('pursuant to Article (10) of this Law.')
        self.assertEqual(r.scope, SCOPE_INTERNAL)

    def test_bare_article_scope_is_unknown_not_assumed_internal(self):
        """'Probably internal' is not a fact. Resolution upgrades it only if it
        actually resolves here."""
        r = _one('as set out in Article 31.')
        self.assertEqual(r.scope, SCOPE_UNKNOWN)

    def test_leading_zeros_normalise(self):
        self.assertEqual(_one('under Article 07').ref_number, '7')

    def test_letter_suffixed_provision(self):
        """The Indian IT Act indexes provisions as '67B.'"""
        self.assertEqual(_one('under Section 67B of this Act').ref_number, '67B')


class SubsectionDetectionTests(SimpleTestCase):
    """B — article plus subsection."""

    def test_bracketed_subsection(self):
        r = _one('Article 31(2) applies.')
        self.assertEqual(r.ref_number, '31(2)')
        self.assertEqual((r.base_number, r.subsection), ('31', '2'))

    def test_spelled_out_subsection(self):
        r = _one('see Article 31 paragraph 2 of this Law')
        self.assertEqual(r.ref_number, '31(2)')

    def test_paragraph_of_article_is_one_reference_not_two(self):
        """The real Bahrain form. Detected as ONE reference to article 34;
        shredding it into a paragraph and an article would file two
        half-references, neither of which is what the text says."""
        r = _one('the committee as referred to in paragraph (2) of Article (34) of this Law.')
        self.assertEqual((r.ref_kind, r.ref_number), (KIND_ARTICLE, '34(2)'))
        self.assertEqual(r.scope, SCOPE_INTERNAL)


class ParagraphDetectionTests(SimpleTestCase):
    """C — paragraph references."""

    def test_bare_paragraph(self):
        r = _one('paragraph 4 shall apply')
        self.assertEqual((r.ref_kind, r.ref_number), (KIND_PARAGRAPH, '4'))

    def test_paragraph_of_this_article_keeps_its_number(self):
        r = _one('the measures referred to under Paragraph (1) of this Article.')
        self.assertEqual(r.ref_kind, KIND_PARAGRAPH)
        self.assertEqual(r.ref_number, 'self(1)')
        self.assertEqual(r.relative_kind, REL_SELF)
        self.assertEqual(r.subsection, '1')


class RangeDetectionTests(SimpleTestCase):
    """D — ranges."""

    def test_range_with_to(self):
        r = _one('Articles 31 to 35 shall apply.')
        self.assertEqual(r.ref_number, '31-35')
        self.assertTrue(r.is_range)
        self.assertEqual(r.range_bounds(), (31, 35))

    def test_range_with_dash(self):
        self.assertEqual(_one('Articles 31-35 shall apply.').ref_number, '31-35')

    def test_range_with_en_dash(self):
        self.assertEqual(_one('Articles 31–35 shall apply.').ref_number, '31-35')

    def test_singular_article_to(self):
        self.assertEqual(_one('Article 31 to 35').ref_number, '31-35')

    def test_descending_pair_is_not_a_range(self):
        """'Articles 35 to 31' is not something anyone drafted; treating it as
        a range would fabricate five targets."""
        refs = detect_references('Articles 35 to 31')
        self.assertFalse(any(r.is_range for r in refs))


class RelativeDetectionTests(SimpleTestCase):
    """I/J — relative designations."""

    def test_preceding(self):
        r = _one('the preceding Article shall apply')
        self.assertEqual(r.ref_number, REL_PRECEDING)
        self.assertTrue(r.is_relative)

    def test_following(self):
        self.assertEqual(_one('the following Article').ref_number, REL_FOLLOWING)

    def test_this_article(self):
        self.assertEqual(_one('this Article').ref_number, REL_SELF)

    def test_this_law_is_detected_as_an_instrument(self):
        r = _one('this Law shall enter into force')
        self.assertEqual((r.ref_kind, r.ref_number), (KIND_LAW, ''))

    def test_this_law_is_not_double_counted_inside_a_provision_reference(self):
        """'Article (10) of this Law' is ONE reference. Filing a second bare
        'this Law' beside it would bury the precise reference in noise — and
        the phrase appears in nearly every Bahrain provision."""
        refs = detect_references('pursuant to Article (10) of this Law.')
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].ref_kind, KIND_ARTICLE)


class ExternalDetectionTests(SimpleTestCase):
    """G/H — cross-document references."""

    def test_article_of_named_law(self):
        r = _one('Article 5 of Law No. 30 of 2018')
        self.assertEqual((r.ref_kind, r.ref_number, r.scope),
                         (KIND_ARTICLE, '5', SCOPE_EXTERNAL))
        self.assertEqual((r.law_number, r.law_year), ('30', '2018'))

    def test_eu_regulation_citation(self):
        r = _one('Article 6 of Regulation (EU) 2016/679')
        self.assertEqual(r.scope, SCOPE_EXTERNAL)
        self.assertEqual(r.law_number, '2016/679')

    def test_bare_instrument_citation(self):
        r = _one('as provided by Law No. 30 of 2018')
        self.assertEqual((r.ref_kind, r.scope), (KIND_LAW, SCOPE_EXTERNAL))


class OtherKindDetectionTests(SimpleTestCase):

    def test_schedule(self):
        r = _one('Schedule 2 lists the fees')
        self.assertEqual((r.ref_kind, r.ref_number), (KIND_SCHEDULE, '2'))

    def test_section(self):
        r = _one('section 5 of this Act')
        self.assertEqual((r.ref_kind, r.ref_number), (KIND_SECTION, '5'))


class FalsePositiveTests(SimpleTestCase):
    """K — ordinary numbers must not become citations.

    Every case here is prose that genuinely occurs in regulatory text. A
    detector that fires on these manufactures links between unrelated
    provisions, which is the failure mode this phase exists to avoid.
    """

    def test_percentage(self):
        self.assertEqual(detect_references('a fee of Article 5% shall apply'), [])

    def test_duration(self):
        self.assertEqual(detect_references('within 31 days of receipt'), [])

    def test_decimal_document_numbering(self):
        self.assertEqual(detect_references('see Section 2.5 of the handbook'), [])

    def test_paragraph_of_a_sentence(self):
        self.assertEqual(
            detect_references('paragraph 3 of the sentence is unclear'), [])

    def test_bare_numbers(self):
        for text in ('the controller shall respond within 15 working days',
                     'a fine not exceeding 20000 dinars',
                     'retained for no longer than 5 years',
                     'at least 72 hours after becoming aware'):
            with self.subTest(text=text):
                self.assertEqual(detect_references(text), [], text)

    def test_empty_and_none(self):
        self.assertEqual(detect_references(''), [])
        self.assertEqual(detect_references(None), [])
        self.assertEqual(detect_references('   '), [])


class ArticleNumberOfTests(SimpleTestCase):
    """The index key. Real article_ref values from the live corpus."""

    def test_bahrain_form(self):
        self.assertEqual(
            article_number_of('Article (7) Processing of data with respect to'), '7')

    def test_gdpr_form(self):
        self.assertEqual(article_number_of('Article (4)'), '4')

    def test_indian_numbered_section(self):
        self.assertEqual(article_number_of('67B. Punishment for publishing'), '67B')

    def test_unnumbered_headings_yield_nothing(self):
        """'' is the honest answer — nothing can cite these by number, so they
        must never become a resolution target."""
        for ref in ('Preamble', 'First Article', 'Third Article', 'Section_1',
                    'CHAPTER XIII - MISCELLANEOUS', '', 'Introduction'):
            with self.subTest(ref=ref):
                self.assertEqual(article_number_of(ref), '', ref)


class OriginalTextPreservationTests(SimpleTestCase):
    """M — ref_text is the audit record and is never normalised."""

    def test_wording_is_kept_verbatim(self):
        r = _one('pursuant to Article (10) of this Law.')
        self.assertEqual(r.ref_text, 'Article (10) of this Law')

    def test_relative_wording_is_kept(self):
        self.assertEqual(_one('the preceding Article').ref_text,
                         'the preceding Article')

    def test_original_survives_normalisation_of_the_number(self):
        r = _one('under Article 07')
        self.assertEqual(r.ref_number, '7')
        self.assertEqual(r.ref_text, 'Article 07')


# ═══════════════════════════════════════════════════════════════════════════
# Resolution
# ═══════════════════════════════════════════════════════════════════════════

def _chunk(node_id, article_ref, content='The controller shall act.'):
    return {'node_id': node_id, 'article_ref': article_ref, 'content': content}


# One chunk per article for 30-35, plus article 40 split across three chunks
# the way clause-chunking really splits a long article.
_ROWS = (
    [_chunk(f'n{n}', f'Article ({n}) Heading') for n in (30, 31, 32, 33, 34, 35)]
    + [_chunk('n40a', 'Article (40) Duties', '1. The Board shall convene.'),
       _chunk('n40b', 'Article (40) Duties', '2. The Board shall publish minutes.'),
       _chunk('n40c', 'Article (40) Duties', '3. The Board shall keep records.')]
    + [_chunk('npre', 'Preamble', 'We, the King, having reviewed...')]
)


class ResolutionTests(TestCase):

    def setUp(self):
        self.reg = Document.objects.create(
            name='Test Reg', doc_type=Document.REGULATION,
            jurisdiction='bahrain', document_id='BH-TEST')
        self.index = ArticleIndex('Test_Reg', _ROWS)

    def _req(self, quote, article_ref='Article (32) Source', chunk_id='n32'):
        return Requirement.objects.create(
            regulation=self.reg, key=f'k{abs(hash(quote)) % 10**9}',
            text='The controller must do the thing.', article_ref=article_ref,
            source_chunk_id=chunk_id, source_quote=quote)

    def _resolve(self, quote, **kw):
        rows = detect_for_requirement(self._req(quote, **kw),
                                      home_index=self.index, regulation=self.reg)
        self.assertTrue(rows, f'nothing detected in {quote!r}')
        return rows[0]

    # ── A: one article, one chunk ──
    def test_unique_article_resolves(self):
        row = self._resolve('as set out in Article 31 of this Law')
        self.assertEqual(row['status'], RR.RESOLVED)
        self.assertEqual(row['target_chunk_id'], 'n31')
        self.assertEqual(row['candidates'], [])

    def test_resolution_upgrades_unknown_scope_to_internal(self):
        row = self._resolve('as set out in Article 31')
        self.assertEqual(row['scope'], SCOPE_INTERNAL)

    # ── E: one article, many chunks ──
    def test_article_split_across_chunks_is_ambiguous(self):
        """One article is NOT one chunk. GDPR Article (4) is ten chunks in the
        live index; picking one would be a coin flip."""
        row = self._resolve('in accordance with Article 40 of this Law')
        self.assertEqual(row['status'], RR.AMBIGUOUS)
        self.assertEqual(row['target_chunk_id'], '')
        self.assertEqual(sorted(row['candidates']), ['n40a', 'n40b', 'n40c'])

    def test_ambiguous_never_picks_a_winner(self):
        row = self._resolve('in accordance with Article 40')
        self.assertFalse(row['target_chunk_id'],
                         'an ambiguous reference must not name a single target')

    # ── B: subsection narrowing ──
    def test_subsection_narrows_a_split_article_when_deterministic(self):
        row = self._resolve('as required by Article 40(2) of this Law')
        self.assertEqual(row['status'], RR.RESOLVED)
        self.assertEqual(row['target_chunk_id'], 'n40b')

    def test_subsection_that_matches_nothing_stays_ambiguous(self):
        """Narrowing that fails must not shrink the candidate set — dropping
        real targets to manufacture a clean answer is the same error as
        guessing."""
        row = self._resolve('as required by Article 40(9) of this Law')
        self.assertEqual(row['status'], RR.AMBIGUOUS)
        self.assertEqual(len(row['candidates']), 3)

    def test_subsection_on_a_unique_article_resolves_to_it(self):
        row = self._resolve('as required by Article 31(2) of this Law')
        self.assertEqual(row['status'], RR.RESOLVED)
        self.assertEqual(row['target_chunk_id'], 'n31')

    # ── F: missing article ──
    def test_missing_article_is_unresolved(self):
        row = self._resolve('as set out in Article 99 of this Law')
        self.assertEqual(row['status'], RR.UNRESOLVED)
        self.assertEqual(row['target_chunk_id'], '')
        self.assertIn('no indexed provision', row['resolution_note'])

    def test_unnumbered_chunks_are_never_targets(self):
        self.assertEqual(self.index.chunks_for(''), [])

    # ── D: ranges ──
    def test_fully_present_range_is_ambiguous_with_all_candidates(self):
        """A range names several provisions, so it does not designate exactly
        one chunk. Recorded honestly rather than collapsed."""
        row = self._resolve('Articles 31 to 33 of this Law shall apply')
        self.assertEqual(row['status'], RR.AMBIGUOUS)
        self.assertEqual(sorted(row['candidates']), ['n31', 'n32', 'n33'])

    def test_partially_missing_range_is_not_reported_resolved(self):
        """Marking this resolved would assert coverage of provisions that are
        not in the corpus at all."""
        row = self._resolve('Articles 33 to 37 of this Law shall apply')
        self.assertEqual(row['status'], RR.UNRESOLVED)
        self.assertIn('not indexed', row['resolution_note'])
        # what WAS found is still preserved
        self.assertEqual(sorted(row['candidates']), ['n33', 'n34', 'n35'])

    # ── I: relative, deterministic ──
    def test_preceding_article_resolves_from_a_numbered_source(self):
        """Inside Article 32, "the preceding Article" is Article 31 by
        arithmetic, not by inference."""
        row = self._resolve('the preceding Article shall apply',
                            article_ref='Article (32) Source')
        self.assertEqual(row['status'], RR.RESOLVED)
        self.assertEqual(row['target_chunk_id'], 'n31')

    def test_following_article_resolves(self):
        row = self._resolve('the following Article shall apply',
                            article_ref='Article (32) Source')
        self.assertEqual(row['target_chunk_id'], 'n33')

    def test_this_article_resolves_to_its_own_article(self):
        """Article 31 is a single chunk, so "of this Article" lands on it
        without needing to narrow by clause marker at all."""
        row = self._resolve('Paragraph (1) of this Article applies',
                            article_ref='Article (31) Source', chunk_id='n31')
        self.assertEqual(row['status'], RR.RESOLVED)
        self.assertEqual(row['target_chunk_id'], 'n31')

    # ── J: relative, not deterministic ──
    def test_relative_from_an_unnumbered_source_stays_unresolved(self):
        """No number to count from means no deterministic target. Pointing at
        a plausible neighbour would be a guess."""
        row = self._resolve('the preceding Article shall apply',
                            article_ref='Preamble', chunk_id='npre')
        self.assertEqual(row['status'], RR.UNRESOLVED)
        self.assertIn('unnumbered', row['resolution_note'])

    def test_preceding_from_article_one_stays_unresolved(self):
        row = self._resolve('the preceding Article shall apply',
                            article_ref='Article (1) Definitions', chunk_id='n1')
        self.assertEqual(row['status'], RR.UNRESOLVED)

    def test_relative_into_a_missing_neighbour_stays_unresolved(self):
        """Article 36 is not indexed, so "the following Article" from 35 has
        nowhere safe to land."""
        row = self._resolve('the following Article shall apply',
                            article_ref='Article (35) Source', chunk_id='n35')
        self.assertEqual(row['status'], RR.UNRESOLVED)

    def test_relative_paragraph_narrows_within_a_split_article(self):
        """"Paragraph (1) of this Article" inside the split Article 40 lands on
        the chunk that actually carries clause marker 1. Deterministic — the
        marker search is anchored — so this is resolution, not a guess."""
        row = self._resolve('Paragraph (1) of this Article applies',
                            article_ref='Article (40) Duties', chunk_id='n40a')
        self.assertEqual(row['status'], RR.RESOLVED)
        self.assertEqual(row['target_chunk_id'], 'n40a')

    def test_relative_paragraph_with_no_matching_clause_stays_ambiguous(self):
        """Article 40 has clauses 1-3. Paragraph 7 matches none of them, so
        every chunk of the article remains a candidate."""
        row = self._resolve('Paragraph (7) of this Article applies',
                            article_ref='Article (40) Duties', chunk_id='n40a')
        self.assertEqual(row['status'], RR.AMBIGUOUS)
        self.assertEqual(len(row['candidates']), 3)

    # ── kinds that cannot be resolved from an article index ──
    def test_bare_paragraph_is_detected_but_not_resolved(self):
        """A paragraph with no article attached probably belongs to the
        enclosing article — but probably is not deterministic."""
        row = self._resolve('paragraph 4 shall apply')
        self.assertEqual(row['ref_kind'], KIND_PARAGRAPH)
        self.assertEqual(row['status'], RR.UNRESOLVED)

    def test_schedule_is_detected_but_not_resolved(self):
        row = self._resolve('Schedule 2 lists the applicable fees')
        self.assertEqual(row['status'], RR.UNRESOLVED)

    def test_this_law_names_the_document_but_no_provision(self):
        row = self._resolve('this Law shall enter into force')
        self.assertEqual(row['status'], RR.UNRESOLVED)
        self.assertEqual(row['target_document'], self.reg)
        self.assertIn('not a provision', row['resolution_note'])


class ExternalResolutionTests(TestCase):
    """G/H — the document/provision distinction."""

    def setUp(self):
        self.reg = Document.objects.create(
            name='Home Reg', doc_type=Document.REGULATION,
            jurisdiction='bahrain', document_id='BH-HOME')
        self.index = ArticleIndex('Home_Reg', _ROWS)

    def _row(self, quote):
        req = Requirement.objects.create(
            regulation=self.reg, key='ext1', text='x',
            article_ref='Article (32) Source', source_chunk_id='n32',
            source_quote=quote)
        rows = detect_for_requirement(req, home_index=self.index,
                                      regulation=self.reg)
        self.assertTrue(rows)
        return rows[0]

    def test_unknown_instrument_is_external_and_unresolved(self):
        row = self._row('as provided in Article 5 of Law No. 77 of 1999')
        self.assertEqual(row['scope'], SCOPE_EXTERNAL)
        self.assertEqual(row['status'], RR.UNRESOLVED)
        self.assertIsNone(row['target_document'])

    def test_known_document_by_document_id(self):
        Document.objects.create(name='GDPR', doc_type=Document.REGULATION,
                                jurisdiction='eu', document_id='2016/679')
        row = self._row('in accordance with Article 6 of Regulation (EU) 2016/679')
        self.assertEqual(row['target_doc_code'], '2016/679')
        self.assertEqual(row['scope'], SCOPE_EXTERNAL)

    def test_known_document_but_unresolvable_provision(self):
        """H — document-level identification is NOT provision-level
        resolution, and conflating them would report a link to a provision
        that was never located."""
        Document.objects.create(name='GDPR', doc_type=Document.REGULATION,
                                jurisdiction='eu', document_id='2016/679')
        row = self._row('in accordance with Article 6 of Regulation (EU) 2016/679')
        self.assertIsNotNone(row['target_document'])
        self.assertEqual(row['status'], RR.UNRESOLVED)
        self.assertEqual(row['target_chunk_id'], '')

    def test_ambiguous_citation_matches_no_document(self):
        """Two documents sharing a code is not a resolution. Picking one would
        be exactly the unauditable error this phase forbids."""
        for i in (1, 2):
            Document.objects.create(name=f'Dup {i}', doc_type=Document.REGULATION,
                                    jurisdiction='other', document_id='99/99')
        row = self._row('under Article 3 of Regulation (EU) 99/99')
        self.assertIsNone(row['target_document'])
        self.assertEqual(row['status'], RR.UNRESOLVED)

    def test_name_match_requires_both_number_and_year(self):
        Document.objects.create(name='Bahrain PDPL Law 30 2018',
                                doc_type=Document.REGULATION,
                                jurisdiction='bahrain', document_id='')
        row = self._row('as provided in Article 5 of Law No. 30 of 2018')
        self.assertIsNotNone(row['target_document'])
        self.assertEqual(row['target_document'].name, 'Bahrain PDPL Law 30 2018')


# ═══════════════════════════════════════════════════════════════════════════
# Persistence
# ═══════════════════════════════════════════════════════════════════════════

class PersistenceTests(TestCase):

    def setUp(self):
        self.reg = Document.objects.create(
            name='Persist Reg', doc_type=Document.REGULATION,
            jurisdiction='bahrain', document_id='BH-P')
        self.req = Requirement.objects.create(
            regulation=self.reg, key='p1',
            text='The controller must notify.',
            article_ref='Article (32) Source', source_chunk_id='n32',
            source_quote='The controller shall notify as set out in Article 31 '
                         'of this Law and in Article 40 of this Law.')

    def _patch_index(self):
        """Substitute the fixture index for the bm25-backed one."""
        from apps.library import references as mod
        original = mod.ArticleIndex.for_document
        mod.ArticleIndex.for_document = classmethod(
            lambda cls, title: ArticleIndex(title or 'Persist_Reg', _ROWS))
        self.addCleanup(setattr, mod.ArticleIndex, 'for_document', original)

    def test_dry_run_writes_nothing(self):
        self._patch_index()
        rep = detect_references_for_regulation(self.reg, dry_run=True)
        self.assertEqual(rep['detected'], 2)
        self.assertEqual(RR.objects.count(), 0)
        self.assertEqual(rep['created'], 0)

    def test_apply_writes_rows(self):
        self._patch_index()
        rep = detect_references_for_regulation(self.reg, dry_run=False)
        self.assertEqual(rep['created'], 2)
        self.assertEqual(RR.objects.count(), 2)
        self.assertEqual(
            {r.status for r in RR.objects.all()}, {RR.RESOLVED, RR.AMBIGUOUS})

    def test_rerun_does_not_duplicate(self):
        """L — re-runnable. The uniqueness key uses only fields fixed at
        detection, so a second pass refreshes rather than duplicates."""
        self._patch_index()
        detect_references_for_regulation(self.reg, dry_run=False)
        first = RR.objects.count()
        rep = detect_references_for_regulation(self.reg, dry_run=False)
        self.assertEqual(RR.objects.count(), first)
        self.assertEqual(rep['created'], 0)
        self.assertEqual(rep['updated'], 2)

    def test_rerun_refreshes_resolution_in_place(self):
        self._patch_index()
        detect_references_for_regulation(self.reg, dry_run=False)
        row = RR.objects.get(ref_number='31')
        row.status = RR.UNRESOLVED
        row.target_chunk_id = ''
        row.save()
        detect_references_for_regulation(self.reg, dry_run=False)
        row.refresh_from_db()
        self.assertEqual(row.status, RR.RESOLVED)
        self.assertEqual(row.target_chunk_id, 'n31')

    def test_stored_ref_text_is_verbatim(self):
        """M — persisted, not just detected."""
        self._patch_index()
        detect_references_for_regulation(self.reg, dry_run=False)
        self.assertEqual(
            sorted(RR.objects.values_list('ref_text', flat=True)),
            ['Article 31 of this Law', 'Article 40 of this Law'])

    def test_candidates_are_persisted_for_ambiguous_rows(self):
        self._patch_index()
        detect_references_for_regulation(self.reg, dry_run=False)
        row = RR.objects.get(status=RR.AMBIGUOUS)
        self.assertEqual(sorted(row.candidates), ['n40a', 'n40b', 'n40c'])

    def test_prune_removes_rows_the_detector_no_longer_produces(self):
        self._patch_index()
        detect_references_for_regulation(self.reg, dry_run=False)
        RR.objects.create(requirement=self.req, ref_text='Article 77 of this Law',
                          ref_kind=KIND_ARTICLE, ref_number='77',
                          detected_by=RR.REGEX, status=RR.UNRESOLVED)
        self.assertEqual(RR.objects.count(), 3)
        rep = detect_references_for_regulation(self.reg, dry_run=False, prune=True)
        self.assertEqual(rep['pruned'], 1)
        self.assertEqual(RR.objects.count(), 2)

    def test_prune_leaves_non_regex_rows_alone(self):
        """Pruning is for the detector's own derived output. A row recorded by
        any other means is not the detector's to delete."""
        self._patch_index()
        detect_references_for_regulation(self.reg, dry_run=False)
        RR.objects.create(requirement=self.req, ref_text='Article 88 of this Law',
                          ref_kind=KIND_ARTICLE, ref_number='88',
                          detected_by=RR.LLM, status=RR.UNRESOLVED)
        detect_references_for_regulation(self.reg, dry_run=False, prune=True)
        self.assertTrue(RR.objects.filter(detected_by=RR.LLM).exists())

    def test_requirement_text_is_never_modified(self):
        """The whole point: a reference is a pointer, not a transplant."""
        self._patch_index()
        before = self.req.text
        detect_references_for_regulation(self.reg, dry_run=False)
        self.req.refresh_from_db()
        self.assertEqual(self.req.text, before)
        self.assertNotIn('Article 31', self.req.text)

    def test_requirement_with_no_quote_yields_nothing(self):
        """A classification/detection failure must never remove a requirement."""
        self._patch_index()
        Requirement.objects.create(regulation=self.reg, key='noquote',
                                   text='A rule.', source_chunk_id='n30',
                                   source_quote='')
        rep = detect_references_for_regulation(self.reg, dry_run=False)
        self.assertEqual(Requirement.objects.filter(regulation=self.reg).count(), 2)
        self.assertEqual(rep['requirements'], 2)

    def test_repeated_reference_in_one_quote_is_one_row(self):
        """A dry run must report the number of ROWS it would write, not the
        number of textual occurrences, or --dry-run and --apply disagree."""
        self._patch_index()
        Requirement.objects.create(
            regulation=self.reg, key='rep',
            text='A rule.', article_ref='Article (32) Source',
            source_chunk_id='n32',
            source_quote='under Article 31 of this Law, and as Article 31 of '
                         'this Law further provides')
        rep = detect_references_for_regulation(self.reg, dry_run=False)
        self.assertEqual(
            RR.objects.filter(requirement__key='rep').count(), 1)
        self.assertEqual(rep['created'], 3)   # 2 for self.req + 1 here

    def test_casing_variants_are_one_row(self):
        self._patch_index()
        Requirement.objects.create(
            regulation=self.reg, key='case', text='A rule.',
            article_ref='Article (32) Source', source_chunk_id='n32',
            source_quote='this Law applies, and this law shall govern')
        detect_references_for_regulation(self.reg, dry_run=False)
        rows = RR.objects.filter(requirement__key='case')
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().ref_text, 'this Law')   # first wins

    def test_dry_run_and_apply_report_the_same_count(self):
        self._patch_index()
        dry = detect_references_for_regulation(self.reg, dry_run=True)
        wet = detect_references_for_regulation(self.reg, dry_run=False)
        self.assertEqual(dry['detected'], wet['detected'])
        self.assertEqual(wet['created'], dry['detected'])

    def test_cascade_on_requirement_delete(self):
        self._patch_index()
        detect_references_for_regulation(self.reg, dry_run=False)
        self.req.delete()
        self.assertEqual(RR.objects.count(), 0)


class CommandTests(TestCase):
    """The command surface, including that dry run is the default."""

    def setUp(self):
        self.reg = Document.objects.create(
            name='Cmd Reg', doc_type=Document.REGULATION,
            jurisdiction='bahrain', document_id='BH-C')
        Requirement.objects.create(
            regulation=self.reg, key='c1', text='A rule.',
            article_ref='Article (32) Source', source_chunk_id='n32',
            source_quote='as set out in Article 31 of this Law')
        from apps.library import references as mod
        original = mod.ArticleIndex.for_document
        mod.ArticleIndex.for_document = classmethod(
            lambda cls, title: ArticleIndex(title or 'Cmd_Reg', _ROWS))
        self.addCleanup(setattr, mod.ArticleIndex, 'for_document', original)

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command('detect_references', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_dry_run_is_the_default(self):
        out = self._run(str(self.reg.pk))
        self.assertIn('DRY RUN', out)
        self.assertEqual(RR.objects.count(), 0)

    def test_apply_writes(self):
        self._run(str(self.reg.pk), '--apply')
        self.assertEqual(RR.objects.count(), 1)

    def test_all_flag(self):
        out = self._run('--all')
        self.assertIn('Cmd Reg', out)
        self.assertEqual(RR.objects.count(), 0)

    def test_missing_document_reports_cleanly(self):
        self.assertIn('No document with id 999999', self._run('999999'))

    def test_no_argument_reports_cleanly(self):
        self.assertIn('Give a document id or --all', self._run())
