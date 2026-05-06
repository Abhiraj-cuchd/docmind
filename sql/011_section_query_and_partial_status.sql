-- 011_section_query_and_partial_status.sql

-- 1. Add 'partial' to the documents.status CHECK constraint.
--    'partial' means some windows ingested successfully but at least one
--    window failed (e.g. Lambda timeout on a 400-page doc). The document
--    is searchable for the pages that were indexed.

ALTER TABLE rag.documents
  DROP CONSTRAINT IF EXISTS documents_status_check;

ALTER TABLE rag.documents
  ADD CONSTRAINT documents_status_check
    CHECK (status IN ('processing', 'indexing', 'ready', 'failed', 'partial'));


-- 2. get_chunks_by_section: retrieves chunks by heading/section name.
--    Enables queries like "what does section 3 say?" or
--    "explain the binary search section".
--    Uses ILIKE for case-insensitive partial match on the heading field.

CREATE OR REPLACE FUNCTION rag.get_chunks_by_section(
    target_user_id  UUID,
    heading_pattern TEXT,
    target_doc_id   UUID DEFAULT NULL,
    match_count     INT  DEFAULT 20
)
RETURNS TABLE (
    id          UUID,
    content     TEXT,
    metadata    JSONB,
    rrf_score   FLOAT,
    embedding   VECTOR(1024)
)
LANGUAGE SQL STABLE AS $$
    SELECT
        id,
        content,
        metadata,
        0.5::FLOAT      AS rrf_score,
        embedding
    FROM rag.chunks
    WHERE
        user_id = target_user_id
        AND (target_doc_id IS NULL OR document_id = target_doc_id)
        AND metadata->>'heading' ILIKE '%' || heading_pattern || '%'
    ORDER BY (metadata->>'chunk_index')::int ASC
    LIMIT match_count;
$$;


-- 3. GIN index on metadata for efficient JSONB containment queries
--    used by get_chunks_by_page (pages @> target_page).
--    If this index already exists from a previous migration, the
--    IF NOT EXISTS guard prevents an error.

CREATE INDEX IF NOT EXISTS idx_chunks_metadata_gin
    ON rag.chunks USING GIN (metadata);
