# Ingestion Lambda — Memory & Latency Fix Task List

## Problem Summary

The current ingestion handler uses a two-pass approach:

1. **Two-pass chunking** — chunks ALL windows before storing any → pipeline stall (~3–4s delay before first embed job is enqueued)
2. **Full chunk list held in memory** — `windows_chunks: list[list[dict]]` holds every chunk for every window simultaneously (~2.5MB avoidable overhead)
3. **Peak memory ~115MB** during PDF extraction — dangerously close to 128MB Lambda limit (PyMuPDF holds full PDF bytes + internal page tree)
4. **8 extra Supabase round-trips** for incremental progress updates — ~800ms of unnecessary blocking latency
5. **MAX_SQS_WORKERS=8** — 8 thread stacks × 8MB virtual = 64MB virtual address overhead; SQS calls are fast (~20ms) and don't need this many

---

## Task List

### Task 1 — Add `finalize` message type to `embed_worker.py`

**File:** `lambdas/ingestion_lambda/embed_worker.py`

- Add a `message_type` field check in `_process_record` (or equivalent entry point)
- When `message_type == "finalize"`: mark document `status = "ready"`, update `chunk_count` from DB count, return immediately
- When `message_type == "embed"`: embed chunks and write embeddings back (existing behaviour, unchanged)
- Remove `is_last_batch` check from the embed path entirely — finalize message replaces it

**Finalize SQS message shape:**
```json
{ "message_type": "finalize", "document_id": "uuid", "user_id": "uuid" }
```

**Embed SQS message shape (add `message_type`):**
```json
{ "message_type": "embed", "document_id": "uuid", "chunk_ids": ["..."], "batch_num": 1 }
```

---

### Task 2 — Remove `total_embed_batches` / `is_last_batch` from `handler.py`

**File:** `lambdas/ingestion_lambda/handler.py`

- Delete `total_embed_batches` calculation (the entire first pass)
- Delete `global_batch_num` counter
- Remove `is_last_batch` from `_send_embed_message` signature and SQS message body
- Simplify `_enqueue_window` — remove `global_batch_num_start` and `total_embed_batches` params

---

### Task 3 — Rewrite handler to single-pass streaming

**File:** `lambdas/ingestion_lambda/handler.py`

Replace the two-pass loop with a true single-pass:

```python
global_chunk_offset = 0
failed_windows = 0
total_chunks_stored = 0

for w_idx, window_pages in enumerate(windows):
    try:
        chunks = chunk_pages(window_pages, global_chunk_offset=global_chunk_offset)
        chunks = _deduplicate(chunks, global_chunk_offset)
    except Exception as e:
        failed_windows += 1
        continue

    try:
        chunk_ids = _store_window(chunks, document_id, user_id)
        global_chunk_offset += len(chunk_ids)
        total_chunks_stored += len(chunk_ids)
        _enqueue_window(chunk_ids, document_id, user_id)
    except Exception as e:
        failed_windows += 1

# After all windows — send finalize instead of setting status=ready here
_send_finalize_message(document_id, user_id)

final_status = "indexing" if failed_windows == 0 else "partial"
_update_document(document_id, {"status": final_status, "chunk_count": total_chunks_stored})
```

Key result: first embed job is enqueued after window 0 completes (~9s), not after all windows are chunked (~13s).

---

### Task 4 — Make per-window progress updates non-blocking

**File:** `lambdas/ingestion_lambda/handler.py`

- Submit `_update_document` calls to a background single-worker executor — do NOT block the main loop on them
- Pattern:

```python
with ThreadPoolExecutor(max_workers=1) as progress_pool:
    for w_idx, window_pages in enumerate(windows):
        ...
        # fire-and-forget, never call .result()
        progress_pool.submit(_update_document, document_id, {
            "chunk_count": total_chunks_stored,
            "windows_processed": w_idx + 1,
        })
```

- The final `_update_document` (status + chunk_count) after the loop stays blocking — it must complete before Lambda exits.

---

### Task 5 — Reduce `MAX_SQS_WORKERS` default from 8 to 4

**File:** `lambdas/ingestion_lambda/handler.py`

```python
# Before
MAX_SQS_WORKERS = int(os.getenv('MAX_SQS_WORKERS', '8'))

# After
MAX_SQS_WORKERS = int(os.getenv('MAX_SQS_WORKERS', '4'))
```

SQS `send_message` latency is ~20ms. 4 concurrent workers provides sufficient throughput while halving thread stack virtual address overhead (64MB → 32MB).

---

### Task 6 — Increase ingestion Lambda memory to 256 MB

*(See AWS CLI guide below)*

- Target: `ingestion_lambda` only — 128MB → 256MB
- `embed_worker` Lambda stays at 128MB (no PDF bytes in memory, just chunk text)
- Rationale: PyMuPDF peak RSS ~115MB on a 40-page PDF; 256MB gives safe headroom for larger documents
- Side effect: Lambda CPU allocation doubles proportionally — speeds up PyMuPDF extraction and structure_detector regex

---

### Task 7 — Apply SQL migration `011`

**File:** `sql/011_section_query_and_partial_status.sql`

Apply to Supabase manually via the SQL editor or psql:

```sql
\i sql/011_section_query_and_partial_status.sql
```

This migration adds:
- `partial` to `documents.status` CHECK constraint
- `rag.get_chunks_by_section()` function for section-based retrieval
- GIN index on `chunks.metadata` for fast JSONB queries

---

### Task 8 — End-to-end validation

- Upload a 100+ page PDF
- Confirm `status` transitions: `processing` → `indexing` → `ready`
- Confirm `windows_processed` increments in `doc_metadata` after each window
- Confirm embed_worker receives finalize message and sets `status = "ready"`
- Confirm first embed SQS message appears within ~9s (CloudWatch Logs timestamp on embed_worker invocation)
- Check CloudWatch `REPORT Max Memory Used` — should stay under 200MB

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/YOUR_INGESTION_LAMBDA_NAME \
  --filter-pattern "Max Memory Used" \
  --region ap-south-1 \
  --limit 10 \
  --query 'events[*].message'
```

---

## AWS CLI Guide — Increase Lambda Memory

### Prerequisites

```bash
# Confirm CLI is authenticated
aws sts get-caller-identity

# Check current config
aws lambda get-function-configuration \
  --function-name YOUR_INGESTION_LAMBDA_NAME \
  --region ap-south-1 \
  --query '[MemorySize, Timeout]'
```

### Step 1 — Find the function name

```bash
aws lambda list-functions \
  --region ap-south-1 \
  --query 'Functions[*].[FunctionName,MemorySize]' \
  --output table
```

### Step 2 — Set memory to 256 MB

```bash
aws lambda update-function-configuration \
  --function-name YOUR_INGESTION_LAMBDA_NAME \
  --memory-size 256 \
  --region ap-south-1
```

### Step 3 — Verify

```bash
aws lambda get-function-configuration \
  --function-name YOUR_INGESTION_LAMBDA_NAME \
  --region ap-south-1 \
  --query 'MemorySize'
# Expected: 256
```

### Step 4 — (Optional) Update env vars in the same call

```bash
aws lambda update-function-configuration \
  --function-name YOUR_INGESTION_LAMBDA_NAME \
  --memory-size 256 \
  --environment "Variables={
    PDF_BUCKET_NAME=your-bucket,
    EMBED_QUEUE_URL=https://sqs.ap-south-1.amazonaws.com/ACCOUNT/your-embed-queue,
    SECRET_NAME=prod/serverless-rag-secrets,
    INGEST_WINDOW_SIZE=50,
    INGEST_WINDOW_OVERLAP=3,
    STORE_BATCH_SIZE=100,
    MAX_STORE_WORKERS=4,
    MAX_SQS_WORKERS=4
  }" \
  --region ap-south-1
```

### Step 5 — Monitor memory in CloudWatch

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/YOUR_INGESTION_LAMBDA_NAME \
  --filter-pattern "Max Memory Used" \
  --region ap-south-1 \
  --limit 20 \
  --query 'events[*].message'
```

Look for `REPORT ... Max Memory Used: NNN MB`. After the fix, this should read well under 200MB.

### Notes

- Memory changes take effect immediately — no redeployment needed
- Lambda CPU scales proportionally with memory: 256MB → ~2× CPU vs 128MB, which also speeds up PyMuPDF and structure_detector regex
- If infrastructure is managed via CDK or Terraform, update the memory setting there too to avoid drift on next deploy
- `embed_worker` Lambda does not need this change — it only handles chunk text, not raw PDF bytes
