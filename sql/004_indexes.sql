-- ============================================================
-- 004_indexes.sql
-- Creates all indexes for the rag schema.
-- Run this after 003_tables.sql.
-- ============================================================


-- ============================================================
-- INDEX 1 — HNSW vector index on chunks.embedding
-- The most important index in the project.
-- Makes semantic similarity search fast at any scale.
-- ============================================================

-- CONCEPT: HNSW (Hierarchical Navigable Small World) builds a
-- multi-layered graph of vectors. Imagine a city with highways,
-- main roads, and side streets. To find the nearest vector to your
-- query, you start on the highway layer (few nodes, big jumps),
-- narrow down to main roads, then to side streets — arriving at
-- the answer without ever checking every single point.
-- This beats brute force search at any corpus size above ~10k vectors
-- and unlike IVFFlat, it never needs a REINDEX as new chunks are added.

-- m = number of bidirectional connections per node in the graph.
--     Higher m = better recall, more memory usage.
--     16 is the universally recommended default.

-- ef_construction = how carefully the graph is built during indexing.
--     Higher = more accurate graph, slower initial build.
--     64 is the standard default — right balance for most use cases.

-- vector_cosine_ops = use cosine distance as the similarity measure.
--     Standard for text embeddings. Score near 0 = similar, near 2 = opposite.

CREATE INDEX chunks_embedding_idx
    ON rag.chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- ============================================================
-- INDEX 2 — GIN index on chunks.fts
-- Makes keyword (BM25-style) search fast.
-- ============================================================

-- CONCEPT: GIN stands for Generalised Inverted Index.
-- The fts column contains a pre-processed list of stemmed words
-- from each chunk's content (e.g. "running" → "run").
-- A GIN index builds a reverse lookup table:
--     word → [row1, row4, row9 ...]
-- So "find all chunks containing transformer" becomes a direct
-- lookup instead of scanning every row in the table.
-- Without this, keyword search is O(n). With it, near O(1).

CREATE INDEX chunks_fts_idx
    ON rag.chunks
    USING GIN (fts);


-- ============================================================
-- INDEX 3 — B-tree index on chunks.user_id
-- Every search query filters by user_id first (data isolation).
-- This makes that filter instant.
-- ============================================================

-- CONCEPT: Without this index, "give me all chunks for user X"
-- scans the entire chunks table — all 60,000 rows across all users.
-- A B-tree index on user_id lets PostgreSQL jump directly to
-- that user's rows. Critical once you have more than a handful of users.

CREATE INDEX chunks_user_id_idx
    ON rag.chunks (user_id);


-- ============================================================
-- INDEX 4 — B-tree index on documents.user_id
-- Makes the "show me my uploaded documents" query instant.
-- ============================================================

CREATE INDEX documents_user_id_idx
    ON rag.documents (user_id);


-- ============================================================
-- INDEX 5 — B-tree index on conversations.user_id
-- Makes loading the conversation sidebar instant.
-- ============================================================

-- CONCEPT: The sidebar shows all conversations for the logged-in
-- user sorted by updated_at. Without this index, PostgreSQL scans
-- ALL conversations from ALL users to find the ones belonging to
-- the current user. With it, direct lookup regardless of total
-- conversation count in the system.

CREATE INDEX conversations_user_id_idx
    ON rag.conversations (user_id);


-- ============================================================
-- INDEX 6 — B-tree index on messages.conversation_id
-- Makes loading chat history fast.
-- ============================================================

-- CONCEPT: Chat history means "give me all messages in conversation X
-- ordered by created_at". Without this index that's a full scan of
-- the entire messages table. With it, PostgreSQL jumps directly to
-- that conversation's messages — instant regardless of how many
-- total messages exist across all users.

CREATE INDEX messages_conversation_id_idx
    ON rag.messages (conversation_id);


-- ============================================================
-- OPTIONAL RUNTIME TUNING (do not run now — for reference only)
-- ============================================================

-- CONCEPT: ef_search controls how thoroughly HNSW searches at
-- query time. Higher = better recall, slightly slower.
-- Default is 40. The ef_construction value (64) is the ceiling —
-- setting ef_search above 64 gives no additional benefit.
-- You can set this per session in your Lambda before running
-- hybrid_search if you ever need to trade speed for accuracy:
--
--     SET hnsw.ef_search = 40;
--
-- Leave it at default for now — it is more than sufficient
-- for a corpus under 1M chunks.


-- ============================================================
-- VERIFICATION — run this after all indexes are created
-- ============================================================

-- SELECT tablename, indexname
-- FROM pg_indexes
-- WHERE schemaname = 'rag'
-- ORDER BY tablename, indexname;

-- Expected output:
-- chunks          | chunks_embedding_idx
-- chunks          | chunks_fts_idx
-- chunks          | chunks_user_id_idx
-- conversations   | conversations_user_id_idx
-- documents       | documents_user_id_idx
-- messages        | messages_conversation_id_idx