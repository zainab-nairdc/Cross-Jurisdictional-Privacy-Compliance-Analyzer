"""Signal handlers for the library app.

``purge_chunks_on_document_delete`` fires before a Document row is removed and
wipes its chunks from BM25 + Chroma. Without it, deleting a Document via any
path (web admin Delete button, Django admin, ORM ``.delete()``) would leave
orphan chunks in the vectorstore that still appear in hybrid_search results
and pollute future comparisons.

Registered from apps/library/apps.py:LibraryConfig.ready().
"""
import logging

from django.db.models.signals import pre_delete
from django.dispatch          import receiver

from .models        import Document
from .chunk_cleanup import purge_doc_chunks

logger = logging.getLogger(__name__)


@receiver(pre_delete, sender=Document)
def purge_chunks_on_document_delete(sender, instance, **kwargs):
    try:
        purge_doc_chunks(instance)
    except Exception as exc:
        # Never block the DB delete on a vectorstore cleanup failure — log
        # and continue. A reconcile run can sweep up survivors later.
        logger.warning('Chunk purge failed for doc #%s: %s', instance.pk, exc)
