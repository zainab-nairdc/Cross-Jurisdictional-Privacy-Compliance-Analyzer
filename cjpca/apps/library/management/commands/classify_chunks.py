"""Backfill taxonomy tags onto already-indexed chunks.

For each chunk in the BM25 index that doesn't yet have a row in
chunk_tags, this command:

  1. Loads the chunk text + doc_title + jurisdiction from BM25.
  2. Calls reasoning.classifier.classify_chunk to get (topic,
     subcategory, confidence).
  3. Writes the tag to the chunk_tags side-table.
  4. Optionally pushes the same tag onto the chunk's chroma metadata
     (so vector-side filtering also works).

Usage:
    python manage.py classify_chunks                 # dry run, no writes
    python manage.py classify_chunks --apply         # actually classify + write
    python manage.py classify_chunks --apply --limit 50
    python manage.py classify_chunks --apply --jurisdiction Bahrain
    python manage.py classify_chunks --apply --no-chroma   # skip chroma update

Designed to be safe to interrupt: each chunk is committed individually,
so Ctrl-C resumes from where it stopped. Re-running with --apply is a
no-op for chunks already tagged unless --force is passed.
"""

import sqlite3
import sys
import time
from pathlib import Path

from django.core.management.base import BaseCommand

_BASE = Path(__file__).resolve().parents[5]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from retrieval.bm25_store import BM25_DB_PATH, upsert_chunk_tags, chunk_tag_stats  # noqa: E402
from reasoning.classifier import classify_chunk                                    # noqa: E402
from reasoning import taxonomy                                                     # noqa: E402


def _load_chunks(*, jurisdiction: str | None, doc_title: str | None,
                 only_untagged: bool, limit: int | None) -> list[dict]:
    """pull (node_id, content, doc_title, jurisdiction) rows from bm25_index,
    optionally restricted to untagged chunks."""
    conditions = []
    params: list = []
    if jurisdiction:
        conditions.append("b.jurisdiction = ?")
        params.append(jurisdiction)
    if doc_title:
        conditions.append("b.doc_title = ?")
        params.append(doc_title)
    if only_untagged:
        conditions.append("t.node_id IS NULL")

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT b.node_id, b.content, b.doc_title, b.jurisdiction
        FROM   bm25_index b
        LEFT JOIN chunk_tags t ON t.node_id = b.node_id
        {where}
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    with sqlite3.connect(str(BM25_DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        # Make sure chunk_tags exists so the LEFT JOIN doesn't error on a
        # fresh db where the side-table hasn't been created yet.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunk_tags (
                node_id TEXT PRIMARY KEY, topic TEXT NOT NULL,
                subcategory TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.0,
                tagged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _push_to_chroma(updates: list[dict]) -> int:
    """update chroma chunk metadata with topic/subcategory. fail-soft: if
    chroma isn't reachable or a node_id is missing, skip and continue —
    the bm25 side-table is the source of truth for filtering anyway."""
    if not updates:
        return 0
    try:
        import chromadb
        from config import CHROMA_DIR, CHROMA_COLLECTION
    except Exception as e:
        return 0

    try:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        col = client.get_or_create_collection(
            CHROMA_COLLECTION, metadata={"hnsw:space": "cosine"},
        )
    except Exception:
        return 0

    written = 0
    for u in updates:
        try:
            col.update(
                ids=[u["node_id"]],
                metadatas=[{
                    "topic":       u["topic"],
                    "subcategory": u.get("subcategory", ""),
                }],
            )
            written += 1
        except Exception:
            # individual failure (e.g. id not in chroma) — skip, don't blow up
            continue
    return written


class Command(BaseCommand):
    help = ('Tag indexed chunks with (topic, subcategory) from the canonical '
            'taxonomy. Dry-run by default; pass --apply to write.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                             help='Actually classify + write. Without this, runs as a count-only dry run.')
        parser.add_argument('--limit', type=int, default=None,
                             help='Stop after N chunks (useful for smoke tests).')
        parser.add_argument('--jurisdiction', type=str, default=None,
                             help='Only classify chunks from this jurisdiction.')
        parser.add_argument('--doc-title', type=str, default=None,
                             help='Only classify chunks from this single doc_title (file stem).')
        parser.add_argument('--force', action='store_true',
                             help='Re-classify chunks that already have a tag.')
        parser.add_argument('--no-chroma', action='store_true',
                             help='Skip pushing tags to chroma metadata. bm25 side-table only.')

    def handle(self, *args, apply, limit, jurisdiction, doc_title, force, no_chroma, **kwargs):
        if not BM25_DB_PATH.exists():
            self.stderr.write(self.style.ERROR(f'BM25 db not found at {BM25_DB_PATH}'))
            return

        before = chunk_tag_stats()
        self.stdout.write(self.style.NOTICE(
            f'Before: {before["tagged"]} tagged / {before["total"]} total '
            f'({before["untagged"]} untagged)'
        ))

        rows = _load_chunks(
            jurisdiction=jurisdiction, doc_title=doc_title,
            only_untagged=(not force), limit=limit,
        )
        self.stdout.write(f'Selected {len(rows)} chunk(s) to classify.')

        if not apply:
            self.stdout.write(self.style.WARNING(
                'Dry run. Pass --apply to actually classify.'
            ))
            return

        if not rows:
            self.stdout.write(self.style.SUCCESS('Nothing to do.'))
            return

        # Classify + write one chunk at a time. Resumable on Ctrl-C — each
        # tag is committed individually.
        written = 0
        chroma_written = 0
        t0 = time.time()
        for i, row in enumerate(rows, 1):
            tag = classify_chunk(
                chunk_text   = row["content"] or "",
                doc_title    = row["doc_title"] or "",
                jurisdiction = row["jurisdiction"] or "",
            )

            upsert_chunk_tags([{
                "node_id":     row["node_id"],
                "topic":       tag.topic,
                "subcategory": tag.subcategory,
                "confidence":  tag.confidence,
            }])
            written += 1

            if not no_chroma and tag.topic != taxonomy.UNCLASSIFIED:
                pushed = _push_to_chroma([{
                    "node_id":     row["node_id"],
                    "topic":       tag.topic,
                    "subcategory": tag.subcategory,
                }])
                chroma_written += pushed

            if i % 10 == 0 or i == len(rows):
                elapsed = time.time() - t0
                rate = i / max(elapsed, 0.001)
                eta = (len(rows) - i) / max(rate, 0.001)
                self.stdout.write(
                    f'  [{i:>4d}/{len(rows)}] {tag.topic}/{tag.subcategory} '
                    f'(conf {tag.confidence:.2f}) — {rate:.1f}/s, ETA {eta/60:.1f}min'
                )

        after = chunk_tag_stats()
        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {written} chunks tagged in side-table'
            + (f', {chroma_written} also pushed to chroma' if not no_chroma else '')
            + '.'
        ))
        self.stdout.write(self.style.NOTICE(
            f'After: {after["tagged"]} tagged / {after["total"]} total '
            f'({after["untagged"]} untagged)'
        ))
        self.stdout.write('Tag counts by topic:')
        for topic_, n in sorted(after["by_topic"].items(), key=lambda kv: -kv[1]):
            self.stdout.write(f'  {n:5d}  {topic_}')
