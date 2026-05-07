-- 013_multi_doc_structured_queries.sql
-- Extend structured query helpers to accept multiple document IDs.

CREATE OR REPLACE FUNCTION rag.get_chunks_by_page(
    target_user_id  UUID,
    target_page     INT,
    match_count     INT    DEFAULT 20,
    target_doc_id   UUID   DEFAULT NULL,
    target_doc_ids  UUID[] DEFAULT NULL
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
        0.5::FLOAT AS rrf_score,
        embedding
    FROM rag.chunks
    WHERE
        user_id = target_user_id
        AND (
            CASE
                WHEN target_doc_ids IS NOT NULL THEN document_id = ANY(target_doc_ids)
                WHEN target_doc_id  IS NOT NULL THEN document_id = target_doc_id
                ELSE TRUE
            END
        )
        AND (
            metadata->'pages' @> to_jsonb(target_page)
            OR (
                metadata->'pages' IS NULL
                AND (metadata->>'page_number')::int = target_page
            )
        )
    ORDER BY (metadata->>'chunk_index')::int ASC
    LIMIT match_count;
$$;

CREATE OR REPLACE FUNCTION rag.get_chunks_by_section(
    target_user_id  UUID,
    heading_pattern TEXT,
    target_doc_id   UUID   DEFAULT NULL,
    match_count     INT    DEFAULT 20,
    target_doc_ids  UUID[] DEFAULT NULL
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
        0.5::FLOAT AS rrf_score,
        embedding
    FROM rag.chunks
    WHERE
        user_id = target_user_id
        AND (
            CASE
                WHEN target_doc_ids IS NOT NULL THEN document_id = ANY(target_doc_ids)
                WHEN target_doc_id  IS NOT NULL THEN document_id = target_doc_id
                ELSE TRUE
            END
        )
        AND metadata->>'heading' ILIKE '%' || heading_pattern || '%'
    ORDER BY (metadata->>'chunk_index')::int ASC
    LIMIT match_count;
$$;
