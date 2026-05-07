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
