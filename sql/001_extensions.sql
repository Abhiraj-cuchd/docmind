-- 001_extensions.sql
-- Enables the pgvector extension which adds the VECTOR(n) data type
-- and the <=> cosine distance operator used for semantic search.
-- Must be run before any other file.

CREATE EXTENSION IF NOT EXISTS vector;