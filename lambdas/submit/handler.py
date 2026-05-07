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
import base64
import boto3
import requests as _req
from upstash_redis              import Redis
from shared_lambda.auth         import get_user_from_event, create_auth_error_response
from shared_lambda.secrets      import get_secret
from shared_lambda.supabase_client import get_service_client, consume_voice_credit, refund_voice_credit
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
TTS_MAX_CHARS   = 500


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
    elif "/document-url" in path:
        return handle_document_url(event)
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
    response_style  = body.get("response_style", "explanatory")
    document_ids    = body.get("document_ids", [])

    if response_style not in {"concise", "explanatory", "conversational"}:
        response_style = "explanatory"

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

    # ── Step 4: Validate conversation ─────────────────────────────
    # CONCEPT: Verify the conversation exists and belongs to this user
    # before using it for cache or enqueueing. Prevents injecting
    # messages into other users' conversations by guessing IDs.
    conversation = _get_conversation(conversation_id, user_id)
    if not conversation:
        return _error_response(
            404,
            "Conversation not found or does not belong to you"
        )

    # ── Step 5: Cache check ────────────────────────────────────────
    # CONCEPT: User- and document-scoped cache key — different
    # documents avoid cross-contaminating answers.
    r         = get_redis_client()
    doc_part  = hashlib.sha256("|".join(sorted(document_ids)).encode()).hexdigest()[:12] if document_ids else (conversation.get("document_id") or "none")
    cache_key = _make_cache_key(user_id, query, doc_part, response_style)
    cached_raw = r.get(cache_key)

    if cached_raw:
        print(f"[Submit] Cache hit — returning instantly")
        try:
            cached = json.loads(cached_raw)
            cached_answer = cached["answer"]
            cached_sources = cached.get("sources", [])
        except (json.JSONDecodeError, KeyError, TypeError):
            cached_answer = cached_raw
            cached_sources = []

        voice_url  = None
        voice_urls = None
        if voice_mode:
            voice_urls = _handle_voice(user_id, cached_answer)
            if voice_urls:
                voice_url = voice_urls[0]

        _save_exchange(
            conversation_id=conversation_id,
            user_id=user_id,
            user_message=query,
            assistant_message=cached_answer,
        )

        return _success_response({
            "job_id":      None,
            "status":      "done",
            "answer":      cached_answer,
            "sources":     cached_sources,
            "cached":      True,
            "voice_url":   voice_url,
            "voice_urls":  voice_urls,
            "tokens_used": 0,
        })

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
        "response_style":  response_style,
        "document_ids":    document_ids,
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

def handle_document_url(event: dict) -> dict:
    """
    Generates a presigned GET URL for viewing a PDF from S3.
    Frontend uses this URL in an iframe to preview the document.

    CONCEPT: We never expose S3 directly to the frontend.
    The presigned URL is temporary (1 hour) and pre-authorised.
    It works in an iframe because it's a direct HTTPS GET to S3.

    Query params: ?document_id=uuid
    """

    # ── Auth ───────────────────────────────────────────────────────
    try:
        user    = get_user_from_event(event)
        user_id = user["user_id"]
    except Exception as e:
        return create_auth_error_response(str(e))

    # ── Get document_id from query params ──────────────────────────
    params      = event.get("queryStringParameters") or {}
    document_id = params.get("document_id", "").strip()

    if not document_id:
        return _error_response(400, "document_id query parameter is required")

    # ── Verify document belongs to this user ───────────────────────
    # CONCEPT: Never generate a presigned URL for a document
    # that doesn't belong to the requesting user.
    # This prevents user A from viewing user B's documents.
    try:
        result = supabase.schema("rag").table("documents") \
            .select("id, s3_key, filename, status") \
            .eq("id", document_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()

        if not result.data:
            return _error_response(404, "Document not found")

        document = result.data

    except Exception as e:
        return _error_response(404, "Document not found")

    if document["status"] != "ready":
        return _error_response(400,
            f"Document is not ready yet (status: {document['status']})")

    s3_key = document["s3_key"]

    # ── Generate presigned GET URL ─────────────────────────────────
    # CONCEPT: presigned GET URL lets the browser fetch the PDF
    # directly from S3 without AWS credentials.
    # ExpiresIn=3600 means the URL is valid for 1 hour.
    # The iframe loads it once — 1 hour is more than enough.
    try:
        presigned_url = s3_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": PDF_BUCKET_NAME,
                "Key":    s3_key,
            },
            ExpiresIn=3600,
        )

        print(f"[DocumentURL] Presigned GET URL generated for "
              f"document={document_id} user={user_id}")

        return _success_response({
            "document_url": presigned_url,
            "filename":     document["filename"],
            "document_id":  document_id,
            "expires_in":   3600,
        })

    except Exception as e:
        print(f"[DocumentURL] Failed to generate presigned URL: {e}")
        return _error_response(500, f"Failed to generate document URL: {str(e)}")
# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _handle_voice(user_id: str, answer: str) -> list[str] | None:
    """Run TTS for a cached answer when voice_mode=True."""
    credit_consumed = consume_voice_credit(user_id)
    if not credit_consumed:
        print(f"[Submit] Voice: no credits for user {user_id}")
        return None

    try:
        api_key = get_secret("SARVAM_API_KEY_RAG")
        chunks  = _split_tts_chunks(answer, TTS_MAX_CHARS)
        resp    = _req.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            json={
                "inputs":               chunks,
                "target_language_code": "en-IN",
                "speaker":              "shruti",
                "model":                "bulbul:v3",
                "pace":                 1.15,
                "enable_preprocessing": True,
            },
            timeout=30,
        )

        if resp.status_code != 200:
            raise Exception(f"TTS error {resp.status_code}: {resp.text}")

        audios  = resp.json().get("audios", [])
        s3      = boto3.client("s3")
        bucket  = os.getenv("VOICE_BUCKET_NAME")
        voice_urls = []

        for index, audio_b64 in enumerate(audios):
            audio = base64.b64decode(audio_b64)
            key   = f"audio/{user_id}/{uuid.uuid4()}_{index}.wav"
            s3.put_object(Bucket=bucket, Key=key, Body=audio, ContentType="audio/wav")
            voice_urls.append(
                s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=86400,
                )
            )

        return voice_urls

    except Exception as e:
        print(f"[Submit] Voice TTS failed — refunding credit: {e}")
        refund_voice_credit(user_id)
        return None


def _split_tts_chunks(text: str, max_chars: int) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]

    sentences = []
    start = 0
    for i, char in enumerate(cleaned):
        if char in ".!?" and i + 1 < len(cleaned) and cleaned[i + 1] == " ":
            sentences.append(cleaned[start:i + 1])
            start = i + 2
    if start < len(cleaned):
        sentences.append(cleaned[start:])

    chunks, buffer = [], ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            while sentence:
                chunks.append(sentence[:max_chars])
                sentence = sentence[max_chars:]
            buffer = ""
            continue
        if not buffer:
            buffer = sentence
        elif len(buffer) + 1 + len(sentence) <= max_chars:
            buffer = f"{buffer} {sentence}"
        else:
            chunks.append(buffer)
            buffer = sentence
    if buffer:
        chunks.append(buffer)
    return chunks


def _get_conversation(conversation_id: str, user_id: str) -> dict | None:
    """
    Returns the conversation row if it belongs to this user.
    """
    try:
        result = supabase.schema("rag") \
            .table("conversations") \
            .select("id, document_id") \
            .eq("id", conversation_id) \
            .eq("user_id", user_id) \
            .single() \
            .execute()
        return result.data
    except Exception:
        return None


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


def _make_cache_key(user_id: str, query: str, doc_part: str, style: str) -> str:
    h = hashlib.sha256(query.lower().strip().encode()).hexdigest()
    return f"cache:{user_id}:{doc_part}:{style}:{h}"


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