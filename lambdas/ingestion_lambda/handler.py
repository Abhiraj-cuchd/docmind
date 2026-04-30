# lambdas/ingestion_lambda/handler.py
#
# REDESIGN: The indexer now has two responsibilities:
#   OLD: extract → chunk → embed → store (all synchronous, one Lambda)
#   NEW: extract → chunk → store chunks WITHOUT embeddings → enqueue embed jobs
#
# Embedding is now handled by a separate Lambda (embed_worker) that
# consumes from a dedicated SQS embed-queue. This means:
#   - The indexer finishes in ~5-10 seconds regardless of document size
#   - Embedding happens at a controlled pace that respects rate limits
#   - A 500-page PDF and a 10-page PDF get the same fast "indexing started" response
#   - Rate limit retries don't block the indexer or burn Lambda minutes

import json
import os
from shared_lambda.supabase_client import get_service_client
from extractor import download_pdf_from_s3, extract_text_from_pdf
from chunker import chunk_pages

supabase   = get_service_client()
PDF_BUCKET = os.getenv("PDF_BUCKET_NAME")
EMBED_QUEUE_URL = os.getenv("EMBED_QUEUE_URL")  # new env var — add to CDK

# Lazy SQS client — only imported if needed
import boto3
sqs = boto3.client("sqs")

# CONCEPT: How many chunk IDs to pack into one SQS embed-job message.
# Each embed worker invocation handles one message = one batch.
# 32 chunks × ~125 tokens = ~4,000 tokens per Voyage API call —
# well within the free tier's per-request limit.
EMBED_BATCH_SIZE = 32


def handler(event, context):
    print(f"[Handler] Received {len(event['Records'])} SQS record(s)")
    for record in event["Records"]:
        _process_record(record)


def _process_record(record: dict) -> None:
    s3_bucket, s3_key, user_id, document_id, filename = _parse_sqs_record(record)

    print(f"[Handler] Processing: document_id={document_id} user_id={user_id} filename={filename}")
    _update_document(document_id, {"status": "processing"})

    try:
        # Step 1: Download
        print(f"[Handler] Step 1/4 — Downloading PDF")
        pdf_bytes = download_pdf_from_s3(PDF_BUCKET, s3_key)

        # Step 2: Extract
        print(f"[Handler] Step 2/4 — Extracting text")
        extraction_result = extract_text_from_pdf(
            pdf_bytes=pdf_bytes,
            s3_key=s3_key,
            filename=filename,
        )
        pages             = extraction_result["pages"]
        document_metadata = extraction_result["document_metadata"]
        skipped_pages     = extraction_result["skipped_pages"]
        print(f"[Handler] Extraction: {len(pages)} pages extracted, {len(skipped_pages)} skipped")

        # Step 3: Chunk
        print(f"[Handler] Step 3/4 — Chunking pages")
        chunks = chunk_pages(pages=pages, chunk_size=500, chunk_overlap=50)
        print(f"[Handler] Chunking: {len(chunks)} chunks produced")

        # Step 4: Store chunks WITHOUT embeddings
        # CONCEPT: We write all chunks to Supabase immediately with
        # embedding=NULL. The embed worker will fill these in shortly.
        # This lets us record the chunk content and metadata right now,
        # and gives us a concrete list of chunk IDs to enqueue.
        print(f"[Handler] Step 4/4 — Storing {len(chunks)} chunks (no embeddings yet)")
        chunk_ids = _store_chunks_without_embeddings(
            chunks=chunks,
            document_id=document_id,
            user_id=user_id,
        )

        # Step 5: Enqueue embed jobs
        # CONCEPT: We send batches of chunk IDs to the embed queue.
        # The embed worker Lambda will pick up each message, fetch
        # the content from Supabase, call Voyage AI, and write
        # the embedding back. Each message = one Voyage API call.
        _enqueue_embed_jobs(
            chunk_ids=chunk_ids,
            document_id=document_id,
            user_id=user_id,
        )

        # Mark as 'indexing' — chunks are stored, embeddings pending
        # CONCEPT: 'indexing' is a new status between 'processing' and 'ready'.
        # The frontend shows "Indexing... (embedding N chunks)" during this phase.
        # The embed worker marks the document 'ready' when all chunks are done.
        _update_document(document_id, {
            "status":        "indexing",
            "chunk_count":   len(chunks),
            "skipped_pages": skipped_pages,
            "doc_metadata":  document_metadata,
        })

        print(f"[Handler] ✅ Document {document_id} chunked and enqueued: "
              f"{len(chunks)} chunks in {len(chunk_ids) // EMBED_BATCH_SIZE + 1} embed batches")

    except ValueError as e:
        print(f"[Handler] ❌ PDF error for document {document_id}: {e}")
        _update_document(document_id, {"status": "failed", "doc_metadata": {"error": str(e)}})
        # Don't re-raise — bad PDF won't get better on retry

    except Exception as e:
        print(f"[Handler] ❌ Processing failed for document {document_id}: {e}")
        _update_document(document_id, {"status": "failed", "doc_metadata": {"error": str(e)}})
        raise  # re-raise → SQS retries


def _store_chunks_without_embeddings(
    chunks: list[dict],
    document_id: str,
    user_id: str,
) -> list[str]:
    """
    Inserts chunks into rag.chunks with embedding=NULL.
    Returns the list of chunk IDs (generated by Supabase).
    """
    BATCH_SIZE = 100
    all_ids = []

    rows = [
        {
            "document_id": document_id,
            "user_id":     user_id,
            "content":     chunk["content"],
            "embedding":   None,  # filled in by embed worker
            "metadata":    chunk["metadata"],
        }
        for chunk in chunks
    ]

    for batch_start in range(0, len(rows), BATCH_SIZE):
        batch = rows[batch_start : batch_start + BATCH_SIZE]
        result = (
            supabase
            .schema("rag").table("chunks")
            .insert(batch)
            .execute()
        )
        # Supabase returns the inserted rows including their generated IDs
        ids = [row["id"] for row in result.data]
        all_ids.extend(ids)
        print(f"[Handler] Stored chunks {batch_start + 1}–{batch_start + len(batch)} of {len(rows)}")

    return all_ids


def _enqueue_embed_jobs(
    chunk_ids: list[str],
    document_id: str,
    user_id: str,
) -> None:
    """
    Sends batches of chunk IDs to the SQS embed queue.
    Each message becomes one embed worker invocation = one Voyage API call.
    """
    total_chunks = len(chunk_ids)
    total_batches = (total_chunks + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE

    for i in range(0, total_chunks, EMBED_BATCH_SIZE):
        batch_ids   = chunk_ids[i : i + EMBED_BATCH_SIZE]
        batch_num   = (i // EMBED_BATCH_SIZE) + 1
        is_last     = batch_num == total_batches

        message = {
            "document_id":  document_id,
            "user_id":      user_id,
            "chunk_ids":    batch_ids,
            "batch_num":    batch_num,
            "total_batches": total_batches,
            "is_last_batch": is_last,
        }

        sqs.send_message(
            QueueUrl=EMBED_QUEUE_URL,
            MessageBody=json.dumps(message),
        )

    print(f"[Handler] Enqueued {total_batches} embed jobs for document {document_id}")


def _update_document(document_id: str, fields: dict) -> None:
    supabase \
        .schema("rag").table("documents") \
        .update(fields) \
        .eq("id", document_id) \
        .execute()
    print(f"[Handler] Document {document_id} → {fields.get('status', 'updated')}")


def _parse_sqs_record(record: dict) -> tuple:
    # unchanged from original
    from urllib.parse import unquote_plus
    sqs_body = json.loads(record["body"])
    s3_event = json.loads(sqs_body["Message"]) if "Message" in sqs_body else sqs_body
    s3_record = s3_event["Records"][0]["s3"]
    s3_bucket = s3_record["bucket"]["name"]
    s3_key    = unquote_plus(s3_record["object"]["key"])
    key_parts = s3_key.split("/")
    return s3_bucket, s3_key, key_parts[1], key_parts[2], key_parts[3]