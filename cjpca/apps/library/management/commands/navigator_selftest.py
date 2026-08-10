"""Prove the navigator-lite (structure-aware) retrieval works end to end.

Reads an indexed document the way a person would — outline -> pick section ->
read — and prints each step so you can see it navigate instead of matching by
similarity.

Usage:
  python manage.py navigator_selftest
  python manage.py navigator_selftest --doc gdpr --q "What is the lawful basis for processing?"
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Demonstrate navigator-lite: outline -> select section -> read (local)."

    def add_arguments(self, parser):
        parser.add_argument("--doc", default="gdpr",
                            help="doc_title of an indexed regulation (default: gdpr)")
        parser.add_argument("--q", default="What is the lawful basis for processing personal data?",
                            help="the question to navigate for")

    def handle(self, *args, **opts):
        from reasoning.navigator import build_outline, select_sections, read_sections
        w = self.stdout.write
        doc, q = opts["doc"], opts["q"]

        w(self.style.MIGRATE_HEADING(f"\nNavigating '{doc}' for: \"{q}\"\n"))

        # 1) Outline — the document's shape, no body read
        outline = build_outline(doc)
        if not outline:
            w(self.style.ERROR(f"No indexed chunks for doc_title='{doc}'. "
                               f"Index it first, or pass --doc <exact title>."))
            return
        w(f"1) OUTLINE — {len(outline)} sections (model sees headings + previews, "
          f"not the full body):")
        for o in outline[:8]:
            w(f"     • {o['ref']}: {o['preview'][:70]}…")
        if len(outline) > 8:
            w(f"     … (+{len(outline) - 8} more)")

        # 2) Select — the model reasons about which section to open
        refs = select_sections(q, outline)
        w(f"\n2) MODEL PICKED: {refs or '(none)'}")
        if not refs:
            w(self.style.WARNING("   Model found no relevant section — would fall back to similarity search."))
            return

        # 3) Read — pull just those full sections, heading intact
        nodes = read_sections(doc, refs)
        w(f"\n3) READ {len(nodes)} full section(s) — each carries its heading path:")
        for n in nodes:
            meta = n.node.metadata
            body = n.node.get_content().replace("\n", " ")
            w(self.style.SUCCESS(f"\n   ── {meta.get('hierarchy_path') or meta.get('article_ref')} ──"))
            w(f"   {body[:340]}…")

        w(self.style.SUCCESS(f"\n✓ NAVIGATOR OK — answered from {len(nodes)} reasoned "
                             f"section(s) instead of scattered similarity chunks.\n"))
