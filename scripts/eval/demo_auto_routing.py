"""End-to-end smoke test for the auto-routed policy mapping.

Run from the project root:
    .venv/Scripts/python.exe tests/demo_auto_routing.py

What it does:
    1. Picks the BBK Retention & Disposal policy.
    2. Calls map_policy_coverage_auto against Bahrain.
    3. Prints the discovered topics, the routing decision, and every row
       of the resulting PolicyMappingReport in a readable table.

LLM provider:
    OpenRouter (primary) → Claude Haiku 4.5 by default. Reads
    OPENROUTER_API_KEY from the project's .env. Local Ollama is the
    automatic fallback ONLY if OpenRouter errors (network, auth, etc.) —
    you do NOT need Ollama running for the happy path.

    To change models, edit reasoning/config.py or set:
        $env:REASON_LLM__MODEL = "anthropic/claude-3-5-sonnet"

Other prerequisites:
    - Chroma + bm25 index already built (they are; ingestion ran already).

This script bypasses Django entirely — it's pure reasoning + retrieval, so
it runs the same pipeline the Django mapping view runs in the background,
without any session/MFA/CSRF noise.
"""

import sys, time, traceback
from pathlib import Path

# Make sure the project root is on sys.path so `reasoning`, `retrieval`,
# `config` import as top-level packages no matter where you run from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    from reasoning.workflows  import map_policy_coverage_auto
    from retrieval.bm25_store import topics_for_docs, topics_for_jurisdiction
    from reasoning.taxonomy   import TAXONOMY

    POLICY_TITLE  = "BBK-RET-005_Retention_Disposal_Policy_OUTDATED"
    JURISDICTION  = "Bahrain"

    print("=" * 78)
    print(f"  AUTO-ROUTED POLICY MAPPING — DEMO")
    print(f"  Policy:       {POLICY_TITLE}")
    print(f"  Jurisdiction: {JURISDICTION}")
    print("=" * 78)

    # 1) what the system *thinks* the policy is about
    print("\n[1/3] Topics classified on the policy:")
    pol_topics = topics_for_docs([POLICY_TITLE], jurisdiction="Bbk")
    if not pol_topics:
        print("  (none — first run will classify on demand)")
    for tag, count in pol_topics:
        label = TAXONOMY.get(tag, {}).get("label", tag)
        print(f"  - {label:38s}  ({count} policy chunks)")

    # 2) intersect with what the regulation actually has
    print(f"\n[2/3] Topics with classified clauses in {JURISDICTION}:")
    reg_topics = topics_for_jurisdiction(JURISDICTION)
    pol_tags = {t for t, _ in pol_topics}
    will_map = [(t, c) for t, c in pol_topics if reg_topics.get(t, 0) > 0]
    skipped  = [(t, c) for t, c in pol_topics if reg_topics.get(t, 0) == 0]
    print(f"  Will map ({len(will_map)} topics):  "
          + ", ".join(TAXONOMY.get(t, {}).get('label', t) for t, _ in will_map))
    print(f"  Skipped  ({len(skipped)} topics):  "
          + (", ".join(TAXONOMY.get(t, {}).get('label', t) for t, _ in skipped)
             or "(none)"))

    # 3) actually run the auto-routed mapping (LLM calls happen here)
    print(f"\n[3/3] Running map_policy_coverage_auto — LLM calls in flight…")
    t0 = time.time()
    try:
        report = map_policy_coverage_auto(
            doc_titles_policy=[POLICY_TITLE],
            jurisdiction=JURISDICTION,
            top_k_per_topic=6,
            rerank=True,
        )
    except Exception:
        print("\nFAILED — most common causes:")
        print("  - OPENROUTER_API_KEY missing or rejected (check the .env file)")
        print("  - Network blocked / OpenRouter rate limit / model unavailable")
        print("  - Ollama fallback also unreachable (only relevant if OpenRouter errored)")
        traceback.print_exc()
        sys.exit(1)
    print(f"   done in {time.time() - t0:.1f}s — {len(report.items)} obligation rows\n")

    # 4) pretty-print the report
    print("=" * 78)
    print("  REPORT SUMMARY")
    print("=" * 78)
    print(report.summary or "(no summary)")

    print("\n" + "=" * 78)
    print(f"  OBLIGATION ROWS ({len(report.items)})")
    print("=" * 78)

    icons = {
        "Fully Covered":     "[OK]      ",
        "Covered":           "[OK]      ",
        "Partially Covered": "[PARTIAL] ",
        "Requires Review":   "[REVIEW]  ",
        "Not Covered":       "[GAP]     ",
    }
    for i, item in enumerate(report.items, 1):
        verdict = icons.get(item.coverage_status, "[?]       ")
        print(f"\n[{i:2d}] {verdict} {item.regulatory_obligation[:140]}")
        print(f"     Reg side:    {item.regulation_citation}")
        if item.regulation_evidence:
            print(f'                  "{item.regulation_evidence[:130]}…"')
        print(f"     Policy side: {item.policy_section}")
        if item.policy_excerpt:
            print(f'                  "{item.policy_excerpt[:130]}…"')
        if item.gap_description:
            print(f"     Gap:         {item.gap_description[:200]}")
        if item.remediation_suggestion:
            print(f"     Fix:         {item.remediation_suggestion[:200]}")
        print(f"     Verified citation: {item.citation_verified}   "
              f"Hallucination risk: {item.hallucination_risk:.2f}")

    print("\n" + "=" * 78)
    print(f"  Mapped against topics: {report.query}")
    print("=" * 78)
    print(report.disclaimer)


if __name__ == "__main__":
    main()
