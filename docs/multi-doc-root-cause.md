# Multi-Document Reasoning — Root Cause Analysis

**Date:** 2026-05-07  
**Symptom:** Selecting two documents and asking a question only returns answers grounded in one document (or neither), not both.

---

## Bug 1 — CRITICAL: `conversation_documents` never queried on load

**File:** `frontend/hooks/useConversations.ts:23`

`fetchConversations` hits the REST endpoint `conversations?order=updated_at.desc` — the plain table, with no join to `rag.conversation_documents`. The `Conversation` type has an optional `documentIds?: string[]` field, but this is never populated from the DB. It only exists if the creator just inserted it in memory during `createConversation`.

**Consequence:** When a user selects any existing conversation from the sidebar, `layout.tsx:57` resolves:

```ts
documentIds: conversation.documentIds ?? (conversation.document_id ? [conversation.document_id] : []),
```

`conversation.documentIds` is always `undefined`, so the fallback is `[conversation.document_id]` — a single-element array. The query lambda receives `document_ids: ["<first-doc-id>"]` and the second document is never searched.

**Fix:** In `fetchConversations`, use a Supabase select that joins the junction table:

```ts
const data = await supabaseFetch<Conversation[]>(
  'conversations?select=*,conversation_documents(document_id)&order=updated_at.desc'
);
// Then map: conv.documentIds = conv.conversation_documents.map(cd => cd.document_id)
```

Or fetch `conversation_documents` separately per conversation on selection. The join approach is cleaner.

---

## Bug 2 — CRITICAL: Guard clause in `ChatWindow` blocks multi-doc-only submissions

**File:** `frontend/components/layout/ChatWindow.tsx` (inside `handleSubmit`)

```ts
if (!documentId || !createConversation) {
  toast.error('Select a document to start chatting');
  return;
}
```

And:

```tsx
disabled={!conversationId && !documentId}
```

`documentId` is the *single active document* prop — not the multi-doc array. If `documentId` is null but `documentIds` has two entries, the UI shows "Select a document to start chatting" and blocks submission entirely.

This affects a flow where the user selects multiple documents but the `activeDocumentId` slot is cleared or misaligned.

**Fix:** Change the guard to also allow `documentIds.length > 0`:

```ts
const hasDoc = !!documentId || (documentIds && documentIds.length > 0);
if (!hasDoc || !createConversation) {
  toast.error('Select a document to start chatting');
  return;
}
```

Same for the `disabled` prop:
```tsx
disabled={!conversationId && !documentId && !(documentIds && documentIds.length > 0)}
```

---

## Bug 3 — HIGH: Structured query path ignores `document_ids`

**File:** `lambdas/query_lambda/handler.py:250,257`

When `_detect_structured_query` matches (e.g. "what is on page 3?" or "what does section 2 say?"), the handler takes a shortcut:

```python
candidates = _get_chunks_by_page(user_id, q_value, document_id)
# or
candidates = _get_chunks_by_section(user_id, q_value, document_id)
```

Both functions take a single `document_id`. In a multi-doc session `document_id` is only the first document; the second is silently excluded.

**Fix:** Extend `_get_chunks_by_page` and `_get_chunks_by_section` to accept `document_ids: list[str]` and use `document_id = ANY(doc_ids)` in the query. Pass `document_ids or ([document_id] if document_id else [])` from the call site.

---

## Bug 4 — MEDIUM: MMR rerank silently degrades when `hybrid_search_multi_doc` returns no embeddings

**File:** `lambdas/query_lambda/mmr.py:60` + `lambdas/query_lambda/handler.py:435`

`mmr_rerank` expects each chunk to have an `"embedding"` key. The Supabase function `hybrid_search_multi_doc` returns `{ id, content, metadata, document_id, rrf_score }` — **no `embedding` column**.

MMR detects this and logs:
> `[MMR] No chunks have embeddings — returning top 3 by RRF score`

It then falls back to simple RRF top-K. This is not a crash, but it means the diversity step is bypassed entirely for all multi-doc queries.

**Fix (option A):** Add `embedding` to the `SELECT` list in `hybrid_search_multi_doc` (and its single-doc sibling for consistency):

```sql
SELECT id, content, metadata, document_id, rrf_score, embedding
```

**Fix (option B — cheaper):** Don't call `mmr_rerank` when chunks have no embeddings. The current fallback already handles it; just log clearly so it's visible in CloudWatch.

---

## Bug 5 — LOW: Cache key uses only first `document_id` for single-doc path

**File:** `lambdas/submit/handler.py` and `lambdas/query_lambda/handler.py`

When `document_ids` is empty and `document_id` is set, the cache key `doc_part = document_id or "none"`. This is correct for single-doc. However if a multi-doc session somehow sends `document_ids=[]` (see Bug 1), the key collapses to the first doc, and a cached single-doc answer may be returned for what should be a multi-doc query — returning a stale answer with no cross-document context.

**Fix:** This is mitigated once Bug 1 is fixed (correct `document_ids` always sent). No separate action needed beyond that.

---

## Fix Priority

| # | Severity | Effort | Impact |
|---|----------|--------|--------|
| 1 | Critical | Medium | Fixes multi-doc on conversation resume |
| 2 | Critical | Small  | Fixes initial multi-doc submission edge case |
| 3 | High     | Small  | Fixes structured queries (page/section lookups) |
| 4 | Medium   | Small  | Restores MMR diversity for multi-doc results |
| 5 | Low      | None   | Auto-fixed when Bug 1 is resolved |

Start with Bug 1 and Bug 2 — they affect every multi-doc query. Bug 3 and 4 are correctness issues in narrower paths.

---

## Implementation Task List

### Task 1 — Fix `fetchConversations` to join `conversation_documents` (Bug 1)

**File:** `frontend/hooks/useConversations.ts`

**Step 1.1** — Change the fetch URL at line 25:

```ts
// Before
'conversations?order=updated_at.desc'

// After
'conversations?select=*,conversation_documents(document_id)&order=updated_at.desc'
```

**Step 1.2** — Map the nested PostgREST join result into `documentIds` before calling `setConversations`. PostgREST returns the nested rows as `conversation_documents: { document_id: string }[]` on each object:

```ts
const mapped = data.map((conv: any) => ({
  ...conv,
  documentIds: (conv.conversation_documents ?? []).map(
    (cd: { document_id: string }) => cd.document_id
  ),
}));
setConversations(mapped);
```

**Step 1.3** — No type change needed. `Conversation` in `frontend/lib/types.ts:6` already has `documentIds?: string[]`.

**Step 1.4** — No change needed in `layout.tsx:57–58`. Once `documentIds` is populated, the existing fallback logic resolves correctly.

---

### Task 2 — Fix `handleSubmit` guard and `disabled` prop in `ChatWindow` (Bug 2)

**File:** `frontend/components/layout/ChatWindow.tsx`

**Step 2.1** — Fix the guard clause at line 170:

```ts
// Before
if (!documentId || !createConversation) {

// After
const hasDoc = !!documentId || (documentIds && documentIds.length > 0);
if (!hasDoc || !createConversation) {
```

**Step 2.2** — Fix the `disabled` prop on `ChatInput` at line 332:

```tsx
// Before
disabled={!conversationId && !documentId}

// After
disabled={!conversationId && !documentId && !(documentIds && documentIds.length > 0)}
```

**Step 2.3** — Fix the `placeholder` fallback at lines 333–338 to match:

```tsx
// Before
!conversationId && !documentId
  ? 'Select a document to start chatting…'

// After
!conversationId && !documentId && !(documentIds && documentIds.length > 0)
  ? 'Select a document to start chatting…'
```

---

### Task 3 — Extend structured query path to support multiple documents (Bug 3)

Requires a SQL migration and a Python update.

**Step 3.1 — New SQL migration** `sql/013_multi_doc_structured_queries.sql`:

The existing `get_chunks_by_page` (`sql/010_page_query_function.sql:15`) and `get_chunks_by_section` (`sql/011_section_query_and_partial_status.sql:21`) each accept a single `target_doc_id UUID DEFAULT NULL`. Add a `target_doc_ids UUID[] DEFAULT NULL` parameter with precedence over the single-ID parameter:

```sql
CREATE OR REPLACE FUNCTION rag.get_chunks_by_page(
    target_user_id  UUID,
    target_page     INT,
    match_count     INT    DEFAULT 20,
    target_doc_id   UUID   DEFAULT NULL,
    target_doc_ids  UUID[] DEFAULT NULL
)
RETURNS TABLE (id UUID, content TEXT, metadata JSONB, rrf_score FLOAT, embedding VECTOR(1024))
LANGUAGE SQL STABLE AS $$
    SELECT id, content, metadata, 0.5::FLOAT AS rrf_score, embedding
    FROM rag.chunks
    WHERE user_id = target_user_id
      AND (
        CASE
          WHEN target_doc_ids IS NOT NULL THEN document_id = ANY(target_doc_ids)
          WHEN target_doc_id  IS NOT NULL THEN document_id = target_doc_id
          ELSE TRUE
        END
      )
      AND (
        metadata->'pages' @> to_jsonb(target_page)
        OR (metadata->'pages' IS NULL AND (metadata->>'page_number')::int = target_page)
      )
    ORDER BY (metadata->>'chunk_index')::int ASC
    LIMIT match_count;
$$;

CREATE OR REPLACE FUNCTION rag.get_chunks_by_section(
    target_user_id  UUID,
    heading_pattern TEXT,
    target_doc_id   UUID   DEFAULT NULL,
    match_count     INT    DEFAULT 20,
    target_doc_ids  UUID[] DEFAULT NULL
)
RETURNS TABLE (id UUID, content TEXT, metadata JSONB, rrf_score FLOAT, embedding VECTOR(1024))
LANGUAGE SQL STABLE AS $$
    SELECT id, content, metadata, 0.5::FLOAT AS rrf_score, embedding
    FROM rag.chunks
    WHERE user_id = target_user_id
      AND (
        CASE
          WHEN target_doc_ids IS NOT NULL THEN document_id = ANY(target_doc_ids)
          WHEN target_doc_id  IS NOT NULL THEN document_id = target_doc_id
          ELSE TRUE
        END
      )
      AND metadata->>'heading' ILIKE '%' || heading_pattern || '%'
    ORDER BY (metadata->>'chunk_index')::int ASC
    LIMIT match_count;
$$;
```

**Step 3.2 — Update `_get_chunks_by_page` at `handler.py:738`:**

```python
def _get_chunks_by_page(
    user_id:      str,
    page_number:  int,
    document_id:  str | None,
    document_ids: list[str] | None = None,
) -> list[dict]:
    params = {
        "target_user_id": user_id,
        "target_page":    page_number,
        "match_count":    20,
        "target_doc_id":  document_id,
    }
    if document_ids:
        params["target_doc_ids"] = document_ids
    result = supabase.schema("rag").rpc("get_chunks_by_page", params).execute()
    return result.data or []
```

**Step 3.3 — Update `_get_chunks_by_section` at `handler.py:755`:**

```python
def _get_chunks_by_section(
    user_id:         str,
    heading_pattern: str,
    document_id:     str | None,
    document_ids:    list[str] | None = None,
) -> list[dict]:
    params = {
        "target_user_id":  user_id,
        "heading_pattern": heading_pattern,
        "target_doc_id":   document_id,
        "match_count":     20,
    }
    if document_ids:
        params["target_doc_ids"] = document_ids
    result = supabase.schema("rag").rpc("get_chunks_by_section", params).execute()
    return result.data or []
```

**Step 3.4 — Update the call sites at `handler.py:250` and `handler.py:257`:**

```python
# line 250 — before
candidates = _get_chunks_by_page(user_id, q_value, document_id)
# after
candidates = _get_chunks_by_page(user_id, q_value, document_id, document_ids or None)

# line 257 — before
candidates = _get_chunks_by_section(user_id, q_value, document_id)
# after
candidates = _get_chunks_by_section(user_id, q_value, document_id, document_ids or None)
```

---

### Task 4 — Add `embedding` to `hybrid_search_multi_doc` return (Bug 4)

**Step 4.1 — New SQL migration** `sql/014_multi_doc_embedding_return.sql`:

The current function at `sql/012_multi_doc.sql:31` omits `embedding` from `RETURNS TABLE` and both CTEs. The `vr` and `kr` CTEs already query `rag.chunks` which has the column:

```sql
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
    COALESCE(vr.id,          kr.id)         AS id,
    COALESCE(vr.content,     kr.content)    AS content,
    COALESCE(vr.metadata,    kr.metadata)   AS metadata,
    COALESCE(vr.document_id, kr.document_id) AS document_id,
    (COALESCE(1.0 / (60 + vr.rank), 0) +
     COALESCE(1.0 / (60 + kr.rank), 0))    AS rrf_score,
    COALESCE(vr.embedding,   kr.embedding)  AS embedding
  FROM vr FULL OUTER JOIN kr ON vr.id = kr.id
  ORDER BY rrf_score DESC
  LIMIT match_count;
$$;

GRANT EXECUTE ON FUNCTION rag.hybrid_search_multi_doc TO service_role;
```

No Python changes needed — `mmr_rerank` already reads `chunk.get("embedding")` at `mmr.py:77` and will use it once the column is returned.

---

### Execution Order

| Step | File(s) | Type | Prerequisite |
|------|---------|------|-------------|
| Task 1 | `useConversations.ts` | Frontend | None |
| Task 2 | `ChatWindow.tsx` | Frontend | None |
| Task 4 SQL | `sql/014_...` | Migration | None |
| Task 3 SQL | `sql/013_...` | Migration | None |
| Task 3 Python | `handler.py` | Lambda deploy | Task 3 SQL applied |

Tasks 1, 2, and both SQL migrations can be done in parallel. The Task 3 Python deploy must come after its SQL migration is applied.
