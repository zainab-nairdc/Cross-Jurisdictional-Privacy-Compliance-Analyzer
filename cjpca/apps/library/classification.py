"""Opt-in policy/section classification, triggered at upload.

Classifying a document's sections into taxonomy topics is what lets the
coverage flow derive scope (a section only needs checking against provisions
on the same topic). It is expensive — one LLM call per chunk — so it is NOT
run silently inside a page request. Instead the uploader opts in via a
checkbox, and this module runs it in a background thread, updating
``Document.classification_state`` so the UI can show not-classified /
classifying / ready.

Idempotent and version-aware: only chunks that are untagged *at the current
taxonomy fingerprint* are (re)classified, so a re-run after a taxonomy bump
re-tags exactly what changed and a re-run with no change is a no-op.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

_BASE = Path(__file__).resolve().parents[3]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

logger = logging.getLogger(__name__)


def classify_document(doc_pk: int, wait_for_indexed: bool = True,
                      timeout_s: int = 900) -> int:
    """Classify one document's chunks into taxonomy topics (blocking).

    Returns the number of chunks newly tagged. Safe to call from a worker
    thread. Reads the source of truth (bm25 side-table) so it works for any
    English document already in the index. Updates the document's lifecycle
    fields as it goes."""
    import django.db
    django.db.close_old_connections()

    from django.utils import timezone
    from apps.library.models import Document
    from retrieval.bm25_store import untagged_chunks_for_docs, upsert_chunk_tags
    from reasoning.classifier import classify_chunk
    from reasoning.taxonomy import TAXONOMY_VERSION, UNCLASSIFIED

    try:
        doc = Document.objects.get(pk=doc_pk)
    except Document.DoesNotExist:
        return 0

    # Wait for indexing to finish — English uploads index asynchronously, and
    # there are no chunks to classify until that completes.
    if wait_for_indexed:
        waited = 0
        while doc.status != Document.INDEXED and waited < timeout_s:
            if doc.status == Document.FAILED:
                Document.objects.filter(pk=doc_pk).update(
                    classification_state=Document.CLASS_NONE)
                return 0
            time.sleep(3)
            waited += 3
            doc.refresh_from_db(fields=['status'])
        if doc.status != Document.INDEXED:
            logger.warning('classify_document %s timed out waiting for indexing', doc_pk)
            Document.objects.filter(pk=doc_pk).update(
                classification_state=Document.CLASS_NONE)
            return 0

    Document.objects.filter(pk=doc_pk).update(classification_state=Document.CLASS_RUNNING)

    title = doc.chunk_doc_title
    untagged = untagged_chunks_for_docs([title]) if title else []
    written = 0
    for row in untagged:
        try:
            tag = classify_chunk(
                chunk_text=row['content'] or '',
                doc_title=row['doc_title'] or '',
                jurisdiction=row['jurisdiction'] or '',
            )
        except Exception as exc:
            logger.error('classify_chunk failed for %s: %s', row['node_id'], exc)
            continue
        upsert_chunk_tags([{
            'node_id': row['node_id'],
            'topic': tag.topic,
            'subcategory': tag.subcategory,
            'confidence': tag.confidence,
        }])
        written += 1

    Document.objects.filter(pk=doc_pk).update(
        classification_state=Document.CLASS_DONE,
        classified_at=timezone.now(),
        classification_version=TAXONOMY_VERSION,
    )
    logger.info('classify_document %s tagged %d chunk(s) at %s',
                doc_pk, written, TAXONOMY_VERSION)
    return written


def classify_document_async(doc_pk: int) -> None:
    """Fire-and-forget wrapper: mark the doc queued and classify in a daemon
    thread once indexing completes."""
    from apps.library.models import Document
    Document.objects.filter(pk=doc_pk).update(classification_state=Document.CLASS_PENDING)

    def _target(pk):
        from django.db import close_old_connections
        close_old_connections()
        try:
            classify_document(pk)
        except Exception:
            import traceback
            logger.error('classify_document_async %s failed:\n%s', pk, traceback.format_exc())
            try:
                Document.objects.filter(pk=pk).update(classification_state=Document.CLASS_NONE)
            except Exception:
                pass
        finally:
            close_old_connections()

    threading.Thread(target=_target, args=(doc_pk,), daemon=True).start()
