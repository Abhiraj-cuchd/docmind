# Phase 2 Context — System HLD

> **Purpose:** Reference document for iterating on Phase 2 features, specifically cross-document reasoning and multi-model support. Captures the complete current state — architecture, data flow, pipeline internals, UX controls, and key thresholds.

---

## 1. System Overview

**What it is:** A serverless RAG system where users upload PDFs, ask questions, and receive LLM-generated answers grounded in their documents.

**Core constraint driving the architecture:** API Gateway has a 29-second timeout. RAG generation takes 8–15 seconds and may queue behind rate-limited tokens. All queries are therefore processed asynchronously via SQS.

**Two async pipelines:**

```
Upload:
  Browser → S3 PUT (presigned URL) → S3 event → SNS → SQS (ingestion_queue)
    → Indexer Lambda → chunk/embed → Supabase (chunks + embeddings)

Query:
  POST /query → Submit Lambda → SQS (query_queue) → Processor Lambda → Redis (job result)
  GET /result/{jobId} ← Poll Lambda (polls every 2s, max 45 polls)
```

---

## 2. Infrastructure

### CDK Stacks

| Stack | Resources |
|---|---|
| `StorageStack` | S3 pdf_bucket, S3 audio_bucket, SNS topic |
| `QueueStack` | SQS ingestion_queue, query_queue, embed_queue (+ DLQ) |
| `ComputeStack` | 6 Lambda functions + IAM roles |
| `ApiStack` | HTTP API v2 (API Gateway), CloudWatch logs |

### API Routes

| Method | Path | Lambda |
|---|---|---|
| POST | /query | rag-submit |
| GET | /result/{jobId} | rag-poll |
| POST | /upload | rag-submit |
| GET | /document-url | rag-submit |
| DELETE | /documents/{documentId} | rag-delete |
| DELETE | /conversations/{conversationId} | rag-delete |

**Throttling:** 20 req/s sustained, burst 50.

### Lambda Functions

| Name | Trigger | Timeout | Memory |
|---|---|---|---|
| rag-submit | HTTP | 10s | 256MB |
| rag-poll | HTTP | 10s | 128MB |
| rag-indexer | SQS (ingestion) | 5min | 512MB |
| rag-embed-worker | SQS (embed) | 90s | 256MB |
| rag-processor | SQS (query) | 5min | 512MB |
| rag-delete | HTTP | 15s | 128MB |

**Shared layer:** `deps_layer` — packages from `shared_lambda/requirements.txt` + the `shared_lambda/` package itself.

---

## 3. Database Schema (Supabase / PostgreSQL, schema: `rag`)

All tables have RLS. Service role bypasses RLS; user JWT respects it.

### Tables

**`user_profiles`**
- `id` UUID PK → `auth.users` (CASCADE)
- `display_name` TEXT
- `voice_credits` INT DEFAULT 3, CHECK >= 0

**`documents`**
- `id` UUID PK
- `user_id` UUID → `auth.users` (CASCADE)
- `filename`, `s3_key` TEXT
- `status`: `processing` | `indexing` | `ready` | `failed` | `partial`
- `chunk_count` INT, `doc_metadata` JSONB (total_pages, file_size_bytes, extracted_pages)
- `skipped_pages` JSONB array `[{page_number, reason}]`

**`chunks`**
- `id` UUID PK
- `document_id` UUID → `documents` (CASCADE)
- `user_id` UUID → `auth.users` (CASCADE) — *denormalized for single-column RLS index*
- `content` TEXT (~500 chars)
- `embedding` VECTOR(1024) — Bedrock Titan V2, normalized
- `fts` TSVECTOR GENERATED — `to_tsvector('english', content)`
- `metadata` JSONB — `{page_number, filename, section, chunk_index}`

**`conversations`**
- `id` UUID PK
- `user_id` UUID → `auth.users` (CASCADE)
- `document_id` UUID → `documents` (CASCADE ON DELETE) — nullable
- `title`, `summary` TEXT
- `updated_at` TIMESTAMPTZ — bumped on every message

**`messages`**
- `id` UUID PK
- `conversation_id` UUID → `conversations` (CASCADE)
- `user_id` UUID — denormalized
- `role`: `user` | `assistant`
- `content` TEXT
- `voice_url` TEXT, `voice_urls` TEXT[] — S3 presigned URLs (24hr)
- `voice_used` BOOLEAN
- `retrieved_chunks` JSONB — stored chunk metadata for source citations
- `tokens_used` INT, `path` TEXT

### Cascade chain

```
auth.users
  └── documents (on user delete)
        └── chunks (on doc delete)
        └── conversations (on doc delete, migration 009)
              └── messages (on conv delete)
  └── conversations (on user delete)
  └── user_profiles (on user delete)
```

### Key SQL Functions

| Function | Purpose |
|---|---|
| `hybrid_search(embedding, text, user_id, count)` | HNSW vector search + GIN keyword search, RRF merge |
| `hybrid_search_in_document(embedding, text, user_id, doc_id, count)` | Same but scoped to one document |
| `get_chunks_by_page(user_id, page, count, doc_id?)` | Exact page lookup |
| `get_chunks_by_section(user_id, pattern, doc_id?, count)` | ILIKE section heading search |
| `consume_voice_credit(user_id)` | Atomic decrement, returns bool |
| `refund_voice_credit(user_id)` | Atomic increment |

**RRF formula:** `score = 1/(60 + vector_rank) + 1/(60 + keyword_rank)`

---

## 4. Ingestion Pipeline

```
S3 PUT → SNS → SQS → rag-indexer:
  1. Download PDF from S3
  2. Extract text (all pages, skipping image-only pages)
  3. Build overlapping page windows (WINDOW_SIZE=50, OVERLAP=3)
  4. Per window: chunk → deduplicate (MD5) → batch insert to Supabase (BATCH=100) → enqueue embed jobs (BATCH=32)
  5. Send "finalize" message to embed queue
  6. Mark document status = "indexing" (or "partial" if a window errored)

SQS (embed_queue) → rag-embed-worker:
  - type="embed": embed chunk batch via Bedrock Titan V2 → update chunks.embedding
  - type="finalize": mark document status = "ready"
```

**Why windowed:** Lambda 15min timeout. 50-page windows with 3-page overlap preserve cross-boundary context without re-processing.

**Concurrency:** Embed workers are unlimited — Titan has no rate limits. All batches process in parallel.

---

## 5. Query Pipeline (rag-processor, detailed)

Entry point: SQS message `{job_id, question, user_id, conversation_id, document_id, voice_mode, response_style}`

```
Step 0:  Conversational check       regex, 0 tokens, ~5ms → instant result to Redis
Step 1:  Cache check                Redis lookup, 0 tokens → instant result if hit
Step 2:  Save user message          Supabase insert (async with step 3)
Step 3:  Fetch history              last 3 Q&A pairs (6 messages) from Supabase
Step 4:  Query rewrite              if history non-empty: Sarvam resolves "it"/"that" etc. (optional)
Step 5:  Smart routing
           - has document_id → always retrieve (no router call)
           - no document_id → LLM router: needs_retrieval? (cost: 1 token, timeout: 15s)
Step 6:  Structured query detection  "page 5", section "Introduction" → exact metadata lookup
Step 7:  Embed query                 Voyage AI (input_type="query")
Step 8:  Hybrid search               Supabase RPC (RRF, HNSW + GIN)
Step 9:  Confidence check            if top RRF score < MIN_USEFUL_RRF_SCORE (0.005) → direct_answer path
Step 10: Conditional HyDE            if top RRF score < HYDE_CONFIDENCE_THRESHOLD (0.02):
                                       generate hypothetical answer (Sarvam, cost 1 token, timeout 15s)
                                       re-embed with Voyage AI
                                       re-run hybrid search with new embedding
Step 11: MMR reranking               top 5 chunks, lambda=0.7 (70% relevance, 30% diversity)
Step 12: Acquire generation tokens   2 tokens from RAG bucket, wait up to 45s
                                       → raises RATE_LIMIT_WAIT if unavailable (SQS requeue, not Redis write)
Step 13: Generate answer             Sarvam AI sarvam-m, response_style applied in prompt
Step 14: Post-generation
           - voice TTS (if voice_mode): Sarvam bulbul:v3, split chunks, upload WAV to S3
           - save assistant message (with sources + voice_urls)
           - write cache to Redis (TTL: 1hr)
           - write job result to Redis (TTL: 1hr)
```

### Rate Limiting (Redis sliding-window token bucket)

| Bucket | Capacity | Window | Operation cost | Timeout |
|---|---|---|---|---|
| Router | 60 tokens | 60s | 1 | 15s |
| RAG | 60 tokens | 60s | HyDE=1, Generate=2 | 45s |

**Re-queue pattern:** Generation token timeout raises `Exception("RATE_LIMIT_WAIT")`. Handler re-raises without writing to Redis — SQS does not delete the message, it returns to queue automatically.

### Response Styles

| Style | Behaviour |
|---|---|
| `concise` | 3–5 lines, no bullets, most important info only |
| `explanatory` (default) | 3 mandatory sections: Answer → Explanation (What it is / How it works / Why it matters) |
| `conversational` | Like talking to a friend, analogies, natural language |

Style is applied inside the Sarvam prompt template. Cache key includes response_style.

### Cache Key Format

```
cache:{user_id}:{document_id or "none"}:{response_style}:{sha256(query.lower().strip())}
```

User-scoped because different users have different documents. Document-scoped because the same question against two different documents should yield different cached answers.

### Fallback Paths

| Trigger | Fallback |
|---|---|
| RRF < 0.005 | `direct_answer` — LLM answers from its own knowledge, no context |
| Router: needs_retrieval=false | `direct_answer` |
| Conversational pattern matched | Pre-written response, no LLM call |
| HyDE token unavailable | Continue with original query embedding |
| Generation tokens unavailable after 45s | SQS requeue |

---

## 6. Voice / TTS

- User opts in via `voice_mode: true` in the query request
- `consume_voice_credit()` called atomically before TTS. If 0 credits → skip TTS
- Answer split into ≤500-char chunks at sentence boundaries
- Sarvam AI `bulbul:v3` model: `target_language_code=en-IN`, speaker=`shruti`, pace=1.15
- Each chunk: WAV stored at `audio/{user_id}/{uuid}_{index}.wav` in VOICE_BUCKET
- Presigned GET URLs (24hr) returned as `voice_urls[]`
- On failure: `refund_voice_credit()` called, `voice_url = null` in result
- Frontend: AudioPlayerBar plays voice_urls sequentially

---

## 7. Deletion

**Document delete** (`DELETE /documents/{id}`):
1. Ownership check
2. Delete S3 PDF (`uploads/`)
3. Delete document row → DB cascade: chunks, conversations, messages

**Conversation delete** (`DELETE /conversations/{id}`):
1. Ownership check
2. Fetch all messages with `voice_url` / `voice_urls`
3. Parse S3 key from presigned URL path, delete each WAV (`audio/`)
4. Delete conversation row → DB cascade: messages

Both go through `rag-delete` Lambda (path-based dispatch).

---

## 8. Frontend

### Pages

| Route | Component | Purpose |
|---|---|---|
| `/dashboard` | `DocumentSelectionScreen` | Grid of documents, select to start chat |
| `/chat` | `ChatPage` | Main RAG interface |
| `/upload` | `UploadPage` | Upload zone + document list |

### Key Hooks

| Hook | Manages |
|---|---|
| `useAuth` | Supabase session, user, signOut |
| `useConversations` | CRUD for conversations; `deleteConversation` hits API route (S3 cleanup) |
| `useDocuments` | CRUD + polling (5s while processing); `deleteDocument` hits API route |
| `useRAGQuery` | Submit query → poll `/api/result/{jobId}` every 2s, max 45 polls (90s) |

### State Management

`ConversationSelectionProvider` (React Context) is the single source of truth across all protected pages:
- `selection: { conversationId, documentId }` — which conversation/doc is active
- `setSelection`, `updateSelection`, `clearSelection`
- Exposes `conversations[]`, `createConversation()`, `deleteConversation()`

### Query Flow (Frontend)

```
1. User types → ChatInput → useRAGQuery.submit(QueryRequest)
2. POST /api/query → returns {job_id} or instant {status: "done", answer}
3. If job_id: poll /api/result/{jobId} every 2s
4. On done: render MessageBubble with answer + sources + AudioPlayerBar
5. Sources rendered as Citations (clickable → opens DocumentPanel PDF preview at page)
```

### Conversation Sidebar

- Inline delete: trash icon → confirm (✓/✗) inline → `deleteConversation(id)`
- Active conversation: highlighted, navigates to `/chat`
- On delete active: `clearSelection()` → `/dashboard`

### Document Panel

- Two-pane: list view ↔ PDF preview (iframe + presigned URL)
- Per-card delete: confirmation modal with "all conversations deleted" warning
- Auto-refresh every 3s while any doc is `processing` / `indexing`

### Dashboard DocumentGridCard

- Delete icon + ArrowRight adjacent in top-right, both appear on hover
- Confirmation modal (same warning as DocumentPanel)

---

## 9. Shared Lambda Modules

| Module | Purpose |
|---|---|
| `auth.py` | RS256/ES256 JWT verify via JWKS, extract user_id |
| `secrets.py` | Secrets Manager fetch + in-memory cache (per warm instance) |
| `rate_limiter.py` | Redis sliding-window token bucket, acquire_tokens() with exponential backoff |
| `supabase_client.py` | Service client (bypasses RLS), user client (respects RLS), hybrid search RPCs, voice credit RPCs |
| `classifier.py` | Regex + embedding-based conversational classifier, pre-compiled patterns |
| `utils.py` | cosine_similarity() |

---

## 10. External Services Summary

| Service | Used for | Notes |
|---|---|---|
| Supabase | PostgreSQL, Auth, REST, RLS | Service role for Lambdas; user JWT for frontend |
| AWS S3 | PDFs (`uploads/`), voice WAVs (`audio/`) | Presigned URLs for upload (15min) + view (1hr/24hr) |
| AWS Bedrock (Titan V2) | Chunk embeddings during ingestion | 1024 dims, normalized, no rate limits |
| Voyage AI | Query-time embeddings | `input_type="query"` vs `"document"` |
| Sarvam AI (sarvam-m) | Router, HyDE, answer generation, TTS | Rate-limited 60/min; strip `<think>` tags from all output |
| Upstash Redis | Rate limiting + job results + query cache | REST API (no pipeline); TTL 3600s |
| AWS SQS | Decoupled async processing | 3 queues + 1 DLQ |
| AWS Secrets Manager | All credentials | One secret JSON, cached in-memory |

---

## 11. Key Constants & Thresholds (quick reference)

```
# Retrieval
MIN_USEFUL_RRF_SCORE     = 0.005   # below → skip context, direct answer
HYDE_CONFIDENCE_THRESHOLD = 0.02   # below → attempt HyDE

# MMR
MMR_TOP_K     = 5
MMR_LAMBDA    = 0.7   # 70% relevance, 30% diversity

# History
HISTORY_PAIRS = 3   # last 3 Q&A pairs sent to LLM

# Cache/jobs
CACHE_TTL     = 3600s
RESULT_TTL    = 3600s

# Voice
TTS_MAX_CHARS = 500
TTS_PACE      = 1.15
VOICE_BUCKET  = audio/{user_id}/{uuid}_{index}.wav

# Ingestion
WINDOW_SIZE   = 50 pages
WINDOW_OVERLAP = 3 pages
EMBED_BATCH   = 32 chunks
STORE_BATCH   = 100 chunks

# Rate limits
BUCKET_CAPACITY = 60 tokens/60s
ROUTER_COST   = 1,  timeout = 15s
HYDE_COST     = 1,  timeout = 15s
GENERATE_COST = 2,  timeout = 45s
```

---

## 12. What Doesn't Exist Yet (Phase 2 target area)

Current limitations relevant to cross-document reasoning:

1. **Single document per conversation** — `conversations.document_id` is a single FK. There's no multi-document conversation scope.
2. **`hybrid_search` is user-scoped or single-document-scoped** — no RPC for "search across a selected subset of documents".
3. **LLM is always Sarvam AI (sarvam-m)** — model is hardcoded in `sarvam.py`. No abstraction layer for swapping models.
4. **No cross-document source attribution** — `retrieved_chunks.metadata` stores filename/page but the retrieval never merges evidence across docs.
5. **No conversation-level document list** — only one document per conversation row; no junction table.
6. **Cache key includes `document_id or "none"`** — cross-doc queries can't be cached the same way.

These are the structural gaps to address in Phase 2.
