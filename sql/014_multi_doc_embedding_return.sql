-- 014_multi_doc_embedding_return.sql
-- Return embeddings from multi-doc hybrid search for MMR.

DROP FUNCTION IF EXISTS rag.hybrid_search_multi_doc(vector, text, uuid, uuid[], integer);

CREATE OR REPLACE FUNCTION rag.hybrid_search_multi_doc(
  query_embedding  VECTOR(1024),
  query_text       TEXT,
  target_user_id   UUID,
  doc_ids          UUID[],
  match_count      INT DEFAULT 10
)
RETURNS TABLE (
  id          UUID,
  content     TEXT,
  metadata    JSONB,
  document_id UUID,
  rrf_score   FLOAT,
  embedding   VECTOR(1024)
)
LANGUAGE sql STABLE
SECURITY INVOKER
AS $$
  WITH vr AS (
    SELECT id, content, metadata, document_id, embedding,
           ROW_NUMBER() OVER (ORDER BY embedding <=> query_embedding) AS rank
    FROM   rag.chunks
    WHERE  user_id     = target_user_id
      AND  document_id = ANY(doc_ids)
    ORDER BY embedding <=> query_embedding
    LIMIT 20
  ),
  kr AS (
    SELECT id, content, metadata, document_id, embedding,
           ROW_NUMBER() OVER (
             ORDER BY ts_rank(fts, plainto_tsquery('english', query_text)) DESC
           ) AS rank
    FROM   rag.chunks
    WHERE  user_id     = target_user_id
      AND  document_id = ANY(doc_ids)
      AND  fts @@ plainto_tsquery('english', query_text)
    ORDER BY ts_rank(fts, plainto_tsquery('english', query_text)) DESC
    LIMIT 20
  )
  SELECT
    COALESCE(vr.id,          kr.id)          AS id,
    COALESCE(vr.content,     kr.content)     AS content,
    COALESCE(vr.metadata,    kr.metadata)    AS metadata,
    COALESCE(vr.document_id, kr.document_id) AS document_id,
    (COALESCE(1.0 / (60 + vr.rank), 0) +
     COALESCE(1.0 / (60 + kr.rank), 0))     AS rrf_score,
    COALESCE(vr.embedding,   kr.embedding)  AS embedding
  FROM vr FULL OUTER JOIN kr ON vr.id = kr.id
  ORDER BY rrf_score DESC
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION rag.hybrid_search_multi_doc TO service_role;
