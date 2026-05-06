# Feature: Response Style + Source Linking

Two independent features. Implement in order — Feature 1 has no frontend work and can ship alone.

---

## Feature 1: Response Style Preference

User selects how the AI answers: **concise**, **explanatory**, or **conversational**.  
Pure prompt engineering — no schema changes, no new services.

### Step 1 — `lambdas/query_lambda/sarvam.py`

**1a.** Add `style` param to `generate_answer()` and `direct_answer()`, thread it into the prompt builders.

**1b.** In `_build_rag_prompt()`, replace the hardcoded "Response strategy" block with a style-selected one:

```python
STYLE_INSTRUCTIONS = {    "concise": """Write a short answer in 3-5 lines.No bullets, no sections, no extra explanation.Only include the most important information.""",    "explanatory": """You MUST follow this exact structure:Answer:<1-2 line direct answer>Explanation:- What it is: <1-2 lines>- How it works: <2-3 lines>- Why it matters: <1-2 lines>Rules:- Always include all three sections- Keep explanations concise but clear- Do not skip sections- Do not write long paragraphs""",    "conversational": """Explain like you're talking to a friend.- Use simple language- Use analogies if helpful- Avoid structured sections- Keep it natural and easy to follow"""}
```

Replace the current hardcoded block in `_build_rag_prompt()`:

```python
# before
"""Response strategy:
- Start with a direct answer (1-2 lines)
- Explain the concept in a structured way using: What it is / How it works / Why it matters
..."""

# after
style_block = STYLE_INSTRUCTIONS.get(style, STYLE_INSTRUCTIONS["explanatory"])
```

**1c.** Signatures to update:

```python
def generate_answer(query, context_chunks, history, style: str = "explanatory") -> str
def direct_answer(query, history, style: str = "explanatory") -> str
def _build_rag_prompt(query, context_chunks, history, style: str = "explanatory") -> str
```

---

### Step 2 — `lambdas/query_lambda/handler.py`

**2a.** Parse `response_style` from SQS body:

```python
response_style = body.get("response_style", "explanatory")
```

**2b.** Pass it through to every `generate_answer()` and `direct_answer()` call in `_process_record()`.

**2c.** Update `_make_cache_key()` to include style — same query with different style = different answer:

```python
def _make_cache_key(user_id, query, document_id, style):
    h = hashlib.sha256(query.lower().strip().encode()).hexdigest()
    doc_part = document_id or "none"
    return f"cache:{user_id}:{doc_part}:{style}:{h}"
```

Update all call sites of `_make_cache_key` in this file.

---

### Step 3 — `lambdas/submit/handler.py`

**3a.** Parse `response_style` from POST body in `handle_query()`:

```python
response_style = body.get("response_style", "explanatory")
```

Validate: if provided and not in `{"concise", "explanatory", "conversational"}`, default to `"explanatory"` (don't error — be lenient).

**3b.** Add it to the SQS message:

```python
message = {
    "job_id":          job_id,
    "query":           query,
    "user_id":         user_id,
    "conversation_id": conversation_id,
    "voice_mode":      bool(voice_mode),
    "response_style":  response_style,   # ← add
}
```

**3c.** Update `_make_cache_key()` here too (same signature change as handler.py step 2c) — both files must produce identical cache keys.

---

### Step 4 — Frontend

Add a style selector UI (segmented control or dropdown) in the chat input area.  
Send `response_style` in the POST body to `/api/query`.  
Persist the user's preference in `localStorage` so it survives page reloads.

---

## Feature 2: Source Linking with PDF Page Jump

Answer messages show clickable source badges. Clicking opens the document panel at the correct page and shows the chunk snippet.

### Step 1 — `lambdas/query_lambda/handler.py`

**1a.** In `_finish()`, build a `sources` array from `retrieved_chunks`:

```python
sources = [
    {
        "chunk_id":    c.get("id"),
        "document_id": c.get("document_id"),
        "page_number": c["metadata"].get("page_number"),
        "filename":    c["metadata"].get("filename"),
        "section":     c["metadata"].get("section"),
        "snippet":     c["content"][:250],
    }
    for c in retrieved_chunks
]
```

**1b.** Add `sources` to `_write_result()` payload:

```python
_write_result(r, job_id, {
    "status":   "done",
    "answer":   answer,
    "sources":  sources,      # ← add
    ...
})
```

**1c.** For direct/fallback paths (`path="direct"`, `path="direct_fallback"`), pass `retrieved_chunks=[]` as they already do — `sources` will be `[]`.

---

### Step 2 — Cache: store `{answer, sources}` together

Currently cache stores just the answer string. Change it to store a JSON object so cached responses also return sources.

In both `query_lambda/handler.py` and `submit/handler.py`:

```python
# write
import json
r.setex(cache_key, CACHE_TTL, json.dumps({"answer": answer, "sources": sources}))

# read
raw = r.get(cache_key)
if raw:
    cached = json.loads(raw)
    cached_answer  = cached["answer"]
    cached_sources = cached.get("sources", [])
```

> **Migration note:** Old cache entries are plain strings. Add a safe parse:
> 
> ```python
> try:
>     cached = json.loads(raw)
>     cached_answer = cached["answer"]
>     cached_sources = cached.get("sources", [])
> except (json.JSONDecodeError, KeyError):
>     cached_answer = raw   # old plain-string entry
>     cached_sources = []
> ```

---

### Step 3 — `lambdas/poll/handler.py`

No changes needed — poll lambda reads the Redis job key and returns it as-is. `sources` rides along automatically once it's in the job result.

Verify the poll response is passed through without filtering keys.

---

### Step 4 — Frontend: Poll response type

Update the TypeScript type for the poll result:

```typescript
interface Source {
  chunk_id:    string
  document_id: string
  page_number: number | null
  filename:    string
  section:     string | null
  snippet:     string
}

interface QueryResult {
  status:                  'pending' | 'done' | 'error'
  answer?:                 string
  sources?:                Source[]
  cached?:                 boolean
  voice_url?:              string | null
  voice_credits_remaining?: number
  tokens_used?:            number
  path?:                   string
}
```

---

### Step 5 — Frontend: Source badges in chat message

In the assistant message component, render source badges below the answer text:

```tsx
{sources && sources.length > 0 && (
  <div className="flex flex-wrap gap-1.5 mt-3">
    {sources.map((src, i) => (
      <button
        key={src.chunk_id}
        onClick={() => onSourceClick(src)}
        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs
                   bg-zinc-800 border border-zinc-700 text-zinc-400
                   hover:border-blue-500/50 hover:text-blue-400 transition-colors"
      >
        <FileText className="w-3 h-3" />
        {src.page_number ? `Page ${src.page_number}` : src.filename}
        {src.section && <span className="text-zinc-600"> · {src.section}</span>}
      </button>
    ))}
  </div>
)}
```

The `onSourceClick(src: Source)` callback bubbles up to the layout.

---

### Step 6 — Frontend: Layout wires source click to DocumentPanel

In the layout component that owns both `ChatPanel` and `DocumentPanel`, add state:

```typescript
const [activeSource, setActiveSource] = useState<Source | null>(null)

function handleSourceClick(src: Source) {
  // ensure the document panel is showing the right document
  if (src.document_id !== activeDocumentId) {
    onDocumentSelect(src.document_id, src.filename)
  }
  setActiveSource(src)
}
```

Pass `activeSource` into `DocumentPanel` as a prop.

---

### Step 7 — Frontend: `DocumentPanel.tsx`

**7a.** Add props:

```typescript
interface DocumentPanelProps {
  userId:           string
  activeDocumentId: string | null
  onDocumentSelect: (documentId: string, filename?: string) => void
  activeSource?:    Source | null   // ← add
}
```

**7b.** When `activeSource` changes and the panel is in preview mode, update the iframe `src` to jump to the target page:

```typescript
const iframeSrc = useMemo(() => {
  if (!pdfUrl) return null
  const page = activeSource?.page_number
  const pageParam = page ? `page=${page}&` : ''
  return `${pdfUrl}#${pageParam}toolbar=0&navpanes=0&scrollbar=0&pagemode=none&view=FitH&zoom=page-width`
}, [pdfUrl, activeSource])
```

Replace the hardcoded iframe `src` with `iframeSrc`.

> **Note:** Updating `src` reloads the iframe. At typical PDF sizes (1-5MB) this is fast (~1s). Acceptable until a future `react-pdf` migration.

**7c.** Add a source snippet strip below the preview header when `activeSource` is set:

```tsx
{activeSource && (
  <div className="px-3 py-2 border-b border-zinc-800 bg-zinc-800/40 shrink-0">
    <div className="flex items-start justify-between gap-2">
      <div className="min-w-0">
        <p className="text-xs text-zinc-500 mb-1">
          Source · {activeSource.page_number ? `Page ${activeSource.page_number}` : activeSource.filename}
          {activeSource.section && ` · ${activeSource.section}`}
        </p>
        <p className="text-xs text-zinc-300 leading-relaxed line-clamp-3">
          {activeSource.snippet}
        </p>
      </div>
      <button
        onClick={() => setActiveSource(null)}  {/* or clear via prop callback */}
        className="p-1 rounded text-zinc-600 hover:text-zinc-400 shrink-0"
      >
        <X className="w-3 h-3" />
      </button>
    </div>
  </div>
)}
```

**7d.** Auto-open preview when a source is clicked and the document panel is in list view:

```typescript
useEffect(() => {
  if (!activeSource) return
  const doc = documents.find(d => d.id === activeSource.document_id)
  if (doc?.status === 'ready') setPreviewDoc(doc)
}, [activeSource, documents])
```

---

## Files Changed Summary

File

Feature 1

Feature 2

`lambdas/query_lambda/sarvam.py`

Style prompt blocks, param threading

—

`lambdas/query_lambda/handler.py`

Parse style from SQS, cache key

Build sources array, add to result, cache {answer,sources}

`lambdas/submit/handler.py`

Parse style from POST, add to SQS msg, cache key

Cache {answer,sources} read/write

`lambdas/poll/handler.py`

—

Verify passthrough (no code change likely)

Frontend chat message component

Style selector UI

Source badges, onSourceClick

`frontend/components/layout/DocumentPanel.tsx`

—

activeSource prop, iframeSrc memo, snippet strip, auto-open

Frontend layout

Pass style to query

Wire onSourceClick → activeSource → DocumentPanel

---

## Testing Checklist

### Feature 1

-    Default style (`explanatory`) works when no `response_style` sent
-    `concise` returns noticeably shorter answers
-    `conversational` drops formal structure
-    Cache keys differ across styles (ask same question twice with different style — should not return cached response from first style)
-    Style persists in localStorage across page reloads

### Feature 2

-    Job result includes `sources` array with correct page numbers
-    Cached responses include sources (not empty array)
-    Source badges render only when `sources.length > 0`
-    Clicking badge opens document panel + jumps to correct page
-    Snippet strip shows the relevant chunk text
-    Closing the strip (X button) clears active source without closing the PDF viewer
-    Works when document panel is already open on a different document