-- 008_conversations_doc_scope.sql
-- Adds document-scoped conversations and doc-specific hybrid search.

ALTER TABLE rag.conversations
    ADD COLUMN IF NOT EXISTS document_id UUID REFERENCES rag.documents(id);

ALTER TABLE rag.conversations
    ADD COLUMN IF NOT EXISTS summary TEXT;

CREATE OR REPLACE FUNCTION rag.hybrid_search_in_document(
    query_embedding     VECTOR(1024),
    query_text          TEXT,
    target_user_id      UUID,
    target_document_id  UUID,
    match_count         INT DEFAULT 10
)
RETURNS TABLE (
    id          UUID,
    content     TEXT,
    metadata    JSONB,
    rrf_score   FLOAT,
    embedding   VECTOR(1024)
)
LANGUAGE SQL
STABLE
AS $$
    WITH vector_results AS (
        SELECT
            id,
            content,
            metadata,
            embedding,
            ROW_NUMBER() OVER (
                ORDER BY embedding <=> query_embedding
            ) AS rank
        FROM rag.chunks
        WHERE
            user_id = target_user_id
            AND document_id = target_document_id
        ORDER BY embedding <=> query_embedding
        LIMIT 20
    ),
    keyword_results AS (
        SELECT
            id,
            content,
            metadata,
            embedding,
            ROW_NUMBER() OVER (
                ORDER BY ts_rank(fts, plainto_tsquery('english', query_text)) DESC
            ) AS rank
        FROM rag.chunks
        WHERE
            user_id = target_user_id
            AND document_id = target_document_id
            AND fts @@ plainto_tsquery('english', query_text)
        LIMIT 20
    )
    SELECT
        COALESCE(v.id, k.id)                AS id,
        COALESCE(v.content, k.content)      AS content,
        COALESCE(v.metadata, k.metadata)    AS metadata,
        (
            COALESCE(1.0 / (60 + v.rank), 0.0) +
            COALESCE(1.0 / (60 + k.rank), 0.0)
        )                                   AS rrf_score,
        COALESCE(v.embedding, k.embedding)  AS embedding
    FROM vector_results v
    FULL OUTER JOIN keyword_results k ON v.id = k.id
    ORDER BY rrf_score DESC
    LIMIT match_count;
$$;
