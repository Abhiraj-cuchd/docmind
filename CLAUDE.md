# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run a specific lambda handler locally (example)
PYTHONPATH=lambdas python -m pytest lambdas/

# Lint
pip install ruff && ruff check lambdas/
```

No build or deployment configs exist in this repo — infrastructure lives elsewhere. SQL migrations in `sql/` must be applied manually to Supabase.

---

## Architecture Overview

Serverless RAG system: users upload PDFs, ask questions, get LLM-generated answers grounded in their documents.

**Two async pipelines, both SQS-triggered:**

```
POST /query → Submit Lambda → SQS → Query Lambda → Redis (job result)
                                                         ↑
GET /result/{jobId} ← Poll Lambda ───────────────────────┘

S3 PUT (PDF) → SNS → SQS → Ingestion Lambda → Supabase (chunks + embeddings)
```

**Why SQS?** API Gateway has a 29-second timeout. Query processing takes 8–15 seconds and may need to wait for rate-limited tokens. SQS lets the HTTP response return immediately while processing continues async.

---

## Lambda Responsibilities

| Lambda | Trigger | Role |
|--------|---------|------|
| `submit_lambda` | HTTP POST /query | JWT verify → cache check → enqueue → return `{job_id}` |
| `poll_lambda` | HTTP GET /result/{jobId} | Read Redis job key → return status/answer |
| `query_lambda` | SQS | Full RAG pipeline (see below) |
| `ingestion_lambda` | SQS (from S3 SNS) | PDF → extract → chunk → embed → store |

---

## Query Pipeline (query_lambda)

Token-aware pipeline. Sarvam AI is rate-limited to 60 calls/60s enforced via a Redis sliding-window token bucket. The system never degrades quality — it either runs full pipeline or re-queues.

```
0. Conversational check    (regex, 0 tokens, ~5ms)
1. Redis cache check       (0 tokens)
2. Save user message       (Supabase insert)
3. Fetch history           (last 3 Q&A pairs)
4. Embed query             (Voyage AI, free)
5. Hybrid search           (Supabase RPC: vector HNSW + keyword GIN → RRF score)
6. Conditional HyDE        (if top RRF score < 0.02 → 1 Sarvam token, 15s timeout)
7. MMR rerank              (top 3 chunks, λ=0.7, free)
8. Acquire generation tokens (2 tokens, wait up to 45s → raise to re-queue if unavailable)
9. Generate answer         (Sarvam AI)
10. Voice TTS              (optional, uses voice credit, uploads to S3)
11. Cache + history save + write job result to Redis
```

**HyDE threshold (0.02):** Derived from RRF math. Rank-1 in both lists ≈ 0.033; rank-1 in one list ≈ 0.016. 0.02 means at least one retrieval signal is confident → skip HyDE.

**Re-queue pattern:** Generation token timeout raises `Exception("RATE_LIMIT_WAIT")`. The handler catches this and re-raises without writing to Redis, so SQS does not delete the message — it returns to the queue automatically.

---

## Shared Modules (`lambdas/shared_lambda/`)

- **`supabase_client.py`** — Singleton service-role client (bypasses RLS), per-request user-scoped client (respects RLS), `execute_hybrid_search()`, `consume_voice_credit()`, `refund_voice_credit()`
- **`rate_limiter.py`** — Redis sliding-window token bucket. `acquire_tokens(cost, timeout_s)` blocks with exponential backoff.
- **`auth.py`** — Local JWT verify (HS256, audience=`"authenticated"`), extracts `user_id` from Authorization header
- **`secrets.py`** — AWS Secrets Manager with in-memory cache per Lambda warm instance

---

## Database (Supabase / PostgreSQL)

Schema: `rag`. All tables have RLS; service role bypasses it. `user_id` is denormalized onto `chunks` and `messages` for single-column index scans.

Key tables: `user_profiles`, `documents`, `chunks` (VECTOR(1024) + tsvector), `conversations`, `messages`.

Key SQL functions (`sql/006_functions.sql`):
- `rag.hybrid_search(...)` — Combines HNSW vector search + GIN keyword search via RRF
- `rag.consume_voice_credit(target_user_id)` — Atomic decrement, returns BOOL
- `rag.refund_voice_credit(target_user_id)` — Atomic increment (called on TTS failure)

Trigger (`sql/007_triggers.sql`): `on_auth_user_created` auto-provisions `rag.user_profiles` on Supabase Auth signup.

---

## External Services

| Service | Used for | Notes |
|---------|---------|-------|
| Voyage AI | Embeddings (query + docs) | Free tier 200M tokens/mo; `input_type` differs for query vs document |
| Sarvam AI (`sarvam-m`) | HyDE, answer generation, TTS | Rate-limited; output contains `<think>` tags — always strip before use |
| Supabase | PostgreSQL + Auth + RLS | Service role for Lambdas, user-scoped JWT client for RLS enforcement |
| Upstash Redis | Token bucket + job cache + query cache | Serverless Redis; TTL=3600s for jobs and cached answers |
| AWS S3 | PDF uploads, voice WAV output | Pre-signed URLs for frontend access (24hr expiry) |
| AWS Secrets Manager | All API keys/credentials | Cached in-memory per warm Lambda instance |

---

## Key Conventions

- **`PYTHONPATH=lambdas`** — All imports are relative to `lambdas/`. `shared_lambda` and `query_lambda` are packages importable at that root.
- **Sarvam output** — Always strip `<think>...</think>` tags before using output as embeddings or returning to user. See `hyde.py` and `sarvam.py`.
- **Voice credits** — Always use `consume_voice_credit()` RPC before TTS, `refund_voice_credit()` RPC on failure. Never update `voice_credits` directly via `.update()`.
- **Token acquisition order** — HyDE token (optional, 15s) always acquired before generation token (required, 45s). Never acquire generation first.
- **Cache key format** — `cache:{user_id}:{sha256(query.lower().strip())}` — user-scoped because each user's docs differ.
- **Job result key format** — `job:{job_id}` — read by poll_lambda, written by query_lambda.
