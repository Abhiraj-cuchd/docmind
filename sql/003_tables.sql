-- 003_tables.sql — Table 1: user_profiles
-- Extends Supabase's built-in auth.users table with app-specific fields.
-- You never insert into auth.users directly — Supabase handles that.
-- This table adds the extra columns your app needs.

CREATE TABLE rag.user_profiles (
    -- CONCEPT: We use the same UUID that Supabase Auth assigned to this
    -- user. That way there's one single ID that works across auth.users,
    -- this table, and every other table. ON DELETE CASCADE means if the
    -- user deletes their account, this row is automatically deleted too.
    id              UUID        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,

    display_name    TEXT,

    -- CONCEPT: voice_credits starts at 3 for every new user.
    -- The CHECK constraint is a hard database-level guarantee that this
    -- number can never go below 0 — even if buggy application code tries
    -- to decrement past zero. It's a safety net below the safety net.
    voice_credits   INT         NOT NULL DEFAULT 3,
    CONSTRAINT voice_credits_non_negative CHECK (voice_credits >= 0),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- Table 2: documents
-- Represents a PDF file uploaded by a user.
-- One user can upload many documents.
-- A document has many chunks (see Table 3).

CREATE TABLE rag.documents (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- CONCEPT: Every table that belongs to a user has a user_id column.
    -- This is what RLS policies check — "does this row's user_id match
    -- the logged-in user?" ON DELETE CASCADE cleans up automatically.
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    filename    TEXT        NOT NULL,

    -- The S3 object key — not the full URL. We store the key and
    -- generate presigned URLs at request time so they never expire
    -- in the database.
    s3_key      TEXT        NOT NULL,

    -- CONCEPT: status tracks where this document is in the ingestion
    -- pipeline. The CHECK constraint means only these three exact values
    -- are allowed — the database rejects anything else.
    status      TEXT        NOT NULL DEFAULT 'processing'
                            CHECK (status IN ('processing', 'ready', 'failed')),

    -- Populated once ingestion is complete — useful for debugging
    -- ("why does search feel thin?" → check chunk_count)
    chunk_count INT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table 3: chunks
-- Each row is one 500-character slice of a document.
-- This is what gets embedded, indexed, and retrieved at query time.

CREATE TABLE rag.chunks (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Which document this chunk came from. Deleting a document
    -- automatically deletes all its chunks.
    document_id UUID        NOT NULL REFERENCES rag.documents(id) ON DELETE CASCADE,

    -- CONCEPT: We denormalise user_id here even though it's already on
    -- the documents table. This lets RLS work with a simple
    -- "WHERE user_id = auth.uid()" check on this table alone,
    -- without needing a JOIN to documents on every single query.
    -- At search time, you're hitting this table millions of times —
    -- avoiding that JOIN matters.
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- The actual text of this chunk — what gets shown to the LLM
    -- as context, and what gets embedded into a vector.
    content     TEXT        NOT NULL,

    -- CONCEPT: VECTOR(1024) stores the Voyage AI embedding for this chunk.
    -- 1024 is the number of dimensions voyage-2 produces. Think of it as
    -- 1024 coordinates that together describe where this chunk sits in
    -- "meaning space". Two chunks about similar topics will have vectors
    -- that point in nearly the same direction.
    embedding   VECTOR(1024),

    -- CONCEPT: tsvector is PostgreSQL's built-in format for full-text
    -- search — it stores a pre-processed version of the text (stemmed,
    -- stopwords removed) that makes keyword search fast.
    -- GENERATED ALWAYS AS means PostgreSQL maintains this column
    -- automatically. You never write to it — insert content, and
    -- PostgreSQL fills fts in for you. This is how we get BM25-style
    -- keyword search without any extra code.
    fts         TSVECTOR    GENERATED ALWAYS AS
                    (to_tsvector('english', content)) STORED,

    -- Page number, source filename, chunk index etc. Stored as flexible
    -- JSON so you can add fields without changing the schema.
    metadata    JSONB       DEFAULT '{}',

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- Table 4: conversations
-- A conversation is a named chat session. One user can have many.
-- Think of it like a thread in ChatGPT — a container for messages.

CREATE TABLE rag.conversations (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Default title shown in the sidebar until the user renames it
    title       TEXT        NOT NULL DEFAULT 'New conversation',

    -- Optional: conversation scoped to a specific document
    document_id UUID        REFERENCES rag.documents(id),

    -- Optional: long-term summary of the conversation
    summary     TEXT,

    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- CONCEPT: updated_at lets you sort conversations by most recently
    -- active — like WhatsApp showing your most recent chat at the top.
    -- We update this column every time a new message is added.
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table 5: messages
-- Each row is one message in a conversation — either from the user
-- or from the assistant. This is how chat history is stored.

CREATE TABLE rag.messages (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),

    conversation_id UUID        NOT NULL REFERENCES rag.conversations(id) ON DELETE CASCADE,

    -- Denormalised again for the same RLS reason as chunks
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- CONCEPT: role tells us who said this message.
    -- 'user' = the human's question
    -- 'assistant' = the LLM's answer
    -- This mirrors the format Sarvam AI expects in its messages array,
    -- so you can pass these rows directly into the API call.
    role            TEXT        NOT NULL CHECK (role IN ('user', 'assistant')),

    content         TEXT        NOT NULL,

    -- Populated only when voice mode was used for this message.
    -- Stores the S3 presigned URL (expires in 24 hours).
    voice_url       TEXT,
    voice_used      BOOLEAN     NOT NULL DEFAULT FALSE,

    -- CONCEPT: We store which chunk IDs were retrieved to generate
    -- this answer. In production this lets you audit retrieval quality —
    -- "why did the model say X?" → look at retrieved_chunks → see what
    -- context it was given. Invaluable for debugging.
    retrieved_chunks JSONB,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);