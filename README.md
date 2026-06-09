# MindAgent - RAG

Production-grade serverless Retrieval-Augmented Generation (RAG) system: users upload PDFs, ask questions, and get answers grounded in their own documents (optionally with text-to-speech).

Supports **multi-document reasoning**: users can select multiple documents when starting a conversation and ask questions that span all of them. Retrieval, HyDE, structured queries (page/section lookups), and MMR reranking all operate across the selected document set.

Target operating cost is designed to be low (on the order of a few hundred INR/month for small usage), primarily by using async pipelines + Voyage AI embeddings (free tier: 200M tokens/month).

## Live environment (current)

- **API Gateway endpoint:** https://om6deoefoe.execute-api.ap-south-1.amazonaws.com
- **AWS region:** `ap-south-1`
- **AWS Secrets Manager secret name:** `prod/serverless-rag-secrets`
- **Supabase project:** https://juzxjfnjysbzymbijzsv.supabase.co

API routes (HTTP API):

- `POST /query`
- `GET /result/{jobId}`
- `POST /upload`
- `GET /document-url`

Note: This README intentionally lists only identifiers/endpoints and secret *key names* — not secret values.

## What this repo contains

- **Frontend app** (Next.js) for auth, uploading PDFs, and chatting.
- **Serverless backend** (AWS Lambda) that runs two asynchronous pipelines:
  - **Ingestion**: extract → chunk → embed → store
  - **Query**: retrieve → rerank → generate → cache → return job result
- **Infrastructure as code** (AWS CDK) for S3/SQS/Lambda/API Gateway.
- **Supabase SQL** migrations for the `rag` schema (tables, RLS, indexes, RPC functions).

## High-level architecture

### Query pipeline (async)

```
Browser → Next.js Route Handler → API Gateway
  → POST /query → Submit Lambda → SQS (query queue)
                 → Query Processor Lambda
                 → Upstash Redis (job:{job_id})
Browser → Next.js Route Handler → API Gateway
  → GET /result/{jobId} → Poll Lambda → Redis
```

### Ingestion pipeline (async)

```
Browser → Next.js Route Handler → API Gateway → POST /upload → presigned S3 PUT URL
Browser           → S3 (uploads/{user_id}/{document_id}/{filename}.pdf)
S3 PUT event       → SQS (ingestion queue) → Indexer Lambda
Indexer Lambda     → Supabase (store chunks, embedding=NULL)
                  → SQS (embed queue) → Embed Worker Lambda
Embed Worker       → AWS Bedrock Titan (embeddings)
                  → Supabase (write embeddings; mark document ready)
```

## Tech stack

### Frontend

- **Next.js (App Router)** + **React** + **TypeScript**
- **Tailwind CSS** + **shadcn/ui** (Radix-based component primitives)
- **Supabase Auth** via `@supabase/ssr` / `@supabase/supabase-js`
- Next.js Route Handlers used as an API proxy (`frontend/app/api/*`) to the backend API Gateway

### Backend (Lambdas)

- **Python 3.11** on **AWS Lambda**
- **API Gateway HTTP API**
- **SQS** for asynchronous job processing (query, ingestion, embeddings)
- **S3** for PDF uploads and optional voice outputs
- **AWS Secrets Manager** for runtime secrets (via `SECRET_NAME`)
- **Upstash Redis** (REST) for:
  - job results (`job:{job_id}`)
  - answer cache (`cache:{user_id}:{sha256(query)}`)
  - Sarvam token-bucket rate limiting
- **Supabase (Postgres)** via `supabase-py` (service role for backend)

### AI / Retrieval

- **Embeddings**: Voyage AI (`voyage-3-large`, 1024-dim) for both query and document chunks
- **LLM**: Sarvam AI (`sarvam-m`) for answer generation, routing, and HyDE; `<think>` tags always stripped before use
- **HyDE**: generates a hypothetical answer (Sarvam), embeds it (Voyage), and re-runs retrieval when direct RRF score is weak (< 0.02)
- **Hybrid retrieval**: Supabase RPC combining HNSW vector search + GIN keyword search scored via RRF — works across a single document, a selected set of documents (`hybrid_search_multi_doc`), or all user documents
- **Reranking**: Maximal Marginal Relevance (MMR, λ=0.7) in Python; requires embeddings to be returned by the search RPC
- **Optional TTS**: Sarvam Text-to-Speech → audio stored in S3 with a presigned GET URL

## Key design decisions

- **Async everywhere:** SQS is used because API Gateway has a hard timeout; query + ingestion work happens in background Lambdas.
- **Voyage AI embeddings:** free tier (200M tokens/month) with 1024-dim output to match `VECTOR(1024)`. `input_type` differs for query vs document.
- **Multi-document reasoning:** a `conversation_documents` junction table links a conversation to any number of documents. The query pipeline detects `document_ids[]` and routes to `hybrid_search_multi_doc` (PostgreSQL `= ANY(doc_ids)` filter) instead of single-doc search. Cache keys hash the sorted doc-ID list so the same document set in any selection order always hits the same cache entry.
- **Upstash Redis REST client:** Lambda-friendly (no TCP), and used for cache + job results + rate-limiting buckets.
- **JWT verification via Supabase HS256:** extracts `user_id` from Authorization header locally; avoids a network round-trip.
- **Skip the router when docs exist:** if a user has ready documents, retrieval is always attempted; a low RRF score triggers a direct fallback.

## Rate limiting and token budget

- Two Upstash-backed sliding-window token buckets:
  - router bucket (routing decisions)
  - rag bucket (HyDE + generation + TTS)
- Budget per query is designed to be small:
  - router: 0–1 token (only when user has no ready docs)
  - HyDE: 0–1 token (conditional on weak retrieval signal)
  - generation: 2 tokens (required)

### Infrastructure

- **AWS CDK v2** (Python) in `infrastructure/`
- Stacks:
  - `StorageStack`: S3 buckets + SQS queues + S3→SQS event notification
  - `ComputeStack`: Lambdas, shared Lambda layer, IAM permissions
  - `ApiStack`: API Gateway routes (`/query`, `/result/{jobId}`, `/upload`, `/document-url`)

## Repository structure

- `frontend/` — Next.js web app
- `lambdas/` — Lambda handlers and shared code
  - `submit/` — handles `/query`, `/upload`, `/document-url`
  - `poll/` — handles `/result/{jobId}`
  - `query_lambda/` — query processor (RAG pipeline)
  - `ingestion_lambda/` — indexer + embed worker (container-based)
  - `shared_lambda/` — auth, secrets, Supabase client, rate limiting
- `infrastructure/` — AWS CDK app and stacks
- `sql/` — Supabase/Postgres schema, RLS, functions, indexes
- `__tests__/` — local test scripts (expects `.env` with at least `AWS_REGION` and `SECRET_NAME`)

## Local development (quickstart)

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Expected environment variables (frontend):

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_API_ENDPOINT` (API Gateway endpoint from CDK output)

### Backend / scripts

This repo’s Lambdas fetch credentials via AWS Secrets Manager. For local scripts/tests you typically need AWS credentials configured (with permission to call `secretsmanager:GetSecretValue`) and an `.env` file with:

- `AWS_REGION`
- `SECRET_NAME` (example: `prod/serverless-rag-secrets`)

The Secrets Manager secret value is expected to be a JSON object containing (names only):

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `SUPABASE_ANON_KEY`
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`
- `SARVAM_API_KEY_ROUTER`
- `SARVAM_API_KEY_RAG`
- `VOYAGE_API_KEY`

Python deps:

```bash
pip install -r requirements.txt
```

## Deployment (AWS CDK)

Infrastructure code lives in `infrastructure/` (AWS CDK v2, Python). Stacks are deployed in dependency order (CDK handles references automatically).

Typical deploy workflow:

```bash
rm -rf infrastructure/cdk.out
cd infrastructure
cdk deploy --all
```

## Supabase notes

- All tables/functions live under the `rag` schema (not `public`).
- Ensure the `rag` schema is exposed in: Supabase Dashboard → Settings → API → Data API → Exposed schemas.
- SQL migrations in `sql/` are applied manually in filename order. Migrations applied to production:
  - `001–011`: base schema, indexes, RLS, functions, triggers, page/section query helpers
  - `012_multi_doc.sql`: `conversation_documents` junction table + `hybrid_search_multi_doc()` RPC
  - `013_multi_doc_structured_queries.sql`: extends `get_chunks_by_page` / `get_chunks_by_section` to accept `target_doc_ids UUID[]`
  - `014_multi_doc_embedding_return.sql`: adds `embedding` column to `hybrid_search_multi_doc` return for MMR reranking

## Known issues / next fixes

- **Voice (TTS) returns `null`:** likely no credits or Sarvam TTS error; check `rag-processor` logs and verify `rag.refund_voice_credit()` exists.
- **Cache busting for query tests:** repeated test runs can hit Redis cache; append a timestamp to the question text when testing “live” behavior.

## Debugging commands

Tail Lambda logs (requires AWS CLI credentials):

```bash
aws logs tail /aws/lambda/rag-processor --region ap-south-1 --since 10m
aws logs tail /aws/lambda/rag-indexer --region ap-south-1 --since 10m
aws logs tail /aws/lambda/rag-embed-worker --region ap-south-1 --since 10m
aws logs tail /aws/lambda/rag-submit --region ap-south-1 --since 10m
aws logs tail /aws/lambda/rag-poll --region ap-south-1 --since 10m
```

Supabase sanity checks:

```sql
-- Document status
SELECT id, filename, status, chunk_count
FROM rag.documents
WHERE user_id = 'USER_UUID';

-- Ensure expected functions exist
SELECT routine_name
FROM information_schema.routines
WHERE routine_schema = 'rag';
```

## Notes

- The Supabase service role key is **server-side only** (Lambdas). Never expose it in the frontend.
- SQL files in `sql/` are intended to be applied manually to Supabase (schema, RLS, RPC functions).
- For deeper architectural detail (pipeline steps, thresholds, conventions), see `CLAUDE.md`.
