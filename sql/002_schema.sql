-- 002_schema.sql
-- Creates a dedicated schema named 'rag' to house all project tables.

-- CONCEPT: PostgreSQL organises tables into namespaces called schemas.
-- The default schema is called 'public' — everything goes there unless
-- you say otherwise. Creating a separate 'rag' schema means:
--   1. Your tables are clearly separated from Supabase's internal tables
--   2. You can grant/revoke access to the entire schema in one command
--   3. If you ever add a second project to the same Supabase instance,
--      there's no naming collision

CREATE SCHEMA IF NOT EXISTS rag;

-- CONCEPT: GRANT USAGE lets the built-in Supabase roles (anon and
-- authenticated) see that the schema exists and access objects inside it.
-- Without this, RLS policies and auth.uid() calls won't work correctly
-- because the roles can't even see the schema.
GRANT USAGE ON SCHEMA rag TO anon, authenticated, service_role;

-- This makes future tables in the rag schema automatically accessible
-- to these roles — so you don't have to GRANT permissions on every
-- new table individually.
ALTER DEFAULT PRIVILEGES IN SCHEMA rag
    GRANT ALL ON TABLES TO anon, authenticated, service_role;