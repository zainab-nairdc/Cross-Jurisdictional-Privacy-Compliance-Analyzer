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
        # In-force regulations the wizard can offer as "this is a newer version of…".
        # Only active regulations (not superseded, not drafts) are valid parents.
        existing_regs = [
            {"id": d.pk, "name": d.name, "jurisdiction": d.jurisdiction or "",
             "category": d.regulation_category or "", "full_name": d.full_name or ""}
            for d in Document.objects.filter(
                doc_type=Document.REGULATION, superseded=False, status='indexed'
            ).order_by("jurisdiction", "name").only(
                "id", "name", "jurisdiction", "regulation_category", "full_name")
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
