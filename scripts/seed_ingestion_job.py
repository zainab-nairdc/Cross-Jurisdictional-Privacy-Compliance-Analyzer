import os
import sys
import django

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cjpca'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cjpca.settings')
django.setup()

from apps.library.models import Document
from apps.ingestion.models import IngestionJob

doc = Document.objects.first()
if not doc:
    print("No documents in library yet. Upload any real PDF first.")
    sys.exit(0)

job = IngestionJob.objects.create(
    document=doc,
    status='running',
    current_stage=3,
    progress_pct=55,
    log_entries=[
        {'stage': 1, 'level': 'info', 'msg': 'Parsing PDF with Docling'},
        {'stage': 1, 'level': 'info', 'msg': 'Extracted 14 pages, 312 paragraphs'},
        {'stage': 2, 'level': 'info', 'msg': 'Section-aware chunking complete (48 chunks)'},
        {'stage': 3, 'level': 'info', 'msg': 'Embedding chunks with BGE-small-en-v1.5'},
        {'stage': 3, 'level': 'info', 'msg': 'Embedded 26 of 48 chunks (54.2%)'},
    ],
)
print(f"Seeded IngestionJob #{job.pk} in running state at 55% on stage 3 for document #{doc.pk}.")
print("Refresh / (dashboard) or /ingestion/widget/ to see the live progress card.")
