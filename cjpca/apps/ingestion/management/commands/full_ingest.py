"""End-to-end CLI ingestion — single self-contained orchestrator.

Reads PDFs / DOCX / MD from `data/regulations/` and `data/internal_policies/`,
runs the full pipeline, and leaves the system with a fresh, fully-indexed
corpus. Designed to be the ONE file you run for bulk ingestion.

Stages (in order):
    1. Convert PDFs / DOCX -> Markdown        (Docling, subprocess-per-file)
    2. Wipe ChromaDB + BM25 + parent_docstore + Document + IngestionJob rows
    3. Per-file ingest: chunk -> scan -> embed -> index
       (uses ingestion/* stage modules directly; no Django pipeline.py)
    4. Hydrate Document fields from data/metadata.csv
    5. Recount Document.chunk_count from BM25 (consistency check)
    6. Run audits/wiring_audit.py (post-ingest verification)

Notes:
  • Stages 1 and 2 are destructive. Requires --apply to actually execute;
    without it the command prints a plan and exits.
  • Stage 1 runs each file in a fresh subprocess so Docling's ONNX heap
    doesn't fragment across files on Windows.
  • Stage 3 uses ingestion/loaders, chunker, scanner, embedder, indexer
    and retrieval/bm25_store directly. It does NOT call pipeline.py — that
    path is reserved for web-upload jobs (with progress tracking, audit,
    notifications). The CLI path here is leaner.
  • The injection scanner uses OpenRouter (Claude Haiku 4.5) as the
    primary Tier B judge with Ollama fallback. Reads OPENROUTER_API_KEY
    from the environment.

Usage (from cjpca/):
    ..\\.venv\\Scripts\\python.exe manage.py full_ingest --apply

    # Re-run without re-parsing PDFs (data/processed/ already current):
    ..\\.venv\\Scripts\\python.exe manage.py full_ingest --apply --skip-convert

    # Preserve BBK internal policies through the wipe:
    ..\\.venv\\Scripts\\python.exe manage.py full_ingest --apply --keep-bbk

    # Skip the post-ingest verification:
    ..\\.venv\\Scripts\\python.exe manage.py full_ingest --apply --skip-verify

    # (Internal) PDF->Markdown subprocess worker, used by stage 1:
    ..\\.venv\\Scripts\\python.exe manage.py full_ingest --single SRC DST
"""
import csv
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction


# Project root — needed so retrieval/config/ingestion imports resolve.
_BASE = Path(__file__).resolve().parents[5]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))


# ── Constants & path roots ───────────────────────────────────────────────────

DATA_DIR      = _BASE / 'data'
REG_DIR       = DATA_DIR / 'regulations'
POL_DIR       = DATA_DIR / 'internal_policies'
PROCESSED_DIR = DATA_DIR / 'processed'
METADATA_CSV  = DATA_DIR / 'metadata.csv'

_EXT_OK         = {'.pdf', '.docx', '.txt', '.md'}
_PARSE_EXT      = {'.pdf', '.docx', '.pptx', '.xlsx', '.html', '.md'}
FORMAT_PRIORITY = {'.md': 0, '.docx': 1, '.pdf': 2}


# ── Command ──────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = ('End-to-end ingestion: convert PDFs, wipe stores, ingest, '
            'import metadata, recount, verify. DESTRUCTIVE. Requires --apply.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help='Actually execute. Without this flag the '
                                 'command prints a plan and exits.')
        parser.add_argument('--skip-convert', action='store_true',
                            help='Skip stage 1 (PDF -> Markdown). Use when '
                                 'data/processed/ is already up to date.')
        parser.add_argument('--skip-verify', action='store_true',
                            help='Skip stage 6 (wiring audit). Faster but '
                                 'you lose the post-ingest sanity check.')
        parser.add_argument('--keep-bbk', action='store_true',
                            help='Preserve BBK internal policies during the wipe.')
        parser.add_argument('--resume', action='store_true',
                            help='Continue a partial ingest: SKIP the stage-2 '
                                 'wipe, skip files already indexed, and retry '
                                 'the rest. Use after an interrupted run so '
                                 'you keep completed work (and any documents '
                                 'uploaded through the web wizard) instead of '
                                 'starting over.')
        parser.add_argument('--per-file-timeout', type=int, default=900,
                            help='Stage 1 per-file Docling timeout in seconds '
                                 '(default: 900).')
        parser.add_argument('--single', nargs=2, metavar=('SRC', 'DST'),
                            help='(internal) Subprocess worker: parse ONE '
                                 'file via Docling and exit. Used by stage 1.')

    # ── entry ────────────────────────────────────────────────────────────────

    def handle(self, *args, **opts):
        # Subprocess worker mode — parse one file, exit. Used by stage 1 so
        # Docling's ONNX heap can't accumulate across files.
        if opts.get('single'):
            src, dst = opts['single']
            sys.exit(self._docling_one(Path(src), Path(dst)))

        apply        = opts['apply']
        skip_convert = opts['skip_convert']
        skip_verify  = opts['skip_verify']
        keep_bbk     = opts['keep_bbk']
        resume       = opts['resume']
        timeout_s    = opts['per_file_timeout']

        # Build & print the plan
        plan = []
        if not skip_convert:
            plan.append(('1', 'Convert PDFs / DOCX -> Markdown'))
        if not resume:
            plan.append(('2', f'Wipe stores{" (keep BBK)" if keep_bbk else ""}'))
        plan.append(('3', 'Per-file ingest: chunk -> scan -> embed -> index'
                          f'{" (resume: skip already-indexed)" if resume else ""}'))
        plan.append(('4', 'Import metadata.csv into Document rows'))
        plan.append(('5', 'Recount Document.chunk_count from BM25'))
        if not skip_verify:
            plan.append(('6', 'Wiring audit (post-ingest verification)'))

        if not apply:
            self.stdout.write(self.style.NOTICE('DRY RUN -- no changes will be made.'))
            self.stdout.write('Pass --apply to execute. Stages that would run:')
            for n, label in plan:
                self.stdout.write(f'  {n}. {label}')
            return

        t0 = time.time()
        self.stdout.write(self.style.NOTICE(
            f'Starting full_ingest. Total stages: {len(plan)}.'
        ))
        self.stdout.write('')

        if not skip_convert:
            self._stage('1', 'Convert PDFs / DOCX -> Markdown',
                        self._stage_1_convert, timeout_s=timeout_s)
        if resume:
            self.stdout.write(self.style.WARNING(
                ' Stage 2 (wipe) SKIPPED -- resuming into the existing index.'))
            self.stdout.write('')
        else:
            self._stage('2', 'Wipe stores', self._stage_2_wipe, keep_bbk=keep_bbk)
        self._stage('3', 'Per-file ingest', self._stage_3_ingest,
                    keep_bbk=keep_bbk, resume=resume)
        self._stage('4', 'Import metadata',  self._stage_4_import_metadata)
        self._stage('5', 'Recount chunks',   self._stage_5_recount)
        if not skip_verify:
            self._stage('6', 'Wiring audit', self._stage_6_verify)

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'full_ingest completed in {time.time() - t0:.1f}s.'
        ))

    # ── stage runner & helpers ───────────────────────────────────────────────

    def _stage(self, num: str, label: str, fn, **kwargs) -> None:
        bar = '-' * 60
        self.stdout.write(self.style.NOTICE(bar))
        self.stdout.write(self.style.NOTICE(f' Stage {num}: {label}'))
        self.stdout.write(self.style.NOTICE(bar))
        t0 = time.time()
        try:
            fn(**kwargs)
        except Exception as exc:
            self.stdout.write(self.style.ERROR(
                f'Stage {num} FAILED after {time.time() - t0:.1f}s: {exc}'
            ))
            raise
        self.stdout.write(self.style.SUCCESS(
            f'Stage {num} done in {time.time() - t0:.1f}s.'
        ))
        self.stdout.write('')

    def _walk_supported(self, root: Path):
        """Yield supported files under root, deduped by stem with format
        priority .md > .docx > .pdf. Skip 'file (1).pdf' duplicates."""
        if not root.exists():
            return
        import re
        by_stem: dict[str, Path] = {}
        for f in sorted(root.rglob('*')):
            if not f.is_file() or f.suffix.lower() not in _EXT_OK:
                continue
            if re.search(r'\s\(\d+\)\.\w+$', f.name):
                continue
            existing = by_stem.get(f.stem)
            new_prio = FORMAT_PRIORITY.get(f.suffix.lower(), 99)
            old_prio = FORMAT_PRIORITY.get(existing.suffix.lower(), 99) if existing else 99
            if existing is None or new_prio < old_prio:
                by_stem[f.stem] = f
        for f in sorted(by_stem.values()):
            yield f

    # ── STAGE 1: PDF/DOCX -> Markdown ────────────────────────────────────────

    def _stage_1_convert(self, *, timeout_s: int) -> None:
        """Convert every source file under regulations/ + internal_policies/
        into a `.md` file under processed/<jurisdiction>/. Skips files whose
        output already exists. Runs each file in a fresh subprocess so
        Docling's ONNX heap can't fragment across many docs."""
        targets: list[tuple[str, Path, Path]] = []
        for jur, folder in (
            ('bahrain', REG_DIR / 'bahrain'),
            ('india',   REG_DIR / 'india'),
            ('kuwait',  REG_DIR / 'kuwait'),
            ('bbk',     POL_DIR),
        ):
            targets.append((jur.upper(), folder, PROCESSED_DIR / jur))

        ok = skip = err = 0
        for label, src_dir, dst_dir in targets:
            files = list(self._walk_supported_for_parse(src_dir))
            self.stdout.write(f'{label} - {len(files)} files -> {dst_dir}')
            dst_dir.mkdir(parents=True, exist_ok=True)

            for f in files:
                out = dst_dir / f'{f.stem}.md'
                if out.exists():
                    self.stdout.write(f'  SKIP   {f.name}  (already converted)')
                    skip += 1
                    continue
                ok_flag, info, dt = self._spawn_docling(f, out, timeout_s)
                if ok_flag:
                    self.stdout.write(f'  OK     {f.name}  ({info}, {dt:.1f}s)')
                    ok += 1
                else:
                    self.stdout.write(self.style.ERROR(
                        f'  ERR    {f.name}: {info}  ({dt:.1f}s)'
                    ))
                    err += 1

        self.stdout.write(f'  Stage 1 summary: ok={ok}  skip={skip}  err={err}')

    def _walk_supported_for_parse(self, root: Path):
        """Stage 1 walker — looser than _walk_supported: accepts .pptx/.xlsx/.html
        as well as the ingestion-supported subset."""
        if not root.exists():
            return
        import re
        by_stem: dict[str, Path] = {}
        for f in sorted(root.glob('*')):
            if f.suffix.lower() not in _PARSE_EXT:
                continue
            if re.search(r'\s\(\d+\)\.\w+$', f.name):
                continue
            existing = by_stem.get(f.stem)
            new_prio = FORMAT_PRIORITY.get(f.suffix.lower(), 99)
            old_prio = FORMAT_PRIORITY.get(existing.suffix.lower(), 99) if existing else 99
            if existing is None or new_prio < old_prio:
                by_stem[f.stem] = f
        for f in sorted(by_stem.values()):
            yield f

    def _spawn_docling(self, src: Path, dst: Path, timeout_s: int):
        """Run THIS command in --single mode in a fresh subprocess. Streams
        Docling's stdout/stderr live to the parent terminal so the user can
        see per-file progress as it happens."""
        manage_py = _BASE / 'cjpca' / 'manage.py'
        cmd = [
            sys.executable, '-u', str(manage_py),
            'full_ingest', '--single', str(src), str(dst),
        ]
        self.stdout.write(
            f'  ...    {src.name}  (loading in fresh subprocess)'
        )
        t0 = time.time()
        try:
            result = subprocess.run(cmd, timeout=timeout_s)
            dt = time.time() - t0
            if result.returncode == 0:
                size = dst.stat().st_size if dst.exists() else 0
                return True, f'{size:,} bytes', dt
            return False, f'exit {result.returncode}', dt
        except subprocess.TimeoutExpired:
            return False, f'timeout ({timeout_s}s)', time.time() - t0

    def _docling_one(self, src: Path, dst: Path) -> int:
        """Subprocess worker: parse ONE file and write its markdown. Called
        via `manage.py full_ingest --single SRC DST` from stage 1."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix.lower() == '.md':
            text = src.read_text(encoding='utf-8')
            dst.write_text(text, encoding='utf-8')
            self.stdout.write(f'__OK__ chars={len(text)} pages=0 (md passthrough)')
            return 0
        from ingestion.loaders import load_document
        doc = load_document(src)
        dst.write_text(doc.text, encoding='utf-8')
        self.stdout.write(f'__OK__ chars={len(doc.text)} pages={doc.page_count}')
        return 0

    # ── STAGE 2: wipe stores ─────────────────────────────────────────────────

    def _stage_2_wipe(self, *, keep_bbk: bool) -> None:
        """Drop everything: BM25 rows, parent_docstore rows, ChromaDB
        collection, Document rows, IngestionJob rows."""
        from apps.ingestion.models import IngestionJob
        from apps.library.models   import Document
        from retrieval.bm25_store  import BM25_DB_PATH
        from config                import CHROMA_DIR, CHROMA_COLLECTION

        # BM25 + parent_docstore
        try:
            con = sqlite3.connect(str(BM25_DB_PATH))
            con.execute('DELETE FROM bm25_index')
            con.execute('DELETE FROM parent_docstore')
            con.commit()
            con.close()
            self.stdout.write('  BM25 + parent_docstore cleared.')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'  BM25 wipe: {exc}'))

        # ChromaDB — drop & recreate the collection
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            try:
                client.delete_collection(CHROMA_COLLECTION)
            except Exception:
                pass
            client.get_or_create_collection(
                CHROMA_COLLECTION, metadata={'hnsw:space': 'cosine'},
            )
            self.stdout.write('  ChromaDB collection reset.')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'  ChromaDB wipe: {exc}'))

        # DB rows
        with transaction.atomic():
            if keep_bbk:
                doc_deleted = Document.objects.exclude(jurisdiction='bbk').delete()
            else:
                doc_deleted = Document.objects.all().delete()
            job_deleted = IngestionJob.objects.all().delete()
        self.stdout.write(
            f'  DB rows deleted: documents={doc_deleted[0]}  jobs={job_deleted[0]}'
        )

    # ── STAGE 3: per-file ingest (chunk -> scan -> embed -> index) ───────────

    def _stage_3_ingest(self, *, keep_bbk: bool, resume: bool = False) -> None:
        """Walk regulations + internal_policies, copy files into MEDIA_ROOT,
        create Document + IngestionJob rows, and run the pipeline stages
        directly on each file's processed markdown. Bypasses pipeline.py —
        no per-stage Django progress, no audit events, no notifications.
        Those are reserved for web uploads."""
        from apps.library.models   import Document
        from apps.ingestion.models import IngestionJob

        media_docs = Path(settings.MEDIA_ROOT) / 'documents'
        media_docs.mkdir(parents=True, exist_ok=True)

        reg_files = list(self._walk_supported(REG_DIR))
        pol_files = [] if keep_bbk else list(self._walk_supported(POL_DIR))
        total = len(reg_files) + len(pol_files)
        self.stdout.write(
            f'  Files to ingest: regulations={len(reg_files)}  '
            f'policies={len(pol_files)}  total={total}'
        )

        # Warm the embedding model once so the per-file loop doesn't pay
        # the ~5s load cost repeatedly.
        from ingestion.embedder import get_model
        st_model = get_model()

        ingested = failed = skipped = 0
        for i, src in enumerate(reg_files + pol_files, 1):
            doc_type      = Document.POLICY if src in pol_files else Document.REGULATION
            jurisdiction  = self._jurisdiction_for(src, doc_type)
            name          = src.stem.replace('_', ' ').replace('-', ' ')
            rel_file      = f'documents/{src.name}'

            # On a resume the wipe did not run, so rows from the interrupted
            # attempt are still here. Match on the file path (exact, unlike the
            # derived display name) to decide: already INDEXED -> skip; present
            # but unfinished -> reuse that row rather than creating a duplicate.
            prior = (Document.objects.filter(file=rel_file).order_by('-pk').first()
                     if resume else None)
            if prior is not None and prior.status == Document.INDEXED:
                self.stdout.write(
                    f'  [{i:>2}/{total}] {name[:55]:55s}  ({jurisdiction})')
                self.stdout.write('      already indexed -- skipped')
                skipped += 1
                continue

            self.stdout.write(
                f'  [{i:>2}/{total}] {name[:55]:55s}  ({jurisdiction})'
            )

            dest = media_docs / src.name
            try:
                shutil.copy2(src, dest)
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'      copy failed: {exc}'))
                failed += 1
                continue

            if prior is not None:
                doc = prior
                doc.status = Document.PROCESSING
                doc.save(update_fields=['status'])
                self.stdout.write('      retrying previously unfinished document')
            else:
                doc = Document.objects.create(
                    name         = name,
                    doc_type     = doc_type,
                    jurisdiction = jurisdiction,
                    status       = Document.PROCESSING,
                    file         = rel_file,
                )
            job = IngestionJob.objects.create(document=doc, status=IngestionJob.QUEUED)

            try:
                leaves, parents = self._ingest_one(doc, st_model)
                doc.status      = Document.INDEXED
                doc.chunk_count = len(leaves)
                doc.save(update_fields=['status', 'chunk_count'])
                job.status = IngestionJob.COMPLETE
                job.save(update_fields=['status', 'updated_at'])
                self.stdout.write(self.style.SUCCESS(
                    f'      -> indexed: {len(leaves)} leaves + {len(parents)} parents'
                ))
                ingested += 1
            except KeyboardInterrupt:
                # Ctrl+C is a BaseException, so the `except Exception` below
                # never saw it: the in-flight document was abandoned mid-write
                # and left stuck at PROCESSING with a QUEUED job forever, and
                # nothing would ever pick it up again. Mark it failed, say how
                # to continue, then re-raise so the interrupt still stops the
                # command promptly.
                self.stdout.write(self.style.WARNING(
                    '      INTERRUPTED -- marked failed so it is retried'))
                doc.status = Document.FAILED
                doc.save(update_fields=['status'])
                job.status        = IngestionJob.FAILED
                job.error_message = 'interrupted by user (Ctrl+C)'
                job.save(update_fields=['status', 'error_message', 'updated_at'])
                self.stdout.write(self.style.WARNING(
                    f'  Stopped at {i}/{total}. Continue without losing the '
                    f'{ingested} document(s) done in this run:\n'
                    f'    python manage.py full_ingest --apply --resume'))
                raise
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'      FAILED: {exc}'))
                doc.status = Document.FAILED
                doc.save(update_fields=['status'])
                job.status        = IngestionJob.FAILED
                job.error_message = str(exc)[:500]
                job.save(update_fields=['status', 'error_message', 'updated_at'])
                failed += 1

        self.stdout.write(
            f'  Stage 3 summary: ingested={ingested}  failed={failed}  '
            f'skipped={skipped}')

    def _jurisdiction_for(self, path: Path, doc_type: str) -> str:
        from apps.library.models import Document
        if doc_type == Document.POLICY:
            return Document.BBK
        try:
            rel = path.relative_to(REG_DIR)
            top = rel.parts[0].lower()
            return {
                'bahrain': Document.BAHRAIN,
                'india':   Document.INDIA,
                'kuwait':  Document.KUWAIT,
            }.get(top, Document.OTHER)
        except ValueError:
            return Document.OTHER

    def _ingest_one(self, doc, st_model):
        """Run loader -> chunker -> scanner -> embedder -> indexer for a
        single Document. Returns (leaves, parents) lists."""
        from ingestion.loaders          import load_document
        from ingestion.chunker          import chunk_document
        from ingestion.injection_scanner import scan_chunks
        from ingestion.embedder         import embed_chunks
        from ingestion.indexer          import index_chunks
        from retrieval.bm25_store       import upsert_chunks as bm25_upsert
        from retrieval.bm25_store       import upsert_parents
        from config                     import OLLAMA_URL, OLLAMA_MODEL

        # 1. Load markdown. Prefer the pre-converted markdown in
        #    data/processed/ (produced by an earlier Docling run) so the CLI
        #    ingest doesn't need Docling just to re-parse the originals. Fall
        #    back to Docling for any document without a processed .md.
        from config import DATA_DIR as _DATA_DIR
        _stem = Path(doc.file.name).stem
        _md_matches = list((_DATA_DIR / 'processed').rglob(f'{_stem}.md'))
        if _md_matches:
            text = _md_matches[0].read_text(encoding='utf-8')
        else:
            loaded = load_document(Path(doc.file.path))
            text = loaded.text if hasattr(loaded, 'text') else str(loaded)
        if not text or not text.strip():
            raise RuntimeError('loader returned empty text (scanned PDF without OCR?)')

        # 2. Chunk
        meta = self._build_meta(doc)
        chunks = chunk_document(text, meta)
        if not chunks:
            raise RuntimeError('chunker produced 0 chunks')

        # 3. Scan for prompt injection. OpenRouter primary, Ollama fallback.
        openrouter_api_key = os.environ.get('OPENROUTER_API_KEY', '')
        openrouter_model   = os.environ.get(
            'INJECTION_JUDGE_MODEL', 'anthropic/claude-haiku-4-5',
        )
        safe_chunks, quarantined = scan_chunks(
            chunks,
            use_judge=True,
            openrouter_api_key=openrouter_api_key,
            openrouter_model=openrouter_model,
            ollama_url=OLLAMA_URL,
            ollama_model=OLLAMA_MODEL,
        )
        if quarantined:
            self.stdout.write(f'      quarantined {len(quarantined)} chunk(s)')
        if not safe_chunks:
            raise RuntimeError('all chunks quarantined by scanner')

        # 4. Split leaves vs parents. Leaves get embedded + indexed; parents
        # go to parent_docstore for context expansion.
        leaves  = [c for c in safe_chunks if not c.get('embed_skip')]
        parents = [c for c in safe_chunks if     c.get('embed_skip')]

        # 5. Embed leaves
        embeddings = embed_chunks(leaves, st_model)

        # 6. Index
        index_chunks(leaves, embeddings)
        bm25_upsert(leaves)
        if parents:
            upsert_parents(parents)

        return leaves, parents

    def _build_meta(self, doc) -> dict:
        """Build the metadata dict the chunker expects from a Document row."""
        if doc.doc_type == 'policy':
            doc_type_str = 'Internal Policy'
        else:
            n = doc.name.lower()
            if any(k in n for k in ('guide', 'circular', 'sop', 'procedure', 'policy')):
                doc_type_str = 'Internal Policy'
            else:
                doc_type_str = 'Regulatory'

        # 'Document Title' is the retrieval key (see notes in apps/ingestion/
        # pipeline.py:_build_meta). Must equal Path(file.name).stem so
        # Document.chunk_doc_title lookups land on the right chunks.
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

    # ── STAGE 4: import metadata.csv ────────────────────────────────────────

    def _stage_4_import_metadata(self) -> None:
        """Walk data/metadata.csv and hydrate every matching Document with
        publication date, issuing authority, regulation category, etc."""
        from apps.library.models import Document
        if not METADATA_CSV.exists():
            self.stdout.write(self.style.WARNING(
                f'  metadata.csv not found at {METADATA_CSV}; skipping.'
            ))
            return

        by_stem = {d.chunk_doc_title: d for d in Document.objects.all() if d.chunk_doc_title}
        self.stdout.write(f'  {len(by_stem)} Documents indexed by file stem.')

        matched = unmatched = updated = 0
        with METADATA_CSV.open('r', encoding='utf-8', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                title = (row.get('Document Title') or '').strip()
                if not title:
                    continue
                doc = by_stem.get(title)
                if not doc:
                    unmatched += 1
                    continue
                matched += 1

                changes = self._diff_metadata_row(doc, row)
                if not changes:
                    continue
                for k, v in changes.items():
                    setattr(doc, k, v)
                doc.save(update_fields=list(changes))
                updated += 1

        self.stdout.write(
            f'  Stage 4 summary: matched={matched}  unmatched={unmatched}  updated={updated}'
        )

    def _diff_metadata_row(self, doc, row: dict) -> dict:
        """Return only the fields whose CSV value differs from the Document."""
        out: dict = {}

        def maybe(field_name: str, csv_key: str, *, max_len: int = 0, transform=None):
            raw = (row.get(csv_key) or '').strip()
            if not raw:
                return
            val = transform(raw) if transform else raw
            if max_len and isinstance(val, str):
                val = val[:max_len]
            if val != getattr(doc, field_name):
                out[field_name] = val

        def _date(s: str):
            try:
                return datetime.strptime(s, '%Y-%m-%d').date()
            except ValueError:
                return None

        maybe('effective_date',     'Effective Date',   transform=_date)
        maybe('publication_date',   'Publication Date', transform=_date)
        maybe('last_updated',       'Last Updated',     transform=_date)
        maybe('full_name',          'Regulation Name + Version',     max_len=500)
        maybe('issuing_authority',  'Issuing Authority',             max_len=255)
        maybe('source_url',         'Source URL',                    max_len=500)
        maybe('version',            'version',                       max_len=50)
        maybe('notes',              'Scope Summary')
        maybe('section_identifiers', 'Section/Article Identifiers',  max_len=255)
        maybe('document_id',        'document_id',                   max_len=50)
        maybe('regulation_category', 'regulation_category',          max_len=50)
        maybe('privacy_relevance',  'privacy_relevance',             max_len=20)
        maybe('applicable_sector',  'applicable_sector',             max_len=50)
        maybe('superseded_by',      'superseded_by',                 max_len=255)
        maybe('parent_regulation',  'parent_regulation',             max_len=50)
        maybe('cross_references',   'cross_references')

        # Special-case bool + list
        sup_raw = (row.get('superseded') or '').strip().upper()
        sup_val = sup_raw in ('TRUE', 'YES', '1')
        if sup_val != doc.superseded:
            out['superseded'] = sup_val

        tags = [t.strip() for t in (row.get('concept_tags') or '').split(',') if t.strip()]
        if tags and tags != doc.concept_tags_csv:
            out['concept_tags_csv'] = tags

        return out

    # ── STAGE 5: recount chunks ─────────────────────────────────────────────

    def _stage_5_recount(self) -> None:
        """Refresh Document.chunk_count from the BM25 store (source of truth).
        Reports drift and zero-chunk documents."""
        from apps.library.models  import Document
        from retrieval.bm25_store import BM25_DB_PATH

        con = sqlite3.connect(str(BM25_DB_PATH))
        cur = con.cursor()
        cur.execute('SELECT doc_title, COUNT(*) FROM bm25_index GROUP BY doc_title')
        bm25_counts = dict(cur.fetchall())
        con.close()
        self.stdout.write(
            f'  BM25 reports {sum(bm25_counts.values())} chunks across '
            f'{len(bm25_counts)} doc_titles.'
        )

        applied = drift = zero = 0
        for d in Document.objects.all():
            stem = Path(d.file.name).stem if d.file and d.file.name else ''
            real = bm25_counts.get(stem, 0)
            if real == 0:
                zero += 1
            if d.chunk_count != real:
                drift += 1
                d.chunk_count = real
                d.save(update_fields=['chunk_count'])
                applied += 1

        self.stdout.write(
            f'  Stage 5 summary: drift={drift}  zero_chunk_docs={zero}  applied={applied}'
        )

    # ── STAGE 6: wiring audit ───────────────────────────────────────────────

    def _stage_6_verify(self) -> None:
        """Run audits/wiring_audit.py as a subprocess."""
        audit_path = _BASE / 'cjpca' / 'audits' / 'wiring_audit.py'
        if not audit_path.exists():
            self.stdout.write(self.style.WARNING(
                f'  wiring_audit.py not found at {audit_path}; skipping.'
            ))
            return
        result = subprocess.run(
            [sys.executable, str(audit_path)],
            cwd=str(_BASE / 'cjpca'),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f'wiring_audit.py exited with code {result.returncode}'
            )
