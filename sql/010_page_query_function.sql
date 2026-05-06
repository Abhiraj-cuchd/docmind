-- 010_page_query_function.sql
--
-- get_chunks_by_page: direct metadata-filtered retrieval for page queries.
-- Used by the query lambda when the user asks "what is on page N?".
--
-- Matches chunks where the target page appears anywhere in the
-- chunk's "pages" JSONB array — this correctly returns chunks that
-- START on page N, END on page N, or SPAN through page N (i.e. a
-- chunk that begins on page 3 and ends on page 4 is returned for
-- both page 3 and page 4 queries).
--
-- Falls back to matching page_number directly for documents that
-- were ingested with the old per-page chunker (no "pages" array).

CREATE OR REPLACE FUNCTION rag.get_chunks_by_page(
    target_user_id  UUID,
    target_page     INT,
    match_count     INT  DEFAULT 20,
    target_doc_id   UUID DEFAULT NULL
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
        0.5::FLOAT                  AS rrf_score,
        embedding
    FROM rag.chunks
    WHERE
        user_id = target_user_id
        AND (target_doc_id IS NULL OR document_id = target_doc_id)
        AND (
            -- New chunker: match against the pages array
            metadata->'pages' @> to_jsonb(target_page)
            OR
            -- Old chunker fallback: match page_number directly
            (
                metadata->'pages' IS NULL
                AND (metadata->>'page_number')::int = target_page
            )
        )
    ORDER BY (metadata->>'chunk_index')::int ASC
    LIMIT match_count;
$$;
