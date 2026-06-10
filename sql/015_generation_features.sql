-- 015_generation_features.sql
-- Tables for async generation features: summaries, flashcard_decks, flashcards.
-- Apply manually to Supabase after deploying the generation Lambda.

-- ── rag.summaries ─────────────────────────────────────────────────────
-- One row per (user, source) — upsert on re-generate keeps the latest.

CREATE TABLE rag.summaries (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    source_type     TEXT        NOT NULL CHECK (source_type IN ('conversation', 'document')),
    conversation_id UUID        REFERENCES rag.conversations(id) ON DELETE CASCADE,
    document_id     UUID        REFERENCES rag.documents(id) ON DELETE CASCADE,
    content         TEXT        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Upsert target: one summary per user+source combination.
    -- conversation_id and document_id are mutually exclusive per source_type.
    CONSTRAINT summaries_unique UNIQUE (user_id, source_type, conversation_id, document_id)
);

-- ── rag.flashcard_decks ───────────────────────────────────────────────
-- Container for a set of flashcards generated from one source.

CREATE TABLE rag.flashcard_decks (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    source_type     TEXT        NOT NULL CHECK (source_type IN ('conversation', 'document')),
    conversation_id UUID        REFERENCES rag.conversations(id) ON DELETE CASCADE,
    document_id     UUID        REFERENCES rag.documents(id) ON DELETE CASCADE,
    title           TEXT        NOT NULL DEFAULT 'Flashcard Deck',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── rag.flashcards ────────────────────────────────────────────────────
-- Individual Q&A cards belonging to a deck.

CREATE TABLE rag.flashcards (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    deck_id     UUID        NOT NULL REFERENCES rag.flashcard_decks(id) ON DELETE CASCADE,
    question    TEXT        NOT NULL,
    answer      TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Row Level Security ────────────────────────────────────────────────

ALTER TABLE rag.summaries      ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.flashcard_decks ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.flashcards      ENABLE ROW LEVEL SECURITY;

CREATE POLICY summaries_user_policy
    ON rag.summaries
    FOR ALL
    USING (user_id = auth.uid());

CREATE POLICY flashcard_decks_user_policy
    ON rag.flashcard_decks
    FOR ALL
    USING (user_id = auth.uid());

-- flashcards has no user_id column — scope via parent deck
CREATE POLICY flashcards_user_policy
    ON rag.flashcards
    FOR ALL
    USING (
        deck_id IN (
            SELECT id FROM rag.flashcard_decks WHERE user_id = auth.uid()
        )
    );

-- ── Indexes ───────────────────────────────────────────────────────────

CREATE INDEX idx_summaries_user_source      ON rag.summaries (user_id, source_type);
CREATE INDEX idx_summaries_conversation     ON rag.summaries (conversation_id);
CREATE INDEX idx_summaries_document         ON rag.summaries (document_id);

CREATE INDEX idx_flashcard_decks_user       ON rag.flashcard_decks (user_id, source_type);
CREATE INDEX idx_flashcard_decks_conversation ON rag.flashcard_decks (conversation_id);
CREATE INDEX idx_flashcard_decks_document   ON rag.flashcard_decks (document_id);

CREATE INDEX idx_flashcards_deck            ON rag.flashcards (deck_id);

-- ── PostgREST reload ──────────────────────────────────────────────────
NOTIFY pgrst, 'reload config';
