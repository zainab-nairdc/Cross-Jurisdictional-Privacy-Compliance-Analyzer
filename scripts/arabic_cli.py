"""CLI for the isolated Arabic RAG pipeline.

    # 1. PROBE extraction first (Arabic PDF quality is the biggest risk):
    .venv\\Scripts\\python.exe scripts\\arabic_cli.py probe data\\raw\\qatar_pdpl_ar.pdf

    # 2. INGEST into the regulations_ar collection:
    .venv\\Scripts\\python.exe scripts\\arabic_cli.py ingest data\\raw\\qatar_pdpl_ar.pdf \\
        --source qatar_pdpl_ar --law "Qatar PDPL (Law No. 13 of 2016)"

    # 3. ASK (English question -> English answer from the Arabic text):
    .venv\\Scripts\\python.exe scripts\\arabic_cli.py ask "What are the penalties?" --source qatar_pdpl_ar
"""
import sys
import json
import argparse
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")   # Arabic prints on Windows consoles


def cmd_probe(args):
    if args.ocr:
        from arabic.ocr_kraken import ocr_pdf, check_available
        ok, msg = check_available()
        if not ok:
            print("OCR unavailable:", msg); return
        n = args.pages
        text = ocr_pdf(args.pdf, max_pages=n)
        print(f"=== kraken OCR of first {n} page(s) ===")
        print(text[:1200])
    else:
        from arabic.extract import extraction_report
        print(json.dumps(extraction_report(args.pdf), ensure_ascii=False, indent=2))


def cmd_ingest(args):
    from arabic.pipeline import ingest
    if args.ocr:
        print("Running kraken OCR (CPU — this takes a few minutes for a full doc)…")
    res = ingest(args.pdf, source=args.source, law_name=args.law,
                 min_arabic_ratio=args.min_arabic_ratio, use_ocr=args.ocr)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("no_article_headings"):
        print("\n[!] No 'مادة/المادة' article headings matched — the whole doc "
              "became ONE chunk. Check the extracted text / article format "
              "(run `probe`) before relying on citations.")


def cmd_ask(args):
    from arabic.query import answer
    res = answer(args.question, k=args.k, source=args.source)
    print("Q:", args.question)
    print("\nA:", res["answer"])
    print("\nSources:", ", ".join(res["citations"]))
    if args.show_arabic:
        print("\n--- retrieved Arabic ---")
        for h in res["hits"]:
            print(f"\n[Art. {h.get('article_number')}] (score {h['score']:.3f})")
            print(h["text"][:300])


def main():
    p = argparse.ArgumentParser(description="Arabic RAG pipeline (isolated).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("probe", help="report Arabic extraction quality for a PDF")
    pp.add_argument("pdf")
    pp.add_argument("--ocr", action="store_true", help="use kraken OCR instead of text extraction")
    pp.add_argument("--pages", type=int, default=3, help="pages to OCR in probe mode")
    pp.set_defaults(func=cmd_probe)

    pi = sub.add_parser("ingest", help="extract, chunk, embed and store a PDF")
    pi.add_argument("pdf")
    pi.add_argument("--source", required=True, help="stable id for this document")
    pi.add_argument("--law", default="", help="human-readable law name (for citations)")
    pi.add_argument("--min-arabic-ratio", type=float, default=0.5)
    pi.add_argument("--ocr", action="store_true",
                    help="use kraken OCR (for broken-font PDFs — reads pixels, clean Arabic)")
    pi.set_defaults(func=cmd_ingest)

    pa = sub.add_parser("ask", help="ask a question against the Arabic corpus")
    pa.add_argument("question")
    pa.add_argument("--source", default=None, help="restrict to one document id")
    pa.add_argument("-k", type=int, default=5)
    pa.add_argument("--show-arabic", action="store_true", help="print retrieved Arabic")
    pa.set_defaults(func=cmd_ask)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
