# lambdas/delete_lambda/handler.py
#
# Routes:
#   DELETE /documents/{documentId}     → delete_document()
#   DELETE /conversations/{conversationId} → delete_conversation()
#
# Document deletion order:
#   1. Verify JWT + ownership
#   2. Delete S3 PDF object
#   3. Delete document row — DB cascades handle the rest:
#        documents → conversations (009 migration)
#        conversations → messages  (existing FK cascade)
#        documents → chunks        (existing FK cascade)
#
# Conversation deletion order:
#   1. Verify JWT + ownership
#   2. Fetch all messages with voice_url / voice_urls
#   3. Delete S3 voice objects (best-effort)
#   4. Delete conversation row — DB cascade deletes messages

import json
import os
from urllib.parse import urlparse

import boto3

from shared_lambda.auth import get_user_from_event, create_auth_error_response
from shared_lambda.supabase_client import get_service_client

s3 = boto3.client("s3")
PDF_BUCKET   = os.getenv("PDF_BUCKET_NAME")
VOICE_BUCKET = os.getenv("VOICE_BUCKET_NAME")


def handler(event, context):
    try:
        user = get_user_from_event(event)
        user_id = user["user_id"]
    except Exception as e:
        return create_auth_error_response(str(e))

    path = event.get("path") or event.get("rawPath") or ""

    if "/conversations/" in path:
        return delete_conversation(event, user_id)
    return delete_document(event, user_id)


# ── Document delete ────────────────────────────────────────────────────

def delete_document(event, user_id: str):
    path_params = event.get("pathParameters") or {}
    document_id = path_params.get("documentId", "").strip()

    if not document_id:
        return _response(400, {"error": "documentId path parameter is required"})

    print(f"[Delete] user={user_id} document={document_id}")

    supabase = get_service_client()

    result = (
        supabase
        .schema("rag").table("documents")
        .select("id, s3_key, status")
        .eq("id", document_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    if not result.data:
        return _response(404, {"error": "Document not found"})

    s3_key = result.data["s3_key"]

    try:
        s3.delete_object(Bucket=PDF_BUCKET, Key=s3_key)
        print(f"[Delete] S3 PDF deleted: s3://{PDF_BUCKET}/{s3_key}")
    except Exception as e:
        print(f"[Delete] Warning: S3 PDF delete failed for {s3_key}: {e}")

    (
        supabase
        .schema("rag").table("documents")
        .delete()
        .eq("id", document_id)
        .eq("user_id", user_id)
        .execute()
    )

    print(f"[Delete] Document {document_id} deleted")
    return _response(200, {"deleted": True, "document_id": document_id})


# ── Conversation delete ────────────────────────────────────────────────

def delete_conversation(event, user_id: str):
    path_params = event.get("pathParameters") or {}
    conversation_id = path_params.get("conversationId", "").strip()

    if not conversation_id:
        return _response(400, {"error": "conversationId path parameter is required"})

    print(f"[Delete] user={user_id} conversation={conversation_id}")

    supabase = get_service_client()

    # Ownership check
    conv = (
        supabase
        .schema("rag").table("conversations")
        .select("id")
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )

    if not conv.data:
        return _response(404, {"error": "Conversation not found"})

    # Fetch all messages that have voice files
    msgs = (
        supabase
        .schema("rag").table("messages")
        .select("voice_url, voice_urls")
        .eq("conversation_id", conversation_id)
        .execute()
    )

    # Collect unique S3 keys from presigned voice URLs
    keys_to_delete: set[str] = set()
    for msg in (msgs.data or []):
        urls = []
        if msg.get("voice_url"):
            urls.append(msg["voice_url"])
        for u in (msg.get("voice_urls") or []):
            urls.append(u)
        for url in urls:
            key = _s3_key_from_url(url)
            if key:
                keys_to_delete.add(key)

    # Delete S3 voice objects (best-effort)
    for key in keys_to_delete:
        try:
            s3.delete_object(Bucket=VOICE_BUCKET, Key=key)
            print(f"[Delete] S3 voice deleted: s3://{VOICE_BUCKET}/{key}")
        except Exception as e:
            print(f"[Delete] Warning: S3 voice delete failed for {key}: {e}")

    # Delete conversation row — DB cascade removes messages
    (
        supabase
        .schema("rag").table("conversations")
        .delete()
        .eq("id", conversation_id)
        .eq("user_id", user_id)
        .execute()
    )

    print(f"[Delete] Conversation {conversation_id} deleted ({len(keys_to_delete)} voice files removed)")
    return _response(200, {"deleted": True, "conversation_id": conversation_id})


# ── Helpers ───────────────────────────────────────────────────────────

def _s3_key_from_url(url: str) -> str | None:
    """Extract the S3 object key from a presigned URL."""
    try:
        path = urlparse(url).path  # e.g. /audio/user-id/uuid_0.wav
        key = path.lstrip("/")
        return key if key.startswith("audio/") else None
    except Exception:
        return None


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
