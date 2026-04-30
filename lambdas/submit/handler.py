# lambdas/submit/handler.py
#
# Responsibility: receive POST /query and POST /upload from API Gateway.
#
# POST /query:
#   1. Verify JWT
#   2. Check conversational (instant response)
#   3. Check Redis cache (instant response)
#   4. Validate conversation belongs to user
#   5. Enqueue to SQS → return job_id
#
# POST /upload:
#   1. Verify JWT
#   2. Generate presigned S3 URL for direct PDF upload
#   3. Return URL to frontend
#
# The frontend uploads PDF directly to S3 using the presigned URL.
# S3 PUT event → SQS ingestion queue → indexer Lambda.

import json
import os
import uuid
import hashlib
import boto3
from upstash_redis              import Redis
from shared_lambda.auth         import get_user_from_event, create_auth_error_response
from shared_lambda.secrets      import get_secret
from shared_lambda.supabase_client import get_service_client
from shared_lambda.classifier   import get_conversational_response


# ── Module-level clients (singletons) ─────────────────────────────────
sqs_client = boto3.client(
    "sqs",
    region_name=os.getenv("AWS_REGION", "ap-south-1")
)
s3_client = boto3.client(
    "s3",
    region_name=os.getenv("AWS_REGION", "ap-south-1")
)
supabase = get_service_client()

QUERY_QUEUE_URL = os.getenv("QUERY_QUEUE_URL")
PDF_BUCKET_NAME = os.getenv("PDF_BUCKET_NAME")
CACHE_TTL       = 3600


def get_redis_client() -> Redis:
    return Redis(
        url=get_secret("UPSTASH_REDIS_REST_URL"),
        token=get_secret("UPSTASH_REDIS_REST_TOKEN"),
    )


# ─────────────────────────────────────────────────────────────────────
# LAMBDA ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

def handler(event, context):
    """
    Routes incoming requests to the correct handler based on path.

    POST /query  → handle_query()
    POST /upload → handle_upload()
    """

    # CONCEPT: API Gateway HTTP API passes the path in rawPath.
    # We use this to route to the correct handler function.
    path = event.get("rawPath", event.get("path", ""))

    print(f"[Submit] Incoming request: {path}")

    if "/upload" in path:
        return handle_upload(event)
    else:
        return handle_query(event)


# ─────────────────────────────────────────────────────────────────────
# UPLOAD HANDLER
# ─────────────────────────────────────────────────────────────────────

def handle_upload(event: dict) -> dict:
    """
    Generates a presigned S3 URL for direct PDF upload.

    CONCEPT: Lambda has a 6MB payload size limit. PDFs can be larger.
    Instead of uploading through Lambda, we generate a presigned URL
    that lets the frontend PUT directly to S3.
    The presigned URL is temporary (15 minutes) and pre-authorised —
    no AWS credentials needed on the frontend.

    Flow:
      Frontend calls POST /upload → gets presigned URL
      Frontend PUTs file to S3 using that URL
      S3 PUT event → SQS ingestion queue → indexer Lambda
    """

    # ── Auth ───────────────────────────────────────────────────────
    try:
        user    = get_user_from_event(event)
        user_id = user["user_id"]
    except Exception as e:
        return create_auth_error_response(str(e))

    # ── Parse body ─────────────────────────────────────────────────
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _error_response(400, "Invalid JSON in request body")

    filename    = body.get("filename", "").strip()
    document_id = body.get("document_id", "").strip()

    if not filename:
        return _error_response(400, "filename field is required")

    if not document_id:
        # Generate document_id if not provided
        document_id = str(uuid.uuid4())

    # Validate filename — only allow PDFs
    if not filename.lower().endswith(".pdf"):
        return _error_response(400, "Only PDF files are supported")

    # CONCEPT: S3 key format encodes user_id and document_id so the
    # indexer Lambda can extract them without a database lookup.
    # Format: uploads/{user_id}/{document_id}/{filename}
    s3_key = f"uploads/{user_id}/{document_id}/{filename}"

    print(f"[Upload] Generating presigned URL: user={user_id} "
          f"document={document_id} file={filename}")

    try:
        # Generate presigned PUT URL valid for 15 minutes
        # CONCEPT: A presigned URL is a temporary URL that grants
        # permission to perform one specific S3 operation.
        # After ExpiresIn seconds it becomes invalid.
        # The frontend uses HTTP PUT (not POST) to upload to S3.
        presigned_url = s3_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket":      PDF_BUCKET_NAME,
                "Key":         s3_key,
                "ContentType": "application/pdf",
            },
            ExpiresIn=900,  # 15 minutes
        )

        print(f"[Upload] Presigned URL generated for {s3_key}")

        return _success_response({
            "upload_url":  presigned_url,
            "s3_key":      s3_key,
            "document_id": document_id,
            "expires_in":  900,
        })

    except Exception as e:
        print(f"[Upload] Failed to generate presigned URL: {e}")
        return _error_response(500, f"Failed to generate upload URL: {str(e)}")


# ─────────────────────────────────────────────────────────────────────
# QUERY HANDLER
# ─────────────────────────────────────────────────────────────────────

def handle_query(event: dict) -> dict:
    """
    Handles POST /query — the main RAG query entry point.

    Fast paths (return immediately):
      1. Conversational query  → instant pre-written response
      2. Cache hit             → return cached answer

    Slow path (async):
      3. Enqueue to SQS → return job_id → frontend polls GET /result/{jobId}
    """

    # ── Step 1: Auth ───────────────────────────────────────────────
    try:
        user    = get_user_from_event(event)
        user_id = user["user_id"]
    except Exception as e:
        return create_auth_error_response(str(e))

    # ── Step 2: Parse body ─────────────────────────────────────────
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _error_response(400, "Invalid JSON in request body")

    query           = body.get("question", "").strip()
    conversation_id = body.get("conversation_id", "").strip()
    voice_mode      = body.get("voice_mode", False)

    if not query:
        return _error_response(400, "question field is required")

    if not conversation_id:
        return _error_response(400, "conversation_id field is required")

    if len(query) > 2000:
        return _error_response(
            400,
            "Question too long. Maximum 2000 characters."
        )

    print(f"[Submit] user={user_id} "
          f"conversation={conversation_id} "
          f"query='{query[:80]}'")

    # ── Step 3: Conversational fast path ───────────────────────────
    # CONCEPT: Greetings and social exchanges are handled instantly
    # here in submit — they never touch SQS or the processor Lambda.
    # Zero tokens, zero latency, zero cost.
    conversational_response = get_conversational_response(query)

    if conversational_response:
        print(f"[Submit] Conversational query — instant response")

        _save_exchange(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=query,
            assistant_message=conversational_response,
        )

        return _success_response({
            "job_id":      None,
            "status":      "done",
            "answer":      conversational_response,
            "cached":      False,
            "tokens_used": 0,
        })

    # ── Step 4: Cache check ────────────────────────────────────────
    # CONCEPT: User-scoped cache key — different users asking the same
    # question get answers from their own documents, not each other's.
    r         = get_redis_client()
    cache_key = _make_cache_key(user_id, query)
    cached    = r.get(cache_key)

    if cached:
        print(f"[Submit] Cache hit — returning instantly")

        _save_exchange(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=query,
            assistant_message=cached,
        )

        return _success_response({
            "job_id":      None,
            "status":      "done",
            "answer":      cached,
            "cached":      True,
            "tokens_used": 0,
        })

    # ── Step 5: Validate conversation ─────────────────────────────
    # CONCEPT: Verify the conversation exists and belongs to this user
    # before enqueuing. Prevents injecting messages into other users'
    # conversations by guessing conversation IDs.
    if not _verify_conversation(conversation_id, user_id):
        return _error_response(
            404,
            "Conversation not found or does not belong to you"
        )

    # ── Step 6: Generate job ID + write pending to Redis ───────────
    job_id = str(uuid.uuid4())

    # CONCEPT: Write pending status BEFORE enqueuing to SQS.
    # If we wrote it after, the processor could finish and write
    # the result before the pending status exists — poll Lambda
    # would return not_found on the first poll.
    r.setex(
        f"job:{job_id}",
        3600,
        json.dumps({"status": "pending"})
    )

    # ── Step 7: Enqueue to SQS ─────────────────────────────────────
    message = {
        "job_id":          job_id,
        "query":           query,
        "user_id":         user_id,
        "conversation_id": conversation_id,
        "voice_mode":      bool(voice_mode),
    }

    sqs_client.send_message(
        QueueUrl=QUERY_QUEUE_URL,
        MessageBody=json.dumps(message),
    )

    print(f"[Submit] Job {job_id} enqueued to SQS")

    return _success_response({
        "job_id": job_id,
        "status": "pending",
    })


# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _verify_conversation(conversation_id: str, user_id: str) -> bool:
    """
    Verifies the conversation exists and belongs to this user.
    """
    try:
        result = supabase.schema("rag") \
            .table("conversations") \
            .select("id") \
            .eq("id", conversation_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        return result.data is not None
    except Exception:
        return False


def _save_exchange(
    conversation_id:   str,
    user_id:           str,
    user_message:      str,
    assistant_message: str,
) -> None:
    """
    Saves a user + assistant message pair to rag.messages.
    Used for conversational and cache-hit responses that
    bypass the processor Lambda entirely.
    """
    try:
        supabase.schema("rag").table("messages").insert([
            {
                "conversation_id": conversation_id,
                "user_id":         user_id,
                "role":            "user",
                "content":         user_message,
                "voice_used":      False,
            },
            {
                "conversation_id":  conversation_id,
                "user_id":          user_id,
                "role":             "assistant",
                "content":          assistant_message,
                "retrieved_chunks": [],
                "voice_used":       False,
            },
        ]).execute()

        supabase.schema("rag") \
            .table("conversations") \
            .update({"updated_at": "NOW()"}) \
            .eq("id", conversation_id) \
            .execute()

        print(f"[Submit] Exchange saved to {conversation_id}")

    except Exception as e:
        # CONCEPT: Don't fail the request if history save fails.
        # The answer was already generated — losing history is
        # acceptable, losing the answer is not.
        print(f"[Submit] Warning: failed to save exchange: {e}")


def _make_cache_key(user_id: str, query: str) -> str:
    h = hashlib.sha256(query.lower().strip().encode()).hexdigest()
    return f"cache:{user_id}:{h}"


def _success_response(body: dict) -> dict:
    return {
        "statusCode": 200,
        "headers": {
            "Content-Type":                "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }


def _error_response(status_code: int, message: str) -> dict:
    error_text = "Bad Request" if status_code == 400 else \
                 "Not Found"   if status_code == 404 else \
                 "Internal Server Error"
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type":                "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps({
            "error":   error_text,
            "message": message,
        }),
    }