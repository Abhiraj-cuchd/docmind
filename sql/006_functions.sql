-- 006_functions.sql — Function 1: hybrid_search
-- Updates hybrid_search to also return the embedding column.
-- consume_voice_credit is untouched.
CREATE OR REPLACE FUNCTION rag.hybrid_search(
    query_embedding     VECTOR(1024),
    query_text          TEXT,
    target_user_id      UUID,
    match_count         INT DEFAULT 10
)
RETURNS TABLE (
    id          UUID,
    content     TEXT,
    metadata    JSONB,
    rrf_score   FLOAT,
    embedding   VECTOR(1024)   -- ← only addition vs original
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
        WHERE user_id = target_user_id
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
        COALESCE(v.embedding, k.embedding)  AS embedding   -- ← only addition
    FROM vector_results v
    FULL OUTER JOIN keyword_results k ON v.id = k.id
    ORDER BY rrf_score DESC
    LIMIT match_count;
$$;


-- Function 1b: hybrid_search_in_document
-- Same as hybrid_search but scoped to a single document.
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


-- Function 2: consume_voice_credit
-- Atomically decrements voice_credits for a user.
-- Returns TRUE if a credit was consumed, FALSE if none remained.
-- Called by the processor Lambda before every TTS call.

CREATE OR REPLACE FUNCTION rag.consume_voice_credit(
    target_user_id UUID
)
RETURNS BOOLEAN
LANGUAGE plpgsql
-- CONCEPT: SECURITY DEFINER means this function runs with the
-- privileges of the user who CREATED it (the superuser/postgres role)
-- rather than the user who CALLS it. This lets us bypass RLS
-- for this specific write operation — necessary because the Lambda
-- processor connects with the service role, and we want the decrement
-- to work cleanly regardless of the calling context.
SECURITY DEFINER
AS $$
DECLARE
    rows_updated INT;
BEGIN
    -- CONCEPT: This single UPDATE statement is atomic — the check
    -- (voice_credits > 0) and the decrement (voice_credits - 1)
    -- happen in one indivisible database operation.
    -- Without atomicity, this race condition is possible:
    --   Request A reads credits = 1, decides to proceed
    --   Request B reads credits = 1, decides to proceed
    --   Request A decrements → credits = 0
    --   Request B decrements → credits = -1  ← disaster
    -- With this atomic UPDATE, only one of them can satisfy
    -- WHERE voice_credits > 0. The other gets rows_updated = 0
    -- and returns FALSE. The CHECK constraint on the table is
    -- a final backstop that rejects any -1 attempt at DB level.

    UPDATE rag.user_profiles
    SET voice_credits = voice_credits - 1
    WHERE id = target_user_id
      AND voice_credits > 0;

    -- GET DIAGNOSTICS captures how many rows the UPDATE touched.
    -- If 1 row was updated → credit consumed → return TRUE
    -- If 0 rows updated → credits were already 0 → return FALSE
    GET DIAGNOSTICS rows_updated = ROW_COUNT;

    RETURN rows_updated = 1;
END;
$$;


-- Function 3: refund_voice_credit
-- Atomically increments voice_credits for a user.
-- Called by the processor Lambda when TTS fails after a credit was consumed.

CREATE OR REPLACE FUNCTION rag.refund_voice_credit(
    target_user_id UUID
)
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    UPDATE rag.user_profiles
    SET voice_credits = voice_credits + 1
    WHERE id = target_user_id;
END;
$$;