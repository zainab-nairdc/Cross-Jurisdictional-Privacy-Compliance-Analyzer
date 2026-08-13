import datetime
from io import BytesIO

from django.db.models import Count
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.decorators import method_decorator
from django.views import View

from apps.accounts.decorators import role_required
from apps.history.audit import Actions, log_event
from apps.comparison.models import (
    AuditEvent, ComparisonResult, ComparisonRun,
    PAIR_CONFIGS, REL_COLORS, REL_BG, REL_LABELS,
)
from apps.mapping.models import ObligationMapping

REVIEW_ROLES = ('reviewer',)


LIFECYCLE_META = {
    'draft':    {'label': 'Pending',  'color': '#FFB800', 'bg': '#E5E8EF'},
    'reviewed': {'label': 'Reviewed', 'color': '#002583', 'bg': '#E5E8EF'},
    'approved': {'label': 'Approved', 'color': '#002583', 'bg': '#E5E8EF'},
    'rejected': {'label': 'Rejected', 'color': '#002583', 'bg': '#E5E8EF'},
}

# Relationship colors restricted to navy / orange / yellow only
REL_COLOR_REVIEW = {
    'equivalent':      '#002583',
    'stricter_in_a':   '#FFB800',
    'stricter_in_b':   '#FFB800',
    'additional_in_a': '#002583',
    'additional_in_b': '#002583',
    'conflicting':     '#FFB800',
}
REL_BG_REVIEW = {
    'equivalent':      '#E5E8EF',
    'stricter_in_a':   '#E5E8EF',
    'stricter_in_b':   '#E5E8EF',
    'additional_in_a': '#E5E8EF',
    'additional_in_b': '#E5E8EF',
    'conflicting':     '#E5E8EF',
}

STEPPER = [
    {'n': 1, 'label': 'Generated'},
    {'n': 2, 'label': 'Under review'},
    {'n': 3, 'label': 'Approved'},
    {'n': 4, 'label': 'Exported'},
]


def _enrich(results):
    for r in results:
        r.status_meta  = LIFECYCLE_META.get(r.lifecycle, LIFECYCLE_META['draft'])
        r.rv_rel_color = REL_COLOR_REVIEW.get(r.relationship, '#FFB800')
        r.rv_rel_bg    = REL_BG_REVIEW.get(r.relationship, '#E5E8EF')
    return results


def _get_stats():
    counts = {
        row['lifecycle']: row['n']
        for row in ComparisonResult.objects.values('lifecycle').annotate(n=Count('id'))
    }
    return {
        'total':    sum(counts.values()),
        'pending':  counts.get('draft', 0),
        'reviewed': counts.get('reviewed', 0),
        'approved': counts.get('approved', 0),
        'rejected': counts.get('rejected', 0),
    }


def _get_mapping_stats():
    counts = {
        row['lifecycle']: row['n']
        for row in ObligationMapping.objects.values('lifecycle').annotate(n=Count('id'))
    }
    return {
        'total':    sum(counts.values()),
        'pending':  counts.get('draft', 0),
        'approved': counts.get('approved', 0),
        'rejected': counts.get('rejected', 0),
    }


def _build_ctx(lifecycle_filter=''):
    qs = ComparisonResult.objects.select_related(
        'run', 'run__reg_a', 'run__reg_b',
    ).order_by('-run__created_at', 'id')

    if lifecycle_filter:
        qs = qs.filter(lifecycle=lifecycle_filter)

    results = _enrich(list(qs[:200]))
    stats   = _get_stats()

    pending_count = stats['pending']
    all_decided   = stats['total'] > 0 and pending_count == 0

    if all_decided:
        current_step = 3
    elif stats['total'] > 0:
        current_step = 2
    else:
        current_step = 1

    mapping_stats = _get_mapping_stats()
    mapping_qs = ObligationMapping.objects.select_related(
        'analysis', 'analysis__policy_doc', 'regulation',
    ).order_by('-analysis__run_at', 'id')
    if lifecycle_filter:
        mapping_qs = mapping_qs.filter(lifecycle=lifecycle_filter)
    mapping_items = list(mapping_qs[:200])

    # Attach the Gap row (if any) onto each item so the review card can show
    # the editable remediation field next to the AI-graded severity. One
    # bulk lookup keyed by obligation_mapping_id avoids N+1 queries.
    from apps.mapping.models import Gap
    gap_by_om = {
        g.obligation_mapping_id: g
        for g in Gap.objects.filter(
            obligation_mapping_id__in=[m.pk for m in mapping_items],
        )
    }
    for m in mapping_items:
        m.gap_for_review = gap_by_om.get(m.pk)

    return {
        'items':           results,
        'mapping_items':   mapping_items,
        'lifecycle_filter': lifecycle_filter,
        'stats':           stats,
        'mapping_stats':   mapping_stats,
        'all_reviewed':    all_decided,
        'current_step':    current_step,
        'stepper':         STEPPER,
        'filter_tabs': [
            {'val': '',         'label': 'All',      'count': stats['total']},
            {'val': 'draft',    'label': 'Pending',  'count': stats['pending']},
            {'val': 'reviewed', 'label': 'Reviewed', 'count': stats['reviewed']},
            {'val': 'approved', 'label': 'Approved', 'count': stats['approved']},
            {'val': 'rejected', 'label': 'Rejected', 'count': stats['rejected']},
        ],
    }


@method_decorator(role_required(*REVIEW_ROLES), name='dispatch')
class ReviewQueueView(View):
    """GET /review/ — comparison result review queue."""

    def get(self, request):
        lifecycle_filter = request.GET.get('lifecycle', '')
        source = request.GET.get('source', 'comparison')
        ctx = _build_ctx(lifecycle_filter)
        ctx['source'] = source
        if request.headers.get('HX-Request'):
            return render(request, 'partials/_review_queue.html', ctx)
        return render(request, 'pages/review.html', ctx)


@method_decorator(role_required(*REVIEW_ROLES), name='dispatch')
class ReviewItemDetailView(View):
    """GET /review/item/<pk>/ — returns the single review card (used by HTMX filter reload)."""

    def get(self, request, pk):
        result = get_object_or_404(
            ComparisonResult.objects.select_related('run', 'run__reg_a', 'run__reg_b'),
            pk=pk,
        )
        _enrich([result])
        return render(request, 'partials/_review_card.html', {
            'result': result,
            'run':    result.run,
        })


@method_decorator(role_required(*REVIEW_ROLES), name='dispatch')
class ReviewExportView(View):
    """GET /review/export/<format>/ — export approved/reviewed results as pdf/docx/xlsx."""

    def get(self, request, format):
        results = ComparisonResult.objects.select_related(
            'run', 'run__reg_a', 'run__reg_b',
        ).exclude(lifecycle='draft').order_by('run__pair_key', 'id')

        if format == 'pdf':
            response = self._export_pdf(results)
        elif format in ('docx', 'word'):
            response = self._export_docx(results)
        elif format in ('xlsx', 'excel'):
            response = self._export_xlsx(results)
        else:
            return HttpResponseBadRequest('Unknown export format')

        # This bulk export ships every reviewed finding out of the system,
        # so it is at least as audit-relevant as the per-package exports in
        # apps.comparison / apps.mapping — it was the one export path that
        # wrote no audit row at all.
        log_event(
            request.user, Actions.EXPORT_DOWNLOADED,
            request=request,
            target_type='comparison.ComparisonResult',
            description=(f'{request.user.username} exported the full review '
                         f'register as {format}'),
            metadata={'format': format, 'scope': 'review_register',
                      'result_count': results.count()},
        )
        return response

    def _rows(self, results):
        rows = []
        for r in results:
            run = r.run
            rows.append({
                'pair':       run.pair_label if run else '—',
                'citation_a': r.citation_a,
                'citation_b': r.citation_b or '—',
                'rel':        REL_LABELS.get(r.relationship, r.relationship),
                'lifecycle':  r.lifecycle.title(),
                'confidence': f'{r.confidence_pct}%',
                'similarity': f'{r.similarity_pct}%',
                'rationale':  r.rationale or '—',
                'difference': r.key_difference or '—',
                'note':       r.reviewer_note or '—',
            })
        return rows

    def _export_xlsx(self, results):
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Comparison Review'

        navy_hex = '1B3068'
        alt_hex  = 'F3F4F6'
        thin = Border(
            left=Side(style='thin', color='E5E7EB'),
            right=Side(style='thin', color='E5E7EB'),
            top=Side(style='thin', color='E5E7EB'),
            bottom=Side(style='thin', color='E5E7EB'),
        )

        ws['A1'] = 'Regulation Comparison Review'
        ws['A1'].font = Font(bold=True, size=14, color=navy_hex)
        ws['A2'] = f'Exported: {datetime.datetime.now().strftime("%d %B %Y, %H:%M")}'
        ws['A2'].font = Font(size=9, color='9CA3AF')
        ws.row_dimensions[3].height = 6

        headers = ['Pair', 'Citation A', 'Citation B', 'Relationship',
                   'Status', 'Confidence', 'Similarity', 'Reviewer Note', 'AI Rationale']
        col_fields = ['pair', 'citation_a', 'citation_b', 'rel',
                      'lifecycle', 'confidence', 'similarity', 'note', 'rationale']
        header_row = 4

        hfill = PatternFill(start_color=navy_hex, end_color=navy_hex, fill_type='solid')
        hfont = Font(bold=True, color='FFFFFF', size=10)
        center = Alignment(horizontal='center', vertical='center', wrap_text=True)

        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=header_row, column=col, value=h)
            cell.font = hfont
            cell.fill = hfill
            cell.alignment = center
            cell.border = thin

        afill = PatternFill(start_color=alt_hex, end_color=alt_hex, fill_type='solid')
        for r_idx, row_data in enumerate(self._rows(results), header_row + 1):
            fill = afill if r_idx % 2 == 0 else None
            for col, field in enumerate(col_fields, 1):
                cell = ws.cell(row=r_idx, column=col, value=str(row_data[field]))
                cell.font = Font(size=9)
                cell.alignment = Alignment(vertical='top', wrap_text=True)
                cell.border = thin
                if fill:
                    cell.fill = fill

        for col, width in enumerate([20, 32, 32, 18, 11, 11, 11, 28, 42], 1):
            ws.column_dimensions[get_column_letter(col)].width = width

        ws.freeze_panes = 'A5'

        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="comparison-review.xlsx"'
        return response

    def _export_docx(self, results):
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.oxml import parse_xml

        doc = Document()
        doc.styles['Normal'].font.name = 'Calibri'
        doc.styles['Normal'].font.size = Pt(10)

        title = doc.add_heading('Regulation Comparison Review', 0)
        title.runs[0].font.color.rgb = RGBColor(0x1B, 0x30, 0x68)
        doc.add_paragraph(f'Exported: {datetime.datetime.now().strftime("%d %B %Y, %H:%M")}')
        doc.add_paragraph()

        headers    = ['Pair', 'Citation A', 'Citation B', 'Relationship', 'Status', 'Conf.', 'Note']
        col_fields = ['pair', 'citation_a', 'citation_b', 'rel', 'lifecycle', 'confidence', 'note']

        table = doc.add_table(rows=1, cols=len(headers))
        table.style = 'Table Grid'
        hrow = table.rows[0]
        for i, h in enumerate(headers):
            cell = hrow.cells[i]
            cell.text = h
            run = cell.paragraphs[0].runs[0]
            run.bold = True
            run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            run.font.size = Pt(9)
            shading = parse_xml(
                '<w:shd xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
                ' w:val="clear" w:color="auto" w:fill="1B3068"/>'
            )
            cell._tc.get_or_add_tcPr().append(shading)

        for row_data in self._rows(results):
            row = table.add_row()
            for i, field in enumerate(col_fields):
                cell = row.cells[i]
                cell.text = str(row_data[field])
                cell.paragraphs[0].runs[0].font.size = Pt(9)

        for i, w in enumerate([1.2, 2.2, 2.2, 1.4, 0.9, 0.7, 2.0]):
            for cell in table.columns[i].cells:
                cell.width = Inches(w)

        buf = BytesIO()
        doc.save(buf)
        buf.seek(0)
        response = HttpResponse(
            buf.read(),
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        response['Content-Disposition'] = 'attachment; filename="comparison-review.docx"'
        return response

    def _export_pdf(self, results):
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=landscape(A4),
            leftMargin=12*mm, rightMargin=12*mm,
            topMargin=12*mm, bottomMargin=12*mm,
        )
        styles = getSampleStyleSheet()
        navy   = colors.HexColor('#002583')
        grey   = colors.HexColor('#D1D5E0')
        alt    = colors.HexColor('#E5E8EF')
        border = colors.HexColor('#E5E8EF')
        wrap   = ParagraphStyle('w', parent=styles['Normal'], fontSize=7, leading=9)

        story = [
            Paragraph('<b>Regulation Comparison Review</b>', ParagraphStyle(
                't', parent=styles['Title'], textColor=navy, fontSize=15, spaceAfter=2,
            )),
            Paragraph(
                f'Exported: {datetime.datetime.now().strftime("%d %B %Y, %H:%M")} &nbsp;·&nbsp; '
                f'Total items: {results.count()}',
                ParagraphStyle('sub', parent=styles['Normal'], textColor=grey, fontSize=8, spaceAfter=0),
            ),
            Spacer(1, 6*mm),
        ]

        headers    = ['Pair', 'Citation A', 'Citation B', 'Relationship', 'Status', 'Conf.', 'Note']
        col_fields = ['pair', 'citation_a', 'citation_b', 'rel', 'lifecycle', 'confidence', 'note']

        data = [[Paragraph(f'<b>{h}</b>', ParagraphStyle(
            'hdr', parent=styles['Normal'], fontSize=8, textColor=colors.white,
        )) for h in headers]]

        for row_data in self._rows(results):
            data.append([Paragraph(str(row_data[f])[:80], wrap) for f in col_fields])

        col_widths = [22*mm, 48*mm, 48*mm, 26*mm, 18*mm, 14*mm, 50*mm]
        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (-1, 0),  navy),
            ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
            ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, alt]),
            ('GRID',          (0, 0), (-1, -1), 0.3, border),
            ('VALIGN',        (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING',    (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING',   (0, 0), (-1, -1), 4),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 4),
        ]))
        story.append(table)
        doc.build(story)

        buf.seek(0)
        response = HttpResponse(buf.read(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="comparison-review.pdf"'
        return response
