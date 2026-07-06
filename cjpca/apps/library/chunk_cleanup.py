"""Purge a Document's chunks from BM25 + parent docstore + chunk tags + Chroma.

Wired into a pre_delete signal on Document (apps/library/signals.py) so any
deletion path (the web admin Delete button, Django admin, programmatic ORM
delete) cleans up the vectorstore. Without this, orphan chunks linger in
hybrid_search results and pollute future comparisons.

The lookup key is Document.chunk_doc_title (= Path(file.name).stem) since
that's what ingestion writes into chunk metadata as doc_title. If a Document
has no file or an empty chunk_doc_title we skip — purging on an empty title
would wipe every untagged chunk.
"""
import logging
import sqlite3

logger = logging.getLogger(__name__)


def purge_doc_chunks(doc) -> dict:
    """Remove every chunk belonging to ``doc`` from BM25 + Chroma.

    Returns a dict with counts so callers can log or surface what was
    removed. Safe to call on a doc whose chunks were never ingested —
    every step short-circuits on empty results.
    """
    result = {'title': '', 'bm25': 0, 'parents': 0, 'tags': 0, 'chroma': 0}
    title = getattr(doc, 'chunk_doc_title', '') or ''
    if not title:
        logger.info('purge_doc_chunks: doc #%s has no chunk_doc_title, skipping', doc.pk)
        return result
    result['title'] = title

    node_ids: list[str] = []

    # ── BM25 + parent docstore + chunk_tags (single sqlite db) ────────────────
    try:
        from retrieval.bm25_store import BM25_DB_PATH
        conn = sqlite3.connect(str(BM25_DB_PATH))
        try:
            cur = conn.cursor()
            rows = cur.execute(
                'SELECT node_id FROM bm25_index WHERE doc_title = ?', (title,),
            ).fetchall()
            node_ids = [r[0] for r in rows if r and r[0]]

            cur.execute('DELETE FROM bm25_index WHERE doc_title = ?', (title,))
            result['bm25'] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else len(rows)

            cur.execute('DELETE FROM parent_docstore WHERE doc_title = ?', (title,))
            result['parents'] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

            if node_ids:
                placeholders = ','.join('?' * len(node_ids))
                cur.execute(
                    f'DELETE FROM chunk_tags WHERE node_id IN ({placeholders})',
                    node_ids,
                )
                result['tags'] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning('purge_doc_chunks: BM25 cleanup failed for %s: %s', title, exc)

    # ── Chroma vectorstore ────────────────────────────────────────────────────
    if node_ids:
        try:
            from ingestion.indexer import get_vectorstore
            collection = get_vectorstore()._collection
            collection.delete(ids=node_ids)
            result['chroma'] = len(node_ids)
        except Exception as exc:
            logger.warning('purge_doc_chunks: Chroma cleanup failed for %s: %s', title, exc)

    logger.info(
        'purge_doc_chunks: doc #%s title=%r removed bm25=%d parents=%d tags=%d chroma=%d',
        doc.pk, title, result['bm25'], result['parents'], result['tags'], result['chroma'],
    )
    return result
