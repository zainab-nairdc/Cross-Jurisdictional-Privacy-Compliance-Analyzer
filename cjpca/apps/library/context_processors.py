"""Template context for the global upload wizard.

The upload wizard now lives in base.html (one front door for every page), so the
admin-created jurisdictions/categories it offers must be available in EVERY
template context — not just the Regulations page that used to own the wizard.
This exposes them app-wide so a document filed under a previously-added country
(e.g. "qatar") lists it in the dropdown instead of re-offering it as new.
"""

from __future__ import annotations


def upload_taxonomy(request):
    """{custom_jurisdictions, custom_categories} for the global wizard.

    Kept cheap and fail-safe: the wizard falls back to its built-in lists if
    this returns nothing, so any error here degrades to 'built-ins only' rather
    than breaking page render."""
    try:
        import json
        from apps.library.models import Document, TaxonomyNode
        # Documents the wizard can offer as "this is a newer version of…".
        # Regulations AND internal policies: a policy gets reissued just as often
        # as a law, and the wizard matches candidates to the type being uploaded.
        # Only active documents (not superseded, not drafts) are valid parents.
        existing_regs = [
            {"id": d.pk, "name": d.name, "jurisdiction": d.jurisdiction or "",
             "category": d.regulation_category or "", "full_name": d.full_name or "",
             "doc_type": d.doc_type or ""}
            for d in Document.objects.filter(
                doc_type__in=[Document.REGULATION, Document.POLICY],
                superseded=False, status='indexed',
            ).order_by("doc_type", "jurisdiction", "name").only(
                "id", "name", "jurisdiction", "regulation_category", "full_name", "doc_type")
        ]
        return {
            "custom_jurisdictions": list(
                TaxonomyNode.objects.filter(node_type=TaxonomyNode.COUNTRY, is_active=True)),
            "custom_categories": list(
                TaxonomyNode.objects.filter(node_type=TaxonomyNode.TOPIC, is_active=True)),
            "existing_regulations_json": json.dumps(existing_regs),
        }
    except Exception:
        return {"custom_jurisdictions": [], "custom_categories": [],
                "existing_regulations_json": "[]"}


def review_counts(request):
    """Badge counts for the sidebar.

    `nav_suggestion_count` is the number of OPEN topic suggestions — concepts
    waiting on a human decision about whether the taxonomy should grow. Only
    open ones count: approved, rejected and merged suggestions are settled and
    would turn the badge into noise.

    Fail-safe like `upload_taxonomy`: any error degrades to no badge rather
    than breaking every page render.
    """
    try:
        from apps.library.models import TopicSuggestion
        return {"nav_suggestion_count": TopicSuggestion.objects.filter(
            status__in=TopicSuggestion.OPEN_STATUSES).count()}
    except Exception:
        return {"nav_suggestion_count": 0}
