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
        from apps.library.models import TaxonomyNode
        return {
            "custom_jurisdictions": list(
                TaxonomyNode.objects.filter(node_type=TaxonomyNode.COUNTRY, is_active=True)),
            "custom_categories": list(
                TaxonomyNode.objects.filter(node_type=TaxonomyNode.TOPIC, is_active=True)),
        }
    except Exception:
        return {"custom_jurisdictions": [], "custom_categories": []}
