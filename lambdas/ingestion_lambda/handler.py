# lambdas/ingestion_lambda/handler.py
#
# Ingestion pipeline — windowed streaming edition.
#
# Flow per document:
#   extract_text_from_pdf  → all pages (held once, then windowed)
#   for each window of WINDOW_SIZE pages:
#       chunk_pages(window)              → section-aware chunks
#       _store_window (ThreadPool)       → parallel batch inserts to Supabase
#       _enqueue_window (ThreadPool)     → parallel SQS embed-job sends
#       _update_progress                 → incremental chunk_count on document
#   mark document "indexing" when all windows enqueued
#   embed_worker marks "ready" on finalize message
#
# Why windowed?
#   A 400-page PDF produces ~1800 chunks. Without windowing, if Lambda
#   times out after 14 minutes (hard limit: 15), all progress is lost.
#   With windowing, chunks stored in earlier windows are preserved.
#   The document ends up partially indexed (status="partial") rather
#   than stuck in "processing" forever.
#
# Concurrency:
#   MAX_STORE_WORKERS  — parallel Supabase batch inserts (I/O bound)
#   MAX_SQS_WORKERS    — parallel SQS send_message calls (I/O bound)
#   Both are capped via env vars so Lambda doesn't spawn unbounded threads.

import json
import os
import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from shared_lambda.supabase_client import get_service_client
from extractor import download_pdf_from_s3, extract_text_from_pdf
from chunker import chunk_pages

supabase   = get_service_client()
PDF_BUCKET = os.getenv("PDF_BUCKET_NAME")
EMBED_QUEUE_URL = os.getenv("EMBED_QUEUE_URL")

import boto3
sqs = boto3.client("sqs")

# ── Tunables (all overridable via Lambda env vars) ────────────────────
EMBED_BATCH_SIZE  = 32
WINDOW_SIZE       = int(os.getenv("INGEST_WINDOW_SIZE",    "50"))
WINDOW_OVERLAP    = int(os.getenv("INGEST_WINDOW_OVERLAP", "3"))
STORE_BATCH_SIZE  = int(os.getenv("INGEST_STORE_BATCH",    "100"))
MAX_STORE_WORKERS = int(os.getenv("MAX_STORE_WORKERS",     "4"))
MAX_SQS_WORKERS   = int(os.getenv("MAX_SQS_WORKERS",       "4"))


# ─────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

def handler(event, context):
    print(f"[Handler] Received {len(event['Records'])} SQS record(s)")
    for record in event["Records"]:
        _process_record(record)


def _process_record(record: dict) -> None:
    s3_bucket, s3_key, user_id, document_id, filename = _parse_sqs_record(record)
    print(f"[Handler] document={document_id} user={user_id} file={filename}")
    _update_document(document_id, {"status": "processing"})

    try:
        # ── Step 1: Download ──────────────────────────────────────
        print(f"[Handler] Step 1 — Downloading PDF")
        pdf_bytes = download_pdf_from_s3(PDF_BUCKET, s3_key)

        # ── Step 2: Extract ───────────────────────────────────────
        print(f"[Handler] Step 2 — Extracting text")
        extraction   = extract_text_from_pdf(pdf_bytes, s3_key, filename)
        pages        = extraction["pages"]
        doc_metadata = extraction["document_metadata"]
        skipped      = extraction["skipped_pages"]
        # Release raw bytes — no longer needed
        del pdf_bytes

        print(f"[Handler] Extracted {len(pages)} pages, "
              f"{len(skipped)} skipped")

        # ── Step 3: Build page windows ────────────────────────────
        windows = _build_windows(pages, WINDOW_SIZE, WINDOW_OVERLAP)
        total_windows = len(windows)
        print(f"[Handler] {total_windows} window(s) of ≤{WINDOW_SIZE} pages "
              f"(overlap={WINDOW_OVERLAP})")

        # ── Step 4: Process each window ───────────────────────────
        total_chunks_stored = 0
        window_stats        = {}
        global_chunk_offset = 0
        failed_windows      = 0

        with ThreadPoolExecutor(max_workers=1) as progress_pool:
            for w_idx, window_pages in enumerate(windows):
                try:
                    chunks = chunk_pages(
                        window_pages,
                        global_chunk_offset=global_chunk_offset,
                    )
                    # Deduplicate cross-window overlap chunks by content hash
                    chunks = _deduplicate(chunks, global_chunk_offset)
                except Exception as e:
                    failed_windows += 1
                    print(f"[Handler] ⚠️  Window {w_idx} chunking failed: {e}")
                    window_stats[f"window_{w_idx}"] = {
                        "chunks": 0,
                        "status": "chunk_failed",
                        "error":  str(e),
                    }
                    continue

                if not chunks:
                    window_stats[f"window_{w_idx}"] = {"chunks": 0, "status": "skipped"}
                    continue

                print(f"[Handler] Window {w_idx + 1}/{total_windows} — "
                      f"{len(chunks)} chunks, pages "
                      f"{window_pages[0]['page_number']}–{window_pages[-1]['page_number']}")

                try:
                    # Store chunks in parallel batches
                    chunk_ids = _store_window(chunks, document_id, user_id)
                    total_chunks_stored += len(chunk_ids)
                    global_chunk_offset += len(chunk_ids)

                    # Enqueue embed jobs in parallel
                    _enqueue_window(
                        chunk_ids=chunk_ids,
                        document_id=document_id,
                    )

                    window_stats[f"window_{w_idx}"] = {
                        "chunks": len(chunk_ids),
                        "status": "ok",
                    }

                    # Fire-and-forget progress update
                    progress_pool.submit(_update_document, document_id, {
                        "chunk_count": total_chunks_stored,
                        "doc_metadata": {
                            **doc_metadata,
                            "windows_processed": w_idx + 1,
                            "windows_total":     total_windows,
                        },
                    })

                except Exception as e:
                    failed_windows += 1
                    print(f"[Handler] ❌ Window {w_idx} store/enqueue failed: {e}")
                    window_stats[f"window_{w_idx}"] = {
                        "chunks": 0,
                        "status": "failed",
                        "error":  str(e),
                    }
                    # Continue — don't fail the entire document for one bad window

        # Send finalize message after all windows are enqueued
        _send_finalize_message(document_id, user_id)

        # ── Step 5: Final status ──────────────────────────────────
        final_status = "indexing" if failed_windows == 0 else "partial"
        _update_document(document_id, {
            "status":        final_status,
            "chunk_count":   total_chunks_stored,
            "skipped_pages": skipped,
            "doc_metadata":  {
                **doc_metadata,
                "windows_processed": total_windows,
                "windows_total":     total_windows,
                "failed_windows":    failed_windows,
                "window_stats":      window_stats,
            },
        })

        print(f"[Handler] ✅ document={document_id} "
              f"chunks={total_chunks_stored} "
              f"status={final_status} "
              f"windows={total_windows} failed={failed_windows}")

    except ValueError as e:
        # Bad PDF — won't improve on retry
        print(f"[Handler] ❌ PDF error: {e}")
        _update_document(document_id, {
            "status": "failed",
            "doc_metadata": {"error": str(e)},
        })

    except Exception as e:
        print(f"[Handler] ❌ Unrecoverable: {e}")
        _update_document(document_id, {
            "status": "failed",
            "doc_metadata": {"error": str(e)},
        })
        raise   # re-raise → SQS retries


# ─────────────────────────────────────────────────────────────────────
# WINDOWING
# ─────────────────────────────────────────────────────────────────────

def _build_windows(
    pages:   list[dict],
    size:    int,
    overlap: int,
) -> list[list[dict]]:
    """
    Splits pages into overlapping windows.

    Window 0: pages[0 : size]
    Window 1: pages[size-overlap : size*2-overlap]
    ...

    The overlap pages re-appear at the start of the next window so the
    chunker sees cross-window boundaries and produces overlapping chunks
    naturally. Duplicate chunks are removed by _deduplicate().
    """
    if len(pages) <= size:
        return [pages]

    windows = []
    step    = size - overlap
    start   = 0
    while start < len(pages):
        end = min(start + size, len(pages))
        windows.append(pages[start:end])
        if end == len(pages):
            break
        start += step
    return windows


def _deduplicate(chunks: list[dict], prev_count: int) -> list[dict]:
    """
    Removes duplicate chunks that arise from window overlap.
    Uses a content hash — two chunks with identical text are the same chunk.
    Only deduplicates chunks that would have been produced by the overlapping
    pages (approximately the first `overlap` chunks of any non-first window).
    """
    seen:   set[str]   = set()
    result: list[dict] = []
    for chunk in chunks:
        h = hashlib.md5(chunk["content"].encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            result.append(chunk)
    return result


# ─────────────────────────────────────────────────────────────────────
# STORAGE — parallel batch inserts
# ─────────────────────────────────────────────────────────────────────

def _store_window(
    chunks:      list[dict],
    document_id: str,
    user_id:     str,
) -> list[str]:
    """
    Stores all chunks for one window using a bounded ThreadPoolExecutor.
    Returns the list of Supabase-assigned chunk IDs.

    Thread count (MAX_STORE_WORKERS) is bounded via env var.
    I/O-bound: each thread waits on a Supabase HTTP response.
    """
    rows = [
        {
            "document_id": document_id,
            "user_id":     user_id,
            "content":     c["content"],
            "embedding":   None,
            "metadata":    c["metadata"],
        }
        for c in chunks
    ]

    batches  = list(_batched(rows, STORE_BATCH_SIZE))
    all_ids: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_STORE_WORKERS) as pool:
        futures = {
            pool.submit(_insert_batch, batch, i, len(batches)): i
            for i, batch in enumerate(batches)
        }
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                ids = future.result()
                all_ids.extend(ids)
            except Exception as e:
                # Propagate — caller decides whether to skip the window
                raise RuntimeError(
                    f"Batch {batch_idx} insert failed: {e}"
                ) from e

    return all_ids


def _insert_batch(batch: list[dict], batch_idx: int, total: int) -> list[str]:
    result = (
        supabase
        .schema("rag").table("chunks")
        .insert(batch)
        .execute()
    )
    ids = [row["id"] for row in result.data]
    print(f"[Handler] Stored batch {batch_idx + 1}/{total} — {len(ids)} chunks")
    return ids


# ─────────────────────────────────────────────────────────────────────
# SQS ENQUEUEING — parallel sends
# ─────────────────────────────────────────────────────────────────────

def _enqueue_window(
    chunk_ids:   list[str],
    document_id: str,
) -> None:
    """
    Sends embed-job SQS messages for all chunks in this window.
    Uses a bounded ThreadPoolExecutor for parallel sends.
    """
    embed_batches = list(_batched(chunk_ids, EMBED_BATCH_SIZE))

    with ThreadPoolExecutor(max_workers=MAX_SQS_WORKERS) as pool:
        futures = []
        for local_idx, batch_ids in enumerate(embed_batches):
            batch_num = local_idx + 1
            futures.append(pool.submit(
                _send_embed_message,
                batch_ids,
                document_id,
                batch_num,
            ))

        for future in as_completed(futures):
            future.result()   # surface SQS errors


def _send_embed_message(
    batch_ids:   list[str],
    document_id: str,
    batch_num:   int,
) -> None:
    sqs.send_message(
        QueueUrl=EMBED_QUEUE_URL,
        MessageBody=json.dumps({
            "message_type": "embed",
            "document_id":  document_id,
            "chunk_ids":    batch_ids,
            "batch_num":    batch_num,
        }),
    )
    print(f"[Handler] Enqueued embed job batch {batch_num} "
          f"({len(batch_ids)} chunks)")


def _send_finalize_message(document_id: str, user_id: str) -> None:
    sqs.send_message(
        QueueUrl=EMBED_QUEUE_URL,
        MessageBody=json.dumps({
            "message_type": "finalize",
            "document_id":  document_id,
            "user_id":      user_id,
        }),
    )
    print(f"[Handler] Enqueued finalize message for document {document_id}")


# ─────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────

def _batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i: i + size]


def _update_document(document_id: str, fields: dict) -> None:
    supabase \
        .schema("rag").table("documents") \
        .update(fields) \
        .eq("id", document_id) \
        .execute()
    status = fields.get("status", "")
    print(f"[Handler] Document updated"
          + (f" → {status}" if status else ""))


def _parse_sqs_record(record: dict) -> tuple:
    from urllib.parse import unquote_plus
    sqs_body  = json.loads(record["body"])
    s3_event  = json.loads(sqs_body["Message"]) if "Message" in sqs_body else sqs_body
    s3_record = s3_event["Records"][0]["s3"]
    s3_bucket = s3_record["bucket"]["name"]
    s3_key    = unquote_plus(s3_record["object"]["key"])
    key_parts = s3_key.split("/")
    return s3_bucket, s3_key, key_parts[1], key_parts[2], key_parts[3]
