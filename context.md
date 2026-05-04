# RAG MVP — Copilot Continuation Context

> Hand-off document from Claude. Contains full project state, architecture,
> decisions, current bugs, and what needs to be done next.
> Read this entirely before writing any code.

---

## Project Overview

A production-grade serverless RAG (Retrieval-Augmented Generation) system
built on AWS. Target cost ~₹300/month for 100 users.

**Live API endpoint:** `https://om6deoefoe.execute-api.ap-south-1.amazonaws.com`
**AWS Account:** 354140340421, region: ap-south-1
**Supabase project:** `https://juzxjfnjysbzymbijzsv.supabase.co`
**Secret name in AWS Secrets Manager:** `prod/serverless-rag-secrets`

---

## Tech Stack

| Layer           | Technology                     | Notes                                                   |
| --------------- | ------------------------------ | ------------------------------------------------------- |
| Compute         | AWS Lambda (5 functions)       | indexer, embed-worker, submit, processor, poll          |
| Queue           | AWS SQS                        | ingestion-queue, query-queue, embed-queue               |
| Storage         | AWS S3                         | PDF bucket, audio bucket                                |
| API             | AWS API Gateway HTTP API       | Routes: /query, /result/{jobId}, /upload, /document-url |
| IaC             | AWS CDK Python                 | infrastructure/ folder                                  |
| Vector DB       | Supabase PostgreSQL + pgvector | rag schema, HNSW indexing                               |
| Embeddings      | Amazon Titan V2 via Bedrock    | 1024 dims, no rate limits, replaces Voyage AI           |
| LLM             | Sarvam AI (sarvam-m)           | Two keys: ROUTER key + RAG key                          |
| Cache/RateLimit | Upstash Redis REST             | Two token buckets: router + rag                         |
| PDF parsing     | PyMuPDF                        | In Docker container Lambda                              |
| Auth            | Supabase Auth (ES256 JWT)      | JWKS verification, not legacy secret                    |
| Frontend        | Next.js 14 App Router          | TypeScript, Tailwind, shadcn/ui                         |

---

## AWS Secrets Manager Keys

Secret name: `prod/serverless-rag-secrets`

```json
{
  "SUPABASE_URL":             "https://juzxjfnjysbzymbijzsv.supabase.co",
  "SUPABASE_ANON_KEY":        "eyJ...",
  "SUPABASE_SERVICE_KEY":     "eyJ...",
  "SARVAM_API_KEY_ROUTER":    "sk-... (dedicated routing key)",
  "SARVAM_API_KEY_RAG":       "sk-... (dedicated RAG/generation key)",
  "UPSTASH_REDIS_REST_URL":   "https://xxxxx.upstash.io",
  "UPSTASH_REDIS_REST_TOKEN": "..."
}
```

Note: VOYAGE_API_KEY was removed. Titan Bedrock used instead (no key needed — IAM).

---

## Project File Structure

```
prod-serverless-rag/
├── infrastructure/
│   ├── app.py
│   ├── cdk.json
│   └── stacks/
│       ├── storage_stack.py       — S3 buckets, SQS queues
│       ├── compute_stack.py       — All Lambda functions + IAM
│       └── api_stack.py           — HTTP API Gateway + routes
├── lambdas/
│   ├── shared_lambda/
│   │   ├── secrets.py             — Secrets Manager fetch
│   │   ├── auth.py                — ES256/RS256 JWT via JWKS
│   │   ├── supabase_client.py     — Service client + hybrid_search RPC
│   │   ├── rate_limiter.py        — Two-bucket token system (upstash-redis REST)
│   │   ├── classifier.py          — Conversational regex classifier
│   │   └── requirements.txt
│   ├── ingestion_lambda/
│   │   ├── Dockerfile             — Container image
│   │   ├── handler.py             — SQS→extract→chunk→store→enqueue
│   │   ├── extractor.py           — PyMuPDF
│   │   ├── chunker.py             — RecursiveCharacterTextSplitter
│   │   ├── embedder.py            — Amazon Titan V2 (1024 dims)
│   │   ├── embed_worker.py        — Embed queue consumer
│   │   └── requirements.txt
│   ├── query_lambda/
│   │   ├── handler.py             — Full pipeline (see below)
│   │   ├── hyde.py                — HyDE via Sarvam + Titan embedding
│   │   ├── mmr.py                 — MMR diversification
│   │   ├── sarvam.py              — Two-key Sarvam calls
│   │   └── history.py             — Chat history fetch/save
│   ├── submit/
│   │   └── handler.py             — POST /query + POST /upload + GET /document-url
│   └── poll/
│       └── handler.py             — GET /result/{jobId}
├── sql/
│   ├── 001_extensions.sql
│   ├── 002_schema.sql
│   ├── 003_tables.sql
│   ├── 004_indexes.sql            — HNSW (m=16, ef_construction=64)
│   ├── 005_rls.sql
│   ├── 006_functions.sql          — hybrid_search, consume_voice_credit, refund_voice_credit
│   └── 007_triggers.sql
├── frontend/                      — Next.js 14 App Router
│   ├── app/
│   │   ├── (auth)/login/
│   │   ├── (auth)/register/
│   │   ├── (protected)/chat/
│   │   ├── (protected)/upload/
│   │   └── api/
│   │       ├── query/route.ts
│   │       ├── result/[jobId]/route.ts
│   │       ├── upload/route.ts
│   │       └── document-url/route.ts
│   ├── components/
│   │   ├── layout/
│   │   │   ├── ThreePanelLayout.tsx
│   │   │   ├── ConversationSidebar.tsx
│   │   │   ├── ChatWindow.tsx
│   │   │   └── DocumentPanel.tsx
│   │   └── chat/
│   │       ├── MessageBubble.tsx
│   │       ├── ChatInput.tsx
│   │       └── VoiceToggle.tsx
│   ├── lib/
│   │   ├── supabase/client.ts     — createBrowserClient from @supabase/ssr
│   │   └── supabase/server.ts     — createServerClient from @supabase/ssr
│   └── middleware.ts
├── fulltest.sh                    — E2E test (7 steps)
└── query_test.sh                  — RAG query test (5 questions)
```

---

## Database Schema (Supabase `rag` schema)

All tables live in the `rag` schema (not public).
All REST calls need headers: `Accept-Profile: rag` and `Content-Profile: rag`

```sql
-- Key tables:
rag.user_profiles    — id, display_name, voice_credits (default 3)
rag.documents        — id, user_id, filename, s3_key, status, chunk_count, skipped_pages, doc_metadata
rag.chunks           — id, document_id, user_id, content, embedding VECTOR(1024), fts TSVECTOR
rag.conversations    — id, user_id, title, created_at, updated_at
rag.messages         — id, conversation_id, user_id, role, content, voice_used, voice_url, retrieved_chunks

-- Key functions:
rag.hybrid_search(query_embedding, query_text, target_user_id, match_count)
  → Returns chunks ordered by RRF score (vector + BM25 fusion)

rag.consume_voice_credit(target_user_id)
  → Atomic decrement, returns TRUE if consumed

rag.refund_voice_credit(target_user_id)
  → Increments credit back (called on TTS failure)
```

---

## Query Pipeline (query_lambda/handler.py)

**Current working state — fully deployed:**

```
Step 0: Conversational check    (free — regex classifier)
Step 1: Cache check             (free — Redis GET)
Step 2: Check user has docs?    (free — Supabase count)

  NO docs → acquire router token → needs_retrieval() YES/NO
    NO  → direct_answer() [2 RAG tokens]
    YES → retrieval pipeline

  HAS docs → always retrieve (skip router entirely)

Step 3: Embed query             (free — Amazon Titan V2)
Step 4: Hybrid search           (free — Supabase HNSW + BM25 RRF)
Step 5: No candidates?          → direct_fallback [2 RAG tokens]
Step 6: RRF < MIN_USEFUL(0.005)?→ doc irrelevant → direct_fallback
Step 7: RRF < HYDE(0.02)?       → conditional HyDE [1 RAG token]
Step 8: MMR top-3               (free — Python, lambda=0.7)
Step 9: acquire_generate_tokens → generate_answer() [2 RAG tokens]
Step 10: voice mode             → Sarvam TTS → S3 presigned URL
Step 11: save history + cache + write Redis result
```

**Token budget per query:**

* Router: 1 (only when no docs)
* HyDE: 0 or 1 (conditional)
* Generate: 2 (always)
* Max: 3 tokens/query

---

## Rate Limiting (shared_lambda/rate_limiter.py)

Two independent Redis token buckets (Upstash REST — not TCP):

```python
ROUTER_REDIS_KEY = "rate_limit:sarvam:router"   # SARVAM_API_KEY_ROUTER calls
RAG_REDIS_KEY    = "rate_limit:sarvam:rag"       # SARVAM_API_KEY_RAG calls
BUCKET_CAPACITY  = 60  # tokens per 60 seconds
```

Functions: `acquire_router_token(r)`, `acquire_hyde_token(r)`, `acquire_generate_tokens(r)`
Each uses sliding window ZADD — individual calls, NOT pipeline (upstash REST doesn't support pipeline).

---

## Embedding: Amazon Titan V2

Replaced Voyage AI due to rate limiting. No API key needed — IAM grants `bedrock:InvokeModel`.

```python
# lambdas/ingestion_lambda/embedder.py
# lambdas/query_lambda/hyde.py (embed_query function)

bedrock_client = boto3.client("bedrock-runtime", region_name="ap-south-1")
MODEL_ID       = "amazon.titan-embed-text-v2:0"

body = json.dumps({
    "inputText":  text[:8000],
    "dimensions": 1024,
    "normalize":  True,    # required for cosine similarity
})

response = bedrock_client.invoke_model(
    modelId=MODEL_ID, body=body,
    contentType="application/json", accept="application/json"
)
embedding = json.loads(response["body"].read())["embedding"]
```

**IAM:** `bedrock:InvokeModel` on `arn:aws:bedrock:ap-south-1::foundation-model/amazon.titan-embed-text-v2:0`
Must be attached to: indexer, embed-worker, processor Lambdas.

---

## Ingestion Pipeline (Async Embed)

```
S3 PUT → SQS ingestion-queue → rag-indexer Lambda
  → download PDF (S3)
  → extract text (PyMuPDF)
  → chunk (500 chars, 50 overlap)
  → store chunks with embedding=NULL → status: indexing
  → enqueue 32-chunk batches to rag-embed-queue

rag-embed-worker Lambda (per batch):
  → fetch chunk content from Supabase
  → embed via Titan (~100ms per chunk, no rate limits)
  → update chunks with embeddings
  → last batch → document status: ready
```

S3 key format: `uploads/{user_id}/{document_id}/{filename}`

---

## Sarvam AI Integration (sarvam.py)

Two keys, two purposes:

* `SARVAM_API_KEY_ROUTER` → `needs_retrieval()` only
* `SARVAM_API_KEY_RAG` → `generate_answer()`, `direct_answer()`, HyDE

**Critical bug already fixed:** `needs_retrieval()` uses `re.finditer` to find
the LAST YES/NO position in the full response (including inside `<think>` tags).
Sarvam-m outputs chain-of-thought in `<think>` blocks that hit max_tokens at
low limits — the closing `</think>` tag never appears, so simple stripping fails.
Solution: `max_tokens=1024` + find last YES/NO position in raw response.

```python
yes_positions = [m.start() for m in re.finditer(r'\bYES\b', raw.upper())]
no_positions  = [m.start() for m in re.finditer(r'\bNO\b',  raw.upper())]
last_yes = yes_positions[-1] if yes_positions else -1
last_no  = no_positions[-1]  if no_positions  else -1
result   = last_yes > last_no if (last_yes != -1 or last_no != -1) else True
```

---

## Supabase Client (shared_lambda/supabase_client.py)

All table calls use `.schema("rag")`:

```python
supabase.schema("rag").table("documents").select(...)
supabase.schema("rag").rpc("hybrid_search", {...})
```

JWT verification uses JWKS (ES256/RS256), not legacy secret:

```python
# auth.py
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
algorithms=["RS256", "ES256"]
```

---

## Frontend (Next.js 14)

**Package:** `@supabase/ssr` (NOT auth-helpers-nextjs — that's deprecated)

```typescript
// lib/supabase/client.ts — for Client Components
import { createBrowserClient } from '@supabase/ssr'
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  )
}

// lib/supabase/server.ts — for Server Components + API routes
import { createServerClient } from '@supabase/ssr'
```

**Three-panel layout:**

* Left 20%: Conversation history sidebar
* Center 50%: Chat window
* Right 30%: Document panel (list + PDF preview)

**PDF Preview flow:**

1. User clicks "Preview" on a ready document card
2. Modal opens → fetches `/api/document-url?document_id=xxx`
3. Next.js route proxies to Lambda `/document-url`
4. Lambda verifies JWT + ownership → presigned S3 GET URL (1hr)
5. URL set as iframe src — renders inline with `ResponseContentDisposition: inline`

**Query flow (async):**

1. POST to `/api/query` → proxies to Lambda
2. If `job_id` returned → poll `/api/result/{jobId}` every 2s
3. If `status: done` with no `job_id` → cache/conversational hit, instant
4. Response shape: `{ status, answer, cached, voice_url, voice_credits_remaining, tokens_used, path }`

**Supabase direct calls (client-side) all need rag schema headers:**

```typescript
supabase.schema('rag').from('conversations').select(...)
```

---

## Current Status

### ✅ Working

* All 7 E2E test steps passing
* Auth (ES256 JWT)
* Conversational classifier (instant, 0 tokens)
* Redis caching
* SQS async pipeline
* Titan embeddings (no rate limits, ~100ms/chunk)
* Hybrid search (HNSW + BM25 + RRF)
* Smart routing (has docs → always retrieve, RRF threshold for fallback)
* HyDE (conditional, strips think tags correctly)
* MMR diversification
* Answer generation (Sarvam RAG key)
* Chat history (last 6 messages)
* PDF upload (presigned PUT URL)
* PDF indexing (async embed worker)
* Document preview (presigned GET URL, iframe)
* Frontend: auth, chat, document panel, PDF preview modal
* Voice credits tracking in DB

### ⚠️ Known Issues / Pending

1. **Voice (TTS) returning null** — check CloudWatch logs for rag-processor
   * Likely: voice_credits = 0 for test user, OR Sarvam TTS API error
   * Fix: `UPDATE rag.user_profiles SET voice_credits = 3 WHERE id = 'user-uuid'`
   * Also verify `refund_voice_credit` function exists in Supabase
2. **Markdown rendering in chat** — answers contain `**bold**` syntax shown as raw text
   * Fix: add `react-markdown` to frontend and wrap MessageBubble content
3. **query_test.sh cache issue** — re-running shows cached answers, not live RAG
   * Fix: append timestamp to questions to bust cache on each run

---

## Planned Verticals (Phase 2+)

Five verticals planned, all on same backend (different prompt templates + new tables):

| Vertical        | Status  | Key Difference                                                          |
| --------------- | ------- | ----------------------------------------------------------------------- |
| RAG (current)   | ✅ Live | Document Q&A                                                            |
| Citation Finder | Phase 2 | RAG + citation tracking, returns `[Doc: filename, Page: X]`           |
| Job Search      | Phase 3 | Resume indexing + skill gap + cover letter generation                   |
| HR Assistant    | Phase 4 | **Org-scoped**RAG (employees share company docs) — different RLS |
| Fitness Planner | Phase 5 | Profile-based coaching, no retrieval needed                             |
| Travel Planner  | Phase 6 | Multi-step itinerary (needs LangGraph)                                  |

**HR is architecturally different** — chunks scoped to `org_id` not `user_id`.
All others are user-scoped like the current system.

---

## LangGraph (Phase 4)

Planned upgrade for CRAG (Corrective RAG):

```
Current: linear pipeline (retrieve → generate)
Future:  graph (retrieve → grade chunks → generate → grade answer → retry if bad)
```

Current Lambda functions become graph nodes. Nothing gets thrown away.
Key new capability: self-correction loop when answer is hallucinated.

---

## Infrastructure Notes

### CDK Stacks

* `RagStorageStack` — S3, SQS
* `RagComputeStack` — All Lambdas + IAM
* `RagApiStack` — API Gateway routes

### Deploy command

```bash
rm -rf infrastructure/cdk.out
cd infrastructure
cdk deploy RagComputeStack   # or --all for everything
```

### IAM gotcha

`secret.grant_read()` in CDK uses exact ARN — AWS appends 6-char suffix at creation.
Always use wildcard: `arn:aws:secretsmanager:region:account:secret:prod/serverless-rag-secrets-*`

### Supabase schema exposure

`rag` schema must be exposed in:
`Supabase Dashboard → Settings → API → Data API → Exposed schemas`

Also run after any schema changes:

```sql
GRANT USAGE ON SCHEMA rag TO anon, authenticated, service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rag TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA rag TO anon, authenticated, service_role;
NOTIFY pgrst, 'reload config';
```

### Upstash Redis

Must use REST client (`upstash-redis`), NOT `redis-py` (TCP not supported in Lambda).
Pipeline NOT supported in upstash REST — use individual calls.

### Lambda package sizes

* ingestion_lambda and embed_worker → Docker/ECR (PyMuPDF + LangChain exceed 250MB zip limit)
* All other Lambdas → zip with shared layer

---

## Test Users

* Email: `ragtest@yopmail.com`
* User ID: `cc2d9741-031e-4a99-a79f-8725acf50116`
* Test conversation: `cccccccc-cccc-cccc-cccc-cccccccccccc`

---

## Immediate Next Tasks

1. **Fix voice (TTS)**
   * Check CloudWatch: `aws logs tail /aws/lambda/rag-processor --region ap-south-1 --since 10m | grep -i voice`
   * Reset credits: `UPDATE rag.user_profiles SET voice_credits = 3 WHERE id = 'cc2d9741-031e-4a99-a79f-8725acf50116'`
   * Verify `refund_voice_credit` SQL function exists in rag schema
2. **Fix markdown rendering in frontend**
   * `npm install react-markdown`
   * Wrap MessageBubble answer content in `<ReactMarkdown>`
3. **Fix query_test.sh cache busting**
   * Add `TIMESTAMP=$(date +%s)` and append to each question
4. **Citation Finder vertical (Phase 2)**
   * Same backend, new prompt template
   * Answer format: `"K-means [Doc: ml_notes.pdf, Page: 3]"`
   * New table: `rag.citation_collections`
   * New API route: POST /citations/export (APA/MLA/BibTeX)
5. **Frontend polish**
   * Markdown rendering in chat bubbles
   * Responsive mobile layout (single panel)
   * Loading skeletons
   * Toast notifications for errors

---

## Key Decisions Made (don't revisit these)

| Decision                    | Reason                                                |
| --------------------------- | ----------------------------------------------------- |
| Titan V2 over Voyage AI     | No rate limits, same region, ~$0.03/month             |
| Upstash REST over redis-py  | TCP not supported in Lambda                           |
| Supabase rag schema         | Cleaner isolation, all tables in one schema           |
| ES256 JWT via JWKS          | Supabase default, not legacy HS256 secret             |
| Async embed pipeline        | Decouples indexing from embedding, handles large PDFs |
| Skip router when docs exist | Users always want doc answers, saves 1 token/query    |
| MIN_USEFUL_RRF = 0.005      | Only filters truly irrelevant queries like "2+2"      |
| Two Sarvam API keys         | Independent rate limits for routing vs generation     |
| Docker for ingestion Lambda | PyMuPDF + LangChain exceed 250MB zip limit            |

---

## Debugging Commands

```bash
# Check processor logs
aws logs tail /aws/lambda/rag-processor --region ap-south-1 --since 10m

# Check indexer logs
aws logs tail /aws/lambda/rag-indexer --region ap-south-1 --since 10m

# Check embed worker logs
aws logs tail /aws/lambda/rag-embed-worker --region ap-south-1 --since 10m

# Check submit lambda logs
aws logs tail /aws/lambda/rag-submit --region ap-south-1 --since 10m

# Flush Redis cache (Upstash console → CLI → FLUSHDB)
# Or via REST:
curl -X POST "YOUR_UPSTASH_URL/flushdb" -H "Authorization: Bearer YOUR_TOKEN"

# Check document status in Supabase
SELECT id, filename, status, chunk_count FROM rag.documents WHERE user_id = 'USER_UUID';

# Reset voice credits
UPDATE rag.user_profiles SET voice_credits = 3 WHERE id = 'USER_UUID';

# Check all rag functions exist
SELECT routine_name FROM information_schema.routines WHERE routine_schema = 'rag';
```
