"""Executive-summary PDF + gap-register XLSX builders.

Phase 2 of the review pipeline: when a mapping or comparison run gets
approved by a reviewer, the system produces two artifacts that travel
through the organisation:

  build_executive_summary_pdf(obj) -> bytes
      One-page PDF suitable for forwarding to a CCO / board pack. Includes:
      policy/regulations, compliance score (mappings) or summary stats
      (comparisons), top-N gaps with severity, reviewer name + approval
      date, and a SHA-256 audit hash so a recipient can verify the file
      hasn't been altered after signing.

  build_gap_register_xlsx(obj) -> bytes
      Flat .xlsx the DPO drops into the GRC tracker. One row per gap with
      regulation citation, gap description, AI-suggested remediation,
      severity, and computed suggested due date (Critical=2w, High=1mo,
      Medium=3mo, Low=6mo). Status/Owner/Notes columns are intentionally
      blank for the DPO to fill in their tracker.

Both builders accept either a MappingAnalysis or ComparisonRun and pick
the right rendering by polymorphism on the object's class. Returning bytes
(not Response) keeps these reusable from views, the management command, and
any future auto-email pipeline.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from io import BytesIO


# Severity → suggested remediation deadline. Calibrated to BBK's working
# expectations: criticals need a board-level response within 2 weeks; lows
# get a 6-month horizon (annual review cycle).
_SEVERITY_TO_DAYS = {
    'critical': 14,
    'high':     30,
    'medium':   90,
    'low':      180,
}

_COVERAGE_LABEL = {
    'covered': 'Fully Covered',
    'partial': 'Partially Covered',
    'review':  'Requires Review',
    'none':    'Not Covered',
}

_REL_LABEL = {
    'equivalent':      'Equivalent',
    'stricter_in_a':   'Stricter in A',
    'stricter_in_b':   'Stricter in B',
    'additional_in_a': 'Additional in A',
    'additional_in_b': 'Additional in B',
    'conflicting':     'Conflicting',
}


# ── PUBLIC API ───────────────────────────────────────────────────────────────


def build_executive_summary_pdf(obj) -> bytes:
    """Return a one-page PDF executive summary as raw bytes."""
    from apps.mapping.models import MappingAnalysis
    if isinstance(obj, MappingAnalysis):
        return _mapping_executive_pdf(obj)
    # Otherwise assume ComparisonRun
    return _comparison_executive_pdf(obj)


def build_gap_register_xlsx(obj) -> bytes:
    """Return a Gap Register .xlsx as raw bytes."""
    from apps.mapping.models import MappingAnalysis
    if isinstance(obj, MappingAnalysis):
        return _mapping_gap_register_xlsx(obj)
    return _comparison_gap_register_xlsx(obj)


def _resolve_due_date(obligation_mapping, gap=None) -> tuple[str, bool]:
    """Return (formatted_date, is_reviewer_set).

    Priority:
      1. Reviewer-set explicit `gap.due_date` (DateField on Gap).
      2. Severity-derived default — today + days(severity).

    `is_reviewer_set` flips True so the exporter can flag the row as
    reviewer-confirmed in the PDF / Excel (vs an auto-computed default
    that the DPO still has authority to adjust).
    """
    if gap is None:
        try:
            from apps.mapping.models import Gap as _G
            gap = _G.objects.filter(obligation_mapping=obligation_mapping).first()
        except Exception:
            gap = None
    if gap is not None and getattr(gap, 'due_date', None):
        return (gap.due_date.strftime('%d %b %Y'), True)
    sev = (obligation_mapping.severity or 'low').lower()
    days = _SEVERITY_TO_DAYS.get(sev, 180)
    return ((datetime.utcnow() + timedelta(days=days)).strftime('%d %b %Y'), False)


def audit_hash(obj) -> str:
    """SHA-256 of the row's identity + decision metadata. Recipients can verify
    the artifact references the same row by re-running this. Not a digital
    signature — it just makes silent post-hoc edits visible."""
    from apps.mapping.models import MappingAnalysis
    payload_parts = [
        obj.__class__.__name__,
        str(obj.pk),
        obj.status if isinstance(obj, MappingAnalysis) else (obj.status or ''),
        str(getattr(obj, 'completed_at', '') or ''),
        str(getattr(obj, 'submitted_for_review_at', '') or ''),
        str(getattr(obj, 'created_by_id', '') or ''),
    ]
    h = hashlib.sha256('|'.join(payload_parts).encode('utf-8')).hexdigest()
    return h[:16]


# ── MAPPING PDF ──────────────────────────────────────────────────────────────


def _mapping_executive_pdf(a) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
    )

    from apps.mapping.models import ObligationMapping
    mappings = list(a.obligation_mappings.select_related('regulation'))
    counts = {
        'covered': sum(1 for m in mappings if m.coverage == ObligationMapping.COVERED),
        'partial': sum(1 for m in mappings if m.coverage == ObligationMapping.PARTIAL),
        'review':  sum(1 for m in mappings if m.coverage == ObligationMapping.REVIEW),
        'none':    sum(1 for m in mappings if m.coverage == ObligationMapping.NONE),
    }
    total = sum(counts.values())
    compliance_score = (
        round((counts['covered'] + 0.5 * counts['partial']) / total * 100)
        if total else 0
    )

    # Top gaps: not Covered. Reviewer-edited rows ALWAYS surface first —
    # if a reviewer demoted a row to Low and set a due date, that's a deliberate
    # decision the executive needs to see, not a row to bury under untouched
    # Criticals. After that, sort by severity (Critical → … → Low) then
    # confidence DESC so the most-defensible gaps surface within each tier.
    severity_rank = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, None: 4, '': 4}
    gaps = [m for m in mappings if m.coverage != ObligationMapping.COVERED]
    # Pre-fetch Gap rows once so we can detect reviewer-set due dates / text
    # without N+1 hits per sort comparison.
    try:
        from apps.mapping.models import Gap as _G
        _gap_by_om = {
            g.obligation_mapping_id: g
            for g in _G.objects.filter(obligation_mapping__in=gaps)
        }
    except Exception:
        _gap_by_om = {}

    def _reviewer_signal(m) -> int:
        """Stratify rows by strength of reviewer involvement.

        0 = strong: reviewer set an explicit due_date or wrote/edited remediation.
        1 = medium: human_override flag (severity touched) but no Gap edits.
        2 = none.

        We don't lump everything with human_override into one bucket because an
        early backfill set the flag on a lot of pre-existing rows — leaning on
        concrete Gap fields keeps the PDF honest about which rows the reviewer
        truly weighed in on.
        """
        g = _gap_by_om.get(m.pk)
        if g is not None:
            if getattr(g, 'due_date', None):
                return 0
            if (getattr(g, 'remediation_source', '') or '') in ('human_written', 'ai_draft_edited'):
                return 0
        if getattr(m, 'human_override', False):
            return 1
        return 2

    gaps.sort(key=lambda m: (
        _reviewer_signal(m),
        severity_rank.get(m.severity, 4),
        -m.confidence,
    ))
    top_gaps = gaps[:3]

    navy   = colors.HexColor('#002583')
    amber  = colors.HexColor('#B07A00')
    green  = colors.HexColor('#1B7F3A')
    red    = colors.HexColor('#D93939')
    text   = colors.HexColor('#1F2937')
    muted  = colors.HexColor('#6B7280')
    line   = colors.HexColor('#E5E8EF')
    soft   = colors.HexColor('#F7F9FC')

    def score_color(s):
        if s >= 70: return green
        if s >= 40: return amber
        return red

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16*mm, rightMargin=16*mm,
        topMargin=14*mm, bottomMargin=14*mm,
        title=f'Executive summary — {a.policy_doc.name}',
        author='CJPCA',
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Title'], textColor=navy, fontSize=16,
                        leading=20, spaceAfter=2, fontName='Helvetica-Bold')
    h2 = ParagraphStyle('h2', parent=styles['Heading2'], textColor=navy, fontSize=10,
                        leading=12, spaceAfter=3, spaceBefore=8, fontName='Helvetica-Bold')
    label = ParagraphStyle('lbl', parent=styles['Normal'], textColor=muted, fontSize=7.5,
                           leading=9, fontName='Helvetica-Bold')
    body = ParagraphStyle('body', parent=styles['Normal'], textColor=text, fontSize=9,
                          leading=12)
    small = ParagraphStyle('small', parent=styles['Normal'], textColor=muted, fontSize=7.5,
                           leading=9)

    story = []
    # Header band
    story.append(Paragraph('BBK · COMPLIANCE MAPPING REVIEW', label))
    story.append(Paragraph(f'<b>{a.policy_doc.name}</b>', h1))
    reg_names = ', '.join(r.name for r in a.regulations.all()) or '—'
    story.append(Paragraph(f'Mapped against: {reg_names}', body))
    story.append(Spacer(1, 6*mm))

    # Score band — big number with traffic-light fill
    score_color_val = score_color(compliance_score)
    score_cell = Paragraph(
        f'<font size="34" color="{score_color_val.hexval()}"><b>{compliance_score}%</b></font>'
        f'<br/><font size="7" color="{muted.hexval()}">COMPLIANCE SCORE</font>',
        ParagraphStyle('sc', parent=styles['Normal'], alignment=1, leading=36),
    )
    breakdown_cell = Paragraph(
        f'<font size="9" color="{green.hexval()}"><b>{counts["covered"]}</b></font> Covered &nbsp;·&nbsp; '
        f'<font size="9" color="{amber.hexval()}"><b>{counts["partial"]}</b></font> Partial &nbsp;·&nbsp; '
        f'<font size="9" color="{navy.hexval()}"><b>{counts["review"]}</b></font> Review &nbsp;·&nbsp; '
        f'<font size="9" color="{red.hexval()}"><b>{counts["none"]}</b></font> Not covered'
        f'<br/><br/><font size="8" color="{muted.hexval()}">Weighting: Covered = 100%, Partial = 50%, Review / Not covered = 0%. '
        f'Based on {total} obligation{"s" if total != 1 else ""} extracted by the AI mapper and '
        f'reviewed for citation grounding.</font>',
        body,
    )
    band = Table([[score_cell, breakdown_cell]], colWidths=[45*mm, None])
    band.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (0, 0), soft),
        ('BOX',           (0, 0), (-1, -1), 0.5, line),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(band)
    story.append(Spacer(1, 6*mm))

    # Top gaps
    story.append(Paragraph('Top gaps requiring action', h2))
    if not top_gaps:
        story.append(Paragraph(
            'No outstanding gaps. Every regulatory obligation in scope was fully covered by the policy.',
            body,
        ))
    else:
        rows = [['#', 'Regulation', 'Obligation', 'Severity', 'Due*']]
        for i, m in enumerate(top_gaps, 1):
            due, reviewer_set = _resolve_due_date(m)
            # Flag reviewer-set values so the executive sees which numbers
            # are the reviewer's explicit decisions vs auto-computed defaults.
            sev_marker = ' (reviewer-set)' if m.human_override else ''
            due_marker = f'<br/><font size="6" color="{green.hexval()}"><b>reviewer-set</b></font>' if reviewer_set else ''
            rows.append([
                str(i),
                Paragraph(f'<b>{_html_escape(m.regulation.name)}</b><br/>'
                          f'<font size="7" color="{muted.hexval()}">{_html_escape(m.article_ref or "")}</font>',
                          small),
                Paragraph(_html_escape(m.obligation_title or m.obligation_text[:200]), small),
                Paragraph(f'<b>{(m.severity or "—").title()}</b>{sev_marker}', small),
                Paragraph(f'{due}{due_marker}', small),
            ])
        tbl = Table(rows, colWidths=[8*mm, 38*mm, None, 22*mm, 26*mm], repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0),   navy),
            ('TEXTCOLOR',      (0, 0), (-1, 0),   colors.white),
            ('FONTNAME',       (0, 0), (-1, 0),   'Helvetica-Bold'),
            ('FONTSIZE',       (0, 0), (-1, 0),   8),
            ('BOTTOMPADDING',  (0, 0), (-1, 0),   5),
            ('TOPPADDING',     (0, 0), (-1, 0),   5),
            ('GRID',           (0, 0), (-1, -1),  0.25, line),
            ('VALIGN',         (0, 0), (-1, -1),  'TOP'),
            ('TOPPADDING',     (0, 1), (-1, -1),  4),
            ('BOTTOMPADDING',  (0, 1), (-1, -1),  4),
            ('LEFTPADDING',    (0, 0), (-1, -1),  5),
            ('RIGHTPADDING',   (0, 0), (-1, -1),  5),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 2*mm))
        story.append(Paragraph(
            '<b>*</b> <i>Severity</i> defaults to the AI grade (coverage + confidence). '
            '<i>Due</i> defaults to today + Critical=2w / High=1mo / Medium=3mo / Low=6mo. '
            'Rows marked "<b>reviewer-set</b>" carry the reviewer\'s explicit decision and '
            'override the AI default — these are the values the DPO should treat as authoritative. '
            'Reviewer-touched rows are surfaced first regardless of severity so deliberate '
            'human decisions are never buried under untouched AI grades.',
            small,
        ))

    story.append(Spacer(1, 6*mm))

    # Sign-off + audit hash
    reviewer = getattr(a.submitted_by, 'get_full_name', lambda: '')() or getattr(a.submitted_by, 'username', '—') or '—'
    submitted_at = a.submitted_for_review_at.strftime('%d %b %Y, %H:%M') if a.submitted_for_review_at else '—'
    completed_at = a.completed_at.strftime('%d %b %Y, %H:%M') if a.completed_at else '—'
    sig_rows = [
        ['Status',                a.get_status_display()],
        ['Analysis completed',    completed_at],
        ['Submitted for review',  submitted_at],
        ['Submitted by',          reviewer],
        ['Obligations evaluated', str(total)],
        ['Audit hash',            audit_hash(a)],
        ['Generated at',          datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')],
    ]
    sig = Table(sig_rows, colWidths=[42*mm, None])
    sig.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), soft),
        ('FONTNAME',   (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',  (0, 0), (-1, -1), text),
        ('TEXTCOLOR',  (0, 0), (0, -1),  muted),
        ('GRID',       (0, 0), (-1, -1), 0.25, line),
        ('LEFTPADDING',(0, 0), (-1, -1), 6),
        ('RIGHTPADDING',(0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(KeepTogether([Paragraph('Sign-off &amp; audit', h2), sig]))

    # Disclaimer
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'This document is AI-assisted analysis verified by a human reviewer. '
        'It supports — but does not replace — qualified legal review of the underlying regulations.',
        small,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ── COMPARISON PDF ───────────────────────────────────────────────────────────


def _comparison_executive_pdf(run) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
    )

    from apps.comparison.models import ComparisonResult
    results = list(run.results.all())
    counts = {
        'equivalent':      sum(1 for r in results if r.relationship == ComparisonResult.EQUIVALENT),
        'stricter_a':      sum(1 for r in results if r.relationship == ComparisonResult.STRICTER_IN_A),
        'stricter_b':      sum(1 for r in results if r.relationship == ComparisonResult.STRICTER_IN_B),
        'additional':      sum(1 for r in results if r.relationship in (ComparisonResult.ADDITIONAL_IN_A, ComparisonResult.ADDITIONAL_IN_B)),
        'conflicting':     sum(1 for r in results if r.relationship == ComparisonResult.CONFLICTING),
    }
    total = len(results)
    alignment_score = (
        round(counts['equivalent'] / total * 100) if total else 0
    )

    # Top conflicts / non-equivalent rows, sorted by confidence DESC
    flagged = [r for r in results
               if r.relationship in (ComparisonResult.CONFLICTING, ComparisonResult.STRICTER_IN_A, ComparisonResult.STRICTER_IN_B)]
    flagged.sort(key=lambda r: -r.confidence)
    top_rows = flagged[:3]

    navy  = colors.HexColor('#002583')
    amber = colors.HexColor('#B07A00')
    green = colors.HexColor('#1B7F3A')
    red   = colors.HexColor('#D93939')
    text  = colors.HexColor('#1F2937')
    muted = colors.HexColor('#6B7280')
    line  = colors.HexColor('#E5E8EF')
    soft  = colors.HexColor('#F7F9FC')

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16*mm, rightMargin=16*mm,
        topMargin=14*mm, bottomMargin=14*mm,
        title=f'Executive summary — {run.reg_a.name} vs {run.reg_b.name}',
        author='CJPCA',
    )
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle('h1', parent=styles['Title'], textColor=navy, fontSize=16,
                        leading=20, spaceAfter=2, fontName='Helvetica-Bold')
    h2 = ParagraphStyle('h2', parent=styles['Heading2'], textColor=navy, fontSize=10,
                        leading=12, spaceAfter=3, spaceBefore=8, fontName='Helvetica-Bold')
    label = ParagraphStyle('lbl', parent=styles['Normal'], textColor=muted, fontSize=7.5,
                           leading=9, fontName='Helvetica-Bold')
    body = ParagraphStyle('body', parent=styles['Normal'], textColor=text, fontSize=9,
                          leading=12)
    small = ParagraphStyle('small', parent=styles['Normal'], textColor=muted, fontSize=7.5,
                           leading=9)

    story = []
    story.append(Paragraph('BBK · REGULATION COMPARISON REVIEW', label))
    story.append(Paragraph(f'<b>{run.reg_a.name} ↔ {run.reg_b.name}</b>', h1))
    if run.topics:
        story.append(Paragraph(f'Scope: {run.topics_display}', body))
    story.append(Spacer(1, 6*mm))

    score_cell = Paragraph(
        f'<font size="34" color="{(green if alignment_score >= 60 else amber if alignment_score >= 30 else red).hexval()}"><b>{alignment_score}%</b></font>'
        f'<br/><font size="7" color="{muted.hexval()}">ALIGNMENT</font>',
        ParagraphStyle('sc', parent=styles['Normal'], alignment=1, leading=36),
    )
    breakdown_cell = Paragraph(
        f'<font size="9" color="{green.hexval()}"><b>{counts["equivalent"]}</b></font> Equivalent &nbsp;·&nbsp; '
        f'<font size="9" color="{amber.hexval()}"><b>{counts["stricter_a"] + counts["stricter_b"]}</b></font> Stricter-side &nbsp;·&nbsp; '
        f'<font size="9" color="{navy.hexval()}"><b>{counts["additional"]}</b></font> Additional &nbsp;·&nbsp; '
        f'<font size="9" color="{red.hexval()}"><b>{counts["conflicting"]}</b></font> Conflicting'
        f'<br/><br/><font size="8" color="{muted.hexval()}">Alignment = % of obligations rated Equivalent. '
        f'Based on {total} obligation pair{"s" if total != 1 else ""} extracted by the AI comparator and '
        f'reviewed for citation grounding.</font>',
        body,
    )
    band = Table([[score_cell, breakdown_cell]], colWidths=[45*mm, None])
    band.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (0, 0), soft),
        ('BOX',           (0, 0), (-1, -1), 0.5, line),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',   (0, 0), (-1, -1), 10),
        ('RIGHTPADDING',  (0, 0), (-1, -1), 10),
        ('TOPPADDING',    (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
    ]))
    story.append(band)
    story.append(Spacer(1, 6*mm))

    story.append(Paragraph('Rows requiring attention', h2))
    if not top_rows:
        story.append(Paragraph(
            'No conflicts or one-sided-stricter rows identified. The two regulations '
            'are substantively aligned across the obligations evaluated.',
            body,
        ))
    else:
        rows = [['#', 'Reg A clause', 'Reg B clause', 'Verdict']]
        for i, r in enumerate(top_rows, 1):
            rows.append([
                str(i),
                Paragraph(f'<b>{_html_escape(r.citation_a)}</b><br/>'
                          f'<font size="7" color="{muted.hexval()}">{_html_escape((r.preview_a or "")[:120])}</font>',
                          small),
                Paragraph(f'<b>{_html_escape(r.citation_b or "—")}</b><br/>'
                          f'<font size="7" color="{muted.hexval()}">{_html_escape((r.preview_b or "")[:120])}</font>',
                          small),
                Paragraph(f'<b>{_REL_LABEL.get(r.relationship, r.relationship)}</b>', small),
            ])
        tbl = Table(rows, colWidths=[8*mm, None, None, 28*mm], repeatRows=1)
        tbl.setStyle(TableStyle([
            ('BACKGROUND',     (0, 0), (-1, 0),   navy),
            ('TEXTCOLOR',      (0, 0), (-1, 0),   colors.white),
            ('FONTNAME',       (0, 0), (-1, 0),   'Helvetica-Bold'),
            ('FONTSIZE',       (0, 0), (-1, 0),   8),
            ('BOTTOMPADDING',  (0, 0), (-1, 0),   5),
            ('TOPPADDING',     (0, 0), (-1, 0),   5),
            ('GRID',           (0, 0), (-1, -1),  0.25, line),
            ('VALIGN',         (0, 0), (-1, -1),  'TOP'),
            ('TOPPADDING',     (0, 1), (-1, -1),  4),
            ('BOTTOMPADDING',  (0, 1), (-1, -1),  4),
        ]))
        story.append(tbl)

    story.append(Spacer(1, 6*mm))
    reviewer = getattr(run.submitted_by, 'get_full_name', lambda: '')() or getattr(run.submitted_by, 'username', '—') or '—'
    submitted_at = run.submitted_for_review_at.strftime('%d %b %Y, %H:%M') if run.submitted_for_review_at else '—'
    sig_rows = [
        ['Status',                run.get_status_display() if hasattr(run, 'get_status_display') else run.status],
        ['Pair',                  run.pair_label],
        ['Submitted for review',  submitted_at],
        ['Submitted by',          reviewer],
        ['Pairs evaluated',       str(total)],
        ['Audit hash',            audit_hash(run)],
        ['Generated at',          datetime.utcnow().strftime('%d %b %Y, %H:%M UTC')],
    ]
    sig = Table(sig_rows, colWidths=[42*mm, None])
    sig.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), soft),
        ('FONTNAME',   (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE',   (0, 0), (-1, -1), 8),
        ('TEXTCOLOR',  (0, 0), (-1, -1), text),
        ('TEXTCOLOR',  (0, 0), (0, -1),  muted),
        ('GRID',       (0, 0), (-1, -1), 0.25, line),
        ('LEFTPADDING',(0, 0), (-1, -1), 6),
        ('RIGHTPADDING',(0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING',(0, 0), (-1, -1), 4),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(KeepTogether([Paragraph('Sign-off &amp; audit', h2), sig]))

    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        'This document is AI-assisted analysis verified by a human reviewer. '
        'It supports — but does not replace — qualified legal review of the underlying regulations.',
        small,
    ))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ── MAPPING GAP REGISTER XLSX ────────────────────────────────────────────────


def _mapping_gap_register_xlsx(a) -> bytes:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from apps.mapping.models import ObligationMapping

    gaps = list(
        a.obligation_mappings
         .exclude(coverage=ObligationMapping.COVERED)
         .select_related('regulation')
         .order_by('-severity', 'article_ref')
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Gap Register'

    navy   = '002583'
    light  = 'F7F9FC'
    text   = '1F2937'
    muted  = '6B7280'
    line_c = 'E5E8EF'

    thin = Border(
        left=Side(style='thin', color=line_c),
        right=Side(style='thin', color=line_c),
        top=Side(style='thin', color=line_c),
        bottom=Side(style='thin', color=line_c),
    )

    # Top meta block
    ws['A1'] = f'Gap Register — {a.policy_doc.name}'
    ws['A1'].font = Font(bold=True, size=14, color=navy)
    ws.merge_cells('A1:I1')
    reg_names = ', '.join(r.name for r in a.regulations.all()) or '—'
    ws['A2'] = f'Regulations mapped: {reg_names}'
    ws['A2'].font = Font(size=9, color=muted)
    ws.merge_cells('A2:I2')
    ws['A3'] = (f'Generated {datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")}'
                f' · Status: {a.get_status_display()}'
                f' · Audit hash: {audit_hash(a)}')
    ws['A3'].font = Font(size=9, color=muted, italic=True)
    ws.merge_cells('A3:I3')
    ws['A4'] = (
        'Severity is derived from coverage + AI confidence. Suggested remediation is the '
        'AI gap-fix proposal. Suggested due date is computed from severity (Critical=2w, '
        'High=1mo, Medium=3mo, Low=6mo). All three are AI-suggested defaults — DPO to '
        'confirm or adjust before scheduling work. Status / Owner / Notes are blank for the DPO.'
    )
    ws['A4'].font = Font(size=8, color=muted, italic=True)
    ws['A4'].alignment = Alignment(wrap_text=True, vertical='top')
    ws.merge_cells('A4:I4')
    ws.row_dimensions[4].height = 32
    ws.row_dimensions[5].height = 6

    headers = [
        'Regulation', 'Article', 'Gap description', 'AI-graded severity',
        'AI-suggested remediation', 'Suggested due date',
        'Status', 'Owner', 'Notes',
    ]
    header_row = 6
    hfill = PatternFill(start_color=navy, end_color=navy, fill_type='solid')
    hfont = Font(bold=True, color='FFFFFF', size=10)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col, value=h)
        cell.font = hfont
        cell.fill = hfill
        cell.alignment = center
        cell.border = thin

    altfill = PatternFill(start_color=light, end_color=light, fill_type='solid')
    body_font = Font(size=10, color=text)
    body_align = Alignment(vertical='top', wrap_text=True)

    for r_idx, m in enumerate(gaps, header_row + 1):
        # Pull the gap row (if any) once — gives us reviewer-edited
        # remediation text and the explicit due_date the reviewer may have set.
        try:
            from apps.mapping.models import Gap as _G
            g = _G.objects.filter(obligation_mapping=m).first()
        except Exception:
            g = None

        gap_desc    = (m.rationale or m.obligation_title or m.obligation_text)[:600]
        remediation = (g.remediation_text if g else '')[:600]
        # Due date — reviewer's explicit setting wins; otherwise compute from severity.
        if g is not None and getattr(g, 'due_date', None):
            due       = g.due_date.strftime('%Y-%m-%d')
            due_note  = '(reviewer-set)'
        else:
            sev = (m.severity or 'low').lower()
            due_days = _SEVERITY_TO_DAYS.get(sev, 180)
            due      = (datetime.utcnow() + timedelta(days=due_days)).strftime('%Y-%m-%d')
            due_note = '(auto from severity)'

        sev_label = (m.severity or '—').title()
        if m.human_override:
            sev_label += ' (reviewer-set)'

        rem_source = (g.remediation_source if g else '') or ''
        rem_label  = remediation
        if rem_source == 'human_written' and remediation:
            rem_label = f'{remediation}\n\n[Reviewer-written]'
        elif rem_source == 'ai_draft_edited' and remediation:
            rem_label = f'{remediation}\n\n[AI suggestion, reviewer-edited]'

        row_data = [
            m.regulation.name if m.regulation else '—',
            m.article_ref or '—',
            gap_desc,
            sev_label,
            rem_label,
            f'{due}\n{due_note}',
            '',  # Status — for DPO
            '',  # Owner  — for DPO
            '',  # Notes  — for DPO
        ]
        fill = altfill if r_idx % 2 == 0 else None
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=r_idx, column=col, value=str(val))
            cell.font = body_font
            cell.alignment = body_align
            cell.border = thin
            if fill:
                cell.fill = fill

    # Empty state
    if not gaps:
        ws.cell(row=header_row + 1, column=1, value='No outstanding gaps — every regulatory obligation in scope was fully covered.')
        ws.merge_cells(start_row=header_row + 1, start_column=1,
                       end_row=header_row + 1, end_column=9)
        ws.cell(row=header_row + 1, column=1).font = Font(italic=True, color=muted, size=10)

    widths = [28, 16, 60, 12, 60, 18, 14, 22, 36]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = f'A{header_row + 1}'

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── COMPARISON GAP REGISTER XLSX ─────────────────────────────────────────────


def _comparison_gap_register_xlsx(run) -> bytes:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from apps.comparison.models import ComparisonResult

    flagged = list(
        run.results
           .filter(relationship__in=[
               ComparisonResult.CONFLICTING,
               ComparisonResult.STRICTER_IN_A,
               ComparisonResult.STRICTER_IN_B,
               ComparisonResult.ADDITIONAL_IN_A,
               ComparisonResult.ADDITIONAL_IN_B,
           ])
           .order_by('relationship', 'citation_a')
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Comparison Register'

    navy   = '002583'
    light  = 'F7F9FC'
    text   = '1F2937'
    muted  = '6B7280'
    line_c = 'E5E8EF'

    thin = Border(
        left=Side(style='thin', color=line_c),
        right=Side(style='thin', color=line_c),
        top=Side(style='thin', color=line_c),
        bottom=Side(style='thin', color=line_c),
    )

    ws['A1'] = f'Comparison Register — {run.reg_a.name} vs {run.reg_b.name}'
    ws['A1'].font = Font(bold=True, size=14, color=navy)
    ws.merge_cells('A1:H1')
    if run.topics:
        ws['A2'] = f'Scope: {run.topics_display}'
        ws['A2'].font = Font(size=9, color=muted)
        ws.merge_cells('A2:H2')
    ws['A3'] = (f'Generated {datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")}'
                f' · Pairs flagged: {len(flagged)} of {run.results.count()}'
                f' · Audit hash: {audit_hash(run)}')
    ws['A3'].font = Font(size=9, color=muted, italic=True)
    ws.merge_cells('A3:H3')
    ws.row_dimensions[4].height = 6

    headers = [
        'Verdict', 'Reg A citation', 'Reg A excerpt',
        'Reg B citation', 'Reg B excerpt', 'Key difference',
        'AI confidence %', 'Reviewer note',
    ]
    header_row = 5
    hfill = PatternFill(start_color=navy, end_color=navy, fill_type='solid')
    hfont = Font(bold=True, color='FFFFFF', size=10)
    center = Alignment(horizontal='center', vertical='center', wrap_text=True)
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=header_row, column=col, value=h)
        cell.font = hfont
        cell.fill = hfill
        cell.alignment = center
        cell.border = thin

    altfill = PatternFill(start_color=light, end_color=light, fill_type='solid')
    body_font = Font(size=10, color=text)
    body_align = Alignment(vertical='top', wrap_text=True)

    for r_idx, r in enumerate(flagged, header_row + 1):
        row_data = [
            _REL_LABEL.get(r.relationship, r.relationship),
            r.citation_a or '—',
            (r.preview_a or r.clause_text_a or '')[:600],
            r.citation_b or '—',
            (r.preview_b or r.clause_text_b or '')[:600],
            (r.key_difference or r.rationale or '')[:600],
            r.confidence_pct,
            r.reviewer_note or '',
        ]
        fill = altfill if r_idx % 2 == 0 else None
        for col, val in enumerate(row_data, 1):
            cell = ws.cell(row=r_idx, column=col, value=val)
            cell.font = body_font
            cell.alignment = body_align
            cell.border = thin
            if fill:
                cell.fill = fill

    if not flagged:
        ws.cell(row=header_row + 1, column=1,
                value='No conflicting / stricter / additional rows. Regulations are substantively aligned.')
        ws.merge_cells(start_row=header_row + 1, start_column=1,
                       end_row=header_row + 1, end_column=8)
        ws.cell(row=header_row + 1, column=1).font = Font(italic=True, color=muted, size=10)

    widths = [18, 24, 60, 24, 60, 50, 12, 36]
    for col, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = f'A{header_row + 1}'

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── helpers ──────────────────────────────────────────────────────────────────


def _html_escape(s: str) -> str:
    """ReportLab Paragraph reads HTML-ish markup, so user-supplied text needs
    its angle-brackets + ampersands escaped or the build crashes."""
    if s is None:
        return ''
    return (str(s)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('\n', '<br/>'))
