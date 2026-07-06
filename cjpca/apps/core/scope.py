from dataclasses import dataclass


@dataclass
class CategoryState:
    count: int
    usable: bool


STATE_LABELS = {
    'not_ready': 'Not ready',
    'partially_ready': 'Partially ready',
    'ready': 'Ready',
}

READY_SENTENCE = (
    'Copilot is ready to answer across <span>all sources</span> — '
    'regulations, internal policies, comparisons, and gaps.'
)

NOT_READY_SENTENCE = (
    'No sources have been ingested yet. '
    'Upload regulations and internal policies to get started.'
)

PARTIAL_TEMPLATES = {
    'sources_only': (
        'Copilot answers from <span>{source_list}</span>. '
        'Comparison and gap answers need approved analyses — '
        '{draft_phrase}.'
    ),
    'analyses_only': (
        'Copilot answers from <span>{analysis_list}</span>. '
        'Upload sources to cover the underlying regulations.'
    ),
    'mixed': (
        'Copilot answers from <span>{ready_list}</span>. '
        '{missing_phrase}.'
    ),
}


def _humanize_list(items: list) -> str:
    if not items:
        return ''
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f'{items[0]} and {items[1]}'
    return ', '.join(items[:-1]) + f', and {items[-1]}'


def classify_state(categories: dict) -> str:
    regs_ok = categories['regulations'].usable
    policies_ok = categories['internal_policies'].usable
    comparisons_ok = categories['approved_comparisons'].usable
    mappings_ok = categories['approved_mappings'].usable

    if not regs_ok and not policies_ok:
        return 'not_ready'
    if regs_ok and policies_ok and comparisons_ok and mappings_ok:
        return 'ready'
    return 'partially_ready'


def compute_fraction(categories: dict) -> float:
    usable_count = sum(1 for cat in categories.values() if cat.usable)
    return round(usable_count / len(categories), 2)


def build_explanation(state: str, categories: dict, drafts_total: int) -> str:
    if state == 'ready':
        return READY_SENTENCE

    if state == 'not_ready':
        base = NOT_READY_SENTENCE
        if drafts_total > 0:
            plural = 'drafts are' if drafts_total != 1 else 'draft is'
            base = base.rstrip('.') + (
                f' {drafts_total} {plural} waiting to be reviewed once sources exist.'
            )
        return base

    ready_items = []
    missing_items = []

    if categories['regulations'].usable:
        ready_items.append('regulations')
    else:
        missing_items.append('regulations')

    if categories['internal_policies'].usable:
        ready_items.append('internal policies')
    else:
        missing_items.append('internal policies')

    analyses_ready = (
        categories['approved_comparisons'].usable or
        categories['approved_mappings'].usable
    )
    has_sources = (
        categories['regulations'].usable or
        categories['internal_policies'].usable
    )

    if has_sources and not analyses_ready:
        source_list = _humanize_list(ready_items)
        if drafts_total > 0:
            plural_verb = 'drafts are' if drafts_total != 1 else 'draft is'
            draft_phrase = f'{drafts_total} {plural_verb} waiting'
        else:
            draft_phrase = 'no drafts are available yet'
        return PARTIAL_TEMPLATES['sources_only'].format(
            source_list=source_list, draft_phrase=draft_phrase
        )

    if analyses_ready and not has_sources:
        analysis_parts = []
        if categories['approved_comparisons'].usable:
            analysis_parts.append('approved comparisons')
        if categories['approved_mappings'].usable:
            analysis_parts.append('approved gap mappings')
        return PARTIAL_TEMPLATES['analyses_only'].format(
            analysis_list=_humanize_list(analysis_parts)
        )

    # mixed: some sources + some analyses
    ready_list = _humanize_list(ready_items)
    missing_phrase = (
        f'Still waiting on {_humanize_list(missing_items)} to unlock full coverage'
        if missing_items
        else 'ready for all answer types'
    )
    return PARTIAL_TEMPLATES['mixed'].format(
        ready_list=ready_list, missing_phrase=missing_phrase
    )


def compute_scope_state(include_drafts: bool = False) -> dict:
    from apps.library.models import Document
    from apps.comparison.models import ComparisonResult
    from apps.mapping.models import MappingAnalysis, ObligationMapping

    regs_count = Document.objects.filter(
        doc_type=Document.REGULATION, status=Document.INDEXED
    ).count()
    policies_count = Document.objects.filter(
        doc_type=Document.POLICY, status=Document.INDEXED
    ).count()

    approved_analyses = MappingAnalysis.objects.filter(status=MappingAnalysis.APPROVED)
    approved_comparisons_count = ComparisonResult.objects.filter(lifecycle='approved').count()
    approved_mappings_count = ObligationMapping.objects.filter(
        analysis__in=approved_analyses
    ).count()

    draft_comparisons = ComparisonResult.objects.filter(lifecycle='draft').count()
    # Analyses that are complete/in-review but not yet approved
    draft_analyses = MappingAnalysis.objects.filter(
        status__in=[MappingAnalysis.COMPLETE, MappingAnalysis.REVIEW]
    ).count()
    drafts_total = draft_comparisons + draft_analyses

    categories = {
        'regulations': CategoryState(count=regs_count, usable=regs_count > 0),
        'internal_policies': CategoryState(count=policies_count, usable=policies_count > 0),
        'approved_comparisons': CategoryState(
            count=approved_comparisons_count, usable=approved_comparisons_count > 0
        ),
        'approved_mappings': CategoryState(
            count=approved_mappings_count, usable=approved_mappings_count > 0
        ),
    }

    state = classify_state(categories)
    fraction = compute_fraction(categories)
    sources_ready = sum(1 for c in categories.values() if c.usable)
    sources_total = len(categories)
    explanation = build_explanation(state, categories, drafts_total)

    return {
        'state': state,
        'state_label': STATE_LABELS[state],
        'fraction_ready': fraction,
        'sources_ready_count': sources_ready,
        'sources_total': sources_total,
        'explanation': explanation,
        'actions': {
            'review_drafts': {
                'enabled': drafts_total > 0,
                'count': drafts_total,
                'url': '/review/',
            },
            'include_drafts_toggle': {
                'visible': drafts_total > 0,
                'current': include_drafts,
            },
        },
        'detail': {
            'regulations': {
                'count': regs_count,
                'usable': regs_count > 0,
                'emphasis_in_sentence': regs_count > 0,
            },
            'internal_policies': {
                'count': policies_count,
                'usable': policies_count > 0,
                'emphasis_in_sentence': policies_count > 0,
            },
            'approved_comparisons': {
                'count': approved_comparisons_count,
                'usable': approved_comparisons_count > 0,
                'emphasis_in_sentence': False,
            },
            'approved_mappings': {
                'count': approved_mappings_count,
                'usable': approved_mappings_count > 0,
                'emphasis_in_sentence': False,
            },
            'drafts_total': drafts_total,
        },
    }
