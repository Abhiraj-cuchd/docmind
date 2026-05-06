# RAG Quality & Latency Improvement Tasks

Goal: improve answer quality (more explanatory, structured, useful) and reduce latency
without infrastructure changes. All tasks use existing Sarvam AI + Titan + Supabase stack.

---

## Analysis

| Area | Current State | Gap |
|---|---|---|
| Generation prompt | `sarvam.py:201` — "helpful assistant", "Be concise and specific", temperature=0.3 | Root cause of terse answers; all three need changing |
| Query rewriting | Not implemented | Pronouns like "it/this" hit embedding verbatim — kills multi-turn retrieval |
| match_count | `handler.py:233` — hardcoded `10` | Missing relevant chunks entirely |
| MMR top_k | `handler.py:71` — `MMR_TOP_K=3` | LLM only sees 3 chunks even when match_count=20 |
| Chunking | `chunker.py:50` — `chunk_size=400, overlap=100` | Short chunks lose cross-sentence context |
| MMR cosine | `mmr.py:196-204` — pure Python loop over 1024 dims | ~3-5ms per similarity calc; ~45ms total with 10 candidates |
| HyDE prompt | `hyde.py:105-110` — "Write a short 2-3 sentence passage..." | Generic; doesn't prime for textbook-style output |
| Context format | `sarvam.py:191-196` — `[Chunk N — Page X of file]` | No section header; model sees fragments not structure |

**Critical dependency:** Task 7 (chunking changes) requires re-indexing all existing
documents. All stored chunks are at the old size. Schedule this last after validating
answer quality from Tasks 1–6.

---

## Tasks

### Task 1 — Fix the generation prompt
**File:** `lambdas/query_lambda/sarvam.py`
**Impact:** Highest — directly causes terse answers

- Replace `_build_rag_prompt()` system instruction:
  - Change "helpful assistant" → tutor persona
  - Remove "Be concise and specific"
  - Add structured response format: What it is / How it works / Why it matters
  - Add depth control: expand key ideas, avoid covering everything
- In `generate_answer()`: temperature `0.3` → `0.5`, keep max_tokens at 1024

**Prompt structure to use:**
```
You are a knowledgeable tutor helping a student understand their uploaded documents.

Response strategy:
- Start with a direct answer (1–2 lines)
- Explain the concept in a structured way using: What it is / How it works / Why it matters
- Prioritize clarity — expand only the most important parts

Context usage:
- Use retrieved chunks as the primary source
- Combine multiple chunks into one coherent explanation
- Simplify fragmented context

Rules:
- Do NOT say "based on the context"
- If not found in documents: "This is not clearly covered in your document. Based on my knowledge: [answer]"
- Never fabricate document content
```

---

### Task 2 — Increase retrieval coverage
**File:** `handler.py`
**Impact:** High — currently cutting off relevant chunks before they reach the LLM

- Line 71: `MMR_TOP_K = 3` → `5`
- Line 233: `match_count=10` → `20`
- Line 306 (HyDE search): `match_count=10` → `20`

---

### Task 3 — Improve context formatting
**File:** `lambdas/query_lambda/sarvam.py`
**Impact:** Medium — helps model synthesize fragmented chunks into coherent answers

In `_build_rag_prompt()` at line 191, update the chunk header format:

```python
# Before
f"[Chunk {i+1} — Page {chunk['metadata'].get('page_number', '?')} of {chunk['metadata'].get('filename', 'document')}]\n"

# After
section = chunk['metadata'].get('section', '')
section_part = f" | Section: {section}" if section else ""
f"[Chunk {i+1} — Page {chunk['metadata'].get('page_number', '?')}{section_part} | {chunk['metadata'].get('filename', 'document')}]\n"
```

---

### Task 4 — Add query rewriting for multi-turn conversations
**Files:** `lambdas/query_lambda/sarvam.py` (add function), `handler.py` (call it)
**Impact:** High for multi-turn — "How does it work?" after discussing gradient descent
currently embeds as-is, causing poor retrieval

**In `sarvam.py`**, add:
```python
def rewrite_query(query: str, history: list[dict]) -> str:
    """
    Rewrites ambiguous follow-up queries into self-contained search queries.
    Only called when history is non-empty and query contains pronouns/references.
    """
    if not history:
        return query

    # Only rewrite if query is short or contains pronouns
    pronouns = {"it", "this", "that", "they", "them", "its", "these", "those", "he", "she"}
    words = set(query.lower().split())
    if len(query.split()) > 12 and not (words & pronouns):
        return query

    history_text = _format_history(history)

    prompt = (
        "Rewrite the user's query into a complete, self-contained search query.\n\n"
        "Rules:\n"
        "- Resolve any pronouns or references using the conversation history\n"
        "- Keep the meaning the same\n"
        "- Output only the rewritten query, nothing else\n\n"
        f"{history_text}\n"
        f"Query: {query}\n\n"
        "Rewritten query:"
    )

    raw = _call_sarvam(
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0.0,
    )

    rewritten = _strip_think_tags(raw).strip()
    print(f"[Sarvam] Query rewritten: '{query[:60]}' → '{rewritten[:60]}'")
    return rewritten if rewritten else query
```

**In `handler.py`**, after line 162 (`fetch_conversation_history`):
```python
# Rewrite ambiguous follow-up queries before embedding
from sarvam import rewrite_query
search_query = rewrite_query(query, history)
```

Then use `search_query` in place of `query` for:
- `embed_query(search_query)` at line 223
- `query_text=search_query` in both `execute_hybrid_search` calls (lines 232, 309)

Keep original `query` for: cache key, saving to history, and the final generation call.

**Token cost:** 1 router token per rewrite. Only triggers on short queries or queries
with pronouns when history is non-empty — most queries pass through unchanged.

---

### Task 5 — Improve HyDE prompt
**File:** `lambdas/query_lambda/hyde.py`
**Impact:** Medium — more specific prompt generates a better embedding target

- Line 105: replace generic "Write a short 2-3 sentence passage..." with:
  ```
  Write a textbook passage that teaches the following concept.
  Include: what it is, how it works, and a concrete example.
  Be specific and factual.

  Question: {query}

  Passage:
  ```
- Line 123: `max_tokens=200` → `300`

---

### Task 6 — Optimize MMR with numpy
**File:** `lambdas/query_lambda/mmr.py`
**Impact:** Medium latency — pure Python loop over 1024 dims runs ~45ms total; numpy cuts to <1ms

- Add `import numpy as np` at top
- Replace `cosine_similarity()` with numpy dot product:
  ```python
  def cosine_similarity(vec_a, vec_b) -> float:
      a = np.array(_parse_vector(vec_a), dtype=np.float32)
      b = np.array(_parse_vector(vec_b), dtype=np.float32)
      if a.size == 0 or b.size == 0 or len(a) != len(b):
          return 0.0
      # Vectors are already normalized by Titan (normalize=True)
      # so magnitude is always 1.0 — dot product equals cosine similarity
      return float(np.dot(a, b))
  ```

---

### Task 7 — Parallelize Supabase calls in handler
**File:** `lambdas/query_lambda/handler.py`
**Impact:** ~100ms latency saving on warm Lambda

Lines 159-162 run sequentially but are independent:
```python
# Before
save_user_message(conversation_id, user_id, query)
history = fetch_conversation_history(conversation_id, user_id)

# After
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=2) as ex:
    save_future    = ex.submit(save_user_message, conversation_id, user_id, query)
    history_future = ex.submit(fetch_conversation_history, conversation_id, user_id)
history = history_future.result()
save_future.result()  # surface any exceptions
```

---

### Task 8 — Increase chunk size (requires re-indexing)
**File:** `lambdas/ingestion_lambda/chunker.py`
**Impact:** Medium quality — short chunks lose context across sentence boundaries

- Line 50: `chunk_size=400` → `600`
- Line 51: `chunk_overlap=100` → `150`

**Prerequisite:** Re-index all existing documents after deploying. Trigger ingestion
Lambda on each existing S3 object, or build a one-time admin script that calls
the ingestion pipeline per document. Existing chunks at size 400 remain in Supabase
until the document is re-indexed — queries will mix old and new chunk sizes.

---

## Implementation Order

```
1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
```

Tasks 1–7 are zero-infra and zero re-indexing. Deploy and validate answer quality first.
Task 8 is the only one with an operational dependency — schedule it after confirming
the prompt and retrieval changes produce the expected improvement.
