-- Phase 3: Cross-document reasoning
-- Creates the conversation_documents junction table and multi-doc hybrid search function.

-- ── Junction table ──────────────────────────────────────────────────────────
CREATE TABLE rag.conversation_documents (
  conversation_id UUID NOT NULL REFERENCES rag.conversations(id) ON DELETE CASCADE,
  document_id     UUID NOT NULL REFERENCES rag.documents(id)     ON DELETE CASCADE,
  added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (conversation_id, document_id)
);

ALTER TABLE rag.conversation_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_own_conversation_documents"
  ON rag.conversation_documents FOR ALL
  USING (
    auth.uid() = (
      SELECT user_id FROM rag.conversations WHERE id = conversation_id
    )
  );

CREATE INDEX ON rag.conversation_documents (conversation_id);
CREATE INDEX ON rag.conversation_documents (document_id);

-- Allow conversations to be scoped to multiple docs (document_id becomes nullable)
ALTER TABLE rag.conversations ALTER COLUMN document_id DROP NOT NULL;

-- ── Multi-document hybrid search function ──────────────────────────────────
-- Drop-in replacement for hybrid_search_in_document when multiple docs are selected.
-- Filters by document_id = ANY(doc_ids) instead of a single document_id.
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
  rrf_score   FLOAT
)
LANGUAGE sql STABLE
SECURITY INVOKER
AS $$
  WITH vr AS (
    SELECT id, content, metadata, document_id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> query_embedding) AS rank
    FROM   rag.chunks
    WHERE  user_id    = target_user_id
      AND  document_id = ANY(doc_ids)
    ORDER BY embedding <=> query_embedding
    LIMIT 20
  ),
  kr AS (
    SELECT id, content, metadata, document_id,
           ROW_NUMBER() OVER (
             ORDER BY ts_rank(fts, plainto_tsquery('english', query_text)) DESC
           ) AS rank
    FROM   rag.chunks
    WHERE  user_id    = target_user_id
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
     COALESCE(1.0 / (60 + kr.rank), 0))     AS rrf_score
  FROM vr FULL OUTER JOIN kr ON vr.id = kr.id
  ORDER BY rrf_score DESC
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION rag.hybrid_search_multi_doc TO service_role;

-- ── Table grants & PostgREST reload ────────────────────────────────────────
GRANT ALL ON TABLE rag.conversation_documents TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload config';
