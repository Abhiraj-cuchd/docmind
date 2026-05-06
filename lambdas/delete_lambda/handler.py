# lambdas/delete_lambda/handler.py
#
# Handles DELETE /documents/{documentId}
#
# Deletion order:
#   1. Verify JWT + ownership
#   2. Delete S3 object
#   3. Delete document row — DB cascades handle the rest:
#        documents → conversations (009 migration)
#        conversations → messages  (existing FK cascade)
#        documents → chunks        (existing FK cascade)

import json
import os
import boto3
from shared_lambda.auth import get_user_from_event, create_auth_error_response
from shared_lambda.supabase_client import get_service_client

s3 = boto3.client("s3")
PDF_BUCKET = os.getenv("PDF_BUCKET_NAME")


def handler(event, context):
    # ── Auth ──────────────────────────────────────────────────────────
    try:
        user = get_user_from_event(event)
        user_id = user["user_id"]
    except Exception as e:
        return create_auth_error_response(str(e))

    # ── Path param ────────────────────────────────────────────────────
    path_params = event.get("pathParameters") or {}
    document_id = path_params.get("documentId", "").strip()

    if not document_id:
        return _response(400, {"error": "documentId path parameter is required"})

    print(f"[Delete] user={user_id} document={document_id}")

    supabase = get_service_client()

    # ── Fetch document (ownership check + get s3_key) ─────────────────
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

    doc = result.data
    s3_key = doc["s3_key"]

    # ── Delete from S3 ────────────────────────────────────────────────
    try:
        s3.delete_object(Bucket=PDF_BUCKET, Key=s3_key)
        print(f"[Delete] S3 object deleted: s3://{PDF_BUCKET}/{s3_key}")
    except Exception as e:
        # Log but don't abort — the S3 object may already be gone;
        # proceed to clean up DB records regardless.
        print(f"[Delete] Warning: S3 delete failed for {s3_key}: {e}")

    # ── Delete document row (DB cascade handles everything else) ──────
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


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }
