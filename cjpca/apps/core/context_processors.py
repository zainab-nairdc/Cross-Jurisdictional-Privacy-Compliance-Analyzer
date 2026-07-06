from django.core.cache import cache

_NAV_COUNTS_TTL = 30  # seconds


def nav_counts(request):
    """
    Inject nav badge counts + scope state into every template context.
    Counts are cached for 30 s to avoid 4 DB hits on every page load.
    """
    try:
        from apps.review.models import ReviewItem
        from apps.mapping.models import Gap
        from apps.library.models import Document
        from apps.ingestion.models import QuarantinedChunk
        from .scope import compute_scope_state

        counts = cache.get('nav_counts')
        if counts is None:
            counts = {
                'nav_pending_review': ReviewItem.objects.filter(status=ReviewItem.PENDING).count(),
                'nav_open_gaps':      Gap.objects.count(),
                'nav_reg_count':      Document.objects.filter(
                                          doc_type=Document.REGULATION,
                                          status=Document.INDEXED,
                                      ).count(),
                'nav_policy_count':   Document.objects.filter(
                                          doc_type=Document.POLICY,
                                          status=Document.INDEXED,
                                      ).count(),
                'nav_quarantine_pending': QuarantinedChunk.objects.filter(
                                              status=QuarantinedChunk.PENDING,
                                          ).count(),
            }
            cache.set('nav_counts', counts, _NAV_COUNTS_TTL)

        include_drafts = request.session.get('copilot_include_drafts', False)
        scope_state = compute_scope_state(include_drafts=include_drafts)

        # Copilot doc-picker dropdown. Retrieval filters by chunk metadata
        # ``doc_title``, which is the chunk_doc_title (file stem like
        # "Bahrain_PDPA_Order_43_2022_..."), NOT the human display name. Build
        # entries with display + chunk_title so the template shows the friendly
        # name but submits the chunk_title to retrieval.
        copilot_doc_options = cache.get('copilot_doc_options')
        if copilot_doc_options is None:
            flag_map = {
                'bahrain': '🇧🇭',
                'kuwait':  '🇰🇼',
                'india':   '🇮🇳',
                'bbk':     '🏦',
            }
            copilot_doc_options = []
            for d in (Document.objects
                      .filter(status=Document.INDEXED)
                      .order_by('jurisdiction', 'name')):
                copilot_doc_options.append({
                    'name':         d.name,                                  # human display
                    'chunk_title':  d.chunk_doc_title or d.name,             # retrieval key
                    'jurisdiction': d.jurisdiction,
                    'flag':         flag_map.get(d.jurisdiction, '📄'),
                })
            cache.set('copilot_doc_options', copilot_doc_options, 10)

        return {**counts,
                'scope_state':         scope_state,
                'copilot_doc_options': copilot_doc_options}
    except Exception:
        return {
            'nav_pending_review':       0,
            'nav_open_gaps':            0,
            'nav_reg_count':            0,
            'nav_policy_count':         0,
            'nav_quarantine_pending':   0,
            'scope_state':              None,
            'copilot_doc_options':      [],
        }
