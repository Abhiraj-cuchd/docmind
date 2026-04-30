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
#     "document_id":   "uuid",
#     "user_id":       "uuid",
#     "chunk_ids":     ["uuid", "uuid", ...],  # 32 IDs per batch
#     "batch_num":     1,
#     "total_batches": 19,
#     "is_last_batch": false
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

    body          = json.loads(record["body"])
    chunk_ids     = body["chunk_ids"]
    document_id   = body["document_id"]
    user_id       = body["user_id"]
    batch_num     = body["batch_num"]
    total_batches = body["total_batches"]
    is_last_batch = body["is_last_batch"]

    print(f"[EmbedWorker] Batch {batch_num}/{total_batches} — "
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

        print(f"[EmbedWorker] ✅ Batch {batch_num}/{total_batches} done "
              f"— {len(embeddings)} embeddings written")

        # ── Step 4: Mark document ready on last batch ──────────────
        # CONCEPT: Only the last batch marks the document ready.
        # Earlier batches finishing out of order is fine — only when
        # ALL batches are done do we flip the status to ready.
        # is_last_batch is set by the indexer based on batch_num == total_batches.
        if is_last_batch:
            supabase.schema("rag").table("documents") \
                .update({"status": "ready"}) \
                .eq("id", document_id) \
                .execute()

            print(f"[EmbedWorker] ✅ Document {document_id} → ready "
                  f"(all {total_batches} batches complete)")

    except Exception as e:
        print(f"[EmbedWorker] ❌ Batch {batch_num} failed: {e}")
        # Re-raise so SQS retries this batch
        # Failed embedding doesn't fail the whole document —
        # only this batch gets retried
        raise