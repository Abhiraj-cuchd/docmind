# Phase 2 Implementation Guide
## Cross-Document Reasoning + Evidence Navigation with Chunk Highlighting

> **Read before starting:** Each phase is independently testable. Complete and verify Phase 1 and 2 before touching the database for Phase 3. The highlighting feature works on single-document conversations — you do not need cross-document to test it.

---

## What We Are Building

| Feature | User-visible outcome |
|---|---|
| Cross-document reasoning | User selects multiple PDFs for one conversation. LLM answers across all of them. |
| Evidence navigation | Clicking an evidence item in the chat switches the document panel to the correct PDF and page. |
| Chunk highlighting | The exact text the LLM retrieved is highlighted in yellow in the PDF viewer. |

---

## Prerequisites

Before starting, verify these are true:

- [ ] `retrieved_chunks` JSONB is being stored in `rag.messages` (check any assistant message row in Supabase)
- [ ] `DocumentPanel` currently renders PDFs via `<iframe src={presignedUrl}>`
- [ ] The `/api/document-url` Next.js route exists and returns a presigned GET URL
- [ ] `react-pdf` is NOT yet installed (`cat frontend/package.json | grep react-pdf` returns nothing)

---

## Phase 1 — Store Chunk Content in `retrieved_chunks`

**Goal:** Add the raw chunk text to the JSONB payload stored with every assistant message. This is the data that drives highlighting in Phase 2. One file changes.

**Estimated time:** 15 minutes  
**Risk:** None — additive JSON field, no schema migration.

---

### Step 1.1 — Update the processor handler

**File:** `lambdas/query_lambda/handler.py`

Find where you build the `retrieved_chunks` list before calling `save_message`. It currently looks something like:

```python
chunks_used = [
    {
        "chunk_id": c["id"],
        "document_id": c["document_id"],
        "page_number": c["metadata"]["page_number"],
        "filename": c["metadata"]["filename"],
        "section": c["metadata"].get("section"),
    }
    for c in relevant_chunks
]
```

Add `"content"` to every dict:

```python
chunks_used = [
    {
        "chunk_id": c["id"],
        "document_id": c["document_id"],
        "page_number": c["metadata"]["page_number"],
        "filename": c["metadata"]["filename"],
        "section": c["metadata"].get("section"),
        "content": c["content"],   # ← ADD THIS LINE ONLY
    }
    for c in relevant_chunks
]
```

> **Why `content` and not `embedding`?** The embedding is a 1024-element float array — storing it in JSONB per message would bloat the messages table. We only need the raw text for the fuzzy match in the browser.

---

### Step 1.2 — Verify

Deploy the Lambda and ask a question that triggers retrieval. Query Supabase:

```sql
SELECT
  retrieved_chunks -> 0 -> 'content' AS first_chunk_content,
  retrieved_chunks -> 0 -> 'page_number' AS page
FROM rag.messages
WHERE role = 'assistant'
ORDER BY created_at DESC
LIMIT 1;
```

Expected: you see actual chunk text and a page number. If `content` is `null`, the Lambda hasn't been redeployed yet.

---

## Phase 2 — Replace `<iframe>` with `react-pdf` + Implement Highlighting

**Goal:** Swap the PDF viewer from a sandboxed iframe to a controllable `react-pdf` renderer, then wire evidence clicks to navigate to the correct page and highlight the retrieved chunk.

**Estimated time:** 3–4 hours  
**Risk:** Medium — the PDF viewer is the most complex frontend component. Test rendering on a large PDF before wiring the highlight logic.

---

### Step 2.1 — Install `react-pdf`

```bash
cd frontend
npm install react-pdf
npm install --save-dev @types/react-pdf
```

`react-pdf` bundles PDF.js internally. No separate pdfjs-dist install needed.

Add this to your `next.config.js` to allow the PDF.js worker:

```js
// next.config.js
const nextConfig = {
  webpack: (config) => {
    config.resolve.alias.canvas = false;
    return config;
  },
};
module.exports = nextConfig;
```

---

### Step 2.2 — Create the PDF viewer component

**New file:** `frontend/components/pdf/PDFViewer.tsx`

```tsx
'use client';

import { useState, useCallback, useRef } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';

// Point to the bundled PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();

interface HighlightTarget {
  content: string;   // raw chunk text from retrieved_chunks JSONB
  pageNumber: number;
}

interface PDFViewerProps {
  url: string;
  initialPage?: number;
  highlight?: HighlightTarget | null;
  onPageChange?: (page: number) => void;
}

// Normalise text for fuzzy comparison:
// lowercase + collapse whitespace + strip punctuation
function normalise(text: string): string {
  return text
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[^\w\s]/g, '')
    .trim();
}

// Returns true if the span text is part of the highlight target.
// We check both directions:
//   - span is fully inside the chunk (chunk contains the span)
//   - chunk starts with this span (first span of a multi-span chunk)
function spanMatchesChunk(spanText: string, normalisedChunk: string): boolean {
  const normSpan = normalise(spanText);
  if (normSpan.length < 4) return false; // skip very short spans (punctuation, numbers)
  return normalisedChunk.includes(normSpan);
}

export default function PDFViewer({
  url,
  initialPage = 1,
  highlight,
  onPageChange,
}: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(initialPage);
  const [scale, setScale] = useState<number>(1.25);
  const containerRef = useRef<HTMLDivElement>(null);

  // When highlight prop changes, jump to the target page
  // This fires whenever the parent passes a new evidence item
  const prevHighlightRef = useRef<HighlightTarget | null>(null);
  if (highlight && highlight !== prevHighlightRef.current) {
    prevHighlightRef.current = highlight;
    if (highlight.pageNumber !== currentPage) {
      setCurrentPage(highlight.pageNumber);
    }
  }

  const normalisedChunkContent = highlight
    ? normalise(highlight.content)
    : null;

  // customTextRenderer fires once per text span in the PDF text layer.
  // We return a <mark> wrapper when the span is part of the target chunk.
  const customTextRenderer = useCallback(
    ({ str }: { str: string }) => {
      if (!normalisedChunkContent || !str.trim()) return str;
      if (spanMatchesChunk(str, normalisedChunkContent)) {
        return `<mark style="background: #FDE68A; border-radius: 2px; padding: 0 1px;">${str}</mark>`;
      }
      return str;
    },
    [normalisedChunkContent],
  );

  function goToPage(page: number) {
    const clamped = Math.max(1, Math.min(page, numPages));
    setCurrentPage(clamped);
    onPageChange?.(clamped);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>

      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '8px 12px', borderBottom: '1px solid var(--color-border-tertiary)',
        fontSize: 13, color: 'var(--color-text-secondary)',
      }}>
        <button
          onClick={() => goToPage(currentPage - 1)}
          disabled={currentPage <= 1}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}
          aria-label="Previous page"
        >‹</button>

        <span>Page</span>
        <input
          type="number"
          value={currentPage}
          min={1}
          max={numPages}
          onChange={(e) => goToPage(Number(e.target.value))}
          style={{
            width: 44, textAlign: 'center', border: '1px solid var(--color-border-secondary)',
            borderRadius: 4, padding: '2px 4px', background: 'var(--color-background-primary)',
            color: 'var(--color-text-primary)',
          }}
        />
        <span>of {numPages}</span>

        <button
          onClick={() => goToPage(currentPage + 1)}
          disabled={currentPage >= numPages}
          style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}
          aria-label="Next page"
        >›</button>

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          <button onClick={() => setScale(s => Math.max(0.5, s - 0.25))}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16 }}>−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button onClick={() => setScale(s => Math.min(3, s + 0.25))}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16 }}>+</button>
        </div>
      </div>

      {/* PDF render area */}
      <div ref={containerRef} style={{ flex: 1, overflow: 'auto', padding: 12 }}>
        <Document
          file={url}
          onLoadSuccess={({ numPages }) => setNumPages(numPages)}
          loading={<div style={{ padding: 24, color: 'var(--color-text-secondary)' }}>Loading PDF…</div>}
          error={<div style={{ padding: 24, color: 'var(--color-text-danger)' }}>Failed to load PDF.</div>}
        >
          <Page
            pageNumber={currentPage}
            scale={scale}
            customTextRenderer={customTextRenderer}
            renderAnnotationLayer={false}
          />
        </Document>
      </div>
    </div>
  );
}
```

> **Dark mode note on the highlight colour:** `#FDE68A` is amber-100, which is visible on both light and dark PDF backgrounds. If your PDF renders on a dark background, change to `#F59E0B` (amber-400).

---

### Step 2.3 — Create the highlight state manager

**New file:** `frontend/hooks/usePDFHighlight.ts`

This hook owns the "what is currently highlighted" state and exposes a `triggerHighlight` function that the evidence list calls on click.

```ts
import { useState, useCallback } from 'react';

export interface ChunkEvidence {
  chunk_id: string;
  document_id: string;
  filename: string;
  page_number: number;
  section?: string;
  content: string;
}

export interface ActiveHighlight {
  documentId: string;
  pageNumber: number;
  content: string;
}

export function usePDFHighlight() {
  const [activeHighlight, setActiveHighlight] = useState<ActiveHighlight | null>(null);
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);

  const triggerHighlight = useCallback((evidence: ChunkEvidence) => {
    // If the evidence is in a different document, switch first.
    // The caller (DocumentPanel) listens to activeDocumentId and fetches
    // a fresh presigned URL when it changes.
    setActiveDocumentId(evidence.document_id);
    setActiveHighlight({
      documentId: evidence.document_id,
      pageNumber: evidence.page_number,
      content: evidence.content,
    });
  }, []);

  const clearHighlight = useCallback(() => {
    setActiveHighlight(null);
  }, []);

  return { activeHighlight, activeDocumentId, triggerHighlight, clearHighlight };
}
```

---

### Step 2.4 — Update `DocumentPanel` to use `PDFViewer`

**File:** `frontend/components/layout/DocumentPanel.tsx`

Remove the `<iframe>` block and replace with the new viewer. The panel now accepts the `activeHighlight` and `activeDocumentId` from the parent.

Key changes:

```tsx
// BEFORE (remove this)
<iframe
  src={presignedUrl}
  style={{ width: '100%', height: '100%', border: 'none' }}
  title="PDF preview"
/>

// AFTER (replace with this)
import PDFViewer from '@/components/pdf/PDFViewer';

// Inside the component, when presignedUrl is ready:
<PDFViewer
  url={presignedUrl}
  initialPage={activeHighlight?.pageNumber ?? 1}
  highlight={
    activeHighlight?.documentId === activeDocumentId
      ? { content: activeHighlight.content, pageNumber: activeHighlight.pageNumber }
      : null
  }
/>
```

When `activeDocumentId` changes (user clicked evidence in a different document), fetch a fresh presigned URL via `/api/document-url?document_id=${activeDocumentId}` and set it as `presignedUrl`.

```tsx
useEffect(() => {
  if (!activeDocumentId) return;
  fetch(`/api/document-url?document_id=${activeDocumentId}`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
  })
    .then(r => r.json())
    .then(data => setPresignedUrl(data.url));
}, [activeDocumentId]);
```

---

### Step 2.5 — Wire evidence list to `triggerHighlight`

**File:** `frontend/components/chat/MessageBubble.tsx` (or wherever the "Evidence used (N)" list renders)

Each evidence row needs an `onClick`:

```tsx
// Parse retrieved_chunks from the assistant message
const evidenceItems: ChunkEvidence[] = message.retrieved_chunks ?? [];

// In the evidence row JSX:
<tr
  key={ev.chunk_id}
  onClick={() => triggerHighlight(ev)}
  style={{ cursor: 'pointer' }}
  role="button"
  aria-label={`Jump to ${ev.filename} page ${ev.page_number}`}
>
  <td>{index + 1}</td>
  <td>{ev.filename}</td>
  <td>Page {ev.page_number}</td>
  <td>{ev.section}</td>
  <td><i className="ti ti-external-link" aria-hidden="true" /></td>
</tr>
```

Pass `triggerHighlight` down from whatever parent holds the `usePDFHighlight` hook (probably `ChatPage` or `ConversationSelectionProvider`).

---

### Step 2.6 — Verify highlighting works

1. Ask a question that triggers retrieval on a single document.
2. Click the first evidence row.
3. The PDF panel should navigate to the correct page AND show yellow-highlighted text.

**If the page navigates but nothing is highlighted:** the fuzzy match failed. Add a `console.log` inside `customTextRenderer` to see what `str` values are being passed vs what your chunk content looks like. Common culprits: leading/trailing whitespace in `content`, ligatures (`fi` → `ﬁ`), or the chunk spanning two pages.

**If the page does not navigate:** check that `activeHighlight.pageNumber` is reaching the `PDFViewer` component. Verify the `page_number` field exists in `retrieved_chunks` (Step 1.2).

---

## Phase 3 — Cross-Document Database Changes

**Goal:** Add a many-to-many junction table linking conversations to documents, and a new SQL function that searches across multiple documents in one call.

**Estimated time:** 30 minutes  
**Risk:** Low — additive only. Existing conversations keep working via `conversations.document_id`.

---

### Step 3.1 — Create the junction table

Run this in the Supabase SQL editor:

```sql
-- Many-to-many: one conversation can reference many documents
CREATE TABLE rag.conversation_documents (
  conversation_id UUID NOT NULL REFERENCES rag.conversations(id) ON DELETE CASCADE,
  document_id     UUID NOT NULL REFERENCES rag.documents(id)     ON DELETE CASCADE,
  added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (conversation_id, document_id)
);

-- RLS: users can only see their own conversation_documents
ALTER TABLE rag.conversation_documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_own_conversation_documents"
  ON rag.conversation_documents FOR ALL
  USING (
    auth.uid() = (
      SELECT user_id FROM rag.conversations WHERE id = conversation_id
    )
  );

-- Index for fast lookup in both directions
CREATE INDEX ON rag.conversation_documents (conversation_id);
CREATE INDEX ON rag.conversation_documents (document_id);

-- Make the existing single document_id nullable
-- (existing rows keep their value; new multi-doc conversations leave it NULL)
ALTER TABLE rag.conversations ALTER COLUMN document_id DROP NOT NULL;
```

---

### Step 3.2 — Create the multi-document search function

This is a direct extension of your existing `hybrid_search_in_document`. The only change is `WHERE document_id = $doc_id` → `WHERE document_id = ANY($doc_ids)`.

```sql
CREATE OR REPLACE FUNCTION rag.hybrid_search_multi_doc(
  query_embedding  VECTOR(1024),
  query_text       TEXT,
  target_user_id   UUID,
  doc_ids          UUID[],          -- array of document UUIDs
  match_count      INT DEFAULT 10
)
RETURNS TABLE (
  id         UUID,
  content    TEXT,
  metadata   JSONB,
  document_id UUID,
  rrf_score  FLOAT
)
LANGUAGE sql STABLE
SECURITY INVOKER
AS $$
  WITH vr AS (
    SELECT id, content, metadata, document_id,
           ROW_NUMBER() OVER (ORDER BY embedding <=> query_embedding) AS rank
    FROM   rag.chunks
    WHERE  user_id = target_user_id
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
    WHERE  user_id = target_user_id
      AND  document_id = ANY(doc_ids)
      AND  fts @@ plainto_tsquery('english', query_text)
    ORDER BY ts_rank(fts, plainto_tsquery('english', query_text)) DESC
    LIMIT 20
  )
  SELECT
    COALESCE(vr.id, kr.id)              AS id,
    COALESCE(vr.content, kr.content)    AS content,
    COALESCE(vr.metadata, kr.metadata)  AS metadata,
    COALESCE(vr.document_id, kr.document_id) AS document_id,
    (COALESCE(1.0 / (60 + vr.rank), 0) +
     COALESCE(1.0 / (60 + kr.rank), 0)) AS rrf_score
  FROM vr FULL OUTER JOIN kr ON vr.id = kr.id
  ORDER BY rrf_score DESC
  LIMIT match_count;
$$;

-- Grant access to service role (Lambda uses service key)
GRANT EXECUTE ON FUNCTION rag.hybrid_search_multi_doc TO service_role;
```

> **Why `document_id` is returned now:** With multiple documents in play, the frontend needs to know which document each retrieved chunk came from — to display the correct document chip colour in the evidence list.

---

### Step 3.3 — Grant and reload

```sql
GRANT ALL ON TABLE rag.conversation_documents TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload config';
```

---

### Step 3.4 — Verify

```sql
-- Insert a test row (use real UUIDs from your DB)
INSERT INTO rag.conversation_documents (conversation_id, document_id)
VALUES ('YOUR-CONV-UUID', 'YOUR-DOC-UUID');

-- Check lookup works
SELECT * FROM rag.conversation_documents WHERE conversation_id = 'YOUR-CONV-UUID';

-- Test the multi-doc function (use a real embedding — pass zeros for a smoke test)
SELECT id, document_id, rrf_score
FROM rag.hybrid_search_multi_doc(
  array_fill(0.0, ARRAY[1024])::vector,
  'leave policy',
  'YOUR-USER-UUID',
  ARRAY['DOC-UUID-1', 'DOC-UUID-2']::uuid[],
  5
);
```

---

## Phase 4 — Lambda Processor Updates

**Goal:** The processor reads `document_ids[]` from the SQS message body, calls `hybrid_search_multi_doc` instead of the single-doc version, and uses a doc-set-aware cache key.

**Estimated time:** 1–2 hours  
**Risk:** Low — fallback to existing single-doc path if `document_ids` is absent.

---

### Step 4.1 — Update the submit Lambda

**File:** `lambdas/submit/handler.py`

The submit handler receives the POST `/query` body and puts a message on SQS. Accept `document_ids`:

```python
body = json.loads(event["body"])
question      = body["question"]
conversation_id = body["conversation_id"]
voice_mode    = body.get("voice_mode", False)
response_style = body.get("response_style", "explanatory")

# Multi-doc: list of UUIDs the conversation is scoped to
document_ids = body.get("document_ids", [])  # ← ADD

# Enqueue
sqs.send_message(
    QueueUrl=QUERY_QUEUE_URL,
    MessageBody=json.dumps({
        "job_id": job_id,
        "question": question,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "voice_mode": voice_mode,
        "response_style": response_style,
        "document_ids": document_ids,   # ← ADD
    }),
)
```

---

### Step 4.2 — Update the processor handler

**File:** `lambdas/query_lambda/handler.py`

```python
body         = json.loads(record["body"])
document_ids = body.get("document_ids", [])  # ← ADD; empty list = no doc scope

# ... existing setup code ...

# CACHE KEY — include a sorted hash of doc_ids so the same question
# against the same doc set hits the same cache entry regardless of order.
import hashlib
doc_ids_sorted = sorted(document_ids)
doc_hash = hashlib.sha256("|".join(doc_ids_sorted).encode()).hexdigest()[:12]
cache_key = f"cache:{user_id}:{doc_hash}:{response_style}:{query_hash}"
# ↑ replaces your current cache key format

# ... cache check, history fetch, embed query ...

# RETRIEVAL — use multi-doc fn if document_ids provided, else existing logic
if document_ids:
    results = supabase.schema("rag").rpc("hybrid_search_multi_doc", {
        "query_embedding": query_vector,
        "query_text": question,
        "target_user_id": user_id,
        "doc_ids": document_ids,
        "match_count": 10,
    }).execute()
else:
    # Existing path: user-scoped search (no doc filter)
    results = supabase.schema("rag").rpc("hybrid_search", {
        "query_embedding": query_vector,
        "query_text": question,
        "target_user_id": user_id,
        "match_count": 10,
    }).execute()
```

---

### Step 4.3 — Verify

Send a test SQS message with `document_ids` set to two real document UUIDs. Check CloudWatch logs for the processor — you should see `hybrid_search_multi_doc` being called and chunks from both documents appearing in the result.

```bash
aws logs tail /aws/lambda/rag-processor \
  --region ap-south-1 \
  --since 5m \
  --format short \
  | grep -E "(hybrid_search|rrf_score|document_id)"
```

---

## Phase 5 — Frontend Multi-Document Selection

**Goal:** Users can select multiple documents when starting a conversation. The selected set is stored in `conversation_documents` and sent with every query.

**Estimated time:** 2–3 hours

---

### Step 5.1 — Add document selection to conversation creation

**File:** `frontend/components/layout/ConversationSidebar.tsx` (or wherever "New conversation" is triggered)

Replace the single-document picker with a multi-select. The `useDocuments` hook already provides the document list.

```tsx
const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);

function toggleDoc(docId: string) {
  setSelectedDocIds(prev =>
    prev.includes(docId)
      ? prev.filter(id => id !== docId)
      : [...prev, docId]
  );
}

// In the document list UI:
{documents.map(doc => (
  <div
    key={doc.id}
    onClick={() => toggleDoc(doc.id)}
    style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px',
      borderRadius: 6, cursor: 'pointer',
      background: selectedDocIds.includes(doc.id)
        ? 'var(--color-background-info)'
        : 'transparent',
    }}
  >
    <input
      type="checkbox"
      readOnly
      checked={selectedDocIds.includes(doc.id)}
      style={{ pointerEvents: 'none' }}
    />
    <span style={{ fontSize: 13 }}>{doc.filename}</span>
    {doc.status === 'ready'
      ? <i className="ti ti-check" style={{ color: 'var(--color-text-success)', marginLeft: 'auto' }} aria-hidden="true" />
      : <i className="ti ti-loader" style={{ color: 'var(--color-text-secondary)', marginLeft: 'auto' }} aria-hidden="true" />
    }
  </div>
))}
```

---

### Step 5.2 — Save selected documents on conversation create

**File:** `frontend/hooks/useConversations.ts`

```ts
async function createConversation(
  title: string,
  documentIds: string[]
): Promise<string> {
  // 1. Create the conversation row
  const { data: conv, error } = await supabase
    .schema('rag')
    .from('conversations')
    .insert({ user_id: session.user.id, title })
    .select('id')
    .single();

  if (error) throw error;

  // 2. Insert junction rows for each selected document
  if (documentIds.length > 0) {
    await supabase.schema('rag').from('conversation_documents').insert(
      documentIds.map(docId => ({
        conversation_id: conv.id,
        document_id: docId,
      }))
    );
  }

  return conv.id;
}
```

---

### Step 5.3 — Load `document_ids` for an active conversation

When a conversation is selected, fetch its document set so queries include the right scope:

```ts
// In useConversations or ConversationSelectionProvider
async function loadConversationDocuments(conversationId: string): Promise<string[]> {
  const { data, error } = await supabase
    .schema('rag')
    .from('conversation_documents')
    .select('document_id')
    .eq('conversation_id', conversationId);

  if (error) return [];
  return data.map(row => row.document_id);
}
```

Store the result in context alongside `conversationId`:

```ts
// ConversationSelectionProvider state
const [selection, setSelection] = useState<{
  conversationId: string | null;
  documentIds: string[];       // ← ADD
}>({ conversationId: null, documentIds: [] });
```

---

### Step 5.4 — Pass `document_ids` in every query

**File:** `frontend/hooks/useRAGQuery.ts`

```ts
async function submitQuery(question: string) {
  const response = await fetch('/api/query', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
    },
    body: JSON.stringify({
      question,
      conversation_id: selection.conversationId,
      document_ids: selection.documentIds,    // ← ADD
      voice_mode: voiceMode && voiceCredits > 0,
      response_style: responseStyle,
    }),
  });
  // ... existing polling logic
}
```

---

### Step 5.5 — Render the document chips header

The "Referenced Documents (3)" header in your mockup maps directly to the `selection.documentIds` array. Resolve document names from the `useDocuments` hook:

```tsx
// In ChatPage or ChatWindow header
const referencedDocs = documents.filter(d => selection.documentIds.includes(d.id));

{referencedDocs.length > 0 && (
  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', padding: '8px 16px',
    borderBottom: '1px solid var(--color-border-tertiary)' }}>
    <span style={{ fontSize: 12, color: 'var(--color-text-secondary)', alignSelf: 'center' }}>
      Referenced documents ({referencedDocs.length})
    </span>
    {referencedDocs.map(doc => (
      <span key={doc.id} style={{
        fontSize: 12, padding: '2px 8px', borderRadius: 12,
        background: 'var(--color-background-secondary)',
        border: '1px solid var(--color-border-secondary)',
        color: 'var(--color-text-primary)',
      }}>
        {doc.filename}
      </span>
    ))}
  </div>
)}
```

---

## Phase 6 — Evidence Panel with Cross-Document Attribution

**Goal:** Each evidence row shows which document it came from (using the `document_id` now returned by `hybrid_search_multi_doc`), with a distinct colour chip per document.

---

### Step 6.1 — Assign a stable colour per document

```ts
// utils/docColors.ts
const COLOR_RAMPS = ['#B5D4F4', '#9FE1CB', '#F4C0D1', '#FAC775', '#CEC BF6'];

export function getDocColor(documentId: string, allDocIds: string[]): string {
  const index = allDocIds.indexOf(documentId) % COLOR_RAMPS.length;
  return COLOR_RAMPS[index];
}
```

---

### Step 6.2 — Update the evidence list component

```tsx
// In MessageBubble.tsx evidence section
{evidenceItems.map((ev, i) => (
  <tr
    key={ev.chunk_id}
    onClick={() => triggerHighlight(ev)}
    style={{ cursor: 'pointer' }}
  >
    <td style={{ padding: '6px 8px', fontSize: 13 }}>{i + 1}</td>
    <td style={{ padding: '6px 8px' }}>
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 4,
        fontSize: 12, padding: '2px 6px', borderRadius: 10,
        background: getDocColor(ev.document_id, selection.documentIds),
      }}>
        {ev.filename}
      </span>
    </td>
    <td style={{ padding: '6px 8px', fontSize: 13 }}>Page {ev.page_number}</td>
    <td style={{ padding: '6px 8px', fontSize: 13, color: 'var(--color-text-secondary)' }}>
      {ev.section ?? '—'}
    </td>
    <td style={{ padding: '6px 8px' }}>
      <i className="ti ti-external-link" aria-hidden="true"
        style={{ fontSize: 14, color: 'var(--color-text-secondary)' }} />
    </td>
  </tr>
))}
```

---

## Testing Checklist

### After Phase 1 + 2 (highlighting, single document)
- [ ] Ask a question → evidence list shows rows with filename, page, section
- [ ] Click evidence row → PDF panel navigates to correct page
- [ ] Clicked chunk text is highlighted in yellow
- [ ] Click a second evidence row (different page) → PDF jumps to new page, old highlight clears, new highlight appears
- [ ] Non-matching text on the page is NOT highlighted

### After Phase 3 + 4 (multi-doc backend)
- [ ] `conversation_documents` rows are created on conversation init
- [ ] `hybrid_search_multi_doc` returns chunks from both documents when 2 are selected
- [ ] Cache key changes when the document set changes (two different doc sets → two cache entries)
- [ ] Existing single-document conversations still work (fallback path in processor)

### After Phase 5 + 6 (multi-doc frontend)
- [ ] Can select 2+ documents on conversation create
- [ ] Document chips appear in the chat header
- [ ] Evidence rows show coloured chips identifying source document
- [ ] Clicking evidence from document B (while document A is displayed) → panel switches to document B, navigates to correct page, highlights chunk

---

## Known Edge Cases to Handle

| Edge case | Handling |
|---|---|
| Chunk spans two pages | `page_number` will be the first page of the chunk. Highlight will show on that page only. Accept this — it is rare and the navigation is still correct. |
| PDF.js text extraction diverges from PyMuPDF | Fuzzy normalise function handles whitespace and punctuation differences. Ligature characters (`ﬁ`, `ﬂ`) can cause failures — add a ligature expansion step to `normalise()` if you see misses: `text.replace(/ﬁ/g, 'fi').replace(/ﬂ/g, 'fl')`. |
| Presigned URL expires mid-session | S3 presigned URLs are valid for 1 hour. Add a `refetchInterval` of 50 minutes in the `useEffect` that fetches the URL, or refetch on every document switch (simpler). |
| User clicks evidence with credits=0 and voice mode on | No change needed — voice is handled separately, evidence click only affects the PDF panel. |
| Very large PDFs (200+ pages) | `react-pdf` renders one page at a time — performance is fine. Thumbnail strip (if you implement one) should render lazily. |
| `retrieved_chunks` is null on old messages | Guard: `const evidenceItems: ChunkEvidence[] = message.retrieved_chunks ?? []`. Old messages show no evidence list. |