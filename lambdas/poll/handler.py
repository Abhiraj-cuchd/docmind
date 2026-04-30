# lambdas/poll/handler.py
#
# Responsibility: handle GET /result/{jobId} from the frontend.
# Reads job status from Redis and returns it.
#
# CONCEPT: Poll is the thinnest Lambda in the system.
# It does exactly one thing — GET a Redis key and return it.
# No auth complexity, no database calls, no business logic.
# Just Redis → HTTP response.
#
# Frontend polls every 2 seconds until status = "done" or "error".
# Average processing time is 8-15 seconds so expect 4-8 polls
# per query in normal operation.
#
# Redis key lifecycle:
#   Created by submit Lambda: job:{job_id} → {status: "pending"}
#   Updated by processor:     job:{job_id} → {status: "done", answer: "..."}
#   TTL: 1 hour — if user doesn't poll within an hour, result is discarded

import json
import os
from upstash_redis import Redis
from shared_lambda.auth    import get_user_from_event, create_auth_error_response
from shared_lambda.secrets import get_secret


def get_redis_client() -> Redis:
    from shared_lambda.rate_limiter import get_redis_client as _get_redis
    return _get_redis()


# ─────────────────────────────────────────────────────────────────────
# LAMBDA ENTRY POINT
# ─────────────────────────────────────────────────────────────────────

def handler(event, context):
    """
    Handles GET /result/{jobId} requests.

    Path parameter: jobId (from API Gateway path)

    Returns one of:

    Pending:
    {"status": "pending"}

    Done:
    {
        "status":                  "done",
        "answer":                  "...",
        "cached":                  false,
        "voice_url":               null,
        "voice_credits_remaining": 3,
        "tokens_used":             2
    }

    Error:
    {"status": "error", "message": "..."}

    Not found (job_id never existed or expired):
    {"status": "not_found"}
    """

    # ── Step 1: Verify JWT ─────────────────────────────────────────
    # CONCEPT: We verify auth on poll too — not just submit.
    # Without this, anyone who guesses a job_id could read
    # another user's answer. Job IDs are UUIDs (hard to guess)
    # but defense in depth is always worth it.
    try:
        user    = get_user_from_event(event)
        user_id = user["user_id"]
    except Exception as e:
        return create_auth_error_response(str(e))

    # ── Step 2: Extract job_id from path ──────────────────────────
    # CONCEPT: API Gateway passes path parameters in
    # event["pathParameters"]. The route is GET /result/{jobId}
    # so the parameter name is "jobId".
    path_params = event.get("pathParameters") or {}
    job_id      = path_params.get("jobId", "").strip()

    if not job_id:
        return _response(400, {"error": "jobId path parameter is required"})

    print(f"[Poll] user={user_id} job={job_id}")

    # ── Step 3: Read from Redis ────────────────────────────────────
    r      = get_redis_client()
    raw    = r.get(f"job:{job_id}")

    if raw is None:
        # CONCEPT: Job not found means either:
        #   a) job_id is invalid / doesn't exist
        #   b) result expired (TTL of 1 hour passed)
        #   c) processor hasn't written the pending status yet
        #      (very rare race condition — submit writes pending
        #       before enqueuing so this window is microseconds)
        # We return not_found so the frontend can stop polling
        # and show an appropriate message.
        print(f"[Poll] Job {job_id} not found in Redis")
        return _response(404, {"status": "not_found"})

    # ── Step 4: Parse and return result ───────────────────────────
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return _response(500, {
            "status":  "error",
            "message": "Invalid result format in Redis"
        })

    status = result.get("status", "unknown")
    print(f"[Poll] Job {job_id} status: {status}")

    # CONCEPT: We return the result as-is from Redis.
    # The processor Lambda writes the complete response shape
    # so poll never needs to transform or enrich the data.
    # What processor writes is exactly what the frontend receives.
    return _response(200, result)


# ─────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ─────────────────────────────────────────────────────────────────────

def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type":                "application/json",
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body),
    }