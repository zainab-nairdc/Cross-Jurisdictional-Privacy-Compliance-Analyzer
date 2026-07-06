"""Restore the corpus from pre-cleaned chunks in data/chunks_inspect/.

Each .chunks.jsonl in that directory is a stream of pre-extracted, cleaned,
embedded-ready chunks. This command:

  1. Reads every line of every JSONL.
  2. Splits chunks by ``embed_skip``: chunks with embed_skip=True go to the
     parent_docstore (used for context expansion); the rest get embedded
     and indexed in BM25 + ChromaDB.
  3. Creates a Document row per JSONL whose name + jurisdiction + doc_type
     are derived from the chunk metadata (all chunks in one file share the
     same Document, by definition).
  4. Sets Document.file to the source PDF/DOCX in data/regulations/* or
     data/internal_policies/* so the chunk_doc_title property aligns with
     the chunk metadata's doc_title field.

This avoids re-running docling/chunker — the user already cleaned the
extracted text and produced these JSONLs. We just have to re-import them
into the live indexes.

Usage:
    python manage.py restore_from_chunks                     # dry-run report
    python manage.py restore_from_chunks --apply             # do it
    python manage.py restore_from_chunks --apply --wipe-first  # clear current
                                                             #  indexes first
"""

import sys
import json
import shutil
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

# project root on sys.path so retrieval/, ingestion/, config resolve
_BASE = Path(__file__).resolve().parents[5]
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

from apps.library.models   import Document        # noqa: E402
from apps.ingestion.models import IngestionJob   # noqa: E402
from retrieval.bm25_store  import BM25_DB_PATH, upsert_chunks, upsert_parents  # noqa: E402
from ingestion.embedder    import embed_chunks, get_model                       # noqa: E402
from ingestion.indexer     import index_chunks                                  # noqa: E402

CHUNKS_DIR = _BASE / 'data' / 'chunks_inspect'
DATA_DIR   = _BASE / 'data'

# Human-readable display names per file stem. The raw file stems make
# unwieldy card titles (e.g. Bahrain_PDPA_Order_43_2022_Technical_…) that
# overflow the regulation card layout and make buttons hard to reach. This
# map uses the same names the original bulk_ingest hardcoded list used.
# Files not in this map fall back to a stem-cleanup heuristic.
_NAME_OVERRIDES = {
    'Bahrain_PDPL_Law_30_2018':                                  'Personal Data Protection Law 30/2018',
    'Bahrain_PDPA_Order_42_2022_Transfer_Personal_Data_Outside': 'PDPA Ministerial Order 42/2022',
    'Bahrain_PDPA_Order_43_2022_Technical_Organisational_Measures': 'PDPA Ministerial Order 43/2022',
    'Bahrain_PDPA_Order_44_2022_Notifications_Authorisations':   'PDPA Ministerial Order 44/2022',
    'Bahrain_PDPA_Order_45_2022_Sensitive_Personal_Data':        'PDPA Ministerial Order 45/2022',
    'Bahrain_PDPA_Order_46_2022_Data_Protection_Guardian_DPO':   'PDPA Ministerial Order 46/2022',
    'Bahrain_PDPA_Order_47_2022_DPO_Fees':                       'PDPA Ministerial Order 47/2022 (DPO Fees)',
    'Bahrain_PDPA_Order_48_2022_Consent_Processing_Conditions':  'PDPA Ministerial Order 48/2022',
    'Bahrain_PDPA_Order_49_2022_Complaints_to_Authority':        'PDPA Ministerial Order 49/2022',
    'Bahrain_PDPA_Order_50_2022_Criminal_Proceedings_Data':      'PDPA Ministerial Order 50/2022',
    'Bahrain_PDPA_Order_51_2022_Public_Personal_Data_Registers': 'PDPA Ministerial Order 51/2022',
    'Bahrain_CBB_OM_Volume1_Cyber_Security_Extract':             'CBB Cyber Security Module Volume 1',
    'India_DPDP_Act_2023':                                       'Digital Personal Data Protection Act 2023',
    'India_DPDP_Rules_2025':                                     'Digital Personal Data Protection Rules 2025',
    'India_IT_Act_2000':                                         'Information Technology Act 2000',
    'India_PMLA_Act_2002_Section_12_Extract':                    'PMLA Act 2002 (Section 12 Extract)',
    'India_RBI_Cybersecurity_Framework_Banks':                   'RBI Cybersecurity Framework for Banks',
    'India_RBI_Information_Technology_Governance_Risk_Controls_Assurance_Practices_Directions_2023': 'RBI IT Governance Risk Controls Directions 2023',
    'India_RBI_KYC_2nd_Amendment':                               'RBI KYC Master Direction 2nd Amendment',
    'India_RBI_KYC_Master_Direction':                            'RBI KYC Master Direction',
    'India_RBI_Outsourcing_of_Information_Technology_Services_Directions_2023': 'RBI Outsourcing of IT Services Directions 2023',
    'India_RBI_Payment_Data_Localisation_Circular_2018':         'RBI Payment Data Localisation Circular 2018',
    'CYBERSECURITY FRAMEWORK':                                   'Kuwait Cybersecurity Framework',
    'Kuwait_CBK_Bank_Customer_Protection_Guide_October_2025':    'CBK Bank Customer Protection Guide 2025',
    'Kuwait_CBK_CORF_Cyber_Operational_Resilience_Framework_December_2025': 'CBK Cyber Operational Resilience Framework 2025',
    'Kuwait_CITRA_Cloud_Computing_Regulatory_Framework_2021':    'CITRA Cloud Computing Regulatory Framework 2021',
    'Kuwait_CITRA_User_Protection_Privacy_Rules_Regulation':     'CITRA User Protection and Privacy Rules',
    'Kuwait_Cybercrime_Law_63_2015':                             'Kuwait Cybercrime Law No. 63/2015',
    'Kuwait_DPPR_Administrative_Decision_26_2024':               'DPPR Administrative Decision 26/2024',
    'Kuwait_Law_20_2014_Electronic_Transactions':                'Electronic Transactions Law 20/2014',
    'Resolution-No-42-On-Data-Privacy-Protection-Regulation':    'Data Privacy Protection Regulation Resolution 42',
    'BBK-CSD-002_Customer_Data_Handling_Procedure_CONTRADICTORY':'BBK Customer Data Handling Procedure v1 (CSD-002)',
    'BBK-Data-Privacy-Statement-Final-and-Approved-by-BoD-1':    'BBK Data Privacy Statement (Board Approved)',
    'BBK-DSR-003_Data_Subject_Rights_Procedure_PARTIAL':         'BBK Data Subject Rights Procedure v1 (DSR-003)',
    'BBK-GDL-011_Third_Party_Data_Sharing_Guideline_VAGUE':      'BBK Third Party Data Sharing Guideline v1 (GDL-011)',
    'BBK-GOV-003_Data_Governance_Framework_Policy':              'BBK Data Governance Framework Policy v1 (GOV-003)',
    'BBK-LGL-001_Data_Privacy_Protection_Policy':                'BBK Data Privacy Protection Policy v1 (LGL-001)',
    'BBK-OPS-012-BH_Data_Handling_SOP_Bahrain_Branch':           'BBK Data Handling SOP - Bahrain Branch (OPS-012-BH)',
    'BBK-OPS-012-IN_Data_Handling_SOP_India_Branch':             'BBK Data Handling SOP - India Branch (OPS-012-IN)',
    'BBK-OPS-012-KW_Data_Handling_SOP_Kuwait_Branch':            'BBK Data Handling SOP - Kuwait Branch (OPS-012-KW)',
    'BBK-PROC-007_Third_Party_Vendor_Data_Processing_Policy':    'BBK Third Party Vendor Data Processing Policy v1 (PROC-007)',
    'BBK-PROC-012_Security_Incident_Response_SOP':               'BBK Security Incident Response SOP v1 (PROC-012)',
    'BBK-RET-005_Retention_Disposal_Policy_OUTDATED':            'BBK Retention and Disposal Policy v1 (RET-005)',
}


def _human_name(stem: str, regulation_name: str | None) -> str:
    """clean display name. prefer the override map; fall back to stem
    cleanup with prefix-stripping."""
    if stem in _NAME_OVERRIDES:
        return _NAME_OVERRIDES[stem]
    import re
    s = re.sub(r'^(Bahrain|India|Kuwait|BBK)[_-]', '', stem)
    s = s.replace('_', ' ').replace('-', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s or (regulation_name or stem)

# jurisdiction string in the chunks → Document.jurisdiction code
_JUR_MAP = {
    'bahrain': Document.BAHRAIN,
    'india':   Document.INDIA,
    'kuwait':  Document.KUWAIT,
    'bbk':     Document.BBK,
}

# doc_type string in the chunks → Document.doc_type code
_TYPE_MAP = {
    'regulation': Document.REGULATION,
    'regulations': Document.REGULATION,
    'policy':     Document.POLICY,
    'policies':   Document.POLICY,
    'internal_policy': Document.POLICY,
}


def _load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                # skip malformed but report
                print(f'  WARN skipping line in {path.name}: {e}')
    return out


def _find_source_file(doc_title: str, jurisdiction: str) -> Path | None:
    """Return the source PDF/DOCX in data/regulations/* or data/internal_policies/."""
    candidates = []
    if jurisdiction == 'bbk':
        candidates.append(DATA_DIR / 'internal_policies')
    else:
        candidates.append(DATA_DIR / 'regulations' / jurisdiction)
        candidates.append(DATA_DIR / 'regulations')   # fallback (some files at top level)

    for root in candidates:
        if not root.exists():
            continue
        for ext in ('.pdf', '.docx', '.txt', '.md'):
            for p in root.rglob(f'{doc_title}{ext}'):
                return p
    return None


class Command(BaseCommand):
    help = ('Restore corpus from pre-cleaned chunks in data/chunks_inspect/. '
            'Embeds + indexes every chunk and creates matching Document rows.')

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                             help='Persist the restored corpus.')
        parser.add_argument('--wipe-first', action='store_true',
                             help='Clear BM25 + ChromaDB + Documents before '
                                  'restoring. Default is to upsert on top of '
                                  'whatever is currently there.')

    def handle(self, *args, apply, wipe_first, **kwargs):
        if not CHUNKS_DIR.exists():
            self.stdout.write(self.style.ERROR(
                f'data/chunks_inspect/ not found at {CHUNKS_DIR}'
            ))
            return

        jsonls = sorted(CHUNKS_DIR.glob('*.chunks.jsonl'))
        self.stdout.write(self.style.NOTICE(
            f'Found {len(jsonls)} .chunks.jsonl files in {CHUNKS_DIR}'
        ))
        if not jsonls:
            return

        # 1. Pre-scan: count chunks, infer per-file metadata
        total_lines = 0
        per_file = []
        for path in jsonls:
            chunks = _load_jsonl(path)
            if not chunks:
                self.stdout.write(self.style.WARNING(f'  EMPTY  {path.name}'))
                continue
            first = chunks[0]
            jur = (first.get('jurisdiction') or '').strip().lower()
            doc_type_raw = (first.get('doc_type') or '').strip().lower()
            reg_name = first.get('regulation_name') or first.get('doc_title') or path.stem.replace('.chunks', '')
            doc_title = first.get('doc_title') or path.stem.replace('.chunks', '')
            issuing = first.get('issuing_authority') or ''
            effective_date = first.get('effective_date') or None
            source_url = first.get('source_url') or ''
            n_embed   = sum(1 for c in chunks if not c.get('embed_skip'))
            n_parents = sum(1 for c in chunks if c.get('embed_skip'))
            total_lines += len(chunks)
            per_file.append({
                'path':           path,
                'chunks':         chunks,
                'jurisdiction':   _JUR_MAP.get(jur, Document.OTHER),
                'doc_type':       _TYPE_MAP.get(doc_type_raw, Document.REGULATION),
                'regulation_name':reg_name,
                'doc_title':      doc_title,
                'issuing':        issuing,
                'effective_date': effective_date,
                'source_url':     source_url,
                'n_embed':        n_embed,
                'n_parents':      n_parents,
            })

        self.stdout.write(self.style.NOTICE(
            f'Total chunks across all JSONLs: {total_lines}'
        ))
        embed_total  = sum(f['n_embed']   for f in per_file)
        parent_total = sum(f['n_parents'] for f in per_file)
        self.stdout.write(f'  to embed + index:  {embed_total}')
        self.stdout.write(f'  to parent-store:   {parent_total}')

        if not apply:
            self.stdout.write(self.style.WARNING(
                '\nDry run. Pass --apply to write the restored corpus.'
            ))
            return

        # 2. Optional wipe
        if wipe_first:
            self.stdout.write(self.style.WARNING('\nWiping current indexes…'))
            try:
                con = sqlite3.connect(str(BM25_DB_PATH))
                cur = con.cursor()
                cur.execute('DELETE FROM bm25_index')
                cur.execute('DELETE FROM parent_docstore')
                con.commit()
                con.close()
                self.stdout.write('  BM25 cleared.')
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  BM25 wipe: {e}'))

            try:
                from config import CHROMA_DIR, CHROMA_COLLECTION
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
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'  ChromaDB wipe: {e}'))

            with transaction.atomic():
                d_count, _ = Document.objects.all().delete()
                j_count, _ = IngestionJob.objects.all().delete()
            self.stdout.write(f'  DB rows deleted: docs={d_count}  jobs={j_count}')

        # 3. Load embedding model once for the whole batch
        self.stdout.write('\nLoading embedding model…')
        st_model = get_model()

        # 4. Per-file: embed → index → create Document
        media_docs = Path(settings.MEDIA_ROOT) / 'documents'
        media_docs.mkdir(parents=True, exist_ok=True)

        ok = failed = 0
        for f in per_file:
            self.stdout.write(
                f'\n[{per_file.index(f)+1:>2}/{len(per_file)}]  {f["regulation_name"][:55]:55s}  '
                f'({f["doc_type"]}, {f["jurisdiction"]})'
            )
            try:
                # split chunks
                child_chunks  = [c for c in f['chunks'] if not c.get('embed_skip')]
                parent_chunks = [c for c in f['chunks'] if c.get('embed_skip')]

                # parents: insert into docstore (no embedding)
                if parent_chunks:
                    upsert_parents(parent_chunks)

                # children: embed + index in BM25 + Chroma
                if child_chunks:
                    embeddings = embed_chunks(child_chunks, st_model)
                    upsert_chunks(child_chunks)
                    index_chunks(child_chunks, embeddings)

                # locate source file (for Document.file)
                source = _find_source_file(f['doc_title'], f['chunks'][0].get('jurisdiction','').lower())
                doc_file_rel = ''
                if source and source.exists():
                    dest = media_docs / source.name
                    if not dest.exists():
                        try:
                            shutil.copy2(source, dest)
                        except Exception as e:
                            self.stdout.write(self.style.WARNING(
                                f'      copy failed: {e}'
                            ))
                    doc_file_rel = f'documents/{source.name}'

                # build a human-readable display name from the file stem;
                # raw stems (e.g. Bahrain_PDPA_Order_43_2022_Technical_…) make
                # cards overflow and buttons unreachable.
                display_name = _human_name(f['doc_title'], f['regulation_name'])

                # create or update the Document row, keyed by file stem
                # (chunk_doc_title) since that's the identity the reasoning
                # layer cares about. ``name`` is just the display label.
                doc, created = Document.objects.update_or_create(
                    file=doc_file_rel,
                    defaults={
                        'name':               display_name,
                        'doc_type':           f['doc_type'],
                        'jurisdiction':       f['jurisdiction'],
                        'issuing_authority':  f['issuing'][:255] if f['issuing'] else '',
                        'source_url':         f['source_url'][:500] if f['source_url'] else '',
                        'status':             Document.INDEXED,
                        'chunk_count':        len(child_chunks),
                    },
                )

                self.stdout.write(self.style.SUCCESS(
                    f'      indexed: child={len(child_chunks)} parent={len(parent_chunks)}  '
                    f'doc=#{doc.pk} {"CREATED" if created else "UPDATED"}'
                ))
                ok += 1
            except Exception as exc:
                import traceback; traceback.print_exc()
                self.stdout.write(self.style.ERROR(f'      FAILED: {exc}'))
                failed += 1

        # 5. Summary + verify chunk_count drift between Django and BM25.
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Done. {ok}/{len(per_file)} files restored ({failed} failed).'
        ))
        # Inline recount (was previously delegated to manage.py recount_chunks).
        import sqlite3
        from retrieval.bm25_store import BM25_DB_PATH
        from apps.library.models  import Document
        con = sqlite3.connect(str(BM25_DB_PATH))
        cur = con.cursor()
        cur.execute('SELECT doc_title, COUNT(*) FROM bm25_index GROUP BY doc_title')
        bm25_counts = dict(cur.fetchall())
        con.close()
        applied = 0
        for d in Document.objects.all():
            stem = Path(d.file.name).stem if d.file and d.file.name else ''
            real = bm25_counts.get(stem, 0)
            if d.chunk_count != real:
                d.chunk_count = real
                d.save(update_fields=['chunk_count'])
                applied += 1
        self.stdout.write(f'  chunk_count reconciled on {applied} Documents.')
