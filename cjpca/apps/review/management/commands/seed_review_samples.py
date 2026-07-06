"""
Management command: seed_review_samples
Creates realistic sample data for the Review & Validate page.

Usage:
    python manage.py seed_review_samples
    python manage.py seed_review_samples --reset   # wipe and re-seed
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.library.models import Document
from apps.mapping.models import Gap, MappingAnalysis, ObligationMapping
from apps.review.models import ReviewItem
from apps.history.models import AuditLog

User = get_user_model()

OBLIGATIONS = [
    # (article_ref, title, coverage, confidence, evidence_snippet, priority)
    ('Art. 5(1)(a)', 'Lawfulness, fairness and transparency of processing',
     ObligationMapping.COVERED, 92,
     'Section 3.1 of the BBK Data Policy explicitly states that personal data shall be processed lawfully, fairly and in a transparent manner. Consent forms are documented and retained per Section 4.',
     None),

    ('Art. 6(1)', 'Legal basis for processing personal data',
     ObligationMapping.PARTIAL, 68,
     'BBK Policy Section 3.2 references consent and legitimate interest but does not address all six legal bases defined under GDPR Art. 6. Contract and legal obligation bases are missing.',
     Gap.MEDIUM),

    ('Art. 13', 'Information to be provided where data collected from subject',
     ObligationMapping.REVIEW, 55,
     'Privacy notices exist but do not include all mandatory elements — retention period and DPO contact are absent from consumer-facing notices reviewed.',
     Gap.HIGH),

    ('Art. 17', 'Right to erasure ("right to be forgotten")',
     ObligationMapping.NONE, 12,
     'No documented procedure found for handling erasure requests. Policy references data subject rights generically without specifying erasure handling timelines or escalation paths.',
     Gap.HIGH),

    ('Art. 25', 'Data protection by design and by default',
     ObligationMapping.COVERED, 88,
     'BBK SDLC Policy (v2.3) mandates privacy impact assessments at project initiation. Evidence of DPIAs found in 8 of 10 sampled projects.',
     None),

    ('Art. 32', 'Security of processing',
     ObligationMapping.PARTIAL, 74,
     'Information Security Policy covers encryption at rest and in transit. However, pseudonymisation is not explicitly required and access-control review cycles exceed GDPR guidance of annual.',
     Gap.MEDIUM),

    ('Art. 33', 'Notification of breach to supervisory authority',
     ObligationMapping.COVERED, 95,
     'Incident Response Procedure v4 mandates 72-hour notification to supervisory authority. Breach register reviewed and up to date.',
     None),

    ('Art. 35', 'Data protection impact assessment',
     ObligationMapping.REVIEW, 60,
     'DPIA template exists but threshold criteria for triggering a DPIA are overly narrow — high-risk processing involving biometrics and profiling may not trigger an assessment under current criteria.',
     Gap.HIGH),

    ('Art. 44', 'General principle for transfers to third countries',
     ObligationMapping.NONE, 8,
     'No cross-border transfer policy identified. Third-party agreements reviewed do not include Standard Contractual Clauses or adequacy decisions.',
     Gap.HIGH),

    ('Art. 88', 'Processing in the context of employment',
     ObligationMapping.PARTIAL, 70,
     'HR Data Policy covers employee data generally. Specific provisions for monitoring, whistleblowing, and reference checks are absent.',
     Gap.LOW),
]

REVIEW_DECISIONS = [
    # (obligation_index, status, reviewer_idx, note, days_ago)
    (0, ReviewItem.ACCEPTED, 0, 'Confirmed — reviewed the consent forms in SharePoint. All present and signed.', 5),
    (1, ReviewItem.MODIFIED, 1,
     'Partially agreed. We do cover contract basis in the vendor agreements — evidence source should be updated to include Annex B of supplier contracts.',
     3),
    (2, ReviewItem.REJECTED, 0,
     'Disagree with "review" status. Privacy notice was updated in Jan 2024 and now includes DPO contact and retention schedule. Changing to covered.',
     2),
    (4, ReviewItem.ACCEPTED, 1, 'DPIA process is solid. Confirmed with the project team — 8/10 is accurate.', 4),
    (6, ReviewItem.ACCEPTED, 0, 'Breach register verified. 72h threshold is met in all logged incidents.', 6),
]


class Command(BaseCommand):
    help = 'Seed sample ReviewItem, ObligationMapping, Gap and AuditLog data for demo purposes.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete existing sample data before seeding')

    def handle(self, *args, **options):
        users = list(User.objects.all().order_by('id'))
        if len(users) < 1:
            self.stderr.write(self.style.ERROR('No users found. Create at least one user first.'))
            return
        user_a = users[0]
        user_b = users[1] if len(users) > 1 else users[0]
        reviewers = [user_a, user_b]

        if options['reset']:
            ReviewItem.objects.all().delete()
            Gap.objects.all().delete()
            ObligationMapping.objects.all().delete()
            MappingAnalysis.objects.all().delete()
            AuditLog.objects.filter(event_type__startswith='review_').delete()
            Document.objects.filter(name__in=['GDPR (EU) 2016/679', 'BBK Data Protection & Privacy Policy']).delete()
            self.stdout.write('Existing sample data cleared.')

        # ── Documents ──────────────────────────────────────────────────────
        reg_doc, _ = Document.objects.get_or_create(
            name='GDPR (EU) 2016/679',
            defaults={
                'doc_type': Document.REGULATION,
                'jurisdiction': Document.EU,
                'status': Document.INDEXED,
                'full_name': 'General Data Protection Regulation',
                'issuing_authority': 'European Parliament',
                'version': '2016/679',
                'chunk_count': 214,
                'token_count': 98400,
            }
        )
        pol_doc, _ = Document.objects.get_or_create(
            name='BBK Data Protection & Privacy Policy',
            defaults={
                'doc_type': Document.POLICY,
                'jurisdiction': Document.BBK,
                'status': Document.INDEXED,
                'full_name': 'Bank of Bahrain and Kuwait — Data Protection & Privacy Policy v3.1',
                'issuing_authority': 'BBK Compliance',
                'version': '3.1',
                'chunk_count': 42,
                'token_count': 18700,
            }
        )

        # ── MappingAnalysis ────────────────────────────────────────────────
        analysis, _ = MappingAnalysis.objects.get_or_create(
            policy_doc=pol_doc,
            topic='GDPR compliance gap analysis',
            defaults={
                'status': MappingAnalysis.REVIEW,
                'obligation_count': len(OBLIGATIONS),
                'gap_count': sum(1 for _, _, cov, *_ in OBLIGATIONS if cov in (ObligationMapping.NONE, ObligationMapping.PARTIAL)),
                'created_by': user_a,
            }
        )
        analysis.regulations.add(reg_doc)

        # ── ObligationMappings + Gaps + ReviewItems ────────────────────────
        now = timezone.now()
        om_list = []
        for article_ref, title, coverage, confidence, evidence, gap_priority in OBLIGATIONS:
            om, _ = ObligationMapping.objects.get_or_create(
                analysis=analysis,
                article_ref=article_ref,
                defaults={
                    'obligation_title': title,
                    'regulation': reg_doc,
                    'coverage': coverage,
                    'evidence_text': evidence,
                    'evidence_source': 'BBK Data Protection & Privacy Policy v3.1',
                    'confidence_pct': confidence,
                }
            )
            om_list.append(om)

            if gap_priority and not Gap.objects.filter(obligation_mapping=om).exists():
                Gap.objects.create(
                    mapping=analysis,
                    obligation_mapping=om,
                    priority=gap_priority,
                    remediation_source=Gap.AI,
                    remediation_text=(
                        f'AI recommendation: Address the missing coverage for {title}. '
                        'Review policy documentation and update or supplement with explicit procedures.'
                    ),
                )

            if not om.review_items.exists():
                ReviewItem.objects.create(
                    mapping=analysis,
                    obligation_mapping=om,
                    status=ReviewItem.PENDING,
                )

        # ── Apply review decisions (simulate history) ──────────────────────
        for om_idx, status, rev_idx, note, days_ago in REVIEW_DECISIONS:
            om = om_list[om_idx]
            ri = om.review_items.first()
            if ri and ri.status == ReviewItem.PENDING:
                reviewer = reviewers[rev_idx]
                reviewed_at = now - timedelta(days=days_ago)
                ri.status = status
                ri.reviewer = reviewer
                ri.reviewed_at = reviewed_at
                ri.reviewer_note = note
                ri.save()

                AuditLog.objects.create(
                    event_type=f'review_{status}',
                    user=reviewer,
                    timestamp=reviewed_at,
                    description=f'{reviewer.get_full_name() or reviewer.username} marked "{om.article_ref}" as {status}.',
                    related_object_type='ReviewItem',
                    related_object_id=ri.pk,
                    change_detail={
                        'article_ref': om.article_ref,
                        'status': status,
                        'note': note,
                        'reviewer': reviewer.username,
                    },
                )

        # ── Summary ────────────────────────────────────────────────────────
        total_ri = ReviewItem.objects.filter(mapping=analysis).count()
        reviewed  = ReviewItem.objects.filter(mapping=analysis).exclude(status=ReviewItem.PENDING).count()
        self.stdout.write(self.style.SUCCESS(
            f'\nSample data seeded successfully!\n'
            f'  Analysis : "{analysis}" (pk={analysis.pk})\n'
            f'  Reviewer A: {user_a.username}\n'
            f'  Reviewer B: {user_b.username}\n'
            f'  Review items : {total_ri} total, {reviewed} reviewed, {total_ri - reviewed} pending\n'
            f'  Audit log entries created: {len(REVIEW_DECISIONS)}\n'
            f'\nOpen the Review page to test it.'
        ))
