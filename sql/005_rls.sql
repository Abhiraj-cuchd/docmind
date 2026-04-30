-- 005_rls.sql — RLS Policy 1: user_profiles
-- A user can only read and write their own profile row.

-- CONCEPT: ENABLE ROW LEVEL SECURITY turns the security guard on
-- for this table. Once enabled, ALL queries against this table
-- are filtered through the policies below — no exceptions.
-- Even a direct database connection respects RLS unless the
-- connecting role is a superuser.

ALTER TABLE rag.user_profiles ENABLE ROW LEVEL SECURITY;

-- CONCEPT: FOR ALL means this policy applies to SELECT, INSERT,
-- UPDATE, and DELETE in one go.
-- USING (auth.uid() = id) is the filter condition.
-- auth.uid() is a Supabase function that returns the UUID of the
-- currently authenticated user extracted from their JWT token.
-- So this policy says: "you can only touch rows where the id
-- column matches your own user ID."

CREATE POLICY "users see own profile"
    ON rag.user_profiles
    FOR ALL
    USING (auth.uid() = id);


-- RLS Policy 2: documents
-- A user can only see documents they uploaded.

ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users see own documents"
    ON rag.documents
    FOR ALL
    USING (auth.uid() = user_id);


-- RLS Policy 3: chunks
-- A user can only see chunks that belong to their documents.
-- This is the most queried table in the entire system —
-- every single search hits this table. RLS adds negligible
-- overhead here because we also have the user_id B-tree index
-- from 004_indexes.sql — the filter is instant.

ALTER TABLE rag.chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users see own chunks"
    ON rag.chunks
    FOR ALL
    USING (auth.uid() = user_id);



-- RLS Policy 4: conversations
-- A user can only see their own conversation threads.

ALTER TABLE rag.conversations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users see own conversations"
    ON rag.conversations
    FOR ALL
    USING (auth.uid() = user_id);



-- RLS Policy 5: messages
-- A user can only see messages from their own conversations.

ALTER TABLE rag.messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY "users see own messages"
    ON rag.messages
    FOR ALL
    USING (auth.uid() = user_id);