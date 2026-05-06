# lambdas/ingestion_lambda/embed_worker.py
#
# Processes embedding jobs from the SQS embed queue.
# Fetches chunk content from Supabase, embeds via Titan, writes back.
#
# CONCEPT: This Lambda exists because we decoupled embedding from
# the main indexer. The indexer stores chunks without embeddings
# and enqueues jobs here. This worker fills in the embeddings.
#
# With Titan there are no rate limits so no delays or retry logic
# for throttling. Jobs process as fast as Bedrock responds (~100ms each).
#
# SQS message shape:
# {
#     "message_type": "embed",
#     "document_id":  "uuid",
#     "chunk_ids":    ["uuid", "uuid", ...],  # 32 IDs per batch
#     "batch_num":    1
# }
# or
# {
#     "message_type": "finalize",
#     "document_id":  "uuid",
#     "user_id":      "uuid"
# }

import json
from shared_lambda.supabase_client import get_service_client
from embedder import embed_texts

supabase = get_service_client()


def handler(event, context):
    print(f"[EmbedWorker] Received {len(event['Records'])} message(s)")
    for record in event["Records"]:
        _process_record(record)


def _process_record(record: dict) -> None:

    body = json.loads(record["body"])
    message_type = body.get("message_type", "embed")
    document_id  = body["document_id"]

    if message_type == "finalize":
        _finalize_document(document_id)
        return

    chunk_ids = body["chunk_ids"]
    batch_num = body.get("batch_num", 0)

    print(f"[EmbedWorker] Batch {batch_num} — "
          f"{len(chunk_ids)} chunks for document {document_id}")

    try:
        # ── Step 1: Fetch chunk content from Supabase ──────────────
        result = supabase.schema("rag").table("chunks") \
            .select("id, content") \
            .in_("id", chunk_ids) \
            .execute()

        if not result.data:
            print(f"[EmbedWorker] ⚠️  No chunks found for batch "
                  f"{batch_num} — may have been deleted")
            return

        chunks = result.data
        texts  = [c["content"] for c in chunks]
        ids    = [c["id"] for c in chunks]

        print(f"[EmbedWorker] Fetched {len(chunks)} chunks — embedding...")

        # ── Step 2: Embed via Titan (no rate limits) ───────────────
        # CONCEPT: Each text gets one Bedrock invoke_model call.
        # ~100ms per call, no throttling, no retry needed for limits.
        embeddings = embed_texts(texts)

        print(f"[EmbedWorker] Embedded {len(embeddings)} chunks — "
              f"writing to Supabase...")

        # ── Step 3: Write embeddings back to Supabase ──────────────
        # Update each chunk row with its embedding vector.
        # Supabase REST API doesn't support bulk updates with
        # different values per row so we update one at a time.
        # At 32 chunks this is 32 calls × ~20ms = ~640ms total.
        for chunk_id, embedding in zip(ids, embeddings):
            supabase.schema("rag").table("chunks") \
                .update({"embedding": embedding}) \
                .eq("id", chunk_id) \
                .execute()

        print(f"[EmbedWorker] ✅ Batch {batch_num} done "
              f"— {len(embeddings)} embeddings written")

    except Exception as e:
        print(f"[EmbedWorker] ❌ Batch {batch_num} failed: {e}")
        # Re-raise so SQS retries this batch
        # Failed embedding doesn't fail the whole document —
        # only this batch gets retried
        raise


def _finalize_document(document_id: str) -> None:
    count_result = (
        supabase.schema("rag").table("chunks")
        .select("id", count="exact")
        .eq("document_id", document_id)
        .execute()
    )
    chunk_count = count_result.count or 0

    supabase.schema("rag").table("documents") \
        .update({"status": "ready", "chunk_count": chunk_count}) \
        .eq("id", document_id) \
        .execute()

    print(f"[EmbedWorker] ✅ Document {document_id} → ready "
          f"(chunks={chunk_count})")
