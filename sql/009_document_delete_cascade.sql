-- 009_document_delete_cascade.sql
-- Adds ON DELETE CASCADE to conversations.document_id so that deleting
-- a document automatically deletes all its conversations (and their
-- messages, which already cascade from conversations).
--
-- Previously this FK had no cascade action, leaving orphaned conversation
-- rows with a stale document_id when a document was deleted.

ALTER TABLE rag.conversations
  DROP CONSTRAINT IF EXISTS conversations_document_id_fkey;

ALTER TABLE rag.conversations
  ADD CONSTRAINT conversations_document_id_fkey
    FOREIGN KEY (document_id)
    REFERENCES rag.documents(id)
    ON DELETE CASCADE;
