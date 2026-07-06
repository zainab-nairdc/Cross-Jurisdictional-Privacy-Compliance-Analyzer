"""
pipeline.py — background ingestion runner for web-uploaded documents.

Called by DocumentUploadView after an IngestionJob is created.
Spawns a daemon thread so the HTTP response returns immediately.
The thread runs the full load → chunk → embed → index → bm25 pipeline,
updating IngestionJob stage/progress and Document.status at each step.
"""
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)


# ── public API ────────────────────────────────────────────────────────────────

def run_job(job_id: int) -> None:
    """Spawn a daemon thread to process the given IngestionJob."""
    t = threading.Thread(target=_process_job, args=(job_id,), daemon=True)
    t.start()


# ── internal ──────────────────────────────────────────────────────────────────

def _set_stage(job, stage: int, progress: int) -> None:
    job.current_stage = stage
    job.progress_pct  = progress
    job.save(update_fields=['current_stage', 'progress_pct', 'updated_at'])


def _fail(job, message: str) -> None:
    from apps.library.models import Document
    job.status        = job.FAILED
    job.error_message = message
    job.save(update_fields=['status', 'error_message', 'updated_at'])
    job.document.status = Document.FAILED
    job.document.save(update_fields=['status'])
    logger.error('IngestionJob %s failed: %s', job.pk, message)
    try:
        from apps.history.audit import log_event, Actions
        log_event(
            job.created_by, Actions.INGESTION_FAILED,
            target_type='ingestion.IngestionJob', target_id=job.pk,
            description=f'Ingestion of "{job.document.name}" failed',
            metadata={
                'document_id': job.document_id,
                'document_name': job.document.name,
                'error': message[:500],
            },
        )
    except Exception:
        pass


def _build_meta(doc) -> dict:
    """Construct the metadata dict expected by chunk_document from a Document instance."""
    # Use doc_type from the model as the ground truth so the chunker routes correctly.
    # 'Internal Policy' → POLICY_HEADER_RE; anything else → ARTICLE_HEADER_RE.
    if doc.doc_type == 'policy':
        doc_type_str = 'Internal Policy'
    else:
        # For regulations, refine by name so the chunker can pick the best strategy.
        n = doc.name.lower()
        if any(k in n for k in ('guide', 'circular', 'sop', 'procedure', 'policy')):
            doc_type_str = 'Internal Policy'
        else:
            doc_type_str = 'Regulatory'

    # 'Document Title' is written to chunk metadata as doc_title and is the
    # key every downstream lookup uses (Document.chunk_doc_title, the comparison
    # workspace, the mapping workflow, the doc viewer). It must equal
    # Path(file.name).stem or freshly uploaded docs become invisible to those
    # screens. 'Regulation Name + Version' is purely display and keeps the
    # human-readable label.
    display_title  = doc.full_name or doc.name
    version_suffix = f' v{doc.version}' if doc.version else ''
    return {
        'Document Title':            doc.chunk_doc_title or display_title,
        'Regulation Name + Version': display_title + version_suffix,
        'Document Type':             doc_type_str,
        'Jurisdiction':              doc.get_jurisdiction_display() or 'Unknown',
        'Issuing Authority':         doc.issuing_authority or '',
        'Effective Date':            doc.effective_date.strftime('%d %b %Y') if doc.effective_date else '',
        'Publication Date':          '',
        'Last Updated':              '',
        'Language':                  'English',
        'Scope Summary':             '',
        'Source URL':                doc.source_url or '',
        'Notes for Ingestion':       doc.notes or '',
    }


def _scan_chunks_for_injection(
    chunks,
    *,
    job,
    openrouter_api_key: str,
    openrouter_model:   str,
    ollama_url:         str,
    ollama_model:       str,
):
    """Run the prompt-injection scanner over chunks before embedding.

    Returns (safe_chunks, quarantined_records). Quarantined chunks are
    persisted to QuarantinedChunk and an audit row is written per detection
    so admins have a forensic trail independent of the queue table.

    Tier B uses OpenRouter (Claude Haiku 4.5) as the primary judge and
    Ollama as the offline fallback. If BOTH judges are unreachable for a
    suspicious chunk, the scanner fails CLOSED — that chunk is
    quarantined as JUDGE_UNAVAILABLE for human review.
    """
    try:
        from ingestion.injection_scanner import scan_chunks
    except Exception as exc:
        logger.warning('Injection scanner unavailable, skipping scan: %s', exc)
        return chunks, []

    safe, quarantined = scan_chunks(
        chunks,
        use_judge=True,
        openrouter_api_key=openrouter_api_key,
        openrouter_model=openrouter_model,
        ollama_url=ollama_url,
        ollama_model=ollama_model,
    )
    if not quarantined:
        return safe, []

    from apps.ingestion.models import QuarantinedChunk
    from apps.history.audit    import log_event, Actions

    records = []
    for chunk, result in quarantined:
        primary = result.detections[0]
        all_dets = [
            {
                'rule_id':     d.rule_id,
                'severity':    d.severity,
                'description': d.description,
                'snippet':     d.snippet,
                'tier':        d.tier,
                'judge_reason': d.judge_reason,
            }
            for d in result.detections
        ]
        try:
            qc = QuarantinedChunk.objects.create(
                job=job,
                document=job.document,
                chunk_index=int(chunk.get('chunk_index') or 0),
                node_id=str(chunk.get('node_id') or '')[:64],
                section_title=str(chunk.get('section_title') or '')[:255],
                content=chunk.get('content', ''),
                rule_id=primary.rule_id,
                severity=primary.severity,
                tier=primary.tier,
                rule_description=primary.description[:255],
                matched_snippet=primary.snippet,
                judge_reason=primary.judge_reason or '',
                all_detections=all_dets,
                chunk_metadata={
                    'hierarchy_path':  chunk.get('hierarchy_path', ''),
                    'jurisdiction':    chunk.get('jurisdiction', ''),
                    'regulation_name': chunk.get('regulation_name', ''),
                    'doc_type':        chunk.get('doc_type', ''),
                },
            )
            records.append(qc)
            log_event(
                job.created_by, Actions.QUARANTINE_FLAGGED,
                target_type='ingestion.QuarantinedChunk', target_id=qc.pk,
                description=(
                    f'Quarantined chunk #{qc.chunk_index} from "{job.document.name}" '
                    f'(rule {qc.rule_id}, severity {qc.severity})'
                ),
                metadata={
                    'document_id': job.document_id,
                    'rule_id':     qc.rule_id,
                    'severity':    qc.severity,
                    'tier':        qc.tier,
                    'all_rules':   [d['rule_id'] for d in all_dets],
                },
            )
        except Exception as exc:
            logger.warning('Failed to persist quarantined chunk: %s', exc)

    logger.info(
        'IngestionJob %s — %d chunk(s) quarantined, %d safe',
        job.pk, len(records), len(safe),
    )
    return safe, records


def _process_job(job_id: int) -> None:
    """Run the full ingestion pipeline for a single IngestionJob (called in a thread)."""
    # Import inside the thread to avoid circular imports at module load time.
    # Django DB connections are per-thread so this is safe.
    import django.db
    django.db.close_old_connections()

    try:
        from apps.ingestion.models import IngestionJob
        from apps.library.models   import Document
        job = IngestionJob.objects.select_related('document').get(pk=job_id)
    except Exception as exc:
        logger.error('Could not load IngestionJob %s: %s', job_id, exc)
        return

    doc = job.document

    # Guard: skip if already running or complete
    if job.status not in (IngestionJob.QUEUED, IngestionJob.RUNNING):
        return

    job.status = IngestionJob.RUNNING
    job.save(update_fields=['status', 'updated_at'])

    try:
        # ── Stage 2: Parse ────────────────────────────────────────────────────
        # ScannedPDFNoGPUError is not exposed by ingestion.loaders right now;
        # the loader returns empty text for scans rather than raising. Catch
        # the broader Exception case but check the empty-text condition below.
        _set_stage(job, 2, 5)
        from ingestion.loaders import load_document
        doc_path = Path(doc.file.path)
        text = load_document(doc_path)
        _set_stage(job, 2, 15)

        # ── Stage 3: Chunk ────────────────────────────────────────────────────
        _set_stage(job, 3, 20)
        from ingestion.chunker  import chunk_document
        from ingestion.embedder import get_model
        from config import OLLAMA_URL, OLLAMA_MODEL
        st_model = get_model()
        meta     = _build_meta(doc)
        chunks   = chunk_document(text, meta)
        if not chunks:
            _fail(job, 'No chunks produced — document may be empty or unreadable.')
            return
        _set_stage(job, 3, 30)

        # Prompt-injection scan. Runs between chunking and embedding so any
        # chunk that trips a rule never reaches Chroma or BM25 — the attack
        # is contained at the boundary. Flagged chunks are persisted to
        # QuarantinedChunk for admin review. The pipeline continues with the
        # safe subset; if all chunks were flagged, fail the job loudly so the
        # uploader doesn't get a silently-empty document.
        #
        # Tier B judge: OpenRouter (Claude Haiku 4.5) primary, Ollama fallback.
        # Override the primary model with INJECTION_JUDGE_MODEL if needed.
        import os
        openrouter_api_key = os.environ.get('OPENROUTER_API_KEY', '')
        openrouter_model   = os.environ.get(
            'INJECTION_JUDGE_MODEL', 'anthropic/claude-haiku-4-5',
        )
        safe_chunks, quarantined = _scan_chunks_for_injection(
            chunks,
            job=job,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
            ollama_url=OLLAMA_URL,
            ollama_model=OLLAMA_MODEL,
        )
        if not safe_chunks:
            _fail(
                job,
                f'All {len(chunks)} chunks were quarantined by the injection scanner. '
                'Review the quarantine queue before retrying.',
            )
            return
        chunks = safe_chunks
        _set_stage(job, 3, 40)

        # Split chunks: leaves go into the searchable indexes, parents go into
        # the parent_docstore so the retriever can expand a child hit back into
        # its full section. The chunker marks oversized sections with
        # embed_skip=True; embedding those would pollute search results
        # because the retriever would return both the parent section AND its
        # own children for the same query.
        leaves  = [c for c in chunks if not c.get('embed_skip')]
        parents = [c for c in chunks if     c.get('embed_skip')]

        # ── Stage 4: Embed (leaves only) ─────────────────────────────────────
        _set_stage(job, 4, 45)
        from ingestion.embedder import embed_chunks
        embeddings = embed_chunks(leaves, st_model)
        _set_stage(job, 4, 70)

        # ── Stage 5: Index ChromaDB + BM25 (leaves), parent_docstore (parents) ─
        _set_stage(job, 5, 75)
        from ingestion.indexer    import index_chunks
        from retrieval.bm25_store import upsert_chunks as bm25_upsert
        from retrieval.bm25_store import upsert_parents
        index_chunks(leaves, embeddings)
        bm25_upsert(leaves)
        if parents:
            upsert_parents(parents)
        _set_stage(job, 5, 90)

        # ── Stage 6: Ready ────────────────────────────────────────────────────
        _set_stage(job, 6, 100)
        from django.db import transaction
        with transaction.atomic():
            job.status = IngestionJob.COMPLETE
            job.save(update_fields=['status', 'updated_at'])
            doc.status      = Document.INDEXED
            # chunk_count reflects searchable leaves, not parents; parents
            # are context-expansion only and never surface in search results.
            doc.chunk_count = len(leaves)
            doc.save(update_fields=['status', 'chunk_count'])

        # Cache privacy-concept topics so the library page can show badges instantly.
        try:
            from apps.comparison.concepts import compute_and_cache_doc_topics
            compute_and_cache_doc_topics(doc)
        except Exception:
            pass  # non-fatal — topics can be absent

        logger.info(
            'IngestionJob %s complete — %d searchable leaves + %d parent sections for "%s"',
            job.pk, len(leaves), len(parents), doc.name,
        )

        try:
            from apps.history.audit import log_event, Actions
            log_event(
                job.created_by, Actions.INGESTION_COMPLETE,
                target_type='ingestion.IngestionJob', target_id=job.pk,
                description=f'Ingestion of "{doc.name}" complete: {len(leaves)} chunks',
                metadata={
                    'document_id':   doc.pk,
                    'document_name': doc.name,
                    'chunk_count':   len(leaves),
                    'parent_count':  len(parents),
                },
            )
        except Exception:
            pass

    except Exception as exc:
        import traceback
        _fail(job, traceback.format_exc())
