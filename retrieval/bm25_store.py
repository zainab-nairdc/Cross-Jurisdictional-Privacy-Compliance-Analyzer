# bm25_store.py
# the keyword-search side of retrieval, backed by sqlite fts5.
#
# why sqlite instead of an in-memory bm25 library:
#   - survives process restarts. an in-memory index would have to re-read the
#     whole corpus every time the service starts.
#   - new docs ingested at runtime are searchable right away — no rebuild step.
#   - filtering by jurisdiction / doc_type happens in the WHERE clause, not as
#     a slow post-filter pass over results.
#   - fts5's bm25() ranking is built in, no extra library needed.
#
# this file also holds the parent docstore (further down) — a separate sqlite
# table for oversized "parent" chunks. retrieval pulls them by id when it
# needs the surrounding context for a top hit. parents are NOT in the fts5
# index (would double-match content their own children already cover) and NOT
# in chroma (the embedder would truncate them to 512 tokens and produce
# misleading partial vectors).

import re
import sqlite3
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import CHROMA_DIR, JURISDICTION_NORM

BM25_DB_PATH = CHROMA_DIR / "bm25.db"

# Token extractor for queries. Word-boundary regex grabs alphanumeric runs of
# 3+ chars and discards punctuation that would otherwise leak into the FTS5
# MATCH string ("consent;" -> empty MATCH term).
_QUERY_TOKEN_RE = re.compile(r"\b\w{3,}\b", re.UNICODE)

# the fts5 schema. only `content` is actually full-text indexed. the other
# columns are UNINDEXED — they ride along for retrieval but don't bloat the
# inverted index, and they're cheap to use as WHERE-clause filters after the
# MATCH narrows down the result set.
_CREATE_TABLE = """
    CREATE VIRTUAL TABLE IF NOT EXISTS bm25_index USING fts5(
        node_id          UNINDEXED,
        content,
        jurisdiction     UNINDEXED,
        doc_type         UNINDEXED,
        doc_title        UNINDEXED,
        regulation_name  UNINDEXED,
        article_ref      UNINDEXED,
        tokenize = 'unicode61'
    )
"""

_INSERT = (
    "INSERT INTO bm25_index"
    "(node_id, content, jurisdiction, doc_type, doc_title, regulation_name, article_ref)"
    " VALUES (?,?,?,?,?,?,?)"
)


def _connect() -> sqlite3.Connection:
    """open a connection. row_factory makes rows act like dicts."""
    conn = sqlite3.connect(str(BM25_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init(conn: sqlite3.Connection) -> None:
    """make sure the fts5 table exists. cheap to call repeatedly."""
    conn.execute(_CREATE_TABLE)


def upsert_chunks(chunks: list[dict]) -> None:
    """write chunks into the fts5 index. safe to re-run on the same chunks —
    we delete-then-insert to mimic upsert (fts5 has no native UPSERT).

    Silently skips rows that are missing node_id or content so a malformed
    caller can't half-insert a batch; bad rows are reported via the print
    line so the operator can investigate."""
    rows: list[tuple] = []
    skipped = 0
    for c in chunks:
        nid = c.get("node_id")
        body = c.get("content")
        if not nid or not body:
            skipped += 1
            continue
        rows.append((
            nid,
            body,
            c.get("jurisdiction", ""),
            c.get("doc_type", ""),
            c.get("doc_title", ""),
            c.get("regulation_name", ""),
            c.get("article_ref", ""),
        ))
    if skipped:
        print(f"[bm25_store.upsert_chunks] skipped {skipped} row(s) missing node_id/content")
    if not rows:
        return
    with _connect() as conn:
        _init(conn)
        # bulk-delete every id we're about to insert, then bulk-insert. one
        # round-trip beats a per-row delete+insert by a lot.
        ids = [row[0] for row in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM bm25_index WHERE node_id IN ({placeholders})", ids)
        conn.executemany(_INSERT, rows)


def delete_by_doc_title(doc_title: str) -> int:
    """Remove every stored row for a document — leaves, parents, and tags.

    Needed for deletes and re-ingests: upsert only overwrites by node_id, so a
    document whose chunk boundaries shift (e.g. after a loader/chunker change)
    leaves its old chunks behind as orphans, and a plain doc.delete() never
    touches the search stores at all. Returns the number of leaf chunks removed.
    Parent/tag cleanup is best-effort (those tables may not exist yet).
    """
    if not doc_title:
        return 0
    with _connect() as conn:
        _init(conn)
        node_ids = [
            r[0] for r in conn.execute(
                "SELECT node_id FROM bm25_index WHERE doc_title = ?", (doc_title,)
            ).fetchall()
        ]
        removed = conn.execute(
            "DELETE FROM bm25_index WHERE doc_title = ?", (doc_title,)
        ).rowcount
        try:
            conn.execute("DELETE FROM parent_docstore WHERE doc_title = ?", (doc_title,))
        except sqlite3.OperationalError:
            pass
        if node_ids:
            try:
                ph = ",".join("?" * len(node_ids))
                conn.execute(f"DELETE FROM chunk_tags WHERE node_id IN ({ph})", node_ids)
            except sqlite3.OperationalError:
                pass
    return removed


# parent docstore
# stores the full body of oversized chunks so retrieval can pull them back
# by id for context expansion. plain table, no fts — we look these up by
# primary key, not by search.

_CREATE_PARENT_TABLE = """
    CREATE TABLE IF NOT EXISTS parent_docstore (
        node_id         TEXT PRIMARY KEY,
        chunk_id        TEXT,
        content         TEXT,
        doc_title       TEXT,
        hierarchy_path  TEXT,
        section_title   TEXT,
        article_ref     TEXT,
        jurisdiction    TEXT
    )
"""


def upsert_parents(parents: list[dict]) -> None:
    """write parent chunks into the docstore. INSERT OR REPLACE handles
    re-ingestion.

    Silently skips rows missing node_id or content (same defensive shape as
    upsert_chunks) so a malformed caller can't half-insert a batch."""
    if not parents:
        return
    rows: list[tuple] = []
    skipped = 0
    for c in parents:
        nid = c.get("node_id")
        body = c.get("content")
        if not nid or not body:
            skipped += 1
            continue
        rows.append((
            nid,
            c.get("chunk_id", ""),
            body,
            c.get("doc_title", ""),
            c.get("hierarchy_path", ""),
            c.get("section_title", ""),
            c.get("article_ref", ""),
            c.get("jurisdiction", ""),
        ))
    if skipped:
        print(f"[bm25_store.upsert_parents] skipped {skipped} row(s) missing node_id/content")
    if not rows:
        return
    with _connect() as conn:
        conn.execute(_CREATE_PARENT_TABLE)
        conn.executemany(
            "INSERT OR REPLACE INTO parent_docstore VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def get_parent(node_id: str) -> dict | None:
    """grab a parent chunk by id. returns None if it doesn't exist (or if the
    db hasn't been created yet — the retriever calls this before knowing
    whether ingestion has run)."""
    if not BM25_DB_PATH.exists():
        return None
    try:
        with _connect() as conn:
            conn.execute(_CREATE_PARENT_TABLE)
            row = conn.execute(
                "SELECT * FROM parent_docstore WHERE node_id = ?", (node_id,)
            ).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row else None


def parent_count() -> int:
    """how many parent chunks are stored. used by the admin status panel."""
    if not BM25_DB_PATH.exists():
        return 0
    try:
        with _connect() as conn:
            conn.execute(_CREATE_PARENT_TABLE)
            return conn.execute("SELECT COUNT(*) FROM parent_docstore").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


# chunk taxonomy tags
# kept as a sidecar table rather than additional fts5 columns: the fts5
# virtual-table schema can't be ALTERed in place without dropping and
# re-indexing the entire corpus, and tags are filter-only (no full-text
# search needed). taxonomy filtering happens via subquery in search_bm25.

_CREATE_TAGS_TABLE = """
    CREATE TABLE IF NOT EXISTS chunk_tags (
        node_id      TEXT PRIMARY KEY,
        topic        TEXT NOT NULL,
        subcategory  TEXT NOT NULL DEFAULT '',
        confidence   REAL NOT NULL DEFAULT 0.0,
        tagged_at    TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""

_CREATE_TAGS_TOPIC_INDEX = """
    CREATE INDEX IF NOT EXISTS idx_chunk_tags_topic ON chunk_tags(topic, subcategory)
"""


def upsert_chunk_tags(rows: list[dict]) -> int:
    """write taxonomy tags for chunks. each row needs node_id + topic; subcategory
    and confidence default to '' / 0.0. returns the number of rows written."""
    if not rows:
        return 0
    with _connect() as conn:
        conn.execute(_CREATE_TAGS_TABLE)
        conn.execute(_CREATE_TAGS_TOPIC_INDEX)
        conn.executemany(
            "INSERT OR REPLACE INTO chunk_tags (node_id, topic, subcategory, confidence) "
            "VALUES (?, ?, ?, ?)",
            [(r["node_id"], r["topic"], r.get("subcategory", ""), float(r.get("confidence", 0.0)))
             for r in rows],
        )
    return len(rows)


def chunk_tag_stats() -> dict:
    """summary stats for the admin/status UI. counts per topic + total tagged
    + total untagged."""
    if not BM25_DB_PATH.exists():
        return {"total": 0, "tagged": 0, "untagged": 0, "by_topic": {}}
    try:
        with _connect() as conn:
            conn.execute(_CREATE_TAGS_TABLE)
            total = conn.execute("SELECT COUNT(*) FROM bm25_index").fetchone()[0]
            tagged = conn.execute("SELECT COUNT(*) FROM chunk_tags").fetchone()[0]
            by_topic = dict(conn.execute(
                "SELECT topic, COUNT(*) FROM chunk_tags GROUP BY topic ORDER BY 2 DESC"
            ).fetchall())
    except sqlite3.OperationalError:
        return {"total": 0, "tagged": 0, "untagged": 0, "by_topic": {}}
    return {"total": total, "tagged": tagged, "untagged": total - tagged, "by_topic": by_topic}


def topics_for_docs(
    doc_titles:   list[str],
    jurisdiction: str | None = None,
) -> list[tuple[str, int]]:
    """enumerate (topic, count) pairs for chunks of the given documents.
    metadata-only — does NOT run a semantic search. used by the policy-driven
    auto-routing (map_policy_coverage_auto) to discover what topics a policy
    actually covers before retrieval. results are sorted by count desc, with
    UNCLASSIFIED filtered out so we don't dispatch a mapping pass against
    chunks the classifier couldn't categorise."""
    if not doc_titles or not BM25_DB_PATH.exists():
        return []
    placeholders = ",".join("?" * len(doc_titles))
    sql = f"""
        SELECT t.topic, COUNT(*) AS n
        FROM   bm25_index b
        JOIN   chunk_tags t ON t.node_id = b.node_id
        WHERE  b.doc_title IN ({placeholders})
        {"AND b.jurisdiction = ?" if jurisdiction else ""}
        AND    t.topic != 'unclassified'
        GROUP BY t.topic
        ORDER BY n DESC
    """
    params: list = list(doc_titles)
    if jurisdiction:
        params.append(jurisdiction)
    try:
        with _connect() as conn:
            conn.execute(_CREATE_TAGS_TABLE)
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(r[0], r[1]) for r in rows]


def topics_for_jurisdiction(jurisdiction: str) -> dict[str, int]:
    """{topic: count} of classified chunks in a jurisdiction. used by the
    auto-routing pre-flight so we don't dispatch a per-topic mapping pass
    against a jurisdiction that has zero classified chunks for that topic
    (e.g. routing a retention policy against Bahrain when Bahrain has no
    retention-tagged regulation chunks). preserves the methodological
    point: the report shouldn't fabricate a verdict for a topic the
    regulation doesn't address."""
    if not BM25_DB_PATH.exists():
        return {}
    sql = """
        SELECT t.topic, COUNT(*) AS n
        FROM   bm25_index b
        JOIN   chunk_tags t ON t.node_id = b.node_id
        WHERE  b.jurisdiction = ?
        AND    t.topic != 'unclassified'
        GROUP BY t.topic
    """
    try:
        with _connect() as conn:
            conn.execute(_CREATE_TAGS_TABLE)
            rows = conn.execute(sql, (jurisdiction,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r[0]: r[1] for r in rows}


def untagged_chunks_for_docs(
    doc_titles:   list[str],
    jurisdiction: str | None = None,
) -> list[dict]:
    """rows from bm25_index that match doc_titles but have no chunk_tags
    entry yet. used by the on-demand classifier backfill in
    map_policy_coverage_auto so we can tag a policy at first use rather
    than requiring a separate ingest-time backfill pass."""
    if not doc_titles or not BM25_DB_PATH.exists():
        return []
    placeholders = ",".join("?" * len(doc_titles))
    sql = f"""
        SELECT b.node_id, b.content, b.doc_title, b.jurisdiction
        FROM   bm25_index b
        LEFT JOIN chunk_tags t ON t.node_id = b.node_id
        WHERE  b.doc_title IN ({placeholders})
        {"AND b.jurisdiction = ?" if jurisdiction else ""}
        AND    t.node_id IS NULL
    """
    params: list = list(doc_titles)
    if jurisdiction:
        params.append(jurisdiction)
    try:
        with _connect() as conn:
            conn.execute(_CREATE_TAGS_TABLE)
            rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []
    return [{"node_id": r[0], "content": r[1], "doc_title": r[2], "jurisdiction": r[3]}
            for r in rows]


def search_bm25(
    query:         str,
    top_k:         int = 20,
    jurisdiction:  str | None = None,
    jurisdictions: list[str] | None = None,
    doc_type:      str | None = None,
    doc_title:     str | None = None,
    doc_titles:    list[str] | None = None,
    topic:         str | None = None,
    subcategory:   str | None = None,
) -> list[dict]:
    """run a keyword search against the fts5 index.

    returns a list of result dicts (id, content, bm25_score, metadata).
    returns [] if the db doesn't exist yet — handy during first-time setup.

    filters: pass `jurisdiction` for a single match, or `jurisdictions` for
    a list (OR'd together). if both are given, the list wins. same applies
    to `doc_title` (str) vs `doc_titles` (list).
    """
    if not BM25_DB_PATH.exists():
        return []

    # split the query into words and OR them together. AND would be too
    # strict for legal text where the same idea has multiple spellings
    # ("minimization" vs "minimisation") and synonyms differ by jurisdiction.
    # Word-boundary regex avoids punctuation leaking into FTS5 MATCH terms
    # ("consent;" used to become an empty match); words < 3 chars are
    # basically stop-words and are skipped.
    tokens = _QUERY_TOKEN_RE.findall(query)
    if not tokens:
        return []
    fts_query = " OR ".join(f'"{t}"' for t in tokens)

    conditions = ["bm25_index MATCH ?"]
    params: list = [fts_query]

    # build the WHERE filters. multi-jurisdiction takes priority if both are
    # given (the API allows it for caller convenience).
    jur_list = jurisdictions or ([jurisdiction] if jurisdiction else None)
    if jur_list:
        normalised = [JURISDICTION_NORM.get(j.lower(), j) for j in jur_list]
        if len(normalised) == 1:
            conditions.append("jurisdiction = ?")
            params.append(normalised[0])
        else:
            placeholders = ",".join("?" * len(normalised))
            conditions.append(f"jurisdiction IN ({placeholders})")
            params.extend(normalised)
    if doc_type:
        conditions.append("doc_type = ?")
        params.append(doc_type)
    # doc_titles (list) takes priority over doc_title (str) — same shape as
    # the jurisdictions vs jurisdiction handling above.
    title_list = doc_titles or ([doc_title] if doc_title else None)
    if title_list:
        if len(title_list) == 1:
            conditions.append("doc_title = ?")
            params.append(title_list[0])
        else:
            placeholders = ",".join("?" * len(title_list))
            conditions.append(f"doc_title IN ({placeholders})")
            params.extend(title_list)

    # Taxonomy filters: push down via subquery on the chunk_tags side-table.
    # If a filter is requested but no chunks are tagged yet (e.g. first run
    # before backfill), the subquery just narrows to zero rows and the search
    # returns []. That's the correct degenerate behaviour — the caller asked
    # for a tag-scoped search and there is nothing tagged.
    if topic:
        conditions.append("node_id IN (SELECT node_id FROM chunk_tags WHERE topic = ?)")
        params.append(topic)
    if subcategory:
        conditions.append("node_id IN (SELECT node_id FROM chunk_tags WHERE subcategory = ?)")
        params.append(subcategory)

    where = " AND ".join(conditions)
    params.append(top_k)

    try:
        with _connect() as conn:
            _init(conn)
            rows = conn.execute(
                f"""
                SELECT node_id, content, jurisdiction, doc_type, doc_title,
                       regulation_name, article_ref,
                       -bm25(bm25_index) AS score
                FROM   bm25_index
                WHERE  {where}
                ORDER  BY rank
                LIMIT  ?
                """,
                params,
            ).fetchall()
    except sqlite3.OperationalError:
        # either the fts5 query was malformed or the db isn't ready yet.
        # either way, return empty rather than crashing the retriever.
        return []

    return [
        {
            "id":         row["node_id"],
            "content":    row["content"],
            # FTS5's raw bm25() returns negative numbers (lower = better).
            # The SQL above already negates it to give higher-is-better.
            "bm25_score": float(row["score"]),
            "metadata": {
                "node_id":         row["node_id"],
                "jurisdiction":    row["jurisdiction"],
                "doc_type":        row["doc_type"],
                "doc_title":       row["doc_title"],
                "regulation_name": row["regulation_name"],
                "article_ref":     row["article_ref"],
            },
        }
        for row in rows
    ]
